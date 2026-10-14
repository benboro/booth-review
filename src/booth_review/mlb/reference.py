"""Column contracts and loaders for the MLB reference tables.

Same discipline as the NFL loaders: every table goes through
`read_reference_csv_numbered`, and every error names the file and line only,
never cell content. Loaders never write; people.csv is read-only here.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import get_args

from booth_review.contract.mlb_models import MlbNetworkFamily
from booth_review.errors import ReferenceTableError
from booth_review.nfl.reference import (
    _check_https,
    _check_note,
    _err,
    _opt_int,
    _req_int,
    ranges_overlap,
)
from booth_review.people.registry import PeopleRegistry, load_people
from booth_review.reference import read_reference_csv_numbered
from booth_review.resolve.names import normalize_team

MLB_CLUB_COLUMNS = (
    "club_id",
    "league",
    "division",
    "season_from",
    "season_to",
    "display_name",
    "nickname",
    "note",
)
MLB_TEAM_CROSSWALK_COLUMNS = ("source", "variant", "club_id", "season_from", "season_to", "note")
MLB_NETWORK_COLUMNS = ("source", "variant", "network_id", "family", "note")
MLB_BOOTH_RANK_COLUMNS = ("network", "season", "rank", "pbp", "analyst", "source_url")
MLB_MAP_OVERRIDE_COLUMNS = ("season", "round", "league", "network_id", "source_url")
MLB_CREW_OVERRIDE_COLUMNS = (
    "season",
    "game_date",
    "away_club",
    "home_club",
    "game_number",
    "network_id",
    "pbp",
    "analyst_1",
    "analyst_2",
    "source_url",
    "note",
)

MLB_TEAM_SOURCES = frozenset({"506", "ratingsref", "retrosheet", "relay", "wikipedia", "any"})
MLB_NETWORK_SOURCES = frozenset({"506", "ratingsref", "retrosheet", "relay", "wikipedia"})
MLB_ROUND_IDS = ("wild_card", "division", "lcs", "world_series", "tiebreak")
MLB_LEAGUES = ("AL", "NL")
# A family is the corporate group (FS1 is fox, truTV is tbs), so a Wikipedia crew listed
# for a network family matches its sister channels; the site contract owns the set.
MLB_NETWORK_FAMILIES = frozenset(get_args(MlbNetworkFamily))

_NETWORK_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_CLUB_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")


def _season_range(
    path: Path, line_no: int, raw: Mapping[str, str]
) -> tuple[int | None, int | None]:
    season_from = _opt_int(path, line_no, raw["season_from"], "season_from")
    season_to = _opt_int(path, line_no, raw["season_to"], "season_to")
    if season_from is not None and season_to is not None and season_to < season_from:
        raise _err(path, line_no, "season_to precedes season_from")
    return season_from, season_to


def normalize_mlb_variant(text: str) -> str:
    return normalize_team(text)


# -- clubs --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class MlbClubName:
    season_from: int | None
    season_to: int | None
    league: str
    division: str
    display_name: str
    nickname: str


@dataclass(frozen=True)
class MlbClubs:
    names: Mapping[str, tuple[MlbClubName, ...]]

    def __contains__(self, club_id: object) -> bool:
        return club_id in self.names

    def ids(self) -> frozenset[str]:
        return frozenset(self.names)


def load_mlb_clubs(reference_dir: Path) -> MlbClubs:
    path = reference_dir / "mlb_clubs.csv"
    raw_rows = read_reference_csv_numbered(path, MLB_CLUB_COLUMNS, required=True)
    names: dict[str, list[MlbClubName]] = {}
    for line_no, raw in raw_rows:
        cid = raw["club_id"]
        if not _CLUB_ID_RE.fullmatch(cid):
            raise _err(path, line_no, "club_id must be a lowercase slug")
        if raw["league"] not in MLB_LEAGUES:
            raise _err(path, line_no, "league must be AL or NL")
        if not raw["division"]:
            raise _err(path, line_no, "division is required")
        if not raw["display_name"]:
            raise _err(path, line_no, "display_name is required")
        season_from, season_to = _season_range(path, line_no, raw)
        _check_note(path, line_no, raw["note"])
        for other in names.get(cid, ()):
            if ranges_overlap(season_from, season_to, other.season_from, other.season_to):
                raise _err(path, line_no, "display-name season ranges overlap for one club")
        names.setdefault(cid, []).append(
            MlbClubName(
                season_from,
                season_to,
                raw["league"],
                raw["division"],
                raw["display_name"],
                raw["nickname"],
            )
        )
    return MlbClubs({cid: tuple(v) for cid, v in names.items()})


# -- team crosswalk -----------------------------------------------------------------------------


@dataclass(frozen=True)
class MlbTeamCrosswalkRow:
    source: str
    variant: str
    club_id: str
    season_from: int | None
    season_to: int | None
    note: str


def load_mlb_team_crosswalk(reference_dir: Path) -> list[MlbTeamCrosswalkRow]:
    path = reference_dir / "mlb_team_crosswalk.csv"
    raw_rows = read_reference_csv_numbered(path, MLB_TEAM_CROSSWALK_COLUMNS, required=True)
    clubs = load_mlb_clubs(reference_dir)
    rows: list[MlbTeamCrosswalkRow] = []
    seen: dict[tuple[str, str], list[tuple[int | None, int | None, str]]] = {}
    for line_no, raw in raw_rows:
        if raw["source"] not in MLB_TEAM_SOURCES:
            raise _err(path, line_no, "invalid source")
        if not raw["variant"]:
            raise _err(path, line_no, "variant is required")
        cid = raw["club_id"]
        if cid not in clubs:
            raise _err(path, line_no, "club_id is not in mlb_clubs.csv")
        season_from, season_to = _season_range(path, line_no, raw)
        _check_note(path, line_no, raw["note"])
        key = (raw["source"], normalize_mlb_variant(raw["variant"]))
        for o_from, o_to, o_cid in seen.get(key, ()):
            if o_cid != cid and ranges_overlap(season_from, season_to, o_from, o_to):
                raise _err(path, line_no, "variant maps to two clubs over overlapping seasons")
        seen.setdefault(key, []).append((season_from, season_to, cid))
        rows.append(
            MlbTeamCrosswalkRow(
                raw["source"], raw["variant"], cid, season_from, season_to, raw["note"]
            )
        )
    return rows


# -- networks -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class MlbNetworkRow:
    source: str
    variant: str
    network_id: str
    family: str
    note: str


def load_mlb_networks(reference_dir: Path) -> list[MlbNetworkRow]:
    path = reference_dir / "mlb_networks.csv"
    raw_rows = read_reference_csv_numbered(path, MLB_NETWORK_COLUMNS, required=True)
    rows: list[MlbNetworkRow] = []
    seen: dict[tuple[str, str], str] = {}
    family_of: dict[str, str] = {}
    for line_no, raw in raw_rows:
        if raw["source"] not in MLB_NETWORK_SOURCES:
            raise _err(path, line_no, "invalid source")
        if not _NETWORK_ID_RE.fullmatch(raw["network_id"]):
            raise _err(path, line_no, "network_id must be a lowercase slug")
        if raw["family"] not in MLB_NETWORK_FAMILIES:
            raise _err(path, line_no, "invalid family")
        if not raw["variant"]:
            raise _err(path, line_no, "variant is required")
        _check_note(path, line_no, raw["note"])
        if family_of.setdefault(raw["network_id"], raw["family"]) != raw["family"]:
            raise _err(path, line_no, "network_id has two families")
        key = (raw["source"], " ".join(raw["variant"].casefold().split()))
        if key in seen and seen[key] != raw["network_id"]:
            raise _err(path, line_no, "variant maps to two networks")
        seen[key] = raw["network_id"]
        rows.append(
            MlbNetworkRow(
                raw["source"], raw["variant"], raw["network_id"], raw["family"], raw["note"]
            )
        )
    return rows


# -- booth ranks --------------------------------------------------------------------------------


@dataclass(frozen=True)
class MlbBoothRank:
    """One cited booth. A person id is None when the name is not in people.csv yet."""

    network: str
    season: int
    rank: int
    pbp_name: str
    analyst_name: str
    pbp_person_id: str | None
    analyst_person_id: str | None
    source_url: str


@dataclass(frozen=True)
class UnresolvedRankName:
    file: str
    line: int
    column: str
    raw_name: str


@dataclass(frozen=True)
class MlbBoothRanks:
    rows: tuple[MlbBoothRank, ...]
    unresolved: tuple[UnresolvedRankName, ...]

    def booths(self, network: str, season: int) -> tuple[MlbBoothRank, ...]:
        return tuple(r for r in self.rows if r.network == network and r.season == season)


def load_mlb_booth_ranks(path: Path, people: PeopleRegistry) -> MlbBoothRanks:
    """Structure errors raise; a name missing from people.csv becomes a review row."""
    raw_rows = read_reference_csv_numbered(path, MLB_BOOTH_RANK_COLUMNS, required=False)
    rows: list[tuple[int, MlbBoothRank]] = []
    unresolved: list[UnresolvedRankName] = []
    seen: set[tuple[str, int, int]] = set()
    for line_no, raw in raw_rows:
        network = raw["network"]
        if not _NETWORK_ID_RE.fullmatch(network):
            raise _err(path, line_no, "network must be a lowercase slug")
        season = _req_int(path, line_no, raw["season"], "season")
        rank = _req_int(path, line_no, raw["rank"], "rank")
        if rank < 1:
            raise _err(path, line_no, "rank must be at least 1")
        _check_https(path, line_no, raw["source_url"])
        if (network, season, rank) in seen:
            raise _err(path, line_no, "duplicate (network, season, rank)")
        seen.add((network, season, rank))
        ids: dict[str, str | None] = {}
        for column in ("pbp", "analyst"):
            name = raw[column]
            if not name:
                raise _err(path, line_no, f"{column} is required")
            pid = people.lookup(name)
            ids[column] = pid
            if pid is None:
                unresolved.append(UnresolvedRankName(path.name, line_no, column, name))
        rows.append(
            (
                line_no,
                MlbBoothRank(
                    network,
                    season,
                    rank,
                    raw["pbp"],
                    raw["analyst"],
                    ids["pbp"],
                    ids["analyst"],
                    raw["source_url"],
                ),
            )
        )
    by_key: dict[tuple[str, int], list[tuple[int, MlbBoothRank]]] = {}
    for line_no, r in rows:
        by_key.setdefault((r.network, r.season), []).append((line_no, r))
    for group in by_key.values():
        for expected, (line_no, r) in enumerate(sorted(group, key=lambda lr: lr[1].rank), start=1):
            if r.rank != expected:
                raise _err(path, line_no, "ranks must run 1..n")
    ordered = sorted(rows, key=lambda lr: (lr[1].network, lr[1].season, lr[1].rank))
    return MlbBoothRanks(tuple(r for _, r in ordered), tuple(unresolved))


# -- postseason map overrides -------------------------------------------------------------------


@dataclass(frozen=True)
class MlbMapOverride:
    season: int
    round: str
    league: str
    network_id: str
    source_url: str


def load_mlb_postseason_map_overrides(reference_dir: Path) -> list[MlbMapOverride]:
    path = reference_dir / "mlb_postseason_map_overrides.csv"
    raw_rows = read_reference_csv_numbered(path, MLB_MAP_OVERRIDE_COLUMNS, required=True)
    out: list[MlbMapOverride] = []
    seen: set[tuple[int, str, str]] = set()
    for line_no, raw in raw_rows:
        season = _req_int(path, line_no, raw["season"], "season")
        if raw["round"] not in MLB_ROUND_IDS:
            raise _err(path, line_no, "invalid round")
        if raw["league"] not in ("AL", "NL", ""):
            raise _err(path, line_no, "league must be AL, NL or empty")
        if not _NETWORK_ID_RE.fullmatch(raw["network_id"]):
            raise _err(path, line_no, "network_id must be a lowercase slug")
        _check_https(path, line_no, raw["source_url"])
        key = (season, raw["round"], raw["league"])
        if key in seen:
            raise _err(path, line_no, "duplicate (season, round, league)")
        seen.add(key)
        out.append(
            MlbMapOverride(
                season, raw["round"], raw["league"], raw["network_id"], raw["source_url"]
            )
        )
    return out


# -- crew overrides (optional) ------------------------------------------------------------------


@dataclass(frozen=True)
class MlbCrewOverride:
    season: int
    game_date: str
    away_club: str
    home_club: str
    game_number: int
    network_id: str
    pbp: str
    analyst_1: str
    analyst_2: str
    source_url: str
    note: str


def load_mlb_crew_overrides(path: Path) -> list[MlbCrewOverride]:
    """Game-level crew corrections (D-10 first tier). A missing file is empty."""
    raw_rows = read_reference_csv_numbered(path, MLB_CREW_OVERRIDE_COLUMNS, required=False)
    out: list[MlbCrewOverride] = []
    for line_no, raw in raw_rows:
        season = _req_int(path, line_no, raw["season"], "season")
        game_number = _req_int(path, line_no, raw["game_number"], "game_number")
        if not raw["game_date"] or not raw["away_club"] or not raw["home_club"]:
            raise _err(path, line_no, "game_date, away_club and home_club are required")
        if not _NETWORK_ID_RE.fullmatch(raw["network_id"]):
            raise _err(path, line_no, "network_id must be a lowercase slug")
        _check_https(path, line_no, raw["source_url"])
        _check_note(path, line_no, raw["note"])
        out.append(
            MlbCrewOverride(
                season,
                raw["game_date"],
                raw["away_club"],
                raw["home_club"],
                game_number,
                raw["network_id"],
                raw["pbp"],
                raw["analyst_1"],
                raw["analyst_2"],
                raw["source_url"],
                raw["note"],
            )
        )
    return out


# -- bundle -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class MlbReference:
    clubs: MlbClubs
    crosswalk: tuple[MlbTeamCrosswalkRow, ...]
    networks: tuple[MlbNetworkRow, ...]
    booth_ranks: MlbBoothRanks
    map_overrides: tuple[MlbMapOverride, ...]
    crew_overrides: tuple[MlbCrewOverride, ...]
    people: PeopleRegistry


def load_mlb_reference(reference_dir: Path) -> MlbReference:
    people = load_people(reference_dir)
    ranks_path = reference_dir / "mlb_booth_ranks.csv"
    if not ranks_path.is_file():
        raise ReferenceTableError(f"{ranks_path.name}: missing required reference table")
    return MlbReference(
        clubs=load_mlb_clubs(reference_dir),
        crosswalk=tuple(load_mlb_team_crosswalk(reference_dir)),
        networks=tuple(load_mlb_networks(reference_dir)),
        booth_ranks=load_mlb_booth_ranks(ranks_path, people),
        map_overrides=tuple(load_mlb_postseason_map_overrides(reference_dir)),
        crew_overrides=tuple(load_mlb_crew_overrides(reference_dir / "mlb_crew_overrides.csv")),
        people=people,
    )
