"""Tests for job/staleness.py: D-14 count-only staleness checks."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import polars as pl
import pytest

from booth_review.config import DataPaths
from booth_review.job.staleness import (
    STALE_BUILD_DAYS,
    STALE_TRAIL_DAYS,
    newest_listed,
    newest_plotted,
    staleness_items,
)

_NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


def _kinds(**overrides: object) -> list[str]:
    args: dict[str, object] = {
        "last_build_at": None,
        "now": _NOW,
        "season": 2026,
        "newest_listed": None,
        "listed_count": 0,
        "newest_plotted": None,
    }
    args.update(overrides)
    return [item.kind for item in staleness_items(**args)]  # type: ignore[arg-type]


def test_constants() -> None:
    assert STALE_BUILD_DAYS == 4
    assert STALE_TRAIL_DAYS == 3


def test_build_age_over_four_days_is_stale() -> None:
    items = staleness_items(
        last_build_at=_NOW - timedelta(days=4, hours=1),
        now=_NOW,
        season=None,
        newest_listed=None,
        listed_count=0,
        newest_plotted=None,
    )
    assert [i.kind for i in items] == ["build_stale"]
    assert items[0].line == "last successful build is 4 days old (limit 4)"


def test_build_age_under_four_days_is_fresh() -> None:
    assert _kinds(last_build_at=_NOW - timedelta(days=3, hours=23)) == []


def test_no_last_build_is_not_stale() -> None:
    assert _kinds(last_build_at=None) == []


def test_plotted_trails_listed_beyond_tolerance() -> None:
    items = staleness_items(
        last_build_at=None,
        now=_NOW,
        season=2026,
        newest_listed=date(2026, 10, 3),
        listed_count=10,
        newest_plotted=date(2026, 9, 29),
    )
    assert [i.kind for i in items] == ["plotted_trails_listed"]
    assert "by 4 days (limit 3)" in items[0].line


def test_trail_of_exactly_tolerance_is_fine() -> None:
    assert _kinds(newest_listed=date(2026, 10, 3), newest_plotted=date(2026, 9, 30)) == []


def test_listed_but_none_plotted() -> None:
    items = staleness_items(
        last_build_at=None,
        now=_NOW,
        season=2026,
        newest_listed=date(2026, 10, 3),
        listed_count=12,
        newest_plotted=None,
    )
    assert [i.line for i in items] == ["RR lists 12 telecasts this season but none are plotted"]


def test_off_season_skips_trail_checks() -> None:
    assert _kinds(season=None, newest_listed=date(2026, 10, 3), newest_plotted=None) == []


def test_naive_now_rejected() -> None:
    with pytest.raises(ValueError):
        _kinds(now=datetime(2026, 10, 8, 12, 0))  # noqa: DTZ001


def _write_sitemap(paths: DataPaths, slugs: list[str], day: str = "2026-10-05") -> None:
    urls = "".join(
        f"<url><loc>https://ratingsreference.com/telecast/{slug}</loc>"
        f"<lastmod>2026-10-05</lastmod></url>"
        for slug in slugs
    )
    path = paths.raw / "ratingsref" / "sitemap" / f"{day}.xml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'
        ).encode()
    )


def test_newest_listed_counts_season_entries(vault_paths: DataPaths) -> None:
    _write_sitemap(
        vault_paths,
        [
            "cfb-ohio-state-vs-michigan-2026-10-03",
            "cfb-texas-vs-oklahoma-2026-09-26",
            "cfb-georgia-vs-alabama-2025-10-04",
        ],
    )
    assert newest_listed(vault_paths, 2026) == (date(2026, 10, 3), 2)
    assert newest_listed(vault_paths, 2030) == (None, 0)


def test_newest_listed_without_sitemap(vault_paths: DataPaths) -> None:
    assert newest_listed(vault_paths, 2026) == (None, 0)


def test_newest_plotted(vault_paths: DataPaths) -> None:
    assert newest_plotted(vault_paths, 2026) is None
    pl.DataFrame(
        {
            "season": pl.Series([2026, 2026, 2026, 2025], dtype=pl.Int32),
            "date_et": [date(2026, 9, 20), date(2026, 9, 27), date(2026, 10, 3), date(2025, 12, 1)],
            "plotted": [True, True, False, True],
        }
    ).write_parquet(vault_paths.processed / "telecasts.parquet")
    assert newest_plotted(vault_paths, 2026) == date(2026, 9, 27)
    assert newest_plotted(vault_paths, 2031) is None
