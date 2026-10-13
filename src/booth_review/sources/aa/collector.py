"""AaCollector: gap-week collection from Awful Announcing (04.19 D-11).

AA publishes one college-football viewership roundup per week, its slug
saying ``college-football-week-<n>-viewership`` with the season's year. A gap
date maps to the CFBD regular-season week whose games include it; ESPN-style
"Week 0" naming can put AA's number one below CFBD's, so a slug week w is
kept when w or w + 1 is a gap week, and only when the slug's year equals the
season. Postseason gap dates have no week roundup and plan nothing here.

The index is the sitemap: the sitemap index (cached once, at
``aa/index/sitemap-1.xml`` where the 04.19-32 policy check stored it), then
only the post sitemaps whose lastmod run spans the season's gap weeks
(``aa/index/<name>.xml``), then the matching posts
(``aa/<season>/posts/<slug>.html``). Every request goes through RawCache and
the standard client; a cached file is never re-fetched.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from datetime import date, timedelta
from typing import Final

from booth_review.sources.aa.index import (
    SITEMAP_INDEX_URL,
    SitemapRef,
    UrlEntry,
    parse_sitemap,
    select_post_sitemaps,
    week_of_slug,
    year_of_slug,
)
from booth_review.sources.base import BatchSummary, run_requests
from booth_review.sources.gapcollect import (
    MAX_REQUESTS_DEFAULT,
    GapRun,
    RequestBudget,
    safe_slug,
)
from booth_review.transport.cache import RawCache
from booth_review.transport.types import FetchRequest

SOURCE: Final = "aa"
# A week's roundup appears a few days after its games; allow three weeks.
PUBLISH_LAG: Final = timedelta(days=21)

INDEX_REQUEST: Final = FetchRequest(
    source=SOURCE, season=None, url=SITEMAP_INDEX_URL, cache_path="aa/index/sitemap-1.xml"
)


def gap_weeks(gap_dates: Iterable[date], week_of: Mapping[date, Collection[int]]) -> set[int]:
    """CFBD regular-season weeks holding a gap date (dates with no week drop out)."""
    return {week for day in gap_dates for week in week_of.get(day, ())}


def week_gap_dates(
    gap_dates: Iterable[date], week_of: Mapping[date, Collection[int]]
) -> list[date]:
    return sorted(day for day in gap_dates if week_of.get(day))


def wanted_entry(entry: UrlEntry, season: int, weeks: Collection[int]) -> bool:
    slug = entry.slug
    week = week_of_slug(slug)
    if week is None or year_of_slug(slug) != season:
        return False
    return week in weeks or week + 1 in weeks


def sitemap_request(ref: SitemapRef) -> FetchRequest:
    return FetchRequest(
        source=SOURCE,
        season=None,
        url=ref.url,
        cache_path=f"aa/index/{safe_slug(ref.name)}.xml",
    )


def post_request(season: int, entry: UrlEntry) -> FetchRequest:
    return FetchRequest(
        source=SOURCE,
        season=season,
        url=entry.url,
        cache_path=f"aa/{season}/posts/{safe_slug(entry.slug)}.html",
    )


class AaCollector:
    """Plans and runs the gap-week AA pass, one season at a time."""

    def __init__(self, cache: RawCache, week_of: Mapping[date, Collection[int]]) -> None:
        self._cache = cache
        self._week_of = week_of

    # -- planning (offline: reads cached files only) ------------------------------------

    def _child_requests(self, gap_dates: Collection[date]) -> list[FetchRequest]:
        days = week_gap_dates(gap_dates, self._week_of)
        if not days:
            return []
        body = self._cache.read_cached(INDEX_REQUEST)
        if body is None:
            return []
        refs = parse_sitemap(body).sitemaps
        return [
            sitemap_request(ref)
            for ref in select_post_sitemaps(refs, days[0], days[-1] + PUBLISH_LAG)
        ]

    def plan_index(self, season: int, gap_dates: Collection[date]) -> list[FetchRequest]:
        if not week_gap_dates(gap_dates, self._week_of):
            return []
        return [INDEX_REQUEST, *self._child_requests(gap_dates)]

    def _posts_in(
        self, children: Sequence[FetchRequest], season: int, weeks: Collection[int]
    ) -> list[UrlEntry]:
        entries: list[UrlEntry] = []
        for req in children:
            body = self._cache.read_cached(req)
            if body is None:
                continue
            entries.extend(
                entry for entry in parse_sitemap(body).urls if wanted_entry(entry, season, weeks)
            )
        return entries

    def plan_posts(self, season: int, gap_dates: Collection[date]) -> list[FetchRequest]:
        """Post requests from the cached sitemaps only."""
        weeks = gap_weeks(gap_dates, self._week_of)
        seen: set[str] = set()
        requests: list[FetchRequest] = []
        for entry in self._posts_in(self._child_requests(gap_dates), season, weeks):
            if entry.url not in seen:
                seen.add(entry.url)
                requests.append(post_request(season, entry))
        return requests

    def plan(self, season: int, gap_dates: Collection[date]) -> list[FetchRequest]:
        return [*self.plan_index(season, gap_dates), *self.plan_posts(season, gap_dates)]

    # -- running -----------------------------------------------------------------------

    def run_season(
        self,
        season: int,
        gap_dates: Collection[date],
        *,
        dry_run: bool,
        budget: RequestBudget,
    ) -> BatchSummary:
        """Dry run: counts for `plan`. Live: the sitemap index, then each
        selected post sitemap followed by its matching posts, under `budget`."""
        label = str(season)
        if dry_run:
            return run_requests(
                self._cache,
                self.plan(season, gap_dates),
                source=SOURCE,
                season_label=label,
                dry_run=True,
            )
        run = GapRun(self._cache, SOURCE, label, budget)
        if not week_gap_dates(gap_dates, self._week_of):
            return run.summary
        if not run.fetch(INDEX_REQUEST):
            return run.summary
        weeks = gap_weeks(gap_dates, self._week_of)
        done: set[str] = set()
        for child in self._child_requests(gap_dates):
            if not run.fetch(child):
                return run.summary
            for entry in self._posts_in([child], season, weeks):
                if entry.url in done:
                    continue
                done.add(entry.url)
                if not run.fetch(post_request(season, entry)):
                    return run.summary
        return run.summary

    def run(
        self,
        seasons: Sequence[int],
        gap_dates_by_season: Mapping[int, Collection[date]],
        *,
        dry_run: bool = False,
        max_requests: int = MAX_REQUESTS_DEFAULT,
    ) -> list[BatchSummary]:
        budget = RequestBudget(max_requests)
        summaries: list[BatchSummary] = []
        for season in seasons:
            summaries.append(
                self.run_season(
                    season,
                    gap_dates_by_season.get(season, set()),
                    dry_run=dry_run,
                    budget=budget,
                )
            )
            if budget.exhausted:
                break
        return summaries
