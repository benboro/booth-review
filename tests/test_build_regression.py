"""Tests for build/regression.py: the AUDIT-03 regression guard against an
accepted build baseline and the Phase 2 completeness counts.
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest

from booth_review.build.games import GAMES_SCHEMA
from booth_review.build.regression import (
    METRIC_COLUMNS,
    RegressionResult,
    SeasonMetrics,
    accept_baseline,
    build_metrics,
    check_regression,
    load_baseline,
    load_completeness_counts,
    write_metrics,
    write_regression_report,
)
from booth_review.build.tables import (
    PEOPLE_SCHEMA,
    TELECAST_PEOPLE_SCHEMA,
    BuildDiagnostics,
    BuildTables,
)
from booth_review.build.telecasts import LISTING_LINKS_SCHEMA, TELECASTS_SCHEMA
from booth_review.build.viewership import TELECAST_FLAGS_SCHEMA, VIEWERSHIP_SCHEMA
from booth_review.config import DataPaths
from booth_review.errors import VaultStateError


def _empty(schema: dict[str, pl.DataType]) -> pl.DataFrame:
    return pl.DataFrame(schema=schema)


def _tables(
    per_season: dict[int, dict[str, int]], join08_by_season: dict[int, float | None]
) -> BuildTables:
    diagnostics = BuildDiagnostics(
        per_season=per_season, totals={}, join08_rate=None, join08_by_season=join08_by_season
    )
    return BuildTables(
        games=_empty(GAMES_SCHEMA),
        telecasts=_empty(TELECASTS_SCHEMA),
        viewership=_empty(VIEWERSHIP_SCHEMA),
        telecast_flags=_empty(TELECAST_FLAGS_SCHEMA),
        listing_links=_empty(LISTING_LINKS_SCHEMA),
        people=_empty(PEOPLE_SCHEMA),
        telecast_people=_empty(TELECAST_PEOPLE_SCHEMA),
        diagnostics=diagnostics,
        review_rows={},
    )


def _metrics(season: int, **overrides: object) -> SeasonMetrics:
    defaults: dict[str, object] = {
        "season": season,
        "rr_records": 100,
        "rated_telecasts": 80,
        "records_with_crew": 75,
        "match_rate": 0.9375,
        "sports506_pages": 18,
        "rr_records_cached": 100,
        "cfbd_files": 6,
    }
    defaults.update(overrides)
    return SeasonMetrics(**defaults)  # type: ignore[arg-type]


def _seed_vault(
    paths: DataPaths, season: int, *, pages: int, rr_files: int, cfbd_endpoints: int
) -> None:
    s506_dir = paths.raw / "sports506" / str(season)
    s506_dir.mkdir(parents=True, exist_ok=True)
    for i in range(pages):
        (s506_dir / f"wk-{i:02d}.html").write_text("<html></html>", encoding="utf-8")

    rr_dir = paths.raw / "ratingsref" / "telecast" / str(season)
    rr_dir.mkdir(parents=True, exist_ok=True)
    for i in range(rr_files):
        (rr_dir / f"cfb-example-{i}.json").write_text("{}", encoding="utf-8")

    from booth_review.audit.completeness import CFBD_SEASON_ENDPOINTS

    for endpoint in CFBD_SEASON_ENDPOINTS[:cfbd_endpoints]:
        endpoint_dir = paths.raw / "cfbd" / endpoint
        endpoint_dir.mkdir(parents=True, exist_ok=True)
        (endpoint_dir / f"{season}.json").write_text("[]", encoding="utf-8")


# -- build_metrics -----------------------------------------------------------------------------


def test_build_metrics_reads_diagnostics_and_raw_counts(tmp_path: Path) -> None:
    paths = DataPaths(vault=tmp_path / "vault")
    _seed_vault(paths, 2024, pages=18, rr_files=343, cfbd_endpoints=6)

    tables = _tables(
        per_season={
            2024: {
                "rr_records": 343,
                "rated_telecasts": 300,
                "records_with_crew": 280,
            }
        },
        join08_by_season={2024: 0.9},
    )

    metrics = build_metrics(tables, paths)

    assert len(metrics) == 1
    m = metrics[0]
    assert m.season == 2024
    assert m.rr_records == 343
    assert m.rated_telecasts == 300
    assert m.records_with_crew == 280
    assert m.match_rate == 0.9
    assert m.sports506_pages == 18
    assert m.rr_records_cached == 343
    assert m.cfbd_files == 6


def test_build_metrics_counts_missing_directories_as_zero(tmp_path: Path) -> None:
    paths = DataPaths(vault=tmp_path / "vault")
    tables = _tables(per_season={2024: {}}, join08_by_season={2024: None})

    metrics = build_metrics(tables, paths)

    m = metrics[0]
    assert m.sports506_pages == 0
    assert m.rr_records_cached == 0
    assert m.cfbd_files == 0
    assert m.rr_records == 0
    assert m.match_rate is None


# -- load_baseline -----------------------------------------------------------------------------


def test_load_baseline_missing_file_returns_none(tmp_path: Path) -> None:
    paths = DataPaths(vault=tmp_path / "vault")
    assert load_baseline(paths) is None


def test_load_baseline_round_trips_accept_baseline(tmp_path: Path) -> None:
    paths = DataPaths(vault=tmp_path / "vault")
    paths.audit.mkdir(parents=True, exist_ok=True)
    metrics = [_metrics(2024), _metrics(2025, match_rate=None)]

    accept_baseline(paths, metrics)
    loaded = load_baseline(paths)

    assert loaded is not None
    assert loaded[2024] == metrics[0]
    assert loaded[2025].match_rate is None


def test_load_baseline_rejects_wrong_header(tmp_path: Path) -> None:
    paths = DataPaths(vault=tmp_path / "vault")
    paths.audit.mkdir(parents=True, exist_ok=True)
    (paths.audit / "build_baseline.csv").write_text(
        "season,not_the_right_header\n2024,1\n", encoding="utf-8"
    )

    with pytest.raises(VaultStateError):
        load_baseline(paths)


def test_load_baseline_rejects_non_integer_count(tmp_path: Path) -> None:
    paths = DataPaths(vault=tmp_path / "vault")
    paths.audit.mkdir(parents=True, exist_ok=True)
    header = ",".join(METRIC_COLUMNS)
    (paths.audit / "build_baseline.csv").write_text(
        f"{header}\n2024,not-a-number,80,75,0.9,18,100,6\n", encoding="utf-8"
    )

    with pytest.raises(VaultStateError):
        load_baseline(paths)


def test_load_baseline_rejects_duplicate_season(tmp_path: Path) -> None:
    paths = DataPaths(vault=tmp_path / "vault")
    paths.audit.mkdir(parents=True, exist_ok=True)
    header = ",".join(METRIC_COLUMNS)
    row = "2024,100,80,75,0.9,18,100,6"
    (paths.audit / "build_baseline.csv").write_text(f"{header}\n{row}\n{row}\n", encoding="utf-8")

    with pytest.raises(VaultStateError):
        load_baseline(paths)


# -- load_completeness_counts -------------------------------------------------------------------


def test_load_completeness_counts_missing_file_returns_none(tmp_path: Path) -> None:
    paths = DataPaths(vault=tmp_path / "vault")
    assert load_completeness_counts(paths) is None


def test_load_completeness_counts_reads_cells(tmp_path: Path) -> None:
    paths = DataPaths(vault=tmp_path / "vault")
    paths.audit.mkdir(parents=True, exist_ok=True)
    report = {
        "cells": [
            {"season": 2024, "source": "sports506", "counts": {"cached": 18}},
            {"season": 2024, "source": "ratingsref", "counts": {"cached": 343}},
            {"season": 2024, "source": "cfbd", "counts": {"present": 6}},
        ]
    }
    (paths.audit / "completeness.json").write_text(json.dumps(report), encoding="utf-8")

    counts = load_completeness_counts(paths)

    assert counts == {2024: {"sports506": 18, "ratingsref": 343, "cfbd": 6}}


def test_load_completeness_counts_corrupt_json_raises(tmp_path: Path) -> None:
    paths = DataPaths(vault=tmp_path / "vault")
    paths.audit.mkdir(parents=True, exist_ok=True)
    (paths.audit / "completeness.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(VaultStateError):
        load_completeness_counts(paths)


def test_load_completeness_counts_malformed_cell_raises(tmp_path: Path) -> None:
    paths = DataPaths(vault=tmp_path / "vault")
    paths.audit.mkdir(parents=True, exist_ok=True)
    (paths.audit / "completeness.json").write_text(
        json.dumps({"cells": [{"season": 2024, "source": "sports506", "counts": {}}]}),
        encoding="utf-8",
    )

    with pytest.raises(VaultStateError):
        load_completeness_counts(paths)


# -- check_regression --------------------------------------------------------------------------


def test_missing_baseline_and_completeness_passes_with_no_baseline_note() -> None:
    current = [_metrics(2024)]
    result = check_regression(current, None, None)
    assert result.blocked is False
    assert result.note == "no baseline"
    assert result.reasons == ()


def test_drop_in_rated_telecasts_blocks() -> None:
    baseline = {2024: _metrics(2024, rated_telecasts=100)}
    current = [_metrics(2024, rated_telecasts=90)]

    result = check_regression(current, baseline, None)

    assert result.blocked is True
    assert any("rated_telecasts" in reason for reason in result.reasons)


def test_drop_in_match_rate_blocks() -> None:
    baseline = {2024: _metrics(2024, match_rate=0.95)}
    current = [_metrics(2024, match_rate=0.90)]

    result = check_regression(current, baseline, None)

    assert result.blocked is True
    assert any("match_rate" in reason for reason in result.reasons)


def test_dropped_season_blocks() -> None:
    baseline = {2023: _metrics(2023), 2024: _metrics(2024)}
    current = [_metrics(2024)]

    result = check_regression(current, baseline, None)

    assert result.blocked is True
    assert any("2023" in reason and "missing" in reason for reason in result.reasons)


def test_input_count_below_completeness_blocks() -> None:
    completeness = {2024: {"sports506": 18, "ratingsref": 343, "cfbd": 6}}
    current = [_metrics(2024, sports506_pages=10)]

    result = check_regression(current, None, completeness)

    assert result.blocked is True
    assert any("sports506_completeness" in reason for reason in result.reasons)


def test_increases_in_every_metric_never_block() -> None:
    baseline = {2024: _metrics(2024)}
    completeness = {2024: {"sports506": 18, "ratingsref": 100, "cfbd": 6}}
    current = [
        _metrics(
            2024,
            rr_records=150,
            rated_telecasts=90,
            records_with_crew=85,
            match_rate=0.99,
            sports506_pages=20,
            rr_records_cached=150,
            cfbd_files=6,
        )
    ]

    result = check_regression(current, baseline, completeness)

    assert result.blocked is False
    assert result.reasons == ()


def test_equal_metrics_never_block() -> None:
    baseline = {2024: _metrics(2024)}
    current = [_metrics(2024)]

    result = check_regression(current, baseline, None)

    assert result.blocked is False


def test_reasons_are_season_metric_and_numbers_only() -> None:
    baseline = {2024: _metrics(2024, rated_telecasts=100)}
    current = [_metrics(2024, rated_telecasts=90)]

    result = check_regression(current, baseline, None)

    for reason in result.reasons:
        assert "2024" in reason
        assert "rated_telecasts" in reason


def test_only_completeness_runs_when_no_baseline_file() -> None:
    completeness = {2024: {"sports506": 18, "ratingsref": 100, "cfbd": 6}}
    current = [_metrics(2024, sports506_pages=18, rr_records_cached=100, cfbd_files=6)]

    result = check_regression(current, None, completeness)

    assert result.blocked is False
    assert "completeness" in result.note


# -- write_metrics / accept_baseline / write_regression_report ----------------------------------


def test_write_metrics_writes_csv(tmp_path: Path) -> None:
    paths = DataPaths(vault=tmp_path / "vault")
    paths.audit.mkdir(parents=True, exist_ok=True)
    metrics = [_metrics(2024)]

    written = write_metrics(paths, metrics)

    assert written == ["audit/build_metrics.csv"]
    text = (paths.vault / "audit/build_metrics.csv").read_text(encoding="utf-8")
    assert text.splitlines()[0] == ",".join(METRIC_COLUMNS)


def test_accept_baseline_writes_csv(tmp_path: Path) -> None:
    paths = DataPaths(vault=tmp_path / "vault")
    paths.audit.mkdir(parents=True, exist_ok=True)
    metrics = [_metrics(2024)]

    written = accept_baseline(paths, metrics)

    assert written == ["audit/build_baseline.csv"]
    assert (paths.vault / "audit/build_baseline.csv").is_file()


def test_write_regression_report_lists_every_compared_metric(tmp_path: Path) -> None:
    paths = DataPaths(vault=tmp_path / "vault")
    paths.audit.mkdir(parents=True, exist_ok=True)
    baseline = {2024: _metrics(2024, rated_telecasts=100)}
    completeness = {2024: {"sports506": 18, "ratingsref": 100, "cfbd": 6}}
    current = [_metrics(2024, rated_telecasts=90)]
    result = check_regression(current, baseline, completeness)

    written = write_regression_report(paths, current, baseline, completeness, result)

    assert written == ["audit/regression.csv"]
    text = (paths.vault / "audit/regression.csv").read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines[0] == "season,metric,baseline,current,status"
    # 7 baseline metrics + 3 completeness metrics = 10 data rows.
    assert len(lines) - 1 == 10
    assert any("rated_telecasts" in line and "blocked" in line for line in lines[1:])


def test_regression_result_dataclass_fields() -> None:
    result = RegressionResult(
        blocked=True,
        reasons=("season 2024: x 1 below baseline 2",),
        compared_seasons=1,
        note="n",
    )
    assert result.blocked is True
    assert result.compared_seasons == 1
