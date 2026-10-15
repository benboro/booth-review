"""Win-expectancy table and per-game excitement on hand-built synthetic games."""

from __future__ import annotations

from itertools import pairwise

import polars as pl
import pytest
from booth_review.mlb.winexp import (
    WeTable,
    build_we_table,
    excitement_by_game,
    game_excitement,
    state_keys,
)

from booth_review.mlb.constants import MIN_WE_PLAYS, WE_MAX_DIFF, WE_PRIOR_K

# (inning, top_bot, score_v, score_h, outs, br1, br2, br3)
Play = tuple[int, int, int, int, int, str | None, str | None, str | None]

KEY = ["inning", "regime", "half", "outs", "bases", "diff"]


def plays_frame(games: dict[str, list[Play]]) -> pl.DataFrame:
    rows = []
    for gid, plays in games.items():
        for seq, (inning, half, sv, sh, outs, b1, b2, b3) in enumerate(plays):
            rows.append(
                {
                    "gid": gid,
                    "seq": seq,
                    "inning": inning,
                    "top_bot": half,
                    "score_v": sv,
                    "score_h": sh,
                    "outs_pre": outs,
                    "br1_pre": b1,
                    "br2_pre": b2,
                    "br3_pre": b3,
                }
            )
    return pl.DataFrame(
        rows,
        schema={
            "gid": pl.String,
            "seq": pl.Int64,
            "inning": pl.Int32,
            "top_bot": pl.Int8,
            "score_v": pl.Int32,
            "score_h": pl.Int32,
            "outs_pre": pl.Int8,
            "br1_pre": pl.String,
            "br2_pre": pl.String,
            "br3_pre": pl.String,
        },
    )


def info_frame(rows: list[dict[str, object]]) -> pl.DataFrame:
    base: dict[str, object] = {
        "season": 2018,
        "round": "regular",
        "innings": 9,
        "vruns": 2,
        "hruns": 3,
        "forfeit": None,
    }
    full = [{**base, **row} for row in rows]
    return pl.DataFrame(
        full,
        schema={
            "gid": pl.String,
            "season": pl.Int32,
            "round": pl.String,
            "innings": pl.Int32,
            "vruns": pl.Int32,
            "hruns": pl.Int32,
            "forfeit": pl.String,
        },
    )


def one_play_games(
    count: int, home_wins: int, play: Play, prefix: str, **info: object
) -> tuple[dict[str, list[Play]], list[dict[str, object]]]:
    games: dict[str, list[Play]] = {}
    rows: list[dict[str, object]] = []
    for index in range(count):
        gid = f"{prefix}{index:04d}"
        games[gid] = [play]
        won = index < home_wins
        rows.append({"gid": gid, "vruns": 1 if won else 3, "hruns": 3 if won else 1, **info})
    return games, rows


def merge(
    *parts: tuple[dict[str, list[Play]], list[dict[str, object]]],
) -> tuple[pl.DataFrame, pl.DataFrame]:
    games: dict[str, list[Play]] = {}
    rows: list[dict[str, object]] = []
    for g, r in parts:
        games.update(g)
        rows.extend(r)
    return plays_frame(games), info_frame(rows)


def state_p(table: WeTable, **where: object) -> float:
    found = table.states.filter(
        [pl.col(name) == value for name, value in where.items()]  # type: ignore[arg-type]
    )
    assert found.height == 1
    return float(found["p"][0])


# -- state keys ---------------------------------------------------------------------------------


def test_state_keys_bases_diff_and_half() -> None:
    plays = plays_frame(
        {
            "G1": [
                (1, 0, 0, 0, 0, None, None, None),
                (3, 1, 2, 5, 1, "r1", None, "r3"),
                (4, 0, 0, 30, 2, "r1", "r2", "r3"),
            ]
        }
    )
    keys = state_keys(plays, info_frame([{"gid": "G1"}])).sort("seq")
    assert keys["bases"].to_list() == [0, 5, 7]
    assert keys["diff"].to_list() == [0, 3, WE_MAX_DIFF]
    assert keys["half"].to_list() == [0, 1, 0]
    assert keys["outs"].to_list() == [0, 1, 2]


def test_state_keys_treat_empty_runner_text_as_empty_base() -> None:
    plays = plays_frame({"G1": [(1, 0, 0, 0, 0, "", "r2", "")]})
    assert state_keys(plays, info_frame([{"gid": "G1"}]))["bases"].to_list() == [2]


def test_extra_innings_pool_and_split_by_regime() -> None:
    plays = plays_frame(
        {
            "REG22": [(9, 0, 0, 0, 0, None, None, None), (11, 0, 0, 0, 0, None, "r2", None)],
            "REG18": [(12, 0, 0, 0, 0, None, "r2", None)],
            "POST22": [(10, 0, 0, 0, 0, None, "r2", None)],
        }
    )
    info = info_frame(
        [
            {"gid": "REG22", "season": 2022},
            {"gid": "REG18", "season": 2018},
            {"gid": "POST22", "season": 2022, "round": "division"},
        ]
    )
    keys = state_keys(plays, info)
    got = {(r["gid"], r["seq"]): (r["inning"], r["regime"]) for r in keys.iter_rows(named=True)}
    assert got[("REG22", 0)] == (9, "standard")
    assert got[("REG22", 1)] == (10, "ghost_runner")
    assert got[("REG18", 0)] == (10, "standard")
    assert got[("POST22", 0)] == (10, "standard")


