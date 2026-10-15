"""Starting lineups from synthetic Retrosheet plays and allplayers."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import polars as pl
import pytest

from booth_review.mlb.lineups import LINEUP_COLUMNS, LineupReview, starting_lineups
from booth_review.sources.retrosheet import loader

FIXTURES = Path(__file__).parent / "fixtures" / "mlb" / "retrosheet"


def make_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for kind in ("gameinfo", "plays", "allplayers"):
            archive.writestr(f"2020{kind}.csv", (FIXTURES / f"{kind}_synthetic.csv").read_bytes())
    return buffer.getvalue()


@pytest.fixture(scope="module")
def result() -> tuple[pl.DataFrame, list[LineupReview]]:
    bundle = make_zip()
    return starting_lineups(loader.read_plays(bundle, 2020), loader.read_allplayers(bundle))


def _side(frame: pl.DataFrame, gid: str, side: str) -> pl.DataFrame:
    return frame.filter((pl.col("gid") == gid) & (pl.col("side") == side)).sort("slot")


def test_ten_rows_per_side_for_complete_game(
    result: tuple[pl.DataFrame, list[LineupReview]],
) -> None:
    frame, _ = result
    assert tuple(frame.columns) == LINEUP_COLUMNS
    for side in ("away", "home"):
        assert _side(frame, "XBB202004010", side)["slot"].to_list() == list(range(10))


def test_starting_nine_in_slot_order_and_pitchers(
    result: tuple[pl.DataFrame, list[LineupReview]],
) -> None:
    frame, _ = result
    away = _side(frame, "XBB202004010", "away")
    assert away["player_id"].to_list()[1:] == [f"abat{i:02d}" for i in range(1, 10)]
    # away starter pitched while the home side batted
    assert away["player_id"][0] == "apit01"
    assert _side(frame, "XBB202004010", "home")["player_id"][0] == "hpit01"
    # the later relief pitcher never replaces the starter
    assert "hpit02" not in frame["player_id"].to_list()


def test_names_and_positions(result: tuple[pl.DataFrame, list[LineupReview]]) -> None:
    frame, _ = result
    away = _side(frame, "XBB202004010", "away")
    assert away["name"][0] == "Ann Pitcha1"
    assert away["name"][1] == "Firsta1 Lasta1"
    assert away["position"][0] == 1
    assert away["position"].to_list()[1:] == [2, 3, 4, 5, 6, 7, 8, 9, 10]


def test_pinch_first_appearance_flags_uncertain(
    result: tuple[pl.DataFrame, list[LineupReview]],
) -> None:
    frame, _ = result
    away = _side(frame, "XBB202004020", "away")
    flagged = away.filter(pl.col("starter_uncertain"))
    assert flagged["slot"].to_list() == [4]
    assert flagged["position"].to_list() == [None]
    assert not _side(frame, "XBB202004010", "away")["starter_uncertain"].any()


def test_unresolved_player_keeps_id_and_reviews_without_name(
    result: tuple[pl.DataFrame, list[LineupReview]],
) -> None:
    frame, reviews = result
    home = _side(frame, "XBB202004020", "home")
    row = home.filter(pl.col("slot") == 6)
    assert row["player_id"][0] == "zzghost01"
    assert row["name"][0] is None
    unresolved = [r for r in reviews if r.reason == "unresolved_player"]
    assert unresolved == [LineupReview("XBB202004020", "home", 6, "unresolved_player", "zzghost01")]


def test_incomplete_game_yields_no_rows_and_review(
    result: tuple[pl.DataFrame, list[LineupReview]],
) -> None:
    frame, reviews = result
    assert frame.filter(pl.col("gid") == "XBB202004021").is_empty()
    incomplete = [r for r in reviews if r.reason == "incomplete_lineup"]
    assert {(r.gid, r.side) for r in incomplete} == {
        ("XBB202004021", "away"),
        ("XBB202004021", "home"),
    }


def test_empty_plays_returns_empty_frame() -> None:
    plays = loader.read_plays(make_zip(), 2020).clear()
    frame, reviews = starting_lineups(plays, loader.read_allplayers(make_zip()))
    assert frame.is_empty()
    assert reviews == []
    assert tuple(frame.columns) == LINEUP_COLUMNS
