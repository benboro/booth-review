"""Phase 10 per-telecast CFB booth tiers.

Defines the frame the site-data build ships `lookups.booths` and the per-game
`booth` index from, and `assign_cfb_booths`, which fills it from the cited booth
order (never inferred). A family-season with no cited rows stays untiered.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import polars as pl

from booth_review.build.booth_ranks import CFB_BOOTH_FAMILIES, CfbBoothRank
from booth_review.build.telecasts import TELECASTS_SCHEMA
from booth_review.resolve.networks import NetworkTable

REVIEW_CFB_BOOTHS_UNTIERED = "review_cfb_booths_untiered"
UNTIERED_COLUMNS = (
    "family",
    "season",
    "pbp_person_id",
    "pbp_name",
    "analyst_person_id",
    "analyst_name",
    "games",
)

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


@dataclass(frozen=True)
class CfbBoothAssignment:
    booth_tiers: pl.DataFrame
    untiered_rows: list[dict[str, object]]
    counts: dict[str, int]


def _modal(values: Sequence[str]) -> str | None:
    """Most common value; ties go to the lowest id. None when empty."""
    if not values:
        return None
    counted = Counter(values)
    top = max(counted.values())
    return min(v for v, n in counted.items() if n == top)


def _lowest_position(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return min(rows, key=lambda r: (r["crew_position"] is None, r["crew_position"] or 0))


def assign_cfb_booths(
    telecasts: pl.DataFrame,
    telecast_people: pl.DataFrame,
    people: pl.DataFrame,
    networks: NetworkTable,
    ranks: Mapping[tuple[str, int], Sequence[CfbBoothRank]],
) -> CfbBoothAssignment:
    """Tier every big-four main-feed telecast from the cited order.

    Family comes from the telecast's own network, so a booth's tier holds on
    every channel of its family. Rank 1 is "a", rank 2 "b", every other cited
    or uncited booth "other". A family-season with no cited rows is untiered
    and feeds the private review list. Nothing is inferred from quality,
    volume or time of day.
    """
    counts = dict.fromkeys(
        (
            "tiered_telecasts",
            "a",
            "b",
            "other",
            "conference_lead",
            "fill_in",
            "no_pbp",
            "multi_pbp",
            "untiered_family_seasons",
            "untiered_review_rows",
        ),
        0,
    )
    net_info = networks.networks()
    pbp_rows: dict[str, list[dict[str, Any]]] = {}
    analyst_rows: dict[str, list[dict[str, Any]]] = {}
    for row in telecast_people.filter(pl.col("feed_type") == "main").iter_rows(named=True):
        if row["role"] == "pbp":
            pbp_rows.setdefault(row["telecast_id"], []).append(row)
        elif row["role"] == "analyst":
            analyst_rows.setdefault(row["telecast_id"], []).append(row)

    # (family, season, telecast_id, pbp, game_analyst)
    entries: list[tuple[str, int, str, str, str | None]] = []
    for trow in telecasts.filter(
        (pl.col("feed_type") == "main") & pl.col("game_id").is_not_null()
    ).iter_rows(named=True):
        net = net_info.get(trow["network_id"]) if trow["network_id"] is not None else None
        family = net[1] if net is not None else None
        if family not in CFB_BOOTH_FAMILIES:
            continue
        tid = trow["telecast_id"]
        pbps = pbp_rows.get(tid, [])
        if not pbps:
            counts["no_pbp"] += 1
            continue
        if len(pbps) > 1:
            counts["multi_pbp"] += 1
        pbp = str(_lowest_position(pbps)["person_id"])
        analysts = analyst_rows.get(tid, [])
        game_analyst = str(_lowest_position(analysts)["person_id"]) if analysts else None
        entries.append((family, int(trow["season"]), tid, pbp, game_analyst))

    modal_analyst: dict[tuple[str, int, str], str | None] = {}
    grouped: dict[tuple[str, int, str], list[str]] = {}
    for family, season, _tid, pbp, game_analyst in entries:
        grouped.setdefault((family, season, pbp), [])
        if game_analyst is not None:
            grouped[(family, season, pbp)].append(game_analyst)
    for key, values in grouped.items():
        modal_analyst[key] = _modal(values)

    tier_rows: list[dict[str, Any]] = []
    untiered_games: dict[tuple[str, int, str], int] = {}
    untiered_seasons: set[tuple[str, int]] = set()
    for family, season, tid, pbp, game_analyst in entries:
        cited = ranks.get((family, season))
        if not cited:
            untiered_seasons.add((family, season))
            key = (family, season, pbp)
            untiered_games[key] = untiered_games.get(key, 0) + 1
            continue
        match = next((c for c in cited if c.pbp_person_id == pbp), None)
        if match is None:
            tier, rank, lead = "other", None, None
            regular = modal_analyst[(family, season, pbp)]
        else:
            rank, lead = match.rank, match.scope_network_id
            tier = "a" if rank == 1 else "b" if rank == 2 else "other"
            if tier != "other":
                lead = None
            regular = match.analyst_person_id
        fill_in = game_analyst is not None and game_analyst != regular
        counts["tiered_telecasts"] += 1
        counts[tier] += 1
        if lead is not None:
            counts["conference_lead"] += 1
        if fill_in:
            counts["fill_in"] += 1
        tier_rows.append(
            {
                "telecast_id": tid,
                "family": family,
                "season": season,
                "pbp_person_id": pbp,
                "analyst_person_id": regular,
                "game_analyst_person_id": game_analyst,
                "is_fill_in": fill_in,
                "rank": rank,
                "tier": tier,
                "lead_network_id": lead,
            }
        )

    names = {
        str(r["person_id"]): r["canonical_name"]
        for r in people.select("person_id", "canonical_name").iter_rows(named=True)
    }
    order = {f: i for i, f in enumerate(CFB_BOOTH_FAMILIES)}
    review: list[dict[str, object]] = []
    for family, season, pbp in untiered_games:
        analyst = modal_analyst[(family, season, pbp)]
        review.append(
            {
                "family": family,
                "season": season,
                "pbp_person_id": pbp,
                "pbp_name": names.get(pbp),
                "analyst_person_id": analyst,
                "analyst_name": names.get(analyst) if analyst is not None else None,
                "games": untiered_games[(family, season, pbp)],
            }
        )
    review.sort(
        key=lambda r: (
            order[str(r["family"])],
            int(str(r["season"])),
            -int(str(r["games"])),
            str(r["pbp_person_id"]),
        )
    )
    counts["untiered_family_seasons"] = len(untiered_seasons)
    counts["untiered_review_rows"] = len(review)
    frame = pl.DataFrame(tier_rows, schema=BOOTH_TIERS_SCHEMA)
    return CfbBoothAssignment(frame, review, counts)
