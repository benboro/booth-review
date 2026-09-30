"""Tests for build/site_data.py: the D-13/D-14 site-data.json contract
built from small, controlled in-memory BuildTables/CoverageReport (Plan 08-10
schemas), exercising every documented behavior deterministically.
"""

from __future__ import annotations

import ast
import json
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

from booth_review.build.coverage import build_coverage
from booth_review.build.games import GAMES_SCHEMA
from booth_review.build.people_links import PEOPLE_SCHEMA, TELECAST_PEOPLE_SCHEMA
from booth_review.build.site_data import build_site_data, time_slot, write_site_data
from booth_review.build.tables import BuildDiagnostics, BuildTables
from booth_review.build.telecasts import LISTING_LINKS_SCHEMA, TELECASTS_SCHEMA
from booth_review.build.viewership import TELECAST_FLAGS_SCHEMA, VIEWERSHIP_SCHEMA
from booth_review.config import DataPaths
from booth_review.contract.models import SITE_DATA_FIELDS, validate_site_data

_GENERATED_AT = datetime(2026, 9, 27, 12, 0, 0, tzinfo=UTC)


# -- time_slot boundaries (docs/site-data.md) -----------------------------------------------


def test_time_slot_before_14_is_noon() -> None:
    assert time_slot("2025-01-01T13:59:00-05:00") == "noon"


def test_time_slot_at_14_is_afternoon() -> None:
    assert time_slot("2025-01-01T14:00:00-05:00") == "afternoon"


def test_time_slot_at_17_59_is_afternoon() -> None:
    assert time_slot("2025-01-01T17:59:00-05:00") == "afternoon"


def test_time_slot_at_18_is_prime() -> None:
    assert time_slot("2025-01-01T18:00:00-05:00") == "prime"


def test_time_slot_at_21_59_is_prime() -> None:
    assert time_slot("2025-01-01T21:59:00-05:00") == "prime"


def test_time_slot_at_22_is_late() -> None:
    assert time_slot("2025-01-01T22:00:00-05:00") == "late"


def test_time_slot_at_23_30_is_late() -> None:
    assert time_slot("2025-01-01T23:30:00-05:00") == "late"


def test_time_slot_after_midnight_is_late() -> None:
    assert time_slot("2025-01-01T00:30:00-05:00") == "late"


def test_time_slot_at_5_is_noon() -> None:
    assert time_slot("2025-01-01T05:00:00-05:00") == "noon"


def test_time_slot_null_kickoff_is_null() -> None:
    assert time_slot(None) is None


# -- small in-memory BuildTables ------------------------------------------------------------


def _game_row(**overrides: object) -> dict[str, object]:
    defaults: dict[str, object] = {
        "game_id": 1,
        "season": 2024,
        "week": 2,
        "season_type": "regular",
        "start_utc": datetime(2024, 9, 14, 17, 30, tzinfo=UTC),
        "date_et": date(2024, 9, 14),
        "kickoff_et": "2024-09-14T13:30:00-04:00",
        "neutral_site": False,
        "conference_game": False,
        "home_id": 100,
        "home_team": "Fixture Home",
        "home_classification": "fbs",
        "home_conference": "Fixture Conference",
        "home_points": 20,
        "away_id": 200,
        "away_team": "Fixture Away",
        "away_classification": "fbs",
        "away_conference": "Fixture Conference",
        "away_points": 10,
        "excitement": 7.2,
        "closing_spread": -3.0,
        "spread_provider": "consensus",
        "pregame_x": -3.0,
        "home_win_prob": 0.65,
        "home_rank": 5,
        "away_rank": None,
        "rank_poll": "AP Top 25",
        "game_type": "regular",
        "playoff_round": None,
    }
    defaults.update(overrides)
    return defaults


def _games_frame(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=GAMES_SCHEMA)


def _telecast_row(**overrides: object) -> dict[str, object]:
    defaults: dict[str, object] = {
        "telecast_id": "1-net-a",
        "game_id": 1,
        "season": 2024,
        "date_et": date(2024, 9, 14),
        "network_id": "net-a",
        "feed_type": "main",
        "outlets": ["net-a"],
        "rated": True,
        "rr_telecast_ids": ["cfb-example-1"],
        "rr_record_urls": ["https://example.com/r1"],
        "duplicate_merges": 0,
        "rr_match_confidence": "exact",
        "s506_match_confidence": "exact",
        "match_confidence": "exact",
        "s506_pointer": "1:0",
        "s506_week": "1",
        "s506_url": "https://506sports.com/ncaaf.php?yr=2024&wk=1",
        "kickoff_et": "2024-09-14T13:30:00-04:00",
        "crew_matched": True,
        "crew_network_mismatch": False,
        "combined_feeds": None,
        "plotted": True,
        "headline_claim_id": "claim-1",
        "headline_value": 1_234_567.4,
        "headline_publisher": "Wire Service Example",
        "headline_source_url": "https://example.com/story1",
        "measurement_type": "nielsen",
        "era_id": "rr-fixture-era-2",
        "rr_current_check": "agree",
        "model_break": False,
    }
    defaults.update(overrides)
    return defaults


