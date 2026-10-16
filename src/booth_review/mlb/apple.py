"""SPORT-06: the Apple lead booth against the other Apple booths, 2026 regular season.

`build_apple_booths` is a pure function: one row per Apple booth (own production only,
D-18) plus one summary row that pools "all other booths" and reports lead-minus-others
differences with a Welch standard error. Stakes lead and excitement follows (D-07).

Until Retrosheet 2026 is collected the stakes and excitement inputs are empty, every
stakes, excitement and residual value is null and `quality_status` is "pending" (D-06).
Once they are supplied the same call fills them; nothing else changes.

Rank labels come only from `mlb_booth_ranks.csv`: the lead is the booth whose
play-by-play person matches the rank-1 row. No match, or more than one, leaves the lead
null and adds a `lead_unresolved` review row. No ranking is implied between low-n rows.
Writing the tables happens elsewhere (plan 09-24).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final

import polars as pl

from booth_review.mlb.adjust import (
    band_expectations,
    mean_se,
    month_band,
    stakes_band,
    stakes_band_edges,
    welch_diff,
)
from booth_review.mlb.constants import LOW_N
from booth_review.mlb.crews import modal_analysts
from booth_review.mlb.inputs import Review
from booth_review.mlb.reference import MlbReference
from booth_review.mlb.rr_match import RRGameMatch

__all__ = ["APPLE_BOOTHS_TABLE", "APPLE_SUMMARY_TABLE", "build_apple_booths"]

APPLE_BOOTHS_TABLE: Final = "mlb_apple_booths"
APPLE_SUMMARY_TABLE: Final = "mlb_apple_summary"

APPLE_NETWORK: Final = "apple"
APPLE_SEASON: Final = 2026
_MEASURES: Final = ("stakes_raw", "stakes_adj", "excitement_raw", "excitement_adj")

_BOOTH_SCHEMA: Final[dict[str, pl.DataType | type[pl.DataType]]] = {
    "booth_key": pl.String,
    "network_id": pl.String,
    "season": pl.Int32,
    "pbp_person_id": pl.String,
    "analyst_person_ids": pl.List(pl.String),
    "rank_label": pl.String,
    "games": pl.Int64,
    "crew_listed": pl.Int64,
    "relay_crews": pl.Int64,
    "stakes_n": pl.Int64,
    "stakes_raw": pl.Float64,
    "stakes_adj": pl.Float64,
    "stakes_adj_se": pl.Float64,
    "excitement_n": pl.Int64,
    "excitement_raw": pl.Float64,
    "excitement_adj": pl.Float64,
    "excitement_adj_se": pl.Float64,
    "strength_prior": pl.Float64,
    "low_n": pl.Boolean,
    "quality_status": pl.String,
}


def _summary_schema() -> dict[str, pl.DataType | type[pl.DataType]]:
    schema: dict[str, pl.DataType | type[pl.DataType]] = {
        "season": pl.Int32,
        "lead_booth_key": pl.String,
        "apple_games": pl.Int64,
        "rr_rated": pl.Int64,
        "lead_games": pl.Int64,
        "others_games": pl.Int64,
        "quality_status": pl.String,
    }
    for m in _MEASURES:
        schema.update(
            {
                f"{m}_lead_n": pl.Int64,
                f"{m}_lead_mean": pl.Float64,
                f"{m}_others_n": pl.Int64,
                f"{m}_others_mean": pl.Float64,
                f"{m}_diff": pl.Float64,
                f"{m}_diff_se": pl.Float64,
            }
        )
    return schema


def _by_game(frame: pl.DataFrame, column: str) -> dict[str, float]:
    if frame.is_empty() or column not in frame.columns:
        return {}
    return {
        str(k): float(v) for k, v in frame.select("game_key", column).iter_rows() if v is not None
    }


_Expect = dict[int, tuple[int, float]]


def _adjusters(baseline: pl.DataFrame | None) -> tuple[_Expect, _Expect, tuple[float, ...]]:
    """(month expectations for stakes, stakes-band expectations for excitement, band edges)."""
    if baseline is None or baseline.is_empty():
        return {}, {}, ()
    base = baseline.with_columns(
        pl.col("game_date").map_elements(month_band, return_dtype=pl.Int64).alias("month")
    )
    month_exp = band_expectations(base, "pregame_stakes", "month")
    edges = stakes_band_edges(base["pregame_stakes"])
    banded = base.with_columns(
        pl.Series(
            "sband",
            [stakes_band(v, edges) for v in base["pregame_stakes"].to_list()],
            dtype=pl.Int64,
        )
    )
    exc_exp = band_expectations(banded, "wp_excitement", "sband")
    return month_exp, exc_exp, edges


def _lead_key(
    booth_pbp: Mapping[str, str | None], ref: MlbReference, reviews: list[Review]
) -> tuple[str | None, dict[str, str]]:
    """Lead booth key (None when unresolved) and booth_key -> rank label from the reference."""
    labels: dict[str, str] = {}
    pointer = f"{APPLE_NETWORK}/{APPLE_SEASON}"
    for rank in ref.booth_ranks.booths(APPLE_NETWORK, APPLE_SEASON):
        matches = (
            []
            if rank.pbp_person_id is None
            else [k for k, pbp in booth_pbp.items() if pbp == rank.pbp_person_id]
        )
        label = "Lead" if rank.rank == 1 else f"#{rank.rank}"
        if len(matches) == 1:
            labels[matches[0]] = label
        elif rank.rank == 1:
            continue
        elif len(matches) > 1:
            reviews.append(Review("apple", "rank_ambiguous", 1, f"{pointer}/{rank.rank}"))
    lead = next((k for k, v in labels.items() if v == "Lead"), None)
    if lead is None:
        reviews.append(Review("apple", "lead_unresolved", 1, pointer))
    return lead, labels


def build_apple_booths(
    games: pl.DataFrame,
    crews: pl.DataFrame,
    stakes: pl.DataFrame,
    excitement: pl.DataFrame,
    strength: pl.DataFrame,
    rr: Sequence[RRGameMatch],
    ref: MlbReference,
    *,
    baseline: pl.DataFrame | None = None,
) -> tuple[pl.DataFrame, pl.DataFrame, list[Review], dict[str, int]]:
    """(booths_frame, summary_frame, reviews, counts) for the Apple 2026 regular season.

    `crews` is the telecast frame after `assign_crews`. `stakes` (game_key,
    pregame_stakes), `excitement` (game_key, wp_excitement) and `strength` (game_key,
    strength_prior) are keyed by game; empty frames mean Retrosheet 2026 is not in yet.
    `baseline` (game_date, pregame_stakes, wp_excitement) holds the pooled
    STAKES_BASELINE_SEASONS games the adjustments compare against.
    """
    reviews: list[Review] = []
    apple = crews.filter(
        (pl.col("network_id") == APPLE_NETWORK)
        & (pl.col("season") == APPLE_SEASON)
        & (pl.col("production") == "own")
        & (pl.col("round").is_null() | (pl.col("round") == "regular"))
    )
    stakes_by, exc_by = _by_game(stakes, "pregame_stakes"), _by_game(excitement, "wp_excitement")
    strength_by = _by_game(strength, "strength_prior")
    month_exp, exc_exp, edges = _adjusters(baseline)

    per_game: list[dict[str, object]] = []
    seen: set[tuple[str, str | None]] = set()
    for row in apple.sort("game_date", "game_key", maintain_order=True).iter_rows(named=True):
        key = str(row["game_key"])
        bkey = row["booth_key"]
        if (key, bkey) in seen:
            continue
        seen.add((key, bkey))
        s, e = stakes_by.get(key), exc_by.get(key)
        s_adj = e_adj = None
        if s is not None and month_exp:
            exp = month_exp.get(month_band(row["game_date"]) or -1)
            s_adj = None if exp is None else s - exp[1]
        if e is not None and s is not None and exc_exp:
            exp = exc_exp.get(stakes_band(s, edges) or 0)
            e_adj = None if exp is None else e - exp[1]
        per_game.append(
            {
                "game_key": key,
                "booth_key": bkey,
                "pbp": row["pbp_person_id"],
                "analysts": row["analyst_person_ids"],
                "crew_source": row["crew_source"],
                "crew_named": bool(row["crew_named"]),
                "stakes_raw": s,
                "stakes_adj": s_adj,
                "excitement_raw": e,
                "excitement_adj": e_adj,
                "strength": strength_by.get(key),
            }
        )
    schema: dict[str, pl.DataType | type[pl.DataType]] = {
        "game_key": pl.String,
        "booth_key": pl.String,
        "pbp": pl.String,
        "analysts": pl.List(pl.String),
        "crew_source": pl.String,
        "crew_named": pl.Boolean,
        "stakes_raw": pl.Float64,
        "stakes_adj": pl.Float64,
        "excitement_raw": pl.Float64,
        "excitement_adj": pl.Float64,
        "strength": pl.Float64,
    }
    pg = pl.DataFrame(per_game, schema=schema)
    boothed = pg.filter(pl.col("booth_key").is_not_null())

    keys = sorted(
        {str(k) for k in boothed["booth_key"].to_list()},
        key=lambda k: (-boothed.filter(pl.col("booth_key") == k).height, k),
    )
    booth_pbp = {k: boothed.filter(pl.col("booth_key") == k)["pbp"][0] for k in keys}
    lead, labels = _lead_key(booth_pbp, ref, reviews)

    rows: list[dict[str, object]] = []
    for k in keys:
        sub = boothed.filter(pl.col("booth_key") == k)
        s_n, s_raw, _ = mean_se(sub["stakes_raw"])
        _, s_adj, s_se = mean_se(sub["stakes_adj"])
        e_n, e_raw, _ = mean_se(sub["excitement_raw"])
        _, e_adj, e_se = mean_se(sub["excitement_adj"])
        _, strength_mean, _ = mean_se(sub["strength"])
        _, season_text, pbp = k.split("|")
        rows.append(
            {
                "booth_key": k,
                "network_id": APPLE_NETWORK,
                "season": int(season_text),
                "pbp_person_id": pbp,
                "analyst_person_ids": modal_analysts(sub["analysts"].to_list()),
                "rank_label": labels.get(k),
                "games": sub.height,
                "crew_listed": sub.filter(pl.col("crew_named")).height,
                "relay_crews": sub.filter(
                    pl.col("crew_named") & (pl.col("crew_source") == "relay")
                ).height,
                "stakes_n": s_n,
                "stakes_raw": s_raw,
                "stakes_adj": s_adj,
                "stakes_adj_se": s_se,
                "excitement_n": e_n,
                "excitement_raw": e_raw,
                "excitement_adj": e_adj,
                "excitement_adj_se": e_se,
                "strength_prior": strength_mean,
                "low_n": sub.height < LOW_N,
                "quality_status": "ready" if (s_n or e_n) else "pending",
            }
        )
    booths = pl.DataFrame(rows, schema=_BOOTH_SCHEMA)

    apple_keys = set(apple["game_key"].to_list())
    rr_rated = sum(
        1 for m in rr if m.game_key in apple_keys and m.cause is None and m.viewers is not None
    )
    summary: dict[str, object] = {
        "season": APPLE_SEASON,
        "lead_booth_key": lead,
        "apple_games": len(apple_keys),
        "rr_rated": rr_rated,
        "lead_games": 0,
        "others_games": 0,
        "quality_status": "ready"
        if any(r["quality_status"] == "ready" for r in rows)
        else "pending",
    }
    lead_rows = boothed.filter(pl.col("booth_key") == lead) if lead else boothed.clear()
    other_rows = boothed.filter(pl.col("booth_key") != lead) if lead else boothed.clear()
    summary["lead_games"] = lead_rows.height
    summary["others_games"] = other_rows.height
    for m in _MEASURES:
        l_n, l_mean, _ = mean_se(lead_rows[m])
        o_n, o_mean, _ = mean_se(other_rows[m])
        diff, se = welch_diff(lead_rows[m], other_rows[m])
        summary.update(
            {
                f"{m}_lead_n": l_n,
                f"{m}_lead_mean": l_mean,
                f"{m}_others_n": o_n,
                f"{m}_others_mean": o_mean,
                f"{m}_diff": diff,
                f"{m}_diff_se": se,
            }
        )
    summary_frame = pl.DataFrame([summary], schema=_summary_schema())
    counts = {
        "apple_games": len(apple_keys),
        "booths": booths.height,
        "unboothed_games": pg.height - boothed.height,
        "rr_rated": rr_rated,
    }
    return booths, summary_frame, reviews, counts
