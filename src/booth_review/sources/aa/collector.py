"""AaCollector: gap-week collection from Awful Announcing (04.19 D-11).

AA's college-football ratings coverage is per game or per network, not one
weekly roundup: slugs such as ``<teams>-week-<n>-<network>-cfb-ratings`` or
``<teams>-<network>-week-<n>-viewership-...`` under the ``ratings/``,
``college-football/`` and ``ncaa/`` categories, usually with no year. A post
is kept only when it can fill a gap:

- its category is one of those three; a ``college-football/`` or ``ncaa/``
  slug must carry a ratings word, and a ``ratings/`` slug must not name another
  league (``nfl``, ``nba`` ...);
- a slug year, when present, equals the season;
- a ``week-<n>`` slug matches a gap week: the CFBD regular-season week of a gap
  date is n or n + 1 (AA counts "Week 0" where CFBD says week 1), and, with no
  slug year, its sitemap lastmod is on or after the season's first gap date;
- a slug with no week also needs a college word (``cfb``/``college``/``ncaa``
  or a college category) and a sitemap lastmod 0-7 days after a gap date.

Postseason gap dates map to no week and plan nothing here.

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
from booth_review.sources.aa.parser import AaParseError, parse_post, post_url_from_html
from booth_review.sources.base import BatchSummary, run_requests
from booth_review.sources.gapcollect import (
    MAX_REQUESTS_DEFAULT,
    GapRun,
    RequestBudget,
    post_validator,
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


RATINGS_CATEGORIES: Final = frozenset({"ratings", "college-football", "ncaa"})
COLLEGE_CATEGORIES: Final = frozenset({"college-football", "ncaa"})
NO_WEEK_WINDOW: Final = timedelta(days=7)
_RATINGS_WORDS: Final = frozenset(
    {"rating", "ratings", "viewership", "viewers", "audience", "watched"}
)
_COLLEGE_WORDS: Final = frozenset({"cfb", "college", "ncaa"})
_OTHER_LEAGUES: Final = frozenset(
    {"nfl", "nba", "wnba", "mlb", "nhl", "mls", "nascar", "pga", "ufc", "wwe", "aew", "f1"}
)


def wanted_entry(
    entry: UrlEntry, season: int, weeks: Collection[int], gap_dates: Collection[date]
) -> bool:
    """True when the sitemap entry can fill a gap week or date (see module doc)."""
    category = entry.category
    if category not in RATINGS_CATEGORIES:
        return False
    slug = entry.slug
    tokens = set(slug.split("-"))
    if category in COLLEGE_CATEGORIES and not tokens & _RATINGS_WORDS:
        return False
    if tokens & _OTHER_LEAGUES:
        return False
    year = year_of_slug(slug)
    if year is not None and year != season:
        return False
    if not gap_dates:
        return False
    posted = entry.lastmod.date() if entry.lastmod is not None else None
    week = week_of_slug(slug)
    if week is not None:
        if week not in weeks and week + 1 not in weeks:
            return False
        return year == season or (posted is not None and posted >= min(gap_dates))
    if category not in COLLEGE_CATEGORIES and not tokens & _COLLEGE_WORDS:
        return False
    if posted is None:
        return False
    return any(timedelta(0) <= posted - day <= NO_WEEK_WINDOW for day in gap_dates)


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
        self, children: Sequence[FetchRequest], season: int, gap_dates: Collection[date]
    ) -> list[UrlEntry]:
        weeks = gap_weeks(gap_dates, self._week_of)
        days = week_gap_dates(gap_dates, self._week_of)
        entries: list[UrlEntry] = []
        for req in children:
            body = self._cache.read_cached(req)
            if body is None:
                continue
            entries.extend(
                entry
                for entry in parse_sitemap(body).urls
                if wanted_entry(entry, season, weeks, days)
            )
        return entries

    def plan_posts(self, season: int, gap_dates: Collection[date]) -> list[FetchRequest]:
        """Post requests from the cached sitemaps only."""
        seen: set[str] = set()
        requests: list[FetchRequest] = []
        for entry in self._posts_in(self._child_requests(gap_dates), season, gap_dates):
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
        # A post the build couldn't read is never cached (CR-01).
        check_post = post_validator(
            SOURCE, season, url_from_html=post_url_from_html, parse=parse_post, error=AaParseError
        )
        if not week_gap_dates(gap_dates, self._week_of):
            return run.summary
        if not run.fetch(INDEX_REQUEST):
            return run.summary
        done: set[str] = set()
        for child in self._child_requests(gap_dates):
            if not run.fetch(child):
                return run.summary
            for entry in self._posts_in([child], season, gap_dates):
                if entry.url in done:
                    continue
                done.add(entry.url)
                if not run.fetch(post_request(season, entry), validate=check_post):
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
