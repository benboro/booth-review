"""Tests for the strict data/reference CSV reader/writer
(src/booth_review/reference.py). Every file here is created under tmp_path;
no real data/reference file is touched.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

from booth_review.errors import ReferenceTableError
from booth_review.reference import read_reference_csv, write_reference_csv

COLUMNS = ("id", "name", "note")


def _write_raw_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    """Write a CSV file byte-for-byte the way the csv module would encode
    it, so an embedded formula-prefix character (e.g. a bare \\r) is quoted
    correctly rather than corrupting line splitting.
    """
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow(row)
    path.write_bytes(buf.getvalue().encode("utf-8"))


def test_missing_file_not_required_returns_empty(tmp_path: Path) -> None:
    assert read_reference_csv(tmp_path / "missing.csv", COLUMNS) == []


def test_missing_file_required_raises(tmp_path: Path) -> None:
    with pytest.raises(ReferenceTableError):
        read_reference_csv(tmp_path / "missing.csv", COLUMNS, required=True)


def test_header_missing_column_raises(tmp_path: Path) -> None:
    path = tmp_path / "bad_header.csv"
    _write_raw_csv(path, ["id", "name"], [["1", "a"]])
    with pytest.raises(ReferenceTableError):
        read_reference_csv(path, COLUMNS)


def test_header_extra_column_raises(tmp_path: Path) -> None:
    path = tmp_path / "extra_header.csv"
    _write_raw_csv(path, ["id", "name", "note", "extra"], [["1", "a", "x", "y"]])
    with pytest.raises(ReferenceTableError):
        read_reference_csv(path, COLUMNS)


def test_header_reordered_raises(tmp_path: Path) -> None:
    path = tmp_path / "reordered.csv"
    _write_raw_csv(path, ["name", "id", "note"], [["a", "1", "x"]])
    with pytest.raises(ReferenceTableError):
        read_reference_csv(path, COLUMNS)


def test_empty_file_raises(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    path.write_bytes(b"")
    with pytest.raises(ReferenceTableError):
        read_reference_csv(path, COLUMNS)


def test_row_with_extra_cells_raises(tmp_path: Path) -> None:
    path = tmp_path / "extra_cells.csv"
    _write_raw_csv(path, list(COLUMNS), [["1", "a", "x", "extra"]])
    with pytest.raises(ReferenceTableError, match=r"line 2"):
        read_reference_csv(path, COLUMNS)


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@", "\t", "\r"])
def test_formula_prefix_raises(tmp_path: Path, prefix: str) -> None:
    path = tmp_path / "formula.csv"
    _write_raw_csv(path, list(COLUMNS), [["1", f"{prefix}cmd", "x"]])
    with pytest.raises(ReferenceTableError, match=r"line 2"):
        read_reference_csv(path, COLUMNS)


def test_blank_row_is_skipped(tmp_path: Path) -> None:
    path = tmp_path / "blank.csv"
    _write_raw_csv(path, list(COLUMNS), [["1", "a", "x"], ["", "", ""]])
    assert read_reference_csv(path, COLUMNS) == [{"id": "1", "name": "a", "note": "x"}]


def test_values_are_stripped(tmp_path: Path) -> None:
    path = tmp_path / "spaced.csv"
    _write_raw_csv(path, list(COLUMNS), [[" 1 ", " a ", "  x  "]])
    assert read_reference_csv(path, COLUMNS) == [{"id": "1", "name": "a", "note": "x"}]


def test_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "round_trip.csv"
    rows = [
        {"id": "1", "name": "a", "note": "first"},
        {"id": "2", "name": "b", "note": "second"},
    ]
    write_reference_csv(path, COLUMNS, rows)
    assert read_reference_csv(path, COLUMNS) == rows


def test_write_uses_lf_line_endings(tmp_path: Path) -> None:
    path = tmp_path / "lf.csv"
    write_reference_csv(path, COLUMNS, [{"id": "1", "name": "a", "note": "x"}])
    raw = path.read_bytes()
    assert b"\r\n" not in raw
    assert raw == b"id,name,note\n1,a,x\n"
