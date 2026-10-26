"""Match 506 NFL listings to nflverse games (D-14: crosswalk only, never guessed).

A game is keyed by season, week and the unordered pair of franchise ids. A
listing that finds no single game, or whose team names do not resolve, becomes
a review row (pointer and reason only, no source text).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Protocol

from booth_review.nfl.inputs import NflInputs
from booth_review.nfl.schedule import NflGame
from booth_review.nfl.teams import NflNetworkResolver, NflTeamResolver
from booth_review.sources.sports506.nfl_parser import NflListing506

GameKey = tuple[int, int, frozenset[str]]


class GameLike(Protocol):
    """The fields a listing needs to find its game (NflGame, UpcomingNflGame)."""

    @property
    def game_id(self) -> str: ...
    @property
    def season(self) -> int: ...
    @property
    def week(self) -> int: ...
    @property
    def away_team(self) -> str: ...
    @property
    def home_team(self) -> str: ...


@dataclass(frozen=True)
class ListingMatch:
    game_id: str
    network_id: str | None
    window: str
    crew_names: tuple[str, ...]
    is_national_line: bool
    intl_city: str | None
    season: int
    week: int
    source_row_index: int


@dataclass(frozen=True)
class ListingReview:
    season: int
    week: int
    source_row_index: int
    reason: str


def index_games_of[G: GameLike](
    games: Sequence[G], teams: NflTeamResolver
) -> dict[GameKey, list[G]]:
    """Games keyed by (season, week, unordered franchise pair); unresolvable games are skipped."""
    index: dict[GameKey, list[G]] = {}
    for game in games:
        away = teams.resolve("nflverse", game.away_team, game.season).franchise_id
        home = teams.resolve("nflverse", game.home_team, game.season).franchise_id
        if away is None or home is None:
            continue
        index.setdefault((game.season, game.week, frozenset((away, home))), []).append(game)
    return index


def index_games(inputs: NflInputs, teams: NflTeamResolver) -> dict[GameKey, list[NflGame]]:
    return index_games_of(inputs.games, teams)


def _merge(first: ListingMatch, second: ListingMatch) -> ListingMatch:
    """Two listings of one game on the same network: keep the national line, fill the crew."""
    base, other = (
        (second, first)
        if second.is_national_line and not first.is_national_line
        else (
            first,
            second,
        )
    )
    crew = base.crew_names or other.crew_names
    return ListingMatch(
        game_id=base.game_id,
        network_id=base.network_id,
        window=base.window,
        crew_names=crew,
        is_national_line=base.is_national_line or other.is_national_line,
        intl_city=base.intl_city or other.intl_city,
        season=base.season,
        week=base.week,
        source_row_index=base.source_row_index,
    )


def match_506_listings(
    inputs: NflInputs,
    teams: NflTeamResolver,
    networks: NflNetworkResolver,
    games: Sequence[GameLike] | None = None,
) -> tuple[dict[str, ListingMatch], list[ListingReview]]:
    index = index_games_of(inputs.games if games is None else games, teams)
    reviews: list[ListingReview] = []
    by_game: dict[str, list[ListingMatch]] = {}

    def review(listing: NflListing506, reason: str) -> None:
        reviews.append(
            ListingReview(listing.season, listing.week, listing.source_row_index, reason)
        )

    for (season, week), listings in sorted(inputs.listings.items()):
        for listing in listings:
            away = teams.resolve("sports506", listing.away_raw, season).franchise_id
            home = teams.resolve("sports506", listing.home_raw, season).franchise_id
            if away is None or home is None or away == home:
                review(listing, "unresolved-team")
                continue
            candidates = index.get((season, week, frozenset((away, home))), [])
            if not candidates:
                review(listing, "no-game")
                continue
            if len(candidates) > 1:
                review(listing, "ambiguous-game")
                continue
            network_id = networks.resolve("sports506", listing.network_raw)
            if network_id is None and listing.network_raw.strip():
                review(listing, "unresolved-network")
            game = candidates[0]
            by_game.setdefault(game.game_id, []).append(
                ListingMatch(
                    game_id=game.game_id,
                    network_id=network_id,
                    window=listing.window,
                    crew_names=listing.crew_names,
                    is_national_line=listing.is_national_line,
                    intl_city=listing.intl_city,
                    season=season,
                    week=week,
                    source_row_index=listing.source_row_index,
                )
            )

    matches: dict[str, ListingMatch] = {}
    for game_id, found in by_game.items():
        merged = found[0]
        networks_seen = {m.network_id for m in found if m.network_id is not None}
        if len(networks_seen) > 1:
            for item in found:
                reviews.append(
                    ListingReview(item.season, item.week, item.source_row_index, "conflict")
                )
            matches[game_id] = replace(found[0], network_id=None)
            continue
        for later in found[1:]:
            merged = _merge(merged, later)
        if merged.network_id is None and networks_seen:
            (only,) = networks_seen
            merged = replace(merged, network_id=only)
        matches[game_id] = merged
    return matches, reviews
