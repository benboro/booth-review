"""Offline tests for the Retrosheet collector: mock transport, synthetic index."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from booth_review.mlb.constants import RETROSHEET_MAX_ZIP_BYTES
from booth_review.mlb.layout import (
    RETROSHEET_INDEX_PATH,
    RETROSHEET_INDEX_URL,
    retrosheet_asset_path,
)
from booth_review.sources.retrosheet.assets import discover_assets
from booth_review.sources.retrosheet.collector import (
    RetrosheetCollector,
    RetrosheetMissingAsset,
    RetrosheetPathError,
    check_retrosheet_url,
)
from booth_review.transport.cache import RawCache
from booth_review.transport.client import PoliteClient

_INDEX = (
    Path(__file__).parent / "fixtures" / "mlb" / "retrosheet" / "csvdownloads_synthetic.html"
).read_bytes()
_BASE = "https://www.retrosheet.org/downloads/"
_ROBOTS = {"https://www.retrosheet.org/robots.txt": (404, b"nf", {})}
_ZIP = b"PK\x03\x04" + b"synthetic"


def _collector(vault_paths, handle) -> RetrosheetCollector:
    client = PoliteClient(transport=handle.transport, clock=lambda: 0.0, sleep=lambda s: None)
    return RetrosheetCollector(RawCache(vault_paths, client), vault_paths)


def _seed_index(vault_paths) -> None:
    path = vault_paths.raw / RETROSHEET_INDEX_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_INDEX)


def _asset_responses() -> dict:
    return {
        **_ROBOTS,
        _BASE + "2099/2099csvs.zip": (200, _ZIP, {}),
        _BASE + "2100/2100csvs.zip": (200, _ZIP, {}),
    }


def test_discover_allow_list() -> None:
    assets = discover_assets(_INDEX)
    assert {(a.kind, a.season) for a in assets} == {
        ("season_bundle", 2099),
        ("season_bundle", 2100),
    }
    for asset in assets:
        assert "gamelogs" not in asset.url
        assert "boxesetc" not in asset.url
        assert asset.url.startswith(_BASE)


def test_discover_ignores_off_host() -> None:
    assert all("example.invalid" not in a.url for a in discover_assets(_INDEX))


@pytest.mark.parametrize(
    "url",
    [
        "https://www.retrosheet.org/gamelogs/gl2099.zip",
        "https://www.retrosheet.org/downloads//gamelogs/x.zip",
        "https://www.retrosheet.org/boxesetc/2099/x.htm",
        "https://www.retrosheet.org/other/x.zip",
        "http://www.retrosheet.org/downloads/x.zip",
        "https://example.invalid/downloads/x.zip",
    ],
)
def test_guard_rejects(url: str) -> None:
    with pytest.raises(RetrosheetPathError) as err:
        check_retrosheet_url(url)
    assert "gl2099" not in str(err.value)


def test_url_guard_passes_downloads_zip() -> None:
    check_retrosheet_url(_BASE + "2099/2099csvs.zip")


def test_asset_name_unsafe_rejected() -> None:
    with pytest.raises(ValueError):
        retrosheet_asset_path("../x.zip")
    with pytest.raises(ValueError):
        retrosheet_asset_path("a/b.zip")


def _collector_for_plan() -> RetrosheetCollector:
    return RetrosheetCollector(None, None)  # type: ignore[arg-type]


def test_plan_index() -> None:
    req = _collector_for_plan().plan_index()
    assert (req.source, req.url, req.cache_path) == (
        "mlb_retrosheet",
        RETROSHEET_INDEX_URL,
        RETROSHEET_INDEX_PATH,
    )


def test_index_only(vault_paths, mock_transport_factory) -> None:
    handle = mock_transport_factory({**_ROBOTS, RETROSHEET_INDEX_URL: (200, _INDEX, {})})
    summary = _collector(vault_paths, handle).run([2099], index_only=True)
    assert summary.fetched == 1
    urls = [r.url for r in handle.requests if "robots" not in r.url]
    assert urls == [RETROSHEET_INDEX_URL]


def test_asset_plan_and_fetch(vault_paths, mock_transport_factory) -> None:
    _seed_index(vault_paths)
    handle = mock_transport_factory(_asset_responses())
    summary = _collector(vault_paths, handle).run([2099, 2100])
    assert summary.counts() == {"planned": 2, "fetched": 2, "cached": 0, "frozen": 0, "failed": 0}
    assert (vault_paths.raw / retrosheet_asset_path("2099csvs.zip")).read_bytes() == _ZIP
    again = _collector(vault_paths, mock_transport_factory({})).run([2099, 2100])
    assert (again.fetched, again.cached) == (0, 2)


def test_frozen_season_skipped(vault_paths, mock_transport_factory) -> None:
    _seed_index(vault_paths)
    vault_paths.frozen.write_text(json.dumps({"mlb_retrosheet": [2099]}), encoding="utf-8")
    handle = mock_transport_factory(_asset_responses())
    summary = _collector(vault_paths, handle).run([2099, 2100])
    assert (summary.planned, summary.frozen, summary.fetched) == (1, 1, 1)
    assert not any("2099csvs" in r.url for r in handle.requests)


def test_missing_asset_raises_before_requests(vault_paths, mock_transport_factory) -> None:
    _seed_index(vault_paths)
    handle = mock_transport_factory(_asset_responses())
    with pytest.raises(RetrosheetMissingAsset) as err:
        _collector(vault_paths, handle).run([2099, 2101])
    assert "2101" in str(err.value)
    assert handle.requests == []


def test_zip_magic_rejected(vault_paths, mock_transport_factory) -> None:
    _seed_index(vault_paths)
    responses = _asset_responses()
    responses[_BASE + "2099/2099csvs.zip"] = (200, b"<html>not a zip</html>", {})
    summary = _collector(vault_paths, mock_transport_factory(responses)).run([2099])
    assert (summary.fetched, summary.failed) == (0, 1)
    assert not (vault_paths.raw / retrosheet_asset_path("2099csvs.zip")).exists()


def test_size_cap_rejected(vault_paths, mock_transport_factory, monkeypatch) -> None:
    _seed_index(vault_paths)
    monkeypatch.setattr("booth_review.sources.retrosheet.collector.RETROSHEET_MAX_ZIP_BYTES", 10)
    assert RETROSHEET_MAX_ZIP_BYTES > 10
    summary = _collector(vault_paths, mock_transport_factory(_asset_responses())).run([2099])
    assert summary.failed == 1
    assert summary.fetched == 0


def test_4xx_counts_failed_and_continues(vault_paths, mock_transport_factory) -> None:
    _seed_index(vault_paths)
    responses = _asset_responses()
    responses[_BASE + "2099/2099csvs.zip"] = (404, b"", {})
    summary = _collector(vault_paths, mock_transport_factory(responses)).run([2099])
    assert (summary.failed, summary.fetched) == (1, 0)


def test_dry_run_sends_nothing(vault_paths, mock_transport_factory) -> None:
    _seed_index(vault_paths)
    handle = mock_transport_factory({})
    summary = _collector(vault_paths, handle).run([2099, 2100], dry_run=True)
    assert summary.dry_run is True
    assert summary.planned == 2
    assert handle.requests == []
    assert set(summary.counts()) == {"planned", "fetched", "cached", "frozen", "failed"}
