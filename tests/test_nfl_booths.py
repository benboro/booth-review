"""NFL booth model per network group on synthetic frames (invented person ids)."""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl

from booth_review.nfl.booths import (
    LEAD_CLOSE_MARGIN,
    assign_booths,
    build_booths,
    infer_lead_booths,
)
from booth_review.nfl.reference import NflBoothRank, NflLeadBoothOverride

SUNDAY = date(2025, 10, 5)

SCHEMA = {
    "season": pl.Int64,
    "week": pl.Int64,
    "game_type": pl.String,
    "game_id": pl.String,
    "game_date": pl.Date,
    "network_id": pl.String,
    "slot_name": pl.String,
    "is_agotw": pl.Boolean,
    "is_cbs_national": pl.Boolean,
    "late_national_status": pl.String,
    "pbp_person_id": pl.String,
    "analyst_person_id": pl.String,
    "crew_source": pl.String,
}


def g(
    gid: str,
    week: int,
    pbp: str | None,
    analyst: str | None = "an-x",
    *,
    season: int = 2025,
    network: str = "fox",
    slot: str = "Sunday late",
    agotw: bool = False,
    cbs_national: bool = False,
    status: str = "single",
    game_type: str = "REG",
    crew_source: str | None = "506",
) -> dict[str, object]:
    return {
        "season": season,
        "week": week,
        "game_type": game_type,
        "game_id": gid,
        "game_date": SUNDAY + timedelta(days=7 * (week - 4)),
        "network_id": network,
        "slot_name": slot,
        "is_agotw": agotw,
        "is_cbs_national": cbs_national,
        "late_national_status": status,
        "pbp_person_id": pbp,
        "analyst_person_id": analyst,
        "crew_source": crew_source,
    }


def frame(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=SCHEMA)


def ov(season: int, person: str, network: str = "fox") -> NflLeadBoothOverride:
    return NflLeadBoothOverride(season, network, person, "reported", "https://example.com/x")


def rk(network: str, season: int, rank: int, pbp: str, analyst: str) -> NflBoothRank:
    return NflBoothRank(network, season, rank, pbp, analyst, "https://example.com/r")


def votes_frame(a: int, b: int) -> pl.DataFrame:
    rows = [g(f"a{i}", i + 1, "pb-a", agotw=True) for i in range(a)]
    rows += [g(f"b{i}", i + 1, "pb-b", agotw=True) for i in range(b)]
    return assign_booths(frame(rows))[0]


# -- assign_booths -----------------------------------------------------------------------------


def test_assign_counts_every_reg_game_of_a_group_without_a_doubleheader_gate() -> None:
    rows = [
        g("fox1", 4, "pb-a"),
        g("fox2", 5, "pb-a"),
        g("po", 4, "pb-a", game_type="POST"),
        g("none", 4, "pb-a", network="unknown"),
        g("nopbp", 5, None),
    ]
    booths, counts = assign_booths(frame(rows))
    assert booths["game_id"].to_list() == ["fox1", "fox2"]
    assert counts["booth_games"] == 2
    assert counts["no_pbp_games"] == 1


def test_assign_regular_analyst_is_mode_and_fill_in_flagged() -> None:
    rows = [g("1", 4, "pb-a", "an-1"), g("2", 5, "pb-a", "an-1"), g("3", 6, "pb-a", "an-2")]
    booths, counts = assign_booths(frame(rows))
    assert set(booths["regular_analyst_person_id"]) == {"an-1"}
    assert booths.sort("game_id")["is_fill_in"].to_list() == [False, False, True]
    assert counts["fill_in_games"] == 1


def test_lineup_filled_games_do_not_vote_for_the_modal_analyst() -> None:
    rows = [g("1", 4, "pb-a", "an-1"), g("2", 5, "pb-a", "an-1")]
    rows += [g(f"p{i}", 6 + i, "pb-a", "an-pub", crew_source="published_lineup") for i in range(3)]
    booths, counts = assign_booths(frame(rows))
    assert set(booths["regular_analyst_person_id"]) == {"an-1"}
    assert counts["fill_in_games"] == 3
    # A booth with no 506 games falls back to the published analyst.
    only = [g(f"p{i}", 4 + i, "pb-b", "an-pub", crew_source="published_lineup") for i in range(2)]
    fallback, _ = assign_booths(frame(only))
    assert set(fallback["regular_analyst_person_id"]) == {"an-pub"}
    assert not any(fallback["is_fill_in"])


