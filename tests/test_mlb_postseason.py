"""Postseason booths table (SPORT-07) on synthetic seasons."""

from __future__ import annotations

import math
from datetime import date

import polars as pl

from booth_review.mlb.constants import CREW_COVERAGE_BAR
from booth_review.mlb.crews import booth_key
from booth_review.mlb.games import GAME_SCHEMA
from booth_review.mlb.listings import game_key, telecast_frame
from booth_review.mlb.postseason import (
    POSTSEASON_SEASONS_TABLE,
    POSTSEASON_TABLE,
    build_postseason_booths,
)
from booth_review.mlb.rr_match import RRGameMatch

# (season, round, league, day, pbp or None, network, production, crew_source)
SPEC = [
    (2014, "wild_card", "AL", date(2014, 10, 1), "p1", "neta", "own", "wikipedia"),
    (2019, "division", "AL", date(2019, 10, 4), "p1", "neta", "own", "wikipedia"),
    (2019, "division", "AL", date(2019, 10, 5), "p1", "neta", "own", "506"),
    (2019, "division", "NL", date(2019, 10, 4), None, "netb", "own", None),
    (2019, "world_series", None, date(2019, 10, 22), "p2", "netc", "own", "wikipedia"),
    (2019, "world_series", None, date(2019, 10, 23), "p2", "netc", "own", "wikipedia"),
    (2019, "world_series", None, date(2019, 10, 23), None, "netb", "simulcast", None),
    (2025, "lcs", "AL", date(2025, 10, 12), "p3", "neta", "own", "506"),
    (2025, "lcs", "AL", date(2025, 10, 13), "p4", "neta", "own", "506"),
    (2026, "division", "AL", date(2026, 10, 5), "p5", "neta", "own", "506"),
    (2026, "division", "AL", date(2026, 10, 6), "p5", "neta", "own", "506"),
]


def _key(row) -> str:
    return game_key(row[3], "alpha", f"home{row[3].day}{row[2] or 'x'}", 0)


def build(spec=SPEC):
    tele, game_rows, extra = [], [], []
    for row in spec:
        season, round_id, league, day, pbp, network, production, source = row
        key = _key(row)
        tele.append(
            {
                "game_key": key,
                "season": season,
                "game_date": day,
                "away_club": "alpha",
                "home_club": "bravo",
                "game_number": 0,
                "network_id": network,
                "family": network,
                "starred": False,
                "is_exclusive": None,
                "production": production,
                "window": None,
                "local_outlet": None,
                "crew_names": [],
                "local_simulcast": False,
                "source": "map",
                "source_label": "",
                "round": round_id,
                "series_game": 1,
                "neutral": False,
                "venue_note": None,
                "date_shift": False,
            }
        )
        game_rows.append(
            {
                "game_key": key,
                "season": season,
                "game_date": day,
                "away_club": "alpha",
                "home_club": "bravo",
                "game_number": 0,
                "round": round_id,
                "series_league": league,
                "series_game": 1,
                "neutral": False,
                "venue_note": None,
                "retrosheet_gid": None,
                "home_won": None,
                "away_score": None,
                "home_score": None,
            }
        )
        extra.append((pbp, source, network, season))
    # a 2014 postseason game with no telecast at all
    game_rows.append({**game_rows[0], "game_key": "2014-10-02|alpha|zulu|0"})
    crews = telecast_frame(tele).with_columns(
        pl.Series("pbp_person_id", [e[0] for e in extra], dtype=pl.String),
        pl.Series(
            "analyst_person_ids", [["a"] if e[0] else [] for e in extra], dtype=pl.List(pl.String)
        ),
        pl.Series("crew_source", [e[1] for e in extra], dtype=pl.String),
        pl.Series("crew_named", [e[0] is not None for e in extra], dtype=pl.Boolean),
        pl.Series("booth_key", [booth_key(e[2], e[3], e[0]) for e in extra], dtype=pl.String),
    )
    return pl.DataFrame(game_rows, schema=dict(GAME_SCHEMA)), crews


def match(key, cause, viewers):
    return RRGameMatch(
        key,
        cause,
        None,
        (),
        None,
        (),
        (),
        viewers,
        "per-game",
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
    )


def exc_frame(entries):
    return pl.DataFrame(
        {"game_key": [k for k, _ in entries], "wp_excitement": [v for _, v in entries]},
        schema={"game_key": pl.String, "wp_excitement": pl.Float64},
    )


def run(rr=(), excitement=None):
    games, crews = build()
    if excitement is None:
        excitement = exc_frame([])
    return build_postseason_booths(games, crews, excitement, list(rr))


def test_table_names() -> None:
    assert POSTSEASON_TABLE == "mlb_postseason_booths"
    assert POSTSEASON_SEASONS_TABLE == "mlb_postseason_seasons"


def test_one_row_per_season_round_league() -> None:
    cells, _, _, _ = run()
    keys = list(zip(cells["season"], cells["round"], cells["league"], strict=True))
    assert keys == [
        (2014, "wild_card", "AL"),
        (2019, "division", "AL"),
        (2019, "division", "NL"),
        (2019, "world_series", None),
        (2025, "lcs", "AL"),
        (2026, "division", "AL"),
    ]
    assert "tiebreak" not in cells["round"].to_list()


