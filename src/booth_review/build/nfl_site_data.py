"""Build `nfl-data.json` content from the vault's NFL tables (999.5 D-07).

Selection, labeling and indexing only: every number already exists in the three
999.4 tables (`nfl_games`, `nfl_special_games_by_team_season`, `nfl_task1_crews`).
Each block is built from an explicit list of display columns, so the analysis-only
fields (the pregame spread, the coverage share, raw crew strings, the raw
win-probability series and the raw mean absolute spread) cannot reach the output;
the contract's `extra="forbid"` is a second wall.

Errors name a file, column and row position only, never a value (T-03-04).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import polars as pl
from pydantic import ValidationError

from booth_review.build.site_data import _contract_error_summary
from booth_review.config import DataPaths
from booth_review.contract.nfl_models import (
    NFL_SLOTS,
    NflBoothColumns,
    NflGameColumns,
    NflSiteData,
)
from booth_review.contract.nfl_models import (
    NflViewershipColumns as NflAgotwColumns,  # plan 08-07 rewrites the builder for 2.0.0
)
from booth_review.errors import SiteBuildError
from booth_review.flags.era import MeasurementEra, load_eras
from booth_review.nfl.adjust import LOW_N
from booth_review.nfl.booths import assign_booths
from booth_review.nfl.games import NFL_GAME_COLUMNS
from booth_review.nfl.reference import NflFranchises, load_nfl_franchises
from booth_review.nfl.tables import NFL_SPECIAL_COLUMNS
from booth_review.nfl.task1 import NFL_TASK1_COLUMNS
from booth_review.people.registry import PeopleRegistry, load_people
from booth_review.transport.cache import atomic_write_bytes

NFL_SITE_DATA_PATH = "processed/nfl-data.json"

_ET = ZoneInfo("America/New_York")

NFL_NETWORK_NAMES: Mapping[str, str] = {
    "abc": "ABC",
    "cbs": "CBS",
    "espn": "ESPN",
    "espn2": "ESPN2",
    "espn_deportes": "ESPN Deportes",
    "espn_plus": "ESPN+",
    "fox": "Fox",
    "nbc": "NBC",
    "netflix": "Netflix",
    "nfln": "NFL Network",
    "peacock": "Peacock",
    "prime": "Prime Video",
    "yahoo": "Yahoo",
    "youtube": "YouTube",
}

_STANDALONE_SUFFIXES: tuple[str, ...] = (
    "christmas",
    "thanksgiving",
    "black_friday",
    "international",
    "tnf",
    "snf",
    "mnf",
    "saturday",
    "friday",
    "sunday_early",
    "sunday_late",
    "other",
)
_SPECIAL_COUNT_COLUMNS: tuple[str, ...] = (
    "games",
    "standalone_total",
    *(f"standalone_{s}" for s in _STANDALONE_SUFFIXES),
    "agotw",
    "cbs_national",
    "international",
    "international_other",
    "flexed",
    "special",
)
_WEEK_COLUMNS: tuple[str, ...] = (
    "fox_doubleheader_weeks",
    "fox_ambiguous_weeks",
    "cbs_doubleheader_weeks",
    "cbs_ambiguous_weeks",
)
_MEASURES: tuple[str, ...] = ("margin", "excitement", "volatility")
_REGIONAL_SLOTS = frozenset({"Sunday early", "Sunday late"})


@dataclass(frozen=True)
class NflSiteInputs:
    games: pl.DataFrame
    special: pl.DataFrame
    task1: pl.DataFrame
    people: PeopleRegistry
    franchises: NflFranchises
    eras: Sequence[MeasurementEra]


# ----------------------------------------------------------------------------
# Loading
# ----------------------------------------------------------------------------


def _read_table(paths: DataPaths, name: str, columns: Sequence[str]) -> pl.DataFrame:
    rel = f"processed/{name}.parquet"
    path = paths.vault / rel
    if not path.is_file():
        raise SiteBuildError(f"{rel} not found; run `booth-review nfl build` first")
    frame = pl.read_parquet(path)
    missing = [c for c in columns if c not in frame.columns]
    if missing:
        raise SiteBuildError(f"{rel}: missing column(s): {', '.join(missing)}")
    return frame


def load_nfl_site_inputs(paths: DataPaths, reference_directory: Path) -> NflSiteInputs:
    """Read the three vault tables plus the public people, franchise and era tables."""
    return NflSiteInputs(
        games=_read_table(paths, "nfl_games", NFL_GAME_COLUMNS),
        special=_read_table(paths, "nfl_special_games_by_team_season", NFL_SPECIAL_COLUMNS),
        task1=_read_table(paths, "nfl_task1_crews", NFL_TASK1_COLUMNS),
        people=load_people(reference_directory),
        franchises=load_nfl_franchises(reference_directory),
        eras=load_eras(reference_directory),
    )


# ----------------------------------------------------------------------------
# Lookups
# ----------------------------------------------------------------------------


class _Index:
    """An insertion-ordered value -> index map."""

    def __init__(self) -> None:
        self.items: list[Any] = []
        self._pos: dict[Any, int] = {}

    def add(self, key: Any, value: Any | None = None) -> int:
        if key not in self._pos:
            self._pos[key] = len(self.items)
            self.items.append(key if value is None else value)
        return self._pos[key]


def _latest_display_name(franchises: NflFranchises, franchise_id: str) -> str:
    names = franchises.names.get(franchise_id)
    if not names:
        raise SiteBuildError("lookups.franchises: a franchise id is missing from nfl_franchises")
    latest = max(
        names,
        key=lambda n: (n.season_to is None, n.season_to or 0, n.season_from or 0),
    )
    return latest.display_name


def _season_name(
    franchises: NflFranchises, franchise_id: str, season: int, shown: str | None
) -> tuple[str, str]:
    """(name, short) a franchise carried in `season`."""
    for entry in franchises.names.get(franchise_id, ()):
        lo = entry.season_from if entry.season_from is not None else season
        hi = entry.season_to if entry.season_to is not None else season
        if lo <= season <= hi:
            return (shown or entry.display_name, entry.nickname or entry.display_name)
    if shown:
        return (shown, shown)
    raise SiteBuildError("lookups.team_names: a franchise has no name for a shown season")


def _et_kickoff(value: datetime | None) -> str | None:
    return None if value is None else value.astimezone(_ET).isoformat()


def _sorted_regular(games: pl.DataFrame) -> pl.DataFrame:
    return games.filter(pl.col("game_type") == "REG").sort(
        ["season", "week", "game_date", "kickoff_utc", "home_franchise_id", "game_id"],
        nulls_last=True,
    )


# ----------------------------------------------------------------------------
# Games
# ----------------------------------------------------------------------------


def _cause(row: dict[str, Any], current: bool, vt_week: int | None, slot: str) -> str:
    """Why a game has no figure (RESEARCH A3): pending, regional or none."""
    if current and (vt_week is None or row["week"] >= vt_week):
        return "pending"
    if slot in _REGIONAL_SLOTS and not row["is_agotw"] and not row["is_cbs_national"]:
        return "regional"
    return "none"


def _games_block(
    games: pl.DataFrame,
    inputs: NflSiteInputs,
    current_season: int | None,
    vt_week: int | None,
) -> tuple[dict[str, list[Any]], dict[str, _Index]]:
    franchise_ids = sorted(
        set(games["home_franchise_id"].to_list())
        | set(games["away_franchise_id"].to_list())
        | set(inputs.special["franchise_id"].to_list())
    )
    franchises = _Index()
    for fid in franchise_ids:
        franchises.add(fid, {"id": fid, "name": _latest_display_name(inputs.franchises, fid)})
    lookups = {
        "franchises": franchises,
        "team_names": _Index(),
        "networks": _Index(),
        "people": _Index(),
    }
    era_pos = {e.era_id: k for k, e in enumerate(inputs.eras)}
    cols: dict[str, list[Any]] = {name: [] for name in NflGameColumns.model_fields}
    for i, row in enumerate(games.iter_rows(named=True)):
        _append_game(cols, row, i, inputs, lookups, era_pos, current_season, vt_week)
    return cols, lookups


def _network_index(networks: _Index, network_id: str | None, where: str) -> int | None:
    if network_id is None:
        return None
    name = NFL_NETWORK_NAMES.get(network_id)
    if name is None:
        raise SiteBuildError(f"{where}: network id has no display name")
    return networks.add(network_id, {"id": network_id, "name": name})


def _person_index(people: _Index, registry: PeopleRegistry, person_id: str, where: str) -> int:
    person = registry.persons.get(person_id)
    if person is None:
        raise SiteBuildError(f"{where}: person id is not in the people registry")
    return people.add(person_id, {"id": person_id, "name": person.canonical_name})


def _append_game(
    cols: dict[str, list[Any]],
    row: dict[str, Any],
    i: int,
    inputs: NflSiteInputs,
    lookups: dict[str, _Index],
    era_pos: dict[str, int],
    current_season: int | None,
    vt_week: int | None,
) -> None:
    season = int(row["season"])
    slot = row["slot_name"]
    if slot not in NFL_SLOTS:
        raise SiteBuildError(f"games.slot[{i}]: not a known slot name")
    where_net = f"games.network[{i}]"
    flexed = bool(row["flexed"])
    cols["season"].append(season)
    cols["week"].append(int(row["week"]))
    cols["date"].append(row["game_date"].isoformat())
    cols["kickoff"].append(_et_kickoff(row["kickoff_utc"]))
    for side in ("home", "away"):
        fid = row[f"{side}_franchise_id"]
        cols[side].append(lookups["franchises"].add(fid))
        name, short = _season_name(inputs.franchises, fid, season, row[f"{side}_display_name"])
        cols[f"{side}_name"].append(
            lookups["team_names"].add((name, short), {"name": name, "short": short})
        )
    cols["home_points"].append(row["home_points"])
    cols["away_points"].append(row["away_points"])
    cols["final_margin"].append(row["final_margin"])
    cols["slot"].append(NFL_SLOTS.index(slot))
    cols["standalone"].append(bool(row["is_standalone"]))
    cols["agotw"].append(bool(row["is_agotw"]))
    cols["cbs_national"].append(bool(row["is_cbs_national"]))
    cols["international"].append(bool(row["is_international"]))
    cols["flexed"].append(flexed)
    original_slot = row["original_slot"] if flexed else None
    if original_slot is not None and original_slot not in NFL_SLOTS:
        raise SiteBuildError(f"games.original_slot[{i}]: not a known slot name")
    cols["original_slot"].append(None if original_slot is None else NFL_SLOTS.index(original_slot))
    cols["original_network"].append(
        _network_index(
            lookups["networks"],
            row["original_network"] if flexed else None,
            f"games.original_network[{i}]",
        )
    )
    cols["change_url"].append(row["change_article_url"] if flexed else None)
    cols["network"].append(_network_index(lookups["networks"], row["network_id"], where_net))
    crew: list[dict[str, Any]] = []
    for role, pid in (
        ("pbp", row["pbp_person_id"]),
        ("analyst", row["analyst_person_id"]),
        *(("unknown", s) for s in (row["sideline_person_ids"] or [])),
    ):
        if pid is not None:
            idx = _person_index(lookups["people"], inputs.people, pid, f"games.crew[{i}]")
            crew.append({"person": idx, "role": role})
    cols["crew"].append(crew)
    excitement = row["excitement_score"]
    cols["excitement"].append(None if excitement is None else round(float(excitement), 3))
    viewers = row["viewership"]
    if viewers is None:
        cols["viewers"].append(None)
        cols["scope"].append(None)
        cols["era"].append(None)
        cols["cause"].append(_cause(row, season == current_season, vt_week, slot))
    else:
        cols["viewers"].append(round(viewers))
        cols["scope"].append(row["viewership_scope"])
        era_id = row["era_id"]
        cols["era"].append(era_pos.get(era_id) if era_id is not None else None)
        cols["cause"].append(None)
    cols["rr_url"].append(row["rr_record_url"] if viewers is not None else None)
    cols["source_url"].append(row["rr_source_url"] if viewers is not None else None)


def _ship_eras(
    all_eras: Sequence[MeasurementEra], cols: dict[str, list[Any]], agotw: dict[str, list[Any]]
) -> list[dict[str, Any]]:
    """Ship only the referenced eras, in era order, remapping the positions the
    blocks hold (positions in `all_eras`) to indexes into the shipped list."""
    used = sorted({e for e in cols["era"] if e is not None} | set(agotw["era"]))
    remap = {old: new for new, old in enumerate(used)}
    cols["era"] = [None if e is None else remap[e] for e in cols["era"]]
    agotw["era"] = [remap[e] for e in agotw["era"]]
    out = []
    for position in used:
        era = all_eras[position]
        out.append(
            {
                "id": era.era_id,
                "label": era.label,
                "start": _iso(era.start),
                "end": _iso(era.end),
                "source_url": era.source_url,
            }
        )
    return out


def _iso(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


# ----------------------------------------------------------------------------
# Freshness and constants
# ----------------------------------------------------------------------------


def _opt_int(value: object) -> int | None:
    return None if value is None else int(value)  # type: ignore[call-overload]


def _freshness(games: pl.DataFrame, task1: pl.DataFrame) -> dict[str, Any]:
    season = int(games["season"].max())  # type: ignore[arg-type]
    current = games.filter(pl.col("season") == season)
    in_progress = bool(current["home_points"].is_null().any())
    through = current.filter(pl.col("home_points").is_not_null())["week"].max()
    rated = current.filter(pl.col("viewership").is_not_null())["week"].max()
    booth_seasons = sorted(
        {int(s) for s in task1.filter(pl.col("view") == "booth")["season"].to_list()}
    )
    if in_progress:
        booth_seasons = [s for s in booth_seasons if s < season]
    return {
        "season": season,
        "in_progress": in_progress,
        "through_week": _opt_int(through),
        "viewership_through_week": _opt_int(rated),
        "fox_default_season": booth_seasons[-1] if booth_seasons else None,
    }


def _constants(task1: pl.DataFrame) -> dict[str, Any]:
    for i, row in enumerate(task1.select("coverage_normalized", "excitement_method").iter_rows()):
        if row[0] is True:
            raise SiteBuildError(f"task1.coverage_normalized[{i}]: must be false")
        if row[1] != "GEI-style":
            raise SiteBuildError(f"task1.excitement_method[{i}]: must be GEI-style")
    return {
        "viewership_scope": "window",
        "coverage_normalized": False,
        "excitement_method": "GEI-style",
        "low_n_threshold": LOW_N,
    }


# ----------------------------------------------------------------------------
# Special and season weeks
# ----------------------------------------------------------------------------


def _regular_game_counts(games: pl.DataFrame) -> dict[tuple[str, int], int]:
    """(franchise, season) -> regular-season games played in the shipped games."""
    counts: dict[tuple[str, int], int] = {}
    for row in games.iter_rows(named=True):
        for side in ("home", "away"):
            key = (row[f"{side}_franchise_id"], int(row["season"]))
            counts[key] = counts.get(key, 0) + 1
    return counts


def _exclusive_counts(games: pl.DataFrame) -> dict[tuple[str, int], list[int]]:
    """(franchise, season) -> [standalone, agotw, cbs_national, international_other]."""
    counts: dict[tuple[str, int], list[int]] = {}
    for row in games.iter_rows(named=True):
        if row["is_standalone"]:
            k = 0
        elif row["is_agotw"]:
            k = 1
        elif row["is_cbs_national"]:
            k = 2
        elif row["is_international"]:
            k = 3
        else:
            continue
        for side in ("home", "away"):
            key = (row[f"{side}_franchise_id"], int(row["season"]))
            counts.setdefault(key, [0, 0, 0, 0])[k] += 1
    return counts


def _special_block(
    special: pl.DataFrame, games: pl.DataFrame, franchises: _Index
) -> dict[str, list[Any]]:
    special = special.sort(["franchise_id", "season"])
    expected = _exclusive_counts(games)
    # D-17 / WR-05: the table's counts must come from regular-season games only.
    # A table built with --include-playoffs counts playoff games too, so it is
    # refused here rather than shipping inflated counts.
    regular = _regular_game_counts(games)
    cols: dict[str, list[Any]] = {
        name: [] for name in ("franchise", "season", *_SPECIAL_COUNT_COLUMNS)
    }
    cols["agotw_rate"] = []
    cols["cbs_national_rate"] = []
    for i, row in enumerate(special.iter_rows(named=True)):
        key = (row["franchise_id"], int(row["season"]))
        got = expected.get(key, [0, 0, 0, 0])
        want = [
            row["standalone_total"],
            row["agotw"],
            row["cbs_national"],
            row["international_other"],
        ]
        if got != want:
            raise SiteBuildError(f"special[{i}]: exclusive category counts do not match games")
        if regular.get(key, 0) != row["games"]:
            raise SiteBuildError(
                f"special[{i}].games: does not match the regular-season games "
                "(was the table built with --include-playoffs?)"
            )
        cols["franchise"].append(franchises.add(row["franchise_id"]))
        cols["season"].append(int(row["season"]))
        for name in _SPECIAL_COUNT_COLUMNS:
            cols[name].append(int(row[name]))
        cols["agotw_rate"].append(row["agotw_rate"])
        cols["cbs_national_rate"].append(row["cbs_national_rate"])
    return cols


def _season_weeks_block(special: pl.DataFrame) -> dict[str, list[Any]]:
    seen: dict[int, tuple[int, ...]] = {}
    for i, row in enumerate(special.sort(["season", "franchise_id"]).iter_rows(named=True)):
        values = tuple(int(row[c]) for c in _WEEK_COLUMNS)
        season = int(row["season"])
        if seen.setdefault(season, values) != values:
            raise SiteBuildError(f"season_weeks[{i}]: week counts differ within a season")
    cols: dict[str, list[Any]] = {"season": [], **{c: [] for c in _WEEK_COLUMNS}}
    for season in sorted(seen):
        cols["season"].append(season)
        for c, v in zip(_WEEK_COLUMNS, seen[season], strict=True):
            cols[c].append(v)
    return cols


# ----------------------------------------------------------------------------
# Fox booths and AGOTW viewership
# ----------------------------------------------------------------------------


def _optional_person(
    people: _Index, registry: PeopleRegistry, person_id: str | None, where: str
) -> int | None:
    return None if person_id is None else _person_index(people, registry, person_id, where)


def _booth_block(
    task1: pl.DataFrame,
    games: pl.DataFrame,
    inputs: NflSiteInputs,
    people: _Index,
    game_index: dict[str, int],
) -> dict[str, list[Any]]:
    booths, _ = assign_booths(games)
    by_booth: dict[tuple[int, str], list[int]] = {}
    for r in booths.iter_rows(named=True):
        by_booth.setdefault((int(r["season"]), r["booth_pbp_person_id"]), []).append(
            game_index[r["game_id"]]
        )
    rows = task1.filter(pl.col("view") == "booth")
    lead_pbp = {
        int(r["season"]): r["booth_pbp_person_id"]
        for r in rows.iter_rows(named=True)
        if r["booth_group"] == "lead"
    }
    cols: dict[str, list[Any]] = {n: [] for n in NflBoothColumns.model_fields}
    for i, r in enumerate(rows.iter_rows(named=True)):
        season = int(r["season"])
        group = r["booth_group"]
        where = f"fox_booths[{i}]"
        cols["season"].append(season)
        cols["group"].append(group)
        cols["rank"].append(None if r["booth_rank"] is None else int(r["booth_rank"]))
        cols["pbp_person"].append(
            _optional_person(people, inputs.people, r["booth_pbp_person_id"], where)
        )
        cols["analyst_person"].append(
            _optional_person(people, inputs.people, r["regular_analyst_person_id"], where)
        )
        for c in ("games", "fill_in_games"):
            cols[c].append(int(r[c] or 0))
        for m in _MEASURES:
            cols[f"raw_n_{m}"].append(int(r[f"raw_n_{m}"] or 0))
            cols[f"adj_n_{m}"].append(int(r[f"adj_n_{m}"] or 0))
            cols[f"adj_{m}_resid"].append(r[f"adj_{m}_resid"])
            cols[f"adj_{m}_se"].append(r[f"adj_{m}_se"])
        cols["raw_mean_abs_margin"].append(r["raw_mean_abs_margin"])
        cols["raw_mean_excitement"].append(r["raw_mean_excitement"])
        cols["raw_mean_volatility"].append(r["raw_mean_volatility"])
        cols["low_n"].append(bool(r["low_n"]))
        if group == "others_pooled":
            members = [
                g
                for (s, pbp), lst in sorted(by_booth.items())
                if s == season and pbp != lead_pbp.get(season)
                for g in lst
            ]
        else:
            members = by_booth.get((season, r["booth_pbp_person_id"]), [])
        cols["game_list"].append(sorted(members))
    return cols


def _agotw_block(
    task1: pl.DataFrame,
    games: pl.DataFrame,
    inputs: NflSiteInputs,
    people: _Index,
    game_index: dict[str, int],
) -> dict[str, list[Any]]:
    booths, _ = assign_booths(games)
    pbp_of = dict(
        zip(booths["game_id"].to_list(), booths["booth_pbp_person_id"].to_list(), strict=True)
    )
    era_pos = {e.era_id: k for k, e in enumerate(inputs.eras)}
    agotw_games = games.filter(
        pl.col("is_agotw").fill_null(False)
        & (pl.col("late_national_status") != "ambiguous")
        & pl.col("viewership").is_not_null()
    )
    cols: dict[str, list[Any]] = {n: [] for n in NflAgotwColumns.model_fields}
    for i, r in enumerate(task1.filter(pl.col("view") == "agotw_viewership").iter_rows(named=True)):
        season = int(r["season"])
        where = f"agotw_viewership[{i}]"
        if r["era_id"] not in era_pos:
            raise SiteBuildError(f"{where}.era: not a known measurement era")
        cols["season"].append(season)
        cols["era"].append(era_pos[r["era_id"]])
        cols["group"].append(r["booth_group"])
        cols["pbp_person"].append(
            _optional_person(people, inputs.people, r["booth_pbp_person_id"], where)
        )
        cols["analyst_person"].append(
            _optional_person(people, inputs.people, r["regular_analyst_person_id"], where)
        )
        cols["games"].append(int(r["n_viewership"] or 0))
        cols["fill_in_games"].append(int(r["fill_in_games"] or 0))
        cols["mean_viewers"].append(r["mean_viewers"])
        cols["viewership_resid"].append(r["viewership_resid"])
        cols["viewership_se"].append(r["viewership_se"])
        cols["low_n"].append(bool(r["low_n"]))
        members = [
            game_index[g["game_id"]]
            for g in agotw_games.filter(
                (pl.col("season") == season) & (pl.col("era_id") == r["era_id"])
            ).iter_rows(named=True)
            if pbp_of.get(g["game_id"]) == r["booth_pbp_person_id"]
        ]
        cols["game_list"].append(sorted(members))
    return cols


# ----------------------------------------------------------------------------
# Assembly
# ----------------------------------------------------------------------------


def build_nfl_site_data(inputs: NflSiteInputs) -> NflSiteData:
    """Build and validate the NFL site payload; pure, deterministic, display fields only."""
    games = _sorted_regular(inputs.games)
    if games.height == 0:
        raise SiteBuildError("games: no regular-season games to ship")
    freshness = _freshness(games, inputs.task1)
    constants = _constants(inputs.task1)
    # The CFB rule (shipped.no_rating_cause): "pending" covers a game in the
    # current season (the freshness season, the latest in the tables) at or
    # after `viewership_through_week`, or any current-season game while that
    # stamp is null. It does not key on whether games are still being played:
    # Ratings Reference figures keep arriving after the last score is in, and
    # a never-scored (cancelled) game stops being pending once a later season
    # becomes current.
    current_season = freshness["season"]
    game_cols, lookups = _games_block(
        games, inputs, current_season, freshness["viewership_through_week"]
    )
    game_index = {gid: k for k, gid in enumerate(games["game_id"].to_list())}
    special = _special_block(inputs.special, games, lookups["franchises"])
    season_weeks = _season_weeks_block(inputs.special)
    booths = _booth_block(inputs.task1, games, inputs, lookups["people"], game_index)
    agotw = _agotw_block(inputs.task1, games, inputs, lookups["people"], game_index)
    era_rows = _ship_eras(inputs.eras, game_cols, agotw)
    payload = {
        "schema_version": "1.0.0",
        "freshness": freshness,
        "constants": constants,
        "lookups": {
            "franchises": lookups["franchises"].items,
            "team_names": lookups["team_names"].items,
            "networks": lookups["networks"].items,
            "people": lookups["people"].items,
            "eras": era_rows,
            "slots": list(NFL_SLOTS),
        },
        "games": game_cols,
        "special": special,
        "season_weeks": season_weeks,
        "fox_booths": booths,
        "agotw_viewership": agotw,
    }
    try:
        return NflSiteData.model_validate(payload)
    except ValidationError as exc:
        raise SiteBuildError(_contract_error_summary(exc)) from None


def nfl_site_payload_bytes(site: NflSiteData) -> bytes:
    """Compact, key-sorted JSON; identical inputs give identical bytes.

    `allow_nan=False`: NaN or Infinity would be invalid JSON (WR-04). The
    contract already rejects them, so this only guards against drift."""
    payload = site.model_dump(mode="json")
    return json.dumps(payload, separators=(",", ":"), sort_keys=True, allow_nan=False).encode(
        "utf-8"
    )


def write_nfl_site_data(paths: DataPaths, site: NflSiteData) -> str:
    """Write `processed/nfl-data.json` atomically; returns its vault-relative path."""
    atomic_write_bytes(paths.vault / NFL_SITE_DATA_PATH, nfl_site_payload_bytes(site))
    return NFL_SITE_DATA_PATH
