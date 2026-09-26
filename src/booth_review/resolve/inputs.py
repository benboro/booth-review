"""Raw-input loaders for the join layer (JOIN-02..04): every season's cached
CFBD games, 506 listings, and RR records, read straight from data already
cached under data/vault/raw/. No HTTP client is built here (T-01-51);
spike/join.py's private per-season loaders now delegate to these.
"""

from __future__ import annotations

from pathlib import Path

from booth_review.config import DataPaths
from booth_review.errors import ParseError
from booth_review.sources.cfbd.parser import CfbdGame, parse_games
from booth_review.sources.ratingsref.parser import RRRecord, parse_record
from booth_review.sources.sports506.parser import Listing506, parse_week_page

_FIRST_SEASON = 2014


def vault_seasons(paths: DataPaths) -> list[int]:
    """Every season >= 2014 with a cached raw/cfbd/games/<season>.json file,
    sorted ascending. [] when raw/cfbd/games/ doesn't exist yet.
    """
    games_dir = paths.raw / "cfbd" / "games"
    if not games_dir.is_dir():
        return []
    seasons: list[int] = []
    for game_file in games_dir.glob("*.json"):
        try:
            season = int(game_file.stem)
        except ValueError:
            continue
        if season >= _FIRST_SEASON:
            seasons.append(season)
    return sorted(seasons)


def load_cfbd_games(paths: DataPaths, season: int) -> list[CfbdGame]:
    """raw/cfbd/games/<season>.json, parsed; [] when the file is missing (a
    season not yet collected, not an error)."""
    games_path = paths.raw / "cfbd" / "games" / f"{season}.json"
    if not games_path.is_file():
        return []
    return parse_games(games_path.read_bytes())


def _week_sort_key_and_label(file_name: str) -> tuple[int, str] | None:
    """ "wk-01.html" -> (1, "1"); "wk-B.html" -> (999, "B"); None for any
    other file name (not a recognized week page)."""
    if not (file_name.startswith("wk-") and file_name.endswith(".html")):
        return None
    raw_label = file_name[len("wk-") : -len(".html")]
    if raw_label == "B":
        return 999, "B"
    if raw_label.isdigit():
        return int(raw_label), str(int(raw_label))
    return None


def load_506_listings(paths: DataPaths, season: int) -> list[Listing506]:
    """Every wk-*.html 506 page cached for `season`, parsed in week order
    (0..16, then B). Generalizes off whatever week files are actually
    present, rather than a hardcoded label list, so a season with fewer
    weeks (e.g. 2020) or a growing 2026 in-season vault both work.
    """
    season_dir = paths.raw / "sports506" / str(season)
    if not season_dir.is_dir():
        return []

    week_files: list[tuple[int, str, Path]] = []
    for file_path in season_dir.glob("wk-*.html"):
        parsed = _week_sort_key_and_label(file_path.name)
        if parsed is None:
            continue
        sort_key, label = parsed
        week_files.append((sort_key, label, file_path))
    week_files.sort(key=lambda item: item[0])

    listings: list[Listing506] = []
    for _sort_key, label, file_path in week_files:
        listings.extend(parse_week_page(file_path.read_bytes(), season=season, week_label=label))
    return listings


def load_rr_records(paths: DataPaths, season: int) -> tuple[list[RRRecord], int]:
    """Every raw/ratingsref/telecast/<season>/*.json record, parsed in
    sorted file order. A file that fails to parse is counted in the second
    element (never silently dropped, per JOIN-04/AUDIT-01's completeness
    needs) but is not itself returned in the records list.
    """
    records: list[RRRecord] = []
    parse_error_count = 0
    season_dir = paths.raw / "ratingsref" / "telecast" / str(season)
    if not season_dir.is_dir():
        return records, parse_error_count
    for record_path in sorted(season_dir.glob("*.json")):
        try:
            records.append(parse_record(record_path.read_bytes()))
        except ParseError:
            parse_error_count += 1
    return records, parse_error_count
