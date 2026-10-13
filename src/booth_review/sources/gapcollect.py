"""Shared pieces of the gap-only second-source collectors (04.19 D-11).

The TV Ratings Guide and Awful Announcing collectors both walk an index one
page at a time and fetch only posts that can still fill a gap. They share a
per-run request cap (`RequestBudget`), the summary merge, and the slug rule
for cache file names.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final

from booth_review.sources.base import BatchSummary, run_requests
from booth_review.transport.cache import RawCache
from booth_review.transport.types import FetchRequest

MAX_REQUESTS_DEFAULT: Final = 150

_SLUG_BAD = re.compile(r"[^a-z0-9-]+")
_SLUG_DASHES = re.compile(r"-{2,}")


def safe_slug(text: str) -> str:
    """Lower-case `text` and keep only [a-z0-9-] (runs of anything else become one dash)."""
    slug = _SLUG_DASHES.sub("-", _SLUG_BAD.sub("-", text.lower())).strip("-")
    return slug or "post"


@dataclass
class RequestBudget:
    """Caps the new requests one run may send; cached pages are free.

    `allows(cache, req)` is asked before each request: a cached page always
    passes, a new one spends one unit, and the first refusal sets `exhausted`.
    """

    limit: int
    spent: int = 0
    exhausted: bool = False

    def allows(self, cache: RawCache, req: FetchRequest) -> bool:
        if cache.status(req) == "cached":
            return True
        if self.spent >= self.limit:
            self.exhausted = True
            return False
        self.spent += 1
        return True


def empty_summary(source: str, season_label: str, *, dry_run: bool = False) -> BatchSummary:
    return BatchSummary(source, season_label, 0, 0, 0, 0, 0, 0, dry_run=dry_run)


def merge(a: BatchSummary, b: BatchSummary) -> BatchSummary:
    return BatchSummary(
        source=a.source,
        season_label=a.season_label,
        planned=a.planned + b.planned,
        cached=a.cached + b.cached,
        fetched=a.fetched + b.fetched,
        not_modified=a.not_modified + b.not_modified,
        failed=a.failed + b.failed,
        frozen_miss=a.frozen_miss + b.frozen_miss,
        new_urls=[*a.new_urls, *b.new_urls],
        failed_urls=[*a.failed_urls, *b.failed_urls],
        dry_run=a.dry_run and b.dry_run,
    )


@dataclass
class GapRun:
    """One season's live pass: requests go out one at a time under the budget."""

    cache: RawCache
    source: str
    season_label: str
    budget: RequestBudget
    summary: BatchSummary = field(init=False)

    def __post_init__(self) -> None:
        self.summary = empty_summary(self.source, self.season_label)

    def fetch(self, req: FetchRequest) -> bool:
        """Serve or fetch `req`; False when the budget refused it (stop the run).

        A 4xx is counted as failed and returns True (the run goes on); any
        other error propagates (robots disallow, unknown host, 5xx after retries).
        """
        if not self.budget.allows(self.cache, req):
            return False
        one = run_requests(
            self.cache,
            [req],
            source=self.source,
            season_label=self.season_label,
            dry_run=False,
        )
        self.summary = merge(self.summary, one)
        return True
