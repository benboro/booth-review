"""Sports506 week-page parser: cached HTML bytes into typed Listing506 rows.

A 506 week page (docs/PLAN.md section 4.1) lays out one <h3> date header per
game day and one <div id="cgame"> per telecast underneath it, each holding a
matchup sub-div, a kickoff-time sub-div, a network sub-div, and a crew
sub-div. This module turns that markup into ordered Listing506 rows.

The only cleanup applied to any name is structural: whitespace collapse,
splitting a leading AP-rank integer off a team name, and splitting a crew
string on its ", " delimiter. No team, network, or announcer name is
otherwise altered (AGENTS.md's crosswalk-only rule; team/announcer
resolution happens later, in Phase 3, through crosswalk tables).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag

from booth_review.errors import ParseError

_EASTERN = ZoneInfo("America/New_York")

_CHARSET_RE = re.compile(rb'charset=["\']?([\w-]+)', re.IGNORECASE)
# A leading AP rank, optionally followed by a parenthesized CFP seed (e.g.
# "20 (11) Tulane"); only the AP rank is kept as the structured integer.
_RANK_RE = re.compile(r"^(\d+)(?:\s*\(\d+\))?\s+(.+)$")

_ALT_CAST_MARKER = "alt-cast"
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
    if _ALT_CAST_MARKER in lowered:
        return "alt"
    if _SPANISH_MARKER in lowered:
        return "spanish"
    return "main"


def _extract_matchup(matchup_div: Tag) -> tuple[str | None, str]:
    """Return (game_label, matchup_text) from a <div id="cmatchup"> element.

    Bowl/CFP pages prefix the matchup with a `<b>label</b><br>` pair; week
    pages have no such prefix. <br> is turned into a separator first so the
    label and the matchup text never run together.
    """
    for br in matchup_div.find_all("br"):
        br.replace_with("\n")
    label_tag = matchup_div.find("b")
    game_label = None
    if label_tag is not None:
        stripped = _collapse_whitespace(label_tag.get_text())
        game_label = stripped or None
    full_text = matchup_div.get_text()
    if label_tag is not None:
        _, _, remainder = full_text.partition("\n")
    else:
        remainder = full_text
    return game_label, _collapse_whitespace(remainder)


def _split_matchup(text: str) -> tuple[str, str, bool] | None:
    if " @ " in text:
        away, _, home = text.partition(" @ ")
        return away.strip(), home.strip(), False
    if " vs " in text:
        away, _, home = text.partition(" vs ")
        return away.strip(), home.strip(), True
    return None


def _parse_row(
    row: Tag, *, season: int, week_label: str, date_et: date, index: int
) -> Listing506 | None:
    matchup_div = row.find("div", id="cmatchup")
    if matchup_div is None:
        return None

    game_label, matchup_text = _extract_matchup(matchup_div)
    split = _split_matchup(matchup_text)
    if split is None:
        return None
    away_part, home_part, neutral = split
    away_rank, away_raw = _split_rank(away_part)
    home_rank, home_raw = _split_rank(home_part)
    if not away_raw or not home_raw:
        return None

    time_div = row.find("div", id="ctime")
    kickoff_et = _parse_kickoff(date_et, time_div.get_text() if time_div else "")

    network_div = row.find("div", id="cntwk")
    network_text = _collapse_whitespace(network_div.get_text()) if network_div else ""
    network_raw = network_text or None

    crew_div = row.find("div", id="canncrs")
    crew_text = _collapse_whitespace(crew_div.get_text()) if crew_div else ""
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


def parse_week_page(html: bytes, *, season: int, week_label: str) -> list[Listing506]:
    """Parse one cached 506 week page into ordered Listing506 rows.

    Raises ParseError on an empty response body or a page with no schedule
    rows at all (a blocked/challenge page, or an unrelated HTML document).
    A row whose matchup carries no team names yet (a not-yet-set CFP final)
    is silently dropped rather than returned with empty teams.
    """
    if not html:
        raise ParseError(f"sports506 {season} wk{week_label}: empty response body")

    soup = BeautifulSoup(_decode(html), features="lxml")
    game_rows = soup.find_all("div", id="cgame")
    if not game_rows:
        raise ParseError(f"sports506 {season} wk{week_label}: no schedule rows found")

    listings: list[Listing506] = []
    current_date: date | None = None
    last_month: int | None = None
    year = season
    index = 0

    for element in soup.find_all(["h3", "div"]):
        if element.name == "h3":
            header_date = _parse_date_header(element.get_text(), year)
            if last_month is not None and header_date.month < last_month:
                year += 1
                header_date = _parse_date_header(element.get_text(), year)
            last_month = header_date.month
            current_date = header_date
            continue

        if element.get("id") != "cgame":
            continue
        if current_date is None:
            # No real 506 page has a game row before its first date header;
            # skip defensively rather than guess at a date.
            continue

        listing = _parse_row(
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
