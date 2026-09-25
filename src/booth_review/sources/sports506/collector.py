"""Sports506Collector: plans and fetches the 506 Sports weekly CFB pages.

One season is exactly 18 pages: weeks 0 through 16 plus the bowls/CFP page
(wk=B), per docs/PLAN.md section 4.1's documented URL pattern.
"""

from __future__ import annotations

from booth_review.sources.base import BatchSummary, run_requests
from booth_review.transport.cache import RawCache
from booth_review.transport.types import FetchRequest

WEEK_LABELS: list[str] = [str(n) for n in range(17)] + ["B"]


def _cache_name(label: str) -> str:
    return label if label == "B" else label.zfill(2)


class Sports506Collector:
    """Plans, dry-runs, and fetches one season of 506 week pages."""

    def __init__(self, cache: RawCache) -> None:
        self._cache = cache

    def plan(self, season: int) -> list[FetchRequest]:
        return [
            FetchRequest(
                source="sports506",
                season=season,
                url=f"https://506sports.com/ncaaf.php?yr={season}&wk={label}",
                cache_path=f"sports506/{season}/wk-{_cache_name(label)}.html",
            )
            for label in WEEK_LABELS
        ]

    def run(self, season: int, *, dry_run: bool) -> BatchSummary:
        requests = self.plan(season)
        return run_requests(
            self._cache,
            requests,
            source="sports506",
            season_label=str(season),
            dry_run=dry_run,
        )
