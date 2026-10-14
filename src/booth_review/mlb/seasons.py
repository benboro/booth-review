"""MLB season helpers: calendar-year seasons and the freeze date.

An MLB season is the calendar year of its games (April through the World
Series in late October or early November). Never use booth_review.seasons,
whose football-season rule would put April games in the previous season.
"""

from __future__ import annotations

from datetime import date

# D-22 as amended: freeze on March 1 of the next year, so the Retrosheet
# release that lands after the World Series can still be collected.
MLB_FREEZE_MONTH_DAY = (3, 1)


def mlb_season_of(d: date) -> int:
    return d.year


def mlb_season_window(season: int) -> tuple[date, date]:
    return date(season, 1, 1), date(season, 12, 31)


def mlb_freeze_date(season: int) -> date:
    """The date `season` becomes eligible to freeze (March 1 of the next year)."""
    month, day = MLB_FREEZE_MONTH_DAY
    return date(season + 1, month, day)


def mlb_current_season(today: date) -> int:
    return today.year
