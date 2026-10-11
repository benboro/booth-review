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


# -- pbp download (Task 2) ------------------------------------------------------------


def _pq(n: int = 40, fill: bytes = b"x") -> bytes:
    return b"PAR1" + fill * (n - 8) + b"PAR1"


def _asset(season: int, *, size: int = 40, updated: str = "2026-01-01T00:00:00Z", aid: int = 7):
    return NflverseAsset(aid + season, f"play_by_play_{season}.parquet", size, updated)


def _asset_url(asset: NflverseAsset) -> str:
    return f"{NFLVERSE_API_BASE}/releases/assets/{asset.asset_id}"


def _ledger(vault_paths) -> list[dict]:
    path = vault_paths.ledger / "nfl_nflverse_assets.jsonl"
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]


def _full(assets: list[NflverseAsset], bodies: dict[int, bytes]) -> dict:
    responses = dict(_listing_responses())
    responses[_page_url(1)] = (
        200,
        json.dumps(
            [
                {"id": a.asset_id, "name": a.name, "size": a.size, "updated_at": a.updated_at}
                for a in assets
            ]
        ).encode(),
        {},
    )
    for a in assets:
        if a.asset_id in bodies:
            responses[_asset_url(a)] = (200, bodies[a.asset_id], {})
    return responses


def test_plan_pbp_shape(vault_paths, mock_transport_factory) -> None:
    col = _collector(vault_paths, mock_transport_factory({}))
    assets = [_asset(2014), _asset(2015)]
    plan = col.plan_pbp([2014, 2015], assets)
    assert len(plan) == 2
    req, asset, exists = plan[0]
    assert req.url == _asset_url(asset)
    assert req.headers == (("Accept", "application/octet-stream"),)
    assert req.cache_path == "nfl/nflverse/pbp/play_by_play_2014.parquet"
    assert req.source == "nfl_nflverse"
    assert req.season == 2014
    assert exists is False


def test_run_pbp_downloads_ledgers_then_skips_unchanged(
    vault_paths, mock_transport_factory
) -> None:
    a = _asset(2015)
    handle = mock_transport_factory(_full([a], {a.asset_id: _pq()}))
    summary = _collector(vault_paths, handle).run_pbp([2015], dry_run=False)
    assert summary.fetched == 1
    assert summary.counts()["fetched"] == 1
    sent = [r for r in handle.requests if r.url == _asset_url(a)]
    assert sent[0].headers["accept"] == "application/octet-stream"
    (line,) = _ledger(vault_paths)
    assert (line["updated_at"], line["size"], line["name"]) == (a.updated_at, 40, a.name)
    assert len(line["sha256"]) == 64

    again = mock_transport_factory(_full([a], {}))
    summary = _collector(vault_paths, again).run_pbp([2015], dry_run=False)
    assert summary.unchanged == 1 and summary.fetched == 0
    assert not [r for r in again.requests if r.url == _asset_url(a)]


def test_run_pbp_refetches_when_updated_at_changes(vault_paths, mock_transport_factory) -> None:
    a = _asset(2016)
    _collector(vault_paths, mock_transport_factory(_full([a], {a.asset_id: _pq()}))).run_pbp(
        [2016], dry_run=False
    )
    b = _asset(2016, size=44, updated="2026-02-02T00:00:00Z")
    handle = mock_transport_factory(_full([b], {b.asset_id: _pq(44, b"y")}))
    summary = _collector(vault_paths, handle).run_pbp([2016], dry_run=False)
    assert summary.fetched == 1
    assert len(_ledger(vault_paths)) == 2
    cached = vault_paths.raw / "nfl/nflverse/pbp/play_by_play_2016.parquet"
    assert cached.read_bytes() == _pq(44, b"y")


def test_run_pbp_frozen(vault_paths, mock_transport_factory) -> None:
    vault_paths.frozen.write_text(json.dumps({"nfl_nflverse": [2014, 2015]}), encoding="utf-8")
    cached = vault_paths.raw / "nfl/nflverse/pbp/play_by_play_2014.parquet"
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(_pq())
    assets = [_asset(2014), _asset(2015)]
    handle = mock_transport_factory(_full(assets, {}))
    summary = _collector(vault_paths, handle).run_pbp([2014, 2015], dry_run=False)
    assert (summary.frozen, summary.frozen_missing, summary.fetched) == (1, 1, 0)
    assert not [r for r in handle.requests if "/releases/assets/" in r.url]


def test_run_pbp_integrity_failures_write_no_ledger(vault_paths, mock_transport_factory) -> None:
    # WR-02: a failed check is a counted failure, not a raise, and writes nothing.
    a = _asset(2014)
    cached = vault_paths.raw / "nfl/nflverse/pbp/play_by_play_2014.parquet"
    for body in (_pq(41), b"XXXX" + b"z" * 32 + b"XXXX"):
        handle = mock_transport_factory(_full([a], {a.asset_id: body}))
        summary = _collector(vault_paths, handle).run_pbp([2014], dry_run=False)
        assert (summary.failed, summary.fetched) == (1, 0)
        assert _ledger(vault_paths) == []
        assert not cached.exists()


