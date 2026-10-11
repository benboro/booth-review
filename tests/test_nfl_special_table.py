"""Task 2 special-games table on synthetic game frames."""

from __future__ import annotations

from datetime import date

import polars as pl

from booth_review.nfl.games import NFL_GAME_COLUMNS, NFL_GAME_SCHEMA, NflGameTable
from booth_review.nfl.tables import NFL_SPECIAL_COLUMNS, special_games_table


def game(game_id: str, season: int, week: int, home: str, away: str, **over: object) -> dict:
    base: dict[str, object] = dict.fromkeys(NFL_GAME_COLUMNS)
    base.update(
        season=season,
        week=week,
        game_type="REG",
        game_id=game_id,
        game_date=date(season, 9, 1),
        home_franchise_id=home,
        away_franchise_id=away,
        home_display_name=f"{home} {season}",
        away_display_name=f"{away} {season}",
        is_standalone=False,
        slot_name="Sunday early",
        fox_dh_sunday=False,
        cbs_dh_sunday=False,
        is_agotw=False,
        is_cbs_national=False,
        flexed=False,
        is_special=False,
        rr_network_ids=[],
        crew_names=[],
        sideline_person_ids=[],
        alt_cast_broadcasts=[],
        late_national_status="not_dh",
    )
    base.update(over)
    return base


def table(rows: list[dict], through: dict[int, int | None] | None = None) -> NflGameTable:
    frame = pl.DataFrame(rows, schema=NFL_GAME_SCHEMA, orient="row").select(NFL_GAME_COLUMNS)
    return NflGameTable(frame, {}, {}, through or {})


def row_for(df: pl.DataFrame, fid: str, season: int) -> dict:
    return df.filter((pl.col("franchise_id") == fid) & (pl.col("season") == season)).to_dicts()[0]


def test_counts_both_sides_and_special_once() -> None:
    rows = [
        game(
            "a",
            2015,
            1,
            "h",
            "v",
            is_standalone=True,
            slot_name="SNF",
            is_agotw=True,
            is_special=True,
        ),
        game("b", 2015, 2, "h", "w"),
    ]
    out = special_games_table(table(rows, {2015: 2}))
    assert out.columns == list(NFL_SPECIAL_COLUMNS)
    home = row_for(out, "h", 2015)
    away = row_for(out, "v", 2015)
    assert home["games"] == 2 and away["games"] == 1
    assert home["standalone_total"] == 1 and home["standalone_snf"] == 1
    assert home["agotw"] == 1 and home["special"] == 1
    assert away["special"] == 1 and home["through_week"] == 2


def test_relocation_rolls_up_by_franchise_id() -> None:
    rows = [game("a", 2016, 1, "g", "x"), game("b", 2017, 1, "g", "x")]
    out = special_games_table(table(rows, {2016: 1, 2017: 1}))
    assert out.filter(pl.col("franchise_id") == "g").height == 2
    assert row_for(out, "g", 2016)["display_name"] == "g 2016"
    assert row_for(out, "g", 2017)["display_name"] == "g 2017"
    assert out.filter(pl.col("franchise_id") == "g")["games"].sum() == 2


def test_rates_use_doubleheader_weeks_minus_ambiguous_and_null_on_zero() -> None:
    rows = [
        game(
            "a",
            2015,
            1,
            "h",
            "v",
            fox_dh_sunday=True,
            network_id="fox",
            late_national_status="settled",
            is_agotw=True,
        ),
        game(
            "b",
            2015,
            2,
            "h",
            "v",
            fox_dh_sunday=True,
            network_id="fox",
            late_national_status="ambiguous",
        ),
        game(
            "c",
            2015,
            3,
            "h",
            "v",
            fox_dh_sunday=True,
            network_id="fox",
            late_national_status="settled",
        ),
        game(
            "d",
            2015,
            4,
            "h",
            "v",
            cbs_dh_sunday=True,
            network_id="cbs",
            late_national_status="ambiguous",
        ),
    ]
    out = special_games_table(table(rows, {2015: 4}))
    home = row_for(out, "h", 2015)
    assert home["fox_doubleheader_weeks"] == 3 and home["fox_ambiguous_weeks"] == 1
    assert home["agotw_rate"] == 0.5
    assert home["cbs_doubleheader_weeks"] == 1 and home["cbs_ambiguous_weeks"] == 1
    assert home["cbs_national_rate"] is None


def test_international_and_flexed_counts() -> None:
    rows = [
        game("a", 2015, 1, "h", "v", is_international=True, flexed=True),
        game("b", 2015, 2, "h", "v", is_international=None),
    ]
    home = row_for(special_games_table(table(rows)), "h", 2015)
    assert home["international"] == 1 and home["flexed"] == 1


def test_empty_frame_gives_empty_table() -> None:
    out = special_games_table(table([]))
    assert out.height == 0 and out.columns == list(NFL_SPECIAL_COLUMNS)
