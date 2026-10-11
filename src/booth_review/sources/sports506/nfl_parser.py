"""506 Sports NFL week-page parser: hand-saved HTML bytes into typed listings.

NFL pages (506sports.com/nfl.php?yr=<season>&wk=<week>) carry the regional
network, window and announcer crew of each Sunday game; kickoff times are not
on regional lines (they come from nflverse). The pages use three layouts:

- 2014-2015: one ``<table>`` per window, one ``<tr>`` per game with a bold
  matchup then ``-- crew [regions]`` in the same cell; no national block.
- 2016-2017: same table layout, matchup and crew split by ``<br>``, plus a
  "NATIONAL BROADCASTS" block of ``<li>`` lines.
- 2018 onward: one ``<div id="game">`` per game (``div#matchup`` and
  ``div#anncrs``), ``div#nogame`` placeholders, and the same national block.

Each window is introduced by a bold header ("CBS EARLY", "FOX SINGLE", ...).
All three layouts are read by one document-order walk that tracks the current
header, so the layouts need no separate code paths.

Only structural cleanup is applied to names: whitespace collapse, dropping
Alaska/Hawaii region brackets and parenthesized notes, and splitting a crew on
commas. Team and announcer resolution happens later through crosswalk tables.
Parse errors name only the season and week, never page content.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Literal

from bs4 import BeautifulSoup, Tag

from booth_review.errors import ParseError
from booth_review.sources.sports506.parser import (
    _collapse_whitespace,
    _decode,
    _split_matchup,
)

SMOKE_MIN_GAMES = 8
SMOKE_MIN_REGIONAL_CREW_SHARE = 0.90

Window = Literal["early", "late", "single", "national", "other"]

_NATIONAL_HEADER = "NATIONAL BROADCASTS"
# Bold uppercase text that is not a window header.
_NOT_HEADERS = frozenset({"NOTE", "NO GAME", "BOTH", "BYES"})
# Header tokens that end the network part of a header ("FOX TUESDAY" -> "FOX").
_HEADER_STOPS = frozenset(
    {
        "EARLY",
        "LATE",
        "(LATE)",
        "SINGLE",
        "MONDAY",
        "TUESDAY",
        "WEDNESDAY",
        "THURSDAY",
        "FRIDAY",
        "SATURDAY",
        "SUNDAY",
        "WEEK",
        "GAMES",
    }
)
_WINDOW_WORDS: dict[str, Window] = {
    "EARLY": "early",
    "LATE": "late",
    "(LATE)": "late",
    "SINGLE": "single",
}

_GAME_DIV_IDS = frozenset({"game", "nogame", "matchup", "anncrs", "updates", "map", "akhi"})
_INTL_RE = re.compile(r"\(\s*in\s+([^)]+?)\s*\)", re.IGNORECASE)
# National lines italicize the host city in three shapes: "(in London)", a bare
# "in London" and "(London)". Each is rewritten to "(in London)" so the city is
# never read as a team suffix or as the network.
_ITALIC_PLACE_RE = re.compile(
    r"^(?:\(\s*[Ii]n\s+(?P<a>[^()]+?)\s*\)"
    r"|[Ii]n\s+(?P<b>[^()]+?)"
    r"|\(\s*(?P<c>[A-Z][a-z]+(?:[ -][A-Z][a-z]+)*)\s*\))$"
)
_TRAILING_PAREN_RE = re.compile(r"\s*\([^)]*\)\s*$")
_PAREN_GROUP_RE = re.compile(r"\s*\(([^)]*)\)")
_BRACKET_RE = re.compile(r"\[[^\]]*\]")
# "(AK)" / "(AK; HI)" region markers: parens holding only two-letter codes.
_REGION_PAREN_RE = re.compile(r"\(\s*[A-Z]{2}(?:\s*[;,/]\s*[A-Z]{2})*\s*\)")
_TIME_RE = re.compile(
    r"^\d{1,2}(?::\d{2})?\s*(?:[ap]\.?m\.?)?(?:\s*ET)?$",
    re.IGNORECASE,
)
_LEAD_PUNCT_RE = re.compile(r"^[\s\-\u2013\u2014:]+")


@dataclass(frozen=True)
class NflListing506:
    """One game line from a 506 NFL week page, in page order."""

    season: int
    week: int
    network_raw: str
    window: Window
    away_raw: str
    home_raw: str
    neutral_site: bool
    crew_names: tuple[str, ...]
    is_national_line: bool
    intl_city: str | None
    national_time_et_raw: str | None
    source_row_index: int


@dataclass(frozen=True)
class NflSmokeResult:
    """Outcome of the NFL page smoke check; never carries page text."""

    passed: bool
    games: int
    regional: int
    regional_with_crew: int
    reason: str | None


def _error(season: int, week: int, reason: str) -> ParseError:
    return ParseError(f"506 nfl page season {season} week {week}: {reason}")


def _text_with_breaks(tag: Tag, *, drop_links: bool = False) -> str:
    """Text of a copy of `tag` with <br> as newlines (the page is not mutated)."""
    clone = copy.copy(tag)
    for br in clone.find_all("br"):
        br.replace_with("\n")
    if drop_links:
        for link in clone.find_all("a"):
            link.decompose()
    return clone.get_text()


def _clean_matchup(text: str) -> tuple[str, str, bool, str | None] | None:
    """(away, home, neutral, intl_city) from matchup text, dropping notes."""
    text = _collapse_whitespace(text)
    city: str | None = None
    intl = _INTL_RE.search(text)
    if intl is not None:
        city = intl.group(1)
        text = _collapse_whitespace(text[: intl.start()] + " " + text[intl.end() :])
    while True:
        trimmed = _TRAILING_PAREN_RE.sub("", text)
        if trimmed == text:
            break
        text = trimmed
    split = _split_matchup(text)
    if split is None:
        return None
    away, home, neutral = split
    if not away or not home:
        return None
    return away, home, neutral, city


def _split_crew(text: str) -> tuple[str, ...]:
    text = _BRACKET_RE.sub(" ", text)
    text = _REGION_PAREN_RE.sub(" ", text)
    text = _LEAD_PUNCT_RE.sub("", _collapse_whitespace(text))
    names = (_collapse_whitespace(part) for part in text.split(","))
    return tuple(name for name in names if name)


def _parse_header(text: str, last_network: str) -> tuple[str, Window, str]:
    """(network, window, network_to_remember) for a window header."""
    tokens = text.split()
    network_tokens: list[str] = []
    window: Window = "other"
    for token in tokens:
        if token in _HEADER_STOPS or token.startswith("("):
            break
        network_tokens.append(token)
    for token in tokens:
        if token in _WINDOW_WORDS:
            window = _WINDOW_WORDS[token]
            break
    network = " ".join(network_tokens)
    if not network:
        return last_network, window, last_network
    return network, window, network


def _header_text(bold: Tag) -> str | None:
    """Collapsed text of a window/national header <b>, else None."""
    if bold.find_parent(["td", "strong", "h2", "h3"]) is not None:
        return None
    if bold.parent is not None and bold.parent.name == "li":
        return None  # a label or network inside a national line
    if bold.find_parent("div", id=lambda value: value in _GAME_DIV_IDS) is not None:
        return None
    text = _collapse_whitespace(bold.get_text())
    if len(text) < 3 or text.endswith(":") or text != text.upper():
        return None
    if text in _NOT_HEADERS or not any(ch.isalpha() for ch in text):
        return None
    return text


def _is_time(token: str) -> bool:
    return bool(_TIME_RE.match(token)) and (
        ":" in token or re.search(r"[ap]\.?m|ET", token, re.IGNORECASE) is not None
    )


def _national_chunks(main: str) -> list[str]:
    """Split a national line at top-level ';' into matchup-led chunks."""
    parts: list[str] = []
    depth = 0
    current = ""
    for ch in main:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == ";" and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += ch
    parts.append(current)
    chunks: list[str] = []
    for part in parts:
        head = part.split("(", 1)[0]
        if _split_matchup(_collapse_whitespace(head)) is not None or not chunks:
            chunks.append(part)
        else:
            chunks[-1] += ";" + part
    return chunks


@dataclass
class _NationalFields:
    away: str
    home: str
    neutral: bool
    network: str
    crew: tuple[str, ...]
    city: str | None
    time_raw: str | None


def _parse_national_chunk(chunk: str) -> _NationalFields | None:
    chunk = _collapse_whitespace(chunk)
    city: str | None = None
    intl = _INTL_RE.search(chunk)
    if intl is not None:
        city = intl.group(1)
        chunk = _collapse_whitespace(chunk[: intl.start()] + " " + chunk[intl.end() :])
    cut = len(chunk)
    for marker in ("(", ";"):
        pos = chunk.find(marker)
        if pos != -1:
            cut = min(cut, pos)
    split = _split_matchup(chunk[:cut])
    if split is None:
        return None
    away, home, neutral = split
    if not away or not home:
        return None
    rest = chunk[cut:]
    contents: list[str] = []
    while True:
        match = _PAREN_GROUP_RE.match(rest)
        if match is None:
            break
        contents.append(match.group(1))
        rest = rest[match.end() :]
    rest = rest.strip()
    if rest.startswith(";"):
        contents.append(rest[1:])
    tokens: list[str] = []
    time_raw: str | None = None
    for content in contents:
        for segment in content.split(";"):
            for raw in segment.split(","):
                token = _collapse_whitespace(raw)
                if not token:
                    continue
                if _is_time(token) and time_raw is None:
                    time_raw = token
                elif not _is_time(token):
                    tokens.append(token)
    network = ""
    crew: tuple[str, ...] = ()
    if tokens:
        network = tokens[0]
        crew = _split_crew(",".join(tokens[1:]))
    return _NationalFields(away, home, neutral, network, crew, city, time_raw)


def _national_listings(li: Tag) -> list[_NationalFields]:
    clone = copy.copy(li)
    first = clone.find("b")
    if first is not None and _collapse_whitespace(first.get_text()).endswith(":"):
        first.decompose()
    for italic in clone.find_all("i"):
        place = _ITALIC_PLACE_RE.match(_collapse_whitespace(italic.get_text()))
        if place is not None:
            city = place.group("a") or place.group("b") or place.group("c")
            italic.replace_with(f" (in {city}) ")
    text = _text_with_breaks(clone, drop_links=True)
    text = text.split("█", 1)[0]
    lines = [_collapse_whitespace(line) for line in text.split("\n")]
    lines = [line for line in lines if line]
    if not lines:
        return []
    found: list[_NationalFields] = []
    for chunk in _national_chunks(lines[0]):
        fields = _parse_national_chunk(chunk)
        if fields is not None:
            found.append(fields)
    if found and not found[-1].crew:
        for extra in lines[1:]:
            if "(" not in extra and "@" not in extra:
                found[-1].crew = _split_crew(extra)
                break
    return found


def _regional_from_row(row: Tag) -> tuple[str, tuple[str, ...]] | None:
    """(matchup_text, crew) for a table row holding a bold matchup.

    The crew follows the matchup in the same cell ("Away @ Home -- crew", or
    after a <br>), or sits in the next cell of a three-cell row.
    """
    strong = row.find("strong")
    if not isinstance(strong, Tag):
        return None
    cell = strong.parent if isinstance(strong.parent, Tag) else row
    matchup = _collapse_whitespace(strong.get_text())
    full = _collapse_whitespace(_text_with_breaks(cell).replace("\n", " "))
    rest = full[len(matchup) :] if full.startswith(matchup) else ""
    if not _split_crew(rest):
        for sibling in cell.find_next_siblings("td"):
            rest += " " + _collapse_whitespace(_text_with_breaks(sibling).replace("\n", " "))
    return matchup, _split_crew(rest)


def parse_nfl_week_page(html: bytes, *, season: int, week: int) -> list[NflListing506]:
    """Parse one hand-saved 506 NFL week page into ordered listings.

    Raises ParseError (naming only season and week) for an empty body, a CFB
    page, or a page with no recognizable game lines.
    """
    if not html:
        raise _error(season, week, "empty response body")

    soup = BeautifulSoup(_decode(html), features="lxml")
    if soup.find("div", id="cgame") is not None or soup.select_one("table.listingtable"):
        raise _error(season, week, "page is not an nfl week page")

    root = soup.find("article") or soup.body or soup
    listings: list[NflListing506] = []
    network = ""
    window: Window = "other"
    last_network = ""
    national_mode = False

    def add(
        *,
        away: str,
        home: str,
        neutral: bool,
        crew: tuple[str, ...],
        is_national: bool,
        city: str | None,
        net: str,
        win: Window,
        time_raw: str | None = None,
    ) -> None:
        listings.append(
            NflListing506(
                season=season,
                week=week,
                network_raw=net,
                window=win,
                away_raw=away,
                home_raw=home,
                neutral_site=neutral,
                crew_names=crew,
                is_national_line=is_national,
                intl_city=city,
                national_time_et_raw=time_raw,
                source_row_index=len(listings),
            )
        )

    for element in list(root.find_all(["b", "tr", "div", "li"])):
        if element.name == "b":
            header = _header_text(element)
            if header is None:
                continue
            if _NATIONAL_HEADER in header:
                national_mode = True
                continue
            national_mode = False
            network, window, last_network = _parse_header(header, last_network)
        elif element.name == "tr":
            row = _regional_from_row(element)
            if row is None:
                continue
            cleaned = _clean_matchup(row[0])
            if cleaned is None:
                continue
            away, home, neutral, city = cleaned
            add(
                away=away,
                home=home,
                neutral=neutral,
                crew=row[1],
                is_national=False,
                city=city,
                net=network,
                win=window,
            )
        elif element.name == "div":
            if element.get("id") != "game":
                continue
            matchup_div = element.find("div", id="matchup")
            if not isinstance(matchup_div, Tag):
                continue
            cleaned = _clean_matchup(_text_with_breaks(matchup_div).replace("\n", " "))
            if cleaned is None:
                continue
            away, home, neutral, city = cleaned
            crew_div = element.find("div", id="anncrs")
            crew = _split_crew(_text_with_breaks(crew_div).replace("\n", " ")) if crew_div else ()
            add(
                away=away,
                home=home,
                neutral=neutral,
                crew=crew,
                is_national=False,
                city=city,
                net=network,
                win=window,
            )
        elif element.name == "li" and national_mode:
            if element.find_parent("font") is not None or element.find_parent(id="updates"):
                continue
            for fields in _national_listings(element):
                add(
                    away=fields.away,
                    home=fields.home,
                    neutral=fields.neutral,
                    crew=fields.crew,
                    is_national=True,
                    city=fields.city,
                    net=fields.network,
                    win="national",
                    time_raw=fields.time_raw,
                )

    if not listings:
        raise _error(season, week, "no game lines found")
    return listings


def nfl_smoke_check(
    html: bytes,
    *,
    season: int,
    week: int,
    expected_games: int | None = None,
) -> NflSmokeResult:
    """Sanity-check a parsed NFL page; never raises.

    Passes when the page has at least `expected_games` lines (or
    SMOKE_MIN_GAMES when unknown) and at least SMOKE_MIN_REGIONAL_CREW_SHARE
    of its regional (non-national) lines name a crew. National lines may have
    no crew, so they are left out of the share.
    """
    try:
        listings = parse_nfl_week_page(html, season=season, week=week)
    except ParseError as exc:
        return NflSmokeResult(False, 0, 0, 0, str(exc))
    games = len(listings)
    regional = [x for x in listings if not x.is_national_line]
    with_crew = sum(1 for x in regional if x.crew_names)
    minimum = expected_games if expected_games is not None else SMOKE_MIN_GAMES
    if games < minimum:
        reason: str | None = f"{games} games found, expected at least {minimum}"
    elif not regional:
        reason = "no regional lines found"
    elif with_crew / len(regional) < SMOKE_MIN_REGIONAL_CREW_SHARE:
        reason = (
            f"{with_crew} of {len(regional)} regional lines name a crew, "
            f"below {SMOKE_MIN_REGIONAL_CREW_SHARE:.0%}"
        )
    else:
        reason = None
    return NflSmokeResult(reason is None, games, len(regional), with_crew, reason)
