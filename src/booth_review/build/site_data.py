"""site-data.json (D-13/D-14): assemble and write the Phase 4 static site's
one data file from the already-built processed tables (build.tables,
build.coverage), validated against the pydantic contract
(contract.models.validate_site_data) before it is ever written.

Only `telecasts.plotted` rows become dots (D-10): a headline figure resolved
on the main broadcast feed. Every field this module assembles is one of
`contract.models.SITE_DATA_FIELDS` -- pydantic's own `extra="forbid"` is the
final gate against a CFBD bulk field ever reaching this file (SITE-19).
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
from typing import TYPE_CHECKING, Literal

import polars as pl
from pydantic import ValidationError

from booth_review.config import DataPaths
from booth_review.contract.models import SCHEMA_VERSION, SiteData, validate_site_data
from booth_review.errors import VaultStateError
from booth_review.flags.era import load_eras
from booth_review.flags.events import load_event_flags
from booth_review.resolve.headline import is_usable_value
from booth_review.resolve.networks import load_networks
from booth_review.transport.cache import atomic_write_bytes

if TYPE_CHECKING:
    from booth_review.build.coverage import CoverageReport
    from booth_review.build.tables import BuildTables

_FEED_ORDER: dict[str, int] = {"main": 0, "alt": 1, "spanish": 2}
_UNMAPPED_NETWORK_ID = "unmapped"
_MEASUREMENT_FLAG_LABEL = "Nielsen+Adobe"
_COMBINED_FLAG_LABEL = "Combined across feeds"
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

    crew_ids: set[str] = set(
        season_telecasts.filter(pl.col("crew_matched"))["telecast_id"].to_list()
    )
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
) -> SiteData:
    """Assemble every plotted telecast (D-10) into the D-13 columnar
    SiteData, validated by the D-14 contract (`validate_site_data`) before
    returning. Never writes anything -- see `write_site_data`.
    """
    eras = {era.era_id: era for era in load_eras(reference_directory)}
    event_flags = {flag.flag_id: flag for flag in load_event_flags(reference_directory)}
    network_info = load_networks(reference_directory).networks()

    plotted = tables.telecasts.filter(pl.col("plotted")).sort(
        ["date_et", "kickoff_et", "telecast_id"], nulls_last=True
    )
    games_slim = tables.games.select(
        "game_id",
        "home_team",
        "away_team",
        "neutral_site",
        "home_points",
        "away_points",
        "home_rank",
        "away_rank",
        "excitement",
        "pregame_x",
        "game_type",
        "playoff_round",
        "home_conference",
        "away_conference",
        "home_classification",
        "away_classification",
    )
    rows = list(plotted.join(games_slim, on="game_id", how="left").iter_rows(named=True))
    unusable = sum(1 for row in rows if not is_usable_value(row["headline_value"]))
    if unusable:
        # Backstop for the plotted rule (CR-02): fail with a clean,
        # count-only error rather than a TypeError from round(None) or a
        # contract failure on a 0-viewer dot.
        raise VaultStateError(
            f"telecasts: {unusable} plotted row(s) without a usable headline_value"
        )
    missing_game_type = sum(1 for row in rows if row["game_type"] is None)
    if missing_game_type:
        raise VaultStateError(f"telecasts: {missing_game_type} plotted row(s) without a game_type")
    missing_fbs_conference = sum(
        1
        for row in rows
        if (row["home_classification"] == "fbs" and row["home_conference"] is None)
        or (row["away_classification"] == "fbs" and row["away_conference"] is None)
    )
    if missing_fbs_conference:
        raise VaultStateError(
            f"telecasts: {missing_fbs_conference} plotted row(s) with an FBS side but no conference"
        )
    plotted_ids = {row["telecast_id"] for row in rows}

    crew_by_telecast: dict[str, list[dict[str, object]]] = {}
    for crow in tables.telecast_people.iter_rows(named=True):
        if crow["telecast_id"] not in plotted_ids:
            continue
        crew_by_telecast.setdefault(crow["telecast_id"], []).append(crow)
    for crew_rows in crew_by_telecast.values():
        crew_rows.sort(key=lambda r: (_FEED_ORDER.get(str(r["feed_type"]), 99), r["crew_position"]))

    flags_by_telecast: dict[str, list[str]] = {}
    flag_kind_by_id: dict[str, str] = {}
    for frow in tables.telecast_flags.iter_rows(named=True):
        flag_kind_by_id[frow["flag_id"]] = frow["kind"]
        if frow["telecast_id"] not in plotted_ids:
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

    for row in rows:
        team_names.add(str(row["home_team"]))
        team_names.add(str(row["away_team"]))
        network_ids.add(
            row["network_id"] if row["network_id"] is not None else _UNMAPPED_NETWORK_ID
        )
        for outlet in row["outlets"]:
            network_ids.add(outlet)
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

    # -- Pass 2: build every TelecastColumns array -------------------------------------------
    columns: dict[str, list[object]] = {
        "season": [],
        "date": [],
        "kickoff": [],
        "time_slot": [],
        "away_team": [],
        "home_team": [],
        "neutral": [],
        "away_points": [],
        "home_points": [],
        "away_rank": [],
        "home_rank": [],
        "network": [],
        "outlets": [],
        "viewers": [],
        "measurement_type": [],
        "publisher": [],
        "source_url": [],
        "rr_urls": [],
        "s506_url": [],
        "excitement": [],
        "pregame": [],
        "flags": [],
        "combined_feeds": [],
        "crew": [],
        "game_type": [],
        "playoff_round": [],
        "home_conference": [],
        "away_conference": [],
        "bowl": [],
    }

    for row in rows:
        telecast_id = row["telecast_id"]
        kickoff_value = row["kickoff_et"]
        network_key = row["network_id"] if row["network_id"] is not None else _UNMAPPED_NETWORK_ID

        columns["season"].append(int(row["season"]))
        columns["date"].append(row["date_et"].isoformat())
        columns["kickoff"].append(kickoff_value)
        columns["time_slot"].append(time_slot(kickoff_value))
        columns["away_team"].append(team_index[str(row["away_team"])])
        columns["home_team"].append(team_index[str(row["home_team"])])
        columns["neutral"].append(bool(row["neutral_site"]))
        columns["away_points"].append(row["away_points"])
        columns["home_points"].append(row["home_points"])
        columns["away_rank"].append(row["away_rank"])
        columns["home_rank"].append(row["home_rank"])
        columns["network"].append(network_index[network_key])
        columns["outlets"].append([network_index[o] for o in row["outlets"]])
        columns["viewers"].append(round(row["headline_value"]))
        columns["measurement_type"].append(row["measurement_type"])
        columns["publisher"].append(
            publisher_index[row["headline_publisher"]] if row["headline_publisher"] else None
        )
        columns["source_url"].append(row["headline_source_url"])
        columns["rr_urls"].append(list(row["rr_record_urls"]))
        columns["s506_url"].append(row["s506_url"])
        columns["excitement"].append(row["excitement"])
        columns["pregame"].append(row["pregame_x"])
        columns["flags"].append([flag_index[f] for f in flags_by_telecast.get(telecast_id, [])])
        columns["combined_feeds"].append(row["combined_feeds"])
        columns["crew"].append(
            [
                {
                    "person": person_index[str(crow["person_id"])],
                    "role": crow["role"],
                    "feed": crow["feed_type"],
                }
                for crow in crew_by_telecast.get(telecast_id, [])
            ]
        )
        columns["game_type"].append(row["game_type"])
        columns["playoff_round"].append(row["playoff_round"])
        home_conf = row["home_conference"]
        columns["home_conference"].append(
            conference_index[home_conf] if home_conf is not None else None
        )
        away_conf = row["away_conference"]
        columns["away_conference"].append(
            conference_index[away_conf] if away_conf is not None else None
        )
        # Plan 04.2-04 resolves bowl from data/reference/bowls.csv.
        columns["bowl"].append(None)

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
                "match_rate": crow["match_rate"],
                "headline_present": _as_int(crow["headline_present"]),
                "excitement_present": _as_int(crow["excitement_present"]),
                "pregame_present": _as_int(crow["pregame_present"]),
                "duplicate_merges": _as_int(crow["duplicate_merges"]),
                "combined_figures": _as_int(crow["combined_figures"]),
                "publisher_counts": pub_counts,
            }
        )

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at.isoformat(),
        "freshness": _build_freshness(tables),
        "lookups": {
            "teams": teams,
            "networks": networks,
            "people": people,
            "publishers": publisher_list,
            "flags": flags,
            "conferences": conferences,
            "bowls": [],
        },
        "telecasts": columns,
        "coverage": coverage_rows,
    }
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
