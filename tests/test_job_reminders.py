"""Tests for job/reminders.py: the Phase 24 hand-save reminder slots (D-12 to D-17).

Synthetic CFBD games, nflverse schedule and saved pages only; the vault is a
throwaway tmp_path vault. The module never fetches, so no client exists here.
"""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from nfl_join_helpers import sched_row, schedule_csv

from booth_review.config import DataPaths
from booth_review.job import reminders
from booth_review.job.attention import (
    REMINDER_506_NFL_URL,
    REMINDER_AA_CFB_URL,
    REMINDER_AA_NFL_URL,
    REMINDER_ESPNPR_CFB_URL,
    REMINDER_FOX_CFB_URL,
    build_attention_body,
)
from booth_review.job.reminders import REMINDER_SLOTS, due_reminders, in_window
from booth_review.nfl.gaps import NflGaps
from booth_review.nfl.layout import NFLVERSE_SCHEDULES_PATH, nfl_506_path

ET = ZoneInfo("America/New_York")
_SRC = Path(__file__).parent.parent / "src" / "booth_review" / "job" / "reminders.py"

# Mon 17:30 EDT (before the Nov 1 change) and Mon 17:30 EST (after it).
MON_EDT = datetime(2026, 10, 26, 21, 30, tzinfo=UTC)
MON_EST = datetime(2026, 11, 2, 22, 30, tzinfo=UTC)
TUE_2130 = datetime(2026, 11, 3, 21, 30, tzinfo=ET)
FRI_1130 = datetime(2026, 11, 6, 11, 30, tzinfo=ET)
WED_1200 = datetime(2026, 10, 28, 12, 0, tzinfo=ET)
THU_1200 = datetime(2026, 10, 29, 12, 0, tzinfo=ET)


def _kinds(items: list) -> list[str]:
    return [item.kind for item in items]


def _write_cfb_games(paths: DataPaths) -> None:
    """Saturdays: week 1 Sep 5, week 9 Oct 31, week 10 Nov 7, week 11 Nov 14."""
    rows = [
        (1, 1, "2026-09-05T16:00:00Z"),
        (2, 9, "2026-10-31T16:00:00Z"),
        (3, 10, "2026-11-07T17:00:00Z"),
        (4, 11, "2026-11-14T17:00:00Z"),
    ]
    games = [
        {
            "id": game_id,
            "season": 2026,
            "week": week,
            "seasonType": "regular",
            "startDate": start,
            "homeTeam": "Home",
            "awayTeam": "Away",
        }
        for game_id, week, start in rows
    ]
    target = paths.raw / "cfbd" / "games" / "2026.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(json.dumps(games).encode())


def _save_espnpr(paths: DataPaths, label: str) -> None:
    page = paths.raw / "espnpr" / "2026" / "commentators" / f"wk-{label}.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_bytes(b"<html>synthetic</html>")


def _write_nfl_schedule(paths: DataPaths) -> None:
    """Weeks 1-9 on Sundays: week 1 Sep 6, week 8 Oct 25, week 9 Nov 1."""
    rows = []
    for week in range(1, 10):
        day = datetime(2026, 9, 6, tzinfo=ET) + timedelta(days=7 * (week - 1))
        rows.append(
            sched_row(f"g{week}", week, day.date().isoformat(), "AAA", "BBB", season="2026")
        )
    target = paths.raw / NFLVERSE_SCHEDULES_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(schedule_csv(rows))


def _save_506(paths: DataPaths, week: int) -> None:
    page = paths.raw / nfl_506_path(2026, week)
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_bytes(b"x")


def _gaps(missing: list[str], stale: list[str]) -> NflGaps:
    return NflGaps(season=2026, missing=missing, stale=stale, judged=8, saved_at_fallbacks=0)


# -- window arithmetic --------------------------------------------------------------


def test_slot_table_is_the_five_slots() -> None:
    spec = {k: (s.weekday, s.hour, s.minute) for k, s in REMINDER_SLOTS.items()}
    assert spec == {
        "espnpr": (0, 17, 30),
        "aa_cfb": (1, 21, 30),
        "aa_nfl": (2, 12, 0),
        "506_nfl": (3, 12, 0),
        "fox_cfb": (4, 11, 30),
    }
    assert all(s.grace == timedelta(hours=3) for s in REMINDER_SLOTS.values())


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (MON_EDT, True),  # 17:30 EDT
        (MON_EDT - timedelta(minutes=1), False),
        (MON_EDT + timedelta(hours=2, minutes=59), True),
        (MON_EDT + timedelta(hours=3), False),
        (MON_EST, True),  # 17:30 EST
        (MON_EST - timedelta(minutes=1), False),
        (MON_EST + timedelta(hours=3), False),
        (datetime(2026, 11, 3, 22, 30, tzinfo=UTC), False),  # Tuesday
    ],
)
def test_monday_window_across_dst(now: datetime, expected: bool) -> None:
    assert in_window(now, REMINDER_SLOTS["espnpr"]) is expected


