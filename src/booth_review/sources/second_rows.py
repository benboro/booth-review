"""The shared row shape for every second viewership source (04.19 D-09).

SMW, TVRG, Awful Announcing and ESPN Press Room all reduce to
`SecondSourceRow`. This module imports nothing from build/ or resolve/, so
contract/ and build/ can both depend on it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal
from urllib.parse import urlsplit

SecondSource = Literal["smw", "tvrg", "aa", "espnpr"]
RowKind = Literal[
    "figure",
    "no_figure",
    "simulcast",
    "multi_feed",
    "regional",
    "non_nielsen",
    "unknown_suffix",
]
ChartKind = Literal["weekly", "postseason", "season_top", "post"]

SECOND_SOURCE_PUBLISHERS: dict[str, str] = {
    "smw": "Sports Media Watch",
    "tvrg": "The TV Ratings Guide",
    "aa": "Awful Announcing",
    "espnpr": "ESPN Press Room",
}

SECOND_SOURCE_HOSTS: dict[str, str] = {
    "smw": "sportsmediawatch.com",
    "tvrg": "thetvratingsguide.com",
    "aa": "awfulannouncing.com",
    "espnpr": "espnpressroom.com",
}


@dataclass(frozen=True)
class SecondSourceRow:
    """One printed viewership row from a second source."""

    source: SecondSource
    season: int
    pointer: str
    date_et: date | None
    away_raw: str
    home_raw: str
    network_raw: str
    viewers: int | None
    kind: RowKind
    chart_kind: ChartKind
    rank: int
    source_url: str
    superseded: bool


def host_matches(source: SecondSource, url: str) -> bool:
    """True when `url` is https and its host is the source's host or a subdomain."""
    parts = urlsplit(url)
    if parts.scheme != "https":
        return False
    host = (parts.hostname or "").lower()
    base = SECOND_SOURCE_HOSTS[source]
    return host == base or host.endswith("." + base)
