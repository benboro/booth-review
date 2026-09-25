"""RatingsRefCollector: fetches the RR sitemap and in-window CFB telecast records.

The sitemap is fetched at most once per UTC day (its cache_path is dated).
Every fetched record's sitemap <lastmod> is written to ledger/rr_lastmod.json
immediately after that record is fetched (D-13), so an interrupted run keeps
every lastmod it earned.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from datetime import UTC, date, datetime

from booth_review.config import DataPaths
from booth_review.sources.base import BatchSummary, run_requests
from booth_review.sources.ratingsref.sitemap import SitemapEntry, parse_sitemap, select_entries
from booth_review.transport.cache import CacheResult, RawCache, atomic_write_json
from booth_review.transport.types import FetchRequest

logger = logging.getLogger(__name__)

SITEMAP_URL = "https://ratingsreference.com/sitemap-telecasts.xml"


class RatingsRefCollector:
    """Plans, dry-runs, and fetches an in-window slice of RR CFB telecast records."""

    def __init__(self, cache: RawCache, paths: DataPaths) -> None:
        self._cache = cache
        self._paths = paths

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

    def _record_lastmod(self, entry: SitemapEntry) -> None:
        path = self._paths.rr_lastmod
        data: dict[str, dict[str, str]] = {}
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
        data[entry.telecast_id] = {
            "lastmod": entry.lastmod,
            "fetched_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "record_url": entry.record_url,
        }
        atomic_write_json(path, data)
