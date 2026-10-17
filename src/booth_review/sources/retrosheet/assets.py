"""Discover Retrosheet download assets from the cached downloads index.

The real index (plan 09-16 recon) links one per-season bundle,
/downloads/<year>/<year>csvs.zip, each holding allplayers, gameinfo, teamstats,
batting, pitching, fielding and plays CSVs. That is the only asset kind.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

RETROSHEET_HOST = "www.retrosheet.org"
RETROSHEET_DOWNLOADS_BASE = f"https://{RETROSHEET_HOST}/downloads/"

# Matched against the last path segment of each link on the index page.
RETROSHEET_ASSET_PATTERNS: dict[str, re.Pattern[str]] = {
    "season_bundle": re.compile(r"^(?P<season>\d{4})csvs\.zip$", re.IGNORECASE),
}


@dataclass(frozen=True)
class RetrosheetAsset:
    name: str
    url: str
    kind: str
    season: int | None


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        for key, value in attrs:
            if key == "href" and value:
                self.hrefs.append(value.strip())


def discover_assets(
    index_html: str | bytes, base_url: str = RETROSHEET_DOWNLOADS_BASE
) -> list[RetrosheetAsset]:
    """Allow-listed assets linked from the index, same host only, deduplicated."""
    text = (
        index_html.decode("utf-8", errors="replace")
        if isinstance(index_html, bytes)
        else index_html
    )
    parser = _LinkParser()
    parser.feed(text)
    found: dict[str, RetrosheetAsset] = {}
    for href in parser.hrefs:
        url = urljoin(base_url, href)
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.netloc != RETROSHEET_HOST:
            continue
        if "%" in parts.path or any(seg in (".", "..") for seg in parts.path.split("/")):
            continue
        name = parts.path.rsplit("/", 1)[-1]
        if not name or "/" in name or ".." in name:
            continue
        for kind, pattern in RETROSHEET_ASSET_PATTERNS.items():
            match = pattern.match(name)
            if match is None:
                continue
            season = int(match.group("season")) if "season" in pattern.groupindex else None
            if season is not None and parts.path.rsplit("/", 2)[-2] != str(season):
                break
            found.setdefault(url, RetrosheetAsset(name=name, url=url, kind=kind, season=season))
            break
    return sorted(found.values(), key=lambda a: (a.kind, a.season or 0, a.name))
