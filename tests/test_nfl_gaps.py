"""Tests for nfl/gaps.py, nfl/seasons.py and the NFL attention constructors (synthetic data)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from nfl_join_helpers import sched_row, schedule_csv

from booth_review.config import DataPaths
from booth_review.job import attention as a
from booth_review.job.attention import build_attention_body
from booth_review.nfl.gaps import find_nfl_506_gaps
from booth_review.nfl.layout import NFLVERSE_SCHEDULES_PATH, nfl_506_path
from booth_review.nfl.seasons import NFL_FREEZE_MONTH_DAY, nfl_collectable_season, nfl_freeze_date
from booth_review.transport.cache import Manifest, ManifestEntry

_FMT = "%Y-%m-%dT%H:%M:%SZ"
_NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


def test_freeze_date_and_collectable_season() -> None:
    assert NFL_FREEZE_MONTH_DAY == (3, 1)
    assert nfl_freeze_date(2026) == date(2027, 3, 1)
    assert nfl_collectable_season(date(2027, 2, 14)) == 2026
    assert nfl_collectable_season(date(2027, 2, 28)) == 2026
    assert nfl_collectable_season(date(2027, 3, 1)) is None
    assert nfl_collectable_season(date(2027, 6, 30)) is None
    assert nfl_collectable_season(date(2026, 7, 15)) == 2026
    assert nfl_collectable_season(date(2026, 9, 20)) == 2026


def _write_schedule(paths: DataPaths) -> None:
    rows = [
        sched_row("a", 1, "2026-09-06", "AAA", "BBB", season="2026"),
        sched_row("b", 2, "2026-09-13", "AAA", "BBB", season="2026"),
        sched_row("c", 3, "2026-09-27", "AAA", "BBB", season="2026"),
        sched_row("p", 19, "2027-01-10", "AAA", "BBB", season="2026", game_type="WC"),
    ]
    target = paths.raw / NFLVERSE_SCHEDULES_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(schedule_csv(rows))


def _page(paths: DataPaths, week: int, *, fetched: datetime, saved: datetime | None) -> None:
    rel = nfl_506_path(2026, week)
    (paths.raw / rel).parent.mkdir(parents=True, exist_ok=True)
    (paths.raw / rel).write_bytes(b"x")
    url = f"https://example.invalid/{week}"
    Manifest(paths.manifest).append(
        ManifestEntry(
            url=url,
            source="nfl_sports506",
            season=2026,
            kind="page",
            fetched_at=fetched.strftime(_FMT),
            status=200,
            etag=None,
            last_modified=None,
            sha256="x" * 8,
            path=rel,
            bytes=1,
            final_url=url,
            saved_at=saved.strftime(_FMT) if saved else None,
        )
    )


def test_schedule_absent_returns_none(vault_paths: DataPaths) -> None:
    assert find_nfl_506_gaps(vault_paths, 2026, _NOW) is None


def test_missing_week(vault_paths: DataPaths) -> None:
    _write_schedule(vault_paths)
    late = datetime(2026, 9, 20, tzinfo=UTC)
    _page(vault_paths, 1, fetched=late, saved=late)
    gaps = find_nfl_506_gaps(vault_paths, 2026, _NOW)
    assert gaps is not None
    assert gaps.missing == ["2"]
    assert gaps.stale == []
    assert gaps.judged == 2  # week 3 not played yet, playoffs never judged


def test_stale_by_saved_at(vault_paths: DataPaths) -> None:
    _write_schedule(vault_paths)
    ok = datetime(2026, 9, 20, tzinfo=UTC)
    early = datetime(2026, 9, 13, 17, 0, tzinfo=UTC)  # before week 2 ends
    _page(vault_paths, 1, fetched=ok, saved=ok)
    _page(vault_paths, 2, fetched=ok, saved=early)  # import time is late, save time early
    gaps = find_nfl_506_gaps(vault_paths, 2026, _NOW)
    assert gaps is not None
    assert gaps.stale == ["2"]
    assert gaps.missing == []
    assert gaps.saved_at_fallbacks == 0


def test_fetched_at_fallback_is_counted(vault_paths: DataPaths) -> None:
    _write_schedule(vault_paths)
    ok = datetime(2026, 9, 20, tzinfo=UTC)
    _page(vault_paths, 1, fetched=ok, saved=ok)
    _page(vault_paths, 2, fetched=ok - timedelta(days=20), saved=None)
    gaps = find_nfl_506_gaps(vault_paths, 2026, _NOW)
    assert gaps is not None
    assert gaps.stale == ["2"]
    assert gaps.saved_at_fallbacks == 1


def test_nfl_attention_lines_pass_whitelist() -> None:
    items = [
        a.nfl_506_missing(2026, ["2", "3"]),
        a.nfl_506_stale(2026, ["4"]),
        a.nfl_rr_backlog(3, 100),
        a.nfl_season_past_freeze(2025, date(2026, 3, 1)),
        a.nfl_build_blocked(2),
        a.nfl_review_due(4),
        a.nfl_schedule_drift(1),
        *(
            a.step_failed(step, "ParseError")
            for step in (
                "nflverse",
                "nfl_rr",
                "nfl_wikipedia",
                "nfl_gaps",
                "nfl_build",
                "nfl_freeze",
            )
        ),
    ]
    body = build_attention_body(items, generated_at=_NOW)
    assert body is not None
    assert "nfl 506 pages missing for 2026: weeks 2, 3" in body
    assert all(i.severity == "attention" for i in items)


@pytest.mark.parametrize("label", ["B", "19", "0"])
def test_nfl_labels_validated(label: str) -> None:
    with pytest.raises(ValueError):
        a.nfl_506_missing(2026, [label])
    with pytest.raises(ValueError):
        a.nfl_506_stale(2026, [label])


def test_nfl_negative_counts_rejected() -> None:
    for call in (
        lambda: a.nfl_rr_backlog(-1, 1),
        lambda: a.nfl_build_blocked(-1),
        lambda: a.nfl_review_due(-1),
        lambda: a.nfl_schedule_drift(-1),
    ):
        with pytest.raises(ValueError):
            call()
