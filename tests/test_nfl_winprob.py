"""GEI-style excitement and volatility on synthetic pbp frames."""

from __future__ import annotations

import statistics
from pathlib import Path

import polars as pl
import pytest

from booth_review.errors import ParseError
from booth_review.nfl.winprob import MIN_WP_PLAYS, PBP_COLUMNS, game_wp_metrics, read_pbp_wp


def _plays(
    gid: str,
    wps: list[float | None],
    post: float | None,
    *,
    last_qtr: int = 4,
    last_qsr: float = 0.0,
) -> pl.DataFrame:
    n = len(wps)
    return pl.DataFrame(
        {
            "game_id": [gid] * n,
            "play_id": list(range(1, n + 1)),
            "qtr": [1] * (n - 1) + [last_qtr],
            "quarter_seconds_remaining": [900.0] * (n - 1) + [last_qsr],
            "home_wp": wps,
            "home_wp_post": [None] * (n - 1) + [post],
        },
        schema={
            "game_id": pl.String,
            "play_id": pl.Int64,
            "qtr": pl.Int64,
            "quarter_seconds_remaining": pl.Float64,
            "home_wp": pl.Float64,
            "home_wp_post": pl.Float64,
        },
    )


def _run(df: pl.DataFrame, season: int = 2022, gtype: str = "REG", **kw: int) -> dict:
    out = game_wp_metrics(df, season_by_game={"g": season}, game_type_by_game={"g": gtype}, **kw)
    return out.row(0, named=True)


def test_regulation_three_plays() -> None:
    row = _run(_plays("g", [0.5, 0.7, 0.4], 1.0), min_plays=3)
    assert row["excitement_score"] == pytest.approx(1.1)
    assert row["wp_volatility"] == pytest.approx(statistics.stdev([0.2, -0.3, 0.6]))
    assert row["wp_plays"] == 3


def test_overtime_2018_regular_season_uses_600s_period() -> None:
    df = _plays("g", [0.5, 0.7, 0.4], 1.0, last_qtr=5, last_qsr=120.0)
    row = _run(df, season=2018, min_plays=3)
    assert row["excitement_score"] == pytest.approx(1.1 * 3600 / (3600 + 480))


def test_overtime_2015_regular_season_uses_900s_period() -> None:
    df = _plays("g", [0.5, 0.7, 0.4], 1.0, last_qtr=5, last_qsr=120.0)
    row = _run(df, season=2015, min_plays=3)
    assert row["excitement_score"] == pytest.approx(1.1 * 3600 / (3600 + 780))


def test_playoff_multiple_overtimes_add_up() -> None:
    df = _plays("g", [0.5, 0.7, 0.4], 1.0, last_qtr=6, last_qsr=300.0)
    row = _run(df, season=2022, gtype="DIV", min_plays=3)
    assert row["excitement_score"] == pytest.approx(1.1 * 3600 / (3600 + 900 + 600))


def test_null_plays_skipped_not_zero_filled() -> None:
    df = _plays("g", [0.5, None, 0.7, 0.4], 1.0)
    row = _run(df, min_plays=3)
    assert row["wp_plays"] == 3
    assert row["excitement_score"] == pytest.approx(1.1)


def test_too_few_plays_is_null_not_zero() -> None:
    row = _run(_plays("g", [0.5, 0.7, 0.4], 1.0))
    assert MIN_WP_PLAYS > 3
    assert row["excitement_score"] is None
    assert row["wp_volatility"] is None


def test_no_wp_at_all_is_null() -> None:
    row = _run(_plays("g", [None, None], None), min_plays=1)
    assert row["excitement_score"] is None


def test_read_pbp_wp_missing_column(tmp_path: Path) -> None:
    df = _plays("g", [0.5, 0.6], 0.7).drop("home_wp")
    path = tmp_path / "pbp.parquet"
    df.write_parquet(path)
    with pytest.raises(ParseError, match="home_wp"):
        read_pbp_wp(path)


def test_read_pbp_wp_projects_columns(tmp_path: Path) -> None:
    df = _plays("g", [0.5, 0.6], 0.7).with_columns(extra=pl.lit(1))
    path = tmp_path / "pbp.parquet"
    df.write_parquet(path)
    assert tuple(read_pbp_wp(path).columns) == PBP_COLUMNS


def test_read_pbp_wp_does_not_require_game_seconds_remaining(tmp_path: Path) -> None:
    # IN-05: nothing reads game_seconds_remaining, so a file without it is valid.
    df = _plays("g", [0.5, 0.6], 0.7)
    assert "game_seconds_remaining" not in df.columns
    path = tmp_path / "pbp.parquet"
    df.write_parquet(path)
    assert read_pbp_wp(path).columns == list(PBP_COLUMNS)
