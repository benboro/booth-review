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


_GAME_NUMS = re.compile(r"(\d+)(?:\s*[-\N{EN DASH}\N{EM DASH}]\s*(\d+))?")


def _note_games(note: str) -> frozenset[int]:
    """Series games a "Games 1-3, 5-6" / "Game 4" note names (empty when it names none)."""
    m = re.search(r"\bgames?\b", note, re.I)
    if m is None:
        return frozenset()
    games: set[int] = set()
    for lo, hi in _GAME_NUMS.findall(note[m.end() :]):
        a = int(lo)
        b = int(hi) if hi else a
        if a <= b <= 9:
            games.update(range(a, b + 1))
    return frozenset(games)


def _stack_options(cell: str) -> list[tuple[str, frozenset[int]]]:
    """Each ``<br>``-stacked entry of a cell as (text without notes, games its note names)."""
    out: list[tuple[str, frozenset[int]]] = []
    for seg in cell.split(_BR):
        if not seg.strip():
            continue
        games: frozenset[int] = frozenset()
        for note in _NOTE.findall(seg):
            games = games | _note_games(note)
        out.append((seg, games))
    return out


def _per_game_assignments(
    pbp_cell: str, analyst_cell: str
) -> list[tuple[str, tuple[str, ...], frozenset[int]]] | None:
    """(pbp, analysts, games) groups when stacked cells carry per-game notes, else None."""
    pbp_opts = _stack_options(pbp_cell)
    an_opts = _stack_options(analyst_cell)
    stacked = len(pbp_opts) > 1 or len(an_opts) > 1
    all_games = frozenset().union(*(g for _, g in pbp_opts + an_opts)) if stacked else frozenset()
    if not all_games or not pbp_opts or not an_opts:
        return None

    def pick(opts: list[tuple[str, frozenset[int]]], g: int) -> str | None:
        for text, games in opts:
            if g in games:
                return text
        for text, games in opts:
            if not games:
                return text
        return None

    groups: dict[tuple[str, tuple[str, ...]], set[int]] = {}
    for g in sorted(all_games):
        pbp_text = pick(pbp_opts, g)
        if pbp_text is None:
            continue
        an_text = pick(an_opts, g) or an_opts[0][0]
        pbp = _first_stacked(pbp_text)
        analysts = tuple(_split_names(an_text.replace(_BR, ";")))
        if pbp and analysts:
            groups.setdefault((pbp, analysts), set()).add(g)
    return [(p, a, frozenset(g)) for (p, a), g in groups.items()]


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
            groups = _per_game_assignments(row[col["pbp"]], row[col["analysts"]])
            base = {
                "season": int(ym.group(0)),
                "round": _ROUND_FOR_KIND.get(round_kind, round_kind),
                "league": league,
                "network_raw": _flat(row[col["network"]]),
                "source_url": url,
            }
            if groups is not None:
                # Stacked cells with per-game notes: one per-game row per distinct crew, plus
                # the first-listed crew as the series fallback for games no note covers.
                first_an = tuple(_split_names(row[col["analysts"]].split(_BR)[0]))
                result.crews.append(
                    ListCrew(
                        **base,  # type: ignore[arg-type]
                        pbp_raw=_first_stacked(row[col["pbp"]]),
                        analysts_raw=first_an or analysts,
                        series_label=series or None,
                        scope="per_series",
                    )
                )
                for g_pbp, g_an, g_games in groups:
                    result.crews.append(
                        ListCrew(
                            **base,  # type: ignore[arg-type]
                            pbp_raw=g_pbp,
                            analysts_raw=g_an,
                            series_label="Games " + ", ".join(str(g) for g in sorted(g_games)),
                            scope="per_game",
                        )
                    )
                continue
            result.crews.append(
                ListCrew(
                    **base,  # type: ignore[arg-type]
                    pbp_raw=_first_stacked(row[col["pbp"]]),
                    analysts_raw=analysts,
                    series_label=label or None,
                    scope="per_game" if per_game else "per_series",
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
