"""NFL Task 1: Fox's AGOTW crew vs. Fox's other crews (SPORT-04; D-01 to D-04, D-22).

`build_task1` turns the game frame into the third NFL hand-off table,
`processed/nfl_task1_crews.parquet`, with two views:

- **booth**: one row per (season, Fox booth) on Fox doubleheader Sundays (plan 16's
  `build_booths`), the lead booth first (booth_rank 1, the AGOTW crew) and the
  other booths compared one at a time (rank 2, 3, ...), plus one `others_pooled`
  row per season that has other booths. Raw columns are plain means (who is
  assigned the better games); adjusted columns are mean residuals against the
  league-wide expectation at the same |pregame_spread| band (how the games turned
  out relative to how they were expected to go), with n, standard error and
  `low_n` (fewer than `LOW_N` games for any adjusted outcome; no ranking is implied
  between low_n rows). Expectations come from every regular-season game in the
  frame, pooled across seasons (nfl/adjust.py).
- **agotw_viewership**: AGOTW games with a headline Ratings Reference figure, one row
  per (season, booth that called AGOTW, Nielsen era). Viewers are modeled on the
  D-04 quality measures within each era only, never across a measurement break;
  small eras fall back to fewer predictors (`predictors_used` says which) and an
  era too small for any model gets null residual stats and a "thin-era" review row.
  Figures are window-level (`viewership_scope` "window") and not normalized by
  coverage share, because no coverage-share source exists (`coverage_normalized`
  False on every row). Non-AGOTW games get no viewership comparison.

Excitement is the GEI-style score from nflverse per-play win probability (D-22),
not CFBD's excitementIndex; every row says so in `excitement_method`.

Playoff games enter the game frame only with --include-playoffs, and even then
never reach these rows: playoffs have no doubleheader Sundays and 506 has no
playoff pages, so no playoff crew exists. Null measures stay null (counted by the
per-measure n), never 0. This table stays in the private vault; the NFL site ships
its display fields (names resolved by person id, means, residuals, standard errors,
low_n) through `nfl-data.json` (999.5), never `raw_mean_abs_spread` or the spread.
"""

from __future__ import annotations

from collections.abc import Sequence

import polars as pl

from booth_review.nfl.adjust import (
    LOW_N,
    OUTCOMES,
    SPREAD_BAND_EDGES,
    VIEWERSHIP_PREDICTORS,
    band_counts,
    band_expectations,
    fit_viewership_model,
    mean_se,
    ols_fit,
    residuals,
    with_derived,
)
from booth_review.nfl.booths import build_booths
from booth_review.nfl.games import NflGameTable, NflReference

TASK1_TABLE = "nfl_task1_crews"
EXCITEMENT_METHOD = "GEI-style"
VIEWERSHIP_SCOPE = "window"

NFL_TASK1_COLUMNS: tuple[str, ...] = (
    "view",
    "season",
    "booth_group",
    "booth_rank",
    "booth_pbp_person_id",
    "regular_analyst_person_id",
    "games",
    "fill_in_games",
    "raw_n_spread",
    "raw_mean_abs_spread",
    "raw_n_margin",
    "raw_mean_abs_margin",
    "raw_n_excitement",
    "raw_mean_excitement",
    "raw_n_volatility",
    "raw_mean_volatility",
    "adj_n_margin",
    "adj_margin_resid",
    "adj_margin_se",
    "adj_n_excitement",
    "adj_excitement_resid",
    "adj_excitement_se",
    "adj_n_volatility",
    "adj_volatility_resid",
    "adj_volatility_se",
    "low_n",
    "predictors_used",
    "era_id",
    "n_viewership",
    "mean_viewers",
    "viewership_resid",
    "viewership_se",
    "viewership_scope",
    "coverage_normalized",
    "excitement_method",
)

_INT_COLUMNS = {
    "season",
    "booth_rank",
    "games",
    "fill_in_games",
    "n_viewership",
    *(c for c in NFL_TASK1_COLUMNS if c.startswith(("raw_n_", "adj_n_"))),
}
_STR_COLUMNS = {
    "view",
    "booth_group",
    "booth_pbp_person_id",
    "regular_analyst_person_id",
    "predictors_used",
    "era_id",
    "viewership_scope",
    "excitement_method",
}
_BOOL_COLUMNS = {"low_n", "coverage_normalized"}

