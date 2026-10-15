"""The `booth-review mlb` command group: build, site-data, gaps, rr-backfill, freeze and people.

Printed output is counts only. The names `booth-review mlb build` and
`booth-review mlb rr-backfill` are fixed because AGENTS.md and the docs name them.
`mlb build` writes the processed MLB tables and review files under one vault lock and
one path-scoped commit; nothing is published. `mlb rr-backfill` computes the D-14
Ratings Reference windows, stores them in ledger/mlb_rr_windows.json (the file every
later `collect ratingsref --league mlb` and `refresh ratingsref --league mlb` reads)
and collects only the records inside them. `mlb people` writes
interim/review_mlb_people.csv and changes people.csv only under --apply. The job
runner never calls any of this (D-16).
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, date, datetime
from typing import Any

from booth_review.build.mlb_site_data import (
    build_mlb_site_data,
    load_mlb_site_inputs,
    mlb_site_counts,
    mlb_site_payload_bytes,
    write_mlb_site_data,
)
from booth_review.build.site_assembly import mlb_site_enabled
from booth_review.config import DataPaths
from booth_review.errors import BoothReviewError
from booth_review.mlb import pipeline
from booth_review.mlb.collect_cli import (
    parse_mlb_season_spec,
    write_mlb_rr_windows,
)
from booth_review.mlb.freeze import (
    accept_retrosheet_drift,
    freeze_mlb_seasons,
    parse_mlb_waiver,
    retrosheet_drift,
)
from booth_review.mlb.gaps import (
    gap_counts_by_network,
    relay_gaps,
    rr_windows,
    write_relay_gaps,
)
from booth_review.mlb.layout import MLB_FIRST_SEASON
from booth_review.mlb.people import register_mlb_people
from booth_review.mlb.pipeline import MlbBuildOutcome, assemble_mlb_tables, run_mlb_build
from booth_review.mlb.seasons import mlb_current_season
from booth_review.reference import reference_dir
from booth_review.vault import VaultRepo, batch_message

EXIT_BLOCKED = 4
RELAY_SEASON = 2026
RR_BACKFILL_MAX_REQUESTS = 150


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected a positive integer: {text!r}") from exc
    if value < 1:
        raise argparse.ArgumentTypeError(f"expected a positive integer: {text!r}")
    return value


def _current_season() -> int:
    return mlb_current_season(datetime.now(UTC).date())


def add_mlb_parser(sub: Any) -> None:
    default_range = f"{MLB_FIRST_SEASON}-{_current_season()}"
    mlb = sub.add_parser("mlb", help="MLB national-telecasts module: build tables, gaps, freeze")
    mlb_sub = mlb.add_subparsers(dest="mlb_command", required=True)

    build = mlb_sub.add_parser("build", help="build the MLB tables and review files")
    build.add_argument("--season", type=parse_mlb_season_spec, default=default_range)
    build.add_argument("--no-commit", action="store_true")
    build.add_argument(
        "--site-data",
        action="store_true",
        help="also write processed/mlb-data.json (on by MLB_SITE_ENABLED=true)",
    )

    site_data = mlb_sub.add_parser(
        "site-data", help="write processed/mlb-data.json from the built MLB tables"
    )
    site_data.add_argument("--no-commit", action="store_true")

    gaps = mlb_sub.add_parser("gaps", help="list games that still need work by hand")
    gaps.add_argument(
        "--relay",
        action="store_true",
        help="list 2026 own-production telecasts with no named crew, for the relay session",
    )
    gaps.add_argument("--season", type=parse_mlb_season_spec, default=str(RELAY_SEASON))

    backfill = mlb_sub.add_parser(
        "rr-backfill", help="store the D-14 windows and collect Ratings Reference records in them"
    )
    backfill.add_argument("--dry-run", action="store_true")
    backfill.add_argument("--no-commit", action="store_true")
    backfill.add_argument(
        "--max-requests",
        type=_positive_int,
        default=RR_BACKFILL_MAX_REQUESTS,
        help=f"cap on new record requests across the run (default {RR_BACKFILL_MAX_REQUESTS})",
    )

    freeze = mlb_sub.add_parser("freeze", help="freeze completed MLB seasons")
    freeze.add_argument("--season", type=parse_mlb_season_spec, default=None)
    freeze.add_argument("--waive", type=parse_mlb_waiver, action="append", default=[])
    freeze.add_argument("--dry-run", action="store_true")
    freeze.add_argument("--no-commit", action="store_true")
    drift = freeze.add_mutually_exclusive_group()
    drift.add_argument("--check-drift", action="store_true")
    drift.add_argument(
        "--accept-drift",
        action="store_true",
        help="re-record the Retrosheet digest of the --season frozen seasons after a drift",
    )

    people = mlb_sub.add_parser("people", help="review and register MLB crew names")
    people.add_argument("--season", type=parse_mlb_season_spec, default=default_range)
    people.add_argument("--apply", action="store_true")


def _seasons(value: Any) -> list[int]:
    if isinstance(value, str):
        return parse_mlb_season_spec(value)
    return list(value)


# -- build ------------------------------------------------------------------------------


def _print_build(outcome: MlbBuildOutcome) -> None:
    c = outcome.counts
    print(
        f"mlb games {c['games']}, telecasts {c['telecasts']}, lineups {c['lineup_games']}, "
        f"excitement {c['excitement_games']}, quality pending {c['quality_pending']}"
    )
    for season, (named, total) in sorted(outcome.coverage.items()):
        share = f"{100 * named / total:.0f}%" if total else "n/a"
        print(f"crew coverage {season}: {named} of {total} ({share})")
    print(
        f"crew disagreements {c['disagreements']}, "
        f"rr doubleheader {c['rr_ambiguous_doubleheader']}, "
        f"rr conflict {c['rr_conflict']}, rr per-network {c['rr_per_network']}, "
        f"unresolved names {c['unresolved_names']}, map ambiguities {c['map_ambiguous']}"
    )
    if c.get("site_data_failed"):
        print("mlb site data: failed (tables committed)")


def _mlb_build(args: argparse.Namespace) -> int:
    paths = DataPaths.from_env()
    explicit = bool(args.site_data)
    wanted = explicit or mlb_site_enabled(os.environ)
    available = pipeline.SITE_DATA_BUILDER is not None
    if wanted and not available and not explicit:
        print("mlb site data: builder not available yet; skipped")
        wanted = False
    outcome = run_mlb_build(
        paths,
        reference_dir(),
        _seasons(args.season),
        commit=not args.no_commit,
        site_data=wanted,
    )
    _print_build(outcome)
    return 0


# -- site-data --------------------------------------------------------------------------


def _mlb_site_data(args: argparse.Namespace) -> int:
    paths = DataPaths.from_env()
    vault = VaultRepo(paths.vault)
    vault.check()
    with vault.lock():
        site = build_mlb_site_data(load_mlb_site_inputs(paths, reference_dir()))
        rel = write_mlb_site_data(paths, site)
        counts = mlb_site_counts(site)
        if not args.no_commit:
            vault.commit_batch(
                batch_message("build", "mlb_site", str(site.freshness.season), counts),
                paths=[rel],
            )
    size = len(mlb_site_payload_bytes(site))
    print(
        f"mlb site data: {counts['games']} games, {counts['lineups']} lineups, "
        f"{len(site.lookups.people)} people, {size} bytes"
    )
    return 0


# -- gaps -------------------------------------------------------------------------------


def _mlb_gaps(args: argparse.Namespace) -> int:
    if not args.relay:
        print("error: choose a gap list (--relay)", file=sys.stderr)
        return 2
    paths = DataPaths.from_env()
    vault = VaultRepo(paths.vault)
    vault.check()
    with vault.lock():
        asm, _ref = assemble_mlb_tables(paths, reference_dir(), _seasons(args.season))
        rows = relay_gaps(asm.telecasts, asm.crews)
        write_relay_gaps(paths, rows)
    print(f"mlb relay gaps: {len(rows)} telecast(s) with no named crew")
    for network, count in gap_counts_by_network(rows).items():
        print(f"  {network}: {count}")
    return 0


# -- rr-backfill ------------------------------------------------------------------------


def _mlb_rr_backfill(args: argparse.Namespace) -> int:
    from booth_review import cli  # lazy: cli imports this module
    from booth_review.runtime import build_runtime
    from booth_review.sources.ratingsref.collector import RatingsRefCollector

    paths = DataPaths.from_env()
    asm, _ref = assemble_mlb_tables(
        paths, reference_dir(), range(MLB_FIRST_SEASON, _current_season() + 1)
    )
    windows = rr_windows(asm.games)
    if not windows:
        print(
            "error: no windows: build the game table first (collect 506 and Retrosheet)",
            file=sys.stderr,
        )
        return 2
    start, end = windows[0][0], windows[-1][1]
    runtime = build_runtime(with_budget=False)
    try:
        collector = RatingsRefCollector(
            runtime.cache, runtime.paths, lock=runtime.vault.lock, league="mlb"
        )
        if args.dry_run:
            summary = collector.run(start, end, dry_run=True, windows=windows)
            print(
                f"mlb rr windows {len(windows)} ({start} to {end}), "
                f"planned records {summary.planned}, cached {summary.cached}, "
                f"new {len(summary.new_urls)}"
            )
            return 0
        return _backfill_run(runtime, collector, windows, args, cli)
    finally:
        runtime.client.close()


def _backfill_run(
    runtime: Any,
    collector: Any,
    windows: list[tuple[date, date]],
    args: argparse.Namespace,
    cli: Any,
) -> int:
    """Real run: store the windows, fetch window by window under the cap, one commit."""
    counts = {"fetched": 0, "cached": 0, "not_modified": 0, "failed": 0}
    remaining = args.max_requests
    stopped = False
    label = f"{windows[0][0].year}-{windows[-1][1].year}"
    failed_urls = 0
    with runtime.vault.lock():
        write_mlb_rr_windows(runtime.paths, windows)
        try:
            collector.sitemap(dry_run=False)
            for window in windows:
                plan = collector.run(window[0], window[1], dry_run=True, windows=[window])
                if len(plan.new_urls) > remaining:
                    stopped = True
                    break
                summary = collector.run(window[0], window[1], dry_run=False, windows=[window])
                remaining -= summary.fetched
                for key in counts:
                    counts[key] += int(getattr(summary, key))
                failed_urls += len(summary.failed_urls)
        finally:
            if not args.no_commit:
                runtime.vault.commit_batch(
                    batch_message("collect", "mlb_ratingsref", label, counts),
                    paths=list(cli._COLLECT_PATHS["mlb_ratingsref"]),
                )
    print(
        f"mlb rr windows {len(windows)}, fetched {counts['fetched']}, cached {counts['cached']}, "
        f"failed {counts['failed']}"
    )
    if stopped:
        print(f"stopped: --max-requests {args.max_requests} reached; run again to continue")
    return 4 if failed_urls else 0


# -- people -----------------------------------------------------------------------------


def _mlb_people(args: argparse.Namespace) -> int:
    from booth_review.mlb.crews import people_review_names

    paths = DataPaths.from_env()
    vault = VaultRepo(paths.vault)
    vault.check()
    with vault.lock():
        asm, ref = assemble_mlb_tables(paths, reference_dir(), _seasons(args.season))
        result = register_mlb_people(
            paths,
            reference_dir(),
            people_review_names(asm.people_reviews),
            ref.booth_ranks.unresolved,
            apply=args.apply,
        )
    print("mlb people: " + ", ".join(f"{k} {v}" for k, v in result.counts.items()))
    return 0


# -- freeze -----------------------------------------------------------------------------


def _mlb_freeze(args: argparse.Namespace) -> int:
    paths = DataPaths.from_env()
    if args.check_drift:
        drifted = retrosheet_drift(paths)
        print(f"mlb retrosheet drift: {len(drifted)} season(s)")
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
    if args.accept_drift:
        return _mlb_accept_drift(args, paths, vault, seasons, today)
    with vault.lock():
        result = freeze_mlb_seasons(paths, seasons, today, waivers=args.waive, dry_run=args.dry_run)
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
                    "mlb",
                    label,
                    {"seasons": len(result.frozen), "waived": len(result.waived)},
                ),
                paths=list(result.written),
            )
    verb = "would freeze" if args.dry_run else "froze"
    print(f"mlb {verb} {len(result.frozen)} season(s), {len(result.waived)} waived")
    return 0


def _mlb_accept_drift(
    args: argparse.Namespace,
    paths: DataPaths,
    vault: VaultRepo,
    seasons: list[int],
    today: date,
) -> int:
    with vault.lock():
        result = accept_retrosheet_drift(paths, seasons, today, dry_run=args.dry_run)
        if result.not_frozen:
            print(
                "error: no frozen Retrosheet digest for season(s) "
                + ", ".join(str(s) for s in result.not_frozen),
                file=sys.stderr,
            )
            return EXIT_BLOCKED
        if result.written and not args.no_commit:
            vault.commit_batch(
                batch_message(
                    "freeze",
                    "mlb_drift",
                    f"{min(seasons)}-{max(seasons)}",
                    {"accepted": len(result.accepted)},
                ),
                paths=list(result.written),
            )
    verb = "would accept" if args.dry_run else "accepted"
    print(
        f"mlb retrosheet drift {verb} for {len(result.accepted)} season(s), "
        f"{len(result.unchanged)} unchanged"
    )
    return 0


# -- dispatch ---------------------------------------------------------------------------

_HANDLERS = {
    "build": _mlb_build,
    "site-data": _mlb_site_data,
    "gaps": _mlb_gaps,
    "rr-backfill": _mlb_rr_backfill,
    "freeze": _mlb_freeze,
    "people": _mlb_people,
}


def run_mlb_command(args: argparse.Namespace) -> int:
    handler = _HANDLERS.get(args.mlb_command)
    if handler is None:
        raise AssertionError(f"unknown mlb command: {args.mlb_command!r}")
    try:
        return handler(args)
    except BoothReviewError:
        raise
    except Exception as exc:
        if os.environ.get("BOOTH_REVIEW_DEBUG"):
            raise
        print(
            f"error: unexpected {type(exc).__name__}; details withheld "
            "(set BOOTH_REVIEW_DEBUG=1 to see the traceback)",
            file=sys.stderr,
        )
        return 3
