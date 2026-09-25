"""Automatic 506/RR lookups for each selected CFBD game, and crew resolution
(D-06). Matching is deterministic and tiered: exact -> date-shift -> partial
-> ambiguous -> none (ARCHITECTURE.md Pattern 3). No HTTP client is built
here (T-01-51); everything is read from data already cached under
data/vault/raw/.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from booth_review.sources.cfbd.parser import CfbdGame
from booth_review.sources.ratingsref.parser import RRRecord
from booth_review.sources.sports506.parser import Listing506
from booth_review.spike.names import normalize_team, significant_tokens, to_et_date

MatchConfidence = Literal["exact", "date-shift", "partial", "ambiguous", "none"]

_RR_SLUG_PREFIX = "cfb-"


@dataclass(frozen=True)
class Match506:
    confidence: MatchConfidence
    listings: tuple[Listing506, ...]


@dataclass(frozen=True)
class MatchRR:
    confidence: MatchConfidence
    records: tuple[RRRecord, ...]


@dataclass(frozen=True)
class CrewResolution:
    crew: str | None
    matched_listing: Listing506 | None
    notes: str


def _pair(a: str, b: str) -> frozenset[str]:
    return frozenset({normalize_team(a), normalize_team(b)})


def _rr_slug_pair(record: RRRecord) -> frozenset[str]:
    return frozenset(normalize_team(_strip_rr_prefix(slug)) for slug in record.telecast.teams)


def _strip_rr_prefix(slug: str) -> str:
    return slug[len(_RR_SLUG_PREFIX) :] if slug.startswith(_RR_SLUG_PREFIX) else slug


def match_506(game: CfbdGame, listings: Sequence[Listing506]) -> Match506:
    """Match `game` to its 506 listing(s) on unordered team pair + ET date.

    Returns every listing of the matched game (main, alt, Spanish feeds all
    share the same matchup text and date).
    """
    game_et_date = to_et_date(game.start_date)
    game_pair = _pair(game.away_team, game.home_team)
    home_tokens = significant_tokens(game.home_team)
    away_tokens = significant_tokens(game.away_team)

    same_pair = [ln for ln in listings if _pair(ln.away_raw, ln.home_raw) == game_pair]

    exact = [ln for ln in same_pair if ln.date_et == game_et_date]
    if exact:
        return Match506(confidence="exact", listings=tuple(exact))

    shifted = [ln for ln in same_pair if abs((ln.date_et - game_et_date).days) == 1]
    if shifted:
        return Match506(confidence="date-shift", listings=tuple(shifted))

    nearby = [ln for ln in listings if abs((ln.date_et - game_et_date).days) <= 1]
    partial_candidates = []
    for ln in nearby:
        listing_tokens = significant_tokens(ln.away_raw) | significant_tokens(ln.home_raw)
        if (home_tokens & listing_tokens) and (away_tokens & listing_tokens):
            partial_candidates.append(ln)

    if not partial_candidates:
        return Match506(confidence="none", listings=())

    groups: dict[tuple[object, ...], list[Listing506]] = {}
    for ln in partial_candidates:
        key = (ln.date_et, ln.away_raw.strip().casefold(), ln.home_raw.strip().casefold())
        groups.setdefault(key, []).append(ln)

    if len(groups) > 1:
        return Match506(confidence="ambiguous", listings=())

    only_group = next(iter(groups.values()))
    return Match506(confidence="partial", listings=tuple(only_group))


def match_rr(game: CfbdGame, records: Sequence[RRRecord]) -> MatchRR:
    """Apply the same match_506 rules to RR telecast.teams slugs and
    event_date. Duplicate records that resolve to the same game are all
    returned (JOIN-05); the caller pools their claims for headline selection.
    """
    game_et_date = to_et_date(game.start_date)
    game_pair = _pair(game.away_team, game.home_team)
    home_tokens = significant_tokens(game.home_team)
    away_tokens = significant_tokens(game.away_team)

    same_pair = [r for r in records if _rr_slug_pair(r) == game_pair]

    exact = [r for r in same_pair if r.telecast.event_date == game_et_date]
    if exact:
        return MatchRR(confidence="exact", records=tuple(exact))

    shifted = [r for r in same_pair if abs((r.telecast.event_date - game_et_date).days) == 1]
    if shifted:
        return MatchRR(confidence="date-shift", records=tuple(shifted))

    nearby = [r for r in records if abs((r.telecast.event_date - game_et_date).days) <= 1]
    partial_candidates = []
    for r in nearby:
        record_tokens: set[str] = set()
        for slug in r.telecast.teams:
            record_tokens |= significant_tokens(slug)
        if (home_tokens & record_tokens) and (away_tokens & record_tokens):
            partial_candidates.append(r)

    if not partial_candidates:
        return MatchRR(confidence="none", records=())

    groups: dict[tuple[object, ...], list[RRRecord]] = {}
    for r in partial_candidates:
        key = (r.telecast.event_date, _rr_slug_pair(r))
        groups.setdefault(key, []).append(r)

    if len(groups) > 1:
        return MatchRR(confidence="ambiguous", records=())

    only_group = next(iter(groups.values()))
    return MatchRR(confidence="partial", records=tuple(only_group))


def resolve_crew(listings: Sequence[Listing506], rr_networks: Sequence[str]) -> CrewResolution:
    """Pick the main-feed listing whose network matches one of `rr_networks`
    (case-insensitive); else the first main-feed listing. Alt and Spanish
    feeds are never the resolved crew; they go into notes.
    """
    main_listings = [ln for ln in listings if ln.feed_kind == "main"]
    other_listings = [ln for ln in listings if ln.feed_kind != "main"]

    rr_networks_lower = {n.lower() for n in rr_networks}
    matched = next(
        (
            ln
            for ln in main_listings
            if ln.network_raw and ln.network_raw.lower() in rr_networks_lower
        ),
        None,
    )
    chosen = matched if matched is not None else (main_listings[0] if main_listings else None)

    notes = "; ".join(
        f"{ln.feed_kind}: {ln.network_raw or '(no network)'} ({ln.crew_raw or 'no crew listed'})"
        for ln in other_listings
    )
    crew = chosen.crew_raw if chosen is not None else None
    return CrewResolution(crew=crew, matched_listing=chosen, notes=notes)
