"""Shared collector run loop: BatchSummary and run_requests.

Every collector (506, Ratings Reference, CFBD) turns its own inputs into a
list of FetchRequest, then hands them to `run_requests`, which is the one
place that knows how to dry-run (cache.status, zero requests sent) or fetch
(cache.get_or_fetch) a batch and tally the outcome (FOUND-01, D-16).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from booth_review.errors import FetchError
from booth_review.transport.cache import CacheResult, RawCache
from booth_review.transport.types import FetchRequest

logger = logging.getLogger(__name__)

_LOG_EVERY = 25


@dataclass
class BatchSummary:
    """The result of planning or running one collector batch."""

    source: str
    season_label: str
    planned: int
    cached: int
    fetched: int
    not_modified: int
    failed: int
    frozen_miss: int
    new_urls: list[str] = field(default_factory=list)
    failed_urls: list[str] = field(default_factory=list)
    cfbd_calls: int = 0
    dry_run: bool = False

    def counts(self) -> dict[str, int]:
        """Counts for vault.batch_message, in a fixed key order."""
        return {
            "fetched": self.fetched,
            "cached": self.cached,
            "not_modified": self.not_modified,
            "failed": self.failed,
        }


def run_requests(
    cache: RawCache,
    requests: Sequence[FetchRequest],
    *,
    source: str,
    season_label: str,
    dry_run: bool,
    bearer_token: str | None = None,
    on_fetched: Callable[[FetchRequest, CacheResult], None] | None = None,
) -> BatchSummary:
    """Plan or run one batch of requests through `cache`.

    In dry-run, only `cache.status` is consulted for each request and no
    request is ever sent. Otherwise each request goes through
    `cache.get_or_fetch` in order; a 4xx (other than 429) is recorded as
    failed and the batch continues, but every other exception (a 5xx that
    survived retries, a transport error, FrozenSeasonError,
    RobotsDisallowedError, or any budget error) propagates immediately so
    the caller can commit what was fetched so far and stop.
    """
    if dry_run:
        return _plan_summary(cache, requests, source=source, season_label=season_label)

    cached = fetched = not_modified = failed = 0
    new_urls: list[str] = []
    failed_urls: list[str] = []

    for i, req in enumerate(requests, start=1):
        try:
            result = cache.get_or_fetch(req, bearer_token=bearer_token)
        except FetchError as exc:
            status = exc.status_code
            if status is not None and 400 <= status < 500 and status != 429:
                failed += 1
                failed_urls.append(req.url)
                continue
            raise

        if result.outcome == "cached":
            cached += 1
        elif result.outcome == "fetched":
            fetched += 1
            new_urls.append(req.url)
            if on_fetched is not None:
                on_fetched(req, result)
        elif result.outcome == "not_modified":
            not_modified += 1

        if i % _LOG_EVERY == 0:
            logger.info(
                "collect %s: %d/%d done (cached=%d fetched=%d not_modified=%d failed=%d)",
                source,
                i,
                len(requests),
                cached,
                fetched,
                not_modified,
                failed,
            )

    return BatchSummary(
        source=source,
        season_label=season_label,
        planned=len(requests),
        cached=cached,
        fetched=fetched,
        not_modified=not_modified,
        failed=failed,
        frozen_miss=0,
        new_urls=new_urls,
        failed_urls=failed_urls,
        cfbd_calls=fetched + not_modified,
        dry_run=False,
    )


def _plan_summary(
    cache: RawCache,
    requests: Sequence[FetchRequest],
    *,
    source: str,
    season_label: str,
) -> BatchSummary:
    cached = 0
    frozen_miss = 0
    new_urls: list[str] = []

    for req in requests:
        status = cache.status(req)
        if status == "cached":
            cached += 1
        elif status == "frozen-miss":
            frozen_miss += 1
        else:
            new_urls.append(req.url)

    return BatchSummary(
        source=source,
        season_label=season_label,
        planned=len(requests),
        cached=cached,
        fetched=0,
        not_modified=0,
        failed=0,
        frozen_miss=frozen_miss,
        new_urls=new_urls,
        failed_urls=[],
        cfbd_calls=len(new_urls),
        dry_run=True,
    )
