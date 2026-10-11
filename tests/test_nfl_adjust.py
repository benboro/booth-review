"""Closed-form adjustment primitives on synthetic frames (no real games)."""

from __future__ import annotations

from collections.abc import Sequence

import polars as pl
import pytest

from booth_review.nfl.adjust import (
    LOW_N,
    MIN_BAND_N,
    SPREAD_BAND_EDGES,
    VIEWERSHIP_FALLBACKS,
    VIEWERSHIP_MIN_N_PER_TERM,
    VIEWERSHIP_PREDICTORS,
    band_expectations,
    band_of,
    mean_se,
    ols_fit,
    ols_multi,
    residuals,
)
from booth_review.nfl.adjust import fit_viewership_model as fit_model

FULL = "abs_spread+abs_final_margin+excitement_score+wp_volatility"


def games(
    spreads: Sequence[float | None],
    margins: Sequence[float | None],
    *,
    game_type: str = "REG",
) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "game_type": [game_type] * len(spreads),
            "pregame_spread": list(spreads),
            "final_margin": list(margins),
        },
        schema={"game_type": pl.String, "pregame_spread": pl.Float64, "final_margin": pl.Float64},
    )


def test_constants() -> None:
    assert SPREAD_BAND_EDGES == (0.0, 3.0, 6.5, 10.0)
    assert MIN_BAND_N == 50
    assert LOW_N == 8
    assert VIEWERSHIP_PREDICTORS == (
        "abs_spread",
        "abs_final_margin",
        "excitement_score",
        "wp_volatility",
    )
    assert VIEWERSHIP_FALLBACKS[0] == VIEWERSHIP_PREDICTORS
    assert VIEWERSHIP_FALLBACKS[1:] == (("abs_spread", "excitement_score"), ("abs_spread",))
    assert VIEWERSHIP_MIN_N_PER_TERM == 5


@pytest.mark.parametrize(
    ("value", "band"),
    [(0.0, 0), (2.99, 0), (3.0, 1), (6.49, 1), (6.5, 2), (9.99, 2), (10.0, 3), (24.0, 3)],
)
def test_band_of(value: float, band: int) -> None:
    assert band_of(value) == band


def test_band_expectations_use_absolute_spread_and_margin() -> None:
    # 60 games per band; negative spreads and margins land by absolute value.
    spreads: list[float] = []
    margins: list[float] = []
    for spread, margin in [(1.0, 4.0), (-4.0, 8.0), (7.0, -12.0), (-13.0, 20.0)]:
        spreads += [spread] * 60
        margins += [margin] * 60
    exp = band_expectations(games(spreads, margins), "abs_final_margin")
    assert exp == {0: (60, 4.0), 1: (60, 8.0), 2: (60, 12.0), 3: (60, 20.0)}


def test_band_expectations_skip_nulls_and_non_regular_games() -> None:
    base = games([1.0] * 60 + [None] * 5, [4.0] * 60 + [9.0] * 5)
    extra = games([1.0] * 5, [None] * 5)
    playoff = games([1.0] * 10, [100.0] * 10, game_type="WC")
    exp = band_expectations(pl.concat([base, extra, playoff]), "abs_final_margin")
    assert exp[0] == (60, 4.0)


def test_thin_outer_band_merges_toward_center() -> None:
    # Band 3 has 10 games: it pools with band 2; bands 0-1 stand alone.
    spreads = [1.0] * 60 + [4.0] * 60 + [7.0] * 60 + [12.0] * 10
    margins = [2.0] * 60 + [4.0] * 60 + [6.0] * 60 + [13.0] * 10
    exp = band_expectations(games(spreads, margins), "abs_final_margin")
    pooled = (60 * 6.0 + 10 * 13.0) / 70
    assert exp[0] == (60, 2.0)
    assert exp[1] == (60, 4.0)
    assert exp[2] == (70, pytest.approx(pooled))
    assert exp[3] == (70, pytest.approx(pooled))


def test_thin_inner_band_merges_toward_center() -> None:
    # Band 0 is thin; its neighbor toward the center is band 1.
    spreads = [1.0] * 5 + [4.0] * 60 + [7.0] * 60 + [12.0] * 60
    margins = [10.0] * 5 + [4.0] * 60 + [6.0] * 60 + [13.0] * 60
    exp = band_expectations(games(spreads, margins), "abs_final_margin")
    assert exp[0][0] == 65 and exp[1][0] == 65
    assert exp[2] == (60, 6.0)


def test_residuals_null_never_zero() -> None:
    frame = games([1.0, None, 4.0, 1.0], [6.0, 3.0, None, 4.0])
    exp = {0: (60, 4.0), 1: (60, 8.0), 2: (60, 12.0), 3: (60, 20.0)}
    out = residuals(frame, "abs_final_margin", exp)
    assert out.to_list() == [2.0, None, None, 0.0]


