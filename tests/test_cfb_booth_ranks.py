"""Loader tests for data/reference/cfb_booth_ranks.csv (Phase 10, BOOTH-01); synthetic ids only."""

from __future__ import annotations

from pathlib import Path

import pytest

from booth_review.build.booth_ranks import (
    CFB_BOOTH_RANK_COLUMNS,
    load_cfb_booth_ranks,
)
from booth_review.errors import ReferenceTableError

_URL = "https://example.com/lineup"
_HEADER = ",".join(CFB_BOOTH_RANK_COLUMNS)

_PEOPLE = """person_id,canonical_name,variants,usual_role,role_override
ana-fixture,Ana Fixture,Ana Fixture,pbp,
bo-fixture,Bo Fixture,Bo Fixture,analyst,
cy-fixture,Cy Fixture,Cy Fixture,pbp,
di-fixture,Di Fixture,Di Fixture,analyst,
ed-fixture,Ed Fixture,Ed Fixture,pbp,
"""

_NETWORKS = """variant,network_id,display_name,family,tier,feed_type,season_from,season_to,priority
Fixture Main,fixture-main,Fixture Main,disney,broadcast,main,,,
Fixture Conf,fixture-conf,Fixture Conf,disney,conference,main,,,
Fixture Fox Conf,fixture-fox-conf,Fixture Fox Conf,fox,conference,main,,,
"""


@pytest.fixture
def ref(tmp_path: Path) -> Path:
    (tmp_path / "people.csv").write_text(_PEOPLE, encoding="utf-8")
    (tmp_path / "networks.csv").write_text(_NETWORKS, encoding="utf-8")
    return tmp_path


def _ranks(ref: Path, *rows: str) -> None:
    (ref / "cfb_booth_ranks.csv").write_text("\n".join([_HEADER, *rows]) + "\n", encoding="utf-8")


def _row(
    rank: str = "1",
    pbp: str = "Ana Fixture",
    analyst: str = "Bo Fixture",
    *,
    family: str = "disney",
    season: str = "2026",
    scope: str = "",
    url: str = _URL,
) -> str:
    return f"{family},{season},{rank},{pbp},{analyst},{scope},{url}"


def test_load_orders_ranked_then_scope(ref: Path) -> None:
    _ranks(
        ref,
        _row("", "Ed Fixture", "Ana Fixture", scope="fixture-conf"),
        _row("3", "Di Fixture", "Cy Fixture"),
        _row("2", "Cy Fixture", "Di Fixture"),
        _row("1"),
    )
    rows = load_cfb_booth_ranks(ref)[("disney", 2026)]
    assert len(rows) == 4
    assert [r.rank for r in rows] == [1, 2, 3, None]
    assert rows[0].pbp_person_id == "ana-fixture"
    assert rows[0].analyst_person_id == "bo-fixture"
    assert rows[3].scope_network_id == "fixture-conf"


def test_missing_file_is_empty(ref: Path) -> None:
    assert load_cfb_booth_ranks(ref) == {}


def test_header_only_is_empty(ref: Path) -> None:
    _ranks(ref)
    assert load_cfb_booth_ranks(ref) == {}


_REJECTIONS: list[list[str]] = [
    [_row(family="cw")],
    [_row(season="2013")],
    [_row(season="2027")],
    [_row(season="x")],
    [_row("0")],
    [_row("")],
    [_row("1"), _row("1", "Cy Fixture", "Di Fixture")],
    [_row("1"), _row("2")],  # same pbp twice
    [_row("1"), _row("3", "Cy Fixture", "Di Fixture")],
    [_row("2")],
    [_row("", "Cy Fixture", "Di Fixture", scope="fixture-conf")],
    [_row("1"), _row("", "Cy Fixture", "Di Fixture", scope="nope")],
    [_row("1"), _row("", "Cy Fixture", "Di Fixture", scope="fixture-main")],
    [_row("1"), _row("", "Cy Fixture", "Di Fixture", scope="fixture-fox-conf")],
    [_row("1", scope="fixture-conf")],
    [
        _row("1"),
        _row("", "Cy Fixture", "Di Fixture", scope="fixture-conf"),
        _row("", "Di Fixture", "Cy Fixture", scope="fixture-conf"),
    ],
    [_row(url="http://example.com/x")],
    [_row(url="")],
    [_row(pbp="Zed Nobody")],
    [_row(analyst="Zed Nobody")],
]


@pytest.mark.parametrize("rows", _REJECTIONS)
def test_rejections(ref: Path, rows: list[str]) -> None:
    _ranks(ref, *rows)
    with pytest.raises(ReferenceTableError) as exc:
        load_cfb_booth_ranks(ref)
    assert "line" in str(exc.value)


def test_unresolved_name_hides_name(ref: Path) -> None:
    _ranks(ref, _row(pbp="Zed Nobody"))
    with pytest.raises(ReferenceTableError) as exc:
        load_cfb_booth_ranks(ref)
    assert "line 2" in str(exc.value)
    assert "Nobody" not in str(exc.value)
