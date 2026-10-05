"""D-05 completeness: a season x source report read entirely from the vault.

Nothing here builds an HTTP client: every fact comes from files already
cached under data/vault/raw/ and data/vault/ledger/. The report persisted by
`write_completeness` (audit/completeness.json + .md) is the AUDIT-03 baseline
Phase 3's regression guard starts from (D-06).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from booth_review.config import CFBD_FLOOR_DEFAULT, DataPaths
from booth_review.errors import ParseError
from booth_review.job.gaps506 import GAME_LENGTH, find_506_gaps, week_windows
from booth_review.sources.cfbd.collector import ENDPOINTS
from booth_review.sources.cfbd.parser import CfbdGame, parse_games
from booth_review.sources.ratingsref.lastmod import load_lastmods
from booth_review.sources.ratingsref.sitemap import SitemapEntry, parse_sitemap
from booth_review.sources.sports506.weeks import (
    discover_season_weeks,
    label_from_cache_name,
    smoke_check,
)
from booth_review.transport.budget import CfbdBudget
from booth_review.transport.cache import Manifest, atomic_write_bytes, atomic_write_json

SOURCES: tuple[str, ...] = ("sports506", "cfbd", "ratingsref")
CFBD_SEASON_ENDPOINTS: tuple[str, ...] = tuple(ENDPOINTS.keys())

# Seasons from here on are collected in season by the scheduled job, so their
# inputs must be shown fresh before a freeze; 2014-2025 were all collected after
# their seasons ended (folded WR-08).
IN_SEASON_FIRST_SEASON = 2026

# Only up to this many RR telecast ids are surfaced (JSON only, never
# markdown) for a season with missing records, so a large gap doesn't bloat
# the persisted report with per-record detail (T-02-23).
_MAX_RR_MISSING_IDS = 50


def _week_sort_key(label: str) -> tuple[int, int]:
    return (1, 0) if label == "B" else (0, int(label))


@dataclass(frozen=True)
class CellResult:
    """One (season, source) cell of the completeness report."""

    season: int
    source: str
    complete: bool
    reasons: list[str]
    counts: dict[str, int]
    details: dict[str, list[str]]

    def to_json(self) -> dict[str, object]:
        return {
            "season": self.season,
            "source": self.source,
            "complete": self.complete,
            "reasons": self.reasons,
            "counts": self.counts,
            "details": self.details,
        }


@dataclass(frozen=True)
class CompletenessReport:
    """The full season x source report, plus CFBD ledger evidence (D-01)."""

    generated_at: str
    seasons: list[int]
    cells: list[CellResult]
    cfbd_ledger: list[dict[str, object]]
    sitemap_date: str | None

    def complete_for(self, season: int) -> bool:
        return all(cell.complete for cell in self.cells if cell.season == season)

    def incomplete_cells(self) -> list[CellResult]:
        return [cell for cell in self.cells if not cell.complete]

    def to_json(self) -> dict[str, object]:
        cells_complete = sum(1 for cell in self.cells if cell.complete)
        cells_incomplete = len(self.cells) - cells_complete
        sports506_pages = sum(
            cell.counts.get("cached", 0) for cell in self.cells if cell.source == "sports506"
        )
        cfbd_endpoint_files = sum(
            cell.counts.get("present", 0) for cell in self.cells if cell.source == "cfbd"
        )
        ratingsref_records = sum(
            cell.counts.get("cached", 0) for cell in self.cells if cell.source == "ratingsref"
        )
        return {
            "generated_at": self.generated_at,
            "seasons": self.seasons,
            "sitemap_date": self.sitemap_date,
            "cells": [cell.to_json() for cell in self.cells],
            "cfbd_ledger": self.cfbd_ledger,
            "summary": {
                "cells_complete": cells_complete,
                "cells_incomplete": cells_incomplete,
                "sports506_pages": sports506_pages,
                "cfbd_endpoint_files": cfbd_endpoint_files,
                "ratingsref_records": ratingsref_records,
            },
        }


# -- 506 -----------------------------------------------------------------------------------


def _load_cfbd_games(paths: DataPaths, season: int) -> list[CfbdGame] | None:
    """The season's CFBD games, or None when the file is absent or unparseable."""
    path = paths.raw / "cfbd" / "games" / f"{season}.json"
    if not path.is_file():
        return None
    try:
        return parse_games(path.read_bytes())
    except ParseError:
        return None


