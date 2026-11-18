"""Awful Announcing as a second NFL crew source, coalesced with 506.

AA's weekly NFL announcing-schedule post (`booth-review import aa`, cached at
`raw/nfl/aa/crews/<season>/wk-NN.html`) lists a role-tagged booth for each game.
This module matches those booths to nflverse games and coalesces them with the 506
crew, by the rules the college football build uses (`build/crew_aa.py`):

- A game with no 506 booth (no 506 listing, no resolved play-by-play voice, or a
  published-lineup fill) takes AA's booth: `crew_source` "aa" with the post URL.
- AA's people equal to, or all within, 506's crew (play-by-play, analyst and the
  later names 506 lists): 506 is kept and the game counts as an agreement (AA's
  parse drops reporters).
- AA's people a strict superset of 506's crew: AA's booth wins.
- Otherwise the newer page wins: AA's `article:modified_time` (else the manifest save
  or fetch time) against the 506 page's save time. A tie or a missing time keeps 506.
  Each superset or newer-page case writes a review row (person ids only).

AA's first analyst fills `analyst_person_id`; any further analysts join the
unlabelled crew entries, as 506's third and later names do. A booth comes whole
from one page: when AA's booth wins, none of 506's names stay; when AA fills a game
with no 506 booth, 506's later names (if any resolved) stay.

A booth is used only when every name resolves through people.csv: the NFL build
never registers people itself, so an unknown name is counted and reported for
`booth-review nfl people`, and the game keeps its 506 crew until it is registered.
Matching uses the team pair and the game date (the week when nflverse has no date
yet); a booth that matches no game or several is counted, never guessed, and a game two
lines match is dropped (whether or not their names resolve). Counts and review
rows never carry page text or names.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal, Protocol

import polars as pl

from booth_review.nfl.teams import NflTeamResolver
from booth_review.people.registry import PeopleRegistry
from booth_review.sources.aa.crews import ParsedCrews

NFL_AA_SOURCE = "aa"
#: Team-crosswalk source for AA's names; it falls back to the shared "any" rows.
AA_TEAM_SOURCE = "aa"

CrewStatus = Literal["aa_filled", "agrees", "superset", "aa_won", "s506_won"]

COUNT_KEYS: tuple[str, ...] = (
    "aa_booths",
    "aa_matched",
    "aa_unresolved_team",
    "aa_no_game",
    "aa_ambiguous",
    "aa_duplicate",
    "aa_unresolved_names",
    "aa_filled",
    "aa_agrees",
    "aa_superset",
    "aa_won",
    "aa_s506_won",
)


@dataclass(frozen=True)
class NflAaPage:
    """One cached AA NFL post and the time compared against 506."""

    season: int
    week: int
    parsed: ParsedCrews
    aa_time: datetime | None


class GameKey(Protocol):
    @property
    def game_id(self) -> str: ...
    @property
    def season(self) -> int: ...
    @property
    def week(self) -> int: ...
    @property
    def gameday(self) -> date | None: ...
    @property
    def home_team(self) -> str: ...
    @property
    def away_team(self) -> str: ...


@dataclass(frozen=True)
class AaGameCrew:
    """An AA booth matched to one game, every name resolved to a person id."""

    game_id: str
    pbp_person_id: str
    analyst_person_ids: tuple[str, ...]
    source_url: str
    aa_time: datetime | None
    pointer: str


@dataclass
class AaMatch:
    crews: dict[str, AaGameCrew] = field(default_factory=dict)
    counts: Counter[str] = field(default_factory=Counter)
    #: Names with no person yet, for `booth-review nfl people` (never logged).
    unresolved_names: Counter[str] = field(default_factory=Counter)


def match_aa_booths(
    pages: Iterable[NflAaPage],
    games: Sequence[GameKey],
    teams: NflTeamResolver,
    people: PeopleRegistry,
) -> AaMatch:
    """Each AA booth's game and resolved people (see module docstring)."""
    result = AaMatch()
    index: dict[tuple[int, frozenset[str]], list[GameKey]] = {}
    for game in games:
        home = teams.resolve("nflverse", game.home_team, game.season).franchise_id
        away = teams.resolve("nflverse", game.away_team, game.season).franchise_id
        if home is not None and away is not None:
            index.setdefault((game.season, frozenset((home, away))), []).append(game)

    # Every line that matched a game, its crew or None when a name did not resolve.
    lines: dict[str, list[AaGameCrew | None]] = {}
    for page in pages:
        for booth in page.parsed.booths:
            result.counts["aa_booths"] += 1
            away = teams.resolve(AA_TEAM_SOURCE, booth.away_raw, page.season).franchise_id
            home = teams.resolve(AA_TEAM_SOURCE, booth.home_raw, page.season).franchise_id
            if away is None or home is None:
                result.counts["aa_unresolved_team"] += 1
                continue
            candidates = index.get((page.season, frozenset((home, away))), [])
            same_day = [g for g in candidates if g.gameday == booth.date_et]
            if not same_day:
                same_day = [g for g in candidates if g.gameday is None and g.week == page.week]
            if not same_day:
                result.counts["aa_no_game"] += 1
                continue
            if len(same_day) > 1:
                result.counts["aa_ambiguous"] += 1
                continue
            game = same_day[0]
            pbp_names = [name for name, role in booth.people if role == "pbp"]
            analyst_names = [name for name, role in booth.people if role == "analyst"]
            ids = {name: people.lookup(name) for name in (*pbp_names, *analyst_names)}
            missing = [name for name, pid in ids.items() if pid is None]
            if missing:
                result.counts["aa_unresolved_names"] += len(missing)
                result.unresolved_names.update(missing)
                lines.setdefault(game.game_id, []).append(None)
                continue
            pbp_id = ids[pbp_names[0]]
            assert pbp_id is not None
            # A second play-by-play voice (rare) joins the analysts' unlabelled tail.
            rest = [ids[n] for n in (*analyst_names, *pbp_names[1:])]
            analysts = tuple(dict.fromkeys(pid for pid in rest if pid and pid != pbp_id))
            lines.setdefault(game.game_id, []).append(
                AaGameCrew(
                    game_id=game.game_id,
                    pbp_person_id=pbp_id,
                    analyst_person_ids=analysts,
                    source_url=booth.source_url,
                    aa_time=page.aa_time,
                    pointer=booth.pointer,
                )
            )
    matched: dict[str, AaGameCrew] = {}
    for game_id, found in lines.items():
        if len(found) > 1:
            # Two lines for one game (an alt-cast, a corrected line): neither is trusted.
            result.counts["aa_duplicate"] += 1
        elif found[0] is not None:
            matched[game_id] = found[0]
    result.crews = matched
    result.counts["aa_matched"] = len(matched)
    return result


