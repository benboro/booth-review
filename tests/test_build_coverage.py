"""Tests for build/coverage.py: the season x network coverage table and
publisher mix (AUDIT-01), built on small in-memory BuildTables (Plan 08
schemas) plus one assemble_tables run on the shared build_vault/build_reference
fixtures.
"""

from __future__ import annotations

import dataclasses
import shutil
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

from booth_review.build.coverage import (
    COVERAGE_COLUMNS,
    PUBLISHER_COLUMNS,
    CoverageReport,
    build_coverage,
    write_coverage,
)
from booth_review.build.games import GAMES_SCHEMA
from booth_review.build.tables import (
    PEOPLE_SCHEMA,
    TELECAST_PEOPLE_SCHEMA,
    BuildDiagnostics,
    BuildTables,
    assemble_tables,
)
from booth_review.build.telecasts import LISTING_LINKS_SCHEMA, TELECASTS_SCHEMA
from booth_review.build.viewership import TELECAST_FLAGS_SCHEMA, VIEWERSHIP_SCHEMA
from booth_review.config import DataPaths


def _game_row(**overrides: object) -> dict[str, object]:
    defaults: dict[str, object] = {
        "game_id": 1,
        "season": 2024,
        "week": 1,
        "season_type": "regular",
        "start_utc": datetime(2024, 9, 7, 0, 0, tzinfo=UTC),
        "date_et": date(2024, 9, 6),
        "kickoff_et": "2024-09-06T20:00:00-04:00",
        "neutral_site": False,
        "conference_game": False,
        "home_id": 100,
        "home_team": "Example State",
        "home_classification": "fbs",
        "home_conference": "Example Conference",
        "home_points": 20,
        "away_id": 200,
        "away_team": "Sample Tech",
        "away_classification": "fbs",
        "away_conference": "Sample Conference",
        "away_points": 10,
        "excitement": 5.0,
        "closing_spread": -3.0,
        "spread_provider": "consensus",
        "pregame_x": -3.0,
        "home_win_prob": 0.65,
        "home_rank": 5,
        "away_rank": None,
        "rank_poll": "AP Top 25",
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
        "date_et": date(2024, 9, 6),
        "network_id": "net-a",
        "feed_type": "main",
        "outlets": ["net-a"],
        "rated": True,
        "rr_telecast_ids": [],
        "rr_record_urls": [],
        "duplicate_merges": 0,
        "rr_match_confidence": "exact",
        "s506_match_confidence": "exact",
        "match_confidence": "exact",
        "s506_pointer": "1:0",
        "s506_week": "1",
        "s506_url": "https://506sports.com/ncaaf.php?yr=2024&wk=1",
        "kickoff_et": "2024-09-06T20:00:00",
        "crew_matched": True,
        "crew_network_mismatch": False,
        "combined_feeds": None,
        "plotted": True,
        "headline_claim_id": "claim-1",
        "headline_value": 1_000_000.0,
        "headline_publisher": "Pub1",
        "headline_source_url": "https://example.com/story",
        "measurement_type": "nielsen",
        "era_id": "era-a",
        "rr_current_check": "agree",
        "model_break": False,
    }
    defaults.update(overrides)
    return defaults


def _telecasts_frame(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=TELECASTS_SCHEMA)


def _empty(schema: dict[str, pl.DataType]) -> pl.DataFrame:
    return pl.DataFrame(schema=schema)


def _build_tables(
    games_rows: list[dict[str, object]],
    telecast_rows: list[dict[str, object]],
    *,
    diagnostics: BuildDiagnostics,
    era_disagreement_rows: list[dict[str, object]] | None = None,
) -> BuildTables:
    era_columns = ("telecast_id", "rr_telecast_id", "claim_id", "era_id", "rr_era_id")
    review_rows: dict[str, tuple[tuple[str, ...], list[dict[str, object]]]] = {
        "review_era_disagreements": (era_columns, era_disagreement_rows or []),
    }
    return BuildTables(
        games=_games_frame(games_rows),
        telecasts=_telecasts_frame(telecast_rows),
        viewership=_empty(VIEWERSHIP_SCHEMA),
        telecast_flags=_empty(TELECAST_FLAGS_SCHEMA),
        listing_links=_empty(LISTING_LINKS_SCHEMA),
        people=_empty(PEOPLE_SCHEMA),
        telecast_people=_empty(TELECAST_PEOPLE_SCHEMA),
        diagnostics=diagnostics,
        review_rows=review_rows,
    )


