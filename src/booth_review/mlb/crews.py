"""MLB crew assignment with the D-10 precedence and a disagreement report.

Precedence per telecast: hand-confirmed override, then 506, then the relay blog,
then the Wikipedia broadcaster lists (postseason only, D-19). Every source that
names a crew is resolved to person ids so two sources can be compared; a game
where two sources both name a person for the play-by-play or first-analyst slot
and the ids differ becomes a `CrewDisagreement` row. The winner is still the
highest-precedence source, but the disagreement is never silent (D-10).

A crew is named only with a play-by-play person and at least one analyst. A
"(local simulcast)" telecast takes no crew and sits outside every crew
denominator. A booth is network + season + play-by-play person; analyst changes
do not split it, and a one-off voice is flagged fill_in.

Names resolve through the shared people table; unresolved names become
`PeopleReview` entries (and null ids) and nothing here ever writes the people
table. Counts and reviews carry ids and labels, never source text beyond the
unresolved announcer names the people review list exists to hold.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final

import polars as pl

from booth_review.build.io import write_review_csv
from booth_review.mlb.inputs import Review
from booth_review.mlb.listings import ROUND_BY_LABEL, game_key
from booth_review.mlb.reference import MlbCrewOverride, MlbReference
from booth_review.mlb.teams import MlbNetworkResolver, MlbTeamResolver
from booth_review.people.normalize import is_placeholder
from booth_review.people.registry import PeopleRegistry
from booth_review.sources.wikipedia.mlb_parser import ListCrew

__all__ = [
    "CREW_COLUMNS",
    "CREW_DISAGREEMENT_COLUMNS",
    "CREW_SOURCES",
    "FILL_IN_MAX_GAMES",
    "CrewDisagreement",
    "PeopleReview",
    "assign_crews",
    "booth_key",
    "modal_analysts",
    "people_review_names",
    "write_crew_disagreements",
]

#: Precedence, highest first (D-10, D-19).
CREW_SOURCES = ("override", "506", "relay", "wikipedia")

#: A play-by-play voice with at most this many games on a network in a season,
#: while another voice on that network has more, is a fill-in booth.
FILL_IN_MAX_GAMES: Final = 1

CREW_COLUMNS: Final = (
    "pbp_person_id",
    "analyst_person_ids",
    "crew_source",
    "crew_source_url",
    "press_url",
    "press_name",
    "crew_named",
    "crew_in_scope",
    "booth_key",
    "fill_in",
)
CREW_DISAGREEMENT_COLUMNS: Final = (
    "game_key",
    "network_id",
    "source_a",
    "source_b",
    "field",
    "person_id_a",
    "person_id_b",
)

_GAMES_LIST = re.compile(r"\bgames?\b", re.I)
_GAME_SPAN = re.compile(r"(\d+)(?:\s*[-\N{EN DASH}\N{EM DASH}]\s*(\d+))?")


@dataclass(frozen=True)
class CrewDisagreement:
    """Two sources name different people for one slot of one telecast (person ids only)."""

    game_key: str
    network_id: str
    source_a: str
    source_b: str
    field: str
    person_id_a: str
    person_id_b: str


@dataclass(frozen=True)
class PeopleReview:
    """An announcer name no people-table variant covers, with its occurrence count."""

    raw_name: str
    count: int


def people_review_names(reviews: Iterable[PeopleReview]) -> list[str]:
    """One entry per occurrence, the shape `register_mlb_people` takes as crew_names."""
    return [r.raw_name for r in reviews for _ in range(r.count)]


def modal_analysts(per_game: Sequence[Sequence[str] | None]) -> list[str]:
    """A booth's analyst label: the most frequent first analyst across its games.

    Ties go to the analyst of the earliest game, then the smaller id. The returned list is
    the most frequent full analyst list among games led by that analyst (same tie-breaks).
    """
    games = [tuple(a) for a in per_game if a]
    if not games:
        return []
    firsts = Counter(g[0] for g in games)
    first_seen: dict[str, int] = {}
    for i, g in enumerate(games):
        first_seen.setdefault(g[0], i)
    lead = min(firsts, key=lambda a: (-firsts[a], first_seen[a], a))
    led = [g for g in games if g[0] == lead]
    tuples = Counter(led)
    order: dict[tuple[str, ...], int] = {}
    for i, g in enumerate(led):
        order.setdefault(g, i)
    best = min(tuples, key=lambda t: (-tuples[t], order[t], t))
    return list(best)


def booth_key(network_id: str, season: int, pbp_person_id: str | None) -> str | None:
    """Network + season + play-by-play person; analyst changes never split a booth."""
    if pbp_person_id is None:
        return None
    return f"{network_id}|{season}|{pbp_person_id}"


def write_crew_disagreements(path: Path, rows: Iterable[CrewDisagreement]) -> None:
    """`interim/review_mlb_crew_disagreements.csv`: ids only, sorted for stable output."""
    ordered = sorted(
        rows, key=lambda r: (r.game_key, r.network_id, r.source_a, r.source_b, r.field)
    )
    write_review_csv(
        path,
        CREW_DISAGREEMENT_COLUMNS,
        [
            {
                "game_key": r.game_key,
                "network_id": r.network_id,
                "source_a": r.source_a,
                "source_b": r.source_b,
                "field": r.field,
                "person_id_a": r.person_id_a,
                "person_id_b": r.person_id_b,
            }
            for r in ordered
        ],
    )


# -- one source's crew -------------------------------------------------------------------------


@dataclass(frozen=True)
class _Candidate:
    source: str
    pbp_name: str
    analyst_names: tuple[str, ...]
    url: str | None = None
    press_url: str | None = None
    press_name: str | None = None


@dataclass(frozen=True)
class _Resolved:
    candidate: _Candidate
    pbp_id: str | None
    analyst1_id: str | None
    analyst_ids: tuple[str, ...]


def _real(name: str) -> bool:
    return bool(name.strip()) and not is_placeholder(name)


def _resolve(
    candidate: _Candidate, registry: PeopleRegistry, unresolved: Counter[str]
) -> _Resolved:
    def look(name: str) -> str | None:
        if not _real(name):
            return None
        found = registry.lookup(name)
        if found is None:
            unresolved[name] += 1
        return found

    pbp_id = look(candidate.pbp_name)
    ids = [look(n) for n in candidate.analyst_names]
    return _Resolved(
        candidate,
        pbp_id,
        ids[0] if ids else None,
        tuple(i for i in ids if i is not None),
    )


def _disagreements(
    key: str, network_id: str, resolved: Sequence[_Resolved]
) -> list[CrewDisagreement]:
    out: list[CrewDisagreement] = []
    for i, a in enumerate(resolved):
        for b in resolved[i + 1 :]:
            for field, ida, idb in (
                ("pbp", a.pbp_id, b.pbp_id),
                ("analyst_1", a.analyst1_id, b.analyst1_id),
            ):
                if ida is not None and idb is not None and ida != idb:
                    out.append(
                        CrewDisagreement(
                            key, network_id, a.candidate.source, b.candidate.source, field, ida, idb
                        )
                    )
    return out


# -- source indexes ----------------------------------------------------------------------------


def _override_candidates(overrides: Iterable[MlbCrewOverride]) -> dict[tuple[str, str], _Candidate]:
    out: dict[tuple[str, str], _Candidate] = {}
    for o in overrides:
        key = game_key(date.fromisoformat(o.game_date), o.away_club, o.home_club, o.game_number)
        names = tuple(n for n in (o.analyst_1, o.analyst_2) if n.strip())
        out[(key, o.network_id)] = _Candidate("override", o.pbp, names, url=o.source_url)
    return out


def _relay_candidates(
    rows: Iterable[Mapping[str, str]], ref: MlbReference, reviews: list[Review]
) -> dict[tuple[str, str], _Candidate]:
    teams = MlbTeamResolver.from_reference(ref)
    networks = MlbNetworkResolver.from_reference(ref)
    known = {n.network_id for n in ref.networks}
    out: dict[tuple[str, str], _Candidate] = {}
    for row in rows:
        season = int(row["season"])
        away = teams.resolve("relay", row["away_club"], season).club_id
        home = teams.resolve("relay", row["home_club"], season).club_id
        if away is None or home is None:
            reviews.append(Review("relay", "unresolved_club", 1, str(season)))
            continue
        network = networks.resolve("relay", row["network_id"]).network_id
        if network is None and row["network_id"] in known:
            network = row["network_id"]
        if network is None:
            reviews.append(Review("relay", "unresolved_network", 1, str(season)))
            continue
        key = game_key(date.fromisoformat(row["game_date"]), away, home, int(row["game_number"]))
        names = tuple(n for n in (row["analyst_1"], row["analyst_2"]) if n.strip())
        out[(key, network)] = _Candidate(
            "relay",
            row["pbp"],
            names,
            url=row["post_url"],
            press_url=row["press_url"] or None,
            press_name=row["press_name"] or None,
        )
    return out


def _list_index(
    crews: Iterable[ListCrew], networks: MlbNetworkResolver, reviews: list[Review]
) -> dict[tuple[int, str, str], list[ListCrew]]:
    index: dict[tuple[int, str, str], list[ListCrew]] = {}
    for crew in crews:
        round_id = ROUND_BY_LABEL.get(crew.round)
        family = networks.resolve("wikipedia", crew.network_raw).family
        if round_id is None or family is None:
            reviews.append(Review("wikipedia", "list_unresolved", 1, f"{crew.season}/{crew.round}"))
            continue
        index.setdefault((crew.season, round_id, family), []).append(crew)
    return index


def _in_games(label: str | None, series_game: int | None) -> bool:
    """True when a per-game list row's "games N-M" note covers `series_game`."""
    if label is None or series_game is None:
        return False
    for m in _GAMES_LIST.finditer(label):
        for lo_text, hi_text in _GAME_SPAN.findall(label[m.end() :]):
            lo = int(lo_text)
            hi = int(hi_text) if hi_text else lo
            if lo <= series_game <= hi:
                return True
    return False


