"""The `booth-review` console script: `collect 506|ratingsref|cfbd` and `budget`.

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
import re
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urlsplit

from booth_review.config import CFBD_FLOOR_DEFAULT, load_cfbd_key
from booth_review.errors import BoothReviewError
from booth_review.runtime import Runtime, build_runtime
from booth_review.seasons import season_window
from booth_review.sources.base import BatchSummary, run_requests
from booth_review.sources.cfbd.collector import ENDPOINTS, CfbdCollector
from booth_review.sources.ratingsref.collector import RatingsRefCollector
from booth_review.sources.ratingsref.sitemap import parse_sitemap, select_entries
from booth_review.sources.sports506.collector import Sports506Collector
from booth_review.sources.sports506.importer import (
    DEFAULT_INCOMING_DIR,
    ImportResult,
    Sports506Importer,
)
from booth_review.transport.budget import BudgetSummary, InfoSnapshot
from booth_review.vault import batch_message

logger = logging.getLogger("booth_review.cli")

_SEASON_SPEC_RE = re.compile(r"^\d{4}(-\d{4})?$")
_MIN_SEASON = 2013


def _current_season_ceiling() -> int:
    return datetime.now(UTC).year


def parse_season_spec(text: str) -> list[int]:
    """Parse "2025" or "2014-2024" into an inclusive list of seasons.

    Valid seasons run 2013 through the current UTC year. Raises
    argparse.ArgumentTypeError on malformed input or an out-of-range or
    descending span.
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

    import_cmd = sub.add_parser("import", help="import hand-saved source pages into the vault")
    import_sub = import_cmd.add_subparsers(dest="source", required=True)

    p506imp = import_sub.add_parser("506", help="import hand-saved 506 Sports week pages")
    p506imp.add_argument("--season", required=True, type=parse_season_spec)
    p506imp.add_argument("--from", dest="from_dir", type=Path, default=None)
    p506imp.add_argument("--force", action="store_true")
    p506imp.add_argument("--no-commit", action="store_true")

    budget = sub.add_parser("budget", help="report and record CFBD budget usage")
    budget.add_argument("--offline", action="store_true")
    budget.add_argument("--probe-info-cost", action="store_true")
    budget.add_argument("--floor", type=int, default=CFBD_FLOOR_DEFAULT)
    budget.add_argument("--no-commit", action="store_true")

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
        collector = RatingsRefCollector(runtime.cache, runtime.paths)

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


_EXPECTED_506_WEEKS = 18


def _print_import_result(result: ImportResult) -> None:
    present = _EXPECTED_506_WEEKS - len(result.missing)
    print(
        f"season {result.season}: present {present}/{_EXPECTED_506_WEEKS}, "
        f"missing {len(result.missing)}/{_EXPECTED_506_WEEKS}"
    )
    if result.missing:
        print(f"missing weeks: {', '.join(result.missing)}")
    print(
        f"imported {len(result.imported)}, skipped_existing {len(result.skipped_existing)}, "
        f"skipped_invalid {len(result.skipped_invalid)}"
    )
    for item in result.skipped_invalid:
        print(f"skipped wk-{item.label}: {item.reason}")


def _import_506(args: argparse.Namespace) -> int:
    runtime = build_runtime(with_budget=False)
    try:
        importer = Sports506Importer(runtime.cache, runtime.paths)
        incoming_dir = args.from_dir if args.from_dir is not None else DEFAULT_INCOMING_DIR

        any_problems = False
        for season in args.season:
            result = importer.run(season, incoming_dir=incoming_dir, force=args.force)
            _print_import_result(result)
            if result.has_problems:
                any_problems = True
            if not args.no_commit:
                message = batch_message("import", "sports506", str(season), result.counts())
                runtime.vault.commit_batch(message)
        return 4 if any_problems else 0
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
            before = collector.info()
            after = collector.info()
            if before.remaining_calls is not None and after.remaining_calls is not None:
                budget.record_info_probe(before.remaining_calls, after.remaining_calls)
            snapshot = after
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
        if args.command == "import":
            if args.source == "506":
                return _import_506(args)
            raise AssertionError(f"unknown import source: {args.source!r}")
        if args.command == "budget":
            return _budget(args)
        raise AssertionError(f"unknown command: {args.command!r}")
    except BoothReviewError as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
