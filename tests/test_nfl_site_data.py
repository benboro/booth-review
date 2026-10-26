"""Builder tests for nfl-data.json on synthetic frames (no vault reads)."""

from __future__ import annotations

import csv
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from booth_review.build.nfl_site_data import (
    NFL_NETWORK_NAMES,
    NFL_SITE_DATA_PATH,
    NflSiteInputs,
    build_nfl_site_data,
    load_nfl_site_inputs,
    nfl_site_payload_bytes,
    write_nfl_site_data,
)
from booth_review.config import DataPaths
from booth_review.contract.nfl_models import (
    NFL_SLOTS,
    NFL_VIEW_CATEGORIES,
    validate_nfl_site_data,
)
from booth_review.errors import SiteBuildError
from booth_review.flags.era import MeasurementEra
from booth_review.nfl.adjust import LOW_N
from booth_review.nfl.games import NFL_GAME_COLUMNS, NFL_GAME_SCHEMA
from booth_review.nfl.reference import FranchiseName, NflFranchises
from booth_review.nfl.tables import (
    _SPECIAL_SCHEMA,
    NFL_SPECIAL_COLUMNS,
    SLOT_COLUMNS,
    SOLO_GROUPS,
)
from booth_review.nfl.task1 import NFL_TASK1_COLUMNS, NFL_TASK1_SCHEMA, VIEW_CATEGORY_ORDER
from booth_review.people.registry import PeopleRegistry, Person

REFERENCE = Path(__file__).parent / "fixtures" / "nfl" / "reference"
FRANCHISE_IDS = ("alpha", "beta", "gamma", "delta")
ERAS = (
    MeasurementEra(
        "era-a",
        "Era A",
        date(2014, 1, 1),
        date(2019, 12, 31),
        frozenset(),
        "https://example.com/a",
        "",
    ),
    MeasurementEra(
        "era-b", "Era B", date(2020, 1, 1), None, frozenset(), "https://example.com/b", ""
    ),
)
EXCLUDED = (
    "pregame_spread",
    "coverage_share",
    "crew_names",
    "wp_volatility",
    "wp_plays",
    "window",
    "network_source",
    "rr_network_ids",
    "raw_mean_abs_spread",
)


def _registry() -> PeopleRegistry:
    names = {
        "p-lead": "Lee Lead",
        "a-one": "Ann One",
        "p-two": "Pat Two",
        "a-two": "Al Two",
        "side": "Sid Side",
        "unused": "Una Used",
    }
    return PeopleRegistry(
        {pid: Person(pid, name, (name,), "pbp", None) for pid, name in names.items()}
    )


def _franchises() -> NflFranchises:
    names = {
        fid: (FranchiseName(None, None, f"{fid.title()} Town", f"{fid.title()}s"),)
        for fid in FRANCHISE_IDS
    }
    names["alpha"] = (
        FranchiseName(None, 2023, "Alpha Old Town", "Olds"),
        FranchiseName(2024, None, "Alpha Town", "Alphas"),
    )
    return NflFranchises(names)


