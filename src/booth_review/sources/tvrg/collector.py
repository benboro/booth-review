"""TvrgCollector: gap-only collection from The TV Ratings Guide (04.19 D-11).

For each season, the collector reads the monthly archive of every month that
holds a gap date and of the month after it (posts are often filed a day or
two after the games), then the daily ratings posts whose title date is within
one day of a gap date. Nothing else is requested: no blanket month sweep, no
re-fetch (a cached page is always served from the cache), and every request
goes through RawCache and the standard client (user agent, robots.txt,
3 s pacing, one at a time).

Archive pages are cached at ``tvrg/index/<yyyy>-<mm>[-p<n>].html`` (the
04.19-32 policy check stored its sample there, so it is reused, not
re-fetched); posts at ``tvrg/<season>/posts/<yyyy>-<mm>-<slug>.html``.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from datetime import date, timedelta
from typing import Final
from urllib.parse import urlsplit

from booth_review.sources.base import BatchSummary, run_requests
from booth_review.sources.gapcollect import (
    MAX_REQUESTS_DEFAULT,
    GapRun,
    RequestBudget,
    safe_slug,
)
from booth_review.sources.tvrg.index import (
    TVRG_HOST,
    PostRef,
    is_ratings_title,
    parse_archive,
    title_date,
)
from booth_review.transport.cache import RawCache
from booth_review.transport.types import FetchRequest

SOURCE: Final = "tvrg"
MAX_PAGES_PER_MONTH: Final = 5
DAY_WINDOW: Final = timedelta(days=1)


def archive_url(year: int, month: int) -> str:
    return f"https://{TVRG_HOST}/{year:04d}/{month:02d}/"


def index_months(gap_dates: Iterable[date]) -> list[tuple[int, int]]:
    """Every month holding a gap date, plus the month after each, ascending."""
    months: set[tuple[int, int]] = set()
    for day in gap_dates:
        months.add((day.year, day.month))
        months.add((day.year + 1, 1) if day.month == 12 else (day.year, day.month + 1))
    return sorted(months)


def _index_request(season: int, year: int, month: int, page: int, url: str) -> FetchRequest:
    suffix = "" if page == 1 else f"-p{page}"
    return FetchRequest(
        source=SOURCE,
        season=season,
        url=url,
        cache_path=f"tvrg/index/{year:04d}-{month:02d}{suffix}.html",
    )


def post_request(season: int, url: str) -> FetchRequest:
    path = urlsplit(url).path  # /<yyyy>/<mm>/<slug>.html, checked by post_url
    year, month, leaf = path.strip("/").split("/", 2)
    slug = safe_slug(leaf.removesuffix(".html"))
    return FetchRequest(
        source=SOURCE,
        season=season,
        url=url,
        cache_path=f"tvrg/{season}/posts/{year}-{month}-{slug}.html",
    )


def _distance(post: PostRef, gap_dates: Collection[date]) -> int | None:
    """Days from the post's title date to the nearest gap date, when within DAY_WINDOW."""
    if not is_ratings_title(post.title):
        return None
    day = title_date(post.title)
    if day is None:
        return None
    best: int | None = None
    for gap in gap_dates:
        delta = abs((day - gap).days)
        if delta <= DAY_WINDOW.days and (best is None or delta < best):
            best = delta
    return best


def select_posts(posts: Iterable[PostRef], gap_dates: Collection[date]) -> list[PostRef]:
    """Ratings posts whose title date is within one day of a gap date: exact
    matches first, then by title date and URL."""
    keyed: list[tuple[int, date, str, PostRef]] = []
    seen: set[str] = set()
    for post in posts:
        if post.url in seen:
            continue
        distance = _distance(post, gap_dates)
        if distance is None:
            continue
        seen.add(post.url)
        day = title_date(post.title)
        assert day is not None
        keyed.append((distance, day, post.url, post))
    keyed.sort(key=lambda item: item[:3])
    return [item[3] for item in keyed]


class TvrgCollector:
    """Plans and runs the gap-only TVRG pass, one season at a time."""

    def __init__(self, cache: RawCache) -> None:
        self._cache = cache

    # -- planning (offline: reads cached pages only) ---------------------------------------

    def _month_chain(self, season: int, year: int, month: int) -> list[FetchRequest]:
        """The month's archive page, then each cached page's older-posts page (at
        most MAX_PAGES_PER_MONTH); the chain stops at the first uncached page."""
        chain = [_index_request(season, year, month, 1, archive_url(year, month))]
        while len(chain) < MAX_PAGES_PER_MONTH:
            body = self._cache.read_cached(chain[-1])
            if body is None:
                break
            next_url = parse_archive(body).next_url
            if next_url is None or next_url in {req.url for req in chain}:
                break
            chain.append(_index_request(season, year, month, len(chain) + 1, next_url))
        return chain

    def plan_index(self, season: int, gap_dates: Collection[date]) -> list[FetchRequest]:
        return [
            req
            for year, month in index_months(gap_dates)
            for req in self._month_chain(season, year, month)
        ]

    def _cached_posts(self, pages: Sequence[FetchRequest]) -> list[PostRef]:
        posts: list[PostRef] = []
        for req in pages:
            body = self._cache.read_cached(req)
            if body is not None:
                posts.extend(parse_archive(body).posts)
        return posts

    def plan_posts(self, season: int, gap_dates: Collection[date]) -> list[FetchRequest]:
        """Post requests from the cached archive pages only."""
        posts = self._cached_posts(self.plan_index(season, gap_dates))
        return [post_request(season, post.url) for post in select_posts(posts, gap_dates)]

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
        """Dry run: counts for `plan` (no request). Live: month by month, the
        archive page(s), then the month's matching posts, under `budget`."""
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
        done: set[str] = set()
        for year, month in index_months(gap_dates):
            pages: list[FetchRequest] = []
            req: FetchRequest | None = _index_request(
                season, year, month, 1, archive_url(year, month)
            )
            while req is not None and len(pages) < MAX_PAGES_PER_MONTH:
                if not run.fetch(req):
                    return run.summary
                body = self._cache.read_cached(req)
                if body is None:  # a 4xx: nothing to follow
                    break
                pages.append(req)
                next_url = parse_archive(body).next_url
                req = (
                    _index_request(season, year, month, len(pages) + 1, next_url)
                    if next_url is not None and next_url not in {p.url for p in pages}
                    else None
                )
            for post in select_posts(self._cached_posts(pages), gap_dates):
                if post.url in done:
                    continue
                done.add(post.url)
                if not run.fetch(post_request(season, post.url)):
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