def test_the_backup_slot_an_hour_later_is_still_inside_the_window() -> None:
    """The cron's 17,18 hour pair fires at 17:30 and 18:30 ET; both are due (WR-07 dedupes)."""
    for month, dom in ((10, 26), (11, 2)):
        for hour in (17, 18):
            assert in_window(
                datetime(2026, month, dom, hour, 30, tzinfo=ET), REMINDER_SLOTS["espnpr"]
            )


def test_tuesday_window_ends_at_local_midnight() -> None:
    slot = REMINDER_SLOTS["aa_cfb"]
    assert in_window(datetime(2026, 11, 3, 23, 59, tzinfo=ET), slot)
    assert not in_window(datetime(2026, 11, 4, 0, 10, tzinfo=ET), slot)


# -- CFB ----------------------------------------------------------------------------


def test_monday_espnpr_reminder_when_page_unsaved(vault_paths: DataPaths) -> None:
    _write_cfb_games(vault_paths)
    items = due_reminders(vault_paths, MON_EST)
    assert _kinds(items) == ["reminder_espnpr"]
    assert "week 10" in items[0].line
    assert "2026" in items[0].line
    assert REMINDER_ESPNPR_CFB_URL in items[0].line
    build_attention_body(items, generated_at=MON_EST)


def test_monday_espnpr_reminder_in_edt_names_week_nine(vault_paths: DataPaths) -> None:
    _write_cfb_games(vault_paths)
    items = due_reminders(vault_paths, MON_EDT)
    assert [item.kind for item in items] == ["reminder_espnpr"]
    assert "week 9" in items[0].line


def test_monday_reminder_stops_once_the_page_is_saved(vault_paths: DataPaths) -> None:
    _write_cfb_games(vault_paths)
    _save_espnpr(vault_paths, "10")
    assert due_reminders(vault_paths, MON_EST) == []


def test_tuesday_aa_and_friday_fox_have_no_saved_check(vault_paths: DataPaths) -> None:
    _write_cfb_games(vault_paths)
    _save_espnpr(vault_paths, "10")
    tue = due_reminders(vault_paths, TUE_2130)
    assert _kinds(tue) == ["reminder_aa_cfb"]
    assert REMINDER_AA_CFB_URL in tue[0].line
    assert "week 10" in tue[0].line
    fri = due_reminders(vault_paths, FRI_1130)
    assert _kinds(fri) == ["reminder_fox_cfb"]
    assert REMINDER_FOX_CFB_URL in fri[0].line
    build_attention_body([*tue, *fri], generated_at=FRI_1130)


def test_outside_every_window_nothing_is_due(vault_paths: DataPaths) -> None:
    _write_cfb_games(vault_paths)
    _write_nfl_schedule(vault_paths)
    assert due_reminders(vault_paths, datetime(2026, 11, 4, 15, 0, tzinfo=ET)) == []  # Wed 15:00


def test_no_games_file_or_no_current_week_means_no_cfb_items(vault_paths: DataPaths) -> None:
    assert due_reminders(vault_paths, MON_EST) == []
    _write_cfb_games(vault_paths)
    bowl = datetime(2026, 12, 21, 17, 30, tzinfo=ET)  # a Monday after the last numbered week
    assert due_reminders(vault_paths, bowl) == []


def test_unreadable_games_file_means_no_cfb_items(vault_paths: DataPaths) -> None:
    target = vault_paths.raw / "cfbd" / "games" / "2026.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"not json")
    assert due_reminders(vault_paths, MON_EST) == []


def test_off_season_means_no_cfb_items(vault_paths: DataPaths) -> None:
    _write_cfb_games(vault_paths)
    assert due_reminders(vault_paths, datetime(2027, 3, 1, 17, 30, tzinfo=ET)) == []


# -- NFL ----------------------------------------------------------------------------


def test_wednesday_aa_nfl_reminder_names_the_current_week(vault_paths: DataPaths) -> None:
    _write_nfl_schedule(vault_paths)
    items = due_reminders(vault_paths, WED_1200)
    assert _kinds(items) == ["reminder_aa_nfl"]
    assert "nfl week 9" in items[0].line
    assert REMINDER_AA_NFL_URL in items[0].line
    build_attention_body(items, generated_at=WED_1200)


def test_nfl_needs_the_schedule_a_season_and_a_regular_season_week(
    vault_paths: DataPaths,
) -> None:
    assert due_reminders(vault_paths, WED_1200) == []  # no schedule file
    _write_nfl_schedule(vault_paths)
    assert due_reminders(vault_paths, datetime(2027, 3, 3, 12, 0, tzinfo=ET)) == []  # off-season


