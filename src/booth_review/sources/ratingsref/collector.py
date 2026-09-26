"""RatingsRefCollector: fetches the RR sitemap and in-window CFB telecast records.

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
from dataclasses import dataclass
from datetime import UTC, date, datetime

from booth_review.config import DataPaths
from booth_review.errors import VaultStateError
from booth_review.sources.base import BatchSummary, run_requests
from booth_review.sources.ratingsref.lastmod import (
    append_lastmod,
    lastmod_ledger_exists,
    load_lastmods,
)
from booth_review.sources.ratingsref.sitemap import SitemapEntry, parse_sitemap, select_entries
from booth_review.transport.cache import CacheResult, RawCache
from booth_review.transport.types import FetchRequest

logger = logging.getLogger(__name__)

SITEMAP_URL = "https://ratingsreference.com/sitemap-telecasts.xml"

# D-08: at most this many capped fetches (advanced records, plus new records
# outside the current season) per refresh run; current-season new records are
# never capped (see RatingsRefCollector.refresh).
REFRESH_CAP_DEFAULT = 100

# D-07: the earliest season the refresh's lastmod diff considers.
FIRST_SEASON = 2014


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

    def counts(self) -> dict[str, int]:
        """Counts for vault.batch_message, in a fixed key order."""
        return {
            "fetched": self.fetched,
            "not_modified": self.not_modified,
            "failed": self.failed,
            "backlog": self.backlog,
        }


class RatingsRefCollector:
    """Plans, dry-runs, and fetches an in-window slice of RR CFB telecast records."""

    def __init__(
        self,
        cache: RawCache,
        paths: DataPaths,
        *,
        lock: Callable[[], AbstractContextManager[object]] | None = None,
    ) -> None:
        """`lock` (normally `VaultRepo.lock`) is held around each lastmod
        append, so an append never lands mid-commit or mid-rebase."""
        self._cache = cache
        self._paths = paths
        self._lock: Callable[[], AbstractContextManager[object]] = lock or contextlib.nullcontext

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

    def plan(self, entries: Sequence[SitemapEntry]) -> list[FetchRequest]:
        return [
            FetchRequest(
                source="ratingsref",
                season=entry.season,
                url=entry.json_url,
                cache_path=f"ratingsref/telecast/{entry.season}/{entry.telecast_id}.json",
            )
            for entry in entries
        ]

    def run(self, start: date, end: date, *, dry_run: bool) -> BatchSummary:
        season_label = f"{start}..{end}"
        xml = self.sitemap(dry_run=dry_run)

        if xml is None:
            logger.info("ratingsref: sitemap not cached; a run would fetch it first (1 request)")
            return BatchSummary(
                source="ratingsref",
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

        entries, _skipped = parse_sitemap(xml)
        selected = select_entries(entries, start, end)
        requests = self.plan(selected)
        entries_by_url = {entry.json_url: entry for entry in selected}

        def _on_fetched(req: FetchRequest, result: CacheResult) -> None:
            self._record_lastmod(entries_by_url[req.url])

        return run_requests(
            self._cache,
            requests,
            source="ratingsref",
            season_label=season_label,
            dry_run=dry_run,
            on_fetched=_on_fetched,
        )

    def refresh(
        self,
        *,
        current_season: int,
        cap: int = REFRESH_CAP_DEFAULT,
        first_season: int = FIRST_SEASON,
        dry_run: bool,
    ) -> RefreshSummary:
        """Re-fetch RR records whose sitemap <lastmod> advanced or that are
        newly listed, in any season 2014..current_season, frozen ones
        included (D-07). New current-season records are uncapped; every
        other qualifying record (including an advanced current-season
        record) is capped at `cap` per run, selected deterministically by
        (lastmod, telecast_id) ascending; the remainder is backlog (D-08).
        A fetched record overwrites its cached file (D-09).
        """
        if not lastmod_ledger_exists(self._paths):
            raise VaultStateError(
                "ledger/rr_lastmod.json(l) missing; refusing a refresh that would "
                "treat every record as new"
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

        entries, _skipped = parse_sitemap(xml)
        known = load_lastmods(self._paths)

        in_window = [e for e in entries if first_season <= e.season <= current_season]
        new_entries = [e for e in in_window if e.telecast_id not in known]
        advanced_entries = [
            e
            for e in in_window
            if e.telecast_id in known and known[e.telecast_id]["lastmod"] != e.lastmod
        ]
        qualifying = new_entries + advanced_entries

        uncapped_entries = [e for e in new_entries if e.season == current_season]
        uncapped_ids = {e.telecast_id for e in uncapped_entries}
        capped_candidates = sorted(
            (e for e in qualifying if e.telecast_id not in uncapped_ids),
            key=lambda e: (e.lastmod, e.telecast_id),
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
        }

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

            batch = run_requests(
                self._cache,
                requests,
                source="ratingsref",
                season_label=season_label,
                dry_run=False,
                refresh=True,
                on_fetched=_on_fetched,
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
            "uncapped_current=%d backlog=%d fetched=%d not_modified=%d failed=%d",
            summary.qualifying,
            summary.new,
            summary.advanced,
            summary.selected,
            summary.uncapped_current,
            summary.backlog,
            summary.fetched,
            summary.not_modified,
            summary.failed,
        )
        return summary

    def _record_lastmod(self, entry: SitemapEntry) -> None:
        with self._lock():
            append_lastmod(self._paths, entry, fetched_at=datetime.now(UTC))
