"""RatingsRefCollector: fetches the RR sitemap and in-window telecast records for one league.

The sitemap is fetched at most once per UTC day (its cache_path is dated).
Every fetched record's sitemap <lastmod> is appended to ledger/rr_lastmod.jsonl
immediately after that record is fetched (D-13), so an interrupted run keeps
every lastmod it earned. The append holds the vault lock when one is given, and
the log is union-merged, so a local run and the job never lose each other's
lastmods (WR-02; see sources.ratingsref.lastmod).
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from booth_review.config import DataPaths
from booth_review.errors import VaultStateError
from booth_review.mlb.constants import MLB_REFRESH_CAP_DEFAULT
from booth_review.mlb.layout import mlb_rr_path
from booth_review.nfl.layout import nfl_rr_path
from booth_review.sources.base import BatchSummary, run_requests
from booth_review.sources.ratingsref.lastmod import (
    append_failure,
    append_lastmod,
    lastmod_has_prefix,
    lastmod_ledger_exists,
    load_failures,
    load_lastmods,
)
from booth_review.sources.ratingsref.sitemap import (
    SitemapEntry,
    parse_sitemap,
    select_entries,
)
from booth_review.transport.cache import CacheResult, RawCache
from booth_review.transport.types import FetchRequest

logger = logging.getLogger(__name__)

SITEMAP_URL = "https://ratingsreference.com/sitemap-telecasts.xml"

# D-08: at most this many capped fetches (advanced records, plus new records
# outside the current season) per refresh run; current-season new records are
# never capped (see RatingsRefCollector.refresh).
REFRESH_CAP_DEFAULT = 100

# D-09: NFL has about 100 records a season versus CFB's thousands; 40 covers a
# week of NFL revisions plus margin. Each league's run has its own cap, so a
# burst of NFL changes never delays CFB re-checks.
NFL_REFRESH_CAP_DEFAULT = 40

__all__ = ["MLB_REFRESH_CAP_DEFAULT"]

# Event pages are not regular telecasts; MLB's are never planned or refreshed.
MLB_EVENT_SLUG_PREFIXES = ("mlb-all-star-", "mlb-home-run-derby-")

Windows = Sequence[tuple[date, date]]


def _cfb_rr_path(season: int, telecast_id: str) -> str:
    return f"ratingsref/telecast/{season}/{telecast_id}.json"


@dataclass(frozen=True)
class LeagueSpec:
    """Per-league collector settings: source key, cache path, lastmod prefix, refresh cap."""

    source: Literal["ratingsref", "nfl_ratingsref", "mlb_ratingsref"]
    record_path: Callable[[int, str], str]
    lastmod_prefix: str | None
    refresh_cap: int
    event_prefixes: tuple[str, ...] = ()


LEAGUES: dict[str, LeagueSpec] = {
    "cfb": LeagueSpec("ratingsref", _cfb_rr_path, None, REFRESH_CAP_DEFAULT),
    "nfl": LeagueSpec("nfl_ratingsref", nfl_rr_path, "nfl-", NFL_REFRESH_CAP_DEFAULT),
    "mlb": LeagueSpec(
        "mlb_ratingsref",
        mlb_rr_path,
        "mlb-",
        MLB_REFRESH_CAP_DEFAULT,
        MLB_EVENT_SLUG_PREFIXES,
    ),
}


def _in_any_window(day: date, windows: Windows) -> bool:
    return any(start <= day <= end for start, end in windows)


@dataclass
class RunSummary(BatchSummary):
    """A BatchSummary that also carries the MLB scope skips (absent for cfb/nfl)."""

    skipped_event: int | None = None
    out_of_window: int | None = None

    def counts(self) -> dict[str, int]:
        counts = super().counts()
        if self.skipped_event is not None:
            counts["skipped_event"] = self.skipped_event
        if self.out_of_window is not None:
            counts["out_of_window"] = self.out_of_window
        return counts


# D-07: the earliest season the refresh's lastmod diff considers.
FIRST_SEASON = 2014

# WR-04: a record whose last refresh fetch failed (a 4xx) at the same sitemap
# lastmod it still has is held back this long, then retried after every other
# qualifying record. 6 days means about one retry a week at the job's
# Sunday/Wednesday cadence. A new lastmod clears the hold at once.
FAILED_RETRY_AFTER = timedelta(days=6)


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class RefreshSummary:
    """The result of one RatingsRefCollector.refresh() run (D-07/D-08/D-09)."""

    qualifying: int
    new: int
    advanced: int
    selected: int
    uncapped_current: int
    backlog: int
    fetched: int
    not_modified: int
    failed: int
    dry_run: bool
    deferred_failed: int = 0
    """Qualifying records held back because they failed recently (WR-04)."""
    out_of_window: int = 0
    """MLB only: sitemap entries outside every D-14 window (never candidates)."""
    skipped_event: int = 0
    """MLB only: all-star / home-run-derby entries (never candidates)."""

    def counts(self) -> dict[str, int]:
        """Counts for vault.batch_message, in a fixed key order."""
        return {
            "fetched": self.fetched,
            "not_modified": self.not_modified,
            "failed": self.failed,
            "backlog": self.backlog,
        }


class RatingsRefCollector:
    """Plans, dry-runs, and fetches RR telecast records for one league (default CFB)."""

    def __init__(
        self,
        cache: RawCache,
        paths: DataPaths,
        *,
        lock: Callable[[], AbstractContextManager[object]] | None = None,
        now: Callable[[], datetime] = _utc_now,
        league: str = "cfb",
    ) -> None:
        """`lock` (normally `VaultRepo.lock`) is held around each lastmod
        append, so an append never lands mid-commit or mid-rebase. `now`
        stamps lastmod/failure lines and times the failed-record hold."""
        if league not in LEAGUES:
            raise ValueError(f"unknown ratingsref league: {league!r}")
        self._league = league
        self._spec = LEAGUES[league]
        self._source = self._spec.source
        self._cache = cache
        self._paths = paths
        self._lock: Callable[[], AbstractContextManager[object]] = lock or contextlib.nullcontext
        self._now = now

    def _sitemap_cache_path(self, day: date) -> str:
        return f"ratingsref/sitemap/{day.isoformat()}.xml"

    def sitemap(self, *, dry_run: bool) -> bytes | None:
        """Fetch (or, in dry-run, look up) today's UTC-dated cached sitemap.

        In dry-run, returns the newest cached sitemap under raw/ratingsref/sitemap/,
        or None if none is cached yet, without sending anything.
        """
        today = datetime.now(UTC).date()

        if dry_run:
            sitemap_dir = self._paths.raw / "ratingsref" / "sitemap"
            if not sitemap_dir.is_dir():
                return None
            files = sorted(sitemap_dir.glob("*.xml"))
            if not files:
                return None
            return files[-1].read_bytes()

        req = FetchRequest(
            source="ratingsref",
            season=None,
            url=SITEMAP_URL,
            cache_path=self._sitemap_cache_path(today),
        )
        result = self._cache.get_or_fetch(req)
        return result.content

    def _record_path(self, entry: SitemapEntry) -> str:
        return self._spec.record_path(entry.season, entry.telecast_id)

    def _scope(
        self, entries: Sequence[SitemapEntry], windows: Windows | None
    ) -> tuple[list[SitemapEntry], int, int]:
        """Drop event slugs and out-of-window entries: (kept, skipped_event, out_of_window)."""
        kept: list[SitemapEntry] = []
        skipped_event = 0
        out_of_window = 0
        for entry in entries:
            if entry.telecast_id.startswith(self._spec.event_prefixes):
                skipped_event += 1
            elif windows is not None and not _in_any_window(entry.event_date, windows):
                out_of_window += 1
            else:
                kept.append(entry)
        return kept, skipped_event, out_of_window

    def plan(
        self, entries: Sequence[SitemapEntry], *, windows: Windows | None = None
    ) -> list[FetchRequest]:
        kept, _event, _out = self._scope(entries, windows)
        return [
            FetchRequest(
                source=self._source,
                season=entry.season,
                url=entry.json_url,
                cache_path=self._record_path(entry),
            )
            for entry in kept
        ]

    def run(
        self, start: date, end: date, *, dry_run: bool, windows: Windows | None = None
    ) -> BatchSummary:
        if self._league == "mlb" and windows is None:
            raise ValueError(
                "MLB collect needs the D-14 windows (2014-2026 postseason + 2026 regular season)"
            )
        season_label = f"{start}..{end}"
        xml = self.sitemap(dry_run=dry_run)

        if xml is None:
            logger.info("ratingsref: sitemap not cached; a run would fetch it first (1 request)")
            return BatchSummary(
                source=self._source,
                season_label=season_label,
                planned=0,
                cached=0,
                fetched=0,
                not_modified=0,
                failed=0,
                frozen_miss=0,
                new_urls=[],
                failed_urls=[],
                cfbd_calls=0,
                dry_run=dry_run,
            )

        entries, _skipped = parse_sitemap(xml, league=self._league)
        selected, skipped_event, out_of_window = self._scope(
            select_entries(entries, start, end), windows
        )
        requests = self.plan(selected)
        entries_by_url = {entry.json_url: entry for entry in selected}

        def _on_fetched(req: FetchRequest, result: CacheResult) -> None:
            self._record_lastmod(entries_by_url[req.url])

        batch = run_requests(
            self._cache,
            requests,
            source=self._source,
            season_label=season_label,
            dry_run=dry_run,
            on_fetched=_on_fetched,
        )
        if self._league != "mlb" and windows is None:
            return batch
        return RunSummary(
            **asdict(batch),
            skipped_event=skipped_event if self._league == "mlb" else None,
            out_of_window=out_of_window if windows is not None else None,
        )

    def refresh(
        self,
        *,
        current_season: int,
        cap: int | None = None,
        first_season: int = FIRST_SEASON,
        dry_run: bool,
        windows: Windows | None = None,
    ) -> RefreshSummary:
        """Re-fetch RR records whose sitemap <lastmod> advanced or that are
        newly listed, in any season 2014..current_season, frozen ones
        included (D-07). New current-season records are uncapped; every
        other qualifying record (including an advanced current-season
        record) is capped at `cap` per run, selected deterministically:
        current-season records first (an advanced current-season record is
        most likely a revised viewership figure, and must not wait behind a
        mass revision of older seasons, WR-05), then by (lastmod,
        telecast_id) ascending; the remainder is backlog (D-08). A fetched
        record overwrites its cached file (D-09).

        A record whose last fetch failed (a 4xx, recorded in the lastmod log)
        at the lastmod the sitemap still lists is held back for
        FAILED_RETRY_AFTER (counted in `deferred_failed`, neither selected
        nor backlog), and after that sorts behind every other capped
        candidate, so a record that keeps failing can never take the cap
        from the rest of the queue (WR-04).

        `windows` (D-14) keeps only entries whose event_date falls inside one;
        league mlb requires it. Event slugs and out-of-window entries are dropped
        before new/advanced selection, so they are never candidates or backlog.
        `cap` defaults to the league's own cap.
        """
        if cap is None:
            cap = self._spec.refresh_cap
        if self._league == "mlb" and windows is None:
            raise ValueError(
                "MLB refresh needs the D-14 windows (2014-2026 postseason + 2026 regular season)"
            )
        if not lastmod_ledger_exists(self._paths):
            raise VaultStateError(
                "ledger/rr_lastmod.json(l) missing; refusing a refresh that would "
                "treat every record as new"
            )
        prefix = self._spec.lastmod_prefix
        if prefix is not None and not lastmod_has_prefix(self._paths, prefix):
            label = self._league.upper()
            raise VaultStateError(
                f"no {label} lastmod lines yet; run `booth-review collect ratingsref "
                f"--league {self._league} --season 2014-{current_season}` first, or every "
                f"{label} record would queue as new"
            )

        season_label = f"{first_season}-{current_season}"
        xml = self.sitemap(dry_run=dry_run)

        if xml is None:
            logger.info(
                "ratingsref refresh: sitemap not cached; a run would fetch it first (1 request)"
            )
            return RefreshSummary(
                qualifying=0,
                new=0,
                advanced=0,
                selected=0,
                uncapped_current=0,
                backlog=0,
                fetched=0,
                not_modified=0,
                failed=0,
                dry_run=dry_run,
            )

        entries, _skipped = parse_sitemap(xml, league=self._league)
        entries, skipped_event, out_of_window = self._scope(entries, windows)
        known = load_lastmods(self._paths)

        in_window = [e for e in entries if first_season <= e.season <= current_season]
        new_entries = [e for e in in_window if e.telecast_id not in known]
        advanced_entries = [
            e
            for e in in_window
            if e.telecast_id in known and known[e.telecast_id]["lastmod"] != e.lastmod
        ]
        qualifying = new_entries + advanced_entries

        failures = load_failures(self._paths)
        failed_before = {
            e.telecast_id
            for e in qualifying
            if e.telecast_id in failures and failures[e.telecast_id].lastmod == e.lastmod
        }
        hold_cutoff = self._now() - FAILED_RETRY_AFTER
        deferred_ids = {
            telecast_id
            for telecast_id in failed_before
            if failures[telecast_id].failed_at > hold_cutoff
        }
        eligible = [e for e in qualifying if e.telecast_id not in deferred_ids]

        uncapped_entries = [
            e
            for e in new_entries
            if e.season == current_season and e.telecast_id not in deferred_ids
        ]
        uncapped_ids = {e.telecast_id for e in uncapped_entries}
        capped_candidates = sorted(
            (e for e in eligible if e.telecast_id not in uncapped_ids),
            key=lambda e: (
                e.telecast_id in failed_before,
                e.season != current_season,
                e.lastmod,
                e.telecast_id,
            ),
        )
        selected_capped = capped_candidates[:cap]
        backlog_entries = capped_candidates[cap:]

        selected = uncapped_entries + selected_capped
        entries_by_url = {entry.json_url: entry for entry in selected}
        requests = self.plan(selected)

        counts = {
            "qualifying": len(qualifying),
            "new": len(new_entries),
            "advanced": len(advanced_entries),
            "selected": len(selected),
            "uncapped_current": len(uncapped_entries),
            "backlog": len(backlog_entries),
            "deferred_failed": len(deferred_ids),
        }
        if self._league == "mlb":
            counts["out_of_window"] = out_of_window
            counts["skipped_event"] = skipped_event

        if dry_run:
            summary = RefreshSummary(
                **counts,
                fetched=0,
                not_modified=0,
                failed=0,
                dry_run=True,
            )
        else:

            def _on_fetched(req: FetchRequest, result: CacheResult) -> None:
                self._record_lastmod(entries_by_url[req.url])

            def _on_failed(req: FetchRequest, status: int) -> None:
                self._record_failure(entries_by_url[req.url], status)

            batch = run_requests(
                self._cache,
                requests,
                source=self._source,
                season_label=season_label,
                dry_run=False,
                refresh=True,
                on_fetched=_on_fetched,
                on_failed=_on_failed,
            )
            summary = RefreshSummary(
                **counts,
                fetched=batch.fetched,
                not_modified=batch.not_modified,
                failed=batch.failed,
                dry_run=False,
            )

        logger.info(
            "ratingsref refresh: qualifying=%d new=%d advanced=%d selected=%d "
            "uncapped_current=%d backlog=%d deferred_failed=%d fetched=%d not_modified=%d "
            "failed=%d",
            summary.qualifying,
            summary.new,
            summary.advanced,
            summary.selected,
            summary.uncapped_current,
            summary.backlog,
            summary.deferred_failed,
            summary.fetched,
            summary.not_modified,
            summary.failed,
        )
        return summary

    def _record_lastmod(self, entry: SitemapEntry) -> None:
        with self._lock():
            append_lastmod(self._paths, entry, fetched_at=self._now())

    def _record_failure(self, entry: SitemapEntry, status: int) -> None:
        with self._lock():
            append_failure(self._paths, entry, status=status, failed_at=self._now())