NFL_TASK1_SCHEMA: dict[str, pl.DataType | type[pl.DataType]] = {
    c: (
        pl.Int64
        if c in _INT_COLUMNS
        else pl.String
        if c in _STR_COLUMNS
        else pl.Boolean
        if c in _BOOL_COLUMNS
        else pl.Float64
    )
    for c in NFL_TASK1_COLUMNS
}

#: raw column suffix -> game-frame measure.
_RAW_MEASURES: tuple[tuple[str, str, str], ...] = (
    ("spread", "abs_spread", "raw_mean_abs_spread"),
    ("margin", "abs_final_margin", "raw_mean_abs_margin"),
    ("excitement", "excitement_score", "raw_mean_excitement"),
    ("volatility", "wp_volatility", "raw_mean_volatility"),
)
#: adjusted column stem -> outcome.
_ADJ_MEASURES: tuple[tuple[str, str], ...] = (
    ("margin", "abs_final_margin"),
    ("excitement", "excitement_score"),
    ("volatility", "wp_volatility"),
)

_MODEL_REVIEW_KEYS: tuple[str, ...] = (
    "kind",
    "outcome",
    "band",
    "band_low",
    "band_high",
    "band_raw_n",
    "n",
    "expected",
    "intercept",
    "slope",
    "era_id",
    "predictors_used",
    *(f"coef_{p}" for p in VIEWERSHIP_PREDICTORS),
    "reason",
)

_BOOTH_GROUP_ORDER = {"lead": 0, "other": 1, "others_pooled": 2}


def _resid_col(outcome: str) -> str:
    return f"resid_{outcome}"


def _base_row(view: str, season: int) -> dict[str, object]:
    row: dict[str, object] = dict.fromkeys(NFL_TASK1_COLUMNS)
    row.update(
        view=view,
        season=season,
        coverage_normalized=False,
        excitement_method=EXCITEMENT_METHOD,
    )
    return row


def _measure_columns(games: pl.DataFrame) -> dict[str, object]:
    """Raw means and adjusted residual stats over one cell's games (pre-sorted)."""
    out: dict[str, object] = {}
    for stem, measure, mean_col in _RAW_MEASURES:
        n, mean, _ = mean_se(games[measure])
        out[f"raw_n_{stem}"] = n
        out[mean_col] = mean
    adj_ns: list[int] = []
    for stem, outcome in _ADJ_MEASURES:
        n, mean, se = mean_se(games[_resid_col(outcome)])
        out[f"adj_n_{stem}"] = n
        out[f"adj_{stem}_resid"] = mean
        out[f"adj_{stem}_se"] = se
        adj_ns.append(n)
    out["low_n"] = min(adj_ns) < LOW_N
    return out


def _model_review_row(**values: object) -> dict[str, object]:
    row: dict[str, object] = dict.fromkeys(_MODEL_REVIEW_KEYS)
    row.update(values)
    return row


def _band_bounds(band: int) -> tuple[float, float | None]:
    low = SPREAD_BAND_EDGES[band]
    high = SPREAD_BAND_EDGES[band + 1] if band + 1 < len(SPREAD_BAND_EDGES) else None
    return low, high


def _adjust(frame: pl.DataFrame) -> tuple[pl.DataFrame, list[dict[str, object]]]:
    """Add per-game residual columns; return the band and OLS review rows."""
    review: list[dict[str, object]] = []
    resid_cols: list[pl.Series] = []
    for outcome in OUTCOMES:
        expectations = band_expectations(frame, outcome)
        raw = band_counts(frame, outcome)
        for band in range(len(SPREAD_BAND_EDGES)):
            low, high = _band_bounds(band)
            n, expected = expectations.get(band, (0, None))
            review.append(
                _model_review_row(
                    kind="band",
                    outcome=outcome,
                    band=band,
                    band_low=low,
                    band_high=high,
                    band_raw_n=raw[band],
                    n=n,
                    expected=expected,
                )
            )
        fit = ols_fit(frame, outcome)
        review.append(
            _model_review_row(
                kind="ols",
                outcome=outcome,
                n=fit[2] if fit else 0,
                intercept=fit[0] if fit else None,
                slope=fit[1] if fit else None,
            )
        )
        resid_cols.append(residuals(frame, outcome, expectations).alias(_resid_col(outcome)))
    return frame.with_columns(resid_cols), review


