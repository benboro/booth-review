"""The `booth-review nfl` command group: `build` and `people`.

Printed output is counts only. `nfl people` writes interim/review_nfl_people.csv
(never committed, like the CFB people review) and changes the shared people.csv
only under --apply, and then only through the rows the user marked add-variant.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from booth_review.build.io import write_review_csv
from booth_review.config import DataPaths
from booth_review.errors import BoothReviewError
from booth_review.nfl.freeze import (
    freeze_nfl_seasons,
    parse_nfl_waiver,
    schedule_drift,
)
from booth_review.nfl.games import NflReference
from booth_review.nfl.gaps import find_nfl_506_gaps
from booth_review.nfl.inputs import load_nfl_inputs
from booth_review.nfl.listings import match_506_listings
from booth_review.nfl.people import (
    REVIEW_NFL_PEOPLE_COLUMNS,
    read_people_decisions,
    register_nfl_people,
)
from booth_review.nfl.pipeline import NflBuildOutcome, run_nfl_build
from booth_review.nfl.seasons import nfl_collectable_season
from booth_review.reference import read_reference_csv, reference_dir
from booth_review.resolve.names import csv_unsafe
from booth_review.seasons import season_of
from booth_review.vault import VaultRepo, batch_message

EXIT_BLOCKED = 4


def add_nfl_parser(sub: Any) -> None:
    from booth_review.cli import parse_season_spec  # lazy: cli imports this module

    default_season = f"2014-{season_of(datetime.now(UTC).date())}"
    nfl = sub.add_parser("nfl", help="NFL special-games module: build tables, register people")
    nfl_sub = nfl.add_subparsers(dest="nfl_command", required=True)

    build = nfl_sub.add_parser("build", help="build the NFL game and special-games tables")
    build.add_argument("--season", type=parse_season_spec, default=default_season)
    build.add_argument("--include-playoffs", action="store_true")
    build.add_argument("--check-acceptance", action="store_true")
    build.add_argument("--no-commit", action="store_true")

    gaps = nfl_sub.add_parser("gaps", help="list played NFL 506 week pages to hand-save")
    gaps.add_argument("--season", type=int, default=None)

    freeze = nfl_sub.add_parser("freeze", help="freeze completed NFL seasons")
    freeze.add_argument("--season", type=parse_season_spec, default=None)
    freeze.add_argument("--waive", type=parse_nfl_waiver, action="append", default=[])
    freeze.add_argument("--dry-run", action="store_true")
    freeze.add_argument("--no-commit", action="store_true")
    freeze.add_argument("--check-drift", action="store_true")

    people = nfl_sub.add_parser("people", help="review and register NFL crew names")
    people.add_argument("--season", type=parse_season_spec, default=default_season)
    people.add_argument("--apply", action="store_true")


def _seasons(value: Any) -> list[int]:
    if isinstance(value, str):
        from booth_review.cli import parse_season_spec

        return parse_season_spec(value)
    return list(value)


def _print_build(outcome: NflBuildOutcome, *, check: bool) -> None:
    c = outcome.counts
    print(
        f"nfl games {c.get('games', 0)}, standalone {c.get('standalone', 0)}, "
        f"agotw {c.get('agotw', 0)}, cbs national {c.get('cbs_national', 0)}, "
        f"blocked {'yes' if outcome.blocked else 'no'}"
    )
    if outcome.blocked:
        print(f"override errors {c.get('override_errors', 0)}")
    if check and outcome.acceptance is not None:
        text = f"acceptance: {outcome.acceptance.unmatched} unmatched"
        if outcome.acceptance.multi_network:
            text += f" ({outcome.acceptance.multi_network} multi-network)"
        print(text)


def _nfl_build(args: argparse.Namespace) -> int:
    paths = DataPaths.from_env()
    try:
        outcome = run_nfl_build(
            paths,
            reference_dir(),
            seasons=_seasons(args.season),
            include_playoffs=args.include_playoffs,
            commit=not args.no_commit,
            check_acceptance=args.check_acceptance,
        )
    except BoothReviewError:
        raise
    except Exception as exc:
        if os.environ.get("BOOTH_REVIEW_DEBUG"):
            raise
        print(
            f"error: unexpected {type(exc).__name__} during nfl build; details withheld "
            "(set BOOTH_REVIEW_DEBUG=1 to see the traceback)",
            file=sys.stderr,
        )
        return 3
    _print_build(outcome, check=args.check_acceptance)
    unmatched = outcome.acceptance.unmatched if outcome.acceptance else 0
    if outcome.blocked or (args.check_acceptance and unmatched > 0):
        return EXIT_BLOCKED
    return 0


def _nfl_people(args: argparse.Namespace) -> int:
    paths = DataPaths.from_env()
    reference = reference_dir()
    review_path = paths.interim / "review_nfl_people.csv"
    with VaultRepo(paths.vault).lock():
        inputs = load_nfl_inputs(paths, _seasons(args.season))
        ref = NflReference.load(reference)
        listings, _reviews = match_506_listings(inputs, ref.teams, ref.networks)
        name_counts: Counter[str] = Counter()
        for match in listings.values():
            name_counts.update(match.crew_names)

        if args.apply:
            approvals, invalid_rows = read_people_decisions(review_path)
            result = register_nfl_people(reference, name_counts, approved_variants=approvals)
            counts = dict(result.counts)
            counts["invalid_decisions"] += invalid_rows
        else:
            result = register_nfl_people(reference, name_counts, dry_run=True)
            counts = dict(result.counts)
            previous = {
                (csv_unsafe(r["raw_name"]), r["person_id"]): r["decision"]
                for r in read_reference_csv(review_path, REVIEW_NFL_PEOPLE_COLUMNS, required=False)
            }
            rows = [
                {
                    "raw_name": m.raw_name,
                    "person_id": m.person_id,
                    "count": m.count,
                    "spelling_known": "yes" if m.spelling_known else "no",
                    "decision": previous.get((m.raw_name, m.person_id), ""),
                }
                for m in sorted(result.existing_matches, key=lambda m: (m.raw_name, m.person_id))
            ]
            write_review_csv(review_path, REVIEW_NFL_PEOPLE_COLUMNS, rows)

    print(
        f"nfl people: {sum(1 for _ in name_counts)} distinct names, "
        + ", ".join(f"{k} {v}" for k, v in counts.items())
    )
    return 0


def _nfl_gaps(args: argparse.Namespace) -> int:
    now = datetime.now(UTC)
    season = args.season if args.season is not None else nfl_collectable_season(now.date())
    if season is None:
        print("error: no NFL season is collectable now; pass --season", file=sys.stderr)
        return 2
    gaps = find_nfl_506_gaps(DataPaths.from_env(), season, now)
    if gaps is None:
        print(
            "error: nfl schedules missing: run booth-review collect nflverse first", file=sys.stderr
        )
        return 2
    print(
        f"nfl 506 {season}: judged {gaps.judged}, missing {len(gaps.missing)}, "
        f"stale {len(gaps.stale)}, saved_at fallbacks {gaps.saved_at_fallbacks}"
    )
    if gaps.missing:
        print(f"missing weeks: {', '.join(gaps.missing)}")
    if gaps.stale:
        print(f"stale weeks: {', '.join(gaps.stale)}")
    return 0


def _nfl_freeze(args: argparse.Namespace) -> int:
    paths = DataPaths.from_env()
    if args.check_drift:
        drifted = schedule_drift(paths)
        print(f"nfl schedule drift: {len(drifted)} season(s)")
        if drifted:
            print(f"drifted seasons: {', '.join(str(s) for s in drifted)}")
            return EXIT_BLOCKED
        return 0
    if args.season is None:
        print("error: --season is required", file=sys.stderr)
        return 2
    seasons = _seasons(args.season)
    today = datetime.now(UTC).date()
    vault = VaultRepo(paths.vault)
    vault.check()
    with vault.lock():
        result = freeze_nfl_seasons(paths, seasons, today, waivers=args.waive, dry_run=args.dry_run)
        if result.refused:
            print("freeze refused:", file=sys.stderr)
            for season, reason in sorted(result.refused.items()):
                print(f"  {season}: {reason}", file=sys.stderr)
            return EXIT_BLOCKED
        if args.dry_run:
            for season in seasons:
                status = "would freeze" if season in result.frozen else "already frozen"
                print(f"{season}: {status}")
        elif result.written and not args.no_commit:
            label = f"{min(seasons)}-{max(seasons)}"
            vault.commit_batch(
                batch_message(
                    "freeze",
                    "nfl",
                    label,
                    {"seasons": len(result.frozen), "waived": len(result.waived)},
                ),
                paths=list(result.written),
            )
    verb = "would freeze" if args.dry_run else "froze"
    print(f"nfl {verb} {len(result.frozen)} season(s), {len(result.waived)} waived")
    return 0


def run_nfl_command(args: argparse.Namespace) -> int:
    if args.nfl_command == "build":
        return _nfl_build(args)
    if args.nfl_command == "people":
        return _nfl_people(args)
    if args.nfl_command == "gaps":
        return _nfl_gaps(args)
    if args.nfl_command == "freeze":
        return _nfl_freeze(args)
    raise AssertionError(f"unknown nfl command: {args.nfl_command!r}")
