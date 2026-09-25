"""Sports506Importer: hand-saved 506 week pages brought into the vault cache.

506sports.com returned 403 Forbidden to booth-review's correctly-identified
client on its first live attempt (2025 weeks 0-2, 01-09 Task 2). Per AGENTS.md
this block is never worked around: instead, the 2025 week pages are saved by
hand in a browser and imported with `booth-review import 506`, which writes
each page to exactly the same vault cache path and manifest shape the
collector would have produced, so a later `booth-review collect 506` run (or
any RawCache lookup) treats them as already-cached and never re-fetches or
re-requests the blocked host.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from booth_review.config import DataPaths
from booth_review.errors import FrozenSeasonError
from booth_review.sources.sports506.collector import WEEK_LABELS, Sports506Collector
from booth_review.sources.sports506.weeks import discover_season_weeks, smoke_check
from booth_review.transport.cache import (
    FreezeGuard,
    Manifest,
    ManifestEntry,
    RawCache,
    atomic_write_bytes,
)
from booth_review.transport.types import FetchRequest

DEFAULT_INCOMING_DIR = Path("data/incoming/506")

_MANUAL_ORIGIN = "manual"

_CHALLENGE_MARKERS = ("just a moment", "cf-chl", "attention required")

# A saved week page names itself in its canonical link and its <title>, so the
# importer identifies pages by content and filenames don't matter (a browser's
# default "506 Sports - College Football_ Week 12, 2025.html" works as-is).
_CANONICAL_RE = re.compile(
    r"<link[^>]*rel=[\"']canonical[\"'][^>]*href=[\"'][^\"']*ncaaf\.php\?yr=(\d{4})(?:&amp;|&)wk=(\d{1,2}|B)[\"']",
    re.IGNORECASE,
)
_TITLE_RE = re.compile(r"<title>[^<]*Week\s+(\d{1,2}|B),\s*(\d{4})[^<]*</title>", re.IGNORECASE)
_FILENAME_RE = re.compile(r"^(\d{4})-wk(\d{1,2}|B)\.html$")


@dataclass
class SkippedFile:
    label: str
    reason: str


@dataclass
class ImportResult:
    """The outcome of importing one season's worth of incoming 506 files."""

    season: int
    imported: list[str] = field(default_factory=list)
    skipped_existing: list[str] = field(default_factory=list)
    skipped_invalid: list[SkippedFile] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    unrecognized: int = 0
    expected: list[str] = field(default_factory=list)
    """D-05: the week labels this season is expected to have, either read from
    the season's own page nav (`expected_source == "nav"`) or, when no nav was
    found in any scanned/cached page, the full WEEK_LABELS set
    (`expected_source == "default"`)."""
    expected_source: str = "default"
    unsupported_labels: list[str] = field(default_factory=list)
    """Nav labels outside WEEK_LABELS (e.g. a future week number), surfaced
    rather than silently dropped."""

    def counts(self) -> dict[str, int]:
        """Counts for vault.batch_message, count-only (never real page text)."""
        return {
            "imported": len(self.imported),
            "skipped": len(self.skipped_existing) + len(self.skipped_invalid),
        }

    @property
    def has_problems(self) -> bool:
        """True when something needs a human's attention."""
        return bool(self.missing or self.skipped_invalid or self.unsupported_labels)


def _normalize_label(raw: str) -> str | None:
    label = raw if raw == "B" else str(int(raw))
    return label if label in WEEK_LABELS else None


def _week_sort_key(label: str) -> tuple[int, int]:
    return (1, 0) if label == "B" else (0, int(label))


def identify_page(path: Path, content: bytes) -> tuple[int, str] | None:
    """Return (season, week label) for a saved 506 week page, or None if unknown.

    Page content wins: the canonical link, then the title. The filename pattern
    `{season}-wk{label}.html` is only a fallback for pages that carry neither.
    """
    text = content.decode("utf-8", errors="replace")
    canonical = _CANONICAL_RE.search(text)
    if canonical:
        label = _normalize_label(canonical.group(2))
        return (int(canonical.group(1)), label) if label else None
    title = _TITLE_RE.search(text)
    if title:
        label = _normalize_label(title.group(1))
        return (int(title.group(2)), label) if label else None
    named = _FILENAME_RE.match(path.name)
    if named:
        label = _normalize_label(named.group(2))
        return (int(named.group(1)), label) if label else None
    return None


def _looks_like_challenge_page(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _CHALLENGE_MARKERS)


def _looks_like_html(text: str) -> bool:
    lowered = text.lower()
    return "<html" in lowered or "<!doctype html" in lowered


def _validation_failure_reason(content: bytes, season: int) -> str | None:
    """Return a rejection reason, or None when `content` is acceptable."""
    if not content:
        return "empty file"
    text = content.decode("utf-8", errors="replace")
    if _looks_like_challenge_page(text):
        return "looks like a Cloudflare challenge/error page"
    if not _looks_like_html(text):
        return "does not look like HTML"
    if str(season) not in text:
        return f"does not mention {season}"
    return None


