"""WikipediaCollector: one plain-HTML request per NFL season article (D-17).

Only ``https://en.wikipedia.org/wiki/<year>_NFL_season`` is ever requested;
the ``/w/`` and ``/api/`` paths are robots-disallowed and never built. Article
text is licensed CC BY-SA 4.0: only extracted facts (week, team pair, original
slot and network) are stored downstream, each with the article URL.
"""

from __future__ import annotations

from collections.abc import Sequence

from booth_review.nfl.layout import wikipedia_path, wikipedia_url
from booth_review.sources.base import BatchSummary, run_requests
from booth_review.transport.cache import RawCache
from booth_review.transport.types import FetchRequest

SOURCE = "nfl_wikipedia"


class WikipediaCollector:
    """Plans and fetches NFL season articles, one request per season."""

    def __init__(self, cache: RawCache) -> None:
        self._cache = cache

    def plan(self, season: int) -> list[FetchRequest]:
        return [
            FetchRequest(
                source=SOURCE,
                season=season,
                url=wikipedia_url(season),
                cache_path=wikipedia_path(season),
            )
        ]

    def run(
        self, seasons: Sequence[int], *, refresh: bool = False, dry_run: bool = False
    ) -> list[BatchSummary]:
        return [
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
