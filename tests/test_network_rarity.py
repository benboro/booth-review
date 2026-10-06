"""network_rarity.csv loader and cross-check (04.13 D-11)."""

from __future__ import annotations

from pathlib import Path

import pytest

from booth_review.errors import ReferenceTableError
from booth_review.resolve.networks import (
    check_network_rarity,
    load_network_rarity,
    load_networks,
)

FIXTURES = Path(__file__).parent / "fixtures" / "reference"


def _write(tmp_path: Path, *rows: str) -> Path:
    (tmp_path / "network_rarity.csv").write_text(
        "network_id,rarely_rated\n" + "".join(r + "\n" for r in rows), encoding="utf-8"
    )
    return tmp_path


def test_fixture_loads_one_entry_per_network() -> None:
    rarity = load_network_rarity(FIXTURES)
    table = load_networks(FIXTURES)
    assert set(rarity) == set(table.networks())
    assert rarity["net-c"] is True
    assert rarity["net-d"] is True
    assert rarity["net-a"] is False
    check_network_rarity(rarity, table)


@pytest.mark.parametrize("value", ["yes", "TRUE", "", "1"])
def test_bad_value_cites_the_line(tmp_path: Path, value: str) -> None:
    d = _write(tmp_path, "net-a,false", f"net-b,{value}")
    with pytest.raises(ReferenceTableError, match=r"network_rarity\.csv: line 3:"):
        load_network_rarity(d)


def test_bad_id_cites_the_line(tmp_path: Path) -> None:
    d = _write(tmp_path, "Bad Id,true")
    with pytest.raises(ReferenceTableError, match=r"line 2: invalid network_id"):
        load_network_rarity(d)


def test_duplicate_is_rejected(tmp_path: Path) -> None:
    d = _write(tmp_path, "net-a,true", "net-a,false")
    with pytest.raises(ReferenceTableError, match=r"line 3: duplicate network_id"):
        load_network_rarity(d)


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ReferenceTableError):
        load_network_rarity(tmp_path)


def test_check_flags_unknown_id() -> None:
    rarity = load_network_rarity(FIXTURES)
    rarity["net-zzz"] = True
    with pytest.raises(
        ReferenceTableError, match=r"1 network_id\(s\) not in networks.csv: net-zzz"
    ):
        check_network_rarity(rarity, load_networks(FIXTURES))


def test_check_flags_missing_row() -> None:
    rarity = load_network_rarity(FIXTURES)
    del rarity["net-g"]
    with pytest.raises(
        ReferenceTableError, match=r"1 networks.csv network_id\(s\) have no row: net-g"
    ):
        check_network_rarity(rarity, load_networks(FIXTURES))
