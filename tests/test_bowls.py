"""Loader validation for the public bowl-name crosswalk (D-17/D-18).

Names below are invented; no real bowl, sponsor, or vault text appears here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from booth_review.build.bowls import BOWL_COLUMNS, BowlEntry, load_bowls
from booth_review.errors import ReferenceTableError
from booth_review.transport.cache import atomic_write_bytes

HEADER = "cfbd_game_id,official_name,core_name,at_bowl,franchise\n"
REPO_ROOT = Path(__file__).resolve().parents[1]


def _write(tmp_path: Path, body: str) -> Path:
    atomic_write_bytes(tmp_path / "bowls.csv", (HEADER + body).encode("utf-8"))
    return tmp_path


def test_columns_constant() -> None:
    assert BOWL_COLUMNS == (
        "cfbd_game_id",
        "official_name",
        "core_name",
        "at_bowl",
        "franchise",
    )


def test_valid_rows_load(tmp_path: Path) -> None:
    ref = _write(
        tmp_path,
        "1,Acme Harbor Bowl,Harbor Bowl,true,harbor-bowl\n2,,,true,\n3,,,false,\n",
    )
    result = load_bowls(ref)
    assert result[1] == BowlEntry("Acme Harbor Bowl", "Harbor Bowl", True, "harbor-bowl")
    assert result[2] == BowlEntry(None, None, True)
    assert result[3] == BowlEntry(None, None, False)


def test_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_bowls(tmp_path) == {}


def test_real_table_loads() -> None:
    load_bowls(REPO_ROOT / "data" / "reference")


def test_rejects_non_integer_id(tmp_path: Path) -> None:
    with pytest.raises(ReferenceTableError, match=r"bowls\.csv: line 2"):
        load_bowls(_write(tmp_path, "abc,,,true,\n"))


def test_rejects_duplicate_id(tmp_path: Path) -> None:
    with pytest.raises(ReferenceTableError, match=r"line 3"):
        load_bowls(_write(tmp_path, "1,,,true,\n1,,,true,\n"))


def test_rejects_bad_at_bowl(tmp_path: Path) -> None:
    with pytest.raises(ReferenceTableError, match=r"line 2"):
        load_bowls(_write(tmp_path, "1,,,yes,\n"))


def test_rejects_core_not_substring(tmp_path: Path) -> None:
    with pytest.raises(ReferenceTableError) as exc:
        load_bowls(_write(tmp_path, "1,Acme Harbor Bowl,harbor bowl,true,harbor-bowl\n"))
    assert "bowls.csv" in str(exc.value)
    assert "line 2" in str(exc.value)
    assert "Harbor" not in str(exc.value)
    assert "harbor" not in str(exc.value)


def test_rejects_official_without_core(tmp_path: Path) -> None:
    with pytest.raises(ReferenceTableError) as exc:
        load_bowls(_write(tmp_path, "1,Acme Harbor Bowl,,true,\n"))
    assert "Harbor" not in str(exc.value)


def test_rejects_core_without_official(tmp_path: Path) -> None:
    with pytest.raises(ReferenceTableError) as exc:
        load_bowls(_write(tmp_path, "1,,Harbor Bowl,true,harbor-bowl\n"))
    assert "Harbor" not in str(exc.value)


def test_rejects_names_on_non_bowl_row(tmp_path: Path) -> None:
    with pytest.raises(ReferenceTableError) as exc:
        load_bowls(_write(tmp_path, "1,Acme Harbor Bowl,Harbor Bowl,false,\n"))
    assert "Harbor" not in str(exc.value)


def test_rejects_formula_cell(tmp_path: Path) -> None:
    with pytest.raises(ReferenceTableError):
        load_bowls(_write(tmp_path, "1,=cmd,cmd,true,cmd\n"))


def test_rejects_named_row_without_franchise(tmp_path: Path) -> None:
    with pytest.raises(ReferenceTableError) as exc:
        load_bowls(_write(tmp_path, "1,Acme Harbor Bowl,Harbor Bowl,true,\n"))
    assert "line 2" in str(exc.value)
    assert "franchise must be set" in str(exc.value)
    assert "Harbor" not in str(exc.value)


def test_rejects_franchise_on_unnamed_row(tmp_path: Path) -> None:
    with pytest.raises(ReferenceTableError) as exc:
        load_bowls(_write(tmp_path, "1,,,true,harbor-bowl\n"))
    assert "franchise must be empty" in str(exc.value)
    assert "harbor" not in str(exc.value)


@pytest.mark.parametrize("slug", ["Harbor_Bowl", "harbor--bowl", "-harbor", "harbor bowl"])
def test_rejects_non_kebab_franchise(tmp_path: Path, slug: str) -> None:
    body = f"1,Acme Harbor Bowl,Harbor Bowl,true,{slug}\n"
    if slug.startswith("-"):
        body = f'1,Acme Harbor Bowl,Harbor Bowl,true,"{slug}"\n'
    with pytest.raises(ReferenceTableError) as exc:
        load_bowls(_write(tmp_path, body))
    assert "line 2" in str(exc.value)
    assert slug not in str(exc.value)