def _diagnostics(
    per_season: dict[int, dict[str, int]], join08_by_season: dict[int, float | None]
) -> BuildDiagnostics:
    return BuildDiagnostics(
        per_season=per_season, totals={}, join08_rate=None, join08_by_season=join08_by_season
    )


@pytest.fixture
def small_tables() -> BuildTables:
    games = [
        _game_row(
            game_id=1,
            excitement=5.0,
            pregame_x=-3.0,
            home_points=20,
            away_points=10,
            home_rank=5,
            away_rank=None,
        ),
        _game_row(
            game_id=2,
            excitement=None,
            pregame_x=None,
            closing_spread=None,
            home_points=None,
            away_points=None,
            home_rank=None,
            away_rank=None,
        ),
        _game_row(
            game_id=3,
            excitement=7.5,
            pregame_x=-1.0,
            closing_spread=-1.0,
            home_points=30,
            away_points=27,
            home_rank=None,
            away_rank=None,
        ),
        # An unrated main telecast's game: must never enter the eligible population.
        _game_row(game_id=4, excitement=9.0),
    ]
    telecasts = [
        _telecast_row(
            telecast_id="1-net-a",
            game_id=1,
            network_id="net-a",
            crew_matched=True,
            headline_claim_id="claim-1",
            headline_publisher="Pub1",
            headline_source_url="https://example.com/a",
            kickoff_et="2024-09-06T20:00:00",
            duplicate_merges=1,
            combined_feeds=None,
            rr_current_check="agree",
        ),
        _telecast_row(
            telecast_id="2-net-a",
            game_id=2,
            network_id="net-a",
            crew_matched=False,
            headline_claim_id=None,
            headline_value=None,
            headline_publisher=None,
            headline_source_url=None,
            kickoff_et=None,
            duplicate_merges=0,
            combined_feeds=2,
            rr_current_check=None,
        ),
        _telecast_row(
            telecast_id="3-net-b",
            game_id=3,
            network_id="net-b",
            crew_matched=True,
            headline_claim_id="claim-3",
            headline_publisher=None,
            headline_source_url=None,
            duplicate_merges=0,
            combined_feeds=None,
            rr_current_check="disagree",
        ),
        _telecast_row(
            telecast_id="4-net-a",
            game_id=4,
            network_id="net-a",
            rated=False,
        ),
    ]
    diagnostics = _diagnostics(
        per_season={
            2024: {
                "rr_records": 10,
                "rr_excluded": 1,
                "rr_out_of_scope": 1,
                "rr_unmatched": 0,
                "records_with_crew": 6,
            }
        },
        join08_by_season={2024: 0.75},
    )
    era_rows = [
        {
            "telecast_id": "1-net-a",
            "rr_telecast_id": "cfb-example-2024",
            "claim_id": "claim-1",
            "era_id": "era-a",
            "rr_era_id": "rr-era-b",
        }
    ]
    return _build_tables(games, telecasts, diagnostics=diagnostics, era_disagreement_rows=era_rows)


def _row(report: CoverageReport, season: int, network_id: str) -> dict[str, object]:
    for row in report.rows:
        if row["season"] == season and row["network_id"] == network_id:
            return row
    raise AssertionError(f"no row for season={season} network_id={network_id}")


def test_only_rated_main_telecasts_are_counted(small_tables: BuildTables) -> None:
    report = build_coverage(small_tables)
    net_a = _row(report, 2024, "net-a")
    # 2 rated-main telecasts on net-a (game 1, game 2); the unrated game-4 row never counts.
    assert net_a["rated_telecasts"] == 2


def test_null_excitement_counts_as_missing_not_zero(small_tables: BuildTables) -> None:
    report = build_coverage(small_tables)
    net_a = _row(report, 2024, "net-a")
    # Game 1 has excitement=5.0, game 2 has excitement=None: only 1 should count present.
    assert net_a["excitement_present"] == 1
    assert net_a["spread_present"] == 1
    assert "pregame_present" not in net_a
    assert net_a["points_present"] == 1


def test_ranks_present_and_unranked_games(small_tables: BuildTables) -> None:
    report = build_coverage(small_tables)
    net_a = _row(report, 2024, "net-a")
    # Game 1 has a home_rank (ranks_present); game 2 has neither rank (unranked).
    assert net_a["ranks_present"] == 1
    assert net_a["unranked_games"] == 1


