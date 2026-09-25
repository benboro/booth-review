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

from booth_review.errors import (
    BudgetFloorError,
    FrozenSeasonError,
    MissingApiKeyError,
)
from booth_review.sources.cfbd.collector import CfbdCollector
from booth_review.sources.ratingsref.collector import SITEMAP_URL, RatingsRefCollector
from booth_review.sources.sports506.collector import WEEK_LABELS, Sports506Collector
from booth_review.transport.budget import CfbdBudget
from booth_review.transport.cache import RawCache
from booth_review.transport.client import PoliteClient

CFBD_BASE = "https://api.collegefootballdata.com"
FIXTURES_CFBD = Path(__file__).parent / "fixtures" / "cfbd"
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


def _cfbd_info_body(remaining: int) -> bytes:
    return json.dumps(
        {
            "patronLevel": "free",
            "tierName": "Free",
            "monthlyLimit": 1000,
            "remainingCalls": remaining,
            "usedCalls": 1000 - remaining,
            "resetAt": "2026-10-01T00:00:00.000Z",
        }
    ).encode()


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


# -- CfbdCollector --------------------------------------------------------------


def test_cfbd_plan_returns_six_requests_with_expected_endpoints_and_params(
    vault_paths, mock_transport_factory
) -> None:
    handle = mock_transport_factory({})
    budget = CfbdBudget(vault_paths.cfbd_ledger)
    cache = RawCache(vault_paths, _client(handle), guards=[budget])
    collector = CfbdCollector(cache, budget, "test-token")

    names = ["games", "media", "wp_pregame", "lines", "rankings", "teams_fbs"]
    requests = collector.plan(2025, names)

    assert len(requests) == 6
    assert [r.endpoint for r in requests] == [
        "/games",
        "/games/media",
        "/metrics/wp/pregame",
        "/lines",
        "/rankings",
        "/teams/fbs",
    ]
    assert all(r.url.startswith(CFBD_BASE) for r in requests)
    for r, name in zip(requests, names, strict=True):
        assert r.cache_path == f"cfbd/{name}/2025.json"

    for r in requests[:5]:
        assert ("seasonType", "both") in r.params
        assert ("year", "2025") in r.params
        assert "seasonType=both" in r.url
        assert "year=2025" in r.url

    assert requests[5].params == (("year", "2025"),)
    assert "seasonType" not in requests[5].url


def test_cfbd_plan_unknown_name_raises_value_error(vault_paths, mock_transport_factory) -> None:
    handle = mock_transport_factory({})
    budget = CfbdBudget(vault_paths.cfbd_ledger)
    cache = RawCache(vault_paths, _client(handle), guards=[budget])
    collector = CfbdCollector(cache, budget, "test-token")

    with pytest.raises(ValueError):
        collector.plan(2025, ["games", "plays"])
    assert handle.requests == []


def test_cfbd_run_dry_run_reports_cfbd_calls_as_uncached_count_even_without_token(
    vault_paths, mock_transport_factory
) -> None:
    handle = mock_transport_factory({})
    budget = CfbdBudget(vault_paths.cfbd_ledger)
    cache = RawCache(vault_paths, _client(handle), guards=[budget])
    collector = CfbdCollector(cache, budget, None)

    summary = collector.run(2025, ["games", "media"], dry_run=True)

    assert summary.cfbd_calls == 2
    assert summary.planned == 2
    assert handle.requests == []


def test_cfbd_run_without_token_raises_missing_api_key_before_any_request(
    vault_paths, mock_transport_factory
) -> None:
    handle = mock_transport_factory({})
    budget = CfbdBudget(vault_paths.cfbd_ledger)
    cache = RawCache(vault_paths, _client(handle), guards=[budget])
    collector = CfbdCollector(cache, budget, None)

    with pytest.raises(MissingApiKeyError):
        collector.run(2025, ["games"], dry_run=False)
    assert handle.requests == []


