"""Awful Announcing crews as a second crew source (Phase 27, AAC-03).

AA's weekly college football announcing-schedule post (cached by
`booth-review collect aa --crews`) gives whole role-tagged booths. This pass
coalesces them with 506's crews:

- A hand-confirmed override always wins (04.3 D-09), untouched.
- A main telecast 506 listed no crew for (plotted, unrated or not yet plotted)
  takes AA's whole booth, credited "Awful Announcing" with the post's canonical
  URL. `crew_aa` marks it; `crew_patched` is never set, so the 506 match-rate
  separation holds.
- A 506 crew with the same people is kept and counted as an agreement.
- D-04: when AA's booth is a strict superset of 506's people, AA's whole booth
  wins whatever the page times say, and a review row is written.
- D-02: otherwise the newer page wins, AA's `article:modified_time` (else the
  fetched_at of the last HTTP 200 manifest line) against 506's saved_at (else
  fetched_at). A tie or a missing 506 time keeps 506. A review row is written.
- Booths stay whole (04.3 D-08): a telecast's main rows come from one page.
- D-03: only 2026 is read. Names unknown to people.csv become provisional persons.

Page content is private vault data: every error and count is count-only, review
rows go to the vault's interim/ folder through the caller, and tests use
invented names.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final

import polars as pl

from booth_review.build.crew_backup import ScheduledCrew
from booth_review.config import DataPaths
from booth_review.job.gaps506 import _entry_time
from booth_review.resolve.diagnose import UnmatchedRow, UnresolvedTeamRow
from booth_review.sources.aa.crews import (
    CREWS_SEASON,
    AaCrewsParseError,
    ParsedCrews,
    parse_crews,
)
from booth_review.sources.aa.index import on_host
from booth_review.sources.aa.parser import post_url_from_html
from booth_review.sources.second_rows import RejectedPage
from booth_review.transport.cache import Manifest

CREW_AA_LABEL = "Awful Announcing"
# The telecast_people.source value for AA rows.
CREW_AA_SOURCE = "crew_aa"
REVIEW_CREW_AA_DISAGREEMENTS = "review_crew_aa_disagreements"
REVIEW_CREW_AA_DISAGREEMENT_COLUMNS = (
    "telecast_id",
    "cfbd_game_id",
    "network_id",
    "season",
    "date_et",
    "pointer",
    "source_url",
    "s506_person_ids",
    "aa_names",
    "aa_person_ids",
    "winner",
    "relation",
    "aa_time",
    "s506_time",
    "aa_time_source",
)
_SOURCE: Final = "aa"
_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

_COUNT_KEYS: tuple[str, ...] = (
    "booths",
    "matched",
    "unmatched",
    "unresolved_team",
    "ambiguous",
    "no_game",
    "excluded_override",
    "unmapped_network",
    "network_mismatch",
    "no_telecast",
    "page_conflicts",
    "bad_url",
    "filled",
    "scheduled_filled",
    "kept_override",
    "agreements",
    "disagreements",
    "superset",
    "aa_won",
    "s506_won",
    "unparsed_lines",
    "tbd",
    "no_pbp",
    "undated_pages",
    "rejected_pages",
    "rows",
    "provisional_persons",
)


@dataclass(frozen=True)
class AaPage:
    """One cached crews post: its parse and the time the pass compares (D-02)."""

    path: str
    parsed: ParsedCrews
    aa_time: datetime | None
    aa_time_source: str  # modified | fetched | none


@dataclass(frozen=True)
class LoadedAaPages:
    pages: list[AaPage]
    rejected: list[RejectedPage] = field(default_factory=list)


@dataclass(frozen=True)
class CrewAaResult:
    telecasts: pl.DataFrame
    telecast_people: pl.DataFrame
    people: pl.DataFrame
    season_counts: dict[int, dict[str, int]]
    statuses: dict[str, str]  # filled | override | agrees | aa_won | superset | s506_won
    review_rows: list[dict[str, object]]
    new_name_rows: list[dict[str, object]]
    counts: dict[str, int]
    unmatched_rows: list[UnmatchedRow] = field(default_factory=list)
    unresolved_rows: list[UnresolvedTeamRow] = field(default_factory=list)
    scheduled_crews: dict[int, ScheduledCrew] = field(default_factory=dict)

    @property
    def filled_ids(self) -> frozenset[str]:
        return frozenset(tid for tid, status in self.statuses.items() if status == "filled")

    @property
    def won_ids(self) -> frozenset[str]:
        return frozenset(
            tid for tid, status in self.statuses.items() if status in ("aa_won", "superset")
        )


# -- Loading ---------------------------------------------------------------------------------


def _manifest_time(stamp: object) -> datetime | None:
    if not isinstance(stamp, str):
        return None
    try:
        return datetime.strptime(stamp, _TIME_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        return None


def load_aa_pages(paths: DataPaths, seasons: Sequence[int] | None = None) -> LoadedAaPages:
    """Every cached crews post (raw/aa/crews/<season>/wk-*.html), 2026 only (D-03).

    The time compared against 506 is the post's `article:modified_time`, else the
    fetched_at of the page's latest HTTP 200 manifest line (a 304 line is not a
    fetch of new content). A page with no on-host canonical link, or one the
    parser refuses, is returned in `rejected`; it never stops the build.
    """
    wanted = [CREWS_SEASON] if seasons is None else [s for s in seasons if s == CREWS_SEASON]
    found: list[tuple[int, str]] = []
    for season in wanted:
        directory = paths.raw / _SOURCE / "crews" / str(season)
        if directory.is_dir():
            found.extend(
                (season, f"{_SOURCE}/crews/{season}/{page.name}")
                for page in sorted(directory.glob("wk-*.html"))
            )
    if not found:
        return LoadedAaPages(pages=[])

    fetched: dict[str, datetime] = {}
    for entry in Manifest(paths.manifest).entries():
        path = entry.get("path")
        if entry.get("source") != _SOURCE or not isinstance(path, str):
            continue
        if entry.get("status") != 200:
            continue
        moment = _manifest_time(entry.get("fetched_at"))
        if moment is not None:
            fetched[path] = moment

    pages: list[AaPage] = []
    rejected: list[RejectedPage] = []
    for season, rel in found:
        html = (paths.raw / rel).read_text(encoding="utf-8", errors="replace")
        canonical = post_url_from_html(html)
        if canonical is None:
            rejected.append(RejectedPage(_SOURCE, season, rel, "no_canonical_url"))
            continue
        if on_host(canonical) is None:
            rejected.append(RejectedPage(_SOURCE, season, rel, "off_host_url"))
            continue
        try:
            parsed = parse_crews(html, season=season)
        except AaCrewsParseError:
            rejected.append(RejectedPage(_SOURCE, season, rel, "parse_error"))
            continue
        if parsed.modified is not None:
            aa_time: datetime | None = parsed.modified.astimezone(UTC)
            source = "modified"
        elif rel in fetched:
            aa_time, source = fetched[rel], "fetched"
        else:
            aa_time, source = None, "none"
        pages.append(AaPage(path=rel, parsed=parsed, aa_time=aa_time, aa_time_source=source))
    return LoadedAaPages(pages=pages, rejected=rejected)


def load_506_times(paths: DataPaths) -> dict[tuple[int, str], datetime]:
    """(season, 506 week label) -> when that week page was saved (saved_at, else
    fetched_at of its latest manifest line), as aware UTC datetimes."""
    latest: dict[str, dict[str, Any]] = {}
    for entry in Manifest(paths.manifest).entries():
        path = entry.get("path")
        if entry.get("source") == "sports506" and isinstance(path, str):
            latest[path] = entry
    out: dict[tuple[int, str], datetime] = {}
    for path, entry in latest.items():
        parts = path.split("/")
        if len(parts) != 3 or parts[0] != "sports506":
            continue
        name = parts[2]
        if not (name.startswith("wk-") and name.endswith(".html")):
            continue
        label = name[3:-5]
        if label != "B":
            label = label.lstrip("0") or "0"
        moment = _manifest_time(_entry_time(entry))
        if parts[1].isdecimal() and moment is not None:
            out[(int(parts[1]), label)] = moment
    return out
