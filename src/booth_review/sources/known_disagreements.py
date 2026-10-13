"""Known RR disagreements for the post-based second sources (04.19 D-02, D-10, D-12).

TVRG, AA and ESPN Press Room each keep one ``known_disagreements.csv`` per
season in the vault at ``raw/<source>/<season>/known_disagreements.csv``, with
the SMW columns (``chart_file,row,explanation``): ``chart_file`` holds the post
(or ratings release) slug and ``row`` the line, so ``<chart_file>:<row>`` is
the row's pointer. TVRG and AA posts are cached under ``posts/``; ESPN Press
Room ratings releases, imported by hand, under ``ratings/``. The file is
written by hand under ``data/incoming/`` and enters the vault only through
``booth-review import known``, which validates it against the cached posts
and copies it atomically with a manual manifest entry. Messages carry file
names, line numbers and counts only, never a cell value.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal

from booth_review.config import DataPaths
from booth_review.errors import BoothReviewError, FrozenSeasonError, ReferenceTableError
from booth_review.reference import read_reference_csv_numbered
from booth_review.sources.aa import parser as aa_parser
from booth_review.sources.espnpr import parser as espnpr_parser
from booth_review.sources.second_rows import (
    ParsedPost,
    RejectedPage,
    RejectReason,
    SecondSourceRow,
    host_matches,
)
from booth_review.sources.smw.diff import KNOWN_DISAGREEMENT_COLUMNS
from booth_review.sources.tvrg import parser as tvrg_parser
from booth_review.transport.cache import FreezeGuard, Manifest, ManifestEntry
from booth_review.transport.cache import atomic_write_bytes as _atomic_write_bytes

PostSource = Literal["tvrg", "aa", "espnpr"]
POST_SOURCES: Final[tuple[PostSource, ...]] = ("tvrg", "aa", "espnpr")
# Waves B and C cover Ratings Reference's 2021-2024 gaps only.
POST_SEASONS: Final = range(2021, 2025)
KNOWN_FILE: Final = "known_disagreements.csv"
MAX_EXPLANATION: Final = 200

_SLUG_RE = re.compile(r"^[a-z0-9-]+$")
_MANUAL_ORIGIN = "manual"
_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


@dataclass(frozen=True)
class _PostParser:
    url_from_html: Callable[[str], str | None]
    parse: Callable[..., ParsedPost]
    error: type[ValueError]
    folder: str = "posts"


_PARSERS: Final[Mapping[PostSource, _PostParser]] = {
    "tvrg": _PostParser(
        tvrg_parser.post_url_from_html, tvrg_parser.parse_post, tvrg_parser.TvrgParseError
    ),
    "aa": _PostParser(aa_parser.post_url_from_html, aa_parser.parse_post, aa_parser.AaParseError),
    "espnpr": _PostParser(
        espnpr_parser.viewership_url_from_html,
        espnpr_parser.parse_viewership,
        espnpr_parser.EspnPrParseError,
        folder="ratings",
    ),
}


def known_path(paths: DataPaths, source: PostSource, season: int) -> Path:
    return paths.raw / source / str(season) / KNOWN_FILE


def load_known(path: Path) -> frozenset[str]:
    """Strictly read one known-disagreements file; the pointers it lists."""

    def fail(line_no: int, what: str) -> ReferenceTableError:
        return ReferenceTableError(f"{path.name}: line {line_no}: {what}")

    pointers: set[str] = set()
    for line_no, raw in read_reference_csv_numbered(
        path, KNOWN_DISAGREEMENT_COLUMNS, required=True
    ):
        slug, row = raw["chart_file"], raw["row"]
        if not _SLUG_RE.match(slug):
            raise fail(line_no, "chart_file must be a post slug ([a-z0-9-])")
        if not (row.isascii() and row.isdecimal()) or int(row) <= 0:
            raise fail(line_no, "row must be a positive integer")
        explanation = raw["explanation"].strip()
        if not explanation or len(explanation) > MAX_EXPLANATION:
            raise fail(line_no, f"explanation must be 1-{MAX_EXPLANATION} characters")
        pointer = f"{slug}:{int(row)}"
        if pointer in pointers:
            raise fail(line_no, "duplicate (chart_file, row)")
        pointers.add(pointer)
    return frozenset(pointers)


@dataclass(frozen=True)
class CachedPosts:
    rows: list[SecondSourceRow]
    ignored: int
    # Posts skipped because they lack an on-host canonical URL or their parser
    # refuses them; the build lists them in interim/ and counts them on the gate.
    rejected: tuple[RejectedPage, ...] = ()


def examine_post(
    source: PostSource, html: str, season: int
) -> tuple[ParsedPost | None, RejectReason | None]:
    """(parsed post, None), or (None, why) when the post has no canonical URL,
    one off the source's host, or its parser refuses it."""
    parser = _PARSERS[source]
    url = parser.url_from_html(html)
    if url is None:
        return None, "no_canonical_url"
    if not host_matches(source, url):
        return None, "off_host_url"
    try:
        return parser.parse(html, url=url, season=season), None
    except parser.error:
        return None, "parse_error"


