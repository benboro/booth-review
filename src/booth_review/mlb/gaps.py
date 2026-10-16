"""MLB operational lists: the relay gap list (D-11) and the D-14 Ratings Reference windows.

`relay_gaps` names the 2026 own-production telecasts that still have no named crew, so
the relay session knows which games to look up. It is a local working list (written to
interim/, never committed and never published). `rr_windows` computes the date windows
the Ratings Reference backfill and every later MLB collect/refresh may touch: each
2014-2025 postseason (first game minus one day to last game plus one day, from Retrosheet)
and the 2026 season. No window ever covers a 2014-2025 regular-season date outside a
postseason's own margin.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from typing import Final

import polars as pl

from booth_review.build.io import write_review_csv
from booth_review.config import DataPaths
from booth_review.mlb.collect_cli import Windows
from booth_review.mlb.constants import MLB_CURRENT_SEASON

__all__ = [
    "RELAY_GAPS_COLUMNS",
    "RELAY_GAPS_PATH",
    "RR_WINDOWS_END_2026",
    "RR_WINDOW_MARGIN_DAYS",
    "gap_counts_by_network",
    "relay_gaps",
    "rr_windows",
    "write_relay_gaps",
]

RELAY_GAPS_PATH: Final = "interim/review_mlb_relay_gaps.csv"
RELAY_GAPS_COLUMNS: Final = ("game_key", "network_id", "game_date")
RELAY_SEASON: Final = MLB_CURRENT_SEASON
RR_WINDOW_MARGIN_DAYS: Final = 1
RR_WINDOWS_END_2026: Final = date(MLB_CURRENT_SEASON, 12, 31)
_FIRST_RETROSHEET_POSTSEASON: Final = 2014
_NOT_POSTSEASON: Final = ("regular", "allstar")


def relay_gaps(telecasts: pl.DataFrame, crews: pl.DataFrame) -> list[dict[str, object]]:
    """2026 own-production telecasts with no named crew after assignment.

    A 506 cell that names no usable crew (blank, "TBA", a play-by-play name alone) is a
    gap like any other; only `crew_named` decides.

    `telecasts` is the telecast frame before crew assignment; `crews` is the same frame
    after `assign_crews`. A game the relay (or an override or Wikipedia) has already
    filled is not a gap.
    """
    if telecasts.is_empty() or crews.is_empty():
        return []
    named = {
        (str(k), str(n)): bool(v)
        for k, n, v in crews.select("game_key", "network_id", "crew_named").iter_rows()
    }
    in_scope = {
        (str(k), str(n)): bool(v)
        for k, n, v in crews.select("game_key", "network_id", "crew_in_scope").iter_rows()
    }
    rows: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    current = telecasts.filter((pl.col("season") == RELAY_SEASON) & (pl.col("production") == "own"))
    for row in current.iter_rows(named=True):
        slot = (str(row["game_key"]), str(row["network_id"]))
        if slot in seen or not in_scope.get(slot, False):
            continue
        if named.get(slot, False):
            continue
        seen.add(slot)
        rows.append(
            {
                "game_key": slot[0],
                "network_id": slot[1],
                "game_date": row["game_date"].isoformat(),
            }
        )
    return sorted(
        rows, key=lambda r: (str(r["game_date"]), str(r["game_key"]), str(r["network_id"]))
    )


def gap_counts_by_network(rows: list[dict[str, object]]) -> dict[str, int]:
    counts = Counter(str(r["network_id"]) for r in rows)
    return dict(sorted(counts.items()))


def write_relay_gaps(paths: DataPaths, rows: list[dict[str, object]]) -> str:
    """Write the gap list to the vault's interim/ folder; returns its vault-relative path."""
    write_review_csv(paths.vault / RELAY_GAPS_PATH, RELAY_GAPS_COLUMNS, rows)
    return RELAY_GAPS_PATH


def _merge(windows: list[tuple[date, date]]) -> Windows:
    merged: Windows = []
    for start, end in sorted(windows):
        if merged and start <= merged[-1][1] + timedelta(days=1):
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _days(frame: pl.DataFrame) -> list[date]:
    return sorted(frame["game_date"].to_list())


def rr_windows(games: pl.DataFrame) -> Windows:
    """The D-14 windows from the game table (`season`, `game_date`, `round`).

    2014-2025: each season's postseason, first game minus one day to last plus one day.
    2026: the regular season from the first to the last listed date, and the postseason
    from its first listed date through Dec 31 (when no 2026 round game is listed yet,
    from the day after the last regular-season date). Sorted and merged.
    """
    if games.is_empty():
        return []
    margin = timedelta(days=RR_WINDOW_MARGIN_DAYS)
    out: list[tuple[date, date]] = []
    post = games.filter(~pl.col("round").is_in(list(_NOT_POSTSEASON)))
    for season in sorted({int(s) for s in post["season"].unique().to_list()}):
        if not _FIRST_RETROSHEET_POSTSEASON <= season < RELAY_SEASON:
            continue
        days = _days(post.filter(pl.col("season") == season))
        out.append((days[0] - margin, days[-1] + margin))

    current = games.filter(pl.col("season") == RELAY_SEASON)
    regular = _days(current.filter(pl.col("round") == "regular"))
    round_days = _days(current.filter(~pl.col("round").is_in(list(_NOT_POSTSEASON))))
    if regular:
        out.append((regular[0], regular[-1]))
        start = round_days[0] if round_days else regular[-1] + timedelta(days=1)
        out.append((start, RR_WINDOWS_END_2026))
    elif round_days:
        out.append((round_days[0], RR_WINDOWS_END_2026))
    return _merge(out)