def _game(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = dict.fromkeys(NFL_GAME_COLUMNS)
    day = date(2024, 9, 8)
    row.update(
        season=2024,
        week=1,
        game_type="REG",
        game_id="g0",
        game_date=day,
        kickoff_utc=datetime(2024, 9, 8, 17, 0, tzinfo=UTC),
        weekday="Sunday",
        home_franchise_id="alpha",
        away_franchise_id="beta",
        home_display_name="Alpha Town",
        away_display_name="Beta Town",
        is_international=False,
        network_id="cbs",
        is_standalone=False,
        slot_name="Sunday early",
        fox_dh_sunday=False,
        cbs_dh_sunday=False,
        is_agotw=False,
        is_cbs_national=False,
        late_national_status="not_dh",
        flexed=False,
        is_special=False,
        pregame_spread=3.5,
        crew_names=["Raw Name"],
        wp_volatility=1.5,
        wp_plays=100,
        window="early",
        network_source="506",
        rr_network_ids=["cbs"],
        excitement_score=1.23456,
        final_margin=3,
        home_points=24,
        away_points=21,
    )
    row.update(overrides)
    if row["pbp_person_id"] is not None and row["crew_source"] is None:
        row["crew_source"] = "506"
    return row


def _frame(rows: list[dict[str, Any]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=NFL_GAME_SCHEMA, orient="row").select(NFL_GAME_COLUMNS)


def _special_rows(
    games: pl.DataFrame, week_counts: dict[int, tuple[int, int, int, int]]
) -> pl.DataFrame:
    reg = games.filter(pl.col("game_type") == "REG")
    rows: list[dict[str, Any]] = []
    keys = sorted(
        {
            (g[f"{side}_franchise_id"], g["season"])
            for g in reg.iter_rows(named=True)
            for side in ("home", "away")
        }
    )
    for fid, season in keys:
        mine = [
            g
            for g in reg.iter_rows(named=True)
            if g["season"] == season and fid in (g["home_franchise_id"], g["away_franchise_id"])
        ]
        row: dict[str, Any] = dict.fromkeys(NFL_SPECIAL_COLUMNS, 0)
        stand = [g for g in mine if g["is_standalone"]]
        row.update(
            franchise_id=fid,
            season=season,
            display_name=fid,
            games=len(mine),
            standalone_total=len(stand),
            agotw=sum(bool(g["is_agotw"]) for g in mine),
            cbs_national=sum(bool(g["is_cbs_national"]) for g in mine),
            international=sum(bool(g["is_international"]) for g in mine),
            international_other=sum(
                bool(g["is_international"])
                and not (g["is_standalone"] or g["is_agotw"] or g["is_cbs_national"])
                for g in mine
            ),
            flexed=sum(bool(g["flexed"]) for g in mine),
        )
        for label, suffix in SLOT_COLUMNS.items():
            row[f"standalone_{suffix}"] = sum(g["slot_name"] == label for g in stand)
        for suffix, labels in SOLO_GROUPS.items():
            row[f"solo_{suffix}"] = sum(g["slot_name"] in labels for g in stand)
        row["special"] = row["standalone_total"] + row["agotw"] + row["cbs_national"]
        fox_dh, fox_amb, cbs_dh, cbs_amb = week_counts.get(season, (0, 0, 0, 0))
        row.update(
            fox_doubleheader_weeks=fox_dh,
            fox_ambiguous_weeks=fox_amb,
            cbs_doubleheader_weeks=cbs_dh,
            cbs_ambiguous_weeks=cbs_amb,
            agotw_rate=row["agotw"] / (fox_dh - fox_amb) if fox_dh - fox_amb > 0 else None,
            cbs_national_rate=(
                row["cbs_national"] / (cbs_dh - cbs_amb) if cbs_dh - cbs_amb > 0 else None
            ),
            through_week=1,
        )
        rows.append(row)
    return pl.DataFrame(rows, schema=_SPECIAL_SCHEMA, orient="row").select(NFL_SPECIAL_COLUMNS)


def _t1(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = dict.fromkeys(NFL_TASK1_COLUMNS)
    row.update(coverage_normalized=False, excitement_method="GEI-style", low_n=False)
    for name in NFL_TASK1_COLUMNS:
        if name.startswith(("raw_n_", "adj_n_")):
            row[name] = 3
    row.update(
        games=3,
        flagship_games=0,
        fill_in_games=0,
        lineup_games=0,
        view="booth",
        network_group="fox",
        rank_source="inferred",
    )
    row.update(overrides)
    return row


def _task1(rows: list[dict[str, Any]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=NFL_TASK1_SCHEMA, orient="row").select(NFL_TASK1_COLUMNS)


def _fox(game_id: str, season: int, week: int, pbp: str, analyst: str, **kw: Any) -> dict[str, Any]:
    return _game(
        game_id=game_id,
        season=season,
        week=week,
        game_date=date(season, 9, 7) + timedelta(days=7 * (week - 1)),
        kickoff_utc=datetime(season, 9, 7, 20, 25, tzinfo=UTC) + timedelta(days=7 * (week - 1)),
        network_id="fox",
        fox_dh_sunday=True,
        late_national_status="single",
        pbp_person_id=pbp,
        analyst_person_id=analyst,
        slot_name="Sunday late",
        **kw,
    )


def _scenario() -> NflSiteInputs:
    rows = [
        # season 2023, complete: lead booth calls two AGOTW games, other booth one game
        _fox(
            "g1",
            2023,
            1,
            "p-lead",
            "a-one",
            is_agotw=True,
            viewership=9_000_000.4,
            viewership_scope="window",
            era_id="era-a",
            rr_record_url="https://example.com/r1",
            rr_source_url="https://example.com/s1",
            home_franchise_id="alpha",
            away_franchise_id="gamma",
            home_display_name="Alpha Old Town",
            away_display_name="Gamma Town",
        ),
        _fox(
            "g2",
            2023,
            2,
            "p-lead",
            "a-one",
            is_agotw=True,
            viewership=8_000_000.0,
            viewership_scope="window",
            era_id="era-a",
            home_franchise_id="beta",
            away_franchise_id="delta",
        ),
        _fox("g3", 2023, 3, "p-two", "a-two", home_franchise_id="gamma", away_franchise_id="delta"),
        # season 2024, in progress through week 2
        _fox(
            "g4",
            2024,
            1,
            "p-lead",
            "a-one",
            is_agotw=True,
            viewership=7_000_000.0,
            viewership_scope="window",
            era_id="era-b",
            home_franchise_id="alpha",
            away_franchise_id="beta",
        ),
        _fox("g5", 2024, 2, "p-two", "a-two", home_franchise_id="gamma", away_franchise_id="alpha"),
        _game(
            game_id="g6",
            season=2024,
            week=3,
            game_date=date(2024, 9, 22),
            home_points=None,
            away_points=None,
            final_margin=None,
            excitement_score=None,
            home_franchise_id="beta",
            away_franchise_id="gamma",
        ),
        _game(
            game_id="po",
            game_type="POST",
            season=2024,
            week=19,
            home_franchise_id="beta",
            away_franchise_id="delta",
        ),
    ]
    games = _frame(rows)
    # g1 and g3 get sideline crew; g4 flexed with a Wikipedia change
    people_rows = games.to_dicts()
    for g in people_rows:
        if g["game_id"] == "g1":
            g["sideline_person_ids"] = ["side"]
        if g["game_id"] == "g4":
            g.update(
                flexed=True,
                original_slot="SNF",
                original_network="nbc",
                change_article_url="https://example.com/change",
            )
    games = pl.DataFrame(people_rows, schema=NFL_GAME_SCHEMA, orient="row").select(NFL_GAME_COLUMNS)
    special = _special_rows(games, {2023: (3, 1, 1, 1), 2024: (2, 0, 0, 0)})
    task1 = _task1(
        [
            _t1(
                season=2023,
                booth_group="lead",
                booth_rank=1,
                booth_pbp_person_id="p-lead",
                regular_analyst_person_id="a-one",
                games=2,
                flagship_games=2,
            ),
            _t1(
                season=2023,
                booth_group="other",
                booth_rank=2,
                booth_pbp_person_id="p-two",
                regular_analyst_person_id="a-two",
                games=1,
                low_n=True,
            ),
            _t1(
                season=2024,
                booth_group="lead",
                booth_rank=1,
                booth_pbp_person_id="p-lead",
                regular_analyst_person_id="a-one",
                games=1,
                flagship_games=1,
            ),
            _t1(
                view="category_viewership",
                view_category="agotw",
                season=2023,
                era_id="era-a",
                n_viewership=2,
                mean_viewers=8_500_000.0,
                viewership_resid=1.0,
                viewership_se=2.0,
            ),
            _t1(
                view="category_viewership",
                view_category="agotw",
                season=2024,
                era_id="era-b",
                n_viewership=1,
                mean_viewers=7_000_000.0,
                low_n=True,
            ),
        ]
    )
    return NflSiteInputs(games, special, task1, _registry(), _franchises(), ERAS)


def _build() -> Any:
    return build_nfl_site_data(_scenario())


def _single(rows: list[dict[str, Any]], task1_rows: list[dict[str, Any]] | None = None) -> Any:
    """Build from a few games and no booth or viewership rows unless given."""
    games = _frame(rows)
    special = _special_rows(games, {})
    task1 = _task1(task1_rows or [])
    return build_nfl_site_data(
        NflSiteInputs(games, special, task1, _registry(), _franchises(), ERAS)
    )


def test_override_lead_without_games_does_not_break_the_build() -> None:
    from booth_review.nfl.booths import build_booths
    from booth_review.nfl.reference import NflLeadBoothOverride

    rows = [
        _fox("g1", 2023, 1, "p-lead", "a-one", is_agotw=True),
        _fox("g2", 2023, 2, "p-two", "a-two"),
    ]
    games = _frame(rows)
    over = {("fox", 2023): NflLeadBoothOverride(2023, "fox", "unused", "reported", "https://e.com")}
    out = build_booths(games.with_columns(pl.lit("506").alias("crew_source")), {}, over)
    assert out.reviews["lead_booth"][0]["reason"] == "override-no-games"
    t1 = [
        _t1(
            season=2023,
            booth_group="other",
            booth_rank=b["booth_rank"],
            booth_pbp_person_id=b["booth_pbp_person_id"],
            regular_analyst_person_id=b["regular_analyst_person_id"],
            rank_source=b["rank_source"],
            games=b["games"],
            flagship_games=b["flagship_games"],
            raw_n_viewers=0,
        )
        for b in out.booths.iter_rows(named=True)
    ]
    site = _single(rows, t1)
    assert {b for b in site.booths.rank_source} == {"games"}
    assert not any(site.booths.is_lead)
    validate_nfl_site_data(site.model_dump(mode="json"))


# ---------------------------------------------------------------- games block


def test_regular_season_only_and_validates() -> None:
    site = _build()
    assert len(site.games.season) == 6
    assert 19 not in site.games.week
    validate_nfl_site_data(site.model_dump(mode="json"))


def test_kickoff_et_follows_dst() -> None:
    site = _single(
        [
            _game(
                game_id="a",
                game_date=date(2025, 9, 7),
                season=2025,
                kickoff_utc=datetime(2025, 9, 7, 17, 0, tzinfo=UTC),
            ),
            _game(
                game_id="b",
                game_date=date(2025, 11, 9),
                season=2025,
                week=10,
                kickoff_utc=datetime(2025, 11, 9, 18, 0, tzinfo=UTC),
            ),
            _game(
                game_id="c", game_date=date(2025, 11, 16), season=2025, week=11, kickoff_utc=None
            ),
        ]
    )
    assert site.games.kickoff == [
        "2025-09-07T13:00:00-04:00",
        "2025-11-09T13:00:00-05:00",
        None,
    ]


def test_franchise_and_team_name_lookups() -> None:
    site = _build()
    by_id = {f.id: f.name for f in site.lookups.franchises}
    assert by_id["alpha"] == "Alpha Town"
    assert [f.id for f in site.lookups.franchises] == sorted(by_id)
    names = [(n.name, n.short) for n in site.lookups.team_names]
    assert ("Alpha Old Town", "Olds") in names
    assert ("Alpha Town", "Alphas") in names
    g1 = site.games.season.index(2023)
    assert site.lookups.team_names[site.games.home_name[g1]].name == "Alpha Old Town"


def test_network_lookup_and_null() -> None:
    site = _build()
    assert {(n.id, n.name, n.family) for n in site.lookups.networks} == {
        ("fox", "Fox", "fox"),
        ("cbs", "CBS", "cbs"),
        ("nbc", "NBC", "nbc"),
    }
    site2 = _single([_game(network_id=None)])
    assert site2.games.network == [None]


def test_network_families() -> None:
    site = _single(
        [
            _game(game_id="a", network_id="abc"),
            _game(game_id="b", week=2, network_id="peacock"),
            _game(game_id="c", week=3, network_id="nfln"),
        ]
    )
    assert {n.id: n.family for n in site.lookups.networks} == {
        "abc": "disney",
        "peacock": "nbc",
        "nfln": "other",
    }


def test_network_groups_list_shipped_groups_in_picker_order() -> None:
    site = _build()
    groups = site.lookups.network_groups
    assert [g.id for g in groups] == ["fox", "cbs", "nbc"]
    assert [g.flagship for g in groups] == ["AGOTW", "Late national", "SNF"]
    nets = site.lookups.networks
    assert [[nets[m].id for m in g.members] for g in groups] == [["fox"], ["cbs"], ["nbc"]]


def test_null_network_game_enters_no_group() -> None:
    site = _single([_game(network_id=None)])
    assert site.games.network == [None]
    assert site.lookups.network_groups == []


def test_view_categories_ship_in_contract_order() -> None:
    assert tuple(c[0] for c in NFL_VIEW_CATEGORIES) == VIEW_CATEGORY_ORDER
    site = _build()
    assert [(c.id, c.label, c.window_level) for c in site.lookups.view_categories] == list(
        NFL_VIEW_CATEGORIES
    )


def test_network_names_cover_reference_table() -> None:
    with (REFERENCE / "nfl_networks.csv").open(newline="") as handle:
        ids = {row["network_id"] for row in csv.DictReader(handle)}
    assert ids <= set(NFL_NETWORK_NAMES)
    assert NFL_NETWORK_NAMES["prime"] == "Prime Video"


def test_unknown_network_raises_position_only() -> None:
    with pytest.raises(SiteBuildError) as err:
        _single([_game(network_id="mystery-net")])
    assert "mystery-net" not in str(err.value)
    assert "games.network[0]" in str(err.value)


def test_crew_roles_and_referenced_people_only() -> None:
    site = _build()
    people = {p.id: p.name for p in site.lookups.people}
    assert "unused" not in people
    assert people["p-lead"] == "Lee Lead"
    i = site.games.season.index(2023)
    roles = [(site.lookups.people[c.person].id, c.role) for c in site.games.crew[i]]
    assert roles == [("p-lead", "pbp"), ("a-one", "analyst"), ("side", "unknown")]


def test_published_lineup_crew_ships_with_its_citation() -> None:
    site = _single(
        [
            _game(
                game_id="pl",
                pbp_person_id="p-lead",
                analyst_person_id="a-one",
                crew_source="published_lineup",
                crew_source_url="https://example.com/lineup",
            ),
            _game(
                game_id="s5",
                week=2,
                pbp_person_id="p-two",
                crew_source="506",
                crew_source_url="https://example.com/leaked",
            ),
        ]
    )
    assert site.games.crew_source == ["published_lineup", "506"]
    assert site.games.crew_source_url == ["https://example.com/lineup", None]
    assert [c.role for c in site.games.crew[0]] == ["pbp", "analyst"]


def test_missing_registry_person_raises_without_value() -> None:
    with pytest.raises(SiteBuildError) as err:
        _single([_game(pbp_person_id="ghost-person")])
    assert "ghost-person" not in str(err.value)
    assert "games.crew[0]" in str(err.value)


def test_flexed_wikipedia_fields() -> None:
    site = _build()
    i = next(k for k, f in enumerate(site.games.flexed) if f)
    assert NFL_SLOTS[site.games.original_slot[i] or 0] == "SNF"
    assert site.lookups.networks[site.games.original_network[i] or 0].id == "nbc"
    assert site.games.change_url[i] == "https://example.com/change"
    others = [k for k in range(len(site.games.flexed)) if k != i]
    assert all(site.games.original_slot[k] is None for k in others)
    assert all(site.games.change_url[k] is None for k in others)


def test_score_excitement_and_viewership_fields() -> None:
    site = _build()
    i = site.games.season.index(2023)
    assert site.games.home_points[i] == 24
    assert site.games.final_margin[i] == 3
    assert site.games.excitement[i] == 1.235
    assert site.games.viewers[i] == 9_000_000
    assert site.games.scope[i] == "window"
    assert site.lookups.eras[site.games.era[i] or 0].id == "era-a"
    assert site.games.rr_url[i] == "https://example.com/r1"
    assert site.games.source_url[i] == "https://example.com/s1"
    pending = next(k for k, h in enumerate(site.games.home_points) if h is None)
    assert site.games.excitement[pending] is None
    assert site.games.scope[pending] is None
    assert site.games.era[pending] is None


def test_unrated_causes() -> None:
    rows = [
        _game(game_id="r1", season=2023, week=1, slot_name="Sunday early"),
        _game(game_id="r2", season=2023, week=2, slot_name="TNF", is_standalone=True),
        _game(game_id="r3", season=2023, week=3, slot_name="Sunday late", is_agotw=True),
        _game(
            game_id="r4",
            season=2024,
            week=1,
            viewership=5_000_000.0,
            viewership_scope="window",
            era_id="era-b",
        ),
        _game(game_id="r5", season=2024, week=2),
        _game(
            game_id="r6",
            season=2024,
            week=3,
            viewership=None,
            home_points=None,
            away_points=None,
            final_margin=None,
        ),
    ]
    site = _single(rows)
    assert site.freshness.in_progress
    assert site.freshness.viewership_through_week == 1
    assert site.games.cause == ["regional", "none", "none", None, "pending", "pending"]


def test_pending_outlives_the_last_score_like_cfb() -> None:
    # Iter-2 WR-01: figures keep arriving after the last score is in, so a
    # complete current season stays "pending" at and after the stamp week,
    # the CFB rule. Before the stamp week a game is regional or has none.
    rated = {"viewership": 5_000_000.0, "viewership_scope": "window", "era_id": "era-b"}
    rows = [
        _game(game_id="c1", season=2024, week=1, slot_name="Sunday early"),
        _game(game_id="c2", season=2024, week=2, **rated),
        _game(game_id="c3", season=2024, week=2, slot_name="Sunday late"),
        _game(game_id="c4", season=2024, week=3, slot_name="SNF", is_standalone=True),
    ]
    site = _single(rows)
    assert not site.freshness.in_progress
    assert site.freshness.viewership_through_week == 2
    assert site.games.cause == ["regional", None, "pending", "pending"]


def test_a_season_that_is_no_longer_current_is_never_pending() -> None:
    # Iter-2 WR-01: once a later season is current, an earlier season's
    # unrated games are regional or have none, a never-scored (cancelled) game
    # included. A current season with no figure yet is pending throughout.
    unscored = {"home_points": None, "away_points": None, "final_margin": None}
    rows = [
        _game(
            game_id="p1",
            season=2023,
            week=17,
            viewership=4_000_000.0,
            viewership_scope="window",
            era_id="era-a",
        ),
        _game(game_id="p2", season=2023, week=17, slot_name="Sunday early", **unscored),
        _game(game_id="p3", season=2023, week=18, slot_name="Sunday late"),
        _game(game_id="p4", season=2023, week=18, slot_name="SNF", is_standalone=True),
        _game(game_id="n1", season=2024, week=1, slot_name="Sunday early"),
        _game(game_id="n2", season=2024, week=2, slot_name="MNF", is_standalone=True, **unscored),
    ]
    site = _single(rows)
    assert site.freshness.season == 2024
    assert site.freshness.viewership_through_week is None
    assert site.games.cause == [None, "regional", "regional", "none", "pending", "pending"]


def _all_keys(node: Any) -> set[str]:
    if isinstance(node, dict):
        return set(node) | {k for v in node.values() for k in _all_keys(v)}
    if isinstance(node, list):
        return {k for v in node for k in _all_keys(v)}
    return set()


def test_analysis_only_names_never_ship() -> None:
    dumped = _build().model_dump(mode="json")
    assert not _all_keys(dumped) & set(EXCLUDED)
    assert "Raw Name" not in nfl_site_payload_bytes(_build()).decode()


# ------------------------------------------------------- freshness, constants


def test_freshness_in_progress() -> None:
    f = _build().freshness
    assert (f.season, f.in_progress, f.through_week, f.viewership_through_week) == (
        2024,
        True,
        2,
        1,
    )
    assert f.crews_default_season == 2023


def test_freshness_complete_season_uses_latest_booth_season() -> None:
    inputs = _scenario()
    games = inputs.games.with_columns(
        pl.when(pl.col("home_points").is_null())
        .then(1)
        .otherwise(pl.col("home_points"))
        .alias("home_points"),
        pl.when(pl.col("away_points").is_null())
        .then(0)
        .otherwise(pl.col("away_points"))
        .alias("away_points"),
        pl.when(pl.col("final_margin").is_null())
        .then(1)
        .otherwise(pl.col("final_margin"))
        .alias("final_margin"),
    )
    site = build_nfl_site_data(
        NflSiteInputs(
            games, inputs.special, inputs.task1, inputs.people, inputs.franchises, inputs.eras
        )
    )
    assert not site.freshness.in_progress
    assert site.freshness.crews_default_season == 2024


def test_crews_default_null_without_booth_rows() -> None:
    inputs = _scenario()
    task1 = inputs.task1.filter(pl.col("view") != "booth")
    site = build_nfl_site_data(
        NflSiteInputs(
            inputs.games, inputs.special, task1, inputs.people, inputs.franchises, inputs.eras
        )
    )
    assert site.freshness.crews_default_season is None


def test_constants() -> None:
    c = _build().constants
    assert (c.viewership_scope, c.coverage_normalized, c.excitement_method) == (
        "window",
        False,
        "GEI-style",
    )
    assert c.low_n_threshold == LOW_N


@pytest.mark.parametrize(
    ("column", "value"), [("coverage_normalized", True), ("excitement_method", "CFBD")]
)
def test_task1_constant_violations_raise(column: str, value: object) -> None:
    inputs = _scenario()
    task1 = inputs.task1.with_columns(
        pl.when(pl.int_range(pl.len()) == 0)
        .then(pl.lit(value))
        .otherwise(pl.col(column))
        .alias(column)
    )
    with pytest.raises(SiteBuildError, match=column):
        build_nfl_site_data(
            NflSiteInputs(
                inputs.games, inputs.special, task1, inputs.people, inputs.franchises, inputs.eras
            )
        )


# ------------------------------------------------------------ aggregate blocks


def test_special_rows_copy_counts_and_rates() -> None:
    site = _build()
    s = site.special
    assert s.special == [
        a + b + c for a, b, c in zip(s.standalone_total, s.agotw, s.cbs_national, strict=True)
    ]
    k = next(
        i
        for i in range(len(s.season))
        if s.season[i] == 2023 and site.lookups.franchises[s.franchise[i]].id == "alpha"
    )
    assert s.agotw[k] == 1
    assert s.agotw_rate[k] == pytest.approx(1 / 2)
    assert s.cbs_national_rate[k] is None  # cbs doubleheader weeks 1 minus ambiguous 1 = 0


def test_international_other_counts_once() -> None:
    site = _single(
        [
            _game(
                game_id="i1", is_international=True, slot_name="International", is_standalone=True
            ),
            _game(game_id="i2", week=2, is_international=True),
        ]
    )
    k = site.lookups.franchises[0].id
    assert k == "alpha"
    assert site.special.international[0] == 2
    assert site.special.international_other[0] == 1
    assert site.special.standalone_total[0] == 1


def test_solo_columns_ship_and_sum_to_standalone() -> None:
    site = _single(
        [
            _game(game_id="t", slot_name="TNF", is_standalone=True),
            _game(game_id="x", week=2, slot_name="Christmas", is_standalone=True),
            _game(game_id="y", week=3, slot_name="Saturday", is_standalone=True),
        ]
    )
    s = site.special
    assert (s.solo_thursday[0], s.solo_holiday[0], s.solo_other[0]) == (1, 1, 1)
    assert s.solo_sunday[0] == s.solo_monday[0] == 0
    assert s.standalone_total[0] == 3


def test_solo_mismatch_raises_position_only() -> None:
    inputs = _scenario()
    bad = inputs.special.with_columns(
        pl.when(pl.int_range(pl.len()) == 1)
        .then(pl.col("solo_other") + 1)
        .otherwise(pl.col("solo_other"))
        .alias("solo_other")
    )
    with pytest.raises(SiteBuildError) as err:
        build_nfl_site_data(
            NflSiteInputs(
                inputs.games, bad, inputs.task1, inputs.people, inputs.franchises, inputs.eras
            )
        )
    assert str(err.value) == "special[1]: exclusive category counts do not match games"


def test_special_mismatch_raises_position_only() -> None:
    inputs = _scenario()
    bad = inputs.special.with_columns(
        pl.when(pl.int_range(pl.len()) == 1)
        .then(pl.col("agotw") + 1)
        .otherwise(pl.col("agotw"))
        .alias("agotw"),
        pl.when(pl.int_range(pl.len()) == 1)
        .then(pl.col("special") + 1)
        .otherwise(pl.col("special"))
        .alias("special"),
    )
    with pytest.raises(SiteBuildError) as err:
        build_nfl_site_data(
            NflSiteInputs(
                inputs.games, bad, inputs.task1, inputs.people, inputs.franchises, inputs.eras
            )
        )
    assert str(err.value) == "special[1]: exclusive category counts do not match games"


def test_season_weeks_one_row_per_season() -> None:
    w = _build().season_weeks
    assert w.season == [2023, 2024]
    assert w.fox_doubleheader_weeks == [3, 2]
    assert w.cbs_ambiguous_weeks == [1, 0]
    assert w.fox_ambiguous_weeks == [1, 0]


def test_season_weeks_mismatch_raises() -> None:
    inputs = _scenario()
    bad = inputs.special.with_columns(
        pl.when(pl.int_range(pl.len()) == 0)
        .then(pl.col("fox_doubleheader_weeks") + 1)
        .otherwise(pl.col("fox_doubleheader_weeks"))
        .alias("fox_doubleheader_weeks")
    )
    with pytest.raises(SiteBuildError, match="season_weeks"):
        build_nfl_site_data(
            NflSiteInputs(
                inputs.games, bad, inputs.task1, inputs.people, inputs.franchises, inputs.eras
            )
        )


def _ids(site: Any, idx: list[int]) -> list[str]:
    return [site.games.season[i] and f"{site.games.season[i]}-{site.games.week[i]}" for i in idx]


def test_booths_rows_and_game_lists() -> None:
    site = _build()
    b = site.booths
    assert b.season == [2023, 2023, 2024]
    assert [site.lookups.network_groups[g].id for g in b.network_group] == ["fox"] * 3
    assert b.is_lead == [True, False, True]
    assert b.rank == [1, 2, 1]
    assert b.rank_source == ["inferred"] * 3
    assert b.low_n == [False, True, False]
    assert site.lookups.people[b.pbp_person[0]].id == "p-lead"
    assert _ids(site, b.game_list[0]) == ["2023-1", "2023-2"]
    assert _ids(site, b.game_list[1]) == ["2023-3"]
    assert _ids(site, b.game_list[2]) == ["2024-1"]
    assert all(len(g) == n for g, n in zip(b.game_list, b.games, strict=True))


def test_zero_game_published_booth_ships_an_empty_list() -> None:
    site = _single(
        [_fox("f1", 2024, 1, "p-lead", "a-one")],
        [
            _t1(
                season=2024,
                booth_group="lead",
                booth_rank=1,
                rank_source="published",
                booth_pbp_person_id="p-lead",
                regular_analyst_person_id="a-one",
                games=1,
            ),
            _t1(
                season=2024,
                booth_group="other",
                booth_rank=2,
                rank_source="published",
                booth_pbp_person_id="p-two",
                games=0,
                raw_n_margin=0,
                raw_n_excitement=0,
                raw_n_viewers=0,
                adj_n_margin=0,
                adj_n_excitement=0,
            ),
        ],
    )
    assert site.booths.games == [1, 0]
    assert site.booths.game_list[1] == []
    assert site.booths.rank_source == ["published", "published"]


def test_games_ranked_group_season_ships_without_a_lead() -> None:
    site = _single(
        [_fox("f1", 2024, 1, "p-lead", "a-one"), _fox("f2", 2024, 2, "p-two", "a-two")],
        [
            _t1(
                season=2024,
                booth_group="other",
                booth_rank=rank,
                rank_source="games",
                booth_pbp_person_id=pbp,
                games=1,
            )
            for rank, pbp in ((1, "p-lead"), (2, "p-two"))
        ],
    )
    b = site.booths
    assert b.rank == [1, 2]
    assert b.rank_source == ["games", "games"]
    assert b.is_lead == [False, False]
    assert [len(g) for g in b.game_list] == [1, 1]


def test_a_null_rank_booth_row_is_a_build_error() -> None:
    with pytest.raises(SiteBuildError) as err:
        _single(
            [_fox("f1", 2024, 1, "p-lead", "a-one")],
            [_t1(season=2024, booth_group="other", booth_rank=None, booth_pbp_person_id="p-lead")],
        )
    assert "booths[0].rank" in str(err.value)


def test_booth_row_for_an_unshipped_group_raises_by_position() -> None:
    with pytest.raises(SiteBuildError) as err:
        _single(
            [_game(game_id="c1")],
            [_t1(season=2024, booth_group="lead", booth_rank=1, booth_pbp_person_id="p-lead")],
        )
    assert "booths[0].network_group" in str(err.value)


def test_viewership_rows_per_category_season_and_era() -> None:
    site = _build()
    v = site.viewership
    assert v.season == [2023, 2024]
    assert [site.lookups.view_categories[c].id for c in v.category] == ["agotw", "agotw"]
    assert [site.lookups.eras[e].id for e in v.era] == ["era-a", "era-b"]
    assert v.games == [2, 1]
    assert v.low_n == [False, True]
    assert v.mean_viewers[0] == 8_500_000.0
    assert _ids(site, v.game_list[0]) == ["2023-1", "2023-2"]
    assert _ids(site, v.game_list[1]) == ["2024-1"]


def test_viewership_unknown_era_raises_by_position() -> None:
    with pytest.raises(SiteBuildError) as err:
        _single(
            [_game(game_id="a")],
            [
                _t1(
                    view="category_viewership",
                    view_category="snf",
                    era_id="era-zzz",
                    n_viewership=1,
                )
            ],
        )
    assert "viewership[0].era" in str(err.value)


def test_forbidden_names_never_reach_the_bytes() -> None:
    body = nfl_site_payload_bytes(_build()).decode()
    for name in (
        "fox_booths",
        "agotw_viewership",
        "volatility",
        "pregame_spread",
        "coverage_share",
        "raw_mean_abs_spread",
        "others_pooled",
    ):
        assert name not in body


def test_only_referenced_eras_ship_in_era_order() -> None:
    site = _single([_game(viewership=5_000_000.0, viewership_scope="window", era_id="era-b")])
    assert [e.id for e in site.lookups.eras] == ["era-b"]
    assert site.games.era == [0]


# ------------------------------------------------------- whole payload and I/O


def test_payload_is_deterministic() -> None:
    assert nfl_site_payload_bytes(_build()) == nfl_site_payload_bytes(_build())


def test_realistic_payload_under_size_ceiling() -> None:
    rows: list[dict[str, Any]] = []
    n = 0
    for season in range(2014, 2027):
        for week in range(1, 18):
            for slot in range(16):
                n += 1
                rows.append(
                    _game(
                        game_id=f"s{n}",
                        season=season,
                        week=week,
                        game_date=date(season, 9, 1) + timedelta(days=7 * week),
                        kickoff_utc=datetime(season, 9, 1, 17, 0, tzinfo=UTC)
                        + timedelta(days=7 * week, minutes=slot),
                        home_franchise_id=FRANCHISE_IDS[slot % 4],
                        away_franchise_id=FRANCHISE_IDS[(slot + 1) % 4],
                        home_display_name=f"{FRANCHISE_IDS[slot % 4].title()} Town",
                        away_display_name=f"{FRANCHISE_IDS[(slot + 1) % 4].title()} Town",
                        pbp_person_id="p-lead",
                        analyst_person_id="a-one",
                        viewership=8_123_456.0,
                        viewership_scope="window",
                        era_id="era-b",
                        rr_record_url="https://ratingsreference.example.com/api/telecast/123456.json",
                        rr_source_url="https://news.example.com/ratings/2024/09/some-long-article-slug",
                    )
                )
    games = _frame(rows)
    inputs = NflSiteInputs(
        games,
        _special_rows(games, {}),
        _task1(
            [
                _t1(
                    season=2024,
                    network_group="cbs",
                    booth_group="lead",
                    booth_rank=1,
                    booth_pbp_person_id="p-lead",
                    regular_analyst_person_id="a-one",
                    games=16 * 17,
                )
            ]
        ),
        _registry(),
        _franchises(),
        ERAS,
    )
    assert len(nfl_site_payload_bytes(build_nfl_site_data(inputs))) < 1_572_864


def test_write_is_atomic_path(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path / "vault")
    rel = write_nfl_site_data(paths, _build())
    assert rel == NFL_SITE_DATA_PATH == "processed/nfl-data.json"
    body = (paths.vault / rel).read_bytes()
    assert body == nfl_site_payload_bytes(_build())


def test_loader_missing_table_and_column(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path / "vault")
    with pytest.raises(SiteBuildError) as err:
        load_nfl_site_inputs(paths, REFERENCE)
    assert (
        str(err.value)
        == "processed/nfl_games.parquet not found; run `booth-review nfl build` first"
    )
    inputs = _scenario()
    paths.processed.mkdir(parents=True)
    inputs.games.drop("home_points").write_parquet(paths.processed / "nfl_games.parquet")
    with pytest.raises(SiteBuildError, match=r"missing column.*home_points"):
        load_nfl_site_inputs(paths, REFERENCE)


def test_loader_roundtrip(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path / "vault")
    paths.processed.mkdir(parents=True)
    inputs = _scenario()
    inputs.games.write_parquet(paths.processed / "nfl_games.parquet")
    inputs.special.write_parquet(paths.processed / "nfl_special_games_by_team_season.parquet")
    inputs.task1.write_parquet(paths.processed / "nfl_task1_crews.parquet")
    loaded = load_nfl_site_inputs(paths, REFERENCE)
    assert loaded.games.height == inputs.games.height
    assert loaded.special.height == inputs.special.height


def test_a_nan_statistic_fails_the_build_by_position_only() -> None:
    # WR-04: polars propagates NaN through mean(); one NaN must never reach the
    # file as a bare NaN token (invalid JSON for the whole NFL side).
    inputs = _scenario()
    task1 = inputs.task1.with_columns(
        pl.when(pl.col("view") == "category_viewership")
        .then(float("nan"))
        .otherwise(pl.col("viewership_se"))
        .alias("viewership_se")
    )
    with pytest.raises(SiteBuildError) as err:
        build_nfl_site_data(
            NflSiteInputs(
                inputs.games, inputs.special, task1, inputs.people, inputs.franchises, ERAS
            )
        )
    assert "viewership.viewership_se[0]: must be finite" in str(err.value)
    assert "nan" not in str(err.value).lower()


def test_a_playoff_inclusive_special_table_is_refused_by_position() -> None:
    # WR-05 / D-17: a special table built with --include-playoffs counts playoff
    # games; even when the categories happen to match, it must not ship.
    inputs = _scenario()
    games = inputs.games.with_columns(pl.lit("REG").alias("game_type"))
    playoff_special = _special_rows(games, {2023: (3, 1, 1, 1), 2024: (2, 0, 0, 0)})
    with pytest.raises(SiteBuildError) as err:
        build_nfl_site_data(
            NflSiteInputs(
                inputs.games,
                playoff_special,
                inputs.task1,
                inputs.people,
                inputs.franchises,
                inputs.eras,
            )
        )
    assert str(err.value).startswith("special[")
    assert "].games: does not match the regular-season games" in str(err.value)


# ------------------------------------------------------- upcoming block (Phase 18)


def _up(**over: Any) -> dict[str, Any]:
    from booth_review.nfl.upcoming import UPCOMING_COLUMNS

    row: dict[str, Any] = dict.fromkeys(UPCOMING_COLUMNS)
    row.update(
        season=2024,
        week=2,
        game_id="u0",
        game_date=date(2024, 9, 15),
        kickoff_utc=datetime(2024, 9, 15, 17, 0, tzinfo=UTC),
        home_franchise_id="gamma",
        away_franchise_id="delta",
        home_display_name="Gamma Town",
        away_display_name="Delta Town",
        slot_name="Sunday early",
        is_international=False,
        is_neutral=False,
        network_id="cbs",
        network_basis="506",
        sideline_person_ids=[],
    )
    row.update(over)
    return row


def _with_upcoming(rows: list[dict[str, Any]], weekend: dict[str, Any] | None = None) -> Any:
    from booth_review.nfl.upcoming import UPCOMING_SCHEMA, WEEKEND_SCHEMA

    base = _scenario()
    upcoming = pl.DataFrame(rows, schema=UPCOMING_SCHEMA, orient="row")
    stamp = pl.DataFrame([weekend] if weekend else [], schema=WEEKEND_SCHEMA, orient="row")
    return build_nfl_site_data(
        NflSiteInputs(
            base.games,
            base.special,
            base.task1,
            base.people,
            base.franchises,
            base.eras,
            upcoming,
            stamp,
        )
    )


def test_upcoming_block_ships_tba_states_crews_and_basis() -> None:
    site = _with_upcoming(
        [
            _up(
                game_id="u-tbd",
                game_date=None,
                kickoff_utc=None,
                slot_name=None,
                network_id=None,
                network_basis=None,
                home_franchise_id="alpha",
                away_franchise_id="beta",
                home_display_name="Alpha Town",
                away_display_name="Beta Town",
            ),
            _up(
                game_id="u-slot",
                slot_name="SNF",
                network_id="nbc",
                network_basis="slot",
                kickoff_utc=datetime(2024, 9, 16, 0, 20, tzinfo=UTC),
                game_date=date(2024, 9, 15),
            ),
            _up(
                game_id="u-crew",
                pbp_person_id="p-lead",
                analyst_person_id="a-one",
                sideline_person_ids=["side"],
                crew_source="506",
                booth_rank=1,
                crew_source_url="https://506sports.com/nfl.php?yr=2024&wk=2",
                home_franchise_id="beta",
                away_franchise_id="gamma",
                home_display_name="Beta Town",
                away_display_name="Gamma Town",
            ),
        ]
    )
    u = site.upcoming
    assert len(u.season) == 3
    # dated rows first, the date-less game last
    assert u.date[-1] is None and u.kickoff[-1] is None and u.slot[-1] is None
    assert u.network[-1] is None and u.network_basis[-1] is None
    basis = {b for b in u.network_basis if b}
    assert basis == {"506", "slot"}
    crew_row = next(i for i in range(3) if u.crew[i])
    assert [e.role for e in u.crew[crew_row]] == ["pbp", "analyst", "unknown"]
    assert u.crew_source[crew_row] == "506" and u.booth_rank[crew_row] == 1
    assert u.crew_source_url[crew_row] is not None


def test_upcoming_missing_tables_give_an_empty_block(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path / "vault")
    paths.processed.mkdir(parents=True)
    inputs = _scenario()
    inputs.games.write_parquet(paths.processed / "nfl_games.parquet")
    inputs.special.write_parquet(paths.processed / "nfl_special_games_by_team_season.parquet")
    inputs.task1.write_parquet(paths.processed / "nfl_task1_crews.parquet")
    loaded = load_nfl_site_inputs(paths, REFERENCE)
    assert loaded.upcoming.height == 0 and loaded.weekend.height == 0
    from dataclasses import replace

    loaded = replace(loaded, people=inputs.people, franchises=inputs.franchises, eras=inputs.eras)
    site = build_nfl_site_data(loaded)
    assert site.upcoming.season == []
    assert site.freshness.weekend is None


def test_weekend_freshness_comes_from_the_weekend_table() -> None:
    site = _with_upcoming(
        [_up()],
        {
            "season": 2024,
            "week": 2,
            "schedule_updated_at": "2024-09-10T21:30:00Z",
            "crews_506_saved_at": None,
        },
    )
    weekend = site.freshness.weekend
    assert weekend is not None
    assert (weekend.week, weekend.schedule_updated_at, weekend.crews_506_saved_at) == (
        2,
        "2024-09-10T21:30:00Z",
        None,
    )


def test_upcoming_payload_is_deterministic_and_input_order_free() -> None:
    a = _up(
        game_id="a",
        home_franchise_id="alpha",
        away_franchise_id="beta",
        home_display_name="Alpha Town",
        away_display_name="Beta Town",
    )
    b = _up(game_id="b")
    assert nfl_site_payload_bytes(_with_upcoming([a, b])) == nfl_site_payload_bytes(
        _with_upcoming([b, a])
    )
