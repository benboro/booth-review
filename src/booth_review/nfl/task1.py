"""NFL Task 1: crews for every network group, and viewership by category (SPORT-08, SPORT-09).

`build_task1` turns the game frame into the third NFL hand-off table,
`processed/nfl_task1_crews.parquet`, with two views:

- **booth**: one row per (season, network group, booth) over every regular-season game
  the booth called for that group (`build_booths`), ordered by published rank, cited
  lead-booth override, or flagship-window inference (`rank_source` says which), the
  rest by games called. Raw columns are plain means (who is assigned the better games,
  plus `raw_mean_viewers` over rated games); adjusted columns are mean residuals
  against the league-wide expectation at the same |pregame_spread| band (how the games
  turned out relative to how they were expected to go), with n, standard error and
  `low_n` (fewer than `LOW_N` games for any adjusted outcome; no ranking is implied
  between low_n rows). WP volatility stays in the table but is not shown on the site.
  Expectations come from every regular-season game in the frame, pooled across seasons
  (nfl/adjust.py).
- **category_viewership**: one row per (view category, season, Nielsen era) over rated
  regular-season games. Viewers are modeled on the quality measures within each
  (category, era) cell only, never across a measurement break; small cells fall back to
  fewer predictors (`predictors_used` says which) and a cell too small for any model
  gets null residual stats, `low_n` and a "thin-era" review row. Figures for AGOTW and
  CBS late national are window-level (`viewership_scope` "window"); the rest are
  game-level. Nothing is normalized by coverage share (`coverage_normalized` False).

Excitement is the GEI-style score from nflverse per-play win probability (D-22),
not CFBD's excitementIndex; every row says so in `excitement_method`.

Playoff games enter the game frame only with --include-playoffs and never reach these
rows. Null measures stay null (counted by the per-measure n), never 0. This table stays
in the private vault; the NFL site ships its display fields (names resolved by person
id, means, residuals, standard errors, low_n) through `nfl-data.json`, never
`raw_mean_abs_spread` or the spread.
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
from booth_review.nfl.network_groups import NETWORK_GROUPS

TASK1_TABLE = "nfl_task1_crews"
EXCITEMENT_METHOD = "GEI-style"
VIEWERSHIP_WINDOW = "window"
VIEWERSHIP_GAME = "game"
_WINDOW_CATEGORIES = frozenset({"agotw", "cbs_national"})

#: Must equal the contract's NFL_VIEW_CATEGORIES ids (plan 07 tests the equality).
VIEW_CATEGORY_ORDER: tuple[str, ...] = (
    "agotw",
    "cbs_national",
    "snf",
    "mnf",
    "tnf",
    "thanksgiving",
    "christmas",
    "black_friday",
    "international",
    "saturday",
    "friday",
    "other",
)
_SLOT_CATEGORY: dict[str, str] = {
    "SNF": "snf",
    "MNF": "mnf",
    "TNF": "tnf",
    "Thanksgiving": "thanksgiving",
    "Christmas": "christmas",
    "Black Friday": "black_friday",
    "International": "international",
    "Saturday": "saturday",
    "Friday": "friday",
    "Other": "other",
}


def view_category_expr() -> pl.Expr:
    """The viewership category of a game; null for Sunday early and Sunday late."""
    slot = pl.col("slot_name").replace_strict(_SLOT_CATEGORY, default=None, return_dtype=pl.String)
    settled_agotw = (
        pl.col("is_agotw") & (pl.col("late_national_status") != "ambiguous")
    ).fill_null(False)
    return (
        pl.when(settled_agotw)
        .then(pl.lit("agotw"))
        .when(pl.col("is_cbs_national").fill_null(False))
        .then(pl.lit("cbs_national"))
        .otherwise(slot)
        .alias("view_category")
    )


NFL_TASK1_COLUMNS: tuple[str, ...] = (
    "view",
    "season",
    "network_group",
    "view_category",
    "booth_group",
    "booth_rank",
    "rank_source",
    "booth_pbp_person_id",
    "regular_analyst_person_id",
    "games",
    "flagship_games",
    "fill_in_games",
    "lineup_games",
    "raw_n_spread",
    "raw_mean_abs_spread",
    "raw_n_margin",
    "raw_mean_abs_margin",
    "raw_n_excitement",
    "raw_mean_excitement",
    "raw_n_volatility",
    "raw_mean_volatility",
    "raw_n_viewers",
    "raw_mean_viewers",
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
    "flagship_games",
    "fill_in_games",
    "lineup_games",
    "n_viewership",
    *(c for c in NFL_TASK1_COLUMNS if c.startswith(("raw_n_", "adj_n_"))),
}
_STR_COLUMNS = {
    "view",
    "network_group",
    "view_category",
    "booth_group",
    "rank_source",
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
    ("viewers", "viewership", "raw_mean_viewers"),
)
#: adjusted column stem -> outcome.
_ADJ_MEASURES: tuple[tuple[str, str], ...] = (
    ("margin", "abs_final_margin"),
    ("excitement", "excitement_score"),
    ("volatility", "wp_volatility"),
)

_MODEL_REVIEW_KEYS: tuple[str, ...] = (
    "kind",
    "view_category",
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


def _booth_view(games: pl.DataFrame, booths: pl.DataFrame) -> list[dict[str, object]]:
    group_order = {g.id: i for i, g in enumerate(NETWORK_GROUPS)}
    rows: list[dict[str, object]] = []
    for booth in booths.iter_rows(named=True):
        season = int(booth["season"])
        cell = games.filter(
            (pl.col("season") == season)
            & (pl.col("network_group") == booth["network_group"])
            & (pl.col("booth_pbp_person_id") == booth["booth_pbp_person_id"])
        )
        row = _base_row("booth", season)
        row.update(
            network_group=booth["network_group"],
            booth_group="lead" if booth["is_lead_booth"] else "other",
            booth_rank=booth["booth_rank"],
            rank_source=booth["rank_source"],
            booth_pbp_person_id=booth["booth_pbp_person_id"],
            regular_analyst_person_id=booth["regular_analyst_person_id"],
            games=booth["games"],
            flagship_games=booth["flagship_games"],
            fill_in_games=booth["fill_in_games"],
            lineup_games=booth["lineup_games"],
            **_measure_columns(cell),
        )
        rows.append(row)
    rows.sort(
        key=lambda r: (
            int(r["season"]),  # type: ignore[call-overload]
            group_order.get(str(r["network_group"]), 99),
            r["booth_rank"] if r["booth_rank"] is not None else 1_000_000,
            str(r["booth_pbp_person_id"]),
        )
    )
    return rows


def _category_viewership_view(
    frame: pl.DataFrame,
) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, int]]:
    rated = frame.filter(
        (pl.col("game_type") == "REG")
        & pl.col("viewership").is_not_null()
        & pl.col("view_category").is_not_null()
    )
    no_era = rated.filter(pl.col("era_id").is_null()).height
    rated = rated.filter(pl.col("era_id").is_not_null())

    rows: list[dict[str, object]] = []
    review: list[dict[str, object]] = []
    thin_eras = 0
    for category in VIEW_CATEGORY_ORDER:
        in_category = rated.filter(pl.col("view_category") == category)
        for era in sorted(in_category["era_id"].unique().to_list()):
            era_games = in_category.filter(pl.col("era_id") == era)
            fit, used = fit_viewership_model(era_games)
            if fit is None:
                thin_eras += 1
                review.append(
                    _model_review_row(
                        kind="viewership",
                        view_category=category,
                        era_id=era,
                        n=era_games.height,
                        reason="thin-era",
                    )
                )
                era_games = era_games.with_columns(pl.lit(None, dtype=pl.Float64).alias("v_resid"))
            else:
                coefs = dict(zip(fit.predictors, fit.coefs, strict=True))
                review.append(
                    _model_review_row(
                        kind="viewership",
                        view_category=category,
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
            for season in sorted(era_games["season"].unique().to_list()):
                cell = era_games.filter(pl.col("season") == season).sort("game_id")
                n_resid, resid, se = mean_se(cell["v_resid"])
                _, mean_viewers, _ = mean_se(cell["viewership"].cast(pl.Float64))
                row = _base_row("category_viewership", int(season))
                row.update(
                    view_category=category,
                    games=cell.height,
                    era_id=era,
                    predictors_used=used,
                    n_viewership=cell.height,
                    mean_viewers=mean_viewers,
                    viewership_resid=resid if fit is not None else None,
                    viewership_se=se if fit is not None else None,
                    low_n=fit is None or n_resid < LOW_N,
                    viewership_scope=(
                        VIEWERSHIP_WINDOW if category in _WINDOW_CATEGORIES else VIEWERSHIP_GAME
                    ),
                )
                rows.append(row)
    order = {c: i for i, c in enumerate(VIEW_CATEGORY_ORDER)}
    rows.sort(
        key=lambda r: (
            int(r["season"]),  # type: ignore[call-overload]
            order[str(r["view_category"])],
            str(r["era_id"]),
        )
    )
    counts = {
        "category_viewership_games": int(rated.height),
        "category_viewership_no_era": no_era,
        "thin_eras": thin_eras,
    }
    return rows, review, counts


def _ambiguous_fox_weeks(frame: pl.DataFrame) -> int:
    ambiguous = frame.filter(
        (pl.col("game_type") == "REG")
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
    frame = (
        with_derived(game_table.frame)
        .with_columns(view_category_expr())
        .sort(["season", "game_date", "game_id"])
    )
    adjusted, model_review = _adjust(frame)

    # Overrides for seasons outside this build would only add "override-no-games" noise.
    built = set(frame["season"].unique().to_list())
    overrides = {k: o for k, o in ref.lead_booth_overrides.items() if k[1] in built}
    booth_model = build_booths(frame, ref.booth_ranks, overrides)
    booths = booth_model.booths
    games = (
        booth_model.game_booths.select(
            "game_id",
            "network_group",
            "booth_pbp_person_id",
            "is_fill_in",
            "is_flagship",
        )
        .join(
            adjusted.select(
                "game_id",
                "season",
                "abs_spread",
                "abs_final_margin",
                "excitement_score",
                "wp_volatility",
                pl.col("viewership").cast(pl.Float64),
                *(_resid_col(o) for o in OUTCOMES),
            ),
            on="game_id",
            how="left",
        )
        .sort(["season", "network_group", "booth_pbp_person_id", "game_id"])
    )
    booth_rows = _booth_view(games, booths)
    view_rows, view_review, view_counts = _category_viewership_view(frame)

    reviews: dict[str, list[dict[str, object]]] = {
        "lead_booth": list(booth_model.reviews["lead_booth"]),
        "agotw_misses": list(booth_model.reviews["agotw_misses"]),
        "lead_absent_weeks": list(booth_model.reviews["lead_absent_weeks"]),
        "booth_rank_disagreements": list(booth_model.reviews["booth_rank_disagreements"]),
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
