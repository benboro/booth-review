"""Match Ratings Reference MLB records to games (D-14), with every hazard reported.

This is the MLB twin of `nfl/rr_match.py`; the four `cfb-` regexes stay untouched.
Slugs read `mlb-<nick>-<nick>-<yyyy-mm-dd>`: two nicknames in alphabetical order (not
away then home), possibly multi-word ("red-sox"), no game number. Nothing is guessed
or summed:

- a same-day doubleheader between the same clubs is `ambiguous_doubleheader`;
- two records for one game with different finals and no supersedes link are a
  `conflict`; records that each cover a different network are `per_network`;
- a record whose headline is a per-network cut is `per_network`;
- event slugs (all-star game, home run derby) are skipped;
- a regionalized window figure is kept but labelled `window-level`.

Every figure keeps its record URL and the headline claim's `source_url`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Final, Literal

import polars as pl

from booth_review.flags.era import MeasurementEra, era_check, era_for
from booth_review.mlb.constants import MAX_DATE_SHIFT_DAYS
from booth_review.mlb.teams import MlbNetworkResolver, MlbTeamResolver
from booth_review.resolve.headline import claim_id, select_headline
from booth_review.sources.ratingsref.parser import RRClaim, RRRecord

__all__ = [
    "MLB_RR_CAUSES",
    "RRGameMatch",
    "RRReview",
    "match_mlb_rr",
]

#: Why a game has no usable figure ("pending" and "regional" are set by the site builder).
MLB_RR_CAUSES: Final = ("none", "per_network", "ambiguous_doubleheader", "conflict", "window_level")

_SLUG_DATE_RE = re.compile(r"-\d{4}-\d{2}-\d{2}$")
# RR team ids carry the league prefix ("mlb-aces"), as CFB ids carry "cfb-".
_TEAM_ID_PREFIX = "mlb-"
_EVENT_PREFIXES: Final = ("mlb-all-star", "mlb-home-run-derby")


@dataclass(frozen=True)
class RRGameMatch:
    """What Ratings Reference says about one game (a row per game, matched or not)."""

    game_key: str
    cause: str | None
    tier: Literal["date", "date-shift"] | None
    telecast_ids: tuple[str, ...]
    record_url: str | None
    record_urls: tuple[str, ...]
    network_ids: tuple[str, ...]
    viewers: float | None
    viewership_label: str
    era_id: str | None
    era_check: str | None
    headline_cut: str | None
    headline_status: str | None
    headline_era_id: str | None
    headline_source_url: str | None
    headline_measured_by: str | None
    title: str | None


@dataclass(frozen=True)
class RRReview:
    season: int
    telecast_id: str
    reason: str


# -- slug and teams ----------------------------------------------------------------------------


def is_event_slug(slug: str) -> bool:
    return slug.startswith(_EVENT_PREFIXES)


def _pair_from_names(
    names: Iterable[str], teams: MlbTeamResolver, season: int
) -> frozenset[str] | None:
    found: list[str] = []
    for name in names:
        key = name.removeprefix(_TEAM_ID_PREFIX)
        club = teams.resolve("ratingsref", key, season).club_id
        if club is not None and club not in found:
            found.append(club)
    return frozenset(found) if len(found) == 2 else None


def _pair_from_slug(slug: str, teams: MlbTeamResolver, season: int) -> frozenset[str] | None:
    body = _SLUG_DATE_RE.sub("", slug).removeprefix(_TEAM_ID_PREFIX)
    tokens = [t for t in body.split("-") if t]
    # Multi-word nicknames: try every split of the remaining tokens into two nicknames.
    for split in range(1, len(tokens)):
        first = teams.resolve("ratingsref", "-".join(tokens[:split]), season).club_id
        second = teams.resolve("ratingsref", "-".join(tokens[split:]), season).club_id
        if first and second and first != second:
            return frozenset((first, second))
    return None


def _record_pair(record: RRRecord, teams: MlbTeamResolver, season: int) -> frozenset[str] | None:
    pair = _pair_from_names(record.telecast.teams, teams, season)
    return pair or _pair_from_slug(record.telecast.id, teams, season)


# -- figure labels -----------------------------------------------------------------------------


def _extra(claim: RRClaim) -> Mapping[str, object]:
    return claim.model_extra or {}


def _is_window(claim: RRClaim) -> bool:
    return claim.cut == "window" or _extra(claim).get("figure_scope") == "split_window"


def _viewership_label(claim: RRClaim | None) -> str:
    """Per-game, window-level, composite, unnormalized or none, from the claim's own fields."""
    if claim is None:
        return "none"
    extra = _extra(claim)
    if claim.composite_of:
        return "composite"
    if _is_window(claim):
        return "window-level"
    if extra.get("unnormalized") is True or extra.get("normalized") is False:
        return "unnormalized"
    return "per-game"


