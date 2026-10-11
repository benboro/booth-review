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
from booth_review.nfl.games import NflReference
from booth_review.nfl.inputs import load_nfl_inputs
from booth_review.nfl.listings import match_506_listings
from booth_review.nfl.people import (
    REVIEW_NFL_PEOPLE_COLUMNS,
    read_people_decisions,
    register_nfl_people,
)
from booth_review.nfl.pipeline import NflBuildOutcome, run_nfl_build
from booth_review.reference import read_reference_csv, reference_dir
from booth_review.resolve.names import csv_unsafe
from booth_review.seasons import season_of
from booth_review.vault import VaultRepo

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


def run_nfl_command(args: argparse.Namespace) -> int:
    if args.nfl_command == "build":
        return _nfl_build(args)
    if args.nfl_command == "people":
        return _nfl_people(args)
    raise AssertionError(f"unknown nfl command: {args.nfl_command!r}")
