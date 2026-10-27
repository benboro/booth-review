"""Stadium coordinates from a cached Wikipedia stadium article.

Reads the page's coordinates microformat (``span.geo`` as "lat; lon", else
``span.geo-dec`` as "40.81°N 74.07°W"). Returns None on any doubt: never a
city-centre fallback and never a guess.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

_GEO_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*[;,]\s*(-?\d+(?:\.\d+)?)\s*$")
_DEC_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*°?\s*([NS])[\s,;]+(\d+(?:\.\d+)?)\s*°?\s*([EW])\s*$")


def _in_range(lat: float, lon: float) -> tuple[float, float] | None:
    if -90 <= lat <= 90 and -180 <= lon <= 180:
        return (lat, lon)
    return None


def _first(scope: Tag | BeautifulSoup, css: str) -> str | None:
    node = scope.select_one(css)
    return node.get_text(strip=True) if node is not None else None


def parse_stadium_coordinates(html: bytes) -> tuple[float, float] | None:
    soup = BeautifulSoup(html, "html.parser")
    scope = soup.find(id="coordinates") or soup.select_one("table.infobox")
    scopes: list[Tag | BeautifulSoup] = [scope] if isinstance(scope, Tag) else []
    scopes.append(soup)
    for part in scopes:
        geo = _first(part, "span.geo")
        if geo is not None:
            m = _GEO_RE.match(geo)
            if m:
                return _in_range(float(m.group(1)), float(m.group(2)))
        dec = _first(part, "span.geo-dec")
        if dec is not None:
            d = _DEC_RE.match(dec)
            if d:
                lat = float(d.group(1)) * (1 if d.group(2) == "N" else -1)
                lon = float(d.group(3)) * (1 if d.group(4) == "E" else -1)
                return _in_range(lat, lon)
    return None
