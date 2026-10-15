"""Relay gap list and the D-14 Ratings Reference windows on synthetic data."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
from mlb_pipeline_support import make_reference, make_vault, write_relay

from booth_review.config import DataPaths
from booth_review.mlb.gaps import (
    RELAY_GAPS_PATH,
    gap_counts_by_network,
    relay_gaps,
    rr_windows,
    write_relay_gaps,
)
from booth_review.mlb.pipeline import assemble_mlb_tables


def _games(*rows: tuple[int, date, str]) -> pl.DataFrame:
    return pl.DataFrame(
        [{"season": s, "game_date": d, "round": r} for s, d, r in rows],
        schema={"season": pl.Int32, "game_date": pl.Date, "round": pl.String},
    )


def test_relay_gaps_lists_own_production_2026_telecasts_with_no_crew(
    git_vault: DataPaths, tmp_path: Path
) -> None:
    paths = git_vault
    make_vault(paths)
    ref = make_reference(tmp_path / "ref")

    asm, _ = assemble_mlb_tables(paths, ref, [2025, 2026])
    rows = relay_gaps(asm.telecasts, asm.crews)

    # The unstarred FOX listing has no crew; Apple has one; the starred MLBN* is a simulcast.
    assert [(r["network_id"], r["game_date"]) for r in rows] == [("fox_net", "2026-06-07")]
    assert gap_counts_by_network(rows) == {"fox_net": 1}
    rel = write_relay_gaps(paths, rows)
    assert rel == RELAY_GAPS_PATH
    text = (paths.vault / rel).read_text(encoding="utf-8").splitlines()
    assert text[0] == "game_key,network_id,game_date"
    assert len(text) == 2


def test_relay_gaps_skips_a_game_the_relay_filled(git_vault: DataPaths, tmp_path: Path) -> None:
    paths = git_vault
    make_vault(paths)
    ref = make_reference(tmp_path / "ref")
    write_relay(
        paths,
        "2026,2026-06-07,Bravo Town,Alpha City,0,fox_net,Cy Fixture,Bo Fixture,,"
        "https://example.invalid/post,,,2026-06-08",
    )

    asm, _ = assemble_mlb_tables(paths, ref, [2026])

    assert relay_gaps(asm.telecasts, asm.crews) == []


def test_relay_gaps_empty_frames() -> None:
    assert relay_gaps(pl.DataFrame(), pl.DataFrame()) == []


def test_windows_are_postseason_margins_and_the_2026_season() -> None:
    games = _games(
        (2019, date(2019, 10, 1), "wild_card"),
        (2019, date(2019, 10, 10), "division"),
        (2019, date(2019, 10, 30), "world_series"),
        (2019, date(2019, 6, 1), "regular"),
        (2026, date(2026, 4, 1), "regular"),
        (2026, date(2026, 9, 27), "regular"),
    )

    windows = rr_windows(games)

    assert windows == [
        (date(2019, 9, 30), date(2019, 10, 31)),
        (date(2026, 4, 1), date(2026, 12, 31)),
    ]


def test_windows_2026_postseason_starts_at_its_first_round_listing() -> None:
    games = _games(
        (2026, date(2026, 4, 1), "regular"),
        (2026, date(2026, 9, 27), "regular"),
        (2026, date(2026, 10, 6), "wild_card"),
    )

    assert rr_windows(games) == [
        (date(2026, 4, 1), date(2026, 9, 27)),
        (date(2026, 10, 6), date(2026, 12, 31)),
    ]


def test_windows_2026_without_a_round_listing_run_from_the_day_after_the_regular_season() -> None:
    games = _games((2026, date(2026, 4, 1), "regular"), (2026, date(2026, 9, 27), "regular"))

    # The two windows are adjacent days, so they merge.
    assert rr_windows(games) == [(date(2026, 4, 1), date(2026, 12, 31))]


def test_windows_overlapping_postseason_margins_merge() -> None:
    games = _games(
        (2018, date(2018, 10, 2), "wild_card"),
        (2018, date(2018, 10, 28), "world_series"),
        (2019, date(2019, 10, 1), "wild_card"),
    )

    windows = rr_windows(games)

    assert windows == [
        (date(2018, 10, 1), date(2018, 10, 29)),
        (date(2019, 9, 30), date(2019, 10, 2)),
    ]


def test_windows_no_regular_season_before_2026() -> None:
    games = _games(
        (2022, date(2022, 4, 7), "regular"),
        (2022, date(2022, 9, 20), "regular"),
        (2022, date(2022, 10, 7), "wild_card"),
        (2022, date(2022, 11, 5), "world_series"),
        (2026, date(2026, 5, 1), "regular"),
    )

    windows = rr_windows(games)

    for day in (date(2022, 4, 7), date(2022, 9, 20), date(2022, 10, 4)):
        assert not any(a <= day <= b for a, b in windows), day
    assert any(a <= date(2022, 10, 7) <= b for a, b in windows)


def test_windows_empty_game_table() -> None:
    assert rr_windows(_games()) == []
