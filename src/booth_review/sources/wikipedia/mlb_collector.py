"""MlbWikipediaCollector: plain /wiki/ requests for MLB postseason articles and lists.

Only ``https://en.wikipedia.org/wiki/<title>`` is ever requested; the ``/w/``
and ``/api/`` paths are robots-disallowed and never built. Text is CC BY-SA 4.0:
only extracted facts plus the article URL are stored downstream.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from booth_review.mlb.layout import (
    MLB_WIKIPEDIA_LIST_PAGES,
    mlb_wikipedia_list_path,
    mlb_wikipedia_list_url,
    mlb_wikipedia_path,
    mlb_wikipedia_url,
)
from booth_review.sources.base import BatchSummary, run_requests
from booth_review.transport.cache import RawCache
from booth_review.transport.types import FetchRequest

SOURCE: Final = "mlb_wikipedia"


class MlbWikipediaCollector:
    """Plans and fetches MLB postseason articles and broadcaster list pages."""

    def __init__(self, cache: RawCache) -> None:
        self._cache = cache

    def plan(self, season: int) -> list[FetchRequest]:
        return [
            FetchRequest(
                source=SOURCE,
                season=season,
                url=mlb_wikipedia_url(season),
                cache_path=mlb_wikipedia_path(season),
            )
        ]

    def plan_lists(self) -> list[FetchRequest]:
        return [
            FetchRequest(
                source=SOURCE,
                season=None,
                url=mlb_wikipedia_list_url(title),
                cache_path=mlb_wikipedia_list_path(slug),
            )
            for slug, title, _kind in MLB_WIKIPEDIA_LIST_PAGES
        ]

    def run(
        self,
        seasons: Sequence[int],
        *,
        lists: bool = False,
        refresh: bool = False,
        dry_run: bool = False,
    ) -> list[BatchSummary]:
        out = [
            run_requests(
                self._cache,
                self.plan(season),
                source=SOURCE,
                season_label=str(season),
                dry_run=dry_run,
                refresh=refresh,
            )
            for season in seasons
        ]
        if lists:
            out.append(
                run_requests(
                    self._cache,
                    self.plan_lists(),
                    source=SOURCE,
                    season_label="lists",
                    dry_run=dry_run,
                    refresh=refresh,
                )
            )
        return out
