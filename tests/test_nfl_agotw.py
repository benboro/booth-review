"""AGOTW / CBS late national branches and doubleheader flags on synthetic Sundays."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from nfl_game_helpers import NOW, game_row, listing_for, make_inputs, make_ref, override, rr_record

import booth_review.nfl.games as games_mod
from booth_review.nfl.changes import GameChange
from booth_review.nfl.games import NflGameTable, assemble_nfl_games

SUNDAY = "2015-10-04"  # a Sunday


def sunday_games(
    spec: list[tuple[str, str, str]], *, day: str = SUNDAY, week: int = 4, season: int = 2015
):
    """spec rows are (game_id, time, network); every game gets two fresh teams."""
    rows = []
    listings = []
    for i, (gid, time, network) in enumerate(spec):
        away, home = 2 * i + 1, 2 * i + 2
        rows.append(game_row(gid, away, home, day, time, week=week, season=season))
        listings.append(listing_for(away, home, network, week=week, season=season, idx=i))
    return rows, listings


def run(
    tmp_path: Path,
    spec: list[tuple[str, str, str]],
    *,
    overrides=(),
    national: set[str] = frozenset(),
    rr_for: dict[str, str] | None = None,
    include_playoffs: bool = False,
    day: str = SUNDAY,
) -> NflGameTable:
    rows, listings = sunday_games(spec, day=day)
    ids = [gid for gid, _t, _n in spec]
    listings = [
        listings[i]
        if gid not in national
        else listing_for(2 * i + 1, 2 * i + 2, spec[i][2], week=4, idx=i, national=True)
        for i, gid in enumerate(ids)
    ]
    records = []
    for gid, network in (rr_for or {}).items():
        i = ids.index(gid)
        records.append(
            rr_record(
                f"nfl-team-{2 * i + 1:02d}-team-{2 * i + 2:02d}-{day}",
                day,
                2 * i + 1,
                2 * i + 2,
                [network],
            )
        )
    ref = make_ref(tmp_path, overrides=overrides)
    return assemble_nfl_games(
        make_inputs(rows, listings=listings, rr=records),
        ref,
        include_playoffs=include_playoffs,
        now=NOW,
    )


def flags(table: NflGameTable, gid: str) -> dict[str, object]:
    return table.frame.filter(pl.col("game_id") == gid).row(0, named=True)


FOX_ONE = [
    ("f1", "13:00", "FOX"),
    ("f2", "13:00", "FOX"),
    ("f3", "13:00", "FOX"),
    ("fl", "16:25", "FOX"),
    ("c1", "13:00", "CBS"),
]
FOX_TWO = [
    ("f1", "13:00", "FOX"),
    ("fa", "16:25", "FOX"),
    ("fb", "16:25", "FOX"),
    ("c1", "13:00", "CBS"),
]


def test_single_fox_late_game_is_agotw(tmp_path: Path) -> None:
    table = run(tmp_path, FOX_ONE)
    late = flags(table, "fl")
    assert late["is_agotw"] is True
    assert late["agotw_source"] == "single"
    assert late["late_national_status"] == "settled"
    assert flags(table, "f1")["is_agotw"] is False
    assert flags(table, "f1")["fox_dh_sunday"] is True
    assert flags(table, "c1")["fox_dh_sunday"] is True  # a date-level flag
    assert flags(table, "c1")["cbs_dh_sunday"] is False
    assert table.counts["fox_dh_sundays"] == 1
    assert table.counts["agotw"] == 1


def test_two_candidates_named_by_rr(tmp_path: Path) -> None:
    table = run(tmp_path, FOX_TWO, rr_for={"fb": "FOX"})
    assert flags(table, "fb")["is_agotw"] is True
    assert flags(table, "fb")["agotw_source"] == "rr"
    assert flags(table, "fa")["is_agotw"] is False


def test_two_candidates_named_by_506_national_line(tmp_path: Path) -> None:
    table = run(tmp_path, FOX_TWO, national={"fa"})
    assert flags(table, "fa")["is_agotw"] is True
    assert flags(table, "fa")["agotw_source"] == "506"
    assert flags(table, "fb")["is_agotw"] is False


def test_two_candidates_settled_by_override(tmp_path: Path) -> None:
    table = run(tmp_path, FOX_TWO, overrides=[override(2015, 4, "fox", "fb")])
    assert flags(table, "fb")["agotw_source"] == "override"
    assert flags(table, "fa")["is_agotw"] is False
    assert table.counts["override_unused"] == 0


def test_ambiguous_week_excluded_and_counted(tmp_path: Path) -> None:
    table = run(tmp_path, FOX_TWO)
    for gid in ("fa", "fb"):
        row = flags(table, gid)
        assert row["is_agotw"] is False
        assert row["is_special"] is False
        assert row["late_national_status"] == "ambiguous"
    assert table.counts["ambiguous_fox_weeks"] == 1
    assert table.counts["agotw"] == 0
    (review,) = table.reviews["late_national"]
    assert (review["season"], review["week"], review["network"]) == (2015, 4, "fox")
    assert review["candidates"] == 2


def test_never_chosen_by_crew(tmp_path: Path) -> None:
    rows, listings = sunday_games(FOX_TWO)
    listings = [
        listing_for(3, 4, "FOX", week=4, idx=1, crew=["Ana Fixture", "Bo Fixture"])
        if item.away_raw == "Team 03"
        else item
        for item in listings
    ]
    ref = make_ref(tmp_path)
    table = assemble_nfl_games(
        make_inputs(rows, listings=listings), ref, include_playoffs=False, now=NOW
    )
    assert flags(table, "fa")["is_agotw"] is False
    assert flags(table, "fb")["is_agotw"] is False
    assert table.counts["ambiguous_fox_weeks"] == 1


def test_override_on_non_candidate_is_counted_error(tmp_path: Path) -> None:
    table = run(tmp_path, FOX_TWO, overrides=[override(2015, 4, "fox", "f1")])
    assert table.counts["override_errors"] == 1
    assert table.reviews["late_national"][0]["reason"] == "override-invalid"
    assert flags(table, "fa")["is_agotw"] is False  # the bad override never picks a game


def test_unused_override_counted_when_text_source_settles(tmp_path: Path) -> None:
    table = run(
        tmp_path,
        FOX_TWO,
        overrides=[override(2015, 4, "fox", "fb")],
        rr_for={"fa": "FOX"},
    )
    assert flags(table, "fa")["agotw_source"] == "rr"
    assert flags(table, "fb")["is_agotw"] is False
    assert table.counts["override_unused"] == 1


def test_cbs_branches(tmp_path: Path) -> None:
    single = run(tmp_path, [("c1", "13:00", "CBS"), ("cl", "16:25", "CBS"), ("f1", "13:00", "FOX")])
    assert flags(single, "cl")["is_cbs_national"] is True
    assert flags(single, "cl")["cbs_national_source"] == "single"
    assert flags(single, "cl")["is_agotw"] is False
    assert single.counts["cbs_dh_sundays"] == 1

    cbs_two = [("c1", "13:00", "CBS"), ("ca", "16:25", "CBS"), ("cb", "16:25", "CBS")]
    by_rr = run(tmp_path, cbs_two, rr_for={"ca": "CBS"})
    assert flags(by_rr, "ca")["cbs_national_source"] == "rr"
    by_506 = run(tmp_path, cbs_two, national={"cb"})
    assert flags(by_506, "cb")["cbs_national_source"] == "506"
    by_override = run(tmp_path, cbs_two, overrides=[override(2015, 4, "cbs", "cb")])
    assert flags(by_override, "cb")["cbs_national_source"] == "override"
    ambiguous = run(tmp_path, cbs_two)
    assert ambiguous.counts["ambiguous_cbs_weeks"] == 1
    assert ambiguous.counts["cbs_national"] == 0
    assert flags(ambiguous, "ca")["is_special"] is False


def test_both_networks_can_have_doubleheaders(tmp_path: Path) -> None:
    table = run(
        tmp_path,
        [
            ("f1", "13:00", "FOX"),
            ("fl", "16:25", "FOX"),
            ("c1", "13:00", "CBS"),
            ("cl", "16:25", "CBS"),
        ],
    )
    assert flags(table, "f1")["fox_dh_sunday"] and flags(table, "f1")["cbs_dh_sunday"]
    assert flags(table, "fl")["is_agotw"] and flags(table, "cl")["is_cbs_national"]
    assert flags(table, "fl")["is_special"] is True


def test_no_doubleheader_without_early_game(tmp_path: Path) -> None:
    table = run(tmp_path, [("fl", "16:25", "FOX"), ("c1", "13:00", "CBS")])
    assert flags(table, "fl")["is_agotw"] is False
    assert flags(table, "fl")["late_national_status"] == "not_dh"
    assert table.counts["fox_dh_sundays"] == 0


def test_saturday_slate_never_sets_doubleheader_flags(tmp_path: Path) -> None:
    rows = [
        game_row("s1", 1, 2, "2015-12-19", "13:00", weekday="Saturday", week=15),
        game_row("s2", 3, 4, "2015-12-19", "16:25", weekday="Saturday", week=15),
    ]
    listings = [
        listing_for(1, 2, "FOX", week=15, idx=0),
        listing_for(3, 4, "FOX", week=15, idx=1),
    ]
    table = assemble_nfl_games(
        make_inputs(rows, listings=listings), make_ref(tmp_path), include_playoffs=False, now=NOW
    )
    assert table.frame["fox_dh_sunday"].to_list() == [False, False]
    assert table.frame["is_agotw"].to_list() == [False, False]


def _stub_changes(monkeypatch: pytest.MonkeyPatch, change: GameChange) -> None:
    monkeypatch.setattr(games_mod, "match_schedule_changes", lambda *_a, **_k: ({"a": change}, []))


def test_flex_into_snf_is_flexed_with_originals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    change = GameChange("a", "Sunday early", "cbs", "13:00", "nbc", "https://example.com/wiki", "h")
    _stub_changes(monkeypatch, change)
    rows = [game_row("a", 1, 2, "2015-10-04", "20:30", week=4)]
    table = assemble_nfl_games(
        make_inputs(rows), make_ref(tmp_path), include_playoffs=False, now=NOW
    )
    got = flags(table, "a")
    assert got["flexed"] is True
    assert got["original_slot"] == "Sunday early"
    assert got["original_network"] == "cbs"
    assert got["original_time_et"] == "13:00"
    assert got["change_article_url"] == "https://example.com/wiki"


def test_cross_flex_not_flexed_but_originals_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    change = GameChange("a", "Sunday early", "cbs", "13:00", "fox", "https://example.com/wiki", "h")
    _stub_changes(monkeypatch, change)
    rows = [game_row("a", 1, 2, "2015-10-04", "13:00", week=4)]
    table = assemble_nfl_games(
        make_inputs(rows), make_ref(tmp_path), include_playoffs=False, now=NOW
    )
    got = flags(table, "a")
    assert got["flexed"] is False
    assert got["original_network"] == "cbs"
