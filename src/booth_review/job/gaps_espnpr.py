"""The ESPN Press Room hand-save reminder: is this week's commentators page saved? (04.19 D-14)

ESPN Press Room's season commentators page
(`/<yyyy>-<yy>-espn-college-football-commentators-schedule/`) carries only the
current week and is overwritten every Monday, so a week that is not saved
before the next Monday's update is lost from that URL (its weekly release,
found through the college-football category listing, is the only way back).
Disney's Terms of Use ban automated access, so the scheduled job never
fetches espnpressroom.com. This module only names, by ESPN week label, the
week the page carries right now when the vault has no saved copy of it, so
the job can list it in the D-12 attention issue beside the 506 weeks. The
user saves the page in a browser and imports it with
`booth-review import espnpr`. It sends nothing over the network and reads
only the vault (`raw/espnpr/<season>/commentators/wk-<label>.html`, Plan
38's layout) and the CFBD games already collected for the season.

ESPN's week labels are 506's: CFBD regular week 1 holds both ESPN Week 0 (the
early openers) and Week 1, and for N >= 2 ESPN Week N is CFBD week N (Plan 37
checked 2024 and 2026 by date). `gaps506.week_windows` already splits CFBD
week 1 by date, so its numeric labels are reused here rather than a fixed
label offset.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta

from booth_review.config import DataPaths
from booth_review.job.gaps506 import EASTERN, week_windows
from booth_review.sources.cfbd.parser import CfbdGame
from booth_review.sources.espnpr.importer import SOURCE

_WEEK = timedelta(days=7)
_SATURDAY = 5  # date.weekday()


def _monday_start(day: date) -> datetime:
    """00:00 ET on the Monday of `day`'s Monday-to-Sunday week."""
    monday = day - timedelta(days=day.weekday())
    return datetime.combine(monday, time(0, 0), tzinfo=EASTERN)


def _game_label(game: CfbdGame, windows: dict[str, tuple[datetime, datetime]]) -> str:
    """The 506/ESPN label of one regular-season game, by `week_windows`' week-1 split."""
    if game.week != 1:
        return str(game.week)
    week_zero = windows.get("0")
    return "0" if week_zero is not None and game.start_date <= week_zero[1] else "1"


def week_spans(games: Sequence[CfbdGame], season: int) -> dict[str, datetime]:
    """Map each numbered ESPN week label to the Monday 00:00 ET that opens its page.

    A week's page runs Monday to Sunday ET around its Saturday slate, so each
    label is anchored on the Monday of the ET week holding most of its Saturday
    games (with no Saturday game, most of its games; a tie goes to the later
    Monday). A stray game outside that week -- a Sunday opener, a Labor Day
    Monday finale -- cannot pull the label into a neighbouring week's span.
    Postseason games (506's "B") have no numbered page and are left out.
    """
    windows = week_windows(games, season)
    saturdays: dict[str, Counter[datetime]] = {}
    any_day: dict[str, Counter[datetime]] = {}
    for game in games:
        if game.season != season or game.season_type != "regular":
            continue
        label = _game_label(game, windows)
        if label not in windows or not label.isdigit():
            continue
        day = game.start_date.astimezone(EASTERN).date()
        monday = _monday_start(day)
        any_day.setdefault(label, Counter())[monday] += 1
        if day.weekday() == _SATURDAY:
            saturdays.setdefault(label, Counter())[monday] += 1

    def _anchor(counts: Counter[datetime]) -> datetime:
        return max(counts, key=lambda monday: (counts[monday], monday))

    return {label: _anchor(saturdays.get(label) or counts) for label, counts in any_day.items()}


def espnpr_page_week(games: Sequence[CfbdGame], season: int, now: datetime) -> str | None:
    """The ESPN week label the commentators page carries at `now`, else None.

    The page carries the week whose Monday-to-Sunday ET span (`week_spans`)
    holds `now`; were two labels ever anchored on one Monday, the higher wins.
    Before the first week's Monday, after the final numbered week's Sunday,
    in a week with no games, and in bowl season this returns None.
    """
    current = [
        label
        for label, monday in week_spans(games, season).items()
        if monday <= now < monday + _WEEK
    ]
    return max(current, key=int) if current else None


def find_espnpr_gap(
    paths: DataPaths, season: int, games: Sequence[CfbdGame], now: datetime
) -> str | None:
    """The current ESPN week label when its commentators page is not in the vault.

    A week counts as saved when `raw/espnpr/<season>/commentators/wk-<label>.html`
    exists (Plan 38 writes it on import; N is unpadded). Returns None when the
    page is saved or no numbered week is current (see `espnpr_page_week`).
    """
    label = espnpr_page_week(games, season, now)
    if label is None:
        return None
    saved = paths.raw / SOURCE / str(season) / "commentators" / f"wk-{label}.html"
    return None if saved.is_file() else label
