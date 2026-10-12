"""Published-lineup fill for NFL games 506 left without a crew (D-20).

The second documented exception to the 506-only crew rule, alongside
`crew_overrides.csv`: a regular-season flagship-window game with no 506 crew gets the
rank-1 booth a cited lineup release names for its network group and season. A
506-named crew always wins.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import polars as pl

from booth_review.nfl.network_groups import flagship_expr, with_network_group
from booth_review.nfl.reference import NflBoothRank


def apply_published_lineups(
    frame: pl.DataFrame,
    booth_ranks: Mapping[tuple[str, int], Sequence[NflBoothRank]],
) -> tuple[pl.DataFrame, int]:
    """Tag rows with a resolved 506 crew `crew_source = "506"` and fill listing-less flagship games.

    "Has a crew" means a resolved person id (play-by-play, analyst or sideline), the same
    fields the site ships, so `crew_source` is null exactly when the shipped `crew` is
    empty. A 506 listing whose names did not resolve still blocks the fill.
    """
    columns = frame.columns
    has_crew = (
        pl.col("pbp_person_id").is_not_null()
        | pl.col("analyst_person_id").is_not_null()
        | (pl.col("sideline_person_ids").list.len() > 0)
    )
    has_listing = has_crew | (pl.col("crew_names").list.len() > 0)
    frame = frame.with_columns(
        pl.when(has_crew).then(pl.lit("506")).otherwise(None).cast(pl.String).alias("crew_source"),
        pl.lit(None, dtype=pl.String).alias("crew_source_url"),
        (~has_listing).alias("_no_listing"),
    )
    filled = 0
    first = [rows[0] for rows in booth_ranks.values() if rows and rows[0].rank == 1]
    if first and frame.height:
        frame = with_network_group(frame).with_columns(flagship_expr())
        for row in first:
            mask = (
                (pl.col("game_type") == "REG")
                & (pl.col("network_group") == row.network)
                & (pl.col("season") == row.season)
                & pl.col("is_flagship")
                & pl.col("_no_listing")
            )
            filled += int(frame.select(mask.sum()).item())
            frame = frame.with_columns(
                pl.when(mask)
                .then(pl.lit(row.pbp_person_id))
                .otherwise(pl.col("pbp_person_id"))
                .alias("pbp_person_id"),
                pl.when(mask)
                .then(pl.lit(row.analyst_person_id))
                .otherwise(pl.col("analyst_person_id"))
                .alias("analyst_person_id"),
                pl.when(mask)
                .then(pl.lit(row.source_url))
                .otherwise(pl.col("crew_source_url"))
                .alias("crew_source_url"),
                pl.when(mask)
                .then(pl.lit("published_lineup"))
                .otherwise(pl.col("crew_source"))
                .alias("crew_source"),
            )
    return frame.select(columns), filled
