"""Daily standings, pregame stakes and the strength prior, from Retrosheet results only.

Every number here is computed from the regular-season results in the Retrosheet
game-info table: each club's record through the previous day, its games behind the
division leader and behind the last wild-card spot, and a scalar leverage proxy (our
own design: a proxy for how much one game moves a club's race, not a simulation).
Missing stays null: stakes is null early in the season, in 2020, and for any season
with no results. A tie or forfeit is left out of the records and listed in a review.
Pure functions; no I/O.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

import polars as pl

from booth_review.mlb.constants import (
    GB_SD_PER_ROOT_GAME,
    SEASON_GAMES,
    STAKES_EXCLUDED_SEASONS,
    STAKES_GAME_SHIFT,
    STAKES_MIN_GAMES,
    wc_spots,
)
from booth_review.mlb.reference import MlbReference

#: team code -> (league, division)
Teams = Mapping[str, tuple[str, str]]

STRENGTH_PRIOR_SEASON = 2025

STANDINGS_COLUMNS: tuple[str, ...] = (
    "season",
    "date",
    "team",
    "league",
    "division",
    "w",
    "l",
    "played",
    "games_left",
    "gb_div",
    "gb_wc",
    "tie_flag",
)

STAKES_COLUMNS: tuple[str, ...] = (
    "gid",
    "season",
    "date",
    "visteam",
    "hometeam",
    "away_w",
    "away_l",
    "away_gb_div",
    "away_gb_wc",
    "away_leverage",
    "home_w",
    "home_l",
    "home_gb_div",
    "home_gb_wc",
    "home_leverage",
    "pregame_stakes",
)

_RESULT_COLUMNS = ("gid", "vruns", "hruns")
_SQRT_2PI = math.sqrt(2.0 * math.pi)


@dataclass(frozen=True)
class StandingsReview:
    """A game left out of the records; carries the game id and a reason only."""

    gid: str
    reason: str


def team_divisions(ref: MlbReference, season: int) -> dict[str, tuple[str, str]]:
    """Retrosheet team code -> (league, division) for `season`, via the crosswalk."""
    out: dict[str, tuple[str, str]] = {}
    for row in ref.crosswalk:
        if row.source != "retrosheet":
            continue
        if row.season_from is not None and season < row.season_from:
            continue
        if row.season_to is not None and season > row.season_to:
            continue
        for name in ref.clubs.names.get(row.club_id, ()):
            if name.season_from is not None and season < name.season_from:
                continue
            if name.season_to is not None and season > name.season_to:
                continue
            out[row.variant] = (name.league, name.division)
    return out


# -- records ------------------------------------------------------------------------------------


def _season_games(
    gameinfo: pl.DataFrame, season: int, results: pl.DataFrame | None
) -> pl.DataFrame:
    """Regular-season games of `season` with vruns/hruns and a forfeit flag, in play order."""
    frame = gameinfo.filter((pl.col("season") == season) & (pl.col("round") == "regular"))
    if "forfeit" not in frame.columns:
        frame = frame.with_columns(pl.lit(None, dtype=pl.String).alias("forfeit"))
    if results is not None:
        for column in _RESULT_COLUMNS:
            if column not in results.columns:
                raise ValueError(f"results frame lacks column {column}")
        patch = results.select(
            "gid", pl.col("vruns").alias("_rv"), pl.col("hruns").alias("_rh")
        ).unique("gid", keep="first", maintain_order=True)
        if "vruns" not in frame.columns:
            frame = frame.with_columns(
                pl.lit(None, dtype=pl.Int32).alias("vruns"),
                pl.lit(None, dtype=pl.Int32).alias("hruns"),
            )
        frame = (
            frame.join(patch, on="gid", how="left")
            .with_columns(
                pl.coalesce("vruns", "_rv").alias("vruns"),
                pl.coalesce("hruns", "_rh").alias("hruns"),
            )
            .drop("_rv", "_rh")
        )
    elif "vruns" not in frame.columns:
        frame = frame.with_columns(
            pl.lit(None, dtype=pl.Int32).alias("vruns"),
            pl.lit(None, dtype=pl.Int32).alias("hruns"),
        )
    return frame.sort("date", "number", "gid", maintain_order=True)


def _decided(
    frame: pl.DataFrame,
) -> tuple[list[tuple[str, str, str, str]], list[StandingsReview]]:
    """(date, winner, loser, gid) rows for games with a clean result, plus reviews."""
    rows: list[tuple[str, str, str, str]] = []
    reviews: list[StandingsReview] = []
    for gid, date, away, home, vruns, hruns, forfeit in frame.select(
        "gid", "date", "visteam", "hometeam", "vruns", "hruns", "forfeit"
    ).iter_rows():
        if forfeit:
            reviews.append(StandingsReview(gid, "forfeit"))
        elif vruns is None or hruns is None:
            reviews.append(StandingsReview(gid, "no_result"))
        elif vruns == hruns:
            reviews.append(StandingsReview(gid, "tie"))
        elif hruns > vruns:
            rows.append((date, home, away, gid))
        else:
            rows.append((date, away, home, gid))
    return rows, reviews


def _order_key(team: str, w: int, losses: int) -> tuple[int, int, str]:
    # best (W-L) first, then wins, then club id
    return (-(w - losses), -w, team)


def _gb(ref_w: int, ref_l: int, w: int, losses: int) -> float:
    return ((ref_w - w) + (losses - ref_l)) / 2


def _race(
    records: dict[str, tuple[int, int]], teams: Teams, season: int
) -> dict[str, tuple[float | None, float | None, bool]]:
    """team -> (gb_div, gb_wc, tie_flag) for one date's records."""
    out: dict[str, tuple[float | None, float | None, bool]] = {}
    by_division: dict[tuple[str, str], list[str]] = {}
    for team, (league, division) in teams.items():
        by_division.setdefault((league, division), []).append(team)
    winners: dict[str, list[str]] = {}
    gb_div: dict[str, float | None] = {}
    tie_flag: dict[str, bool] = {}
    for (league, _division), members in sorted(by_division.items()):
        ranked = sorted(members, key=lambda t: _order_key(t, *records[t]))
        leader_w, leader_l = records[ranked[0]]
        winners.setdefault(league, []).append(ranked[0])
        diffs = [records[t][0] - records[t][1] for t in ranked]
        for index, team in enumerate(ranked):
            w, losses = records[team]
            tie_flag[team] = diffs.count(w - losses) > 1
            if index > 0:
                gb_div[team] = _gb(leader_w, leader_l, w, losses)
            elif len(ranked) > 1:
                second_w, second_l = records[ranked[1]]
                gb_div[team] = -_gb(leader_w, leader_l, second_w, second_l)
            else:
                gb_div[team] = None
    spots = wc_spots(season)
    by_league: dict[str, list[str]] = {}
    for team, (league, _division) in teams.items():
        if team not in winners.get(league, []):
            by_league.setdefault(league, []).append(team)
    gb_wc: dict[str, float | None] = dict.fromkeys(teams)
    for members in by_league.values():
        ranked = sorted(members, key=lambda t: _order_key(t, *records[t]))
        for index, team in enumerate(ranked):
            w, losses = records[team]
            if index < spots:
                # holding a spot: lead over the first club outside the spots
                if len(ranked) > spots:
                    out_w, out_l = records[ranked[spots]]
                    gb_wc[team] = -_gb(w, losses, out_w, out_l)
            elif len(ranked) >= spots:
                last_w, last_l = records[ranked[spots - 1]]
                gb_wc[team] = _gb(last_w, last_l, w, losses)
            # tie flag also covers the wild-card order
            diffs = [records[t][0] - records[t][1] for t in ranked]
            if diffs.count(w - losses) > 1:
                tie_flag[team] = True
    for team in teams:
        out[team] = (gb_div[team], gb_wc[team], tie_flag[team])
    return out


