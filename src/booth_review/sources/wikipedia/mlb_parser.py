"""Parsers for MLB Wikipedia broadcaster lists, postseason articles and the national list.

Facts only (names, labels, URLs, a sentence hash): article prose is CC BY-SA 4.0
and is never stored. Unknown layouts return empty results plus an ``unparsed``
list so the build can report them; nothing is guessed.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Tag

from booth_review.sources.wikipedia.tables import expand_wikitable

_HEADER_ALIASES: dict[str, str] = {
    "year": "year",
    "season": "year",
    "network": "network",
    "channel": "network",
    "networks": "network",
    "play-by-play": "pbp",
    "play by play": "pbp",
    "color commentator(s)": "analysts",
    "color commentator": "analysts",
    "color commentator(s)/secondary play-by-play": "analysts",
    "color commentators": "analysts",
    "analyst(s)": "analysts",
    "analysts": "analysts",
    "analyst": "analysts",
    "color": "analysts",
    "league": "series",
    "series": "series",
}
_REQUIRED = {"year", "network", "pbp", "analysts"}
_YEAR = re.compile(r"\b(19|20)\d{2}\b")
_NOTE = re.compile(r"\(([^)]*)\)")
_SPLIT = re.compile(r"\s*(?:,|&|;|\band\b)\s*")
_BR = "\u00a6"  # marks a <br> inside a cell; names never contain it
_ROUND_FOR_KIND = {
    "wild_card": "WC",
    "lcs_al": "CS",
    "lcs_nl": "CS",
    "world_series": "WS",
}
_LEAGUE_FOR_KIND = {"lcs_al": "AL", "lcs_nl": "NL"}


@dataclass(frozen=True)
class ListCrew:
    season: int
    round: str
    league: str | None
    network_raw: str
    pbp_raw: str
    analysts_raw: tuple[str, ...]
    series_label: str | None
    scope: str
    source_url: str


@dataclass(frozen=True)
class MapProposal:
    season: int
    round: str
    league: str | None
    network_raw: str
    source_url: str
    evidence_hash: str


@dataclass(frozen=True)
class NationalCrew:
    network_raw: str
    rank: int
    pbp_raw: str
    analysts_raw: tuple[str, ...]
    source_url: str


@dataclass(frozen=True)
class UnparsedTable:
    table_index: int
    headers: tuple[str, ...]


@dataclass
class ListParse:
    crews: list[ListCrew] = field(default_factory=list)
    unparsed: list[UnparsedTable] = field(default_factory=list)


def _norm(text: str) -> str:
    folded = re.sub(r"\s+", " ", text).strip().lower()
    return folded.replace(" (s)", "(s)")  # live pages write "Color commentator (s)"


_NATIONAL_TV_EXCLUDED = ("radio", "local")


def _is_television_table(table: Tag) -> bool:
    """False for tables under a Radio or Local section: only national TV crews count."""
    heading = table.find_previous("h2")
    if heading is None:
        return True
    text = heading.get_text(" ").lower()
    return not any(word in text for word in _NATIONAL_TV_EXCLUDED)


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace(_BR, " ")).strip()


def _first_stacked(text: str) -> str:
    """The first of several play-by-play names stacked in one cell with ``<br>``.

    A cell like "A (Games 1-3)<br>B (Game 4)" names the series voice first and a
    one-game fill-in after; the series crew keeps the first name.
    """
    return _NOTE.sub("", text.split(_BR)[0]).strip()


def _split_names(text: str) -> list[str]:
    cleaned = _NOTE.sub("", text)
    return [n.strip() for n in _SPLIT.split(cleaned) if n.strip()]


def _league(text: str) -> str | None:
    low = text.lower()
    if "american" in low or re.search(r"\bal\b", low):
        return "AL"
    if "national" in low or re.search(r"\bnl\b", low):
        return "NL"
    return None


def _header_rows(grid: list[list[str]]) -> tuple[int, dict[int, str]] | None:
    """Find the header block: leading rows whose merged labels map to all required fields."""
    for depth in (1, 2, 3):
        if depth > len(grid):
            break
        merged: list[str] = []
        for col in range(len(grid[0])):
            labels: list[str] = []
            for r in range(depth):
                cell = grid[r][col]
                if cell and cell not in labels:
                    labels.append(cell)
            merged.append(labels[-1] if labels else "")
        mapping = {
            i: _HEADER_ALIASES[_norm(h)]
            for i, h in enumerate(merged)
            if _norm(h) in _HEADER_ALIASES
        }
        if set(mapping.values()) >= _REQUIRED:
            return depth, mapping
    return None


def _raw_analyst_cells(cell: str) -> tuple[tuple[str, ...], bool, str | None]:
    notes = _NOTE.findall(cell)
    per_game = any(re.search(r"\bgames?\b", n, re.I) for n in notes)
    note = next((n.strip() for n in notes if re.search(r"\bgames?\b", n, re.I)), None)
    return tuple(_split_names(cell)), per_game, note


def parse_broadcaster_list(html: str, url: str, round_kind: str) -> ListParse:
    soup = BeautifulSoup(html, "html.parser")
    result = ListParse()
    for t_idx, table in enumerate(soup.find_all("table")):
        if not isinstance(table, Tag) or table.find_parent("table") is not None:
            continue
        if not _is_television_table(table):
            continue
        grid = expand_wikitable(table, _BR)
        if not grid or not grid[0]:
            continue
        found = _header_rows(grid)
        if found is None:
            result.unparsed.append(UnparsedTable(t_idx, tuple(c for c in grid[0] if c)))
            continue
        depth, mapping = found
        col = {role: i for i, role in mapping.items()}
        for row in grid[depth:]:
            ym = _YEAR.search(row[col["year"]])
            if ym is None:
                continue
            analysts, per_game, note = _raw_analyst_cells(row[col["analysts"]].replace(_BR, ";"))
            series = _flat(row[col["series"]]) if "series" in col else ""
            league = _LEAGUE_FOR_KIND.get(round_kind) or (_league(series) if series else None)
            label = series or note if per_game else (series or None)
            result.crews.append(
                ListCrew(
                    season=int(ym.group(0)),
                    round=_ROUND_FOR_KIND.get(round_kind, round_kind),
                    league=league,
                    network_raw=_flat(row[col["network"]]),
                    pbp_raw=_first_stacked(row[col["pbp"]]),
                    analysts_raw=analysts,
                    series_label=label or None,
                    scope="per_game" if per_game else "per_series",
                    source_url=url,
                )
            )
    return result


_SECTION_WORDS = ("broadcasting", "television", "broadcasters", "broadcast")
_ROUND_WORDS: tuple[tuple[str, str], ...] = (
    ("wild card", "WC"),
    ("division series", "DS"),
    ("championship series", "CS"),
    ("world series", "WS"),
)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


_SKIP_SECTION_WORDS = ("radio", "streaming", "most watched", "notes", "references", "external")


def _is_heading(node: Tag) -> bool:
    if node.name in ("h2", "h3"):
        return True
    return node.name == "div" and "mw-heading" in (node.get("class") or [])


def _broadcast_sections(soup: BeautifulSoup) -> list[str]:
    """Prose under a Broadcasting/Television heading, headings wrapped or bare.

    Live pages wrap each heading in `div.mw-heading` and nest subsections in
    `<section>` siblings; radio, streaming and viewership sections are skipped.
    """
    texts: list[str] = []
    for head in soup.find_all(["h2", "h3"]):
        if _norm(head.get_text(" ")).strip() not in _SECTION_WORDS:
            continue
        holder = head.parent if head.parent is not None and _is_heading(head.parent) else head
        for sib in holder.find_next_siblings():
            if _is_heading(sib):
                break
            inner = sib.find(["h2", "h3", "h4"])
            title = _norm(inner.get_text(" ")) if inner is not None else ""
            if any(word in title for word in _SKIP_SECTION_WORDS):
                continue
            texts.append(sib.get_text(" "))
    return texts


def extract_postseason_map(
    html: str, season: int, url: str, network_names: Iterable[str]
) -> list[MapProposal]:
    """Propose (season, round, league, network) rows for human review."""
    names = [n for n in network_names if n]
    soup = BeautifulSoup(html, "html.parser")
    seen: set[tuple[str, str | None, str]] = set()
    out: list[MapProposal] = []
    for block in _broadcast_sections(soup):
        for sentence in _sentences(re.sub(r"\s+", " ", block)):
            low = sentence.lower()
            rounds = [code for word, code in _ROUND_WORDS if word in low]
            nets = [n for n in names if re.search(rf"\b{re.escape(n)}\b", sentence)]
            if not rounds or not nets:
                continue
            leagues: list[str | None] = []
            if "american league" in low or re.search(r"\bAL\b", sentence):
                leagues.append("AL")
            if "national league" in low or re.search(r"\bNL\b", sentence):
                leagues.append("NL")
            digest = hashlib.sha256(sentence.encode()).hexdigest()
            for rnd in rounds:
                round_leagues = [None] if rnd in ("WS", "WC") and not leagues else leagues or [None]
                if rnd == "WS":
                    round_leagues = [None]
                for lg in round_leagues:
                    for net in nets:
                        key = (rnd, lg, net)
                        if key in seen:
                            continue
                        seen.add(key)
                        out.append(MapProposal(season, rnd, lg, net, url, digest))
    return out


_CREW = re.compile(r"^\s*crew\s+(\d+)\s*[:\-]?\s*(.*)$", re.I)


def _crew_row(network: str, rank: int, names: list[str], url: str) -> NationalCrew | None:
    if not names:
        return None
    return NationalCrew(network, rank, names[0], tuple(names[1:]), url)


def parse_national_list(html: str, url: str) -> list[NationalCrew]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[NationalCrew] = []
    for head in soup.find_all(["h2", "h3"]):
        network = re.sub(r"\[.*?\]", "", head.get_text(" ")).strip()
        for sib in head.find_next_siblings():
            if sib.name in ("h2", "h3"):
                break
            if sib.name == "table" and isinstance(sib, Tag):
                grid = expand_wikitable(sib)
                if len(grid) < 2:
                    continue
                roles = [_HEADER_ALIASES.get(_norm(h), _norm(h)) for h in grid[0]]
                if "pbp" not in roles or "analysts" not in roles:
                    continue
                for row in grid[1:]:
                    m = _CREW.match(row[0])
                    if m is None:
                        continue
                    names = _split_names(row[roles.index("pbp")]) + _split_names(
                        row[roles.index("analysts")]
                    )
                    crew = _crew_row(network, int(m.group(1)), names, url)
                    if crew:
                        out.append(crew)
            else:
                for li in sib.find_all("li") if sib.name in ("ul", "ol") else [sib]:
                    m = _CREW.match(li.get_text(" "))
                    if m is None:
                        continue
                    crew = _crew_row(network, int(m.group(1)), _split_names(m.group(2)), url)
                    if crew:
                        out.append(crew)
    return out
