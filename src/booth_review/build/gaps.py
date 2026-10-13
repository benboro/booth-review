"""Dates that still need a second viewership source (04.19 D-11).

The TV Ratings Guide and Awful Announcing are fetched only for dates that still
carry an unrated main-feed telecast after RR and SMW. `remaining_gap_dates`
reads the same offline tables `booth-review build` assembles; it never fetches.
"""

from __future__ import annotations

from collections.abc import Collection
from datetime import date

import polars as pl

from booth_review.build.tables import BuildTables

GAP_SEASONS: range = range(2021, 2025)


def remaining_gap_dates(
    tables: BuildTables, seasons: Collection[int] = GAP_SEASONS
) -> dict[int, set[date]]:
    """Per season, the ET dates of in-scope main-feed telecasts still unrated.

    A telecast counts when its feed is "main", it is not rated, it has a
    network, and its game is in the games frame (the build's scope). Every
    requested season gets a key, empty when it has no gap left.
    """
    wanted = sorted(set(seasons))
    result: dict[int, set[date]] = {season: set() for season in wanted}
    scoped_ids = tables.games.get_column("game_id").unique()
    gaps = tables.telecasts.filter(
        (pl.col("feed_type") == "main")
        & ~pl.col("rated").fill_null(value=False)
        & pl.col("network_id").is_not_null()
        & pl.col("season").is_in(wanted)
        & pl.col("game_id").is_in(scoped_ids.implode())
        & pl.col("date_et").is_not_null()
    ).select("season", "date_et")
    for season, day in gaps.iter_rows():
        result[int(season)].add(day)
    return result


def earliest_gap_month(gaps: dict[int, set[date]]) -> tuple[int, int] | None:
    """(year, month) of the earliest gap date, or None when nothing is left."""
    days = [day for season_days in gaps.values() for day in season_days]
    if not days:
        return None
    first = min(days)
    return first.year, first.month


def regular_weeks_by_date(
    games: pl.DataFrame, seasons: Collection[int] = GAP_SEASONS
) -> dict[date, set[int]]:
    """ET date -> CFBD regular-season week(s) of the games played that day.

    Awful Announcing's weekly roundups are planned per week (04.19 D-11), so a
    gap date maps to its week here; postseason dates map to nothing.
    """
    rows = (
        games.filter(
            (pl.col("season_type").fill_null("regular") == "regular")
            & pl.col("season").is_in(sorted(set(seasons)))
            & pl.col("date_et").is_not_null()
            & pl.col("week").is_not_null()
        )
        .select("date_et", "week")
        .unique()
    )
    result: dict[date, set[int]] = {}
    for day, week in rows.iter_rows():
        result.setdefault(day, set()).add(int(week))
    return result