def _telecasts_frame(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=TELECASTS_SCHEMA)


def _flags_frame(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=TELECAST_FLAGS_SCHEMA)


def _people_frame(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=PEOPLE_SCHEMA)


def _telecast_people_frame(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=TELECAST_PEOPLE_SCHEMA)


def _empty(schema: dict[str, pl.DataType]) -> pl.DataFrame:
    return pl.DataFrame(schema=schema)


def _diagnostics(per_season: dict[int, dict[str, int]]) -> BuildDiagnostics:
    join08_by_season = {season: None for season in per_season}
    return BuildDiagnostics(
        per_season=per_season, totals={}, join08_rate=None, join08_by_season=join08_by_season
    )


def _build_tables(
    *,
    games_rows: list[dict[str, object]],
    telecast_rows: list[dict[str, object]],
    flag_rows: list[dict[str, object]],
    people_rows: list[dict[str, object]],
    telecast_people_rows: list[dict[str, object]],
) -> BuildTables:
    diagnostics = _diagnostics(
        {
            2024: {
                "rr_records": 3,
                "rr_excluded": 0,
                "rr_out_of_scope": 0,
                "rr_unmatched": 0,
                "records_with_crew": 3,
            }
        }
    )
    return BuildTables(
        games=_games_frame(games_rows),
        telecasts=_telecasts_frame(telecast_rows),
        viewership=_empty(VIEWERSHIP_SCHEMA),
        telecast_flags=_flags_frame(flag_rows),
        listing_links=_empty(LISTING_LINKS_SCHEMA),
        people=_people_frame(people_rows),
        telecast_people=_telecast_people_frame(telecast_people_rows),
        diagnostics=diagnostics,
        review_rows={"review_era_disagreements": ((), [])},
    )


def _people_rows() -> list[dict[str, object]]:
    return [
        {
            "person_id": "mike-golic-jr",
            "canonical_name": "Mike Golic Jr.",
            "variants": ["Mike Golic Jr."],
            "usual_role": "pbp",
            "registered": True,
        },
        {
            "person_id": "mike-golic",
            "canonical_name": "Mike Golic",
            "variants": ["Mike Golic"],
            "usual_role": "analyst",
            "registered": True,
        },
        {
            "person_id": "dale-harlow",
            "canonical_name": "Dale Harlow",
            "variants": ["Dale Harlow"],
            "usual_role": "unknown",
            "registered": True,
        },
        {
            "person_id": "dale-harlow-jr",
            "canonical_name": "Dale Harlow Jr.",
            "variants": ["Dale Harlow Jr."],
            "usual_role": "unknown",
            "registered": True,
        },
        {
            "person_id": "kris-venn",
            "canonical_name": "Kris Venn",
            "variants": ["Kris Venn", "Chris Venn"],
            "usual_role": "unknown",
            "registered": True,
        },
    ]