# -- game index --------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Game:
    key: str
    day: date
    away: str
    home: str


def _find(
    candidates: Sequence[_Game], event_date: date
) -> tuple[list[_Game], Literal["date", "date-shift"]] | None:
    exact = [g for g in candidates if g.day == event_date]
    if exact:
        return exact, "date"
    shifted = [g for g in candidates if abs((g.day - event_date).days) <= MAX_DATE_SHIFT_DAYS]
    if shifted:
        return shifted, "date-shift"
    return None


def _superseded(records: Sequence[RRRecord]) -> set[int]:
    """Indexes of records an other record's claim supersedes (an explicit replacement)."""
    owner: dict[str, int] = {}
    for i, rec in enumerate(records):
        for claim in rec.claims:
            cid = claim_id(claim)
            if cid is not None:
                owner[cid] = i
    out: set[int] = set()
    for i, rec in enumerate(records):
        for claim in rec.claims:
            target = owner.get(claim.supersedes_id) if claim.supersedes_id else None
            if target is not None and target != i:
                out.add(target)
    return out


def _networks(record: RRRecord) -> frozenset[str]:
    return frozenset(n.strip().casefold() for n in record.telecast.networks if n.strip())


def _network_ids(
    records: Sequence[RRRecord], networks: MlbNetworkResolver | None
) -> tuple[str, ...]:
    ids: list[str] = []
    if networks is not None:
        for rec in records:
            for raw in rec.telecast.networks:
                nid = networks.resolve("ratingsref", raw).network_id
                if nid is not None and nid not in ids:
                    ids.append(nid)
    return tuple(ids)


def _result(
    game: _Game,
    records: Sequence[RRRecord],
    tier: Literal["date", "date-shift"] | None,
    cause: str | None,
    *,
    eras: Sequence[MeasurementEra],
    networks: MlbNetworkResolver | None,
    claim: RRClaim | None = None,
) -> RRGameMatch:
    era = era_for(game.day, eras) if eras else None
    keep_figure = cause in (None, "window_level") and claim is not None
    first = records[0] if records else None
    return RRGameMatch(
        game_key=game.key,
        cause=cause,
        tier=tier,
        telecast_ids=tuple(r.telecast.id for r in records),
        record_url=first.record_url if first is not None and len(records) == 1 else None,
        record_urls=tuple(r.record_url for r in records),
        network_ids=_network_ids(records, networks),
        viewers=claim.value if keep_figure and claim is not None else None,
        viewership_label=_viewership_label(claim) if keep_figure else "none",
        era_id=era.era_id if era is not None else None,
        era_check=era_check(era, claim.era_id) if era is not None and claim is not None else None,
        headline_cut=claim.cut if keep_figure and claim is not None else None,
        headline_status=claim.status if keep_figure and claim is not None else None,
        headline_era_id=claim.era_id if keep_figure and claim is not None else None,
        headline_source_url=claim.source_url if keep_figure and claim is not None else None,
        headline_measured_by=claim.measured_by if keep_figure and claim is not None else None,
        title=first.telecast.title if first is not None and len(records) == 1 else None,
    )


def _single(
    game: _Game,
    record: RRRecord,
    tier: Literal["date", "date-shift"],
    *,
    eras: Sequence[MeasurementEra],
    networks: MlbNetworkResolver | None,
) -> RRGameMatch:
    claim = select_headline(record.claims)
    if claim is None:
        return _result(game, [record], tier, "none", eras=eras, networks=networks)
    if claim.cut == "per_network":
        # The record keeps its URL for provenance, but no figure is shown or summed.
        out = _result(game, [record], tier, "per_network", eras=eras, networks=networks)
        return out
    cause = "window_level" if _is_window(claim) else None
    return _result(game, [record], tier, cause, eras=eras, networks=networks, claim=claim)


