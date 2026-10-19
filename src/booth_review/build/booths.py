"""Phase 10 per-telecast CFB booth tiers.

Defines the frame the site-data build ships `lookups.booths` and the per-game
`booth` index from. The assignment function that fills it lands in plan 10-04;
until then `BuildTables.booth_tiers` is empty and every booth ships null.
"""

from __future__ import annotations

import polars as pl

from booth_review.build.telecasts import TELECASTS_SCHEMA

# One row per tiered telecast; untiered telecasts have no row.
BOOTH_TIERS_SCHEMA: dict[str, pl.DataType] = {
    "telecast_id": TELECASTS_SCHEMA["telecast_id"],
    "family": pl.Utf8(),
    "season": TELECASTS_SCHEMA["season"],
    "pbp_person_id": pl.Utf8(),
    # The booth's regular analyst.
    "analyst_person_id": pl.Utf8(),
    # The analyst on this game's crew (differs from the regular one on a fill-in).
    "game_analyst_person_id": pl.Utf8(),
    "is_fill_in": pl.Boolean(),
    "rank": pl.Int64(),
    # One of "a", "b", "other".
    "tier": pl.Utf8(),
    "lead_network_id": pl.Utf8(),
}


def empty_booth_tiers_frame() -> pl.DataFrame:
    return pl.DataFrame(schema=BOOTH_TIERS_SCHEMA)