@pytest.fixture
def small_tables() -> BuildTables:
    games = [
        _game_row(game_id=1),
        _game_row(
            game_id=2,
            week=3,
            date_et=date(2024, 9, 21),
            kickoff_et=None,
            home_team="Fixture Home 2",
            away_team="Fixture Away 2",
            neutral_site=True,
            home_points=None,
            away_points=None,
            home_rank=None,
            away_rank=None,
            excitement=None,
            pregame_x=None,
        ),
        _game_row(
            game_id=3,
            week=1,
            season_type="postseason",
            date_et=date(2024, 12, 30),
            kickoff_et="2024-12-30T18:30:00-05:00",
            home_team="Fixture Bowl Home",
            away_team="Fixture Bowl Away",
            neutral_site=True,
            home_points=30,
            away_points=27,
            home_rank=None,
            away_rank=None,
            excitement=9.9,
            pregame_x=-1.0,
            game_type="bowl",
        ),
    ]
    telecasts = [
        _telecast_row(
            telecast_id="1-net-a",
            game_id=1,
            network_id="net-a",
            outlets=["net-a", "net-b"],
        ),
        _telecast_row(
            telecast_id="2-net-b",
            game_id=2,
            network_id="net-b",
            outlets=["net-b"],
            date_et=date(2024, 9, 21),
            kickoff_et=None,
            combined_feeds=2,
            headline_claim_id="claim-2",
            headline_value=54321.0,
            headline_publisher=None,
            headline_source_url=None,
            measurement_type="nielsen_adobe",
            rr_current_check=None,
            model_break=True,
            rr_telecast_ids=["cfb-example-2"],
            rr_record_urls=["https://example.com/r2"],
        ),
        _telecast_row(
            telecast_id="3-net-c",
            game_id=3,
            network_id="net-c",
            outlets=["net-c"],
            date_et=date(2024, 12, 30),
            kickoff_et="2024-12-30T18:30:00-05:00",
            headline_claim_id="claim-3",
            headline_value=2_000_000.0,
            headline_publisher="Wire Service Example",
            headline_source_url="https://example.com/story3",
            measurement_type="unknown",
            rr_telecast_ids=["cfb-example-3"],
            rr_record_urls=["https://example.com/r3"],
        ),
        # Not plotted: never referenced anywhere in the output (network net-d
        # must never appear in lookups.networks either).
        _telecast_row(
            telecast_id="4-net-d",
            game_id=1,
            network_id="net-d",
            outlets=["net-d"],
            rated=True,
            crew_matched=False,
            plotted=False,
            headline_claim_id=None,
            headline_value=None,
            headline_publisher=None,
            headline_source_url=None,
            measurement_type="unknown",
            rr_current_check=None,
            rr_telecast_ids=[],
            rr_record_urls=[],
        ),
    ]
    flags = [
        {"telecast_id": "1-net-a", "flag_id": "rr-fixture-era-2", "kind": "era"},
        {"telecast_id": "2-net-b", "flag_id": "rr-fixture-era-2", "kind": "era"},
        # Deliberately out of feed/kind order to prove the module re-sorts.
        {"telecast_id": "2-net-b", "flag_id": "fixture-event-1", "kind": "event"},
        {"telecast_id": "2-net-b", "flag_id": "combined", "kind": "combined"},
        {"telecast_id": "2-net-b", "flag_id": "nielsen_adobe", "kind": "measurement"},
        {"telecast_id": "2-net-b", "flag_id": "fixture-model-break", "kind": "model_break"},
        {"telecast_id": "3-net-c", "flag_id": "rr-fixture-era-2", "kind": "era"},
        {"telecast_id": "4-net-d", "flag_id": "rr-fixture-era-2", "kind": "era"},
    ]
    telecast_people = [
        # Inserted out of feed order (spanish, alt, main) to prove the
        # module reorders to main -> alt -> spanish regardless of frame order.
        {
            "telecast_id": "2-net-b",
            "person_id": "dale-harlow-jr",
            "role": "unknown",
            "feed_type": "spanish",
            "crew_position": 0,
            "s506_pointer": "3:0",
            "source": "registered",
        },
        {
            "telecast_id": "2-net-b",
            "person_id": "dale-harlow",
            "role": "unknown",
            "feed_type": "alt",
            "crew_position": 0,
            "s506_pointer": "3:0",
            "source": "registered",
        },
        {
            "telecast_id": "2-net-b",
            "person_id": "mike-golic",
            "role": "analyst",
            "feed_type": "main",
            "crew_position": 1,
            "s506_pointer": "3:0",
            "source": "registered",
        },
        {
            "telecast_id": "2-net-b",
            "person_id": "mike-golic-jr",
            "role": "pbp",
            "feed_type": "main",
            "crew_position": 0,
            "s506_pointer": "3:0",
            "source": "registered",
        },
        {
            "telecast_id": "1-net-a",
            "person_id": "kris-venn",
            "role": "unknown",
            "feed_type": "main",
            "crew_position": 0,
            "s506_pointer": "1:0",
            "source": "registered",
        },
    ]
    return _build_tables(
        games_rows=games,
        telecast_rows=telecasts,
        flag_rows=flags,
        people_rows=_people_rows(),
        telecast_people_rows=telecast_people,
    )


def _site(tables: BuildTables, reference_directory: Path) -> dict[str, object]:
    coverage = build_coverage(tables)
    site = build_site_data(tables, coverage, reference_directory, _GENERATED_AT)
    return site.model_dump(mode="json")


# -- behavior --------------------------------------------------------------------------------


def test_only_plotted_telecasts_appear_ordered_by_date(
    small_tables: BuildTables, build_reference: Path
) -> None:
    payload = _site(small_tables, build_reference)
    assert payload["telecasts"]["season"] == [2024, 2024, 2024]
    assert payload["telecasts"]["date"] == ["2024-09-14", "2024-09-21", "2024-12-30"]


def test_null_excitement_stays_null_never_zero(
    small_tables: BuildTables, build_reference: Path
) -> None:
    payload = _site(small_tables, build_reference)
    assert payload["telecasts"]["excitement"] == [7.2, None, 9.9]


def test_time_slot_column_matches_kickoff(small_tables: BuildTables, build_reference: Path) -> None:
    payload = _site(small_tables, build_reference)
    assert payload["telecasts"]["time_slot"] == ["noon", None, "prime"]
    assert payload["telecasts"]["kickoff"][1] is None


def test_viewers_is_rounded_int(small_tables: BuildTables, build_reference: Path) -> None:
    payload = _site(small_tables, build_reference)
    assert payload["telecasts"]["viewers"][0] == 1_234_567


def test_publisher_null_when_not_known(small_tables: BuildTables, build_reference: Path) -> None:
    payload = _site(small_tables, build_reference)
    assert payload["telecasts"]["publisher"][1] is None
    assert payload["telecasts"]["publisher"][0] == payload["telecasts"]["publisher"][2]


