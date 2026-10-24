"""CFB booth tiering on synthetic frames (invented ids, no kickoff or slot columns)."""

from __future__ import annotations

import pytest
from cfb_booth_support import URL, by_id, crew, run, run_scenario, scenarios, tel

from booth_review.build.booth_ranks import load_cfb_booth_ranks
from booth_review.build.booths import (
    BOOTH_TIERS_SCHEMA,
    UNTIERED_COLUMNS,
)
from booth_review.errors import ReferenceTableError


def test_tiers_by_rank_and_scope() -> None:
    got = by_id(run_scenario("tiers_by_rank_and_scope"))
    assert (got["t1"]["tier"], got["t1"]["rank"]) == ("a", 1)
    assert (got["t2"]["tier"], got["t2"]["rank"]) == ("b", 2)
    assert (got["t3"]["tier"], got["t3"]["rank"]) == ("other", 3)
    assert got["t4"]["tier"] == "other"
    assert got["t4"]["rank"] is None
    assert got["t4"]["lead_network_id"] == "d-conf"
    assert got["t5"]["tier"] == "other"
    assert got["t5"]["rank"] is None
    assert got["t5"]["analyst_person_id"] == "a5"
    assert got["t5"]["lead_network_id"] is None


def test_schema_and_counts() -> None:
    result = run_scenario("schema_and_counts")
    assert dict(result.booth_tiers.schema) == BOOTH_TIERS_SCHEMA
    assert result.counts["tiered_telecasts"] == 2
    assert result.counts["a"] == 1
    assert result.counts["conference_lead"] == 1
    assert all(isinstance(v, int) for v in result.counts.values())


def test_fill_in_keeps_tier() -> None:
    got = by_id(run_scenario("fill_in_keeps_tier"))
    assert got["t1"]["tier"] == "a"
    assert got["t1"]["is_fill_in"] is True
    assert got["t1"]["analyst_person_id"] == "a1"
    assert got["t1"]["game_analyst_person_id"] == "x"


def test_regular_analyst_is_not_fill_in() -> None:
    got = by_id(run_scenario("regular_analyst_not_fill_in"))
    assert got["t1"]["is_fill_in"] is False


def test_regular_analyst_with_other_pbp_is_other_booth() -> None:
    got = by_id(run_scenario("regular_analyst_other_pbp"))
    assert got["t1"]["tier"] == "other"
    assert got["t1"]["pbp_person_id"] == "z"


def test_uncited_family_season_is_untiered() -> None:
    result = run_scenario("uncited_family_season")
    assert result.booth_tiers.is_empty()
    assert result.counts["untiered_family_seasons"] == 1


def test_other_family_never_tiered_or_reviewed() -> None:
    result = run_scenario("other_family")
    assert result.booth_tiers.is_empty()
    assert result.untiered_rows == []


def test_unmapped_network_untiered() -> None:
    result = run_scenario("unmapped_network")
    assert result.booth_tiers.is_empty()


def test_no_pbp_role_untiered_and_counted() -> None:
    result = run_scenario("no_pbp_role")
    assert result.booth_tiers.is_empty()
    assert result.counts["no_pbp"] == 1


def test_multi_pbp_lowest_position_wins() -> None:
    result = run_scenario("multi_pbp_lowest_position")
    assert by_id(result)["t1"]["pbp_person_id"] == "p1"
    assert result.counts["multi_pbp"] == 1


def test_alt_feed_crew_never_chooses_pbp() -> None:
    assert by_id(run_scenario("alt_feed_crew_never_chooses"))["t1"]["pbp_person_id"] == "p2"


def test_alt_feed_telecast_not_tiered() -> None:
    result = run_scenario("alt_feed_telecast")
    assert result.booth_tiers.is_empty()


def test_january_bowl_uses_telecast_season() -> None:
    got = by_id(run_scenario("january_bowl_season"))
    assert got["t1"]["season"] == 2024


def test_untiered_review_rows_sorted() -> None:
    result = run_scenario("untiered_review_rows")
    rows = result.untiered_rows
    assert [(r["family"], r["pbp_person_id"], r["games"]) for r in rows] == [
        ("disney", "q2", 2),
        ("disney", "q1", 1),
        ("fox", "r1", 1),
    ]
    assert set(rows[0]) == set(UNTIERED_COLUMNS)
    assert rows[0]["pbp_name"] == "Name q2"
    assert result.counts["untiered_family_seasons"] == 2
    assert result.counts["untiered_review_rows"] == 3


