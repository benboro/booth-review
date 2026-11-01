"""Awful Announcing weekly college football announcing-schedule post parser (Phase 27).

This module parses cached crews posts (D-01). Unlike ``feed.py``, whose response
is never cached, a crews post is cached in the private vault and parsed here.
All page content is private vault data, so every error message is count-only:
no text from the page is echoed.

The post body (``entry-content``) holds ``<h3>`` day headers ("Saturday,
November 7", with or without the comma) and one ``<p>`` per game::

    Away at Home (7:30 p.m., Network): Name (play-by-play), Name (analyst), ...

The whole paragraph text is parsed, never the ``<strong>`` boundaries (the colon
sits inside or outside the tag). Roles come from the post's own tags
(play-by-play -> pbp, analyst -> analyst); reporters are dropped. A TBD crew is
counted, a line that does not fit the shape or carries an unknown role is
counted as unparsed, and a crew with no play-by-play is counted and skipped.
Nothing here fetches or executes anything.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from booth_review.people.roles import Role
from booth_review.sources.aa.index import on_host
from booth_review.sources.aa.parser import (
    _classes,
    _PostParser,
    _walk,
    post_slug,
    post_url_from_html,
)
from booth_review.sources.espnpr.parser import _AT_RE, _VS_RE, _clean

_MONTHS = {
    name: number
    for number, name in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"),
        start=1,
    )
}
_HEADER_RE = re.compile(r"^[A-Za-z]+,?\s+([A-Za-z]+)\.?\s+(\d{1,2})$")
_GAME_RE = re.compile(
    r"^(?P<matchup>.+?)\s*\((?P<time>[^,()]+),\s*(?P<net>[^()]+)\)\s*:\s*(?P<crew>.*)$"
)
_PERSON_RE = re.compile(r"\s*(?P<name>[^(),]+?)\s*\((?P<role>[^()]+)\)\s*(?:,\s*|$)")
_CITY_RE = re.compile(r"\s+in\s+.+$")
_ROLES: dict[str, Role | None] = {"play-by-play": "pbp", "analyst": "analyst", "reporter": None}


class AaCrewsParseError(ValueError):
    """A crews post that can't be parsed safely; the message is count-only."""


@dataclass(frozen=True)
class AaBooth:
    season: int
    date_et: date
    kickoff: str | None
    away_raw: str
    home_raw: str
    network_raw: str
    people: tuple[tuple[str, Role], ...]
    source_url: str
    pointer: str


@dataclass(frozen=True)
class ParsedCrews:
    url: str
    modified: datetime | None
    published: datetime | None
    booths: list[AaBooth]
    unparsed: int
    tbd: int
    no_pbp: int


class _CrewsParser(_PostParser):
    """The post-body walk plus the article time meta tags."""

    def __init__(self) -> None:
        super().__init__()
        self.modified_meta: str | None = None
        self.published_meta: str | None = None
        self.saw_body = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        if tag == "meta":
            prop = attr.get("property")
            if prop == "article:modified_time":
                self.modified_meta = self.modified_meta or attr.get("content")
            elif prop == "article:published_time":
                self.published_meta = self.published_meta or attr.get("content")
        if tag == "div" and not self._body_depth and "entry-content" in _classes(attr):
            self.saw_body = True
        super().handle_starttag(tag, attrs)


def _aware(stamp: object) -> datetime | None:
    if not isinstance(stamp, str):
        return None
    try:
        moment = datetime.fromisoformat(stamp.strip())
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


def _ld_time(blobs: list[str], key: str) -> datetime | None:
    for blob in blobs:
        try:
            objects: list[dict[str, Any]] = _walk(json.loads(blob))
        except ValueError:
            continue
        for obj in objects:
            moment = _aware(obj.get(key))
            if moment is not None:
                return moment
    return None


