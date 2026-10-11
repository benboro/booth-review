"""Match Wikipedia scheduling changes to nflverse games (D-14: never guessed).

A change is keyed by season, week and the unordered franchise pair. The original
slot is derived with the same slot_name rule as the current slot. International
games are not special-cased: a move out of an international slot is not
representable from article text, so outside_us is False here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from booth_review.nfl.inputs import NflInputs
from booth_review.nfl.layout import wikipedia_url
from booth_review.nfl.listings import index_games
from booth_review.nfl.rules import ET, SlotName, slot_name
from booth_review.nfl.schedule import NflGame
from booth_review.nfl.teams import NflNetworkResolver, NflTeamResolver
from booth_review.sources.wikipedia.parser import ScheduleChange

_WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


@dataclass(frozen=True)
class GameChange:
    game_id: str
    original_slot: SlotName | None
    original_network_id: str | None
    original_time_et: str | None
    new_network_id: str | None
    article_url: str
    raw_text_hash: str


@dataclass(frozen=True)
class ChangeReview:
    season: int
    week: int | None
    raw_text_hash: str
    reason: str


def _original_date(game: NflGame, day_name: str | None) -> date:
    """The game's date, or the stated weekday within the game's Thursday-Wednesday week."""
    if day_name:
        target = _WEEKDAYS.get(day_name.strip()[:3].casefold())
        if target is not None:
            start = game.gameday - timedelta(days=(game.gameday.weekday() - 3) % 7)
            return start + timedelta(days=(target - 3) % 7)
    return game.gameday


def _original_slot(game: NflGame, change: ScheduleChange) -> SlotName | None:
    if not change.original_time_et:
        return None
    try:
        hour, minute = (int(part) for part in change.original_time_et.split(":")[:2])
    except ValueError:
        return None
    day = _original_date(game, change.original_day)
    when = datetime.combine(day, time(hour, minute), tzinfo=ET)
    return slot_name(when, outside_us=False)


def match_schedule_changes(
    inputs: NflInputs, teams: NflTeamResolver, networks: NflNetworkResolver
) -> tuple[dict[str, GameChange], list[ChangeReview]]:
    index = index_games(inputs, teams)
    matched: dict[str, GameChange] = {}
    reviews: list[ChangeReview] = []
    for season, result in sorted(inputs.changes.items()):
        for unparsed in result.unparsed:
            reviews.append(ChangeReview(season, unparsed.week, unparsed.raw_text_hash, "unparsed"))
        for change in result.changes:
            a = teams.resolve("wikipedia", change.team_a_raw, season).franchise_id
            b = teams.resolve("wikipedia", change.team_b_raw, season).franchise_id
            if a is None or b is None or a == b:
                reviews.append(
                    ChangeReview(season, change.week, change.raw_text_hash, "unresolved-team")
                )
                continue
            candidates = index.get((season, change.week, frozenset((a, b))), [])
            if not candidates:
                reviews.append(ChangeReview(season, change.week, change.raw_text_hash, "no-game"))
                continue
            if len(candidates) > 1:
                reviews.append(
                    ChangeReview(season, change.week, change.raw_text_hash, "ambiguous-game")
                )
                continue
            game = candidates[0]
            if game.game_id in matched:
                reviews.append(
                    ChangeReview(season, change.week, change.raw_text_hash, "multiple-changes")
                )
                continue
            original_net = (
                networks.resolve("wikipedia", change.original_network_raw)
                if change.original_network_raw
                else None
            )
            new_net = (
                networks.resolve("wikipedia", change.new_network_raw)
                if change.new_network_raw
                else None
            )
            matched[game.game_id] = GameChange(
                game_id=game.game_id,
                original_slot=_original_slot(game, change),
                original_network_id=original_net,
                original_time_et=change.original_time_et,
                new_network_id=new_net,
                article_url=wikipedia_url(season),
                raw_text_hash=change.raw_text_hash,
            )
    return matched, reviews