def test_coverage_only_network_still_enters_lookups_but_not_outlets(
    small_tables: BuildTables, build_reference: Path
) -> None:
    """net-d is never plotted (telecast 4 isn't a dot), but it is a rated
    main telecast's network, so the coverage table (AUDIT-01) still reports
    it -- it must appear in lookups.networks (a "coverage network") without
    ever appearing in any plotted telecast's own network/outlets columns.
    """
    payload = _site(small_tables, build_reference)
    network_ids_by_index = [n["id"] for n in payload["lookups"]["networks"]]
    assert "net-d" in network_ids_by_index
    assert {"net-a", "net-b", "net-c"} <= set(network_ids_by_index)

    referenced_by_telecasts: set[str] = set()
    for i, outlets in zip(
        payload["telecasts"]["network"], payload["telecasts"]["outlets"], strict=True
    ):
        referenced_by_telecasts.add(network_ids_by_index[i])
        referenced_by_telecasts.update(network_ids_by_index[j] for j in outlets)
    assert "net-d" not in referenced_by_telecasts


def test_crew_ordered_main_then_alt_then_spanish_by_position(
    small_tables: BuildTables, build_reference: Path
) -> None:
    payload = _site(small_tables, build_reference)
    people = payload["lookups"]["people"]
    crew = payload["telecasts"]["crew"][1]
    names = [people[entry["person"]]["name"] for entry in crew]
    feeds = [entry["feed"] for entry in crew]
    assert names == ["Mike Golic Jr.", "Mike Golic", "Dale Harlow", "Dale Harlow Jr."]
    assert feeds == ["main", "main", "alt", "spanish"]


def test_flags_include_era_measurement_combined_event_model_break_labels(
    small_tables: BuildTables, build_reference: Path
) -> None:
    payload = _site(small_tables, build_reference)
    flags_lookup = {f["id"]: f for f in payload["lookups"]["flags"]}
    assert flags_lookup["nielsen_adobe"]["label"] == "Nielsen+Adobe"
    assert flags_lookup["nielsen_adobe"]["kind"] == "measurement"
    assert flags_lookup["nielsen_adobe"]["source_url"] is None
    assert flags_lookup["combined"]["label"] == "Combined across feeds"
    assert flags_lookup["combined"]["source_url"] is None
    assert flags_lookup["rr-fixture-era-2"]["label"] == "Fixture Out-of-Home Era"
    assert flags_lookup["rr-fixture-era-2"]["source_url"] == "https://example.com/era2"
    assert flags_lookup["fixture-event-1"]["kind"] == "event"
    assert flags_lookup["fixture-model-break"]["kind"] == "model_break"

    flag_ids_by_index = [f["id"] for f in payload["lookups"]["flags"]]
    telecast_2_flags = {flag_ids_by_index[i] for i in payload["telecasts"]["flags"][1]}
    assert telecast_2_flags == {
        "rr-fixture-era-2",
        "fixture-event-1",
        "combined",
        "nielsen_adobe",
        "fixture-model-break",
    }


def test_combined_feeds_passthrough(small_tables: BuildTables, build_reference: Path) -> None:
    payload = _site(small_tables, build_reference)
    assert payload["telecasts"]["combined_feeds"] == [None, 2, None]


def test_coverage_all_row_aggregates_publisher_counts_across_networks(
    small_tables: BuildTables, build_reference: Path
) -> None:
    payload = _site(small_tables, build_reference)
    all_row = next(
        row for row in payload["coverage"] if row["season"] == 2024 and row["network"] is None
    )
    # telecast 2's headline has no known publisher: coverage.py's own
    # "(none)" marker (build.coverage._NO_PUBLISHER) still counts it.
    assert all_row["publisher_counts"] == {"Wire Service Example": 2, "(none)": 1}
    assert all_row["rated_telecasts"] == all_row["matched_game"]


def test_freshness_reports_postseason_when_present(
    small_tables: BuildTables, build_reference: Path
) -> None:
    payload = _site(small_tables, build_reference)
    assert payload["freshness"]["season"] == 2024
    assert payload["freshness"]["crews_through_week"] == "postseason"
    assert payload["freshness"]["viewership_through_week"] == "postseason"


def test_freshness_reports_max_regular_week_without_postseason(build_reference: Path) -> None:
    games = [_game_row(game_id=1, week=2), _game_row(game_id=2, week=3, date_et=date(2024, 9, 21))]
    telecasts = [
        _telecast_row(telecast_id="1-net-a", game_id=1),
        _telecast_row(
            telecast_id="2-net-a",
            game_id=2,
            date_et=date(2024, 9, 21),
            headline_claim_id="claim-2",
            headline_value=100.0,
            rr_telecast_ids=["cfb-example-2"],
            rr_record_urls=["https://example.com/r2"],
        ),
    ]
    tables = _build_tables(
        games_rows=games,
        telecast_rows=telecasts,
        flag_rows=[
            {"telecast_id": "1-net-a", "flag_id": "rr-fixture-era-2", "kind": "era"},
            {"telecast_id": "2-net-a", "flag_id": "rr-fixture-era-2", "kind": "era"},
        ],
        people_rows=_people_rows(),
        telecast_people_rows=[],
    )
    payload = _site(tables, build_reference)
    assert payload["freshness"]["crews_through_week"] == "3"
    assert payload["freshness"]["viewership_through_week"] == "3"


