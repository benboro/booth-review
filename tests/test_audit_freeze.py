"""Tests for D-06 freeze (audit/freeze.py).

`freeze_seasons` is exercised directly against `vault_paths` (no git
required); the post-freeze `FrozenSeasonError` checks build a `RawCache`
against a mock transport with zero configured responses, so any accidental
request raises immediately.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path

import pytest

from booth_review.audit.completeness import CFBD_SEASON_ENDPOINTS
from booth_review.audit.freeze import Waiver, freeze_seasons, parse_waiver
from booth_review.config import DataPaths
from booth_review.errors import FreezeRefusedError, FrozenSeasonError
from booth_review.sources.cfbd.collector import CfbdCollector
from booth_review.transport.budget import CfbdBudget
from booth_review.transport.cache import RawCache
from booth_review.transport.client import PoliteClient
from booth_review.transport.types import FetchRequest

FIXTURES = Path(__file__).parent / "fixtures" / "sports506"
_WEEK_TEMPLATE = (FIXTURES / "week_synthetic.html").read_bytes()

_TODAY = date(2026, 9, 25)


def _page(season: int, label: str, *, nav_labels: list[str]) -> bytes:
    text = _WEEK_TEMPLATE.decode("utf-8")
    text = text.replace("yr=2025&wk=5", f"yr={season}&wk={label}")
    text = text.replace("Week 5, 2025", f"Week {label}, {season}")
    anchors = "".join(
        f'<a href="ncaaf.php?yr={season}&wk={nav_label}">wk {nav_label}</a>'
        for nav_label in nav_labels
    )
    text = text.replace("<body>", f"<body><nav>{anchors}</nav>", 1)
    return text.encode("utf-8")


def _slug(season: int) -> str:
    return f"cfb-alpha-vs-beta-{season}-09-06"


def _seed_complete_season(paths: DataPaths, season: int) -> None:
    label = "0"
    (paths.raw / "sports506" / str(season)).mkdir(parents=True, exist_ok=True)
    (paths.raw / "sports506" / str(season) / f"wk-{label.zfill(2)}.html").write_bytes(
        _page(season, label, nav_labels=[label])
    )
    for name in CFBD_SEASON_ENDPOINTS:
        endpoint_path = paths.raw / "cfbd" / name / f"{season}.json"
        endpoint_path.parent.mkdir(parents=True, exist_ok=True)
        endpoint_path.write_text(json.dumps([{"id": 1}]), encoding="utf-8")

    slug = _slug(season)
    sitemap_path = paths.raw / "ratingsref" / "sitemap" / "2026-09-25.xml"
    existing_urls = ""
    if sitemap_path.is_file():
        existing = sitemap_path.read_text(encoding="utf-8")
        start = existing.find("<urlset")
        end_tag = existing.find(">", start) + 1
        existing_urls = existing[end_tag : existing.rfind("</urlset>")]
    sitemap_path.parent.mkdir(parents=True, exist_ok=True)
    sitemap_path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{existing_urls}"
        f"<url><loc>https://ratingsreference.com/telecast/{slug}</loc>"
        f"<lastmod>2026-01-01</lastmod></url>"
        "</urlset>",
        encoding="utf-8",
    )

    record_path = paths.raw / "ratingsref" / "telecast" / str(season) / f"{slug}.json"
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text("{}", encoding="utf-8")

    lastmod_data: dict[str, object] = {}
    if paths.rr_lastmod.is_file():
        lastmod_data = json.loads(paths.rr_lastmod.read_text(encoding="utf-8"))
    lastmod_data[slug] = {
        "lastmod": "2026-01-01",
        "fetched_at": "2026-01-01T00:00:00Z",
        "record_url": "x",
    }
    paths.rr_lastmod.write_text(json.dumps(lastmod_data), encoding="utf-8")


def _client(handle) -> PoliteClient:
    return PoliteClient(transport=handle.transport, clock=lambda: 0.0, sleep=lambda _s: None)


# -- happy path -------------------------------------------------------------------------


def test_freeze_seasons_all_complete_merges_with_existing_sorted_no_duplicates(
    vault_paths: DataPaths,
) -> None:
    vault_paths.frozen.write_text(
        json.dumps({"sports506": [2019], "ratingsref": [2019], "cfbd": [2019]}),
        encoding="utf-8",
    )
    _seed_complete_season(vault_paths, 2020)
    _seed_complete_season(vault_paths, 2021)

    result = freeze_seasons(vault_paths, [2020, 2021], today=_TODAY, waivers=())

    assert result.seasons_added == [2020, 2021]
    assert result.already_frozen == []

    frozen = json.loads(vault_paths.frozen.read_text(encoding="utf-8"))
    assert frozen == {
        "sports506": [2019, 2020, 2021],
        "ratingsref": [2019, 2020, 2021],
        "cfbd": [2019, 2020, 2021],
    }

    freeze_record = json.loads((vault_paths.audit / "freeze.json").read_text(encoding="utf-8"))
    assert freeze_record["seasons"] == [2020, 2021]
    assert freeze_record["waivers"] == []
    assert "frozen_at" in freeze_record

    completeness_bytes = (vault_paths.audit / "completeness.json").read_bytes()
    assert freeze_record["completeness_sha256"] == hashlib.sha256(completeness_bytes).hexdigest()


def test_freeze_seasons_already_frozen_is_idempotent(vault_paths: DataPaths) -> None:
    _seed_complete_season(vault_paths, 2020)
    freeze_seasons(vault_paths, [2020], today=_TODAY, waivers=())
    before = vault_paths.frozen.read_bytes()

    result = freeze_seasons(vault_paths, [2020], today=_TODAY, waivers=())

    assert result.already_frozen == [2020]
    assert result.seasons_added == []
    assert vault_paths.frozen.read_bytes() == before


# -- refusals -----------------------------------------------------------------------------


def test_freeze_seasons_before_freeze_date_raises_and_writes_nothing(
    vault_paths: DataPaths,
) -> None:
    before = vault_paths.frozen.read_bytes()

    with pytest.raises(FreezeRefusedError, match="2026"):
        freeze_seasons(vault_paths, [2026], today=_TODAY, waivers=())

    assert vault_paths.frozen.read_bytes() == before
    assert not (vault_paths.audit / "completeness.json").exists()


def test_freeze_seasons_incomplete_cell_not_waived_raises_frozen_json_untouched(
    vault_paths: DataPaths,
) -> None:
    # No 506/CFBD/RR data at all for 2020: every cell is incomplete.
    before = vault_paths.frozen.read_bytes()

    with pytest.raises(FreezeRefusedError, match="2020:sports506"):
        freeze_seasons(vault_paths, [2020], today=_TODAY, waivers=())

    assert vault_paths.frozen.read_bytes() == before


def test_freeze_seasons_waiver_allows_incomplete_cell(vault_paths: DataPaths) -> None:
    _seed_complete_season(vault_paths, 2020)
    # Remove the RR record only, so ratingsref is the one incomplete cell.
    slug = _slug(2020)
    (vault_paths.raw / "ratingsref" / "telecast" / "2020" / f"{slug}.json").unlink()

    result = freeze_seasons(vault_paths, [2020], today=_TODAY, waivers=[Waiver(2020, "ratingsref")])

    assert result.seasons_added == [2020]
    frozen = json.loads(vault_paths.frozen.read_text(encoding="utf-8"))
    assert 2020 in frozen["ratingsref"]

    freeze_record = json.loads((vault_paths.audit / "freeze.json").read_text(encoding="utf-8"))
    assert freeze_record["waivers"] == ["2020:ratingsref"]


def test_freeze_seasons_dry_run_writes_nothing(vault_paths: DataPaths) -> None:
    _seed_complete_season(vault_paths, 2020)
    frozen_before = vault_paths.frozen.read_bytes()

    result = freeze_seasons(vault_paths, [2020], today=_TODAY, waivers=(), dry_run=True)

    assert result.seasons_added == [2020]
    assert vault_paths.frozen.read_bytes() == frozen_before
    assert not (vault_paths.audit / "completeness.json").exists()
    assert not (vault_paths.audit / "freeze.json").exists()


# -- parse_waiver ---------------------------------------------------------------------------


def test_parse_waiver_valid() -> None:
    assert parse_waiver("2020:sports506") == Waiver(season=2020, source="sports506")


def test_parse_waiver_malformed_raises() -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        parse_waiver("not-a-waiver")


def test_parse_waiver_unknown_source_raises() -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        parse_waiver("2020:unknown")


# -- post-freeze: FrozenSeasonError through RawCache -----------------------------------------


def test_frozen_season_raises_for_uncached_sports506_request(
    vault_paths: DataPaths, mock_transport_factory
) -> None:
    _seed_complete_season(vault_paths, 2020)
    freeze_seasons(vault_paths, [2020], today=_TODAY, waivers=())

    handle = mock_transport_factory({})
    cache = RawCache(vault_paths, _client(handle))
    req = FetchRequest(
        source="sports506",
        season=2020,
        url="https://506sports.com/ncaaf.php?yr=2020&wk=9",
        cache_path="sports506/2020/wk-09.html",
    )

    with pytest.raises(FrozenSeasonError):
        cache.get_or_fetch(req)
    assert handle.requests == []


def test_frozen_season_raises_for_cfbd_refresh(
    vault_paths: DataPaths, mock_transport_factory
) -> None:
    _seed_complete_season(vault_paths, 2020)
    freeze_seasons(vault_paths, [2020], today=_TODAY, waivers=())

    handle = mock_transport_factory({})
    cache = RawCache(vault_paths, _client(handle))
    budget = CfbdBudget(vault_paths.cfbd_ledger)
    collector = CfbdCollector(cache, budget, "fake-token")

    with pytest.raises(FrozenSeasonError):
        collector.run(2020, ["games"], dry_run=False, refresh=True)
    assert handle.requests == []
