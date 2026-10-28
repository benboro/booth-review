"""Build `mlb-data.json` content from the vault's MLB tables (phase 09 plan 26).

Selection, labeling and indexing only: every number already exists in the processed
`mlb_*` tables. Only the games that feed the three views ship (Apple 2026 regular-season
own-production games and the 2014-2026 own-production postseason games), never the full
telecast table. Each block is built from an explicit list of display fields, so the
analysis-only fields (`is_exclusive`, `production`, raw crew strings, the win-expectancy
table, per-play series) cannot reach the output; the contract's `extra="forbid"` is a
second wall.

Whether quality is pending comes from the data (an Apple booth with no stakes or
excitement figure), so no code change is needed when Retrosheet 2026 arrives (D-06).
There is no wall-clock value, so identical tables give identical bytes. Errors name a
file, column and row position only, never a value (T-03-04).
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Final

import polars as pl
from pydantic import ValidationError

from booth_review.build.serif_glyphs import check_serif_text, lookup_names
from booth_review.build.site_data import _contract_error_summary
from booth_review.config import DataPaths
from booth_review.contract.mlb_models import (
    MLB_CAUSES,
    MLB_ROUNDS,
    MLB_SCHEMA_VERSION,
    MlbAppleBoothColumns,
    MlbGameColumns,
    MlbLineupColumns,
    MlbPostseasonColumns,
    MlbSiteData,
)
from booth_review.errors import SiteBuildError
from booth_review.flags.era import MeasurementEra, load_eras
from booth_review.mlb.constants import (
    CREW_COVERAGE_BAR,
    EXCITEMENT_METHOD,
    LOW_N,
    STAKES_METHOD,
)
from booth_review.mlb.layout import MLB_FIRST_SEASON
from booth_review.mlb.reference import MlbClubName, MlbReference, load_mlb_reference
from booth_review.transport.cache import atomic_write_bytes

__all__ = [
    "MLB_SITE_DATA_PATH",
    "MlbSiteInputs",
    "build_and_write_mlb_site_data",
    "build_mlb_site_data",
    "load_mlb_site_inputs",
    "mlb_site_counts",
    "mlb_site_payload_bytes",
    "write_mlb_site_data",
]

MLB_SITE_DATA_PATH: Final = "processed/mlb-data.json"

APPLE_NETWORK: Final = "apple"
APPLE_SEASON: Final = 2026
_POSTSEASON_LAST: Final = 2026
_NON_POSTSEASON: Final = frozenset({"regular", "allstar"})
_LEAGUES: Final = ("AL", "NL")
_LEAGUE_REFS: Final = (
    {"id": "AL", "name": "American League"},
    {"id": "NL", "name": "National League"},
)
_POSITIONS: Final[Mapping[int, str]] = {
    1: "P",
    2: "C",
    3: "1B",
    4: "2B",
    5: "3B",
    6: "SS",
    7: "LF",
    8: "CF",
    9: "RF",
    10: "DH",
}

_GAME_COLUMNS: Final = (
    "game_key",
    "season",
    "game_date",
    "series_league",
    "series_game",
    "home_score",
    "pregame_stakes",
    "wp_excitement",
)
_TELECAST_COLUMNS: Final = (
    "game_key",
    "season",
    "game_date",
    "away_club",
    "home_club",
    "game_number",
    "network_id",
    "network_source",
    "network_source_url",
    "production",
    "round",
    "series_game",
    "pbp_person_id",
    "analyst_person_ids",
    "crew_source",
    "crew_source_url",
    "press_url",
    "press_name",
    "crew_named",
    "booth_key",
    "rr_figure_row",
    "rr_cause",
    "rr_viewers",
    "rr_label",
    "rr_url",
    "rr_source_url",
    "rr_era_id",
)
_LINEUP_COLUMNS: Final = (
    "game_key",
    "side",
    "slot",
    "player_id",
    "name",
    "position",
    "starter_uncertain",
)
_BOOTH_COLUMNS: Final = (
    "booth_key",
    "pbp_person_id",
    "analyst_person_ids",
    "rank_label",
    "games",
    "crew_listed",
    "relay_crews",
    "stakes_n",
    "stakes_raw",
    "stakes_adj",
    "stakes_adj_se",
    "excitement_raw",
    "excitement_adj",
    "excitement_adj_se",
    "strength_prior",
    "low_n",
    "quality_status",
)
_SUMMARY_COLUMNS: Final = (
    "apple_games",
    "rr_rated",
    "lead_games",
    "others_games",
    "stakes_adj_diff",
    "stakes_adj_diff_se",
    "excitement_adj_diff",
    "excitement_adj_diff_se",
)
_POST_COLUMNS: Final = (
    "season",
    "round",
    "league",
    "network_ids",
    "booths",
    "games",
    "crew_listed",
    "coverage_num",
    "coverage_den",
    "mean_excitement",
    "excitement_n",
    "viewers_mean",
    "viewers_n",
    "game_list",
)
_POST_SEASON_COLUMNS: Final = ("season", "coverage_num", "coverage_den")


@dataclass(frozen=True)
class MlbSiteInputs:
    games: pl.DataFrame
    telecasts: pl.DataFrame
    lineups: pl.DataFrame
    apple_booths: pl.DataFrame
    apple_summary: pl.DataFrame
    postseason: pl.DataFrame
    postseason_seasons: pl.DataFrame
    reference: MlbReference
    eras: Sequence[MeasurementEra]


# ----------------------------------------------------------------------------
# Loading
# ----------------------------------------------------------------------------


def _read_table(paths: DataPaths, name: str, columns: Sequence[str]) -> pl.DataFrame:
    rel = f"processed/{name}.parquet"
    path = paths.vault / rel
    if not path.is_file():
        raise SiteBuildError(f"{rel} not found; run `booth-review mlb build` first")
    frame = pl.read_parquet(path)
    missing = [c for c in columns if c not in frame.columns]
    if missing:
        raise SiteBuildError(f"{rel}: missing column(s): {', '.join(missing)}")
    return frame


def load_mlb_site_inputs(paths: DataPaths, reference_directory: Path) -> MlbSiteInputs:
    """Read the seven vault tables plus the reference clubs, networks, people and eras."""
    return MlbSiteInputs(
        games=_read_table(paths, "mlb_games", _GAME_COLUMNS),
        telecasts=_read_table(paths, "mlb_telecasts", _TELECAST_COLUMNS),
        lineups=_read_table(paths, "mlb_lineups", _LINEUP_COLUMNS),
        apple_booths=_read_table(paths, "mlb_apple_booths", _BOOTH_COLUMNS),
        apple_summary=_read_table(paths, "mlb_apple_summary", _SUMMARY_COLUMNS),
        postseason=_read_table(paths, "mlb_postseason_booths", _POST_COLUMNS),
        postseason_seasons=_read_table(paths, "mlb_postseason_seasons", _POST_SEASON_COLUMNS),
        reference=load_mlb_reference(reference_directory),
        eras=load_eras(reference_directory),
    )


# ----------------------------------------------------------------------------
# Helpers
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


def _finite(value: object, digits: int | None = None) -> float | None:
    """A float cell, or None for a missing or non-finite value."""
    if value is None:
        return None
    number = float(value)  # type: ignore[arg-type]
    if not math.isfinite(number):
        return None
    return number if digits is None else round(number, digits)


def _iso(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def _latest_name(names: Sequence[MlbClubName]) -> MlbClubName:
    return max(names, key=lambda n: (n.season_to is None, n.season_to or 0, n.season_from or 0))


def _network_display(reference: MlbReference) -> dict[str, tuple[str, str]]:
    """network_id -> (display name, family); the name is the 506 label for the network."""
    names: dict[str, tuple[str, str]] = {}
    fallback: dict[str, tuple[str, str]] = {}
    for row in reference.networks:
        fallback.setdefault(row.network_id, (row.variant, row.family))
        if row.source == "506":
            names.setdefault(row.network_id, (row.variant, row.family))
    return {**fallback, **names}


# ----------------------------------------------------------------------------
# Game selection
# ----------------------------------------------------------------------------


def _shipped_telecasts(telecasts: pl.DataFrame) -> pl.DataFrame:
    """One own-production telecast row per game that feeds a view, in display order."""
    own = telecasts.filter(pl.col("production") == "own")
    is_post = (
        pl.col("round").is_not_null()
        & ~pl.col("round").is_in(sorted(_NON_POSTSEASON))
        & pl.col("season").is_between(MLB_FIRST_SEASON, _POSTSEASON_LAST)
    )
    is_apple = (
        (pl.col("network_id") == APPLE_NETWORK)
        & (pl.col("season") == APPLE_SEASON)
        & (pl.col("round").is_null() | (pl.col("round") == "regular"))
    )
    shipped = (
        own.filter(is_post | is_apple)
        .sort("game_date", "game_key", maintain_order=True)
        .unique("game_key", keep="first", maintain_order=True)
        .sort("season", "game_date", "game_key", maintain_order=True)
    )
    # A game's Ratings Reference figure sits on one telecast row (`rr_figure_row`), which
    # need not be the shipped row, so it is joined back by game.
    figure_cols = [c for c in telecasts.columns if c.startswith("rr_") and c != "rr_figure_row"]
    figures = telecasts.filter(pl.col("rr_figure_row").fill_null(False)).unique(
        "game_key", keep="first", maintain_order=True
    )
    return shipped.drop(figure_cols).join(
        figures.select("game_key", *figure_cols), on="game_key", how="left", maintain_order="left"
    )


def _cause(rr_cause: str | None, season: int, current: int, where: str) -> str:
    """Why a game has no figure: pending in the current season, else the match cause."""
    if rr_cause in (None, "none"):
        return "pending" if season == current else "none"
    if rr_cause not in MLB_CAUSES:
        raise SiteBuildError(f"{where}: not a known viewership cause")
    return rr_cause


class _Lookups:
    def __init__(self, inputs: MlbSiteInputs) -> None:
        self.reference = inputs.reference
        self.network_names = _network_display(inputs.reference)
        self.clubs = _Index()
        self.networks = _Index()
        self.people = _Index()
        self.players = _Index()
        self.eras = _Index()
        self.era_rows = {e.era_id: e for e in inputs.eras}

    def club(self, club_id: str, where: str) -> int:
        names = self.reference.clubs.names.get(club_id)
        if not names:
            raise SiteBuildError(f"{where}: a club id is missing from mlb_clubs")
        latest = _latest_name(names)
        return self.clubs.add(
            club_id,
            {
                "id": club_id,
                "name": latest.display_name,
                "league": latest.league,
                "division": latest.division,
            },
        )

    def network(self, network_id: str, where: str) -> int:
        entry = self.network_names.get(network_id)
        if entry is None:
            raise SiteBuildError(f"{where}: a network id is missing from mlb_networks")
        return self.networks.add(
            network_id, {"id": network_id, "name": entry[0], "family": entry[1]}
        )

    def person(self, person_id: str, where: str) -> int:
        person = self.reference.people.persons.get(person_id)
        if person is None:
            raise SiteBuildError(f"{where}: person id is not in the people registry")
        return self.people.add(person_id, {"id": person_id, "name": person.canonical_name})

    def era(self, era_id: str | None) -> int | None:
        if era_id is None or era_id not in self.era_rows:
            return None
        era = self.era_rows[era_id]
        return self.eras.add(
            era_id,
            {
                "id": era.era_id,
                "label": era.label,
                "start": _iso(era.start),
                "end": _iso(era.end),
                "source_url": era.source_url,
            },
        )


# ----------------------------------------------------------------------------
# Blocks
# ----------------------------------------------------------------------------


def _lineup_rows(lineups: pl.DataFrame, shipped_keys: set[str]) -> dict[str, list[dict[str, Any]]]:
    by_game: dict[str, list[dict[str, Any]]] = {}
    ordered = lineups.filter(pl.col("game_key").is_in(sorted(shipped_keys))).sort(
        "game_key", "side", "slot", maintain_order=True
    )
    for row in ordered.iter_rows(named=True):
        by_game.setdefault(str(row["game_key"]), []).append(row)
    return by_game


def _games_and_lineups(
    inputs: MlbSiteInputs, shipped: pl.DataFrame, lk: _Lookups, current: int
) -> tuple[dict[str, list[Any]], dict[str, list[Any]], dict[str, int]]:
    game_info = {
        str(r["game_key"]): r
        for r in inputs.games.select(
            "game_key", "series_league", "series_game", "pregame_stakes", "wp_excitement",
        ).iter_rows(named=True)
    }  # fmt: skip
    keys = [str(k) for k in shipped["game_key"].to_list()]
    lineup_rows = _lineup_rows(inputs.lineups, set(keys))
    cols: dict[str, list[Any]] = {name: [] for name in MlbGameColumns.model_fields}
    lin: dict[str, list[Any]] = {name: [] for name in MlbLineupColumns.model_fields}
    for i, row in enumerate(shipped.iter_rows(named=True)):
        key = str(row["game_key"])
        info = game_info.get(key, {})
        season = int(row["season"])
        rnd = row["round"] or "regular"
        if rnd not in MLB_ROUNDS:
            raise SiteBuildError(f"games.round[{i}]: not a known round")
        regular = rnd == "regular"
        cols["season"].append(season)
        cols["date"].append(row["game_date"].isoformat())
        cols["game_number"].append(int(row["game_number"] or 0))
        cols["away"].append(lk.club(row["away_club"], f"games.away[{i}]"))
        cols["home"].append(lk.club(row["home_club"], f"games.home[{i}]"))
        cols["round"].append(rnd)
        league = info.get("series_league")
        league_idx = None
        if league is not None and not regular and rnd != "world_series":
            if league not in _LEAGUES:
                raise SiteBuildError(f"games.series_league[{i}]: not a league")
            league_idx = _LEAGUES.index(league)
        cols["series_league"].append(league_idx)
        series_game = info.get("series_game")
        if series_game is None:
            series_game = row["series_game"]
        cols["series_game"].append(None if regular or series_game is None else int(series_game))
        cols["network"].append(lk.network(row["network_id"], f"games.network[{i}]"))
        _append_network_source(cols, row, i)
        _append_crew(cols, row, lk, i)
        cols["wp_excitement"].append(_finite(info.get("wp_excitement"), 3))
        cols["stakes"].append(_finite(info.get("pregame_stakes"), 3) if regular else None)
        _append_rating(cols, row, lk, i, season, current)
        _append_lineup(cols, lin, lineup_rows.get(key), lk, i, season, current)
    return cols, lin, {key: i for i, key in enumerate(keys)}


def _append_network_source(cols: dict[str, list[Any]], row: dict[str, Any], i: int) -> None:
    """Where the outlet came from; a Wikipedia or hand-confirmed outlet keeps its link."""
    source = row["network_source"] or "506"
    if source not in ("506", "wikipedia", "override"):
        raise SiteBuildError(f"games.network_source[{i}]: not a known outlet source")
    cols["network_source"].append(source)
    cols["network_source_url"].append(row["network_source_url"] if source != "506" else None)


def _append_crew(cols: dict[str, list[Any]], row: dict[str, Any], lk: _Lookups, i: int) -> None:
    where = f"games.crew[{i}]"
    crew: list[dict[str, Any]] = []
    if row["pbp_person_id"] is not None:
        crew.append({"person": lk.person(row["pbp_person_id"], where), "role": "pbp"})
    for analyst in row["analyst_person_ids"] or []:
        crew.append({"person": lk.person(analyst, where), "role": "analyst"})
    source = row["crew_source"] if crew else None
    cols["crew"].append(crew)
    cols["crew_source"].append(source)
    cols["crew_source_url"].append(row["crew_source_url"] if source is not None else None)
    relay = source == "relay"
    cols["press_url"].append(row["press_url"] if relay else None)
    cols["press_name"].append(row["press_name"] if relay else None)


def _append_rating(
    cols: dict[str, list[Any]], row: dict[str, Any], lk: _Lookups, i: int, season: int, current: int
) -> None:
    viewers = _finite(row["rr_viewers"])
    if viewers is not None and viewers > 0:
        cols["viewers"].append(round(viewers))
        cols["viewership_label"].append(row["rr_label"])
        cols["scope"].append("window" if row["rr_cause"] == "window_level" else "game")
        cols["era"].append(lk.era(row["rr_era_id"]))
        cols["rr_url"].append(row["rr_url"])
        cols["source_url"].append(row["rr_source_url"])
        cols["cause"].append(None)
        return
    for name in ("viewers", "viewership_label", "scope", "era", "rr_url", "source_url"):
        cols[name].append(None)
    cols["cause"].append(_cause(row["rr_cause"], season, current, f"games.cause[{i}]"))


def _append_lineup(
    cols: dict[str, list[Any]],
    lin: dict[str, list[Any]],
    rows: list[dict[str, Any]] | None,
    lk: _Lookups,
    i: int,
    season: int,
    current: int,
) -> None:
    if not rows:
        # A current-season game waits for Retrosheet; an older game is not in it.
        cols["lineup_status"].append("pending" if season == current else "missing")
        cols["lineup_start"].append(None)
        cols["lineup_end"].append(None)
        return
    start = len(lin["game"])
    for r in rows:
        player_id = str(r["player_id"])
        lin["game"].append(i)
        lin["side"].append(r["side"])
        lin["slot"].append(int(r["slot"]))
        lin["player"].append(
            lk.players.add(player_id, {"id": player_id, "name": r["name"] or player_id})
        )
        lin["position"].append(_POSITIONS.get(r["position"], "?") if r["position"] else "?")
        lin["starter_uncertain"].append(bool(r["starter_uncertain"]))
    cols["lineup_status"].append("present")
    cols["lineup_start"].append(start)
    cols["lineup_end"].append(len(lin["game"]) - 1)


def _rank_order(label: str) -> tuple[int, int]:
    if label == "Lead":
        return (0, 0)
    if label.startswith("#") and label[1:].isdigit():
        return (1, int(label[1:]))
    return (2, 0)


def _apple_block(
    inputs: MlbSiteInputs, shipped: pl.DataFrame, lk: _Lookups, game_index: Mapping[str, int]
) -> tuple[dict[str, list[Any]], dict[str, Any]]:
    apple = inputs.telecasts.filter(
        (pl.col("production") == "own")
        & (pl.col("network_id") == APPLE_NETWORK)
        & (pl.col("season") == APPLE_SEASON)
        & (pl.col("round").is_null() | (pl.col("round") == "regular"))
        & pl.col("booth_key").is_not_null()
    ).sort("game_date", "game_key", maintain_order=True)
    members: dict[str, list[int]] = {}
    for key, booth in apple.select("game_key", "booth_key").unique(maintain_order=True).iter_rows():
        index = game_index.get(str(key))
        if index is None:
            raise SiteBuildError("apple_booths.game_list: a booth game was not shipped")
        members.setdefault(str(booth), []).append(index)
    rows = sorted(
        inputs.apple_booths.iter_rows(named=True),
        key=lambda r: (
            _rank_order(r["rank_label"] or "Other"),
            -int(r["games"]),
            str(r["booth_key"]),
        ),
    )
    cols: dict[str, list[Any]] = {name: [] for name in MlbAppleBoothColumns.model_fields}
    any_pending = False
    for i, r in enumerate(rows):
        where = f"apple_booths[{i}]"
        pending = r["quality_status"] != "ready"
        any_pending = any_pending or pending
        analysts = r["analyst_person_ids"] or []
        cols["rank_label"].append(r["rank_label"] or "Other")
        cols["pbp"].append(lk.person(r["pbp_person_id"], where))
        cols["analyst"].append(lk.person(analysts[0], where) if analysts else None)
        cols["games"].append(int(r["games"]))
        cols["crew_listed"].append(int(r["crew_listed"]))
        cols["relay_crews"].append(int(r["relay_crews"]))
        for name, source in (
            ("raw_stakes", "stakes_raw"),
            ("adj_stakes", "stakes_adj"),
            ("adj_stakes_se", "stakes_adj_se"),
            ("raw_excitement", "excitement_raw"),
            ("adj_excitement", "excitement_adj"),
            ("adj_excitement_se", "excitement_adj_se"),
        ):
            cols[name].append(None if pending else _finite(r[source]))
        cols["raw_stakes_n"].append(int(r["stakes_n"] or 0))
        cols["strength_prior"].append(_finite(r["strength_prior"]))
        cols["low_n"].append(bool(r["low_n"]))
        cols["quality_status"].append("pending" if pending else "ready")
        cols["game_list"].append(sorted(members.get(str(r["booth_key"]), [])))
    return cols, _summary_block(inputs.apple_summary, any_pending)


def _summary_block(summary: pl.DataFrame, pending: bool) -> dict[str, Any]:
    row = summary.row(0, named=True) if summary.height else {}

    def diff(name: str) -> float | None:
        return None if pending else _finite(row.get(name))

    return {
        "lead_minus_others_stakes": diff("stakes_adj_diff"),
        "lead_minus_others_stakes_se": diff("stakes_adj_diff_se"),
        "lead_minus_others_excitement": diff("excitement_adj_diff"),
        "lead_minus_others_excitement_se": diff("excitement_adj_diff_se"),
        "n_lead": int(row.get("lead_games") or 0),
        "n_others": int(row.get("others_games") or 0),
        "rr_rated": int(row.get("rr_rated") or 0),
        "apple_games": int(row.get("apple_games") or 0),
    }


def _wikipedia_outlet_urls(telecasts: pl.DataFrame) -> dict[str, str]:
    """game_key -> the Wikipedia article an own-production outlet of that game came from."""
    rows = telecasts.filter(
        (pl.col("production") == "own")
        & (pl.col("network_source") == "wikipedia")
        & pl.col("network_source_url").is_not_null()
    ).select("game_key", "network_source_url")
    out: dict[str, str] = {}
    for key, url in rows.sort("game_key", "network_source_url").iter_rows():
        out.setdefault(str(key), str(url))
    return out


def _postseason_block(
    inputs: MlbSiteInputs, lk: _Lookups, game_index: Mapping[str, int]
) -> tuple[dict[str, list[Any]], dict[str, list[Any]]]:
    cols: dict[str, list[Any]] = {name: [] for name in MlbPostseasonColumns.model_fields}
    wiki_urls = _wikipedia_outlet_urls(inputs.telecasts)
    for i, r in enumerate(inputs.postseason.iter_rows(named=True)):
        where = f"postseason[{i}]"
        league = r["league"]
        if league is not None and league not in _LEAGUES:
            raise SiteBuildError(f"{where}.league: not a league")
        cols["season"].append(int(r["season"]))
        cols["round"].append(r["round"])
        cols["league"].append(None if league is None else _LEAGUES.index(league))
        cols["networks"].append(
            [lk.network(str(n), f"{where}.networks") for n in r["network_ids"] or []]
        )
        booths: list[list[int | None]] = []
        for booth in r["booths"] or []:
            analysts = booth["analyst_person_ids"] or []
            booths.append(
                [
                    lk.person(booth["pbp_person_id"], where),
                    lk.person(analysts[0], where) if analysts else None,
                ]
            )
        cols["booths"].append(booths)
        for name in ("games", "crew_listed", "coverage_num", "coverage_den"):
            cols[name].append(int(r[name]))
        cols["mean_excitement"].append(_finite(r["mean_excitement"]))
        cols["excitement_n"].append(int(r["excitement_n"]))
        cols["viewers_mean"].append(_finite(r["viewers_mean"]))
        cols["viewers_n"].append(int(r["viewers_n"]))
        indexes: list[int] = []
        urls: set[str] = set()
        for key in r["game_list"] or []:
            index = game_index.get(str(key))
            if index is None:
                raise SiteBuildError(f"{where}.game_list: a cell game was not shipped")
            indexes.append(index)
            if str(key) in wiki_urls:
                urls.add(wiki_urls[str(key)])
        cols["game_list"].append(sorted(indexes))
        cols["outlet_source_url"].append(min(urls) if urls else None)
    return cols, _season_coverage(inputs.postseason_seasons)


def _season_coverage(seasons: pl.DataFrame) -> dict[str, list[Any]]:
    """Per-season coverage straight from the builder's season table.

    The denominator is every postseason game of the season, including games with no
    own-production outlet, which belong to no cell; the cells add up to at most this."""
    ordered = seasons.sort("season")
    return {
        "season": [int(v) for v in ordered["season"].to_list()],
        "coverage_num": [int(v) for v in ordered["coverage_num"].to_list()],
        "coverage_den": [int(v) for v in ordered["coverage_den"].to_list()],
    }


def _team_names(lk: _Lookups, seasons: Sequence[int]) -> list[dict[str, Any]]:
    low, high = min(seasons), max(seasons)
    out: list[dict[str, Any]] = []
    for position, club in enumerate(lk.clubs.items):
        for name in sorted(
            lk.reference.clubs.names[club["id"]],
            key=lambda n: (n.season_from or 0, n.season_to or 9999),
        ):
            start = name.season_from if name.season_from is not None else MLB_FIRST_SEASON
            end = name.season_to
            if start > high or (end is not None and end < low):
                continue
            out.append(
                {
                    "club": position,
                    "name": name.display_name,
                    "short": name.nickname or name.display_name,
                    "season_start": start,
                    "season_end": end,
                }
            )
    return out


def _freshness(inputs: MlbSiteInputs, any_pending: bool) -> dict[str, Any]:
    games = inputs.games
    if games.height == 0:
        raise SiteBuildError("games: no MLB games to ship")
    season = int(games["season"].max())  # type: ignore[arg-type]
    # Retrosheet evidence is a final score or a win-expectancy excitement figure.
    has_result = pl.col("home_score").is_not_null() | pl.col("wp_excitement").is_not_null()
    through = games.filter(has_result)["season"].max()
    current = games.filter(pl.col("season") == season)
    return {
        "season": season,
        "in_progress": bool(current.filter(~has_result).height),
        "retrosheet_through_season": None if through is None else int(through),  # type: ignore[arg-type]
        "quality_pending": any_pending,
    }


# ----------------------------------------------------------------------------
# Assembly
# ----------------------------------------------------------------------------


def build_mlb_site_data(inputs: MlbSiteInputs) -> MlbSiteData:
    """Build and validate the MLB site payload; pure, deterministic, display fields only."""
    current = int(inputs.games["season"].max()) if inputs.games.height else APPLE_SEASON  # type: ignore[arg-type]
    shipped = _shipped_telecasts(inputs.telecasts)
    lk = _Lookups(inputs)
    games, lineups, game_index = _games_and_lineups(inputs, shipped, lk, current)
    apple, summary = _apple_block(inputs, shipped, lk, game_index)
    post, post_seasons = _postseason_block(inputs, lk, game_index)
    freshness = _freshness(inputs, "pending" in apple["quality_status"])
    shipped_seasons = sorted(set(games["season"])) or [current]
    payload = {
        "schema_version": MLB_SCHEMA_VERSION,
        "freshness": freshness,
        "constants": {
            "excitement_method": EXCITEMENT_METHOD,
            "stakes_method": STAKES_METHOD,
            "low_n_threshold": LOW_N,
            "coverage_bar": CREW_COVERAGE_BAR,
        },
        "lookups": {
            "clubs": lk.clubs.items,
            "team_names": _team_names(lk, shipped_seasons),
            "networks": lk.networks.items,
            "people": lk.people.items,
            "players": lk.players.items,
            "rounds": list(MLB_ROUNDS),
            "leagues": list(_LEAGUE_REFS),
            "eras": lk.eras.items,
        },
        "games": games,
        "lineups": lineups,
        "apple_booths": apple,
        "apple_summary": summary,
        "postseason": post,
        "postseason_seasons": post_seasons,
    }
    try:
        return MlbSiteData.model_validate(payload)
    except ValidationError as exc:
        raise SiteBuildError(_contract_error_summary(exc)) from None


def mlb_site_payload_bytes(site: MlbSiteData) -> bytes:
    """Compact, key-sorted JSON with no trailing newline; identical inputs, identical bytes.

    `allow_nan=False`: NaN or Infinity would be invalid JSON. The contract already
    rejects them, so this only guards against drift."""
    payload = site.model_dump(mode="json")
    return json.dumps(payload, separators=(",", ":"), sort_keys=True, allow_nan=False).encode(
        "utf-8"
    )


def check_mlb_serif(site: MlbSiteData) -> None:
    """Raise SiteBuildError when a lookup name uses a character the serif subset lacks."""
    lookups = site.lookups
    for lookup, rows, fields in (
        ("clubs", lookups.clubs, ("name",)),
        ("team_names", lookups.team_names, ("name", "short")),
        ("leagues", lookups.leagues, ("name",)),
        ("people", lookups.people, ("name",)),
    ):
        check_serif_text(lookup_names(rows, *fields), where=f"mlb-data.json lookups.{lookup}")


def write_mlb_site_data(paths: DataPaths, site: MlbSiteData) -> str:
    """Write `processed/mlb-data.json` atomically; returns its vault-relative path."""
    check_mlb_serif(site)
    atomic_write_bytes(paths.vault / MLB_SITE_DATA_PATH, mlb_site_payload_bytes(site))
    return MLB_SITE_DATA_PATH


def mlb_site_counts(site: MlbSiteData) -> dict[str, int]:
    """The count-only numbers a commit message may carry."""
    return {
        "games": len(site.games.season),
        "lineups": sum(1 for s in site.games.lineup_status if s == "present"),
    }


def build_and_write_mlb_site_data(paths: DataPaths, reference_directory: Path) -> str:
    """Build from the vault tables and write the file; the hook `mlb build --site-data` calls."""
    site = build_mlb_site_data(load_mlb_site_inputs(paths, reference_directory))
    return write_mlb_site_data(paths, site)
