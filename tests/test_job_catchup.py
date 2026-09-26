"""Tests for job/catchup.py: ET schedule, job state, and D-13 catch-up.

Verified calendar facts used below: 2026-10-04, 2026-10-11, 2026-11-01 are
Sundays; 2026-10-07, 2026-10-14, 2026-10-28, 2026-11-04 are Wednesdays.
America/New_York is UTC-4 (EDT) through 2026-11-01 02:00 local, then UTC-5
(EST).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from booth_review.errors import VaultStateError
from booth_review.job.catchup import (
    EASTERN,
    JobState,
    catchup_window,
    collectable_season,
    is_due,
    load_state,
    missed_slots,
    save_state,
    scheduled_slots,
)

_EMPTY_STATE = JobState(
    season=None,
    last_success_at=None,
    last_attempt_at=None,
    last_status=None,
    last_window_start=None,
)


def _state_with_last_success(last_success: datetime) -> JobState:
    return JobState(
        season=2026,
        last_success_at=last_success,
        last_attempt_at=last_success,
        last_status="ok",
        last_window_start=None,
    )


# -- scheduled_slots --------------------------------------------------------


def test_scheduled_slots_dst_transition_pair() -> None:
    start = datetime(2026, 10, 25, 0, 0, tzinfo=UTC)
    end = datetime(2026, 11, 2, 0, 0, tzinfo=UTC)
    slots = scheduled_slots(start, end)
    # Wed 2026-10-28 20:00 ET, still EDT (UTC-4)
    assert datetime(2026, 10, 29, 0, 0, tzinfo=UTC) in slots
    # Sun 2026-11-01 10:00 ET, now EST (UTC-5)
    assert datetime(2026, 11, 1, 15, 0, tzinfo=UTC) in slots


def test_scheduled_slots_is_half_open_start_exclusive_end_inclusive() -> None:
    slot = datetime(2026, 11, 1, 15, 0, tzinfo=UTC)
    # start == the slot itself: excluded (start exclusive), and end == start
    # means an empty window regardless.
    assert scheduled_slots(slot, slot) == []
    # end == the slot itself: included (end inclusive)
    before = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)
    assert slot in scheduled_slots(before, slot)


def test_scheduled_slots_sorted_ascending() -> None:
    start = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    end = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    slots = scheduled_slots(start, end)
    assert slots == sorted(slots)
    assert len(slots) >= 2


def test_scheduled_slots_empty_when_end_before_start() -> None:
    start = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    end = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    assert scheduled_slots(start, end) == []


def test_scheduled_slots_rejects_naive_datetimes() -> None:
    aware = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    naive = datetime(2026, 10, 1, 0, 0)  # noqa: DTZ001
    with pytest.raises(ValueError, match="timezone-aware"):
        scheduled_slots(naive, aware)
    with pytest.raises(ValueError, match="timezone-aware"):
        scheduled_slots(aware, naive)


# -- missed_slots (D-13) ------------------------------------------------------


def test_missed_slots_schedule_trigger_excludes_own_slot() -> None:
    last_success = datetime(2026, 10, 4, 14, 5, tzinfo=UTC)
    now = datetime(2026, 10, 15, 0, 10, tzinfo=UTC)
    assert missed_slots(last_success, now, "schedule") == 2


def test_missed_slots_manual_trigger_counts_every_slot() -> None:
    last_success = datetime(2026, 10, 4, 14, 5, tzinfo=UTC)
    now = datetime(2026, 10, 15, 0, 10, tzinfo=UTC)
    assert missed_slots(last_success, now, "manual") == 3


def test_missed_slots_first_run_is_zero() -> None:
    now = datetime(2026, 10, 15, 0, 10, tzinfo=UTC)
    assert missed_slots(None, now, "schedule") == 0
    assert missed_slots(None, now, "manual") == 0


def test_missed_slots_rejects_naive_datetimes() -> None:
    aware = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    naive = datetime(2026, 10, 1, 0, 0)  # noqa: DTZ001
    with pytest.raises(ValueError, match="timezone-aware"):
        missed_slots(naive, aware, "schedule")
    with pytest.raises(ValueError, match="timezone-aware"):
        missed_slots(aware, naive, "schedule")


# -- catchup_window ------------------------------------------------------------


def test_catchup_window_first_run_starts_at_season_july_first_et() -> None:
    state = JobState(
        season=None,
        last_success_at=None,
        last_attempt_at=None,
        last_status=None,
        last_window_start=None,
    )
    now = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    window = catchup_window(state, now, 2026, "schedule")
    assert window.first_run is True
    assert window.missed_slots == 0
    assert window.end == now
    expected_start = datetime(2026, 7, 1, 0, 0, tzinfo=EASTERN).astimezone(UTC)
    assert window.start == expected_start


def test_catchup_window_with_prior_success_starts_there() -> None:
    last_success = datetime(2026, 10, 4, 14, 5, tzinfo=UTC)
    state = JobState(
        season=2026,
        last_success_at=last_success,
        last_attempt_at=last_success,
        last_status="ok",
        last_window_start=None,
    )
    now = datetime(2026, 10, 15, 0, 10, tzinfo=UTC)
    window = catchup_window(state, now, 2026, "schedule")
    assert window.first_run is False
    assert window.start == last_success
    assert window.end == now
    assert window.missed_slots == 2


def test_catchup_window_rejects_naive_now() -> None:
    state = JobState(
        season=None,
        last_success_at=None,
        last_attempt_at=None,
        last_status=None,
        last_window_start=None,
    )
    naive_now = datetime(2026, 10, 1, 0, 0)  # noqa: DTZ001
    with pytest.raises(ValueError, match="timezone-aware"):
        catchup_window(state, naive_now, 2026, "schedule")


# -- load_state / save_state ---------------------------------------------------


def test_load_state_missing_file_returns_empty_state(tmp_path: Path) -> None:
    state = load_state(tmp_path / "job_state.json")
    assert state == JobState(
        season=None,
        last_success_at=None,
        last_attempt_at=None,
        last_status=None,
        last_window_start=None,
    )


def test_load_state_invalid_json_raises(tmp_path: Path) -> None:
    path = tmp_path / "job_state.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(VaultStateError):
        load_state(path)


def test_load_state_wrong_type_raises(tmp_path: Path) -> None:
    path = tmp_path / "job_state.json"
    path.write_text('{"season": "2026"}', encoding="utf-8")
    with pytest.raises(VaultStateError):
        load_state(path)


def test_load_state_bad_status_raises(tmp_path: Path) -> None:
    path = tmp_path / "job_state.json"
    path.write_text('{"last_status": "not-a-status"}', encoding="utf-8")
    with pytest.raises(VaultStateError):
        load_state(path)


def test_load_state_bad_timestamp_raises(tmp_path: Path) -> None:
    path = tmp_path / "job_state.json"
    path.write_text('{"last_success_at": "not-a-timestamp"}', encoding="utf-8")
    with pytest.raises(VaultStateError):
        load_state(path)


def test_save_state_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "ledger" / "job_state.json"
    state = JobState(
        season=2026,
        last_success_at=datetime(2026, 10, 14, 0, 0, tzinfo=UTC),
        last_attempt_at=datetime(2026, 10, 14, 0, 0, tzinfo=UTC),
        last_status="ok",
        last_window_start=datetime(2026, 10, 11, 14, 0, tzinfo=UTC),
    )
    save_state(path, state)
    assert load_state(path) == state


def test_save_state_writes_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "job_state.json"
    state = JobState(
        season=None,
        last_success_at=None,
        last_attempt_at=None,
        last_status=None,
        last_window_start=None,
    )
    save_state(path, state)
    assert '"version": 1' in path.read_text(encoding="utf-8")


# -- collectable_season (COLL-04) ----------------------------------------------


def test_collectable_season_mid_season() -> None:
    assert collectable_season(date(2026, 10, 1)) == 2026


def test_collectable_season_past_freeze_date_is_none() -> None:
    assert collectable_season(date(2027, 2, 15)) is None


def test_collectable_season_new_season_starts_july() -> None:
    assert collectable_season(date(2027, 7, 1)) == 2027


# -- is_due (backup-slot no-op) -------------------------------------------------


def test_is_due_manual_trigger_is_always_due() -> None:
    last_success = datetime(2026, 10, 29, 0, 0, tzinfo=UTC)  # Wed 2026-10-28 20:00 ET slot
    now = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)  # Friday, no main slot since
    state = _state_with_last_success(last_success)
    assert is_due(state, now, "manual") is True


def test_is_due_first_run_no_state_is_always_due() -> None:
    now = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
    assert is_due(_EMPTY_STATE, now, "schedule") is True
    assert is_due(_EMPTY_STATE, now, "manual") is True


def test_is_due_schedule_trigger_false_with_no_main_slot_since_last_success() -> None:
    last_success = datetime(2026, 10, 29, 0, 0, tzinfo=UTC)  # Wed 2026-10-28 20:00 ET slot
    now = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)  # Friday -- a backup slot, nothing due
    state = _state_with_last_success(last_success)
    assert is_due(state, now, "schedule") is False


def test_is_due_schedule_trigger_true_with_a_main_slot_since_last_success() -> None:
    last_success = datetime(2026, 10, 4, 14, 5, tzinfo=UTC)
    now = datetime(2026, 10, 15, 0, 10, tzinfo=UTC)
    state = _state_with_last_success(last_success)
    assert is_due(state, now, "schedule") is True


def test_is_due_across_dst_boundary_false_before_the_next_main_slot() -> None:
    # Wed 2026-10-28 20:00 ET (still EDT, UTC-4) == 2026-10-29T00:00Z; the next
    # main slot is Sun 2026-11-01 10:00 ET (now EST, UTC-5) == 2026-11-01T15:00Z.
    last_success = datetime(2026, 10, 29, 0, 0, tzinfo=UTC)
    state = _state_with_last_success(last_success)
    just_before_next_slot = datetime(2026, 11, 1, 14, 59, tzinfo=UTC)
    assert is_due(state, just_before_next_slot, "schedule") is False


def test_is_due_across_dst_boundary_true_at_the_next_main_slot() -> None:
    last_success = datetime(2026, 10, 29, 0, 0, tzinfo=UTC)
    state = _state_with_last_success(last_success)
    at_next_slot = datetime(2026, 11, 1, 15, 0, tzinfo=UTC)
    assert is_due(state, at_next_slot, "schedule") is True
