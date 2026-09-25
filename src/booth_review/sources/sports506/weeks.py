"""506 Sports: D-03 parse smoke check and D-05 offline week-list discovery.

Both functions read a page already saved to disk (imported or cached); neither
sends a request. `smoke_check` gives the importer a cheap, printable signal
that a hand-saved page is a genuine, mostly-complete week page rather than a
truncated download, a Cloudflare challenge page, or an older layout the
current parser can't read. `discover_season_weeks` reads a season's own page
navigation for the week labels that season actually shows, so a completeness
check never assumes a fixed weeks-0-through-16-plus-B pattern held for every
season (2020's irregular schedule is the concrete case this avoids).

The smoke-check thresholds below are a judgment call from the 2025 baseline
(RESEARCH.md Pattern 4: every 2025 week clears roughly 70-100% crew coverage)
and are named constants so they can be confirmed or tuned at the D-06 freeze
checkpoint, not silently hardcoded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from booth_review.errors import ParseError
from booth_review.sources.sports506.collector import WEEK_LABELS
from booth_review.sources.sports506.parser import parse_week_page

# D-03: a page must parse to at least this many games, with at least this
# share carrying a non-empty crew, or the import is rejected with a
# count-only reason. Every real 2025 week clears ~70-100% crew coverage,
# so 50% is a conservative floor that still catches a broken/incomplete save.
SMOKE_MIN_GAMES = 1
SMOKE_MIN_CREW_SHARE = 0.5

# Nav anchors on a season's own page use a literal "&" (not the "&amp;" of
# the <link rel="canonical"> tag), so this is a dedicated regex, not a reuse
# of the importer's canonical-link pattern (RESEARCH.md Pattern 3).
_WEEK_ANCHOR_RE = re.compile(
    r'<a\b[^>]*\bhref=["\'][^"\']*ncaaf\.php\?yr=(\d{4})(?:&amp;|&)wk=(\d{1,2}|B)["\']',
    re.IGNORECASE,
)

_CACHE_NAME_RE = re.compile(r"^wk-(\d{1,2}|B)\.html$")


@dataclass(frozen=True)
class SmokeResult:
    """The outcome of a D-03 smoke check on one saved 506 week page."""

    passed: bool
    games: int
    with_crew: int
    reason: str | None


@dataclass(frozen=True)
class SeasonWeeks:
    """The week labels a season's own page navigation lists (D-05)."""

    labels: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)


def smoke_check(html: bytes, *, season: int, week_label: str) -> SmokeResult:
    """Check that `html` plausibly parses to a real week's worth of games.

    Never raises: a page that fails to parse at all (empty body, no schedule
    rows) is reported as a failed SmokeResult with a `"parse failed: ..."`
    reason, not a propagated ParseError. ParseError's own message names only
    the season and week label, so the reason stays safe to print or commit.
    """
    try:
        listings = parse_week_page(html, season=season, week_label=week_label)
    except ParseError as exc:
        return SmokeResult(passed=False, games=0, with_crew=0, reason=f"parse failed: {exc}")

    games = len(listings)
    with_crew = sum(1 for row in listings if row.crew_names)
    if games < SMOKE_MIN_GAMES or with_crew / games < SMOKE_MIN_CREW_SHARE:
        return SmokeResult(
            passed=False,
            games=games,
            with_crew=with_crew,
            reason=f"smoke check failed: {with_crew}/{games} games with crew",
        )
    return SmokeResult(passed=True, games=games, with_crew=with_crew, reason=None)


def _normalize_label(raw: str) -> str:
    return raw if raw == "B" else str(int(raw))


def _sort_key(label: str) -> tuple[int, int]:
    return (1, 0) if label == "B" else (0, int(label))


def discover_season_weeks(html: bytes, season: int) -> SeasonWeeks:
    """Read the week labels `season`'s own page navigation lists.

    Only anchors for `season` itself are kept (a page's nav also links one
    representative week per prior archive year); those are ignored. A label
    recognized by the importer (in WEEK_LABELS) goes to `labels`; anything
    else (e.g. a future or malformed label) goes to `unsupported` rather than
    being silently dropped.
    """
    text = html.decode("utf-8", errors="replace")
    labels: set[str] = set()
    unsupported: set[str] = set()
    for match in _WEEK_ANCHOR_RE.finditer(text):
        year = int(match.group(1))
        if year != season:
            continue
        label = _normalize_label(match.group(2))
        if label in WEEK_LABELS:
            labels.add(label)
        else:
            unsupported.add(label)
    return SeasonWeeks(
        labels=sorted(labels, key=_sort_key),
        unsupported=sorted(unsupported, key=_sort_key),
    )


def label_from_cache_name(name: str) -> str | None:
    """Return the week label a cached filename (`wk-00.html`, `wk-B.html`) encodes.

    Used by later plans (completeness audit, gap reports) to read week labels
    back out of already-cached files without re-parsing page content.
    """
    match = _CACHE_NAME_RE.match(name)
    if match is None:
        return None
    return _normalize_label(match.group(1))
