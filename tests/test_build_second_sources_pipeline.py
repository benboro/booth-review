"""End-to-end second-source wiring (04.19-07): a synthetic vault with raw/smw
files runs through run_build, the unrated telecast flips to rated with an SMW
headline, the review CSVs and counts appear, and a vault with no raw/smw files
changes nothing. Teams and figures are invented.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from smw_helpers import PAGE
from test_build_crew_overrides_pipeline import _vault

from booth_review.build.coverage import build_coverage, write_coverage
from booth_review.build.pipeline import BuildOutcome, run_build
from booth_review.build.regression import build_metrics
from booth_review.build.second_sources import (
    REVIEW_AGREEMENT,
    REVIEW_CONFLICTS,
    REVIEW_GATE,
    REVIEW_NETWORK,
    REVIEW_UNMATCHED,
    SECOND_SOURCE_REVIEW_NAMES,
)
from booth_review.build.tables import assemble_tables, write_tables
from booth_review.config import DataPaths
from booth_review.sources.smw.chart_order import parse_chart_order, write_chart_order_csv
from booth_review.sources.smw.rows import ROWS_COLUMNS

SEASON = 2025
UNRATED = "500008-ecn"  # Ironpeak (home) v Northfield, 8/30, ECN: no RR record
RATED = "500001-ecn"  # Northfield (home) v Lakeview, 10/11, ECN: RR headline 2.05M
CHART = "week5cfb.png"


def _write_smw_season(paths: DataPaths, rows: list[list[str]]) -> None:
    folder = paths.raw / "smw" / str(SEASON)
    (folder / "transcription").mkdir(parents=True)
    page = PAGE.replace("2022 college", f"{SEASON} college").replace(
        "/2022-season/", f"/{SEASON}-season/"
    )
    (folder / "season-page.html").write_text(page, encoding="utf-8")
    order = parse_chart_order(page, {CHART})
    write_chart_order_csv(folder / "chart_order.csv", order)
    with (folder / "transcription" / "rows.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(ROWS_COLUMNS)
        writer.writerows(rows)


def _row(n: int, day: str, away: str, home: str, viewers: str) -> list[str]:
    return [CHART, str(n), "Sat", day, "", away, home, "ECN", "1.0", viewers, "", ""]


def _telecasts(paths: DataPaths) -> pl.DataFrame:
    return pl.read_parquet(paths.vault / "processed" / "telecasts.parquet")


def _one(frame: pl.DataFrame, telecast_id: str) -> dict[str, Any]:
    rows = frame.filter(pl.col("telecast_id") == telecast_id).to_dicts()
    assert len(rows) == 1
    return rows[0]


def _csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        return list(reader.fieldnames or []), rows


def _coverage_all(paths: DataPaths) -> dict[str, str]:
    with (paths.vault / "processed" / "coverage.csv").open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if row["season"] == str(SEASON) and row["network_id"] == "ALL":
                return row
    raise AssertionError("no ALL coverage row")


def _build(git_vault: DataPaths, reference: Path) -> BuildOutcome:
    return run_build(git_vault, reference, commit=False, accept_baseline=False)


def test_no_smw_files_writes_empty_review_csvs_and_flips_nothing(
    git_vault: DataPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reference = _vault(git_vault, tmp_path, monkeypatch)
    outcome = _build(git_vault, reference)

    for name in SECOND_SOURCE_REVIEW_NAMES:
        header, rows = _csv_rows(git_vault.vault / "interim" / f"{name}.csv")
        assert header and rows == []
    telecasts = _telecasts(git_vault)
    assert not _one(telecasts, UNRATED)["rated"]
    assert outcome.counts["rated_second_source"] == 0
    assert set(telecasts.filter(pl.col("rated"))["headline_source"].to_list()) == {"rr"}
    viewership = pl.read_parquet(git_vault.vault / "processed" / "viewership.parquet")
    assert set(viewership["source"].to_list()) == {"rr"}


def test_smw_figures_flip_an_unrated_telecast_and_reach_every_consumer(
    git_vault: DataPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Tables, coverage and metrics are checked directly; run_build at the end covers site data.
    reference = _vault(git_vault, tmp_path, monkeypatch)
    before = _build(git_vault, reference)
    rated_before = _telecasts(git_vault).filter(pl.col("rated") & (pl.col("feed_type") == "main"))

    _write_smw_season(
        git_vault,
        [
            _row(1, "8/30", "Northfield", "Ironpeak", "1.20M"),
            _row(2, "10/11", "Lakeview", "Northfield", "2.07M"),
        ],
    )
    tables = assemble_tables(git_vault, reference)
    write_tables(git_vault, tables)
    coverage = build_coverage(tables)
    write_coverage(git_vault, coverage)
    metrics = {m.season: m for m in build_metrics(tables, git_vault)}
    totals = tables.diagnostics.totals

    telecasts = _telecasts(git_vault)
    flipped = _one(telecasts, UNRATED)
    assert flipped["rated"] and flipped["plotted"]
    assert flipped["headline_source"] == "smw"
    assert flipped["headline_value"] == 1_200_000.0
    assert flipped["headline_publisher"] == "Sports Media Watch"
    assert flipped["measurement_type"] == "unknown"
    assert flipped["rr_current_check"] is None
    assert flipped["headline_source_url"].startswith("https://www.sportsmediawatch.com/")

    # An RR-rated telecast keeps its RR headline.
    kept = _one(telecasts, RATED)
    assert kept["headline_source"] == "rr"
    assert kept["headline_value"] == 2_050_000.0

    # Viewership: SMW rows exist, null RR identifiers, and one headline per telecast.
    viewership = pl.read_parquet(git_vault.vault / "processed" / "viewership.parquet")
    smw = viewership.filter(pl.col("source") == "smw")
    assert smw.height == 2
    assert smw["rr_telecast_id"].null_count() == 2
    assert smw["record_url"].null_count() == 2
    assert smw["is_rr_current"].null_count() == 2
    assert smw.filter(pl.col("telecast_id") == UNRATED)["is_headline"].to_list() == [True]
    assert smw.filter(pl.col("telecast_id") == RATED)["is_headline"].to_list() == [False]
    assert viewership["source"].null_count() == 0
    assert not viewership.filter(pl.col("source") == "rr")["record_url"].has_nulls()

    # D-20: counted like an RR-rated telecast, in coverage and in the AUDIT-03 metrics.
    rated_after = telecasts.filter(pl.col("rated") & (pl.col("feed_type") == "main"))
    assert rated_after.height == rated_before.height + 1
    assert totals["rated_telecasts"] == before.counts["rated_telecasts"] + 1
    assert totals["rated_second_source"] == 1
    assert metrics[SEASON].rated_telecasts == totals["rated_telecasts"]
    cov = _coverage_all(git_vault)
    assert int(cov["rated_telecasts"]) == rated_after.height
    assert int(cov["headline_second_source"]) == 1

    # Gate and review files.
    assert len(tables.second_source_gates) == 1
    gate = tables.second_source_gates[0]
    assert (gate.source, gate.season, gate.shared, gate.within_3pct) == ("smw", SEASON, 1, 1)
    assert gate.status == "passed"
    assert gate.loaded == 2
    for name in SECOND_SOURCE_REVIEW_NAMES:
        assert (git_vault.vault / "interim" / f"{name}.csv").is_file()
    _, agreement = _csv_rows(git_vault.vault / "interim" / f"{REVIEW_AGREEMENT}.csv")
    assert [r["status"] for r in agreement] == ["ok"]
    _, gate_rows = _csv_rows(git_vault.vault / "interim" / f"{REVIEW_GATE}.csv")
    assert [r["status"] for r in gate_rows] == ["passed"]
    for name in (REVIEW_UNMATCHED, REVIEW_NETWORK, REVIEW_CONFLICTS):
        assert _csv_rows(git_vault.vault / "interim" / f"{name}.csv")[1] == []

    # Contract 2.4.0: the full build validates and ships the SMW figure with its source label.
    _build(git_vault, reference)
    site = json.loads((git_vault.vault / "processed" / "site-data.json").read_text())
    assert site["schema_version"] == "2.7.0"
    columns = site["telecasts"]
    assert Counter(columns["figure_source"]) == {"rr": rated_before.height, "smw": 1}
    i = columns["figure_source"].index("smw")
    assert columns["rr_urls"][i] == []
    assert columns["source_url"][i].startswith("https://www.sportsmediawatch.com/")
    assert site["lookups"]["publishers"][columns["publisher"][i]] == "Sports Media Watch"
