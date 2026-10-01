"""JOIN-08 stratified sample of 50 plotted telecasts (D-08 precedent) for a
user hand-check: `booth-review review sample` draws the sample from the
vault's own processed tables, writes it to `interim/join08_sample.csv` for
local review, and prints counts only (T-03-48). This module never commits.
"""

from __future__ import annotations

import argparse
import random
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import polars as pl

from booth_review.build.crew_overrides import CREW_OVERRIDE_SOURCE
from booth_review.build.io import write_review_csv
from booth_review.config import DataPaths
from booth_review.vault import VaultRepo

SAMPLE_COLUMNS = (
    "row",
    "season",
    "date_et",
    "kickoff_et",
    "matchup",
    "network_id",
    "crew",
    "headline_viewers",
    "publisher",
    "rr_record_urls",
    "s506_url",
    "match_confidence",
    "crew_network_mismatch",
    "check_status",
    "check_note",
)

DEFAULT_SIZE = 50
DEFAULT_SEED = 2026
_MIN_PER_SEASON = 2
_MIN_NON_EXACT = 10
_UNMAPPED_NETWORK = "(unmapped)"


@dataclass(frozen=True)
class SampleRow:
    """One drawn telecast, with everything `write_sample` needs to render a
    `join08_sample.csv` row (minus `row`/`check_status`/`check_note`, filled
    in by `write_sample` itself).
    """

    telecast_id: str
    season: int
    date_et: str
    kickoff_et: str | None
    matchup: str
    network_id: str | None
    crew: str
    headline_viewers: int | None
    publisher: str | None
    rr_record_urls: str
    s506_url: str | None
    match_confidence: str | None
    crew_network_mismatch: bool