def test_site_data_column_keys_equal_site_data_fields(
    small_tables: BuildTables, build_reference: Path
) -> None:
    payload = _site(small_tables, build_reference)
    assert set(payload["telecasts"].keys()) == set(SITE_DATA_FIELDS)


def test_written_file_validates_against_the_contract(
    small_tables: BuildTables, build_reference: Path, tmp_path: Path
) -> None:
    coverage = build_coverage(small_tables)
    site = build_site_data(small_tables, coverage, build_reference, _GENERATED_AT)

    paths = DataPaths(vault=tmp_path / "vault")
    written = write_site_data(paths, site)

    assert written == ["processed/site-data.json"]
    written_path = paths.vault / "processed/site-data.json"
    assert written_path.is_file()
    body = json.loads(written_path.read_text(encoding="utf-8"))
    validate_site_data(body)


def test_written_file_is_compact_and_sorted(
    small_tables: BuildTables, build_reference: Path, tmp_path: Path
) -> None:
    coverage = build_coverage(small_tables)
    site = build_site_data(small_tables, coverage, build_reference, _GENERATED_AT)
    paths = DataPaths(vault=tmp_path / "vault")
    write_site_data(paths, site)

    text = (paths.vault / "processed/site-data.json").read_text(encoding="utf-8")
    assert "\n" not in text
    assert ", " not in text
    assert ": " not in text


def test_two_builds_with_same_generated_at_are_byte_identical(
    small_tables: BuildTables, build_reference: Path, tmp_path: Path
) -> None:
    coverage = build_coverage(small_tables)
    site_a = build_site_data(small_tables, coverage, build_reference, _GENERATED_AT)
    site_b = build_site_data(small_tables, coverage, build_reference, _GENERATED_AT)

    paths_a = DataPaths(vault=tmp_path / "vault_a")
    paths_b = DataPaths(vault=tmp_path / "vault_b")
    write_site_data(paths_a, site_a)
    write_site_data(paths_b, site_b)

    bytes_a = (paths_a.vault / "processed/site-data.json").read_bytes()
    bytes_b = (paths_b.vault / "processed/site-data.json").read_bytes()
    assert bytes_a == bytes_b


def test_written_file_never_contains_the_cfbd_key(
    small_tables: BuildTables,
    build_reference: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CFBD_API_KEY", "fake-test-key-should-never-appear")
    coverage = build_coverage(small_tables)
    site = build_site_data(small_tables, coverage, build_reference, _GENERATED_AT)
    paths = DataPaths(vault=tmp_path / "vault")
    write_site_data(paths, site)

    text = (paths.vault / "processed/site-data.json").read_text(encoding="utf-8")
    assert "fake-test-key-should-never-appear" not in text


# build/site_assembly.py is the one deliberate exception (T-04-13/SITE-19):
# its key-leak guard needs the key to grep the assembled dist/site output,
# covered by tests/test_cli_site.py's key-leak tests.
_KEY_READER_ALLOWLIST = {"site_assembly.py": "check_no_key_leak"}


def test_no_build_module_reads_the_cfbd_key() -> None:
    """WR-10: no module anywhere under build/ (current or future) may read
    the CFBD key, except the allowlisted key-leak guard."""
    offenders = [
        path.relative_to("src/booth_review/build").as_posix()
        for path in sorted(Path("src/booth_review/build").rglob("*.py"))
        if path.name not in _KEY_READER_ALLOWLIST
        and "load_cfbd_key" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_site_assembly_reads_the_key_only_inside_its_leak_guard() -> None:
    """WR-10: the allowlisted module calls `load_cfbd_key` only from its
    guard function, never anywhere else in the module."""
    tree = ast.parse(Path("src/booth_review/build/site_assembly.py").read_text(encoding="utf-8"))
    callers: set[str] = set()
    for func in ast.walk(tree):
        if not isinstance(func, ast.FunctionDef):
            continue
        for node in ast.walk(func):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "load_cfbd_key"
            ):
                callers.add(func.name)
    all_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "load_cfbd_key"
    ]
    assert callers == {_KEY_READER_ALLOWLIST["site_assembly.py"]}
    assert len(all_calls) == 1


# -- conferences / game_type / playoff_round (D-09/D-17) -------------------------------------


def test_conferences_lookup_sorted_and_is_fbs_from_classification(build_reference: Path) -> None:
    games = [
        _game_row(
            game_id=10,
            home_team="Team A",
            home_classification="fbs",
            home_conference="Zulu Conference",
            away_team="Team B",
            away_classification="fbs",
            away_conference="Alpha Conference",
        ),
        _game_row(
            game_id=11,
            date_et=date(2024, 9, 21),
            home_team="Team C",
            home_classification="fcs",
            home_conference="Echo Conference",
            away_team="Team D",
            away_classification="fbs",
            away_conference="Alpha Conference",
        ),
    ]
    telecasts = [
        _telecast_row(telecast_id="10-net-a", game_id=10),
        _telecast_row(
            telecast_id="11-net-a",
            game_id=11,
            date_et=date(2024, 9, 21),
            headline_claim_id="claim-11",
            headline_value=100.0,
            rr_telecast_ids=["cfb-example-11"],
            rr_record_urls=["https://example.com/r11"],
        ),
    ]
    tables = _build_tables(
        games_rows=games,
        telecast_rows=telecasts,
        flag_rows=[],
        people_rows=_people_rows(),
        telecast_people_rows=[],
    )
    payload = _site(tables, build_reference)
    conferences = payload["lookups"]["conferences"]
    assert [c["name"] for c in conferences] == [
        "Alpha Conference",
        "Echo Conference",
        "Zulu Conference",
    ]
    by_name = {c["name"]: c["is_fbs"] for c in conferences}
    assert by_name["Alpha Conference"] is True
    assert by_name["Zulu Conference"] is True
    assert by_name["Echo Conference"] is False


