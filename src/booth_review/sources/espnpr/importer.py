"""EspnPrImporter: hand-saved ESPN Press Room pages brought into the vault (04.19 D-12).

Disney's Terms of Use ban automated access to espnpressroom.com, so the only
route into the vault is this import of pages the user saved in a browser. It
takes no HTTP client and builds none.

Pages are identified by content, never by file name (verified structure in
04.19-37): the `<link rel="canonical">` URL on espnpressroom.com, backed by the
WordPress body class. `og:title` / `og:type` appear twice and can disagree, so
they are never read. Three data kinds are kept:

- commentators: the season page
  `/<yyyy>-<yy>-espn-college-football-commentators-schedule/`, overwritten every
  Monday with the current week only, so a save is keyed by its `WEEK N` heading
  -> raw/espnpr/<season>/commentators/wk-<N>.html
- release: a `/press-release/<slug>/` whose body holds the Date / Time (ET)
  schedule table -> raw/espnpr/<season>/releases/<slug>.html
- ratings: a `/press-release/<slug>/` that reports viewers (a viewers table or
  "N.N million" viewer wording) -> raw/espnpr/<season>/ratings/<slug>.html

A release's season comes from its published date (never the modified date: a
2026 site migration touched every old release). The category listing is
recognized and skipped with a message; it is not a data page.

Two different files claiming one page are both rejected, never guessed at;
with --force the newest save wins. Messages carry counts and reasons only,
never page text.
"""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal
from urllib.parse import unquote, urlsplit

from booth_review.config import DataPaths
from booth_review.transport.cache import FreezeGuard, Manifest, ManifestEntry, atomic_write_bytes

DEFAULT_INCOMING_DIR = Path("data/incoming/espnpr")
SOURCE = "espnpr"
HOSTS = frozenset({"espnpressroom.com", "www.espnpressroom.com"})

LISTING_MESSAGE = "category listing, not a data page; open a release from it and save that"

PageKind = Literal["commentators", "release", "ratings"]
_KIND_DIRS: dict[str, str] = {
    "commentators": "commentators",
    "release": "releases",
    "ratings": "ratings",
}

_MANUAL_ORIGIN = "manual"
_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_MAX_SLUG = 200
# A release published before July belongs to the season that started the
# previous August (bowls and the CFP final run into January).
_SEASON_START_MONTH = 7

_CHALLENGE_MARKERS = ("just a moment", "cf-chl", "attention required", "access denied")

_COMMENTATORS_PATH_RE = re.compile(
    r"^/(\d{4})-(\d{2})-espn-college-football-commentators-schedule/?$"
)
_RELEASE_PATH_RE = re.compile(r"^/press-release/([^/]+)/?$")
_LISTING_PATH_PREFIX = "/press-release-category/"
_LISTING_BODY_CLASS = "tax-press-release-category"
_POST_BODY_CLASS = "single-post"
_RELEASE_BODY_CLASS = "single-press-release"

