"""Closed-form adjustment primitives for the MLB result tables (SPORT-06, SPORT-07).

A booth's games are compared with what the league produces in comparable games:
pregame stakes against the pooled mean in the same calendar-month band, excitement
against the pooled mean in the same stakes band (band edges are quantiles of the
baseline stakes, `STAKES_BAND_QUANTILES`). A band with fewer than `MIN_BAND_N` games
pools with its neighbour toward the centre of the band list. Missing values stay null.
Float sums keep row order (per-band filters, no group_by), so a rebuild is bit-identical.
No numpy or scipy.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date

import polars as pl

from booth_review.mlb.constants import MIN_BAND_N, STAKES_BAND_QUANTILES

__all__ = [
    "band_expectations",
    "mean_se",
    "month_band",
    "residuals",
    "stakes_band",
    "stakes_band_edges",
    "welch_diff",
]


def month_band(day: date | None) -> int | None:
    """Calendar-month band of a game date."""
    return None if day is None else day.month


def stakes_band_edges(
    pool: pl.Series, quantiles: Sequence[float] = STAKES_BAND_QUANTILES
) -> tuple[float, ...]:
    """Linear-interpolated quantiles of the pooled baseline stakes; () for an empty pool."""
    values = sorted(float(v) for v in pool.drop_nulls().to_list())
    if not values:
        return ()
    edges: list[float] = []
    for q in quantiles:
        pos = q * (len(values) - 1)
        lo = math.floor(pos)
        hi = min(lo + 1, len(values) - 1)
        edges.append(values[lo] + (values[hi] - values[lo]) * (pos - lo))
    return tuple(edges)


def stakes_band(value: float | None, edges: Sequence[float]) -> int | None:
    """Index of the stakes band holding `value` (number of edges at or below it)."""
    if value is None:
        return None
    return sum(1 for edge in edges if value >= edge)


def band_expectations(
    frame: pl.DataFrame,
    outcome: str,
    band_col: str = "band",
    *,
    min_n: int = MIN_BAND_N,
) -> dict[int, tuple[int, float]]:
    """Band -> (n, mean outcome) over rows with a band and an outcome.

    Thin bands (n < min_n) pool with the neighbour toward the centre of the band list,
    outermost thin group first; a merged band reports the pooled n and mean.
    """
    data = frame.filter(pl.col(band_col).is_not_null() & pl.col(outcome).is_not_null())
    present = sorted({int(b) for b in data[band_col].unique().to_list()})
    sums: dict[int, tuple[int, float]] = {}
    for b in present:
        values = data.filter(pl.col(band_col) == b)[outcome].cast(pl.Float64)
        sums[b] = (values.len(), float(values.sum()))

    groups: list[list[int]] = [[b] for b in present]

    def group_n(group: list[int]) -> int:
        return sum(sums[b][0] for b in group)

    while len(groups) > 1:
        center = (len(groups) - 1) / 2
        thin = [j for j, grp in enumerate(groups) if group_n(grp) < min_n]
        if not thin:
            break
        j = max(thin, key=lambda k: (abs(k - center), -k))
        k = j + 1 if j < center else j - 1
        lo, hi = min(j, k), max(j, k)
        groups[lo : hi + 1] = [groups[lo] + groups[hi]]

    out: dict[int, tuple[int, float]] = {}
    for grp in groups:
        n = group_n(grp)
        if n == 0:
            continue
        mean = sum(sums[b][1] for b in grp) / n
        for b in grp:
            out[b] = (n, mean)
    return out


def residuals(
    frame: pl.DataFrame,
    outcome: str,
    expectations: Mapping[int, tuple[int, float]],
    band_col: str = "band",
) -> pl.Series:
    """outcome - expected(band) per row; a null outcome, band or unknown band gives null."""
    out: list[float | None] = []
    for y, b in zip(frame[outcome].to_list(), frame[band_col].to_list(), strict=True):
        exp = expectations.get(int(b)) if b is not None else None
        out.append(None if y is None or exp is None else float(y) - exp[1])
    return pl.Series(f"{outcome}_resid", out, dtype=pl.Float64)


def mean_se(values: pl.Series) -> tuple[int, float | None, float | None]:
    """(n, mean, sample sd / sqrt(n)) over non-null values; se None when n < 2."""
    clean = [float(v) for v in values.drop_nulls().to_list()]
    n = len(clean)
    if n == 0:
        return 0, None, None
    mean = sum(clean) / n
    if n < 2:
        return n, mean, None
    var = sum((v - mean) ** 2 for v in clean) / (n - 1)
    return n, mean, math.sqrt(var) / math.sqrt(n)


def welch_diff(a: pl.Series, b: pl.Series) -> tuple[float | None, float | None]:
    """(mean a - mean b, sqrt(s1^2/n1 + s2^2/n2)); (None, None) with under 2 values a side."""
    n1, m1, se1 = mean_se(a)
    n2, m2, se2 = mean_se(b)
    if n1 < 2 or n2 < 2 or m1 is None or m2 is None or se1 is None or se2 is None:
        return None, None
    return m1 - m2, math.sqrt(se1**2 + se2**2)
