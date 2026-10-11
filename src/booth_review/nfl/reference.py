"""Column contracts and loaders for the seven NFL reference tables (D-02, D-14, D-16).

Every table is read through `reference.read_reference_csv_numbered`, so a wrong
header, an extra cell or a formula-like cell is rejected, and every error here
names the file and line only, never cell content.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from booth_review.errors import ReferenceTableError
from booth_review.people.registry import load_people
from booth_review.reference import SLUG_PATTERN, read_reference_csv_numbered
from booth_review.resolve.names import normalize_team

NFL_FRANCHISE_COLUMNS = (
    "franchise_id",
    "season_from",
    "season_to",
    "display_name",
    "nickname",
    "note",
)
NFL_TEAM_CROSSWALK_COLUMNS = (
    "source",
    "variant",
    "franchise_id",
    "season_from",
    "season_to",
    "note",
)
NFL_STADIUM_COLUMNS = ("stadium_id", "stadium", "country", "source_url", "note")
NFL_STADIUM_OVERRIDE_COLUMNS = ("nflverse_game_id", "stadium_id", "source_url", "note")
NFL_NETWORK_COLUMNS = ("source", "variant", "network_id", "note")
NFL_LEAD_BOOTH_OVERRIDE_COLUMNS = ("season", "person_id", "reason", "source_url")
NFL_WEEK_OVERRIDE_COLUMNS = (
    "season",
    "week",
    "network",
    "nflverse_game_id",
    "source_url",
    "reason",
)

NFL_TEAM_SOURCES = ("nflverse", "sports506", "ratingsref", "wikipedia", "any")
NFL_NETWORK_SOURCES = ("nflverse", "sports506", "ratingsref", "wikipedia")
NFL_NETWORK_IDS = frozenset(
    {
        "cbs",
        "fox",
        "nbc",
        "espn",
        "abc",
        "espn2",
        "nfln",
        "prime",
        "netflix",
        "youtube",
        "peacock",
        "espn_plus",
        "espn_deportes",
        "yahoo",  # 2015 London game streamed only on Yahoo; 2017 London game on Yahoo/Go90
    }
)
NFL_LEAD_BOOTH_REASONS = ("inference-tie", "inference-wrong", "close-call")
NFL_WEEK_OVERRIDE_REASONS = ("agotw-text-source", "cbs-national-text-source")
NFL_WEEK_OVERRIDE_NETWORKS = ("fox", "cbs")

_MAX_NOTE_LEN = 120
_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")


def _err(path: Path, line_no: int, message: str) -> ReferenceTableError:
    return ReferenceTableError(f"{path.name}: line {line_no}: {message}")


def _opt_int(path: Path, line_no: int, raw: str, field: str) -> int | None:
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        raise _err(path, line_no, f"invalid {field}") from None


def _req_int(path: Path, line_no: int, raw: str, field: str) -> int:
    value = _opt_int(path, line_no, raw, field)
    if value is None:
        raise _err(path, line_no, f"{field} is required")
    return value


def _check_note(path: Path, line_no: int, note: str) -> None:
    if len(note) > _MAX_NOTE_LEN:
        raise _err(path, line_no, f"note exceeds {_MAX_NOTE_LEN} characters")


def _check_https(path: Path, line_no: int, url: str) -> None:
    if not url.startswith("https://") or len(url) <= len("https://"):
        raise _err(path, line_no, "source_url must be an https URL")


_OPEN_LOW = -(10**9)
_OPEN_HIGH = 10**9


def ranges_overlap(
    a_from: int | None, a_to: int | None, b_from: int | None, b_to: int | None
) -> bool:
    """True when two inclusive season ranges (None = open-ended) share a season."""
    lo = max(
        a_from if a_from is not None else _OPEN_LOW, b_from if b_from is not None else _OPEN_LOW
    )
    hi = min(a_to if a_to is not None else _OPEN_HIGH, b_to if b_to is not None else _OPEN_HIGH)
    return lo <= hi


# -- franchises ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class FranchiseName:
    season_from: int | None
    season_to: int | None
    display_name: str
    nickname: str


@dataclass(frozen=True)
class NflFranchises:
    names: Mapping[str, tuple[FranchiseName, ...]]

    def __contains__(self, franchise_id: object) -> bool:
        return franchise_id in self.names

    def ids(self) -> frozenset[str]:
        return frozenset(self.names)


def load_nfl_franchises(reference_dir: Path) -> NflFranchises:
    path = reference_dir / "nfl_franchises.csv"
    raw_rows = read_reference_csv_numbered(path, NFL_FRANCHISE_COLUMNS, required=True)
    names: dict[str, list[FranchiseName]] = {}
    for line_no, raw in raw_rows:
        fid = raw["franchise_id"]
        if not SLUG_PATTERN.fullmatch(fid):
            raise _err(path, line_no, "franchise_id must be a lowercase kebab slug")
        if not raw["display_name"]:
            raise _err(path, line_no, "display_name is required")
        season_from = _opt_int(path, line_no, raw["season_from"], "season_from")
        season_to = _opt_int(path, line_no, raw["season_to"], "season_to")
        if season_from is not None and season_to is not None and season_to < season_from:
            raise _err(path, line_no, "season_to precedes season_from")
        _check_note(path, line_no, raw["note"])
        for other in names.get(fid, ()):
            if ranges_overlap(season_from, season_to, other.season_from, other.season_to):
                raise _err(path, line_no, "display-name season ranges overlap for one franchise")
        names.setdefault(fid, []).append(
            FranchiseName(season_from, season_to, raw["display_name"], raw["nickname"])
        )
    return NflFranchises({fid: tuple(v) for fid, v in names.items()})


# -- team crosswalk -----------------------------------------------------------------------------


@dataclass(frozen=True)
class NflTeamCrosswalkRow:
    source: str
    variant: str
    franchise_id: str
    season_from: int | None
    season_to: int | None
    note: str


def normalize_nfl_variant(text: str) -> str:
    """Fold a team variant the same way for loading and resolving."""
    return normalize_team(text)


def load_nfl_team_crosswalk(reference_dir: Path) -> list[NflTeamCrosswalkRow]:
    path = reference_dir / "nfl_team_crosswalk.csv"
    raw_rows = read_reference_csv_numbered(path, NFL_TEAM_CROSSWALK_COLUMNS, required=True)
    franchises = load_nfl_franchises(reference_dir)
    rows: list[NflTeamCrosswalkRow] = []
    seen: dict[tuple[str, str], list[tuple[int | None, int | None, str]]] = {}
    for line_no, raw in raw_rows:
        source = raw["source"]
        if source not in NFL_TEAM_SOURCES:
            raise _err(path, line_no, "invalid source")
        if not raw["variant"]:
            raise _err(path, line_no, "variant is required")
        fid = raw["franchise_id"]
        if fid not in franchises:
            raise _err(path, line_no, "franchise_id is not in nfl_franchises.csv")
        season_from = _opt_int(path, line_no, raw["season_from"], "season_from")
        season_to = _opt_int(path, line_no, raw["season_to"], "season_to")
        _check_note(path, line_no, raw["note"])
        key = (source, normalize_nfl_variant(raw["variant"]))
        for o_from, o_to, o_fid in seen.get(key, ()):
            if o_fid != fid and ranges_overlap(season_from, season_to, o_from, o_to):
                raise _err(path, line_no, "variant maps to two franchises over overlapping seasons")
        seen.setdefault(key, []).append((season_from, season_to, fid))
        rows.append(
            NflTeamCrosswalkRow(source, raw["variant"], fid, season_from, season_to, raw["note"])
        )
    return rows


# -- stadiums -----------------------------------------------------------------------------------


def load_nfl_stadiums(reference_dir: Path) -> Mapping[str, str]:
    """stadium_id -> two-letter country. A missing table is empty."""
    path = reference_dir / "nfl_stadiums.csv"
    raw_rows = read_reference_csv_numbered(path, NFL_STADIUM_COLUMNS, required=False)
    out: dict[str, str] = {}
    for line_no, raw in raw_rows:
        sid = raw["stadium_id"]
        if not sid:
            raise _err(path, line_no, "stadium_id is required")
        if sid in out:
            raise _err(path, line_no, "duplicate stadium_id")
        if not _COUNTRY_RE.fullmatch(raw["country"]):
            raise _err(path, line_no, "country must be two uppercase letters")
        _check_https(path, line_no, raw["source_url"])
        _check_note(path, line_no, raw["note"])
        out[sid] = raw["country"]
    return out


def load_nfl_stadium_overrides(reference_dir: Path) -> Mapping[str, str]:
    """nflverse_game_id -> the venue's stadium_id, for games nflverse files under the home
    team's own stadium id (2025 international games). A missing table is empty; every
    stadium_id must be a row in nfl_stadiums.csv."""
    path = reference_dir / "nfl_stadium_overrides.csv"
    raw_rows = read_reference_csv_numbered(path, NFL_STADIUM_OVERRIDE_COLUMNS, required=False)
    if not raw_rows:
        return {}
    stadiums = load_nfl_stadiums(reference_dir)
    out: dict[str, str] = {}
    for line_no, raw in raw_rows:
        game_id = raw["nflverse_game_id"]
        if not game_id:
            raise _err(path, line_no, "nflverse_game_id is required")
        if game_id in out:
            raise _err(path, line_no, "duplicate nflverse_game_id")
        if raw["stadium_id"] not in stadiums:
            raise _err(path, line_no, "stadium_id is not in nfl_stadiums.csv")
        _check_https(path, line_no, raw["source_url"])
        _check_note(path, line_no, raw["note"])
        out[game_id] = raw["stadium_id"]
    return out


# -- networks -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class NflNetworkRow:
    source: str
    variant: str
    network_id: str
    note: str


def load_nfl_networks(reference_dir: Path) -> list[NflNetworkRow]:
    path = reference_dir / "nfl_networks.csv"
    raw_rows = read_reference_csv_numbered(path, NFL_NETWORK_COLUMNS, required=True)
    rows: list[NflNetworkRow] = []
    seen: dict[tuple[str, str], str] = {}
    for line_no, raw in raw_rows:
        if raw["source"] not in NFL_NETWORK_SOURCES:
            raise _err(path, line_no, "invalid source")
        if raw["network_id"] not in NFL_NETWORK_IDS:
            raise _err(path, line_no, "unknown network_id")
        if not raw["variant"]:
            raise _err(path, line_no, "variant is required")
        _check_note(path, line_no, raw["note"])
        key = (raw["source"], " ".join(raw["variant"].casefold().split()))
        if key in seen and seen[key] != raw["network_id"]:
            raise _err(path, line_no, "variant maps to two networks")
        seen[key] = raw["network_id"]
        rows.append(NflNetworkRow(raw["source"], raw["variant"], raw["network_id"], raw["note"]))
    return rows


# -- lead-booth overrides -----------------------------------------------------------------------


@dataclass(frozen=True)
class NflLeadBoothOverride:
    season: int
    person_id: str
    reason: str
    source_url: str


def load_nfl_lead_booth_overrides(reference_dir: Path) -> dict[int, NflLeadBoothOverride]:
    path = reference_dir / "nfl_lead_booth_overrides.csv"
    raw_rows = read_reference_csv_numbered(path, NFL_LEAD_BOOTH_OVERRIDE_COLUMNS, required=False)
    if not raw_rows:
        return {}
    people = load_people(reference_dir).persons
    out: dict[int, NflLeadBoothOverride] = {}
    for line_no, raw in raw_rows:
        season = _req_int(path, line_no, raw["season"], "season")
        if season in out:
            raise _err(path, line_no, "duplicate season")
        if raw["person_id"] not in people:
            raise _err(path, line_no, "person_id is not in people.csv")
        if raw["reason"] not in NFL_LEAD_BOOTH_REASONS:
            raise _err(path, line_no, "invalid reason")
        _check_https(path, line_no, raw["source_url"])
        out[season] = NflLeadBoothOverride(
            season, raw["person_id"], raw["reason"], raw["source_url"]
        )
    return out


# -- week overrides -----------------------------------------------------------------------------


@dataclass(frozen=True)
class NflWeekOverride:
    season: int
    week: int
    network: str
    nflverse_game_id: str
    source_url: str
    reason: str


def load_nfl_week_overrides(
    reference_dir: Path,
) -> dict[tuple[int, int, str], NflWeekOverride]:
    path = reference_dir / "nfl_week_overrides.csv"
    raw_rows = read_reference_csv_numbered(path, NFL_WEEK_OVERRIDE_COLUMNS, required=False)
    out: dict[tuple[int, int, str], NflWeekOverride] = {}
    for line_no, raw in raw_rows:
        season = _req_int(path, line_no, raw["season"], "season")
        week = _req_int(path, line_no, raw["week"], "week")
        if raw["network"] not in NFL_WEEK_OVERRIDE_NETWORKS:
            raise _err(path, line_no, "network must be fox or cbs")
        if not raw["nflverse_game_id"]:
            raise _err(path, line_no, "nflverse_game_id is required")
        _check_https(path, line_no, raw["source_url"])
        if raw["reason"] not in NFL_WEEK_OVERRIDE_REASONS:
            raise _err(path, line_no, "invalid reason")
        key = (season, week, raw["network"])
        if key in out:
            raise _err(path, line_no, "duplicate (season, week, network)")
        out[key] = NflWeekOverride(
            season, week, raw["network"], raw["nflverse_game_id"], raw["source_url"], raw["reason"]
        )
    return out