def _combine(
    game: _Game,
    records: Sequence[RRRecord],
    tier: Literal["date", "date-shift"],
    reviews: list[RRReview],
    *,
    eras: Sequence[MeasurementEra],
    networks: MlbNetworkResolver | None,
) -> RRGameMatch:
    """Several records for one game: replacement first, then equal finals, else a cause."""
    dropped = _superseded(records)
    live = [r for i, r in enumerate(records) if i not in dropped]
    if len(live) == 1:
        return _single(game, live[0], tier, eras=eras, networks=networks)
    claims = [select_headline(r.claims) for r in live]
    values = {c.value for c in claims if c is not None}
    if len(values) <= 1 and all(c is not None for c in claims):
        return _single(game, live[0], tier, eras=eras, networks=networks)
    nets = [_networks(r) for r in live]
    distinct = all(n for n in nets) and all(
        nets[i].isdisjoint(nets[j]) for i in range(len(nets)) for j in range(i + 1, len(nets))
    )
    cause = "per_network" if distinct else "conflict"
    for rec in live:
        reviews.append(RRReview(game.day.year, rec.telecast.id, cause))
    return _result(game, live, tier, cause, eras=eras, networks=networks)


def match_mlb_rr(
    records: Iterable[RRRecord],
    games: pl.DataFrame,
    telecasts: pl.DataFrame,
    teams: MlbTeamResolver,
    eras: Sequence[MeasurementEra],
    networks: MlbNetworkResolver | None = None,
) -> tuple[list[RRGameMatch], list[RRReview]]:
    """One `RRGameMatch` per game in `games` (cause "none" when no record attaches).

    `telecasts` is accepted so a caller can later tie a per-network record to its
    telecast row; matching itself is by club pair and date, since RR slugs carry no
    network or game number.
    """
    del telecasts
    by_pair: dict[frozenset[str], list[_Game]] = {}
    ordered: list[_Game] = []
    for row in games.select("game_key", "game_date", "away_club", "home_club").iter_rows():
        game = _Game(row[0], row[1], row[2], row[3])
        ordered.append(game)
        by_pair.setdefault(frozenset((game.away, game.home)), []).append(game)

    reviews: list[RRReview] = []
    attached: dict[str, list[tuple[RRRecord, Literal["date", "date-shift"]]]] = {}
    ambiguous: dict[str, str] = {}
    for record in records:
        tid = record.telecast.id
        event_date = record.telecast.event_date
        season = event_date.year
        if is_event_slug(tid):
            reviews.append(RRReview(season, tid, "event"))
            continue
        pair = _record_pair(record, teams, season)
        if pair is None:
            reviews.append(RRReview(season, tid, "unresolved_team"))
            continue
        found = _find(by_pair.get(pair, []), event_date)
        if found is None:
            reviews.append(RRReview(season, tid, "unmatched"))
            continue
        candidates, tier = found
        if len(candidates) > 1:
            same_day = len({g.day for g in candidates}) == 1
            reason = "ambiguous_doubleheader" if same_day else "ambiguous_date_shift"
            reviews.append(RRReview(season, tid, reason))
            if same_day:
                for g in candidates:
                    ambiguous[g.key] = reason
            continue
        game = candidates[0]
        attached.setdefault(game.key, []).append((record, tier))

    matches: list[RRGameMatch] = []
    for game in ordered:
        if game.key in ambiguous:
            matches.append(
                _result(game, [], None, "ambiguous_doubleheader", eras=eras, networks=networks)
            )
            continue
        found_records = attached.get(game.key)
        if not found_records:
            matches.append(_result(game, [], None, "none", eras=eras, networks=networks))
            continue
        tier = "date" if any(t == "date" for _, t in found_records) else "date-shift"
        recs = [r for r, _ in found_records]
        if len(recs) == 1:
            matches.append(_single(game, recs[0], tier, eras=eras, networks=networks))
        else:
            matches.append(_combine(game, recs, tier, reviews, eras=eras, networks=networks))
    return matches, reviews