def _list_candidate(
    index: Mapping[tuple[int, str, str], list[ListCrew]],
    *,
    season: int,
    round_id: str,
    family: str,
    league: str | None,
    series_game: int | None,
    reviews: list[Review],
) -> _Candidate | None:
    found = [
        c
        for c in index.get((season, round_id, family), [])
        if c.league is None or (league is not None and c.league == league)
    ]
    per_game = [
        c for c in found if c.scope == "per_game" and _in_games(c.series_label, series_game)
    ]
    pool = per_game or [c for c in found if c.scope == "per_series"]
    distinct = {(c.pbp_raw, c.analysts_raw): c for c in pool}
    if not distinct:
        return None
    if len(distinct) > 1:
        reviews.append(Review("wikipedia", "ambiguous_list_crew", 1, f"{season}/{round_id}"))
        return None
    crew = next(iter(distinct.values()))
    return _Candidate("wikipedia", crew.pbp_raw, crew.analysts_raw, url=crew.source_url)


# -- assignment --------------------------------------------------------------------------------


def _schema() -> dict[str, pl.DataType | type[pl.DataType]]:
    return {
        "pbp_person_id": pl.String,
        "analyst_person_ids": pl.List(pl.String),
        "crew_source": pl.String,
        "crew_source_url": pl.String,
        "press_url": pl.String,
        "press_name": pl.String,
        "crew_named": pl.Boolean,
        "crew_in_scope": pl.Boolean,
        "booth_key": pl.String,
        "fill_in": pl.Boolean,
    }


