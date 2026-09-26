"""Tests for resolve/lines.py: provider_priority and closing_spread_by_game
(promoted from spike/pregame_measure.py in Phase 3), and the new pregame_x
pre-game x-axis helper (SPIKE-04).
"""

from __future__ import annotations

from booth_review.resolve.lines import closing_spread_by_game, pregame_x, provider_priority
from booth_review.sources.cfbd.parser import CfbdLine


def _line(game_id: int, provider: str, spread: float | None) -> CfbdLine:
    return CfbdLine(
        game_id=game_id,
        season=2025,
        week=1,
        season_type="regular",
        start_date=None,
        home_team="Example Home",
        away_team="Example Away",
        provider=provider,
        spread=spread,
        formatted_spread=None,
        spread_open=None,
        over_under=None,
        over_under_open=None,
        home_moneyline=None,
        away_moneyline=None,
    )


# -- lines.provider_priority --------------------------------------------------------------


def test_provider_priority_puts_consensus_first() -> None:
    counts = {"OtherBook": 5, "consensus": 2, "ThirdBook": 3}
    assert provider_priority(counts) == ["consensus", "OtherBook", "ThirdBook"]


def test_provider_priority_orders_by_descending_count_then_alphabetical() -> None:
    counts = {"Bravo": 3, "Alpha": 3, "Charlie": 5}
    assert provider_priority(counts) == ["Charlie", "Alpha", "Bravo"]


def test_provider_priority_without_consensus() -> None:
    counts = {"Bravo": 1, "Alpha": 2}
    assert provider_priority(counts) == ["Alpha", "Bravo"]


# -- lines.closing_spread_by_game -----------------------------------------------------------


def test_closing_spread_by_game_picks_highest_priority_provider_with_a_spread() -> None:
    lines = [
        _line(1, "consensus", None),
        _line(1, "OtherBook", -3.5),
        _line(2, "consensus", -7.0),
        _line(2, "OtherBook", -6.5),
    ]
    priority = ["consensus", "OtherBook"]
    result = closing_spread_by_game(lines, priority)
    # Game 1's top-priority provider (consensus) had a null spread, so the
    # next-priority provider with a non-null spread is picked instead.
    assert result[1] == -3.5
    assert result[2] == -7.0


def test_closing_spread_by_game_falls_back_to_an_arbitrary_provider() -> None:
    lines = [_line(1, "UnlistedBook", -4.0)]
    result = closing_spread_by_game(lines, ["consensus"])
    assert result[1] == -4.0


def test_closing_spread_by_game_skips_null_spread_lines() -> None:
    lines = [_line(1, "consensus", None)]
    result = closing_spread_by_game(lines, ["consensus"])
    assert result == {}


# -- lines.pregame_x -------------------------------------------------------------------------


def test_pregame_x_is_minus_absolute_spread() -> None:
    assert pregame_x(-7.5) == -7.5
    assert pregame_x(3.0) == -3.0


def test_pregame_x_pickem_plots_rightmost() -> None:
    assert pregame_x(0.0) == 0.0


def test_pregame_x_none_stays_none() -> None:
    assert pregame_x(None) is None
