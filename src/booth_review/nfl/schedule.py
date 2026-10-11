"""Typed parse of the nflverse schedules CSV.

Pure: bytes in, rows out. All columns are read as strings and converted
explicitly; empty strings become None. Errors name the column, or the season
and row number, never the cell value (T-999.4-11-01).

A row whose date, kickoff time or week is not set yet (empty, NA, TBD or TBA,
as for an unscheduled late-season or flex game) is skipped and counted, never
an error (WR-04): one such row must not stop the NFL build, gaps or freeze
checks. A value that is set but malformed still raises.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

import polars as pl

from booth_review.errors import ParseError

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")

# Placeholder cell values meaning "not scheduled yet" (compared upper-cased).
_UNSET = frozenset({"", "NA", "TBD", "TBA"})

SCHEDULE_REQUIRED_COLUMNS: tuple[str, ...] = (
    "game_id",
    "season",
    "game_type",
    "week",
    "gameday",
    "weekday",
    "gametime",
    "away_team",
    "away_score",
    "home_team",
    "home_score",
    "location",
    "result",
    "overtime",
    "spread_line",
    "stadium_id",
    "stadium",
)


@dataclass(frozen=True)
class NflGame:
    game_id: str
    season: int
    game_type: str
    week: int
    gameday: date
    gametime: str
    kickoff_et: datetime
    weekday: str
    away_team: str
    home_team: str
    away_score: int | None
    home_score: int | None
    result: int | None
    location: str
    overtime: bool | None
    spread_line: float | None
    stadium_id: str
    stadium: str


def _text(value: str | None) -> str:
    return "" if value is None else value.strip()


def _opt_int(value: str | None, column: str, where: str) -> int | None:
    text = _text(value)
    if not text or text.upper() == "NA":
        return None
    try:
        return int(float(text))
    except ValueError as exc:
        raise ParseError(f"nfl schedules {where}: {column} is not a number") from exc


def _opt_float(value: str | None, column: str, where: str) -> float | None:
    text = _text(value)
    if not text or text.upper() == "NA":
        return None
    try:
        return float(text)
    except ValueError as exc:
        raise ParseError(f"nfl schedules {where}: {column} is not a number") from exc


def parse_schedules(content: bytes, *, seasons: Sequence[int] | None = None) -> list[NflGame]:
    """Parse schedules CSV bytes into NflGame rows, optionally filtered by season.
    Rows with no date, kickoff time or week yet are left out (see the module doc)."""
    return parse_schedules_counted(content, seasons=seasons)[0]


def parse_schedules_counted(
    content: bytes, *, seasons: Sequence[int] | None = None
) -> tuple[list[NflGame], int]:
    """`parse_schedules` plus the number of rows skipped as not scheduled yet."""
    try:
        frame = pl.read_csv(io.BytesIO(content), infer_schema_length=0)
    except Exception as exc:  # polars raises several types for malformed CSV
        raise ParseError("nfl schedules: unreadable CSV") from exc
    for column in SCHEDULE_REQUIRED_COLUMNS:
        if column not in frame.columns:
            raise ParseError(f"nfl schedules: missing column {column}")
    wanted = None if seasons is None else set(seasons)
    games: list[NflGame] = []
    unscheduled = 0
    for index, row in enumerate(frame.iter_rows(named=True), start=2):
        raw_season = _text(row["season"])
        where = f"season {raw_season} row {index}"
        try:
            season = int(raw_season)
        except ValueError as exc:
            raise ParseError(f"nfl schedules row {index}: season is not a number") from exc
        if wanted is not None and season not in wanted:
            continue
        if any(_text(row[c]).upper() in _UNSET for c in ("gameday", "gametime", "week")):
            unscheduled += 1
            continue
        gametime = _text(row["gametime"])
        try:
            gameday = date.fromisoformat(_text(row["gameday"]))
            kickoff = datetime.fromisoformat(f"{gameday.isoformat()}T{gametime}").replace(tzinfo=ET)
        except ValueError as exc:
            raise ParseError(f"nfl schedules {where}: unparseable date or time") from exc
        week = _opt_int(row["week"], "week", where)
        if week is None:
            raise ParseError(f"nfl schedules {where}: week is empty")
        overtime_text = _text(row["overtime"])
        overtime = (
            None
            if not overtime_text or overtime_text.upper() == "NA"
            else (overtime_text in {"1", "1.0", "TRUE", "True", "true"})
        )
        games.append(
            NflGame(
                game_id=_text(row["game_id"]),
                season=season,
                game_type=_text(row["game_type"]),
                week=week,
                gameday=gameday,
                gametime=gametime,
                kickoff_et=kickoff,
                weekday=_text(row["weekday"]),
                away_team=_text(row["away_team"]),
                home_team=_text(row["home_team"]),
                away_score=_opt_int(row["away_score"], "away_score", where),
                home_score=_opt_int(row["home_score"], "home_score", where),
                result=_opt_int(row["result"], "result", where),
                location=_text(row["location"]),
                overtime=overtime,
                spread_line=_opt_float(row["spread_line"], "spread_line", where),
                stadium_id=_text(row["stadium_id"]),
                stadium=_text(row["stadium"]),
            )
        )
    if unscheduled:
        logger.warning("nfl schedules: %d row(s) not scheduled yet were skipped", unscheduled)
    return games, unscheduled
