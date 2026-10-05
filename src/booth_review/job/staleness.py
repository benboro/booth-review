"""D-14: count-only staleness checks for the in-season update pipeline.

Two signals, both computed from the vault alone (read-only, no requests):
the last successful build is too old, or the newest plotted current-season
telecast trails the newest Ratings Reference-listed one. Only dates and
counts leave this module, as `AttentionItem`s.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import polars as pl

from booth_review.audit.completeness import _newest_sitemap
from booth_review.config import DataPaths
from booth_review.job.attention import (
    AttentionItem,
    build_stale,
    plotted_none_listed,
    plotted_trails_listed,
)
from booth_review.sources.ratingsref.sitemap import parse_sitemap

STALE_BUILD_DAYS = 4
"""D-14, user-set: a last successful build older than this is stale."""

STALE_TRAIL_DAYS = 3
"""Proposed tolerance (D-14 gave no number): a lone non-FBS game on an odd date
would otherwise raise a false alarm. Named so it can be changed."""


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")


def newest_listed(paths: DataPaths, season: int) -> tuple[date | None, int]:
    """Newest RR-listed event date for `season` in the newest cached sitemap, and the count."""
    xml, _stamp = _newest_sitemap(paths)
    if xml is None:
        return None, 0
    entries, _skipped = parse_sitemap(xml)
    dates = [entry.event_date for entry in entries if entry.season == season]
    if not dates:
        return None, 0
    return max(dates), len(dates)


def newest_plotted(paths: DataPaths, season: int) -> date | None:
    """Newest plotted telecast date for `season`, or None without a table or rows."""
    table = paths.processed / "telecasts.parquet"
    if not table.is_file():
        return None
    frame = pl.read_parquet(table, columns=["season", "date_et", "plotted"])
    rows = frame.filter((pl.col("season") == season) & pl.col("plotted"))
    if rows.is_empty():
        return None
    newest = rows["date_et"].max()
    return newest if isinstance(newest, date) else None


def staleness_items(
    *,
    last_build_at: datetime | None,
    now: datetime,
    season: int | None,
    newest_listed: date | None,
    listed_count: int,
    newest_plotted: date | None,
) -> list[AttentionItem]:
    """The D-14 attention items for the given inputs (empty when all is fresh)."""
    _require_aware(now, "now")
    items: list[AttentionItem] = []
    if last_build_at is not None:
        _require_aware(last_build_at, "last_build_at")
        age = now - last_build_at
        if age > timedelta(days=STALE_BUILD_DAYS):
            items.append(build_stale(age.days, STALE_BUILD_DAYS))
    if season is not None and newest_listed is not None:
        if newest_plotted is None:
            items.append(plotted_none_listed(listed_count))
        else:
            trail = (newest_listed - newest_plotted).days
            if trail > STALE_TRAIL_DAYS:
                items.append(plotted_trails_listed(trail, STALE_TRAIL_DAYS))
    return items
