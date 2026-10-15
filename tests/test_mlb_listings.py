"""506 MLB listings to telecast rows, and the MLB input loader (synthetic only)."""

from __future__ import annotations

from pathlib import Path

import polars as pl
from mlb_games_support import build_reference, bundle_zip, gameinfo_row, page_html

from booth_review.config import DataPaths
from booth_review.mlb.inputs import Review, load_mlb_inputs
from booth_review.mlb.layout import mlb_506_path, retrosheet_asset_path
from booth_review.mlb.listings import PRODUCTION_RULES, game_key, listings_to_telecasts
from booth_review.sources.sports506.mlb_parser import parse_mlb_page

DAY = "Friday, June 05"


def _telecasts(
    tmp_path: Path, entries: list[tuple[str, str, str, str, str]], label: str = "3"
) -> tuple[pl.DataFrame, list[Review]]:
    ref = build_reference(tmp_path / "ref")
    page = parse_mlb_page(page_html(entries), season=2026, label=label)
    return listings_to_telecasts(page.listings, ref, page.non_game)


def _kinds(reviews: list[Review]) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in reviews:
        out[item.kind] = out.get(item.kind, 0) + item.count
    return out


def test_own_production_with_crew_and_key(tmp_path: Path) -> None:
    frame, reviews = _telecasts(
        tmp_path, [(DAY, "Alpha City @ Bravo Town", "7:00 PM ET", "Apple TV+", "Pat Ex, Sam Ca")]
    )
    row = frame.row(0, named=True)
    assert row["game_key"] == game_key(row["game_date"], "alpha", "bravo", 0)
    assert str(row["game_date"]) == "2026-06-05"
    assert (row["network_id"], row["family"]) == ("apple", "apple")
    assert row["production"] == "own"
    assert row["is_exclusive"] is None  # never guessed
    assert row["crew_names"] == ["Pat Ex", "Sam Ca"]
    assert row["source"] == "506"
    assert reviews == []


def test_starred_without_crew_is_simulcast_not_exclusive(tmp_path: Path) -> None:
    frame, _ = _telecasts(tmp_path, [(DAY, "Alpha City @ Bravo Town", "7:10 PM ET", "MLBN*", "")])
    row = frame.row(0, named=True)
    assert row["starred"] is True
    assert row["production"] == "simulcast"
    assert row["is_exclusive"] is False
    assert row["crew_names"] == []


def test_starred_with_crew_is_showcase_own(tmp_path: Path) -> None:
    frame, _ = _telecasts(
        tmp_path, [(DAY, "Alpha City @ Bravo Town", "7:10 PM ET", "MLBN*", "Pat Ex, Sam Ca")]
    )
    row = frame.row(0, named=True)
    assert (row["production"], row["is_exclusive"]) == ("own", False)


def test_local_simulcast_cell_has_no_crew(tmp_path: Path) -> None:
    frame, _ = _telecasts(
        tmp_path,
        [(DAY, "Alpha City @ Bravo Town", "7:10 PM ET", "ESPN Unltd*", "(local simulcast)")],
    )
    row = frame.row(0, named=True)
    assert row["local_simulcast"] is True
    assert row["crew_names"] == []
    assert row["production"] == "simulcast"


def test_two_outlets_one_row_each_and_not_exclusive(tmp_path: Path) -> None:
    frame, _ = _telecasts(
        tmp_path, [(DAY, "Alpha City @ Bravo Town", "7:15 PM ET", "MLBN* ESPN Unltd*", "")]
    )
    assert sorted(frame["network_id"].to_list()) == ["espn_unltd", "mlbn"]
    assert frame["is_exclusive"].to_list() == [False, False]


def test_window_and_regional_tail(tmp_path: Path) -> None:
    frame, _ = _telecasts(
        tmp_path,
        [
            (DAY, "Alpha City @ Bravo Town", "4:00 PM ET", "FOX (red circle on map)", "A B, C D"),
            (DAY, "Charlie Chargers @ Delta Bay", "7:05 PM ET", "TBS / NESN", "E F, G H"),
        ],
    )
    fox = frame.filter(pl.col("network_id") == "fox_net").row(0, named=True)
    assert fox["window"] == "red"
    tbs = frame.filter(pl.col("network_id") == "tbs").row(0, named=True)
    assert tbs["local_outlet"] == "NESN"
    assert tbs["is_exclusive"] is False


