"""CLI handlers for the MLB-only collection commands, and the D-14 windows file.

`collect retrosheet`, `import relay` and `collect statsapi` live here; the
league-aware existing commands (ratingsref, 506, wikipedia) are extended in
cli.py. Every handler holds the vault lock, commits only the paths its source
writes, and prints counts only. MLB seasons are calendar years, never the
July-June football helpers.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from booth_review.config import HOST_POLICIES, DataPaths
from booth_review.errors import (
    BoothReviewError,
    RobotsDisallowedError,
    UnknownHostError,
    VaultStateError,
)
from booth_review.mlb.seasons import mlb_current_season
from booth_review.runtime import Runtime, build_runtime
from booth_review.sources.relay.importer import (
    DEFAULT_RELAY_DIR,
    RelayImporter,
    RelayValidationError,
)
from booth_review.sources.retrosheet.collector import (
    RetrosheetCollector,
    RetrosheetMissingAsset,
)
from booth_review.sources.statsapi.collector import (
    STATSAPI_HOST,
    STATSAPI_SEASON,
    StatsApiCollector,
    StatsApiRefused,
    plan_dates,
    statsapi_route_closed,
)
from booth_review.transport.cache import atomic_write_bytes
from booth_review.vault import batch_message

MLB_RR_WINDOWS_FILE = "ledger/mlb_rr_windows.json"
MLB_RR_WINDOWS_MISSING = "run booth-review mlb rr-backfill first"
MLB_FIRST_SEASON = 2014
STATSAPI_MAX_REQUESTS_DEFAULT = 1
RELAY_SEASON_DEFAULT = 2026

_SEASON_SPEC_RE = re.compile(r"^\d{4}(-\d{4})?$")

Windows = list[tuple[date, date]]
CommitPaths = Mapping[str, tuple[str, ...]]


# -- D-14 windows file ------------------------------------------------------------------


def load_mlb_rr_windows(paths: DataPaths) -> Windows | None:
    """The stored D-14 windows, or None when the file is absent.

    Raises VaultStateError when the file is malformed, unsorted or overlapping.
    """
    path = paths.vault / MLB_RR_WINDOWS_FILE
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        raw = data["windows"]
        windows: Windows = [(date.fromisoformat(a), date.fromisoformat(b)) for a, b in raw]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise VaultStateError("mlb_rr_windows.json is not a valid windows file") from exc
    for index, (start, end) in enumerate(windows):
        if start > end:
            raise VaultStateError(f"mlb_rr_windows.json window {index} ends before it starts")
        if index and start <= windows[index - 1][1]:
            raise VaultStateError("mlb_rr_windows.json windows are unsorted or overlap")
    return windows


def write_mlb_rr_windows(paths: DataPaths, windows: Windows) -> str:
    """Atomically write the windows file; returns its vault-relative path."""
    for index, (start, end) in enumerate(windows):
        if start > end or (index and start <= windows[index - 1][1]):
            raise VaultStateError("windows must be sorted, non-overlapping and ordered")
    body = {"windows": [[a.isoformat(), b.isoformat()] for a, b in windows]}
    atomic_write_bytes(
        paths.vault / MLB_RR_WINDOWS_FILE,
        (json.dumps(body, indent=2) + "\n").encode("utf-8"),
    )
    return MLB_RR_WINDOWS_FILE


def clip_windows(windows: Windows, start: date, end: date) -> Windows:
    """Intersect stored windows with [start, end]."""
    out: Windows = []
    for w_start, w_end in windows:
        lo, hi = max(w_start, start), min(w_end, end)
        if lo <= hi:
            out.append((lo, hi))
    return out


# -- season spec ------------------------------------------------------------------------


def mlb_season_ceiling() -> int:
    return mlb_current_season(datetime.now(UTC).date())


def parse_mlb_season_spec(text: str) -> list[int]:
    """ "2026" or "2014-2025" as inclusive calendar-year seasons."""
    if not _SEASON_SPEC_RE.match(text):
        raise argparse.ArgumentTypeError(f"invalid season spec: {text!r}")
    start_text, _, end_text = text.partition("-")
    start = int(start_text)
    end = int(end_text) if end_text else start
    if start > end:
        raise argparse.ArgumentTypeError(f"season range must be ascending: {text!r}")
    ceiling = mlb_season_ceiling()
    if start < MLB_FIRST_SEASON or end > ceiling:
        raise argparse.ArgumentTypeError(
            f"season out of range [{MLB_FIRST_SEASON}, {ceiling}]: {text!r}"
        )
    return list(range(start, end + 1))


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected a whole number: {text!r}") from exc
    if value < 1:
        raise argparse.ArgumentTypeError(f"expected 1 or more: {text!r}")
    return value


def _parse_date_list(text: str) -> list[date]:
    try:
        days = [date.fromisoformat(part.strip()) for part in text.split(",") if part.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected comma-separated YYYY-MM-DD: {text!r}") from exc
    if not days:
        raise argparse.ArgumentTypeError("expected at least one date")
    return days


# -- parsers ----------------------------------------------------------------------------


def add_mlb_collect_parsers(
    collect_sub: Any,
    import_sub: Any,
) -> None:
    """Register `collect retrosheet`, `collect statsapi` and `import relay`."""
    retro = collect_sub.add_parser("retrosheet", help="collect Retrosheet CSV downloads (MLB)")
    retro.add_argument("--season", type=parse_mlb_season_spec, default=None)
    retro_mode = retro.add_mutually_exclusive_group()
    retro_mode.add_argument("--index-only", action="store_true")
    retro_mode.add_argument("--list-assets", action="store_true")
    retro.add_argument("--refresh", action="store_true")
    retro.add_argument("--dry-run", action="store_true")
    retro.add_argument("--no-commit", action="store_true")

    stats = collect_sub.add_parser(
        "statsapi", help="collect MLB Stats API schedules (gated until a host policy exists)"
    )
    stats.add_argument("--season", type=int, default=STATSAPI_SEASON)
    stats.add_argument("--dates", type=_parse_date_list, required=True)
    stats.add_argument("--max-requests", type=_positive_int, default=STATSAPI_MAX_REQUESTS_DEFAULT)
    stats.add_argument("--dry-run", action="store_true")
    stats.add_argument("--no-commit", action="store_true")

    relay = import_sub.add_parser("relay", help="import the staged MLB relay crew CSV")
    relay.add_argument("--season", type=int, default=RELAY_SEASON_DEFAULT)
    relay.add_argument("--from", dest="from_dir", type=Path, default=None)
    relay.add_argument("--force", action="store_true")
    relay.add_argument("--no-commit", action="store_true")


# -- handlers ---------------------------------------------------------------------------


def _commit(
    runtime: Runtime,
    commit_paths: CommitPaths,
    *,
    action: str,
    source: str,
    label: str,
    counts: Mapping[str, int],
    skip: bool,
) -> None:
    if skip:
        return
    runtime.vault.commit_batch(
        batch_message(action, source, label, counts), paths=list(commit_paths[source])
    )


def _season_label(seasons: list[int]) -> str:
    return f"{seasons[0]}-{seasons[-1]}" if len(seasons) > 1 else str(seasons[0])


def _partial(runtime: Runtime, before: dict[str, int]) -> dict[str, int]:
    after = runtime.cache.counters
    return {
        "fetched": after["fetched"] - before["fetched"],
        "cached": after["cached"] - before["cached"],
        "failed": 0,
    }


def _guarded(
    runtime: Runtime,
    commit_paths: CommitPaths,
    *,
    source: str,
    label: str,
    skip_commit: bool,
    run: Callable[[], dict[str, int]],
) -> tuple[dict[str, int], BoothReviewError | None]:
    """Run under the vault lock; commit what was fetched even on a stop."""
    before = dict(runtime.cache.counters)
    with runtime.vault.lock():
        try:
            counts = run()
        except (RobotsDisallowedError, UnknownHostError) as exc:
            counts = _partial(runtime, before)
            _commit(
                runtime,
                commit_paths,
                action="collect",
                source=source,
                label=label,
                counts=counts,
                skip=skip_commit,
            )
            return counts, exc
        except BaseException:
            _commit(
                runtime,
                commit_paths,
                action="collect",
                source=source,
                label=label,
                counts=_partial(runtime, before),
                skip=skip_commit,
            )
            raise
        _commit(
            runtime,
            commit_paths,
            action="collect",
            source=source,
            label=label,
            counts=counts,
            skip=skip_commit,
        )
    return counts, None


def run_collect_retrosheet(args: argparse.Namespace, commit_paths: CommitPaths) -> int:
    runtime = build_runtime(with_budget=False)
    try:
        collector = RetrosheetCollector(runtime.cache, runtime.paths)
        if args.list_assets:
            assets = collector.assets_from_cache()
            if assets is None:
                print("index not cached; run collect retrosheet --index-only first")
                return 4
            kinds: dict[str, int] = {}
            for asset in assets:
                kinds[asset.kind] = kinds.get(asset.kind, 0) + 1
            print(
                f"assets {len(assets)}: " + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items()))
            )
            return 0

        seasons: list[int] = args.season or list(range(MLB_FIRST_SEASON, mlb_season_ceiling() + 1))
        label = "index" if args.index_only else _season_label(seasons)
        result: dict[str, Any] = {}

        def run() -> dict[str, int]:
            summary = collector.run(
                seasons,
                index_only=args.index_only,
                dry_run=args.dry_run,
                refresh=args.refresh,
            )
            result["summary"] = summary
            return summary.counts()

        try:
            _counts, error = _guarded(
                runtime,
                commit_paths,
                source="mlb_retrosheet",
                label=label,
                skip_commit=args.dry_run or args.no_commit,
                run=run,
            )
        except RetrosheetMissingAsset as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 4
        if error is not None:
            print(f"error: {type(error).__name__}", file=sys.stderr)
            return 4
        summary = result["summary"]
        if args.dry_run:
            print(f"planned {summary.planned}, frozen {summary.frozen}")
        else:
            print(
                f"planned {summary.planned}, fetched {summary.fetched}, cached {summary.cached}, "
                f"frozen {summary.frozen}, failed {summary.failed}"
            )
        return 4 if summary.failed else 0
    finally:
        runtime.client.close()


def run_import_relay(args: argparse.Namespace, commit_paths: CommitPaths) -> int:
    runtime = build_runtime(with_budget=False)
    try:
        importer = RelayImporter(runtime.cache, runtime.paths)
        src: Path = args.from_dir if args.from_dir is not None else DEFAULT_RELAY_DIR
        with runtime.vault.lock():
            try:
                result = importer.run(args.season, src=src, force=args.force)
            except RelayValidationError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 4
            print(
                f"relay {args.season}: rows {result.rows}, written {result.written}, "
                f"skipped_existing {result.skipped_existing}, "
                f"changed_without_force {result.changed_without_force}, "
                f"problems {result.problems}"
            )
            if result.changed_without_force:
                print("the staged file differs from the vault copy; use --force to overwrite")
            _commit(
                runtime,
                commit_paths,
                action="import",
                source="mlb_relay",
                label=str(args.season),
                counts=result.counts(),
                skip=args.no_commit,
            )
        return 4 if result.has_problems else 0
    finally:
        runtime.client.close()


def run_collect_statsapi(args: argparse.Namespace, commit_paths: CommitPaths) -> int:
    if args.season != STATSAPI_SEASON:
        print(f"error: the Stats API pass covers season {STATSAPI_SEASON} only", file=sys.stderr)
        return 2
    try:
        requests = plan_dates(args.dates, max_requests=args.max_requests)
    except (ValueError, BoothReviewError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.dry_run:
        for req in requests:
            print(req.url)
        print(f"planned {len(requests)}")
        return 0
    if STATSAPI_HOST not in HOST_POLICIES:
        print(
            f"error: host {STATSAPI_HOST} is not enabled; see plan 09-28 checkpoint "
            "(nothing was sent)",
            file=sys.stderr,
        )
        return 3
    runtime = build_runtime(with_budget=False)
    try:
        if statsapi_route_closed(runtime.paths):
            print(
                "error: statsapi refused an earlier request; the route is closed "
                "(nothing was sent)",
                file=sys.stderr,
            )
            return 3
        collector = StatsApiCollector(runtime.cache, runtime.paths)
        result: dict[str, Any] = {}

        def run() -> dict[str, int]:
            summary = collector.run(requests)
            result["summary"] = summary
            return summary.counts()

        try:
            _counts, error = _guarded(
                runtime,
                commit_paths,
                source="mlb_statsapi",
                label=str(args.season),
                skip_commit=args.no_commit,
                run=run,
            )
        except StatsApiRefused as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 4
        if error is not None:
            print(f"error: {type(error).__name__}", file=sys.stderr)
            return 4
        summary = result["summary"]
        print(f"planned {summary.planned}, fetched {summary.fetched}, cached {summary.cached}")
        return 0
    finally:
        runtime.client.close()
