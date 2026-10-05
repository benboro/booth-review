"""Loader validation for the curated rivalries table (D-12/D-13).

Team and rivalry names below are invented.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from booth_review.build.rivalries import RIVALRY_COLUMNS, Rivalry, load_rivalries
from booth_review.contract.models import GAME_SLUG_PATTERN, RESERVED_GAME_SLUGS
from booth_review.errors import ReferenceTableError
from booth_review.reference import SLUG_PATTERN
from booth_review.transport.cache import atomic_write_bytes

HEADER = "rivalry_id,name,article,team_a,team_b,season_from,season_to\n"


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
        "article",
        "team_a",
        "team_b",
        "season_from",
        "season_to",
    )


def test_valid_rows_load_in_order(tmp_path: Path) -> None:
    ref = _write(
        tmp_path,
        "zebra-cup,Zebra Cup,the,Northfield,Lakeview,,\n"
        'ridge-run,"Ridge, Run",,Lakeview,Hilltop,2005,2012\n',
    )
    assert load_rivalries(ref) == [
        Rivalry("zebra-cup", "Zebra Cup", "the", "Northfield", "Lakeview", None, None),
        Rivalry("ridge-run", "Ridge, Run", None, "Lakeview", "Hilltop", 2005, 2012),
    ]


def test_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_rivalries(tmp_path) == []


def test_wrong_header_raises(tmp_path: Path) -> None:
    atomic_write_bytes(tmp_path / "rivalries.csv", b"a,b\n1,2\n")
    with pytest.raises(ReferenceTableError):
        load_rivalries(tmp_path)


def test_rejects_bad_id(tmp_path: Path) -> None:
    _rejects(tmp_path, "Zebra_Cup,Zebra Cup,,Northfield,Lakeview,,\n", leaked=("Zebra_Cup",))


def test_rejects_duplicate_id(tmp_path: Path) -> None:
    _rejects(
        tmp_path,
        "zc,Zebra Cup,,Northfield,Lakeview,,\nzc,Other Cup,,Northfield,Hilltop,,\n",
        line=3,
    )


def test_rejects_duplicate_name_case_insensitive(tmp_path: Path) -> None:
    _rejects(
        tmp_path,
        "a,Zebra Cup,,Northfield,Lakeview,,\nb,ZEBRA cup,,Northfield,Hilltop,,\n",
        line=3,
    )


def test_rejects_repeated_unordered_pair(tmp_path: Path) -> None:
    _rejects(
        tmp_path,
        "a,Zebra Cup,,Northfield,Lakeview,,\nb,Other Cup,,Lakeview,Northfield,,\n",
        line=3,
    )


def test_rejects_identical_teams(tmp_path: Path) -> None:
    _rejects(tmp_path, "a,Zebra Cup,,Northfield,Northfield,,\n")


@pytest.mark.parametrize(
    "row",
    ["a,,,Northfield,Lakeview,,\n", "a,Zebra Cup,,,Lakeview,,\n", "a,Zebra Cup,,Northfield,,,\n"],
)
def test_rejects_empty_fields(tmp_path: Path, row: str) -> None:
    _rejects(tmp_path, row)


@pytest.mark.parametrize("name", ["Zebra <Cup>", "Zebra Cup>"])
def test_rejects_angle_brackets(tmp_path: Path, name: str) -> None:
    _rejects(tmp_path, f"a,{name},,Northfield,Lakeview,,\n")


@pytest.mark.parametrize("rid", sorted(RESERVED_GAME_SLUGS))
def test_rejects_reserved_id(tmp_path: Path, rid: str) -> None:
    text = _rejects(tmp_path, f"{rid},Zebra Cup,,Northfield,Lakeview,,\n")
    assert rid not in text


def test_rejects_non_integer_season(tmp_path: Path) -> None:
    _rejects(tmp_path, "a,Zebra Cup,,Northfield,Lakeview,abc,\n")


def test_rejects_season_order(tmp_path: Path) -> None:
    _rejects(tmp_path, "a,Zebra Cup,,Northfield,Lakeview,2012,2005\n")


def test_rejects_formula_cell(tmp_path: Path) -> None:
    with pytest.raises(ReferenceTableError):
        load_rivalries(_write(tmp_path, "a,=Zebra,,Northfield,Lakeview,,\n"))


@pytest.mark.parametrize("article", ["The", "a", "an", "THE"])
def test_rejects_unknown_article(tmp_path: Path, article: str) -> None:
    _rejects(tmp_path, f"a,Zebra Cup,{article},Northfield,Lakeview,,\n")


def test_rejects_article_before_a_the_name(tmp_path: Path) -> None:
    _rejects(tmp_path, "a,The Zebra Cup,the,Northfield,Lakeview,,\n")


def test_the_name_with_empty_article_loads(tmp_path: Path) -> None:
    (row,) = load_rivalries(_write(tmp_path, "a,The Zebra Cup,,Northfield,Lakeview,,\n"))
    assert row.article is None


def test_slug_pattern_copies_agree() -> None:
    assert SLUG_PATTERN.pattern == GAME_SLUG_PATTERN


def test_reserved_slugs_match_client_cfp_defs() -> None:
    js = Path(__file__).resolve().parents[1] / "site" / "modules" / "format.js"
    text = js.read_text(encoding="utf-8")
    block = text[text.index("export const CFP_GAME_DEFS") :]
    block = block[: block.index("]);")]
    slugs = re.findall(r"slug: '([a-z0-9-]+)'", block)
    assert len(slugs) == 4
    assert set(slugs) == RESERVED_GAME_SLUGS
