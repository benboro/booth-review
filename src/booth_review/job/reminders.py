"""Phase 24 hand-save reminders: which reminder lines are due at `now` (D-12 to D-17).

The user hand-saves ESPN Press Room, Awful Announcing, FOX and 506 pages. These
slots (Mon 17:30, Tue 21:30, Wed 12:00, Thu 12:00, Fri 11:30 ET) name the page
to save, with a fixed public link, as lines on the needs-attention issue.

D-15: this module only reads the vault (the CFBD games file, the nflverse
schedule, saved ESPN and 506 pages, and the 506 gap report). It sends no
request, imports no transport or collector, and writes nothing. The caller
decides what a due reminder does: a run with nothing else due posts it through
the comment-only path (no state, budget, build or deploy, D-16); a full or
schedule run adds the lines to its own attention items.

Each slot is a local America/New_York time plus a three hour window, so the
cron's backup entry an hour later (the "17,18" hour pair, in ET) is still
inside it and posts only if the first run's line did not already land (the
workflow's WR-07 compare). The window ends at local midnight at the latest.

Rules for the saved checks:
- ESPN: only while `raw/espnpr/<season>/commentators/wk-<label>.html` is absent.
- AA and FOX (CFB) and AA (NFL): no saved check exists, so the line is due
  whenever its window is open and a known week is current; the week label in
  the text makes the workflow's WR-07 compare post it once per week.
- 506 NFL (Thursday): every already-played week `find_nfl_506_gaps` reports
  missing or stale, plus the upcoming week's page while its file is absent.
  "Stale" means saved before the week's games finished, so it cannot be judged
  for an unplayed week; for the upcoming week only "missing" applies.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from booth_review.config import DataPaths
from booth_review.errors import ParseError
from booth_review.job.attention import (
    AttentionItem,
    reminder_506_nfl,
    reminder_506_nfl_played,
    reminder_aa_cfb,
    reminder_aa_nfl,
    reminder_espnpr,
    reminder_fox_cfb,
)
from booth_review.job.catchup import collectable_season
from booth_review.job.gaps_espnpr import espnpr_page_week, find_espnpr_gap
from booth_review.nfl.gaps import find_nfl_506_gaps
from booth_review.nfl.layout import NFLVERSE_SCHEDULES_PATH, nfl_506_path
from booth_review.nfl.schedule import parse_upcoming
from booth_review.nfl.seasons import nfl_collectable_season
from booth_review.nfl.upcoming import current_nfl_week
from booth_review.sources.cfbd.parser import CfbdGame, parse_games

EASTERN = ZoneInfo("America/New_York")

_LAST_NFL_WEEK = 18


@dataclass(frozen=True)
class ReminderSlot:
    """One reminder time: a local ET weekday (Monday=0) and clock time, open for `grace`."""

    kind: str
    weekday: int
    hour: int
    minute: int
    grace: timedelta


_GRACE = timedelta(hours=3)

REMINDER_SLOTS: dict[str, ReminderSlot] = {
    slot.kind: slot
    for slot in (
        ReminderSlot("espnpr", 0, 17, 30, _GRACE),
        ReminderSlot("aa_cfb", 1, 21, 30, _GRACE),
        ReminderSlot("aa_nfl", 2, 12, 0, _GRACE),
        ReminderSlot("506_nfl", 3, 12, 0, _GRACE),
        ReminderSlot("fox_cfb", 4, 11, 30, _GRACE),
    )
}


def in_window(now: datetime, slot: ReminderSlot) -> bool:
    """Whether `now` falls in [slot time, slot time + grace) on the slot's ET weekday."""
    local = now.astimezone(EASTERN)
    if local.weekday() != slot.weekday:
        return False
    start = local.replace(hour=slot.hour, minute=slot.minute, second=0, microsecond=0)
    return start <= local < start + slot.grace


def _cfb_items(paths: DataPaths, now: datetime) -> list[AttentionItem]:
    open_slots = [
        kind for kind in ("espnpr", "aa_cfb", "fox_cfb") if in_window(now, REMINDER_SLOTS[kind])
    ]
    if not open_slots:
        return []
    season = collectable_season(now.astimezone(EASTERN).date())
    if season is None:
        return []
    games_path = paths.raw / "cfbd" / "games" / f"{season}.json"
    if not games_path.is_file():
        return []
    try:
        games: list[CfbdGame] = parse_games(games_path.read_bytes())
    except ParseError:
        return []
    label = espnpr_page_week(games, season, now)
    if label is None:
        return []
    items: list[AttentionItem] = []
    for kind in open_slots:
        if kind == "espnpr":
            if find_espnpr_gap(paths, season, games, now) is not None:
                items.append(reminder_espnpr(season, label))
        elif kind == "aa_cfb":
            items.append(reminder_aa_cfb(season, label))
        else:
            items.append(reminder_fox_cfb(season, label))
    return items


def _nfl_items(paths: DataPaths, now: datetime) -> list[AttentionItem]:
    open_slots = [kind for kind in ("aa_nfl", "506_nfl") if in_window(now, REMINDER_SLOTS[kind])]
    if not open_slots:
        return []
    schedule = paths.raw / NFLVERSE_SCHEDULES_PATH
    if not schedule.is_file():
        return []
    season = nfl_collectable_season(now.astimezone(EASTERN).date())
    if season is None:
        return []
    try:
        upcoming, _unplaced = parse_upcoming(schedule.read_bytes(), seasons=[season])
    except ParseError:
        return []
    week = current_nfl_week(upcoming, now)
    if week is None or not 1 <= week <= _LAST_NFL_WEEK:
        return []
    label = str(week)
    items: list[AttentionItem] = []
    if "aa_nfl" in open_slots:
        items.append(reminder_aa_nfl(season, label))
    if "506_nfl" in open_slots:
        gaps = find_nfl_506_gaps(paths, season, now)
        if gaps is not None:
            if gaps.missing:
                items.append(reminder_506_nfl_played(season, label, "missing", gaps.missing))
            if gaps.stale:
                items.append(reminder_506_nfl_played(season, label, "stale", gaps.stale))
        if not (paths.raw / nfl_506_path(season, week)).is_file():
            items.append(reminder_506_nfl(season, label))
    return items


def due_reminders(paths: DataPaths, now: datetime) -> list[AttentionItem]:
    """The reminder lines due at `now`: the open slots whose saved checks say a page is needed."""
    return [*_cfb_items(paths, now), *_nfl_items(paths, now)]
