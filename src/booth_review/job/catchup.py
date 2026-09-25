"""ET schedule, vault-held job state, and the D-13 catch-up calculator.

The scheduled job fires Sunday 10:00 and Wednesday 20:00 America/New_York
(D-11), a schedule that must stay correct across the fall DST change. State
(`ledger/job_state.json`, D-13/discretion item) lives in the vault, never in
Actions cache or artifacts; a missing file means "first run", and a corrupt
one fails loudly (`VaultStateError`) rather than silently treating the vault
as empty. `missed_slots`/`catchup_window` let the job (Plan 06) know how many
scheduled runs it missed since its last success and how far back to collect,
proven here from backdated state with an explicitly injected `now`, never
the wall clock read directly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from booth_review.errors import VaultStateError
from booth_review.seasons import is_past_freeze_date, season_of
from booth_review.transport.cache import atomic_write_json

EASTERN = ZoneInfo("America/New_York")

# (weekday, hour) pairs in America/New_York local time, using Python's
# date.weekday() numbering (Monday=0 .. Sunday=6): Sunday 10:00 and
# Wednesday 20:00 (D-11).
SCHEDULE: tuple[tuple[int, int], ...] = ((6, 10), (2, 20))

Trigger = Literal["schedule", "manual"]

_STATUSES = frozenset({"ok", "attention", "failed"})
_TIME_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")


def _format_dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).strftime(_TIME_FMT)


def _parse_dt(data: dict[str, Any], key: str, *, path: Path) -> datetime | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise VaultStateError(f"invalid job state in {path}: {key} must be an ISO UTC string")
    try:
        return datetime.strptime(value, _TIME_FMT).replace(tzinfo=UTC)
    except ValueError as exc:
        raise VaultStateError(
            f"invalid job state in {path}: {key} is not a valid timestamp: {value!r}"
        ) from exc


@dataclass(frozen=True)
class JobState:
    """The job's persisted, vault-held state (`ledger/job_state.json`)."""

    season: int | None
    last_success_at: datetime | None
    last_attempt_at: datetime | None
    last_status: str | None
    """One of "ok", "attention", "failed", or None (never attempted)."""
    last_window_start: datetime | None


_EMPTY_STATE = JobState(
    season=None,
    last_success_at=None,
    last_attempt_at=None,
    last_status=None,
    last_window_start=None,
)


def load_state(path: Path) -> JobState:
    """Read `path` into a JobState. A missing file means "first run"."""
    if not path.is_file():
        return _EMPTY_STATE

    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise VaultStateError(f"could not load job state from {path}") from exc
    if not isinstance(data, dict):
        raise VaultStateError(f"invalid job state in {path}: expected an object")

    season = data.get("season")
    if season is not None and not isinstance(season, int):
        raise VaultStateError(f"invalid job state in {path}: season must be an int or null")

    last_status = data.get("last_status")
    if last_status is not None and last_status not in _STATUSES:
        raise VaultStateError(
            f"invalid job state in {path}: last_status must be one of {sorted(_STATUSES)}"
        )

    return JobState(
        season=season,
        last_success_at=_parse_dt(data, "last_success_at", path=path),
        last_attempt_at=_parse_dt(data, "last_attempt_at", path=path),
        last_status=last_status,
        last_window_start=_parse_dt(data, "last_window_start", path=path),
    )


def save_state(path: Path, state: JobState) -> None:
    """Write `state` to `path` atomically, schema-versioned."""
    payload: dict[str, Any] = {
        "version": 1,
        "season": state.season,
        "last_success_at": _format_dt(state.last_success_at),
        "last_attempt_at": _format_dt(state.last_attempt_at),
        "last_status": state.last_status,
        "last_window_start": _format_dt(state.last_window_start),
    }
    atomic_write_json(path, payload)


def scheduled_slots(start: datetime, end: datetime) -> list[datetime]:
    """Return every scheduled UTC slot in (start, end], sorted ascending.

    Both bounds must be timezone-aware. Slots are built in America/New_York
    local time (D-11) and converted to UTC, so this stays correct across the
    fall DST change without any UTC-offset arithmetic.
    """
    _require_aware(start, "start")
    _require_aware(end, "end")
    if end <= start:
        return []

    # A 2-day buffer on each side covers the ET/UTC offset near midnight, so
    # no candidate slot near the start/end boundary is ever missed by the
    # local-date iteration below.
    day = (start.astimezone(EASTERN) - timedelta(days=2)).date()
    last_day = (end.astimezone(EASTERN) + timedelta(days=2)).date()

    slots: list[datetime] = []
    while day <= last_day:
        weekday = day.weekday()
        for slot_weekday, slot_hour in SCHEDULE:
            if weekday != slot_weekday:
                continue
            local = datetime(day.year, day.month, day.day, slot_hour, 0, tzinfo=EASTERN)
            utc_slot = local.astimezone(UTC)
            if start < utc_slot <= end:
                slots.append(utc_slot)
        day += timedelta(days=1)

    slots.sort()
    return slots


def missed_slots(last_success: datetime | None, now: datetime, trigger: Trigger) -> int:
    """Count scheduled slots missed since `last_success`.

    `last_success=None` (first run) always reports 0 -- there is no prior
    success to measure a gap from; `catchup_window` handles the first-run
    window separately. A `trigger="schedule"` run never counts its own slot
    as missed (it is the run currently servicing that slot); a
    `trigger="manual"` run has no "own slot", so nothing is subtracted.
    """
    _require_aware(now, "now")
    if last_success is None:
        return 0
    _require_aware(last_success, "last_success")

    slots = scheduled_slots(last_success, now)
    count = len(slots)
    if trigger == "schedule" and count >= 1:
        count -= 1
    return count


@dataclass(frozen=True)
class CatchupWindow:
    """The window a run should collect over, and how far behind it is."""

    start: datetime
    end: datetime
    missed_slots: int
    first_run: bool


def catchup_window(
    state: JobState, now: datetime, season: int, trigger: Trigger
) -> CatchupWindow:
    """Compute the window and missed-slot count a run should catch up on.

    With no prior success (`state.last_success_at is None`), the window
    starts at July 1 00:00 ET of `season` -- the season's own start -- since
    there is no last-success timestamp to start from. Otherwise it starts at
    `state.last_success_at`. The window always ends at `now`.
    """
    _require_aware(now, "now")
    last_success_at = state.last_success_at
    first_run = last_success_at is None
    start = (
        datetime(season, 7, 1, 0, 0, tzinfo=EASTERN).astimezone(UTC)
        if last_success_at is None
        else last_success_at
    )

    return CatchupWindow(
        start=start,
        end=now,
        missed_slots=missed_slots(state.last_success_at, now, trigger),
        first_run=first_run,
    )


def collectable_season(today: date) -> int | None:
    """The season a run started `today` should collect, or None off-season.

    `season_of(today)` unless that season is already past its freeze date
    (COLL-04) -- from Feb 15 through June 30, the just-ended season is
    reported for audit+freeze instead of collected as "current".
    """
    season = season_of(today)
    if is_past_freeze_date(season, today):
        return None
    return season
