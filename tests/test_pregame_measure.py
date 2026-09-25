"""Tests for the SPIKE-04 pre-game x-axis measure: coverage_by_season,
choose_measure, the axis-orientation helpers, and run_pregame_measure.

All fixtures are synthetic (invented teams), built inline for two seasons.
No real CFBD row appears in this file (D-07).
"""

from __future__ import annotations

import json

import pytest

from booth_review.config import DataPaths
from booth_review.spike.pregame_measure import (
    SeasonCoverage,
    choose_measure,
    coverage_by_season,
    run_pregame_measure,
    spread_closeness,
    wp_closeness,
)


def _game(game_id: int, *, completed: bool = True, home_class: str = "fbs") -> dict[str, object]:
    return {
        "id": game_id,
        "season": 2014,
        "week": 1,
        "seasonType": "regular",
        "startDate": "2014-08-30T16:00:00.000Z",
        "completed": completed,
        "neutralSite": False,
        "homeTeam": f"Example Home {game_id}",
        "homeClassification": home_class,
        "awayTeam": f"Example Away {game_id}",
        "awayClassification": "fbs",
        "excitementIndex": 4.0,
    }


def _wp_row(game_id: int, spread: float, prob: float) -> dict[str, object]:
    return {
        "season": 2014,
        "seasonType": "regular",
        "week": 1,
        "gameId": game_id,
        "homeTeam": f"Example Home {game_id}",
        "awayTeam": f"Example Away {game_id}",
        "spread": spread,
        "homeWinProbability": prob,
    }


def _lines_row(game_id: int, providers: dict[str, float | None]) -> dict[str, object]:
    return {
        "id": game_id,
        "season": 2014,
        "week": 1,
        "seasonType": "regular",
        "startDate": "2014-08-30T16:00:00.000Z",
        "homeTeam": f"Example Home {game_id}",
        "awayTeam": f"Example Away {game_id}",
        "lines": [
            {
                "provider": provider,
                "spread": spread,
                "formattedSpread": None,
                "spreadOpen": None,
                "overUnder": None,
                "overUnderOpen": None,
                "homeMoneyline": None,
                "awayMoneyline": None,
            }
            for provider, spread in providers.items()
        ],
    }


def _seed_season(
    paths: DataPaths,
    *,
    season: int,
    game_ids: list[int],
    wp_game_ids: list[int],
    spread_game_ids: list[int],
    providers: dict[str, float | None] | None = None,
) -> None:
    providers = providers or {"consensus": -3.0}
    games_dir = paths.raw / "cfbd" / "games"
    wp_dir = paths.raw / "cfbd" / "wp_pregame"
    lines_dir = paths.raw / "cfbd" / "lines"
    for d in (games_dir, wp_dir, lines_dir):
        d.mkdir(parents=True, exist_ok=True)

    games = [_game(gid) for gid in game_ids]
    (games_dir / f"{season}.json").write_text(json.dumps(games), encoding="utf-8")

    wp_rows = [_wp_row(gid, -3.0, 0.6) for gid in wp_game_ids]
    (wp_dir / f"{season}.json").write_text(json.dumps(wp_rows), encoding="utf-8")

    lines_rows = [_lines_row(gid, providers) for gid in spread_game_ids]
    (lines_dir / f"{season}.json").write_text(json.dumps(lines_rows), encoding="utf-8")


# -- coverage_by_season -------------------------------------------------------------------


def test_coverage_by_season_counts_universe_and_coverage(vault_paths: DataPaths) -> None:
    _seed_season(
        vault_paths,
        season=2014,
        game_ids=[1001, 1002, 1003, 1004, 1005],
        wp_game_ids=[1001, 1002, 1003, 1004, 1005],
        spread_game_ids=[1001, 1002, 1003],
    )
    _seed_season(
        vault_paths,
        season=2015,
        game_ids=[2001, 2002, 2003, 2004, 2005],
        wp_game_ids=[2001, 2002, 2003, 2004],
        spread_game_ids=[2001, 2002, 2003, 2004, 2005],
    )
    coverages = coverage_by_season(vault_paths, [2014, 2015])
    assert len(coverages) == 2
    cov_2014 = next(c for c in coverages if c.season == 2014)
    assert cov_2014.universe == 5
    assert cov_2014.wp_covered == 5
    assert cov_2014.spread_covered == 3
    assert cov_2014.wp_pct == 100.0
    assert cov_2014.spread_pct == 60.0

    cov_2015 = next(c for c in coverages if c.season == 2015)
    assert cov_2015.wp_covered == 4
    assert cov_2015.spread_covered == 5


