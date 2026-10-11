"""NFL season helpers: the freeze date and the season a run should collect.

An NFL season starts in the fall of `season` and ends with the Super Bowl in
February of `season + 1`. It freezes on March 1 after that, past the Super Bowl
(Feb 8-15; LXI is Feb 14, 2027) with margin for late playoff records.
"""

from __future__ import annotations

from datetime import date

from booth_review.seasons import season_of

NFL_FREEZE_MONTH_DAY = (3, 1)


def nfl_freeze_date(season: int) -> date:
    """The date `season` becomes eligible to freeze (March 1 after the season)."""
    month, day = NFL_FREEZE_MONTH_DAY
    return date(season + 1, month, day)


def nfl_collectable_season(today: date) -> int | None:
    """The NFL season a run on `today` should collect, or None from March 1 to June 30.

    Playoffs and the Super Bowl (through Feb 28/29) still belong to the season
    that started the previous fall.
    """
    season = season_of(today)
    if today >= nfl_freeze_date(season):
        return None
    return season
