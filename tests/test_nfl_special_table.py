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


def test_international_other_is_exclusive() -> None:
    rows = [
        game(
            "a",
            2015,
            1,
            "h",
            "v",
            is_international=True,
            is_standalone=True,
            slot_name="International",
            is_special=True,
        ),
        game("b", 2015, 2, "h", "v", is_international=True),
        game("c", 2015, 3, "h", "v", is_agotw=True, is_special=True),
    ]
    home = row_for(special_games_table(table(rows)), "h", 2015)
    assert home["international"] == 2
    assert home["international_other"] == 1
    assert home["special"] == 2
    assert home["standalone_total"] + home["agotw"] + home["cbs_national"] == home["special"]


def test_international_other_with_agotw_and_cbs_excluded() -> None:
    rows = [
        game("a", 2015, 1, "h", "v", is_international=True, is_agotw=True, is_special=True),
        game("b", 2015, 2, "h", "w", is_international=True, is_cbs_national=True, is_special=True),
        game("c", 2015, 3, "x", "v", is_international=True, is_special=False),
    ]
    out = special_games_table(table(rows))
    assert out.columns == list(NFL_SPECIAL_COLUMNS)
    for r in out.to_dicts():
        assert r["international_other"] <= r["international"]
        assert r["standalone_total"] + r["agotw"] + r["cbs_national"] == r["special"]
    assert row_for(out, "h", 2015)["international_other"] == 0
    assert row_for(out, "x", 2015)["international_other"] == 1


def test_solo_columns_are_exclusive_and_sum_to_standalone_total() -> None:
    slots = [
        ("TNF", True),
        ("SNF", True),
        ("MNF", True),
        ("Thanksgiving", True),
        ("Christmas", True),
        ("Saturday", True),
        ("International", True),
    ]
    rows = [
        game(f"s{i}", 2015, i + 1, "h", "v", is_standalone=True, slot_name=slot, is_special=True)
        for i, (slot, _) in enumerate(slots)
    ]
    home = row_for(special_games_table(table(rows)), "h", 2015)
    assert home["solo_thursday"] == 1
    assert home["solo_sunday"] == 1
    assert home["solo_monday"] == 1
    assert home["solo_holiday"] == 2
    assert home["solo_other"] == 2
    solo = sum(home[f"solo_{k}"] for k in ("thursday", "sunday", "monday", "holiday", "other"))
    assert solo == home["standalone_total"] == 7


def test_monday_doubleheader_game_adds_nothing_to_solo_monday() -> None:
    rows = [game("a", 2015, 1, "h", "v", is_standalone=False, slot_name="MNF")]
    home = row_for(special_games_table(table(rows)), "h", 2015)
    assert home["solo_monday"] == 0 and home["standalone_total"] == 0


def test_standalone_international_is_solo_other_not_international_other() -> None:
    rows = [
        game(
            "a",
            2015,
            1,
            "h",
            "v",
            is_international=True,
            is_standalone=True,
            slot_name="International",
            is_special=True,
        )
    ]
    home = row_for(special_games_table(table(rows)), "h", 2015)
    assert home["solo_other"] == 1
    assert home["international"] == 1
    assert home["international_other"] == 0
