"""Network groups, the flagship test and the published-lineup fill (D-03, D-20, D-21)."""

from __future__ import annotations

import polars as pl
import pytest

from booth_review.nfl.lineups import apply_published_lineups
from booth_review.nfl.network_groups import (
    NETWORK_GROUP_IDS,
    NETWORK_GROUPS,
    flagship_expr,
    network_group_of,
    with_network_group,
)
from booth_review.nfl.reference import NFL_NETWORK_IDS, NflBoothRank

URL = "https://example.com/lineup"
SCHEMA = {
    "game_id": pl.String,
    "season": pl.Int64,
    "game_type": pl.String,
    "network_id": pl.String,
    "slot_name": pl.String,
    "is_agotw": pl.Boolean,
    "is_cbs_national": pl.Boolean,
    "late_national_status": pl.String,
    "crew_names": pl.List(pl.String),
    "pbp_person_id": pl.String,
    "analyst_person_id": pl.String,
    "sideline_person_ids": pl.List(pl.String),
    "crew_source": pl.String,
    "crew_source_url": pl.String,
}


def row(gid: str, network: str | None, **over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "game_id": gid,
        "season": 2025,
        "game_type": "REG",
        "network_id": network,
        "slot_name": "Sunday early",
        "is_agotw": False,
        "is_cbs_national": False,
        "late_national_status": "single",
        "crew_names": [],
        "pbp_person_id": None,
        "analyst_person_id": None,
        "sideline_person_ids": [],
        "crew_source": None,
        "crew_source_url": None,
    }
    base.update(over)
    return base


def frame(*rows: dict[str, object]) -> pl.DataFrame:
    return pl.DataFrame(list(rows), schema=SCHEMA, orient="row")


def rank1(
    network: str = "nbc", season: int = 2025
) -> dict[tuple[str, int], tuple[NflBoothRank, ...]]:
    return {(network, season): (NflBoothRank(network, season, 1, "pbp-a", "an-a", URL),)}


def test_every_network_id_in_exactly_one_group() -> None:
    members = [m for g in NETWORK_GROUPS for m in g.members]
    assert sorted(members) == sorted(NFL_NETWORK_IDS)
    assert len(members) == len(set(members))
    assert {network_group_of(n) for n in NFL_NETWORK_IDS} == set(NETWORK_GROUP_IDS)


def test_group_mapping() -> None:
    assert network_group_of("peacock") == "nbc"
    assert network_group_of("espn_plus") == "espn_abc"
    assert network_group_of("abc") == "espn_abc"
    assert network_group_of(None) is None
    out = with_network_group(frame(row("a", "abc"), row("b", "peacock"), row("c", None)))
    assert out["network_group"].to_list() == ["espn_abc", "nbc", None]


@pytest.mark.parametrize(
    ("network", "over", "expected"),
    [
        ("fox", {"is_agotw": True, "late_national_status": "settled"}, True),
        ("fox", {"is_agotw": True, "late_national_status": "ambiguous"}, False),
        ("cbs", {"is_cbs_national": True}, True),
        ("nbc", {"slot_name": "SNF"}, True),
        ("nbc", {"slot_name": "TNF"}, False),
        ("abc", {"slot_name": "MNF"}, True),
        ("prime", {"slot_name": "TNF"}, True),
        ("nfln", {"slot_name": "TNF"}, False),
    ],
)
def test_flagship(network: str, over: dict[str, object], expected: bool) -> None:
    f = with_network_group(frame(row("a", network, **over)))
    assert f.select(flagship_expr()).item() is expected


def test_no_ranks_tags_506_only() -> None:
    f = frame(
        row("a", "nbc", pbp_person_id="p"),
        row("b", "nbc", sideline_person_ids=["s"]),
        row("c", "nbc", crew_names=["Someone"]),
        row("d", "nbc"),
    )
    out, filled = apply_published_lineups(f, {})
    assert filled == 0
    # A crew is a resolved id; a listing whose names did not resolve has no source.
    assert out["crew_source"].to_list() == ["506", "506", None, None]
    assert out["pbp_person_id"].to_list() == ["p", None, None, None]
    assert out.columns == f.columns


def test_fill_only_crewless_flagship_reg_games() -> None:
    f = frame(
        row("fill", "nbc", slot_name="SNF"),
        row("crewed", "nbc", slot_name="SNF", pbp_person_id="p"),
        row("saturday", "nbc", slot_name="Saturday"),
        row("old", "nbc", slot_name="SNF", season=2024),
        row("unresolved", "nbc", slot_name="SNF", crew_names=["Unknown Name"]),
        row("post", "nbc", slot_name="SNF", game_type="POST"),
        row("peacock", "peacock", slot_name="SNF"),
    )
    out, filled = apply_published_lineups(f, rank1())
    got = {r["game_id"]: r for r in out.iter_rows(named=True)}
    assert filled == 2
    for gid in ("fill", "peacock"):
        assert got[gid]["pbp_person_id"] == "pbp-a"
        assert got[gid]["analyst_person_id"] == "an-a"
        assert got[gid]["crew_source"] == "published_lineup"
        assert got[gid]["crew_source_url"] == URL
    assert got["crewed"]["pbp_person_id"] == "p"
    assert got["crewed"]["crew_source"] == "506"
    for gid in ("saturday", "old", "post"):
        assert got[gid]["pbp_person_id"] is None
    assert got["unresolved"]["pbp_person_id"] is None
    assert got["unresolved"]["crew_source"] is None
    assert out.columns == f.columns


def test_lower_ranks_never_fill() -> None:
    ranks = {("nbc", 2025): (NflBoothRank("nbc", 2025, 2, "pbp-b", "an-b", URL),)}
    out, filled = apply_published_lineups(frame(row("a", "nbc", slot_name="SNF")), ranks)
    assert filled == 0
    assert out["pbp_person_id"].to_list() == [None]
