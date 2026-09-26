"""Deterministic tiered matching of a CFBD game to its 506 listing(s) and RR
record(s), promoted from the Phase 1 spike (D-06) into booth_review.resolve
for Phase 3's join layer (JOIN-02), plus the FBS-inclusion filter (JOIN-07).

Matching is tiered: exact -> date-shift -> partial -> ambiguous -> none
(ARCHITECTURE.md Pattern 3). is_fbs_game is a precondition applied before any
matching runs, not one of the tiers itself.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from booth_review.errors import ReferenceTableError
from booth_review.resolve.names import normalize_team, significant_tokens, to_et_date
from booth_review.resolve.overrides import GameOverride, pointer_for_listing, pointer_for_record
from booth_review.resolve.teams import ResolvedTeam, TeamResolver
from booth_review.seasons import season_of
from booth_review.sources.cfbd.parser import CfbdGame
from booth_review.sources.ratingsref.parser import RRRecord
from booth_review.sources.sports506.parser import Listing506

MatchConfidence = Literal["exact", "date-shift", "partial", "ambiguous", "none"]
GameMatchSource = Literal["override", "auto"]

_RR_SLUG_PREFIX = "cfb-"

CONFIDENCE_RANK: dict[str, int] = {
    "exact": 0,
    "date-shift": 1,
    "partial": 2,
    "ambiguous": 3,
    "none": 4,
}


@dataclass(frozen=True)
class Match506:
    confidence: MatchConfidence
    listings: tuple[Listing506, ...]


@dataclass(frozen=True)
class MatchRR:
    confidence: MatchConfidence
    records: tuple[RRRecord, ...]


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


def is_fbs_game(game: CfbdGame) -> bool:
    """True when at least one team is FBS that season (JOIN-07): a game is
    in scope even against an FCS opponent, but fcs-vs-fcs and
    unclassified-vs-unclassified games are excluded.
    """
    return "fbs" in (game.home_classification, game.away_classification)


# -- Crosswalk-aware, record-centric matching (JOIN-01/02/08) -----------------------------


@dataclass(frozen=True)
class GameMatch:
    """The outcome of matching one 506 listing or RR record to a CFBD game
    through the team crosswalk and the pointer-only override table.
    """

    confidence: MatchConfidence
    game: CfbdGame | None
    source: GameMatchSource
    excluded: bool
    home_resolved: ResolvedTeam
    away_resolved: ResolvedTeam


class GameIndex:
    """Every CFBD game (all divisions, all seasons), indexed for fast lookup
    by (season, unordered team-id pair) and by (season, ET date), plus a
    by-id map for override targets. Built once per diagnostic run so a full
    2014-2026 pass never rescans every game per listing/record.
    """

    def __init__(self, games: Sequence[CfbdGame]) -> None:
        self._by_id: dict[int, CfbdGame] = {}
        self._by_pair: dict[tuple[int, frozenset[int]], list[CfbdGame]] = {}
        self._by_season_date: dict[tuple[int, date], list[CfbdGame]] = {}
        for game in games:
            self._by_id[game.id] = game
            et_date = to_et_date(game.start_date)
            self._by_season_date.setdefault((game.season, et_date), []).append(game)
            if game.home_id is not None and game.away_id is not None:
                pair_key = (game.season, frozenset({game.home_id, game.away_id}))
                self._by_pair.setdefault(pair_key, []).append(game)

    def by_id(self, game_id: int) -> CfbdGame | None:
        return self._by_id.get(game_id)

    def games_by_pair(self, season: int, team_ids: frozenset[int]) -> list[CfbdGame]:
        return self._by_pair.get((season, team_ids), [])

    def games_near(self, season: int, et_date: date, *, within_days: int = 1) -> list[CfbdGame]:
        result: list[CfbdGame] = []
        for offset in range(-within_days, within_days + 1):
            result.extend(self._by_season_date.get((season, et_date + timedelta(days=offset)), []))
        return result


def _apply_override_result(
    override: GameOverride,
    index: GameIndex,
    home_resolved: ResolvedTeam,
    away_resolved: ResolvedTeam,
) -> GameMatch:
    if override.action == "exclude":
        return GameMatch(
            confidence="none",
            game=None,
            source="override",
            excluded=True,
            home_resolved=home_resolved,
            away_resolved=away_resolved,
        )
    game = index.by_id(override.cfbd_game_id) if override.cfbd_game_id is not None else None
    if game is None:
        raise ReferenceTableError(
            f"game_overrides.csv: unknown cfbd_game_id {override.cfbd_game_id} "
            f"for pointer {override.pointer!r}"
        )
    return GameMatch(
        confidence="exact",
        game=game,
        source="override",
        excluded=False,
        home_resolved=home_resolved,
        away_resolved=away_resolved,
    )


def _match_by_teams(
    index: GameIndex,
    *,
    season: int,
    date_et: date,
    home_resolved: ResolvedTeam,
    away_resolved: ResolvedTeam,
    home_raw: str,
    away_raw: str,
) -> GameMatch:
    if home_resolved.team_id is not None and away_resolved.team_id is not None:
        pair = frozenset({home_resolved.team_id, away_resolved.team_id})
        candidates = index.games_by_pair(season, pair)

        exact = [g for g in candidates if to_et_date(g.start_date) == date_et]
        if exact:
            confidence: MatchConfidence = "exact" if len(exact) == 1 else "ambiguous"
            game = exact[0] if len(exact) == 1 else None
            return GameMatch(confidence, game, "auto", False, home_resolved, away_resolved)

        shifted = [g for g in candidates if abs((to_et_date(g.start_date) - date_et).days) == 1]
        if shifted:
            confidence = "date-shift" if len(shifted) == 1 else "ambiguous"
            game = shifted[0] if len(shifted) == 1 else None
            return GameMatch(confidence, game, "auto", False, home_resolved, away_resolved)

        return GameMatch("none", None, "auto", False, home_resolved, away_resolved)

    # At least one team is unresolved: fall back to the spike's token-overlap
    # rule, grouped by CFBD game id (never attempted when both teams resolve
    # -- a resolved pair simply missing from the index is "none", not partial).
    home_tokens = significant_tokens(home_raw)
    away_tokens = significant_tokens(away_raw)
    groups: dict[int, CfbdGame] = {}
    for game in index.games_near(season, date_et):
        game_tokens = significant_tokens(game.home_team) | significant_tokens(game.away_team)
        if (home_tokens & game_tokens) and (away_tokens & game_tokens):
            groups[game.id] = game

    if not groups:
        return GameMatch("none", None, "auto", False, home_resolved, away_resolved)
    if len(groups) > 1:
        return GameMatch("ambiguous", None, "auto", False, home_resolved, away_resolved)
    return GameMatch(
        "partial", next(iter(groups.values())), "auto", False, home_resolved, away_resolved
    )


def match_listing_to_game(
    listing: Listing506,
    index: GameIndex,
    resolver: TeamResolver,
    overrides: Mapping[tuple[str, int, str], GameOverride],
) -> GameMatch:
    """Match one 506 listing to a CFBD game: the pointer-only override table
    first, then the team crosswalk plus the exact/date-shift/partial/
    ambiguous/none tiers (JOIN-01/02).
    """
    season = listing.season
    home_resolved = resolver.resolve("sports506", listing.home_raw, season)
    away_resolved = resolver.resolve("sports506", listing.away_raw, season)

    override = overrides.get(("sports506", season, pointer_for_listing(listing)))
    if override is not None:
        return _apply_override_result(override, index, home_resolved, away_resolved)

    return _match_by_teams(
        index,
        season=season,
        date_et=listing.date_et,
        home_resolved=home_resolved,
        away_resolved=away_resolved,
        home_raw=listing.home_raw,
        away_raw=listing.away_raw,
    )


def match_record_to_game(
    record: RRRecord,
    index: GameIndex,
    resolver: TeamResolver,
    overrides: Mapping[tuple[str, int, str], GameOverride],
) -> GameMatch:
    """Match one RR record to a CFBD game: the pointer-only override table
    first, then the team crosswalk plus the exact/date-shift/partial/
    ambiguous/none tiers (JOIN-01/02). `telecast.teams` must hold exactly two
    slugs to attempt a name-based match; any other count resolves both sides
    unresolved rather than guessing which slug is which team.
    """
    season = season_of(record.telecast.event_date)
    teams = record.telecast.teams
    if len(teams) == 2:
        team_a_raw, team_b_raw = teams
        team_a_resolved = resolver.resolve("ratingsref", team_a_raw, season)
        team_b_resolved = resolver.resolve("ratingsref", team_b_raw, season)
    else:
        team_a_raw = team_b_raw = ""
        team_a_resolved = ResolvedTeam(team_id=None, canonical=None, method="unresolved")
        team_b_resolved = team_a_resolved

    override = overrides.get(("ratingsref", season, pointer_for_record(record)))
    if override is not None:
        return _apply_override_result(override, index, team_a_resolved, team_b_resolved)

    return _match_by_teams(
        index,
        season=season,
        date_et=record.telecast.event_date,
        home_resolved=team_a_resolved,
        away_resolved=team_b_resolved,
        home_raw=team_a_raw,
        away_raw=team_b_raw,
    )
