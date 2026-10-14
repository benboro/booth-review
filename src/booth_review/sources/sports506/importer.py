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
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

from booth_review.config import DataPaths
from booth_review.errors import FrozenSeasonError
from booth_review.mlb.layout import MLB_ROUNDS, mlb_506_path, mlb_506_url
from booth_review.nfl.layout import nfl_506_path, nfl_506_url
from booth_review.sources.sports506.collector import WEEK_LABELS
from booth_review.sources.sports506.mlb_parser import (
    Layout,
    detect_layout,
    discover_mlb_season_labels,
    mlb_smoke_check,
    parse_mlb_page,
)
from booth_review.sources.sports506.nfl_parser import nfl_smoke_check
from booth_review.sources.sports506.weeks import discover_season_weeks, smoke_check
from booth_review.transport.cache import (
    FreezeGuard,
    Manifest,
    ManifestEntry,
    RawCache,
    atomic_write_bytes,
)
from booth_review.transport.types import FetchRequest, Source

DEFAULT_INCOMING_DIR = Path("data/incoming/506/cfb")
LEGACY_INCOMING_DIR = Path("data/incoming/506")
# D-19: read the old root through the 2026 season, then delete this fallback.
ROOT_FALLBACK_LAST_SEASON = 2026
NFL_18_WEEK_FIRST_SEASON = 2021

_MANUAL_ORIGIN = "manual"

_CHALLENGE_MARKERS = ("just a moment", "cf-chl", "attention required")

# A saved week page names itself in its canonical link and its <title>, so the
# importer identifies pages by content and filenames don't matter (a browser's
# default "506 Sports - College Football_ Week 12, 2025.html" works as-is).
_CANONICAL_RE = re.compile(
    r"<link[^>]*rel=[\"']canonical[\"'][^>]*href=[\"'][^\"']*ncaaf\.php\?yr=(\d{4})(?:&amp;|&)wk=(\d{1,2}|B)[\"']",
    re.IGNORECASE,
)
# The lookahead keeps an "NFL Maps" title from reading as a CFB page.
_TITLE_RE = re.compile(
    r"<title>(?![^<]*\bNFL\b)[^<]*Week\s+(\d{1,2}|B),\s*(\d{4})[^<]*</title>", re.IGNORECASE
)
_FILENAME_RE = re.compile(r"^(\d{4})-wk(\d{1,2}|B)\.html$")

_NFL_CANONICAL_RE = re.compile(
    r"<link[^>]*rel=[\"']canonical[\"'][^>]*href=[\"'][^\"']*nfl\.php\?yr=(\d{4})(?:&amp;|&)wk=(\d{1,2})[\"']",
    re.IGNORECASE,
)
_NFL_TITLE_RE = re.compile(
    r"<title>[^<]*NFL Maps:\s*Week\s+(\d{1,2}),\s*(\d{4})[^<]*</title>", re.IGNORECASE
)
_NFL_FILENAME_RE = re.compile(r"^(\d{4})-nfl-wk(\d{1,2})\.html$")

# The MLB token is matched loosely (any short word) so an unexpected round label
# (a tiebreak page, say) is reported as unsupported instead of looking like junk.
_MLB_CANONICAL_RE = re.compile(
    r"<link[^>]*rel=[\"']canonical[\"'][^>]*href=[\"'][^\"']*mlb\.php\?yr=(\d{4})(?:&amp;|&)wk=(\d{1,2}|[A-Za-z]{1,4})[\"']",
    re.IGNORECASE,
)
_MLB_TITLE_RE = re.compile(
    r"<title>[^<]*MLB:\s*Week\s+(\d{1,2}|[A-Za-z]{1,4}),\s*(\d{4})[^<]*</title>", re.IGNORECASE
)
_MLB_FILENAME_RE = re.compile(r"^(\d{4})-mlb-wk(\d{1,2}|WC|DS|CS|WS)\.html$")
# D-21: 506 has no MLB round pages before 2025; 2026 weekly pages are cgame.
MLB_FIRST_PAGE_SEASON = 2025
MLB_WEEKLY_FIRST_SEASON = 2026
_MLB_MAX_WEEK = 30


class _Smoke(Protocol):
    @property
    def passed(self) -> bool: ...

    @property
    def reason(self) -> str | None: ...


