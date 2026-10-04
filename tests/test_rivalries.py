"""Loader validation for the curated rivalries table (D-12/D-13).

Team and rivalry names below are invented.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from booth_review.build.rivalries import RIVALRY_COLUMNS, Rivalry, load_rivalries
from booth_review.errors import ReferenceTableError
from booth_review.transport.cache import atomic_write_bytes

HEADER = "rivalry_id,name,team_a,team_b,season_from,season_to\n"


def _write(tmp_path: Path, body: str) -> Path:
    atomic_write_bytes(tmp_path / "rivalries.csv", (HEADER + body).encode("utf-8"))
    return tmp_path


def _rejects(tmp_path: Path, body: str, line: int = 2, leaked: tuple[str, ...] = ()) -> str:
    with pytest.raises(ReferenceTableError) as exc:
        load_rivalries(_write(tmp_path, body))
    text = str(exc.value)
    assert f"rivalries.csv: line {line}" in text
    for word in ("Northfield", "Lakeview", "Zebra"):
        assert word not in text
    for word in leaked:
        assert word not in text
    return text


def test_columns_constant() -> None:
    assert RIVALRY_COLUMNS == (
        "rivalry_id",
        "name",
        "team_a",
        "team_b",
        "season_from",
        "season_to",
    )


def test_valid_rows_load_in_order(tmp_path: Path) -> None:
    ref = _write(
        tmp_path,
        "zebra-cup,Zebra Cup,Northfield,Lakeview,,\n"
        'ridge-run,"Ridge, Run",Lakeview,Hilltop,2005,2012\n',
    )
    assert load_rivalries(ref) == [
        Rivalry("zebra-cup", "Zebra Cup", "Northfield", "Lakeview", None, None),
        Rivalry("ridge-run", "Ridge, Run", "Lakeview", "Hilltop", 2005, 2012),
    ]


def test_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_rivalries(tmp_path) == []


def test_wrong_header_raises(tmp_path: Path) -> None:
    atomic_write_bytes(tmp_path / "rivalries.csv", b"a,b\n1,2\n")
    with pytest.raises(ReferenceTableError):
        load_rivalries(tmp_path)


def test_rejects_bad_id(tmp_path: Path) -> None:
    _rejects(tmp_path, "Zebra_Cup,Zebra Cup,Northfield,Lakeview,,\n", leaked=("Zebra_Cup",))


def test_rejects_duplicate_id(tmp_path: Path) -> None:
    _rejects(
        tmp_path,
        "zc,Zebra Cup,Northfield,Lakeview,,\nzc,Other Cup,Northfield,Hilltop,,\n",
        line=3,
    )


def test_rejects_duplicate_name_case_insensitive(tmp_path: Path) -> None:
    _rejects(
        tmp_path,
        "a,Zebra Cup,Northfield,Lakeview,,\nb,ZEBRA cup,Northfield,Hilltop,,\n",
        line=3,
    )


def test_rejects_repeated_unordered_pair(tmp_path: Path) -> None:
    _rejects(
        tmp_path,
        "a,Zebra Cup,Northfield,Lakeview,,\nb,Other Cup,Lakeview,Northfield,,\n",
        line=3,
    )


def test_rejects_identical_teams(tmp_path: Path) -> None:
    _rejects(tmp_path, "a,Zebra Cup,Northfield,Northfield,,\n")


@pytest.mark.parametrize(
    "row",
    ["a,,Northfield,Lakeview,,\n", "a,Zebra Cup,,Lakeview,,\n", "a,Zebra Cup,Northfield,,,\n"],
)
def test_rejects_empty_fields(tmp_path: Path, row: str) -> None:
    _rejects(tmp_path, row)


@pytest.mark.parametrize("name", ["Zebra <Cup>", "Zebra Cup>"])
def test_rejects_angle_brackets(tmp_path: Path, name: str) -> None:
    _rejects(tmp_path, f"a,{name},Northfield,Lakeview,,\n")


@pytest.mark.parametrize(
    "rid", ["cfp-national-championship", "cfp-semifinal", "cfp-quarterfinal", "cfp-first-round"]
)
def test_rejects_reserved_id(tmp_path: Path, rid: str) -> None:
    text = _rejects(tmp_path, f"{rid},Zebra Cup,Northfield,Lakeview,,\n")
    assert rid not in text


def test_rejects_non_integer_season(tmp_path: Path) -> None:
    _rejects(tmp_path, "a,Zebra Cup,Northfield,Lakeview,abc,\n")


def test_rejects_season_order(tmp_path: Path) -> None:
    _rejects(tmp_path, "a,Zebra Cup,Northfield,Lakeview,2012,2005\n")


def test_rejects_formula_cell(tmp_path: Path) -> None:
    with pytest.raises(ReferenceTableError):
        load_rivalries(_write(tmp_path, "a,=Zebra,Northfield,Lakeview,,\n"))
