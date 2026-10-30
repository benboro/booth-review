"""Tests for build/regression.py: the AUDIT-03 regression guard against an
accepted build baseline and the Phase 2 completeness counts.
"""

from __future__ import annotations

import json
from dataclasses import replace
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
        "records_with_506_crew": 75,
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
                "records_with_506_crew": 270,
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
    assert m.records_with_506_crew == 270
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


def test_load_baseline_rejects_a_506_crew_count_that_is_not_an_integer(tmp_path: Path) -> None:
    paths = DataPaths(vault=tmp_path / "vault")
    paths.audit.mkdir(parents=True, exist_ok=True)
    header = ",".join(METRIC_COLUMNS)
    (paths.audit / "build_baseline.csv").write_text(
        f"{header}\n2024,100,80,75,,0.9,18,100,6\n", encoding="utf-8"
    )

    with pytest.raises(VaultStateError):
        load_baseline(paths)


def _legacy_baseline(paths: DataPaths, rows: list[str]) -> None:
    """A baseline accepted before records_with_506_crew existed (04.3 IN-06)."""
    paths.audit.mkdir(parents=True, exist_ok=True)
    header = ",".join(c for c in METRIC_COLUMNS if c != "records_with_506_crew")
    body = "".join(f"{row}\n" for row in rows)
    (paths.audit / "build_baseline.csv").write_text(f"{header}\n{body}", encoding="utf-8")


def test_legacy_baseline_loads_with_no_506_crew_baseline(tmp_path: Path) -> None:
    paths = DataPaths(vault=tmp_path / "vault")
    _legacy_baseline(paths, ["2024,100,80,75,0.9375,18,100,6"])

    loaded = load_baseline(paths)

    assert loaded == {2024: _metrics(2024, records_with_506_crew=None)}


def test_legacy_baseline_never_blocks_on_the_new_metric(tmp_path: Path) -> None:
    paths = DataPaths(vault=tmp_path / "vault")
    _legacy_baseline(paths, ["2024,100,80,75,0.9375,18,100,6"])
    baseline = load_baseline(paths)
    # Far below records_with_crew: there is simply no accepted 506-only count yet.
    current = [_metrics(2024, records_with_506_crew=0)]

    result = check_regression(current, baseline, None)
    assert result.blocked is False
    assert result.reasons == ()

    written = write_regression_report(paths, current, baseline, None, result)
    assert written == ["audit/regression.csv"]
    text = (paths.vault / "audit/regression.csv").read_text(encoding="utf-8")
    assert "2024,records_with_506_crew,,0,ok" in text.splitlines()


def test_legacy_baseline_still_blocks_on_the_old_metrics(tmp_path: Path) -> None:
    paths = DataPaths(vault=tmp_path / "vault")
    _legacy_baseline(paths, ["2024,100,80,75,0.9375,18,100,6"])
    current = [_metrics(2024, records_with_crew=70)]

    result = check_regression(current, load_baseline(paths), None)

    assert result.blocked is True
    assert result.reasons == ("season 2024: records_with_crew 70 below baseline 75",)


def test_accepting_after_a_legacy_baseline_writes_the_new_column(tmp_path: Path) -> None:
    paths = DataPaths(vault=tmp_path / "vault")
    _legacy_baseline(paths, ["2024,100,80,75,0.9375,18,100,6"])

    accept_baseline(paths, [_metrics(2024, records_with_506_crew=72)])

    loaded = load_baseline(paths)
    assert loaded is not None
    assert loaded[2024].records_with_506_crew == 72


def test_lost_506_crew_covered_by_an_override_still_blocks() -> None:
    # 506 dropped a crew worth 2 records; an override patched the same
    # telecast, so records_with_crew (and JOIN-08) did not move.
    baseline = {2024: _metrics(2024)}
    current = [_metrics(2024, records_with_506_crew=73)]

    result = check_regression(current, baseline, None)

    assert result.blocked is True
    assert result.reasons == ("season 2024: records_with_506_crew 73 below baseline 75",)


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
        f"{header}\n2024,not-a-number,80,75,75,0.9,18,100,6\n", encoding="utf-8"
    )

    with pytest.raises(VaultStateError):
        load_baseline(paths)