def test_run_pbp_integrity_failure_keeps_the_good_file_and_runs_other_seasons(
    vault_paths, mock_transport_factory
) -> None:
    good = _asset(2016)
    _collector(vault_paths, mock_transport_factory(_full([good], {good.asset_id: _pq()}))).run_pbp(
        [2016], dry_run=False
    )
    cached = vault_paths.raw / "nfl/nflverse/pbp/play_by_play_2016.parquet"
    manifest_before = vault_paths.manifest.read_text(encoding="utf-8")

    bad = _asset(2016, size=44, updated="2026-02-02T00:00:00Z")
    other = _asset(2017)
    handle = mock_transport_factory(
        _full([bad, other], {bad.asset_id: _pq(43), other.asset_id: _pq()})
    )
    summary = _collector(vault_paths, handle).run_pbp([2016, 2017], dry_run=False)

    assert (summary.failed, summary.fetched) == (1, 1)
    assert cached.read_bytes() == _pq()
    assert [line["name"] for line in _ledger(vault_paths)] == [good.name, other.name]
    added = vault_paths.manifest.read_text(encoding="utf-8")[len(manifest_before) :]
    rejected = [
        json.loads(x) for x in added.splitlines() if json.loads(x)["url"] == _asset_url(bad)
    ]
    assert len(rejected) == 1
    assert rejected[0]["path"] is None and rejected[0]["etag"] is None


def test_run_pbp_without_a_ledger_line_never_sends_validators(
    vault_paths, mock_transport_factory
) -> None:
    # A file cached without a ledger line (e.g. a bad download kept by an older
    # version) must be re-downloaded in full, never confirmed by a 304.
    a = _asset(2018)
    responses = _full([a], {})
    responses[_asset_url(a)] = (200, _pq(), {"ETag": '"v1"'})
    _collector(vault_paths, mock_transport_factory(responses)).run_pbp([2018], dry_run=False)
    (vault_paths.ledger / "nfl_nflverse_assets.jsonl").unlink()

    handle = mock_transport_factory(responses)
    summary = _collector(vault_paths, handle).run_pbp([2018], dry_run=False)

    assert summary.fetched == 1
    sent = [r for r in handle.requests if r.url == _asset_url(a)]
    assert "if-none-match" not in sent[0].headers
    assert len(_ledger(vault_paths)) == 1

    # With the ledger line back, a changed listing is checked conditionally.
    b = _asset(2018, size=44, updated="2026-03-03T00:00:00Z")
    changed = _full([b], {})
    changed[_asset_url(b)] = (200, _pq(44), {"ETag": '"v2"'})
    handle = mock_transport_factory(changed)
    _collector(vault_paths, handle).run_pbp([2018], dry_run=False)
    sent = [r for r in handle.requests if r.url == _asset_url(b)]
    assert sent[0].headers.get("if-none-match") == '"v1"'


def test_run_pbp_missing_asset_counted(vault_paths, mock_transport_factory) -> None:
    handle = mock_transport_factory(_full([_asset(2014)], {}))
    summary = _collector(vault_paths, handle).run_pbp([2020], dry_run=False)
    assert summary.missing_assets == (2020,)
    assert summary.counts()["missing_assets"] == 1


def test_run_pbp_follows_redirect(vault_paths, mock_transport_factory) -> None:
    a = _asset(2014)
    signed = "https://release-assets.githubusercontent.com/signed/abc?sig=1"
    responses = _full([a], {})
    responses[_asset_url(a)] = (302, b"", {"Location": signed})
    responses[signed] = (200, _pq(), {})
    responses["https://release-assets.githubusercontent.com/robots.txt"] = (404, b"nf", {})
    handle = mock_transport_factory(responses)
    summary = _collector(vault_paths, handle, token="tok").run_pbp([2014], dry_run=False)
    assert summary.fetched == 1
    redirected = [r for r in handle.requests if r.url == signed]
    assert redirected and "authorization" not in redirected[0].headers


def test_run_pbp_dry_run_sends_nothing(vault_paths, mock_transport_factory) -> None:
    handle = mock_transport_factory({})
    summary = _collector(vault_paths, handle).run_pbp([2014], dry_run=True)
    assert summary.dry_run and summary.planned == 0
    assert handle.requests == []


def test_collector_source_has_no_github_com_or_httpx() -> None:
    text = (Path(__file__).parents[1] / "src/booth_review/sources/nflverse/collector.py").read_text(
        encoding="utf-8"
    )
    assert "httpx" not in text
    assert "https://github.com" not in text