def test_booths_games_and_crew_listed() -> None:
    cells, _, _, _ = run()
    al = cells.filter((pl.col("season") == 2019) & (pl.col("league") == "AL")).row(0, named=True)
    assert al["games"] == 2 and al["crew_listed"] == 2
    assert [b["pbp_person_id"] for b in al["booths"]] == ["p1"]
    assert al["booths"][0]["games"] == 2
    assert al["network_id"] == "neta"
    lcs = cells.filter(pl.col("season") == 2025).row(0, named=True)
    assert sorted(b["pbp_person_id"] for b in lcs["booths"]) == ["p3", "p4"]
    ws = cells.filter(pl.col("round") == "world_series").row(0, named=True)
    # the simulcast row is excluded from every count
    assert ws["games"] == 2 and ws["coverage_den"] == 2
    nl = cells.filter((pl.col("season") == 2019) & (pl.col("league") == "NL")).row(0, named=True)
    assert nl["booths"] == [] and nl["coverage_num"] == 0 and nl["coverage_den"] == 1


def test_excitement_null_until_retrosheet_and_filled_after() -> None:
    cells, _, _, _ = run()
    assert cells["mean_excitement"].null_count() == cells.height
    assert set(cells["excitement_n"]) == {0}
    _, crews = build()
    keys = crews.filter((pl.col("season") == 2019) & (pl.col("round") == "division"))[
        "game_key"
    ].to_list()
    out, _, _, _ = run(excitement=exc_frame([(keys[0], 2.0), (keys[1], 4.0)]))
    row = out.filter((pl.col("season") == 2019) & (pl.col("league") == "AL")).row(0, named=True)
    assert row["excitement_n"] == 2 and math.isclose(row["mean_excitement"], 3.0)


def test_viewers_use_clean_figures_only() -> None:
    _, crews = build()
    ws = crews.filter(pl.col("round") == "world_series")["game_key"].to_list()
    rr = [match(ws[0], None, 10.0e6), match(ws[1], "conflict", None)]
    cells, _, _, _ = run(rr)
    row = cells.filter(pl.col("round") == "world_series").row(0, named=True)
    assert row["viewers_n"] == 1 and math.isclose(row["viewers_mean"], 10.0e6)


def test_season_coverage_keeps_seasons_below_the_bar() -> None:
    _, seasons, reviews, _ = run()
    by = {r["season"]: r for r in seasons.iter_rows(named=True)}
    # 2014: one named crew, one extra game with no telecast in the games table
    assert (by[2014]["coverage_num"], by[2014]["coverage_den"]) == (1, 2)
    assert by[2014]["below_bar"] and math.isclose(by[2014]["coverage_pct"], 0.5)
    # 2019: 4 of 5 own games named; the simulcast row is not a game of ours
    assert (by[2019]["coverage_num"], by[2019]["coverage_den"]) == (4, 5)
    assert by[2025]["coverage_pct"] == 1.0 and not by[2025]["below_bar"]
    assert CREW_COVERAGE_BAR > 4 / 5
    assert sorted(r.pointer for r in reviews) == ["2014", "2019"]


def test_tiebreak_row_only_when_a_tiebreak_game_exists() -> None:
    spec = [*SPEC, (2018, "tiebreak", None, date(2018, 10, 1), "p6", "neta", "own", "wikipedia")]
    games, crews = build(spec)
    cells, _, _, _ = build_postseason_booths(games, crews, exc_frame([]), [])
    assert cells.filter(pl.col("round") == "tiebreak").height == 1


def test_wikipedia_crewed_booth_counts_as_listed() -> None:
    cells, _, _, _ = run()
    ws = cells.filter(pl.col("round") == "world_series").row(0, named=True)
    assert ws["crew_listed"] == ws["games"] == 2
    wc = cells.filter(pl.col("season") == 2014).row(0, named=True)
    assert wc["crew_listed"] == wc["games"] == 1


def test_booth_analyst_is_the_most_frequent_not_the_first_game() -> None:
    games, crews = build()
    ws = crews["round"].to_list()
    idx = [i for i, r in enumerate(ws) if r == "world_series"][:2]
    analysts = crews["analyst_person_ids"].to_list()
    analysts[idx[0]] = ["one_off"]
    analysts[idx[1]] = ["regular"]
    # 2019 AL division booth: three games, first one-off, then the regular twice
    crews = crews.with_columns(pl.Series("analyst_person_ids", analysts, dtype=pl.List(pl.String)))
    cells, _, _, _ = build_postseason_booths(games, crews, exc_frame([]), [])
    ws_row = cells.filter(pl.col("round") == "world_series").row(0, named=True)
    # tie (1 each): the earliest game's analyst wins
    assert ws_row["booths"][0]["analyst_person_ids"] == ["one_off"]
    analysts[idx[0]] = ["regular"]
    analysts[idx[1]] = ["regular"]
    crews2 = crews.with_columns(pl.Series("analyst_person_ids", analysts, dtype=pl.List(pl.String)))
    cells2, _, _, _ = build_postseason_booths(games, crews2, exc_frame([]), [])
    ws2 = cells2.filter(pl.col("round") == "world_series").row(0, named=True)
    assert ws2["booths"][0]["analyst_person_ids"] == ["regular"]
