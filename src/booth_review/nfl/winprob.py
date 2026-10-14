"""GEI-style excitement and win-probability volatility from nflfastR pbp.

GEI-style (Benz Game Excitement Index); comparable in kind to, not identical
with, CFBD's unpublished excitementIndex (D-22). wp_volatility is a separate
measure. A missing value stays null and is never filled with 0 (D-05).
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping
from itertools import pairwise
from pathlib import Path

import polars as pl

from booth_review.errors import ParseError

PBP_COLUMNS: tuple[str, ...] = (
    "game_id",
    "play_id",
    "qtr",
    "quarter_seconds_remaining",
    "home_wp",
    "home_wp_post",
)

#: Low-data cut: fewer valid win-probability plays than this gives null metrics.
MIN_WP_PLAYS = 20

REGULATION_SECONDS = 3600
#: Regular-season overtime is 10 minutes from 2017; every other OT period is 15.
OT_PERIOD_REG_FROM_2017 = 600
OT_PERIOD_DEFAULT = 900
_OT_REG_FIRST_SEASON = 2017


def read_pbp_wp(path: Path) -> pl.DataFrame:
    """Read only PBP_COLUMNS from a pbp parquet; ParseError names a missing column."""
    lazy = pl.scan_parquet(path)
    names = lazy.collect_schema().names()
    for column in PBP_COLUMNS:
        if column not in names:
            raise ParseError(f"nfl pbp: missing column {column}")
    return lazy.select(PBP_COLUMNS).collect()


def _ot_period(season: int, game_type: str) -> int:
    if game_type == "REG" and season >= _OT_REG_FIRST_SEASON:
        return OT_PERIOD_REG_FROM_2017
    return OT_PERIOD_DEFAULT


def _game_seconds(last_qtr: int | None, last_qsr: float | None, period: int) -> float:
    """Elapsed game time t, including overtime actually played."""
    if last_qtr is None or last_qtr < 5 or last_qsr is None:
        return float(REGULATION_SECONDS)
    completed = (last_qtr - 5) * period
    return float(REGULATION_SECONDS + completed + (period - last_qsr))


def game_wp_metrics(
    plays: pl.DataFrame,
    *,
    season_by_game: Mapping[str, int],
    game_type_by_game: Mapping[str, str],
    min_plays: int = MIN_WP_PLAYS,
) -> pl.DataFrame:
    """Per-game GEI-style excitement and sample sd of per-play home_wp deltas.

    excitement = (3600 / t) x sum |delta home_wp|, t including overtime played.
    Null home_wp plays are skipped; the series is the non-null home_wp values
    plus the last play's non-null home_wp_post. Fewer than `min_plays` valid
    home_wp values gives null excitement_score and wp_volatility.
    """
    rows: list[dict[str, object]] = []
    for (game_id,), game in (
        plays.sort("play_id").partition_by("game_id", as_dict=True, maintain_order=True).items()
    ):
        gid = str(game_id)
        series = [float(v) for v in game["home_wp"].to_list() if v is not None]
        wp_plays = len(series)
        last = game.row(-1, named=True)
        post = last["home_wp_post"]
        if post is not None:
            series.append(float(post))
        excitement: float | None = None
        volatility: float | None = None
        if wp_plays >= min_plays and len(series) >= 2:
            deltas = [b - a for a, b in pairwise(series)]
            period = _ot_period(season_by_game.get(gid, 0), game_type_by_game.get(gid, "REG"))
            qtr = last["qtr"]
            qsr = last["quarter_seconds_remaining"]
            t = _game_seconds(
                None if qtr is None else int(qtr),
                None if qsr is None else float(qsr),
                period,
            )
            excitement = REGULATION_SECONDS / t * sum(abs(d) for d in deltas)
            if len(deltas) >= 2:
                volatility = statistics.stdev(deltas)
        rows.append(
            {
                "game_id": gid,
                "wp_plays": wp_plays,
                "excitement_score": excitement,
                "wp_volatility": volatility,
            }
        )
    return pl.DataFrame(
        rows,
        schema={
            "game_id": pl.String,
            "wp_plays": pl.Int64,
            "excitement_score": pl.Float64,
            "wp_volatility": pl.Float64,
        },
    )
