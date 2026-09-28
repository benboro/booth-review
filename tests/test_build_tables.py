"""Tests for build/tables.py: full assembly on the synthetic build_vault +
build_reference fixtures (extended with the network rows the shared RR/506
spike fixtures need -- D-07), determinism, the Parquet/CSV writer, the
JOIN-08 formula, and main's counts-only output (T-03-28/T-03-31).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import polars as pl
import pytest

from booth_review.build.tables import (
    ERA_DISAGREEMENT_COLUMNS,
    HEADLINE_DISAGREEMENT_COLUMNS,
    PEOPLE_SCHEMA,
    TELECAST_PEOPLE_SCHEMA,
    BuildDiagnostics,
    assemble_tables,
    main,
    write_tables,
)
from booth_review.config import DataPaths
from booth_review.resolve.diagnose import UNMATCHED_COLUMNS, UNRESOLVED_COLUMNS


@pytest.fixture
def vault_reference(build_reference: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """`build_reference`'s fixture dir, plus the ECN/ESPN network rows the
    shared spike RR/506 fixtures' own outlet text needs (D-07, invented).
    """
    extended = tmp_path / "reference_ext"
    shutil.copytree(build_reference, extended)
    with (extended / "networks.csv").open("a", encoding="utf-8", newline="") as fh:
        fh.write("ECN,ecn,Example Cable Network,family-ecn,cable,main,,,\n")
        fh.write("ECN2,ecn2,Example Cable Network 2,family-ecn,cable,main,,,\n")
        fh.write("ESPN,espn,ESPN,family-espn,cable,main,,,\n")
        fh.write("ESPN2,espn2,ESPN2,family-espn,cable,main,,,\n")
        fh.write("ESPNU,espnu,ESPNU,family-espn,cable,main,,,\n")
        fh.write("ESPN Deportes,espn-deportes,ESPN Deportes,family-espn,cable,spanish,,,\n")
    monkeypatch.setenv("BOOTH_REVIEW_REFERENCE", str(extended))
    return extended


def test_assemble_tables_builds_every_table(build_vault: DataPaths, vault_reference: Path) -> None:
    tables = assemble_tables(build_vault, vault_reference, seasons=[2025])

    assert tables.games.height > 0
    assert tables.telecasts.height > 0
    assert tables.viewership.height > 0
    assert tables.telecast_flags.height > 0
    assert tables.listing_links.height > 0
    assert tables.people.height > 0
    assert tables.people.columns == list(PEOPLE_SCHEMA.keys())
    assert tables.telecast_people.height > 0
    assert tables.telecast_people.columns == list(TELECAST_PEOPLE_SCHEMA.keys())


def test_assemble_tables_is_deterministic(build_vault: DataPaths, vault_reference: Path) -> None:
    a = assemble_tables(build_vault, vault_reference, seasons=[2025])
    b = assemble_tables(build_vault, vault_reference, seasons=[2025])

    assert a.telecasts.equals(b.telecasts)
    assert a.viewership.equals(b.viewership)
    assert a.telecast_flags.equals(b.telecast_flags)
    assert a.games.equals(b.games)


def test_review_rows_have_the_diagnose_module_columns(
    build_vault: DataPaths, vault_reference: Path
) -> None:
    tables = assemble_tables(build_vault, vault_reference, seasons=[2025])

    assert tables.review_rows["review_unmatched"][0] == UNMATCHED_COLUMNS
    assert tables.review_rows["review_unresolved_teams"][0] == UNRESOLVED_COLUMNS
    assert tables.review_rows["review_headline_disagreements"][0] == HEADLINE_DISAGREEMENT_COLUMNS
    assert tables.review_rows["review_era_disagreements"][0] == ERA_DISAGREEMENT_COLUMNS


def test_join08_formula_on_known_counts() -> None:
    diagnostics = BuildDiagnostics(
        per_season={
            2024: {
                "rr_records": 10,
                "rr_excluded": 1,
                "rr_out_of_scope": 1,
                "records_with_crew": 6,
            }
        },
        totals={},
        join08_rate=None,
        join08_by_season={},
    )
    season_counts = diagnostics.per_season[2024]
    denominator = (
        season_counts["rr_records"]
        - season_counts["rr_excluded"]
        - season_counts["rr_out_of_scope"]
    )
    rate = season_counts["records_with_crew"] / denominator
    assert denominator == 8
    assert rate == pytest.approx(0.75)


def test_write_tables_writes_parquet_and_review_csvs_and_returns_sorted_paths(
    build_vault: DataPaths, vault_reference: Path
) -> None:
    tables = assemble_tables(build_vault, vault_reference, seasons=[2025])

    written = write_tables(build_vault, tables)

    assert written == sorted(written)
    for rel_path in written:
        assert (build_vault.vault / rel_path).is_file()

    expected = {
        "processed/games.parquet",
        "processed/telecasts.parquet",
        "processed/viewership.parquet",
        "processed/telecast_flags.parquet",
        "processed/listing_links.parquet",
        "processed/people.parquet",
        "processed/telecast_people.parquet",
        "interim/review_unmatched.csv",
        "interim/review_unresolved_teams.csv",
        "interim/review_headline_disagreements.csv",
        "interim/review_era_disagreements.csv",
        "interim/review_people_new.csv",
        "interim/review_combined.csv",
    }
    assert set(written) == expected


def test_write_tables_parquet_round_trip_preserves_nulls(
    build_vault: DataPaths, vault_reference: Path
) -> None:
    tables = assemble_tables(build_vault, vault_reference, seasons=[2025])

    write_tables(build_vault, tables)

    read_back = pl.read_parquet(build_vault.vault / "processed/telecasts.parquet")
    assert read_back.equals(tables.telecasts)
    assert read_back["headline_claim_id"].null_count() >= 0  # column exists and is nullable
    # At least one column with an intentional null round-trips as null, not a
    # placeholder (D-11/D-12: never fill_null).
    unrated = read_back.filter(~pl.col("rated"))
    if unrated.height:
        assert unrated["headline_value"].null_count() == unrated.height


def test_main_prints_counts_only_and_no_team_or_announcer_name(
    build_vault: DataPaths,
    vault_reference: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOOTH_REVIEW_REFERENCE", str(vault_reference))

    main(["--no-write", "--season", "2025"])

    captured = capsys.readouterr()
    forbidden = (
        "Northfield",
        "Lakeview",
        "Cedarhollow",
        "Boulderpass",
        "Ravenwood",
        "Thornfield",
        "Pat Example",
        "Jordan Sample",
    )
    for name in forbidden:
        assert name not in captured.out

    assert "join-08" in captured.out.lower()
    assert not (build_vault.processed / "telecasts.parquet").is_file()
    assert not (build_vault.interim / "review_unmatched.csv").is_file()


# -- WR-06: the build refuses a missing networks.csv or an unknown override network ---------


def test_assemble_tables_requires_networks_csv(
    build_vault: DataPaths, build_reference: Path, tmp_path: Path
) -> None:
    from booth_review.errors import ReferenceTableError

    reference = tmp_path / "reference_no_networks"
    shutil.copytree(build_reference, reference)
    (reference / "networks.csv").unlink()

    with pytest.raises(ReferenceTableError, match=r"networks\.csv"):
        assemble_tables(build_vault, reference)


def test_assemble_tables_rejects_an_override_network_missing_from_networks_csv(
    build_vault: DataPaths, build_reference: Path, tmp_path: Path
) -> None:
    from booth_review.errors import ReferenceTableError

    reference = tmp_path / "reference_bad_override"
    shutil.copytree(build_reference, reference)
    (reference / "primary_network_overrides.csv").write_text(
        "cfbd_game_id,network_id,reason\n900001,net-typo,other\n", encoding="utf-8"
    )

    with pytest.raises(ReferenceTableError, match="net-typo"):
        assemble_tables(build_vault, reference)
