"""Starting lineups and starting pitchers from Retrosheet plays plus allplayers.

The starting nine are the first batter seen in each lineup slot for a batting
side; the starting pitcher is the first pitcher the opposing side batted against.
Known weakness (not corrected): a starter replaced before his first plate
appearance is missed; the replacement shows instead. A slot whose first batter
came in as a pinch hitter (Retrosheet `bat_f` 11) or pinch runner (12) is flagged
`starter_uncertain`. Review rows hold ids and reasons only, never names.
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl

LINEUP_COLUMNS: tuple[str, ...] = (
    "gid",
    "side",
    "slot",
    "player_id",
    "name",
    "position",
    "starter_uncertain",
)

_SIDES = {0: "away", 1: "home"}
_PINCH_POSITIONS = (11, 12)
_PITCHER_POSITION = 1


@dataclass(frozen=True)
class LineupReview:
    """A lineup problem; carries ids and a reason, no name text."""

    gid: str
    side: str
    slot: int
    reason: str
    player_id: str | None = None


def _names(players: pl.DataFrame) -> dict[str, str]:
    out: dict[str, str] = {}
    for pid, first, last in players.select("id", "first", "last").iter_rows():
        text = " ".join(part for part in (first, last) if part)
        if pid is not None and text:
            out[pid] = text
    return out


def starting_lineups(
    plays: pl.DataFrame, players: pl.DataFrame
) -> tuple[pl.DataFrame, list[LineupReview]]:
    """Return (lineup rows, review list); slot 0 is the starting pitcher."""
    names = _names(players)
    ordered = plays.sort("gid", "seq", maintain_order=True)
    rows: list[dict[str, object]] = []
    reviews: list[LineupReview] = []

    for gid in ordered["gid"].unique(maintain_order=True).to_list():
        game = ordered.filter(pl.col("gid") == gid)
        for vis_home, side in _SIDES.items():
            batting = game.filter(pl.col("vis_home") == vis_home)
            first_by_slot = batting.unique(subset=["lp"], keep="first", maintain_order=True)
            seen = {int(r["lp"]): r for r in first_by_slot.iter_rows(named=True)}
            fielding = game.filter(pl.col("vis_home") != vis_home)
            starters = fielding["pitcher"].drop_nulls()
            if not all(slot in seen for slot in range(1, 10)) or starters.is_empty():
                reviews.append(LineupReview(gid, side, 0, "incomplete_lineup"))
                continue
            entries: list[tuple[int, str, int | None, bool]] = [
                (0, starters[0], _PITCHER_POSITION, False)
            ]
            for slot in range(1, 10):
                rec = seen[slot]
                bat_f = rec["bat_f"]
                pinch = bat_f in _PINCH_POSITIONS
                position = bat_f if bat_f is not None and 1 <= bat_f <= 10 else None
                entries.append((slot, rec["batter"], position, pinch))
            for slot, player_id, position, uncertain in entries:
                name = names.get(player_id)
                if name is None:
                    reviews.append(LineupReview(gid, side, slot, "unresolved_player", player_id))
                rows.append(
                    {
                        "gid": gid,
                        "side": side,
                        "slot": slot,
                        "player_id": player_id,
                        "name": name,
                        "position": position,
                        "starter_uncertain": uncertain,
                    }
                )

    schema = {
        "gid": pl.String,
        "side": pl.String,
        "slot": pl.Int8,
        "player_id": pl.String,
        "name": pl.String,
        "position": pl.Int8,
        "starter_uncertain": pl.Boolean,
    }
    return pl.DataFrame(rows, schema=schema), reviews