# -- table --------------------------------------------------------------------------------------

P_OUT0: Play = (1, 0, 0, 0, 0, None, None, None)
P_OUT1: Play = (1, 0, 0, 0, 1, None, None, None)
P_OUT2: Play = (1, 0, 0, 0, 2, None, None, None)


def test_training_filter_keeps_regular_nine_inning_games_in_the_window() -> None:
    parts = [
        one_play_games(4, 2, P_OUT0, "A"),  # kept
        one_play_games(3, 1, P_OUT0, "B", round="division"),  # postseason
        one_play_games(3, 1, P_OUT0, "C", innings=7),  # seven-inning game
        one_play_games(3, 1, P_OUT0, "D", season=2012),  # before the window
        one_play_games(2, 1, P_OUT0, "E", innings=None),  # blank = nine
        one_play_games(2, 1, P_OUT0, "F", forfeit="V"),  # forfeit
    ]
    plays, info = merge(*parts)
    table = build_we_table(plays, info, min_train_games=1)
    assert int(table.states["n"].sum()) == 6  # A and E only


def test_build_fails_below_the_training_minimum() -> None:
    plays, info = merge(one_play_games(4, 2, P_OUT0, "A"))
    with pytest.raises(ValueError, match="training games"):
        build_we_table(plays, info, min_train_games=5)


def test_state_probability_is_shrunk_toward_the_coarse_table() -> None:
    plays, info = merge(
        one_play_games(10, 10, P_OUT0, "A"),
        one_play_games(10, 0, P_OUT1, "B"),
    )
    table = build_we_table(plays, info, min_train_games=1)
    # coarse (inning 1, top, diff 0): n=20, wins=10, home rate 0.5 -> 0.5
    assert state_p(table, outs=0) == pytest.approx((10 + WE_PRIOR_K * 0.5) / (10 + WE_PRIOR_K))
    assert state_p(table, outs=1) == pytest.approx((0 + WE_PRIOR_K * 0.5) / (10 + WE_PRIOR_K))
    assert table.states["n"].sort().to_list() == [10, 10]
    assert table.states["home_wins"].sort().to_list() == [0, 10]


def test_sparse_state_sits_closer_to_coarse_than_to_its_raw_frequency() -> None:
    plays, info = merge(
        one_play_games(10, 10, P_OUT0, "A"),
        one_play_games(10, 0, P_OUT1, "B"),
        one_play_games(1, 1, P_OUT2, "C"),
    )
    table = build_we_table(plays, info, min_train_games=1)
    coarse = float(table.coarse["p"][0])
    p = state_p(table, outs=2)
    assert p == pytest.approx((1 + WE_PRIOR_K * coarse) / (1 + WE_PRIOR_K))
    assert abs(p - coarse) < abs(p - 1.0)


def test_probabilities_stay_in_bounds() -> None:
    plays, info = merge(
        one_play_games(10, 10, P_OUT0, "A"),
        one_play_games(10, 0, P_OUT1, "B"),
        one_play_games(1, 0, P_OUT2, "C"),
    )
    table = build_we_table(plays, info, min_train_games=1)
    for frame in (table.states, table.coarse):
        assert frame["p"].min() >= 0.0  # type: ignore[operator]
        assert frame["p"].max() <= 1.0  # type: ignore[operator]
    assert 0.0 <= table.home_rate <= 1.0


def _monotone_training() -> tuple[pl.DataFrame, pl.DataFrame]:
    def at(diff: int) -> Play:
        return (
            (5, 0, 0, max(diff, 0), 0, None, None, None)
            if diff >= 0
            else (5, 0, -diff, 0, 0, None, None, None)
        )

    return merge(
        one_play_games(40, 40, at(-1), "A"),  # trailing, always wins
        one_play_games(40, 0, at(0), "B"),  # tied, always loses
        one_play_games(40, 20, at(1), "C"),
    )


def _violations(table: WeTable) -> int:
    count = 0
    group = ["inning", "regime", "half", "outs", "bases"]
    for _key, part in table.states.sort(*group, "diff").group_by(group, maintain_order=True):
        values = part["p"].to_list()
        count += sum(1 for a, b in pairwise(values) if b < a - 1e-12)
    return count


def test_probability_is_nondecreasing_in_the_lead_after_pooling() -> None:
    plays, info = _monotone_training()
    raw = build_we_table(plays, info, min_train_games=1, enforce_monotone=False)
    fixed = build_we_table(plays, info, min_train_games=1)
    assert _violations(raw) > 0  # the data really is out of order
    assert _violations(fixed) == 0
    assert fixed.states["n"].sum() == raw.states["n"].sum()