def check_506(paths: DataPaths, season: int, *, now: datetime) -> CellResult:
    """D-05's 506 bar: every week label `season`'s own pages' nav lists is
    cached and passes the D-03 smoke check. Also cross-checks the nav against
    CFBD's played weeks (WR-09) and, for in-season seasons, page save times
    (WR-08).
    """
    season_dir = paths.raw / "sports506" / str(season)
    cached_paths = sorted(season_dir.glob("wk-*.html")) if season_dir.is_dir() else []

    if not cached_paths:
        return CellResult(
            season=season,
            source="sports506",
            complete=False,
            reasons=["no pages imported"],
            counts={"expected": 0, "cached": 0, "smoke_failed": 0, "missing": 0, "extra": 0},
            details={},
        )

    cached_by_label: dict[str, Path] = {}
    for path in cached_paths:
        label = label_from_cache_name(path.name)
        if label is not None:
            cached_by_label[label] = path

    expected_labels: set[str] = set()
    unsupported_labels: set[str] = set()
    for path in cached_paths:
        season_weeks = discover_season_weeks(path.read_bytes(), season)
        expected_labels.update(season_weeks.labels)
        unsupported_labels.update(season_weeks.unsupported)

    expected = sorted(expected_labels, key=_week_sort_key)
    cached = sorted(cached_by_label, key=_week_sort_key)

    smoke_failed: list[str] = []
    for label in expected:
        cached_path = cached_by_label.get(label)
        if cached_path is None:
            continue
        result = smoke_check(cached_path.read_bytes(), season=season, week_label=label)
        if not result.passed:
            smoke_failed.append(label)

    missing = [label for label in expected if label not in cached_by_label]
    extra = [label for label in cached if label not in expected_labels]

    games = _load_cfbd_games(paths, season)
    stale: list[str] = []
    not_in_nav: list[str] = []
    if games is not None:
        if season >= IN_SEASON_FIRST_SEASON:
            stale = sorted(find_506_gaps(paths, season, games, now).stale, key=_week_sort_key)
        for label, (_first, last_kickoff) in week_windows(games, season).items():
            if now <= last_kickoff + GAME_LENGTH or label in expected_labels:
                continue
            if label == "0" and "1" in expected_labels:
                continue  # 506 folds openers into week 1 in some seasons
            not_in_nav.append(label)
        not_in_nav.sort(key=_week_sort_key)
    bowl_not_in_nav = "B" not in expected_labels

    reasons: list[str] = []
    if not expected:
        reasons.append("no week nav discovered in any cached page")
    if unsupported_labels:
        reasons.append(
            "unsupported nav labels: " + ", ".join(sorted(unsupported_labels, key=_week_sort_key))
        )
    if missing:
        reasons.append(f"missing weeks: {', '.join(missing)}")
    if smoke_failed:
        reasons.append(f"smoke check failed: {', '.join(smoke_failed)}")
    if stale:
        reasons.append(f"saved before games finished: {', '.join(stale)}")
    if not_in_nav:
        reasons.append(f"cfbd weeks not in nav: {', '.join(not_in_nav)}")
    if bowl_not_in_nav:
        reasons.append("bowl week B not in nav")

    complete = (
        bool(expected)
        and not unsupported_labels
        and not missing
        and not smoke_failed
        and not stale
        and not not_in_nav
        and not bowl_not_in_nav
    )

    return CellResult(
        season=season,
        source="sports506",
        complete=complete,
        reasons=reasons,
        counts={
            "expected": len(expected),
            "cached": len(cached),
            "smoke_failed": len(smoke_failed),
            "missing": len(missing),
            "extra": len(extra),
            "stale": len(stale),
            "not_in_nav": len(not_in_nav),
            "bowl_not_in_nav": int(bowl_not_in_nav),
        },
        details={
            "stale": stale,
            "not_in_nav": not_in_nav,
            "expected": expected,
            "cached": cached,
            "smoke_failed": smoke_failed,
            "missing": missing,
            "extra": extra,
            "unsupported": sorted(unsupported_labels, key=_week_sort_key),
        },
    )


