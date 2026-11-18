"""Awful Announcing as a second NFL crew source (nfl/crew_aa.py), on invented data."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
from nfl_game_helpers import NOW, game_row, listing_for, make_inputs, make_ref, team_name
from nfl_join_helpers import schedule_csv

from booth_review.nfl.booths import _vote_rows, assign_booths
from booth_review.nfl.crew_aa import (
    AaGameCrew,
    NflAaPage,
    coalesce,
    match_aa_booths,
)
from booth_review.nfl.games import assemble_nfl_games
from booth_review.nfl.reference import NflBoothRank
from booth_review.nfl.schedule import parse_upcoming
from booth_review.nfl.upcoming import assemble_upcoming
from booth_review.people.registry import load_people
from booth_review.sources.aa.crews import AaBooth, ParsedCrews

POST = "https://awfulannouncing.com/nfl/week-1-announcing-schedule-2015.html"
OLD = datetime(2015, 9, 10, tzinfo=UTC)
NEW = datetime(2015, 9, 12, tzinfo=UTC)

PEOPLE = """person_id,canonical_name,variants,usual_role,role_override
ana-fixture,Ana Fixture,Ana Fixture,pbp,
bo-fixture,Bo Fixture,Bo Fixture,analyst,
cy-fixture,Cy Fixture,Cy Fixture,analyst,
dee-fixture,Dee Fixture,Dee Fixture,pbp,
"""


def _ref(tmp_path: Path, **kw):
    ref = make_ref(tmp_path, **kw)
    (tmp_path / "ref" / "people.csv").write_text(PEOPLE, encoding="utf-8")
    return replace(ref, people=load_people(tmp_path / "ref"))


def _booth(
    away: int,
    home: int,
    day: date,
    people: tuple[tuple[str, str], ...],
    *,
    season: int = 2015,
    line: int = 1,
) -> AaBooth:
    return AaBooth(
        season=season,
        date_et=day,
        kickoff="1 p.m.",
        away_raw=team_name(away),
        home_raw=team_name(home),
        network_raw="Net1",
        people=people,  # type: ignore[arg-type]
        source_url=POST,
        pointer=f"week-1:{line}",
    )


def _page(*booths: AaBooth, season: int = 2015, week: int = 1, time=NEW) -> NflAaPage:
    parsed = ParsedCrews(
        url=POST, modified=time, published=None, booths=list(booths), unparsed=0, tbd=0, no_pbp=0
    )
    return NflAaPage(season, week, parsed, time)


ANA_BO = (("Ana Fixture", "pbp"), ("Bo Fixture", "analyst"))
DEE_CY = (("Dee Fixture", "pbp"), ("Cy Fixture", "analyst"))
SEP13 = date(2015, 9, 13)


def _crew(pbp: str, *analysts: str, when=NEW) -> AaGameCrew:
    return AaGameCrew("g", pbp, tuple(analysts), POST, when, "p:1")


# -- coalesce ---------------------------------------------------------------------------


def test_no_506_booth_takes_aa_and_keeps_506_sideline() -> None:
    pick = coalesce(
        pbp=None,
        analyst=None,
        sideline=["side"],
        s506_booth=False,
        s506_time=OLD,
        aa=_crew("ana", "bo"),
    )
    assert (pick.pbp_person_id, pick.analyst_person_id) == ("ana", "bo")
    assert pick.sideline_person_ids == ("side",)
    assert pick.from_aa and pick.status == "aa_filled"


def test_same_people_and_subset_agree() -> None:
    same = coalesce(
        pbp="ana", analyst="bo", sideline=[], s506_booth=True, s506_time=OLD, aa=_crew("ana", "bo")
    )
    subset = coalesce(
        pbp="ana", analyst="bo", sideline=[], s506_booth=True, s506_time=OLD, aa=_crew("ana")
    )
    assert same.status == subset.status == "agrees"
    assert not same.from_aa and not subset.from_aa


def test_strict_superset_wins_whatever_the_times() -> None:
    pick = coalesce(
        pbp="ana",
        analyst=None,
        sideline=[],
        s506_booth=True,
        s506_time=NEW,
        aa=_crew("ana", "bo", when=OLD),
    )
    assert pick.status == "superset" and pick.from_aa
    assert pick.analyst_person_id == "bo"


def test_disagreement_goes_to_the_newer_page() -> None:
    kw = {"pbp": "ana", "analyst": "bo", "sideline": ["bo", "side"], "s506_booth": True}
    newer = coalesce(**kw, s506_time=OLD, aa=_crew("dee", "cy", "bo", when=NEW))
    assert newer.status == "aa_won" and newer.from_aa
    assert (newer.pbp_person_id, newer.analyst_person_id) == ("dee", "cy")
    # A further analyst joins the unlabelled tail; the booth is AA's whole, so 506's
    # later names do not stay.
    assert newer.sideline_person_ids == ("bo",)
    older = coalesce(**kw, s506_time=NEW, aa=_crew("dee", "cy", when=OLD))
    assert older.status == "s506_won" and not older.from_aa
    tie = coalesce(**kw, s506_time=NEW, aa=_crew("dee", "cy", when=NEW))
    missing = coalesce(**kw, s506_time=None, aa=_crew("dee", "cy", when=NEW))
    assert tie.status == missing.status == "s506_won"


def test_three_person_506_crew_listed_alike_by_aa_agrees() -> None:
    # 506's third name sits in the sideline list; the same three people agree.
    pick = coalesce(
        pbp="ana",
        analyst="bo",
        sideline=["cy"],
        s506_booth=True,
        s506_time=NEW,
        aa=_crew("ana", "bo", "cy", when=OLD),
    )
    assert pick.status == "agrees" and not pick.from_aa
    assert pick.sideline_person_ids == ("cy",)


def test_superset_of_every_506_name_takes_the_whole_aa_booth() -> None:
    pick = coalesce(
        pbp="ana",
        analyst="bo",
        sideline=["cy"],
        s506_booth=True,
        s506_time=NEW,
        aa=_crew("ana", "bo", "cy", "dee", when=OLD),
    )
    assert pick.status == "superset" and pick.from_aa
    assert pick.sideline_person_ids == ("cy", "dee")


def test_aa_win_drops_the_replaced_booths_third_member() -> None:
    pick = coalesce(
        pbp="ana",
        analyst="bo",
        sideline=["cy"],
        s506_booth=True,
        s506_time=OLD,
        aa=_crew("dee", "eve", when=NEW),
    )
    assert pick.status == "aa_won"
    assert (pick.pbp_person_id, pick.analyst_person_id, pick.sideline_person_ids) == (
        "dee",
        "eve",
        (),
    )


def test_506_crew_without_a_play_by_play_voice_is_filled() -> None:
    pick = coalesce(
        pbp=None,
        analyst="bo",
        sideline=["side"],
        s506_booth=True,
        s506_time=NEW,
        aa=_crew("ana", "bo"),
    )
    assert pick.status == "aa_filled" and pick.from_aa
    assert pick.sideline_person_ids == ("side",)


def test_no_aa_booth_leaves_the_crew_alone() -> None:
    pick = coalesce(pbp="ana", analyst="bo", sideline=[], s506_booth=True, s506_time=OLD, aa=None)
    assert pick.status is None and not pick.from_aa


# -- matching ---------------------------------------------------------------------------


def _games(rows):
    return make_inputs(rows).games


def test_match_by_team_pair_and_date(tmp_path: Path) -> None:
    ref = _ref(tmp_path)
    games = _games([game_row("a", 1, 2, "2015-09-13"), game_row("b", 1, 2, "2015-12-13")])
    # AA lists the home side first here; the pair is unordered.
    match = match_aa_booths([_page(_booth(2, 1, SEP13, ANA_BO))], games, ref.teams, ref.people)
    assert list(match.crews) == ["a"]
    crew = match.crews["a"]
    assert (crew.pbp_person_id, crew.analyst_person_ids) == ("ana-fixture", ("bo-fixture",))
    assert crew.source_url == POST and crew.aa_time == NEW


def test_unknown_names_teams_and_games_are_counted(tmp_path: Path) -> None:
    ref = _ref(tmp_path)
    games = _games([game_row("a", 1, 2, "2015-09-13"), game_row("b", 3, 4, "2015-09-13")])
    page = _page(
        _booth(1, 2, SEP13, (("Nobody Known", "pbp"), ("Bo Fixture", "analyst")), line=1),
        _booth(3, 99, SEP13, ANA_BO, line=2),
        _booth(5, 6, SEP13, ANA_BO, line=3),
        _booth(3, 4, date(2015, 9, 14), ANA_BO, line=4),
    )
    match = match_aa_booths([page], games, ref.teams, ref.people)
    assert match.crews == {}
    assert match.counts["aa_unresolved_names"] == 1
    assert match.unresolved_names == {"Nobody Known": 1}
    assert match.counts["aa_unresolved_team"] == 1
    assert match.counts["aa_no_game"] == 2


def test_a_second_line_with_an_unknown_name_still_drops_the_game(tmp_path: Path) -> None:
    ref = _ref(tmp_path)
    games = _games([game_row("a", 1, 2, "2015-09-13")])
    unknown = (("Nobody Known", "pbp"), ("Bo Fixture", "analyst"))
    page = _page(_booth(1, 2, SEP13, unknown, line=1), _booth(1, 2, SEP13, DEE_CY, line=2))
    match = match_aa_booths([page], games, ref.teams, ref.people)
    assert match.crews == {} and match.counts["aa_duplicate"] == 1
    assert match.unresolved_names == {"Nobody Known": 1}


def test_two_booths_for_one_game_are_both_dropped(tmp_path: Path) -> None:
    ref = _ref(tmp_path)
    games = _games([game_row("a", 1, 2, "2015-09-13")])
    page = _page(_booth(1, 2, SEP13, ANA_BO, line=1), _booth(1, 2, SEP13, DEE_CY, line=2))
    match = match_aa_booths([page], games, ref.teams, ref.people)
    assert match.crews == {} and match.counts["aa_duplicate"] == 1


# -- played games ---------------------------------------------------------------------------


def _played(tmp_path: Path, rows, *, pages=(), listings=(), s506=None, **ref_kw):
    ref = _ref(tmp_path, **ref_kw)
    inputs = replace(
        make_inputs(rows, listings=listings),
        aa_pages=tuple(pages),
        s506_times=dict(s506 or {}),
    )
    return assemble_nfl_games(inputs, ref, include_playoffs=False, now=NOW)


def _one(table, game_id: str):
    return table.frame.filter(pl.col("game_id") == game_id).row(0, named=True)


def test_played_game_without_506_crew_takes_aa(tmp_path: Path) -> None:
    rows = [game_row("a", 1, 2, "2015-09-13")]
    table = _played(tmp_path, rows, pages=[_page(_booth(1, 2, SEP13, ANA_BO))])
    got = _one(table, "a")
    assert (got["pbp_person_id"], got["analyst_person_id"]) == ("ana-fixture", "bo-fixture")
    assert (got["crew_source"], got["crew_source_url"]) == ("aa", POST)
    assert table.counts["aa_filled"] == 1 and table.counts["aa_matched"] == 1
    assert table.reviews["crew_aa"] == []


def test_aa_replaces_a_published_lineup_fill(tmp_path: Path) -> None:
    # A Sunday night NBC game 506 lists with no crew: the season lineup fills it...
    rows = [game_row("a", 1, 2, "2015-09-13", "20:20")]
    lst = listing_for(1, 2, "NBC")
    rank = NflBoothRank("nbc", 2015, 1, "ana-fixture", "bo-fixture", "https://example.com/l")
    ranks = {("nbc", 2015): (rank,)}
    without = _played(tmp_path, rows, listings=[lst], booth_ranks=ranks)
    assert _one(without, "a")["crew_source"] == "published_lineup"
    # ...until AA names the game's own booth.
    table = _played(
        tmp_path,
        rows,
        listings=[lst],
        pages=[_page(_booth(1, 2, SEP13, DEE_CY))],
        booth_ranks=ranks,
    )
    got = _one(table, "a")
    assert (got["crew_source"], got["crew_source_url"]) == ("aa", POST)
    assert got["pbp_person_id"] == "dee-fixture"
    assert table.counts["aa_filled"] == 1


def test_newer_aa_page_beats_an_older_506_crew_with_a_review_row(tmp_path: Path) -> None:
    rows = [game_row("a", 1, 2, "2015-09-13")]
    lst = listing_for(1, 2, "CBS", crew=["Ana Fixture", "Bo Fixture"])
    table = _played(
        tmp_path,
        rows,
        listings=[lst],
        pages=[_page(_booth(1, 2, SEP13, DEE_CY), time=NEW)],
        s506={(2015, 1): OLD},
    )
    got = _one(table, "a")
    assert (got["crew_source"], got["pbp_person_id"]) == ("aa", "dee-fixture")
    assert table.counts["aa_won"] == 1
    [row] = table.reviews["crew_aa"]
    assert row["status"] == "aa_won" and row["s506_pbp_person_id"] == "ana-fixture"
    assert "Dee" not in str(row)


def test_agreeing_aa_page_keeps_the_506_source(tmp_path: Path) -> None:
    rows = [game_row("a", 1, 2, "2015-09-13")]
    lst = listing_for(1, 2, "CBS", crew=["Ana Fixture", "Bo Fixture"])
    table = _played(tmp_path, rows, listings=[lst], pages=[_page(_booth(1, 2, SEP13, ANA_BO))])
    assert _one(table, "a")["crew_source"] == "506"
    assert table.counts["aa_agrees"] == 1


def test_aa_games_vote_for_the_lead_booth() -> None:
    frame = pl.DataFrame(
        {
            "game_id": ["a", "b", "c"],
            "crew_source": ["506", "aa", "published_lineup"],
            "is_flagship": [True, True, True],
            "network_group": ["fox", "fox", "fox"],
        }
    )
    assert _vote_rows(frame)["game_id"].to_list() == ["a", "b"]
    assert callable(assign_booths)


# -- upcoming games -----------------------------------------------------------------------


def test_upcoming_game_takes_aa_crew_and_its_booth_rank(tmp_path: Path) -> None:
    rows = [game_row("u", 1, 2, "2026-11-08", "16:25", season=2026, week=9)]
    rank = NflBoothRank("fox", 2026, 1, "dee-fixture", "cy-fixture", "https://example.com/l")
    ref = _ref(tmp_path, booth_ranks={("fox", 2026): (rank,)})
    ups, unplaced = parse_upcoming(schedule_csv(rows), seasons=[2026])
    lst = listing_for(1, 2, "FOX", season=2026, week=9)
    booth = _booth(1, 2, date(2026, 11, 8), DEE_CY, season=2026)
    inputs = replace(
        make_inputs(rows, listings=[lst]),
        upcoming=tuple(ups),
        upcoming_unplaced=unplaced,
        aa_pages=(_page(booth, season=2026, week=9),),
    )
    frame, counts = assemble_upcoming(
        inputs, ref, now=datetime(2026, 11, 4, tzinfo=UTC), reference_directory=tmp_path / "ref"
    )
    got = frame.row(0, named=True)
    assert (got["pbp_person_id"], got["analyst_person_id"]) == ("dee-fixture", "cy-fixture")
    assert (got["crew_source"], got["crew_source_url"]) == ("aa", POST)
    assert got["booth_rank"] == 1
    assert counts["upcoming_aa_crews"] == 1 and counts["upcoming_aa_filled"] == 1


def test_upcoming_disagreement_writes_a_review_row(tmp_path: Path) -> None:
    rows = [game_row("u", 1, 2, "2026-11-08", "16:25", season=2026, week=9)]
    ref = _ref(tmp_path)
    ups, unplaced = parse_upcoming(schedule_csv(rows), seasons=[2026])
    lst = listing_for(1, 2, "FOX", season=2026, week=9, crew=("Ana Fixture", "Bo Fixture"))
    booth = _booth(1, 2, date(2026, 11, 8), DEE_CY, season=2026)
    inputs = replace(
        make_inputs(rows, listings=[lst]),
        upcoming=tuple(ups),
        upcoming_unplaced=unplaced,
        aa_pages=(_page(booth, season=2026, week=9, time=NEW),),
        s506_times={(2026, 9): OLD},
    )
    reviews: list[dict[str, object]] = []
    frame, counts = assemble_upcoming(
        inputs,
        ref,
        now=datetime(2026, 11, 4, tzinfo=UTC),
        reference_directory=tmp_path / "ref",
        aa_reviews=reviews,
    )
    assert frame.row(0, named=True)["crew_source"] == "aa"
    assert counts["upcoming_aa_won"] == 1
    [row] = reviews
    assert row["upcoming"] is True and row["status"] == "aa_won"
    assert row["s506_pbp_person_id"] == "ana-fixture"
