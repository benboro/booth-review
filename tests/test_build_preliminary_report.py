"""Preliminary headlines older than 10 days are listed in a private interim
report (PITFALLS "Looks Done But Isn't"). Synthetic data only.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest
from test_cli_build import _seed_build_raw

from booth_review.build import pipeline
from booth_review.build.pipeline import PRELIMINARY_STALE_DAYS, run_build
from booth_review.build.tables import BuildTables
from booth_review.config import DataPaths

_REFERENCE_FIXTURES = Path(__file__).parent / "fixtures" / "reference"
# Telecast 500002-ecn is played 2025-12-06; its headline claim is made preliminary below.
_TARGET = "500002-ecn"


def _build(
    git_vault: DataPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, now: datetime
) -> pipeline.BuildOutcome:
    _seed_build_raw(git_vault)
    reference = tmp_path / "reference_ext"
    shutil.copytree(_REFERENCE_FIXTURES, reference)
    with (reference / "networks.csv").open("a", encoding="utf-8", newline="") as fh:
        fh.write("ECN,ecn,Example Cable Network,family-ecn,cable,main,,,\n")
        fh.write("ECN2,ecn2,Example Cable Network 2,family-ecn,cable,main,,,\n")
        fh.write("ESPN,espn,ESPN,family-espn,cable,main,,,\n")
        fh.write("ESPN2,espn2,ESPN2,family-espn,cable,main,,,\n")
        fh.write("ESPNU,espnu,ESPNU,family-espn,cable,main,,,\n")
        fh.write("ESPN Deportes,espn-deportes,ESPN Deportes,family-espn,cable,spanish,,,\n")
    (reference / "bowls.csv").write_text(
        "cfbd_game_id,official_name,core_name,at_bowl,franchise\n"
        "500007,Zebra Ridge Bowl,Ridge Bowl,true,ridge-bowl\n",
        encoding="utf-8",
    )

    original = pipeline.assemble_tables

    def with_preliminary_headline(paths: DataPaths, reference_directory: Path) -> BuildTables:
        tables = original(paths, reference_directory)
        viewership = tables.viewership.with_columns(
            pl.when((pl.col("telecast_id") == _TARGET) & pl.col("is_headline"))
            .then(pl.lit("preliminary"))
            .otherwise(pl.col("status"))
            .alias("status")
        )
        return BuildTables(**{**tables.__dict__, "viewership": viewership})

    monkeypatch.setattr(pipeline, "assemble_tables", with_preliminary_headline)
    return run_build(git_vault, reference, commit=False, accept_baseline=False, now=now)


def test_stale_constant_is_ten_days() -> None:
    assert PRELIMINARY_STALE_DAYS == 10


def test_twelve_day_old_preliminary_headline_is_listed(
    git_vault: DataPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outcome = _build(git_vault, tmp_path, monkeypatch, datetime(2025, 12, 18, tzinfo=UTC))
    assert outcome.counts["preliminary_headlines_over_10_days"] == 1
    report = git_vault.vault / "interim" / "review_preliminary_headlines.csv"
    lines = report.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "telecast_id,date_et,claim_id"
    assert len(lines) == 2
    assert lines[1].startswith(f"{_TARGET},2025-12-06,")


def test_nine_day_old_preliminary_headline_is_not_listed(
    git_vault: DataPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outcome = _build(git_vault, tmp_path, monkeypatch, datetime(2025, 12, 15, tzinfo=UTC))
    assert outcome.counts["preliminary_headlines_over_10_days"] == 0
    report = git_vault.vault / "interim" / "review_preliminary_headlines.csv"
    assert _TARGET not in report.read_text(encoding="utf-8")
