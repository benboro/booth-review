"""Read-only match diagnostic for JOIN-01/02/08: runs the crosswalk-aware
matcher (resolve/teams.py, resolve/overrides.py, resolve/games.py) across
every cached season and writes two review CSVs to the vault's interim/
folder. Reads only cached raw/ files and data/reference/*.csv; sends no
request, and never writes anywhere but interim/ (T-03-10..16). Printed
output is counts and percentages only -- never a team, announcer, or
matchup string (T-03-15).
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from booth_review.config import DataPaths
from booth_review.reference import reference_dir
from booth_review.resolve.games import (
    GameIndex,
    is_fbs_game,
    match_listing_to_game,
    match_record_to_game,
)
from booth_review.resolve.inputs import (
    load_506_listings,
    load_cfbd_games,
    load_rr_records,
    vault_seasons,
)
from booth_review.resolve.names import csv_safe, significant_tokens
from booth_review.resolve.overrides import (
    load_game_overrides,
    pointer_for_listing,
    pointer_for_record,
)
from booth_review.resolve.teams import ResolvedTeam, TeamResolver, load_team_crosswalk
from booth_review.sources.cfbd.parser import CfbdGame
from booth_review.sources.ratingsref.parser import RRRecord
from booth_review.sources.sports506.parser import Listing506
from booth_review.transport.cache import atomic_write_bytes

UNRESOLVED_TEAM_COLUMNS = (
    "source",
    "season_first",
    "season_last",
    "raw_name",
    "occurrences",
    "suggested_canonical",
    "suggested_cfbd_team_id",
)
UNMATCHED_COLUMNS = (
    "source",
    "season",
    "pointer",
    "date_et",
    "away_raw",
    "home_raw",
    "network_raw",
    "confidence",
    "reason",
)

# Public alias: build.telecasts (Plan 08) reuses this column tuple under the
# name the plan documents, so both modules' review_unresolved_teams.csv
# writers agree on the header without importing a "team"-specific name.
UNRESOLVED_COLUMNS = UNRESOLVED_TEAM_COLUMNS

_NEARBY_DAYS = 1


@dataclass(frozen=True)
class UnresolvedTeamRow:
    source: str
    season_first: int
    season_last: int
    raw_name: str
    occurrences: int
    suggested_canonical: str
    suggested_cfbd_team_id: str


@dataclass(frozen=True)
class UnmatchedRow:
    source: str
    season: int
    pointer: str
    date_et: str
    away_raw: str
    home_raw: str
    network_raw: str
    confidence: str
    reason: str


@dataclass(frozen=True)
class MatchDiagnostic:
    rr_records: int
    rr_parse_errors: int
    rr_matched_by_confidence: dict[str, int]
    rr_excluded: int
    rr_out_of_scope: int
    rr_unmatched: int
    rr_matched_fbs: int
    rr_matched_fbs_with_crew: int
    listings_total: int
    listings_matched: int
    listings_unmatched: int
    unresolved_names_by_source: dict[str, int]
    unresolved_team_rows: tuple[UnresolvedTeamRow, ...] = field(default_factory=tuple)
    unmatched_rows: tuple[UnmatchedRow, ...] = field(default_factory=tuple)


def suggest_canonical(
    raw_name: str, season: int, games_by_season: Mapping[int, Sequence[CfbdGame]]
) -> tuple[str | None, int | None]:
    """The season's CFBD team (home or away side of any of that season's
    games) with the largest significant_tokens overlap against `raw_name`;
    (None, None) when no team shares a single token.
    """
    raw_tokens = significant_tokens(raw_name)
    if not raw_tokens:
        return None, None

    best_name: str | None = None
    best_id: int | None = None
    best_overlap = 0
    for game in games_by_season.get(season, ()):
        for team_id, name in ((game.home_id, game.home_team), (game.away_id, game.away_team)):
            if team_id is None:
                continue
            overlap = len(raw_tokens & significant_tokens(name))
            if overlap == 0:
                continue
            if overlap > best_overlap or (
                overlap == best_overlap and (best_name is None or name < best_name)
            ):
                best_overlap = overlap
                best_name = name
                best_id = team_id
    if best_name is None:
        return None, None
    return best_name, best_id


def run_match_diagnostic(
    paths: DataPaths, reference_dir: Path, seasons: Sequence[int] | None = None
) -> MatchDiagnostic:
    all_seasons = list(seasons) if seasons is not None else vault_seasons(paths)

    games_by_season: dict[int, list[CfbdGame]] = {}
    listings_by_season: dict[int, list[Listing506]] = {}
    records_by_season: dict[int, list[RRRecord]] = {}
    rr_parse_errors = 0

    for season in all_seasons:
        games_by_season[season] = load_cfbd_games(paths, season)
        listings_by_season[season] = load_506_listings(paths, season)
        records, errors = load_rr_records(paths, season)
        records_by_season[season] = records
        rr_parse_errors += errors

    crosswalk = load_team_crosswalk(reference_dir)
    resolver = TeamResolver(games_by_season, crosswalk)
    overrides = load_game_overrides(reference_dir)
    all_games = [g for games in games_by_season.values() for g in games]
    index = GameIndex(all_games)

    unresolved_counts: dict[tuple[str, str], dict[str, int]] = {}

    def _track_unresolved(source: str, raw: str, season: int, resolved: ResolvedTeam) -> None:
        track_unresolved(unresolved_counts, source, raw, season, resolved)

    listings_total = 0
    listings_matched = 0
    unmatched_rows: list[UnmatchedRow] = []
    fbs_games_with_crew: set[int] = set()

    for season in all_seasons:
        for listing in listings_by_season[season]:
            listings_total += 1
            match = match_listing_to_game(listing, index, resolver, overrides)
            _track_unresolved("sports506", listing.away_raw, season, match.away_resolved)
            _track_unresolved("sports506", listing.home_raw, season, match.home_resolved)

            if match.excluded:
                continue

            if match.game is not None and match.confidence != "none":
                listings_matched += 1
                if listing.feed_kind == "main" and listing.crew_names:
                    fbs_games_with_crew.add(match.game.id)
            else:
                unmatched_rows.append(
                    UnmatchedRow(
                        source="sports506",
                        season=season,
                        pointer=pointer_for_listing(listing),
                        date_et=listing.date_et.isoformat(),
                        away_raw=listing.away_raw,
                        home_raw=listing.home_raw,
                        network_raw=listing.network_raw or "",
                        confidence=match.confidence,
                        reason="ambiguous" if match.confidence == "ambiguous" else "none",
                    )
                )

    listings_unmatched = sum(1 for row in unmatched_rows if row.source == "sports506")

    rr_records_count = 0
    rr_matched_by_confidence: Counter[str] = Counter()
    rr_excluded = 0
    rr_out_of_scope = 0
    rr_unmatched = 0
    rr_matched_fbs = 0
    rr_matched_fbs_with_crew = 0

    for season in all_seasons:
        for record in records_by_season[season]:
            rr_records_count += 1
            for team_slug in record.telecast.teams:
                resolved = resolver.resolve("ratingsref", team_slug, season)
                _track_unresolved("ratingsref", team_slug, season, resolved)

            match = match_record_to_game(record, index, resolver, overrides)

            if match.excluded:
                rr_excluded += 1
                continue

            if match.game is None:
                rr_unmatched += 1
                teams = record.telecast.teams
                unmatched_rows.append(
                    UnmatchedRow(
                        source="ratingsref",
                        season=season,
                        pointer=pointer_for_record(record),
                        date_et=record.telecast.event_date.isoformat(),
                        away_raw=teams[0] if teams else "",
                        home_raw=teams[1] if len(teams) > 1 else "",
                        network_raw=", ".join(record.telecast.networks),
                        confidence=match.confidence,
                        reason="ambiguous" if match.confidence == "ambiguous" else "none",
                    )
                )
                continue

            rr_matched_by_confidence[match.confidence] += 1

            if not is_fbs_game(match.game):
                rr_out_of_scope += 1
                continue

            rr_matched_fbs += 1
            if match.game.id in fbs_games_with_crew:
                rr_matched_fbs_with_crew += 1

    unresolved_names_by_source: Counter[str] = Counter()
    unresolved_team_rows: list[UnresolvedTeamRow] = []
    for (source, raw_name), info in unresolved_counts.items():
        unresolved_names_by_source[source] += 1
        suggested_name, suggested_id = suggest_canonical(
            raw_name, info["season_last"], games_by_season
        )
        unresolved_team_rows.append(
            UnresolvedTeamRow(
                source=source,
                season_first=info["season_first"],
                season_last=info["season_last"],
                raw_name=raw_name,
                occurrences=info["count"],
                suggested_canonical=suggested_name or "",
                suggested_cfbd_team_id=str(suggested_id) if suggested_id is not None else "",
            )
        )
    unresolved_team_rows.sort(key=lambda row: (row.source, row.raw_name))
    unmatched_rows.sort(key=lambda row: (row.source, row.season, row.pointer))

    return MatchDiagnostic(
        rr_records=rr_records_count,
        rr_parse_errors=rr_parse_errors,
        rr_matched_by_confidence=dict(rr_matched_by_confidence),
        rr_excluded=rr_excluded,
        rr_out_of_scope=rr_out_of_scope,
        rr_unmatched=rr_unmatched,
        rr_matched_fbs=rr_matched_fbs,
        rr_matched_fbs_with_crew=rr_matched_fbs_with_crew,
        listings_total=listings_total,
        listings_matched=listings_matched,
        listings_unmatched=listings_unmatched,
        unresolved_names_by_source=dict(unresolved_names_by_source),
        unresolved_team_rows=tuple(unresolved_team_rows),
        unmatched_rows=tuple(unmatched_rows),
    )


def _write_csv(path: Path, columns: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(columns), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    atomic_write_bytes(path, buf.getvalue().encode("utf-8"))


def track_unresolved(
    unresolved_counts: dict[tuple[str, str], dict[str, int]],
    source: str,
    raw: str,
    season: int,
    resolved: ResolvedTeam,
) -> None:
    """Tally one (source, raw) name resolution outcome into `unresolved_counts`
    (mutated in place) when `resolved` is "unresolved"; a no-op otherwise.
    Shared by run_match_diagnostic's own scan and build.telecasts's (Plan 08)
    so both accumulate unresolved-name evidence the same way.
    """
    if resolved.method != "unresolved":
        return
    key = (source, raw)
    entry = unresolved_counts.setdefault(
        key, {"season_first": season, "season_last": season, "count": 0}
    )
    entry["season_first"] = min(entry["season_first"], season)
    entry["season_last"] = max(entry["season_last"], season)
    entry["count"] += 1


def unmatched_row(row: UnmatchedRow) -> dict[str, str]:
    """One review_unmatched.csv row (UNMATCHED_COLUMNS order), csv_safe applied
    here -- the single place either writer needs to protect this row's raw
    text. Shared by write_team_review and build.telecasts's own writer
    (Plan 08) so both produce byte-identical review files for the same match
    outcome.
    """
    return {
        "source": row.source,
        "season": str(row.season),
        "pointer": row.pointer,
        "date_et": row.date_et,
        "away_raw": csv_safe(row.away_raw),
        "home_raw": csv_safe(row.home_raw),
        "network_raw": csv_safe(row.network_raw),
        "confidence": row.confidence,
        "reason": row.reason,
    }


def unresolved_rows(rows: Sequence[UnresolvedTeamRow]) -> list[dict[str, str]]:
    """review_unresolved_teams.csv rows (UNRESOLVED_COLUMNS order) for every
    entry in `rows`, csv_safe applied. Shared the same way as unmatched_row.
    """
    return [
        {
            "source": row.source,
            "season_first": str(row.season_first),
            "season_last": str(row.season_last),
            "raw_name": csv_safe(row.raw_name),
            "occurrences": str(row.occurrences),
            "suggested_canonical": csv_safe(row.suggested_canonical),
            "suggested_cfbd_team_id": row.suggested_cfbd_team_id,
        }
        for row in rows
    ]


def write_team_review(paths: DataPaths, diagnostic: MatchDiagnostic) -> None:
    """Write interim/review_unresolved_teams.csv and interim/review_unmatched.csv.

    Rebuilt every run (not committed by this module): Plan 11's build commits
    the vault's interim/ artifacts.
    """
    _write_csv(
        paths.interim / "review_unresolved_teams.csv",
        UNRESOLVED_COLUMNS,
        unresolved_rows(diagnostic.unresolved_team_rows),
    )
    _write_csv(
        paths.interim / "review_unmatched.csv",
        UNMATCHED_COLUMNS,
        [unmatched_row(row) for row in diagnostic.unmatched_rows],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-write", action="store_true", help="Print counts only; skip writing review CSVs."
    )
    args = parser.parse_args(argv)

    paths = DataPaths.from_env()
    diagnostic = run_match_diagnostic(paths, reference_dir())
    if not args.no_write:
        write_team_review(paths, diagnostic)

    print(f"506 listings: {diagnostic.listings_total} total")
    print(f"  matched: {diagnostic.listings_matched}")
    print(f"  unmatched: {diagnostic.listings_unmatched}")
    print()
    print(f"RR records: {diagnostic.rr_records} ({diagnostic.rr_parse_errors} parse errors)")
    print(f"  excluded (override): {diagnostic.rr_excluded}")
    print(f"  out of scope (non-FBS): {diagnostic.rr_out_of_scope}")
    print(f"  unmatched: {diagnostic.rr_unmatched}")
    print(f"  matched by confidence: {dict(sorted(diagnostic.rr_matched_by_confidence.items()))}")
    print(f"  matched to an FBS game: {diagnostic.rr_matched_fbs}")
    print(f"  matched to an FBS game with a 506 crew: {diagnostic.rr_matched_fbs_with_crew}")
    print()

    denominator = diagnostic.rr_records - diagnostic.rr_excluded - diagnostic.rr_out_of_scope
    if denominator > 0:
        game_rate = diagnostic.rr_matched_fbs / denominator * 100
        crew_rate = diagnostic.rr_matched_fbs_with_crew / denominator * 100
        print(f"RR-to-game rate: {game_rate:.1f}% ({diagnostic.rr_matched_fbs}/{denominator})")
        print(
            f"RR-to-game-plus-crew rate: {crew_rate:.1f}% "
            f"({diagnostic.rr_matched_fbs_with_crew}/{denominator})"
        )
    print()

    print("unresolved team names by source (distinct raw names):")
    for source, count in sorted(diagnostic.unresolved_names_by_source.items()):
        print(f"  {source}: {count}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
