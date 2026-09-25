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
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from booth_review.config import DataPaths
from booth_review.sources.sports506.collector import WEEK_LABELS, Sports506Collector
from booth_review.transport.cache import Manifest, ManifestEntry, RawCache, atomic_write_bytes
from booth_review.transport.types import FetchRequest

DEFAULT_INCOMING_DIR = Path("data/incoming/506")

_MANUAL_ORIGIN = "manual"

_CHALLENGE_MARKERS = ("just a moment", "cf-chl", "attention required")


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

    def counts(self) -> dict[str, int]:
        """Counts for vault.batch_message, count-only (never real page text)."""
        return {
            "imported": len(self.imported),
            "skipped": len(self.skipped_existing) + len(self.skipped_invalid),
        }

    @property
    def has_problems(self) -> bool:
        """True when something needs a human's attention (missing or invalid files)."""
        return bool(self.missing or self.skipped_invalid)


def _candidate_filenames(season: int, label: str) -> list[str]:
    names = [f"{season}-wk{label}.html"]
    if label != "B":
        padded = label.zfill(2)
        if padded != label:
            names.append(f"{season}-wk{padded}.html")
    return names


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

    def _find_incoming_file(self, incoming_dir: Path, season: int, label: str) -> Path | None:
        for name in _candidate_filenames(season, label):
            candidate = incoming_dir / name
            if candidate.is_file():
                return candidate
        return None

    def run(self, season: int, *, incoming_dir: Path, force: bool = False) -> ImportResult:
        result = ImportResult(season=season)
        collector = Sports506Collector(self._cache)
        requests_by_label = dict(zip(WEEK_LABELS, collector.plan(season), strict=True))

        for label in WEEK_LABELS:
            req = requests_by_label[label]
            source_path = self._find_incoming_file(incoming_dir, season, label)
            if source_path is None:
                result.missing.append(label)
                continue

            dest = self._paths.raw / req.cache_path
            if dest.exists() and not force:
                result.skipped_existing.append(label)
                continue

            content = source_path.read_bytes()
            reason = _validation_failure_reason(content, season)
            if reason is not None:
                result.skipped_invalid.append(SkippedFile(label=label, reason=reason))
                continue

            self._import_one(req, dest, content)
            result.imported.append(label)

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