def crews_cache_path(season: int, label: str) -> str:
    """Vault-relative cache path of a week's crews post (week zero-padded)."""
    if not label.isdigit():
        raise ValueError("crews week label must be numeric")
    return f"aa/crews/{season}/wk-{int(label):02d}.html"


def _header_date(text: str, season: int) -> date | None:
    match = _HEADER_RE.match(text)
    if match is None:
        return None
    month = _MONTHS.get(match.group(1)[:3].lower())
    if month is None:
        return None
    try:
        return date(season, month, int(match.group(2)))
    except ValueError:
        return None


def _is_header(text: str) -> bool:
    match = _HEADER_RE.match(text)
    return match is not None and match.group(1)[:3].lower() in _MONTHS


def _split_matchup(matchup: str) -> tuple[str, str] | None:
    away_home = _AT_RE.split(matchup, maxsplit=1)
    if len(away_home) == 2:
        away, home = away_home
    else:
        parts = _VS_RE.split(matchup, maxsplit=1)
        if len(parts) != 2:
            return None
        away, home = parts[0], _CITY_RE.sub("", parts[1])
    away, home = away.strip(), home.strip()
    return (away, home) if away and home else None


def _crew(text: str) -> tuple[tuple[str, Role], ...] | None:
    """The role-tagged people of a crew string, or None when it doesn't fit."""
    people: list[tuple[str, Role]] = []
    pos = 0
    text = text.strip()
    if not text:
        return None
    while pos < len(text):
        match = _PERSON_RE.match(text, pos)
        if match is None:
            return None
        pos = match.end()
        role_key = match.group("role").strip().lower()
        if role_key not in _ROLES:
            return None
        role = _ROLES[role_key]
        name = match.group("name").strip()
        if not name:
            return None
        if role is not None:
            people.append((name, role))
    return tuple(people)


def parse_crews(html: str, *, season: int) -> ParsedCrews:
    """Every crewed game line of one cached AA schedule post (see module docstring)."""
    parser = _CrewsParser()
    parser.feed(html)
    parser.close()
    canonical = post_url_from_html(html)
    url = on_host(canonical) if canonical else None
    if url is None:
        raise AaCrewsParseError("aa crews post has no on-host canonical url")
    if not parser.saw_body:
        raise AaCrewsParseError("aa crews post has no entry-content body")
    slug = post_slug(url)
    modified = _aware(parser.modified_meta) or _ld_time(parser.ld_blobs, "dateModified")
    published = _aware(parser.published_meta) or _ld_time(parser.ld_blobs, "datePublished")

    booths: list[AaBooth] = []
    unparsed = tbd = no_pbp = 0
    day: date | None = None
    seen_header = False
    line = 0
    for block in parser.blocks:
        text = _clean(block.text)
        if _is_header(text):
            seen_header = True
            day = _header_date(text, season)
            continue
        if not seen_header:
            continue
        game = _GAME_RE.match(text)
        if game is None:
            if _AT_RE.search(text) or _VS_RE.search(text):
                line += 1
                unparsed += 1
            continue
        line += 1
        teams = _split_matchup(game.group("matchup"))
        if teams is None or day is None:
            unparsed += 1
            continue
        crew_text = game.group("crew").strip()
        if crew_text.lower() == "tbd":
            tbd += 1
            continue
        people = _crew(crew_text)
        if people is None:
            unparsed += 1
            continue
        if not any(role == "pbp" for _, role in people):
            no_pbp += 1
            continue
        booths.append(
            AaBooth(
                season=season,
                date_et=day,
                kickoff=game.group("time").strip() or None,
                away_raw=teams[0],
                home_raw=teams[1],
                network_raw=game.group("net").strip(),
                people=people,
                source_url=url,
                pointer=f"{slug}:{line}",
            )
        )
    return ParsedCrews(
        url=url,
        modified=modified,
        published=published,
        booths=booths,
        unparsed=unparsed,
        tbd=tbd,
        no_pbp=no_pbp,
    )
