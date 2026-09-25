"""Sports506 week-page parser: cached HTML bytes into typed Listing506 rows.

A 506 week page (docs/PLAN.md section 4.1) lays out one <h3> date header per
game day, with one telecast row underneath it in one of two layouts:

- 2022 onward: one <div id="cgame"> per telecast, holding a matchup
  sub-div, a kickoff-time sub-div, a network sub-div, and a crew sub-div.
- 2013-2021 (verified against 2014-2021; 2013 is out of this project's
  scope): one <table class="listingtable"> per date, holding one <tr> per
  telecast with four plain <td> cells in the same order (time, matchup,
  network, crew), no id attributes.

Both layouts carry the same four fields in the same order, so this module
locates each row's four cells generically per layout and then shares one
field-extraction path (`_build_listing`) for both. A bowl/CFP listing's
matchup cell prefixes the matchup with a game-label line (bold in some
pages, plain text in others) and may append a trailing location-note line;
the label/matchup/location lines are told apart by which line contains a
matchup separator (" @ " or " vs[.] "), not by whether the label happens to
be bold, so the same logic reads both conventions without a per-layout
special case.

The only cleanup applied to any name is structural: whitespace collapse,
splitting a leading AP-rank integer off a team name, and splitting a crew
string on its ", " delimiter. No team, network, or announcer name is
otherwise altered (AGENTS.md's crosswalk-only rule; team/announcer
resolution happens later, in Phase 3, through crosswalk tables).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag

from booth_review.errors import ParseError

_EASTERN = ZoneInfo("America/New_York")

_CHARSET_RE = re.compile(rb'charset=["\']?([\w-]+)', re.IGNORECASE)
# A leading AP rank, optionally prefixed with "#" (2014's plain-text rank
# convention; other years wrap the same bare digits in <font>/<small>, which
# get_text() already strips before this regex ever sees them) and optionally
# followed by a parenthesized CFP seed (e.g. "20 (11) Tulane"); only the AP
# rank is kept as the structured integer.
_RANK_RE = re.compile(r"^#?(\d+)(?:\s*\(\d+\))?\s+(.+)$")

# "alt-cast" is the 2022+ wording; 2014-2021 pages mark the same simulcast
# concept as "(alt)" instead. Both are checked so feed_kind classifies
# either convention the same way.
_ALT_CAST_MARKERS = ("alt-cast", "(alt)")
_SPANISH_MARKER = "spanish"

FeedKind = Literal["main", "alt", "spanish", "unknown"]


@dataclass(frozen=True)
class Listing506:
    """One telecast row from a 506 week page, in page order."""

    season: int
    week_label: str
    source_row_index: int
    date_et: date
    kickoff_et: datetime | None
    away_raw: str
    away_rank: int | None
    home_raw: str
    home_rank: int | None
    neutral: bool
    network_raw: str | None
    crew_raw: str | None
    crew_names: tuple[str, ...]
    feed_kind: FeedKind
    game_label: str | None


def _decode(html: bytes) -> str:
    """Decode `html` with the charset it declares, else fall back to utf-8."""
    match = _CHARSET_RE.search(html[:2048])
    encoding = match.group(1).decode("ascii") if match else "utf-8"
    try:
        return html.decode(encoding)
    except (LookupError, UnicodeDecodeError):
        return html.decode("utf-8", errors="replace")


def _collapse_whitespace(text: str) -> str:
    return " ".join(text.split())


def _split_rank(part: str) -> tuple[int | None, str]:
    part = _collapse_whitespace(part)
    match = _RANK_RE.match(part)
    if match is None:
        return None, part
    return int(match.group(1)), match.group(2)


def _parse_date_header(text: str, year: int) -> date:
    _, _, month_day = text.partition(",")
    month_day = _collapse_whitespace(month_day)
    return datetime.strptime(f"{month_day} {year}", "%B %d %Y").date()  # noqa: DTZ007


def _parse_kickoff(date_et: date, time_text: str) -> datetime | None:
    time_text = _collapse_whitespace(time_text)
    if not time_text or time_text.upper() in {"TBA", "TBD"}:
        return None
    try:
        parsed = datetime.strptime(time_text, "%I:%M %p")  # noqa: DTZ007
    except ValueError:
        return None
    return datetime.combine(date_et, parsed.time(), tzinfo=_EASTERN)


def _classify_feed(network_raw: str | None) -> FeedKind:
    if network_raw is None:
        return "unknown"
    lowered = network_raw.lower()
    if any(marker in lowered for marker in _ALT_CAST_MARKERS):
        return "alt"
    if _SPANISH_MARKER in lowered:
        return "spanish"
    return "main"


def _extract_cell_text(tag: Tag | None) -> str:
    """Collapsed text of a network/crew/time cell.

    <br> is turned into a space first, so a line-wrapped multi-network cell
    ("Network A,<br>Network B", seen in 2014-2021 pages) reads as one
    comma-separated string, the same shape the newer layout's single-line
    network cell already produces.
    """
    if tag is None:
        return ""
    for br in tag.find_all("br"):
        br.replace_with(" ")
    return _collapse_whitespace(tag.get_text())


def _extract_matchup(matchup_tag: Tag) -> tuple[str | None, str]:
    """Return (game_label, matchup_text) from a matchup cell/div.

    A matchup cell normally holds one line ("Away @ Home" or "Away vs
    Home"). A bowl/CFP listing prefixes it with a game-label line -- bold
    (`<b>label</b><br>`) in most pages, plain text followed directly by
    `<br>` in some 2014-2021 pages -- and may append a trailing
    `<br>(in <city>)` location note, itself sometimes present on an
    ordinary (non-bowl) neutral-site game with no label at all. `<br>` is
    turned into a line break first; the *first* line that itself parses as
    a matchup (`_split_matchup` succeeds) is the matchup line, any line(s)
    before it are the label, and any line(s) after it are appended back
    onto the matchup text with a space. This tells a label line from a
    location-note line by content (only a matchup line contains a
    separator), so it reads the bold and plain-text label conventions, and
    the labelless neutral-site case, without a per-layout special case.
    """
    for br in matchup_tag.find_all("br"):
        br.replace_with("\n")
    full_text = matchup_tag.get_text()
    lines = [_collapse_whitespace(line) for line in full_text.split("\n")]
    lines = [line for line in lines if line]
    if not lines:
        return None, ""

    matchup_index = next(
        (i for i, line in enumerate(lines) if _split_matchup(line) is not None), None
    )
    if matchup_index is None:
        return None, _collapse_whitespace(full_text)

    game_label = lines[0] if matchup_index > 0 else None
    return game_label, " ".join(lines[matchup_index:])


# " @ " for a home game; " vs " or " vs. " (2014 pages use the period) for a
# neutral-site game. Matched against already-whitespace-collapsed text, so a
# non-breaking space around either separator (also seen in 2014-2021 pages)
# is already a plain space by the time this runs.
_HOME_AWAY_RE = re.compile(r"^(.+?)\s@\s(.+)$")
_NEUTRAL_RE = re.compile(r"^(.+?)\svs\.?\s(.+)$")


def _split_matchup(text: str) -> tuple[str, str, bool] | None:
    text = _collapse_whitespace(text)
    match = _HOME_AWAY_RE.match(text)
    if match:
        return match.group(1).strip(), match.group(2).strip(), False
    match = _NEUTRAL_RE.match(text)
    if match:
        return match.group(1).strip(), match.group(2).strip(), True
    return None


def _build_listing(
    *,
    season: int,
    week_label: str,
    date_et: date,
    index: int,
    matchup_tag: Tag,
    time_text: str,
    network_tag: Tag | None,
    crew_tag: Tag | None,
) -> Listing506 | None:
    """Shared field extraction for one row, whichever layout it came from."""
    game_label, matchup_text = _extract_matchup(matchup_tag)
    split = _split_matchup(matchup_text)
    if split is None:
        return None
    away_part, home_part, neutral = split
    away_rank, away_raw = _split_rank(away_part)
    home_rank, home_raw = _split_rank(home_part)
    if not away_raw or not home_raw:
        return None

    kickoff_et = _parse_kickoff(date_et, time_text)

    network_text = _extract_cell_text(network_tag)
    network_raw = network_text or None

    crew_text = _extract_cell_text(crew_tag)
    crew_raw = crew_text or None
    crew_names = tuple(name.strip() for name in crew_text.split(",") if name.strip())

    return Listing506(
        season=season,
        week_label=week_label,
        source_row_index=index,
        date_et=date_et,
        kickoff_et=kickoff_et,
        away_raw=away_raw,
        away_rank=away_rank,
        home_raw=home_raw,
        home_rank=home_rank,
        neutral=neutral,
        network_raw=network_raw,
        crew_raw=crew_raw,
        crew_names=crew_names,
        feed_kind=_classify_feed(network_raw),
        game_label=game_label,
    )


def _parse_row(
    row: Tag, *, season: int, week_label: str, date_et: date, index: int
) -> Listing506 | None:
    """A 2022+ row: `<div id="cgame">` holding four id'd sub-divs."""
    matchup_div = row.find("div", id="cmatchup")
    if matchup_div is None:
        return None
    time_div = row.find("div", id="ctime")
    return _build_listing(
        season=season,
        week_label=week_label,
        date_et=date_et,
        index=index,
        matchup_tag=matchup_div,
        time_text=time_div.get_text() if time_div else "",
        network_tag=row.find("div", id="cntwk"),
        crew_tag=row.find("div", id="canncrs"),
    )


def _parse_table_row(
    row: Tag, *, season: int, week_label: str, date_et: date, index: int
) -> Listing506 | None:
    """A 2014-2021 row: `<tr>` holding four plain `<td>` cells, in the same
    time/matchup/network/crew order the 2022+ id'd divs carry, but with no
    id attributes of their own."""
    cells = row.find_all("td")
    if len(cells) < 4:
        return None
    time_cell, matchup_cell, network_cell, crew_cell = cells[:4]
    return _build_listing(
        season=season,
        week_label=week_label,
        date_et=date_et,
        index=index,
        matchup_tag=matchup_cell,
        time_text=time_cell.get_text(),
        network_tag=network_cell,
        crew_tag=crew_cell,
    )


def _walk_page(
    soup: BeautifulSoup,
    *,
    season: int,
    week_label: str,
    row_tag: str,
    is_row: Callable[[Tag], bool],
    parse_row: Callable[..., Listing506 | None],
) -> list[Listing506]:
    """Walk `<h3>` date headers and `row_tag` rows in document order.

    Both 506 layouts share this date-header and row-ordering logic; only
    how a single row's four fields are located differs (`_parse_row` for
    `<div id="cgame">`, `_parse_table_row` for `<table class="listingtable">`
    `<tr>`s), passed in by the caller.
    """
    listings: list[Listing506] = []
    current_date: date | None = None
    last_month: int | None = None
    year = season
    index = 0

    for element in soup.find_all(["h3", row_tag]):
        if element.name == "h3":
            header_date = _parse_date_header(element.get_text(), year)
            if last_month is not None and header_date.month < last_month:
                year += 1
                header_date = _parse_date_header(element.get_text(), year)
            last_month = header_date.month
            current_date = header_date
            continue

        if not is_row(element):
            continue
        if current_date is None:
            # No real 506 page has a game row before its first date header;
            # skip defensively rather than guess at a date.
            continue

        listing = parse_row(
            element,
            season=season,
            week_label=week_label,
            date_et=current_date,
            index=index,
        )
        if listing is not None:
            listings.append(listing)
        index += 1

    return listings


def parse_week_page(html: bytes, *, season: int, week_label: str) -> list[Listing506]:
    """Parse one cached 506 week page into ordered Listing506 rows.

    Detects which of the two 506 layouts (2022+ `<div id="cgame">` rows, or
    2014-2021 `<table class="listingtable">` rows) the page uses, and reads
    it with the matching row source; both produce identical Listing506
    output via `_build_listing`. Raises ParseError on an empty response
    body or a page with no schedule rows in either layout (a blocked/
    challenge page, an unrelated HTML document, or a week 506 itself lists
    no games for). A row whose matchup carries no team names yet (a
    not-yet-set CFP final) is silently dropped rather than returned with
    empty teams.
    """
    if not html:
        raise ParseError(f"sports506 {season} wk{week_label}: empty response body")

    soup = BeautifulSoup(_decode(html), features="lxml")

    if soup.find_all("div", id="cgame"):
        return _walk_page(
            soup,
            season=season,
            week_label=week_label,
            row_tag="div",
            is_row=lambda el: el.get("id") == "cgame",
            parse_row=_parse_row,
        )

    if soup.select("table.listingtable tr"):
        return _walk_page(
            soup,
            season=season,
            week_label=week_label,
            row_tag="tr",
            is_row=lambda el: el.find_parent("table", class_="listingtable") is not None,
            parse_row=_parse_table_row,
        )

    raise ParseError(f"sports506 {season} wk{week_label}: no schedule rows found")