def test_tiered_family_season_has_no_review_rows() -> None:
    result = run_scenario("regular_analyst_not_fill_in")
    assert result.untiered_rows == []


def test_empty_inputs_keep_schema() -> None:
    result = run_scenario("other_family")
    assert dict(result.booth_tiers.schema) == BOOTH_TIERS_SCHEMA


def test_three_person_crew_with_regular_analyst_is_not_fill_in() -> None:
    # The regular analyst sits in the second analyst seat; the lowest-position analyst differs.
    got = by_id(run_scenario("three_person_with_regular"))
    assert got["t1"]["is_fill_in"] is False
    assert got["t1"]["game_analyst_person_id"] == "x"


def test_three_person_crew_without_regular_analyst_is_fill_in() -> None:
    assert by_id(run_scenario("three_person_without_regular"))["t1"]["is_fill_in"] is True


def test_cited_regular_on_no_crew_makes_every_analyst_game_a_fill_in() -> None:
    got = by_id(run_scenario("CITED_ANALYST_ON_NO_CREW"))
    assert {t: got[t]["analyst_person_id"] for t in got} == {"n1": "a2", "n2": "a2", "n3": "a2"}
    assert [got[t]["is_fill_in"] for t in ("n1", "n2", "n3")] == [True, True, False]
    assert {got[t]["tier"] for t in got} == {"b"}


def test_cited_not_modal_keeps_cited_regular_and_untiered_network_uses_its_modal() -> None:
    result = run_scenario("CITED_NOT_MODAL_UNTIERED_SECOND_NETWORK")
    got = by_id(result)
    assert {got[t]["analyst_person_id"] for t in ("g1", "g2", "g3")} == {"a1"}
    assert [got[t]["is_fill_in"] for t in ("g1", "g2", "g3")] == [False, True, True]
    assert set(got) == {"g1", "g2", "g3"}
    assert [(r["family"], r["pbp_person_id"]) for r in result.untiered_rows] == [("fox", "p1")]


@pytest.mark.parametrize("name", list(scenarios()))
def test_every_shared_scenario_keeps_the_schema(name: str) -> None:
    """Each shared case (also fed to the client parity test) runs and keeps the schema."""
    assert dict(run_scenario(name).booth_tiers.schema) == BOOTH_TIERS_SCHEMA


_LOADER_PEOPLE = """person_id,canonical_name,variants,usual_role,role_override
p1,P One,P One,pbp,
a1,A One,A One,analyst,
p2,P Two,P Two,pbp,
a2,A Two,A Two,analyst,
p3,P Three,P Three,pbp,
a3,A Three,A Three,analyst,
"""
_LOADER_NETWORKS = (
    "variant,network_id,display_name,family,tier,feed_type,season_from,season_to,priority\n"
    "D Conf,d-conf,D Conf,disney,conference,main,,,\n"
)
_LOADER_HEADER = "family,season,rank,pbp,analyst,scope,source_url\n"


def _load(tmp_path, *rows: str):
    (tmp_path / "people.csv").write_text(_LOADER_PEOPLE, encoding="utf-8")
    (tmp_path / "networks.csv").write_text(_LOADER_NETWORKS, encoding="utf-8")
    (tmp_path / "cfb_booth_ranks.csv").write_text(_LOADER_HEADER + "\n".join(rows) + "\n")
    return load_cfb_booth_ranks(tmp_path)


def test_loader_to_assignment_scoped_lead_keeps_scope(tmp_path) -> None:
    ranks = _load(
        tmp_path,
        f"disney,2024,1,P One,A One,,{URL}",
        f"disney,2024,2,P Two,A Two,,{URL}",
        f"disney,2024,,P Three,A Three,d-conf,{URL}",
    )
    got = by_id(
        run([(tel("t2"), crew("t2", "p2", "a2")), (tel("t3"), crew("t3", "p3", "a3"))], ranks)
    )
    assert got["t2"]["tier"] == "b"
    assert got["t3"]["tier"] == "other"
    assert got["t3"]["lead_network_id"] == "d-conf"


def test_loader_rejects_scoped_rank_two_before_assignment(tmp_path) -> None:
    with pytest.raises(ReferenceTableError):
        _load(
            tmp_path,
            f"disney,2024,1,P One,A One,,{URL}",
            f"disney,2024,2,P Two,A Two,d-conf,{URL}",
        )
