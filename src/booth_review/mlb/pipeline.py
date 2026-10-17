"""The MLB build behind `booth-review mlb build` (999.4 D-23 pattern).

Everything runs inside one `VaultRepo.lock()`: load the MLB inputs, build the game and
telecast tables, assign crews, match Ratings Reference records, train the win-expectancy
table and score per-game excitement and pregame stakes from Retrosheet, build the Apple
and postseason result tables, write the processed tables and the interim review files,
then make one path-scoped, count-only commit. Tables go to the vault only; nothing is
published.

Retrosheet feeds three things whatever seasons are asked for: the win-expectancy table
(trained on the regular seasons in WE_TRAIN_SEASONS), the pooled stakes baseline
(STAKES_BASELINE_SEASONS) and the strength prior (STRENGTH_PRIOR_SEASON). Those seasons
are loaded for modelling only; the game, telecast and booth tables cover `seasons`.
Until Retrosheet 2026 is collected the 2026 stakes and excitement stay null and
`quality_pending` is 1 (D-06).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Final

import polars as pl

from booth_review.build.mlb_site_data import build_and_write_mlb_site_data
from booth_review.config import DataPaths
from booth_review.errors import BoothReviewError, ParseError
from booth_review.flags.era import load_eras
from booth_review.mlb.apple import build_apple_booths
from booth_review.mlb.constants import (
    MLB_CURRENT_SEASON,
    STAKES_BASELINE_SEASONS,
    WE_MIN_TRAIN_GAMES,
    WE_TRAIN_SEASONS,
)
from booth_review.mlb.crews import (
    CrewDisagreement,
    PeopleReview,
    assign_crews,
    people_review_names,
    write_crew_disagreements,
)
from booth_review.mlb.games import (
    build_mlb_games,
    build_postseason_map,
    write_postseason_map_review,
)
from booth_review.mlb.inputs import MlbInputs, Review, load_mlb_inputs
from booth_review.mlb.layout import (
    MLB_WIKIPEDIA_LIST_PAGES,
    mlb_rr_path,
    mlb_wikipedia_list_url,
)
from booth_review.mlb.lineups import starting_lineups
from booth_review.mlb.listings import game_key, listings_to_telecasts
from booth_review.mlb.people import register_mlb_people, review_path
from booth_review.mlb.postseason import build_postseason_booths
from booth_review.mlb.reference import MlbReference, load_mlb_reference
from booth_review.mlb.rr_match import RRGameMatch, RRReview, match_mlb_rr
from booth_review.mlb.standings import (
    STRENGTH_PRIOR_SEASON,
    daily_standings,
    game_strength_prior,
    pregame_stakes,
    strength_prior,
    team_divisions,
)
from booth_review.mlb.tables import (
    LINEUPS_TABLE,
    REVIEW_ROW_COLUMNS,
    WE_TABLE,
    review_rows,
    write_mlb_reviews,
    write_mlb_tables,
)
from booth_review.mlb.teams import MlbNetworkResolver, MlbTeamResolver
from booth_review.mlb.winexp import WeTable, build_we_table, excitement_by_game
from booth_review.sources.ratingsref.parser import RRRecord, parse_record
from booth_review.sources.retrosheet.loader import cached_slim_plays
from booth_review.sources.wikipedia.mlb_parser import ListCrew, parse_broadcaster_list
from booth_review.vault import VaultRepo, batch_message

__all__ = [
    "SITE_DATA_BUILDER",
    "MlbAssembly",
    "MlbBuildOutcome",
    "assemble_mlb_tables",
    "run_mlb_build",
]

CURRENT_SEASON: Final = MLB_CURRENT_SEASON
_MAX_MESSAGE_LEN: Final = 120
_LIST_ROUND_SLUGS: Final = ("wild_card", "lcs_al", "lcs_nl", "world_series")
_MAP_ISSUE_KINDS: Final = frozenset(
    {"ambiguous_map", "no_map_network", "unresolved_map_network", "no_outlet"}
)
_RR_REVIEW_COLUMNS: Final = ("season", "telecast_id", "reason")
_LINEUP_REVIEW_COLUMNS: Final = ("game_key", "side", "slot", "reason", "player_id")

_WE_SCHEMA: Final[dict[str, pl.DataType | type[pl.DataType]]] = {
    "inning": pl.Int32,
    "regime": pl.String,
    "half": pl.Int8,
    "outs": pl.Int8,
    "bases": pl.Int8,
    "diff": pl.Int32,
    "n": pl.Int64,
    "home_wins": pl.Int64,
    "p": pl.Float64,
}
_LINEUP_SCHEMA: Final[dict[str, pl.DataType | type[pl.DataType]]] = {
    "game_key": pl.String,
    "side": pl.String,
    "slot": pl.Int8,
    "player_id": pl.String,
    "name": pl.String,
    "position": pl.Int8,
    "starter_uncertain": pl.Boolean,
}


#: The site-data writer `--site-data` calls: (paths, reference dir) -> vault path.
SITE_DATA_BUILDER: Callable[[DataPaths, Path], str] | None = build_and_write_mlb_site_data


@dataclass(frozen=True)
class MlbBuildOutcome:
    written: tuple[str, ...]
    counts: Mapping[str, int]
    #: season -> (games with a named crew, own-production games)
    coverage: Mapping[int, tuple[int, int]]
    committed: bool


@dataclass(frozen=True)
class MlbAssembly:
    """The game table and the telecast frame before and after crew assignment."""

    games: pl.DataFrame
    telecasts: pl.DataFrame
    crews: pl.DataFrame
    disagreements: list[CrewDisagreement]
    people_reviews: list[PeopleReview]
    listing_reviews: list[Review]
    game_reviews: list[Review]
    crew_reviews: list[Review]


def _load_inputs(paths: DataPaths, season_list: Sequence[int]) -> tuple[MlbInputs, MlbInputs]:
    """(inputs with the modelling seasons, inputs for the requested seasons only)."""
    model_seasons = sorted(
        set(season_list)
        | set(WE_TRAIN_SEASONS)
        | set(STAKES_BASELINE_SEASONS)
        | {STRENGTH_PRIOR_SEASON}
    )
    all_inputs = load_mlb_inputs(paths, model_seasons)
    return all_inputs, _restrict(all_inputs, season_list)


def _assemble(inputs: MlbInputs, ref: MlbReference, season_list: Sequence[int]) -> MlbAssembly:
    listings = [item for _k, page in sorted(inputs.pages.items()) for item in page.listings]
    non_game = [item for _k, page in sorted(inputs.pages.items()) for item in page.non_game]
    telecasts, listing_reviews = listings_to_telecasts(listings, ref, non_game)
    games, telecasts, game_reviews = build_mlb_games(inputs, ref, telecasts)
    crew_reviews: list[Review] = []
    crews, disagreements, people_reviews = assign_crews(
        telecasts,
        games,
        inputs.relay_rows,
        _list_crews(inputs, season_list),
        ref.crew_overrides,
        ref,
        crew_reviews,
    )
    return MlbAssembly(
        games,
        telecasts,
        crews,
        disagreements,
        people_reviews,
        listing_reviews,
        game_reviews,
        crew_reviews,
    )


def assemble_mlb_tables(
    paths: DataPaths, reference_directory: Path, seasons: Sequence[int]
) -> tuple[MlbAssembly, MlbReference]:
    """Games, telecasts and crews for `seasons` without Retrosheet modelling or writes.

    Used by `mlb gaps`, `mlb people` and `mlb rr-backfill`; the caller holds the lock
    when it writes anything.
    """
    ref = load_mlb_reference(reference_directory)
    _all, inputs = _load_inputs(paths, sorted(set(seasons)))
    return _assemble(inputs, ref, sorted(set(seasons))), ref


def _site_data_unavailable() -> BoothReviewError:
    return BoothReviewError(
        "site data builder not available yet; run the build without --site-data"
    )


def _restrict(inputs: MlbInputs, seasons: Sequence[int]) -> MlbInputs:
    """The inputs for the requested seasons only; modelling seasons stay in `inputs`."""
    keep = set(seasons)
    gameinfo = (
        inputs.gameinfo.filter(pl.col("season").is_in(sorted(keep)))
        if not inputs.gameinfo.is_empty()
        else inputs.gameinfo
    )
    return replace(
        inputs,
        pages={k: v for k, v in inputs.pages.items() if k[0] in keep},
        gameinfo=gameinfo,
        retrosheet_zips={k: v for k, v in inputs.retrosheet_zips.items() if k in keep},
        wikipedia={k: v for k, v in inputs.wikipedia.items() if k in keep},
        seasons=tuple(sorted(keep)),
    )


def _list_crews(inputs: MlbInputs, seasons: Sequence[int]) -> list[ListCrew]:
    keep = set(seasons)
    titles = {slug: (title, kind) for slug, title, kind in MLB_WIKIPEDIA_LIST_PAGES}
    crews: list[ListCrew] = []
    for slug in _LIST_ROUND_SLUGS:
        html = inputs.wikipedia_lists.get(slug)
        if not html:
            continue
        title, kind = titles[slug]
        parsed = parse_broadcaster_list(html, mlb_wikipedia_list_url(title), kind)
        crews.extend(c for c in parsed.crews if c.season in keep)
    return crews


def _rr_records(paths: DataPaths, seasons: Sequence[int]) -> tuple[list[RRRecord], int]:
    records: list[RRRecord] = []
    failures = 0
    for season in sorted(set(seasons)):
        folder = (paths.raw / mlb_rr_path(season, "x")).parent
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.json")):
            try:
                records.append(parse_record(path.read_bytes()))
            except ParseError:
                failures += 1
    return records, failures


def _parse_day(text: object) -> date | None:
    try:
        return datetime.strptime(str(text), "%Y%m%d").date()  # noqa: DTZ007 - a calendar date
    except ValueError:
        return None


def _gid_slots(gameinfo: pl.DataFrame, ref: MlbReference) -> dict[str, tuple[date, str, str, int]]:
    """Retrosheet game id -> (date, away club, home club, game number), where all resolve."""
    if gameinfo.is_empty():
        return {}
    teams = MlbTeamResolver.from_reference(ref)
    clubs: dict[tuple[str, int], str | None] = {}

    def club(code: str, season: int) -> str | None:
        slot = (code, season)
        if slot not in clubs:
            clubs[slot] = teams.resolve("retrosheet", code, season).club_id
        return clubs[slot]

    out: dict[str, tuple[date, str, str, int]] = {}
    for gid, season, day, vis, home, number in gameinfo.select(
        "gid", "season", "date", "visteam", "hometeam", "number"
    ).iter_rows():
        parsed = _parse_day(day)
        away_club, home_club = club(str(vis), int(season)), club(str(home), int(season))
        if parsed is None or away_club is None or home_club is None:
            continue
        out.setdefault(str(gid), (parsed, away_club, home_club, int(number or 0)))
    return out


def _gid_keys(gameinfo: pl.DataFrame, ref: MlbReference) -> dict[str, str]:
    """Retrosheet game id -> game key, for every game whose clubs and date resolve."""
    return {
        gid: game_key(day, away, home, number)
        for gid, (day, away, home, number) in _gid_slots(gameinfo, ref).items()
    }


def _join_unnumbered(
    games: pl.DataFrame,
    gameinfo: pl.DataFrame,
    ref: MlbReference,
    gid_keys: dict[str, str],
) -> tuple[dict[str, str], list[Review]]:
    """Give shown games with no exact Retrosheet key a gid by (date, clubs) when unambiguous.

    A listing 506 numbers 0 (one game of a doubleheader named without "Game N") never
    meets Retrosheet's 1 or 2 on the exact key. Returns the gid -> shown key additions
    and a `shown_game_no_gid` review for every shown game still without a gid, in each
    season a Retrosheet bundle covers.
    """
    if gameinfo.is_empty() or games.is_empty():
        return {}, []
    covered = {int(s) for s in gameinfo["season"].unique().to_list()}
    have = set(gid_keys.values())
    slots = _gid_slots(gameinfo, ref)
    by_slot: dict[tuple[date, str, str], list[str]] = {}
    for gid, (day, away, home, _number) in slots.items():
        by_slot.setdefault((day, away, home), []).append(gid)
    shown = set(games["game_key"].to_list())
    taken = {gid for gid, key in gid_keys.items() if key in shown}
    extra: dict[str, str] = {}
    reviews: list[Review] = []
    for row in games.filter(pl.col("season").is_in(sorted(covered))).iter_rows(named=True):
        key = str(row["game_key"])
        if key in have:
            continue
        found = [
            g
            for g in by_slot.get((row["game_date"], row["away_club"], row["home_club"]), [])
            if g not in taken and g not in extra
        ]
        if len(found) == 1:
            extra[found[0]] = key
        else:
            reviews.append(Review("retrosheet", "shown_game_no_gid", 1, str(row["season"])))
    return extra, reviews


def _coverage(crews: pl.DataFrame) -> dict[int, tuple[int, int]]:
    """season -> (games with a named crew, own-production games with a crew in scope)."""
    if crews.is_empty():
        return {}
    own = crews.filter((pl.col("production") == "own") & pl.col("crew_in_scope"))
    out: dict[int, tuple[int, int]] = {}
    for season in sorted({int(s) for s in own["season"].unique().to_list()}):
        rows = own.filter(pl.col("season") == season)
        named = rows.filter(pl.col("crew_named"))["game_key"].n_unique()
        out[season] = (int(named), int(rows["game_key"].n_unique()))
    return out


def _rr_columns(crews: pl.DataFrame, matches: Sequence[RRGameMatch]) -> pl.DataFrame:
    """The telecast table: crew columns plus the game's Ratings Reference figure and cause.

    A figure belongs to the game, not to a telecast, so it sits on one row per game only:
    the first own-production telecast in table order (the row the site ships), else the
    first row. `rr_figure_row` marks that row; the game's other rows carry nulls, so
    aggregating `rr_viewers` over telecasts never counts one audience twice.
    """
    schema: dict[str, pl.DataType | type[pl.DataType]] = {
        "game_key": pl.String,
        "rr_cause": pl.String,
        "rr_tier": pl.String,
        "rr_viewers": pl.Float64,
        "rr_label": pl.String,
        "rr_url": pl.String,
        "rr_source_url": pl.String,
        "rr_era_id": pl.String,
    }
    rows = [
        {
            "game_key": m.game_key,
            "rr_cause": m.cause,
            "rr_tier": m.tier,
            "rr_viewers": m.viewers,
            "rr_label": m.viewership_label or None,
            "rr_url": m.record_url,
            "rr_source_url": m.headline_source_url,
            "rr_era_id": m.era_id,
        }
        for m in matches
    ]
    frame = pl.DataFrame(rows, schema=schema).unique("game_key", keep="first", maintain_order=True)
    joined = crews.join(frame, on="game_key", how="left", maintain_order="left")
    if joined.is_empty():
        return joined.with_columns(pl.lit(None, dtype=pl.Boolean).alias("rr_figure_row"))
    own = (joined["production"] == "own").to_list()
    keys = joined["game_key"].to_list()
    has_own = {k for k, o in zip(keys, own, strict=True) if o}
    claimed: set[str] = set()
    primary: list[bool] = []
    for key, is_own in zip(keys, own, strict=True):
        take = key not in claimed and (is_own or key not in has_own)
        if take:
            claimed.add(key)
        primary.append(take)
    flag = pl.Series("rr_figure_row", primary, dtype=pl.Boolean)
    figure_cols = [name for name in schema if name != "game_key"]
    return joined.with_columns(
        [pl.when(flag).then(pl.col(name)).otherwise(None).alias(name) for name in figure_cols]
    ).with_columns(flag)


@dataclass
class _Model:
    """Retrosheet-derived frames keyed by game key (empty until the data is collected)."""

    we: pl.DataFrame
    excitement: pl.DataFrame
    stakes: pl.DataFrame
    strength: pl.DataFrame
    baseline: pl.DataFrame
    lineups: pl.DataFrame
    reviews: list[Review]
    lineup_reviews: list[dict[str, object]]
    counts: dict[str, int]


def _empty_model() -> _Model:
    return _Model(
        we=pl.DataFrame(schema=_WE_SCHEMA),
        excitement=pl.DataFrame(
            schema={"game_key": pl.String, "wp_excitement": pl.Float64, "n_plays": pl.Int64}
        ),
        stakes=pl.DataFrame(schema={"game_key": pl.String, "pregame_stakes": pl.Float64}),
        strength=pl.DataFrame(schema={"game_key": pl.String, "strength_prior": pl.Float64}),
        baseline=pl.DataFrame(
            schema={
                "game_date": pl.Date,
                "pregame_stakes": pl.Float64,
                "wp_excitement": pl.Float64,
            }
        ),
        lineups=pl.DataFrame(schema=_LINEUP_SCHEMA),
        reviews=[],
        lineup_reviews=[],
        counts={"we_states": 0, "excitement_games": 0, "lineup_games": 0},
    )


def _model(
    paths: DataPaths,
    all_inputs: MlbInputs,
    ref: MlbReference,
    seasons: Sequence[int],
    wanted_gids: Mapping[str, str],
    gid_keys: Mapping[str, str],
    *,
    we_min_train_games: int,
) -> _Model:
    """Win-expectancy table, excitement, stakes, strength prior, baseline and lineups."""
    model = _empty_model()
    info = all_inputs.gameinfo
    if info.is_empty():
        return model

    plays: dict[int, pl.DataFrame] = {}
    for season, bundle in sorted(all_inputs.retrosheet_zips.items()):
        plays[season] = cached_slim_plays(paths, season, bundle.read_bytes())
    train = [plays[s] for s in WE_TRAIN_SEASONS if s in plays]
    if train:
        table: WeTable | None = build_we_table(
            pl.concat(train, how="vertical_relaxed"),
            info.filter(pl.col("season").is_in(list(WE_TRAIN_SEASONS))),
            min_train_games=we_min_train_games,
        )
    else:
        table = None
    if table is not None:
        model.we = table.states.select(list(_WE_SCHEMA)).cast(_WE_SCHEMA)  # type: ignore[arg-type]
        model.counts["we_states"] = model.we.height

    excite_seasons = sorted((set(STAKES_BASELINE_SEASONS) | set(seasons)) & set(plays))
    excitement_frames: list[pl.DataFrame] = []
    if table is not None:
        for season in excite_seasons:
            excitement_frames.append(
                excitement_by_game(plays[season], info.filter(pl.col("season") == season), table)
            )
    excitement = (
        pl.concat(excitement_frames)
        if excitement_frames
        else pl.DataFrame(
            schema={"gid": pl.String, "wp_excitement": pl.Float64, "n_plays": pl.Int64}
        )
    )
    model.counts["excitement_games"] = int(excitement["wp_excitement"].drop_nulls().len())
    exc_by_gid = {
        str(g): (e, n)
        for g, e, n in excitement.select("gid", "wp_excitement", "n_plays").iter_rows()
    }
    model.excitement = pl.DataFrame(
        [
            {"game_key": gid_keys[g], "wp_excitement": v[0], "n_plays": v[1]}
            for g, v in sorted(exc_by_gid.items())
            if g in wanted_gids and g in gid_keys
        ],
        schema={"game_key": pl.String, "wp_excitement": pl.Float64, "n_plays": pl.Int64},
    )

    # Stakes: the pooled baseline seasons plus the current season when it is requested.
    stakes_seasons = sorted(
        (set(STAKES_BASELINE_SEASONS) | ({CURRENT_SEASON} & set(seasons)))
        & {int(s) for s in info["season"].unique().to_list()}
    )
    baseline_rows: list[dict[str, object]] = []
    current_stakes: dict[str, float | None] = {}
    for season in stakes_seasons:
        season_info = info.filter(pl.col("season") == season)
        standings, standing_reviews = daily_standings(
            season_info, team_divisions(ref, season), season
        )
        model.reviews.extend(
            Review("standings", r.reason, 1, str(season)) for r in standing_reviews
        )
        stakes = pregame_stakes(season_info, standings, season)
        for gid, day, value in stakes.select("gid", "date", "pregame_stakes").iter_rows():
            if season in STAKES_BASELINE_SEASONS:
                parsed = _parse_day(day)
                if parsed is not None and value is not None:
                    baseline_rows.append(
                        {
                            "game_date": parsed,
                            "pregame_stakes": value,
                            "wp_excitement": (exc_by_gid.get(str(gid)) or (None, 0))[0],
                        }
                    )
            if season == CURRENT_SEASON:
                current_stakes[str(gid)] = value
    model.baseline = pl.DataFrame(
        baseline_rows,
        schema={"game_date": pl.Date, "pregame_stakes": pl.Float64, "wp_excitement": pl.Float64},
    ).sort("game_date", "pregame_stakes", "wp_excitement", nulls_last=True)
    model.stakes = pl.DataFrame(
        [
            {"game_key": gid_keys[g], "pregame_stakes": v}
            for g, v in sorted(current_stakes.items())
            if g in gid_keys
        ],
        schema={"game_key": pl.String, "pregame_stakes": pl.Float64},
    )

    current_info = info.filter(
        (pl.col("season") == CURRENT_SEASON) & (pl.col("round") == "regular")
    )
    if not current_info.is_empty():
        prior = strength_prior(info, STRENGTH_PRIOR_SEASON)
        by_gid = game_strength_prior(current_info, prior)
        model.strength = pl.DataFrame(
            [
                {"game_key": gid_keys[g], "strength_prior": v}
                for g, v in sorted(by_gid.select("gid", "strength_prior").iter_rows())
                if g in gid_keys
            ],
            schema={"game_key": pl.String, "strength_prior": pl.Float64},
        )

    # Lineups for the games the module shows (postseason and current-season national games).
    lineup_frames: list[pl.DataFrame] = []
    for season in sorted(set(seasons) & set(plays)):
        season_gids = set(info.filter(pl.col("season") == season)["gid"].to_list())
        gids = sorted(g for g in wanted_gids if g in season_gids)
        if not gids:
            continue
        subset = plays[season].filter(pl.col("gid").is_in(gids))
        lineups, lineup_reviews = starting_lineups(subset, all_inputs.allplayers)
        lineup_frames.append(lineups)
        model.lineup_reviews.extend(
            {
                "game_key": gid_keys.get(r.gid, ""),
                "side": r.side,
                "slot": r.slot,
                "reason": r.reason,
                "player_id": r.player_id,
            }
            for r in lineup_reviews
        )
    if lineup_frames:
        key_map = pl.DataFrame(
            {"gid": list(wanted_gids), "game_key": list(wanted_gids.values())},
            schema={"gid": pl.String, "game_key": pl.String},
        )
        keyed = (
            pl.concat(lineup_frames, how="vertical_relaxed")
            .join(key_map, on="gid", how="inner")
            .select(list(_LINEUP_SCHEMA))
            .cast(_LINEUP_SCHEMA)  # type: ignore[arg-type]
            .sort("game_key", "side", "slot")
        )
        model.lineups = keyed
        model.counts["lineup_games"] = int(keyed["game_key"].n_unique())
    return model


def _club_strength(
    info: pl.DataFrame, ref: MlbReference, games: pl.DataFrame, existing: pl.DataFrame
) -> pl.DataFrame:
    """Strength prior for current-season games from their clubs, without Retrosheet 2026.

    The 2025 win percentage per Retrosheet team code is mapped to club ids through the
    crosswalk, then each shown current-season game takes the mean of its away and home
    club values. Rows already in `existing` (the Retrosheet-gid path) win; both paths use
    the same club values, so they agree.
    """
    if info.is_empty() or games.is_empty():
        return existing
    prior = strength_prior(info, STRENGTH_PRIOR_SEASON)
    if prior.is_empty():
        return existing
    teams = MlbTeamResolver.from_reference(ref)
    by_club: dict[str, float] = {}
    for team, pct in prior.select("team", "win_pct").iter_rows():
        club_id = teams.resolve("retrosheet", str(team), STRENGTH_PRIOR_SEASON).club_id
        if club_id is not None:
            by_club[club_id] = float(pct)
    have = set(existing["game_key"].to_list())
    rows = []
    current = games.filter(pl.col("season") == CURRENT_SEASON)
    for key, away, home in current.select("game_key", "away_club", "home_club").iter_rows():
        a, h = by_club.get(str(away)), by_club.get(str(home))
        if key in have or a is None or h is None:
            continue
        rows.append({"game_key": key, "strength_prior": (a + h) / 2})
    extra = pl.DataFrame(rows, schema={"game_key": pl.String, "strength_prior": pl.Float64})
    return pl.concat([existing, extra]).sort("game_key")


def _message_counts(counts: Mapping[str, int]) -> dict[str, int]:
    return {
        "games": counts["games"],
        "telecasts": counts["telecasts"],
        "disagree": counts["disagreements"],
        "rrdh": counts["rr_ambiguous_doubleheader"],
        "rrconf": counts["rr_conflict"],
        "unresolved": counts["unresolved_names"],
        "pending": counts["quality_pending"],
    }


def run_mlb_build(
    paths: DataPaths,
    reference_directory: Path,
    seasons: Sequence[int],
    *,
    commit: bool,
    site_data: bool = False,
    we_min_train_games: int = WE_MIN_TRAIN_GAMES,
    site_builder: Callable[[DataPaths, Path], str] | None = None,
) -> MlbBuildOutcome:
    """Build every MLB table and review file under one vault lock, then one scoped commit.

    `we_min_train_games` exists for tests with tiny synthetic Retrosheet bundles.
    `site_builder` replaces the site-data writer (tests); with none available, asking for
    site data stops the build before anything is written.
    """
    site_builder = site_builder or SITE_DATA_BUILDER
    if site_data and site_builder is None:
        raise _site_data_unavailable()
    season_list = sorted(set(seasons))
    vault = VaultRepo(paths.vault)
    vault.check()

    with vault.lock():
        ref = load_mlb_reference(reference_directory)
        eras = load_eras(reference_directory)
        all_inputs, inputs = _load_inputs(paths, season_list)
        asm = _assemble(inputs, ref, season_list)
        games, crews = asm.games, asm.crews
        disagreements, people_reviews = asm.disagreements, asm.people_reviews
        listing_reviews, game_reviews, crew_reviews = (
            asm.listing_reviews,
            asm.game_reviews,
            asm.crew_reviews,
        )

        records, rr_failures = _rr_records(paths, season_list)
        matches, rr_reviews = match_mlb_rr(
            records,
            games,
            crews,
            MlbTeamResolver.from_reference(ref),
            eras,
            MlbNetworkResolver.from_reference(ref),
        )
        crews = _rr_columns(crews, matches)

        gid_keys = _gid_keys(all_inputs.gameinfo, ref)
        shown_keys = set(games["game_key"].to_list())
        extra_gids, no_gid_reviews = _join_unnumbered(games, all_inputs.gameinfo, ref, gid_keys)
        gid_keys = {**gid_keys, **extra_gids}
        wanted = {g: k for g, k in gid_keys.items() if k in shown_keys}
        model = _model(
            paths,
            all_inputs,
            ref,
            season_list,
            wanted,
            gid_keys,
            we_min_train_games=we_min_train_games,
        )

        model.strength = _club_strength(all_inputs.gameinfo, ref, games, model.strength)

        apple, apple_summary, apple_reviews, apple_counts = build_apple_booths(
            games,
            crews,
            model.stakes,
            model.excitement,
            model.strength,
            matches,
            ref,
            baseline=model.baseline if not model.baseline.is_empty() else None,
        )
        post, post_seasons, post_reviews, post_counts = build_postseason_booths(
            games, crews, model.excitement, matches
        )

        games_out = (
            games.join(model.stakes, on="game_key", how="left", maintain_order="left")
            .join(model.strength, on="game_key", how="left", maintain_order="left")
            .join(model.excitement, on="game_key", how="left", maintain_order="left")
        )

        written = write_mlb_tables(
            paths,
            {
                "mlb_games": games_out,
                "mlb_telecasts": crews,
                LINEUPS_TABLE: model.lineups,
                WE_TABLE: model.we.select(list(_WE_SCHEMA))
                if not model.we.is_empty()
                else model.we,
                "mlb_apple_booths": apple,
                "mlb_apple_summary": apple_summary,
                "mlb_postseason_booths": post,
                "mlb_postseason_seasons": post_seasons,
            },
        )

        # People review (never touches people.csv), crew disagreements and the map.
        people = register_mlb_people(
            paths,
            reference_directory,
            people_review_names(people_reviews),
            ref.booth_ranks.unresolved,
        )
        written.append(f"interim/{review_path(paths).name}")
        write_crew_disagreements(paths.interim / "review_mlb_crew_disagreements.csv", disagreements)
        written.append("interim/review_mlb_crew_disagreements.csv")
        map_rows, _map_reviews = build_postseason_map(inputs, ref)
        write_postseason_map_review(paths, map_rows)
        written.append("interim/review_mlb_postseason_map.csv")

        all_reviews = [
            *listing_reviews,
            *game_reviews,
            *crew_reviews,
            *apple_reviews,
            *post_reviews,
            *model.reviews,
            *no_gid_reviews,
        ]
        nongame = [r for r in all_reviews if r.kind.startswith("non_game_")]
        other = [r for r in all_reviews if not r.kind.startswith("non_game_")]
        written += write_mlb_reviews(
            paths,
            {
                "nongame": (REVIEW_ROW_COLUMNS, review_rows(nongame)),
                "unresolved": (REVIEW_ROW_COLUMNS, review_rows(other)),
                "rr": (_RR_REVIEW_COLUMNS, _rr_review_rows(rr_reviews)),
                "lineups": (
                    _LINEUP_REVIEW_COLUMNS,
                    sorted(
                        model.lineup_reviews,
                        key=lambda r: (str(r["game_key"]), str(r["side"]), int(str(r["slot"]))),
                    ),
                ),
            },
        )

        coverage = _coverage(crews)
        cause = Counter(m.cause for m in matches)
        kinds: Counter[str] = Counter()
        for item in all_reviews:
            kinds[item.kind] += item.count
        counts: dict[str, int] = {
            "games": games.height,
            "telecasts": crews.height,
            "lineup_games": model.counts["lineup_games"],
            "excitement_games": model.counts["excitement_games"],
            "disagreements": len(disagreements),
            "rr_ambiguous_doubleheader": cause["ambiguous_doubleheader"],
            "rr_conflict": cause["conflict"],
            "rr_per_network": cause["per_network"],
            "rr_records": len(records),
            "rr_parse_failures": rr_failures,
            "unresolved_names": people.counts["unresolved"],
            "map_ambiguous": sum(n for k, n in kinds.items() if k in _MAP_ISSUE_KINDS),
            "listing_parse_failures": inputs.page_parse_failures,
            "retrosheet_failures": all_inputs.retrosheet_failures,
            "quality_pending": int(not _has_current_results(all_inputs.gameinfo)),
            **{f"apple_{k}": v for k, v in apple_counts.items()},
            **{f"postseason_{k}": v for k, v in post_counts.items()},
        }
        for season, (named, total) in coverage.items():
            counts[f"crew_named_{season}"] = named
            counts[f"crew_own_{season}"] = total

        if site_data and site_builder is not None:
            try:
                written.append(site_builder(paths, reference_directory))
            except Exception:
                # A site-data failure never blocks the table commit.
                counts["site_data_failed"] = 1

        committed = False
        if commit:
            label = f"{min(season_list)}-{max(season_list)}" if season_list else "none"
            message = batch_message("build", "mlb", label, _message_counts(counts))
            if len(message) > _MAX_MESSAGE_LEN:
                message = batch_message(
                    "build",
                    "mlb",
                    label,
                    {"games": counts["games"], "pending": counts["quality_pending"]},
                )
            committed = vault.commit_batch(message, paths=sorted(set(written)))

    return MlbBuildOutcome(
        written=tuple(sorted(set(written))),
        counts=counts,
        coverage=coverage,
        committed=committed,
    )


def _rr_review_rows(rows: Sequence[RRReview]) -> list[dict[str, object]]:
    return sorted(
        ({"season": r.season, "telecast_id": r.telecast_id, "reason": r.reason} for r in rows),
        key=lambda r: (int(str(r["season"])), str(r["telecast_id"]), str(r["reason"])),
    )


def _has_current_results(gameinfo: pl.DataFrame) -> bool:
    if gameinfo.is_empty():
        return False
    return (
        gameinfo.filter(
            (pl.col("season") == CURRENT_SEASON)
            & (pl.col("round") == "regular")
            & pl.col("vruns").is_not_null()
        ).height
        > 0
    )
