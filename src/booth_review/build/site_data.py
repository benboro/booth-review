"""site-data.json (D-13/D-14): assemble and write the Phase 4 static site's
one data file from the already-built processed tables (build.tables,
build.coverage), validated against the pydantic contract
(contract.models.validate_site_data) before it is ever written.

Only `telecasts.plotted` rows become dots on the log axis (D-10): a headline
figure resolved on the main broadcast feed. Every other main-feed game with a
game and a resolved network ships in `telecasts_unrated` (04.13 D-13) with a
build-time cause (D-10). Every field this module assembles is one of
`contract.models.SITE_DATA_FIELDS` -- pydantic's own `extra="forbid"` is the
final gate against a CFBD bulk field ever reaching this file (SITE-19);
SITE_DATA_FIELDS and UNRATED_FIELDS are the allowlists.
This module never reads the CFBD API key from the environment or `.env`: a
test sets a fake key in the environment and asserts it never appears
anywhere in the written bytes (T-03-44).

The file this module writes stays in the private vault (`processed/`) until
Phase 5 deploys it to the public site.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import polars as pl
from pydantic import ValidationError

from booth_review.build.bowls import load_bowls
from booth_review.build.named_games import (
    build_franchises,
    check_game_slugs,
    resolve_rivalry_games,
)
from booth_review.build.rivalries import load_rivalries
from booth_review.build.shipped import (
    left_out_unrated_expr,
    network_rated_counts,
    no_rating_cause,
    rarity_contradictions,
    select_unrated_shipped,
)
from booth_review.config import DataPaths
from booth_review.contract.models import (
    SCHEMA_VERSION,
    SiteData,
    validate_site_data,
)
from booth_review.errors import BowlCrosswalkError, VaultStateError
from booth_review.flags.era import load_eras
from booth_review.flags.events import load_event_flags
from booth_review.resolve.headline import is_usable_value
from booth_review.resolve.networks import (
    check_network_rarity,
    load_network_rarity,
    load_networks,
)
from booth_review.transport.cache import atomic_write_bytes

if TYPE_CHECKING:
    from booth_review.build.coverage import CoverageReport
    from booth_review.build.tables import BuildTables

_FEED_ORDER: dict[str, int] = {"main": 0, "alt": 1, "spanish": 2}
_UNMAPPED_NETWORK_ID = "unmapped"
_MEASUREMENT_FLAG_LABEL = "Nielsen+Adobe"
_COMBINED_FLAG_LABEL = "Combined across feeds"
_POSTSEASON_TYPES = frozenset({"bowl", "playoff"})
_CFP_AT_BOWL_ROUNDS = frozenset({"quarterfinal", "semifinal"})
_NOON_HOUR = 14
_PRIME_HOUR = 18
_LATE_HOUR = 22
_LATE_NIGHT_END_HOUR = 5


def _as_int(value: object) -> int:
    return value if isinstance(value, int) else 0


def _as_str_list(value: object) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def time_slot(kickoff_et: str | None) -> Literal["noon", "afternoon", "prime", "late"] | None:
    """docs/site-data.md's time-slot boundaries, read off `kickoff_et`'s own
    ET wall-clock hour -- the string already carries the ET UTC offset, so no
    timezone conversion happens here (D-20/D-26):

    - **"late"** ("After dark") -- 00:00 up to (not including) 05:00 ET (a
      kickoff after midnight, e.g. a Hawaii home game), OR 22:00 ET or later.
    - **"noon"** -- 05:00 up to (not including) 14:00 ET.
    - **"afternoon"** -- 14:00 up to (not including) 18:00 ET.
    - **"prime"** -- 18:00 up to (not including) 22:00 ET.

    A null kickoff is a null time_slot.
    """
    if kickoff_et is None:
        return None
    hour = datetime.fromisoformat(kickoff_et).hour
    if hour < _LATE_NIGHT_END_HOUR:
        return "late"
    if hour < _NOON_HOUR:
        return "noon"
    if hour < _PRIME_HOUR:
        return "afternoon"
    if hour < _LATE_HOUR:
        return "prime"
    return "late"


def _through_week(
    telecast_ids: set[str], game_by_telecast: dict[str, tuple[str, int]]
) -> str | None:
    """ "postseason" if any telecast in `telecast_ids` belongs to a postseason
    game (postseason always follows every regular-season week); else the
    highest regular-season week among them, as a string; else None.
    """
    has_postseason = False
    max_regular_week: int | None = None
    for telecast_id in telecast_ids:
        info = game_by_telecast.get(telecast_id)
        if info is None:
            continue
        season_type, week = info
        if season_type == "postseason":
            has_postseason = True
        elif max_regular_week is None or week > max_regular_week:
            max_regular_week = week
    if has_postseason:
        return "postseason"
    if max_regular_week is not None:
        return str(max_regular_week)
    return None


def _build_freshness(tables: BuildTables) -> dict[str, object]:
    games = tables.games
    telecasts = tables.telecasts
    seasons = games["season"].to_list() if games.height else telecasts["season"].to_list()
    season = max(seasons) if seasons else 0

    game_type_week: dict[int, tuple[str, int]] = {
        row["game_id"]: (row["season_type"], row["week"])
        for row in games.select("game_id", "season_type", "week").iter_rows(named=True)
    }
    season_telecasts = telecasts.filter(pl.col("season") == season)
    game_by_telecast: dict[str, tuple[str, int]] = {}
    for row in season_telecasts.select("telecast_id", "game_id").iter_rows(named=True):
        info = game_type_week.get(row["game_id"])
        if info is not None:
            game_by_telecast[row["telecast_id"]] = info

    # The 506 crews stamp keys on the pre-override 506 match: a telecast 506
    # listed a main crew for. apply_crew_overrides flips crew_matched only for
    # status `patched` (506 listed no main crew) and marks exactly those
    # crew_patched, so this is that match; redundant, correction, and differs
    # overrides sit on crews 506 did list and still advance the stamp.
    crew_filter = pl.col("crew_matched") & ~pl.col("crew_patched")
    crew_ids: set[str] = set(season_telecasts.filter(crew_filter)["telecast_id"].to_list())
    viewership_ids: set[str] = set(
        season_telecasts.filter(pl.col("plotted"))["telecast_id"].to_list()
    )
    return {
        "season": season,
        "crews_through_week": _through_week(crew_ids, game_by_telecast),
        "viewership_through_week": _through_week(viewership_ids, game_by_telecast),
    }


def build_site_data(
    tables: BuildTables,
    coverage: CoverageReport,
    reference_directory: Path,
    generated_at: datetime,
    *,
    counts: dict[str, int] | None = None,
    bowl_crosswalk: Literal["strict", "lenient"] = "strict",
) -> SiteData:
    """Assemble every plotted telecast (D-10) into the D-13 columnar
    SiteData, validated by the D-14 contract (`validate_site_data`) before
    returning. Rated telecasts become dots on the log axis; every other
    main-feed game with a game and a resolved network ships in
    `telecasts_unrated` (04.13 D-13) with a build-time cause (D-10). Bowls,
    franchises, rivalries and lookups derive from both blocks (D-14).
    Never writes anything -- see `write_site_data`.

    When `counts` is given, the rivalry resolution's counts (D-13) are added
    to it for the build summary: numbers only, never a name.

    `bowl_crosswalk="lenient"` (the scheduled job) lets a plotted postseason
    game with no bowls.csv row, or an at-bowl row with no franchise, build
    with a null bowl instead of aborting (D-07); both are counted. The
    "postseason game" there covers unrated games too (04.13 D-14). An at_bowl
    disagreement stays a hard error in both modes.
    """
    eras = {era.era_id: era for era in load_eras(reference_directory)}
    event_flags = {flag.flag_id: flag for flag in load_event_flags(reference_directory)}
    network_table = load_networks(reference_directory)
    network_info = network_table.networks()
    rarity = load_network_rarity(reference_directory)
    check_network_rarity(rarity, network_table)

    sort_keys = ["date_et", "kickoff_et", "telecast_id"]
    plotted = tables.telecasts.filter(pl.col("plotted")).sort(sort_keys, nulls_last=True)
    repeated_games = (
        plotted.filter(pl.col("game_id").is_not_null())
        .group_by("game_id")
        .len()
        .filter(pl.col("len") > 1)
        .height
    )
    if repeated_games:
        raise VaultStateError(
            f"telecasts: {repeated_games} game(s) have more than one plotted telecast"
        )
    unrated_frame, duplicates_dropped = select_unrated_shipped(tables.telecasts, sort_keys)
    freshness = _build_freshness(tables)
    games_slim = tables.games.select(
        "game_id",
        "season_type",
        "week",
        "home_team",
        "away_team",
        "neutral_site",
        "home_points",
        "away_points",
        "home_rank",
        "away_rank",
        "excitement",
        "closing_spread",
        "game_type",
        "playoff_round",
        "home_conference",
        "away_conference",
        "home_classification",
        "away_classification",
    )
    rated_rows = list(plotted.join(games_slim, on="game_id", how="left").iter_rows(named=True))
    unrated_rows = list(
        unrated_frame.join(games_slim, on="game_id", how="left").iter_rows(named=True)
    )
    shipped_rows = rated_rows + unrated_rows
    unusable = sum(1 for row in rated_rows if not is_usable_value(row["headline_value"]))
    if unusable:
        # Backstop for the plotted rule (CR-02): fail with a clean,
        # count-only error rather than a TypeError from round(None) or a
        # contract failure on a 0-viewer dot.
        raise VaultStateError(
            f"telecasts: {unusable} plotted row(s) without a usable headline_value"
        )
    missing_game_type = sum(1 for row in shipped_rows if row["game_type"] is None)
    if missing_game_type:
        raise VaultStateError(f"telecasts: {missing_game_type} shipped row(s) without a game_type")
    missing_fbs_conference = sum(
        1
        for row in shipped_rows
        if (row["home_classification"] == "fbs" and row["home_conference"] is None)
        or (row["away_classification"] == "fbs" and row["away_conference"] is None)
    )
    if missing_fbs_conference:
        raise VaultStateError(
            f"telecasts: {missing_fbs_conference} shipped row(s) with an FBS side but no conference"
        )
    bowl_entries = load_bowls(reference_directory)
    missing_bowl = 0
    bowl_disagreements = 0
    for row in shipped_rows:
        if row["game_type"] not in _POSTSEASON_TYPES:
            continue
        entry = bowl_entries.get(int(row["game_id"]))
        if entry is None:
            missing_bowl += 1
            continue
        if row["game_type"] == "bowl":
            expects_at_bowl = True
        else:
            expects_at_bowl = row["playoff_round"] in _CFP_AT_BOWL_ROUNDS
        if entry.at_bowl != expects_at_bowl:
            bowl_disagreements += 1
    if missing_bowl and bowl_crosswalk == "strict":
        raise BowlCrosswalkError(
            f"telecasts: {missing_bowl} shipped postseason row(s) without a bowls.csv entry; "
            "see interim/review_bowls.csv"
        )
    if bowl_disagreements:
        raise VaultStateError(
            f"bowls.csv: {bowl_disagreements} row(s) disagree with the game's type (at_bowl)"
        )
    season_by_game = {
        int(row["game_id"]): int(row["season"])
        for row in shipped_rows
        if row["game_type"] in _POSTSEASON_TYPES
    }
    bowls_no_franchise = 0
    if bowl_crosswalk == "lenient":
        for game_id in list(season_by_game):
            soft = bowl_entries.get(game_id)
            if (
                soft is not None
                and soft.at_bowl
                and soft.core_name is not None
                and soft.franchise is None
            ):
                del season_by_game[game_id]
                bowls_no_franchise += 1
    franchises = build_franchises(bowl_entries, season_by_game)
    franchise_slugs = sorted(franchises)
    franchise_index = {slug: i for i, slug in enumerate(franchise_slugs)}
    # Keyed by official name, core name, and franchise, so two bowls that share
    # both names but belong to different franchises stay apart (04.9 D-07).
    bowl_triples: set[tuple[str, str, str]] = set()
    for row in shipped_rows:
        if row["game_type"] not in _POSTSEASON_TYPES:
            continue
        found = bowl_entries.get(int(row["game_id"]))
        if (
            found is not None
            and found.at_bowl
            and found.official_name is not None
            and found.core_name is not None
            and found.franchise is not None
        ):
            bowl_triples.add((found.official_name, found.core_name, found.franchise))
    bowls_lookup = sorted(bowl_triples)
    bowl_index = {triple: i for i, triple in enumerate(bowls_lookup)}

    rivalries = load_rivalries(reference_directory)
    check_game_slugs(franchise_slugs, [r.rivalry_id for r in rivalries])
    rivalry_resolution = resolve_rivalry_games(tables.games, rivalries)
    tagged_ids = {
        rivalry_resolution.by_game[int(row["game_id"])]
        for row in shipped_rows
        if int(row["game_id"]) in rivalry_resolution.by_game
    }
    used_rivalries = sorted(
        (r for r in rivalries if r.rivalry_id in tagged_ids), key=lambda r: r.rivalry_id
    )
    rivalry_index = {r.rivalry_id: i for i, r in enumerate(used_rivalries)}
    shipped_ids = {row["telecast_id"] for row in shipped_rows}
    rated_ids = {row["telecast_id"] for row in rated_rows}

    crew_by_telecast: dict[str, list[dict[str, object]]] = {}
    for crow in tables.telecast_people.iter_rows(named=True):
        if crow["telecast_id"] not in shipped_ids:
            continue
        crew_by_telecast.setdefault(crow["telecast_id"], []).append(crow)
    for crew_rows in crew_by_telecast.values():
        crew_rows.sort(key=lambda r: (_FEED_ORDER.get(str(r["feed_type"]), 99), r["crew_position"]))

    flags_by_telecast: dict[str, list[str]] = {}
    flag_kind_by_id: dict[str, str] = {}
    for frow in tables.telecast_flags.iter_rows(named=True):
        flag_kind_by_id[frow["flag_id"]] = frow["kind"]
        if frow["telecast_id"] not in shipped_ids:
            continue
        flags_by_telecast.setdefault(frow["telecast_id"], []).append(frow["flag_id"])

    people_by_id: dict[str, dict[str, object]] = {
        prow["person_id"]: prow for prow in tables.people.iter_rows(named=True)
    }
    missing_people = {
        str(crow["person_id"])
        for crew_rows in crew_by_telecast.values()
        for crow in crew_rows
        if crow["person_id"] not in people_by_id
    }
    if missing_people:
        # Backstop for people_links' override check (CR-04): a clean,
        # count-only error instead of a raw KeyError below.
        raise VaultStateError(
            f"telecast_people: {len(missing_people)} person_id(s) missing from the people table"
        )

    # -- Pass 1: discover every referenced lookup value -------------------------------------
    team_names: set[str] = set()
    network_ids: set[str] = set()
    person_ids: set[str] = set()
    publishers: set[str] = set()
    flag_ids: set[str] = set()
    conference_is_fbs: dict[str, bool] = {}

    for row in shipped_rows:
        team_names.add(str(row["home_team"]))
        team_names.add(str(row["away_team"]))
        network_ids.add(
            row["network_id"] if row["network_id"] is not None else _UNMAPPED_NETWORK_ID
        )
        for outlet in row["outlets"]:
            network_ids.add(outlet)
        if row["telecast_id"] in rated_ids:
            if row["headline_publisher"]:
                publishers.add(row["headline_publisher"])
            flag_ids.update(flags_by_telecast.get(row["telecast_id"], []))
        for crow in crew_by_telecast.get(row["telecast_id"], []):
            person_ids.add(str(crow["person_id"]))
        for side in ("home", "away"):
            conf = row[f"{side}_conference"]
            if conf is None:
                continue
            is_fbs = row[f"{side}_classification"] == "fbs"
            conference_is_fbs[conf] = conference_is_fbs.get(conf, False) or is_fbs

    for crow in coverage.rows:
        network_id = crow["network_id"]
        if network_id is None:
            # Rated telecasts with no mapped network: their own coverage
            # row points at the "unmapped" lookup entry, the same one the
            # telecast columns use (WR-07).
            network_ids.add(_UNMAPPED_NETWORK_ID)
        elif network_id != "ALL":
            network_ids.add(str(network_id))

    team_index = {name: i for i, name in enumerate(sorted(team_names))}
    network_index = {network_id: i for i, network_id in enumerate(sorted(network_ids))}
    person_index = {person_id: i for i, person_id in enumerate(sorted(person_ids))}
    publisher_index = {name: i for i, name in enumerate(sorted(publishers))}
    flag_index = {flag_id: i for i, flag_id in enumerate(sorted(flag_ids))}
    unmatched_rivalry_teams = sum(
        1 for r in used_rivalries if r.team_a not in team_index or r.team_b not in team_index
    )
    if unmatched_rivalry_teams:
        raise VaultStateError(
            f"rivalries.csv: {unmatched_rivalry_teams} rivalr(ies) whose team names differ "
            "from their shipped games"
        )
    rivalries_lookup = [
        {
            "slug": r.rivalry_id,
            "name": r.name,
            "article": r.article,
            "teams": sorted([team_index[r.team_a], team_index[r.team_b]]),
        }
        for r in used_rivalries
    ]
    conference_index = {name: i for i, name in enumerate(sorted(conference_is_fbs))}

    teams = [{"name": name} for name in sorted(team_names)]
    conferences = [
        {"name": name, "is_fbs": conference_is_fbs[name]} for name in sorted(conference_is_fbs)
    ]
    networks = [
        {
            "id": network_id,
            "name": network_info.get(network_id, (network_id, "other"))[0],
            "family": network_info.get(network_id, (network_id, "other"))[1],
        }
        for network_id in sorted(network_ids)
    ]
    people = [
        {
            "id": person_id,
            "name": str(people_by_id[person_id]["canonical_name"]),
            "variants": _as_str_list(people_by_id[person_id]["variants"]),
            "usual_role": people_by_id[person_id]["usual_role"],
        }
        for person_id in sorted(person_ids)
    ]
    publisher_list = sorted(publishers)

    flags: list[dict[str, object]] = []
    for flag_id in sorted(flag_ids):
        kind = flag_kind_by_id.get(flag_id, "era")
        if kind == "era":
            era = eras.get(flag_id)
            label = era.label if era is not None else flag_id
            source_url = era.source_url if era is not None else None
        elif kind == "measurement":
            label = _MEASUREMENT_FLAG_LABEL
            source_url = None
        elif kind == "combined":
            label = _COMBINED_FLAG_LABEL
            source_url = None
        else:
            event = event_flags.get(flag_id)
            label = event.label if event is not None else flag_id
            source_url = event.source_url if event is not None else None
        flags.append({"id": flag_id, "kind": kind, "label": label, "source_url": source_url})

    # -- Pass 2: build every TelecastColumns / UnratedColumns array ---------------------------
    shared_names = (
        "season",
        "date",
        "kickoff",
        "time_slot",
        "away_team",
        "home_team",
        "neutral",
        "away_points",
        "home_points",
        "away_rank",
        "home_rank",
        "network",
        "outlets",
        "s506_url",
        "crew_source_url",
        "crew_source_label",
        "excitement",
        "home_spread",
        "crew",
        "game_type",
        "playoff_round",
        "home_conference",
        "away_conference",
        "bowl",
        "rivalry",
    )
    rated_only_names = (
        "viewers",
        "measurement_type",
        "publisher",
        "source_url",
        "rr_urls",
        "flags",
        "combined_feeds",
    )
    columns: dict[str, list[object]] = {name: [] for name in (*shared_names, *rated_only_names)}
    unrated_columns: dict[str, list[object]] = {name: [] for name in (*shared_names, "cause")}

    def _append_game_fields(target: dict[str, list[object]], row: dict[str, Any]) -> None:
        kickoff_value = row["kickoff_et"]
        network_key = row["network_id"] if row["network_id"] is not None else _UNMAPPED_NETWORK_ID
        target["season"].append(int(row["season"]))
        target["date"].append(row["date_et"].isoformat())
        target["kickoff"].append(kickoff_value)
        target["time_slot"].append(time_slot(kickoff_value))
        target["away_team"].append(team_index[str(row["away_team"])])
        target["home_team"].append(team_index[str(row["home_team"])])
        target["neutral"].append(bool(row["neutral_site"]))
        target["away_points"].append(row["away_points"])
        target["home_points"].append(row["home_points"])
        target["away_rank"].append(row["away_rank"])
        target["home_rank"].append(row["home_rank"])
        target["network"].append(network_index[network_key])
        target["outlets"].append([network_index[o] for o in row["outlets"]])
        target["s506_url"].append(row["s506_url"])
        target["crew_source_url"].append(row["crew_source_url"])
        target["crew_source_label"].append(row["crew_source_label"])
        target["excitement"].append(row["excitement"])
        target["home_spread"].append(row["closing_spread"])
        target["crew"].append(
            [
                {
                    "person": person_index[str(crow["person_id"])],
                    "role": crow["role"],
                    "feed": crow["feed_type"],
                }
                for crow in crew_by_telecast.get(row["telecast_id"], [])
            ]
        )
        target["game_type"].append(row["game_type"])
        target["playoff_round"].append(row["playoff_round"])
        home_conf = row["home_conference"]
        target["home_conference"].append(
            conference_index[home_conf] if home_conf is not None else None
        )
        away_conf = row["away_conference"]
        target["away_conference"].append(
            conference_index[away_conf] if away_conf is not None else None
        )
        bowl_entry = (
            bowl_entries.get(int(row["game_id"])) if row["game_type"] in _POSTSEASON_TYPES else None
        )
        if (
            bowl_entry is not None
            and bowl_entry.official_name is not None
            and bowl_entry.core_name is not None
            and bowl_entry.franchise is not None
        ):
            target["bowl"].append(
                bowl_index[(bowl_entry.official_name, bowl_entry.core_name, bowl_entry.franchise)]
            )
        else:
            target["bowl"].append(None)
        tagged = rivalry_resolution.by_game.get(int(row["game_id"]))
        target["rivalry"].append(rivalry_index[tagged] if tagged is not None else None)

    for row in rated_rows:
        _append_game_fields(columns, row)
        columns["viewers"].append(round(row["headline_value"]))
        columns["measurement_type"].append(row["measurement_type"])
        columns["publisher"].append(
            publisher_index[row["headline_publisher"]] if row["headline_publisher"] else None
        )
        columns["source_url"].append(row["headline_source_url"])
        columns["rr_urls"].append(list(row["rr_record_urls"]))
        columns["flags"].append(
            [flag_index[f] for f in flags_by_telecast.get(row["telecast_id"], [])]
        )
        columns["combined_feeds"].append(row["combined_feeds"])

    for row in unrated_rows:
        _append_game_fields(unrated_columns, row)
        unrated_columns["cause"].append(
            no_rating_cause(
                season=int(row["season"]),
                season_type=str(row["season_type"]),
                week=int(row["week"]),
                network_id=str(row["network_id"]),
                rarely_rated=rarity,
                current_season=_as_int(freshness["season"]),
                viewership_through_week=freshness["viewership_through_week"],  # type: ignore[arg-type]
                rated_not_plotted=bool(row["rated"]),
            )
        )

    # -- coverage: publisher_counts per (season, network), and per-season totals ------------
    publisher_counts_by_key: dict[tuple[int, str], dict[str, int]] = {}
    publisher_counts_by_season: dict[int, dict[str, int]] = {}
    for prow in coverage.publisher_rows:
        season_key = _as_int(prow["season"])
        network_key_raw = prow["network_id"]
        publisher_name = str(prow["publisher"])
        count = _as_int(prow["headline_count"])
        season_bucket = publisher_counts_by_season.setdefault(season_key, {})
        season_bucket[publisher_name] = season_bucket.get(publisher_name, 0) + count
        network_key = str(network_key_raw) if network_key_raw is not None else _UNMAPPED_NETWORK_ID
        per_network_bucket = publisher_counts_by_key.setdefault((season_key, network_key), {})
        per_network_bucket[publisher_name] = per_network_bucket.get(publisher_name, 0) + count

    coverage_rows: list[dict[str, object]] = []
    for crow in coverage.rows:
        crow_season = _as_int(crow["season"])
        network_id = crow["network_id"]
        if network_id == "ALL":
            # network=None is reserved for the season-wide "ALL" row.
            network_field: int | None = None
            pub_counts = publisher_counts_by_season.get(crow_season, {})
        else:
            network_key = str(network_id) if network_id is not None else _UNMAPPED_NETWORK_ID
            network_field = network_index[network_key]
            pub_counts = publisher_counts_by_key.get((crow_season, network_key), {})

        rated_telecasts = _as_int(crow["rated_telecasts"])
        coverage_rows.append(
            {
                "season": crow_season,
                "network": network_field,
                "rated_telecasts": rated_telecasts,
                "matched_game": rated_telecasts,
                "matched_crew": _as_int(crow["matched_crew"]),
                "matched_crew_patched": _as_int(crow["crew_patched"]),
                "match_rate": crow["match_rate"],
                "headline_present": _as_int(crow["headline_present"]),
                "excitement_present": _as_int(crow["excitement_present"]),
                "spread_present": _as_int(crow["spread_present"]),
                "duplicate_merges": _as_int(crow["duplicate_merges"]),
                "combined_figures": _as_int(crow["combined_figures"]),
                "publisher_counts": pub_counts,
            }
        )

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at.isoformat(),
        "freshness": freshness,
        "lookups": {
            "teams": teams,
            "networks": networks,
            "people": people,
            "publishers": publisher_list,
            "flags": flags,
            "conferences": conferences,
            "bowls": [
                {"name": n, "core": c, "franchise": franchise_index[f]} for n, c, f in bowls_lookup
            ],
            "bowl_franchises": [
                {
                    "slug": slug,
                    "name": franchises[slug].name,
                    "former": list(franchises[slug].former),
                }
                for slug in franchise_slugs
            ],
            "rivalries": rivalries_lookup,
        },
        "telecasts": columns,
        "telecasts_unrated": unrated_columns,
        "coverage": coverage_rows,
    }
    if counts is not None:
        counts["bowls_no_franchise"] = bowls_no_franchise
        counts["rivalry_games_tagged"] = len(rivalry_resolution.by_game)
        counts["rivalry_telecasts_tagged"] = sum(
            1 for v in (*columns["rivalry"], *unrated_columns["rivalry"]) if v is not None
        )
        counts["unrated_shipped"] = len(unrated_rows)
        counts["unrated_left_out"] = tables.telecasts.filter(left_out_unrated_expr()).height
        counts["unrated_duplicates_dropped"] = duplicates_dropped
        flagged_rated, unflagged_unrated = rarity_contradictions(
            network_rated_counts(tables.telecasts), rarity
        )
        counts["rarely_rated_but_mostly_rated"] = flagged_rated
        counts["not_rarely_rated_but_mostly_unrated"] = unflagged_unrated
        counts["rivalry_title_games_excluded"] = rivalry_resolution.title_games_excluded
        counts["rivalry_rematches_demoted"] = rivalry_resolution.rematches_demoted
    try:
        return validate_site_data(payload)
    except ValidationError as exc:
        raise VaultStateError(_contract_error_summary(exc)) from None


_MAX_REPORTED_ERRORS = 5


def _contract_error_summary(exc: ValidationError) -> str:
    """A contract failure described by field location and error type only.

    pydantic's own messages can embed the offending cell (`input_value=...`),
    which may be a vault value, so only `loc` and `type` are kept -- plus the
    message of a `value_error`, which is always one of the contract's own
    model_validator messages (column and position only, T-03-04). The
    exception is re-raised `from None` so the original error (and its
    input) never reaches a traceback.
    """
    errors = exc.errors(include_input=False, include_url=False, include_context=False)
    parts: list[str] = []
    for error in errors[:_MAX_REPORTED_ERRORS]:
        loc = ".".join(str(part) for part in error["loc"]) or "<root>"
        detail = error["type"]
        if error["type"] == "value_error":
            detail = f"{detail}: {error['msg']}"
        parts.append(f"{loc} ({detail})")
    more = len(errors) - _MAX_REPORTED_ERRORS
    suffix = f"; {more} more" if more > 0 else ""
    return f"site data failed the contract: {len(errors)} error(s): {'; '.join(parts)}{suffix}"


def write_site_data(paths: DataPaths, site: SiteData) -> list[str]:
    """Write `processed/site-data.json`: compact JSON (",", ":" separators,
    sorted keys), atomically. Returns its vault-relative path.
    """
    payload = site.model_dump(mode="json")
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    atomic_write_bytes(paths.processed / "site-data.json", body)
    return ["processed/site-data.json"]
