"""Offline tests for the collector run loop and the three source collectors.

No network: each collector is driven through a real RawCache wrapping a
PoliteClient built on httpx2.MockTransport and the fake clock, so pacing
sleeps are recorded rather than slept (FOUND-01, D-13, D-16, FOUND-03).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from booth_review.errors import FrozenSeasonError
from booth_review.sources.ratingsref.collector import SITEMAP_URL, RatingsRefCollector
from booth_review.sources.sports506.collector import WEEK_LABELS, Sports506Collector
from booth_review.transport.cache import RawCache
from booth_review.transport.client import PoliteClient

FIXTURES_RR = Path(__file__).parent / "fixtures" / "ratingsref"

_SELECTED_RR_IDS = [
    "cfb-northfield-state-lakeshore-tech-2025-09-13",
    "cfb-pat-valley-clearwater-tech-2026-01-10",
    "cfb-riverside-poly-granite-college-2025-11-01",
]


def _client(handle, *, fake_clock=None) -> PoliteClient:
    kwargs: dict = {"transport": handle.transport}
    if fake_clock is not None:
        kwargs["clock"] = fake_clock.now
        kwargs["sleep"] = fake_clock.sleep
    else:
        kwargs["clock"] = lambda: 0.0
        kwargs["sleep"] = lambda seconds: None
    return PoliteClient(**kwargs)


def _sports506_urls(season: int) -> list[str]:
    return [f"https://506sports.com/ncaaf.php?yr={season}&wk={label}" for label in WEEK_LABELS]


# -- Sports506Collector -------------------------------------------------------


def test_sports506_plan_returns_18_requests_in_documented_pattern(
    vault_paths, mock_transport_factory
) -> None:
    handle = mock_transport_factory({})
    cache = RawCache(vault_paths, _client(handle))
    collector = Sports506Collector(cache)

    requests = collector.plan(2025)

    assert len(requests) == 18
    assert requests[0].url == "https://506sports.com/ncaaf.php?yr=2025&wk=0"
    assert requests[-1].url == "https://506sports.com/ncaaf.php?yr=2025&wk=B"
    assert requests[0].cache_path == "sports506/2025/wk-00.html"
    assert requests[16].cache_path == "sports506/2025/wk-16.html"
    assert requests[-1].cache_path == "sports506/2025/wk-B.html"
    assert all(req.source == "sports506" and req.season == 2025 for req in requests)


def test_sports506_dry_run_empty_vault_reports_all_new_and_sends_nothing(
    vault_paths, mock_transport_factory
) -> None:
    handle = mock_transport_factory({})
    cache = RawCache(vault_paths, _client(handle))
    collector = Sports506Collector(cache)

    summary = collector.run(2025, dry_run=True)

    assert summary.planned == 18
    assert len(summary.new_urls) == 18
    assert summary.fetched == 0
    assert summary.dry_run is True
    assert handle.requests == []


def test_sports506_run_fetches_18_pages_and_second_run_is_fully_cached(
    vault_paths, mock_transport_factory, fake_clock
) -> None:
    responses = {"https://506sports.com/robots.txt": (404, b"nf", {})}
    for url in _sports506_urls(2025):
        responses[url] = (200, f"<html>{url}</html>".encode(), {})
    handle = mock_transport_factory(responses)
    cache = RawCache(vault_paths, _client(handle, fake_clock=fake_clock))
    collector = Sports506Collector(cache)

    summary = collector.run(2025, dry_run=False)

    assert summary.fetched == 18
    assert len(handle.requests) == 19  # 18 pages + one robots.txt

    second_summary = collector.run(2025, dry_run=False)
    assert second_summary.cached == 18
    assert second_summary.fetched == 0
    assert len(handle.requests) == 19  # unchanged: no new requests sent


def test_sports506_one_404_is_recorded_failed_others_still_fetched(
    vault_paths, mock_transport_factory, fake_clock
) -> None:
    responses = {"https://506sports.com/robots.txt": (404, b"nf", {})}
    for url in _sports506_urls(2025):
        responses[url] = (200, b"<html>ok</html>", {})
    missing_url = "https://506sports.com/ncaaf.php?yr=2025&wk=5"
    responses[missing_url] = (404, b"not found", {})
    handle = mock_transport_factory(responses)
    cache = RawCache(vault_paths, _client(handle, fake_clock=fake_clock))
    collector = Sports506Collector(cache)

    summary = collector.run(2025, dry_run=False)

    assert summary.failed == 1
    assert missing_url in summary.failed_urls
    assert summary.fetched == 17

    lines = [
        json.loads(line) for line in vault_paths.manifest.read_text(encoding="utf-8").splitlines()
    ]
    assert any(line["url"] == missing_url and line["status"] == 404 for line in lines)


def test_sports506_frozen_season_dry_run_reports_frozen_miss_and_real_run_raises(
    vault_paths, mock_transport_factory
) -> None:
    vault_paths.frozen.write_text(json.dumps({"sports506": [2025], "ratingsref": [], "cfbd": []}))
    handle = mock_transport_factory({})
    cache = RawCache(vault_paths, _client(handle))
    collector = Sports506Collector(cache)

    dry_summary = collector.run(2025, dry_run=True)
    assert dry_summary.frozen_miss == 18
    assert handle.requests == []

    with pytest.raises(FrozenSeasonError):
        collector.run(2025, dry_run=False)
    assert handle.requests == []


# -- RatingsRefCollector -------------------------------------------------------


def test_ratingsref_sitemap_dry_run_with_no_cache_returns_none_and_sends_nothing(
    vault_paths, mock_transport_factory
) -> None:
    handle = mock_transport_factory({})
    cache = RawCache(vault_paths, _client(handle))
    collector = RatingsRefCollector(cache, vault_paths)

    result = collector.sitemap(dry_run=True)

    assert result is None
    assert handle.requests == []


def test_ratingsref_run_dry_run_with_no_cached_sitemap_reports_planned_zero(
    vault_paths, mock_transport_factory, caplog
) -> None:
    handle = mock_transport_factory({})
    cache = RawCache(vault_paths, _client(handle))
    collector = RatingsRefCollector(cache, vault_paths)

    with caplog.at_level("INFO"):
        summary = collector.run(date(2025, 7, 1), date(2026, 6, 30), dry_run=True)

    assert summary.planned == 0
    assert handle.requests == []
    assert any("sitemap not cached" in record.message for record in caplog.records)


def test_ratingsref_run_fetches_sitemap_and_in_window_records_with_lastmod_tracking(
    vault_paths, mock_transport_factory, fake_clock
) -> None:
    sitemap_xml = (FIXTURES_RR / "sitemap_synthetic.xml").read_bytes()
    responses = {
        "https://ratingsreference.com/robots.txt": (404, b"nf", {}),
        SITEMAP_URL: (200, sitemap_xml, {}),
    }
    for telecast_id in _SELECTED_RR_IDS:
        url = f"https://ratingsreference.com/api/telecast/{telecast_id}.json"
        responses[url] = (200, json.dumps({"telecast": {"id": telecast_id}}).encode(), {})
    handle = mock_transport_factory(responses)
    cache = RawCache(vault_paths, _client(handle, fake_clock=fake_clock))
    collector = RatingsRefCollector(cache, vault_paths)

    summary = collector.run(date(2025, 7, 1), date(2026, 6, 30), dry_run=False)

    assert summary.planned == 3
    assert summary.fetched == 3

    sitemap_files = list((vault_paths.raw / "ratingsref" / "sitemap").glob("*.xml"))
    assert len(sitemap_files) == 1

    for telecast_id in _SELECTED_RR_IDS:
        expected = vault_paths.raw / "ratingsref" / "telecast" / "2025" / f"{telecast_id}.json"
        assert expected.is_file()

    lastmod_data = json.loads(vault_paths.rr_lastmod.read_text(encoding="utf-8"))
    assert set(lastmod_data) == set(_SELECTED_RR_IDS)
    for entry in lastmod_data.values():
        assert set(entry) == {"lastmod", "fetched_at", "record_url"}
        assert entry["record_url"].startswith("https://ratingsreference.com/telecast/")


def test_ratingsref_second_run_same_day_reuses_sitemap_and_sends_zero_requests(
    vault_paths, mock_transport_factory, fake_clock
) -> None:
    sitemap_xml = (FIXTURES_RR / "sitemap_synthetic.xml").read_bytes()
    responses = {
        "https://ratingsreference.com/robots.txt": (404, b"nf", {}),
        SITEMAP_URL: (200, sitemap_xml, {}),
    }
    for telecast_id in _SELECTED_RR_IDS:
        url = f"https://ratingsreference.com/api/telecast/{telecast_id}.json"
        responses[url] = (200, json.dumps({"telecast": {"id": telecast_id}}).encode(), {})
    handle = mock_transport_factory(responses)
    cache = RawCache(vault_paths, _client(handle, fake_clock=fake_clock))
    collector = RatingsRefCollector(cache, vault_paths)

    collector.run(date(2025, 7, 1), date(2026, 6, 30), dry_run=False)
    first_request_count = len(handle.requests)

    second_summary = collector.run(date(2025, 7, 1), date(2026, 6, 30), dry_run=False)

    assert second_summary.cached == 3
    assert second_summary.fetched == 0
    assert len(handle.requests) == first_request_count
