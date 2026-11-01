"""Awful Announcing weekly college football announcing-schedule post parser (Phase 27).

This module parses cached crews posts (D-01). Unlike ``feed.py``, whose response
is never cached, a crews post is cached in the private vault and parsed here.
All page content is private vault data, so every error message is count-only:
no text from the page is echoed.

The post body (``entry-content``) holds ``<h3>`` day headers ("Saturday,
November 7", with or without the comma; a header starts with a weekday, and
January to May dates fall in the next year) and one ``<p>`` per game::

    Away at Home (7:30 p.m., Network): Name (play-by-play), Name (analyst), ...

The whole paragraph text is parsed, never the ``<strong>`` boundaries (the colon
sits inside or outside the tag). Roles come from the post's own tags
(play-by-play -> pbp, analyst -> analyst); reporters are dropped. A TBD crew is
counted, a line that does not fit the shape or carries an unknown role is
counted as unparsed, and a crew with no play-by-play is counted and skipped.
A game line before any recognised day header, or under a weekday heading that
does not parse, is counted as unparsed too, and a
post with no booth at all while it has unparsed game lines, or with no day header,
raises ``AaCrewsParseError``, so header drift is never cached as a good page.

The fetch half (``fetch_week_crews``) is shared by ``booth-review collect aa
--crews`` and the scheduled job. Unlike the feed, a crews response is cached.
The only URLs it ever fetches are the ``weeks`` values the feed watch recorded in
``ledger/aa_feed_watch.json`` (D-01), after the policy gate and the feed URL
whitelist; it takes no URL argument. Only season 2026 is ever fetched (D-03).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal

from booth_review.config import DataPaths
from booth_review.people.roles import Role
from booth_review.sources.aa.feed import _check_url, load_feed_state, week_key
from booth_review.sources.aa.index import on_host
from booth_review.sources.aa.parser import (
    _classes,
    _PostParser,
    _walk,
    post_slug,
    post_url_from_html,
)
from booth_review.sources.espnpr.parser import _AT_RE, _VS_RE, _clean
from booth_review.sources.gapcollect import post_validator
from booth_review.sources.policy import policy_fresh
from booth_review.transport.cache import RawCache
from booth_review.transport.types import FetchRequest

_MONTHS = {
    name: number
    for number, name in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"),
        start=1,
    )
}
_WEEKDAYS = frozenset(
    {
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
        "mon", "tue", "tues", "wed", "thu", "thur", "thurs", "fri", "sat", "sun",
    }
)  # fmt: skip
# "Saturday, November 7", also "Saturday, Nov. 7th:" (Phase 27 review WR-04) and
# "Saturday, November 7, 2026". The first word must be a weekday (full or
# abbreviated), so prose such as "Updated Nov. 5" is never a header (adversarial
# panel F2).
_HEADER_RE = re.compile(
    r"^([A-Za-z]+)\.?,?\s+([A-Za-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?:?$"
)
# A short block led by a weekday that is not a recognised header still ends the
# previous day, so the games under it count as unparsed instead of inheriting the
# date above (adversarial panel F3).
_DAY_LIKE_MAX = 40
_GAME_RE = re.compile(
    r"^(?P<matchup>.+?)\s*\((?P<time>[^,()]+),\s*(?P<net>[^()]+)\)\s*:\s*(?P<crew>.*)$"
)
_PERSON_RE = re.compile(r"\s*(?P<name>[^(),]+?)\s*\((?P<role>[^()]+)\)\s*(?:,\s*|$)")
_CITY_RE = re.compile(r"\s+in\s+.+$")
_ROLES: dict[str, Role | None] = {"play-by-play": "pbp", "analyst": "analyst", "reporter": None}
# Placeholders AA writes where a name is not known yet; never a person (adversarial
# panel N1). Compared case-insensitively with punctuation removed ("T.B.D.", "TBA:").
_PLACEHOLDERS = frozenset({"tbd", "tba"})


def _is_placeholder(text: str) -> bool:
    return re.sub(r"[^a-z]", "", text.lower()) in _PLACEHOLDERS


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
    """The date of a day header, or None when ``text`` is not one.

    January to May belong to the season's bowls and playoff, so they take the next
    calendar year; a header that states its year keeps that year.
    """
    match = _HEADER_RE.match(text)
    if match is None or match.group(1).lower() not in _WEEKDAYS:
        return None
    month = _MONTHS.get(match.group(2)[:3].lower())
    if month is None:
        return None
    year = int(match.group(4)) if match.group(4) else season + (1 if month <= 5 else 0)
    try:
        return date(year, month, int(match.group(3)))
    except ValueError:
        return None


def _is_day_like(text: str) -> bool:
    """A short weekday-led block with no game shape (an unrecognised day header)."""
    first = text.split(maxsplit=1)[0].rstrip(",.:").lower() if text else ""
    return (
        first in _WEEKDAYS
        and len(text) <= _DAY_LIKE_MAX
        and "(" not in text
        and not (_AT_RE.search(text) or _VS_RE.search(text))
    )


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


def _crew(text: str) -> tuple[tuple[tuple[str, Role], ...], frozenset[Role]] | None:
    """The role-tagged people of a crew string and the roles held only by a
    placeholder, or None when it doesn't fit.

    A placeholder name (TBD, TBA) is dropped, so it never reaches a booth."""
    people: list[tuple[str, Role]] = []
    placeholders: set[Role] = set()
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
        if role is None:
            continue
        if _is_placeholder(name):
            placeholders.add(role)
        else:
            people.append((name, role))
    return tuple(people), frozenset(placeholders)


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
        header_day = _header_date(text, season)
        if header_day is not None:
            seen_header = True
            day = header_day
            continue
        if _is_day_like(text):
            day = None
            continue
        game = _GAME_RE.match(text)
        if not seen_header:
            # A game line with no day above it (an unrecognised header style).
            if game is not None and _split_matchup(game.group("matchup")) is not None:
                line += 1
                unparsed += 1
            continue
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
        if _is_placeholder(crew_text):
            tbd += 1
            continue
        crew = _crew(crew_text)
        if crew is None:
            unparsed += 1
            continue
        people, placeholders = crew
        if not any(role == "pbp" for _, role in people):
            # A booth whose play-by-play is only a placeholder is still TBD.
            if "pbp" in placeholders:
                tbd += 1
            else:
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
    if not booths and (unparsed or not seen_header):
        raise AaCrewsParseError(
            f"aa crews post has no booth: {unparsed} unparsed game lines, "
            f"day header {'found' if seen_header else 'missing'}"
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


CREWS_SEASON = 2026
_ROBOTS_CACHE = "raw/_robots/awfulannouncing.com"
_REQUESTS_LEDGER = "ledger/requests.jsonl"

# if_missing: fetch only when not cached (the Tuesday run). conditional: fetch, or
# re-check a cached post with its validators (the CLI). recheck: re-check a cached
# post only; never a first fetch (the Friday/Saturday runs, Phase 27 review WR-02).
CrewsMode = Literal["if_missing", "conditional", "recheck"]
CrewsOutcome = Literal[
    "fetched",
    "not_modified",
    "cached",
    "not_cached",
    "no_link",
    "stale_policy",
    "not_season",
    "no_budget",
    "dry_run",
]


def crews_request(season: int, label: str, url: str) -> FetchRequest:
    return FetchRequest(
        source="aa", season=season, url=url, cache_path=crews_cache_path(season, label)
    )


@dataclass(frozen=True)
class CrewsFetchResult:
    outcome: CrewsOutcome
    requests: int
    url: str | None
    cache_path: str | None
    touched: tuple[str, ...]


def _result(outcome: CrewsOutcome, url: str | None = None) -> CrewsFetchResult:
    return CrewsFetchResult(outcome, 0, url, None, ())


def _parse_adapter(html: str, *, url: str, season: int) -> ParsedCrews:
    return parse_crews(html, season=season)


def fetch_week_crews(
    cache: RawCache,
    paths: DataPaths,
    *,
    season: int,
    label: str,
    now: datetime,
    mode: CrewsMode,
    budget: int,
    dry_run: bool = False,
    on_request: Callable[[], None] | None = None,
) -> CrewsFetchResult:
    """Fetch one week's recorded crews post through the cache (D-01, D-03).

    ``on_request`` runs just before the one request is sent (the job records its
    re-check slot there). Robots and host errors propagate; the caller installed
    ``robots_guard``.
    """
    if season != CREWS_SEASON:
        return _result("not_season")
    if not policy_fresh(paths, "aa", now):
        return _result("stale_policy")
    url = load_feed_state(paths).weeks.get(week_key(season, label))
    if url is None:
        return _result("no_link")
    _check_url(url)
    req = crews_request(season, label, url)
    cached = cache.status(req) == "cached"
    if mode == "if_missing" and cached:
        return CrewsFetchResult("cached", 0, url, req.cache_path, ())
    if mode == "recheck" and not cached:
        return CrewsFetchResult("not_cached", 0, url, None, ())
    if budget < 1:
        return _result("no_budget", url)
    if dry_run:
        return _result("dry_run", url)
    validate = post_validator(
        "aa",
        season,
        url_from_html=post_url_from_html,
        parse=_parse_adapter,
        error=AaCrewsParseError,
    )
    if on_request is not None:
        on_request()
    result = cache.get_or_fetch(req, refresh=cached, validate=validate)
    outcome: CrewsOutcome = "not_modified" if result.outcome == "not_modified" else "fetched"
    vault_path = f"raw/{req.cache_path}"
    return CrewsFetchResult(
        outcome, 1, url, req.cache_path, (vault_path, _REQUESTS_LEDGER, _ROBOTS_CACHE)
    )
