"""Shared synthetic CFB booth inputs for tests/test_cfb_booths.py and the Phase 14 in-page
parity test (tests/e2e/test_site_crew_groups.py). Invented ids only."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import polars as pl

from booth_review.build.booth_ranks import CfbBoothRank
from booth_review.build.booths import CfbBoothAssignment, assign_cfb_booths
from booth_review.resolve.networks import NetworkRow, NetworkTable

URL = "https://example.com/lineup"


def net_row(nid: str, family: str) -> NetworkRow:
    return NetworkRow(nid, nid, nid, family, "cable", "main", None, None, None)


NETWORKS = NetworkTable(
    [
        net_row("d-one", "disney"),
        net_row("d-two", "disney"),
        net_row("d-conf", "disney"),
        net_row("f-one", "fox"),
        net_row("c-one", "conference"),
    ]
)


def rank(
    r: int | None, pbp: str, analyst: str, *, scope: str | None = None, family: str = "disney"
) -> CfbBoothRank:
    return CfbBoothRank(family, 2024, r, pbp, analyst, scope, URL)


RANKS = {
    ("disney", 2024): (
        rank(1, "p1", "a1"),
        rank(2, "p2", "a2"),
        rank(3, "p3", "a3"),
        rank(None, "p4", "a4", scope="d-conf"),
    )
}


def tel(tid: str, net: str = "d-one", season: int = 2024, feed: str = "main") -> dict[str, object]:
    return {
        "telecast_id": tid,
        "game_id": 1,
        "season": season,
        "network_id": net,
        "feed_type": feed,
    }


def crew(
    tid: str,
    pbp: str | None,
    analyst: str | None = None,
    *,
    feed: str = "main",
    pos: int = 1,
    role: str = "pbp",
) -> list[dict[str, object]]:
    rows = []
    if pbp:
        rows.append(
            {
                "telecast_id": tid,
                "person_id": pbp,
                "role": role,
                "feed_type": feed,
                "crew_position": pos,
            }
        )
    if analyst:
        rows.append(
            {
                "telecast_id": tid,
                "person_id": analyst,
                "role": "analyst",
                "feed_type": feed,
                "crew_position": pos + 1,
            }
        )
    return rows


def frames(
    items: list[tuple[dict[str, object], list[dict[str, object]]]],
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    tels = pl.DataFrame([t for t, _ in items])
    tp_schema = {
        "telecast_id": pl.Utf8,
        "person_id": pl.Utf8,
        "role": pl.Utf8,
        "feed_type": pl.Utf8,
        "crew_position": pl.Int64,
    }
    tp = pl.DataFrame([r for _, rows in items for r in rows], schema=tp_schema)
    ids = sorted({str(r["person_id"]) for _, rows in items for r in rows})
    people = pl.DataFrame({"person_id": ids, "canonical_name": [f"Name {i}" for i in ids]})
    return tels, tp, people


def run(
    items: list[tuple[dict[str, object], list[dict[str, object]]]],
    ranks: Mapping[tuple[str, int], Sequence[CfbBoothRank]] = RANKS,
) -> CfbBoothAssignment:
    tels, tp, people = frames(items)
    return assign_cfb_booths(tels, tp, people, NETWORKS, ranks)


def by_id(result: CfbBoothAssignment) -> dict[str, dict[str, object]]:
    return {r["telecast_id"]: r for r in result.booth_tiers.iter_rows(named=True)}