def test_lineup_majority_still_reports_analyst_disagreement() -> None:
    rows = [g("1", 4, "pb-a", "an-1", agotw=True)]
    rows += [
        g(f"p{i}", 5 + i, "pb-a", "an-pub", agotw=True, crew_source="published_lineup")
        for i in range(3)
    ]
    ranks = {("fox", 2025): (rk("fox", 2025, 1, "pb-a", "an-pub"),)}
    out = build_booths(frame(rows), ranks)
    kinds = [r["kind"] for r in out.reviews["booth_rank_disagreements"]]
    assert kinds == ["analyst"]


def test_assign_mode_tie_goes_to_smallest_person_id() -> None:
    booths, _ = assign_booths(frame([g("1", 4, "pb-a", "an-2"), g("2", 5, "pb-a", "an-1")]))
    assert set(booths["regular_analyst_person_id"]) == {"an-1"}


def test_assign_null_analyst_is_not_a_fill_in_and_keeps_regular() -> None:
    booths, _ = assign_booths(frame([g("1", 4, "pb-a", "an-1"), g("2", 5, "pb-a", None)]))
    row = booths.filter(pl.col("game_id") == "2").row(0, named=True)
    assert row["is_fill_in"] is False
    assert row["regular_analyst_person_id"] == "an-1"


def test_assign_booth_never_spans_seasons() -> None:
    rows = [g("1", 4, "pb-a", "an-1"), g("2", 4, "pb-a", "an-2", season=2024)]
    booths, counts = assign_booths(frame(rows))
    assert set(booths["is_fill_in"]) == {False}
    assert counts["fill_in_games"] == 0


def test_same_pbp_on_two_groups_is_two_booths() -> None:
    rows = [g("1", 4, "pb-a", network="fox"), g("2", 5, "pb-a", network="cbs")]
    out = build_booths(frame(rows))
    assert sorted(out.booths["network_group"].to_list()) == ["cbs", "fox"]
    assert out.booths["booth_pbp_person_id"].to_list() == ["pb-a", "pb-a"]


def test_lineup_games_are_counted() -> None:
    rows = [g("1", 4, "pb-a"), g("2", 5, "pb-a", crew_source="published_lineup")]
    _, counts = assign_booths(frame(rows))
    assert counts["lineup_games"] == 1


# -- infer_lead_booths -------------------------------------------------------------------------


def test_lead_inferred_clear_for_fox() -> None:
    lead = infer_lead_booths(votes_frame(12, 3), {}, {}).row(0, named=True)
    assert lead["lead_pbp_person_id"] == "pb-a"
    assert lead["lead_source"] == "inferred"
    assert (lead["lead_votes"], lead["runner_up_votes"]) == (12, 3)
    assert lead["close"] is False
    assert LEAD_CLOSE_MARGIN == 1


def test_lead_close_and_tied_flags() -> None:
    close = infer_lead_booths(votes_frame(8, 7), {}, {}).row(0, named=True)
    assert (close["close"], close["tied"]) == (True, False)
    tied = infer_lead_booths(votes_frame(8, 8), {}, {}).row(0, named=True)
    assert (tied["close"], tied["tied"]) == (True, True)
    assert tied["lead_pbp_person_id"] == "pb-a"


def test_cbs_lead_follows_late_national_not_games() -> None:
    rows = [g(f"a{i}", i + 1, "pb-a", network="cbs", cbs_national=i < 3) for i in range(10)]
    rows += [g(f"b{i}", i + 1, "pb-b", network="cbs", cbs_national=i < 1) for i in range(14)]
    out = build_booths(frame(rows))
    by = {r["booth_pbp_person_id"]: r for r in out.booths.iter_rows(named=True)}
    assert (by["pb-a"]["booth_rank"], by["pb-a"]["rank_source"]) == (1, "inferred")
    assert by["pb-b"]["booth_rank"] == 2
    assert by["pb-a"]["flagship_games"] == 3


def test_nbc_snf_booth_leads_and_peacock_joins_group() -> None:
    rows = [g(f"s{i}", i + 1, "pb-s", network="nbc", slot="SNF") for i in range(5)]
    rows += [g(f"p{i}", i + 1, "pb-p", network="peacock") for i in range(6)]
    out = build_booths(frame(rows))
    assert out.booths["network_group"].unique().to_list() == ["nbc"]
    assert out.booths.filter(pl.col("is_lead_booth"))["booth_pbp_person_id"].to_list() == ["pb-s"]