# -- CFBD ----------------------------------------------------------------------------------


def _parse_utc(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)


def check_cfbd(paths: DataPaths, season: int) -> CellResult:
    """D-05's CFBD bar: all six season endpoints cached and non-empty."""
    present: list[str] = []
    missing: list[str] = []
    for name in CFBD_SEASON_ENDPOINTS:
        path = paths.raw / "cfbd" / name / f"{season}.json"
        ok = False
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = None
            if isinstance(data, list) and data:
                ok = True
        (present if ok else missing).append(name)

    fetched_before_end: list[str] = []
    if season >= IN_SEASON_FIRST_SEASON:
        # CFP title games finish by about Jan 20; require a fetch from Feb 1 on.
        season_end = datetime(season + 1, 2, 1, tzinfo=UTC)
        newest: dict[str, str] = {}
        for entry in Manifest(paths.manifest).entries():
            entry_path = entry.get("path")
            fetched_at = entry.get("fetched_at")
            if isinstance(entry_path, str) and isinstance(fetched_at, str):
                newest[entry_path] = max(fetched_at, newest.get(entry_path, ""))
        for name in CFBD_SEASON_ENDPOINTS:
            fetched = newest.get(f"cfbd/{name}/{season}.json")
            if fetched is None or _parse_utc(fetched) < season_end:
                fetched_before_end.append(name)

    complete = not missing and not fetched_before_end
    reasons = [f"missing/empty endpoints: {', '.join(missing)}"] if missing else []
    if fetched_before_end:
        reasons.append(f"fetched before season end: {', '.join(fetched_before_end)}")

    counts = {
        "total": len(CFBD_SEASON_ENDPOINTS),
        "present": len(present),
        "missing": len(missing),
    }
    details = {"present": present, "missing": missing}
    if season >= IN_SEASON_FIRST_SEASON:
        counts["fetched_before_end"] = len(fetched_before_end)
        details["fetched_before_end"] = fetched_before_end

    return CellResult(
        season=season,
        source="cfbd",
        complete=complete,
        reasons=reasons,
        counts=counts,
        details=details,
    )


# -- Ratings Reference -----------------------------------------------------------------------


def check_rr(
    paths: DataPaths,
    season: int,
    entries: Sequence[SitemapEntry],
    lastmod_keys: set[str],
) -> CellResult:
    """D-05's RR bar: every sitemap CFB telecast for `season` is cached with
    its lastmod recorded.
    """
    cached_count = 0
    lastmod_count = 0
    missing_ids: set[str] = set()
    for entry in entries:
        record_path = (
            paths.raw / "ratingsref" / "telecast" / str(season) / f"{entry.telecast_id}.json"
        )
        is_cached = record_path.is_file()
        has_lastmod = entry.telecast_id in lastmod_keys
        if is_cached:
            cached_count += 1
        if has_lastmod:
            lastmod_count += 1
        if not (is_cached and has_lastmod):
            missing_ids.add(entry.telecast_id)

    sorted_missing = sorted(missing_ids)
    # RR lists telecasts for every in-scope season, so an empty list means the
    # sitemap is missing or unparsed, never a vacuously complete season.
    complete = bool(entries) and not sorted_missing
    reasons: list[str] = []
    if not entries:
        reasons.append("sitemap lists no telecasts for this season (missing or unparsed sitemap)")
    elif sorted_missing:
        reasons.append(
            f"missing {len(sorted_missing)}/{len(entries)} records cached or lastmod-recorded"
        )

    return CellResult(
        season=season,
        source="ratingsref",
        complete=complete,
        reasons=reasons,
        counts={
            "listed": len(entries),
            "cached": cached_count,
            "lastmod_recorded": lastmod_count,
            "missing": len(sorted_missing),
        },
        details={"missing_telecast_ids": sorted_missing[:_MAX_RR_MISSING_IDS]},
    )


# -- CFBD ledger evidence (D-01 verification) ------------------------------------------------


