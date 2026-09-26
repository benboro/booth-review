"""Offline tests for RatingsRefCollector.refresh (D-07/D-08/D-09).

No network: each test drives a real RawCache wrapping a PoliteClient built on
httpx2.MockTransport and the fake clock (FOUND-01, D-13, FOUND-03). Sitemap
XML is built in-test with plain string templates (lxml-free), matching the
shape of tests/fixtures/ratingsref/sitemap_synthetic.xml.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest

from booth_review.errors import VaultStateError
from booth_review.sources.ratingsref.collector import (
    FAILED_RETRY_AFTER,
    FIRST_SEASON,
    REFRESH_CAP_DEFAULT,
    SITEMAP_URL,
    RatingsRefCollector,
)
from booth_review.sources.ratingsref.lastmod import load_failures, load_lastmods
from booth_review.transport.cache import RawCache
from booth_review.transport.client import PoliteClient


def _client(handle, *, fake_clock=None) -> PoliteClient:
    kwargs: dict = {"transport": handle.transport}
    if fake_clock is not None:
        kwargs["clock"] = fake_clock.now
        kwargs["sleep"] = fake_clock.sleep
    else:
        kwargs["clock"] = lambda: 0.0
        kwargs["sleep"] = lambda seconds: None
    return PoliteClient(**kwargs)


def _sitemap_xml(entries: list[tuple[str, str]]) -> bytes:
    """Build sitemap XML from a list of (slug, lastmod) tuples, matching the
    shape of tests/fixtures/ratingsref/sitemap_synthetic.xml without lxml.
    """
    urls = "".join(
        f"<url><loc>https://ratingsreference.com/telecast/{slug}</loc>"
        f"<lastmod>{lastmod}</lastmod></url>\n"
        for slug, lastmod in entries
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}</urlset>\n"
    ).encode()


def _record_body(telecast_id: str) -> bytes:
    return json.dumps({"telecast": {"id": telecast_id}}).encode()


def _write_lastmod(vault_paths, data: dict[str, dict[str, str]]) -> None:
    vault_paths.rr_lastmod.write_text(json.dumps(data), encoding="utf-8")


def _telecast_url(slug: str) -> str:
    return f"https://ratingsreference.com/api/telecast/{slug}.json"


# -- qualifying set: new or advanced only ----------------------------------------------


def test_refresh_requests_only_new_or_advanced_entries(
    vault_paths, mock_transport_factory, fake_clock
) -> None:
    unchanged_slug = "cfb-team-a-team-b-2025-09-06"
    advanced_slug = "cfb-team-c-team-d-2025-09-13"
    new_slug = "cfb-team-e-team-f-2025-09-20"

    sitemap_xml = _sitemap_xml(
        [
            (unchanged_slug, "2026-01-01T00:00:00+00:00"),
            (advanced_slug, "2026-02-01T00:00:00+00:00"),
            (new_slug, "2026-03-01T00:00:00+00:00"),
        ]
    )
    _write_lastmod(
        vault_paths,
        {
            unchanged_slug: {
                "lastmod": "2026-01-01T00:00:00+00:00",
                "fetched_at": "2026-01-01T00:00:00Z",
                "record_url": f"https://ratingsreference.com/telecast/{unchanged_slug}",
            },
            advanced_slug: {
                "lastmod": "2025-12-01T00:00:00+00:00",  # stale: sitemap has a newer lastmod
                "fetched_at": "2025-12-01T00:00:00Z",
                "record_url": f"https://ratingsreference.com/telecast/{advanced_slug}",
            },
        },
    )
    responses = {
        "https://ratingsreference.com/robots.txt": (404, b"nf", {}),
        SITEMAP_URL: (200, sitemap_xml, {}),
        _telecast_url(advanced_slug): (200, _record_body(advanced_slug), {}),
        _telecast_url(new_slug): (200, _record_body(new_slug), {}),
    }
    handle = mock_transport_factory(responses)
    cache = RawCache(vault_paths, _client(handle, fake_clock=fake_clock))
    collector = RatingsRefCollector(cache, vault_paths)

    summary = collector.refresh(current_season=2025, dry_run=False)

    assert summary.qualifying == 2
    assert summary.new == 1
    assert summary.advanced == 1
    assert summary.selected == 2
    assert summary.fetched == 2
    assert summary.backlog == 0

    telecast_urls = {r.url for r in handle.requests if "/api/telecast/" in r.url}
    assert telecast_urls == {_telecast_url(advanced_slug), _telecast_url(new_slug)}

    lastmod_data = load_lastmods(vault_paths)
    assert lastmod_data[advanced_slug]["lastmod"] == "2026-02-01T00:00:00+00:00"
    assert lastmod_data[new_slug]["lastmod"] == "2026-03-01T00:00:00+00:00"
    # unchanged entry's lastmod record is untouched
    assert lastmod_data[unchanged_slug]["lastmod"] == "2026-01-01T00:00:00+00:00"


# -- frozen-season exemption and D-09 overwrite ------------------------------------------


def test_refresh_frozen_season_advanced_record_is_fetched_and_overwrites(
    vault_paths, mock_transport_factory, fake_clock
) -> None:
    slug = "cfb-team-a-team-b-2019-09-07"
    vault_paths.frozen.write_text(
        json.dumps({"sports506": [], "ratingsref": [2019], "cfbd": []}), encoding="utf-8"
    )

    cached_path = vault_paths.raw / "ratingsref" / "telecast" / "2019" / f"{slug}.json"
    cached_path.parent.mkdir(parents=True, exist_ok=True)
    cached_path.write_bytes(b'{"stale": true}')

    _write_lastmod(
        vault_paths,
        {
            slug: {
                "lastmod": "2025-01-01T00:00:00+00:00",
                "fetched_at": "2025-01-01T00:00:00Z",
                "record_url": f"https://ratingsreference.com/telecast/{slug}",
            }
        },
    )
    # Seed a manifest entry for this record, matching a real prior fetch, so
    # the refresh's overwrite can be seen as a *second* manifest line (D-09).
    vault_paths.manifest.parent.mkdir(parents=True, exist_ok=True)
    vault_paths.manifest.write_text(
        json.dumps(
            {
                "url": _telecast_url(slug),
                "source": "ratingsref",
                "season": 2019,
                "kind": "page",
                "fetched_at": "2025-01-01T00:00:00Z",
                "status": 200,
                "etag": None,
                "last_modified": None,
                "sha256": "x",
                "path": f"ratingsref/telecast/2019/{slug}.json",
                "bytes": 16,
                "final_url": _telecast_url(slug),
            }
        )
        + "\n",
        encoding="utf-8",
    )

    new_lastmod = "2026-02-01T00:00:00+00:00"
    sitemap_xml = _sitemap_xml([(slug, new_lastmod)])
    responses = {
        "https://ratingsreference.com/robots.txt": (404, b"nf", {}),
        SITEMAP_URL: (200, sitemap_xml, {}),
        _telecast_url(slug): (200, b'{"stale": false}', {}),
    }
    handle = mock_transport_factory(responses)
    cache = RawCache(vault_paths, _client(handle, fake_clock=fake_clock))
    collector = RatingsRefCollector(cache, vault_paths)

    summary = collector.refresh(current_season=2025, dry_run=False)

    assert summary.advanced == 1
    assert summary.fetched == 1
    assert cached_path.read_bytes() == b'{"stale": false}'

    manifest_lines = [
        json.loads(line) for line in vault_paths.manifest.read_text(encoding="utf-8").splitlines()
    ]
    telecast_lines = [line for line in manifest_lines if line["url"] == _telecast_url(slug)]
    assert len(telecast_lines) == 2

    lastmod_data = load_lastmods(vault_paths)
    assert lastmod_data[slug]["lastmod"] == new_lastmod


# -- missing ledger refuses the refresh ---------------------------------------------------


def test_refresh_missing_lastmod_ledger_raises_before_sitemap_fetch(
    vault_paths, mock_transport_factory
) -> None:
    assert not vault_paths.rr_lastmod.is_file()
    handle = mock_transport_factory({})
    cache = RawCache(vault_paths, _client(handle))
    collector = RatingsRefCollector(cache, vault_paths)

    with pytest.raises(VaultStateError):
        collector.refresh(current_season=2025, dry_run=False)

    assert handle.requests == []


# -- dry-run matches live plan counts ------------------------------------------------------


def test_refresh_dry_run_sends_nothing_and_matches_live_counts(
    vault_paths, mock_transport_factory, fake_clock
) -> None:
    advanced_slug = "cfb-team-c-team-d-2025-09-13"
    new_slug = "cfb-team-e-team-f-2025-09-20"
    sitemap_xml = _sitemap_xml(
        [
            (advanced_slug, "2026-02-01T00:00:00+00:00"),
            (new_slug, "2026-03-01T00:00:00+00:00"),
        ]
    )
    _write_lastmod(
        vault_paths,
        {
            advanced_slug: {
                "lastmod": "2025-12-01T00:00:00+00:00",
                "fetched_at": "2025-12-01T00:00:00Z",
                "record_url": f"https://ratingsreference.com/telecast/{advanced_slug}",
            }
        },
    )

    # Seed a cached sitemap file directly (as a prior live sitemap() call would
    # have written), so the dry-run path can find it without fetching.
    sitemap_dir = vault_paths.raw / "ratingsref" / "sitemap"
    sitemap_dir.mkdir(parents=True, exist_ok=True)
    (sitemap_dir / "2026-09-25.xml").write_bytes(sitemap_xml)

    handle_dry = mock_transport_factory({})
    cache_dry = RawCache(vault_paths, _client(handle_dry, fake_clock=fake_clock))
    collector_dry = RatingsRefCollector(cache_dry, vault_paths)

    dry_summary = collector_dry.refresh(current_season=2025, dry_run=True)

    assert handle_dry.requests == []
    assert dry_summary.qualifying == 2
    assert dry_summary.new == 1
    assert dry_summary.advanced == 1
    assert dry_summary.selected == 2
    assert dry_summary.backlog == 0

    responses = {
        "https://ratingsreference.com/robots.txt": (404, b"nf", {}),
        SITEMAP_URL: (200, sitemap_xml, {}),
        _telecast_url(advanced_slug): (200, _record_body(advanced_slug), {}),
        _telecast_url(new_slug): (200, _record_body(new_slug), {}),
    }
    handle_live = mock_transport_factory(responses)
    cache_live = RawCache(vault_paths, _client(handle_live, fake_clock=fake_clock))
    collector_live = RatingsRefCollector(cache_live, vault_paths)

    live_summary = collector_live.refresh(current_season=2025, dry_run=False)

    assert live_summary.qualifying == dry_summary.qualifying
    assert live_summary.new == dry_summary.new
    assert live_summary.advanced == dry_summary.advanced
    assert live_summary.selected == dry_summary.selected
    assert live_summary.backlog == dry_summary.backlog


# -- cap, current-season exclusion, deterministic backlog ----------------------------------


def test_refresh_caps_advanced_records_excludes_current_season_new_reports_backlog(
    vault_paths, mock_transport_factory, fake_clock
) -> None:
    current_season = 2026
    start_date = date(2019, 8, 1)  # within the 2019 season window (2019-07-01..2020-06-30)

    advanced_entries: list[tuple[str, str]] = []
    known: dict[str, dict[str, str]] = {}
    for i in range(150):
        event_date = start_date + timedelta(days=i)
        slug = f"cfb-old-team-{i:03d}-{event_date.isoformat()}"
        new_lastmod = (date(2026, 1, 1) + timedelta(days=i)).isoformat() + "T00:00:00+00:00"
        advanced_entries.append((slug, new_lastmod))
        known[slug] = {
            "lastmod": "2020-01-01T00:00:00+00:00",  # older than every sitemap value above
            "fetched_at": "2020-01-01T00:00:00Z",
            "record_url": f"https://ratingsreference.com/telecast/{slug}",
        }
    _write_lastmod(vault_paths, known)

    new_entries: list[tuple[str, str]] = []
    for i in range(5):
        event_date = date(2026, 9, 1) + timedelta(days=i)
        slug = f"cfb-new-team-{i:03d}-{event_date.isoformat()}"
        new_entries.append((slug, "2026-09-25T00:00:00+00:00"))

    sitemap_xml = _sitemap_xml(advanced_entries + new_entries)

    # No capped current-season entries here, so the order is (lastmod,
    # telecast_id) ascending: capped selection is i=0..99 of
    # the advanced (old-season) entries; i=100..149 are backlog.
    selected_advanced = advanced_entries[:100]
    backlog_advanced = advanced_entries[100:]

    responses = {
        "https://ratingsreference.com/robots.txt": (404, b"nf", {}),
        SITEMAP_URL: (200, sitemap_xml, {}),
    }
    for slug, _lastmod in selected_advanced:
        responses[_telecast_url(slug)] = (200, _record_body(slug), {})
    for slug, _lastmod in new_entries:
        responses[_telecast_url(slug)] = (200, _record_body(slug), {})

    handle = mock_transport_factory(responses)
    cache = RawCache(vault_paths, _client(handle, fake_clock=fake_clock))
    collector = RatingsRefCollector(cache, vault_paths)

    summary = collector.refresh(
        current_season=current_season, cap=REFRESH_CAP_DEFAULT, dry_run=False
    )

    assert summary.qualifying == 155
    assert summary.new == 5
    assert summary.advanced == 150
    assert summary.uncapped_current == 5
    assert summary.selected == 105
    assert summary.backlog == 50
    assert summary.fetched == 105

    telecast_urls = {r.url for r in handle.requests if "/api/telecast/" in r.url}
    assert len(telecast_urls) == 105
    assert telecast_urls == {_telecast_url(slug) for slug, _ in selected_advanced} | {
        _telecast_url(slug) for slug, _ in new_entries
    }
    # The first-sorted advanced entry (lowest lastmod) was fetched; the
    # last-sorted one (highest lastmod, backlog) was never requested.
    assert _telecast_url(selected_advanced[0][0]) in telecast_urls
    assert _telecast_url(backlog_advanced[-1][0]) not in telecast_urls


def test_refresh_current_season_advanced_records_come_before_the_historical_backlog(
    vault_paths, mock_transport_factory, fake_clock
) -> None:
    current_season = 2026

    old_entries: list[tuple[str, str]] = []
    known: dict[str, dict[str, str]] = {}
    for i in range(3):
        slug = f"cfb-old-team-{i:03d}-2019-09-{7 + i:02d}"
        old_entries.append((slug, f"2026-01-0{i + 1}T00:00:00+00:00"))
        known[slug] = {
            "lastmod": "2020-01-01T00:00:00+00:00",
            "fetched_at": "2020-01-01T00:00:00Z",
            "record_url": f"https://ratingsreference.com/telecast/{slug}",
        }
    # A current-season record RR revised: its newer lastmod would sort it last.
    current_slug = "cfb-cur-team-a-2026-09-12"
    known[current_slug] = {
        "lastmod": "2026-09-13T00:00:00+00:00",
        "fetched_at": "2026-09-13T00:00:00Z",
        "record_url": f"https://ratingsreference.com/telecast/{current_slug}",
    }
    _write_lastmod(vault_paths, known)

    sitemap_xml = _sitemap_xml([*old_entries, (current_slug, "2026-09-20T00:00:00+00:00")])
    responses = {
        "https://ratingsreference.com/robots.txt": (404, b"nf", {}),
        SITEMAP_URL: (200, sitemap_xml, {}),
        _telecast_url(current_slug): (200, _record_body(current_slug), {}),
        _telecast_url(old_entries[0][0]): (200, _record_body(old_entries[0][0]), {}),
    }
    handle = mock_transport_factory(responses)
    cache = RawCache(vault_paths, _client(handle, fake_clock=fake_clock))
    collector = RatingsRefCollector(cache, vault_paths)

    summary = collector.refresh(current_season=current_season, cap=2, dry_run=False)

    assert summary.advanced == 4
    assert summary.selected == 2
    assert summary.backlog == 2
    telecast_urls = [r.url for r in handle.requests if "/api/telecast/" in r.url]
    assert telecast_urls == [_telecast_url(current_slug), _telecast_url(old_entries[0][0])]


def test_refresh_failed_record_is_held_back_then_retried_last(
    vault_paths, mock_transport_factory, fake_clock
) -> None:
    _write_lastmod(vault_paths, {})
    bad = "cfb-gone-team-a-2019-09-07"  # listed in the sitemap, but its record 404s
    good_a = "cfb-old-team-b-2019-09-14"
    good_b = "cfb-old-team-c-2019-09-21"
    sitemap_xml = _sitemap_xml(
        [
            (bad, "2026-01-01T00:00:00+00:00"),  # oldest lastmod: head of the queue
            (good_a, "2026-01-02T00:00:00+00:00"),
            (good_b, "2026-01-03T00:00:00+00:00"),
        ]
    )
    responses = {
        "https://ratingsreference.com/robots.txt": (404, b"nf", {}),
        SITEMAP_URL: (200, sitemap_xml, {}),
        _telecast_url(bad): (404, b"not found", {}),
        _telecast_url(good_a): (200, _record_body(good_a), {}),
        _telecast_url(good_b): (200, _record_body(good_b), {}),
    }
    handle = mock_transport_factory(responses)
    cache = RawCache(vault_paths, _client(handle, fake_clock=fake_clock))
    clock = {"now": datetime(2026, 10, 4, 14, 5, tzinfo=UTC)}

    def _collector() -> RatingsRefCollector:
        return RatingsRefCollector(cache, vault_paths, now=lambda: clock["now"])

    def _telecast_requests() -> list[str]:
        return [r.url for r in handle.requests if "/api/telecast/" in r.url]

    # Run 1: the bad record heads the queue and fails; the failure is logged.
    first = _collector().refresh(current_season=2026, cap=1, dry_run=False)
    assert first.failed == 1
    assert _telecast_requests() == [_telecast_url(bad)]
    failures = load_failures(vault_paths)
    assert failures[bad].lastmod == "2026-01-01T00:00:00+00:00"
    assert failures[bad].status == 404

    # Run 2, three days later: the bad record is held back, so the cap goes to
    # the next record instead of the same 404.
    clock["now"] += timedelta(days=3)
    handle.requests.clear()
    second = _collector().refresh(current_season=2026, cap=1, dry_run=False)
    assert second.deferred_failed == 1
    assert second.selected == 1
    assert second.backlog == 1
    assert _telecast_requests() == [_telecast_url(good_a)]

    # Run 3, past the hold: the bad record is eligible again but sorts behind
    # every other candidate, so good_b goes first.
    clock["now"] += FAILED_RETRY_AFTER
    handle.requests.clear()
    third = _collector().refresh(current_season=2026, cap=1, dry_run=False)
    assert third.deferred_failed == 0
    assert third.backlog == 1
    assert _telecast_requests() == [_telecast_url(good_b)]


def test_refresh_failure_at_an_older_lastmod_does_not_hold_the_record_back(
    vault_paths, mock_transport_factory, fake_clock
) -> None:
    slug = "cfb-old-team-a-2019-09-07"
    _write_lastmod(vault_paths, {})
    vault_paths.rr_lastmod_log.write_text(
        json.dumps(
            {
                "event": "failed",
                "telecast_id": slug,
                "lastmod": "2025-12-01T00:00:00+00:00",  # RR has since changed the record
                "failed_at": "2026-10-03T00:00:00Z",
                "status": 404,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    responses = {
        "https://ratingsreference.com/robots.txt": (404, b"nf", {}),
        SITEMAP_URL: (200, _sitemap_xml([(slug, "2026-01-01T00:00:00+00:00")]), {}),
        _telecast_url(slug): (200, _record_body(slug), {}),
    }
    handle = mock_transport_factory(responses)
    cache = RawCache(vault_paths, _client(handle, fake_clock=fake_clock))
    collector = RatingsRefCollector(
        cache, vault_paths, now=lambda: datetime(2026, 10, 4, tzinfo=UTC)
    )

    summary = collector.refresh(current_season=2026, cap=10, dry_run=False)

    assert summary.deferred_failed == 0
    assert summary.fetched == 1


def test_refresh_default_cap_constant_is_100_and_first_season_2014() -> None:
    assert REFRESH_CAP_DEFAULT == 100
    assert FIRST_SEASON == 2014