def test_group_without_flagship_leads_by_games() -> None:
    rows = [g(f"a{i}", i + 1, "pb-a", network="netflix") for i in range(2)]
    rows += [g(f"b{i}", i + 1, "pb-b", network="netflix") for i in range(4)]
    out = build_booths(frame(rows))
    assert out.booths.filter(pl.col("is_lead_booth"))["booth_pbp_person_id"].to_list() == ["pb-b"]
    assert set(out.booths["flagship_games"]) == {0}


def test_ambiguous_agotw_casts_no_vote_but_counts_as_game() -> None:
    rows = [
        g("a1", 4, "pb-a", agotw=True, status="ambiguous"),
        g("a2", 5, "pb-a", agotw=True, status="ambiguous"),
        g("b1", 6, "pb-b", agotw=True),
    ]
    out = build_booths(frame(rows))
    lead = out.leads.row(0, named=True)
    assert lead["lead_pbp_person_id"] == "pb-b"
    assert lead["lead_votes"] == 1
    assert lead["runner_up_pbp_person_id"] is None
    a = out.booths.filter(pl.col("booth_pbp_person_id") == "pb-a").row(0, named=True)
    assert (a["games"], a["flagship_games"]) == (2, 0)


def test_published_ranks_follow_citation_and_zero_game_booth_gets_a_row() -> None:
    rows = [g(f"a{i}", i + 1, "pb-a", "an-a", agotw=True) for i in range(5)]
    rows += [g(f"b{i}", i + 1, "pb-b", "an-b") for i in range(3)]
    rows += [g(f"c{i}", i + 1, "pb-c", "an-c") for i in range(4)]
    ranks = {
        ("fox", 2025): (
            rk("fox", 2025, 1, "pb-b", "an-b"),
            rk("fox", 2025, 2, "pb-a", "an-a"),
            rk("fox", 2025, 3, "pb-z", "an-z"),
        )
    }
    out = build_booths(frame(rows), ranks)
    got = {
        r["booth_pbp_person_id"]: (r["booth_rank"], r["rank_source"], r["games"])
        for r in out.booths.iter_rows(named=True)
    }
    assert got == {
        "pb-b": (1, "published", 3),
        "pb-a": (2, "published", 5),
        "pb-z": (3, "published", 0),
        "pb-c": (4, "published", 4),
    }
    zero = out.booths.filter(pl.col("booth_pbp_person_id") == "pb-z").row(0, named=True)
    assert (zero["flagship_games"], zero["regular_analyst_person_id"]) == (0, "an-z")


def test_published_disagreements_are_reported_by_kind() -> None:
    rows = [g(f"a{i}", i + 1, "pb-a", "an-a", agotw=True) for i in range(3)]
    rows += [g("b1", 1, "pb-b", "an-b")]
    ranks = {
        ("fox", 2025): (
            rk("fox", 2025, 1, "pb-b", "an-other"),
            rk("fox", 2025, 2, "pb-a", "an-a"),
        )
    }
    out = build_booths(frame(rows), ranks)
    kinds = sorted(r["kind"] for r in out.reviews["booth_rank_disagreements"])
    assert kinds == ["analyst", "lead"]
    assert out.counts["booth_rank_disagreements"] == 2
    assert out.counts["seasons_published"] == 1


def test_override_sets_lead_and_published_wins_over_it() -> None:
    rows = [g(f"a{i}", i + 1, "pb-a", network="cbs", cbs_national=True) for i in range(4)]
    rows += [g(f"b{i}", i + 1, "pb-b", network="cbs") for i in range(2)]
    over = {("cbs", 2025): ov(2025, "pb-b", "cbs")}
    out = build_booths(frame(rows), {}, over)
    lead = out.leads.row(0, named=True)
    assert (lead["lead_pbp_person_id"], lead["lead_source"]) == ("pb-b", "override")
    assert set(out.booths["rank_source"]) == {"override"}
    ranks = {("cbs", 2025): (rk("cbs", 2025, 1, "pb-a", "an-x"),)}
    both = build_booths(frame(rows), ranks, over).leads.row(0, named=True)
    assert (both["lead_pbp_person_id"], both["lead_source"]) == ("pb-a", "published")


def test_override_without_games_is_counted() -> None:
    out = build_booths(
        frame([g("a1", 4, "pb-a", agotw=True)]), {}, {("fox", 2025): ov(2025, "pb-z")}
    )
    assert out.leads["lead_pbp_person_id"].to_list() == ["pb-z"]
    assert out.counts["override_no_games"] == 1
    assert out.counts["seasons_overridden"] == 1
    assert out.reviews["lead_booth"][0]["reason"] == "override-no-games"
    # D-23: the ignored override leaves the group ranked by games with no Lead.
    assert out.booths["booth_pbp_person_id"].to_list() == ["pb-a"]
    assert out.booths["rank_source"].to_list() == ["games"]
    assert out.booths["is_lead_booth"].to_list() == [False]


