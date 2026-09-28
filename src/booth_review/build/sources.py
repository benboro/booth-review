"""Per-season raw-source loading for the build layer: every cached CFBD,
506, and Ratings Reference file for one season, gathered into a single
`SeasonSources` the rest of the build (games, telecasts, joins) reads from.
Nothing here fetches; every endpoint file is read straight from
data/vault/raw/ if present, and treated as an empty list if not (a season
not yet collected for that endpoint, not an error).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from booth_review.config import DataPaths
from booth_review.resolve.inputs import (
    load_506_listings,
    load_cfbd_games,
    load_rr_records,
    vault_seasons,
)
from booth_review.sources.cfbd.parser import (
    CfbdGame,
    CfbdLine,
    CfbdMedia,
    CfbdPollWeek,
    CfbdPregameWp,
    parse_lines,
    parse_media,
    parse_rankings,
    parse_wp_pregame,
)
from booth_review.sources.ratingsref.parser import RRRecord
from booth_review.sources.sports506.parser import Listing506


@dataclass(frozen=True)
class SeasonSources:
    """Every raw source row cached for one season."""

    season: int
    games: list[CfbdGame]
    listings: list[Listing506]
    rr_records: list[RRRecord]
    rr_parse_errors: int
    media: list[CfbdMedia]
    lines: list[CfbdLine]
    rankings: list[CfbdPollWeek]
    wp_pregame: list[CfbdPregameWp]


def _load_cfbd_endpoint[T](
    paths: DataPaths, endpoint: str, season: int, parser: Callable[[bytes], list[T]]
) -> list[T]:
    path = paths.raw / "cfbd" / endpoint / f"{season}.json"
    if not path.is_file():
        return []
    return parser(path.read_bytes())


def load_season_sources(paths: DataPaths, season: int) -> SeasonSources:
    """Every raw source cached for `season`: CFBD games, 506 listings, RR
    records (plus their parse-error count), and the CFBD media/lines/
    rankings/wp_pregame endpoints. A missing endpoint file gives an empty
    list, not an error.
    """
    games = load_cfbd_games(paths, season)
    listings = load_506_listings(paths, season)
    rr_records, rr_parse_errors = load_rr_records(paths, season)
    media: list[CfbdMedia] = _load_cfbd_endpoint(paths, "media", season, parse_media)
    lines: list[CfbdLine] = _load_cfbd_endpoint(paths, "lines", season, parse_lines)
    rankings: list[CfbdPollWeek] = _load_cfbd_endpoint(paths, "rankings", season, parse_rankings)
    wp_pregame: list[CfbdPregameWp] = _load_cfbd_endpoint(
        paths, "wp_pregame", season, parse_wp_pregame
    )
    return SeasonSources(
        season=season,
        games=games,
        listings=listings,
        rr_records=rr_records,
        rr_parse_errors=rr_parse_errors,
        media=media,
        lines=lines,
        rankings=rankings,
        wp_pregame=wp_pregame,
    )


def load_all_sources(paths: DataPaths, seasons: Sequence[int] | None = None) -> list[SeasonSources]:
    """One SeasonSources per vault season, in ascending order. `seasons`
    defaults to `resolve.inputs.vault_seasons` (every season >= 2014 with a
    cached raw/cfbd/games/<season>.json file).
    """
    resolved_seasons = seasons if seasons is not None else vault_seasons(paths)
    return [load_season_sources(paths, season) for season in resolved_seasons]