def test_doubleheader_numbers_keep_games_apart(tmp_path: Path) -> None:
    frame, _ = _telecasts(
        tmp_path,
        [
            (DAY, "Alpha City @ Bravo Town (Game 1)", "1:00 PM ET", "TBS", "A B, C D"),
            (DAY, "Alpha City @ Bravo Town (Game 2)", "6:00 PM ET", "TBS", "A B, C D"),
        ],
    )
    assert sorted(frame["game_number"].to_list()) == [1, 2]
    assert frame["game_key"].n_unique() == 2


def test_not_played_and_non_game_rows_are_counted(tmp_path: Path) -> None:
    frame, reviews = _telecasts(
        tmp_path,
        [
            (DAY, "Alpha City @ Bravo Town (rained out)", "7:05 PM ET", "FOX", ""),
            (DAY, "All-Star Game", "8:00 PM ET", "FOX", "A B"),
            (DAY, "Home Run Derby", "8:00 PM ET", "FOX", "A B"),
        ],
    )
    assert frame.is_empty()
    kinds = _kinds(reviews)
    assert kinds == {"not_played": 1, "non_game_all_star": 1, "non_game_home_run_derby": 1}


def test_unresolved_club_and_network_go_to_reviews_only(tmp_path: Path) -> None:
    frame, reviews = _telecasts(
        tmp_path,
        [
            (DAY, "Nowhere Nine @ Bravo Town", "7:00 PM ET", "FOX", "A B"),
            (DAY, "Alpha City @ Bravo Town", "7:00 PM ET", "Mystery Net", "A B"),
        ],
    )
    assert frame.is_empty()
    assert _kinds(reviews) == {"unresolved_club": 1, "unresolved_network": 1}


def test_round_label_sets_round_and_series_game(tmp_path: Path) -> None:
    frame, _ = _telecasts(
        tmp_path,
        [("Saturday, October 24", "Game 2: Alpha City @ Bravo Town", "8:08 PM ET", "FOX", "A B")],
        label="WS",
    )
    row = frame.row(0, named=True)
    assert (row["round"], row["series_game"]) == ("world_series", 2)


def test_duplicate_listing_is_merged_and_counted(tmp_path: Path) -> None:
    ref = build_reference(tmp_path / "ref")
    one = parse_mlb_page(
        page_html([(DAY, "Alpha City @ Bravo Town", "7:00 PM ET", "FOX", "")]),
        season=2026,
        label="3",
    )
    two = parse_mlb_page(
        page_html([(DAY, "Alpha City @ Bravo Town", "7:00 PM ET", "FOX", "A B, C D")]),
        season=2026,
        label="4",
    )
    frame, reviews = listings_to_telecasts([*one.listings, *two.listings], ref)
    assert frame.height == 1
    assert frame["crew_names"].to_list() == [["A B", "C D"]]
    assert _kinds(reviews) == {"duplicate_listing": 1}


def test_production_rules_cover_every_combination() -> None:
    assert len(PRODUCTION_RULES) == 8
    assert set(PRODUCTION_RULES.values()) == {"own", "simulcast"}


def test_loader_reads_only_mlb_and_tolerates_missing_sources(tmp_path: Path) -> None:
    paths = DataPaths(vault=tmp_path / "vault")
    empty = load_mlb_inputs(paths, [2025, 2026])
    assert empty.pages == {}
    assert empty.gameinfo.is_empty()
    assert empty.wikipedia == {} and empty.relay_rows == ()

    raw = paths.raw
    page = raw / mlb_506_path(2026, "3")
    page.parent.mkdir(parents=True)
    page.write_bytes(page_html([(DAY, "Alpha City @ Bravo Town", "7:00 PM ET", "FOX", "A B")]))
    bad = raw / mlb_506_path(2026, "4")
    bad.write_bytes(b"<html><body>nothing</body></html>")
    (raw / "cfb" / "x").mkdir(parents=True)
    (raw / "cfb" / "x" / "wk-01.html").write_bytes(b"not read")
    bundle = raw / retrosheet_asset_path("2025csvs.zip")
    bundle.parent.mkdir(parents=True)
    bundle.write_bytes(
        bundle_zip(
            [gameinfo_row("XBB2025100", "XAA", "XBB", "20251001", "wildcard", season=2025)], 2025
        )
    )
    loaded = load_mlb_inputs(paths, [2025, 2026])
    assert list(loaded.pages) == [(2026, "3")]
    assert loaded.page_parse_failures == 1
    assert loaded.gameinfo.height == 1
    assert loaded.gameinfo["round"].to_list() == ["wild_card"]
    assert set(loaded.retrosheet_zips) == {2025}
    assert not loaded.allplayers.is_empty()
