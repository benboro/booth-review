"""WikipediaCollector: plain-HTML requests for NFL season and stadium articles.

Only ``https://en.wikipedia.org/wiki/<year>_NFL_season`` (D-17) and the stadium
articles listed in ``NFL_WIKIPEDIA_STADIUM_PAGES`` (Phase 24, map coordinates) are
ever requested; the ``/w/`` and ``/api/`` paths are robots-disallowed and never built. Article
text is licensed CC BY-SA 4.0: only extracted facts (week, team pair, original
slot and network) are stored downstream, each with the article URL.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from booth_review.nfl.layout import (
    NFL_WIKIPEDIA_STADIUM_PAGES,
    wikipedia_path,
    wikipedia_stadium_path,
    wikipedia_stadium_url,
    wikipedia_url,
)
from booth_review.sources.base import BatchSummary, run_requests
from booth_review.transport.cache import RawCache
from booth_review.transport.types import FetchRequest

SOURCE: Final = "nfl_wikipedia"


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

    def plan_stadiums(self) -> list[FetchRequest]:
        """One request per distinct stadium article (a shared title is requested once)."""
        seen: set[str] = set()
        out: list[FetchRequest] = []
        for stadium_id, title in NFL_WIKIPEDIA_STADIUM_PAGES:
            if title in seen:
                continue
            seen.add(title)
            out.append(
                FetchRequest(
                    source=SOURCE,
                    season=None,
                    url=wikipedia_stadium_url(title),
                    cache_path=wikipedia_stadium_path(stadium_id),
                )
            )
        return out

    def run_stadiums(self, *, refresh: bool = False, dry_run: bool = False) -> BatchSummary:
        return run_requests(
            self._cache,
            self.plan_stadiums(),
            source=SOURCE,
            season_label="stadiums",
            dry_run=dry_run,
            refresh=refresh,
        )