def daily_standings(
    gameinfo: pl.DataFrame,
    teams: Teams,
    season: int,
    results: pl.DataFrame | None = None,
) -> tuple[pl.DataFrame, list[StandingsReview]]:
    """One row per club per game date: its record through the previous day and its races.

    `results` (gid, vruns, hruns) fills runs gameinfo lacks. A suspended game counts on
    its recorded (original) date. Ties and forfeits are excluded and reviewed.
    """
    frame = _season_games(gameinfo, season, results)
    decided, reviews = _decided(frame)
    dates = sorted(set(frame["date"].to_list()))
    schema = {
        "season": pl.Int32,
        "date": pl.String,
        "team": pl.String,
        "league": pl.String,
        "division": pl.String,
        "w": pl.Int32,
        "l": pl.Int32,
        "played": pl.Int32,
        "games_left": pl.Int32,
        "gb_div": pl.Float64,
        "gb_wc": pl.Float64,
        "tie_flag": pl.Boolean,
    }
    if not decided:
        return pl.DataFrame(schema=schema), reviews
    records: dict[str, tuple[int, int]] = {}
    for team in teams:
        records[team] = (0, 0)
    by_date: dict[str, list[tuple[str, str]]] = {}
    for date, winner, loser, _gid in decided:
        by_date.setdefault(date, []).append((winner, loser))
    rows: list[dict[str, object]] = []
    for date in dates:
        race = _race(records, teams, season)
        for team in sorted(teams):
            w, losses = records[team]
            league, division = teams[team]
            gb_div, gb_wc, tie = race[team]
            rows.append(
                {
                    "season": season,
                    "date": date,
                    "team": team,
                    "league": league,
                    "division": division,
                    "w": w,
                    "l": losses,
                    "played": w + losses,
                    "games_left": SEASON_GAMES - (w + losses),
                    "gb_div": gb_div,
                    "gb_wc": gb_wc,
                    "tie_flag": tie,
                }
            )
        for winner, loser in by_date.get(date, ()):
            if winner in records:
                records[winner] = (records[winner][0] + 1, records[winner][1])
            if loser in records:
                records[loser] = (records[loser][0], records[loser][1] + 1)
    return pl.DataFrame(rows, schema=schema), reviews