@dataclass(frozen=True)
class PageProfile:
    """Everything that differs between the CFB and NFL 506 hand-save importers."""

    league: Literal["cfb", "nfl", "mlb"]
    source: Source
    canonical_re: re.Pattern[str]
    title_re: re.Pattern[str]
    filename_re: re.Pattern[str]
    labels: Callable[[int], tuple[str, ...]]
    request: Callable[[int, str], FetchRequest]
    smoke: Callable[[bytes, int, str], _Smoke]
    season_marker: Callable[[int], str]
    default_dir: Path


def _cfb_request(season: int, label: str) -> FetchRequest:
    name = label if label == "B" else label.zfill(2)
    return FetchRequest(
        source="sports506",
        season=season,
        url=f"https://506sports.com/ncaaf.php?yr={season}&wk={label}",
        cache_path=f"sports506/{season}/wk-{name}.html",
    )


def _nfl_request(season: int, label: str) -> FetchRequest:
    week = int(label)
    return FetchRequest(
        source="nfl_sports506",
        season=season,
        url=nfl_506_url(season, week),
        cache_path=nfl_506_path(season, week),
    )


def _nfl_labels(season: int) -> tuple[str, ...]:
    last = 18 if season >= NFL_18_WEEK_FIRST_SEASON else 17
    return tuple(str(n) for n in range(1, last + 1))


def _mlb_labels(season: int) -> tuple[str, ...]:
    if season < MLB_FIRST_PAGE_SEASON:
        return ()
    weeks = (
        tuple(str(n) for n in range(1, _MLB_MAX_WEEK + 1))
        if season >= MLB_WEEKLY_FIRST_SEASON
        else ()
    )
    return (*weeks, *MLB_ROUNDS)


def _mlb_request(season: int, label: str) -> FetchRequest:
    return FetchRequest(
        source="mlb_sports506",
        season=season,
        url=mlb_506_url(season, label),
        cache_path=mlb_506_path(season, label),
    )


@dataclass(frozen=True)
class _MlbSmoke:
    reason: str | None

    @property
    def passed(self) -> bool:
        return self.reason is None


def _mlb_smoke(content: bytes, season: int, label: str) -> _MlbSmoke:
    return _MlbSmoke(mlb_smoke_check(content, season=season, label=label))


CFB_PROFILE = PageProfile(
    league="cfb",
    source="sports506",
    canonical_re=_CANONICAL_RE,
    title_re=_TITLE_RE,
    filename_re=_FILENAME_RE,
    labels=lambda _season: tuple(WEEK_LABELS),
    request=_cfb_request,
    smoke=lambda content, season, label: smoke_check(content, season=season, week_label=label),
    season_marker=str,
    default_dir=DEFAULT_INCOMING_DIR,
)

NFL_PROFILE = PageProfile(
    league="nfl",
    source="nfl_sports506",
    canonical_re=_NFL_CANONICAL_RE,
    title_re=_NFL_TITLE_RE,
    filename_re=_NFL_FILENAME_RE,
    labels=_nfl_labels,
    request=_nfl_request,
    smoke=lambda content, season, label: nfl_smoke_check(content, season=season, week=int(label)),
    season_marker=str,
    default_dir=Path("data/incoming/506/nfl"),
)

MLB_PROFILE = PageProfile(
    league="mlb",
    source="mlb_sports506",
    canonical_re=_MLB_CANONICAL_RE,
    title_re=_MLB_TITLE_RE,
    filename_re=_MLB_FILENAME_RE,
    labels=_mlb_labels,
    request=_mlb_request,
    smoke=_mlb_smoke,
    season_marker=str,
    default_dir=Path("data/incoming/506/mlb"),
)


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
    root_pages: int = 0
    """D-19: recognized CFB pages taken from the legacy incoming root."""
    root_shadowed: list[str] = field(default_factory=list)
    """WR-05: weeks whose legacy-root page differs from the one in cfb/ (or
    conflicts within the root); the cfb/ page is used and the root one ignored."""

    out_of_scope: int = 0
    """MLB: pages in a layout the profile does not read (Fox coverage maps)."""
    unsupported_pages: list[str] = field(default_factory=list)
    """MLB: page labels that are neither a week nor a known round; never written."""
    changed_without_force: list[str] = field(default_factory=list)
    """MLB: labels whose saved page differs from the cached one and were kept."""
    replaced: list[str] = field(default_factory=list)
    """Labels whose cached page was overwritten by a forced re-import."""

    def counts(self) -> dict[str, int]:
        """Counts for vault.batch_message, count-only (never real page text)."""
        counts = {
            "imported": len(self.imported),
            "skipped": len(self.skipped_existing) + len(self.skipped_invalid),
        }
        if self.unsupported_pages:
            counts["unsupported"] = len(self.unsupported_pages)
        if self.out_of_scope:
            counts["out_of_scope"] = self.out_of_scope
        return counts

    @property
    def has_problems(self) -> bool:
        """True when something needs a human's attention."""
        return bool(
            self.missing
            or self.skipped_invalid
            or self.unsupported_labels
            or self.unsupported_pages
            or self.changed_without_force
        )