def _booth_view(
    games: pl.DataFrame, booths: pl.DataFrame, has_lead: dict[int, bool]
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for booth in booths.iter_rows(named=True):
        season = int(booth["season"])
        cell = games.filter(
            (pl.col("season") == season)
            & (pl.col("booth_pbp_person_id") == booth["booth_pbp_person_id"])
        )
        row = _base_row("booth", season)
        row.update(
            booth_group="lead" if booth["is_lead_booth"] else "other",
            booth_rank=booth["booth_rank"],
            booth_pbp_person_id=booth["booth_pbp_person_id"],
            regular_analyst_person_id=booth["regular_analyst_person_id"],
            games=cell.height,
            fill_in_games=int(cell["is_fill_in"].sum()),
            **_measure_columns(cell),
        )
        rows.append(row)
    for season in sorted(has_lead):
        others = games.filter((pl.col("season") == season) & ~pl.col("is_lead_booth"))
        if others.height == 0:
            continue
        row = _base_row("booth", season)
        row.update(
            booth_group="others_pooled",
            games=others.height,
            fill_in_games=int(others["is_fill_in"].sum()),
            **_measure_columns(others),
        )
        rows.append(row)
    rows.sort(
        key=lambda r: (
            int(r["season"]),  # type: ignore[call-overload]
            _BOOTH_GROUP_ORDER[str(r["booth_group"])],
            r["booth_rank"] if r["booth_rank"] is not None else 1_000_000,
            str(r["booth_pbp_person_id"]),
        )
    )
    return rows


def _viewership_view(
    frame: pl.DataFrame, game_booths: pl.DataFrame, booths: pl.DataFrame
) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, int]]:
    agotw = frame.filter(
        (pl.col("game_type") == "REG")
        & pl.col("is_agotw").fill_null(False)
        & (pl.col("late_national_status") != "ambiguous")
        & pl.col("viewership").is_not_null()
    )
    no_era = agotw.filter(pl.col("era_id").is_null()).height
    agotw = agotw.filter(pl.col("era_id").is_not_null())
    booth_info = {
        (int(r["season"]), str(r["booth_pbp_person_id"])): r for r in booths.iter_rows(named=True)
    }
    booth_of = game_booths.select("game_id", "booth_pbp_person_id", "is_fill_in")

    rows: list[dict[str, object]] = []
    review: list[dict[str, object]] = []
    thin_eras = 0
    no_booth = 0
    for era in sorted(agotw["era_id"].unique().to_list()):
        era_games = agotw.filter(pl.col("era_id") == era)
        fit, used = fit_viewership_model(era_games)
        if fit is None:
            thin_eras += 1
            review.append(
                _model_review_row(
                    kind="viewership", era_id=era, n=era_games.height, reason="thin-era"
                )
            )
            era_games = era_games.with_columns(pl.lit(None, dtype=pl.Float64).alias("v_resid"))
        else:
            coefs = dict(zip(fit.predictors, fit.coefs, strict=True))
            review.append(
                _model_review_row(
                    kind="viewership",
                    era_id=era,
                    n=fit.n,
                    intercept=fit.intercept,
                    predictors_used=used,
                    **{f"coef_{p}": coefs.get(p) for p in VIEWERSHIP_PREDICTORS},
                )
            )
            fitted = fit.predict(era_games)
            era_games = era_games.with_columns(
                (pl.col("viewership").cast(pl.Float64) - fitted).alias("v_resid")
            )
        joined = era_games.join(booth_of, on="game_id", how="left")
        no_booth += joined.filter(pl.col("booth_pbp_person_id").is_null()).height
        joined = joined.filter(pl.col("booth_pbp_person_id").is_not_null())
        keys = (
            joined.select("season", "booth_pbp_person_id")
            .unique()
            .sort(["season", "booth_pbp_person_id"])
        )
        for season, pbp in keys.iter_rows():
            cell = joined.filter(
                (pl.col("season") == season) & (pl.col("booth_pbp_person_id") == pbp)
            ).sort("game_id")
            info = booth_info.get((int(season), str(pbp)))
            n_resid, resid, se = mean_se(cell["v_resid"])
            _, mean_viewers, _ = mean_se(cell["viewership"])
            row = _base_row("agotw_viewership", int(season))
            row.update(
                booth_group=(
                    ("lead" if info["is_lead_booth"] else "other") if info is not None else None
                ),
                booth_rank=info["booth_rank"] if info is not None else None,
                booth_pbp_person_id=pbp,
                regular_analyst_person_id=(
                    info["regular_analyst_person_id"] if info is not None else None
                ),
                games=cell.height,
                fill_in_games=int(cell["is_fill_in"].sum()),
                era_id=era,
                predictors_used=used,
                n_viewership=cell.height,
                mean_viewers=mean_viewers,
                viewership_resid=resid if fit is not None else None,
                viewership_se=se if fit is not None else None,
                low_n=fit is None or n_resid < LOW_N,
                viewership_scope=VIEWERSHIP_SCOPE,
            )
            rows.append(row)
    rows.sort(
        key=lambda r: (
            int(r["season"]),  # type: ignore[call-overload]
            str(r["era_id"]),
            r["booth_rank"] if r["booth_rank"] is not None else 1_000_000,
            str(r["booth_pbp_person_id"]),
        )
    )
    counts = {
        "agotw_viewership_games": int(agotw.height),
        "agotw_viewership_no_booth": no_booth,
        "agotw_viewership_no_era": no_era,
        "thin_eras": thin_eras,
    }
    return rows, review, counts


