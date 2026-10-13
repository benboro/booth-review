"""The TV Ratings Guide monthly archive page (``/<yyyy>/<mm>/``) parser.

TVRG is a Blogger site. An archive page carries two lists of the month's
posts: the main column's post blocks (an ``h2``/``h3`` ``post-title`` heading
with the full title, then an ``abbr.published`` timestamp) and the sidebar
archive widget's expanded month (``ul.posts``, one truncated title per post,
nearly the whole month). Both are read and merged by URL, the main column's
full title winning. The pager is filled by script, so ``next_url`` is set only
when a static ``blog-pager-older-link`` anchor carries an on-host href.

Only ``https://www.thetvratingsguide.com/<yyyy>/<mm>/<slug>.html`` links are
kept; everything else (labels, profiles, images, other hosts) is ignored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from html.parser import HTMLParser
from typing import Final
from urllib.parse import urlsplit, urlunsplit

TVRG_HOST: Final = "www.thetvratingsguide.com"

_POST_PATH = re.compile(r"^/(\d{4})/(\d{2})/[A-Za-z0-9_.-]+\.html$")
_ARCHIVE_PATH = re.compile(r"^/(\d{4})/(\d{2})/?$|^/search$")
# "8/28/21", "10/1/2022", "10.1.2022": the same separator twice.
_TITLE_DATE = re.compile(r"(?<![\d/.])(\d{1,2})([/.])(\d{1,2})\2(\d{4}|\d{2})(?![\d/.])")
_RATINGS_WORD = re.compile(r"\bratings\b", re.IGNORECASE)


@dataclass(frozen=True)
class PostRef:
    url: str
    title: str
    published: date | None


@dataclass(frozen=True)
class ArchivePage:
    posts: list[PostRef]
    next_url: str | None


def post_url(href: str) -> str | None:
    """`href` as a canonical post URL, or None when it is not a TVRG post link."""
    parts = urlsplit(href.strip())
    if parts.scheme != "https" or parts.hostname != TVRG_HOST or parts.query:
        return None
    if not _POST_PATH.match(parts.path):
        return None
    return urlunsplit(("https", TVRG_HOST, parts.path, "", ""))


def _older_url(href: str) -> str | None:
    parts = urlsplit(href.strip())
    if parts.scheme != "https" or parts.hostname != TVRG_HOST:
        return None
    if not _ARCHIVE_PATH.match(parts.path):
        return None
    return urlunsplit(("https", TVRG_HOST, parts.path, parts.query, ""))


def title_date(title: str) -> date | None:
    """The first M/D/YY (or M/D/YYYY, or dotted) date in a post title."""
    match = _TITLE_DATE.search(title)
    if match is None:
        return None
    month, day, year_text = int(match.group(1)), int(match.group(3)), match.group(4)
    year = int(year_text) + (2000 if len(year_text) == 2 else 0)
    try:
        return date(year, month, day)
    except ValueError:
        return None


def is_ratings_title(title: str) -> bool:
    """A daily ratings post: the word "Ratings" and an air date in the title."""
    return bool(_RATINGS_WORD.search(title)) and title_date(title) is not None


def _published(stamp: str | None) -> date | None:
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(stamp.strip()).date()
    except ValueError:
        return None


def _classes(attrs: dict[str, str | None]) -> set[str]:
    return set((attrs.get("class") or "").split())


@dataclass
class _MainEntry:
    url: str
    title: str
    published: date | None = None


class _ArchiveParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.main: list[_MainEntry] = []
        self.sidebar: list[tuple[str, str]] = []
        self.next_url: str | None = None
        self._heading_depth = 0
        self._in_posts_list = 0
        self._href: str | None = None
        self._where: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        classes = _classes(attr)
        if tag in ("h1", "h2", "h3") and "post-title" in classes:
            self._heading_depth = 1
            return
        if tag == "ul" and "posts" in classes:
            self._in_posts_list += 1
            return
        if tag == "ul" and self._in_posts_list:
            self._in_posts_list += 1
            return
        if tag == "abbr" and "published" in classes and self.main:
            entry = self.main[-1]
            if entry.published is None:
                entry.published = _published(attr.get("title"))
            return
        if tag != "a":
            return
        href = attr.get("href") or ""
        if "blog-pager-older-link" in classes or attr.get("id") == "Blog1_blog-pager-older-link":
            older = _older_url(href)
            if older is not None and self.next_url is None:
                self.next_url = older
            return
        url = post_url(href)
        if url is None:
            return
        if self._heading_depth:
            self._href, self._where, self._text = url, "main", []
        elif self._in_posts_list:
            self._href, self._where, self._text = url, "sidebar", []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            title = " ".join("".join(self._text).split())
            if self._where == "main":
                self.main.append(_MainEntry(self._href, title))
            else:
                self.sidebar.append((self._href, title))
            self._href = self._where = None
            return
        if tag in ("h1", "h2", "h3") and self._heading_depth:
            self._heading_depth = 0
        elif tag == "ul" and self._in_posts_list:
            self._in_posts_list -= 1


def parse_archive(html: bytes | str) -> ArchivePage:
    """Every post the archive page links (main column first), and the older-posts URL."""
    text = html.decode("utf-8", errors="replace") if isinstance(html, bytes) else html
    parser = _ArchiveParser()
    parser.feed(text)
    parser.close()
    posts: list[PostRef] = []
    seen: set[str] = set()
    for entry in parser.main:
        if entry.url in seen:
            continue
        seen.add(entry.url)
        posts.append(PostRef(url=entry.url, title=entry.title, published=entry.published))
    for url, title in parser.sidebar:
        if url in seen:
            continue
        seen.add(url)
        posts.append(PostRef(url=url, title=title, published=None))
    return ArchivePage(posts=posts, next_url=parser.next_url)
