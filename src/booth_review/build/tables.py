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
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from booth_review.build.games import build_games_frame
from booth_review.build.io import write_parquet_atomic, write_review_csv
from booth_review.build.sources import load_all_sources
from booth_review.build.telecasts import build_telecasts
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
from booth_review.reference import reference_dir
from booth_review.resolve.diagnose import (
    UNMATCHED_COLUMNS,
    UNRESOLVED_COLUMNS,
    unmatched_row,
    unresolved_rows,
)
from booth_review.resolve.games import GameIndex
from booth_review.resolve.networks import load_networks, load_primary_overrides
from booth_review.resolve.overrides import load_game_overrides
from booth_review.resolve.teams import TeamResolver, load_team_crosswalk

PEOPLE_SCHEMA: dict[str, pl.DataType] = {
    "person_id": pl.Utf8(),
    "canonical_name": pl.Utf8(),
    "variants": pl.List(pl.Utf8()),
    "usual_role": pl.Utf8(),
    "registered": pl.Boolean(),
}

TELECAST_PEOPLE_SCHEMA: dict[str, pl.DataType] = {
    "telecast_id": pl.Utf8(),
    "person_id": pl.Utf8(),
    "role": pl.Utf8(),
    "feed_type": pl.Utf8(),
    "crew_position": pl.Int32(),
    "s506_pointer": pl.Utf8(),
    "source": pl.Utf8(),
}

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
    networks = load_networks(reference_directory)
    primary_overrides = load_primary_overrides(reference_directory)

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

    people = pl.DataFrame(schema=PEOPLE_SCHEMA)
    telecast_people = pl.DataFrame(schema=TELECAST_PEOPLE_SCHEMA)

    unmatched_review_rows: list[dict[str, object]] = [
        dict(unmatched_row(row)) for row in telecast_build.unmatched_rows
    ]
    unresolved_review_rows: list[dict[str, object]] = [
        dict(row) for row in unresolved_rows(telecast_build.unresolved_rows)
    ]

    review_rows: dict[str, tuple[tuple[str, ...], list[dict[str, object]]]] = {
        "review_unmatched": (UNMATCHED_COLUMNS, unmatched_review_rows),
        "review_unresolved_teams": (UNRESOLVED_COLUMNS, unresolved_review_rows),
        "review_headline_disagreements": (HEADLINE_DISAGREEMENT_COLUMNS, disagreement_rows),
        "review_era_disagreements": (ERA_DISAGREEMENT_COLUMNS, era_disagreement_rows),
    }

    diagnostics = _build_diagnostics(telecast_build.counts)

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
    )


def write_tables(paths: DataPaths, tables: BuildTables) -> list[str]:
    """Write every processed Parquet table and interim review CSV, atomically
    (build.io), returning the sorted list of vault-relative paths written.
    """
    written: list[str] = []
    for name in _PARQUET_TABLES:
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

    paths = DataPaths.from_env()
    seasons = [args.season] if args.season is not None else None
    tables = assemble_tables(paths, reference_dir(), seasons)
    if not args.no_write:
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


if __name__ == "__main__":
    main()
