"""MLB crew precedence, crew named, booth keys and disagreement reviews (synthetic)."""

from __future__ import annotations

import dataclasses
from datetime import date
from pathlib import Path

import polars as pl
from mlb_games_support import build_reference

from booth_review.mlb.crews import (
    CREW_SOURCES,
    CrewDisagreement,
    assign_crews,
    booth_key,
    modal_analysts,
    people_review_names,
    write_crew_disagreements,
)
from booth_review.mlb.games import GAME_SCHEMA
from booth_review.mlb.listings import game_key, telecast_frame
from booth_review.mlb.reference import MlbCrewOverride, MlbTeamCrosswalkRow
from booth_review.people.registry import load_people
from booth_review.sources.wikipedia.mlb_parser import ListCrew

PEOPLE = (
    "person_id,canonical_name,variants,usual_role,role_override\n"
    "pat,Pat Quill,Pat Quill,unknown,\n"
    "lee,Lee Marsh,Lee Marsh,unknown,\n"
    "sam,Sam Rook,Sam Rook,unknown,\n"
    "kim,Kim Vale,Kim Vale,unknown,\n"
    "ray,Ray Epsilon,Ray Epsilon,unknown,\n"
    "jo,Jo Zeta,Jo Zeta,unknown,\n"
    "ana,Ana Delta,Ana Delta,unknown,\n"
)
DAY = date(2026, 5, 2)
KEY = game_key(DAY, "alpha", "bravo", 0)
RELAY_ROW = {
    "season": "2026",
    "game_date": "2026-05-02",
    "away_club": "Alpha Foxes",
    "home_club": "Bravo Herons",
    "game_number": "0",
    "network_id": "apple",
    "pbp": "Pat Quill",
    "analyst_1": "Sam Rook",
    "analyst_2": "",
    "post_url": "https://example.org/post",
    "press_name": "Example Press",
    "press_url": "https://example.org/press",
    "read_date": "2026-05-03",
}


def make_ref(tmp_path: Path):
    ref = build_reference(tmp_path / "ref")
    (tmp_path / "ref" / "people.csv").write_text(PEOPLE, encoding="utf-8")
    extra = (
        MlbTeamCrosswalkRow("relay", "Alpha Foxes", "alpha", None, None, ""),
        MlbTeamCrosswalkRow("relay", "Bravo Herons", "bravo", None, None, ""),
    )
    return dataclasses.replace(
        ref, crosswalk=ref.crosswalk + extra, people=load_people(tmp_path / "ref")
    )


def tele(
    names=(),
    *,
    network="apple",
    family="apple",
    day=DAY,
    away="alpha",
    home="bravo",
    round_id=None,
    series_game=None,
    simulcast=False,
    number=0,
):
    return {
        "game_key": game_key(day, away, home, number),
        "season": day.year,
        "game_date": day,
        "away_club": away,
        "home_club": home,
        "game_number": number,
        "network_id": network,
        "family": family,
        "starred": False,
        "is_exclusive": None,
        "production": "own",
        "window": None,
        "local_outlet": None,
        "crew_names": list(names),
        "local_simulcast": simulcast,
        "source": "506",
        "source_label": "1",
        "round": round_id,
        "series_game": series_game,
        "neutral": False,
        "venue_note": None,
        "date_shift": False,
    }


def games_for(rows):
    out = []
    for r in rows:
        out.append(
            {
                "game_key": r["game_key"],
                "season": r["season"],
                "game_date": r["game_date"],
                "away_club": r["away_club"],
                "home_club": r["home_club"],
                "game_number": r["game_number"],
                "round": r["round"],
                "series_league": "AL" if r["round"] else None,
                "series_game": r["series_game"],
                "neutral": False,
                "venue_note": None,
                "retrosheet_gid": None,
                "home_won": None,
                "away_score": None,
                "home_score": None,
            }
        )
    return pl.DataFrame(out, schema=dict(GAME_SCHEMA))