def test_thursday_lists_played_missing_and_stale_weeks_and_the_upcoming_page(
    vault_paths: DataPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_nfl_schedule(vault_paths)
    monkeypatch.setattr(reminders, "find_nfl_506_gaps", lambda *_: _gaps(["3"], ["4"]))
    items = due_reminders(vault_paths, THU_1200)
    assert _kinds(items) == [
        "reminder_506_nfl_played",
        "reminder_506_nfl_played",
        "reminder_506_nfl",
    ]
    assert "not saved for week 3" in items[0].line
    assert "saved before their games finished for week 4" in items[1].line
    assert "save the 506 nfl week 9 page" in items[2].line
    assert all(REMINDER_506_NFL_URL in item.line for item in items)
    build_attention_body(items, generated_at=THU_1200)


def test_thursday_upcoming_page_is_independent_of_played_gaps(
    vault_paths: DataPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_nfl_schedule(vault_paths)
    monkeypatch.setattr(reminders, "find_nfl_506_gaps", lambda *_: _gaps([], []))
    assert _kinds(due_reminders(vault_paths, THU_1200)) == ["reminder_506_nfl"]
    _save_506(vault_paths, 9)
    assert due_reminders(vault_paths, THU_1200) == []


def test_thursday_with_no_gap_report_has_no_played_lines(
    vault_paths: DataPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_nfl_schedule(vault_paths)
    monkeypatch.setattr(reminders, "find_nfl_506_gaps", lambda *_: None)
    _save_506(vault_paths, 9)
    assert due_reminders(vault_paths, THU_1200) == []


def test_thursday_uses_the_real_gap_report(vault_paths: DataPaths) -> None:
    """Nothing saved: every played week is missing; no stub in between."""
    _write_nfl_schedule(vault_paths)
    items = due_reminders(vault_paths, THU_1200)
    assert _kinds(items) == ["reminder_506_nfl_played", "reminder_506_nfl"]
    assert "weeks 1, 2, 3, 4, 5, 6, 7, 8" in items[0].line


# -- purity -------------------------------------------------------------------------


def test_the_module_imports_no_network_code() -> None:
    tree = ast.parse(_SRC.read_text(encoding="utf-8"))
    modules = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)] + [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    ]
    for module in modules:
        assert not module.startswith(("booth_review.transport", "booth_review.sources.base"))
        assert module.split(".")[0] not in {"httpx", "httpx2", "requests", "urllib"}


def test_a_reminder_run_writes_nothing_to_the_vault(vault_paths: DataPaths) -> None:
    _write_cfb_games(vault_paths)
    before = sorted(p for p in vault_paths.vault.rglob("*") if p.is_file())
    due_reminders(vault_paths, MON_EST)
    assert sorted(p for p in vault_paths.vault.rglob("*") if p.is_file()) == before


# -- guarded slots, season bounds, aware clock ------------------------------------------


def test_a_corrupt_506_manifest_skips_the_slot_instead_of_raising(vault_paths: DataPaths) -> None:
    _write_nfl_schedule(vault_paths)
    manifest = vault_paths.manifest
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text('{"truncated": \n', encoding="utf-8")
    items = due_reminders(vault_paths, THU_1200)  # must not raise
    assert "reminder_506_nfl_played" not in _kinds(items)


def test_a_failing_slot_does_not_take_the_other_slots_down(
    vault_paths: DataPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_nfl_schedule(vault_paths)

    def boom(*_args: object) -> NflGaps:
        raise OSError("disk")

    monkeypatch.setattr(reminders, "find_nfl_506_gaps", boom)
    assert _kinds(due_reminders(vault_paths, THU_1200)) == ["reminder_506_nfl"]


def test_nfl_reminders_are_quiet_in_july_before_week_one(vault_paths: DataPaths) -> None:
    _write_nfl_schedule(vault_paths)
    assert due_reminders(vault_paths, datetime(2026, 7, 15, 12, 0, tzinfo=ET)) == []  # Wed
    assert due_reminders(vault_paths, datetime(2026, 7, 16, 12, 0, tzinfo=ET)) == []  # Thu


def test_nfl_reminders_start_in_week_ones_monday_week(vault_paths: DataPaths) -> None:
    _write_nfl_schedule(vault_paths)  # week 1 is Sunday Sep 6, so its Monday is Aug 31
    assert due_reminders(vault_paths, datetime(2026, 8, 26, 12, 0, tzinfo=ET)) == []
    items = due_reminders(vault_paths, datetime(2026, 9, 2, 12, 0, tzinfo=ET))
    assert _kinds(items) == ["reminder_aa_nfl"]


def test_nfl_reminders_stop_once_the_last_week_is_played(vault_paths: DataPaths) -> None:
    _write_nfl_schedule(vault_paths)  # the schedule ends at week 9 (Sunday Nov 1)
    assert due_reminders(vault_paths, datetime(2027, 1, 6, 12, 0, tzinfo=ET)) == []  # Wed
    assert due_reminders(vault_paths, datetime(2027, 1, 7, 12, 0, tzinfo=ET)) == []  # Thu


def test_a_naive_now_is_rejected(vault_paths: DataPaths) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        due_reminders(vault_paths, datetime(2026, 10, 29, 12, 0))  # noqa: DTZ001
