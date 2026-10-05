"""The `booth-review` console script: `collect 506|ratingsref|cfbd`, `build`,
`site`, and `budget`.

A single argparse-based entry point (D-15); every subcommand goes through
`runtime.build_runtime`, dry-run (D-16) sends no request, and every live
batch commits and pushes the vault afterward (D-04). This is also the
module that loads the CFBD key (via `config.load_cfbd_key`) and hands it
to a collector as a bearer token — it never prints or logs the key itself.
"""

from __future__ import annotations

import argparse
import functools
import logging
import os
import re
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

from booth_review.audit.completeness import (
    SOURCES,
    CompletenessReport,
    build_completeness,
    write_completeness,
)
from booth_review.audit.freeze import FreezeResult, Waiver, freeze_seasons, parse_waiver
from booth_review.build import combined as build_combined
from booth_review.build import sample as build_sample
from booth_review.build.pipeline import BuildOutcome, run_build
from booth_review.build.site_assembly import (
    SiteBuildResult,
    assemble_site,
    docs_dir,
    fixture_path,
    site_source_dir,
)
from booth_review.config import CFBD_FLOOR_DEFAULT, DataPaths, load_cfbd_key
from booth_review.deploy.publish import SUBDIR_DEFAULT, publish_site
from booth_review.errors import BoothReviewError, FreezeRefusedError, SiteBuildError
from booth_review.job.attention import build_attention_body
from booth_review.job.runner import EXIT_NOTHING_DUE, JOB_CFBD_MAX_CALLS, JobRunResult, ScheduledJob
from booth_review.people import review as people_review
from booth_review.reference import reference_dir
from booth_review.resolve import diagnose as resolve_diagnose
from booth_review.resolve import network_diagnose
from booth_review.runtime import Runtime, build_runtime
from booth_review.seasons import season_of, season_window
from booth_review.sources.base import BatchSummary, run_requests
from booth_review.sources.cfbd.collector import ENDPOINTS, CfbdCollector
from booth_review.sources.cfbd.parser import parse_games
from booth_review.sources.ratingsref.collector import (
    FIRST_SEASON,
    REFRESH_CAP_DEFAULT,
    RatingsRefCollector,
    RefreshSummary,
)
from booth_review.sources.ratingsref.sitemap import parse_sitemap, select_entries
from booth_review.sources.sports506.collector import Sports506Collector
from booth_review.sources.sports506.importer import (
    DEFAULT_INCOMING_DIR,
    ImportResult,
    Sports506Importer,
)
from booth_review.spike.inventory import run_inventory
from booth_review.spike.join import (
    build_join_rows,
    finalize,
    load_rr_sitemap_entries,
    write_outputs,
)
from booth_review.spike.selection import (
    build_candidates,
    load_selection,
    replace_games,
    save_selection,
    select_games,
)
from booth_review.transport.budget import BudgetSummary, InfoSnapshot
from booth_review.vault import VaultRepo, batch_message

logger = logging.getLogger("booth_review.cli")

_SEASON_SPEC_RE = re.compile(r"^\d{4}(-\d{4})?$")
_MIN_SEASON = 2013


def _current_season_ceiling() -> int:
    """The latest season that can have any games yet, per the project's
    July-June season window (booth_review.seasons.season_of) rather than
    the bare calendar year -- e.g. February 2026 is still season 2025.
    """
    return season_of(datetime.now(UTC).date())


def parse_season_spec(text: str) -> list[int]:
    """Parse "2025" or "2014-2024" into an inclusive list of seasons.

    Valid seasons run 2013 through the current season (July-June window).
    Raises argparse.ArgumentTypeError on malformed input or an out-of-range
    or descending span.
    """
    if not _SEASON_SPEC_RE.match(text):
        raise argparse.ArgumentTypeError(f"invalid season spec: {text!r}")
    if "-" in text:
        start_text, end_text = text.split("-")
        start, end = int(start_text), int(end_text)
    else:
        start = end = int(text)
    if start > end:
        raise argparse.ArgumentTypeError(f"season range must be ascending: {text!r}")
    ceiling = _current_season_ceiling()
    if start < _MIN_SEASON or end > ceiling:
        raise argparse.ArgumentTypeError(
            f"season out of range [{_MIN_SEASON}, {ceiling}]: {text!r}"
        )
    return list(range(start, end + 1))


