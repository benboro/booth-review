"""ESPN Press Room backup crews (04.19 D-13..D-15): precedence, whole booths,
roles, the sideline rule, disagreements, provisional persons, the page loader
and the D-15 gap list. Synthetic data only: invented teams and people."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

import polars as pl

from booth_review.build.crew_backup import (
    CREW_BACKUP_LABEL,
    CREW_BACKUP_SOURCE,
    CrewBackupResult,
    SavedBooth,
    apply_crew_backup,
    backfill_gap_rows,
    load_espnpr_booths,
)
from booth_review.build.crew_overrides import crew_gap_rows
from booth_review.build.people_links import PEOPLE_SCHEMA, TELECAST_PEOPLE_SCHEMA
from booth_review.build.telecasts import TELECASTS_SCHEMA
from booth_review.config import DataPaths
from booth_review.contract.models import crew_source_label_problem
from booth_review.people.registry import PeopleRegistry, Person
from booth_review.resolve.games import GameIndex
from booth_review.resolve.networks import NetworkRow, NetworkTable
from booth_review.resolve.overrides import GameOverride
from booth_review.resolve.teams import TeamResolver
from booth_review.sources.cfbd.parser import CfbdGame
from booth_review.sources.espnpr.parser import EspnPrBooth

SEASON = 2022
TEAMS = {
    1: "Silverlake",
    2: "Northfield",
    3: "Riverbend",
    4: "Lakeshore",
    5: "Hilltop",
    6: "Eastbrook",
    7: "Westmere",
    8: "Granite Bay",
}
URL = "https://espnpressroom.com/press-release/synthetic-week-6-college-football-coverage/"
URL_B = "https://espnpressroom.com/2022-23-espn-college-football-commentators-schedule/"
PEOPLE_CSV = {
    "avery-lane": ("Avery Lane", "pbp"),
    "morgan-pike": ("Morgan Pike", "analyst"),
    "quinn-harrow": ("Quinn Harrow", "analyst"),
    "rowan-ellis": ("Rowan Ellis", "unknown"),
    "blair-tolley": ("Blair Tolley", "pbp"),
    "casey-lorn": ("Casey Lorn", "analyst"),
}


def _game(game_id: int, home: int, away: int, day: int, **extra: Any) -> CfbdGame:
    fields: dict[str, Any] = {
        "id": game_id,
        "season": SEASON,
        "week": 6,
        "season_type": "regular",
        "start_date": datetime(SEASON, 10, day, 20, 0, tzinfo=UTC),
        "start_time_tbd": False,
        "completed": True,
        "neutral_site": False,
        "conference_game": True,
        "venue": "Test Field",
        "home_id": home,
        "home_team": TEAMS[home],
        "home_classification": "fbs",
        "home_conference": "Test Conference",
        "home_points": 20,
        "away_id": away,
        "away_team": TEAMS[away],
        "away_classification": "fbs",
        "away_conference": "Test Conference",
        "away_points": 17,
        "excitement_index": None,
        "notes": None,
    }
    fields.update(extra)
    return CfbdGame(**fields)


GAMES = [
    _game(100, home=2, away=1, day=8),  # Silverlake at Northfield, ESPN
    _game(101, home=4, away=3, day=8),  # Riverbend at Lakeshore, CBS
    _game(102, home=7, away=6, day=8),  # Eastbrook at Westmere, ESPN
    _game(103, home=8, away=5, day=8),  # Hilltop at Granite Bay, ABC
]


def _networks() -> NetworkTable:
    def row(variant: str, network_id: str, family: str, tier: str) -> NetworkRow:
        return NetworkRow(
            variant=variant,
            network_id=network_id,
            display_name=variant,
            family=family,
            tier=tier,  # type: ignore[arg-type]
            feed_type="main",
            season_from=None,
            season_to=None,
            priority=None,
        )

    return NetworkTable(
        [
            row("ABC", "abc", "disney", "broadcast"),
            row("ESPN", "espn", "disney", "cable"),
            row("ESPN2", "espn2", "disney", "cable"),
            row("ESPN+", "espn-plus", "disney", "streaming"),
            row("CBS", "cbs", "paramount", "broadcast"),
        ]
    )


def _registry() -> PeopleRegistry:
    return PeopleRegistry(
        {
            pid: Person(pid, name, (name,), role, None)  # type: ignore[arg-type]
            for pid, (name, role) in PEOPLE_CSV.items()
        }
    )


def _people_frame(extra: list[dict[str, object]] | None = None) -> pl.DataFrame:
    rows: list[dict[str, object]] = [
        {
            "person_id": pid,
            "canonical_name": name,
            "variants": [name],
            "usual_role": role,
            "registered": True,
        }
        for pid, (name, role) in PEOPLE_CSV.items()
    ]
    rows.extend(extra or [])
    return pl.DataFrame(rows, schema=PEOPLE_SCHEMA).sort("person_id")


def _tel(game_id: int, network_id: str = "espn", **changes: object) -> dict[str, object]:
    row: dict[str, object] = dict.fromkeys(TELECASTS_SCHEMA)
    game = next(g for g in GAMES if g.id == game_id)
    row.update(
        telecast_id=f"{game_id}-{network_id}",
        game_id=game_id,
        season=SEASON,
        date_et=game.start_date.date(),
        network_id=network_id,
        feed_type="main",
        rated=True,
        rr_telecast_ids=["rr1", "rr2"],
        crew_matched=False,
        crew_patched=False,
        crew_backup=False,
        crew_network_mismatch=False,
        plotted=True,
    )
    row.update(changes)
    return row


def _tp(telecast_id: str, person_id: str, position: int = 0, **changes: object) -> dict[str, Any]:
    row: dict[str, Any] = {
        "telecast_id": telecast_id,
        "person_id": person_id,
        "role": "pbp" if position == 0 else "analyst",
        "feed_type": "main",
        "crew_position": position,
        "s506_pointer": "6:1",
        "source": "registered",
    }
    row.update(changes)
    return row


def _booth(
    names: tuple[str, ...],
    *,
    away: str = "Silverlake",
    home: str = "Northfield",
    network: str = "ESPN",
    pointer: str = "wk-6:1",
    url: str = URL,
    day: int = 8,
    saved_at: str = "2022-10-03T18:00:00Z",
) -> SavedBooth:
    return SavedBooth(
        booth=EspnPrBooth(
            season=SEASON,
            date_et=date(SEASON, 10, day),
            kickoff="Noon",
            away_raw=away,
            home_raw=home,
            network_raw=network,
            tv_names=names,
            source_url=url,
            pointer=pointer,
        ),
        saved_at=saved_at,
    )


_COUNTS = {SEASON: {"rated_with_crew": 4, "records_with_crew": 9, "records_with_506_crew": 9}}


def _run(
    tels: list[dict[str, object]],
    booths: list[SavedBooth],
    people_rows: list[dict[str, Any]] | None = None,
    *,
    people: pl.DataFrame | None = None,
    overrides: dict[tuple[str, int, str], GameOverride] | None = None,
    season_counts: dict[int, dict[str, int]] | None = None,
) -> CrewBackupResult:
    return apply_crew_backup(
        pl.DataFrame(tels, schema=TELECASTS_SCHEMA),
        pl.DataFrame(people_rows or [], schema=TELECAST_PEOPLE_SCHEMA),
        people if people is not None else _people_frame(),
        booths,
        resolver=TeamResolver({SEASON: GAMES}, []),
        index=GameIndex(GAMES),
        overrides=overrides or {},
        networks=_networks(),
        registry=_registry(),
        season_counts=season_counts if season_counts is not None else _COUNTS,
    )


# -- Filling -----------------------------------------------------------------------------------


def test_two_name_booth_fills_a_crewless_espn_telecast() -> None:
    tels = [_tel(100)]
    frame_before = pl.DataFrame(tels, schema=TELECASTS_SCHEMA)
    counts_before = {SEASON: dict(_COUNTS[SEASON])}
    result = _run(tels, [_booth(("Avery Lane", "Morgan Pike"))], season_counts=counts_before)

    rows = result.telecast_people.to_dicts()
    assert [(r["person_id"], r["role"], r["crew_position"]) for r in rows] == [
        ("avery-lane", "pbp", 0),
        ("morgan-pike", "analyst", 1),
    ]
    assert all(
        r["feed_type"] == "main" and r["s506_pointer"] is None and r["source"] == CREW_BACKUP_SOURCE
        for r in rows
    )
    tel = result.telecasts.to_dicts()[0]
    assert tel["crew_backup"] is True
    assert tel["crew_matched"] is True
    assert tel["crew_patched"] is False
    assert tel["crew_source_label"] == CREW_BACKUP_LABEL == "ESPN Press Room"
    assert tel["crew_source_url"] == URL
    assert result.statuses == {"100-espn": "filled"}
    assert result.filled_ids == frozenset({"100-espn"})
    assert result.counts["filled"] == 1
    assert result.counts["rows"] == 2
    # records_with_crew rises like a patched crew; the 506-only count never does.
    assert result.season_counts[SEASON] == {
        "rated_with_crew": 5,
        "records_with_crew": 11,
        "records_with_506_crew": 9,
    }
    # Inputs are copied, never mutated.
    assert counts_before == _COUNTS
    assert pl.DataFrame(tels, schema=TELECASTS_SCHEMA).equals(frame_before)
    assert result.new_name_rows == []
    assert result.people.equals(_people_frame())


def test_label_passes_the_contract_check() -> None:
    assert crew_source_label_problem(CREW_BACKUP_LABEL) is None


def test_unrated_fill_leaves_the_rated_counts() -> None:
    result = _run([_tel(100, rated=False)], [_booth(("Avery Lane", "Morgan Pike"))])
    assert result.statuses == {"100-espn": "filled"}
    assert result.season_counts == _COUNTS


def test_no_booths_is_a_no_op() -> None:
    tels = [_tel(100)]
    result = _run(tels, [])
    assert result.telecasts.equals(pl.DataFrame(tels, schema=TELECASTS_SCHEMA))
    assert result.statuses == {}
    assert result.counts["filled"] == 0


def test_combined_network_cell_picks_the_tv_network() -> None:
    # "ESPN/ESPN Radio": ESPN Radio has no networks.csv row; the TV network wins.
    result = _run([_tel(100)], [_booth(("Avery Lane", "Morgan Pike"), network="ESPN/ESPN Radio")])
    assert result.statuses == {"100-espn": "filled"}


# -- Precedence --------------------------------------------------------------------------------


def test_506_crew_with_the_same_people_is_left_alone_and_not_flagged() -> None:
    tels = [_tel(100, crew_matched=True)]
    people = [_tp("100-espn", "avery-lane"), _tp("100-espn", "morgan-pike", 1)]
    result = _run(tels, [_booth(("Avery Lane", "Morgan Pike"))], people)
    assert result.statuses == {"100-espn": "agrees"}
    assert result.review_rows == []
    assert result.counts["disagreements"] == 0
    assert result.counts["agreements"] == 1
    assert result.telecast_people.equals(pl.DataFrame(people, schema=TELECAST_PEOPLE_SCHEMA))
    assert result.telecasts.to_dicts()[0]["crew_backup"] is False
    assert result.season_counts == _COUNTS


def test_506_crew_with_other_people_writes_one_disagreement_row() -> None:
    tels = [_tel(100, crew_matched=True)]
    people = [_tp("100-espn", "blair-tolley"), _tp("100-espn", "morgan-pike", 1)]
    result = _run(tels, [_booth(("Avery Lane", "Morgan Pike"))], people)
    assert result.statuses == {"100-espn": "differs"}
    assert result.counts["disagreements"] == 1
    assert len(result.review_rows) == 1
    review = result.review_rows[0]
    assert review["telecast_id"] == "100-espn"
    assert review["s506_person_ids"] == "blair-tolley|morgan-pike"
    assert review["backup_person_ids"] == "avery-lane|morgan-pike"
    assert review["source_url"] == URL
    # 506 wins: nothing about the telecast or its crew changes.
    assert result.telecast_people.equals(pl.DataFrame(people, schema=TELECAST_PEOPLE_SCHEMA))
    tel = result.telecasts.to_dicts()[0]
    assert tel["crew_backup"] is False
    assert tel["crew_source_label"] is None
    assert result.season_counts == _COUNTS


def test_override_telecast_is_never_changed() -> None:
    url = "https://example.com/pr/1"
    tels = [
        _tel(100, crew_matched=True, crew_patched=True, crew_source_url=url, crew_source_label="PR")
    ]
    people = [
        _tp("100-espn", "blair-tolley", source="crew_override", s506_pointer=None),
        _tp("100-espn", "casey-lorn", 1, source="crew_override", s506_pointer=None),
    ]
    result = _run(tels, [_booth(("Avery Lane", "Morgan Pike"))], people)
    assert result.statuses == {"100-espn": "override"}
    assert result.counts["kept_override"] == 1
    assert result.review_rows == []
    assert result.telecasts.equals(pl.DataFrame(tels, schema=TELECASTS_SCHEMA))
    assert result.telecast_people.equals(pl.DataFrame(people, schema=TELECAST_PEOPLE_SCHEMA))


def test_correction_override_on_a_506_crew_is_never_flagged() -> None:
    # A correction override keeps crew_patched False; its rows mark it.
    tels = [_tel(100, crew_matched=True, crew_source_label="PR")]
    people = [_tp("100-espn", "blair-tolley", source="crew_override", s506_pointer=None)]
    result = _run(tels, [_booth(("Avery Lane", "Morgan Pike"))], people)
    assert result.statuses == {"100-espn": "override"}
    assert result.review_rows == []


def test_cbs_telecast_is_never_filled() -> None:
    tels = [_tel(101, "cbs")]
    result = _run(
        tels,
        [_booth(("Avery Lane", "Morgan Pike"), away="Riverbend", home="Lakeshore", network="CBS")],
    )
    assert result.statuses == {}
    assert result.counts["not_espn_family"] == 1
    assert result.telecast_people.is_empty()
    assert result.telecasts.to_dicts()[0]["crew_backup"] is False


def test_booth_on_another_network_is_skipped_and_counted() -> None:
    tels = [_tel(100)]
    result = _run(tels, [_booth(("Avery Lane", "Morgan Pike"), network="ESPN2")])
    assert result.statuses == {}
    assert result.counts["network_mismatch"] == 1
    assert result.telecast_people.is_empty()
    assert [(r.reason, r.pointer) for r in result.unmatched_rows] == [
        ("network_mismatch", "wk-6:1")
    ]


def test_unplotted_telecast_is_never_filled() -> None:
    result = _run([_tel(100, plotted=False)], [_booth(("Avery Lane", "Morgan Pike"))])
    assert result.statuses == {}
    assert result.counts["not_plotted"] == 1


def test_alt_feed_telecast_is_never_a_target() -> None:
    result = _run([_tel(100, feed_type="alt")], [_booth(("Avery Lane", "Morgan Pike"))])
    assert result.statuses == {}
    assert result.counts["no_telecast"] == 1


def test_unresolved_team_is_unmatched_and_listed() -> None:
    result = _run([_tel(100)], [_booth(("Avery Lane", "Morgan Pike"), away="Nowhere State")])
    assert result.counts["unmatched"] == 1
    assert result.counts["unresolved_team"] == 1
    assert [r.raw_name for r in result.unresolved_rows] == ["Nowhere State"]
    assert [r.source for r in result.unresolved_rows] == ["espnpr"]
    assert [r.reason for r in result.unmatched_rows] == ["unresolved_team"]


def test_date_a_day_off_still_matches() -> None:
    result = _run([_tel(100)], [_booth(("Avery Lane", "Morgan Pike"), day=9)])
    assert result.statuses == {"100-espn": "filled"}


def test_game_override_excludes_a_booth() -> None:
    override = GameOverride("espnpr", SEASON, "wk-6:1", "exclude", None, "not-fbs")  # type: ignore[arg-type]
    result = _run(
        [_tel(100)],
        [_booth(("Avery Lane", "Morgan Pike"))],
        overrides={("espnpr", SEASON, "wk-6:1"): override},
    )
    assert result.statuses == {}
    assert result.counts["excluded_override"] == 1


def test_off_host_url_is_never_credited() -> None:
    result = _run(
        [_tel(100)], [_booth(("Avery Lane", "Morgan Pike"), url="https://example.com/x/")]
    )
    assert result.statuses == {}
    assert result.counts["bad_url"] == 1


# -- Roles and the sideline rule ---------------------------------------------------------------


def test_four_name_line_drops_a_trailing_name_with_no_booth_role() -> None:
    result = _run(
        [_tel(100)],
        [_booth(("Avery Lane", "Morgan Pike", "Quinn Harrow", "Rowan Ellis"))],
    )
    rows = result.telecast_people.sort("crew_position").to_dicts()
    assert [(r["person_id"], r["role"]) for r in rows] == [
        ("avery-lane", "pbp"),
        ("morgan-pike", "analyst"),
        ("quinn-harrow", "analyst"),
    ]
    assert result.counts["sideline_dropped"] == 1


def test_three_name_line_keeps_a_registered_analyst_third() -> None:
    result = _run([_tel(100)], [_booth(("Avery Lane", "Morgan Pike", "Quinn Harrow"))])
    rows = result.telecast_people.sort("crew_position").to_dicts()
    assert [r["person_id"] for r in rows] == ["avery-lane", "morgan-pike", "quinn-harrow"]
    assert result.counts["sideline_dropped"] == 0


def test_three_name_line_drops_an_unknown_third_without_registering_it() -> None:
    result = _run([_tel(100)], [_booth(("Avery Lane", "Morgan Pike", "Sable Wren"))])
    assert result.telecast_people["person_id"].to_list() == ["avery-lane", "morgan-pike"]
    assert result.counts["sideline_dropped"] == 1
    assert result.new_name_rows == []


def test_four_name_line_drops_every_trailing_name_with_no_booth_role() -> None:
    # Primetime lines can print two sideline names after the booth; both go.
    result = _run(
        [_tel(100)],
        [_booth(("Avery Lane", "Morgan Pike", "Sable Wren", "Tamsin Vale"))],
    )
    assert result.telecast_people["person_id"].to_list() == ["avery-lane", "morgan-pike"]
    assert result.counts["sideline_dropped"] == 1
    assert result.new_name_rows == []


def test_two_trailing_sideline_names_still_agree_with_the_506_booth() -> None:
    tels = [_tel(100, crew_matched=True)]
    people = [_tp("100-espn", "avery-lane"), _tp("100-espn", "morgan-pike", 1)]
    booth = _booth(("Avery Lane", "Morgan Pike", "Sable Wren", "Tamsin Vale"))
    result = _run(tels, [booth], people)
    assert result.statuses == {"100-espn": "agrees"}
    assert result.counts["disagreements"] == 0


def test_later_names_take_their_people_csv_role() -> None:
    # Blair Tolley is a registered pbp voice; listed second she keeps that role.
    result = _run([_tel(100)], [_booth(("Avery Lane", "Blair Tolley", "Morgan Pike"))])
    roles = {r["person_id"]: r["role"] for r in result.telecast_people.to_dicts()}
    assert roles == {"avery-lane": "pbp", "blair-tolley": "pbp", "morgan-pike": "analyst"}


# -- Unknown names -----------------------------------------------------------------------------


def test_unknown_name_becomes_a_provisional_person() -> None:
    result = _run([_tel(100)], [_booth(("Avery Lane", "Tamsin Vale"))])
    rows = {r["person_id"]: r for r in result.telecast_people.to_dicts()}
    assert set(rows) == {"avery-lane", "tamsin-vale"}
    assert rows["tamsin-vale"]["role"] == "analyst"
    assert result.counts["provisional_persons"] == 1
    assert result.new_name_rows == [
        {
            "name": "Tamsin Vale",
            "occurrences": 1,
            "season_first": SEASON,
            "season_last": SEASON,
            "provisional_id": "tamsin-vale",
        }
    ]
    person = result.people.filter(pl.col("person_id") == "tamsin-vale").to_dicts()
    assert person == [
        {
            "person_id": "tamsin-vale",
            "canonical_name": "Tamsin Vale",
            "variants": ["Tamsin Vale"],
            "usual_role": "unknown",
            "registered": False,
        }
    ]
    # The person table stays sorted for the writer.
    assert result.people["person_id"].to_list() == sorted(result.people["person_id"].to_list())


def test_name_506_already_made_provisional_reuses_its_id() -> None:
    people = _people_frame(
        [
            {
                "person_id": "tamsin-vale",
                "canonical_name": "Tamsin Vale",
                "variants": ["Tamsin Vale"],
                "usual_role": "unknown",
                "registered": False,
            }
        ]
    )
    result = _run([_tel(100)], [_booth(("Avery Lane", "Tamsin Vale"))], people=people)
    assert "tamsin-vale" in result.telecast_people["person_id"].to_list()
    assert result.new_name_rows == []
    assert result.people.equals(people)


# -- Two pages, one telecast -------------------------------------------------------------------


def test_later_saved_page_wins_and_the_conflict_is_counted() -> None:
    older = _booth(
        ("Blair Tolley", "Casey Lorn"), pointer="slug-a:1", saved_at="2022-10-03T10:00:00Z"
    )
    newer = _booth(
        ("Avery Lane", "Morgan Pike"), pointer="wk-6:1", url=URL_B, saved_at="2022-10-04T10:00:00Z"
    )
    for booths in ([older, newer], [newer, older]):
        result = _run([_tel(100)], booths)
        assert sorted(result.telecast_people["person_id"].to_list()) == [
            "avery-lane",
            "morgan-pike",
        ]
        assert result.telecasts.to_dicts()[0]["crew_source_url"] == URL_B
        assert result.counts["page_conflicts"] == 1


def test_same_booth_on_two_pages_is_no_conflict() -> None:
    first = _booth(
        ("Avery Lane", "Morgan Pike"), pointer="slug-a:1", saved_at="2022-10-03T10:00:00Z"
    )
    second = _booth(
        ("Avery Lane", "Morgan Pike"), pointer="wk-6:1", saved_at="2022-10-04T10:00:00Z"
    )
    result = _run([_tel(100)], [first, second])
    assert result.counts["page_conflicts"] == 0
    assert result.counts["filled"] == 1


# -- Gap rows and the D-15 list ----------------------------------------------------------------


def test_crew_gap_rows_mark_a_filled_telecast_backup() -> None:
    tels = pl.DataFrame([_tel(100), _tel(102)], schema=TELECASTS_SCHEMA)
    games = pl.DataFrame(
        [
            {
                "game_id": g.id,
                "game_type": "regular",
                "playoff_round": None,
                "away_team": g.away_team,
                "home_team": g.home_team,
            }
            for g in GAMES
        ]
    )
    rows = crew_gap_rows(
        tels,
        games,
        pl.DataFrame([], schema=TELECAST_PEOPLE_SCHEMA),
        {},
        set(),
        backup_ids={"100-espn"},
    )
    assert {r["cfbd_game_id"]: r["override_status"] for r in rows} == {
        100: "backup",
        102: "missing",
    }


def _gap(game_id: int, network_id: str, season: int, day: date, status: str = "missing") -> dict:
    return {
        "cfbd_game_id": game_id,
        "network_id": network_id,
        "season": season,
        "date_et": day,
        "override_status": status,
    }


def test_backfill_gap_rows_group_disney_gaps_by_week_with_espn_labels() -> None:
    def g(game_id: int, season: int, week: int, month: int, day: int, **extra: Any) -> CfbdGame:
        return _game(
            game_id,
            home=2,
            away=1,
            day=1,
            season=season,
            week=week,
            start_date=datetime(season, month, day, 20, 0, tzinfo=UTC),
            **extra,
        )

    games = [
        g(1, 2021, 1, 8, 28),  # ESPN Week 0 (the early opener)
        g(2, 2021, 1, 9, 4),  # ESPN Week 1
        g(3, 2021, 1, 9, 4),
        g(4, 2021, 6, 10, 9),
        g(5, 2021, 6, 10, 9),  # CBS: not ESPN family
        g(6, 2021, 1, 12, 31, season_type="postseason"),
        g(7, 2021, 2, 1, 10, season_type="postseason"),
        g(8, 2026, 6, 10, 10),  # outside 2014-2025
        g(9, 2021, 6, 10, 10),  # backup-filled
    ]
    gaps = [
        _gap(1, "espn", 2021, date(2021, 8, 28)),
        _gap(2, "abc", 2021, date(2021, 9, 4)),
        _gap(3, "espn2", 2021, date(2021, 9, 4)),
        _gap(4, "espn", 2021, date(2021, 10, 9)),
        _gap(5, "cbs", 2021, date(2021, 10, 9)),
        _gap(6, "espn", 2021, date(2021, 12, 31)),
        _gap(7, "abc", 2021, date(2022, 1, 10)),
        _gap(8, "espn", 2026, date(2026, 10, 10)),
        _gap(9, "espn", 2021, date(2021, 10, 10), status="backup"),
    ]
    rows = backfill_gap_rows(gaps, games, _networks())
    assert rows == [
        {
            "season": 2021,
            "cfbd_week": 1,
            "espn_week_label": "Week 0",
            "telecasts": 1,
            "first_date": date(2021, 8, 28),
            "last_date": date(2021, 8, 28),
            "networks": "espn",
        },
        {
            "season": 2021,
            "cfbd_week": 1,
            "espn_week_label": "Week 1",
            "telecasts": 2,
            "first_date": date(2021, 9, 4),
            "last_date": date(2021, 9, 4),
            "networks": "abc|espn2",
        },
        {
            "season": 2021,
            "cfbd_week": 6,
            "espn_week_label": "Week 6",
            "telecasts": 1,
            "first_date": date(2021, 10, 9),
            "last_date": date(2021, 10, 9),
            "networks": "espn",
        },
        {
            "season": 2021,
            "cfbd_week": "postseason",
            "espn_week_label": "bowls",
            "telecasts": 2,
            "first_date": date(2021, 12, 31),
            "last_date": date(2022, 1, 10),
            "networks": "abc|espn",
        },
    ]


# -- Loader ------------------------------------------------------------------------------------


def _page(canonical: str, body_class: str, rows: str, *, published: str, heading: str) -> str:
    return f"""<!DOCTYPE html><html><head><title>Synthetic - ESPN Press Room</title>
