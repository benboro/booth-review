"""Per-game NFL frame (D-20 step 2, second half): the 999.5 hand-off table.

Pure assembly: file reads happen only through `NflInputs` (pbp paths) and the
reference loaders behind `NflReference`. Missing values stay null and are never
coerced to 0.

Analysis-only columns (field list "Display rule"): network_id, network_source,
rr_network_id, rr_network_ids, window, crew_names, pbp_person_id,
analyst_person_id, sideline_person_ids and pregame_spread. 999.5 may use them in
analysis but must not display them; only values derived from them reach the site.

Network order: 506 first; Ratings Reference (RR) supplies the network for
national games, 2014-2015 standalone games and any non-Sunday-afternoon slot. An
RR network alone is never trusted for a Sunday-afternoon regional game. A game
RR lists on several networks (2014-2015 TNF on CBS and NFL Network, 2015 MNF on
ESPN and ABC) keeps all of them in `rr_network_ids`; `rr_network_id` is set only
when exactly one network resolves, and the main feed is never picked automatically.

The AGOTW / CBS late national comes from text sources only: a single 4:25 candidate,
a text source (RR late-window record or a 506 national line) or a cited week
override; otherwise the week is ambiguous and excluded (D-16).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl

from booth_review.flags.era import MeasurementEra, era_for, load_eras
from booth_review.nfl.changes import GameChange, match_schedule_changes
from booth_review.nfl.inputs import NflInputs
from booth_review.nfl.listings import ListingMatch, match_506_listings
from booth_review.nfl.people import CrewResolution, resolve_crew
from booth_review.nfl.reference import (
    NflWeekOverride,
    load_nfl_stadium_overrides,
    load_nfl_stadiums,
    load_nfl_week_overrides,
)
from booth_review.nfl.rr_match import RRGameMatch, match_rr_records
from booth_review.nfl.rules import (
    DhInput,
    SlotName,
    doubleheader_networks,
    is_flexed,
    is_special,
    late_national_candidates,
    pick_late_national,
    slot_name,
    standalone_ids,
)
from booth_review.nfl.schedule import NflGame
from booth_review.nfl.teams import NflNetworkResolver, NflTeamResolver, ResolvedNflTeam
from booth_review.nfl.winprob import game_wp_metrics, read_pbp_wp
from booth_review.people.registry import PeopleRegistry, load_people

NFL_GAME_COLUMNS: tuple[str, ...] = (
    "season",
    "week",
    "game_type",
    "game_id",
    "game_date",
    "kickoff_time_et",
    "kickoff_utc",
    "weekday",
    "home_franchise_id",
    "away_franchise_id",
    "home_display_name",
    "away_display_name",
    "stadium_id",
    "is_international",
    "network_id",
    "network_source",
    "rr_network_id",
    "rr_network_ids",
    "window",
    "crew_names",
    "pbp_person_id",
    "analyst_person_id",
    "sideline_person_ids",
    "alt_cast_broadcasts",
    "is_standalone",
    "slot_name",
    "fox_dh_sunday",
    "cbs_dh_sunday",
    "is_agotw",
    "agotw_source",
    "is_cbs_national",
    "cbs_national_source",
    "late_national_status",
    "flexed",
    "original_slot",
    "original_network",
    "original_time_et",
    "change_article_url",
    "is_special",
    "excitement_score",
    "wp_volatility",
    "wp_plays",
    "pregame_spread",
    "final_margin",
    "viewership",
    "viewership_scope",
    "viewership_status",
    "viewership_cut",
    "viewership_measured_by",
    "era_id",
    "may_combine_feeds",
    "rr_telecast_id",
    "rr_record_url",
    "rr_source_url",
)

#: Child broadcast row shape for alternate feeds (Phase 6 D-15); no source exists yet.
ALT_CAST_DTYPE = pl.Struct({"network_id": pl.String, "crew_names": pl.List(pl.String)})

NFL_GAME_SCHEMA: dict[str, pl.DataType | type[pl.DataType]] = {
    "season": pl.Int64,
    "week": pl.Int64,
    "game_type": pl.String,
    "game_id": pl.String,
    "game_date": pl.Date,
    "kickoff_time_et": pl.String,
    "kickoff_utc": pl.Datetime("us", "UTC"),
    "weekday": pl.String,
    "home_franchise_id": pl.String,
    "away_franchise_id": pl.String,
    "home_display_name": pl.String,
    "away_display_name": pl.String,
    "stadium_id": pl.String,
    "is_international": pl.Boolean,
    "network_id": pl.String,
    "network_source": pl.String,
    "rr_network_id": pl.String,
    "rr_network_ids": pl.List(pl.String),
    "window": pl.String,
    "crew_names": pl.List(pl.String),
    "pbp_person_id": pl.String,
    "analyst_person_id": pl.String,
    "sideline_person_ids": pl.List(pl.String),
    "alt_cast_broadcasts": pl.List(ALT_CAST_DTYPE),
    "is_standalone": pl.Boolean,
    "slot_name": pl.String,
    "fox_dh_sunday": pl.Boolean,
    "cbs_dh_sunday": pl.Boolean,
    "is_agotw": pl.Boolean,
    "agotw_source": pl.String,
    "is_cbs_national": pl.Boolean,
    "cbs_national_source": pl.String,
    "late_national_status": pl.String,
    "flexed": pl.Boolean,
    "original_slot": pl.String,
    "original_network": pl.String,
    "original_time_et": pl.String,
    "change_article_url": pl.String,
    "is_special": pl.Boolean,
    "excitement_score": pl.Float64,
    "wp_volatility": pl.Float64,
    "wp_plays": pl.Int64,
    "pregame_spread": pl.Float64,
    "final_margin": pl.Int64,
    "viewership": pl.Float64,
    "viewership_scope": pl.String,
    "viewership_status": pl.String,
    "viewership_cut": pl.String,
    "viewership_measured_by": pl.String,
    "era_id": pl.String,
    "may_combine_feeds": pl.Boolean,
    "rr_telecast_id": pl.String,
    "rr_record_url": pl.String,
    "rr_source_url": pl.String,
}

#: Each key becomes interim/review_nfl_<key>.csv. Never "people": `nfl people` owns
#: review_nfl_people.csv (the user's add-variant decisions) and the build must not overwrite it.
REVIEW_KEYS: tuple[str, ...] = (
    "teams",
    "stadiums",
    "networks",
    "listings",
    "rr",
    "changes",
    "crew_names",
    "late_national",
    "acceptance",
)

COUNT_KEYS: tuple[str, ...] = (
    "games",
    "standalone",
    "agotw",
    "cbs_national",
    "fox_dh_sundays",
    "cbs_dh_sundays",
    "ambiguous_fox_weeks",
    "ambiguous_cbs_weeks",
    "override_errors",
    "override_unused",
    "unresolved_teams",
    "unknown_stadiums",
    "rr_regional_only",
    "rr_multi_network_games",
    "network_disagree",
    "pbp_missing_seasons",
    "unresolved_crew_names",
    "unmatched_listings",
    "unmatched_rr",
    "unmatched_changes",
)

#: A game counts as played this long after its scheduled kickoff (D-12).
PLAYED_AFTER = timedelta(hours=4)

_SUNDAY_AFTERNOON: frozenset[str] = frozenset({"Sunday early", "Sunday late"})
_COMBINED_FEED_NETWORKS: frozenset[str] = frozenset({"espn", "abc"})
_MONDAY = 0
_LATE_NETWORKS = ("fox", "cbs")


@dataclass(frozen=True)
class NflReference:
    teams: NflTeamResolver
    networks: NflNetworkResolver
    stadiums: Mapping[str, str]
    week_overrides: Mapping[tuple[int, int, str], NflWeekOverride]
    people: PeopleRegistry
    eras: Sequence[MeasurementEra]
    #: nflverse_game_id -> venue stadium_id; applied ahead of nflverse's own stadium_id.
    stadium_overrides: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, reference_dir: Path) -> NflReference:
        return cls(
            teams=NflTeamResolver.from_reference_dir(reference_dir),
            networks=NflNetworkResolver.from_reference_dir(reference_dir),
            stadiums=load_nfl_stadiums(reference_dir),
            week_overrides=load_nfl_week_overrides(reference_dir),
            people=load_people(reference_dir),
            eras=load_eras(reference_dir),
            stadium_overrides=load_nfl_stadium_overrides(reference_dir),
        )


@dataclass(frozen=True)
class NflGameTable:
    frame: pl.DataFrame
    reviews: Mapping[str, list[dict[str, object]]]
    counts: Mapping[str, int]
    through_week: Mapping[int, int | None]


@dataclass(frozen=True)
class _NetworkChoice:
    network_id: str | None
    source: str | None
    rr_ids: list[str]
    rr_id: str | None
    reasons: tuple[str, ...]


def _review(game: NflGame, reason: str, **extra: object) -> dict[str, object]:
    row: dict[str, object] = {
        "game_id": game.game_id,
        "season": game.season,
        "week": game.week,
        "reason": reason,
    }
    row.update(extra)
    return row


def _choose_network(
    *,
    listing: ListingMatch | None,
    rr_matches: Sequence[RRGameMatch],
    slot: str,
    standalone: bool,
) -> _NetworkChoice:
    rr_ids = sorted({nid for m in rr_matches for nid in m.network_ids})
    rr_id = rr_ids[0] if len(rr_ids) == 1 else None
    reasons: list[str] = []
    if len(rr_ids) > 1:
        reasons.append("rr-multi-network")
    n506 = listing.network_id if listing is not None else None
    if n506 is not None:
        if standalone and rr_ids and n506 not in rr_ids:
            reasons.append("network-disagree")
        return _NetworkChoice(n506, "506", rr_ids, rr_id, tuple(reasons))
    if not rr_ids:
        return _NetworkChoice(None, None, rr_ids, rr_id, tuple(reasons))
    if slot in _SUNDAY_AFTERNOON and not standalone:
        reasons.append("rr-regional-only")
        return _NetworkChoice(None, None, rr_ids, rr_id, tuple(reasons))
    if rr_id is not None:
        return _NetworkChoice(rr_id, "rr", rr_ids, rr_id, tuple(reasons))
    return _NetworkChoice(None, "rr-multi", rr_ids, rr_id, tuple(reasons))


def _through_week(games: Sequence[NflGame], played: frozenset[str]) -> int | None:
    regular = sorted((g for g in games if g.game_type == "REG"), key=lambda g: g.week)
    last: int | None = None
    for week in sorted({g.week for g in regular}):
        if all(g.game_id in played for g in regular if g.week == week):
            last = week
        else:
            break
    return last


def _pick_headline(
    matches: Sequence[RRGameMatch], network_id: str | None
) -> tuple[RRGameMatch | None, bool]:
    """Prefer date-tier records, then ones on the game's network; first by telecast id.

    The flag is True when more than one record remained after both preferences.
    """
    if not matches:
        return None, False
    pool = [m for m in matches if m.tier == "date"] or list(matches)
    if network_id is not None:
        pool = [m for m in pool if network_id in m.network_ids] or pool
    return sorted(pool, key=lambda m: m.telecast_id)[0], len(pool) > 1


def _wp_by_game(
    inputs: NflInputs, games_by_season: Mapping[int, Sequence[NflGame]]
) -> tuple[dict[str, dict[str, object]], int]:
    metrics: dict[str, dict[str, object]] = {}
    missing = 0
    for season, season_games in sorted(games_by_season.items()):
        path = inputs.pbp_paths.get(season)
        if path is None:
            missing += 1
            continue
        table = game_wp_metrics(
            read_pbp_wp(path),
            season_by_game={g.game_id: g.season for g in season_games},
            game_type_by_game={g.game_id: g.game_type for g in season_games},
        )
        for row in table.iter_rows(named=True):
            metrics[str(row["game_id"])] = row
    return metrics, missing


@dataclass(frozen=True)
class _GameInfo:
    home: ResolvedNflTeam
    away: ResolvedNflTeam
    listing: ListingMatch | None
    international: bool | None
    slot: SlotName
    standalone: bool
    choice: _NetworkChoice
    crew: CrewResolution


def assemble_nfl_games(
    inputs: NflInputs,
    ref: NflReference,
    *,
    include_playoffs: bool,
    now: datetime,
) -> NflGameTable:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    counts: dict[str, int] = dict.fromkeys(COUNT_KEYS, 0)
    reviews: dict[str, list[dict[str, object]]] = {key: [] for key in REVIEW_KEYS}

    listings, listing_reviews = match_506_listings(inputs, ref.teams, ref.networks)
    rr_matches, rr_reviews = match_rr_records(inputs, ref.teams, ref.networks)
    changes, change_reviews = match_schedule_changes(inputs, ref.teams, ref.networks)
    for lr in listing_reviews:
        reviews["listings"].append(
            {
                "season": lr.season,
                "week": lr.week,
                "row": lr.source_row_index,
                "reason": lr.reason,
            }
        )
    for rr_item in rr_reviews:
        reviews["rr"].append(
            {"season": rr_item.season, "telecast_id": rr_item.telecast_id, "reason": rr_item.reason}
        )
    for change_item in change_reviews:
        reviews["changes"].append(
            {
                "season": change_item.season,
                "week": change_item.week,
                "raw_text_hash": change_item.raw_text_hash,
                "reason": change_item.reason,
            }
        )
    counts["unmatched_listings"] = len(listing_reviews)
    counts["unmatched_rr"] = len(rr_reviews)
    counts["unmatched_changes"] = len(change_reviews)

    all_by_season: dict[int, list[NflGame]] = defaultdict(list)
    for game in inputs.games:
        all_by_season[game.season].append(game)

    # Standalone sees every game of the season, playoffs included, toggle or not.
    standalone: set[str] = set()
    for season_games in all_by_season.values():
        standalone |= standalone_ids({g.game_id: g.kickoff_et for g in season_games})

    played = frozenset(g.game_id for g in inputs.games if g.kickoff_et + PLAYED_AFTER <= now)
    through_week = {
        season: _through_week(season_games, played)
        for season, season_games in sorted(all_by_season.items())
    }
    out_games = [
        g
        for g in inputs.games
        if g.game_id in played and (g.game_type == "REG" or include_playoffs)
    ]
    out_by_season: dict[int, list[NflGame]] = defaultdict(list)
    for game in out_games:
        out_by_season[game.season].append(game)

    # -- identity, slot, network ------------------------------------------------------------
    info: dict[str, _GameInfo] = {}
    network_of: dict[str, str | None] = {}
    for game in out_games:
        home = ref.teams.resolve("nflverse", game.home_team, game.season)
        away = ref.teams.resolve("nflverse", game.away_team, game.season)
        for side in (home, away):
            if side.franchise_id is None:
                counts["unresolved_teams"] += 1
                reviews["teams"].append(_review(game, "unresolved-team"))
        listing = listings.get(game.game_id)
        stadium_id = ref.stadium_overrides.get(game.game_id, game.stadium_id)
        country = ref.stadiums.get(stadium_id)
        international: bool | None
        if country is not None:
            international = country != "US"
        elif (listing is not None and listing.intl_city) or game.location == "Neutral":
            international = None
            counts["unknown_stadiums"] += 1
            reviews["stadiums"].append(_review(game, "unknown-stadium"))
        else:
            international = False
        slot: SlotName = slot_name(game.kickoff_et, outside_us=international is True)
        is_alone = game.game_id in standalone
        choice = _choose_network(
            listing=listing,
            rr_matches=rr_matches.get(game.game_id, []),
            slot=slot,
            standalone=is_alone,
        )
        for reason in choice.reasons:
            reviews["networks"].append(_review(game, reason))
            if reason == "rr-multi-network":
                counts["rr_multi_network_games"] += 1
            elif reason == "network-disagree":
                counts["network_disagree"] += 1
            elif reason == "rr-regional-only":
                counts["rr_regional_only"] += 1
        crew = resolve_crew(listing.crew_names if listing else (), ref.people)
        if crew.unresolved_names:
            counts["unresolved_crew_names"] += len(crew.unresolved_names)
            reviews["crew_names"].append(
                _review(game, "unresolved-crew-name", count=len(crew.unresolved_names))
            )
        network_of[game.game_id] = choice.network_id
        info[game.game_id] = _GameInfo(
            home, away, listing, international, slot, is_alone, choice, crew
        )

    # -- doubleheader Sundays and the late national game ---------------------------------------
    reg_by_date: dict[date, list[NflGame]] = defaultdict(list)
    for game in out_games:
        if game.game_type == "REG":
            reg_by_date[game.gameday].append(game)
    dh_flags: dict[str, set[str]] = {}
    late_source: dict[str, dict[str, str]] = {n: {} for n in _LATE_NETWORKS}
    late_status: dict[str, str] = {}
    for day, day_games in sorted(reg_by_date.items()):
        dh_inputs = [DhInput(g.game_id, g.kickoff_et, network_of[g.game_id]) for g in day_games]
        dh = doubleheader_networks(dh_inputs)
        for game in day_games:
            dh_flags[game.game_id] = set(dh)
        for network in _LATE_NETWORKS:
            if network not in dh:
                continue
            counts[f"{network}_dh_sundays"] += 1
            week = day_games[0].week
            season = day_games[0].season
            candidates = late_national_candidates(dh_inputs, network)
            rr_named = {
                gid
                for gid in candidates
                if any(
                    m.event_date == day and network in m.network_ids
                    for m in rr_matches.get(gid, [])
                )
            }
            s506_named = {
                gid
                for gid in candidates
                if (lm := listings.get(gid)) is not None
                and lm.is_national_line
                and lm.network_id == network
            }
            override = ref.week_overrides.get((season, week, network))
            override_id = override.nflverse_game_id if override is not None else None
            try:
                pick = pick_late_national(
                    candidates,
                    rr_named=rr_named,
                    s506_named=s506_named,
                    override_game_id=override_id,
                )
            except ValueError:
                counts["override_errors"] += 1
                reviews["late_national"].append(
                    {
                        "season": season,
                        "week": week,
                        "network": network,
                        "reason": "override-invalid",
                        "candidates": len(candidates),
                    }
                )
                pick = pick_late_national(
                    candidates, rr_named=rr_named, s506_named=s506_named, override_game_id=None
                )
            if pick.override_unused:
                counts["override_unused"] += 1
            if pick.game_id is not None:
                late_source[network][pick.game_id] = pick.source
                status = "settled"
            else:
                status = "ambiguous"
                counts[f"ambiguous_{network}_weeks"] += 1
                reviews["late_national"].append(
                    {
                        "season": season,
                        "week": week,
                        "network": network,
                        "reason": "ambiguous",
                        "candidates": len(candidates),
                    }
                )
            for game in day_games:
                if network_of[game.game_id] == network:
                    late_status[game.game_id] = status

    # -- win probability --------------------------------------------------------------------
    wp, missing_seasons = _wp_by_game(inputs, out_by_season)
    counts["pbp_missing_seasons"] = missing_seasons

    monday_dates: dict[date, int] = defaultdict(int)
    for game in inputs.games:
        if game.kickoff_et.weekday() == _MONDAY:
            monday_dates[game.gameday] += 1

    rows: list[dict[str, object]] = []
    for game in out_games:
        item = info[game.game_id]
        home, away, choice, crew = item.home, item.away, item.choice, item.crew
        slot_value = item.slot
        flags = dh_flags.get(game.game_id, set())
        agotw_src = late_source["fox"].get(game.game_id)
        cbs_src = late_source["cbs"].get(game.game_id)
        change: GameChange | None = changes.get(game.game_id)
        time_et = game.kickoff_et.strftime("%H:%M")
        flexed = False
        if change is not None:
            flexed = is_flexed(
                current_slot=item.slot,
                original_slot=change.original_slot,
                is_late_national=agotw_src is not None or cbs_src is not None,
                original_time_et=change.original_time_et,
                current_time_et=time_et,
            )
        metrics = wp.get(game.game_id, {})
        headline, many = _pick_headline(rr_matches.get(game.game_id, []), choice.network_id)
        if many:
            reviews["rr"].append(_review(game, "multiple-records"))
        feed_ids = set(choice.rr_ids)
        if choice.network_id is not None:
            feed_ids.add(choice.network_id)
        may_combine = game.kickoff_et.weekday() == _MONDAY and (
            bool(feed_ids & _COMBINED_FEED_NETWORKS) or monday_dates[game.gameday] >= 2
        )
        margin = (
            game.home_score - game.away_score
            if game.home_score is not None and game.away_score is not None
            else None
        )
        is_agotw = agotw_src is not None
        is_cbs = cbs_src is not None
        listing = item.listing
        rows.append(
            {
                "season": game.season,
                "week": game.week,
                "game_type": game.game_type,
                "game_id": game.game_id,
                "game_date": game.gameday,
                "kickoff_time_et": time_et,
                "kickoff_utc": game.kickoff_et.astimezone(UTC),
                "weekday": game.weekday,
                "home_franchise_id": home.franchise_id,
                "away_franchise_id": away.franchise_id,
                "home_display_name": home.display_name,
                "away_display_name": away.display_name,
                "stadium_id": ref.stadium_overrides.get(game.game_id, game.stadium_id) or None,
                "is_international": item.international,
                "network_id": choice.network_id,
                "network_source": choice.source,
                "rr_network_id": choice.rr_id,
                "rr_network_ids": choice.rr_ids,
                "window": listing.window if listing else None,
                "crew_names": list(listing.crew_names) if listing else [],
                "pbp_person_id": crew.pbp_person_id,
                "analyst_person_id": crew.analyst_person_id,
                "sideline_person_ids": list(crew.sideline_person_ids),
                "alt_cast_broadcasts": [],
                "is_standalone": item.standalone,
                "slot_name": slot_value,
                "fox_dh_sunday": "fox" in flags,
                "cbs_dh_sunday": "cbs" in flags,
                "is_agotw": is_agotw,
                "agotw_source": agotw_src,
                "is_cbs_national": is_cbs,
                "cbs_national_source": cbs_src,
                "late_national_status": late_status.get(game.game_id, "not_dh"),
                "flexed": flexed,
                "original_slot": change.original_slot if change else None,
                "original_network": change.original_network_id if change else None,
                "original_time_et": change.original_time_et if change else None,
                "change_article_url": change.article_url if change else None,
                "is_special": is_special(
                    is_standalone=item.standalone,
                    is_agotw=is_agotw,
                    is_cbs_national=is_cbs,
                    game_type=game.game_type,
                    include_playoffs=include_playoffs,
                ),
                "excitement_score": metrics.get("excitement_score"),
                "wp_volatility": metrics.get("wp_volatility"),
                "wp_plays": metrics.get("wp_plays"),
                "pregame_spread": game.spread_line,
                "final_margin": margin,
                "viewership": headline.headline_value if headline else None,
                "viewership_scope": "window" if slot_value in _SUNDAY_AFTERNOON else "game",
                "viewership_status": headline.headline_status if headline else None,
                "viewership_cut": headline.headline_cut if headline else None,
                "viewership_measured_by": headline.headline_measured_by if headline else None,
                "era_id": era_for(game.gameday, ref.eras).era_id,
                "may_combine_feeds": may_combine,
                "rr_telecast_id": headline.telecast_id if headline else None,
                "rr_record_url": headline.record_url if headline else None,
                "rr_source_url": headline.headline_source_url if headline else None,
            }
        )

    frame = (
        pl.DataFrame(rows, schema=NFL_GAME_SCHEMA, orient="row")
        if rows
        else pl.DataFrame(schema=NFL_GAME_SCHEMA)
    )
    frame = frame.select(NFL_GAME_COLUMNS)
    counts["games"] = frame.height
    counts["standalone"] = int(frame["is_standalone"].sum()) if frame.height else 0
    counts["agotw"] = int(frame["is_agotw"].sum()) if frame.height else 0
    counts["cbs_national"] = int(frame["is_cbs_national"].sum()) if frame.height else 0
    return NflGameTable(frame=frame, reviews=reviews, counts=counts, through_week=through_week)
