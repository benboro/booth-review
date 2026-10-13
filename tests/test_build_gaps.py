"""04.19 D-11: the dates TVRG and AA may be fetched for."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import cast

import polars as pl

from booth_review.build.gaps import earliest_gap_month, remaining_gap_dates
from booth_review.build.tables import BuildTables


def _tables() -> BuildTables:
    games = pl.DataFrame({"game_id": [1, 2, 3, 4, 5, 6, 7]}, schema={"game_id": pl.Int64})
    rows = [
        # (game_id, season, date_et, network_id, feed_type, rated)
        (1, 2021, date(2021, 9, 4), "espn", "main", False),  # a gap
        (2, 2021, date(2021, 9, 4), "abc", "main", False),  # same date, counted once
        (3, 2022, date(2022, 10, 1), "espn", "main", True),  # rated (RR or SMW)
        (4, 2022, date(2022, 10, 8), "fs1", "alt", False),  # alternate feed
        (5, 2023, date(2023, 11, 4), None, "main", False),  # no network
        (6, 2020, date(2020, 9, 12), "espn", "main", False),  # outside 2021-2024
        (99, 2024, date(2024, 9, 7), "espn", "main", False),  # out of scope (no game)
        (7, 2024, date(2024, 11, 30), "cbs", "main", None),  # unknown rated -> a gap
    ]
    telecasts = pl.DataFrame(
        rows,
        schema={
            "game_id": pl.Int64,
            "season": pl.Int32,
            "date_et": pl.Date,
            "network_id": pl.Utf8,
            "feed_type": pl.Utf8,
            "rated": pl.Boolean,
        },
        orient="row",
    )
    return cast(BuildTables, SimpleNamespace(games=games, telecasts=telecasts))


def test_remaining_gap_dates_keeps_only_main_unrated_in_scope_dates() -> None:
    gaps = remaining_gap_dates(_tables())
    assert gaps == {
        2021: {date(2021, 9, 4)},
        2022: set(),
        2023: set(),
        2024: {date(2024, 11, 30)},
    }


def test_remaining_gap_dates_honors_a_season_subset() -> None:
    assert remaining_gap_dates(_tables(), seasons=[2024]) == {2024: {date(2024, 11, 30)}}


def test_earliest_gap_month() -> None:
    assert earliest_gap_month(remaining_gap_dates(_tables())) == (2021, 9)
    assert earliest_gap_month({2021: set()}) is None