def test_symmetric_training_gives_mirrored_probabilities() -> None:
    plus: Play = (5, 0, 0, 2, 0, None, None, None)
    minus: Play = (5, 0, 2, 0, 0, None, None, None)
    plays, info = merge(one_play_games(100, 80, plus, "A"), one_play_games(100, 20, minus, "B"))
    table = build_we_table(plays, info, min_train_games=1)
    total = state_p(table, diff=2) + state_p(table, diff=-2)
    assert abs(total - 1.0) < 0.05


def test_table_build_is_deterministic() -> None:
    plays, info = _monotone_training()
    first = build_we_table(plays, info, min_train_games=1)
    second = build_we_table(plays, info, min_train_games=1)
    assert first.states.equals(second.states)
    assert first.coarse.equals(second.coarse)


# -- excitement ---------------------------------------------------------------------------------


def test_game_excitement_sums_changes_including_the_final_step() -> None:
    probs = [0.5, 0.6, 0.4]
    assert game_excitement(probs, True, min_plays=3) == pytest.approx(0.1 + 0.2 + 0.6, abs=1e-12)
    assert game_excitement(probs, False, min_plays=3) == pytest.approx(0.1 + 0.2 + 0.4, abs=1e-12)


def test_game_excitement_is_null_not_zero_when_unscorable() -> None:
    assert game_excitement([0.5, 0.6], True, min_plays=3) is None
    assert game_excitement([0.5, 0.6, 0.4], None, min_plays=3) is None
    assert game_excitement([0.5, 0.6, 0.4], True, min_plays=3, forfeit=True) is None
    assert game_excitement([0.5] * (MIN_WE_PLAYS - 1), True) is None
    assert game_excitement([0.5] * MIN_WE_PLAYS, True) is not None


def _fixed_table() -> WeTable:
    states = pl.DataFrame(
        {
            "inning": [1, 1, 1],
            "regime": ["standard"] * 3,
            "half": [0, 0, 0],
            "outs": [0, 1, 2],
            "bases": [0, 0, 0],
            "diff": [0, 0, 0],
            "n": [10, 10, 10],
            "home_wins": [5, 6, 4],
            "p": [0.5, 0.6, 0.4],
        }
    )
    coarse = pl.DataFrame(
        {
            "inning": [1],
            "regime": ["standard"],
            "half": [0],
            "diff": [0],
            "n": [30],
            "home_wins": [15],
            "p": [0.55],
        }
    )
    return WeTable(states=states, coarse=coarse, home_rate=0.52)


def test_excitement_by_game_follows_play_order_not_row_order() -> None:
    ordered = plays_frame({"G1": [P_OUT0, P_OUT1, P_OUT2]})
    shuffled = ordered.sort("seq", descending=True)
    info = info_frame([{"gid": "G1", "vruns": 1, "hruns": 3}])
    got = excitement_by_game(shuffled, info, _fixed_table(), min_plays=3)
    assert got.columns == ["gid", "wp_excitement", "n_plays"]
    assert got.height == 1
    assert got["wp_excitement"][0] == pytest.approx(0.9, abs=1e-12)
    assert got["n_plays"][0] == 3


def test_excitement_by_game_is_null_for_short_forfeit_and_undecided_games() -> None:
    plays = plays_frame(
        {
            "SHORT": [P_OUT0, P_OUT1],
            "FORF": [P_OUT0, P_OUT1, P_OUT2],
            "TIED": [P_OUT0, P_OUT1, P_OUT2],
            "OK": [P_OUT0, P_OUT1, P_OUT2],
        }
    )
    info = info_frame(
        [
            {"gid": "SHORT"},
            {"gid": "FORF", "forfeit": "H"},
            {"gid": "TIED", "vruns": 2, "hruns": 2},
            {"gid": "OK"},
        ]
    )
    got = excitement_by_game(plays, info, _fixed_table(), min_plays=3).sort("gid")
    by_gid = dict(got.select("gid", "wp_excitement").iter_rows())
    assert by_gid["OK"] == pytest.approx(0.9, abs=1e-12)
    assert by_gid["SHORT"] is None and by_gid["FORF"] is None and by_gid["TIED"] is None
    assert dict(got.select("gid", "n_plays").iter_rows())["SHORT"] == 2


def test_unseen_states_fall_back_to_coarse_then_the_home_rate() -> None:
    table = _fixed_table()
    plays = plays_frame(
        {
            "G1": [
                (1, 0, 0, 0, 0, "r1", None, None),  # unseen bases: coarse 0.55
                (2, 0, 0, 0, 0, None, None, None),  # unseen inning: home rate 0.52
            ]
        }
    )
    info = info_frame([{"gid": "G1", "vruns": 1, "hruns": 3}])
    got = excitement_by_game(plays, info, table, min_plays=2)
    assert got["wp_excitement"][0] == pytest.approx(abs(0.52 - 0.55) + abs(1.0 - 0.52), abs=1e-12)
