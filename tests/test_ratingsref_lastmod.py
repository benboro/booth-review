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
    append_lastmod,
    lastmod_ledger_exists,
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
        "fetched_at": "2026-03-06T00:00:00Z",
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
        responses[f"https://ratingsreference.com/api/telecast/{slug}.json"] = (200, b"{}", {})
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
