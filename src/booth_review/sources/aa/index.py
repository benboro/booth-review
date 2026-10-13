"""Awful Announcing sitemap parsing (Yoast-style index and child urlsets).

The sitemap index (``/sitemap_index.xml``) lists numbered child sitemaps
(``post-sitemap.xml``, ``post-sitemap2.xml`` ...) with a ``lastmod`` each; the
post sitemaps are filled oldest post first, so a child's ``lastmod`` (its
newest entry's modified time) climbs with its number once the early, undated
children are past. A child urlset lists ``<url><loc>/<lastmod>`` entries.

Untrusted XML: a document with a DOCTYPE or ENTITY declaration is refused
outright, and the parser never resolves entities or touches the network. Only
``https://awfulannouncing.com/`` URLs are kept; any other host is skipped.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Final, Literal
from urllib.parse import urlsplit, urlunsplit

from lxml import etree

from booth_review.errors import ParseError

AA_HOST: Final = "awfulannouncing.com"
SITEMAP_INDEX_URL: Final = f"https://{AA_HOST}/sitemap_index.xml"

_FORBIDDEN_DECL = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)
_POST_SITEMAP = re.compile(r"^/post-sitemap(\d*)\.xml$")
_WEEK_SLUG = re.compile(r"college-football-week-(\d{1,2})-viewership")
_SLUG_YEAR = re.compile(r"(?:^|-)(20\d{2})(?=-|$)")


@dataclass(frozen=True)
class SitemapRef:
    url: str
    lastmod: datetime | None

    @property
    def name(self) -> str:
        """File stem, e.g. ``post-sitemap40``."""
        return urlsplit(self.url).path.rsplit("/", 1)[-1].removesuffix(".xml")

    @property
    def post_number(self) -> int | None:
        """1 for ``post-sitemap.xml``, n for ``post-sitemap<n>.xml``, None otherwise."""
        match = _POST_SITEMAP.match(urlsplit(self.url).path)
        if match is None:
            return None
        return int(match.group(1)) if match.group(1) else 1


@dataclass(frozen=True)
class UrlEntry:
    url: str
    lastmod: datetime | None

    @property
    def slug(self) -> str:
        return urlsplit(self.url).path.rstrip("/").rsplit("/", 1)[-1].removesuffix(".html")


@dataclass(frozen=True)
class Sitemap:
    kind: Literal["index", "urlset"]
    sitemaps: list[SitemapRef]
    urls: list[UrlEntry]
    skipped: int
    """Entries dropped for an off-host or non-https loc."""


def _local(tag: object) -> str | None:
    if not isinstance(tag, str):
        return None  # comment, PI or an unresolved entity reference
    return tag.rsplit("}", 1)[-1]


def _lastmod(text: str | None) -> datetime | None:
    """A timezone-aware lastmod; WordPress's "-0001-11-30..." and junk give None."""
    if not text:
        return None
    try:
        value = datetime.fromisoformat(text.strip())
    except ValueError:
        return None
    return value if value.tzinfo is not None else None


def on_host(url: str) -> str | None:
    parts = urlsplit(url.strip())
    if parts.scheme != "https" or parts.hostname != AA_HOST or parts.query:
        return None
    return urlunsplit(("https", AA_HOST, parts.path, "", ""))


def parse_sitemap(xml: bytes) -> Sitemap:
    """Parse a sitemap index or urlset. Raises ParseError on a DOCTYPE/ENTITY
    declaration, invalid XML, or an unknown root element."""
    if _FORBIDDEN_DECL.search(xml):
        raise ParseError("aa sitemap: DOCTYPE/ENTITY declarations are forbidden")
    parser = etree.XMLParser(
        resolve_entities=False, no_network=True, huge_tree=False, load_dtd=False
    )
    try:
        root = etree.fromstring(xml, parser=parser)
    except etree.XMLSyntaxError as exc:
        raise ParseError(f"aa sitemap: invalid XML: {exc}") from exc
    kind = _local(root.tag)
    if kind == "sitemapindex":
        item_name = "sitemap"
    elif kind == "urlset":
        item_name = "url"
    else:
        raise ParseError(f"aa sitemap: unexpected root element {kind!r}")

    refs: list[tuple[str, datetime | None]] = []
    skipped = 0
    for item in root:
        if _local(item.tag) != item_name:
            continue
        loc: str | None = None
        lastmod: datetime | None = None
        for child in item:
            name = _local(child.tag)
            if name == "loc":
                loc = (child.text or "").strip()
            elif name == "lastmod":
                lastmod = _lastmod(child.text)
        url = on_host(loc) if loc else None
        if url is None:
            skipped += 1
            continue
        refs.append((url, lastmod))

    if kind == "sitemapindex":
        return Sitemap("index", [SitemapRef(url, lm) for url, lm in refs], [], skipped=skipped)
    return Sitemap("urlset", [], [UrlEntry(url, lm) for url, lm in refs], skipped=skipped)


def ordered_post_sitemaps(refs: Sequence[SitemapRef]) -> list[SitemapRef]:
    """Post sitemaps by number, keeping only those whose lastmod is set and no
    later than every higher-numbered one's (the climbing, datable run)."""
    posts = sorted(
        (ref for ref in refs if ref.post_number is not None and ref.lastmod is not None),
        key=lambda ref: ref.post_number or 0,
    )
    kept: list[SitemapRef] = []
    floor: datetime | None = None
    for ref in reversed(posts):
        assert ref.lastmod is not None
        if floor is None or ref.lastmod <= floor:
            kept.append(ref)
            floor = ref.lastmod
    kept.reverse()
    return kept


def select_post_sitemaps(refs: Sequence[SitemapRef], start: date, end: date) -> list[SitemapRef]:
    """The datable post sitemaps that can hold a post published in [start, end]:
    from the first whose lastmod reaches `start` through the first whose
    lastmod reaches `end` (inclusive)."""
    ordered = ordered_post_sitemaps(refs)
    selected: list[SitemapRef] = []
    for ref in ordered:
        assert ref.lastmod is not None
        if ref.lastmod.date() < start:
            continue
        selected.append(ref)
        if ref.lastmod.date() >= end:
            break
    return selected


def week_of_slug(slug: str) -> int | None:
    match = _WEEK_SLUG.search(slug)
    return int(match.group(1)) if match else None


def year_of_slug(slug: str) -> int | None:
    match = _SLUG_YEAR.search(slug)
    return int(match.group(1)) if match else None