def test_crew_and_headline_and_publisher_completeness(small_tables: BuildTables) -> None:
    report = build_coverage(small_tables)
    net_a = _row(report, 2024, "net-a")
    assert net_a["matched_crew"] == 1
    assert net_a["crew_rate"] == pytest.approx(0.5)
    assert net_a["headline_present"] == 1
    assert net_a["publisher_present"] == 1
    assert net_a["source_url_present"] == 1
    assert net_a["kickoff_present"] == 1

    net_b = _row(report, 2024, "net-b")
    assert net_b["publisher_present"] == 0  # headline exists, publisher is null
    assert net_b["headline_disagreements"] == 1


def test_duplicate_merges_and_combined_figures(small_tables: BuildTables) -> None:
    report = build_coverage(small_tables)
    net_a = _row(report, 2024, "net-a")
    assert net_a["duplicate_merges"] == 1
    assert net_a["combined_figures"] == 1


def test_era_disagreements_join_back_to_network(small_tables: BuildTables) -> None:
    report = build_coverage(small_tables)
    net_a = _row(report, 2024, "net-a")
    net_b = _row(report, 2024, "net-b")
    assert net_a["era_disagreements"] == 1
    assert net_b["era_disagreements"] == 0


def test_all_row_carries_diagnostics_counts_and_join08_match_rate(
    small_tables: BuildTables,
) -> None:
    report = build_coverage(small_tables)
    all_row = _row(report, 2024, "ALL")
    assert all_row["rr_records"] == 10
    assert all_row["rr_excluded"] == 1
    assert all_row["rr_out_of_scope"] == 1
    assert all_row["rr_unmatched"] == 0
    assert all_row["records_with_crew"] == 6
    assert all_row["match_rate"] == small_tables.diagnostics.join08_by_season[2024]
    assert all_row["rated_telecasts"] == 3
    assert all_row["matched_crew"] == 2


def test_per_network_rows_leave_diagnostics_only_fields_null(small_tables: BuildTables) -> None:
    report = build_coverage(small_tables)
    net_a = _row(report, 2024, "net-a")
    assert net_a["rr_records"] is None
    assert net_a["rr_excluded"] is None
    assert net_a["rr_out_of_scope"] is None
    assert net_a["rr_unmatched"] is None
    assert net_a["records_with_crew"] is None
    assert net_a["match_rate"] is None


def test_publisher_rows_use_none_marker_and_count_headlines(small_tables: BuildTables) -> None:
    report = build_coverage(small_tables)
    by_key = {
        (r["season"], r["network_id"], r["publisher"]): r["headline_count"]
        for r in report.publisher_rows
    }
    assert by_key[(2024, "net-a", "Pub1")] == 1
    assert by_key[(2024, "net-b", "(none)")] == 1
    # net-a's second telecast has no headline at all, so it contributes no publisher row.
    assert (2024, "net-a", None) not in by_key


def test_rows_sorted_by_season_then_network_with_all_last(small_tables: BuildTables) -> None:
    report = build_coverage(small_tables)
    season_2024 = [row for row in report.rows if row["season"] == 2024]
    assert [row["network_id"] for row in season_2024] == ["net-a", "net-b", "ALL"]


def test_build_coverage_is_deterministic(small_tables: BuildTables) -> None:
    a = build_coverage(small_tables)
    b = build_coverage(small_tables)
    assert a.rows == b.rows
    assert a.publisher_rows == b.publisher_rows


def test_report_columns_match_declared_constants(small_tables: BuildTables) -> None:
    report = build_coverage(small_tables)
    for row in report.rows:
        assert set(row) == set(COVERAGE_COLUMNS)
    for row in report.publisher_rows:
        assert set(row) == set(PUBLISHER_COLUMNS)


def test_totals_rolls_up_every_all_row() -> None:
    tables_2024 = _build_tables(
        [_game_row(game_id=1)],
        [_telecast_row(telecast_id="1-net-a", game_id=1, network_id="net-a")],
        diagnostics=_diagnostics(
            per_season={
                2024: {
                    "rr_records": 5,
                    "rr_excluded": 0,
                    "rr_out_of_scope": 0,
                    "rr_unmatched": 0,
                    "records_with_crew": 4,
                }
            },
            join08_by_season={2024: 0.8},
        ),
    )
    report = build_coverage(tables_2024)
    totals = report.totals()
    assert totals["rated_telecasts"] == 1
    assert totals["matched_crew"] == 1
    assert totals["rr_records"] == 5
    assert totals["match_rate"] == pytest.approx(4 / 5)


