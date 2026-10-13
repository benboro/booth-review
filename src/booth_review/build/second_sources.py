"""Second viewership sources (04.19 D-05..D-09, D-21).

A second-source row (Sports Media Watch, The TV Ratings Guide, Awful
Announcing and ESPN Press Room, in that headline order) is matched to an EXISTING main-feed
telecast through the team crosswalk's candidate sets, held when its network
disagrees with ours, settled against duplicates and season-top rows, and gated
per (source, season) against Ratings Reference's headline figures. Nothing here
creates a telecast. Review rows go to the vault's interim/ folder through the
caller; this module never prints, and every error message is count-only.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import cast

import polars as pl

from booth_review.config import DataPaths
from booth_review.errors import ReferenceTableError
from booth_review.reference import read_reference_csv_numbered
from booth_review.resolve.diagnose import (
    UNMATCHED_COLUMNS,
    UnmatchedRow,
    UnresolvedTeamRow,
    unmatched_row,
)
from booth_review.resolve.games import GameIndex
from booth_review.resolve.headline import is_usable_value, select_headline
from booth_review.resolve.names import to_et_date
from booth_review.resolve.networks import NetworkTable, primary_network
from booth_review.resolve.overrides import GameOverride
from booth_review.resolve.teams import TeamResolver, TeamSource
from booth_review.sources.cfbd.parser import CfbdGame
from booth_review.sources.known_disagreements import (
    POST_SEASONS,
    PostSource,
    known_path,
    load_known,
    read_cached_posts,
)
from booth_review.sources.ratingsref.parser import RRClaim, RRRecord
from booth_review.sources.second_rows import (
    SECOND_SOURCE_PUBLISHERS,
    RejectedPage,
    SecondSourceRow,
    host_matches,
)
from booth_review.sources.smw.chart_order import identify_season_page, load_chart_order_csv
from booth_review.sources.smw.rows import load_rows_csv, smw_second_rows

REVIEW_UNMATCHED_COLUMNS = UNMATCHED_COLUMNS
REVIEW_NETWORK_COLUMNS = (
    "source",
    "season",
    "pointer",
    "cfbd_game_id",
    "date_et",
    "chart_network_raw",
    "chart_network_id",
    "our_network_ids",
)
REVIEW_AGREEMENT_COLUMNS = (
    "source",
    "season",
    "pointer",
    "telecast_id",
    "second_value",
    "rr_value",
    "pct_diff",
    "status",
)
REVIEW_CONFLICT_COLUMNS = (
    "source",
    "season",
    "telecast_id",
    "kept_pointer",
    "other_pointer",
    "kept_value",
    "other_value",
    "kind",
)
REVIEW_GATE_COLUMNS = (
    "source",
    "season",
    "rows",
    "figures",
    "matched",
    "loaded",
    "held_network",
    "out_of_scope",
    "no_telecast",
    "excluded_simulcast",
    "excluded_multi_feed",
    "excluded_regional",
    "excluded_non_nielsen",
    "excluded_non_game",
    "no_figure",
    "unlinked_prose",
    "ignored",
    "shared",
    "within_3pct",
    "logged",
    "unexplained",
    "stale_known",
    "rejected_pages",
    "superseded",
    "excluded_override",
    "status",
)
REVIEW_REJECTED_COLUMNS = ("source", "season", "path", "reason")

REVIEW_UNMATCHED = "review_second_source_unmatched"
REVIEW_NETWORK = "review_second_source_network"
REVIEW_AGREEMENT = "review_second_source_agreement"
REVIEW_CONFLICTS = "review_second_source_conflicts"
REVIEW_GATE = "review_second_source_gate"
# Cached pages the build skipped (no on-host canonical URL, or the parser
# refuses them): vault paths and reasons, never printed.
REVIEW_REJECTED = "review_second_source_rejected"
SECOND_SOURCE_REVIEW_NAMES = (
    REVIEW_UNMATCHED,
    REVIEW_NETWORK,
    REVIEW_AGREEMENT,
    REVIEW_CONFLICTS,
    REVIEW_GATE,
    REVIEW_REJECTED,
)
NETWORK_ACCEPT_COLUMNS = ("source", "season", "pointer", "reason")
GATE_OVERRIDE_COLUMNS = ("source", "season", "max_logged", "reason")

# D-02: a second figure within 3% of the RR headline agrees.
AGREEMENT_TOLERANCE = 0.03
# D-02: a season may log this many explained misses before it needs a recorded override.
DEFAULT_MAX_LOGGED = 2
_MAX_LOGGED_RANGE = (3, 20)
_REASON_MAX_LEN = 80

_EXCLUDED_KINDS = {
    "simulcast": "excluded_simulcast",
    "multi_feed": "excluded_multi_feed",
    "regional": "excluded_regional",
    "non_nielsen": "excluded_non_nielsen",
    "non_game": "excluded_non_game",
    "no_figure": "no_figure",
}
_WEEKLY_CLASS_EXCLUDED = "season_top"
# Sources whose needs_review rows are counted on the gate instead of listed for
# review: AA and ESPN Press Room prose mentions the parser can't tie to one game
# (season or window averages, other-season comparisons, multi-game sentences,
# non-game shows, whole-million figures). They never carry a figure, so listing
# them asks the user nothing (user, 04.19-35).
COUNTED_REVIEW_SOURCES: frozenset[str] = frozenset({"aa", "espnpr"})

SourceSeason = tuple[str, int]


# -- Reference tables ----------------------------------------------------------------------


def _parse_ascii_int(cell: str) -> int | None:
    if not (cell.isascii() and cell.isdecimal()):
        return None
    return int(cell)


def _check_source_season(path: Path, line_no: int, raw: Mapping[str, str]) -> tuple[str, int]:
    source = raw["source"]
    if source not in SECOND_SOURCE_PUBLISHERS:
        raise ReferenceTableError(f"{path.name}: line {line_no}: source is not a second source")
    season = _parse_ascii_int(raw["season"])
    if season is None:
        raise ReferenceTableError(f"{path.name}: line {line_no}: season must be an integer")
    reason = raw["reason"]
    if not reason or len(reason) > _REASON_MAX_LEN:
        raise ReferenceTableError(
            f"{path.name}: line {line_no}: reason must be 1-{_REASON_MAX_LEN} characters"
        )
    return source, season


def load_network_accepts(reference_dir: Path) -> frozenset[tuple[str, int, str]]:
    """Read second_source_network_accepts.csv (not required): (source, season,
    pointer) rows whose chart network we accept against our own (D-06)."""
    path = reference_dir / "second_source_network_accepts.csv"
    accepts: set[tuple[str, int, str]] = set()
    for line_no, raw in read_reference_csv_numbered(path, NETWORK_ACCEPT_COLUMNS, required=False):
        source, season = _check_source_season(path, line_no, raw)
        pointer = raw["pointer"]
        if not pointer:
            raise ReferenceTableError(f"{path.name}: line {line_no}: pointer must not be empty")
        key = (source, season, pointer)
        if key in accepts:
            raise ReferenceTableError(f"{path.name}: line {line_no}: duplicate row")
        accepts.add(key)
    return frozenset(accepts)


def load_gate_overrides(reference_dir: Path) -> dict[tuple[str, int], int]:
    """Read second_source_gate_overrides.csv (not required): the user's recorded
    cap on logged misses for one (source, season) (D-02)."""
    path = reference_dir / "second_source_gate_overrides.csv"
    overrides: dict[tuple[str, int], int] = {}
    for line_no, raw in read_reference_csv_numbered(path, GATE_OVERRIDE_COLUMNS, required=False):
        source, season = _check_source_season(path, line_no, raw)
        max_logged = _parse_ascii_int(raw["max_logged"])
        low, high = _MAX_LOGGED_RANGE
        if max_logged is None or not low <= max_logged <= high:
            raise ReferenceTableError(
                f"{path.name}: line {line_no}: max_logged must be an integer {low}-{high}"
            )
        if (source, season) in overrides:
            raise ReferenceTableError(f"{path.name}: line {line_no}: duplicate (source, season)")
        overrides[(source, season)] = max_logged
    return overrides


# -- Vault inputs --------------------------------------------------------------------------


@dataclass(frozen=True)
class SecondSourceInputs:
    rows: tuple[SecondSourceRow, ...]
    # (source, season) -> pointers whose RR disagreement the user explained.
    known: dict[SourceSeason, frozenset[str]]
    # Cached pages skipped because they lack an on-host canonical URL or don't parse.
    rejected: tuple[RejectedPage, ...] = ()
    # (source, season) -> post lines or figure mentions the parsers ignored
    # (non-football rows, peaks, streaming numbers): a template change that
    # makes every line ignored shows on the gate row instead of vanishing.
    ignored: dict[SourceSeason, int] = field(default_factory=dict)


@dataclass
class _LoaderResult:
    rows: list[SecondSourceRow] = field(default_factory=list)
    known: dict[SourceSeason, frozenset[str]] = field(default_factory=dict)
    rejected: list[RejectedPage] = field(default_factory=list)
    ignored: dict[SourceSeason, int] = field(default_factory=dict)


def _load_smw(paths: DataPaths, seasons: Sequence[int] | None) -> _LoaderResult:
    from booth_review.sources.smw.diff import KNOWN_DISAGREEMENT_COLUMNS

    result = _LoaderResult()
    root = paths.raw / "smw"
    if not root.is_dir():
        return result
    for folder in sorted(root.iterdir()):
        season = _parse_ascii_int(folder.name)
        if season is None or (seasons is not None and season not in seasons):
            continue
        rows_path = folder / "transcription" / "rows.csv"
        if not rows_path.is_file():
            continue
        page = folder / "season-page.html"
        if not page.is_file():
            raise ReferenceTableError(f"smw {season}: season-page.html is missing")
        identified = identify_season_page(page.read_text(encoding="utf-8", errors="replace"))
        if identified is None or identified[0] != season:
            raise ReferenceTableError(f"smw {season}: season-page.html does not name the season")
        url = identified[1]
        if not host_matches("smw", url):
            raise ReferenceTableError(f"smw {season}: season page URL has an unexpected host")
        order = load_chart_order_csv(folder / "chart_order.csv")
        result.rows.extend(
            smw_second_rows(load_rows_csv(rows_path), order, season=season, source_url=url)
        )
        known_path = folder / "transcription" / "known_disagreements.csv"
        if known_path.is_file():
            result.known[("smw", season)] = frozenset(
                f"{raw['chart_file']}:{raw['row']}"
                for _, raw in read_reference_csv_numbered(
                    known_path, KNOWN_DISAGREEMENT_COLUMNS, required=True
                )
            )
    return result


def _load_posts(
    source: PostSource, paths: DataPaths, seasons: Sequence[int] | None
) -> _LoaderResult:
    """Every cached post of `source` for 2021-2024 (raw/<source>/<season>/posts/*.html;
    ESPN Press Room: ratings/*.html), parsed into rows, plus that season's
    known_disagreements.csv (D-02, D-10, D-12). A post that can't be read is
    skipped and returned in `rejected`."""
    result = _LoaderResult()
    root = paths.raw / source
    if not root.is_dir():
        return result
    for folder in sorted(root.iterdir()):
        season = _parse_ascii_int(folder.name)
        if season is None or season not in POST_SEASONS:
            continue
        if seasons is not None and season not in seasons:
            continue
        cached = read_cached_posts(paths, source, season)
        result.rows.extend(cached.rows)
        result.rejected.extend(cached.rejected)
        result.ignored[(source, season)] = cached.ignored
        known_file = known_path(paths, source, season)
        if known_file.is_file():
            result.known[(source, season)] = load_known(known_file)
    return result


def _load_tvrg(paths: DataPaths, seasons: Sequence[int] | None) -> _LoaderResult:
    return _load_posts("tvrg", paths, seasons)


def _load_aa(paths: DataPaths, seasons: Sequence[int] | None) -> _LoaderResult:
    return _load_posts("aa", paths, seasons)


def _load_espnpr(paths: DataPaths, seasons: Sequence[int] | None) -> _LoaderResult:
    """Hand-imported ESPN Press Room ratings releases (raw/espnpr/<season>/ratings/);
    the commentators pages and weekly releases beside them are crews, never read
    here (D-12, D-13)."""
    return _load_posts("espnpr", paths, seasons)


# Headline order (D-09) lives in resolve/headline.py SOURCE_ORDER; ESPN Press Room is last.
SECOND_SOURCE_LOADERS: tuple[Callable[[DataPaths, Sequence[int] | None], _LoaderResult], ...] = (
    _load_smw,
    _load_tvrg,
    _load_aa,
    _load_espnpr,
)


def load_second_source_inputs(
    paths: DataPaths, seasons: Sequence[int] | None = None
) -> SecondSourceInputs:
    rows: list[SecondSourceRow] = []
    known: dict[SourceSeason, frozenset[str]] = {}
    rejected: list[RejectedPage] = []
    ignored: dict[SourceSeason, int] = {}
    for loader in SECOND_SOURCE_LOADERS:
        loaded = loader(paths, seasons)
        rows.extend(loaded.rows)
        known.update(loaded.known)
        rejected.extend(loaded.rejected)
        ignored.update(loaded.ignored)
    return SecondSourceInputs(
        rows=tuple(rows), known=known, rejected=tuple(rejected), ignored=ignored
    )


# -- Result types --------------------------------------------------------------------------


@dataclass(frozen=True)
class GateStatus:
    source: str
    season: int
    rows: int
    figures: int
    matched: int
    loaded: int
    held_network: int
    out_of_scope: int
    no_telecast: int
    excluded_simulcast: int
    excluded_multi_feed: int
    excluded_regional: int
    excluded_non_nielsen: int
    excluded_non_game: int
    no_figure: int
    unlinked_prose: int
    shared: int
    within_3pct: int
    logged: int
    unexplained: int
    stale_known: int
    status: str  # passed | withheld | no_shared
    # Cached pages of this (source, season) skipped as unreadable (CR-01).
    rejected_pages: int = 0
    # Post lines or figure mentions the parsers ignored (WR-01).
    ignored: int = 0
    # Rows replaced by a later chart (D-08) and rows game_overrides.csv excludes
    # (WR-02), so the gate row's buckets add up to `rows`.
    superseded: int = 0
    excluded_override: int = 0

    def as_row(self) -> dict[str, object]:
        return {column: getattr(self, column) for column in REVIEW_GATE_COLUMNS}


@dataclass(frozen=True)
class SecondSourceResult:
    telecasts: pl.DataFrame
    claims_by_telecast: dict[str, list[RRClaim]]
    season_counts: dict[int, dict[str, int]]
    review_rows: dict[str, tuple[tuple[str, ...], list[dict[str, object]]]]
    unresolved_rows: list[UnresolvedTeamRow]
    gates: tuple[GateStatus, ...]
    counts: dict[str, int]
    rejected_pages: tuple[RejectedPage, ...] = ()


@dataclass(frozen=True)
class _Winner:
    row: SecondSourceRow
    telecast_id: str
    viewers: int


def rejected_page_rows(pages: Sequence[RejectedPage]) -> list[dict[str, object]]:
    """interim/review_second_source_rejected.csv rows, in path order."""
    return [
        {"source": p.source, "season": p.season, "path": p.path, "reason": p.reason}
        for p in sorted(pages, key=lambda p: p.path)
    ]


# -- Matching ------------------------------------------------------------------------------


def find_games(
    season: int,
    date_et: date | None,
    away_ids: tuple[int, ...],
    home_ids: tuple[int, ...],
    index: GameIndex,
) -> tuple[list[CfbdGame], str]:
    """(games, confidence) for one team-candidate pair: confidence is exact,
    date-shift (a day either way), ambiguous or none. With no date, the pair
    must have exactly one game that season (season-top rows)."""
    seen: dict[int, CfbdGame] = {}
    for away in away_ids:
        for home in home_ids:
            if away == home:
                continue
            for game in index.games_by_pair(season, frozenset({away, home})):
                seen.setdefault(game.id, game)
    games = [seen[key] for key in sorted(seen)]
    if date_et is None:
        if len(games) == 1:
            return games, "exact"
        return [], "ambiguous" if games else "none"
    exact = [g for g in games if to_et_date(g.start_date) == date_et]
    if exact:
        return (exact, "exact") if len(exact) == 1 else ([], "ambiguous")
    shifted = [g for g in games if abs((to_et_date(g.start_date) - date_et).days) == 1]
    if shifted:
        return (shifted, "date-shift") if len(shifted) == 1 else ([], "ambiguous")
    return [], "none"


def match_row_to_game(
    source: str,
    season: int,
    date_et: date | None,
    away_raw: str,
    home_raw: str,
    *,
    resolver: TeamResolver,
    index: GameIndex,
    overrides: Mapping[tuple[str, int, str], GameOverride],
    pointer: str,
) -> tuple[CfbdGame | None, str]:
    """The CFBD game one second-source listing names, through game_overrides.csv
    (keyed by source, season and pointer) and then the team crosswalk's
    candidate sets plus the ET date (a day either way).

    Returns (game, reason). Matched: reason is override, exact or date-shift.
    Unmatched (game None): excluded_override, unresolved_team, ambiguous or
    none. An override naming an unknown game raises (count-only).
    """
    override = overrides.get((source, season, pointer))
    if override is not None:
        if override.action == "exclude":
            return None, "excluded_override"
        game = index.by_id(override.cfbd_game_id) if override.cfbd_game_id is not None else None
        if game is None:
            raise ReferenceTableError(
                "game_overrides.csv: 1 second-source row names an unknown game"
            )
        return game, "override"
    team_source = cast("TeamSource", source)
    away_ids = resolver.resolve_candidates(team_source, away_raw, season)
    home_ids = resolver.resolve_candidates(team_source, home_raw, season)
    if not away_ids or not home_ids:
        return None, "unresolved_team"
    found, confidence = find_games(season, date_et, away_ids, home_ids, index)
    if not found:
        return None, "ambiguous" if confidence == "ambiguous" else "none"
    return found[0], confidence


def _iso(day: date | None) -> str:
    return day.isoformat() if day is not None else ""


def _unmatched(row: SecondSourceRow, confidence: str, reason: str) -> dict[str, object]:
    return dict(
        unmatched_row(
            UnmatchedRow(
                source=row.source,
                season=row.season,
                pointer=row.pointer,
                date_et=_iso(row.date_et),
                away_raw=row.away_raw,
                home_raw=row.home_raw,
                network_raw=row.network_raw,
                confidence=confidence,
                reason=reason,
            )
        )
    )


def _round_value(value: int | float) -> object:
    return int(value) if float(value).is_integer() else value


def _settle(
    candidates: list[_Winner], conflicts: list[dict[str, object]]
) -> _Winner:  # candidates for one (source, telecast), non-empty
    weekly = [w for w in candidates if w.row.chart_kind != _WEEKLY_CLASS_EXCLUDED]
    pool = weekly or candidates
    kept = max(pool, key=lambda w: (w.row.rank, w.row.pointer))
    for other in sorted(candidates, key=lambda w: w.row.pointer):
        if other is kept or other.viewers == kept.viewers:
            continue
        kind = (
            "season_top"
            if other.row.chart_kind == _WEEKLY_CLASS_EXCLUDED and weekly
            else ("duplicate")
        )
        conflicts.append(
            {
                "source": kept.row.source,
                "season": kept.row.season,
                "telecast_id": kept.telecast_id,
                "kept_pointer": kept.row.pointer,
                "other_pointer": other.row.pointer,
                "kept_value": kept.viewers,
                "other_value": other.viewers,
                "kind": kind,
            }
        )
    return kept


def _superseded_conflicts(
    rows: Sequence[SecondSourceRow],
    superseded: Sequence[SecondSourceRow],
    candidates: Mapping[tuple[str, str], Sequence[_Winner]],
) -> list[dict[str, object]]:
    """A conflict row (kind "superseded") for each superseded row whose figure
    differs from the row that replaces it (D-08, D-21: every conflict is
    reported). `telecast_id` is the replacing row's telecast when it matched
    one, else empty; a missing figure is an empty cell."""
    by_pointer = {(r.source, r.season, r.pointer): r for r in rows}
    placed = {
        (w.row.source, w.row.season, w.row.pointer): w.telecast_id
        for group in candidates.values()
        for w in group
    }
    out: list[dict[str, object]] = []
    for row in superseded:
        key = (row.source, row.season, row.superseded_by)
        target = by_pointer.get(key)
        if target is None or target.viewers == row.viewers:
            continue
        out.append(
            {
                "source": row.source,
                "season": row.season,
                "telecast_id": placed.get(key, ""),
                "kept_pointer": target.pointer,
                "other_pointer": row.pointer,
                "kept_value": target.viewers if target.viewers is not None else "",
                "other_value": row.viewers if row.viewers is not None else "",
                "kind": "superseded",
            }
        )
    return out


def apply_second_sources(
    telecasts: pl.DataFrame,
    records_by_telecast: Mapping[str, Sequence[RRRecord]],
    inputs: SecondSourceInputs,
    *,
    resolver: TeamResolver,
    index: GameIndex,
    networks: NetworkTable,
    overrides: Mapping[tuple[str, int, str], GameOverride],
    accepts: frozenset[tuple[str, int, str]],
    gate_overrides: Mapping[tuple[str, int], int],
    fbs_game_ids: Collection[int],
    season_counts: Mapping[int, Mapping[str, int]],
) -> SecondSourceResult:
    """Match, hold, settle and gate every second-source row; see module docstring.

    The telecasts frame gains no row (D-07); only `rated` can flip. Inputs are
    not mutated.
    """
    mains: dict[int, list[tuple[str, str | None]]] = {}
    for tel in telecasts.filter(pl.col("feed_type") == "main").iter_rows(named=True):
        mains.setdefault(tel["game_id"], []).append((tel["telecast_id"], tel["network_id"]))
    telecast_info = {
        row["telecast_id"]: row
        for row in telecasts.select("telecast_id", "season", "rated", "crew_matched").iter_rows(
            named=True
        )
    }

    tally: dict[SourceSeason, Counter[str]] = {}
    unmatched_rows: list[dict[str, object]] = []
    network_rows: list[dict[str, object]] = []
    conflict_rows: list[dict[str, object]] = []
    agreement_rows: list[dict[str, object]] = []
    unresolved: dict[tuple[str, str], list[int]] = {}
    candidates: dict[tuple[str, str], list[_Winner]] = {}
    superseded_rows: list[SecondSourceRow] = []

    def unresolved_name(row: SecondSourceRow, raw: str) -> None:
        unresolved.setdefault((row.source, raw), []).append(row.season)

    # A season whose every page was rejected still gets a gate row, so the
    # rejection shows in the build output.
    for page in inputs.rejected:
        tally.setdefault((page.source, page.season), Counter())["rejected_pages"] += 1
    for ignored_key, ignored in inputs.ignored.items():
        if ignored:
            tally.setdefault(ignored_key, Counter())["ignored"] += ignored

    for row in inputs.rows:
        tally_key = (row.source, row.season)
        count = tally.setdefault(tally_key, Counter())
        count["rows"] += 1
        if row.superseded:
            count["superseded"] += 1
            superseded_rows.append(row)
            continue
        if row.kind in _EXCLUDED_KINDS:
            count[_EXCLUDED_KINDS[row.kind]] += 1
            continue
        if row.kind == "needs_review" and row.source in COUNTED_REVIEW_SOURCES:
            count["unlinked_prose"] += 1
            continue
        if row.kind in ("unknown_suffix", "needs_review"):
            unmatched_rows.append(_unmatched(row, "", row.kind))
            count["unmatched"] += 1
            continue
        if row.viewers is None or not is_usable_value(float(row.viewers)):
            count["no_figure"] += 1
            continue
        count["figures"] += 1

        if (
            (row.source, row.season, row.pointer) not in overrides
            and row.date_et is None
            and row.chart_kind != _WEEKLY_CLASS_EXCLUDED
        ):
            unmatched_rows.append(_unmatched(row, "", "no_date"))
            count["unmatched"] += 1
            continue
        game, reason = match_row_to_game(
            row.source,
            row.season,
            row.date_et,
            row.away_raw,
            row.home_raw,
            resolver=resolver,
            index=index,
            overrides=overrides,
            pointer=row.pointer,
        )
        if game is None:
            if reason == "excluded_override":
                count["excluded_override"] += 1
                continue
            if reason == "unresolved_team":
                for raw in (row.away_raw, row.home_raw):
                    if not resolver.resolve_candidates(row.source, raw, row.season):
                        unresolved_name(row, raw)
                unmatched_rows.append(_unmatched(row, "", "unresolved_team"))
                count["unmatched"] += 1
                continue
            unmatched_rows.append(_unmatched(row, reason, reason))
            count["unmatched"] += 1
            if reason == "ambiguous":
                count["ambiguous"] += 1
            continue
        count["matched"] += 1

        if game.id not in fbs_game_ids:
            count["out_of_scope"] += 1
            continue
        game_mains = mains.get(game.id, [])
        if not game_mains:
            count["no_telecast"] += 1
            continue

        chart = primary_network([row.network_raw] if row.network_raw else [], row.season, networks)
        if chart.network_id is None:
            unmatched_rows.append(_unmatched(row, "", "unmapped_network"))
            count["unmatched"] += 1
            continue
        target: str | None = next((tid for tid, nid in game_mains if nid == chart.network_id), None)
        if (
            target is None
            and (row.source, row.season, row.pointer) in accepts
            and len(game_mains) == 1
        ):
            target = game_mains[0][0]
        if target is None:
            network_rows.append(
                {
                    "source": row.source,
                    "season": row.season,
                    "pointer": row.pointer,
                    "cfbd_game_id": game.id,
                    "date_et": _iso(to_et_date(game.start_date)),
                    "chart_network_raw": row.network_raw,
                    "chart_network_id": chart.network_id,
                    "our_network_ids": "|".join(sorted(str(nid) for _, nid in game_mains)),
                }
            )
            count["held_network"] += 1
            continue
        candidates.setdefault((row.source, target), []).append(
            _Winner(row=row, telecast_id=target, viewers=row.viewers)
        )

    winners: list[_Winner] = [
        _settle(group, conflict_rows) for _, group in sorted(candidates.items())
    ]
    conflict_rows.extend(_superseded_conflicts(inputs.rows, superseded_rows, candidates))

    # -- Gate (D-02) --
    by_key: dict[SourceSeason, list[_Winner]] = {}
    for winner in winners:
        by_key.setdefault((winner.row.source, winner.row.season), []).append(winner)

    gates: list[GateStatus] = []
    loaded_winners: list[_Winner] = []
    for gate_key in sorted(tally):
        source, season = gate_key
        count = tally[gate_key]
        known = inputs.known.get(gate_key, frozenset())
        shared = within = logged = unexplained = 0
        missed: set[str] = set()
        for winner in by_key.get(gate_key, []):
            records = records_by_telecast.get(winner.telecast_id, ())
            pooled = [claim for record in records for claim in record.claims]
            headline = select_headline(pooled) if pooled else None
            if headline is None or headline.value is None:
                continue
            rr_value = headline.value
            shared += 1
            pct = abs(winner.viewers - rr_value) / rr_value
            pointer = winner.row.pointer
            if round(pct, 9) <= AGREEMENT_TOLERANCE:
                within += 1
                status = "ok"
            elif pointer in known:
                logged += 1
                missed.add(pointer)
                status = "miss_logged"
            else:
                unexplained += 1
                missed.add(pointer)
                status = "miss_unexplained"
            agreement_rows.append(
                {
                    "source": source,
                    "season": season,
                    "pointer": pointer,
                    "telecast_id": winner.telecast_id,
                    "second_value": winner.viewers,
                    "rr_value": _round_value(rr_value),
                    "pct_diff": round(pct, 4),
                    "status": status,
                }
            )
        cap = gate_overrides.get(gate_key, DEFAULT_MAX_LOGGED)
        if shared == 0:
            gate_status = "no_shared"
        elif unexplained == 0 and logged <= cap:
            gate_status = "passed"
        else:
            gate_status = "withheld"
        loads = gate_status != "withheld"
        if loads:
            loaded_winners.extend(by_key.get(gate_key, []))
        gates.append(
            GateStatus(
                source=source,
                season=season,
                rows=count["rows"],
                figures=count["figures"],
                matched=count["matched"],
                loaded=len(by_key.get(gate_key, [])) if loads else 0,
                held_network=count["held_network"],
                out_of_scope=count["out_of_scope"],
                no_telecast=count["no_telecast"],
                excluded_simulcast=count["excluded_simulcast"],
                excluded_multi_feed=count["excluded_multi_feed"],
                excluded_regional=count["excluded_regional"],
                excluded_non_nielsen=count["excluded_non_nielsen"],
                excluded_non_game=count["excluded_non_game"],
                no_figure=count["no_figure"],
                unlinked_prose=count["unlinked_prose"],
                shared=shared,
                within_3pct=within,
                logged=logged,
                unexplained=unexplained,
                stale_known=len(known - missed),
                status=gate_status,
                rejected_pages=count["rejected_pages"],
                ignored=count["ignored"],
                superseded=count["superseded"],
                excluded_override=count["excluded_override"],
            )
        )

    # -- Claims and the rated flip --
    claims_by_telecast: dict[str, list[RRClaim]] = {}
    new_counts: dict[int, dict[str, int]] = {s: dict(c) for s, c in season_counts.items()}
    for bucket in new_counts.values():
        bucket.setdefault("rated_second_source", 0)
    flip_ids: list[str] = []
    for winner in sorted(loaded_winners, key=lambda w: (w.row.source, w.row.season, w.row.pointer)):
        row = winner.row
        claim = RRClaim.model_validate(
            {
                "metric_type": "avg_audience",
                "status": "final",
                "value": float(winner.viewers),
                "unit": "viewers",
                "publisher": SECOND_SOURCE_PUBLISHERS[row.source],
                "source_url": row.source_url,
                "measured_by": None,
                "id": f"{row.source}:{row.season}:{row.pointer}",
                "source": row.source,
            }
        )
        claims_by_telecast.setdefault(winner.telecast_id, []).append(claim)
        info = telecast_info[winner.telecast_id]
        if (
            not info["rated"]
            and winner.telecast_id not in flip_ids
            and is_usable_value(claim.value)
        ):
            flip_ids.append(winner.telecast_id)
            bucket = new_counts.setdefault(info["season"], {})
            bucket["rated_telecasts"] = bucket.get("rated_telecasts", 0) + 1
            bucket["rated_second_source"] = bucket.get("rated_second_source", 0) + 1
            if info["crew_matched"]:
                bucket["rated_with_crew"] = bucket.get("rated_with_crew", 0) + 1

    telecasts_out = telecasts
    if flip_ids:
        telecasts_out = telecasts.with_columns(
            pl.when(pl.col("telecast_id").is_in(flip_ids))
            .then(True)
            .otherwise(pl.col("rated"))
            .alias("rated")
        )

    # -- Review rows and counts --
    def ordered(rows: list[dict[str, object]], *keys: str) -> list[dict[str, object]]:
        return sorted(rows, key=lambda r: tuple(str(r[k]).zfill(8) for k in keys))

    review_rows: dict[str, tuple[tuple[str, ...], list[dict[str, object]]]] = {
        REVIEW_UNMATCHED: (
            REVIEW_UNMATCHED_COLUMNS,
            ordered(unmatched_rows, "source", "season", "pointer"),
        ),
        REVIEW_NETWORK: (
            REVIEW_NETWORK_COLUMNS,
            ordered(network_rows, "source", "season", "pointer"),
        ),
        REVIEW_AGREEMENT: (
            REVIEW_AGREEMENT_COLUMNS,
            ordered(agreement_rows, "source", "season", "pointer"),
        ),
        REVIEW_CONFLICTS: (
            REVIEW_CONFLICT_COLUMNS,
            ordered(conflict_rows, "source", "season", "telecast_id", "other_pointer"),
        ),
        REVIEW_GATE: (REVIEW_GATE_COLUMNS, [gate.as_row() for gate in gates]),
        REVIEW_REJECTED: (
            REVIEW_REJECTED_COLUMNS,
            rejected_page_rows(inputs.rejected),
        ),
    }
    unresolved_out = [
        UnresolvedTeamRow(
            source=source,
            season_first=min(seasons),
            season_last=max(seasons),
            raw_name=raw,
            occurrences=len(seasons),
            suggested_canonical="",
            suggested_cfbd_team_id="",
        )
        for (source, raw), seasons in sorted(unresolved.items())
    ]
    totals = Counter[str]()
    for count in tally.values():
        totals["held_network"] += count["held_network"]
        totals["unmatched"] += count["unmatched"]
        totals["ambiguous"] += count["ambiguous"]
        totals["out_of_scope"] += count["out_of_scope"]
        totals["no_telecast"] += count["no_telecast"]
        totals["superseded"] += count["superseded"]
        totals["excluded_override"] += count["excluded_override"]
    counts = {
        "loaded": sum(gate.loaded for gate in gates),
        "held_network": totals["held_network"],
        "unmatched": totals["unmatched"],
        "ambiguous": totals["ambiguous"],
        "out_of_scope": totals["out_of_scope"],
        "no_telecast": totals["no_telecast"],
        "withheld_seasons": sum(1 for gate in gates if gate.status == "withheld"),
        "conflicts": len(conflict_rows),
        "rejected_pages": len(inputs.rejected),
        "superseded": totals["superseded"],
        "excluded_override": totals["excluded_override"],
    }
    return SecondSourceResult(
        telecasts=telecasts_out,
        claims_by_telecast=claims_by_telecast,
        season_counts=new_counts,
        review_rows=review_rows,
        unresolved_rows=unresolved_out,
        gates=tuple(gates),
        counts=counts,
        rejected_pages=inputs.rejected,
    )