def _normalize_label(raw: str, season: int, profile: PageProfile) -> str | None:
    if profile.league == "mlb":
        # Membership is decided later so an odd round token is reported, not dropped.
        return str(int(raw)) if raw.isdigit() else raw.upper()
    label = raw if raw == "B" else str(int(raw))
    return label if label in profile.labels(season) else None


def _week_sort_key(label: str) -> tuple[int, int]:
    if label in MLB_ROUNDS:
        return (2, MLB_ROUNDS.index(label))
    return (1, 0) if label == "B" else (0, int(label))


def identify_page(
    path: Path, content: bytes, profile: PageProfile = CFB_PROFILE
) -> tuple[int, str] | None:
    """Return (season, week label) for a saved 506 week page, or None if unknown.

    Page content wins: the canonical link, then the title. The filename pattern
    `{season}-wk{label}.html` is only a fallback for pages that carry neither.
    """
    text = content.decode("utf-8", errors="replace")
    canonical = profile.canonical_re.search(text)
    if profile.league == "mlb":
        # T-09-11-01: when both are present, canonical link and title must agree.
        title_hit = profile.title_re.search(text)
        if canonical and title_hit:
            same = int(canonical.group(1)) == int(title_hit.group(2)) and _normalize_label(
                canonical.group(2), 0, profile
            ) == _normalize_label(title_hit.group(1), 0, profile)
            if not same:
                return None
    if canonical:
        season = int(canonical.group(1))
        label = _normalize_label(canonical.group(2), season, profile)
        return (season, label) if label else None
    title = profile.title_re.search(text)
    if title:
        season = int(title.group(2))
        label = _normalize_label(title.group(1), season, profile)
        return (season, label) if label else None
    named = profile.filename_re.match(path.name)
    if named:
        season = int(named.group(1))
        label = _normalize_label(named.group(2), season, profile)
        return (season, label) if label else None
    return None


def _looks_like_challenge_page(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _CHALLENGE_MARKERS)


def _looks_like_html(text: str) -> bool:
    lowered = text.lower()
    return "<html" in lowered or "<!doctype html" in lowered


def _validation_failure_reason(
    content: bytes, season: int, profile: PageProfile = CFB_PROFILE
) -> str | None:
    """Return a rejection reason, or None when `content` is acceptable."""
    if not content:
        return "empty file"
    text = content.decode("utf-8", errors="replace")
    if _looks_like_challenge_page(text):
        return "looks like a Cloudflare challenge/error page"
    if not _looks_like_html(text):
        return "does not look like HTML"
    if profile.season_marker(season) not in text:
        return f"does not mention {season}"
    return None