def assign_crews(
    telecasts: pl.DataFrame,
    games: pl.DataFrame,
    relay_rows: Iterable[Mapping[str, str]],
    list_crews: Iterable[ListCrew],
    overrides: Iterable[MlbCrewOverride],
    ref: MlbReference,
    reviews: list[Review] | None = None,
) -> tuple[pl.DataFrame, list[CrewDisagreement], list[PeopleReview]]:
    """Add the crew columns (`CREW_COLUMNS`) to `telecasts`.

    `reviews`, when given, receives one `Review` per dropped relay or list row.
    """
    sink: list[Review] = reviews if reviews is not None else []
    networks = MlbNetworkResolver.from_reference(ref)
    override_map = _override_candidates(overrides)
    relay_map = _relay_candidates(relay_rows, ref, sink)
    list_map = _list_index(list_crews, networks, sink)
    game_info: dict[str, tuple[str | None, int | None]] = {}
    if games.height:
        for g in games.select("game_key", "series_league", "series_game").iter_rows():
            game_info[g[0]] = (g[1], g[2])

    unresolved: Counter[str] = Counter()
    disagreements: list[CrewDisagreement] = []
    used_relay: set[tuple[str, str]] = set()
    out: dict[str, list[object]] = {name: [] for name in CREW_COLUMNS}

    for row in telecasts.iter_rows(named=True):
        key = str(row["game_key"])
        network = str(row["network_id"])
        season = int(row["season"])
        in_scope = not bool(row["local_simulcast"])
        pbp_id: str | None = None
        analyst_ids: list[str] = []
        source: str | None = None
        url: str | None = None
        press_url: str | None = None
        press_name: str | None = None
        if in_scope:
            candidates: list[_Candidate] = []
            if (key, network) in override_map:
                candidates.append(override_map[(key, network)])
            names = [str(n) for n in (row["crew_names"] or [])]
            if names and _real(names[0]):
                candidates.append(_Candidate("506", names[0], tuple(names[1:])))
            if (key, network) in relay_map:
                candidates.append(relay_map[(key, network)])
                used_relay.add((key, network))
            round_id = row["round"]
            family = row["family"]
            if round_id and family:
                league, series_game = game_info.get(key, (None, None))
                listed = _list_candidate(
                    list_map,
                    season=season,
                    round_id=str(round_id),
                    family=str(family),
                    league=league,
                    series_game=series_game if series_game is not None else row["series_game"],
                    reviews=sink,
                )
                if listed is not None:
                    candidates.append(listed)
            resolved = [_resolve(c, ref.people, unresolved) for c in candidates]
            disagreements.extend(_disagreements(key, network, resolved))
            if resolved:
                # A source that names no complete crew must not block a lower one that does.
                complete = [r for r in resolved if r.pbp_id is not None and r.analyst_ids]
                win = complete[0] if complete else resolved[0]
                pbp_id = win.pbp_id
                analyst_ids = list(win.analyst_ids)
                source = win.candidate.source
                url = win.candidate.url
                press_url = win.candidate.press_url
                press_name = win.candidate.press_name
        out["pbp_person_id"].append(pbp_id)
        out["analyst_person_ids"].append(analyst_ids)
        out["crew_source"].append(source)
        out["crew_source_url"].append(url)
        out["press_url"].append(press_url)
        out["press_name"].append(press_name)
        out["crew_named"].append(pbp_id is not None and len(analyst_ids) > 0)
        out["crew_in_scope"].append(in_scope)
        out["booth_key"].append(booth_key(network, season, pbp_id) if in_scope else None)
        out["fill_in"].append(False)

    for slot in set(relay_map) - used_relay:
        sink.append(Review("relay", "no_telecast", 1, slot[0]))

    schema = _schema()
    frame = telecasts.with_columns(
        [pl.Series(name, values, dtype=schema[name]) for name, values in out.items()]
    )
    frame = _flag_fill_ins(frame)
    people = [PeopleReview(n, c) for n, c in sorted(unresolved.items())]
    return frame, disagreements, people


def _flag_fill_ins(frame: pl.DataFrame) -> pl.DataFrame:
    """Flag voices with at most FILL_IN_MAX_GAMES games where the network has a regular voice."""
    if not frame.height:
        return frame
    counts = (
        frame.filter(pl.col("booth_key").is_not_null())
        .group_by("network_id", "season", "booth_key")
        .agg(pl.col("game_key").n_unique().alias("_n"))
        .with_columns(pl.col("_n").max().over("network_id", "season").alias("_top"))
        .with_columns(
            ((pl.col("_n") <= FILL_IN_MAX_GAMES) & (pl.col("_top") > FILL_IN_MAX_GAMES)).alias(
                "_fill"
            )
        )
        .select("booth_key", "network_id", "season", "_fill")
    )
    joined = frame.drop("fill_in").join(
        counts.select("booth_key", "network_id", "season", "_fill"),
        on=["booth_key", "network_id", "season"],
        how="left",
    )
    order = [c for c in frame.columns if c != "fill_in"]
    return joined.with_columns(pl.col("_fill").fill_null(False).alias("fill_in")).select(
        [*order, "fill_in"]
    )
