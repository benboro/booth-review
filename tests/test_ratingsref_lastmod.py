"""Tests for the Ratings Reference lastmod ledger (WR-02).

The legacy `ledger/rr_lastmod.json` snapshot is read but never rewritten;
new lastmods go to the append-only, union-merged `ledger/rr_lastmod.jsonl`.
All telecast ids are synthetic.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from booth_review.errors import VaultStateError
from booth_review.sources.ratingsref.collector import SITEMAP_URL, RatingsRefCollector
from booth_review.sources.ratingsref.lastmod import (
    append_failure,
    append_lastmod,
    lastmod_ledger_exists,
    load_failures,
    load_fetched_lastmods,
    load_lastmods,
)
from booth_review.sources.ratingsref.sitemap import SitemapEntry
from booth_review.transport.cache import RawCache
from booth_review.transport.client import PoliteClient


def _entry(telecast_id: str, lastmod: str) -> SitemapEntry:
    return SitemapEntry(
        telecast_id=telecast_id,
        record_url=f"https://ratingsreference.com/telecast/{telecast_id}",
        json_url=f"https://ratingsreference.com/api/telecast/{telecast_id}.json",
        event_date=datetime(2025, 9, 6, tzinfo=UTC).date(),
        season=2025,
        lastmod=lastmod,
    )


def _record_body(telecast_id: str) -> bytes:
    telecast = {"id": telecast_id, "event_date": "2025-09-06"}
    return json.dumps({"telecast": telecast}).encode()


def _log_line(telecast_id: str, lastmod: str, fetched_at: str) -> str:
    return json.dumps(
        {
            "event": "fetched",
            "telecast_id": telecast_id,
            "lastmod": lastmod,
            "fetched_at": fetched_at,
            "record_url": f"https://ratingsreference.com/telecast/{telecast_id}",
        }
    )


def test_no_files_means_no_ledger_and_empty_map(vault_paths) -> None:
    assert not lastmod_ledger_exists(vault_paths)
    assert load_lastmods(vault_paths) == {}


def test_legacy_json_alone_still_loads(vault_paths) -> None:
    vault_paths.rr_lastmod.write_text(
        json.dumps(
            {
                "cfb-a-b-2025-09-06": {
                    "lastmod": "2026-01-01T00:00:00+00:00",
                    "fetched_at": "2026-01-02T00:00:00Z",
                    "record_url": "https://ratingsreference.com/telecast/cfb-a-b-2025-09-06",
                }
            }
        ),
        encoding="utf-8",
    )
    assert lastmod_ledger_exists(vault_paths)
    loaded = load_lastmods(vault_paths)
    assert loaded["cfb-a-b-2025-09-06"]["lastmod"] == "2026-01-01T00:00:00+00:00"


def test_log_overrides_legacy_json_with_the_greater_lastmod(vault_paths) -> None:
    vault_paths.rr_lastmod.write_text(
        json.dumps(
            {
                "cfb-a-b-2025-09-06": {
                    "lastmod": "2026-01-01T00:00:00+00:00",
                    "fetched_at": "2026-01-02T00:00:00Z",
                    "record_url": "https://ratingsreference.com/telecast/cfb-a-b-2025-09-06",
                }
            }
        ),
        encoding="utf-8",
    )
    append_lastmod(
        vault_paths,
        _entry("cfb-a-b-2025-09-06", "2026-03-01T00:00:00+00:00"),
        fetched_at=datetime(2026, 3, 2, tzinfo=UTC),
    )
    append_lastmod(
        vault_paths,
        _entry("cfb-c-d-2025-09-13", "2026-03-05T00:00:00+00:00"),
        fetched_at=datetime(2026, 3, 6, tzinfo=UTC),
    )

    loaded = load_lastmods(vault_paths)
    assert loaded["cfb-a-b-2025-09-06"]["lastmod"] == "2026-03-01T00:00:00+00:00"
    assert loaded["cfb-c-d-2025-09-13"] == {
        "lastmod": "2026-03-05T00:00:00+00:00",
        "fetched_at": "2026-03-06T00:00:00.000000Z",
        "record_url": "https://ratingsreference.com/telecast/cfb-c-d-2025-09-13",
    }


def test_union_merged_log_gives_the_same_map_in_any_line_order(vault_paths) -> None:
    # A job line and a local line for the same record, plus one line each for
    # records only one side fetched, as a merge=union rebase could leave them.
    job_side = [
        _log_line("cfb-a-b-2025-09-06", "2026-02-01T00:00:00+00:00", "2026-02-02T00:00:00Z"),
        _log_line("cfb-e-f-2019-09-07", "2026-02-01T00:00:00+00:00", "2026-02-02T00:00:00Z"),
    ]
    local_side = [
        _log_line("cfb-a-b-2025-09-06", "2026-01-01T00:00:00+00:00", "2026-02-03T00:00:00Z"),
        _log_line("cfb-g-h-2014-09-06", "2026-01-01T00:00:00+00:00", "2026-02-03T00:00:00Z"),
    ]

    results = []
    for lines in (job_side + local_side, local_side + job_side):
        vault_paths.rr_lastmod_log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        results.append(load_lastmods(vault_paths))

    assert results[0] == results[1]
    assert set(results[0]) == {"cfb-a-b-2025-09-06", "cfb-e-f-2019-09-07", "cfb-g-h-2014-09-06"}
    assert results[0]["cfb-a-b-2025-09-06"]["lastmod"] == "2026-02-01T00:00:00+00:00"


def test_fetched_lastmods_follow_the_latest_fetch_not_the_greatest_lastmod(vault_paths) -> None:
    # The sitemap's lastmod moved backwards after a fetch at the greater value;
    # the record was then fetched again at the lower one.
    lines = [
        _log_line("cfb-a-b-2025-09-06", "2026-02-05T00:00:00+00:00", "2026-02-06T00:00:00Z"),
        _log_line("cfb-a-b-2025-09-06", "2026-02-03T00:00:00+00:00", "2026-02-07T00:00:00Z"),
    ]
    vault_paths.rr_lastmod_log.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert load_lastmods(vault_paths)["cfb-a-b-2025-09-06"]["lastmod"] == (
        "2026-02-05T00:00:00+00:00"
    )
    assert load_fetched_lastmods(vault_paths)["cfb-a-b-2025-09-06"]["lastmod"] == (
        "2026-02-03T00:00:00+00:00"
    )


def test_fetched_lastmods_give_the_same_map_in_any_line_order(vault_paths) -> None:
    # A lastmod that goes A, B, A: the latest fetch is the second A.
    lines = [
        _log_line("cfb-a-b-2025-09-06", "2026-02-01T00:00:00+00:00", "2026-02-02T00:00:00Z"),
        _log_line("cfb-a-b-2025-09-06", "2026-02-05T00:00:00+00:00", "2026-02-06T00:00:00Z"),
        _log_line("cfb-a-b-2025-09-06", "2026-02-01T00:00:00+00:00", "2026-02-09T00:00:00Z"),
    ]
    results = []
    for ordered in (lines, list(reversed(lines)), [lines[1], lines[2], lines[0]]):
        vault_paths.rr_lastmod_log.write_text("\n".join(ordered) + "\n", encoding="utf-8")
        results.append(load_fetched_lastmods(vault_paths))

    assert results[0] == results[1] == results[2]
    assert results[0]["cfb-a-b-2025-09-06"]["fetched_at"] == "2026-02-09T00:00:00Z"
    assert results[0]["cfb-a-b-2025-09-06"]["lastmod"] == "2026-02-01T00:00:00+00:00"


def test_fetched_lastmods_break_a_tie_between_two_spellings_of_one_instant(vault_paths) -> None:
    # Same fetch time, same instant, different text: refresh compares the text,
    # so the choice must not depend on which line comes first.
    lines = [
        _log_line("cfb-a-b-2025-09-06", "2026-02-01T00:00:00Z", "2026-02-02T00:00:00Z"),
        _log_line("cfb-a-b-2025-09-06", "2026-02-01T00:00:00+00:00", "2026-02-02T00:00:00Z"),
    ]
    results = []
    for ordered in (lines, list(reversed(lines))):
        vault_paths.rr_lastmod_log.write_text("\n".join(ordered) + "\n", encoding="utf-8")
        results.append(load_fetched_lastmods(vault_paths))

    assert results[0] == results[1]


def test_fetched_lastmods_read_the_legacy_json_and_the_log_together(vault_paths) -> None:
    vault_paths.rr_lastmod.write_text(
        json.dumps(
            {
                "cfb-a-b-2025-09-06": {
                    "lastmod": "2026-01-01T00:00:00+00:00",
                    "fetched_at": "2026-01-02T00:00:00Z",
                    "record_url": "https://ratingsreference.com/telecast/cfb-a-b-2025-09-06",
                },
                "cfb-c-d-2025-09-13": {
                    "lastmod": "2026-01-01T00:00:00+00:00",
                    "fetched_at": "2026-01-02T00:00:00Z",
                    "record_url": "https://ratingsreference.com/telecast/cfb-c-d-2025-09-13",
                },
            }
        ),
        encoding="utf-8",
    )
    append_lastmod(
        vault_paths,
        _entry("cfb-a-b-2025-09-06", "2025-12-01T00:00:00+00:00"),
        fetched_at=datetime(2026, 3, 2, tzinfo=UTC),
    )

    loaded = load_fetched_lastmods(vault_paths)
    assert loaded["cfb-a-b-2025-09-06"]["lastmod"] == "2025-12-01T00:00:00+00:00"
    assert loaded["cfb-c-d-2025-09-13"]["lastmod"] == "2026-01-01T00:00:00+00:00"


def test_corrupt_log_line_raises_vault_state_error(vault_paths) -> None:
    vault_paths.rr_lastmod_log.write_text("{not json\n", encoding="utf-8")
    with pytest.raises(VaultStateError):
        load_lastmods(vault_paths)


def test_refresh_appends_to_the_log_under_the_lock_and_never_rewrites_legacy_json(
    vault_paths, mock_transport_factory, fake_clock
) -> None:
    legacy = {
        "cfb-old-a-b-2025-09-06": {
            "lastmod": "2026-01-01T00:00:00+00:00",
            "fetched_at": "2026-01-02T00:00:00Z",
            "record_url": "https://ratingsreference.com/telecast/cfb-old-a-b-2025-09-06",
        }
    }
    vault_paths.rr_lastmod.write_text(json.dumps(legacy), encoding="utf-8")
    legacy_bytes = vault_paths.rr_lastmod.read_bytes()

    slugs = ["cfb-old-a-b-2025-09-06", "cfb-new-c-d-2025-09-13"]
    sitemap = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join(
            f"<url><loc>https://ratingsreference.com/telecast/{slug}</loc>"
            "<lastmod>2026-03-01T00:00:00+00:00</lastmod></url>\n"
            for slug in slugs
        )
        + "</urlset>\n"
    ).encode()
    responses = {
        "https://ratingsreference.com/robots.txt": (404, b"nf", {}),
        SITEMAP_URL: (200, sitemap, {}),
    }
    for slug in slugs:
        responses[f"https://ratingsreference.com/api/telecast/{slug}.json"] = (
            200,
            _record_body(slug),
            {},
        )
    handle = mock_transport_factory(responses)
    client = PoliteClient(transport=handle.transport, clock=fake_clock.now, sleep=fake_clock.sleep)

    lock_entries: list[int] = []

    @contextlib.contextmanager
    def _counting_lock() -> Iterator[None]:
        lock_entries.append(1)
        yield

    collector = RatingsRefCollector(RawCache(vault_paths, client), vault_paths, lock=_counting_lock)
    summary = collector.refresh(current_season=2025, dry_run=False)

    assert summary.fetched == 2
    assert len(lock_entries) == 2  # one lock hold per appended lastmod
    assert vault_paths.rr_lastmod.read_bytes() == legacy_bytes
    log_lines = vault_paths.rr_lastmod_log.read_text(encoding="utf-8").splitlines()
    assert len(log_lines) == 2
    loaded = load_lastmods(vault_paths)
    assert {entry["lastmod"] for entry in loaded.values()} == {"2026-03-01T00:00:00+00:00"}


def test_a_later_fetch_within_the_same_second_wins_the_fetched_lastmod(vault_paths) -> None:
    # Two fetches of one record inside one second: the later one fetched the
    # lower lastmod, so that is the value the record was last fetched at.
    entry_high = _entry("cfb-a-b-2025-09-06", "2026-02-05T00:00:00+00:00")
    entry_low = _entry("cfb-a-b-2025-09-06", "2026-02-03T00:00:00+00:00")
    append_lastmod(
        vault_paths, entry_high, fetched_at=datetime(2026, 3, 1, 12, 0, 0, 100_000, tzinfo=UTC)
    )
    append_lastmod(
        vault_paths, entry_low, fetched_at=datetime(2026, 3, 1, 12, 0, 0, 900_000, tzinfo=UTC)
    )

    lines = vault_paths.rr_lastmod_log.read_text(encoding="utf-8").splitlines()
    for ordered in (lines, list(reversed(lines))):
        vault_paths.rr_lastmod_log.write_text("\n".join(ordered) + "\n", encoding="utf-8")
        loaded = load_fetched_lastmods(vault_paths)["cfb-a-b-2025-09-06"]
        assert loaded["lastmod"] == "2026-02-03T00:00:00+00:00"


def _failed_line(telecast_id: str, lastmod: str, failed_at: str, status: int | None) -> str:
    return json.dumps(
        {
            "event": "failed",
            "telecast_id": telecast_id,
            "lastmod": lastmod,
            "failed_at": failed_at,
            "status": status,
        }
    )


def test_failures_in_the_same_second_do_not_depend_on_line_order(vault_paths) -> None:
    lines = [
        _failed_line(
            "cfb-a-b-2025-09-06", "2026-02-01T00:00:00+00:00", "2026-03-01T12:00:00Z", 404
        ),
        _failed_line(
            "cfb-a-b-2025-09-06", "2026-02-05T00:00:00+00:00", "2026-03-01T12:00:00Z", None
        ),
    ]
    results = []
    for ordered in (lines, list(reversed(lines))):
        vault_paths.rr_lastmod_log.write_text("\n".join(ordered) + "\n", encoding="utf-8")
        results.append(load_failures(vault_paths))

    assert results[0] == results[1]


def test_a_later_failure_within_the_same_second_wins(vault_paths) -> None:
    entry_old = _entry("cfb-a-b-2025-09-06", "2026-02-05T00:00:00+00:00")
    entry_new = _entry("cfb-a-b-2025-09-06", "2026-02-03T00:00:00+00:00")
    append_failure(
        vault_paths,
        entry_old,
        status=None,
        failed_at=datetime(2026, 3, 1, 12, 0, 0, 900_000, tzinfo=UTC),
    )
    append_failure(
        vault_paths,
        entry_new,
        status=None,
        failed_at=datetime(2026, 3, 1, 12, 0, 0, 100_000, tzinfo=UTC),
    )
    # The 0.9s line is the later failure even though it was written first.
    lines = vault_paths.rr_lastmod_log.read_text(encoding="utf-8").splitlines()
    for ordered in (lines, list(reversed(lines))):
        vault_paths.rr_lastmod_log.write_text("\n".join(ordered) + "\n", encoding="utf-8")
        assert (
            load_failures(vault_paths)["cfb-a-b-2025-09-06"].lastmod == "2026-02-05T00:00:00+00:00"
        )


def test_entries_that_tie_on_every_key_merge_the_same_in_any_order(vault_paths) -> None:
    # Same fetch time and lastmod; only record_url differs.
    def line(url: str) -> str:
        return json.dumps(
            {
                "event": "fetched",
                "telecast_id": "cfb-a-b-2025-09-06",
                "lastmod": "2026-02-01T00:00:00Z",
                "fetched_at": "2026-03-01T12:00:00.123456Z",
                "record_url": url,
            }
        )

    lines = [line("http://example.test/r"), line("https://example.test/r")]
    for loader in (load_fetched_lastmods, load_lastmods):
        results = []
        for ordered in (lines, list(reversed(lines))):
            vault_paths.rr_lastmod_log.write_text("\n".join(ordered) + "\n", encoding="utf-8")
            results.append(loader(vault_paths))
        assert results[0] == results[1]


def test_a_legacy_whole_second_fetch_does_not_outrank_a_later_fraction(vault_paths) -> None:
    # Two lines with one lastmod: the .5s fetch is later than the whole-second one,
    # though "Z" sorts after "." as text.
    lines = [
        _log_line("cfb-a-b-2025-09-06", "2026-02-01T00:00:00+00:00", "2026-03-01T12:00:00Z"),
        _log_line("cfb-a-b-2025-09-06", "2026-02-01T00:00:00+00:00", "2026-03-01T12:00:00.500000Z"),
    ]
    vault_paths.rr_lastmod_log.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert load_lastmods(vault_paths)["cfb-a-b-2025-09-06"]["fetched_at"] == (
        "2026-03-01T12:00:00.500000Z"
    )