# -- leverage and stakes ------------------------------------------------------------------------


def team_leverage(
    gb_div: float | None, gb_wc: float | None, games_left: int | float
) -> float | None:
    """STAKES_GAME_SHIFT * phi(z) / sigma, sigma = GB_SD_PER_ROOT_GAME*sqrt(games_left).

    The gap is the race closest to its cutoff: the smaller of |games behind the division|
    and |games behind the last wild-card spot| (a lead counts as distance, as a deficit
    does); z = that gap / sigma. A club 0.5 games out of its division but comfortably in
    the wild-card field is still in a live race. Null with no gap or under one game left.
    """
    gaps = [g for g in (gb_div, gb_wc) if g is not None]
    if not gaps or games_left < 1:
        return None
    sigma = GB_SD_PER_ROOT_GAME * math.sqrt(games_left)
    z = min(abs(g) for g in gaps) / sigma
    phi = math.exp(-0.5 * z * z) / _SQRT_2PI
    return STAKES_GAME_SHIFT * phi / sigma


def pregame_stakes(games: pl.DataFrame, standings: pl.DataFrame, season: int) -> pl.DataFrame:
    """Per game: both clubs' record and races through the previous day plus the stakes scalar.

    `games` carries gid, season, date, visteam, hometeam (regular-season rows are used).
    The scalar is the mean of the two clubs' leverage; null when either club has played
    fewer than STAKES_MIN_GAMES, for an excluded season, or with no standings.
    """
    rows = games.filter(pl.col("season") == season)
    if "round" in rows.columns:
        rows = rows.filter(pl.col("round") == "regular")
    rows = (
        rows.sort("date", "number", "gid", maintain_order=True)
        if "number" in rows.columns
        else rows
    )
    lookup: dict[tuple[str, str], tuple[int, int, float | None, float | None, int]] = {}
    for date, team, w, losses, gb_div, gb_wc, left in (
        standings.filter(pl.col("season") == season)
        .select("date", "team", "w", "l", "gb_div", "gb_wc", "games_left")
        .iter_rows()
    ):
        lookup[(date, team)] = (w, losses, gb_div, gb_wc, left)
    excluded = season in STAKES_EXCLUDED_SEASONS
    out: list[dict[str, object]] = []
    for gid, date, away, home in rows.select("gid", "date", "visteam", "hometeam").iter_rows():
        row: dict[str, object] = {
            "gid": gid,
            "season": season,
            "date": date,
            "visteam": away,
            "hometeam": home,
        }
        levers: list[float | None] = []
        for prefix, team in (("away", away), ("home", home)):
            rec = lookup.get((date, team))
            if rec is None:
                row.update(
                    {f"{prefix}_{k}": None for k in ("w", "l", "gb_div", "gb_wc", "leverage")}
                )
                levers.append(None)
                continue
            w, losses, gb_div, gb_wc, left = rec
            young = (w + losses) < STAKES_MIN_GAMES
            lever = None if (excluded or young) else team_leverage(gb_div, gb_wc, left)
            row.update(
                {
                    f"{prefix}_w": w,
                    f"{prefix}_l": losses,
                    f"{prefix}_gb_div": gb_div,
                    f"{prefix}_gb_wc": gb_wc,
                    f"{prefix}_leverage": lever,
                }
            )
            levers.append(lever)
        known = [v for v in levers if v is not None]
        row["pregame_stakes"] = sum(known) / 2 if len(known) == 2 else None
        out.append(row)
    schema = {
        "gid": pl.String,
        "season": pl.Int32,
        "date": pl.String,
        "visteam": pl.String,
        "hometeam": pl.String,
        "away_w": pl.Int32,
        "away_l": pl.Int32,
        "away_gb_div": pl.Float64,
        "away_gb_wc": pl.Float64,
        "away_leverage": pl.Float64,
        "home_w": pl.Int32,
        "home_l": pl.Int32,
        "home_gb_div": pl.Float64,
        "home_gb_wc": pl.Float64,
        "home_leverage": pl.Float64,
        "pregame_stakes": pl.Float64,
    }
    return pl.DataFrame(out, schema=schema)