def run(tmp_path, rows, *, relay=(), lists=(), overrides=()):
    ref = make_ref(tmp_path)
    reviews: list = []
    frame, dis, people = assign_crews(
        telecast_frame(rows), games_for(rows), relay, lists, overrides, ref, reviews
    )
    return frame, dis, people, reviews


def test_sources_constant() -> None:
    assert CREW_SOURCES == ("override", "506", "relay", "wikipedia")


def test_506_wins_and_disagreement_is_reported(tmp_path: Path) -> None:
    rows = [tele(["Lee Marsh", "Sam Rook"])]
    frame, dis, _, _ = run(tmp_path, rows, relay=[RELAY_ROW])
    row = frame.row(0, named=True)
    assert row["crew_source"] == "506"
    assert row["pbp_person_id"] == "lee"
    assert row["press_url"] is None
    assert dis == [CrewDisagreement(KEY, "apple", "506", "relay", "pbp", "lee", "pat")]


def test_relay_fills_with_credits(tmp_path: Path) -> None:
    frame, dis, _, _ = run(tmp_path, [tele()], relay=[RELAY_ROW])
    row = frame.row(0, named=True)
    assert row["crew_source"] == "relay"
    assert row["crew_source_url"] == "https://example.org/post"
    assert row["press_url"] == "https://example.org/press"
    assert row["press_name"] == "Example Press"
    assert row["pbp_person_id"] == "pat"
    assert row["analyst_person_ids"] == ["sam"]
    assert row["crew_named"] is True
    assert dis == []


def test_override_wins_over_everything(tmp_path: Path) -> None:
    override = MlbCrewOverride(
        2026,
        "2026-05-02",
        "alpha",
        "bravo",
        0,
        "apple",
        "Ana Delta",
        "Kim Vale",
        "",
        "https://example.org/o",
        "note",
    )
    frame, dis, _, _ = run(
        tmp_path, [tele(["Lee Marsh", "Sam Rook"])], relay=[RELAY_ROW], overrides=[override]
    )
    row = frame.row(0, named=True)
    assert row["crew_source"] == "override"
    assert row["pbp_person_id"] == "ana"
    assert row["crew_source_url"] == "https://example.org/o"
    assert {(d.source_a, d.source_b) for d in dis} == {
        ("override", "506"),
        ("override", "relay"),
        ("506", "relay"),
    }


def test_agreeing_sources_report_nothing(tmp_path: Path) -> None:
    _, dis, _, _ = run(tmp_path, [tele(["Pat Quill", "Sam Rook", "Kim Vale"])], relay=[RELAY_ROW])
    assert dis == []


def _list(scope: str, label: str | None, pbp: str, analysts: tuple[str, ...], league="AL"):
    return ListCrew(
        2020, "DS", league, "NetB", pbp, analysts, label, scope, "https://example.org/l"
    )


def test_wikipedia_per_series_fills_every_game(tmp_path: Path) -> None:
    day = date(2020, 10, 6)
    rows = [
        tele(network="netb", family="disney", day=day, round_id="division", series_game=n)
        for n in (1, 2)
    ]
    rows[1] = tele(
        network="netb", family="disney", day=date(2020, 10, 7), round_id="division", series_game=2
    )
    crew = _list("per_series", "AL Division", "Kim Vale", ("Ray Epsilon",))
    frame, _, _, _ = run(tmp_path, rows, lists=[crew])
    assert frame["crew_source"].to_list() == ["wikipedia", "wikipedia"]
    assert frame["crew_source_url"].to_list() == ["https://example.org/l"] * 2
    assert frame["crew_named"].to_list() == [True, True]


def test_wikipedia_per_game_fills_only_listed_games(tmp_path: Path) -> None:
    rows = [
        tele(
            network="netb",
            family="disney",
            day=date(2020, 10, 5 + n),
            round_id="division",
            series_game=n,
        )
        for n in (1, 2, 3)
    ]
    crew = _list("per_game", "games 1-2", "Kim Vale", ("Ray Epsilon",))
    frame, _, _, _ = run(tmp_path, rows, lists=[crew])
    assert frame["crew_source"].to_list() == ["wikipedia", "wikipedia", None]


