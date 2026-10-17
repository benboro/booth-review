"""506 MLB listings to telecast rows: network ids, production and exclusivity.

One row per outlet cell. Names resolve through the data/reference/ crosswalks;
a listing whose clubs or network do not resolve is kept out of the telecast
table and shows up only as a review row (counts and ids, never source text).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Final

import polars as pl

from booth_review.mlb.inputs import Review
from booth_review.mlb.reference import MlbReference
from booth_review.mlb.teams import MlbNetworkResolver, MlbTeamResolver
from booth_review.sources.sports506.mlb_parser import MlbListing506, MlbNonGameRow

#: Production per (local_simulcast, starred, has_crew), from
#: docs/sources/mlb-field-list.md § Rules ("Production") and § Edge cases:
#: a "(local simulcast)" cell is always a simulcast of the club's feed with no crew;
#: a starred listing with no crew is a local-feed simulcast; a starred listing that
#: names a crew is the outlet's own showcase production; an unstarred listing is the
#: outlet's own production. Never inferred from the outlet's name.
PRODUCTION_RULES: Final[Mapping[tuple[bool, bool, bool], str]] = {
    (True, False, False): "simulcast",
    (True, False, True): "simulcast",
    (True, True, False): "simulcast",
    (True, True, True): "simulcast",
    (False, True, False): "simulcast",
    (False, True, True): "own",
    (False, False, False): "own",
    (False, False, True): "own",
}

ROUND_BY_LABEL: Final[Mapping[str, str]] = {
    "WC": "wild_card",
    "DS": "division",
    "CS": "lcs",
    "WS": "world_series",
}

TELECAST_SCHEMA: Final[Mapping[str, pl.DataType | type[pl.DataType]]] = {
    "game_key": pl.String,
    "season": pl.Int32,
    "game_date": pl.Date,
    "away_club": pl.String,
    "home_club": pl.String,
    "game_number": pl.Int8,
    "network_id": pl.String,
    "family": pl.String,
    "starred": pl.Boolean,
    "is_exclusive": pl.Boolean,
    "production": pl.String,
    "window": pl.String,
    "local_outlet": pl.String,
    "crew_names": pl.List(pl.String),
    "local_simulcast": pl.Boolean,
    "source": pl.String,
    "source_label": pl.String,
    "round": pl.String,
    "series_game": pl.Int8,
    "neutral": pl.Boolean,
    "venue_note": pl.String,
    "date_shift": pl.Boolean,
    # Where the outlet came from: "506" (the listing itself), or "wikipedia"/"override"
    # (the round/league outlet map) with the map row's article or citation URL.
    "network_source": pl.String,
    "network_source_url": pl.String,
}


def game_key(day: date, away: str, home: str, number: int) -> str:
    """`YYYY-MM-DD|away|home|n`: date, both clubs and game number (0 for a single game)."""
    return f"{day.isoformat()}|{away}|{home}|{number}"


def production_of(*, local_simulcast: bool, starred: bool, has_crew: bool) -> str:
    return PRODUCTION_RULES[(local_simulcast, starred, has_crew)]


def empty_telecasts() -> pl.DataFrame:
    return pl.DataFrame(schema=dict(TELECAST_SCHEMA))


def telecast_frame(rows: list[dict[str, object]]) -> pl.DataFrame:
    if not rows:
        return empty_telecasts()
    return pl.DataFrame(rows, schema=dict(TELECAST_SCHEMA))


@dataclass
class _Counts:
    counts: dict[tuple[str, str, str], int]

    def add(self, source: str, kind: str, pointer: str = "") -> None:
        key = (source, kind, pointer)
        self.counts[key] = self.counts.get(key, 0) + 1

    def reviews(self) -> list[Review]:
        return [Review(s, k, n, p) for (s, k, p), n in sorted(self.counts.items())]


def listings_to_telecasts(
    listings: Iterable[MlbListing506],
    ref: MlbReference,
    non_game: Iterable[MlbNonGameRow] = (),
) -> tuple[pl.DataFrame, list[Review]]:
    """Telecast rows (one per outlet cell) and review rows for everything left out."""
    teams = MlbTeamResolver.from_reference(ref)
    networks = MlbNetworkResolver.from_reference(ref)
    counts = _Counts({})
    for skipped in non_game:
        counts.add("506", f"non_game_{skipped.kind}", f"{skipped.season}/{skipped.label}")

    merged: dict[tuple[str, str], dict[str, object]] = {}
    for item in listings:
        pointer = f"{item.season}/{item.label}"
        if item.not_played:
            counts.add("506", "not_played", pointer)
            continue
        if item.game_date is None:
            counts.add("506", "no_date", pointer)
            continue
        away = teams.resolve("506", item.away_raw, item.season).club_id
        home = teams.resolve("506", item.home_raw, item.season).club_id
        if away is None or home is None:
            counts.add("506", "unresolved_club", pointer)
            continue
        key = game_key(item.game_date, away, home, item.game_number)
        for cell in item.outlets:
            resolved = networks.resolve("506", cell.raw_name)
            if resolved.network_id is None:
                counts.add("506", "unresolved_network", pointer)
                continue
            has_crew = bool(item.crew_names)
            row: dict[str, object] = {
                "game_key": key,
                "season": item.season,
                "game_date": item.game_date,
                "away_club": away,
                "home_club": home,
                "game_number": item.game_number,
                "network_id": resolved.network_id,
                "family": resolved.family,
                "starred": cell.starred,
                "is_exclusive": (
                    False if cell.starred or cell.local_outlet or len(item.outlets) > 1 else None
                ),
                "production": production_of(
                    local_simulcast=item.local_simulcast,
                    starred=cell.starred,
                    has_crew=has_crew,
                ),
                "window": cell.window,
                "local_outlet": cell.local_outlet,
                "crew_names": [] if item.local_simulcast else list(item.crew_names),
                "local_simulcast": item.local_simulcast,
                "source": "506",
                "source_label": item.label,
                "round": ROUND_BY_LABEL.get(item.label),
                "series_game": item.series_game,
                "neutral": item.neutral,
                "venue_note": item.venue_note,
                "date_shift": False,
                "network_source": "506",
                "network_source_url": None,
            }
            slot = (key, resolved.network_id)
            prior = merged.get(slot)
            if prior is None:
                merged[slot] = row
                continue
            counts.add("506", "duplicate_listing", pointer)
            if not prior["crew_names"] and row["crew_names"]:
                row["round"] = row["round"] or prior["round"]
                merged[slot] = row
            elif prior["round"] is None:
                prior["round"] = row["round"]
                prior["series_game"] = prior["series_game"] or row["series_game"]

    # Another outlet carrying the same game means local carriage exists elsewhere.
    outlets_by_game: dict[str, set[str]] = {}
    for (key, network), _row in merged.items():
        outlets_by_game.setdefault(key, set()).add(network)
    for (key, _network), row in merged.items():
        if len(outlets_by_game[key]) > 1:
            row["is_exclusive"] = False
    return telecast_frame(list(merged.values())), counts.reviews()