def _single_header_weeks(frame: pl.DataFrame) -> list[dict[str, object]]:
    """Sundays with Fox regular-season games but no Fox doubleheader (skipped in Task 1)."""
    single = frame.filter(
        (pl.col("game_type") == "REG")
        & (pl.col("network_id") == "fox")
        & ~pl.col("fox_dh_sunday").fill_null(False)
        & (pl.col("game_date").dt.weekday() == 7)
    )
    grouped = (
        single.group_by(["season", "week", "game_date"])
        .agg(pl.len().alias("fox_games"))
        .sort(["season", "game_date", "week"])
    )
    return [dict(r) for r in grouped.iter_rows(named=True)]


def _ambiguous_fox_weeks(frame: pl.DataFrame) -> int:
    ambiguous = frame.filter(
        (pl.col("game_type") == "REG")
        & pl.col("fox_dh_sunday").fill_null(False)
        & (pl.col("network_id") == "fox")
        & (pl.col("late_national_status") == "ambiguous")
    )
    return ambiguous.select("season", "week").unique().height


def _frame(rows: Sequence[dict[str, object]]) -> pl.DataFrame:
    if not rows:
        return pl.DataFrame(schema=NFL_TASK1_SCHEMA)
    return pl.DataFrame(list(rows), schema=NFL_TASK1_SCHEMA, orient="row").select(NFL_TASK1_COLUMNS)


def build_task1(
    game_table: NflGameTable, ref: NflReference
) -> tuple[pl.DataFrame, dict[str, list[dict[str, object]]], dict[str, int]]:
    """The nfl_task1_crews frame, its review lists and int counts."""
    # A fixed row order keeps every float sum, and so the parquet bytes, stable.
    frame = with_derived(game_table.frame).sort(["season", "game_date", "game_id"])
    adjusted, model_review = _adjust(frame)

    # Overrides for seasons outside this build would only add "override-no-games" noise.
    built = set(frame["season"].unique().to_list())
    overrides = {s: o for s, o in ref.lead_booth_overrides.items() if s in built}
    booth_model = build_booths(frame, overrides)
    booths = booth_model.booths
    lead_flags = booths.select("season", "booth_pbp_person_id", "is_lead_booth")
    games = (
        booth_model.game_booths.select("game_id", "booth_pbp_person_id", "is_fill_in")
        .join(
            adjusted.select(
                "game_id",
                "season",
                "abs_spread",
                "abs_final_margin",
                "excitement_score",
                "wp_volatility",
                *(_resid_col(o) for o in OUTCOMES),
            ),
            on="game_id",
            how="left",
        )
        .join(lead_flags, on=["season", "booth_pbp_person_id"], how="left")
        .sort(["season", "booth_pbp_person_id", "game_id"])
    )
    has_lead = {
        int(r["season"]): r["lead_pbp_person_id"] is not None
        for r in booth_model.leads.iter_rows(named=True)
    }
    booth_rows = _booth_view(games, booths, has_lead)
    view_rows, view_review, view_counts = _viewership_view(frame, booth_model.game_booths, booths)
    single_weeks = _single_header_weeks(frame)

    reviews: dict[str, list[dict[str, object]]] = {
        "lead_booth": list(booth_model.reviews["lead_booth"]),
        "agotw_misses": list(booth_model.reviews["agotw_misses"]),
        "lead_absent_weeks": list(booth_model.reviews["lead_absent_weeks"]),
        "single_header_weeks": single_weeks,
        "task1_model": model_review + view_review,
    }
    counts: dict[str, int] = {
        **{k: int(v) for k, v in booth_model.counts.items()},
        "ambiguous_fox_weeks": _ambiguous_fox_weeks(frame),
        "task1_booth_rows": len(booth_rows),
        "task1_viewership_rows": len(view_rows),
        **view_counts,
    }
    return _frame(booth_rows + view_rows), reviews, counts