def test_load_baseline_rejects_duplicate_season(tmp_path: Path) -> None:
    paths = DataPaths(vault=tmp_path / "vault")
    paths.audit.mkdir(parents=True, exist_ok=True)
    header = ",".join(METRIC_COLUMNS)
    row = "2024,100,80,75,75,0.9,18,100,6"
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
            records_with_506_crew=85,
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
    # 8 baseline metrics + 3 completeness metrics = 11 data rows.
    assert len(lines) - 1 == 11
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


# -- explained match_rate drops (rated games 506 lists with no crew) ---------------------------


def _gap_metrics(season: int, *, crewless: int, gaps: int, games: int, **overrides: object):
    """A current-build season with `crewless` crewless denominator records, `gaps` of
    them unpatched no-506-crew gaps on `games` games."""
    return _metrics(
        season,
        crewless_records=crewless,
        no_506_crew_records=gaps,
        no_506_crew_games=games,
        **overrides,
    )


def test_drop_explained_by_no_506_crew_gaps_does_not_block(tmp_path: Path) -> None:
    # Accepted at 1.0; RR then rates one game whose 506 row has a blank crew.
    baseline = {2022: _metrics(2022, rr_records=141, records_with_crew=141, match_rate=1.0)}
    current = [
        _gap_metrics(
            2022,
            crewless=1,
            gaps=1,
            games=1,
            rr_records=142,
            records_with_crew=141,
            match_rate=141 / 142,
        )
    ]

    result = check_regression(current, baseline, None)

    assert result.blocked is False
    assert result.reasons == ()
    assert [(d.season, d.games) for d in result.explained] == [(2022, 1)]

    paths = DataPaths(vault=tmp_path / "vault")
    paths.audit.mkdir(parents=True)
    write_regression_report(paths, current, baseline, None, result)
    lines = (paths.vault / "audit/regression.csv").read_text(encoding="utf-8").splitlines()
    rate_rows = [line for line in lines if ",match_rate," in line]
    assert len(rate_rows) == 1
    assert rate_rows[0].startswith("2022,match_rate,1.0,")
    assert rate_rows[0].endswith(",explained")


def test_no_506_listing_crewless_record_still_blocks() -> None:
    # Two crewless records, only one of them a no-506-crew gap: the other has
    # no 506 listing at all, which can mean a 506 page stopped parsing.
    baseline = {2026: _metrics(2026, rr_records=282, records_with_crew=282, match_rate=1.0)}
    current = [
        _gap_metrics(
            2026,
            crewless=2,
            gaps=1,
            games=1,
            rr_records=284,
            records_with_crew=282,
            match_rate=282 / 284,
        )
    ]

    result = check_regression(current, baseline, None)

    assert result.blocked is True
    assert result.reasons == ("season 2026: match_rate 0.993 below baseline 1.0",)
    assert result.explained == ()


def test_drop_with_no_gaps_at_all_still_blocks() -> None:
    baseline = {2026: _metrics(2026, match_rate=1.0)}
    current = [_gap_metrics(2026, crewless=3, gaps=0, games=0, match_rate=0.97)]

    result = check_regression(current, baseline, None)

    assert result.blocked is True
    assert result.explained == ()


def test_crew_loss_alongside_gaps_blocks_and_the_drop_is_not_explained(tmp_path: Path) -> None:
    # A crew was lost (records_with_crew fell) and that game now shows as a
    # blank 506 crew: every crewless record is a gap, but the loss still blocks.
    base = _metrics(2024, records_with_crew=80, records_with_506_crew=80, match_rate=1.0)
    baseline = {2024: base}
    current = [
        _gap_metrics(
            2024,
            crewless=1,
            gaps=1,
            games=1,
            records_with_crew=79,
            records_with_506_crew=79,
            match_rate=79 / 80,
        )
    ]

    result = check_regression(current, baseline, None)

    assert result.blocked is True
    assert "season 2024: records_with_crew 79 below baseline 80" in result.reasons
    assert "season 2024: match_rate 0.9875 below baseline 1.0" in result.reasons
    assert result.explained == ()

    paths = DataPaths(vault=tmp_path / "vault")
    paths.audit.mkdir(parents=True)
    write_regression_report(paths, current, baseline, None, result)
    text = (paths.vault / "audit/regression.csv").read_text(encoding="utf-8")
    assert "explained" not in text


