"""Our own MLB win-expectancy table and per-game excitement, from Retrosheet plays.

State = (inning capped at WE_EXTRA_INNING_CAP, rule regime for the pooled extra-inning
state, half, outs, bases as a 3-bit code, home score difference before the play clipped
to +/- WE_MAX_DIFF). The label is "home team won". Each state is shrunk toward a coarse
(inning, regime, half, difference) table, itself shrunk toward the overall home win
rate, then forced non-decreasing in the lead by pool-adjacent-violators. Excitement is
the sum of absolute changes in home win probability over a game's plays, ending with
the 0/1 outcome; there is no clock, so extra innings simply add terms. A game that is
too short, forfeited or undecided gets null, never 0. The table is trained and read on
the same games (in-sample); the methodology page says so. Pure functions; no I/O.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import polars as pl

from booth_review.mlb.constants import (
    MIN_WE_PLAYS,
    WE_ENFORCE_MONOTONE,
    WE_EXTRA_INNING_CAP,
    WE_GHOST_RUNNER_SEASONS,
    WE_MAX_DIFF,
    WE_MIN_TRAIN_GAMES,
    WE_PRIOR_K,
    WE_TRAIN_INNINGS,
    WE_TRAIN_SEASONS,
)

REGIME_STANDARD = "standard"
REGIME_GHOST = "ghost_runner"

STATE_COLUMNS = ["inning", "regime", "half", "outs", "bases", "diff"]
COARSE_COLUMNS = ["inning", "regime", "half", "diff"]

_PLAY_COLUMNS = (
    "gid",
    "seq",
    "inning",
    "top_bot",
    "score_v",
    "score_h",
    "outs_pre",
    "br1_pre",
    "br2_pre",
    "br3_pre",
)


@dataclass(frozen=True)
class WeTable:
    """Per-state table (with support n), the coarse fallback and the overall home win rate."""

    states: pl.DataFrame
    coarse: pl.DataFrame
    home_rate: float


def _occupied(column: str) -> pl.Expr:
    text = pl.col(column).cast(pl.String)
    return (text.is_not_null() & (text != "")).cast(pl.Int8)


def state_keys(plays: pl.DataFrame, gameinfo: pl.DataFrame) -> pl.DataFrame:
    """One row per play: gid, seq and the state key columns (pre-play scores are used)."""
    missing = [c for c in _PLAY_COLUMNS if c not in plays.columns]
    if missing:
        raise ValueError(f"plays frame lacks columns: {', '.join(missing)}")
    regime_info = gameinfo.select(
        "gid",
        (
            (pl.col("round") == "regular") & pl.col("season").is_in(list(WE_GHOST_RUNNER_SEASONS))
        ).alias("_ghost"),
    ).unique("gid", keep="first", maintain_order=True)
    capped = pl.col("inning").clip(upper_bound=WE_EXTRA_INNING_CAP)
    keyed = (
        plays.select(_PLAY_COLUMNS)
        .join(regime_info, on="gid", how="left", maintain_order="left")
        .select(
            "gid",
            "seq",
            capped.cast(pl.Int32).alias("inning"),
            pl.when((pl.col("inning") >= WE_EXTRA_INNING_CAP) & pl.col("_ghost").fill_null(False))
            .then(pl.lit(REGIME_GHOST))
            .otherwise(pl.lit(REGIME_STANDARD))
            .alias("regime"),
            pl.col("top_bot").cast(pl.Int8).alias("half"),
            pl.col("outs_pre").cast(pl.Int8).alias("outs"),
            (_occupied("br1_pre") + _occupied("br2_pre") * 2 + _occupied("br3_pre") * 4).alias(
                "bases"
            ),
            (pl.col("score_h") - pl.col("score_v"))
            .clip(-WE_MAX_DIFF, WE_MAX_DIFF)
            .cast(pl.Int32)
            .alias("diff"),
        )
    )
    return keyed


def _training_games(gameinfo: pl.DataFrame) -> pl.DataFrame:
    """Decided regular-season games scheduled for WE_TRAIN_INNINGS innings in the window."""
    forfeit = (
        pl.col("forfeit").is_null() | (pl.col("forfeit") == "")
        if "forfeit" in gameinfo.columns
        else pl.lit(True)
    )
    return gameinfo.filter(
        (pl.col("round") == "regular")
        & pl.col("season").is_in(list(WE_TRAIN_SEASONS))
        & (pl.col("innings").is_null() | (pl.col("innings") == WE_TRAIN_INNINGS))
        & pl.col("vruns").is_not_null()
        & pl.col("hruns").is_not_null()
        & (pl.col("vruns") != pl.col("hruns"))
        & forfeit
    ).select("gid", (pl.col("hruns") > pl.col("vruns")).cast(pl.Int32).alias("home_won"))


def _pool_adjacent_violators(values: list[float], weights: list[float]) -> list[float]:
    """Weighted isotonic (non-decreasing) fit, plain Python and deterministic."""
    blocks: list[list[float]] = []  # [weighted sum, weight, count]
    for value, weight in zip(values, weights, strict=True):
        blocks.append([value * weight, weight, 1.0])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            last = blocks.pop()
            blocks[-1][0] += last[0]
            blocks[-1][1] += last[1]
            blocks[-1][2] += last[2]
    out: list[float] = []
    for total, weight, count in blocks:
        out.extend([total / weight] * int(count))
    return out


def _monotone(frame: pl.DataFrame, group: list[str]) -> pl.DataFrame:
    """Make `p` non-decreasing in `diff` within each `group`, weighted by n."""
    ordered = frame.sort(*group, "diff")
    fitted: list[float] = []
    for _key, part in ordered.group_by(group, maintain_order=True):
        fitted.extend(
            _pool_adjacent_violators(part["p"].to_list(), [float(n) for n in part["n"].to_list()])
        )
    return ordered.with_columns(pl.Series("p", fitted, dtype=pl.Float64))


def build_we_table(
    plays: pl.DataFrame,
    gameinfo: pl.DataFrame,
    *,
    min_train_games: int = WE_MIN_TRAIN_GAMES,
    prior_k: float = WE_PRIOR_K,
    enforce_monotone: bool = WE_ENFORCE_MONOTONE,
) -> WeTable:
    """Train the table on regular-season games; fails loudly with too few training games."""
    games = _training_games(gameinfo)
    if games.height < min_train_games:
        raise ValueError(
            f"win-expectancy table needs {min_train_games} training games, found {games.height}"
        )
    home_rate = float(games["home_won"].mean())  # type: ignore[arg-type]
    train_plays = plays.filter(pl.col("gid").is_in(games["gid"].implode()))
    keys = state_keys(train_plays, gameinfo).join(games, on="gid", how="inner")
    states = (
        keys.group_by(STATE_COLUMNS)
        .agg(pl.len().cast(pl.Int64).alias("n"), pl.col("home_won").sum().alias("home_wins"))
        .sort(STATE_COLUMNS)
    )
    coarse = (
        states.group_by(COARSE_COLUMNS)
        .agg(pl.col("n").sum(), pl.col("home_wins").sum())
        .sort(COARSE_COLUMNS)
        .with_columns(
            ((pl.col("home_wins") + prior_k * home_rate) / (pl.col("n") + prior_k)).alias("p")
        )
    )
    if enforce_monotone:
        coarse = _monotone(coarse, ["inning", "regime", "half"])
    states = states.join(
        coarse.select(*COARSE_COLUMNS, pl.col("p").alias("p_coarse")),
        on=COARSE_COLUMNS,
        how="left",
        maintain_order="left",
    ).with_columns(
        ((pl.col("home_wins") + prior_k * pl.col("p_coarse")) / (pl.col("n") + prior_k)).alias("p")
    )
    states = states.drop("p_coarse")
    if enforce_monotone:
        states = _monotone(states, ["inning", "regime", "half", "outs", "bases"])
    return WeTable(
        states=states.sort(STATE_COLUMNS),
        coarse=coarse.sort(COARSE_COLUMNS),
        home_rate=home_rate,
    )


def _lookup(keys: pl.DataFrame, table: WeTable) -> pl.DataFrame:
    """Add `p` to each play: its state, else its coarse cell, else the home win rate."""
    indexed = keys.with_row_index("_i")
    joined = (
        indexed.join(
            table.states.select(*STATE_COLUMNS, pl.col("p").alias("_p_state")),
            on=STATE_COLUMNS,
            how="left",
            maintain_order="left",
        )
        .join(
            table.coarse.select(*COARSE_COLUMNS, pl.col("p").alias("_p_coarse")),
            on=COARSE_COLUMNS,
            how="left",
            maintain_order="left",
        )
        .sort("_i")
    )
    return joined.with_columns(
        pl.coalesce("_p_state", "_p_coarse", pl.lit(table.home_rate)).alias("p")
    ).drop("_i", "_p_state", "_p_coarse")


def game_excitement(
    probs: Sequence[float],
    home_won: bool | None,
    *,
    min_plays: int = MIN_WE_PLAYS,
    forfeit: bool = False,
) -> float | None:
    """Sum of absolute changes in home win probability, ending at the 0/1 outcome.

    `probs` are the pre-play probabilities in play order. Null (never 0) for a game with
    fewer than `min_plays` plays, a forfeit, or no decided winner.
    """
    if forfeit or home_won is None or len(probs) < min_plays or not probs:
        return None
    total = 0.0
    previous = probs[0]
    for current in probs[1:]:
        total += abs(current - previous)
        previous = current
    return total + abs((1.0 if home_won else 0.0) - previous)


def excitement_by_game(
    plays: pl.DataFrame,
    gameinfo: pl.DataFrame,
    table: WeTable,
    *,
    min_plays: int = MIN_WE_PLAYS,
) -> pl.DataFrame:
    """One row per game in `plays`: gid, wp_excitement (null when unscorable), n_plays."""
    keys = _lookup(state_keys(plays, gameinfo).sort("gid", "seq", maintain_order=True), table)
    per_game = keys.group_by("gid", maintain_order=True).agg(pl.col("p"))
    has_forfeit = "forfeit" in gameinfo.columns
    outcome: dict[str, tuple[bool | None, bool]] = {}
    for row in gameinfo.iter_rows(named=True):
        vruns, hruns = row.get("vruns"), row.get("hruns")
        home_won = None if vruns is None or hruns is None or vruns == hruns else hruns > vruns
        forfeited = bool(row["forfeit"]) if has_forfeit else False
        outcome.setdefault(row["gid"], (home_won, forfeited))
    rows: list[dict[str, object]] = []
    for gid, probs in per_game.iter_rows():
        home_won, forfeited = outcome.get(gid, (None, False))
        rows.append(
            {
                "gid": gid,
                "wp_excitement": game_excitement(
                    probs, home_won, min_plays=min_plays, forfeit=forfeited
                ),
                "n_plays": len(probs),
            }
        )
    return pl.DataFrame(
        rows,
        schema={"gid": pl.String, "wp_excitement": pl.Float64, "n_plays": pl.Int64},
    )