def test_same_team_different_conference_across_seasons_gets_different_index(
    build_reference: Path,
) -> None:
    games = [
        _game_row(
            game_id=20,
            home_team="Wandering State",
            home_conference="Old Conference",
        ),
        _game_row(
            game_id=21,
            date_et=date(2024, 9, 21),
            home_team="Wandering State",
            home_conference="New Conference",
        ),
    ]
    telecasts = [
        _telecast_row(telecast_id="20-net-a", game_id=20),
        _telecast_row(
            telecast_id="21-net-a",
            game_id=21,
            date_et=date(2024, 9, 21),
            headline_claim_id="claim-21",
            headline_value=100.0,
            rr_telecast_ids=["cfb-example-21"],
            rr_record_urls=["https://example.com/r21"],
        ),
    ]
    tables = _build_tables(
        games_rows=games,
        telecast_rows=telecasts,
        flag_rows=[],
        people_rows=_people_rows(),
        telecast_people_rows=[],
    )
    payload = _site(tables, build_reference)
    conference_index = {c["name"]: i for i, c in enumerate(payload["lookups"]["conferences"])}
    home_conference = payload["telecasts"]["home_conference"]
    assert home_conference[0] == conference_index["Old Conference"]
    assert home_conference[1] == conference_index["New Conference"]
    assert home_conference[0] != home_conference[1]


def test_alphabetically_first_conference_emits_index_zero_not_none(
    small_tables: BuildTables, build_reference: Path
) -> None:
    payload = _site(small_tables, build_reference)
    assert payload["lookups"]["conferences"][0]["name"] == "Fixture Conference"
    assert payload["telecasts"]["home_conference"][0] == 0
    assert payload["telecasts"]["away_conference"][0] == 0


def test_null_conference_on_fcs_side_yields_none_and_does_not_raise(build_reference: Path) -> None:
    games = [_game_row(game_id=30, away_classification="fcs", away_conference=None)]
    telecasts = [_telecast_row(telecast_id="30-net-a", game_id=30)]
    tables = _build_tables(
        games_rows=games,
        telecast_rows=telecasts,
        flag_rows=[],
        people_rows=_people_rows(),
        telecast_people_rows=[],
    )
    payload = _site(tables, build_reference)
    assert payload["telecasts"]["away_conference"][0] is None


def test_game_type_and_playoff_round_passthrough_for_a_bowl(
    small_tables: BuildTables, build_reference: Path
) -> None:
    payload = _site(small_tables, build_reference)
    assert payload["telecasts"]["game_type"][2] == "bowl"
    assert payload["telecasts"]["playoff_round"][2] is None


def test_game_type_and_playoff_round_passthrough_for_a_cfp_quarterfinal(
    build_reference: Path,
) -> None:
    games = [
        _game_row(
            game_id=40,
            season_type="postseason",
            game_type="playoff",
            playoff_round="quarterfinal",
        )
    ]
    telecasts = [_telecast_row(telecast_id="40-net-a", game_id=40)]
    tables = _build_tables(
        games_rows=games,
        telecast_rows=telecasts,
        flag_rows=[],
        people_rows=_people_rows(),
        telecast_people_rows=[],
    )
    payload = _site(tables, build_reference)
    assert payload["telecasts"]["game_type"][0] == "playoff"
    assert payload["telecasts"]["playoff_round"][0] == "quarterfinal"


def test_plotted_row_without_game_type_raises_vault_state_error(build_reference: Path) -> None:
    from booth_review.errors import VaultStateError

    games = [_game_row(game_id=50, game_type=None)]
    telecasts = [_telecast_row(telecast_id="50-net-a", game_id=50)]
    tables = _build_tables(
        games_rows=games,
        telecast_rows=telecasts,
        flag_rows=[],
        people_rows=_people_rows(),
        telecast_people_rows=[],
    )

    with pytest.raises(VaultStateError, match="without a game_type"):
        _site(tables, build_reference)


def test_fbs_home_side_with_no_conference_raises_vault_state_error(build_reference: Path) -> None:
    from booth_review.errors import VaultStateError

    games = [_game_row(game_id=60, home_conference=None)]
    telecasts = [_telecast_row(telecast_id="60-net-a", game_id=60)]
    tables = _build_tables(
        games_rows=games,
        telecast_rows=telecasts,
        flag_rows=[],
        people_rows=_people_rows(),
        telecast_people_rows=[],
    )

    with pytest.raises(VaultStateError) as excinfo:
        _site(tables, build_reference)

    message = str(excinfo.value)
    assert "with an FBS side but no conference" in message
    assert "Fixture Home" not in message