<link rel="canonical" href="{canonical}" />
<meta property="article:published_time" content="{published}" />
</head><body class="{body_class}"><main><article>
<div class="brxe-post-content">
<p class="has-medium-font-size"><strong>{heading}</strong></p>
<table><tbody>
<tr><td><strong>Date</strong></td><td><strong>Time (ET)</strong></td>
<td><strong>Game/Commentators</strong></td><td><strong>Platform</strong></td></tr>
{rows}
</tbody></table></div></article></main></body></html>"""


_ROW = (
    "<tr><td><strong>Sat, Oct 8</strong></td><td>Noon</td>"
    "<td><strong>Silverlake at Northfield</strong><br>{names}</td><td>ESPN</td></tr>"
)


def _vault(tmp_path: Any) -> DataPaths:
    return DataPaths(vault=tmp_path / "vault")


def _write(paths: DataPaths, rel: str, text: str) -> None:
    path = paths.raw / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _manifest(paths: DataPaths, entries: list[dict[str, object]]) -> None:
    paths.manifest.parent.mkdir(parents=True, exist_ok=True)
    with paths.manifest.open("a", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(json.dumps(entry) + "\n")


def test_loader_reads_commentators_pages_and_releases_with_save_times(tmp_path: Any) -> None:
    paths = _vault(tmp_path)
    commentators = _page(
        URL_B,
        "single single-post post-template-default",
        _ROW.format(names="Avery Lane, Morgan Pike"),
        published="2022-10-03T15:30:00-04:00",
        heading="WEEK 6",
    )
    release = _page(
        URL,
        "single single-press-release",
        _ROW.format(names="Blair Tolley, Casey Lorn"),
        published="2022-10-03T14:00:00-04:00",
        heading="College Football on ESPN &#8211; WEEK 6",
    )
    _write(paths, "espnpr/2022/commentators/wk-6.html", commentators)
    _write(paths, "espnpr/2022/releases/synthetic-week-6-college-football-coverage.html", release)
    _write(paths, "espnpr/2022/ratings/ignored.html", "<html></html>")
    _manifest(
        paths,
        [
            {
                "source": "espnpr",
                "path": "espnpr/2022/commentators/wk-6.html",
                "url": URL_B,
                "saved_at": "2022-10-04T01:00:00Z",
                "fetched_at": "2026-10-13T00:00:00Z",
            },
            {
                "source": "espnpr",
                "path": "espnpr/2022/commentators/wk-6.html",
                "url": URL_B,
                "saved_at": "2022-10-05T01:00:00Z",
                "fetched_at": "2026-10-13T00:01:00Z",
            },
            {"source": "sports506", "path": "sports506/2022/wk-06.html"},
        ],
    )
    loaded = load_espnpr_booths(paths)
    assert loaded.rejected == ()
    by_pointer = {b.booth.pointer: b for b in loaded.booths}
    assert set(by_pointer) == {"wk-6:1", "synthetic-week-6-college-football-coverage:1"}
    assert by_pointer["wk-6:1"].saved_at == "2022-10-05T01:00:00Z"  # the newest manifest line
    assert by_pointer["wk-6:1"].booth.source_url == URL_B
    # No manifest line: the page's own canonical URL and published time.
    release_booth = by_pointer["synthetic-week-6-college-football-coverage:1"]
    assert release_booth.saved_at == "2022-10-03T18:00:00Z"
    assert release_booth.booth.source_url == URL
    assert release_booth.booth.tv_names == ("Blair Tolley", "Casey Lorn")
    assert load_espnpr_booths(paths, seasons=[2021]).booths == []


def test_loader_without_pages_is_empty(tmp_path: Any) -> None:
    loaded = load_espnpr_booths(_vault(tmp_path))
    assert (loaded.booths, loaded.rejected) == ([], ())


def test_loader_skips_and_lists_an_unidentifiable_page(tmp_path: Any) -> None:
    paths = _vault(tmp_path)
    _write(paths, "espnpr/2022/releases/broken.html", "<html><body>SENTINEL TEXT</body></html>")
    loaded = load_espnpr_booths(paths)
    assert loaded.booths == []
    (page,) = loaded.rejected
    assert (page.source, page.season, page.path, page.reason) == (
        "espnpr",
        2022,
        "espnpr/2022/releases/broken.html",
        "no_canonical_url",
    )
