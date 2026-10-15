"""506 Sports MLB page parser: hand-saved HTML bytes into typed listings.

MLB pages (506sports.com/mlb.php?yr=<season>&wk=<label>) come in these layouts:

- ``cgame``: ``<h3>Weekday, Month DD</h3>`` date headers followed by
  ``<div id="cgame">`` blocks with ``#cmatchup``, ``#ctime``, ``#cntwk`` and
  ``#canncrs`` (2026 weekly pages, and round pages with or without a round
  header paragraph and note).
- ``map``: Fox coverage maps (``div#map`` plus ``div#game`` blocks); recognised
  but out of scope for the MLB profile, so they yield no listings.

Only structural cleanup is applied: whitespace collapse, suffix markers
(``Game N:``, ``(Game N)``, ``(in City)``, ``(rained out)``), outlet-cell
splitting and crew splitting on commas. Team, network and announcer names are
resolved later through crosswalk tables. Crews come only from the crew cell of
a game block, never from note paragraphs, and HTML comments are never read.
Parse errors and smoke reasons name only the season, label and counts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Literal

from bs4 import BeautifulSoup, Tag

from booth_review.errors import ParseError
from booth_review.mlb.constants import (
    MLB_SMOKE_MIN_LISTINGS,
    MLB_SMOKE_MIN_OUTLET_SHARE,
    MLB_SMOKE_MIN_ROUND_CREW_SHARE,
)
from booth_review.mlb.layout import MLB_ROUNDS
from booth_review.sources.sports506.parser import (
    collapse_whitespace,
    decode_html,
    split_matchup,
)

Layout = Literal["cgame", "listingtable", "map", "unknown"]
NonGameKind = Literal["all_star", "home_run_derby", "exhibition", "blank", "other"]

_SISTER_TOKENS = ("NBCSN", "truTV")

_NAV_RE = re.compile(r"mlb\.php\?yr=\d+(?:&amp;|&)wk=(\d{1,2}|WC|DS|CS|WS)\b", re.IGNORECASE)
_SERIES_PREFIX_RE = re.compile(r"^Game\s+(\d+)\s*:\s*", re.IGNORECASE)
_TRAILING_PAREN_RE = re.compile(r"\s*\(([^()]*)\)\s*$")
_GAME_NUMBER_RE = re.compile(r"^Game\s+([12])$", re.IGNORECASE)
_IN_RE = re.compile(r"^in\s+(.+)$", re.IGNORECASE)
_WINDOW_RE = re.compile(r"\(\s*(\w+)\s+circle[^)]*on map\s*\)", re.IGNORECASE)
# Live pages mark the map window with a colored emoji circle instead of the words.
_EMOJI_WINDOWS = {
    "\U0001f534": "red",
    "\U0001f535": "blue",
    "\U0001f7e2": "green",
    "\U0001f7e1": "yellow",
    "\U0001f7e0": "orange",
    "\U0001f7e3": "purple",
}
_EMOJI_WINDOW_RE = re.compile(r"\(\s*([" + "".join(_EMOJI_WINDOWS) + r"])\s*on map\s*\)")
# A star ends an outlet token even when the next outlet follows with no space ("MLBN*ESPN Unltd").
_STAR_SPLIT_RE = re.compile(r"(?<=\*)\s*(?=\S)")
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})\s*([AP]M)", re.IGNORECASE)
_NOT_PLAYED = ("rained out", "postponed")


@dataclass(frozen=True)
class MlbOutletCell:
    """One outlet named in a 506 network cell (names resolve later)."""

    raw_name: str
    starred: bool
    window: str | None
    local_outlet: str | None


@dataclass(frozen=True)
class MlbListing506:
    """One game block from a 506 MLB page, in page order."""

    season: int
    label: str
    game_date: date | None
    time_et: str
    away_raw: str
    home_raw: str
    neutral: bool
    series_game: int | None
    game_number: int
    venue_note: str | None
    outlets: tuple[MlbOutletCell, ...]
    crew_names: tuple[str, ...]
    local_simulcast: bool
    not_played: bool
    round_header: str | None


@dataclass(frozen=True)
class MlbNonGameRow:
    """A block that is not a regular game; no row text is stored."""

    season: int
    label: str
    game_date: date | None
    kind: NonGameKind


@dataclass(frozen=True)
class MlbPage:
    """Parsed page: listings, non-game rows and the nav labels seen."""

    layout: Layout
    listings: tuple[MlbListing506, ...]
    non_game: tuple[MlbNonGameRow, ...]
    labels_in_nav: tuple[str, ...]


def _error(season: int, label: str, reason: str) -> ParseError:
    return ParseError(f"506 mlb page season {season} label {label}: {reason}")


def _soup(content: bytes) -> BeautifulSoup:
    return BeautifulSoup(decode_html(content), features="lxml")


def _detect(soup: BeautifulSoup) -> Layout:
    if soup.find("div", id="cgame") is not None:
        return "cgame"
    if soup.find("table", class_="listingtable") is not None:
        return "listingtable"
    if soup.find("div", id="map") is not None or soup.find("div", id="game") is not None:
        return "map"
    return "unknown"


def detect_layout(html: str) -> Layout:
    """The layout of a decoded MLB page, or "unknown"."""
    return _detect(BeautifulSoup(html, features="lxml"))


def _date_header(text: str, year: int) -> date | None:
    _, _, month_day = text.partition(",")
    try:
        return datetime.strptime(  # noqa: DTZ007
            f"{collapse_whitespace(month_day)} {year}", "%B %d %Y"
        ).date()
    except ValueError:
        return None


def parse_outlet_cell(raw: str) -> tuple[MlbOutletCell, ...]:
    """Split one network cell into outlet cells (structural only)."""
    text = collapse_whitespace(raw)
    window: str | None = None
    match = _WINDOW_RE.search(text)
    emoji = _EMOJI_WINDOW_RE.search(text) if match is None else None
    if match is None and emoji is not None:
        window = _EMOJI_WINDOWS[emoji.group(1)]
        text = collapse_whitespace(text[: emoji.start()] + " " + text[emoji.end() :])
    elif match is not None:
        window = match.group(1).lower()
        text = collapse_whitespace(text[: match.start()] + " " + text[match.end() :])
    if not text:
        return ()
    first, _, second = text.partition(" / ")
    local_outlet: str | None = None
    second = second.strip().rstrip("*").strip()
    if second and second not in _SISTER_TOKENS:
        local_outlet = second
    cells: list[MlbOutletCell] = []
    for token in _STAR_SPLIT_RE.split(first.strip()):
        starred = token.endswith("*")
        name = token.rstrip("*").strip()
        if name:
            cells.append(MlbOutletCell(name, starred, window, local_outlet))
    return tuple(cells)


def _non_game_kind(text: str) -> NonGameKind:
    lowered = text.lower()
    if not lowered:
        return "blank"
    if "all-star" in lowered or "all star" in lowered:
        return "all_star"
    if "derby" in lowered:
        return "home_run_derby"
    if "exhibition" in lowered or "spring training" in lowered:
        return "exhibition"
    return "other"


def _time_minutes(time_et: str) -> int:
    match = _TIME_RE.match(collapse_whitespace(time_et))
    if match is None:
        return 0
    hour = int(match.group(1)) % 12 + (12 if match.group(3).upper() == "PM" else 0)
    return hour * 60 + int(match.group(2))


def _round_header(soup: BeautifulSoup) -> str | None:
    for font in soup.find_all("font"):
        if font.get("size") == "5" and font.find_parent("b") is not None:
            text = collapse_whitespace(font.get_text())
            if text:
                return text
    return None


def _split_crew(text: str) -> tuple[tuple[str, ...], bool]:
    if "(local simulcast" in text.lower():
        return (), True
    names = tuple(n for n in (collapse_whitespace(p) for p in text.split(",")) if n)
    return names, False


def _cell_text(block: Tag, cell_id: str) -> str:
    cell = block.find("div", id=cell_id)
    return collapse_whitespace(cell.get_text()) if isinstance(cell, Tag) else ""


def _number_doubleheaders(listings: list[MlbListing506]) -> list[MlbListing506]:
    groups: dict[tuple[date | None, str, str], list[int]] = {}
    for idx, item in enumerate(listings):
        if item.game_number == 0 and not item.not_played:
            groups.setdefault((item.game_date, item.away_raw, item.home_raw), []).append(idx)
    result = list(listings)
    for indexes in groups.values():
        if len(indexes) != 2:
            continue
        ordered = sorted(indexes, key=lambda i: _time_minutes(listings[i].time_et))
        for number, idx in enumerate(ordered, start=1):
            result[idx] = replace(listings[idx], game_number=number)
    return result


def _parse_block(
    block: Tag,
    *,
    season: int,
    label: str,
    game_date: date | None,
    header: str | None,
) -> MlbListing506 | MlbNonGameRow:
    text = _cell_text(block, "cmatchup")
    time_et = _cell_text(block, "ctime")
    series_game: int | None = None
    prefix = _SERIES_PREFIX_RE.match(text)
    if prefix is not None:
        series_game = int(prefix.group(1))
        text = text[prefix.end() :]
    game_number = 0
    venue_note: str | None = None
    not_played = False
    while True:
        paren = _TRAILING_PAREN_RE.search(text)
        if paren is None:
            break
        inner = collapse_whitespace(paren.group(1))
        if inner.lower() in _NOT_PLAYED:
            not_played = True
        elif (num := _GAME_NUMBER_RE.match(inner)) is not None:
            game_number = int(num.group(1))
        elif (venue := _IN_RE.match(inner)) is not None:
            venue_note = venue.group(1)
        else:
            break
        text = text[: paren.start()]
    split = split_matchup(text)
    if split is None:
        return MlbNonGameRow(season, label, game_date, _non_game_kind(text))
    away, home, neutral = split
    crew, simulcast = _split_crew(_cell_text(block, "canncrs"))
    return MlbListing506(
        season=season,
        label=label,
        game_date=game_date,
        time_et=time_et,
        away_raw=away,
        home_raw=home,
        neutral=neutral,
        series_game=series_game,
        game_number=game_number,
        venue_note=venue_note,
        outlets=parse_outlet_cell(_cell_text(block, "cntwk")),
        crew_names=crew,
        local_simulcast=simulcast,
        not_played=not_played,
        round_header=header,
    )


def discover_mlb_season_labels(content: bytes) -> tuple[str, ...]:
    """Week and round labels the page's season nav links to, in order."""
    soup = _soup(content)
    weeks: set[int] = set()
    rounds: set[str] = set()
    for link in soup.find_all("a", href=True):
        match = _NAV_RE.search(str(link["href"]))
        if match is None:
            continue
        value = match.group(1).upper()
        if value.isdigit():
            weeks.add(int(value))
        else:
            rounds.add(value)
    return (
        *(str(n) for n in sorted(weeks)),
        *(r for r in MLB_ROUNDS if r in rounds),
    )


