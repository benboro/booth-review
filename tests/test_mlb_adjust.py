"""MLB adjustment primitives on synthetic frames."""

from __future__ import annotations

import math
from datetime import date

import polars as pl

from booth_review.mlb.adjust import (
    band_expectations,
    mean_se,
    month_band,
    residuals,
    stakes_band,
    stakes_band_edges,
    welch_diff,
)
from booth_review.mlb.constants import MIN_BAND_N


def _frame(bands: list[int | None], values: list[float | None]) -> pl.DataFrame:
    return pl.DataFrame({"band": bands, "y": values}, schema={"band": pl.Int64, "y": pl.Float64})


def test_stakes_band_edges_are_quantiles_of_the_pool() -> None:
    pool = pl.Series([float(i) for i in range(101)] + [None])
    edges = stakes_band_edges(pool)
    assert edges == (50.0, 80.0, 95.0)
    assert stakes_band_edges(pl.Series([], dtype=pl.Float64)) == ()


def test_stakes_band_of_a_value() -> None:
    edges = (1.0, 2.0, 3.0)
    assert [stakes_band(v, edges) for v in (0.5, 1.0, 2.5, 9.0)] == [0, 1, 2, 3]
    assert stakes_band(None, edges) is None


def test_month_band_is_the_calendar_month() -> None:
    assert month_band(date(2025, 7, 4)) == 7
    assert month_band(None) is None


def test_thin_band_pools_toward_the_centre() -> None:
    big = MIN_BAND_N
    bands = [0] * 5 + [1] * big + [2] * big
    values = [10.0] * 5 + [2.0] * big + [4.0] * big
    exp = band_expectations(_frame(bands, values), "y")
    # band 0 is thin and merges into band 1
    assert exp[0] == exp[1]
    assert exp[0][0] == 5 + big
    assert math.isclose(exp[0][1], (50.0 + 2.0 * big) / (5 + big))
    assert exp[2] == (big, 4.0)


def test_residual_of_a_null_outcome_or_band_is_null() -> None:
    frame = _frame([1, 1, None, 1], [1.0, 3.0, 5.0, None])
    exp = band_expectations(frame, "y", min_n=1)
    out = residuals(frame, "y", exp)
    assert out.to_list() == [-1.0, 1.0, None, None]


def test_mean_se() -> None:
    assert mean_se(pl.Series([], dtype=pl.Float64)) == (0, None, None)
    n, mean, se = mean_se(pl.Series([1.0, 3.0, None]))
    assert (n, mean) == (2, 2.0)
    assert se is not None and math.isclose(se, math.sqrt(2) / math.sqrt(2))
    assert mean_se(pl.Series([4.0])) == (1, 4.0, None)


def test_welch_diff() -> None:
    a = pl.Series([1.0, 2.0, 3.0])
    b = pl.Series([5.0, 7.0, None])
    diff, se = welch_diff(a, b)
    assert diff == 2.0 - 6.0
    assert se is not None
    assert math.isclose(se, math.sqrt(1.0 / 3 + 2.0 / 2))
    assert welch_diff(a, pl.Series([1.0])) == (None, None)
    assert welch_diff(pl.Series([], dtype=pl.Float64), a) == (None, None)


def test_two_runs_are_bit_identical() -> None:
    bands = [i % 3 for i in range(900)]
    values = [math.sin(i) * 0.1 + (i % 7) for i in range(900)]
    frame = _frame(bands, values)
    first = band_expectations(frame, "y")
    second = band_expectations(frame, "y")
    assert first == second
    assert residuals(frame, "y", first).to_list() == residuals(frame, "y", second).to_list()
