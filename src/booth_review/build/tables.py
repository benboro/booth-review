"""Assembly, writer, and counts-only diagnostic for the full build: games,
telecasts, viewership, telecast_flags, listing_links, and (empty until Plan
09) people/telecast_people, plus every review CSV the build discovers.

`main` prints season-by-season and overall counts only (T-03-28/T-03-31):
RR record accounting, rated-telecast/crew counts, the JOIN-08 rate, headline
agreement counts, and era-disagreement counts -- never a team, announcer, or
figure.
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

import polars as pl

from booth_review.build.bowls import BowlEntry, load_bowls
from booth_review.build.combined import (
    REVIEW_COMBINED_COLUMNS,
    CombinedCandidate,
    CombinedDecision,
    apply_combined,
    decision_for,
    find_combined_candidates,
    load_combined_figures,
    orphan_decision_count,
)
from booth_review.build.crew_overrides import (
    REVIEW_CREW_GAPS_COLUMNS,
    apply_crew_overrides,
    crew_gap_rows,
    load_crew_overrides,
    unmatched_506_keys,
)
from booth_review.build.games import build_games_frame
from booth_review.build.io import write_parquet_atomic, write_review_csv
from booth_review.build.people_links import (
    NEW_NAME_COLUMNS,
    build_people_links,
)
from booth_review.build.people_links import (
    PEOPLE_SCHEMA as PEOPLE_SCHEMA,
)
from booth_review.build.people_links import (
    TELECAST_PEOPLE_SCHEMA as TELECAST_PEOPLE_SCHEMA,
)
from booth_review.build.shipped import (
    network_rated_counts,
    rarity_verdict,
    shipped_expr,
)
from booth_review.build.sources import load_all_sources, load_cfbd_venues
from booth_review.build.telecasts import build_telecasts
from booth_review.build.venues import (
    empty_venues_frame,
    fill_venue_locations,
    load_venue_locations,
    venues_frame,
)
from booth_review.build.viewership import (
    TELECAST_FLAGS_SCHEMA as TELECAST_FLAGS_SCHEMA,
)
from booth_review.build.viewership import (
    apply_headlines,
    build_viewership,
)
from booth_review.config import DataPaths
from booth_review.flags.era import load_eras
from booth_review.flags.events import load_event_flags
from booth_review.people.registry import load_people, load_person_overrides
from booth_review.reference import reference_dir
from booth_review.resolve.diagnose import (
    UNMATCHED_COLUMNS,
    UNRESOLVED_COLUMNS,
    unmatched_row,
    unresolved_rows,
)
from booth_review.resolve.games import GameIndex
from booth_review.resolve.networks import (
    check_primary_overrides,
    load_network_rarity,
    load_networks,
    load_primary_overrides,
)
from booth_review.resolve.overrides import load_game_overrides, pointer_for_listing
from booth_review.resolve.teams import TeamResolver, load_team_crosswalk
from booth_review.sources.sports506.parser import Listing506
from booth_review.vault import VaultRepo

HEADLINE_DISAGREEMENT_COLUMNS = (
    "telecast_id",
    "rr_telecast_id",
    "headline_claim_id",
    "rr_current_claim_id",
    "reason",
)
ERA_DISAGREEMENT_COLUMNS = ("telecast_id", "rr_telecast_id", "claim_id", "era_id", "rr_era_id")

_PARQUET_TABLES: tuple[str, ...] = (
    "games",
    "telecasts",
    "viewership",
    "telecast_flags",
    "listing_links",
    "people",
    "telecast_people",
)


@dataclass(frozen=True)
class BuildDiagnostics:
    per_season: dict[int, dict[str, int]]
    totals: dict[str, int]
    join08_rate: float | None
    join08_by_season: dict[int, float | None]


@dataclass(frozen=True)
class BuildTables:
    games: pl.DataFrame
    telecasts: pl.DataFrame
    viewership: pl.DataFrame
    telecast_flags: pl.DataFrame
    listing_links: pl.DataFrame
    people: pl.DataFrame
    telecast_people: pl.DataFrame
    diagnostics: BuildDiagnostics
    review_rows: dict[str, tuple[tuple[str, ...], list[dict[str, object]]]]
    # crew_overrides.csv lines whose crew differs from 506's without `correction`.
    crew_override_differs_lines: tuple[int, ...] = ()
    # CFBD /venues, for the Map's lookups.venues; empty until collected.
    venues: pl.DataFrame = field(default_factory=empty_venues_frame)


def _combined_review_row(
    candidate: CombinedCandidate, decision: CombinedDecision | None
) -> dict[str, object]:
    return {
        "candidate_id": candidate.telecast_id,
        "rr_telecast_id": candidate.rr_telecast_id,
        "season": candidate.season,
        "date_et": candidate.date_et.isoformat(),
        "network_id": candidate.network_id or "",
        "reasons": "|".join(candidate.reasons),
        "alt_feed_count": candidate.alt_feed_count,
        "headline_value": candidate.headline_value,
        "network_median": candidate.network_median,
        "proposed": candidate.proposed,
        "proposed_feeds": candidate.proposed_feeds,
        "decision": decision.decision if decision is not None else "",
    }


def _join08_rate(
    records_with_crew: int, rr_records: int, rr_excluded: int, rr_out_of_scope: int
) -> float | None:
    denominator = rr_records - rr_excluded - rr_out_of_scope
    if denominator <= 0:
        return None
    return records_with_crew / denominator


def _build_diagnostics(counts: dict[int, dict[str, int]]) -> BuildDiagnostics:
    totals: dict[str, int] = {}
    join08_by_season: dict[int, float | None] = {}
    for season, season_counts in counts.items():
        for key, value in season_counts.items():
            totals[key] = totals.get(key, 0) + value
        join08_by_season[season] = _join08_rate(
            season_counts["records_with_crew"],
            season_counts["rr_records"],
            season_counts["rr_excluded"],
            season_counts["rr_out_of_scope"],
        )
    join08_rate = _join08_rate(
        totals.get("records_with_crew", 0),
        totals.get("rr_records", 0),
        totals.get("rr_excluded", 0),
        totals.get("rr_out_of_scope", 0),
    )
    return BuildDiagnostics(
        per_season=counts,
        totals=totals,
        join08_rate=join08_rate,
        join08_by_season=join08_by_season,
    )


REVIEW_BOWLS_COLUMNS = (
    "cfbd_game_id",
    "season",
    "date_et",
    "game_type",
    "playoff_round",
    "away_team",
    "home_team",
    "raw_note",
)

_POSTSEASON_GAME_TYPES = ("bowl", "playoff")


def _shipped_postseason_games(telecasts: pl.DataFrame, games: pl.DataFrame) -> pl.DataFrame:
    """Games of shipped (rated or unrated) bowl/CFP telecasts, one row per game,
    sorted by season then id. Uses the build_site_data predicate (04.13 D-14).
    """
    plotted_ids = telecasts.filter(shipped_expr())["game_id"].unique()
    return games.filter(
        pl.col("game_id").is_in(plotted_ids.implode())
        & pl.col("game_type").is_in(_POSTSEASON_GAME_TYPES)
    ).sort(["season", "game_id"])


def bowl_review_rows(
    telecasts: pl.DataFrame, games: pl.DataFrame, bowls: Mapping[int, BowlEntry]
) -> list[dict[str, object]]:
    """One row per shipped postseason game with no bowls.csv row, with its
    raw CFBD note as the fill aid. Vault-only (interim/); never published.
    """
    rows: list[dict[str, object]] = []
    for game in _shipped_postseason_games(telecasts, games).iter_rows(named=True):
        if game["game_id"] in bowls:
            continue
        rows.append(
            {
                "cfbd_game_id": game["game_id"],
                "season": game["season"],
                "date_et": game["date_et"],
                "game_type": game["game_type"],
                "playoff_round": game["playoff_round"],
                "away_team": game["away_team"],
                "home_team": game["home_team"],
                "raw_note": game["notes"],
            }
        )
    return rows


REVIEW_NETWORK_RARITY_COLUMNS = ("network_id", "main_feed_games", "rated", "rarely_rated", "audit")


def network_rarity_review_rows(
    telecasts: pl.DataFrame, rarity: Mapping[str, bool]
) -> list[dict[str, object]]:
    """One row per network with main-feed telecasts or a rarity flag, so the
    hand-set flags can be checked. Vault-only (interim/); never published.
    """
    counts = network_rated_counts(telecasts)
    rows: list[dict[str, object]] = []
    for network_id in sorted(set(counts) | set(rarity)):
        games, rated = counts.get(network_id, (0, 0))
        flag = rarity.get(network_id)
        verdict = rarity_verdict(games, rated, bool(flag))
        rows.append(
            {
                "network_id": network_id,
                "main_feed_games": games,
                "rated": rated,
                "rarely_rated": "" if flag is None else str(flag).lower(),
                "audit": "contradicts" if verdict is not None else "",
            }
        )
    return rows


def assemble_tables(
    paths: DataPaths, reference_directory: Path, seasons: Sequence[int] | None = None
) -> BuildTables:
    """Load every raw source, match/merge/flag every telecast (JOIN-02..08,
    FLAG-01..04), and return every table and review row the build produces.
    Never writes anything -- see write_tables.
    """
    sources = load_all_sources(paths, seasons)
    games = build_games_frame(sources)

    crosswalk = load_team_crosswalk(reference_directory)
    resolver = TeamResolver({s.season: s.games for s in sources}, crosswalk)
    index = GameIndex([g for s in sources for g in s.games])
    overrides = load_game_overrides(reference_directory)
    # Required here (WR-06): a missing networks.csv would otherwise turn every
    # telecast "unmapped" without failing the build.
    networks = load_networks(reference_directory, required=True)
    primary_overrides = load_primary_overrides(reference_directory)
    check_primary_overrides(primary_overrides, networks)

    media_by_game: dict[int, list[str]] = {}
    for season_sources in sources:
        for media in season_sources.media:
            if media.outlet:
                media_by_game.setdefault(media.id, []).append(media.outlet)

    telecast_build = build_telecasts(
        sources, games, resolver, index, overrides, networks, primary_overrides, media_by_game
    )

    eras = load_eras(reference_directory)
    event_flags = load_event_flags(reference_directory)

    viewership = build_viewership(telecast_build, eras)
    telecasts, disagreement_rows, era_disagreement_rows, telecast_flags = apply_headlines(
        telecast_build.telecasts, viewership, telecast_build.records_by_telecast, eras, event_flags
    )

    combined_decisions = load_combined_figures(reference_directory)
    combined_candidates = find_combined_candidates(
        telecasts, viewership, telecast_build.listing_links
    )
    telecasts, telecast_flags = apply_combined(
        telecasts, telecast_flags, combined_candidates, combined_decisions
    )

    registry = load_people(reference_directory)
    person_overrides = load_person_overrides(reference_directory)
    listings_by_pointer: dict[tuple[int, str], Listing506] = {
        (season_sources.season, pointer_for_listing(listing)): listing
        for season_sources in sources
        for listing in season_sources.listings
    }
    people_links = build_people_links(
        telecast_build.listing_links,
        listings_by_pointer,
        telecasts,
        registry,
        person_overrides,
        networks,
    )
    people = people_links.people
    telecast_people = people_links.telecast_people

    # 04.3 D-13: overrides land after the 506 crews are linked and before the
    # diagnostics, so patched crews reach coverage, JOIN-08, metrics, site data.
    telecasts_pre = telecasts
    telecast_people_pre = telecast_people
    crew_overrides = load_crew_overrides(reference_directory)
    override_result = apply_crew_overrides(
        telecasts, telecast_people, crew_overrides, registry, telecast_build.counts
    )
    telecasts = override_result.telecasts
    telecast_people = override_result.telecast_people
    crew_gap_review = crew_gap_rows(
        telecasts_pre,
        games,
        telecast_people_pre,
        override_result.statuses,
        unmatched_506_keys(telecast_build.unmatched_rows, networks),
    )

    unmatched_review_rows: list[dict[str, object]] = [
        dict(unmatched_row(row)) for row in telecast_build.unmatched_rows
    ]
    unresolved_review_rows: list[dict[str, object]] = [
        dict(row) for row in unresolved_rows(telecast_build.unresolved_rows)
    ]

    bowl_entries = load_bowls(reference_directory)
    bowl_rows = bowl_review_rows(telecasts, games, bowl_entries)
    rarity = load_network_rarity(reference_directory)

    review_rows: dict[str, tuple[tuple[str, ...], list[dict[str, object]]]] = {
        "review_bowls": (REVIEW_BOWLS_COLUMNS, bowl_rows),
        "review_network_rarity": (
            REVIEW_NETWORK_RARITY_COLUMNS,
            network_rarity_review_rows(telecasts, rarity),
        ),
        "review_crew_overrides": (REVIEW_CREW_GAPS_COLUMNS, crew_gap_review),
        "review_unmatched": (UNMATCHED_COLUMNS, unmatched_review_rows),
        "review_unresolved_teams": (UNRESOLVED_COLUMNS, unresolved_review_rows),
        "review_headline_disagreements": (HEADLINE_DISAGREEMENT_COLUMNS, disagreement_rows),
        "review_era_disagreements": (ERA_DISAGREEMENT_COLUMNS, era_disagreement_rows),
        "review_people_new": (NEW_NAME_COLUMNS, people_links.new_name_rows),
        "review_combined": (
            REVIEW_COMBINED_COLUMNS,
            [
                _combined_review_row(c, decision_for(c, combined_decisions))
                for c in combined_candidates
            ],
        ),
    }

    diagnostics = _build_diagnostics(override_result.season_counts)
    merged_totals = dict(diagnostics.totals)
    merged_totals.update({f"people_{key}": value for key, value in people_links.counts.items()})
    merged_totals["combined_candidates_alt_listed"] = sum(
        1 for c in combined_candidates if "alt_listed" in c.reasons
    )
    merged_totals["combined_candidates_outlier"] = sum(
        1 for c in combined_candidates if "outlier" in c.reasons
    )
    merged_totals["combined_decided"] = sum(
        1 for c in combined_candidates if decision_for(c, combined_decisions) is not None
    )
    merged_totals["combined_combined"] = sum(
        1
        for c in combined_candidates
        if (d := decision_for(c, combined_decisions)) is not None and d.decision == "combined"
    )
    merged_totals["combined_orphan_decisions"] = orphan_decision_count(
        combined_candidates, combined_decisions
    )
    merged_totals.update(
        {f"crew_overrides_{key}": value for key, value in override_result.counts.items()}
    )
    merged_totals["crew_gaps_unpatched"] = sum(
        1 for r in crew_gap_review if r["override_status"] == "missing"
    )
    venues, venues_from_reference = fill_venue_locations(
        venues_frame(load_cfbd_venues(paths)), load_venue_locations(reference_directory)
    )
    merged_totals["venues_from_reference"] = venues_from_reference
    merged_totals["bowls_missing"] = len(bowl_rows)
    merged_totals["bowl_names_unknown"] = sum(
        1
        for game in _shipped_postseason_games(telecasts, games).iter_rows(named=True)
        if (entry := bowl_entries.get(game["game_id"])) is not None
        and entry.at_bowl
        and entry.official_name is None
    )
    diagnostics = replace(diagnostics, totals=merged_totals)

    return BuildTables(
        games=games,
        telecasts=telecasts,
        viewership=viewership,
        telecast_flags=telecast_flags,
        listing_links=telecast_build.listing_links,
        people=people,
        telecast_people=telecast_people,
        diagnostics=diagnostics,
        review_rows=review_rows,
        crew_override_differs_lines=override_result.differs_lines,
        venues=venues,
    )


def write_tables(paths: DataPaths, tables: BuildTables, *, processed: bool = True) -> list[str]:
    """Write every processed Parquet table and interim review CSV, atomically
    (build.io), returning the sorted list of vault-relative paths written.
    `processed=False` writes only the interim review CSVs (a blocked build,
    build.pipeline).
    """
    written: list[str] = []
    for name in _PARQUET_TABLES if processed else ():
        frame: pl.DataFrame = getattr(tables, name)
        rel_path = f"processed/{name}.parquet"
        write_parquet_atomic(frame, paths.vault / rel_path)
        written.append(rel_path)

    for name, (columns, rows) in tables.review_rows.items():
        rel_path = f"interim/{name}.csv"
        write_review_csv(paths.vault / rel_path, columns, rows)
        written.append(rel_path)

    return sorted(written)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Build the games/telecasts/viewership/flags tables."
    )
    parser.add_argument("--no-write", action="store_true", help="Print counts only; write nothing.")
    parser.add_argument("--season", type=int, default=None)
    args = parser.parse_args(argv)

    if args.season is not None and not args.no_write:
        # A single season's tables would overwrite every season's processed
        # tables, bypassing the regression guard (WR-08); only
        # `booth-review build` writes processed tables for real.
        parser.error("--season requires --no-write (use `booth-review build` to write tables)")

    paths = DataPaths.from_env()
    seasons = [args.season] if args.season is not None else None
    tables = assemble_tables(paths, reference_dir(), seasons)
    if not args.no_write:
        with VaultRepo(paths.vault).lock():
            write_tables(paths, tables)

    print(
        "season | rr_records | matched | out_of_scope | unmatched | "
        "rated_telecasts | records_with_crew | duplicate_merges | JOIN-08"
    )
    for season in sorted(tables.diagnostics.per_season):
        counts = tables.diagnostics.per_season[season]
        rate = tables.diagnostics.join08_by_season.get(season)
        rate_text = f"{rate * 100:.1f}%" if rate is not None else "n/a"
        print(
            f"  {season} | {counts['rr_records']} | {counts['rr_matched']} | "
            f"{counts['rr_out_of_scope']} | {counts['rr_unmatched']} | "
            f"{counts['rated_telecasts']} | {counts['records_with_crew']} | "
            f"{counts['duplicate_merges']} | {rate_text}"
        )

    overall_rate = tables.diagnostics.join08_rate
    overall_text = f"{overall_rate * 100:.1f}%" if overall_rate is not None else "n/a"
    print(f"overall JOIN-08 rate: {overall_text}")

    check_counts = Counter(tables.telecasts["rr_current_check"].drop_nulls().to_list())
    print(
        f"headline agree/disagree/not_comparable: {check_counts.get('agree', 0)}/"
        f"{check_counts.get('disagree', 0)}/{check_counts.get('not_comparable', 0)}"
    )
    print(f"era disagreements: {len(tables.review_rows['review_era_disagreements'][1])}")

    totals = tables.diagnostics.totals
    print(
        "crew overrides applied/patched/redundant/differs/corrections: "
        f"{totals.get('crew_overrides_applied', 0)}/"
        f"{totals.get('crew_overrides_patched', 0)}/"
        f"{totals.get('crew_overrides_redundant', 0)}/"
        f"{totals.get('crew_overrides_differs', 0)}/"
        f"{totals.get('crew_overrides_corrections', 0)}"
    )
    print(f"crew gaps unpatched: {totals.get('crew_gaps_unpatched', 0)}")
    print(
        "people rows by role (pbp/analyst/unknown): "
        f"{totals.get('people_rows_role_pbp', 0)}/"
        f"{totals.get('people_rows_role_analyst', 0)}/"
        f"{totals.get('people_rows_role_unknown', 0)}"
    )
    print(
        "people rows by feed (main/alt/spanish): "
        f"{totals.get('people_rows_feed_main', 0)}/"
        f"{totals.get('people_rows_feed_alt', 0)}/"
        f"{totals.get('people_rows_feed_spanish', 0)}"
    )
    print(
        f"provisional persons: {totals.get('people_provisional_persons', 0)} | "
        f"unlinked alt listings: {totals.get('people_unlinked_alt_listings', 0)} | "
        f"override rows: {totals.get('people_override_rows', 0)}"
    )
    print(
        "combined candidates (alt_listed/outlier): "
        f"{totals.get('combined_candidates_alt_listed', 0)}/"
        f"{totals.get('combined_candidates_outlier', 0)} | "
        f"decided: {totals.get('combined_decided', 0)} | "
        f"combined: {totals.get('combined_combined', 0)}"
    )


if __name__ == "__main__":
    main()