def test_wikipedia_does_not_beat_506_and_other_league_not_used(tmp_path: Path) -> None:
    rows = [
        tele(
            ["Lee Marsh", "Sam Rook"],
            network="netb",
            family="disney",
            day=date(2020, 10, 6),
            round_id="division",
            series_game=1,
        )
    ]
    frame, dis, _, _ = run(
        tmp_path, rows, lists=[_list("per_series", None, "Kim Vale", ("Ray Epsilon",))]
    )
    assert frame["crew_source"].to_list() == ["506"]
    assert [(d.source_b, d.field) for d in dis] == [
        ("wikipedia", "pbp"),
        ("wikipedia", "analyst_1"),
    ]
    frame2, _, _, _ = run(
        tmp_path / "b",
        [
            tele(
                network="netb",
                family="disney",
                day=date(2020, 10, 6),
                round_id="division",
                series_game=1,
            )
        ],
        lists=[_list("per_series", None, "Kim Vale", ("Ray Epsilon",), league="NL")],
    )
    assert frame2["crew_source"].to_list() == [None]


def test_crew_named_needs_pbp_and_an_analyst(tmp_path: Path) -> None:
    rows = [
        tele(["Pat Quill"], network="a1"),
        tele([], network="a2"),
        tele(["Pat Quill", "TBA"], network="a3"),
        tele(["Pat Quill", "Sam Rook"], network="a4"),
    ]
    frame, _, _, _ = run(tmp_path, rows)
    assert frame["crew_named"].to_list() == [False, False, False, True]


def test_local_simulcast_is_outside_denominators(tmp_path: Path) -> None:
    frame, _, _, _ = run(tmp_path, [tele(simulcast=True)], relay=[RELAY_ROW])
    row = frame.row(0, named=True)
    assert row["crew_in_scope"] is False
    assert row["crew_source"] is None
    assert row["booth_key"] is None


def test_booth_key_ignores_analyst_and_marks_fill_in(tmp_path: Path) -> None:
    rows = [
        tele(["Pat Quill", "Sam Rook"], day=date(2026, 5, 2 + n), away="alpha", home="bravo")
        for n in range(3)
    ]
    rows[2] = tele(["Pat Quill", "Kim Vale"], day=date(2026, 5, 4))
    rows.append(tele(["Lee Marsh", "Sam Rook"], day=date(2026, 5, 9)))
    frame, _, _, _ = run(tmp_path, rows)
    keys = frame["booth_key"].to_list()
    assert keys[0] == keys[1] == keys[2] == booth_key("apple", 2026, "pat") == "apple|2026|pat"
    assert frame["fill_in"].to_list() == [False, False, False, True]


def test_unresolved_names_are_reviewed_and_people_not_written(tmp_path: Path) -> None:
    frame, _, people, _ = run(tmp_path, [tele(["Zed Unknown", "Sam Rook"])])
    row = frame.row(0, named=True)
    assert row["pbp_person_id"] is None
    assert row["crew_named"] is False
    assert [(p.raw_name, p.count) for p in people] == [("Zed Unknown", 1)]
    assert people_review_names(people) == ["Zed Unknown"]
    assert (tmp_path / "ref" / "people.csv").read_text(encoding="utf-8") == PEOPLE


def test_unmatched_relay_row_is_reviewed(tmp_path: Path) -> None:
    _, _, _, reviews = run(tmp_path, [tele()], relay=[{**RELAY_ROW, "game_date": "2026-05-09"}])
    assert [(r.source, r.kind) for r in reviews] == [("relay", "no_telecast")]


def test_disagreement_csv_has_ids_only(tmp_path: Path) -> None:
    path = tmp_path / "review.csv"
    write_crew_disagreements(
        path, [CrewDisagreement(KEY, "apple", "506", "relay", "pbp", "lee", "pat")]
    )
    text = path.read_text(encoding="utf-8").splitlines()
    assert text[0].startswith("game_key,network_id,source_a")
    assert text[1].endswith("pbp,lee,pat")