@dataclass(frozen=True)
class CrewPick:
    pbp_person_id: str | None
    analyst_person_id: str | None
    sideline_person_ids: tuple[str, ...]
    #: True when AA's booth is the one shipped (source "aa", its post URL).
    from_aa: bool
    status: CrewStatus | None


def coalesce(
    *,
    pbp: str | None,
    analyst: str | None,
    sideline: Sequence[str],
    s506_booth: bool,
    s506_time: datetime | None,
    aa: AaGameCrew | None,
) -> CrewPick:
    """The crew a game ships: 506's, AA's, or 506's when there is no AA booth.

    `s506_booth` is False when the crew did not come from 506 (none listed, or a
    published-lineup fill); a 506 crew with no resolved play-by-play voice counts as
    no booth too.
    """
    keep = CrewPick(pbp, analyst, tuple(sideline), from_aa=False, status=None)
    if aa is None:
        return keep
    aa_people = {aa.pbp_person_id, *aa.analyst_person_ids}
    # A 506 booth needs a resolved play-by-play voice; its people include the later
    # (unlabelled) names, which can be a third booth member.
    has_booth = s506_booth and pbp is not None
    s506_people = {pid for pid in (pbp, analyst, *sideline) if pid is not None}
    status: CrewStatus
    if not has_booth:
        status = "aa_filled"
    elif aa_people <= s506_people:
        return CrewPick(pbp, analyst, tuple(sideline), from_aa=False, status="agrees")
    elif aa_people > s506_people:
        status = "superset"
    elif aa.aa_time is not None and s506_time is not None and aa.aa_time > s506_time:
        status = "aa_won"
    else:
        return CrewPick(pbp, analyst, tuple(sideline), from_aa=False, status="s506_won")
    analysts = aa.analyst_person_ids
    first, rest = (analysts[0], analysts[1:]) if analysts else (None, ())
    # Booths stay whole: 506's names stay only where AA fills a game 506 gave no booth.
    kept = sideline if status == "aa_filled" else ()
    tail = tuple(dict.fromkeys((*rest, *(s for s in kept if s not in aa_people))))
    return CrewPick(aa.pbp_person_id, first, tail, from_aa=True, status=status)