def parse_mlb_page(content: bytes, *, season: int, label: str) -> MlbPage:
    """Parse one saved MLB page; raises ParseError on an unrecognized layout."""
    soup = _soup(content)
    layout = _detect(soup)
    labels = discover_mlb_season_labels(content)
    if layout == "map":
        return MlbPage("map", (), (), labels)
    if layout != "cgame":
        raise _error(season, label, "unrecognized layout")
    header = _round_header(soup)
    listings: list[MlbListing506] = []
    non_game: list[MlbNonGameRow] = []
    current: date | None = None
    last_month: int | None = None
    year = season
    for element in soup.find_all(["h3", "div"]):
        if element.name == "h3":
            parsed = _date_header(element.get_text(), year)
            if parsed is None:
                continue
            if last_month is not None and parsed.month < last_month:
                year += 1
                parsed = _date_header(element.get_text(), year)
                if parsed is None:
                    continue
            last_month = parsed.month
            current = parsed
            continue
        if element.get("id") != "cgame":
            continue
        row = _parse_block(element, season=season, label=label, game_date=current, header=header)
        if isinstance(row, MlbListing506):
            listings.append(row)
        else:
            non_game.append(row)
    return MlbPage("cgame", tuple(_number_doubleheaders(listings)), tuple(non_game), labels)


def mlb_smoke_check(content: bytes, *, season: int, label: str) -> str | None:
    """None when the page looks like a valid MLB page, else a count-only reason."""
    try:
        page = parse_mlb_page(content, season=season, label=label)
    except ParseError as exc:
        return str(exc)
    if page.layout == "map":
        return f"season {season} label {label}: map layout is out of scope"
    total = len(page.listings)
    is_round = label in MLB_ROUNDS
    minimum = 1 if is_round else MLB_SMOKE_MIN_LISTINGS
    if total < minimum:
        return f"season {season} label {label}: {total} listings, need {minimum}"
    with_outlet = sum(1 for item in page.listings if item.outlets)
    if with_outlet / total < MLB_SMOKE_MIN_OUTLET_SHARE:
        return f"season {season} label {label}: {with_outlet} of {total} listings have an outlet"
    if is_round:
        with_crew = sum(1 for item in page.listings if item.crew_names)
        if with_crew / total < MLB_SMOKE_MIN_ROUND_CREW_SHARE:
            return f"season {season} label {label}: {with_crew} of {total} listings name a crew"
    return None