def test_coverage_by_season_skips_seasons_with_no_cached_games(vault_paths: DataPaths) -> None:
    _seed_season(
        vault_paths,
        season=2014,
        game_ids=[1001],
        wp_game_ids=[1001],
        spread_game_ids=[1001],
    )
    coverages = coverage_by_season(vault_paths, [2013, 2014, 2016])
    assert [c.season for c in coverages] == [2014]


# -- choose_measure ------------------------------------------------------------------------


def test_choose_measure_prefers_higher_min_coverage_when_gap_at_least_two_points() -> None:
    coverages = [
        SeasonCoverage(
            season=2014, universe=100, wp_covered=80, spread_covered=60, provider_counts={}
        ),
        SeasonCoverage(
            season=2015, universe=100, wp_covered=90, spread_covered=95, provider_counts={}
        ),
    ]
    choice = choose_measure(coverages)
    # min wp pct = 80, min spread pct = 60 -> wp wins by 20 points.
    assert choice.measure == "pregame_wp"
    assert choice.min_coverage == 80.0
    assert "80.0%" in choice.reason


def test_choose_measure_falls_back_to_closing_spread_within_gap() -> None:
    coverages = [
        SeasonCoverage(
            season=2014, universe=100, wp_covered=59, spread_covered=60, provider_counts={}
        ),
    ]
    choice = choose_measure(coverages)
    assert choice.measure == "closing_spread"
    assert "interpretability" in choice.reason


# -- orientation helpers -------------------------------------------------------------------


def test_spread_closeness_orients_pickem_rightmost() -> None:
    assert spread_closeness(-3.5) == -3.5
    assert spread_closeness(7.0) == -7.0
    assert spread_closeness(0.0) == 0.0


def test_wp_closeness_orients_toss_up_rightmost() -> None:
    assert wp_closeness(0.5) == 1.0
    assert wp_closeness(0.9) == pytest.approx(0.2)


# -- run_pregame_measure -------------------------------------------------------------------


def test_run_pregame_measure_writes_coverage_csv_and_report(vault_paths: DataPaths) -> None:
    _seed_season(
        vault_paths,
        season=2014,
        game_ids=[1001, 1002, 1003],
        wp_game_ids=[1001, 1002, 1003],
        spread_game_ids=[1001, 1002],
        providers={"consensus": -3.0, "OtherBook": -2.5},
    )
    _seed_season(
        vault_paths,
        season=2025,
        game_ids=[2001, 2002],
        wp_game_ids=[2001],
        spread_game_ids=[2001, 2002],
    )

    choice = run_pregame_measure(vault_paths)

    csv_path = vault_paths.spike / "pregame-coverage.csv"
    assert csv_path.is_file()
    csv_lines = csv_path.read_text(encoding="utf-8").splitlines()
    header = csv_lines[0].split(",")
    assert header == [
        "season",
        "universe",
        "wp_covered",
        "wp_pct",
        "spread_covered",
        "spread_pct",
        "providers",
    ]
    assert any(line.startswith("2014,") for line in csv_lines)
    assert any(line.startswith("2025,") for line in csv_lines)

    report_path = vault_paths.spike / "pregame-measure.md"
    assert report_path.is_file()
    report = report_path.read_text(encoding="utf-8")
    assert f"Chosen measure: {choice.measure}" in report
    assert "Reason:" in report
    assert "Orientation:" in report
    assert "consensus" in report  # provider priority order is written into the report
    assert "Spearman correlation" in report or "Not enough overlapping" in report