class Sports506Importer:
    """Imports hand-saved 506 week pages from an incoming folder into the vault."""

    def __init__(self, cache: RawCache, paths: DataPaths) -> None:
        self._cache = cache
        self._paths = paths
        self._manifest = Manifest(paths.manifest)

    def _scan(self, incoming_dir: Path, season: int, result: ImportResult) -> dict[str, bytes]:
        """Map week label -> page bytes for every page of `season` in the folder.

        Other seasons' pages are left alone. HTML files that aren't 506 week
        pages (a Downloads folder holds plenty) are only counted. Two different
        files claiming the same week are both rejected rather than guessed at.
        """
        found: dict[str, bytes] = {}
        conflicts: set[str] = set()
        for path in sorted(incoming_dir.glob("*.htm*")):
            if not path.is_file():
                continue
            content = path.read_bytes()
            identity = identify_page(path, content)
            if identity is None:
                result.unrecognized += 1
                continue
            page_season, label = identity
            if page_season != season:
                continue
            if label in found and found[label] != content:
                conflicts.add(label)
            found[label] = content
        for label in sorted(conflicts):
            del found[label]
            result.skipped_invalid.append(
                SkippedFile(label=label, reason="two different files claim this week")
            )
        return found

    def _expected_weeks(
        self, season: int, pages: dict[str, bytes]
    ) -> tuple[list[str], str, list[str]]:
        """D-05: the week labels `season` itself lists, from every page we can
        see (this run's incoming pages plus whatever is already cached),
        never a fixed 18-week assumption.
        """
        labels: set[str] = set()
        unsupported: set[str] = set()
        for content in pages.values():
            season_weeks = discover_season_weeks(content, season)
            labels.update(season_weeks.labels)
            unsupported.update(season_weeks.unsupported)
        season_dir = self._paths.raw / "sports506" / str(season)
        if season_dir.is_dir():
            for cached_path in sorted(season_dir.glob("wk-*.html")):
                season_weeks = discover_season_weeks(cached_path.read_bytes(), season)
                labels.update(season_weeks.labels)
                unsupported.update(season_weeks.unsupported)

        if labels:
            expected = sorted(labels, key=_week_sort_key)
            expected_source = "nav"
        else:
            expected = list(WEEK_LABELS)
            expected_source = "default"
        return expected, expected_source, sorted(unsupported, key=_week_sort_key)

    def run(self, season: int, *, incoming_dir: Path, force: bool = False) -> ImportResult:
        # D-06/D-07: a frozen season refuses every write, checked before any
        # file is scanned or touched.
        freeze = FreezeGuard.load(self._paths.frozen)
        if freeze.is_frozen("sports506", season):
            raise FrozenSeasonError(f"cannot import frozen season: sports506 {season}")

        result = ImportResult(season=season)
        collector = Sports506Collector(self._cache)
        requests_by_label = dict(zip(WEEK_LABELS, collector.plan(season), strict=True))
        pages = self._scan(incoming_dir, season, result)
        conflicted = {item.label for item in result.skipped_invalid}

        result.expected, result.expected_source, result.unsupported_labels = self._expected_weeks(
            season, pages
        )

        for label in WEEK_LABELS:
            req = requests_by_label[label]
            if label in conflicted:
                continue
            content = pages.get(label)
            if content is None:
                continue

            dest = self._paths.raw / req.cache_path
            if dest.exists() and not force:
                result.skipped_existing.append(label)
                continue

            reason = _validation_failure_reason(content, season)
            if reason is not None:
                result.skipped_invalid.append(SkippedFile(label=label, reason=reason))
                continue

            # D-03: reject a page that validates but parses to implausibly
            # few games/crews (a bad or incomplete hand-save, or an older
            # layout this parser can't read), before it's ever written.
            smoke = smoke_check(content, season=season, week_label=label)
            if not smoke.passed:
                result.skipped_invalid.append(
                    SkippedFile(label=label, reason=smoke.reason or "smoke check failed")
                )
                continue

            self._import_one(req, dest, content)
            result.imported.append(label)

        result.missing = [
            label
            for label in result.expected
            if not (self._paths.raw / requests_by_label[label].cache_path).exists()
        ]

        return result

    def _import_one(self, req: FetchRequest, dest: Path, content: bytes) -> None:
        atomic_write_bytes(dest, content)
        fetched_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        entry = ManifestEntry(
            url=req.url,
            source=req.source,
            season=req.season,
            kind="page",
            fetched_at=fetched_at,
            status=200,
            etag=None,
            last_modified=None,
            sha256=hashlib.sha256(content).hexdigest(),
            path=req.cache_path,
            bytes=len(content),
            final_url=req.url,
            origin=_MANUAL_ORIGIN,
        )
        self._manifest.append(entry)