class Sports506Importer:
    """Imports hand-saved 506 week pages from an incoming folder into the vault."""

    def __init__(
        self, cache: RawCache, paths: DataPaths, *, profile: PageProfile = CFB_PROFILE
    ) -> None:
        self._profile = profile
        self._cache = cache
        self._paths = paths
        self._manifest = Manifest(paths.manifest)

    def _scan(
        self,
        incoming_dir: Path,
        season: int,
        result: ImportResult,
        saved_mtimes: dict[str, float] | None = None,
    ) -> dict[str, bytes]:
        """Map week label -> page bytes for every page of `season` in the folder.

        Other seasons' pages are left alone. HTML files that aren't 506 week
        pages (a Downloads folder holds plenty) are only counted. Two different
        files claiming the same week are both rejected rather than guessed at.
        When `saved_mtimes` is given it receives each week's file modified time
        (the browser's save time).
        """
        found: dict[str, bytes] = {}
        conflicts: set[str] = set()
        for path in sorted(incoming_dir.glob("*.htm*")):
            if not path.is_file():
                continue
            content = path.read_bytes()
            identity = identify_page(path, content, self._profile)
            if identity is None:
                result.unrecognized += 1
                continue
            page_season, label = identity
            if page_season != season:
                continue
            if self._profile.league == "mlb" and self._mlb_excluded(season, label, content, result):
                continue
            if label in found and found[label] != content:
                conflicts.add(label)
            found[label] = content
            if saved_mtimes is not None:
                saved_mtimes[label] = path.stat().st_mtime
        for label in sorted(conflicts):
            del found[label]
            if saved_mtimes is not None:
                saved_mtimes.pop(label, None)
            result.skipped_invalid.append(
                SkippedFile(label=label, reason="two different files claim this week")
            )
        return found

    def _mlb_excluded(self, season: int, label: str, content: bytes, result: ImportResult) -> bool:
        """True when an MLB page is counted out of the import (count-only reasons)."""
        if season < MLB_FIRST_PAGE_SEASON:
            result.skipped_invalid.append(
                SkippedFile(label=label, reason="no MLB round pages before 2025")
            )
            return True
        if label.isdigit() and detect_layout(content.decode("utf-8", errors="replace")) == "map":
            result.out_of_scope += 1
            return True
        if label not in self._profile.labels(season):
            if label not in result.unsupported_pages:
                result.unsupported_pages.append(label)
            return True
        return False

    def _mlb_expected_weeks(
        self, season: int, pages: dict[str, bytes]
    ) -> tuple[list[str], str, list[str]]:
        """2026 weeks come from the page nav; 2025 expects the four rounds."""
        known = set(self._profile.labels(season))
        nav: set[str] = set()
        if season >= MLB_WEEKLY_FIRST_SEASON:
            sources = list(pages.values())
            season_dir = self._paths.raw / "mlb" / "sports506" / str(season)
            if season_dir.is_dir():
                sources += [p.read_bytes() for p in sorted(season_dir.glob("wk-*.html"))]
            for content in sources:
                nav.update(discover_mlb_season_labels(content))
        unsupported = sorted(nav - known, key=_week_sort_key)
        if nav & known:
            return sorted(nav & known, key=_week_sort_key), "nav", unsupported
        default = list(MLB_ROUNDS) if known else []
        return default, "default", unsupported

    def _expected_weeks(
        self, season: int, pages: dict[str, bytes]
    ) -> tuple[list[str], str, list[str]]:
        """D-05: the week labels `season` itself lists, from every page we can
        see (this run's incoming pages plus whatever is already cached),
        never a fixed 18-week assumption.
        """
        if self._profile.league == "mlb":
            return self._mlb_expected_weeks(season, pages)
        if self._profile.league == "nfl":
            # NFL never relies on 506's nav: the week list is fixed by season.
            return list(self._profile.labels(season)), "default", []
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

    def run(
        self, season: int, *, incoming_dir: Path | None = None, force: bool = False
    ) -> ImportResult:
        profile = self._profile
        # D-06/D-07: a frozen season refuses every write, checked before any
        # file is scanned or touched.
        freeze = FreezeGuard.load(self._paths.frozen)
        if freeze.is_frozen(profile.source, season):
            raise FrozenSeasonError(f"cannot import frozen season: {profile.source} {season}")

        result = ImportResult(season=season)
        labels = profile.labels(season)
        requests_by_label = {label: profile.request(season, label) for label in labels}
        saved_mtimes: dict[str, float] = {}
        if incoming_dir is not None:
            pages = self._scan(incoming_dir, season, result, saved_mtimes)
        else:
            pages = self._scan(profile.default_dir, season, result, saved_mtimes)
            if profile.league == "cfb" and season <= ROOT_FALLBACK_LAST_SEASON:
                pages = self._merge_legacy_root(pages, season, result, saved_mtimes)
        conflicted = {item.label for item in result.skipped_invalid}

        result.expected, result.expected_source, result.unsupported_labels = self._expected_weeks(
            season, pages
        )

        for label in labels:
            req = requests_by_label[label]
            if label in conflicted:
                continue
            content = pages.get(label)
            if content is None:
                continue

            dest = self._paths.raw / req.cache_path
            if dest.exists() and not force:
                if profile.league == "mlb" and dest.read_bytes() != content:
                    result.changed_without_force.append(label)
                else:
                    result.skipped_existing.append(label)
                continue

            reason = _validation_failure_reason(content, season, profile)
            if reason is not None:
                result.skipped_invalid.append(SkippedFile(label=label, reason=reason))
                continue

            # D-03: reject a page that validates but parses to implausibly
            # few games/crews (a bad or incomplete hand-save, or an older
            # layout this parser can't read), before it's ever written.
            smoke = profile.smoke(content, season, label)
            if not smoke.passed:
                result.skipped_invalid.append(
                    SkippedFile(label=label, reason=smoke.reason or "smoke check failed")
                )
                continue

            replacing = dest.exists()
            self._import_one(req, dest, content, saved_mtimes[label])
            result.imported.append(label)
            if replacing:
                result.replaced.append(label)

        result.missing = [
            label
            for label in result.expected
            if not (self._paths.raw / requests_by_label[label].cache_path).exists()
        ]

        return result

    def _merge_legacy_root(
        self,
        pages: dict[str, bytes],
        season: int,
        result: ImportResult,
        saved_mtimes: dict[str, float],
    ) -> dict[str, bytes]:
        """D-19: add CFB pages saved at the old incoming root (non-recursive).

        Identical bytes in both folders collapse to one. When both folders hold
        different pages for one week, the cfb/ page wins and the week is listed
        in `root_shadowed` (WR-05): a fresh re-save goes to cfb/ while last
        week's stale save often stays at the root. Only two different files
        within one folder reject a week as a conflict.
        """
        root_mtimes: dict[str, float] = {}
        root_result = ImportResult(season=season)
        root_pages = self._scan(LEGACY_INCOMING_DIR, season, root_result, root_mtimes)
        result.unrecognized += root_result.unrecognized
        merged = dict(pages)
        conflicted = {item.label for item in result.skipped_invalid}
        for item in root_result.skipped_invalid:
            if item.label in merged and item.label not in conflicted:
                if item.label not in result.root_shadowed:
                    result.root_shadowed.append(item.label)
                continue
            if item.label not in conflicted:
                result.skipped_invalid.append(item)
                conflicted.add(item.label)
            merged.pop(item.label, None)
            saved_mtimes.pop(item.label, None)
        for label, content in root_pages.items():
            if label in conflicted:
                continue
            if label in merged:
                if merged[label] != content and label not in result.root_shadowed:
                    result.root_shadowed.append(label)
                continue
            merged[label] = content
            saved_mtimes[label] = root_mtimes[label]
            result.root_pages += 1
        result.root_shadowed.sort(key=_week_sort_key)
        return merged

    def _import_one(
        self, req: FetchRequest, dest: Path, content: bytes, saved_mtime: float
    ) -> None:
        atomic_write_bytes(dest, content)
        fetched_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        # The file's own modified time is when the browser saved the page.
        saved_at = datetime.fromtimestamp(saved_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
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
            saved_at=saved_at,
        )
        self._manifest.append(entry)


