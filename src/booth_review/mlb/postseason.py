"""SPORT-07: postseason booth assignment by season, round and league, 2014-2026.

`build_postseason_booths` is a pure function. One cell row per season x round x league
(league is null for the World Series; tiebreak rows appear only when a tiebreak game
exists) holds the outlet, the booth or booths, game and crew counts, coverage, the mean
Retrosheet win-expectancy excitement with its n, and the mean Ratings Reference viewers
with its n. No stakes (D-08). A second frame holds the per-season crew coverage with its
percentage; a season below `CREW_COVERAGE_BAR` still appears (D-12), and games without a
crew count in the denominator. Viewership and every count use own-production telecasts
only (D-18). Excitement is null for 2026 until Retrosheet 2026 is collected.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

import polars as pl

from booth_review.mlb.constants import CREW_COVERAGE_BAR
from booth_review.mlb.inputs import Review
from booth_review.mlb.rr_match import RRGameMatch

__all__ = ["POSTSEASON_SEASONS_TABLE", "POSTSEASON_TABLE", "build_postseason_booths"]

POSTSEASON_TABLE: Final = "mlb_postseason_booths"
POSTSEASON_SEASONS_TABLE: Final = "mlb_postseason_seasons"

FIRST_SEASON: Final = 2014
LAST_SEASON: Final = 2026
_ROUND_ORDER: Final = ("tiebreak", "wild_card", "division", "lcs", "world_series")
_NON_POSTSEASON: Final = frozenset({"regular", "allstar"})

_BOOTH_STRUCT: Final = pl.Struct(
    {
        "booth_key": pl.String,
        "pbp_person_id": pl.String,
        "analyst_person_ids": pl.List(pl.String),
        "games": pl.Int64,
    }
)
_CELL_SCHEMA: Final[dict[str, pl.DataType | type[pl.DataType]]] = {
    "season": pl.Int32,
    "round": pl.String,
    "league": pl.String,
    "network_id": pl.String,
    "network_ids": pl.List(pl.String),
    "booths": pl.List(_BOOTH_STRUCT),
    "games": pl.Int64,
    "crew_listed": pl.Int64,
    "coverage_num": pl.Int64,
    "coverage_den": pl.Int64,
    "mean_excitement": pl.Float64,
    "excitement_n": pl.Int64,
    "viewers_mean": pl.Float64,
    "viewers_n": pl.Int64,
    "game_list": pl.List(pl.String),
}
_SEASON_SCHEMA: Final[dict[str, pl.DataType | type[pl.DataType]]] = {
    "season": pl.Int32,
    "coverage_num": pl.Int64,
    "coverage_den": pl.Int64,
    "coverage_pct": pl.Float64,
    "below_bar": pl.Boolean,
}


def _round_rank(round_id: str) -> int:
    return _ROUND_ORDER.index(round_id) if round_id in _ROUND_ORDER else len(_ROUND_ORDER)


def build_postseason_booths(
    games: pl.DataFrame,
    crews: pl.DataFrame,
    excitement: pl.DataFrame,
    rr: Sequence[RRGameMatch],
) -> tuple[pl.DataFrame, pl.DataFrame, list[Review], dict[str, int]]:
    """(cells_frame, seasons_frame, reviews, counts) for postseasons 2014-2026.

    `games` is the game table (round, series_league); `crews` the telecast frame after
    `assign_crews`; `excitement` has game_key and wp_excitement; `rr` the Ratings
    Reference matches (only figures with no cause count toward viewers).
    """
    league_of = {
        str(k): lg
        for k, lg in games.select("game_key", "series_league").iter_rows()
        if lg is not None
    }
    exc_by = (
        {
            str(k): float(v)
            for k, v in excitement.select("game_key", "wp_excitement").iter_rows()
            if v is not None
        }
        if not excitement.is_empty()
        else {}
    )
    viewers_by = {m.game_key: m.viewers for m in rr if m.cause is None and m.viewers is not None}

    post = crews.filter(
        pl.col("round").is_not_null()
        & ~pl.col("round").is_in(list(_NON_POSTSEASON))
        & (pl.col("production") == "own")
        & pl.col("season").is_between(FIRST_SEASON, LAST_SEASON)
    )
    cells: dict[tuple[int, str, str | None], list[dict[str, object]]] = {}
    for row in post.sort("game_date", "game_key", maintain_order=True).iter_rows(named=True):
        round_id = str(row["round"])
        league = None if round_id == "world_series" else league_of.get(str(row["game_key"]))
        cells.setdefault((int(row["season"]), round_id, league), []).append(row)

    out: list[dict[str, object]] = []
    for (season, round_id, league), rows in sorted(
        cells.items(), key=lambda kv: (kv[0][0], _round_rank(kv[0][1]), kv[0][2] or "")
    ):
        by_game: dict[str, dict[str, object]] = {}
        for r in rows:
            by_game.setdefault(str(r["game_key"]), r)
        keys = list(by_game)
        net_counts: dict[str, int] = {}
        for r in by_game.values():
            net_counts[str(r["network_id"])] = net_counts.get(str(r["network_id"]), 0) + 1
        networks = sorted(net_counts, key=lambda n: (-net_counts[n], n))
        booth_games: dict[str, dict[str, object]] = {}
        for r in by_game.values():
            bk = r["booth_key"]
            if bk is None:
                continue
            entry = booth_games.setdefault(
                str(bk),
                {
                    "booth_key": str(bk),
                    "pbp_person_id": r["pbp_person_id"],
                    "analyst_person_ids": r["analyst_person_ids"] or [],
                    "games": 0,
                },
            )
            entry["games"] = int(str(entry["games"])) + 1
        booths = sorted(
            booth_games.values(), key=lambda b: (-int(str(b["games"])), str(b["booth_key"]))
        )
        exc_vals = [exc_by[k] for k in keys if k in exc_by]
        view_vals = [float(viewers_by[k]) for k in keys if viewers_by.get(k) is not None]
        out.append(
            {
                "season": season,
                "round": round_id,
                "league": league,
                "network_id": networks[0],
                "network_ids": networks,
                "booths": booths,
                "games": len(keys),
                "crew_listed": sum(1 for r in by_game.values() if r["crew_source"] == "506"),
                "coverage_num": sum(1 for r in by_game.values() if r["crew_named"]),
                "coverage_den": len(keys),
                "mean_excitement": sum(exc_vals) / len(exc_vals) if exc_vals else None,
                "excitement_n": len(exc_vals),
                "viewers_mean": sum(view_vals) / len(view_vals) if view_vals else None,
                "viewers_n": len(view_vals),
                "game_list": keys,
            }
        )
    cells_frame = pl.DataFrame(out, schema=_CELL_SCHEMA)

    # Season coverage: every postseason game counts in the denominator, crew or not.
    den: dict[int, set[str]] = {}
    num: dict[int, set[str]] = {}
    for r in games.filter(
        pl.col("round").is_not_null()
        & ~pl.col("round").is_in(list(_NON_POSTSEASON))
        & pl.col("season").is_between(FIRST_SEASON, LAST_SEASON)
    ).iter_rows(named=True):
        den.setdefault(int(str(r["season"])), set()).add(str(r["game_key"]))
    for r in post.iter_rows(named=True):
        s = int(str(r["season"]))
        den.setdefault(s, set()).add(str(r["game_key"]))
        if r["crew_named"]:
            num.setdefault(s, set()).add(str(r["game_key"]))
    reviews: list[Review] = []
    season_rows: list[dict[str, object]] = []
    for s in sorted(den):
        n, d = len(num.get(s, set())), len(den[s])
        pct = n / d if d else None
        below = pct is not None and pct < CREW_COVERAGE_BAR
        if below:
            reviews.append(Review("postseason", "coverage_below_bar", 1, str(s)))
        season_rows.append(
            {
                "season": s,
                "coverage_num": n,
                "coverage_den": d,
                "coverage_pct": pct,
                "below_bar": below,
            }
        )
    seasons_frame = pl.DataFrame(season_rows, schema=_SEASON_SCHEMA)
    counts = {
        "cells": cells_frame.height,
        "seasons": seasons_frame.height,
        "games": sum(len(v) for v in den.values()),
    }
    return cells_frame, seasons_frame, reviews, counts
