"""The TV Ratings Guide daily ratings post parser (04.19 D-10, D-17, D-21).

A post's body (``div.post-body.entry-content``) holds a small lead table and
then the data table, whose first row is the header: cable posts read
``Show | Network | 18-49 Viewers | Viewers (mil.)`` and broadcast posts
``Time | Show | 18-49 Rating/Share | Viewers (mil) | Network``. Columns are
found by header text, so both layouts parse the same way.

Only football game rows become rows: a Show cell of the form
``<label> Football: <away> v. <home>`` whose label is not a pro, high-school
or fantasy league. A football label with no game after it (a studio show, a
weather delay, an untitled window) becomes a ``non_game`` row; everything
else is counted as ignored. Reruns (`` (R)``) are ignored.

Units: TVRG prints viewers in millions with no suffix ("1.23" -> 1,230,000).
A number with any other trailing text (the stray "f") is ``unknown_suffix``;
a cell with no digit ("TBA", blank) is ``no_figure``. Two networks in one
cell ("ABC/ESPN2", "ABC & ESPN2") are a simulcast total and never a figure.

Pointers are ``<post-slug>:<line>``: the slug is ``<yyyy>-<mm>-<leaf>`` from
the post URL (the collector's cache file name), and the line is the row's
1-based position among the data table's rows below the header, blank rows
included, so a pointer can be re-read in the cached page. The row date is the
air date in the post title; rank is that date's ordinal, so a later post wins
a duplicate. Errors are count-only; nothing here fetches or executes anything.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urlsplit

from booth_review.sources.gapcollect import safe_slug
from booth_review.sources.second_rows import RowKind, SecondSourceRow, host_matches
from booth_review.sources.smw.rows import classify_row
from booth_review.sources.tvrg.index import title_date

_POST_PATH_RE = re.compile(r"^/(\d{4})/(\d{2})/([^/]+)\.html$")
_MILLIONS_RE = re.compile(r"^\d+(?:\.\d+)?$")
_FOOTBALL_RE = re.compile(r"^(?P<label>.*?)\bfootball\b\s*(?P<rest>.*)$", re.IGNORECASE)
# Leagues whose football rows are never college games.
_NON_COLLEGE_LABEL_RE = re.compile(
    r"\b(?:nfl|xfl|usfl|ufl|cfl|afl|arena|indoor|high\s+school|hs|fantasy|flag|canadian"
    r"|monday\s+night|sunday\s+night|thursday\s+night|women'?s|spring\s+league)\b",
    re.IGNORECASE,
)
_GAME_SEPARATOR_RE = re.compile(r"\s+(?:v\.?|vs\.?|at|@)\s+", re.IGNORECASE)
_RERUN_RE = re.compile(r"\(R\)\s*$")
_SIMULCAST_SLASH_RE = re.compile(r"/")


class TvrgParseError(ValueError):
    """A post that can't be parsed safely; the message is count-only."""


@dataclass(frozen=True)
class ParsedPost:
    rows: list[SecondSourceRow]
    ignored: int


def parse_tvrg_viewers(printed: str) -> int | None:
    """TVRG's unit rule: a bare number is millions ("1.23" -> 1,230,000); anything
    else (a trailing letter, "TBA", blank) -> None."""
    text = printed.strip().replace(",", "")
    if not _MILLIONS_RE.match(text):
        return None
    return round(float(text) * 1_000_000)


def post_slug(url: str) -> str:
    """``<yyyy>-<mm>-<leaf>`` for a post URL, the collector's cache file stem."""
    match = _POST_PATH_RE.match(urlsplit(url).path)
    if match is None:
        raise TvrgParseError("tvrg post URL is not a /<yyyy>/<mm>/<slug>.html path")
    year, month, leaf = match.groups()
    return f"{year}-{month}-{safe_slug(leaf)}"


def _classes(attrs: dict[str, str | None]) -> set[str]:
    return set((attrs.get("class") or "").split())