def _parse_date(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid date (expected YYYY-MM-DD): {text!r}") from exc


def _parse_endpoints(text: str) -> list[str]:
    names = [name.strip() for name in text.split(",") if name.strip()]
    unknown = [name for name in names if name not in ENDPOINTS]
    if unknown:
        raise argparse.ArgumentTypeError(f"unknown CFBD endpoint name(s): {', '.join(unknown)}")
    return names


def build_parser() -> argparse.ArgumentParser:
    """Build the `booth-review` argparse parser: `collect` and `budget`."""
    parser = argparse.ArgumentParser(prog="booth-review")
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser("collect", help="fetch and cache source data")
    collect_sub = collect.add_subparsers(dest="source", required=True)

    p506 = collect_sub.add_parser("506", help="collect 506 Sports week pages")
    p506.add_argument("--season", required=True, type=parse_season_spec)
    p506.add_argument("--dry-run", action="store_true")
    p506.add_argument("--no-commit", action="store_true")

    prr = collect_sub.add_parser("ratingsref", help="collect Ratings Reference records")
    window_group = prr.add_mutually_exclusive_group(required=True)
    window_group.add_argument("--season", type=parse_season_spec)
    window_group.add_argument("--from-date", type=_parse_date)
    prr.add_argument("--to-date", type=_parse_date)
    mode_group = prr.add_mutually_exclusive_group()
    mode_group.add_argument("--dry-run", action="store_true")
    mode_group.add_argument("--sitemap-only", action="store_true")
    prr.add_argument("--no-commit", action="store_true")

    pcfbd = collect_sub.add_parser("cfbd", help="collect CFBD season data")
    pcfbd.add_argument("--season", required=True, type=parse_season_spec)
    pcfbd.add_argument("--endpoints", type=_parse_endpoints, default=None)
    pcfbd.add_argument("--max-calls", type=int, default=None)
    pcfbd.add_argument("--tag", default=None)
    pcfbd.add_argument("--floor", type=int, default=CFBD_FLOOR_DEFAULT)
    pcfbd.add_argument("--dry-run", action="store_true")
    pcfbd.add_argument("--no-commit", action="store_true")

    refresh = sub.add_parser("refresh", help="re-fetch source records whose lastmod changed")
    refresh_sub = refresh.add_subparsers(dest="source", required=True)
    prefresh = refresh_sub.add_parser(
        "ratingsref", help="refresh Ratings Reference records whose sitemap lastmod advanced"
    )
    prefresh.add_argument("--cap", type=int, default=REFRESH_CAP_DEFAULT)
    prefresh.add_argument("--dry-run", action="store_true")
    prefresh.add_argument("--no-commit", action="store_true")

    import_cmd = sub.add_parser("import", help="import hand-saved source pages into the vault")
    import_sub = import_cmd.add_subparsers(dest="source", required=True)

    p506imp = import_sub.add_parser("506", help="import hand-saved 506 Sports week pages")
    p506imp.add_argument("--season", required=True, type=parse_season_spec)
    p506imp.add_argument("--from", dest="from_dir", type=Path, default=None)
    p506imp.add_argument("--force", action="store_true")
    p506imp.add_argument("--no-commit", action="store_true")

    spike = sub.add_parser("spike", help="spike-only analysis commands (SPIKE-03/04)")
    spike_sub = spike.add_subparsers(dest="spike_command", required=True)
    spike_inventory = spike_sub.add_parser(
        "inventory", help="rebuild source inventories and the pregame-measure report from raw"
    )
    spike_inventory.add_argument("--no-commit", action="store_true")

    spike_join = spike_sub.add_parser(
        "join", help="build/finalize the SPIKE-02 20-game hand-join outputs (D-06/D-09)"
    )
    spike_join.add_argument("--reselect", action="store_true")
    spike_join.add_argument(
        "--replace-rows",
        type=_parse_row_list,
        default=None,
        help="comma-separated 1-based rows of selection.csv to swap for new games",
    )
    spike_join.add_argument("--finalize", action="store_true")
    spike_join.add_argument("--no-commit", action="store_true")

    audit = sub.add_parser("audit", help="D-05 completeness audit")
    audit_sub = audit.add_subparsers(dest="audit_command", required=True)
    audit_completeness = audit_sub.add_parser(
        "completeness", help="write a season x source completeness report"
    )
    audit_completeness.add_argument("--season", required=True, type=parse_season_spec)
    audit_completeness.add_argument("--no-commit", action="store_true")

    freeze = sub.add_parser("freeze", help="D-06 freeze seasons after a completeness check")
    freeze.add_argument("--season", required=True, type=parse_season_spec)
    freeze.add_argument("--waive", type=parse_waiver, action="append", default=[])
    freeze.add_argument("--dry-run", action="store_true")
    freeze.add_argument("--no-commit", action="store_true")

    job = sub.add_parser("job", help="AUTO-01 scheduled collect-only job")
    job_sub = job.add_subparsers(dest="job_command", required=True)
    job_run = job_sub.add_parser("run", help="run one scheduled collect-only pass")
    job_run.add_argument("--trigger", choices=["schedule", "manual"], default="manual")
    job_run.add_argument("--rr-cap", type=int, default=REFRESH_CAP_DEFAULT)
    job_run.add_argument("--max-cfbd-calls", type=int, default=JOB_CFBD_MAX_CALLS)
    job_run.add_argument("--attention-out", type=Path, default=None)
    job_run.add_argument("--dry-run", action="store_true")
    job_run.add_argument("--no-commit", action="store_true")
    job_run.add_argument(
        "--update",
        action="store_true",
        help="also rebuild, assemble the site with a required key check, "
        "and report deploy readiness",
    )
    job_run.add_argument("--site-out", type=Path, default=None)
    job_run.add_argument("--result-out", type=Path, default=None)

    budget = sub.add_parser("budget", help="report and record CFBD budget usage")
    budget.add_argument("--offline", action="store_true")
    budget.add_argument("--probe-info-cost", action="store_true")
    budget.add_argument("--floor", type=int, default=CFBD_FLOOR_DEFAULT)
    budget.add_argument("--no-commit", action="store_true")

    build_cmd = sub.add_parser(
        "build",
        help="Phase 3 full rebuild from raw: tables, coverage, regression guard, site data",
    )
    build_cmd.add_argument("--no-commit", action="store_true")
    build_cmd.add_argument("--accept-baseline", action="store_true")

    site_cmd = sub.add_parser(
        "site", help="D-14: assemble dist/site/ from site/, site-data.json, and rendered pages"
    )
    site_cmd.add_argument(
        "--fixture",
        action="store_true",
        help="use the synthetic contract fixture instead of the vault's processed/site-data.json",
    )
    site_cmd.add_argument("--out", type=Path, default=Path("dist/site"))
    site_cmd.add_argument(
        "--require-key-check",
        action="store_true",
        help="AUTO-05: exit 3 when the CFBD key check was skipped (no key configured)",
    )

    deploy_cmd = sub.add_parser(
        "deploy",
        help="AUTO-03: mirror an assembled site into booth-review/ of a checked-out target "
        "repo; does nothing unless PUBLISH_ENABLED is true",
    )
    deploy_cmd.add_argument("--site", type=Path, required=True)
    deploy_cmd.add_argument("--target", type=Path, required=True)
    deploy_cmd.add_argument("--subdir", default=SUBDIR_DEFAULT)

    review = sub.add_parser(
        "review", help="Phase 3 review tools: teams, people, networks, combined"
    )
    review_sub = review.add_subparsers(dest="review_command", required=True)

    review_teams = review_sub.add_parser(
        "teams", help="JOIN-01/02/08 crosswalk match diagnostic (resolve.diagnose)"
    )
    review_teams.add_argument("--no-write", action="store_true")

    review_people = review_sub.add_parser(
        "people", help="people registry scan/apply (people.review)"
    )
    review_people.add_argument(
        "--apply", action="store_true", help="apply review_people.csv's decisions (default: scan)"
    )

    review_networks = review_sub.add_parser(
        "networks",
        help="JOIN-06 outlet inventory and combination diagnostic (resolve.network_diagnose)",
    )
    review_networks.add_argument("--no-write", action="store_true")

    review_sub.add_parser(
        "combined",
        help="combined-figure candidates; proposals stay in the vault review file (build.combined)",
    )

    review_sample = review_sub.add_parser(
        "sample", help="JOIN-08 stratified sample of plotted telecasts for a hand-check (D-08)"
    )
    review_sample.add_argument("--size", type=int, default=build_sample.DEFAULT_SIZE)
    review_sample.add_argument("--seed", type=int, default=build_sample.DEFAULT_SEED)

    return parser


# -- shared run/commit/print helpers -----------------------------------------------


def _partial_counts(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    return {
        "fetched": after["fetched"] - before["fetched"],
        "cached": after["cached"] - before["cached"],
        "not_modified": after["not_modified"] - before["not_modified"],
        "failed": 0,
    }


def _run_and_commit(
    runtime: Runtime,
    run: Callable[[], BatchSummary],
    *,
    action: str,
    source: str,
    season_label: str,
    dry_run: bool,
    no_commit: bool,
) -> BatchSummary:
    """Run one collector batch; commit whatever was fetched even when `run`
    raises partway through (D-04), then let the exception propagate.
    """
    before = dict(runtime.cache.counters)
    summary: BatchSummary | None = None
    try:
        summary = run()
    finally:
        if not dry_run and not no_commit:
            counts = (
                summary.counts()
                if summary is not None
                else _partial_counts(before, runtime.cache.counters)
            )
            runtime.vault.commit_batch(batch_message(action, source, season_label, counts))
    assert summary is not None
    return summary


def _identity(url: str) -> str:
    return url


def _parse_row_list(text: str) -> list[int]:
    try:
        return [int(part) for part in text.split(",") if part.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected comma-separated row numbers: {text}") from exc


def _cfbd_url_display(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.path}?{parts.query}" if parts.query else parts.path


def _print_dry_run(
    summary: BatchSummary,
    *,
    url_display: Callable[[str], str] = _identity,
    cfbd: bool = False,
) -> None:
    for url in summary.new_urls:
        print(url_display(url))
    line = (
        f"planned {summary.planned}, cached {summary.cached}, new {len(summary.new_urls)}, "
        f"frozen-miss {summary.frozen_miss}"
    )
    # Only CFBD requests spend the monthly budget; other sources would overstate it.
    if cfbd:
        line += f", cfbd calls {summary.cfbd_calls}"
    print(line)


def _print_run_summary(
    summary: BatchSummary, *, url_display: Callable[[str], str] = _identity
) -> None:
    print(
        f"fetched {summary.fetched}, cached {summary.cached}, "
        f"not_modified {summary.not_modified}, failed {summary.failed}"
    )
    for url in summary.failed_urls:
        print(f"failed: {url_display(url)}")


# -- collect 506 --------------------------------------------------------------------


def _collect_506(args: argparse.Namespace) -> int:
    runtime = build_runtime(with_budget=False)
    try:
        collector = Sports506Collector(runtime.cache)
        any_failed = False
        for season in args.season:
            season_label = str(season)
            summary = _run_and_commit(
                runtime,
                functools.partial(collector.run, season, dry_run=args.dry_run),
                action="collect",
                source="sports506",
                season_label=season_label,
                dry_run=args.dry_run,
                no_commit=args.no_commit,
            )
            if args.dry_run:
                _print_dry_run(summary)
            elif summary.failed_urls:
                _print_run_summary(summary)
                any_failed = True
            else:
                _print_run_summary(summary)
        return 4 if any_failed else 0
    finally:
        runtime.client.close()


# -- collect ratingsref ---------------------------------------------------------------


def _collect_ratingsref(args: argparse.Namespace) -> int:
    runtime = build_runtime(with_budget=False)
    try:
        collector = RatingsRefCollector(runtime.cache, runtime.paths, lock=runtime.vault.lock)

        if args.season is not None:
            seasons = args.season
            start = season_window(min(seasons))[0]
            end = season_window(max(seasons))[1]
        else:
            if args.to_date is None:
                print(
                    "error: --to-date is required when --from-date is given",
                    file=sys.stderr,
                )
                return 3
            start, end = args.from_date, args.to_date

        season_label = f"{start}..{end}"

        if args.sitemap_only:
            return _collect_ratingsref_sitemap_only(
                runtime, collector, start, end, season_label, args
            )

        summary = _run_and_commit(
            runtime,
            functools.partial(collector.run, start, end, dry_run=args.dry_run),
            action="collect",
            source="ratingsref",
            season_label=season_label,
            dry_run=args.dry_run,
            no_commit=args.no_commit,
        )
        if args.dry_run:
            _print_dry_run(summary)
        else:
            _print_run_summary(summary)
        return 4 if summary.failed_urls else 0
    finally:
        runtime.client.close()


def _collect_ratingsref_sitemap_only(
    runtime: Runtime,
    collector: RatingsRefCollector,
    start: date,
    end: date,
    season_label: str,
    args: argparse.Namespace,
) -> int:
    before = dict(runtime.cache.counters)
    xml = collector.sitemap(dry_run=False)
    counts = _partial_counts(before, runtime.cache.counters)
    if not args.no_commit:
        runtime.vault.commit_batch(batch_message("collect", "ratingsref", season_label, counts))

    assert xml is not None
    entries, _skipped = parse_sitemap(xml)
    selected = select_entries(entries, start, end)
    requests = collector.plan(selected)
    plan_summary = run_requests(
        runtime.cache, requests, source="ratingsref", season_label=season_label, dry_run=True
    )
    _print_dry_run(plan_summary)
    return 0


# -- refresh ratingsref ---------------------------------------------------------------


def _partial_refresh_counts(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    return {
        "fetched": after["fetched"] - before["fetched"],
        "not_modified": after["not_modified"] - before["not_modified"],
        "failed": 0,
        "backlog": 0,
    }


def _print_refresh_summary(summary: RefreshSummary) -> None:
    print(
        f"qualifying {summary.qualifying}, new {summary.new}, advanced {summary.advanced}, "
        f"selected {summary.selected}, uncapped_current {summary.uncapped_current}, "
        f"backlog {summary.backlog}"
    )
    if summary.deferred_failed > 0:
        print(f"held back after a recent failed fetch {summary.deferred_failed}")


def _refresh_ratingsref(args: argparse.Namespace) -> int:
    runtime = build_runtime(with_budget=False)
    try:
        collector = RatingsRefCollector(runtime.cache, runtime.paths, lock=runtime.vault.lock)
        current_season = _current_season_ceiling()
        season_label = f"{FIRST_SEASON}-{current_season}"

        before = dict(runtime.cache.counters)
        summary: RefreshSummary | None = None
        try:
            summary = collector.refresh(
                current_season=current_season, cap=args.cap, dry_run=args.dry_run
            )
        finally:
            if not args.dry_run and not args.no_commit:
                counts = (
                    summary.counts()
                    if summary is not None
                    else _partial_refresh_counts(before, runtime.cache.counters)
                )
                runtime.vault.commit_batch(
                    batch_message("refresh", "ratingsref", season_label, counts),
                    paths=[
                        "raw/ratingsref",
                        "raw/_robots",
                        "ledger/requests.jsonl",
                        "ledger/rr_lastmod.json",
                        "ledger/rr_lastmod.jsonl",
                    ],
                )
        assert summary is not None

        _print_refresh_summary(summary)
        if not args.dry_run:
            print(
                f"fetched {summary.fetched}, not_modified {summary.not_modified}, "
                f"failed {summary.failed}"
            )
            if summary.backlog > 0:
                print(f"backlog {summary.backlog}")
            return 4 if summary.failed > 0 or summary.backlog > 0 else 0
        return 0
    finally:
        runtime.client.close()


# -- collect cfbd ---------------------------------------------------------------------


def _collect_cfbd(args: argparse.Namespace) -> int:
    runtime = build_runtime(
        with_budget=True, floor=args.floor, max_calls=args.max_calls, tag=args.tag
    )
    try:
        assert runtime.budget is not None
        names = args.endpoints if args.endpoints is not None else list(ENDPOINTS.keys())
        token = load_cfbd_key() if not args.dry_run else None
        collector = CfbdCollector(runtime.cache, runtime.budget, token)

        any_failed = False
        for season in args.season:
            season_label = str(season)
            summary = _run_and_commit(
                runtime,
                functools.partial(collector.run, season, names, dry_run=args.dry_run),
                action="collect",
                source="cfbd",
                season_label=season_label,
                dry_run=args.dry_run,
                no_commit=args.no_commit,
            )
            if args.dry_run:
                _print_dry_run(summary, url_display=_cfbd_url_display, cfbd=True)
                remaining = runtime.budget.last_known_remaining()
                if remaining is not None:
                    print(f"remaining (last known): {remaining}")
                    if remaining - summary.cfbd_calls < args.floor:
                        print(
                            f"warning: planned {summary.cfbd_calls} calls would drop "
                            f"remaining below the floor of {args.floor}",
                            file=sys.stderr,
                        )
            else:
                _print_run_summary(summary, url_display=_cfbd_url_display)
                if summary.failed_urls:
                    any_failed = True
        return 4 if any_failed else 0
    finally:
        runtime.client.close()


# -- import 506 ----------------------------------------------------------------------------


def _print_import_result(result: ImportResult) -> None:
    total = len(result.expected)
    present = total - len(result.missing)
    source_note = "(weeks from nav)" if result.expected_source == "nav" else "(default 18 weeks)"
    print(
        f"season {result.season}: present {present}/{total}, "
        f"missing {len(result.missing)}/{total} {source_note}"
    )
    if result.missing:
        print(f"missing weeks: {', '.join(result.missing)}")
    if result.unsupported_labels:
        print(f"unsupported nav weeks: {', '.join(result.unsupported_labels)}")
    print(
        f"imported {len(result.imported)}, skipped_existing {len(result.skipped_existing)}, "
        f"skipped_invalid {len(result.skipped_invalid)}"
    )
    for item in result.skipped_invalid:
        print(f"skipped wk-{item.label}: {item.reason}")
    if result.unrecognized:
        print(f"ignored {result.unrecognized} HTML file(s) that aren't 506 week pages")


def _import_506(args: argparse.Namespace) -> int:
    runtime = build_runtime(with_budget=False)
    try:
        importer = Sports506Importer(runtime.cache, runtime.paths)
        incoming_dir = args.from_dir if args.from_dir is not None else DEFAULT_INCOMING_DIR

        any_problems = False
        for season in args.season:
            # D-04: hold the vault lock and commit only this season's own
            # files, so a concurrent RR refresh or another season's import
            # never races on the same working copy (T-02-02).
            with runtime.vault.lock():
                result = importer.run(season, incoming_dir=incoming_dir, force=args.force)
                _print_import_result(result)
                if result.has_problems:
                    any_problems = True
                if not args.no_commit:
                    message = batch_message("import", "sports506", str(season), result.counts())
                    runtime.vault.commit_batch(
                        message, paths=[f"raw/sports506/{season}", "ledger/requests.jsonl"]
                    )
        return 4 if any_problems else 0
    finally:
        runtime.client.close()


# -- spike inventory ----------------------------------------------------------------------


def _spike_inventory(args: argparse.Namespace) -> int:
    """Rebuild the SPIKE-03/04 reports from data already cached in the vault.

    Builds no PoliteClient (there is nothing to fetch): only checks the vault
    is a real, pushable git working copy, then calls run_inventory.
    """
    paths = DataPaths.from_env()
    VaultRepo(paths.vault).check()
    run_inventory(paths, commit=not args.no_commit)
    return 0


# -- spike join ---------------------------------------------------------------------------

_SPIKE_JOIN_SEASON = 2025


def _spike_join(args: argparse.Namespace) -> int:
    """Build (or finalize) the SPIKE-02 hand-join outputs from data already
    cached in the vault. Builds no PoliteClient: only checks the vault is a
    real, pushable git working copy, then reads/writes data/vault/spike/.
    """
    paths = DataPaths.from_env()
    vault = VaultRepo(paths.vault)
    vault.check()

    if args.finalize:
        result = finalize(paths)
        verdict = "PASS" if result["passed"] else "FAIL"
        print(
            f"confirmed {result['confirmed']}, corrected {result['corrected']}, "
            f"rejected {result['rejected']}"
        )
        print(f"join rate {result['confirmed']}/{result['total']}: D-09 (80%) {verdict}")
        if not args.no_commit:
            counts = {"confirmed": cast(int, result["confirmed"])}
            vault.commit_batch(
                batch_message("spike", "join-final", str(_SPIKE_JOIN_SEASON), counts)
            )
        return 0

    selection_path = paths.spike / "selection.csv"
    selections = None if args.reselect else load_selection(selection_path)
    if selections is None or args.replace_rows:
        games_path = paths.raw / "cfbd" / "games" / f"{_SPIKE_JOIN_SEASON}.json"
        games = parse_games(games_path.read_bytes())
        rr_entries = load_rr_sitemap_entries(paths)
        candidates = build_candidates(games, rr_entries)
        if selections is not None and args.replace_rows:
            selections = replace_games(selections, args.replace_rows, candidates)
        else:
            selections = select_games(candidates)
        save_selection(selection_path, selections)

    rows = build_join_rows(paths, selections)
    write_outputs(paths, rows, selections)
    print(f"selected {len(selections)}, rows {len(rows)}")
    if not args.no_commit:
        vault.commit_batch(
            batch_message("spike", "join", str(_SPIKE_JOIN_SEASON), {"rows": len(rows)})
        )
    return 0


# -- audit completeness --------------------------------------------------------------------


def _print_completeness(report: CompletenessReport, seasons: Sequence[int]) -> None:
    by_key = {(cell.season, cell.source): cell for cell in report.cells}
    for season in seasons:
        parts = []
        for source in SOURCES:
            cell = by_key.get((season, source))
            status = "complete" if cell is not None and cell.complete else "incomplete"
            parts.append(f"{source}={status}")
        print(f"season {season}: {' '.join(parts)}")


def _audit_completeness(args: argparse.Namespace) -> int:
    """Write the D-05 completeness report from data already cached in the
    vault. Builds no PoliteClient: only checks the vault is a real, pushable
    git working copy, then reads/writes data/vault/audit/.
    """
    paths = DataPaths.from_env()
    vault = VaultRepo(paths.vault)
    vault.check()

    report = build_completeness(paths, args.season, now=datetime.now(UTC))
    with vault.lock():
        write_completeness(paths, report)
        if not args.no_commit:
            complete_count = sum(1 for season in args.season if report.complete_for(season))
            incomplete_count = len(args.season) - complete_count
            season_label = f"{min(args.season)}-{max(args.season)}"
            vault.commit_batch(
                batch_message(
                    "audit",
                    "completeness",
                    season_label,
                    {"complete": complete_count, "incomplete": incomplete_count},
                ),
                paths=["audit"],
            )

    _print_completeness(report, args.season)
    complete_count = sum(1 for season in args.season if report.complete_for(season))
    return 0 if complete_count == len(args.season) else 4


# -- freeze -----------------------------------------------------------------------------


def _freeze(args: argparse.Namespace) -> int:
    """Re-verify D-05 completeness and D-06 freeze dates, then write
    ledger/frozen.json for --season. Refuses (writes nothing to frozen.json)
    on any unmet precondition; builds no PoliteClient.
    """
    paths = DataPaths.from_env()
    vault = VaultRepo(paths.vault)
    vault.check()

    today = datetime.now(UTC).date()
    season_label = f"{min(args.season)}-{max(args.season)}"
    waivers: list[Waiver] = args.waive

    try:
        with vault.lock():
            result: FreezeResult = freeze_seasons(
                paths, args.season, today=today, waivers=waivers, dry_run=args.dry_run
            )
            if not args.dry_run and not args.no_commit:
                vault.commit_batch(
                    batch_message(
                        "freeze",
                        "all",
                        season_label,
                        {"seasons": len(args.season), "waived": len(result.waivers)},
                    ),
                    paths=["ledger/frozen.json", "audit"],
                )
    except FreezeRefusedError as exc:
        print("freeze refused:", file=sys.stderr)
        for line in str(exc).splitlines():
            print(f"  {line}", file=sys.stderr)
        return 4

    verb = "would freeze" if args.dry_run else "froze"
    print(
        f"{verb} {len(result.seasons_added)} season(s), "
        f"{len(result.already_frozen)} already frozen, {len(result.waivers)} waived"
    )
    return 0


# -- job run (AUTO-01) -------------------------------------------------------------------


def _job_run(args: argparse.Namespace) -> int:
    """Run one scheduled pass (collect-only, or the full update with --update).
    Never prints or logs the CFBD key (loaded via config.load_cfbd_key, same
    as every other live command)."""
    if args.update and args.site_out is None:
        print("error: --update requires --site-out", file=sys.stderr)
        return 2
    runtime = build_runtime(
        with_budget=True, floor=CFBD_FLOOR_DEFAULT, max_calls=args.max_cfbd_calls, tag="job"
    )
    try:
        token = None if args.dry_run else load_cfbd_key()
        job = ScheduledJob(
            runtime,
            token=token,
            now=lambda: datetime.now(UTC),
            trigger=args.trigger,
            rr_cap=args.rr_cap,
            dry_run=args.dry_run,
            commit=not args.no_commit,
            update=args.update,
            site_out=args.site_out,
        )
        result: JobRunResult = job.run()

        if result.exit_code == EXIT_NOTHING_DUE:
            print("nothing due since last attempt")

        if args.attention_out is not None:
            body = build_attention_body(result.items, generated_at=datetime.now(UTC))
            if body is not None:
                args.attention_out.parent.mkdir(parents=True, exist_ok=True)
                args.attention_out.write_text(body, encoding="utf-8")

        if args.result_out is not None:
            args.result_out.parent.mkdir(parents=True, exist_ok=True)
            args.result_out.write_text(
                f"deploy_ready={'true' if result.deploy_ready else 'false'}\n"
                f"stale_only={'true' if result.stale_only else 'false'}\n",
                encoding="utf-8",
            )

        return result.exit_code
    finally:
        runtime.client.close()


# -- budget -----------------------------------------------------------------------------


def _print_budget_summary(summary: BudgetSummary, *, snapshot: InfoSnapshot | None = None) -> None:
    print(f"month {summary.month}")
    print(f"remaining {summary.last_remaining}")
    if snapshot is not None:
        print(f"monthly limit {snapshot.monthly_limit}")
        print(f"reset at {snapshot.reset_at}")
    print(f"floor {summary.floor}")
    print(f"info counts against quota: {summary.info_counts_against_quota}")
    for endpoint, count in sorted(summary.by_endpoint.items()):
        print(f"calls {endpoint}: {count}")
    for tag, count in sorted(summary.by_tag.items()):
        print(f"calls tag={tag}: {count}")


def _budget(args: argparse.Namespace) -> int:
    runtime = build_runtime(with_budget=True, floor=args.floor)
    try:
        assert runtime.budget is not None
        budget = runtime.budget

        if args.offline:
            _print_budget_summary(budget.summary())
            return 0

        token = load_cfbd_key()
        collector = CfbdCollector(runtime.cache, budget, token)

        if args.probe_info_cost:
            snapshot, _probed = collector.probe_info_cost()
            calls_made = 2
        else:
            snapshot = collector.info()
            calls_made = 1

        _print_budget_summary(budget.summary(), snapshot=snapshot)

        if not args.no_commit:
            runtime.vault.commit_batch(
                batch_message("budget", "cfbd", "info", {"calls": calls_made})
            )
        return 0
    finally:
        runtime.client.close()


# -- build (D-12) -------------------------------------------------------------------------


def _build(args: argparse.Namespace) -> int:
    """Rebuild every processed table from raw behind the AUDIT-03 regression
    guard; prints counts and rates only (T-03-45)."""
    paths = DataPaths.from_env()
    try:
        outcome: BuildOutcome = run_build(
            paths,
            reference_dir(),
            commit=not args.no_commit,
            accept_baseline=args.accept_baseline,
        )
    except BoothReviewError:
        raise
    except Exception as exc:
        # An unexpected error's message or traceback can carry a vault value
        # (a team or person name), so only its type is printed unless the
        # user opts in locally (WR-03).
        if os.environ.get("BOOTH_REVIEW_DEBUG"):
            raise
        print(
            f"error: unexpected {type(exc).__name__} during build; details withheld "
            "(set BOOTH_REVIEW_DEBUG=1 to see the traceback)",
            file=sys.stderr,
        )
        return 3
    exit_blocked = outcome.blocked and not outcome.accepted
    rate = outcome.counts.get("join08_rate_x10000", 0) / 100
    print(
        f"telecasts {outcome.counts.get('plotted_telecasts', 0)} plotted, "
        f"join rate {rate:.1f}%, merges {outcome.counts.get('duplicate_merges', 0)}, "
        f"blocked {'yes' if exit_blocked else 'no'}"
    )
    if "rivalry_games_tagged" in outcome.counts:
        # D-13: title games excluded via CFBD notes (2022 on) and later meetings
        # demoted by the first-meeting rule. Counts only.
        print(
            f"rivalries: {outcome.counts['rivalry_games_tagged']} games tagged "
            f"({outcome.counts['rivalry_telecasts_tagged']} plotted telecasts), "
            f"title games excluded {outcome.counts['rivalry_title_games_excluded']}, "
            f"rematches demoted {outcome.counts['rivalry_rematches_demoted']}"
        )
    bowl_names_unknown = outcome.counts.get("bowl_names_unknown", 0)
    if bowl_names_unknown > 0:
        print(f"bowl names unknown {bowl_names_unknown}")
    if (n := outcome.counts.get("preliminary_headlines_over_10_days", 0)) > 0:
        print(f"preliminary headlines over 10 days old: {n}")
    if (n := outcome.counts.get("crew_overrides_applied", 0)) > 0:
        print(f"crew overrides applied {n}")
    if (n := outcome.counts.get("crew_overrides_patched", 0)) > 0:
        print(f"crew overrides patching a telecast 506 gave no crew: {n}")
    if (n := outcome.counts.get("crew_overrides_redundant", 0)) > 0:
        print(f"crew overrides now redundant: {n}")
    if (n := outcome.counts.get("crew_overrides_corrections", 0)) > 0:
        # A correction deliberately replaces a crew 506 publishes; always say so.
        print(f"crew overrides correcting 506: {n} (see interim/review_crew_overrides.csv)")
    if (n := outcome.counts.get("crew_overrides_differs", 0)) > 0:
        print(f"crew overrides differing from 506: {n} (see interim/review_crew_overrides.csv)")
    # An override whose booth disagrees with the crew 506 lists, without
    # reason `correction`, is either mislabeled or 506 has a newer crew. The
    # override still wins and the build is not blocked; flag each row so the
    # user decides. Only public crew_overrides.csv line numbers are printed.
    for line in outcome.crew_override_differs_lines:
        print(
            f"warning: crew_overrides.csv line {line}: booth differs from the crew 506 lists "
            "but reason is not correction; set reason to correction if the override is "
            "right, or fix the row if 506 is",
            file=sys.stderr,
        )
    print(f"crew gaps unpatched {outcome.counts.get('crew_gaps_unpatched', 0)}")
    if outcome.accepted:
        print("accepted new baseline")
    for reason in outcome.reasons:
        print(reason)
    return 4 if exit_blocked else 0


# -- site (D-14) --------------------------------------------------------------------------


def _site(args: argparse.Namespace) -> int:
    """Assemble dist/site/ (D-14) from site/, docs/, and either the
    synthetic fixture or the vault's processed/site-data.json. Read-only
    against the vault -- no VaultRepo lock needed."""
    if args.fixture:
        source = fixture_path()
    else:
        source = DataPaths.from_env().processed / "site-data.json"
        if not source.is_file():
            raise SiteBuildError(
                "processed/site-data.json not found; run `booth-review build` first"
            )
    try:
        result: SiteBuildResult = assemble_site(
            source=source,
            out_dir=args.out,
            site_src=site_source_dir(),
            docs=docs_dir(),
        )
    except BoothReviewError:
        raise
    except Exception as exc:
        # An unexpected error's message or traceback could carry a data
        # value, so only its type is printed unless the user opts in
        # locally (WR-03).
        if os.environ.get("BOOTH_REVIEW_DEBUG"):
            raise
        print(
            f"error: unexpected {type(exc).__name__} assembling the site; details withheld "
            "(set BOOTH_REVIEW_DEBUG=1 to see the traceback)",
            file=sys.stderr,
        )
        return 3
    if args.require_key_check and not result.key_checked:
        print(
            "cfbd key check: skipped (no key configured); --require-key-check set",
            file=sys.stderr,
        )
        return 3
    prefix = "site (fixture):" if args.fixture else "site:"
    print(
        f"{prefix} {result.telecasts} telecasts, {result.people} people, "
        f"{len(result.files)} files -> {result.out_dir}"
    )
    print(
        "cfbd key check: passed"
        if result.key_checked
        else "cfbd key check: skipped (no key configured)"
    )
    return 0


# -- deploy (AUTO-03) ----------------------------------------------------------------------


def _deploy(args: argparse.Namespace) -> int:
    """Mirror an assembled site into the target checkout. Output is count-only."""
    try:
        result = publish_site(args.site, args.target, subdir=args.subdir)
    except ValueError:
        print("error: invalid --subdir", file=sys.stderr)
        return 2
    except BoothReviewError:
        raise
    except Exception as exc:
        if os.environ.get("BOOTH_REVIEW_DEBUG"):
            raise
        print(
            f"error: unexpected {type(exc).__name__} during deploy; details withheld "
            "(set BOOTH_REVIEW_DEBUG=1 to see the traceback)",
            file=sys.stderr,
        )
        return 3
    if result.status == "skipped":
        print("deploy skipped: publishing disabled")
        return 0
    short = (result.bundle_sha256 or "")[:12]
    if result.status == "no_change":
        print(f"deploy: no change (bundle {short}, files {result.files})")
    else:
        print(
            f"deploy: published bundle {short} (files {result.files}, attempts {result.attempts})"
        )
    print(
        "outside booth-review unchanged: yes "
        f"(before {(result.outside_before or '')[:12]}, after {(result.outside_after or '')[:12]})"
    )
    return 0


# -- review (Plans 04/05/06/09 review tools) -----------------------------------------------


def _with_vault_lock(run: Callable[[], int]) -> int:
    """Run a vault-writing review command under the vault lock (AGENTS.md:
    every command that writes to the vault holds it), so it can never
    interleave with a scheduled-job or build commit (WR-08).
    """
    with VaultRepo(DataPaths.from_env().vault).lock():
        return run()


def _review_teams(args: argparse.Namespace) -> int:
    if args.no_write:
        return resolve_diagnose.main(["--no-write"])
    return _with_vault_lock(lambda: resolve_diagnose.main([]))


def _review_people(args: argparse.Namespace) -> int:
    return _with_vault_lock(lambda: people_review.main(["apply"] if args.apply else ["scan"]))


def _review_networks(args: argparse.Namespace) -> int:
    if args.no_write:
        return network_diagnose.main(["--no-write"])
    return _with_vault_lock(lambda: network_diagnose.main([]))


def _review_combined(args: argparse.Namespace) -> int:
    def _run() -> int:
        build_combined.main([])
        return 0

    return _with_vault_lock(_run)


def _review_sample(args: argparse.Namespace) -> int:
    return _with_vault_lock(
        lambda: build_sample.main(["--size", str(args.size), "--seed", str(args.seed)])
    )


# -- main -------------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr
    )
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "collect":
            if args.source == "506":
                return _collect_506(args)
            if args.source == "ratingsref":
                return _collect_ratingsref(args)
            if args.source == "cfbd":
                return _collect_cfbd(args)
            raise AssertionError(f"unknown collect source: {args.source!r}")
        if args.command == "refresh":
            if args.source == "ratingsref":
                return _refresh_ratingsref(args)
            raise AssertionError(f"unknown refresh source: {args.source!r}")
        if args.command == "import":
            if args.source == "506":
                return _import_506(args)
            raise AssertionError(f"unknown import source: {args.source!r}")
        if args.command == "spike":
            if args.spike_command == "inventory":
                return _spike_inventory(args)
            if args.spike_command == "join":
                return _spike_join(args)
            raise AssertionError(f"unknown spike command: {args.spike_command!r}")
        if args.command == "audit":
            if args.audit_command == "completeness":
                return _audit_completeness(args)
            raise AssertionError(f"unknown audit command: {args.audit_command!r}")
        if args.command == "freeze":
            return _freeze(args)
        if args.command == "job":
            if args.job_command == "run":
                return _job_run(args)
            raise AssertionError(f"unknown job command: {args.job_command!r}")
        if args.command == "budget":
            return _budget(args)
        if args.command == "build":
            return _build(args)
        if args.command == "site":
            return _site(args)
        if args.command == "deploy":
            return _deploy(args)
        if args.command == "review":
            if args.review_command == "teams":
                return _review_teams(args)
            if args.review_command == "people":
                return _review_people(args)
            if args.review_command == "networks":
                return _review_networks(args)
            if args.review_command == "combined":
                return _review_combined(args)
            if args.review_command == "sample":
                return _review_sample(args)
            raise AssertionError(f"unknown review command: {args.review_command!r}")
        raise AssertionError(f"unknown command: {args.command!r}")
    except BoothReviewError as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