def read_cached_posts(paths: DataPaths, source: PostSource, season: int) -> CachedPosts:
    """Parse every cached post of one (source, season). A post with no canonical
    URL on the source's host, or one its parser refuses, is skipped and returned
    in `rejected` (vault path and reason), so one bad page never stops the build."""
    parser = _PARSERS[source]
    folder = paths.raw / source / str(season) / parser.folder
    if not folder.is_dir():
        return CachedPosts(rows=[], ignored=0)
    rows: list[SecondSourceRow] = []
    rejected: list[RejectedPage] = []
    ignored = 0
    for post in sorted(folder.glob("*.html")):
        html = post.read_text(encoding="utf-8", errors="replace")
        parsed, reason = examine_post(source, html, season)
        if parsed is None:
            assert reason is not None
            rejected.append(
                RejectedPage(
                    source=source,
                    season=season,
                    path=post.relative_to(paths.raw).as_posix(),
                    reason=reason,
                )
            )
            continue
        rows.extend(parsed.rows)
        ignored += parsed.ignored
    return CachedPosts(rows=rows, ignored=ignored, rejected=tuple(rejected))


# -- import known ------------------------------------------------------------------------


@dataclass
class KnownImportResult:
    """The outcome of one `import known` (counts only)."""

    source: str
    season: int
    imported: int = 0
    skipped: int = 0
    changed_without_force: bool = False
    problems: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return {"imported": self.imported, "skipped": self.skipped}

    @property
    def has_problems(self) -> bool:
        return bool(self.problems or self.changed_without_force)


def import_known(
    paths: DataPaths,
    source: PostSource,
    season: int,
    from_file: Path,
    *,
    force: bool = False,
) -> KnownImportResult:
    """Validate `from_file` and copy it into the vault (see module docstring).

    Every pointer must name a row the cached posts parse to; nothing is written
    when anything fails. An identical vault copy is skipped; a different one
    needs `force`.
    """
    if source not in POST_SOURCES:
        raise ValueError(f"import known takes one of {len(POST_SOURCES)} post sources")
    result = KnownImportResult(source=source, season=season)
    if season not in POST_SEASONS:
        result.problems.append("season is outside 2021-2024")
        return result
    if FreezeGuard.load(paths.frozen).is_frozen(source, season):
        raise FrozenSeasonError(f"cannot import frozen season: {source} {season}")
    if not from_file.is_file():
        result.problems.append(f"{from_file.name} is missing")
        return result
    try:
        pointers = load_known(from_file)
        posts = read_cached_posts(paths, source, season)
    except BoothReviewError as exc:
        result.problems.append(f"{type(exc).__name__}: {exc}")
        return result
    # The import stays strict: a known file is checked against every cached post.
    if posts.rejected:
        result.problems.append(
            f"{len(posts.rejected)} cached post(s) lack an on-host canonical URL or don't parse"
        )
        return result
    cached = {row.pointer for row in posts.rows}
    unknown = pointers - cached
    if unknown:
        result.problems.append(f"{len(unknown)} pointer(s) name no row of a cached post")
        return result

    content = from_file.read_bytes()
    dest = known_path(paths, source, season)
    if dest.is_file():
        if dest.read_bytes() == content:
            result.skipped = 1
            return result
        if not force:
            result.changed_without_force = True
            return result
    _atomic_write_bytes(dest, content)
    rel = f"{source}/{season}/{KNOWN_FILE}"
    now = datetime.now(UTC).strftime(_TIME_FORMAT)
    Manifest(paths.manifest).append(
        ManifestEntry(
            url=f"manual:{rel}",
            source=source,
            season=season,
            kind="known_disagreements",
            fetched_at=now,
            status=200,
            etag=None,
            last_modified=None,
            sha256=hashlib.sha256(content).hexdigest(),
            path=rel,
            bytes=len(content),
            final_url=f"manual:{rel}",
            origin=_MANUAL_ORIGIN,
            saved_at=datetime.fromtimestamp(from_file.stat().st_mtime, UTC).strftime(_TIME_FORMAT),
        )
    )
    result.imported = 1
    return result
