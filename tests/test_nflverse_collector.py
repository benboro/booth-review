"""Offline tests for NflverseCollector (D-21): mock transport, synthetic data."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from booth_review.nfl.layout import (
    NFLVERSE_API_BASE,
    NFLVERSE_PBP_RELEASE_PATH,
    NFLVERSE_SCHEDULES_PATH,
    NFLVERSE_SCHEDULES_URL,
    nflverse_pbp_assets_page_path,
)
from booth_review.sources.nflverse.collector import (
    API_HEADERS,
    MAX_ASSET_PAGES,
    NflverseAsset,
    NflverseCollector,
    NflverseSchemaError,
)
from booth_review.transport.cache import RawCache
from booth_review.transport.client import PoliteClient

_FIX = Path(__file__).parent / "fixtures" / "nfl" / "nflverse"
_RELEASE_URL = f"{NFLVERSE_API_BASE}/releases/tags/pbp"
_ROBOTS = {
    "https://api.github.com/robots.txt": (404, b"nf", {}),
    "https://raw.githubusercontent.com/robots.txt": (404, b"nf", {}),
}


def _page_url(page: int) -> str:
    return f"{NFLVERSE_API_BASE}/releases/900001/assets?per_page=100&page={page}"


def _collector(vault_paths, handle, *, token: str | None = None) -> NflverseCollector:
    client = PoliteClient(transport=handle.transport, clock=lambda: 0.0, sleep=lambda s: None)
    return NflverseCollector(RawCache(vault_paths, client), vault_paths, token=token)


def _listing_responses() -> dict:
    return {
        **_ROBOTS,
        _RELEASE_URL: (200, (_FIX / "release_pbp_synthetic.json").read_bytes(), {}),
        _page_url(1): (200, (_FIX / "assets_p1_synthetic.json").read_bytes(), {}),
    }


def test_plan_schedules(vault_paths, mock_transport_factory) -> None:
    col = _collector(vault_paths, mock_transport_factory({}))
    req = col.plan_schedules()
    assert req.url == NFLVERSE_SCHEDULES_URL
    assert req.cache_path == NFLVERSE_SCHEDULES_PATH
    assert req.season is None
    assert req.headers == ()
    assert req.source == "nfl_nflverse"


def test_run_schedules_conditional_refresh(vault_paths, mock_transport_factory) -> None:
    body = (_FIX / "games_synthetic.csv").read_bytes()
    first = mock_transport_factory(
        {**_ROBOTS, NFLVERSE_SCHEDULES_URL: (200, body, {"ETag": '"abc"'})}
    )
    summary = _collector(vault_paths, first).run_schedules(refresh=False, dry_run=False)
    assert summary.fetched == 1
    assert (vault_paths.raw / NFLVERSE_SCHEDULES_PATH).read_bytes() == body

    second = mock_transport_factory({**_ROBOTS, NFLVERSE_SCHEDULES_URL: (304, b"", {})})
    summary = _collector(vault_paths, second).run_schedules(refresh=True, dry_run=False)
    assert summary.not_modified == 1
    sent = [r for r in second.requests if r.url == NFLVERSE_SCHEDULES_URL]
    assert sent[0].headers.get("if-none-match") == '"abc"'


def test_pbp_assets_lists_and_sends_api_headers(vault_paths, mock_transport_factory) -> None:
    handle = mock_transport_factory(_listing_responses())
    assets = _collector(vault_paths, handle).pbp_assets(dry_run=False)
    names = {a.name for a in assets}
    assert "play_by_play_2015.parquet" in names
    assert len(assets) == 9
    assert isinstance(assets[0], NflverseAsset)
    api = [r for r in handle.requests if r.url in (_RELEASE_URL, _page_url(1))]
    assert len(api) == 2
    for r in api:
        for key, value in API_HEADERS:
            assert r.headers[key.lower()] == value
    for r in handle.requests:
        assert "://github.com/" not in r.url
        assert r.url.split("/")[2] in ("api.github.com", "raw.githubusercontent.com")


def test_pbp_assets_paginates_until_short_page(vault_paths, mock_transport_factory) -> None:
    def item(i: int) -> dict:
        return {"id": i, "name": f"x{i}", "size": 1, "updated_at": "2026-01-01T00:00:00Z"}

    responses = _listing_responses()
    responses[_page_url(1)] = (200, json.dumps([item(i) for i in range(100)]).encode(), {})
    responses[_page_url(2)] = (200, json.dumps([item(1000)]).encode(), {})
    handle = mock_transport_factory(responses)
    assets = _collector(vault_paths, handle).pbp_assets(dry_run=False)
    assert len(assets) == 101


@pytest.mark.parametrize(
    "bad",
    [
        {"name": "a", "size": 1, "updated_at": "x"},
        {"id": 1, "name": "a", "size": "1", "updated_at": "x"},
        {"id": True, "name": "a", "size": 1, "updated_at": "x"},
        {"id": 1, "name": "a", "size": 1},
    ],
)
def test_pbp_assets_schema_errors(vault_paths, mock_transport_factory, bad) -> None:
    responses = _listing_responses()
    responses[_page_url(1)] = (200, json.dumps([bad]).encode(), {})
    handle = mock_transport_factory(responses)
    with pytest.raises(NflverseSchemaError) as exc:
        _collector(vault_paths, handle).pbp_assets(dry_run=False)
    assert "page 1" in str(exc.value)


def test_pbp_assets_page_cap(vault_paths, mock_transport_factory) -> None:
    full = json.dumps(
        [
            {"id": i, "name": f"x{i}", "size": 1, "updated_at": "2026-01-01T00:00:00Z"}
            for i in range(100)
        ]
    ).encode()
    responses = _listing_responses()
    for page in range(1, MAX_ASSET_PAGES + 1):
        responses[_page_url(page)] = (200, full, {})
    handle = mock_transport_factory(responses)
    with pytest.raises(NflverseSchemaError):
        _collector(vault_paths, handle).pbp_assets(dry_run=False)
    assert MAX_ASSET_PAGES == 10


def test_pbp_assets_dry_run_reads_cache_only(vault_paths, mock_transport_factory) -> None:
    handle = mock_transport_factory({})
    col = _collector(vault_paths, handle)
    assert col.pbp_assets(dry_run=True) == []

    raw = vault_paths.raw
    (raw / NFLVERSE_PBP_RELEASE_PATH).parent.mkdir(parents=True, exist_ok=True)
    (raw / NFLVERSE_PBP_RELEASE_PATH).write_bytes(
        (_FIX / "release_pbp_synthetic.json").read_bytes()
    )
    (raw / nflverse_pbp_assets_page_path(1)).write_bytes(
        (_FIX / "assets_p1_synthetic.json").read_bytes()
    )
    assert len(col.pbp_assets(dry_run=True)) == 9
    assert handle.requests == []


def test_bearer_only_on_api_host(vault_paths, mock_transport_factory) -> None:
    sched = mock_transport_factory({**_ROBOTS, NFLVERSE_SCHEDULES_URL: (200, b"a,b\n", {})})
    _collector(vault_paths, sched, token="tok").run_schedules(refresh=False, dry_run=False)
    assert all("authorization" not in r.headers for r in sched.requests)

    api = mock_transport_factory(_listing_responses())
    _collector(vault_paths, api, token="tok").pbp_assets(dry_run=False)
    listed = [r for r in api.requests if r.url == _RELEASE_URL]
    assert listed[0].headers["authorization"] == "Bearer tok"