def test_fbs_away_side_with_no_conference_raises_vault_state_error(build_reference: Path) -> None:
    from booth_review.errors import VaultStateError

    games = [_game_row(game_id=61, away_conference=None)]
    telecasts = [_telecast_row(telecast_id="61-net-a", game_id=61)]
    tables = _build_tables(
        games_rows=games,
        telecast_rows=telecasts,
        flag_rows=[],
        people_rows=_people_rows(),
        telecast_people_rows=[],
    )

    with pytest.raises(VaultStateError) as excinfo:
        _site(tables, build_reference)

    message = str(excinfo.value)
    assert "with an FBS side but no conference" in message
    assert "Fixture Away" not in message


# -- CR-02: a plotted row with no usable headline value fails cleanly --------------------------


@pytest.mark.parametrize("bad_value", [None, 0.0, 0.4, -3.0])
def test_plotted_row_without_usable_headline_value_raises_vault_state_error(
    small_tables: BuildTables, build_reference: Path, bad_value: float | None
) -> None:
    from dataclasses import replace

    from booth_review.errors import VaultStateError

    first_id = small_tables.telecasts.sort("date_et")["telecast_id"][0]
    telecasts = small_tables.telecasts.with_columns(
        pl.when(pl.col("telecast_id") == first_id)
        .then(pl.lit(bad_value, dtype=pl.Float64()))
        .otherwise(pl.col("headline_value"))
        .alias("headline_value")
    )
    tables = replace(small_tables, telecasts=telecasts)

    with pytest.raises(VaultStateError, match="headline_value"):
        _site(tables, build_reference)


# -- CR-04: a crew person_id missing from the people table fails cleanly -----------------------


def test_crew_person_missing_from_people_table_raises_vault_state_error(
    small_tables: BuildTables, build_reference: Path
) -> None:
    from dataclasses import replace

    from booth_review.errors import VaultStateError

    assert small_tables.telecast_people.height > 0
    tables = replace(small_tables, people=small_tables.people.head(0))

    with pytest.raises(VaultStateError, match="person_id"):
        _site(tables, build_reference)


# -- WR-03: a contract failure never echoes a cell value -------------------------------------


def test_contract_failure_reports_location_and_type_but_never_the_cell_value(
    small_tables: BuildTables, build_reference: Path
) -> None:
    from dataclasses import replace

    from booth_review.errors import VaultStateError

    people = small_tables.people.with_columns(pl.lit("zz-sentinel-role").alias("usual_role"))
    tables = replace(small_tables, people=people)

    with pytest.raises(VaultStateError) as excinfo:
        _site(tables, build_reference)

    message = str(excinfo.value)
    assert "usual_role" in message
    assert "zz-sentinel-role" not in message
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__suppress_context__ is True


# -- WR-07: the unmapped-network coverage row is not a second "ALL" row -----------------------


def test_unmapped_network_coverage_row_points_at_the_unmapped_lookup(
    small_tables: BuildTables, build_reference: Path
) -> None:
    from dataclasses import replace

    first = small_tables.telecasts.sort("date_et").row(0, named=True)
    unmapped_row = {
        **first,
        "telecast_id": f"{first['game_id']}-unmapped",
        "network_id": None,
        "outlets": [],
        "headline_publisher": "Unmapped Publisher Example",
    }
    telecasts = pl.concat(
        [small_tables.telecasts, pl.DataFrame([unmapped_row], schema=small_tables.telecasts.schema)]
    )
    tables = replace(small_tables, telecasts=telecasts)

    payload = _site(tables, build_reference)

    network_ids = [n["id"] for n in payload["lookups"]["networks"]]
    unmapped_index = network_ids.index("unmapped")
    season = first["season"]
    season_rows = [r for r in payload["coverage"] if r["season"] == season]
    all_rows = [r for r in season_rows if r["network"] is None]
    unmapped_rows = [r for r in season_rows if r["network"] == unmapped_index]
    assert len(all_rows) == 1
    assert len(unmapped_rows) == 1
    assert unmapped_rows[0]["publisher_counts"] == {"Unmapped Publisher Example": 1}


# -- bowl-name crosswalk (04.2-04) -----------------------------------------------------------

_BOWL_HEADER = "cfbd_game_id,official_name,core_name,at_bowl\n"


def _bowl_reference(tmp_path: Path, build_reference: Path, rows: str) -> Path:
    import shutil

    reference = tmp_path / "reference"
    shutil.copytree(build_reference, reference)
    (reference / "bowls.csv").write_text(_BOWL_HEADER + rows, encoding="utf-8")
    return reference


