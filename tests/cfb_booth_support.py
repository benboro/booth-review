"""Shared synthetic CFB booth inputs for tests/test_cfb_booths.py and the Phase 14 in-page
parity test (tests/e2e/test_site_crew_groups.py). Invented ids only.

`scenarios()` is the one case list both tests read: tests/test_cfb_booths.py asserts each
case against `assign_cfb_booths`, and the parity test feeds every case, in the shape
site_data.py ships, to the client grouping. A case added here reaches both."""

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


Item = tuple[dict[str, object], list[dict[str, object]]]
Scenario = tuple[list[Item], Mapping[tuple[str, int], Sequence[CfbBoothRank]]]


def seat(tid: str, person: str, pos: int, role: str = "analyst") -> dict[str, object]:
    """One main-feed crew row (for a third seat beyond `crew`'s pbp and analyst)."""
    return {
        "telecast_id": tid,
        "person_id": person,
        "role": role,
        "feed_type": "main",
        "crew_position": pos,
    }


def scenarios() -> dict[str, Scenario]:
    """Every shared case, built fresh on each call: name -> (items, ranks)."""
    cited_not_modal: list[Item] = [
        (tel("g1"), crew("g1", "p1", "a1")),
        (tel("g2"), crew("g2", "p1", "x")),
        (tel("g3"), crew("g3", "p1", "x")),
    ]
    out: dict[str, Scenario] = {
        "tiers_by_rank_and_scope": (
            [
                (tel("t1"), crew("t1", "p1", "a1")),
                (tel("t2", "d-two"), crew("t2", "p2", "a2")),
                (tel("t3"), crew("t3", "p3", "a3")),
                (tel("t4", "d-one"), crew("t4", "p4", "a4")),
                (tel("t5"), crew("t5", "p5", "a5")),
            ],
            RANKS,
        ),
        "schema_and_counts": (
            [(tel("t1"), crew("t1", "p1", "a1")), (tel("t4"), crew("t4", "p4", "a4"))],
            RANKS,
        ),
        # The cited analyst a1 is on no crew row, so site_data ships the booth's analyst as null.
        "fill_in_keeps_tier": ([(tel("t1"), crew("t1", "p1", "x"))], RANKS),
        "regular_analyst_not_fill_in": ([(tel("t1"), crew("t1", "p1", "a1"))], RANKS),
        "regular_analyst_other_pbp": ([(tel("t1"), crew("t1", "z", "a1"))], RANKS),
        "uncited_family_season": ([(tel("t1", "f-one"), crew("t1", "p1", "a1"))], RANKS),
        "other_family": ([(tel("t1", "c-one"), crew("t1", "p1", "a1"))], RANKS),
        "unmapped_network": ([(tel("t1", "nope"), crew("t1", "p1", "a1"))], RANKS),
        "no_pbp_role": ([(tel("t1"), crew("t1", "p1", None, role="sideline"))], RANKS),
        "multi_pbp_lowest_position": (
            [(tel("t1"), crew("t1", "p2", None, pos=2) + crew("t1", "p1", None, pos=1))],
            RANKS,
        ),
        "alt_feed_crew_never_chooses": (
            [(tel("t1"), crew("t1", "p1", None, feed="alt") + crew("t1", "p2", None))],
            RANKS,
        ),
        "alt_feed_telecast": (
            [(tel("t1", feed="alt"), crew("t1", "p1", "a1", feed="alt"))],
            RANKS,
        ),
        "january_bowl_season": ([(tel("t1", season=2024), crew("t1", "p1", "a1"))], RANKS),
        "three_person_with_regular": (
            [(tel("t1"), [*crew("t1", "p1", "x"), seat("t1", "a1", 3)])],
            RANKS,
        ),
        "three_person_without_regular": (
            [(tel("t1"), [*crew("t1", "p1", "x"), seat("t1", "y", 3)])],
            RANKS,
        ),
        "untiered_review_rows": (
            [
                (tel("t1"), crew("t1", "q1", "b1")),
                (tel("t2"), crew("t2", "q2", "b2")),
                (tel("t3"), crew("t3", "q2", "b2")),
                (tel("t4", "f-one"), crew("t4", "r1", "c1")),
            ],
            {},
        ),
        "CITED_NOT_MODAL": (cited_not_modal, RANKS),
        # The same pbp and analysts on an untiered network too (fox 2024 has no cited rows):
        # there the regular falls back to that group's own modal analyst.
        "CITED_NOT_MODAL_UNTIERED_SECOND_NETWORK": (
            [
                *cited_not_modal,
                (tel("h1", "f-one"), crew("h1", "p1", "a1")),
                (tel("h2", "f-one"), crew("h2", "p1", "x")),
                (tel("h3", "f-one"), crew("h3", "p1", "x")),
            ],
            RANKS,
        ),
        # A cited booth whose regular analyst never appears: every game with an analyst is a
        # fill-in, and the booth's shipped analyst is null.
        "CITED_ANALYST_ON_NO_CREW": (
            [
                (tel("n1"), crew("n1", "p2", "x")),
                (tel("n2"), crew("n2", "p2", "y")),
                (tel("n3"), crew("n3", "p2", None)),
            ],
            RANKS,
        ),
        "MODAL_TIE": (
            [
                (tel("m1", "f-one"), crew("m1", "z", "m")),
                (tel("m2", "f-one"), crew("m2", "z", "k")),
            ],
            RANKS,
        ),
        "TWO_FAMILIES": (
            [
                (tel("d-one-g"), crew("d-one-g", "p9", "a9")),
                (tel("f-one-g", "f-one"), crew("f-one-g", "p9", "a9")),
            ],
            RANKS,
        ),
        "NON_BIG_FOUR": (
            [
                (tel("c1", "c-one"), crew("c1", "p9", "a9")),
                (tel("c2", "c-two"), crew("c2", "p9", "a9")),
            ],
            RANKS,
        ),
        "two_seasons_and_no_analyst": (
            [
                (tel("t1"), crew("t1", "p1", "a1")),
                (tel("t2", season=2023), crew("t2", "p1", "a1")),
                (tel("t3"), crew("t3", "p2", None)),
            ],
            RANKS,
        ),
    }
    return out


def scenario_items(name: str) -> list[Item]:
    return scenarios()[name][0]


def run_scenario(name: str) -> CfbBoothAssignment:
    items, ranks = scenarios()[name]
    return run(items, ranks)