def test_lineup_games_never_vote_but_still_count() -> None:
    rows = [
        g(f"a{i}", i + 1, "pb-a", network="cbs", cbs_national=True, crew_source="published_lineup")
        for i in range(5)
    ]
    rows += [g("b1", 1, "pb-b", network="cbs", cbs_national=True)]
    out = build_booths(frame(rows))
    assert out.leads.row(0, named=True)["lead_pbp_person_id"] == "pb-b"
    a = out.booths.filter(pl.col("booth_pbp_person_id") == "pb-a").row(0, named=True)
    assert (a["games"], a["flagship_games"], a["lineup_games"]) == (5, 5, 5)
    assert out.counts["published_lineup_games"] == 5


def test_no_flagship_votes_has_no_lead_and_review() -> None:
    out = build_booths(frame([g("1", 4, "pb-a"), g("2", 4, "pb-b")]))
    assert out.leads["lead_pbp_person_id"].to_list() == [None]
    assert out.reviews["lead_booth"][0]["reason"] == "no-flagship-votes"
    # D-23: the booths still ship, ranked by games called, none labeled Lead.
    assert out.booths["booth_rank"].to_list() == [1, 2]
    assert out.booths["rank_source"].to_list() == ["games", "games"]
    assert out.booths["is_lead_booth"].to_list() == [False, False]


def test_games_ranking_orders_by_games_then_person_id() -> None:
    out = build_booths(frame([g("1", 4, "pb-b"), g("2", 5, "pb-b"), g("3", 4, "pb-a")]))
    assert out.booths["booth_pbp_person_id"].to_list() == ["pb-b", "pb-a"]
    assert out.booths["booth_rank"].to_list() == [1, 2]
    assert out.booths["booth_rank"].null_count() == 0


def test_ranks_lead_first_then_games_then_person_id() -> None:
    rows = [
        g("a1", 4, "pb-a", agotw=True),
        g("b1", 4, "pb-b"),
        g("b2", 5, "pb-b"),
        g("c1", 4, "pb-c"),
        g("d1", 4, "pb-d"),
        g("d2", 5, "pb-d"),
        g("d3", 6, "pb-d"),
    ]
    out = build_booths(frame(rows))
    ranks = dict(zip(out.booths["booth_pbp_person_id"], out.booths["booth_rank"], strict=True))
    assert ranks == {"pb-a": 1, "pb-d": 2, "pb-b": 3, "pb-c": 4}


def test_fox_agotw_misses_and_lead_absent_weeks() -> None:
    rows = [
        g("a4", 4, "pb-a", agotw=True),
        g("b4", 4, "pb-b"),
        g("a5", 5, "pb-a", agotw=True),
        g("b5", 5, "pb-b"),
        g("a6", 6, "pb-a", agotw=True),
        g("b6", 6, "pb-b"),
        g("a7", 7, "pb-a"),
        g("b7", 7, "pb-b", agotw=True),
        g("b8", 8, "pb-b", agotw=True),
        g("c8", 8, "pb-c"),
    ]
    out = build_booths(frame(rows))
    assert out.leads["lead_pbp_person_id"].to_list() == ["pb-a"]
    misses = {(m["week"], m["agotw_booth_pbp_person_id"]): m for m in out.reviews["agotw_misses"]}
    assert set(misses) == {(7, "pb-b"), (8, "pb-b")}
    assert misses[(7, "pb-b")]["lead_on_other_fox_game"] is True
    assert misses[(8, "pb-b")]["lead_on_other_fox_game"] is False
    assert out.reviews["lead_absent_weeks"] == [{"season": 2025, "week": 8}]


def test_booth_row_counts_flagship_and_fill_ins() -> None:
    rows = [
        g("a1", 4, "pb-a", "an-1", agotw=True),
        g("a2", 5, "pb-a", "an-1", agotw=True),
        g("a3", 6, "pb-a", "an-2"),
    ]
    row = build_booths(frame(rows)).booths.row(0, named=True)
    assert (row["games"], row["flagship_games"], row["fill_in_games"]) == (3, 2, 1)
    assert row["regular_analyst_person_id"] == "an-1"