# -- strength prior -----------------------------------------------------------------------------


def strength_prior(
    gameinfo: pl.DataFrame,
    season: int = STRENGTH_PRIOR_SEASON,
    results: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """Each club's regular-season win percentage in `season` (team, w, l, win_pct)."""
    decided, _reviews = _decided(_season_games(gameinfo, season, results))
    wins: dict[str, int] = {}
    losses: dict[str, int] = {}
    for _date, winner, loser, _gid in decided:
        wins[winner] = wins.get(winner, 0) + 1
        losses[loser] = losses.get(loser, 0) + 1
    rows = []
    for team in sorted(set(wins) | set(losses)):
        w, lo = wins.get(team, 0), losses.get(team, 0)
        rows.append({"team": team, "w": w, "l": lo, "win_pct": w / (w + lo)})
    return pl.DataFrame(
        rows,
        schema={"team": pl.String, "w": pl.Int32, "l": pl.Int32, "win_pct": pl.Float64},
    )


def game_strength_prior(games: pl.DataFrame, prior: pl.DataFrame) -> pl.DataFrame:
    """Per game, the mean of its two clubs' prior win percentages (null if either is missing)."""
    pct = dict(prior.select("team", "win_pct").iter_rows())
    rows = []
    for gid, away, home in games.select("gid", "visteam", "hometeam").iter_rows():
        a, h = pct.get(away), pct.get(home)
        rows.append(
            {"gid": gid, "strength_prior": (a + h) / 2 if a is not None and h is not None else None}
        )
    return pl.DataFrame(rows, schema={"gid": pl.String, "strength_prior": pl.Float64})