def test_wikipedia_per_game_note_accepts_comma_lists_and_ranges(tmp_path: Path) -> None:
    rows = [
        tele(
            network="netb",
            family="disney",
            day=date(2020, 10, 5 + n),
            round_id="division",
            series_game=n,
        )
        for n in (1, 2, 3, 4, 5, 6)
    ]
    crew = _list("per_game", "Games 1\u20132, 5, 6", "Kim Vale", ("Ray Epsilon",))
    frame, _, _, _ = run(tmp_path, rows, lists=[crew])
    assert [s is not None for s in frame["crew_source"]] == [True, True, False, False, True, True]


def test_modal_analysts_most_frequent_then_earliest_then_id() -> None:
    assert modal_analysts([["b"], ["a"], ["a"], ["a", "x"]]) == ["a"]
    assert modal_analysts([["b"], ["a"]]) == ["b"]  # tie: earliest game wins
    assert modal_analysts([None, [], ["z"]]) == ["z"]
    assert modal_analysts([]) == []


def test_per_game_fill_in_pbp_reaches_the_game_crew(tmp_path: Path) -> None:
    from test_mlb_crews import _list, run, tele

    rows = [
        tele(
            network="netb",
            family="disney",
            day=date(2020, 10, 5 + n),
            round_id="division",
            series_game=n,
        )
        for n in (1, 2, 3)
    ]
    crews = [
        _list("per_series", None, "Kim Vale", ("Ray Epsilon",)),
        _list("per_game", "Games 1, 3", "Kim Vale", ("Ray Epsilon",)),
        _list("per_game", "Games 2", "Jo Zeta", ("Ray Epsilon",)),
    ]
    frame, _, _, _ = run(tmp_path, rows, lists=crews)
    assert frame["pbp_person_id"].to_list() == ["kim", "jo", "kim"]


def test_506_placeholder_cell_does_not_block_the_relay(tmp_path: Path) -> None:
    frame, _, _, _ = run(tmp_path, [tele(["TBA"])], relay=[RELAY_ROW])
    row = frame.row(0, named=True)
    assert row["crew_source"] == "relay"
    assert row["pbp_person_id"] == "pat"
    assert row["crew_named"] is True


def test_506_pbp_only_crew_does_not_block_a_complete_relay_crew(tmp_path: Path) -> None:
    frame, dis, _, _ = run(tmp_path, [tele(["Lee Marsh"])], relay=[RELAY_ROW])
    row = frame.row(0, named=True)
    assert row["crew_source"] == "relay"
    assert row["crew_named"] is True
    assert dis == [CrewDisagreement(KEY, "apple", "506", "relay", "pbp", "lee", "pat")]


def test_506_pbp_only_crew_still_wins_when_nothing_complete_exists(tmp_path: Path) -> None:
    frame, _, _, _ = run(tmp_path, [tele(["Lee Marsh"])])
    row = frame.row(0, named=True)
    assert row["crew_source"] == "506"
    assert row["pbp_person_id"] == "lee"
    assert row["crew_named"] is False


def test_malformed_relay_rows_are_reviewed_not_fatal(tmp_path: Path) -> None:
    bad_date = {**RELAY_ROW, "game_date": "not-a-date"}
    bad_number = {**RELAY_ROW, "game_number": "x"}
    missing_url = {k: v for k, v in RELAY_ROW.items() if k != "post_url"}
    bad_season = {**RELAY_ROW, "season": ""}
    frame, _, _, reviews = run(
        tmp_path, [tele()], relay=[bad_date, bad_number, missing_url, bad_season, RELAY_ROW]
    )
    assert [r.kind for r in reviews if r.source == "relay"] == ["malformed_row"] * 4
    assert frame.row(0, named=True)["crew_source"] == "relay"
