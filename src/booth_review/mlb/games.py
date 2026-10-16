"""The MLB game universe, game keys and the per-season round/league/outlet map.

The game table holds every 2026 national game (from the 506 telecast table) and
every postseason game 2014-2026: 2014-2025 from Retrosheet game info (round from
`gametype`), 2026 from 506 round pages. Regular-season Retrosheet games stay out
of this table (they feed standings and win-expectancy training in plan 09-21).

The round/league/outlet map is data (D-12): Wikipedia proposals per season,
corrected by `mlb_postseason_map_overrides.csv`. An ambiguous round leaves the
outlet null with a review row; nothing is guessed. Every drop, ambiguity and
date shift becomes a review row (counts and ids only).
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Final

import polars as pl

from booth_review.config import DataPaths
from booth_review.mlb.constants import MAX_DATE_SHIFT_DAYS, MLB_CURRENT_SEASON
from booth_review.mlb.inputs import MlbInputs, Review
from booth_review.mlb.layout import mlb_wikipedia_url
from booth_review.mlb.listings import (
    game_key,
    telecast_frame,
)
from booth_review.mlb.reference import MlbMapOverride, MlbReference
from booth_review.mlb.teams import MlbNetworkResolver, MlbTeamResolver
from booth_review.sources.wikipedia.mlb_parser import MapProposal, extract_postseason_map

__all__ = [
    "GAME_SCHEMA",
    "MAP_REVIEW_COLUMNS",
    "MapRow",
    "build_mlb_games",
    "build_postseason_map",
    "game_key",
    "postseason_map",
    "write_postseason_map_review",
]

GAME_SCHEMA: Final[Mapping[str, pl.DataType | type[pl.DataType]]] = {
    "game_key": pl.String,
    "season": pl.Int32,
    "game_date": pl.Date,
    "away_club": pl.String,
    "home_club": pl.String,
    "game_number": pl.Int8,
    "round": pl.String,
    "series_league": pl.String,
    "series_game": pl.Int8,
    "neutral": pl.Boolean,
    "venue_note": pl.String,
    "retrosheet_gid": pl.String,
    "home_won": pl.Boolean,
    "away_score": pl.Int32,
    "home_score": pl.Int32,
}

MAP_REVIEW_COLUMNS: Final = ("season", "round", "league", "network_id", "source", "source_url")

_LEAGUE_ROUNDS: Final = frozenset({"wild_card", "division", "lcs"})
_NON_POSTSEASON: Final = frozenset({"regular", "allstar"})
_CURRENT_SEASON_FROM_506: Final = MLB_CURRENT_SEASON
_MAP_ROUNDS: Final = {"WC": "wild_card", "DS": "division", "CS": "lcs", "WS": "world_series"}


# -- the round/league/outlet map ----------------------------------------------------------------


@dataclass(frozen=True)
class MapRow:
    season: int
    round: str
    league: str | None
    network_id: str | None
    source: str
    source_url: str


def postseason_map(
    season: int,
    proposals: Iterable[MapProposal],
    overrides: Iterable[MlbMapOverride],
    network_resolver: MlbNetworkResolver,
) -> tuple[list[MapRow], list[Review]]:
    """Map rows for one season. Overrides win; two proposed networks give a null outlet."""
    reviews: list[Review] = []
    proposed: dict[tuple[str, str | None], list[MapProposal]] = {}
    for proposal in proposals:
        if proposal.season != season:
            continue
        round_id = _MAP_ROUNDS.get(proposal.round)
        if round_id is None:
            continue
        proposed.setdefault((round_id, proposal.league), []).append(proposal)
    chosen: dict[tuple[str, str | None], MlbMapOverride] = {
        (o.round, o.league or None): o for o in overrides if o.season == season
    }
    rows: list[MapRow] = []
    for round_id, league in sorted(set(proposed) | set(chosen), key=lambda k: (k[0], k[1] or "")):
        override = chosen.get((round_id, league))
        if override is not None:
            rows.append(
                MapRow(
                    season, round_id, league, override.network_id, "override", override.source_url
                )
            )
            continue
        group = proposed[(round_id, league)]
        url = group[0].source_url
        ids: set[str] = set()
        for proposal in group:
            resolved = network_resolver.resolve("wikipedia", proposal.network_raw)
            if resolved.network_id is None:
                reviews.append(
                    Review("wikipedia", "unresolved_map_network", 1, f"{season}/{round_id}")
                )
            else:
                ids.add(resolved.network_id)
        pointer = f"{season}/{round_id}/{league or '-'}"
        if len(ids) == 1:
            rows.append(MapRow(season, round_id, league, next(iter(ids)), "wikipedia", url))
        else:
            kind = "ambiguous_map" if ids else "no_map_network"
            reviews.append(Review("wikipedia", kind, 1, pointer))
            rows.append(MapRow(season, round_id, league, None, "wikipedia", url))
    return rows, reviews


def build_postseason_map(inputs: MlbInputs, ref: MlbReference) -> tuple[list[MapRow], list[Review]]:
    """The full per-season map across every season in `inputs`."""
    resolver = MlbNetworkResolver.from_reference(ref)
    names = sorted({row.variant for row in ref.networks if row.source == "wikipedia"})
    rows: list[MapRow] = []
    reviews: list[Review] = []
    for season in inputs.seasons:
        html = inputs.wikipedia.get(season)
        proposals = (
            extract_postseason_map(html, season, mlb_wikipedia_url(season), names) if html else []
        )
        season_rows, season_reviews = postseason_map(season, proposals, ref.map_overrides, resolver)
        rows.extend(season_rows)
        reviews.extend(season_reviews)
    return rows, reviews


def write_postseason_map_review(paths: DataPaths, rows: Sequence[MapRow]) -> Path:
    """Write the map to interim/review_mlb_postseason_map.csv for human review."""
    target = paths.interim / "review_mlb_postseason_map.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(MAP_REVIEW_COLUMNS)
        for row in rows:
            writer.writerow(
                [
                    row.season,
                    row.round,
                    row.league or "",
                    row.network_id or "",
                    row.source,
                    row.source_url,
                ]
            )
    return target


def _lookup_network(
    index: Mapping[tuple[int, str, str | None], MapRow],
    season: int,
    round_id: str,
    league: str | None,
) -> str | None:
    """The exact (round, league) row wins, even when null; else the league-less row."""
    exact = index.get((season, round_id, league))
    if exact is not None:
        return exact.network_id
    fallback = index.get((season, round_id, None))
    return fallback.network_id if fallback is not None else None


# -- game universe ------------------------------------------------------------------------------


def _club_league(ref: MlbReference, club_id: str, season: int) -> str | None:
    entries = ref.clubs.names.get(club_id)
    if not entries:
        return None
    for entry in entries:
        if (entry.season_from is None or season >= entry.season_from) and (
            entry.season_to is None or season <= entry.season_to
        ):
            return entry.league
    return entries[-1].league


def _parse_date(text: str) -> date | None:
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:]))
    except ValueError:
        return None


def _retrosheet_postseason(
    inputs: MlbInputs, ref: MlbReference, reviews: list[Review]
) -> dict[str, dict[str, Any]]:
    games: dict[str, dict[str, Any]] = {}
    if inputs.gameinfo.is_empty():
        return games
    teams = MlbTeamResolver.from_reference(ref)
    frame = inputs.gameinfo.filter(~pl.col("round").is_in(sorted(_NON_POSTSEASON)))
    for row in frame.iter_rows(named=True):
        season = int(row["season"])
        day = _parse_date(str(row["date"]))
        away = teams.resolve("retrosheet", str(row["visteam"]), season).club_id
        home = teams.resolve("retrosheet", str(row["hometeam"]), season).club_id
        if day is None or away is None or home is None:
            reviews.append(Review("retrosheet", "unresolved_game", 1, f"{season}/{row['round']}"))
            continue
        number = int(row["number"] or 0)
        key = game_key(day, away, home, number)
        vruns, hruns = row["vruns"], row["hruns"]
        games[key] = {
            "game_key": key,
            "season": season,
            "game_date": day,
            "away_club": away,
            "home_club": home,
            "game_number": number,
            "round": row["round"],
            "series_league": None,
            "series_game": None,
            "neutral": False,
            "venue_note": None,
            "retrosheet_gid": row["gid"],
            "home_won": None if vruns is None or hruns is None or vruns == hruns else hruns > vruns,
            "away_score": vruns,
            "home_score": hruns,
        }
    return games


def _via_retrosheet(row: Mapping[str, Any], retro_seasons: frozenset[int]) -> bool:
    """True when a telecast row is matched to a Retrosheet game (exact key, then +/-1 day).

    Every pre-2026 row is. A current-season round row is too once Retrosheet holds that
    season's postseason, so the two sources never list one game twice. Without those
    Retrosheet rows, current-season rows build their own games from the 506 table.
    """
    season = int(row["season"])
    if season != _CURRENT_SEASON_FROM_506:
        return True
    return season in retro_seasons and row["round"] is not None


def _games_from_telecasts(
    telecasts: pl.DataFrame, retro_seasons: frozenset[int] = frozenset()
) -> dict[str, dict[str, Any]]:
    games: dict[str, dict[str, Any]] = {}
    if telecasts.is_empty():
        return games
    current = [
        r
        for r in telecasts.iter_rows(named=True)
        if r["season"] == _CURRENT_SEASON_FROM_506 and not _via_retrosheet(r, retro_seasons)
    ]
    for row in current:
        existing = games.get(row["game_key"])
        if existing is None:
            games[row["game_key"]] = {
                "game_key": row["game_key"],
                "season": row["season"],
                "game_date": row["game_date"],
                "away_club": row["away_club"],
                "home_club": row["home_club"],
                "game_number": row["game_number"],
                "round": row["round"] or "regular",
                "series_league": None,
                "series_game": row["series_game"],
                "neutral": bool(row["neutral"]),
                "venue_note": row["venue_note"],
                "retrosheet_gid": None,
                "home_won": None,
                "away_score": None,
                "home_score": None,
            }
        else:
            if existing["round"] == "regular" and row["round"]:
                existing["round"] = row["round"]
            existing["series_game"] = existing["series_game"] or row["series_game"]
    return games


def _number_series(
    games: dict[str, dict[str, Any]], ref: MlbReference, reviews: list[Review]
) -> None:
    """Fill series_league (club league) and series_game (date order within the series)."""
    groups: dict[tuple[object, ...], list[dict[str, Any]]] = {}
    for game in games.values():
        round_id = str(game["round"])
        if round_id in ("regular", "allstar"):
            continue
        season = int(str(game["season"]))
        if round_id in _LEAGUE_ROUNDS:
            away = _club_league(ref, str(game["away_club"]), season)
            home = _club_league(ref, str(game["home_club"]), season)
            if away is not None and away == home:
                game["series_league"] = away
            else:
                reviews.append(Review("games", "series_league_unknown", 1, f"{season}/{round_id}"))
        pair = frozenset((game["away_club"], game["home_club"]))
        groups.setdefault((season, round_id, game["series_league"], pair), []).append(game)
    for key, members in groups.items():
        members.sort(key=lambda g: (g["game_date"], g["game_number"]))
        if not any(g["series_game"] for g in members):
            for index, game in enumerate(members, start=1):
                game["series_game"] = index
            continue
        # Some games carry 506's own "Game N". The rest take their place in date order
        # only when that makes the series numbers unique and gap-free; otherwise a missing
        # or unlisted game would shift every later number, so they stay unnumbered.
        proposed = [g["series_game"] or index for index, g in enumerate(members, start=1)]
        if sorted(proposed) == list(range(1, len(members) + 1)):
            for game, number in zip(members, proposed, strict=True):
                game["series_game"] = number
        elif any(not g["series_game"] for g in members):
            reviews.append(Review("games", "series_game_unknown", 1, f"{key[0]}/{key[1]}"))


def _attach_round_telecasts(
    telecasts: pl.DataFrame,
    games: dict[str, dict[str, Any]],
    reviews: list[Review],
    retro_seasons: frozenset[int] = frozenset(),
) -> list[dict[str, Any]]:
    """Attach round-page telecasts to Retrosheet games: exact key, then +/-1 day.

    That is every pre-2026 row and, once Retrosheet holds the 2026 postseason, the 2026
    round rows too (see `_via_retrosheet`).
    """
    rows = [r for r in telecasts.iter_rows(named=True) if _via_retrosheet(r, retro_seasons)]
    by_pair: dict[tuple[object, object, object], dict[date, str]] = {}
    for key, game in games.items():
        if game["retrosheet_gid"] is None:
            continue
        pair = (game["away_club"], game["home_club"], game["game_number"])
        by_pair.setdefault(pair, {})[game["game_date"]] = key
    attached: list[dict[str, Any]] = []
    claimed: set[str] = set()
    pending: list[dict[str, Any]] = []
    for row in rows:
        if row["round"] is None:
            reviews.append(Review("506", "regular_telecast_out_of_scope", 1, str(row["season"])))
            continue
        target = by_pair.get((row["away_club"], row["home_club"], row["game_number"]), {})
        exact = target.get(row["game_date"])
        if exact is None:
            pending.append(row)
            continue
        claimed.add(exact)
        attached.append({**row, "game_key": exact, "date_shift": False})
    for row in pending:
        target = by_pair.get((row["away_club"], row["home_club"], row["game_number"]), {})
        candidates = [
            hit
            for offset in range(-MAX_DATE_SHIFT_DAYS, MAX_DATE_SHIFT_DAYS + 1)
            if offset != 0
            and (hit := target.get(row["game_date"] + timedelta(days=offset))) is not None
            and hit not in claimed
        ]
        pointer = f"{row['season']}/{row['round']}"
        if len(candidates) == 1:
            attached.append({**row, "game_key": candidates[0], "date_shift": True})
            reviews.append(Review("506", "date_shift", 1, pointer))
        elif candidates:
            reviews.append(Review("506", "ambiguous_date_shift", 1, pointer))
        else:
            reviews.append(Review("506", "unmatched_round_listing", 1, pointer))
    for row in attached:
        game = games[str(row["game_key"])]
        row["game_date"] = game["game_date"]
        row["game_number"] = game["game_number"]
        row["round"] = game["round"]
        row["series_game"] = game["series_game"]
        # 506 knows about neutral-site games and venue notes that Retrosheet rows lack.
        game["neutral"] = bool(game["neutral"] or row["neutral"])
        game["venue_note"] = game["venue_note"] or row["venue_note"]
        row["neutral"] = game["neutral"]
        row["venue_note"] = game["venue_note"]
    return attached


def build_mlb_games(
    inputs: MlbInputs, ref: MlbReference, telecasts: pl.DataFrame
) -> tuple[pl.DataFrame, pl.DataFrame, list[Review]]:
    """Game table, final telecast table and review rows."""
    reviews: list[Review] = []
    games = _retrosheet_postseason(inputs, ref, reviews)
    retro_seasons = frozenset(int(str(g["season"])) for g in games.values())
    for key, game in _games_from_telecasts(telecasts, retro_seasons).items():
        games.setdefault(key, game)
    _number_series(games, ref, reviews)

    current_rows = [
        r
        for r in telecasts.iter_rows(named=True)
        if r["season"] == _CURRENT_SEASON_FROM_506 and not _via_retrosheet(r, retro_seasons)
    ]
    for row in current_rows:
        game = games[row["game_key"]]
        row["round"] = game["round"] if game["round"] != "regular" else row["round"]
        row["series_game"] = game["series_game"]
    attached = _attach_round_telecasts(telecasts, games, reviews, retro_seasons)

    map_rows, map_reviews = build_postseason_map(inputs, ref)
    reviews.extend(map_reviews)
    index = {(m.season, m.round, m.league): m for m in map_rows}
    families = {row.network_id: row.family for row in ref.networks}
    have = {str(r["game_key"]) for r in [*current_rows, *attached]}
    mapped: list[dict[str, Any]] = []
    missing: dict[str, int] = {}
    for key, game in games.items():
        if key in have or game["retrosheet_gid"] is None:
            continue
        season = int(str(game["season"]))
        round_id = str(game["round"])
        league = game["series_league"]
        network = _lookup_network(
            index, season, round_id, league if isinstance(league, str) else None
        )
        if network is None:
            pointer = f"{season}/{round_id}/{league or '-'}"
            missing[pointer] = missing.get(pointer, 0) + 1
            continue
        mapped.append(
            {
                "game_key": key,
                "season": season,
                "game_date": game["game_date"],
                "away_club": game["away_club"],
                "home_club": game["home_club"],
                "game_number": game["game_number"],
                "network_id": network,
                "family": families.get(network),
                "starred": False,
                "is_exclusive": None,
                "production": "own",
                "window": None,
                "local_outlet": None,
                "crew_names": [],
                "local_simulcast": False,
                "source": "map",
                "source_label": "",
                "round": round_id,
                "series_game": game["series_game"],
                "neutral": game["neutral"],
                "venue_note": game["venue_note"],
                "date_shift": False,
            }
        )
    reviews.extend(Review("map", "no_outlet", n, p) for p, n in sorted(missing.items()))

    game_rows = sorted(games.values(), key=lambda g: (g["game_date"], g["game_key"]))
    games_frame = (
        pl.DataFrame(game_rows, schema=dict(GAME_SCHEMA), infer_schema_length=None)
        if game_rows
        else pl.DataFrame(schema=dict(GAME_SCHEMA))
    )
    telecast_out = telecast_frame([*current_rows, *attached, *mapped])
    return games_frame, telecast_out, reviews