def test_cfbd_run_fetches_all_six_with_bearer_token_and_none_on_robots(
    vault_paths, mock_transport_factory, fake_clock
) -> None:
    responses = {
        "https://api.collegefootballdata.com/robots.txt": (404, b"nf", {}),
        "https://api.collegefootballdata.com/info": (200, _cfbd_info_body(600), {}),
        "https://api.collegefootballdata.com/games?seasonType=both&year=2025": (200, b"[]", {}),
        "https://api.collegefootballdata.com/games/media?seasonType=both&year=2025": (
            200,
            b"[]",
            {},
        ),
        "https://api.collegefootballdata.com/metrics/wp/pregame?seasonType=both&year=2025": (
            200,
            b"[]",
            {},
        ),
        "https://api.collegefootballdata.com/lines?seasonType=both&year=2025": (200, b"[]", {}),
        "https://api.collegefootballdata.com/rankings?seasonType=both&year=2025": (200, b"[]", {}),
        "https://api.collegefootballdata.com/teams/fbs?year=2025": (200, b"[]", {}),
    }
    handle = mock_transport_factory(responses)
    budget = CfbdBudget(vault_paths.cfbd_ledger)
    cache = RawCache(vault_paths, _client(handle, fake_clock=fake_clock), guards=[budget])
    collector = CfbdCollector(cache, budget, "test-token")

    collector.info()  # seeds the budget's remaining-calls knowledge for this month

    summary = collector.run(
        2025,
        ["games", "media", "wp_pregame", "lines", "rankings", "teams_fbs"],
        dry_run=False,
    )

    assert summary.fetched == 6

    for req in handle.requests:
        if req.url.endswith("/info") or req.url.endswith("robots.txt"):
            continue
        assert req.headers.get("authorization") == "Bearer test-token"
    robots_request = next(r for r in handle.requests if r.url.endswith("robots.txt"))
    assert "authorization" not in robots_request.headers

    ledger_lines = [
        json.loads(line)
        for line in vault_paths.cfbd_ledger.read_text(encoding="utf-8").splitlines()
    ]
    data_call_lines = [
        line
        for line in ledger_lines
        if line.get("event") == "call" and line.get("endpoint") != "/info"
    ]
    assert len(data_call_lines) == 6


def test_cfbd_run_below_floor_raises_budget_floor_error_and_sends_no_data_request(
    vault_paths, mock_transport_factory, fake_clock
) -> None:
    responses = {
        "https://api.collegefootballdata.com/robots.txt": (404, b"nf", {}),
        "https://api.collegefootballdata.com/info": (200, _cfbd_info_body(250), {}),
        "https://api.collegefootballdata.com/games?seasonType=both&year=2025": (200, b"[]", {}),
    }
    handle = mock_transport_factory(responses)
    budget = CfbdBudget(vault_paths.cfbd_ledger, floor=250)
    cache = RawCache(vault_paths, _client(handle, fake_clock=fake_clock), guards=[budget])
    collector = CfbdCollector(cache, budget, "test-token")

    collector.info()

    with pytest.raises(BudgetFloorError):
        collector.run(2025, ["games"], dry_run=False)

    data_requests = [
        r for r in handle.requests if r.url.endswith("/games?seasonType=both&year=2025")
    ]
    assert data_requests == []


def test_cfbd_info_returns_snapshot_and_writes_unique_path_each_call(
    vault_paths, mock_transport_factory, fake_clock
) -> None:
    info_body = (FIXTURES_CFBD / "info.json").read_bytes()
    responses = {
        "https://api.collegefootballdata.com/robots.txt": (404, b"nf", {}),
        "https://api.collegefootballdata.com/info": (200, info_body, {}),
    }
    handle = mock_transport_factory(responses)
    budget = CfbdBudget(vault_paths.cfbd_ledger)
    cache = RawCache(vault_paths, _client(handle, fake_clock=fake_clock), guards=[budget])
    collector = CfbdCollector(cache, budget, "test-token")

    snapshot = collector.info()
    assert snapshot.remaining_calls == 743

    info_dir = vault_paths.raw / "cfbd" / "info"
    assert len(list(info_dir.glob("*.json"))) == 1

    collector.info()
    assert len(list(info_dir.glob("*.json"))) == 2


def test_cfbd_probe_info_cost_returns_false_when_remaining_equal(
    vault_paths, mock_transport_factory, fake_clock
) -> None:
    responses = {
        "https://api.collegefootballdata.com/robots.txt": (404, b"nf", {}),
        "https://api.collegefootballdata.com/info": (200, _cfbd_info_body(600), {}),
    }
    handle = mock_transport_factory(responses)
    budget = CfbdBudget(vault_paths.cfbd_ledger)
    cache = RawCache(vault_paths, _client(handle, fake_clock=fake_clock), guards=[budget])
    collector = CfbdCollector(cache, budget, "test-token")

    result = collector.probe_info_cost()

    assert result is False
    ledger_lines = [
        json.loads(line)
        for line in vault_paths.cfbd_ledger.read_text(encoding="utf-8").splitlines()
    ]
    assert any(line.get("event") == "info_cost_probe" for line in ledger_lines)


def test_cfbd_bearer_token_never_appears_in_any_vault_file(
    vault_paths, mock_transport_factory, fake_clock
) -> None:
    responses = {
        "https://api.collegefootballdata.com/robots.txt": (404, b"nf", {}),
        "https://api.collegefootballdata.com/info": (200, _cfbd_info_body(600), {}),
        "https://api.collegefootballdata.com/games?seasonType=both&year=2025": (200, b"[]", {}),
    }
    handle = mock_transport_factory(responses)
    budget = CfbdBudget(vault_paths.cfbd_ledger)
    cache = RawCache(vault_paths, _client(handle, fake_clock=fake_clock), guards=[budget])
    collector = CfbdCollector(cache, budget, "test-token")

    collector.info()
    collector.run(2025, ["games"], dry_run=False)

    for path in vault_paths.vault.rglob("*"):
        if path.is_file():
            assert b"test-token" not in path.read_bytes()