def _season_allocation(counts: Mapping[int, int], size: int) -> dict[int, int]:
    """Allocate `size` samples across `counts` (season -> available telecasts),
    proportional to each season's share of the total, with at least
    `_MIN_PER_SEASON` per season that has any plotted telecasts (or as many
    as that season has, when it has fewer than the minimum). The remainder
    is handed out one at a time to whichever season is furthest below its
    ideal proportional share (largest-fraction-first), ties broken by the
    lower season number; a season already at its own total telecast count
    gets no more.
    """
    seasons = sorted(counts)
    total = sum(counts.values())
    size = min(size, total)
    if total == 0 or size <= 0:
        return dict.fromkeys(seasons, 0)

    # The per-season floor never pushes the sample past `size` (WR-17): with
    # more seasons than size // _MIN_PER_SEASON it shrinks (to 0 if need be)
    # and the proportional pass below places every row.
    active_seasons = sum(1 for season in seasons if counts[season] > 0)
    floor = min(_MIN_PER_SEASON, size // active_seasons) if active_seasons else 0
    alloc = {season: min(floor, counts[season]) for season in seasons}
    remaining = size - sum(alloc.values())

    while remaining > 0:
        best_season: int | None = None
        best_score: float | None = None
        for season in seasons:
            if alloc[season] >= counts[season]:
                continue
            ideal = size * counts[season] / total
            score = ideal - alloc[season]
            if best_score is None or score > best_score:
                best_season = season
                best_score = score
        if best_season is None:
            break
        alloc[best_season] += 1
        remaining -= 1

    return alloc


def _crew_string(telecast_id: str, telecast_people: pl.DataFrame, people: pl.DataFrame) -> str:
    crew = (
        telecast_people.filter(
            (pl.col("telecast_id") == telecast_id) & (pl.col("feed_type") == "main")
        )
        .sort("crew_position")
        .join(people.select("person_id", "canonical_name"), on="person_id", how="left")
    )
    parts = []
    for row in crew.iter_rows(named=True):
        name = row["canonical_name"] or row["person_id"]
        parts.append(f"{name} ({row['role']})")
    return "; ".join(parts)


def _matchup(game_row: Mapping[str, object]) -> str:
    away = str(game_row["away_team"])
    home = str(game_row["home_team"])
    if game_row["neutral_site"]:
        return f"{away} vs {home}"
    return f"{away} @ {home}"


def stratified_sample(
    telecasts: pl.DataFrame,
    telecast_people: pl.DataFrame,
    people: pl.DataFrame,
    games: pl.DataFrame,
    *,
    size: int = DEFAULT_SIZE,
    seed: int = DEFAULT_SEED,
) -> list[SampleRow]:
    """Draw a stratified sample of `size` plotted telecasts: allocated across
    seasons proportionally (at least 2 per season with any plotted telecast),
    round-robining across each season's primary networks (ordered by
    telecast count, most-covered first) to avoid bunching on one network,
    then topped up so at least `min(10, available)` sampled telecasts have a
    non-exact `match_confidence`. Deterministic for a given `seed`; a
    different seed draws a different sample from the same inputs.

    JOIN-08 measures the 506 join, so a telecast whose main crew came from
    data/reference/crew_overrides.csv (04.3: `crew_patched`, or main rows
    with source `crew_override`) is never drawn; it has no 506 crew to check.
    """
    override_ids = set(
        telecast_people.filter(
            (pl.col("feed_type") == "main") & (pl.col("source") == CREW_OVERRIDE_SOURCE)
        )["telecast_id"].to_list()
    )
    if "crew_patched" in telecasts.columns:  # a pre-04.3 telecasts.parquet has no column
        override_ids.update(
            telecasts.filter(pl.col("crew_patched").fill_null(False))["telecast_id"].to_list()
        )
    plotted = telecasts.filter(
        pl.col("plotted") & ~pl.col("telecast_id").is_in(sorted(override_ids))
    )
    games_by_id = {row["game_id"]: row for row in games.iter_rows(named=True)}

    by_season: dict[int, list[dict[str, Any]]] = {}
    for row in plotted.iter_rows(named=True):
        by_season.setdefault(int(row["season"]), []).append(row)

    counts = {season: len(rows) for season, rows in by_season.items()}
    alloc = _season_allocation(counts, size)

    rng = random.Random(seed)
    selected: list[dict[str, Any]] = []

    for season in sorted(by_season):
        season_rows = by_season[season]
        by_network: dict[str, list[dict[str, Any]]] = {}
        for row in season_rows:
            network_id = row["network_id"] or _UNMAPPED_NETWORK
            by_network.setdefault(network_id, []).append(row)

        network_order = sorted(by_network, key=lambda n: (-len(by_network[n]), n))
        pools: dict[str, list[dict[str, Any]]] = {}
        for network_id in network_order:
            pool = sorted(by_network[network_id], key=lambda r: str(r["telecast_id"]))
            rng.shuffle(pool)
            pools[network_id] = pool

        needed = alloc.get(season, 0)
        chosen: list[dict[str, Any]] = []
        while len(chosen) < needed:
            progressed = False
            for network_id in network_order:
                if len(chosen) >= needed:
                    break
                pool = pools[network_id]
                if pool:
                    chosen.append(pool.pop(0))
                    progressed = True
            if not progressed:
                break
        selected.extend(chosen)

    _ensure_non_exact(selected, by_season, rng)

    selected.sort(key=lambda r: (int(r["season"]), str(r["date_et"]), str(r["telecast_id"])))

    rows: list[SampleRow] = []
    for row in selected:
        game = games_by_id.get(row["game_id"])
        matchup = _matchup(game) if game is not None else ""
        headline_value = row["headline_value"]
        rr_urls = row["rr_record_urls"] or []
        rows.append(
            SampleRow(
                telecast_id=str(row["telecast_id"]),
                season=int(row["season"]),
                date_et=str(row["date_et"]),
                kickoff_et=row["kickoff_et"],
                matchup=matchup,
                network_id=row["network_id"],
                crew=_crew_string(str(row["telecast_id"]), telecast_people, people),
                headline_viewers=(round(headline_value) if headline_value is not None else None),
                publisher=row["headline_publisher"],
                rr_record_urls="|".join(rr_urls),
                s506_url=row["s506_url"],
                match_confidence=row["match_confidence"],
                crew_network_mismatch=bool(row["crew_network_mismatch"]),
            )
        )
    return rows


def _ensure_non_exact(
    selected: list[dict[str, Any]],
    by_season: Mapping[int, list[dict[str, Any]]],
    rng: random.Random,
) -> None:
    """Swap exact-confidence picks for non-exact ones (in place) until the
    sample holds at least `min(10, available)` non-exact `match_confidence`
    telecasts, or no more swaps are possible. A swap keeps the same season
    it displaces from when one is available there, else any season.
    """
    all_non_exact = [
        row for rows in by_season.values() for row in rows if row["match_confidence"] != "exact"
    ]
    target = min(_MIN_NON_EXACT, len(all_non_exact))

    selected_ids = {row["telecast_id"] for row in selected}
    have = sum(1 for row in selected if row["match_confidence"] != "exact")
    if have >= target:
        return

    candidates = [row for row in all_non_exact if row["telecast_id"] not in selected_ids]
    rng.shuffle(candidates)

    for candidate in candidates:
        if have >= target:
            break
        removable = [
            i
            for i, row in enumerate(selected)
            if row["match_confidence"] == "exact" and row["season"] == candidate["season"]
        ]
        if not removable:
            # A cross-season swap may only take from a season holding more
            # than its floor, so stratification never empties a season
            # (WR-17).
            per_season = Counter(row["season"] for row in selected)
            removable = [
                i
                for i, row in enumerate(selected)
                if row["match_confidence"] == "exact"
                and per_season[row["season"]] > _MIN_PER_SEASON
            ]
        if not removable:
            break
        idx = removable[0]
        selected_ids.discard(selected[idx]["telecast_id"])
        selected[idx] = candidate
        selected_ids.add(candidate["telecast_id"])
        have += 1


def write_sample(paths: DataPaths, rows: Sequence[SampleRow]) -> str:
    """Write `interim/join08_sample.csv` (SAMPLE_COLUMNS) through
    `write_review_csv`; `check_status` starts `"pending"` on every row.
    Returns the vault-relative path written.
    """
    final_rows: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        final_rows.append(
            {
                "row": index,
                "season": row.season,
                "date_et": row.date_et,
                "kickoff_et": row.kickoff_et,
                "matchup": row.matchup,
                "network_id": row.network_id,
                "crew": row.crew,
                "headline_viewers": row.headline_viewers,
                "publisher": row.publisher,
                "rr_record_urls": row.rr_record_urls,
                "s506_url": row.s506_url,
                "match_confidence": row.match_confidence,
                "crew_network_mismatch": row.crew_network_mismatch,
                "check_status": "pending",
                "check_note": "",
            }
        )
    rel_path = "interim/join08_sample.csv"
    write_review_csv(paths.vault / rel_path, SAMPLE_COLUMNS, final_rows)
    return rel_path


def sample_from_vault(
    paths: DataPaths, *, size: int = DEFAULT_SIZE, seed: int = DEFAULT_SEED
) -> list[SampleRow]:
    """Read the vault's own processed Parquet tables and draw the sample."""
    telecasts = pl.read_parquet(paths.processed / "telecasts.parquet")
    telecast_people = pl.read_parquet(paths.processed / "telecast_people.parquet")
    people = pl.read_parquet(paths.processed / "people.parquet")
    games = pl.read_parquet(paths.processed / "games.parquet")
    return stratified_sample(telecasts, telecast_people, people, games, size=size, seed=seed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, default=DEFAULT_SIZE)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args(argv)
    if args.size <= 0:
        parser.error("--size must be a positive integer")

    paths = DataPaths.from_env()
    rows = sample_from_vault(paths, size=args.size, seed=args.seed)
    write_sample(paths, rows)

    by_season: dict[int, int] = {}
    non_exact = 0
    for row in rows:
        by_season[row.season] = by_season.get(row.season, 0) + 1
        if row.match_confidence != "exact":
            non_exact += 1

    print(f"sample rows: {len(rows)}")
    for season in sorted(by_season):
        print(f"  season {season}: {by_season[season]}")
    print(f"non-exact match_confidence: {non_exact}")
    return 0


if __name__ == "__main__":
    with VaultRepo(DataPaths.from_env().vault).lock():
        raise SystemExit(main())
