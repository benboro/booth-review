"""NFL special-game rules as pure functions (docs/sources/nfl-field-list.md Rules).

Standalone is decided from combined date and kickoff time only; slot_name is a
display label and never feeds it. AGOTW / CBS late national is never picked by
crew or map image. No I/O happens here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

#: Another kickoff this close or closer (inclusive) disqualifies a game.
STANDALONE_GAP = timedelta(hours=3)

#: Late national window (field list: "4:25 ET late national kickoff (4:15-4:35)").
LATE_NATIONAL_MIN = time(16, 15)
LATE_NATIONAL_MAX = time(16, 35)
#: The rule's "1:00 ET game"; a few minutes of tolerance for odd kickoffs.
EARLY_KICK_MIN = time(13, 0)
EARLY_KICK_MAX = time(13, 5)

SlotName = Literal[
    "Christmas",
    "Thanksgiving",
    "Black Friday",
    "International",
    "TNF",
    "SNF",
    "MNF",
    "Saturday",
    "Friday",
    "Sunday early",
    "Sunday late",
    "Other",
]

_THURSDAY, _FRIDAY, _SATURDAY, _SUNDAY, _MONDAY = 3, 4, 5, 6, 0
_NIGHT = time(19, 0)
_SUNDAY_LATE_FROM = time(15, 0)
_NOON = time(12, 0)


def standalone_ids(kickoffs: Mapping[str, datetime]) -> frozenset[str]:
    """Ids whose nearest other kickoff is strictly more than STANDALONE_GAP away.

    The caller passes every game of the season, playoffs included, regardless
    of the playoffs toggle.
    """
    ordered = sorted(kickoffs.items(), key=lambda item: item[1])
    result: set[str] = set()
    for i, (game_id, when) in enumerate(ordered):
        before_ok = i == 0 or when - ordered[i - 1][1] > STANDALONE_GAP
        after_ok = i == len(ordered) - 1 or ordered[i + 1][1] - when > STANDALONE_GAP
        if before_ok and after_ok:
            result.add(game_id)
    return frozenset(result)


def thanksgiving(year: int) -> date:
    """The fourth Thursday of November."""
    first = date(year, 11, 1)
    first_thursday = first + timedelta(days=(_THURSDAY - first.weekday()) % 7)
    return first_thursday + timedelta(weeks=3)


def slot_name(kickoff_et: datetime, *, outside_us: bool) -> SlotName:
    """Display label, first match in field-list order. Never decides standalone."""
    day = kickoff_et.date()
    clock = kickoff_et.timetz().replace(tzinfo=None)
    weekday = day.weekday()
    turkey = thanksgiving(day.year)
    if day.month == 12 and day.day == 25:
        return "Christmas"
    if day == turkey:
        return "Thanksgiving"
    if day == turkey + timedelta(days=1):
        return "Black Friday"
    if outside_us and (clock < _NOON or weekday == _FRIDAY):
        return "International"
    if weekday == _THURSDAY and clock >= _NIGHT:
        return "TNF"
    if weekday == _SUNDAY and clock >= _NIGHT:
        return "SNF"
    if weekday == _MONDAY:
        return "MNF"
    if weekday == _SATURDAY:
        return "Saturday"
    if weekday == _FRIDAY:
        return "Friday"
    if weekday == _SUNDAY:
        return "Sunday early" if clock < _SUNDAY_LATE_FROM else "Sunday late"
    return "Other"


def is_special(
    *,
    is_standalone: bool,
    is_agotw: bool,
    is_cbs_national: bool,
    game_type: str,
    include_playoffs: bool,
) -> bool:
    """Rollup. International and flexed never count; playoffs only when toggled on."""
    if game_type != "REG" and not include_playoffs:
        return False
    return is_standalone or is_agotw or is_cbs_national


_PRIMETIME: frozenset[str] = frozenset({"SNF", "MNF", "TNF"})


def is_flexed(
    *,
    current_slot: SlotName,
    original_slot: SlotName | None,
    is_late_national: bool,
    original_time_et: str | None,
    current_time_et: str,
) -> bool:
    """True for a move into SNF/MNF/TNF or into the AGOTW / CBS late national game.

    Cross-flexes (same slot, different network) are not flexed. Unknown
    original_slot gives False.
    """
    if original_slot is None:
        return False
    if current_slot in _PRIMETIME and current_slot != original_slot:
        return True
    if is_late_national:
        if original_time_et is None:
            return original_slot != "Sunday late"
        return not _in_late_window(_parse_clock(original_time_et))
    return False


def _parse_clock(text: str) -> time:
    hour, minute = text.split(":")[:2]
    return time(int(hour), int(minute))


def _in_late_window(clock: time) -> bool:
    return LATE_NATIONAL_MIN <= clock <= LATE_NATIONAL_MAX


@dataclass(frozen=True)
class DhInput:
    game_id: str
    kickoff_et: datetime
    network_id: str | None


_DH_NETWORKS = ("fox", "cbs")


def _sunday_games(games: Sequence[DhInput]) -> list[DhInput]:
    return [g for g in games if g.kickoff_et.weekday() == _SUNDAY]


def doubleheader_networks(games: Sequence[DhInput]) -> frozenset[str]:
    """Networks (fox, cbs) with a late-window game and a 1:00 ET game that Sunday.

    Games passed are one date's; non-Sunday dates give an empty set.
    """
    found: set[str] = set()
    sunday = _sunday_games(games)
    for network in _DH_NETWORKS:
        mine = [g for g in sunday if g.network_id == network]
        has_late = any(_in_late_window(g.kickoff_et.timetz().replace(tzinfo=None)) for g in mine)
        has_early = any(
            EARLY_KICK_MIN <= g.kickoff_et.timetz().replace(tzinfo=None) <= EARLY_KICK_MAX
            for g in mine
        )
        if has_late and has_early:
            found.add(network)
    return frozenset(found)


def late_national_candidates(games: Sequence[DhInput], network: str) -> tuple[str, ...]:
    """Game ids of `network` in the late national window on a Sunday."""
    return tuple(
        g.game_id
        for g in _sunday_games(games)
        if g.network_id == network and _in_late_window(g.kickoff_et.timetz().replace(tzinfo=None))
    )


@dataclass(frozen=True)
class LateNationalPick:
    game_id: str | None
    source: Literal["single", "rr", "506", "override", "ambiguous"]
    override_unused: bool


def pick_late_national(
    candidates: Sequence[str],
    *,
    rr_named: AbstractSet[str],
    s506_named: AbstractSet[str],
    override_game_id: str | None,
) -> LateNationalPick:
    """Pick the AGOTW / CBS late national game from text sources only.

    Never by crew or map image. An override settles only an otherwise
    ambiguous week; naming a non-candidate raises ValueError.
    """
    pool = set(candidates)
    if override_game_id is not None and override_game_id not in pool:
        raise ValueError("override names a game that is not a late national candidate")
    settled: LateNationalPick | None = None
    if len(candidates) == 1:
        settled = LateNationalPick(candidates[0], "single", False)
    elif len(candidates) > 1:
        named = (set(rr_named) | set(s506_named)) & pool
        if len(named) == 1:
            (only,) = named
            settled = LateNationalPick(only, "rr" if only in rr_named else "506", False)
    if settled is not None:
        return LateNationalPick(
            settled.game_id, settled.source, override_unused=override_game_id is not None
        )
    if override_game_id is not None:
        return LateNationalPick(override_game_id, "override", False)
    return LateNationalPick(None, "ambiguous", False)
