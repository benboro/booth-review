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


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _optional_int(row: dict[str, Any], field: str, *, kind: str) -> int | None:
    """An int field that may be absent; the message names the field, never the value."""
    value = row.get(field)
    if value is None:
        return None
    if not _is_int(value):
        raise ParseError(f"cfbd {kind}: {field} is not an integer")
    return int(value)


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
    is_cfp: bool = False
    playoff_round: str | None = None
    venue_id: int | None = None


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
        # Source: the CFBD /games "playoff" object, non-null only for CFP
        # games (competition="cfp"); VERIFIED against the real vault this
        # session (booth-review, phase 04.1 research).
        playoff = row.get("playoff")
        is_cfp = isinstance(playoff, dict)
        playoff_round_raw = playoff.get("round") if isinstance(playoff, dict) else None
        playoff_round = playoff_round_raw if isinstance(playoff_round_raw, str) else None
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
                is_cfp=is_cfp,
                playoff_round=playoff_round,
                venue_id=_optional_int(row, "venueId", kind="game"),
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


@dataclass(frozen=True)
class CfbdVenue:
    id: int
    name: str
    city: str | None
    state: str | None
    country_code: str | None
    latitude: float | None
    longitude: float | None


def _venue_text(row: dict[str, Any], field: str) -> str | None:
    value = row.get(field)
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ParseError(f"cfbd venue: {field} is not a string")
    return value


def _venue_coordinate(value: object, field: str, limit: float) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ParseError(f"cfbd venue: {field} is not a number")
    if not -limit <= value <= limit:
        raise ParseError(f"cfbd venue: {field} is out of range")
    return float(value)


@dataclass(frozen=True)
class VenueParse:
    venues: list[CfbdVenue]
    malformed: int


def _parse_venue_row(row: object) -> CfbdVenue:
    """One /venues row; raises ParseError when the row is malformed."""
    if not isinstance(row, dict):
        raise ParseError("cfbd venues: expected an object per row")
    venue_id = _require(row, "id", kind="venue")
    if not _is_int(venue_id):
        raise ParseError("cfbd venue: id is not an integer")
    name = _require(row, "name", kind="venue")
    if not isinstance(name, str):
        raise ParseError("cfbd venue: name is not a string")
    location = row.get("location")
    nested = location if isinstance(location, dict) else {}
    raw_lat = row.get("latitude")
    if raw_lat is None:
        raw_lat = nested.get("y")
    raw_lon = row.get("longitude")
    if raw_lon is None:
        raw_lon = nested.get("x")
    latitude = _venue_coordinate(raw_lat, "latitude", 90.0)
    longitude = _venue_coordinate(raw_lon, "longitude", 180.0)
    if latitude == 0.0 and longitude == 0.0:
        # (0, 0) is a placeholder, not a place: leave it unlocated so the
        # reference CSV can fill it.
        latitude = longitude = None
    return CfbdVenue(
        id=venue_id,
        name=name,
        city=_venue_text(row, "city"),
        state=_venue_text(row, "state"),
        country_code=_venue_text(row, "countryCode"),
        latitude=latitude,
        longitude=longitude,
    )


def parse_venues(content: bytes) -> VenueParse:
    """Parse the /venues list. Coordinates come from top-level latitude/longitude,
    falling back to a nested location {x: longitude, y: latitude} when the
    top-level value is null or absent; a venue with neither (or at 0, 0) parses
    with None coordinates (handled downstream).

    A malformed row, or a repeat of an earlier id, is skipped and counted: its
    venue is then unlocated and its games ship place: null. Only a malformed
    response as a whole (not an array) raises. Errors name fields, never values.
    """
    rows = _load_list(content, kind="venues")
    venues: list[CfbdVenue] = []
    seen: set[int] = set()
    malformed = 0
    for row in rows:
        try:
            venue = _parse_venue_row(row)
        except ParseError:
            malformed += 1
            continue
        if venue.id in seen:
            malformed += 1
            continue
        seen.add(venue.id)
        venues.append(venue)
    return VenueParse(venues=venues, malformed=malformed)
