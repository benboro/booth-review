"""Tests for the strict data/reference CSV reader/writer
(src/booth_review/reference.py). Every file here is created under tmp_path;
no real data/reference file is touched.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Callable
from pathlib import Path

import pytest

from booth_review.errors import ReferenceTableError
from booth_review.reference import (
    read_reference_csv,
    read_reference_csv_numbered,
    write_reference_csv,
)

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


def test_numbered_rows_carry_physical_line_numbers(tmp_path: Path) -> None:
    path = tmp_path / "spaced_out.csv"
    path.write_text("id,name,note\n\n1,a,x\n,,\n\n2,b,y\n", encoding="utf-8")
    assert read_reference_csv_numbered(path, COLUMNS) == [
        (3, {"id": "1", "name": "a", "note": "x"}),
        (6, {"id": "2", "name": "b", "note": "y"}),
    ]
    assert read_reference_csv(path, COLUMNS) == [
        row for _, row in read_reference_csv_numbered(path, COLUMNS)
    ]


def test_reader_error_cites_physical_line_after_blank_rows(tmp_path: Path) -> None:
    path = tmp_path / "spaced_formula.csv"
    path.write_text("id,name,note\n\n\n1,=cmd,x\n", encoding="utf-8")
    with pytest.raises(ReferenceTableError, match=r"line 4:"):
        read_reference_csv(path, COLUMNS)


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


# -- WR-13: whitespace can't smuggle a formula past the check; writes can't produce one -------


def test_formula_behind_leading_whitespace_raises(tmp_path: Path) -> None:
    path = tmp_path / "t.csv"
    path.write_text('a,b\nx," =HYPERLINK(1)"\n', encoding="utf-8")
    with pytest.raises(ReferenceTableError, match="disallowed"):
        read_reference_csv(path, ("a", "b"))


def test_write_refuses_a_formula_leading_cell(tmp_path: Path) -> None:
    path = tmp_path / "t.csv"
    with pytest.raises(ReferenceTableError, match="disallowed"):
        write_reference_csv(path, ("a", "b"), [{"a": "x", "b": "-"}])
    assert not path.exists()


# -- Loader line numbers stay right when a hand-edited table has blank spacer rows --------


def _loader_cases() -> list[tuple[str, tuple[str, ...], Callable[[Path], object]]]:
    from booth_review.build.bowls import BOWL_COLUMNS, load_bowls
    from booth_review.build.combined import COMBINED_COLUMNS, load_combined_figures
    from booth_review.build.crew_overrides import CREW_OVERRIDE_COLUMNS, load_crew_overrides
    from booth_review.build.rivalries import RIVALRY_COLUMNS, load_rivalries
    from booth_review.people.registry import (
        PEOPLE_COLUMNS,
        PERSON_OVERRIDE_COLUMNS,
        REVIEWED_COLUMNS,
        load_people,
        load_person_overrides,
        load_reviewed,
    )
    from booth_review.resolve.networks import (
        NETWORK_COLUMNS,
        NETWORK_RARITY_COLUMNS,
        PRIMARY_OVERRIDE_COLUMNS,
        load_network_rarity,
        load_networks,
        load_primary_overrides,
    )
    from booth_review.resolve.overrides import GAME_OVERRIDE_COLUMNS, load_game_overrides
    from booth_review.resolve.teams import TEAM_CROSSWALK_COLUMNS, load_team_crosswalk

    return [
        ("bowls.csv", BOWL_COLUMNS, load_bowls),
        ("rivalries.csv", RIVALRY_COLUMNS, load_rivalries),
        ("combined_figures.csv", COMBINED_COLUMNS, load_combined_figures),
        ("crew_overrides.csv", CREW_OVERRIDE_COLUMNS, load_crew_overrides),
        ("people.csv", PEOPLE_COLUMNS, load_people),
        ("people_reviewed.csv", REVIEWED_COLUMNS, load_reviewed),
        ("person_overrides.csv", PERSON_OVERRIDE_COLUMNS, load_person_overrides),
        ("networks.csv", NETWORK_COLUMNS, load_networks),
        ("primary_network_overrides.csv", PRIMARY_OVERRIDE_COLUMNS, load_primary_overrides),
        ("network_rarity.csv", NETWORK_RARITY_COLUMNS, load_network_rarity),
        ("game_overrides.csv", GAME_OVERRIDE_COLUMNS, load_game_overrides),
        ("team_crosswalk.csv", TEAM_CROSSWALK_COLUMNS, load_team_crosswalk),
    ]


@pytest.mark.parametrize("index", range(12))
def test_loader_errors_cite_the_physical_line_past_blank_rows(tmp_path: Path, index: int) -> None:
    name, columns, load = _loader_cases()[index]
    bad_row = ",".join(["ZZ BAD"] * len(columns))
    (tmp_path / name).write_text(",".join(columns) + "\n\n\n" + bad_row + "\n", encoding="utf-8")
    with pytest.raises(ReferenceTableError) as exc:
        load(tmp_path)
    assert f"{name}: line 4:" in str(exc.value)