def test_506_crew_loss_alongside_gaps_blocks() -> None:
    # An override hides the lost 506 crew from records_with_crew, not from the 506-only count.
    base = _metrics(2024, records_with_crew=80, records_with_506_crew=80, match_rate=1.0)
    baseline = {2024: base}
    current = [
        _gap_metrics(
            2024,
            crewless=1,
            gaps=1,
            games=1,
            rr_records=101,
            records_with_crew=80,
            records_with_506_crew=78,
            match_rate=80 / 81,
        )
    ]

    result = check_regression(current, baseline, None)

    assert result.blocked is True
    assert result.reasons == (
        "season 2024: records_with_506_crew 78 below baseline 80",
        "season 2024: match_rate 0.9877 below baseline 1.0",
    )
    assert result.explained == ()


def test_explained_drop_does_not_hide_other_blocks() -> None:
    baseline = {2022: _metrics(2022, match_rate=1.0), 2023: _metrics(2023)}
    completeness = {2022: {"sports506": 18, "ratingsref": 100, "cfbd": 6}}
    current = [
        _gap_metrics(2022, crewless=1, gaps=1, games=1, match_rate=0.99, sports506_pages=17),
        _metrics(2023, rated_telecasts=70),
    ]

    result = check_regression(current, baseline, completeness)

    assert result.blocked is True
    assert result.reasons == (
        "season 2022: sports506_pages 17 below baseline 18",
        "season 2023: rated_telecasts 70 below baseline 80",
        "season 2022: sports506_completeness 17 below baseline 18",
    )
    assert [(d.season, d.games) for d in result.explained] == [(2022, 1)]


def test_build_metrics_counts_crewless_records_and_no_506_crew_gaps(tmp_path: Path) -> None:
    paths = DataPaths(vault=tmp_path / "vault")
    tables = _tables(
        per_season={
            2022: {
                "rr_records": 150,
                "rr_excluded": 3,
                "rr_out_of_scope": 5,
                "records_with_crew": 140,
            },
            2023: {"rr_records": 10, "records_with_crew": 10},
        },
        join08_by_season={2022: 140 / 142, 2023: 1.0},
    )
    tables = replace(
        tables, diagnostics=replace(tables.diagnostics, no_506_crew_by_season={2022: (1, 2)})
    )

    by_season = {m.season: m for m in build_metrics(tables, paths)}

    assert by_season[2022].crewless_records == 2
    assert (by_season[2022].no_506_crew_games, by_season[2022].no_506_crew_records) == (1, 2)
    assert by_season[2023].crewless_records == 0
    assert by_season[2023].no_506_crew_records == 0


def test_baseline_files_keep_their_header_and_load_without_gap_counts(tmp_path: Path) -> None:
    # The gap counts are current-build only: the header a v0.18.2 vault holds is
    # still METRIC_COLUMNS, and a written-then-loaded baseline drops the counts.
    paths = DataPaths(vault=tmp_path / "vault")
    paths.audit.mkdir(parents=True)
    accept_baseline(paths, [_gap_metrics(2024, crewless=1, gaps=1, games=1)])

    header = (paths.audit / "build_baseline.csv").read_text(encoding="utf-8").splitlines()[0]
    assert header == (
        "season,rr_records,rated_telecasts,records_with_crew,records_with_506_crew,"
        "match_rate,sports506_pages,rr_records_cached,cfbd_files"
    )
    assert load_baseline(paths) == {2024: _metrics(2024)}
