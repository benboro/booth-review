"""Ratings Reference sitemap-telecasts.xml parsing.

Filters to telecast pages for one league (default CFB, path starting /telecast/cfb-) whose slug ends
in a trailing -YYYY-MM-DD date, and builds the derived per-telecast JSON API
URL. Disables entity resolution and network access on the XML parser (T-01-25).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from urllib.parse import urlparse

from lxml import etree

from booth_review.errors import ParseError
from booth_review.seasons import season_of

# 999.7 adds "mlb": "/telecast/mlb-" here.
LEAGUE_PATH_PREFIXES: dict[str, str] = {
    "cfb": "/telecast/cfb-",
    "nfl": "/telecast/nfl-",
}
_TRAILING_DATE_RE = re.compile(r"-(\d{4})-(\d{2})-(\d{2})$")


def _local_name(tag: str) -> str:
    """Strip a `{namespace}` prefix from an lxml element tag, if present."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


@dataclass(frozen=True)
class SitemapEntry:
    telecast_id: str
    record_url: str
    json_url: str
    event_date: date
    season: int
    lastmod: str
    league: str = "cfb"


def parse_sitemap(xml: bytes, league: str = "cfb") -> tuple[list[SitemapEntry], int]:
    """Parse sitemap XML bytes into (telecast entries for `league`, skipped count).

    Entries whose loc path isn't a telecast page for `league`, or whose slug has no
    trailing -YYYY-MM-DD date, are skipped and counted rather than raising.
    """
    prefix = LEAGUE_PATH_PREFIXES.get(league)
    if prefix is None:
        raise ValueError(f"unknown ratingsref league: {league!r}")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    try:
        root = etree.fromstring(xml, parser=parser)
    except etree.XMLSyntaxError as exc:
        raise ParseError(f"ratingsref sitemap: invalid XML: {exc}") from exc

    entries: list[SitemapEntry] = []
    skipped = 0

    for url_elem in root.iter():
        # resolve_entities=False leaves an unresolved entity reference (or a
        # comment/PI) as a node whose .tag is a callable, not a string
        # (T-01-25's proof the entity was never expanded); skip non-elements.
        if not isinstance(url_elem.tag, str) or _local_name(url_elem.tag) != "url":
            continue

        loc_text: str | None = None
        lastmod_text: str | None = None
        for child in url_elem:
            if not isinstance(child.tag, str):
                continue
            name = _local_name(child.tag)
            if name == "loc":
                loc_text = (child.text or "").strip()
            elif name == "lastmod":
                lastmod_text = (child.text or "").strip()

        if not loc_text:
            continue

        path = urlparse(loc_text).path
        if not path.startswith(prefix):
            skipped += 1
            continue

        slug = path.rsplit("/", 1)[-1]
        match = _TRAILING_DATE_RE.search(slug)
        if match is None:
            skipped += 1
            continue

        year_s, month_s, day_s = match.groups()
        try:
            event_date = date(int(year_s), int(month_s), int(day_s))
        except ValueError:
            skipped += 1
            continue

        entries.append(
            SitemapEntry(
                telecast_id=slug,
                record_url=loc_text,
                json_url=f"https://ratingsreference.com/api/telecast/{slug}.json",
                event_date=event_date,
                season=season_of(event_date),
                lastmod=lastmod_text or "",
                league=league,
            )
        )

    return entries, skipped


def select_entries(entries: list[SitemapEntry], start: date, end: date) -> list[SitemapEntry]:
    """Keep entries whose event_date falls within [start, end], inclusive."""
    return [e for e in entries if start <= e.event_date <= end]
