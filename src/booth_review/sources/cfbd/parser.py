"""CFBD v2 JSON parsers: pure functions from cached response bytes to typed rows.

Field names on the dataclasses are snake_case, mapped from the CFBD v2
camelCase JSON keys (Pattern 2). No team/outlet name normalization happens
here; that belongs to the resolve stage (AGENTS.md, ARCHITECTURE.md Pattern 2).
Parsing /info stays in transport/budget.parse_info (plan 01-05).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from booth_review.errors import ParseError


def _require(obj: dict[str, Any], key: str, *, kind: str) -> Any:
    if key not in obj:
        raise ParseError(f"cfbd {kind}: missing {key}")
    return obj[key]


def _parse_utc_datetime(value: str, *, kind: str, field: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ParseError(f"cfbd {kind}: invalid {field}: {value!r}") from exc
    if dt.tzinfo is None:
        raise ParseError(f"cfbd {kind}: {field} has no timezone offset: {value!r}")
    return dt.astimezone(UTC)


def _load_list(content: bytes, *, kind: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ParseError(f"cfbd {kind}: invalid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ParseError(f"cfbd {kind}: expected a JSON array")
    return data


@dataclass(frozen=True)
class CfbdGame:
    id: int
    season: int
    week: int
    season_type: str | None
    start_date: datetime
    start_time_tbd: bool | None
    completed: bool | None
    neutral_site: bool | None
    conference_game: bool | None
    venue: str | None
    home_id: int | None
    home_team: str
    home_classification: str | None
    home_conference: str | None
    home_points: int | None
    away_id: int | None
    away_team: str
    away_classification: str | None
    away_conference: str | None
    away_points: int | None
    excitement_index: float | None
    notes: str | None


def parse_games(content: bytes) -> list[CfbdGame]:
    rows = _load_list(content, kind="games")
    games: list[CfbdGame] = []
    for row in rows:
        _require(row, "id", kind="game")
        _require(row, "season", kind="game")
        _require(row, "week", kind="game")
        _require(row, "homeTeam", kind="game")
        _require(row, "awayTeam", kind="game")
        start_date_raw = _require(row, "startDate", kind="game")
        games.append(
            CfbdGame(
                id=row["id"],
                season=row["season"],
                week=row["week"],
                season_type=row.get("seasonType"),
                start_date=_parse_utc_datetime(start_date_raw, kind="game", field="startDate"),
                start_time_tbd=row.get("startTimeTBD"),
                completed=row.get("completed"),
                neutral_site=row.get("neutralSite"),
                conference_game=row.get("conferenceGame"),
                venue=row.get("venue"),
                home_id=row.get("homeId"),
                home_team=row["homeTeam"],
                home_classification=row.get("homeClassification"),
                home_conference=row.get("homeConference"),
                home_points=row.get("homePoints"),
                away_id=row.get("awayId"),
                away_team=row["awayTeam"],
                away_classification=row.get("awayClassification"),
                away_conference=row.get("awayConference"),
                away_points=row.get("awayPoints"),
                excitement_index=row.get("excitementIndex"),
                notes=row.get("notes"),
            )
        )
    return games


@dataclass(frozen=True)
class CfbdMedia:
    id: int
    season: int
    week: int
    season_type: str | None
    start_time: str | None
    is_start_time_tbd: bool | None
    home_team: str
    away_team: str
    media_type: str | None
    outlet: str | None


def parse_media(content: bytes) -> list[CfbdMedia]:
    rows = _load_list(content, kind="media")
    result: list[CfbdMedia] = []
    for row in rows:
        _require(row, "id", kind="media")
        _require(row, "season", kind="media")
        _require(row, "week", kind="media")
        _require(row, "homeTeam", kind="media")
        _require(row, "awayTeam", kind="media")
        result.append(
            CfbdMedia(
                id=row["id"],
                season=row["season"],
                week=row["week"],
                season_type=row.get("seasonType"),
                start_time=row.get("startTime"),
                is_start_time_tbd=row.get("isStartTimeTBD"),
                home_team=row["homeTeam"],
                away_team=row["awayTeam"],
                media_type=row.get("mediaType"),
                outlet=row.get("outlet"),
            )
        )
    return result


@dataclass(frozen=True)
class CfbdLine:
    game_id: int
    season: int
    week: int
    season_type: str | None
    start_date: str | None
    home_team: str
    away_team: str
    provider: str
    spread: float | None
    formatted_spread: str | None
    spread_open: float | None
    over_under: float | None
    over_under_open: float | None
    home_moneyline: int | None
    away_moneyline: int | None


def parse_lines(content: bytes) -> list[CfbdLine]:
    rows = _load_list(content, kind="lines")
    result: list[CfbdLine] = []
    for row in rows:
        _require(row, "id", kind="lines")
        _require(row, "season", kind="lines")
        _require(row, "week", kind="lines")
        _require(row, "homeTeam", kind="lines")
        _require(row, "awayTeam", kind="lines")
        for line in row.get("lines", []):
            _require(line, "provider", kind="line")
            result.append(
                CfbdLine(
                    game_id=row["id"],
                    season=row["season"],
                    week=row["week"],
                    season_type=row.get("seasonType"),
                    start_date=row.get("startDate"),
                    home_team=row["homeTeam"],
                    away_team=row["awayTeam"],
                    provider=line["provider"],
                    spread=line.get("spread"),
                    formatted_spread=line.get("formattedSpread"),
                    spread_open=line.get("spreadOpen"),
                    over_under=line.get("overUnder"),
                    over_under_open=line.get("overUnderOpen"),
                    home_moneyline=line.get("homeMoneyline"),
                    away_moneyline=line.get("awayMoneyline"),
                )
            )
    return result


@dataclass(frozen=True)
class CfbdPregameWp:
    season: int
    season_type: str | None
    week: int
    game_id: int
    home_team: str
    away_team: str
    spread: float | None
    home_win_probability: float


def parse_wp_pregame(content: bytes) -> list[CfbdPregameWp]:
    rows = _load_list(content, kind="wp_pregame")
    result: list[CfbdPregameWp] = []
    for row in rows:
        _require(row, "season", kind="wp_pregame")
        _require(row, "week", kind="wp_pregame")
        _require(row, "gameId", kind="wp_pregame")
        _require(row, "homeTeam", kind="wp_pregame")
        _require(row, "awayTeam", kind="wp_pregame")
        _require(row, "homeWinProbability", kind="wp_pregame")
        result.append(
            CfbdPregameWp(
                season=row["season"],
                season_type=row.get("seasonType"),
                week=row["week"],
                game_id=row["gameId"],
                home_team=row["homeTeam"],
                away_team=row["awayTeam"],
                spread=row.get("spread"),
                home_win_probability=row["homeWinProbability"],
            )
        )
    return result


@dataclass(frozen=True)
class CfbdRank:
    rank: int
    school: str
    conference: str | None


@dataclass(frozen=True)
class CfbdPoll:
    poll: str
    ranks: list[CfbdRank]


@dataclass(frozen=True)
class CfbdPollWeek:
    season: int
    season_type: str | None
    week: int
    polls: list[CfbdPoll]


def parse_rankings(content: bytes) -> list[CfbdPollWeek]:
    rows = _load_list(content, kind="rankings")
    result: list[CfbdPollWeek] = []
    for row in rows:
        _require(row, "season", kind="rankings")
        _require(row, "week", kind="rankings")
        polls: list[CfbdPoll] = []
        for poll_row in row.get("polls", []):
            _require(poll_row, "poll", kind="poll")
            ranks = [
                CfbdRank(
                    rank=rank_row["rank"],
                    school=rank_row["school"],
                    conference=rank_row.get("conference"),
                )
                for rank_row in poll_row.get("ranks", [])
            ]
            polls.append(CfbdPoll(poll=poll_row["poll"], ranks=ranks))
        result.append(
            CfbdPollWeek(
                season=row["season"],
                season_type=row.get("seasonType"),
                week=row["week"],
                polls=polls,
            )
        )
    return result


@dataclass(frozen=True)
class CfbdTeam:
    id: int
    school: str
    conference: str | None
    classification: str | None


def parse_teams(content: bytes) -> list[CfbdTeam]:
    rows = _load_list(content, kind="teams")
    result: list[CfbdTeam] = []
    for row in rows:
        _require(row, "id", kind="team")
        _require(row, "school", kind="team")
        result.append(
            CfbdTeam(
                id=row["id"],
                school=row["school"],
                conference=row.get("conference"),
                classification=row.get("classification"),
            )
        )
    return result
