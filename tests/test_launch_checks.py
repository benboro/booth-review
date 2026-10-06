"""Focused checks behind docs/LAUNCH.md items that had no test of their own.
Synthetic data only.
"""

from __future__ import annotations

import json
import shutil
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
from test_cli_build import _seed_build_raw

from booth_review.build.games import build_games_frame
from booth_review.build.pipeline import run_build
from booth_review.build.sources import load_all_sources
from booth_review.config import DataPaths

_TESTS = Path(__file__).parent
_REFERENCE_FIXTURES = _TESTS / "fixtures" / "reference"


def _synthetic_build(git_vault: DataPaths, tmp_path: Path) -> DataPaths:
    """One synthetic `run_build` over the seeded 2025 vault."""
    _seed_build_raw(git_vault)
    reference = tmp_path / "reference_ext"
    shutil.copytree(_REFERENCE_FIXTURES, reference)
    with (reference / "network_rarity.csv").open("a", encoding="utf-8", newline="") as rarity_fh:
        rarity_fh.write(
            "ecn,false\necn2,false\nespn,false\nespn2,false\nespnu,false\nespn-deportes,false\n"
        )
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
    run_build(
        git_vault,
        reference,
        commit=False,
        accept_baseline=False,
        now=datetime(2025, 12, 30, tzinfo=UTC),
    )
    return git_vault


def test_plotted_telecasts_unique_on_game_and_primary_network(
    git_vault: DataPaths, tmp_path: Path
) -> None:
    paths = _synthetic_build(git_vault, tmp_path)
    telecasts = pl.read_parquet(paths.vault / "processed" / "telecasts.parquet")
    plotted = telecasts.filter(pl.col("plotted"))
    assert plotted.height >= 3
    counts = Counter(zip(plotted["game_id"], plotted["network_id"], strict=True))
    assert max(counts.values()) == 1


def test_headline_viewership_rows_are_all_avg_audience(
    git_vault: DataPaths, tmp_path: Path
) -> None:
    paths = _synthetic_build(git_vault, tmp_path)
    viewership = pl.read_parquet(paths.vault / "processed" / "viewership.parquet")
    headlines = viewership.filter(pl.col("is_headline"))
    assert headlines.height >= 1
    assert set(headlines["metric_type"]) == {"avg_audience"}


def test_november_kickoff_uses_est_offset(build_vault: DataPaths) -> None:
    frame = build_games_frame(load_all_sources(build_vault, seasons=[2025]))
    november = frame.filter(frame["game_id"] == 500005).row(0, named=True)
    october = frame.filter(frame["game_id"] == 500001).row(0, named=True)
    # startDate 2025-11-08T18:00:00Z is after the 2025-11-02 fall-back: EST.
    assert november["kickoff_et"].startswith("2025-11-08T13:00:00-05:00")
    # startDate 2025-10-11T19:30:00Z is before it: EDT.
    assert october["kickoff_et"].startswith("2025-10-11T15:30:00-04:00")


def test_fixture_pages_are_marked_synthetic() -> None:
    pages = sorted((_TESTS / "fixtures").rglob("*.html"))
    assert len(pages) >= 6
    for page in pages:
        text = page.read_text(encoding="utf-8", errors="ignore")
        assert "synthetic" in text.lower(), page.name

    for path in _TESTS.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts or path == Path(__file__):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert "saved from url=" not in text, path.name


def test_plotted_rows_keep_rr_record_urls_and_headline_source_url(
    git_vault: DataPaths, tmp_path: Path
) -> None:
    paths = _synthetic_build(git_vault, tmp_path)
    site = json.loads((paths.vault / "processed" / "site-data.json").read_text(encoding="utf-8"))
    columns = site["telecasts"]
    assert len(columns["rr_urls"]) >= 3
    assert all(len(urls) >= 1 for urls in columns["rr_urls"])

    telecasts = pl.read_parquet(paths.vault / "processed" / "telecasts.parquet")
    viewership = pl.read_parquet(paths.vault / "processed" / "viewership.parquet")
    plotted_ids = telecasts.filter(pl.col("plotted"))["telecast_id"].to_list()
    headlines = viewership.filter(pl.col("is_headline") & pl.col("telecast_id").is_in(plotted_ids))
    assert Counter(columns["source_url"]) == Counter(headlines["source_url"].to_list())