def cfbd_ledger_months(
    paths: DataPaths, *, floor: int = CFBD_FLOOR_DEFAULT
) -> list[dict[str, object]]:
    """Per-month CFBD ledger usage: calls, by_tag, remaining vs floor."""
    budget = CfbdBudget(paths.cfbd_ledger, floor=floor)
    months: set[str] = set()
    if paths.cfbd_ledger.is_file():
        with paths.cfbd_ledger.open(encoding="utf-8") as fh:
            for raw_line in fh:
                stripped = raw_line.strip()
                if not stripped:
                    continue
                line = json.loads(stripped)
                month = line.get("month")
                if isinstance(month, str):
                    months.add(month)

    result: list[dict[str, object]] = []
    for month in sorted(months):
        summary = budget.summary(month)
        above_floor = summary.last_remaining is not None and summary.last_remaining >= floor
        result.append(
            {
                "month": summary.month,
                "calls_counted": summary.calls_counted,
                "by_tag": summary.by_tag,
                "last_remaining": summary.last_remaining,
                "floor": summary.floor,
                "above_floor": above_floor,
            }
        )
    return result


# -- build / render / write -------------------------------------------------------------------


def _newest_sitemap(paths: DataPaths) -> tuple[bytes | None, str | None]:
    sitemap_dir = paths.raw / "ratingsref" / "sitemap"
    if not sitemap_dir.is_dir():
        return None, None
    files = sorted(sitemap_dir.glob("*.xml"))
    if not files:
        return None, None
    newest = files[-1]
    return newest.read_bytes(), newest.stem


def build_completeness(
    paths: DataPaths, seasons: Sequence[int], *, now: datetime
) -> CompletenessReport:
    """Build the full season x source report for `seasons` from vault state.

    Reads the newest cached RR sitemap once (by filename, dated YYYY-MM-DD)
    and shares it across every season's RR cell.
    """
    xml, sitemap_date = _newest_sitemap(paths)
    entries: list[SitemapEntry] = []
    if xml is not None:
        entries, _skipped = parse_sitemap(xml)

    lastmod_keys = set(load_lastmods(paths))

    entries_by_season: dict[int, list[SitemapEntry]] = {}
    for entry in entries:
        entries_by_season.setdefault(entry.season, []).append(entry)

    cells: list[CellResult] = []
    for season in seasons:
        cells.append(check_506(paths, season, now=now))
        cells.append(check_cfbd(paths, season))
        cells.append(check_rr(paths, season, entries_by_season.get(season, []), lastmod_keys))

    return CompletenessReport(
        generated_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        seasons=list(seasons),
        cells=cells,
        cfbd_ledger=cfbd_ledger_months(paths),
        sitemap_date=sitemap_date,
    )


def render_markdown(report: CompletenessReport) -> str:
    """A season x source table: status plus key counts. No page text, no URLs."""
    lines: list[str] = [
        "# Completeness Report",
        "",
        f"Generated: {report.generated_at}",
        f"Sitemap date: {report.sitemap_date or 'none cached'}",
        "",
        "| Season | Source | Status | Counts |",
        "|---|---|---|---|",
    ]
    for cell in report.cells:
        status = "complete" if cell.complete else "incomplete"
        counts_str = ", ".join(f"{key} {value}" for key, value in cell.counts.items())
        lines.append(f"| {cell.season} | {cell.source} | {status} | {counts_str} |")

    lines += [
        "",
        "## CFBD Ledger",
        "",
        "| Month | Calls | Remaining | Floor | Above Floor |",
        "|---|---|---|---|---|",
    ]
    for month in report.cfbd_ledger:
        lines.append(
            f"| {month['month']} | {month['calls_counted']} | {month['last_remaining']} | "
            f"{month['floor']} | {month['above_floor']} |"
        )

    cells_complete = sum(1 for cell in report.cells if cell.complete)
    lines += [
        "",
        "## Summary",
        "",
        f"cells complete: {cells_complete}/{len(report.cells)}",
        "",
    ]
    return "\n".join(lines) + "\n"


def write_completeness(paths: DataPaths, report: CompletenessReport) -> None:
    """Persist audit/completeness.json (+.md), the AUDIT-03 baseline (D-06)."""
    atomic_write_json(paths.audit / "completeness.json", report.to_json())
    atomic_write_bytes(paths.audit / "completeness.md", render_markdown(report).encode("utf-8"))
