"""Phase 24 hand-save reminders: which reminder lines are due at `now` (D-12 to D-17).

The user hand-saves ESPN Press Room, Awful Announcing, FOX and 506 pages. These
slots (Mon 17:30, Tue 21:30, Wed 12:00, Thu 12:00, Fri 11:30 ET) name the page
to save, with a fixed public link, as lines on the needs-attention issue.

D-15: this module only reads the vault (the CFBD games file, the nflverse
schedule, saved ESPN and 506 pages, and the 506 gap report). It sends no
request, writes nothing, and imports no transport client or collector directly
(`nfl.gaps` reads the 506 manifest through `transport.cache.Manifest`, which
only parses a local file and never opens a connection). The caller
decides what a due reminder does: a run with nothing else due posts it through
the comment-only path (no state, budget, build or deploy, D-16); a full or
schedule run adds the lines to its own attention items.

Phase 25 (D-02): D-15 still holds for this module. The Tuesday AA slot may
receive a caller-supplied resolver (`aa_cfb`, built in `job/aa_watch.py`) that
makes the one feed request; this module imports no transport or network code.
Without a resolver the slot yields the plain Phase 24 line.

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

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time, timedelta
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
from booth_review.job.catchup import _require_aware, collectable_season
from booth_review.job.gaps_espnpr import espnpr_page_week, find_espnpr_gap
from booth_review.nfl.games import PLAYED_AFTER
from booth_review.nfl.gaps import find_nfl_506_gaps
from booth_review.nfl.layout import NFLVERSE_SCHEDULES_PATH, nfl_506_path
from booth_review.nfl.schedule import UpcomingNflGame, parse_upcoming
from booth_review.nfl.seasons import nfl_collectable_season
from booth_review.nfl.upcoming import current_nfl_week
from booth_review.sources.cfbd.parser import CfbdGame, parse_games

EASTERN = ZoneInfo("America/New_York")

_LOG = logging.getLogger(__name__)

AaCfbResolver = Callable[[int, str, datetime], list[AttentionItem]]

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


def current_cfb_week(paths: DataPaths, now: datetime) -> tuple[int, str] | None:
    """(season, label) when a numbered CFB week is current at `now`, else None."""
    season = collectable_season(now.astimezone(EASTERN).date())
    if season is None:
        return None
    games = _read_games(paths, season)
    if games is None:
        return None
    label = espnpr_page_week(games, season, now)
    return None if label is None else (season, label)


def _read_games(paths: DataPaths, season: int) -> list[CfbdGame] | None:
    games_path = paths.raw / "cfbd" / "games" / f"{season}.json"
    if not games_path.is_file():
        return None
    try:
        return parse_games(games_path.read_bytes())
    except ParseError:
        return None


def _cfb_items(
    paths: DataPaths, now: datetime, aa_cfb: AaCfbResolver | None
) -> list[AttentionItem]:
    open_slots = [
        kind for kind in ("espnpr", "aa_cfb", "fox_cfb") if in_window(now, REMINDER_SLOTS[kind])
    ]
    if not open_slots:
        return []
    season = collectable_season(now.astimezone(EASTERN).date())
    if season is None:
        return []
    games = _read_games(paths, season)
    if games is None:
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
            if aa_cfb is None:
                items.append(reminder_aa_cfb(season, label))
            else:
                try:
                    items.extend(aa_cfb(season, label, now))
                except Exception as exc:
                    _LOG.warning("aa resolver failed: %s", type(exc).__name__)
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
    if not _in_regular_season(upcoming, now):
        return []
    week = current_nfl_week(upcoming, now)
    if week is None or not 1 <= week <= _LAST_NFL_WEEK:
        return []
    label = str(week)
    items: list[AttentionItem] = []
    if "aa_nfl" in open_slots:
        items.append(reminder_aa_nfl(season, label))
    if "506_nfl" in open_slots:
        items.extend(
            _guarded("506_nfl_played", lambda: _played_506_items(paths, season, label, now))
        )
        items.extend(_guarded("506_nfl", lambda: _upcoming_506_items(paths, season, week)))
    return items


def _in_regular_season(upcoming: list[UpcomingNflGame], now: datetime) -> bool:
    """Whether `now` is between the Monday of week 1's first kickoff week and the last
    regular-season game finishing; July (before week 1) and January (after the last
    week) are outside, though the collectable season still covers them."""
    kickoffs = [g.kickoff_et for g in upcoming if g.week == 1 and g.kickoff_et is not None]
    if not kickoffs:
        return False
    first = min(kickoffs)
    monday = first.date() - timedelta(days=first.weekday())
    if now < datetime.combine(monday, time(0, 0), tzinfo=EASTERN):
        return False
    last_week = max(g.week for g in upcoming)
    final = [g for g in upcoming if g.week == last_week]
    return not all(g.kickoff_et is not None and g.kickoff_et + PLAYED_AFTER <= now for g in final)


def _played_506_items(
    paths: DataPaths, season: int, label: str, now: datetime
) -> list[AttentionItem]:
    gaps = find_nfl_506_gaps(paths, season, now)
    items: list[AttentionItem] = []
    if gaps is not None:
        if gaps.missing:
            items.append(reminder_506_nfl_played(season, label, "missing", gaps.missing))
        if gaps.stale:
            items.append(reminder_506_nfl_played(season, label, "stale", gaps.stale))
    return items


def _upcoming_506_items(paths: DataPaths, season: int, week: int) -> list[AttentionItem]:
    if (paths.raw / nfl_506_path(season, week)).is_file():
        return []
    return [reminder_506_nfl(season, str(week))]


def _guarded(name: str, step: Callable[[], list[AttentionItem]]) -> list[AttentionItem]:
    """Run one reminder slot; a failure skips that slot and logs only the class name,
    so a bad saved file never crashes the run that asked (or its state save)."""
    try:
        return step()
    except Exception as exc:
        _LOG.warning("reminder slot %s skipped: %s", name, type(exc).__name__)
        return []


def due_reminders(
    paths: DataPaths, now: datetime, *, aa_cfb: AaCfbResolver | None = None
) -> list[AttentionItem]:
    """The reminder lines due at `now`: the open slots whose saved checks say a page is needed."""
    _require_aware(now, "now")
    return [
        *_guarded("cfb", lambda: _cfb_items(paths, now, aa_cfb)),
        *_guarded("nfl", lambda: _nfl_items(paths, now)),
    ]