_DROP_BLOCK_RE = re.compile(r"<(script|style|noscript)\b.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_PARAGRAPH_RE = re.compile(r"<p\b[^>]*>(.*?)</p\s*>", re.IGNORECASE | re.DOTALL)
_TABLE_RE = re.compile(r"<table\b.*?</table\s*>", re.IGNORECASE | re.DOTALL)
_ROW_RE = re.compile(r"<tr\b.*?</tr\s*>", re.IGNORECASE | re.DOTALL)
_CELL_RE = re.compile(r"<t[hd]\b[^>]*>(.*?)</t[hd]\s*>", re.IGNORECASE | re.DOTALL)
_TITLE_RE = re.compile(r"<title\b[^>]*>(.*?)</title\s*>", re.IGNORECASE | re.DOTALL)
_JSONLD_PUBLISHED_RE = re.compile(r'"datePublished"\s*:\s*"([^"]+)"')
_CONTENT_MARKERS = ("press-release-content", "brxe-post-content")

_WEEK_HEADING_RE = re.compile(r"^week\s+(\d{1,2})$", re.IGNORECASE)
_RELEASE_WEEK_RE = re.compile(r"[-\u2013\u2014]\s*week\s+(\d{1,2})$", re.IGNORECASE)
_TITLE_WEEK_RE = re.compile(r"\bweek\s+(\d{1,2})\b", re.IGNORECASE)
_MILLION_RE = re.compile(r"\b\d+(?:\.\d+)?\s*million\b", re.IGNORECASE)


# -- identification -------------------------------------------------------------------


@dataclass(frozen=True)
class EspnPrPage:
    """One identified data page."""

    kind: PageKind
    season: int
    key: str
    """The week label for a commentators page, else the sanitized slug."""
    canonical_url: str
    published: datetime | None = None
    week_label: str | None = None
    """ESPN's week label (commentators page always; weekly release when shown)."""

    @property
    def rel(self) -> str:
        """Path under raw/espnpr/<season>/."""
        name = f"wk-{self.key}" if self.kind == "commentators" else self.key
        return f"{_KIND_DIRS[self.kind]}/{name}.html"


ExamineStatus = Literal["page", "listing", "invalid", "unrecognized"]


@dataclass(frozen=True)
class Examined:
    """What one saved file is: a data page, the category listing, an invalid
    save (with a count-safe reason), or something that isn't an ESPN PR page."""

    status: ExamineStatus
    page: EspnPrPage | None = None
    reason: str | None = None


class _HeadScan(HTMLParser):
    """Collects the canonical link(s), published-time meta(s) and body class."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.canonicals: list[str] = []
        self.published: list[str] = []
        self.body_class: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name.lower(): (value or "") for name, value in attrs}
        if tag == "link" and "canonical" in values.get("rel", "").lower().split():
            href = values.get("href", "").strip()
            if href:
                self.canonicals.append(href)
        elif tag == "meta" and values.get("property", "").lower() == "article:published_time":
            content = values.get("content", "").strip()
            if content:
                self.published.append(content)
        elif tag == "body" and self.body_class is None:
            self.body_class = values.get("class", "")


def _clean(fragment: str) -> str:
    """Tag-free, entity-free, single-spaced text (U+00A0 read as a space)."""
    text = html.unescape(_TAG_RE.sub(" ", fragment)).replace("\u00a0", " ")
    return " ".join(text.split())


def _looks_like_challenge_page(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _CHALLENGE_MARKERS)


def _looks_like_html(text: str) -> bool:
    lowered = text.lower()
    return "<html" in lowered or "<!doctype html" in lowered


def _content_region(text: str) -> str:
    """The post body (scripts and styles dropped), or the whole page as a fallback."""
    stripped = _DROP_BLOCK_RE.sub(" ", text)
    for marker in _CONTENT_MARKERS:
        at = stripped.find(marker)
        if at >= 0:
            return stripped[at:]
    return stripped


def _first_row_cells(table: str) -> list[str]:
    row = _ROW_RE.search(table)
    if row is None:
        return []
    return [_clean(cell).lower() for cell in _CELL_RE.findall(row.group(0))]


def _is_schedule_header(cells: list[str]) -> bool:
    return len(cells) >= 2 and cells[0] == "date" and cells[1].startswith("time")


def _is_viewers_header(cells: list[str]) -> bool:
    return any(cell.endswith("viewers") for cell in cells)


def _first_schedule_table_at(content: str) -> int | None:
    for table in _TABLE_RE.finditer(content):
        if _is_schedule_header(_first_row_cells(table.group(0))):
            return table.start()
    return None


def _reports_viewers(content: str) -> bool:
    for table in _TABLE_RE.finditer(content):
        if _is_viewers_header(_first_row_cells(table.group(0))):
            return True
    prose = _clean(content)
    return bool(_MILLION_RE.search(prose)) and "viewer" in prose.lower()


def _commentators_week(content: str) -> str | None:
    """The `WEEK N` heading paragraph that leads the season page's body."""
    table_at = _first_schedule_table_at(content)
    head = content if table_at is None else content[:table_at]
    for paragraph in _PARAGRAPH_RE.finditer(head):
        match = _WEEK_HEADING_RE.match(_clean(paragraph.group(1)))
        if match:
            return str(int(match.group(1)))
    return None


def _release_week(content: str, text: str) -> str | None:
    """The bold `... - WEEK N` paragraph just before the table; the title as a fallback."""
    table_at = _first_schedule_table_at(content)
    head = content if table_at is None else content[:table_at]
    label: str | None = None
    for paragraph in _PARAGRAPH_RE.finditer(head):
        match = _RELEASE_WEEK_RE.search(_clean(paragraph.group(1)))
        if match:
            label = str(int(match.group(1)))
    if label is not None:
        return label
    title = _TITLE_RE.search(text)
    if title:
        match = _TITLE_WEEK_RE.search(_clean(title.group(1)))
        if match:
            return str(int(match.group(1)))
    return None


def _published(scan: _HeadScan, text: str) -> datetime | None:
    candidates = [*scan.published, *_JSONLD_PUBLISHED_RE.findall(text)]
    for raw in candidates:
        try:
            value = datetime.fromisoformat(raw.strip())
        except ValueError:
            continue
        if value.tzinfo is not None:
            return value
    return None


def season_of_release(published: datetime) -> int:
    """The college football season a release published at `published` belongs to."""
    return published.year if published.month >= _SEASON_START_MONTH else published.year - 1


def sanitize_slug(raw: str) -> str:
    """A path-safe slug: lowercase [a-z0-9-] only, no leading/trailing dashes."""
    slug = re.sub(r"[^a-z0-9-]+", "-", unquote(raw).lower())
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug[:_MAX_SLUG].strip("-")


def examine(content: bytes) -> Examined:
    """Classify one saved file by its content alone."""
    if not content.strip():
        return Examined("invalid", reason="empty file")
    text = content.decode("utf-8", errors="replace")
    if _looks_like_challenge_page(text):
        return Examined("invalid", reason="looks like a challenge or error page")
    if not _looks_like_html(text):
        return Examined("invalid", reason="does not look like HTML")

    scan = _HeadScan()
    scan.feed(text)
    scan.close()
    canonicals = set(scan.canonicals)
    if not canonicals:
        return Examined("unrecognized")
    if len(canonicals) > 1:
        return Examined("invalid", reason="more than one canonical link")
    canonical = canonicals.pop()
    parts = urlsplit(canonical)
    if parts.scheme != "https" or (parts.hostname or "").lower() not in HOSTS:
        return Examined("invalid", reason="canonical link is not on espnpressroom.com")
    body_class = (scan.body_class or "").split()

    if parts.path.startswith(_LISTING_PATH_PREFIX) or _LISTING_BODY_CLASS in body_class:
        return Examined("listing", reason=LISTING_MESSAGE)

    content_region = _content_region(text)

    commentators = _COMMENTATORS_PATH_RE.match(parts.path)
    if commentators:
        season = int(commentators.group(1))
        if int(commentators.group(2)) != (season + 1) % 100:
            return Examined("invalid", reason="season in the canonical link is malformed")
        if _POST_BODY_CLASS not in body_class:
            return Examined("invalid", reason="body class does not match the commentators page")
        heading = _commentators_week(content_region)
        if heading is None:
            return Examined("invalid", reason="commentators page has no WEEK heading")
        page = EspnPrPage(
            kind="commentators",
            season=season,
            key=heading,
            canonical_url=canonical,
            published=_published(scan, text),
            week_label=heading,
        )
        return Examined("page", page=page)

    release = _RELEASE_PATH_RE.match(parts.path)
    if release:
        if _RELEASE_BODY_CLASS not in body_class:
            return Examined("invalid", reason="body class does not match a press release")
        slug = sanitize_slug(release.group(1))
        if not slug:
            return Examined("invalid", reason="release link has no usable slug")
        published = _published(scan, text)
        if published is None:
            return Examined("invalid", reason="release has no published date")
        kind: PageKind
        week: str | None = None
        if _first_schedule_table_at(content_region) is not None:
            kind = "release"
            week = _release_week(content_region, text)
        elif _reports_viewers(content_region):
            kind = "ratings"
        else:
            return Examined("unrecognized")
        page = EspnPrPage(
            kind=kind,
            season=season_of_release(published),
            key=slug,
            canonical_url=canonical,
            published=published,
            week_label=week,
        )
        return Examined("page", page=page)

    return Examined("unrecognized")


def identify_page(text: str) -> EspnPrPage | None:
    """The data page `text` is, or None (listing, invalid or not an ESPN PR page)."""
    return examine(text.encode("utf-8")).page


# -- import ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PageRef:
    season: int
    kind: PageKind
    rel: str


@dataclass(frozen=True)
class SkippedFile:
    reason: str
    season: int | None = None


@dataclass
class EspnPrImportResult:
    """The outcome of one import run, which may span seasons (counts only)."""

    imported: list[PageRef] = field(default_factory=list)
    skipped_existing: list[PageRef] = field(default_factory=list)
    changed_without_force: list[PageRef] = field(default_factory=list)
    skipped_invalid: list[SkippedFile] = field(default_factory=list)
    superseded: int = 0
    """Older saves of one page dropped because --force kept the newest."""
    listings: int = 0
    unrecognized: int = 0
    problems: list[str] = field(default_factory=list)

    def seasons(self) -> list[int]:
        found = {
            ref.season
            for ref in (*self.imported, *self.skipped_existing, *self.changed_without_force)
        }
        found.update(item.season for item in self.skipped_invalid if item.season is not None)
        return sorted(found)

    def counts(self, season: int) -> dict[str, int]:
        """Counts for vault.batch_message for one season, count-only."""
        skipped = (
            sum(ref.season == season for ref in self.skipped_existing)
            + sum(ref.season == season for ref in self.changed_without_force)
            + sum(item.season == season for item in self.skipped_invalid)
        )
        return {
            "imported": sum(ref.season == season for ref in self.imported),
            "skipped": skipped,
        }

    @property
    def has_problems(self) -> bool:
        return bool(self.skipped_invalid or self.changed_without_force or self.problems)


@dataclass(frozen=True)
class _Candidate:
    page: EspnPrPage
    content: bytes
    mtime: float


class EspnPrImporter:
    """Imports hand-saved ESPN Press Room pages from an incoming folder into the vault.

    Takes no client: nothing here can send a request.
    """

    def __init__(self, paths: DataPaths) -> None:
        self._paths = paths
        self._manifest = Manifest(paths.manifest)

    def run(self, *, incoming_dir: Path | None = None, force: bool = False) -> EspnPrImportResult:
        result = EspnPrImportResult()
        folder = incoming_dir if incoming_dir is not None else DEFAULT_INCOMING_DIR
        if not folder.is_dir():
            result.problems.append("incoming folder not found")
            return result

        freeze = FreezeGuard.load(self._paths.frozen)
        for candidate in self._choose(self._scan(folder, result), force, result):
            page = candidate.page
            ref = PageRef(page.season, page.kind, page.rel)
            if freeze.is_frozen(SOURCE, page.season):
                result.skipped_invalid.append(SkippedFile("season is frozen", page.season))
                continue
            dest = self._paths.raw / SOURCE / str(page.season) / page.rel
            if dest.is_file():
                if dest.read_bytes() == candidate.content:
                    result.skipped_existing.append(ref)
                    continue
                if not force:
                    result.changed_without_force.append(ref)
                    continue
            self._write(dest, candidate)
            result.imported.append(ref)
        return result

    def _scan(self, folder: Path, result: EspnPrImportResult) -> list[_Candidate]:
        candidates: list[_Candidate] = []
        for path in sorted(folder.glob("*.htm*")):
            if not path.is_file():
                continue
            content = path.read_bytes()
            examined = examine(content)
            if examined.status == "unrecognized":
                result.unrecognized += 1
            elif examined.status == "listing":
                result.listings += 1
            elif examined.status == "invalid":
                result.skipped_invalid.append(SkippedFile(examined.reason or "invalid"))
            elif examined.page is not None:
                candidates.append(_Candidate(examined.page, content, path.stat().st_mtime))
        return candidates

    @staticmethod
    def _choose(
        candidates: list[_Candidate], force: bool, result: EspnPrImportResult
    ) -> list[_Candidate]:
        """One candidate per page. Identical copies collapse; different files
        claiming one page are all rejected, unless --force keeps the newest save."""
        groups: dict[tuple[int, str], list[_Candidate]] = {}
        for candidate in candidates:
            groups.setdefault((candidate.page.season, candidate.page.rel), []).append(candidate)
        chosen: list[_Candidate] = []
        for (season, _rel), group in sorted(groups.items()):
            distinct: dict[bytes, _Candidate] = {}
            for candidate in group:
                kept = distinct.get(candidate.content)
                if kept is None or candidate.mtime > kept.mtime:
                    distinct[candidate.content] = candidate
            if len(distinct) == 1:
                chosen.extend(distinct.values())
                continue
            if force:
                ordered = sorted(distinct.values(), key=lambda c: c.mtime)
                chosen.append(ordered[-1])
                result.superseded += len(ordered) - 1
                continue
            for _ in distinct:
                result.skipped_invalid.append(
                    SkippedFile("two different files claim this page", season)
                )
        return chosen

    def _write(self, dest: Path, candidate: _Candidate) -> None:
        page = candidate.page
        atomic_write_bytes(dest, candidate.content)
        entry = ManifestEntry(
            url=page.canonical_url,
            source=SOURCE,
            season=page.season,
            kind="page",
            fetched_at=datetime.now(UTC).strftime(_TIME_FORMAT),
            status=200,
            etag=None,
            last_modified=None,
            sha256=hashlib.sha256(candidate.content).hexdigest(),
            path=f"{SOURCE}/{page.season}/{page.rel}",
            bytes=len(candidate.content),
            final_url=page.canonical_url,
            origin=_MANUAL_ORIGIN,
            # The file's own modified time is when the browser saved the page.
            saved_at=datetime.fromtimestamp(candidate.mtime, UTC).strftime(_TIME_FORMAT),
        )
        self._manifest.append(entry)