def review_row(
    *,
    season: int,
    week: int,
    game_id: str,
    pick: CrewPick,
    aa: AaGameCrew,
    s506_pbp: str | None,
    s506_analyst: str | None,
    s506_time: datetime | None,
    upcoming: bool = False,
) -> dict[str, object]:
    """A disagreement row for the vault's interim review file (ids only)."""
    return {
        "season": season,
        "week": week,
        "game_id": game_id,
        "upcoming": upcoming,
        "status": pick.status,
        "pointer": aa.pointer,
        "source_url": aa.source_url,
        "s506_pbp_person_id": s506_pbp,
        "s506_analyst_person_id": s506_analyst,
        "aa_person_ids": ";".join((aa.pbp_person_id, *aa.analyst_person_ids)),
        "aa_time": None if aa.aa_time is None else aa.aa_time.isoformat(),
        "s506_time": None if s506_time is None else s506_time.isoformat(),
    }


#: Coalesce outcomes that write a review row.
REVIEWED_STATUSES: frozenset[str] = frozenset({"superset", "aa_won", "s506_won"})


def count_status(
    counts: Counter[str] | dict[str, int], status: CrewStatus | None, *, prefix: str = ""
) -> None:
    key = {
        "aa_filled": "aa_filled",
        "agrees": "aa_agrees",
        "superset": "aa_superset",
        "aa_won": "aa_won",
        "s506_won": "aa_s506_won",
    }
    if status is not None:
        name = prefix + key[status]
        counts[name] = counts.get(name, 0) + 1


def empty_counts() -> Mapping[str, int]:
    return dict.fromkeys(COUNT_KEYS, 0)


def apply_aa_to_games(
    frame: pl.DataFrame,
    match: AaMatch,
    s506_times: Mapping[tuple[int, int], datetime],
) -> tuple[pl.DataFrame, Counter[str], list[dict[str, object]]]:
    """Coalesce AA booths into the played-game frame (after the published-lineup fill).

    A published-lineup row counts as having no 506 booth, so AA's per-game booth
    replaces the season lineup guess.
    """
    counts: Counter[str] = Counter()
    reviews: list[dict[str, object]] = []
    if not match.crews or frame.height == 0:
        return frame, counts, reviews
    schema = frame.schema
    rows = frame.to_dicts()
    for row in rows:
        aa = match.crews.get(str(row["game_id"]))
        if aa is None:
            continue
        season, week = int(row["season"]), int(row["week"])
        s506_time = s506_times.get((season, week))
        pbp, analyst = row["pbp_person_id"], row["analyst_person_id"]
        pick = coalesce(
            pbp=pbp,
            analyst=analyst,
            sideline=row["sideline_person_ids"] or [],
            s506_booth=row["crew_source"] == "506",
            s506_time=s506_time,
            aa=aa,
        )
        count_status(counts, pick.status)
        if pick.status in REVIEWED_STATUSES:
            reviews.append(
                review_row(
                    season=season,
                    week=week,
                    game_id=str(row["game_id"]),
                    pick=pick,
                    aa=aa,
                    s506_pbp=pbp,
                    s506_analyst=analyst,
                    s506_time=s506_time,
                )
            )
        if pick.from_aa:
            row["pbp_person_id"] = pick.pbp_person_id
            row["analyst_person_id"] = pick.analyst_person_id
            row["sideline_person_ids"] = list(pick.sideline_person_ids)
            row["crew_source"] = NFL_AA_SOURCE
            row["crew_source_url"] = aa.source_url
    return pl.DataFrame(rows, schema=schema, orient="row"), counts, reviews
