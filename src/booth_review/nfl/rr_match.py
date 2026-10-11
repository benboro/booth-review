"""Match Ratings Reference NFL records to nflverse games (D-14, RESEARCH Pitfall 8).

Teams come from RRTelecast.teams, falling back to the slug tokens after the
"nfl-" prefix; both resolve through the crosswalk. Every match keeps the record
URL and the headline claim's source_url (RR reuse terms).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Literal

from booth_review.nfl.inputs import NflInputs
from booth_review.nfl.listings import index_games
from booth_review.nfl.schedule import NflGame
from booth_review.nfl.teams import NflNetworkResolver, NflTeamResolver
from booth_review.resolve.headline import select_headline
from booth_review.sources.ratingsref.parser import RRRecord

#: Most days a record may trail its game and still count as the same game (Thu-Wed week).
MAX_DATE_SHIFT_DAYS = 3
_SLUG_DATE_RE = re.compile(r"-\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class RRGameMatch:
    game_id: str
    telecast_id: str
    record_url: str
    network_ids: tuple[str, ...]
    tier: Literal["date", "date-shift"]
    event_date: date
    headline_value: float | None
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


def _pair_from_names(
    names: list[str], teams: NflTeamResolver, season: int
) -> frozenset[str] | None:
    found: list[str] = []
    for name in names:
        fid = teams.resolve("ratingsref", name, season).franchise_id
        if fid is not None and fid not in found:
            found.append(fid)
    return frozenset(found) if len(found) == 2 else None


def _pair_from_slug(slug: str, teams: NflTeamResolver, season: int) -> frozenset[str] | None:
    body = _SLUG_DATE_RE.sub("", slug)
    if body.startswith("nfl-"):
        body = body[4:]
    tokens = [t for t in body.split("-") if t]
    # Event words (christmas, kickoff, ...) may lead the slug; skip as few leading tokens as needed.
    for start in range(len(tokens)):
        rest = tokens[start:]
        for split in range(1, len(rest)):
            first = teams.resolve("ratingsref", "-".join(rest[:split]), season).franchise_id
            second = teams.resolve("ratingsref", "-".join(rest[split:]), season).franchise_id
            if first and second and first != second:
                return frozenset((first, second))
    return None


def _record_pair(record: RRRecord, teams: NflTeamResolver, season: int) -> frozenset[str] | None:
    pair = _pair_from_names(list(record.telecast.teams), teams, season)
    return pair or _pair_from_slug(record.telecast.id, teams, season)


def _find_game(
    candidates: list[NflGame], event_date: date
) -> tuple[NflGame, Literal["date", "date-shift"]] | None:
    exact = [g for g in candidates if g.gameday == event_date]
    if exact:
        return exact[0], "date"
    shifted = sorted(
        (
            g
            for g in candidates
            if 0 < (event_date - g.gameday).days <= MAX_DATE_SHIFT_DAYS
            and _same_nfl_week(g, event_date)
        ),
        key=lambda g: g.gameday,
    )
    if shifted:
        return shifted[0], "date-shift"
    return None


def _same_nfl_week(game: NflGame, event_date: date) -> bool:
    """True when event_date falls in the game's Thursday-Wednesday week."""
    start = game.gameday.toordinal() - ((game.gameday.weekday() - 3) % 7)
    return start <= event_date.toordinal() <= start + 6


def match_rr_records(
    inputs: NflInputs, teams: NflTeamResolver, networks: NflNetworkResolver | None = None
) -> tuple[dict[str, list[RRGameMatch]], list[RRReview]]:
    index = index_games(inputs, teams)
    by_pair: dict[tuple[int, frozenset[str]], list[NflGame]] = {}
    for (g_season, _week, g_pair), games in index.items():
        by_pair.setdefault((g_season, g_pair), []).extend(games)

    matches: dict[str, list[RRGameMatch]] = {}
    reviews: list[RRReview] = []
    for season, records in sorted(inputs.rr_records.items()):
        for record in records:
            tid = record.telecast.id
            pair = _record_pair(record, teams, season)
            if pair is None:
                reviews.append(RRReview(season, tid, "unresolved-team"))
                continue
            found = _find_game(by_pair.get((season, pair), []), record.telecast.event_date)
            if found is None:
                reviews.append(RRReview(season, tid, "no-game"))
                continue
            game, tier = found
            claim = select_headline(record.claims)
            network_ids: list[str] = []
            if networks is not None:
                for raw in record.telecast.networks:
                    nid = networks.resolve("ratingsref", raw)
                    if nid is not None and nid not in network_ids:
                        network_ids.append(nid)
            matches.setdefault(game.game_id, []).append(
                RRGameMatch(
                    game_id=game.game_id,
                    telecast_id=tid,
                    record_url=record.record_url,
                    network_ids=tuple(network_ids),
                    tier=tier,
                    event_date=record.telecast.event_date,
                    headline_value=claim.value if claim else None,
                    headline_cut=claim.cut if claim else None,
                    headline_status=claim.status if claim else None,
                    headline_era_id=claim.era_id if claim else None,
                    headline_source_url=claim.source_url if claim else None,
                    headline_measured_by=claim.measured_by if claim else None,
                    title=record.telecast.title,
                )
            )
    return matches, reviews
