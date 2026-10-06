"""Shipped-row predicate, no-rating cause precedence, and the rarity audit."""

from __future__ import annotations

from typing import Any

import polars as pl
import pytest

from booth_review.build.shipped import (
    left_out_unrated_expr,
    network_rated_counts,
    no_rating_cause,
    rarity_contradictions,
    rarity_verdict,
    select_unrated_shipped,
    shipped_expr,
    unrated_shipped_expr,
)

RARE = {"net-c": True, "net-a": False}


def cause(**overrides: Any) -> str:
    args: dict[str, Any] = {
        "season": 2026,
        "season_type": "regular",
        "week": 4,
        "network_id": "net-a",
        "rarely_rated": RARE,
        "current_season": 2026,
        "viewership_through_week": "4",
        "rated_not_plotted": False,
    }
    args.update(overrides)
    return no_rating_cause(**args)


def test_predicate_keeps_only_unplotted_main_feed_with_game_and_network() -> None:
    frame = pl.DataFrame(
        {
            "plotted": [False, True, False, False, False, False],
            "feed_type": ["main", "main", "alt", "main", "main", "main"],
            "game_id": [1, 2, 3, None, 5, 6],
            "network_id": ["a", "a", "a", "a", None, "b"],
        }
    )
    kept = frame.with_columns(u=unrated_shipped_expr(), s=shipped_expr())
    assert kept["u"].to_list() == [True, False, False, False, False, True]
    assert kept["s"].to_list() == [True, True, False, False, False, True]


def test_rarely_rated_wins_even_in_2023_and_current_season() -> None:
    assert cause(season=2023, network_id="net-c", current_season=2026) == "rarely_rated"
    assert cause(network_id="net-c") == "rarely_rated"


@pytest.mark.parametrize(
    ("season_type", "week", "expected"),
    [
        ("regular", 4, "pending"),
        ("regular", 5, "pending"),
        ("regular", 3, "none"),
        ("postseason", 1, "pending"),
    ],
)
def test_pending_is_at_or_after_through_week(season_type: str, week: int, expected: str) -> None:
    assert cause(season_type=season_type, week=week) == expected


def test_through_postseason() -> None:
    kwargs = {"viewership_through_week": "postseason"}
    assert cause(season_type="postseason", **kwargs) == "pending"
    assert cause(season_type="regular", week=12, **kwargs) == "none"


def test_through_none_makes_every_current_game_pending() -> None:
    assert cause(viewership_through_week=None, week=1) == "pending"


@pytest.mark.parametrize(
    ("season", "expected"), [(2021, "rr_dip"), (2024, "rr_dip"), (2020, "none"), (2025, "none")]
)
def test_rr_dip_seasons(season: int, expected: str) -> None:
    assert cause(season=season) == expected


def test_alt_only_figure_is_none_regardless() -> None:
    assert cause(rated_not_plotted=True, network_id="net-c") == "none"
    assert cause(rated_not_plotted=True, season=2023) == "none"
    assert cause(rated_not_plotted=True, week=9) == "none"


def test_network_rated_counts_main_feed_only() -> None:
    frame = pl.DataFrame(
        {
            "feed_type": ["main", "main", "alt", "main"],
            "network_id": ["a", "a", "a", None],
            "rated": [True, False, True, True],
        }
    )
    assert network_rated_counts(frame) == {"a": (2, 1)}


def test_rarity_verdict() -> None:
    assert rarity_verdict(30, 10, True) == "flagged_but_mostly_rated"
    assert rarity_verdict(30, 2, False) == "unflagged_but_mostly_unrated"
    assert rarity_verdict(24, 0, False) is None
    assert rarity_verdict(30, 5, True) is None


def test_rarity_contradictions_sums_verdicts() -> None:
    counts = {"a": (30, 10), "b": (30, 2), "c": (30, 5), "d": (5, 0)}
    rarity = {"a": True, "b": False, "c": True, "d": False}
    assert rarity_contradictions(counts, rarity) == (1, 1)


_SORT = ["date_et", "kickoff_et", "telecast_id"]


def test_select_unrated_shipped_never_ships_a_game_twice() -> None:
    # WR-01: game 1 has a plotted row, game 2 has two unrated rows, game 3 one.
    frame = pl.DataFrame(
        {
            "telecast_id": ["t1", "t2", "t3", "t4", "t5"],
            "date_et": ["2024-09-07"] * 5,
            "kickoff_et": ["12:00", "12:00", "15:00", "12:00", "12:00"],
            "plotted": [True, False, False, False, False],
            "feed_type": ["main"] * 5,
            "game_id": [1, 1, 2, 2, 3],
            "network_id": ["a"] * 5,
        }
    )
    kept, dropped = select_unrated_shipped(frame, _SORT)
    assert kept["telecast_id"].to_list() == ["t4", "t5"]
    assert dropped == 2


def test_left_out_is_the_complement_of_the_shipped_predicate() -> None:
    frame = pl.DataFrame(
        {
            "plotted": [False, False, False, True, False, False],
            "feed_type": ["main", "main", "main", "main", "alt", "main"],
            "game_id": [1, None, 3, 4, 5, 6],
            "network_id": ["a", "a", None, None, None, "b"],
        }
    )
    out = frame.with_columns(left=left_out_unrated_expr(), u=unrated_shipped_expr())
    assert out["left"].to_list() == [False, True, True, False, False, False]
    assert out["u"].to_list() == [True, False, False, False, False, True]
