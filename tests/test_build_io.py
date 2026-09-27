"""Tests for build/io.py (atomic Parquet/CSV writers) and build/sources.py
(the per-season raw-source loader), on the synthetic `build_vault` fixture
(invented teams, people, and figures only; D-07).
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from booth_review.build.io import write_parquet_atomic, write_review_csv
from booth_review.build.sources import load_all_sources, load_season_sources
from booth_review.config import DataPaths

# -- io.write_parquet_atomic -----------------------------------------------------------------


def test_write_parquet_atomic_round_trips_nulls(tmp_path: Path) -> None:
    frame = pl.DataFrame(
        {"a": [1, None, 3], "b": ["x", "y", None]},
        schema={"a": pl.Int64(), "b": pl.Utf8()},
    )
    out_path = tmp_path / "table.parquet"

    write_parquet_atomic(frame, out_path)

    assert out_path.is_file()
    read_back = pl.read_parquet(out_path)
    assert read_back.equals(frame)
    assert read_back["a"].null_count() == 1
    assert read_back["b"].null_count() == 1


def test_write_parquet_atomic_creates_parent_dirs(tmp_path: Path) -> None:
    frame = pl.DataFrame({"a": [1]}, schema={"a": pl.Int64()})
    out_path = tmp_path / "nested" / "dir" / "table.parquet"

    write_parquet_atomic(frame, out_path)

    assert out_path.is_file()


def test_write_parquet_atomic_leaves_no_tmp_file_on_success(tmp_path: Path) -> None:
    frame = pl.DataFrame({"a": [1]}, schema={"a": pl.Int64()})
    out_path = tmp_path / "table.parquet"

    write_parquet_atomic(frame, out_path)

    leftovers = list(tmp_path.glob(".tmp-*"))
    assert leftovers == []


# -- io.write_review_csv ----------------------------------------------------------------------


def test_write_review_csv_writes_header_and_rows_with_lf_endings(tmp_path: Path) -> None:
    out_path = tmp_path / "review.csv"

    write_review_csv(
        out_path,
        ["id", "name"],
        [{"id": "1", "name": "Alex"}, {"id": "2", "name": "Sam"}],
    )

    raw = out_path.read_bytes()
    assert b"\r\n" not in raw
    text = raw.decode("utf-8")
    assert text.splitlines() == ["id,name", "1,Alex", "2,Sam"]


def test_write_review_csv_applies_csv_safe_to_formula_like_cells(tmp_path: Path) -> None:
    out_path = tmp_path / "review.csv"

    write_review_csv(out_path, ["note"], [{"note": "=SUM(A1:A2)"}])

    text = out_path.read_text(encoding="utf-8")
    assert "'=SUM(A1:A2)" in text


def test_write_review_csv_writes_none_as_empty_cell(tmp_path: Path) -> None:
    out_path = tmp_path / "review.csv"

    write_review_csv(out_path, ["id", "note"], [{"id": "1", "note": None}])

    text = out_path.read_text(encoding="utf-8")
    assert text.splitlines()[1] == "1,"


def test_write_review_csv_does_not_sort_rows(tmp_path: Path) -> None:
    out_path = tmp_path / "review.csv"

    write_review_csv(out_path, ["id"], [{"id": "2"}, {"id": "1"}])

    text = out_path.read_text(encoding="utf-8")
    assert text.splitlines()[1:] == ["2", "1"]


# -- sources.load_season_sources ---------------------------------------------------------------


def test_load_season_sources_loads_every_endpoint_for_2025(build_vault: DataPaths) -> None:
    sources = load_season_sources(build_vault, 2025)

    assert sources.season == 2025
    assert len(sources.games) == 30
    assert len(sources.listings) > 0
    assert len(sources.rr_records) > 0
    assert sources.rr_parse_errors == 0
    assert len(sources.media) > 0
    assert len(sources.lines) > 0
    assert len(sources.rankings) > 0
    assert len(sources.wp_pregame) > 0


def test_load_season_sources_missing_endpoint_file_gives_empty_list(
    build_vault: DataPaths,
) -> None:
    (build_vault.raw / "cfbd" / "media" / "2025.json").unlink()

    sources = load_season_sources(build_vault, 2025)

    assert sources.media == []
    # every other endpoint is unaffected by one missing file
    assert len(sources.games) == 30


def test_load_season_sources_missing_season_gives_empty_everything(
    build_vault: DataPaths,
) -> None:
    sources = load_season_sources(build_vault, 1999)

    assert sources.season == 1999
    assert sources.games == []
    assert sources.listings == []
    assert sources.rr_records == []
    assert sources.rr_parse_errors == 0
    assert sources.media == []
    assert sources.lines == []
    assert sources.rankings == []
    assert sources.wp_pregame == []


# -- sources.load_all_sources ------------------------------------------------------------------


def test_load_all_sources_returns_one_per_vault_season_ascending(build_vault: DataPaths) -> None:
    extra_games_dir = build_vault.raw / "cfbd" / "games"
    (extra_games_dir / "2024.json").write_bytes((extra_games_dir / "2025.json").read_bytes())

    all_sources = load_all_sources(build_vault)

    assert [s.season for s in all_sources] == [2024, 2025]


def test_load_all_sources_honors_explicit_seasons_argument(build_vault: DataPaths) -> None:
    all_sources = load_all_sources(build_vault, seasons=[2025])

    assert [s.season for s in all_sources] == [2025]