def test_write_coverage_writes_both_csvs_and_returns_paths(
    small_tables: BuildTables, tmp_path: Path
) -> None:
    paths = DataPaths(vault=tmp_path / "vault")
    report = build_coverage(small_tables)

    written = write_coverage(paths, report)

    assert written == ["processed/coverage.csv", "processed/coverage_publishers.csv"]
    for rel_path in written:
        assert (paths.vault / rel_path).is_file()

    coverage_text = (paths.vault / "processed/coverage.csv").read_text(encoding="utf-8")
    assert coverage_text.splitlines()[0] == ",".join(COVERAGE_COLUMNS)
    publishers_path = paths.vault / "processed/coverage_publishers.csv"
    publishers_text = publishers_path.read_text(encoding="utf-8")
    assert publishers_text.splitlines()[0] == ",".join(PUBLISHER_COLUMNS)


# -- real-vault-shaped fixture run ------------------------------------------------------------


@pytest.fixture
def vault_reference(build_reference: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """`build_reference`'s fixture dir, plus the ECN/ESPN network rows the
    shared spike RR/506 fixtures' own outlet text needs (D-07, invented) --
    same extension test_build_tables.py's own `vault_reference` fixture uses.
    """
    extended = tmp_path / "reference_ext"
    shutil.copytree(build_reference, extended)
    with (extended / "network_rarity.csv").open("a", encoding="utf-8", newline="") as rarity_fh:
        rarity_fh.write(
            "ecn,false\necn2,false\nespn,false\nespn2,false\nespnu,false\nespn-deportes,false\n"
        )
    with (extended / "networks.csv").open("a", encoding="utf-8", newline="") as fh:
        fh.write("ECN,ecn,Example Cable Network,family-ecn,cable,main,,,\n")
        fh.write("ECN2,ecn2,Example Cable Network 2,family-ecn,cable,main,,,\n")
        fh.write("ESPN,espn,ESPN,family-espn,cable,main,,,\n")
        fh.write("ESPN2,espn2,ESPN2,family-espn,cable,main,,,\n")
        fh.write("ESPNU,espnu,ESPNU,family-espn,cable,main,,,\n")
        fh.write("ESPN Deportes,espn-deportes,ESPN Deportes,family-espn,cable,spanish,,,\n")
    monkeypatch.setenv("BOOTH_REVIEW_REFERENCE", str(extended))
    return extended


def test_build_coverage_on_real_vault_shaped_fixture(
    build_vault: DataPaths, vault_reference: Path
) -> None:
    tables = assemble_tables(build_vault, vault_reference, seasons=[2025])

    report = build_coverage(tables)

    assert report.rows
    assert any(row["network_id"] == "ALL" for row in report.rows)
    written = write_coverage(build_vault, report)
    for rel_path in written:
        assert (build_vault.vault / rel_path).is_file()


def _patched_tables(patched: list[object]) -> BuildTables:
    games = [_game_row(game_id=i + 1) for i in range(len(patched))]
    telecasts = [
        _telecast_row(
            telecast_id=f"{i + 1}-net-a",
            game_id=i + 1,
            crew_matched=True,
            crew_patched=value,
        )
        for i, value in enumerate(patched)
    ]
    return _build_tables(
        games,
        telecasts,
        diagnostics=_diagnostics({2024: {}}, {2024: None}),
    )


def test_crew_patched_counts_separately_but_stays_in_matched_crew() -> None:
    report = build_coverage(_patched_tables([True, False, None]))
    for network in ("net-a", "ALL"):
        row = _row(report, 2024, network)
        assert row["matched_crew"] == 3
        assert row["crew_patched"] == 1
        assert row["crew_rate"] == 1.0


def test_crew_patched_column_follows_matched_crew() -> None:
    index = COVERAGE_COLUMNS.index("matched_crew")
    assert COVERAGE_COLUMNS[index + 1] == "crew_patched"


def test_spread_present_counts_the_closing_spread_not_pregame_x(
    small_tables: BuildTables,
) -> None:
    games = small_tables.games.with_columns(
        pl.when(pl.col("game_id") == 1)
        .then(-1.0)
        .otherwise(None)
        .cast(pl.Float64)
        .alias("closing_spread"),
        pl.lit(None, dtype=pl.Float64).alias("pregame_x"),
    )
    tables = dataclasses.replace(small_tables, games=games)
    net_a = _row(build_coverage(tables), 2024, "net-a")
    assert net_a["spread_present"] == 1