@dataclass(frozen=True)
class InspectRow:
    """One inspected file; carries no file name or page text (counts only)."""

    file_index: int
    season: int | None
    label: str | None
    layout: Layout
    listings: int
    non_game: int
    crew_listed: int
    verdict: Literal["importable", "out_of_scope", "unrecognized", "rejected"]


def inspect_folder(profile: PageProfile, folder: Path) -> tuple[list[InspectRow], dict[str, int]]:
    """Report each saved file's layout, label and counts without importing."""
    if profile.league != "mlb":
        raise NotImplementedError("inspect is only implemented for the MLB profile")
    rows: list[InspectRow] = []
    summary: dict[str, int] = {}

    def bump(key: str) -> None:
        summary[key] = summary.get(key, 0) + 1

    files = [p for p in sorted(folder.glob("*.htm*")) if p.is_file()]
    for index, path in enumerate(files):
        content = path.read_bytes()
        text = content.decode("utf-8", errors="replace")
        layout = detect_layout(text)
        identity = identify_page(path, content, profile)
        if identity is None:
            rows.append(InspectRow(index, None, None, layout, 0, 0, 0, "unrecognized"))
            bump("unrecognized")
            continue
        season, label = identity
        listings = non_game = crew = 0
        try:
            page = parse_mlb_page(content, season=season, label=label)
        except Exception:
            page = None
        if page is not None:
            listings, non_game = len(page.listings), len(page.non_game)
            crew = sum(1 for item in page.listings if item.crew_names)
        verdict: Literal["importable", "out_of_scope", "unrecognized", "rejected"]
        if season < MLB_FIRST_PAGE_SEASON:
            verdict = "rejected"
        elif label.isdigit() and layout == "map":
            verdict = "out_of_scope"
        elif (
            label not in profile.labels(season)
            or _validation_failure_reason(content, season, profile) is not None
            or not profile.smoke(content, season, label).passed
        ):
            verdict = "rejected"
        else:
            verdict = "importable"
        rows.append(InspectRow(index, season, label, layout, listings, non_game, crew, verdict))
        bump(verdict)
        bump(f"season_{season}")
    return rows, summary
