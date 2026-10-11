"""Closed-form adjustment primitives for NFL Task 1 (D-04).

The adjusted booth view compares each game's outcome with what the league as a
whole produces at the same pregame spread. The primary expectation is banded: the
league-wide mean of the outcome within an `|pregame_spread|` band, over every
regular-season game in the frame with a spread and an outcome (pooled across
seasons; a season alone gives too few games per band). A band with fewer than
`MIN_BAND_N` games pools with its neighbor toward the center of the band list.
A single-predictor OLS line (`outcome ~ |spread|`, from polars cov/var) is the
cross-check written to the model review file.

The AGOTW-only viewership view regresses viewers on the four D-04 quality measures
within one Nielsen era (`ols_multi`, normal equations solved in pure Python; the
project uses polars only, no numpy). When an era is too small for every term,
`fit_viewership_model` falls back to fewer predictors in a fixed order and says
which predictors it used.

A missing value stays null: a null outcome or spread gives a null residual, never 0.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import polars as pl

#: Lower edges of the |pregame_spread| bands: [0,3), [3,6.5), [6.5,10), [10,inf).
#: 3 and 7 are the key NFL margins; 10 separates clear mismatches.
SPREAD_BAND_EDGES = (0.0, 3.0, 6.5, 10.0)

#: A band with fewer games than this pools with its neighbor toward the center.
MIN_BAND_N = 50

#: Booth or booth-season cells with fewer games than this are flagged low_n; no
#: ranking is implied between low_n rows.
LOW_N = 8

#: Outcomes adjusted for the pregame spread in the booth view.
OUTCOMES: tuple[str, ...] = ("abs_final_margin", "excitement_score", "wp_volatility")

#: The D-04 quality measures the AGOTW viewership model uses.
VIEWERSHIP_PREDICTORS = ("abs_spread", "abs_final_margin", "excitement_score", "wp_volatility")

#: Models tried in order when an era is small. Final margin and WP volatility drop
#: first because both track excitement closely; the pregame spread stays last because
#: it is the expectation the adjusted view controls for.
VIEWERSHIP_FALLBACKS: tuple[tuple[str, ...], ...] = (
    VIEWERSHIP_PREDICTORS,
    ("abs_spread", "excitement_score"),
    ("abs_spread",),
)

#: A model with k predictors needs at least this many usable rows per term,
#: intercept included: 25 rows for the full model, 15 for two, 10 for one.
VIEWERSHIP_MIN_N_PER_TERM = 5

#: Pivot tolerance (relative to the largest X'X diagonal) below which the normal
#: equations are treated as singular.
_SINGULAR_TOL = 1e-9


@dataclass(frozen=True)
class OlsMultiFit:
    intercept: float
    coefs: tuple[float, ...]
    predictors: tuple[str, ...]
    n: int

    def predict(self, frame: pl.DataFrame) -> pl.Series:
        """Fitted values; null when any predictor is null."""
        expr = pl.lit(self.intercept, dtype=pl.Float64)
        for name, coef in zip(self.predictors, self.coefs, strict=True):
            expr = expr + pl.col(name).cast(pl.Float64) * coef
        return with_derived(frame).select(expr.alias("fitted"))["fitted"]


def with_derived(frame: pl.DataFrame) -> pl.DataFrame:
    """Add abs_spread (|pregame_spread|) and abs_final_margin (|final_margin|) if absent."""
    extra: list[pl.Expr] = []
    if "abs_spread" not in frame.columns and "pregame_spread" in frame.columns:
        extra.append(pl.col("pregame_spread").cast(pl.Float64).abs().alias("abs_spread"))
    if "abs_final_margin" not in frame.columns and "final_margin" in frame.columns:
        extra.append(pl.col("final_margin").cast(pl.Float64).abs().alias("abs_final_margin"))
    return frame.with_columns(extra) if extra else frame


def band_of(abs_spread: float) -> int:
    """Index of the |spread| band holding this value."""
    band = 0
    for i, edge in enumerate(SPREAD_BAND_EDGES):
        if abs_spread >= edge:
            band = i
    return band


def _band_expr() -> pl.Expr:
    expr = pl.lit(0, dtype=pl.Int64)
    for i, edge in enumerate(SPREAD_BAND_EDGES[1:], start=1):
        expr = pl.when(pl.col("abs_spread") >= edge).then(pl.lit(i, dtype=pl.Int64)).otherwise(expr)
    return expr


def _usable(frame: pl.DataFrame, outcome: str) -> pl.DataFrame:
    data = with_derived(frame)
    if "game_type" in data.columns:
        data = data.filter(pl.col("game_type") == "REG")
    return data.filter(pl.col("abs_spread").is_not_null() & pl.col(outcome).is_not_null())


def band_counts(frame: pl.DataFrame, outcome: str) -> dict[int, int]:
    """Usable games per band before any merging (every band present, possibly 0)."""
    data = _usable(frame, outcome)
    bands = data.select(_band_expr().alias("band"))["band"].to_list()
    return {i: bands.count(i) for i in range(len(SPREAD_BAND_EDGES))}


def band_expectations(frame: pl.DataFrame, outcome: str) -> dict[int, tuple[int, float]]:
    """Band -> (n, mean outcome) over REG games with a spread and an outcome.

    Thin bands (n < MIN_BAND_N) pool with the neighbor toward the center of the band
    list, outermost thin group first; a merged band reports the pooled n and mean.
    A band whose pooled group has no games is absent (its residuals are null).
    """
    data = _usable(frame, outcome).with_columns(_band_expr().alias("band"))
    # Per-band filters rather than a group_by keep the float sums in row order, so a
    # rebuild is byte-identical.
    sums: dict[int, tuple[int, float]] = {}
    for i in range(len(SPREAD_BAND_EDGES)):
        values = data.filter(pl.col("band") == i)[outcome].cast(pl.Float64)
        sums[i] = (values.len(), float(values.sum()) if values.len() else 0.0)

    groups: list[list[int]] = [[i] for i in sorted(sums)]

    def group_n(group: list[int]) -> int:
        return sum(sums[b][0] for b in group)

    while len(groups) > 1:
        center = (len(groups) - 1) / 2
        thin = [j for j, grp in enumerate(groups) if group_n(grp) < MIN_BAND_N]
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
    frame: pl.DataFrame, outcome: str, expectations: Mapping[int, tuple[int, float]]
) -> pl.Series:
    """outcome - expected(band) per row; null outcome, spread or band -> null."""
    data = with_derived(frame)
    mapping = {band: mean for band, (_, mean) in expectations.items()}
    expected = (
        pl.when(pl.col("abs_spread").is_null())
        .then(None)
        .otherwise(_band_expr().replace_strict(mapping, default=None, return_dtype=pl.Float64))
    )
    return data.select((pl.col(outcome).cast(pl.Float64) - expected).alias(f"{outcome}_resid"))[
        f"{outcome}_resid"
    ]


def ols_fit(frame: pl.DataFrame, outcome: str) -> tuple[float, float, int] | None:
    """(intercept, slope, n) for outcome ~ |spread| over REG games; None below 3 rows."""
    data = _usable(frame, outcome)
    n = data.height
    if n < 3:
        return None
    stats = data.select(
        pl.cov("abs_spread", outcome).alias("cov"),
        pl.col("abs_spread").var().alias("var"),
        pl.col("abs_spread").mean().alias("mx"),
        pl.col(outcome).cast(pl.Float64).mean().alias("my"),
    ).row(0, named=True)
    var = stats["var"]
    if var is None or var <= 0:
        return None
    slope = float(stats["cov"]) / float(var)
    return float(stats["my"]) - slope * float(stats["mx"]), slope, n


def mean_se(values: pl.Series) -> tuple[int, float | None, float | None]:
    """(n, mean, sample sd / sqrt(n)) over non-null values; se None when n < 2."""
    clean = values.drop_nulls().cast(pl.Float64)
    n = clean.len()
    if n == 0:
        return 0, None, None
    mean = float(clean.mean())  # type: ignore[arg-type]
    if n < 2:
        return n, mean, None
    sd = float(clean.std(ddof=1))  # type: ignore[arg-type]
    return n, mean, sd / math.sqrt(n)


def _solve(matrix: list[list[float]], rhs: list[float]) -> list[float] | None:
    """Gaussian elimination with partial pivoting; None when singular."""
    size = len(rhs)
    a = [[*row, rhs[i]] for i, row in enumerate(matrix)]
    scale = max(abs(matrix[i][i]) for i in range(size))
    if scale == 0:
        return None
    tol = _SINGULAR_TOL * scale
    for col in range(size):
        pivot = max(range(col, size), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < tol:
            return None
        a[col], a[pivot] = a[pivot], a[col]
        for r in range(col + 1, size):
            factor = a[r][col] / a[col][col]
            if factor:
                for c in range(col, size + 1):
                    a[r][c] -= factor * a[col][c]
    x = [0.0] * size
    for r in range(size - 1, -1, -1):
        acc = a[r][size] - sum(a[r][c] * x[c] for c in range(r + 1, size))
        x[r] = acc / a[r][r]
    return x


def ols_multi(frame: pl.DataFrame, outcome: str, predictors: Sequence[str]) -> OlsMultiFit | None:
    """outcome ~ predictors with an intercept; rows with any null dropped.

    None when n < len(predictors) + 2 or the normal equations are singular.
    """
    names = tuple(predictors)
    data = (
        with_derived(frame)
        .select([pl.col(c).cast(pl.Float64) for c in (*names, outcome)])
        .drop_nulls()
    )
    n = data.height
    if n < len(names) + 2:
        return None
    data = data.with_columns(pl.lit(1.0, dtype=pl.Float64).alias("__one"))
    terms: list[pl.Expr] = [pl.col("__one"), *(pl.col(c) for c in names)]
    size = len(terms)
    sums: list[pl.Expr] = []
    for i in range(size):
        for j in range(i, size):
            sums.append((terms[i] * terms[j]).sum().alias(f"xx_{i}_{j}"))
        sums.append((terms[i] * pl.col(outcome)).sum().alias(f"xy_{i}"))
    row = data.select(sums).row(0, named=True)
    xtx = [[0.0] * size for _ in range(size)]
    for i in range(size):
        for j in range(i, size):
            xtx[i][j] = xtx[j][i] = float(row[f"xx_{i}_{j}"])
    xty = [float(row[f"xy_{i}"]) for i in range(size)]
    solution = _solve(xtx, xty)
    if solution is None:
        return None
    return OlsMultiFit(intercept=solution[0], coefs=tuple(solution[1:]), predictors=names, n=n)


def fit_viewership_model(
    frame: pl.DataFrame, outcome: str = "viewership"
) -> tuple[OlsMultiFit | None, str | None]:
    """First VIEWERSHIP_FALLBACKS model with enough rows and a non-singular fit.

    Returns the fit and its predictors joined with "+"; (None, None) when the frame
    is too small for even the one-predictor model.
    """
    data = with_derived(frame)
    for predictors in VIEWERSHIP_FALLBACKS:
        usable = data.select([pl.col(c) for c in (*predictors, outcome)]).drop_nulls().height
        if usable < VIEWERSHIP_MIN_N_PER_TERM * (len(predictors) + 1):
            continue
        fit = ols_multi(data, outcome, predictors)
        if fit is not None:
            return fit, "+".join(predictors)
    return None, None