class _PostParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.canonical: str | None = None
        self.og_url: str | None = None
        self.tables: list[list[list[str]]] = []
        self._in_title = False
        self._body_depth = 0
        self._table_stack: list[list[list[str]]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        if tag == "title" and not self._body_depth:
            self._in_title = True
        elif tag == "link" and (attr.get("rel") or "").lower() == "canonical":
            self.canonical = self.canonical or attr.get("href")
        elif tag == "meta" and attr.get("property") == "og:url":
            self.og_url = self.og_url or attr.get("content")
        if tag == "div":
            if self._body_depth:
                self._body_depth += 1
            elif {"post-body", "entry-content"} <= _classes(attr):
                self._body_depth = 1
            return
        if not self._body_depth:
            return
        if tag == "table":
            table: list[list[str]] = []
            self._table_stack.append(table)
            self.tables.append(table)
        elif tag == "tr" and self._table_stack:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag == "div" and self._body_depth:
            self._body_depth -= 1
            return
        if not self._body_depth:
            return
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._table_stack:
                self._table_stack[-1].append(self._row)
            self._row = None
        elif tag == "table" and self._table_stack:
            self._table_stack.pop()

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        if self._cell is not None:
            self._cell.append(data)


def post_url_from_html(html: str) -> str | None:
    """The post's canonical URL (``link rel=canonical``, else ``og:url``)."""
    parser = _PostParser()
    parser.feed(html)
    parser.close()
    return parser.canonical or parser.og_url


def _data_table(tables: list[list[list[str]]]) -> list[list[str]] | None:
    for table in tables:
        if table and table[0] and table[0][0].strip().lower() in ("show", "time"):
            return table
    return None


def _columns(header: list[str]) -> tuple[int, int, int] | None:
    """(show, network, viewers) column indexes from the header row."""
    lowered = [cell.strip().lower() for cell in header]
    try:
        show = lowered.index("show")
        network = lowered.index("network")
    except ValueError:
        return None
    viewers = next((i for i, cell in enumerate(lowered) if cell.startswith("viewers")), None)
    if viewers is None:
        return None
    return show, network, viewers


def _cell(row: list[str], index: int) -> str:
    return row[index] if index < len(row) else ""


def parse_post(html: str, *, url: str, season: int) -> ParsedPost:
    """Every college football row of one cached TVRG post (see module docstring)."""
    if not host_matches("tvrg", url):
        raise TvrgParseError("tvrg post URL is not https on the source's host")
    slug = post_slug(url)
    parser = _PostParser()
    parser.feed(html)
    parser.close()
    title = " ".join("".join(parser.title_parts).split())
    air_date: date | None = title_date(title)
    rank = air_date.toordinal() if air_date is not None else 0

    table = _data_table(parser.tables)
    if table is None:
        return ParsedPost(rows=[], ignored=0)
    columns = _columns(table[0])
    if columns is None:
        raise TvrgParseError("tvrg data table header lacks a Show, Network or Viewers column")
    show_col, network_col, viewers_col = columns

    rows: list[SecondSourceRow] = []
    ignored = 0
    for line, cells in enumerate(table[1:], start=1):
        show = _cell(cells, show_col).strip()
        match = _FOOTBALL_RE.match(show)
        if (
            match is None
            or _NON_COLLEGE_LABEL_RE.search(match.group("label"))
            or _RERUN_RE.search(show)
        ):
            ignored += 1
            continue
        network = _cell(cells, network_col).strip()
        viewers_text = _cell(cells, viewers_col).strip()
        rest = match.group("rest").strip()
        away = home = ""
        kind: RowKind
        if not rest.startswith(":") or not rest[1:].strip():
            kind = "non_game"
        else:
            parts = _GAME_SEPARATOR_RE.split(rest[1:].strip())
            if len(parts) != 2 or not all(part.strip() for part in parts):
                kind = "needs_review"
            else:
                away, home = parts[0].strip(), parts[1].strip()
                if _SIMULCAST_SLASH_RE.search(network):
                    kind = "simulcast"
                else:
                    kind = classify_row(
                        {"network": network, "away": away, "home": home, "viewers": viewers_text},
                        parse=parse_tvrg_viewers,
                    )
        rows.append(
            SecondSourceRow(
                source="tvrg",
                season=season,
                pointer=f"{slug}:{line}",
                date_et=air_date,
                away_raw=away,
                home_raw=home,
                network_raw=network,
                viewers=parse_tvrg_viewers(viewers_text) if kind == "figure" else None,
                kind=kind,
                chart_kind="post",
                rank=rank,
                source_url=url,
                superseded=False,
            )
        )
    return ParsedPost(rows=rows, ignored=ignored)