def _postseason_tables(specs: list[tuple[int, str, str | None]], **extra: object) -> BuildTables:
    """One plotted telecast per (game_id, game_type, playoff_round) spec."""
    games = [
        _game_row(
            game_id=gid,
            season_type="postseason" if gtype != "regular" else "regular",
            game_type=gtype,
            playoff_round=rnd,
            **extra,
        )
        for gid, gtype, rnd in specs
    ]
    telecasts = [_telecast_row(telecast_id=f"{gid}-net-a", game_id=gid) for gid, _, _ in specs]
    return _build_tables(
        games_rows=games,
        telecast_rows=telecasts,
        flag_rows=[],
        people_rows=_people_rows(),
        telecast_people_rows=[],
    )


def test_named_bowl_resolves_into_lookup(tmp_path: Path, build_reference: Path) -> None:
    ref = _bowl_reference(tmp_path, build_reference, "70,Zebra Harbor Bowl,Harbor Bowl,true\n")
    payload = _site(_postseason_tables([(70, "bowl", None)]), ref)
    assert payload["lookups"]["bowls"] == [{"name": "Zebra Harbor Bowl", "core": "Harbor Bowl"}]
    assert payload["telecasts"]["bowl"] == [0]


def test_bowl_lookup_is_deduplicated_and_sorted(tmp_path: Path, build_reference: Path) -> None:
    ref = _bowl_reference(
        tmp_path,
        build_reference,
        "70,Zeta Bowl,Zeta Bowl,true\n71,Alpha Bowl,Alpha Bowl,true\n72,Zeta Bowl,Zeta Bowl,true\n",
    )
    payload = _site(
        _postseason_tables([(70, "bowl", None), (71, "bowl", None), (72, "bowl", None)]), ref
    )
    assert [b["name"] for b in payload["lookups"]["bowls"]] == ["Alpha Bowl", "Zeta Bowl"]
    assert payload["telecasts"]["bowl"] == [1, 0, 1]


def test_cfp_quarterfinal_at_bowl_and_first_round_not(
    tmp_path: Path, build_reference: Path
) -> None:
    ref = _bowl_reference(
        tmp_path,
        build_reference,
        "80,Fixture Quarter Bowl,Quarter Bowl,true\n81,,,false\n",
    )
    payload = _site(
        _postseason_tables([(80, "playoff", "quarterfinal"), (81, "playoff", "first_round")]),
        ref,
    )
    assert payload["telecasts"]["bowl"] == [0, None]


def test_unknown_name_row_is_null(tmp_path: Path, build_reference: Path) -> None:
    ref = _bowl_reference(tmp_path, build_reference, "70,,,true\n")
    payload = _site(_postseason_tables([(70, "bowl", None)]), ref)
    assert payload["lookups"]["bowls"] == []
    assert payload["telecasts"]["bowl"] == [None]


def test_regular_game_ignores_a_crosswalk_row(tmp_path: Path, build_reference: Path) -> None:
    ref = _bowl_reference(tmp_path, build_reference, "70,Zebra Harbor Bowl,Harbor Bowl,true\n")
    payload = _site(_postseason_tables([(70, "regular", None)]), ref)
    assert payload["telecasts"]["bowl"] == [None]
    assert payload["lookups"]["bowls"] == []


def test_missing_crosswalk_row_raises_count_only(tmp_path: Path, build_reference: Path) -> None:
    from booth_review.errors import BowlCrosswalkError

    ref = _bowl_reference(tmp_path, build_reference, "")
    tables = _postseason_tables([(70, "bowl", None)], home_team="SENTINEL ZEBRA HARBOR BOWL NOTE")
    with pytest.raises(BowlCrosswalkError, match="1 plotted postseason row") as info:
        _site(tables, ref)
    assert "SENTINEL" not in str(info.value)
    assert "see interim/review_bowls.csv" in str(info.value)


@pytest.mark.parametrize(
    ("spec", "row"),
    [
        ((70, "bowl", None), "70,,,false\n"),
        ((70, "playoff", "quarterfinal"), "70,,,false\n"),
        ((70, "playoff", "semifinal"), "70,,,false\n"),
        ((70, "playoff", "first_round"), "70,Zebra Bowl,Zebra Bowl,true\n"),
        ((70, "playoff", "championship"), "70,,,true\n"),
    ],
)
def test_at_bowl_disagreement_raises(
    tmp_path: Path, build_reference: Path, spec: tuple[int, str, str | None], row: str
) -> None:
    from booth_review.errors import VaultStateError

    ref = _bowl_reference(tmp_path, build_reference, row)
    with pytest.raises(VaultStateError, match=r"1 row\(s\) disagree with the game's type"):
        _site(_postseason_tables([spec]), ref)


def test_notes_sentinel_never_ships(tmp_path: Path, build_reference: Path) -> None:
    ref = _bowl_reference(tmp_path, build_reference, "70,Zebra Harbor Bowl,Harbor Bowl,true\n")
    tables = _postseason_tables([(70, "bowl", None)], notes="SENTINEL ZEBRA HARBOR BOWL NOTE")
    site = build_site_data(tables, build_coverage(tables), ref, _GENERATED_AT)
    paths = DataPaths(vault=tmp_path / "vault")
    write_site_data(paths, site)
    text = (paths.vault / "processed/site-data.json").read_text(encoding="utf-8")
    assert "Zebra Harbor Bowl" in text
    assert "SENTINEL" not in text