def test_residuals_missing_band_is_null() -> None:
    frame = games([12.0], [3.0])
    out = residuals(frame, "abs_final_margin", {0: (60, 4.0)})
    assert out.to_list() == [None]


def test_ols_fit_recovers_exact_line() -> None:
    spreads = [float(s) for s in range(-10, 11)]
    margins = [10 + 2 * abs(s) for s in spreads]
    fit = ols_fit(games(spreads, margins), "abs_final_margin")
    assert fit is not None
    intercept, slope, n = fit
    assert intercept == pytest.approx(10.0)
    assert slope == pytest.approx(2.0)
    assert n == 21


def test_ols_fit_needs_three_rows() -> None:
    assert ols_fit(games([1.0, 2.0], [3.0, 4.0]), "abs_final_margin") is None


def test_mean_se() -> None:
    n, mean, se = mean_se(pl.Series([1.0, 2.0, 3.0, None]))
    assert n == 3 and mean == pytest.approx(2.0) and se == pytest.approx(1.0 / 3**0.5)
    assert mean_se(pl.Series([5.0], dtype=pl.Float64)) == (1, 5.0, None)
    assert mean_se(pl.Series([None], dtype=pl.Float64)) == (0, None, None)


# -- multi-predictor OLS and the viewership fallback ---------------------------------------------


def quality(rows: int, *, collinear: bool = False, offset: int = 0) -> pl.DataFrame:
    """Varied, non-collinear synthetic quality measures with an exact viewership line."""
    data: dict[str, list[float | None]] = {
        "game_type": [],  # type: ignore[dict-item]
        "pregame_spread": [],
        "final_margin": [],
        "excitement_score": [],
        "wp_volatility": [],
        "viewership": [],
    }
    for i in range(offset, offset + rows):
        spread = float((i * 7) % 15) - 7.0
        margin = float((i * 11) % 23) - 9.0
        excitement = 1.0 + ((i * 5) % 13) / 2.0
        volatility = abs(margin) * 0.5 if collinear else 0.01 * ((i * 3) % 17) + 0.02 * (i % 4)
        viewers = 1000 + 50 * abs(spread) - 20 * abs(margin) + 30 * excitement + 10 * volatility
        data["game_type"].append("REG")
        data["pregame_spread"].append(spread)
        data["final_margin"].append(margin)
        data["excitement_score"].append(excitement)
        data["wp_volatility"].append(volatility)
        data["viewership"].append(viewers)
    return pl.DataFrame(data)


def test_ols_multi_recovers_all_coefficients() -> None:
    fit = ols_multi(quality(40), "viewership", VIEWERSHIP_PREDICTORS)
    assert fit is not None
    assert fit.n == 40
    assert fit.predictors == VIEWERSHIP_PREDICTORS
    assert fit.intercept == pytest.approx(1000, abs=1e-6)
    for got, want in zip(fit.coefs, (50, -20, 30, 10), strict=True):
        assert got == pytest.approx(want, abs=1e-6)


def test_ols_multi_drops_rows_with_nulls() -> None:
    frame = quality(40).with_columns(
        pl.when(pl.int_range(pl.len()) < 3)
        .then(None)
        .otherwise(pl.col("excitement_score"))
        .alias("excitement_score"),
        pl.when(pl.int_range(pl.len()) == 10)
        .then(None)
        .otherwise(pl.col("viewership"))
        .alias("viewership"),
    )
    fit = ols_multi(frame, "viewership", VIEWERSHIP_PREDICTORS)
    assert fit is not None and fit.n == 36
    assert fit.coefs[0] == pytest.approx(50, abs=1e-6)


def test_ols_multi_singular_returns_none() -> None:
    assert ols_multi(quality(40, collinear=True), "viewership", VIEWERSHIP_PREDICTORS) is None


def test_ols_multi_too_few_rows() -> None:
    assert ols_multi(quality(5), "viewership", VIEWERSHIP_PREDICTORS) is None


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        (40, VIEWERSHIP_PREDICTORS),
        (25, VIEWERSHIP_PREDICTORS),
        (24, ("abs_spread", "excitement_score")),
        (16, ("abs_spread", "excitement_score")),
        (15, ("abs_spread", "excitement_score")),
        (14, ("abs_spread",)),
        (12, ("abs_spread",)),
        (10, ("abs_spread",)),
    ],
)
def test_fit_viewership_model_fallback(rows: int, expected: tuple[str, ...]) -> None:
    fit, used = fit_model(quality(rows))
    assert fit is not None
    assert fit.predictors == expected
    assert used == "+".join(expected)
    if rows == 40:
        assert used == FULL


@pytest.mark.parametrize("rows", [8, 9, 0])
def test_fit_viewership_model_thin_era(rows: int) -> None:
    assert fit_model(quality(rows)) == (None, None)


def test_fit_viewership_model_skips_singular_model() -> None:
    fit, used = fit_model(quality(40, collinear=True))
    assert fit is not None
    assert used == "abs_spread+excitement_score"
