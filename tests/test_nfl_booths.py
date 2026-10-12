"""Fox booth model on synthetic frames (invented person ids)."""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl

from booth_review.nfl.booths import (
    LEAD_CLOSE_MARGIN,
    assign_booths,
    build_booths,
    infer_lead_booths,
)
from booth_review.nfl.reference import NflLeadBoothOverride

SUNDAY = date(2015, 10, 4)


def g(
    gid: str,
    week: int,
    pbp: str | None,
    analyst: str | None = "an-x",
    *,
    season: int = 2015,
    dh: bool = True,
    agotw: bool = False,
    status: str = "single",
    network: str = "fox",
    game_type: str = "REG",
    day_offset: int = 0,
) -> dict[str, object]:
    return {
        "season": season,
        "week": week,
        "game_type": game_type,
        "game_id": gid,
        "game_date": SUNDAY + timedelta(days=7 * (week - 4) + day_offset),
        "network_id": network,
        "fox_dh_sunday": dh,
        "is_agotw": agotw,
        "late_national_status": status,
        "pbp_person_id": pbp,
        "analyst_person_id": analyst,
    }


def frame(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(
        rows,
        schema={
            "season": pl.Int64,
            "week": pl.Int64,
            "game_type": pl.String,
            "game_id": pl.String,
            "game_date": pl.Date,
            "network_id": pl.String,
            "fox_dh_sunday": pl.Boolean,
            "is_agotw": pl.Boolean,
            "late_national_status": pl.String,
            "pbp_person_id": pl.String,
            "analyst_person_id": pl.String,
        },
    )


def ov(season: int, person: str) -> NflLeadBoothOverride:
    return NflLeadBoothOverride(season, "fox", person, "reported", "https://example.com/x")


def votes_frame(a: int, b: int) -> pl.DataFrame:
    rows = [g(f"a{i}", i + 1, "pb-a", agotw=True) for i in range(a)]
    rows += [g(f"b{i}", i + 1, "pb-b", agotw=True) for i in range(b)]
    return assign_booths(frame(rows))[0]


# -- assign_booths -----------------------------------------------------------------------------


def test_assign_only_fox_dh_reg_games_and_counts_single_header_weeks() -> None:
    rows = [
        g("dh1", 4, "pb-a"),
        g("cbs", 4, "pb-c", network="cbs"),
        g("po", 4, "pb-a", game_type="POST"),
        g("s1", 5, "pb-a", dh=False),
        g("s2", 5, "pb-b", dh=False),
        g("s3", 6, "pb-a", dh=False),
        g("mon", 6, "pb-a", dh=False, day_offset=1),
    ]
    booths, counts = assign_booths(frame(rows))
    assert booths["game_id"].to_list() == ["dh1"]
    assert counts["fox_dh_games"] == 1
    assert counts["skipped_single_header_weeks"] == 2


def test_assign_regular_analyst_is_mode_and_fill_in_flagged() -> None:
    rows = [
        g("1", 4, "pb-a", "an-1"),
        g("2", 5, "pb-a", "an-1"),
        g("3", 6, "pb-a", "an-2"),
    ]
    booths, counts = assign_booths(frame(rows))
    assert set(booths["regular_analyst_person_id"]) == {"an-1"}
    assert booths.sort("game_id")["is_fill_in"].to_list() == [False, False, True]
    assert counts["fill_in_games"] == 1


def test_assign_mode_tie_goes_to_smallest_person_id() -> None:
    rows = [g("1", 4, "pb-a", "an-2"), g("2", 5, "pb-a", "an-1")]
    booths, _ = assign_booths(frame(rows))
    assert set(booths["regular_analyst_person_id"]) == {"an-1"}


def test_assign_null_analyst_is_not_a_fill_in_and_keeps_regular() -> None:
    rows = [g("1", 4, "pb-a", "an-1"), g("2", 5, "pb-a", None)]
    booths, _ = assign_booths(frame(rows))
    row = booths.filter(pl.col("game_id") == "2").row(0, named=True)
    assert row["is_fill_in"] is False
    assert row["regular_analyst_person_id"] == "an-1"


def test_assign_null_pbp_excluded_and_counted() -> None:
    booths, counts = assign_booths(frame([g("1", 4, None), g("2", 4, "pb-a")]))
    assert booths["game_id"].to_list() == ["2"]
    assert counts["no_pbp_games"] == 1


def test_assign_same_analyst_different_voice_is_two_booths() -> None:
    booths, _ = assign_booths(frame([g("1", 4, "pb-a", "an-1"), g("2", 4, "pb-b", "an-1")]))
    assert booths["booth_pbp_person_id"].n_unique() == 2


def test_assign_booth_never_spans_seasons() -> None:
    rows = [g("1", 4, "pb-a", "an-1"), g("2", 4, "pb-a", "an-2", season=2016)]
    booths, counts = assign_booths(frame(rows))
    assert set(booths["is_fill_in"]) == {False}
    assert counts["fill_in_games"] == 0


# -- infer_lead_booths -------------------------------------------------------------------------


def test_lead_inferred_clear() -> None:
    lead = infer_lead_booths(votes_frame(12, 3), {}).row(0, named=True)
    assert lead["lead_pbp_person_id"] == "pb-a"
    assert lead["lead_source"] == "inferred"
    assert (lead["lead_votes"], lead["runner_up_votes"]) == (12, 3)
    assert lead["close"] is False
    assert LEAD_CLOSE_MARGIN == 1


def test_lead_close_and_tied_flags() -> None:
    close = infer_lead_booths(votes_frame(8, 7), {}).row(0, named=True)
    assert close["close"] is True
    assert close["tied"] is False
    tied = infer_lead_booths(votes_frame(8, 8), {}).row(0, named=True)
    assert tied["tied"] is True
    assert tied["close"] is True
    assert tied["lead_pbp_person_id"] == "pb-a"


def test_lead_tie_prefers_more_dh_games() -> None:
    rows = [
        g("a1", 4, "pb-a", agotw=True),
        g("b1", 5, "pb-b", agotw=True),
        g("b2", 6, "pb-b"),
    ]
    lead = infer_lead_booths(assign_booths(frame(rows))[0], {}).row(0, named=True)
    assert lead["tied"] is True
    assert lead["lead_pbp_person_id"] == "pb-b"


def test_lead_override_wins_and_is_cited_source() -> None:
    lead = infer_lead_booths(votes_frame(12, 3), {2015: ov(2015, "pb-b")}).row(0, named=True)
    assert lead["lead_pbp_person_id"] == "pb-b"
    assert lead["lead_source"] == "override"
    assert lead["close"] is False


def test_ambiguous_weeks_cast_no_vote() -> None:
    rows = [
        g("a1", 4, "pb-a", agotw=True, status="ambiguous"),
        g("a2", 5, "pb-a", agotw=True, status="ambiguous"),
        g("b1", 6, "pb-b", agotw=True),
    ]
    lead = infer_lead_booths(assign_booths(frame(rows))[0], {}).row(0, named=True)
    assert lead["lead_pbp_person_id"] == "pb-b"
    assert lead["lead_votes"] == 1
    assert lead["runner_up_pbp_person_id"] is None


# -- build_booths ------------------------------------------------------------------------------


def test_no_votes_no_override_has_no_lead_and_review() -> None:
    out = build_booths(frame([g("1", 4, "pb-a"), g("2", 4, "pb-b")]), {})
    assert out.leads["lead_pbp_person_id"].to_list() == [None]
    assert out.reviews["lead_booth"][0]["reason"] == "no-agotw-votes"
    assert out.booths["booth_rank"].to_list() == [None, None]


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
    out = build_booths(frame(rows), {})
    ranks = dict(zip(out.booths["booth_pbp_person_id"], out.booths["booth_rank"], strict=True))
    assert ranks == {"pb-a": 1, "pb-d": 2, "pb-b": 3, "pb-c": 4}
    assert out.booths.filter(pl.col("is_lead_booth"))["booth_pbp_person_id"].to_list() == ["pb-a"]


def test_agotw_misses_and_lead_absent_weeks() -> None:
    rows = [
        g("a4", 4, "pb-a", agotw=True),
        g("b4", 4, "pb-b"),
        g("a5", 5, "pb-a", agotw=True),
        g("b5", 5, "pb-b"),
        g("a6", 6, "pb-a", agotw=True),
        g("b6", 6, "pb-b"),
        # week 7: pb-b calls AGOTW while the lead also calls another Fox game
        g("a7", 7, "pb-a"),
        g("b7", 7, "pb-b", agotw=True),
        # week 8: the lead is off entirely
        g("b8", 8, "pb-b", agotw=True),
        g("c8", 8, "pb-c"),
    ]
    out = build_booths(frame(rows), {})
    assert out.leads["lead_pbp_person_id"].to_list() == ["pb-a"]
    misses = {(m["week"], m["agotw_booth_pbp_person_id"]): m for m in out.reviews["agotw_misses"]}
    assert set(misses) == {(7, "pb-b"), (8, "pb-b")}
    assert misses[(7, "pb-b")]["lead_on_other_fox_game"] is True
    assert misses[(8, "pb-b")]["lead_on_other_fox_game"] is False
    assert out.reviews["lead_absent_weeks"] == [{"season": 2015, "week": 8}]
    assert out.counts["agotw_miss_weeks"] == 2
    assert out.counts["lead_absent_weeks"] == 1


def test_override_without_games_reviewed_and_lead_follows_override() -> None:
    out = build_booths(frame([g("a1", 4, "pb-a", agotw=True)]), {2015: ov(2015, "pb-z")})
    assert out.leads["lead_pbp_person_id"].to_list() == ["pb-z"]
    assert out.counts["override_no_games"] == 1
    assert out.counts["seasons_overridden"] == 1
    assert out.reviews["lead_booth"][0]["reason"] == "override-no-games"


def test_close_and_tied_counts_and_reviews() -> None:
    out = build_booths(frame([g("a1", 4, "pb-a", agotw=True), g("b1", 5, "pb-b", agotw=True)]), {})
    assert out.counts["seasons_tied"] == 1
    assert out.counts["seasons_close"] == 1
    assert out.reviews["lead_booth"][0]["reason"] == "tied"


def test_booth_table_counts_agotw_and_fill_ins() -> None:
    rows = [
        g("a1", 4, "pb-a", "an-1", agotw=True),
        g("a2", 5, "pb-a", "an-1", agotw=True),
        g("a3", 6, "pb-a", "an-2"),
    ]
    row = build_booths(frame(rows), {}).booths.row(0, named=True)
    assert (row["dh_games"], row["agotw_games"], row["fill_in_games"]) == (3, 2, 1)
    assert row["regular_analyst_person_id"] == "an-1"
