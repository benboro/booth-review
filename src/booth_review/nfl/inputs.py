"""Load every NFL input from raw/nfl/ only (D-20 step 2).

CFB raw directories are never read; every path comes from nfl/layout.py.
Pages and records that fail to parse are counted, not fatal, and the counts
never carry a file name or content.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from booth_review.config import DataPaths
from booth_review.errors import ParseError, VaultStateError
from booth_review.nfl.crew_aa import NflAaPage
from booth_review.nfl.layout import (
    NFLVERSE_SCHEDULES_PATH,
    nfl_506_path,
    nfl_aa_crews_path,
    nfl_rr_path,
    nflverse_pbp_path,
    wikipedia_path,
)
from booth_review.nfl.schedule import NflGame, UpcomingNflGame, parse_schedules, parse_upcoming
from booth_review.sources.aa.crews import AaCrewsParseError, parse_crews
from booth_review.sources.ratingsref.parser import RRRecord, parse_record
from booth_review.sources.sports506.nfl_parser import NflListing506, parse_nfl_week_page
from booth_review.sources.wikipedia.parser import ChangesResult, parse_scheduling_changes
from booth_review.transport.cache import Manifest

_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


@dataclass(frozen=True)
class NflInputs:
    games: tuple[NflGame, ...]
    listings: Mapping[tuple[int, int], tuple[NflListing506, ...]]
    listing_parse_failures: int
    rr_records: Mapping[int, tuple[RRRecord, ...]]
    changes: Mapping[int, ChangesResult]
    pbp_paths: Mapping[int, Path]
    rr_parse_failures: int = 0
    change_parse_failures: int = 0
    seasons: tuple[int, ...] = field(default_factory=tuple)
    #: Every regular-season row with a week, scheduled or not (Phase 18).
    upcoming: tuple[UpcomingNflGame, ...] = ()
    #: Regular-season rows with no week yet: counted, never placed.
    upcoming_unplaced: int = 0
    #: Hand-imported Awful Announcing weekly posts (`booth-review import aa`).
    aa_pages: tuple[NflAaPage, ...] = ()
    aa_parse_failures: int = 0
    #: Each 506 week page's browser save time (else its import time), for the AA pass.
    s506_times: Mapping[tuple[int, int], datetime] = field(default_factory=dict)


def _manifest_time(stamp: object) -> datetime | None:
    if not isinstance(stamp, str):
        return None
    try:
        return datetime.strptime(stamp, _TIME_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        return None


def _page_times(paths: DataPaths) -> dict[str, datetime]:
    """The newest written manifest line's saved_at (else fetched_at) per NFL raw path."""
    times: dict[str, datetime] = {}
    if not paths.manifest.is_file():
        return times
    for entry in Manifest(paths.manifest).entries():
        path = entry.get("path")
        if not isinstance(path, str) or not path.startswith("nfl/") or entry.get("status") != 200:
            continue
        moment = _manifest_time(entry.get("saved_at")) or _manifest_time(entry.get("fetched_at"))
        if moment is not None:
            times[path] = moment
    return times


def _week_of(file_name: str) -> int | None:
    if not (file_name.startswith("wk-") and file_name.endswith(".html")):
        return None
    label = file_name[len("wk-") : -len(".html")]
    return int(label) if label.isdigit() else None


def load_nfl_inputs(paths: DataPaths, seasons: Sequence[int]) -> NflInputs:
    """Read schedules, 506 pages, RR records, Wikipedia articles and pbp paths."""
    raw = paths.raw
    schedule_path = raw / NFLVERSE_SCHEDULES_PATH
    if not schedule_path.is_file():
        raise VaultStateError("nfl schedules missing: run booth-review collect nflverse first")
    schedule_bytes = schedule_path.read_bytes()
    games = parse_schedules(schedule_bytes, seasons=seasons)
    upcoming, upcoming_unplaced = parse_upcoming(schedule_bytes, seasons=seasons)

    listings: dict[tuple[int, int], tuple[NflListing506, ...]] = {}
    listing_failures = 0
    rr_records: dict[int, tuple[RRRecord, ...]] = {}
    rr_failures = 0
    changes: dict[int, ChangesResult] = {}
    change_failures = 0
    pbp_paths: dict[int, Path] = {}
    page_times = _page_times(paths)
    aa_pages: list[NflAaPage] = []
    aa_failures = 0
    s506_times: dict[tuple[int, int], datetime] = {}

    for season in sorted(set(seasons)):
        week_dir = (raw / nfl_506_path(season, 1)).parent
        if week_dir.is_dir():
            pages = [(w, p) for p in week_dir.glob("wk-*.html") if (w := _week_of(p.name))]
            for week, page in sorted(pages):
                try:
                    listings[(season, week)] = tuple(
                        parse_nfl_week_page(page.read_bytes(), season=season, week=week)
                    )
                except ParseError:
                    listing_failures += 1
                saved = page_times.get(nfl_506_path(season, week))
                if saved is not None:
                    s506_times[(season, week)] = saved

        aa_dir = (raw / nfl_aa_crews_path(season, 1)).parent
        if aa_dir.is_dir():
            posts = [(w, p) for p in aa_dir.glob("wk-*.html") if (w := _week_of(p.name))]
            for week, post in sorted(posts):
                try:
                    parsed = parse_crews(
                        post.read_text(encoding="utf-8", errors="replace"), season=season
                    )
                except AaCrewsParseError:
                    aa_failures += 1
                    continue
                aa_time = parsed.modified or page_times.get(nfl_aa_crews_path(season, week))
                aa_pages.append(NflAaPage(season, week, parsed, aa_time))

        rr_dir = (raw / nfl_rr_path(season, "x")).parent
        if rr_dir.is_dir():
            records: list[RRRecord] = []
            for record_path in sorted(rr_dir.glob("*.json")):
                try:
                    records.append(parse_record(record_path.read_bytes()))
                except ParseError:
                    rr_failures += 1
            rr_records[season] = tuple(records)

        article = raw / wikipedia_path(season)
        if article.is_file():
            try:
                changes[season] = parse_scheduling_changes(article.read_bytes(), season=season)
            except ParseError:
                change_failures += 1

        pbp = raw / nflverse_pbp_path(season)
        if pbp.is_file():
            pbp_paths[season] = pbp

    return NflInputs(
        games=tuple(games),
        listings=listings,
        listing_parse_failures=listing_failures,
        rr_records=rr_records,
        changes=changes,
        pbp_paths=pbp_paths,
        rr_parse_failures=rr_failures,
        change_parse_failures=change_failures,
        seasons=tuple(sorted(set(seasons))),
        upcoming=tuple(upcoming),
        upcoming_unplaced=upcoming_unplaced,
        aa_pages=tuple(aa_pages),
        aa_parse_failures=aa_failures,
        s506_times=s506_times,
    )
