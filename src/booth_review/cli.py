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
from typing import Any, cast
from urllib.parse import urlsplit

from booth_review.audit.completeness import (
    SOURCES,
    CompletenessReport,
    build_completeness,
    write_completeness,
)
from booth_review.audit.freeze import FreezeResult, Waiver, freeze_seasons, parse_waiver
from booth_review.audit.overrides import (
    TELECASTS,
    check_overrides_exist,
    release_problems,
    safe_loader_message,
)
from booth_review.build import combined as build_combined
from booth_review.build import sample as build_sample
from booth_review.build.pipeline import BuildOutcome, run_build
from booth_review.build.site_assembly import (
    SiteBuildResult,
    assemble_site,
    docs_dir,
    fixture_path,
    load_mlb_site_payload,
    load_nfl_site_payload,
    mlb_fixture_path,
    mlb_site_enabled,
    nfl_fixture_path,
    nfl_site_enabled,
    site_source_dir,
)
from booth_review.config import CFBD_FLOOR_DEFAULT, DataPaths, load_cfbd_key
from booth_review.deploy.publish import SUBDIR_DEFAULT, publish_site
from booth_review.errors import (
    BoothReviewError,
    FreezeRefusedError,
    ReferenceTableError,
    RobotsDisallowedError,
    RobotsUnavailableError,
    SiteBuildError,
    UnknownHostError,
)
from booth_review.job.attention import build_attention_body, split_reminders
from booth_review.job.reminders import current_cfb_week
from booth_review.job.runner import (
    EXIT_NOTHING_DUE,
    JOB_CFBD_MAX_CALLS,
    JOB_CFBD_SCHEDULE_MAX_CALLS,
    JobRunResult,
    ScheduledJob,
)
from booth_review.mlb.collect_cli import (
    MLB_RR_WINDOWS_MISSING,
    add_mlb_collect_parsers,
    clip_windows,
    load_mlb_rr_windows,
    mlb_season_ceiling,
    run_collect_retrosheet,
    run_collect_statsapi,
    run_import_relay,
)
from booth_review.mlb.commands import add_mlb_parser, run_mlb_command
from booth_review.mlb.constants import MLB_REFRESH_CAP_DEFAULT
from booth_review.mlb.seasons import mlb_season_window
from booth_review.nfl.commands import add_nfl_parser, run_nfl_command
from booth_review.people import review as people_review
from booth_review.reference import reference_dir
from booth_review.resolve import diagnose as resolve_diagnose
from booth_review.resolve import network_diagnose
from booth_review.runtime import Runtime, build_runtime
from booth_review.seasons import season_of, season_window
from booth_review.sources.aa.collector import AaCollector
from booth_review.sources.aa.feed import (
    AA_FEED_CANDIDATES,
    FeedNotVerifiedError,
    FeedStatusError,
    check_week,
    load_feed_state,
    verify_feed,
    week_key,
)
from booth_review.sources.base import BatchSummary, run_requests
from booth_review.sources.cfbd.collector import ENDPOINTS, CfbdCollector
from booth_review.sources.cfbd.parser import parse_games
from booth_review.sources.espnpr.importer import (
    LISTING_MESSAGE,
    EspnPrImporter,
    EspnPrImportResult,
)
from booth_review.sources.gapcollect import MAX_REQUESTS_DEFAULT, RequestBudget
from booth_review.sources.known_disagreements import (
    KNOWN_FILE,
    POST_SOURCES,
    PostSource,
    import_known,
)
from booth_review.sources.nflverse.collector import NflverseCollector
from booth_review.sources.policy import (
    POLICY_LEDGER,
    PolicyCheck,
    PolicyChecker,
    PolicyRobotsError,
    PolicySource,
    append_policy_check,
    policy_fresh,
    robots_fresh,
    robots_guard,
)
from booth_review.sources.ratingsref.collector import (
    FIRST_SEASON,
    NFL_REFRESH_CAP_DEFAULT,
    REFRESH_CAP_DEFAULT,
    RatingsRefCollector,
    RefreshSummary,
)
from booth_review.sources.ratingsref.sitemap import parse_sitemap, select_entries
from booth_review.sources.smw.chart_order import parse_chart_order
from booth_review.sources.smw.diff import (
    SmwMergeError,
    diff_passes,
    load_pass_dir,
    load_resolutions,
    merge_rows,
    write_diff_csv,
    write_rows_csv,
)
from booth_review.sources.smw.importer import (
    DEFAULT_INCOMING_DIR as SMW_DEFAULT_ROOT,
)
from booth_review.sources.smw.importer import (
    SmwImporter,
    SmwImportResult,
    list_chart_pngs,
    season_dir,
)
from booth_review.sources.sports506.collector import Sports506Collector
from booth_review.sources.sports506.importer import (
    MLB_PROFILE,
    NFL_PROFILE,
    ImportResult,
    PageProfile,
    Sports506Importer,
    inspect_folder,
)
from booth_review.sources.tvrg.collector import TvrgCollector
from booth_review.sources.wikipedia.collector import WikipediaCollector
from booth_review.sources.wikipedia.mlb_collector import MlbWikipediaCollector
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
from booth_review.transport.budget import BudgetSummary, CfbdBudget, InfoSnapshot
from booth_review.transport.cache import atomic_write_bytes
from booth_review.transport.types import FetchResponse
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


def parse_season_spec_any_league(text: str) -> list[int]:
    """A season spec checked only against the loosest ceiling (the calendar year);
    `_check_league_ceiling` then applies the league's own ceiling after parsing.
    """
    if not _SEASON_SPEC_RE.match(text):
        raise argparse.ArgumentTypeError(f"invalid season spec: {text!r}")
    start_text, _, end_text = text.partition("-")
    start = int(start_text)
    end = int(end_text) if end_text else start
    if start > end:
        raise argparse.ArgumentTypeError(f"season range must be ascending: {text!r}")
    ceiling = max(_current_season_ceiling(), mlb_season_ceiling())
    if start < _MIN_SEASON or end > ceiling:
        raise argparse.ArgumentTypeError(
            f"season out of range [{_MIN_SEASON}, {ceiling}]: {text!r}"
        )
    return list(range(start, end + 1))


def _check_league_ceiling(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Re-apply the football (July-June) ceiling to cfb/nfl; MLB uses calendar years."""
    seasons = getattr(args, "season", None)
    league = getattr(args, "league", None)
    if not isinstance(seasons, list) or league is None or league == "mlb":
        return
    ceiling = _current_season_ceiling()
    if max(seasons) > ceiling:
        parser.error(
            f"argument --season: season out of range [{_MIN_SEASON}, {ceiling}]: "
            f"{_season_text(seasons)!r}"
        )


def _season_text(seasons: list[int]) -> str:
    return f"{seasons[0]}-{seasons[-1]}" if len(seasons) > 1 else str(seasons[0])


def _parse_date(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid date (expected YYYY-MM-DD): {text!r}") from exc


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected a whole number: {text!r}") from exc
    if value < 1:
        raise argparse.ArgumentTypeError(f"expected 1 or more: {text!r}")
    return value


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
    window_group.add_argument("--season", type=parse_season_spec_any_league)
    window_group.add_argument("--from-date", type=_parse_date)
    prr.add_argument("--to-date", type=_parse_date)
    mode_group = prr.add_mutually_exclusive_group()
    mode_group.add_argument("--dry-run", action="store_true")
    mode_group.add_argument("--sitemap-only", action="store_true")
    prr.add_argument("--no-commit", action="store_true")
    prr.add_argument("--league", choices=("cfb", "nfl", "mlb"), default="cfb")

    pnflverse = collect_sub.add_parser("nflverse", help="collect nflverse schedules and pbp")
    pnflverse.add_argument(
        "--season", type=parse_season_spec, default=f"2014-{_current_season_ceiling()}"
    )
    nflverse_scope = pnflverse.add_mutually_exclusive_group()
    nflverse_scope.add_argument("--schedules-only", action="store_true")
    nflverse_scope.add_argument("--pbp-only", action="store_true")
    pnflverse.add_argument("--refresh-schedules", action="store_true")
    pnflverse.add_argument("--dry-run", action="store_true")
    pnflverse.add_argument("--no-commit", action="store_true")

    pwiki = collect_sub.add_parser(
        "wikipedia", help="collect Wikipedia NFL season articles or MLB postseason articles"
    )
    pwiki.add_argument("--league", choices=("nfl", "mlb"), default="nfl")
    pwiki.add_argument("--season", required=True, type=parse_season_spec_any_league)
    pwiki.add_argument("--lists", action="store_true", help="MLB only: also the list pages")
    pwiki.add_argument(
        "--stadiums",
        action="store_true",
        help="NFL only: the stadium articles for map coordinates",
    )
    pwiki.add_argument("--refresh", action="store_true")
    pwiki.add_argument("--dry-run", action="store_true")
    pwiki.add_argument("--no-commit", action="store_true")

    for key, label in (("tvrg", "The TV Ratings Guide"), ("aa", "Awful Announcing")):
        psecond = collect_sub.add_parser(
            key,
            help=f"04.19 D-10/D-11: {label} policy re-check, or the gap-only data pass (--season)",
        )
        psecond.add_argument(
            "--season",
            type=parse_season_spec,
            help="data pass for 2021-2024 seasons: only pages that can fill a remaining gap",
        )
        psecond.add_argument("--dry-run", action="store_true")
        psecond.add_argument(
            "--max-requests",
            type=_positive_int,
            default=MAX_REQUESTS_DEFAULT,
            help=f"cap on new requests across the run (default {MAX_REQUESTS_DEFAULT})",
        )
        psecond.add_argument(
            "--policy-check",
            action="store_true",
            help="fetch robots.txt, the policy page(s) and one index sample; ledger the result",
        )
        psecond.add_argument(
            "--confirm-terms",
            action="store_true",
            help="record that the user read the terms the latest --policy-check fetched and "
            "they allow collection (run alone, after a robots-ok check from the last 30 days)",
        )
        psecond.add_argument("--no-commit", action="store_true")
        if key == "aa":
            psecond.add_argument(
                "--feed",
                action="store_true",
                help="Phase 25: check AA's schedules feed for this week's CFB "
                "announcing-schedule post link (link only)",
            )
            psecond.add_argument(
                "--verify",
                choices=sorted(AA_FEED_CANDIDATES),
                help="with --feed: one request to verify that candidate feed carries the posts",
            )
        else:
            psecond.set_defaults(feed=False, verify=None)

    pcfbd = collect_sub.add_parser("cfbd", help="collect CFBD season data or the venue list")
    cfbd_target = pcfbd.add_mutually_exclusive_group(required=True)
    cfbd_target.add_argument("--season", type=parse_season_spec)
    cfbd_target.add_argument(
        "--venues",
        action="store_true",
        help="collect the CFBD venue list once (no season; counted against the budget)",
    )
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
    prefresh.add_argument("--cap", "--max-refetch", dest="cap", type=int, default=None)
    prefresh.add_argument("--league", choices=("cfb", "nfl", "mlb"), default="cfb")
    prefresh.add_argument("--dry-run", action="store_true")
    prefresh.add_argument("--no-commit", action="store_true")

    import_cmd = sub.add_parser("import", help="import hand-saved source pages into the vault")
    import_sub = import_cmd.add_subparsers(dest="source", required=True)

    p506imp = import_sub.add_parser("506", help="import hand-saved 506 Sports week pages")
    p506imp.add_argument("--season", required=True, type=parse_season_spec_any_league)
    p506imp.add_argument("--from", dest="from_dir", type=Path, default=None)
    p506imp.add_argument("--force", action="store_true")
    p506imp.add_argument("--no-commit", action="store_true")
    p506imp.add_argument("--league", choices=("cfb", "nfl", "mlb"), default="cfb")
    p506imp.add_argument(
        "--inspect",
        action="store_true",
        help="MLB only: report each saved page's layout and counts; imports nothing",
    )

    add_mlb_collect_parsers(collect_sub, import_sub)

    psmwimp = import_sub.add_parser(
        "smw", help="import hand-saved Sports Media Watch charts and their transcriptions"
    )
    psmwimp.add_argument("--season", required=True, type=parse_season_spec)
    psmwimp.add_argument("--from", dest="from_dir", type=Path, default=None)
    psmwimp.add_argument("--force", action="store_true")
    psmwimp.add_argument("--no-commit", action="store_true")

    pespnprimp = import_sub.add_parser(
        "espnpr",
        help="import hand-saved ESPN Press Room pages (04.19 D-12; the site is never fetched)",
    )
    pespnprimp.add_argument("--from", dest="from_dir", type=Path, default=None)
    pespnprimp.add_argument("--force", action="store_true")
    pespnprimp.add_argument("--no-commit", action="store_true")

    pknownimp = import_sub.add_parser(
        "known",
        help="import a hand-written TVRG, AA or ESPN PR known-disagreements file (04.19 D-02)",
    )
    pknownimp.add_argument("--source", dest="known_source", required=True, choices=POST_SOURCES)
    pknownimp.add_argument("--season", required=True, type=int)
    pknownimp.add_argument("--from", dest="from_file", required=True, type=Path)
    pknownimp.add_argument("--force", action="store_true")
    pknownimp.add_argument("--no-commit", action="store_true")

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
    audit_overrides = audit_sub.add_parser(
        "overrides",
        help="release pre-flight: every crew override targets a main telecast in the last build",
    )
    audit_overrides.add_argument(
        "--release",
        action="store_true",
        help="also require the vault to match its origin with its telecasts table committed",
    )
    audit_overrides.add_argument("--vault", type=Path, help="vault working copy (default: env)")
    audit_overrides.add_argument(
        "--reference", type=Path, help="reference directory (default: env)"
    )

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
    job_run.add_argument(
        "--nfl-rr-cap",
        type=int,
        default=NFL_REFRESH_CAP_DEFAULT,
        help="Ratings Reference NFL re-fetch cap per run, separate from --rr-cap (999.4 D-09)",
    )
    job_run.add_argument(
        "--max-cfbd-calls",
        type=int,
        default=None,
        help=f"CFBD call cap (default {JOB_CFBD_MAX_CALLS}, "
        f"{JOB_CFBD_SCHEDULE_MAX_CALLS} on a schedule-only run)",
    )
    job_run.add_argument(
        "--mode",
        choices=["auto", "full", "schedule", "rebuild"],
        default="auto",
        help="auto picks full or schedule-only from the clock; schedule re-pulls only "
        "CFBD games/media and the nflverse schedule; rebuild collects nothing (D-17)",
    )
    job_run.add_argument("--attention-out", type=Path, default=None)
    job_run.add_argument(
        "--reminders-out",
        type=Path,
        default=None,
        help="hand-save reminder lines, written apart so the workflow comments them",
    )
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

    add_nfl_parser(sub)
    add_mlb_parser(sub)

    site_cmd = sub.add_parser(
        "site", help="D-14: assemble dist/site/ from site/, site-data.json, and rendered pages"
    )
    site_cmd.add_argument(
        "--fixture",
        action="store_true",
        help="use the synthetic contract fixture instead of the vault's processed/site-data.json",
    )
    site_cmd.add_argument(
        "--nfl",
        action="store_true",
        help="include the NFL sport switch and nfl-data.json "
        "(also on when NFL_SITE_ENABLED is exactly true)",
    )
    site_cmd.add_argument(
        "--mlb",
        action="store_true",
        help="include the MLB sport switch entry and mlb-data.json "
        "(also on when MLB_SITE_ENABLED is exactly true)",
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

    review_smw_diff = review_sub.add_parser(
        "smw-diff", help="diff two SMW transcription passes, or self-check one (04.19 D-01)"
    )
    review_smw_diff.add_argument("--season", required=True, type=int)
    review_smw_diff.add_argument("--root", type=Path, default=SMW_DEFAULT_ROOT)
    review_smw_diff.add_argument("--check-pass", choices=("a", "b"), default=None)

    review_nfl_stadiums = review_sub.add_parser(
        "nfl-stadiums",
        help="draft nfl_stadium_locations rows from cached stadium articles (offline)",
    )
    review_nfl_stadiums.add_argument("--out", type=Path, default=Path("data/incoming/nfl-stadiums"))

    review_smw_merge = review_sub.add_parser(
        "smw-merge", help="merge SMW transcription passes and resolutions into rows.csv"
    )
    review_smw_merge.add_argument("--season", required=True, type=int)
    review_smw_merge.add_argument("--root", type=Path, default=SMW_DEFAULT_ROOT)

    return parser


# -- shared run/commit/print helpers -----------------------------------------------


def _partial_counts(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    return {
        "fetched": after["fetched"] - before["fetched"],
        "cached": after["cached"] - before["cached"],
        "not_modified": after["not_modified"] - before["not_modified"],
        "failed": 0,
    }


_MESSAGE_COUNT_KEYS = ("fetched", "cached", "not_modified", "failed")
_ROBOTS_AND_REQUEST_LEDGER = ("raw/_robots", "ledger/requests.jsonl")

# The vault paths each collect source writes. A collect commit stages only these,
# so an unrelated untracked file elsewhere in the vault is never swept in (T-02-02).
_COLLECT_PATHS: dict[str, tuple[str, ...]] = {
    "sports506": ("raw/sports506", *_ROBOTS_AND_REQUEST_LEDGER),
    "cfbd": ("raw/cfbd", "ledger/cfbd_ledger.jsonl", *_ROBOTS_AND_REQUEST_LEDGER),
    "ratingsref": (
        "raw/ratingsref",
        "ledger/rr_lastmod.json",
        "ledger/rr_lastmod.jsonl",
        *_ROBOTS_AND_REQUEST_LEDGER,
    ),
    "nfl_ratingsref": (
        "raw/nfl/ratingsref",
        "raw/ratingsref/sitemap",
        "ledger/rr_lastmod.json",
        "ledger/rr_lastmod.jsonl",
        *_ROBOTS_AND_REQUEST_LEDGER,
    ),
    "mlb_ratingsref": (
        "raw/mlb/ratingsref",
        "raw/ratingsref/sitemap",
        "ledger/rr_lastmod.json",
        "ledger/rr_lastmod.jsonl",
        "ledger/mlb_rr_windows.json",
        *_ROBOTS_AND_REQUEST_LEDGER,
    ),
    "mlb_sports506": ("raw/mlb/sports506", "ledger/requests.jsonl"),
    "mlb_wikipedia": ("raw/mlb/wikipedia", *_ROBOTS_AND_REQUEST_LEDGER),
    "mlb_retrosheet": ("raw/mlb/retrosheet", *_ROBOTS_AND_REQUEST_LEDGER),
    "mlb_relay": ("raw/mlb/relay", "ledger/requests.jsonl"),
    "mlb_statsapi": ("raw/mlb/statsapi", *_ROBOTS_AND_REQUEST_LEDGER),
    "nfl_sports506": ("raw/nfl/sports506", "ledger/requests.jsonl"),
    "nfl_nflverse": (
        "raw/nfl/nflverse",
        "ledger/nfl_nflverse_assets.jsonl",
        *_ROBOTS_AND_REQUEST_LEDGER,
    ),
    "nfl_wikipedia": ("raw/nfl/wikipedia", *_ROBOTS_AND_REQUEST_LEDGER),
    "tvrg": ("raw/tvrg", POLICY_LEDGER, *_ROBOTS_AND_REQUEST_LEDGER),
    "aa": ("raw/aa", POLICY_LEDGER, *_ROBOTS_AND_REQUEST_LEDGER),
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
            # MLB summaries add scope-skip counts; the message keeps to the four
            # standard ones so it stays within the 120-character cap.
            counts = {key: counts[key] for key in _MESSAGE_COUNT_KEYS if key in counts}
            runtime.vault.commit_batch(
                batch_message(action, source, season_label, counts),
                paths=list(_COLLECT_PATHS[source]),
            )
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


_RR_SOURCE_KEYS = {"cfb": "ratingsref", "nfl": "nfl_ratingsref", "mlb": "mlb_ratingsref"}


def _rr_source_key(league: str) -> str:
    return _RR_SOURCE_KEYS[league]


def _mlb_windows_or_exit(args: argparse.Namespace) -> int | None:
    """D-14: exit 2 before any runtime or request when the windows file is absent."""
    if load_mlb_rr_windows(DataPaths.from_env()) is None:
        print(f"error: {MLB_RR_WINDOWS_MISSING}", file=sys.stderr)
        return 2
    return None


def _collect_ratingsref(args: argparse.Namespace) -> int:
    if args.league == "mlb":
        if args.sitemap_only:
            print(
                "error: --sitemap-only is shared by both leagues; run it without --league",
                file=sys.stderr,
            )
            return 2
        early = _mlb_windows_or_exit(args)
        if early is not None:
            return early
    runtime = build_runtime(with_budget=False)
    try:
        league = args.league
        source_key = _rr_source_key(league)
        if league in ("nfl", "mlb") and args.sitemap_only:
            print(
                "error: --sitemap-only is shared by both leagues; run it without --league",
                file=sys.stderr,
            )
            return 2
        collector = RatingsRefCollector(
            runtime.cache, runtime.paths, lock=runtime.vault.lock, league=league
        )

        if args.season is not None:
            seasons = args.season
            window_of = mlb_season_window if league == "mlb" else season_window
            start = window_of(min(seasons))[0]
            end = window_of(max(seasons))[1]
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

        run_kwargs: dict[str, Any] = {}
        if league == "mlb":
            stored = load_mlb_rr_windows(runtime.paths)
            assert stored is not None
            run_kwargs["windows"] = clip_windows(stored, start, end)
        summary = _run_and_commit(
            runtime,
            functools.partial(collector.run, start, end, dry_run=args.dry_run, **run_kwargs),
            action="collect",
            source=source_key,
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
        runtime.vault.commit_batch(
            batch_message("collect", "ratingsref", season_label, counts),
            paths=list(_COLLECT_PATHS["ratingsref"]),
        )

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
    if args.league == "mlb":
        early = _mlb_windows_or_exit(args)
        if early is not None:
            return early
    runtime = build_runtime(with_budget=False)
    try:
        league = args.league
        source_key = _rr_source_key(league)
        collector = RatingsRefCollector(
            runtime.cache, runtime.paths, lock=runtime.vault.lock, league=league
        )
        cap = args.cap
        if cap is None:
            cap = {
                "cfb": REFRESH_CAP_DEFAULT,
                "nfl": NFL_REFRESH_CAP_DEFAULT,
                "mlb": MLB_REFRESH_CAP_DEFAULT,
            }[league]
        current_season = mlb_season_ceiling() if league == "mlb" else _current_season_ceiling()
        season_label = f"{FIRST_SEASON}-{current_season}"
        refresh_kwargs: dict[str, Any] = {}
        if league == "mlb":
            refresh_kwargs["windows"] = load_mlb_rr_windows(runtime.paths)

        before = dict(runtime.cache.counters)
        summary: RefreshSummary | None = None
        try:
            summary = collector.refresh(
                current_season=current_season, cap=cap, dry_run=args.dry_run, **refresh_kwargs
            )
        finally:
            if not args.dry_run and not args.no_commit:
                counts = (
                    summary.counts()
                    if summary is not None
                    else _partial_refresh_counts(before, runtime.cache.counters)
                )
                runtime.vault.commit_batch(
                    batch_message("refresh", source_key, season_label, counts),
                    paths=list(_COLLECT_PATHS[source_key]),
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


# -- collect nflverse / wikipedia ----------------------------------------------------------


def _commit_nfl(
    runtime: Runtime,
    source_key: str,
    season_label: str,
    counts: dict[str, int],
    args: argparse.Namespace,
) -> None:
    if args.dry_run or args.no_commit:
        return
    runtime.vault.commit_batch(
        batch_message("collect", source_key, season_label, counts),
        paths=list(_COLLECT_PATHS[source_key]),
    )


def _collect_nflverse(args: argparse.Namespace) -> int:
    runtime = build_runtime(with_budget=False)
    try:
        token = os.environ.get("GITHUB_TOKEN") or None
        collector = NflverseCollector(
            runtime.cache, runtime.paths, lock=runtime.vault.lock, token=token
        )
        seasons: list[int] = args.season
        label = f"{seasons[0]}-{seasons[-1]}" if len(seasons) > 1 else str(seasons[0])
        totals = {"fetched": 0, "cached": 0, "not_modified": 0, "failed": 0}
        before = dict(runtime.cache.counters)
        error: BoothReviewError | None = None
        try:
            if not args.pbp_only:
                sched = collector.run_schedules(
                    refresh=args.refresh_schedules, dry_run=args.dry_run
                )
                for key, value in sched.counts().items():
                    totals[key] += value
                if args.dry_run:
                    print(f"schedules: planned {sched.planned}, new {len(sched.new_urls)}")
            if not args.schedules_only:
                pbp = collector.run_pbp(seasons, dry_run=args.dry_run)
                counts = pbp.counts()
                totals["fetched"] += counts["fetched"]
                totals["cached"] += counts["unchanged"]
                totals["not_modified"] += counts["not_modified"]
                totals["failed"] += counts["failed"]
                if args.dry_run:
                    print(
                        f"pbp: planned {pbp.planned}, unchanged {pbp.unchanged}, "
                        f"frozen {pbp.frozen}, missing_assets {len(pbp.missing_assets)}"
                    )
        except (RobotsDisallowedError, UnknownHostError) as exc:
            error = exc
            totals = _partial_counts(before, runtime.cache.counters)
        except BaseException:
            _commit_nfl(
                runtime,
                "nfl_nflverse",
                label,
                _partial_counts(before, runtime.cache.counters),
                args,
            )
            raise
        _commit_nfl(runtime, "nfl_nflverse", label, totals, args)
        if error is not None:
            print(f"error: {type(error).__name__}", file=sys.stderr)
            return 4
        if not args.dry_run:
            print(
                f"fetched {totals['fetched']}, cached {totals['cached']}, "
                f"not_modified {totals['not_modified']}, failed {totals['failed']}"
            )
        return 4 if totals["failed"] else 0
    finally:
        runtime.client.close()


def _collect_wikipedia(args: argparse.Namespace) -> int:
    mlb = args.league == "mlb"
    if args.lists and not mlb:
        print("error: --lists is MLB only", file=sys.stderr)
        return 2
    if args.stadiums and mlb:
        print("error: --stadiums is NFL only", file=sys.stderr)
        return 2
    runtime = build_runtime(with_budget=False)
    try:
        collector = (
            MlbWikipediaCollector(runtime.cache) if mlb else WikipediaCollector(runtime.cache)
        )
        source_key = "mlb_wikipedia" if mlb else "nfl_wikipedia"
        seasons: list[int] = args.season
        label = f"{seasons[0]}-{seasons[-1]}" if len(seasons) > 1 else str(seasons[0])
        current = mlb_season_ceiling() if mlb else _current_season_ceiling()
        before = dict(runtime.cache.counters)
        summaries: list[BatchSummary] = []
        error: BoothReviewError | None = None
        try:
            for season in seasons:
                # A re-read applies only to the current NFL season; completed
                # seasons are served from cache.
                refresh = args.refresh and season >= current
                if isinstance(collector, MlbWikipediaCollector):
                    summaries.extend(
                        collector.run(
                            [season],
                            lists=args.lists and season == seasons[-1],
                            refresh=refresh,
                            dry_run=args.dry_run,
                        )
                    )
                else:
                    summaries.extend(collector.run([season], refresh=refresh, dry_run=args.dry_run))
            if args.stadiums and isinstance(collector, WikipediaCollector):
                summaries.append(collector.run_stadiums(refresh=args.refresh, dry_run=args.dry_run))
        except (RobotsDisallowedError, UnknownHostError) as exc:
            error = exc
        except BaseException:
            _commit_nfl(
                runtime,
                source_key,
                label,
                _partial_counts(before, runtime.cache.counters),
                args,
            )
            raise
        counts = (
            _partial_counts(before, runtime.cache.counters)
            if error is not None
            else {
                key: sum(s.counts()[key] for s in summaries)
                for key in ("fetched", "cached", "not_modified", "failed")
            }
        )
        _commit_nfl(runtime, source_key, label, counts, args)
        if error is not None:
            print(f"error: {type(error).__name__}", file=sys.stderr)
            return 4
        if args.dry_run:
            print(
                f"planned {sum(s.planned for s in summaries)}, "
                f"cached {sum(s.cached for s in summaries)}, "
                f"new {sum(len(s.new_urls) for s in summaries)}"
            )
        else:
            print(
                f"fetched {counts['fetched']}, cached {counts['cached']}, "
                f"not_modified {counts['not_modified']}, failed {counts['failed']}"
            )
        return 4 if counts["failed"] else 0
    finally:
        runtime.client.close()


# -- collect tvrg / aa (04.19 D-10 policy re-check) -----------------------------------


def _earliest_gap_month(paths: DataPaths) -> tuple[int, int] | None:
    """The month of the earliest 2021-2024 date SMW left unrated (D-11), offline."""
    from booth_review.build.gaps import earliest_gap_month, remaining_gap_dates
    from booth_review.build.tables import assemble_tables

    # Every season, as `booth-review build` assembles them: a season subset trips
    # the crew-override check for overrides that name other seasons.
    tables = assemble_tables(paths, reference_dir())
    return earliest_gap_month(remaining_gap_dates(tables))


def _confirm_terms_only(source: PolicySource, args: argparse.Namespace) -> int:
    paths = DataPaths.from_env()
    vault = VaultRepo(paths.vault)
    vault.check()
    fresh = robots_fresh(paths, source, datetime.now(UTC))
    if fresh is None:
        print(
            f"error: no robots-ok policy check for {source} in the last 30 days; "
            "run --policy-check first",
            file=sys.stderr,
        )
        return 4
    with vault.lock():
        append_policy_check(
            paths,
            PolicyCheck(
                source=source,
                checked_at=fresh.checked_at,
                robots_ok=True,
                crawl_delay=fresh.crawl_delay,
                terms_ok=True,
            ),
        )
    if not args.no_commit:
        vault.commit_batch(
            batch_message("collect", source, "policy", {"confirmed": 1}),
            paths=[POLICY_LEDGER],
        )
    print(f"{source} policy: terms confirmed 1")
    return 0


def _feed_now() -> datetime:
    return datetime.now(UTC)


def _collect_aa_feed(args: argparse.Namespace) -> int:
    """Phase 25: one verify request, or the job's week check, link-only output."""
    paths = DataPaths.from_env()
    now = _feed_now()
    if not policy_fresh(paths, "aa", now):
        print(
            "error: policy check older than 30 days or not approved; run --policy-check",
            file=sys.stderr,
        )
        return 4
    verify: str | None = args.verify
    week: tuple[int, str] | None = None
    if verify is None:
        state = load_feed_state(paths)
        if state.verified_feed_url is None:
            print("error: no verified feed; run --feed --verify schedules", file=sys.stderr)
            return 4
        week = current_cfb_week(paths, now)
        if week is None:
            print("aa feed: no current cfb week, nothing to check")
            return 0
        key = week_key(*week)
        if key in state.weeks:
            print(f"aa feed week {week[1]}: already linked {state.weeks[key]}")
            return 0
        if key in state.blind_weeks:
            print(f"aa feed week {week[1]}: plain reminder already sent, not polled")
            return 0
        if args.dry_run:
            print(f"aa feed: planned 1 request {state.verified_feed_url}")
            return 0
    elif args.dry_run:
        print(f"aa feed: planned 1 request {AA_FEED_CANDIDATES[verify]}")
        return 0

    runtime = build_runtime(with_budget=False)
    try:
        runtime.client.add_robots_listener(robots_guard("aa"))
        requests = 1
        try:
            if verify is not None:
                result = verify_feed(runtime.client, paths, verify, now)
                print(
                    f"aa feed {verify}: status {result.status}, entries {result.entries}, "
                    f"cfb schedule posts {len(result.cfb_links)}"
                )
                for url in result.cfb_links:
                    print(f"  {url}")
                for url in result.other_schedule_links:
                    print(f"  other {url}")
                if result.verified:
                    print(f"verified {result.feed_url}")
                else:
                    print("not verified; try --verify site")
                code = 0 if result.verified else 4
            else:
                assert week is not None
                check = check_week(runtime.client, paths, season=week[0], label=week[1], now=now)
                requests = 1 if check.requested else 0
                matched = check.url if check.url is not None else "none"
                print(f"aa feed week {week[1]}: status {check.status}, matched {matched}")
                code = 0
        except (
            PolicyRobotsError,
            RobotsDisallowedError,
            RobotsUnavailableError,
            UnknownHostError,
            FeedNotVerifiedError,
        ) as exc:
            print(f"error: {type(exc).__name__}", file=sys.stderr)
            return 4
        except BoothReviewError as exc:
            # A fetch, parse or status failure: the request was made and its audit row
            # was appended, so it is committed under this command's own message.
            print(f"error: {type(exc).__name__}", file=sys.stderr)
            code = 4
        except FeedStatusError as exc:
            print(f"error: {type(exc).__name__}", file=sys.stderr)
            code = 4
        if not args.no_commit:
            runtime.vault.commit_batch(
                batch_message("collect", "aa", "feed", {"requests": requests}),
                paths=[
                    "ledger/aa_feed_watch.json",
                    "ledger/requests.jsonl",
                    "raw/_robots/awfulannouncing.com",
                ],
            )
        return code
    finally:
        runtime.client.close()


def _collect_second(args: argparse.Namespace, source: PolicySource) -> int:
    if getattr(args, "feed", False):
        if args.season or args.policy_check or args.confirm_terms:
            print("error: --feed runs on its own", file=sys.stderr)
            return 2
        return _collect_aa_feed(args)
    if getattr(args, "verify", None):
        print("error: --verify needs --feed", file=sys.stderr)
        return 2
    if args.policy_check and args.confirm_terms:
        # WR-04 (D-10): the confirmation stands for terms the user has read, so it
        # can't be recorded in the run that fetches them.
        print(
            "error: run --policy-check first and read its summary, then --confirm-terms on its own",
            file=sys.stderr,
        )
        return 2
    policy_mode = args.policy_check or args.confirm_terms
    if policy_mode and args.season:
        print("error: --season runs the data pass; run --policy-check on its own", file=sys.stderr)
        return 2
    if policy_mode:
        return _collect_policy(args, source)
    if not args.season:
        print(
            f"error: {source} needs --season for the data pass, "
            "or --policy-check / --confirm-terms",
            file=sys.stderr,
        )
        return 2
    return _collect_gap_pass(args, source)


def _second_source_gaps(
    paths: DataPaths, seasons: Sequence[int]
) -> tuple[dict[int, set[date]], dict[date, set[int]]]:
    """(gap dates per season, regular-season week per date), offline (D-11).

    Only dates with an unrated telecast on a network TVRG and AA list count."""
    from booth_review.build.gaps import (
        LISTED_GAP_NETWORKS,
        regular_weeks_by_date,
        remaining_gap_dates,
    )
    from booth_review.build.tables import assemble_tables

    # Every season, as `booth-review build` assembles them (see _earliest_gap_month).
    tables = assemble_tables(paths, reference_dir())
    gaps = remaining_gap_dates(tables, seasons, networks=LISTED_GAP_NETWORKS)
    return gaps, regular_weeks_by_date(tables.games, seasons)


def _robots_guard(source: PolicySource) -> Callable[[str, FetchResponse], None]:
    """One guard for the CLI data pass and the job's feed poll (policy.robots_guard)."""
    return robots_guard(source)


def _collect_gap_pass(args: argparse.Namespace, source: PolicySource) -> int:
    seasons: list[int] = args.season
    outside = [season for season in seasons if season not in range(2021, 2025)]
    if outside:
        print(f"error: {source} covers the 2021-2024 seasons only", file=sys.stderr)
        return 2
    paths = DataPaths.from_env()
    if not policy_fresh(paths, source, datetime.now(UTC)):
        print(
            "error: policy check older than 30 days or not approved; run --policy-check",
            file=sys.stderr,
        )
        return 4
    gaps, week_of = _second_source_gaps(paths, seasons)
    runtime = build_runtime(with_budget=False)
    try:
        runtime.client.add_robots_listener(_robots_guard(source))
        collector: TvrgCollector | AaCollector = (
            TvrgCollector(runtime.cache)
            if source == "tvrg"
            else AaCollector(runtime.cache, week_of)
        )
        budget = RequestBudget(args.max_requests)
        any_failed = False
        for season in seasons:
            season_gaps = gaps.get(season, set())
            plan = collector.plan(season, season_gaps)
            cached = sum(1 for req in plan if runtime.cache.status(req) == "cached")
            print(
                f"{source} {season}: gap dates {len(season_gaps)}, planned {len(plan)} "
                f"(cached {cached}, new {len(plan) - cached}; "
                "posts are planned from cached index pages only)"
            )
            try:
                summary = _run_and_commit(
                    runtime,
                    functools.partial(
                        collector.run_season,
                        season,
                        season_gaps,
                        dry_run=args.dry_run,
                        budget=budget,
                    ),
                    action="collect",
                    source=source,
                    season_label=str(season),
                    dry_run=args.dry_run,
                    no_commit=args.no_commit,
                )
            except (
                PolicyRobotsError,
                RobotsDisallowedError,
                RobotsUnavailableError,
                UnknownHostError,
            ) as exc:
                print(f"error: {type(exc).__name__}", file=sys.stderr)
                return 4
            if args.dry_run:
                print(
                    f"planned {summary.planned}, cached {summary.cached}, "
                    f"new {len(summary.new_urls)}"
                )
            else:
                print(
                    f"fetched {summary.fetched}, cached {summary.cached}, "
                    f"not_modified {summary.not_modified}, failed {summary.failed}"
                )
                any_failed = any_failed or bool(summary.failed)
            if budget.exhausted:
                print(f"stopped: --max-requests {args.max_requests} reached")
                break
        return 4 if any_failed else 0
    finally:
        runtime.client.close()


def _collect_policy(args: argparse.Namespace, source: PolicySource) -> int:
    if not args.policy_check:
        return _confirm_terms_only(source, args)

    paths = DataPaths.from_env()
    index_month = _earliest_gap_month(paths) if source == "tvrg" else None
    runtime = build_runtime(with_budget=False)
    try:
        checker = PolicyChecker(
            runtime.cache,
            runtime.client,
            runtime.paths,
            source,
            today=datetime.now(UTC).date(),
            index_month=index_month,
        )
        before = dict(runtime.cache.counters)
        error: BoothReviewError | None = None
        outcome = None
        try:
            outcome = checker.run()
        except (
            PolicyRobotsError,
            RobotsDisallowedError,
            RobotsUnavailableError,
            UnknownHostError,
        ) as exc:
            error = exc
        except BaseException:
            if not args.no_commit:
                runtime.vault.commit_batch(
                    batch_message(
                        "collect",
                        source,
                        "policy",
                        _partial_counts(before, runtime.cache.counters),
                    ),
                    paths=list(_COLLECT_PATHS[source]),
                )
            raise

        now = datetime.now(UTC)
        if outcome is None:
            delay = error.verdict.crawl_delay if isinstance(error, PolicyRobotsError) else None
            check = PolicyCheck(source, now, robots_ok=False, crawl_delay=delay, terms_ok=None)
            counts = _partial_counts(before, runtime.cache.counters)
        else:
            summary = outcome.summary
            # terms_ok stays null: only a later `--confirm-terms` run, after the
            # user has read this summary, records it (WR-04).
            check = PolicyCheck(
                source,
                outcome.robots_checked_at or now,
                robots_ok=outcome.robots_ok,
                crawl_delay=outcome.verdict.crawl_delay if outcome.verdict else None,
                terms_ok=None,
            )
            counts = summary.counts()
        with runtime.vault.lock():
            append_policy_check(runtime.paths, check)
        if not args.no_commit:
            runtime.vault.commit_batch(
                batch_message("collect", source, "policy", counts),
                paths=list(_COLLECT_PATHS[source]),
            )

        if error is not None:
            print(f"error: {type(error).__name__}", file=sys.stderr)
            print(f"{source} policy: robots blocked, crawl-delay {check.crawl_delay or 'none'}")
            return 4
        assert outcome is not None
        verdict = outcome.verdict
        print(
            f"{source} policy: fetched {counts['fetched']}, cached {counts['cached']}, "
            f"failed {counts['failed']}; robots {'ok' if outcome.robots_ok else 'unknown'}, "
            f"crawl-delay {check.crawl_delay if check.crawl_delay is not None else 'none'}, "
            f"sitemaps {len(verdict.sitemaps) if verdict else 0}; "
            f"legal page: {outcome.legal_page}; index sample: {outcome.index_sample}; "
            f"terms_ok {'true' if check.terms_ok else 'null'}"
        )
        if not outcome.robots_ok:
            return 4
        return 4 if counts["failed"] else 0
    finally:
        runtime.client.close()


# -- collect cfbd ---------------------------------------------------------------------


def _print_cfbd_batch(summary: BatchSummary, budget: CfbdBudget, args: argparse.Namespace) -> bool:
    """Print one CFBD batch's dry-run plan or run summary; True when a URL failed."""
    if args.dry_run:
        _print_dry_run(summary, url_display=_cfbd_url_display, cfbd=True)
        remaining = budget.last_known_remaining()
        if remaining is not None:
            print(f"remaining (last known): {remaining}")
            if remaining - summary.cfbd_calls < args.floor:
                print(
                    f"warning: planned {summary.cfbd_calls} calls would drop "
                    f"remaining below the floor of {args.floor}",
                    file=sys.stderr,
                )
        return False
    _print_run_summary(summary, url_display=_cfbd_url_display)
    return bool(summary.failed_urls)


def _collect_cfbd(args: argparse.Namespace) -> int:
    if args.venues and args.endpoints is not None:
        print("--endpoints does not apply to --venues", file=sys.stderr)
        return 2
    runtime = build_runtime(
        with_budget=True, floor=args.floor, max_calls=args.max_calls, tag=args.tag
    )
    try:
        assert runtime.budget is not None
        names = args.endpoints if args.endpoints is not None else list(ENDPOINTS.keys())
        token = load_cfbd_key() if not args.dry_run else None
        collector = CfbdCollector(runtime.cache, runtime.budget, token)

        any_failed = False
        batches: list[tuple[str, Callable[[], BatchSummary]]]
        if args.venues:
            batches = [
                ("all", functools.partial(collector.run_static, ["venues"], dry_run=args.dry_run))
            ]
        else:
            batches = [
                (
                    str(season),
                    functools.partial(collector.run, season, names, dry_run=args.dry_run),
                )
                for season in args.season
            ]
        for season_label, run in batches:
            summary = _run_and_commit(
                runtime,
                run,
                action="collect",
                source="cfbd",
                season_label=season_label,
                dry_run=args.dry_run,
                no_commit=args.no_commit,
            )
            if _print_cfbd_batch(summary, runtime.budget, args):
                any_failed = True
        return 4 if any_failed else 0
    finally:
        runtime.client.close()


# -- import 506 ----------------------------------------------------------------------------


def _print_import_result(result: ImportResult) -> None:
    total = len(result.expected)
    present = total - len(result.missing)
    if result.expected_source == "nav":
        source_note = "(weeks from nav)"
    elif result.league == "mlb":
        source_note = f"(default {total} rounds)"
    else:
        source_note = "(default 18 weeks)"
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
    if result.replaced:
        print(f"replaced {len(result.replaced)}: {', '.join(result.replaced)}")
    if result.changed_without_force:
        print(
            f"changed_without_force {len(result.changed_without_force)}: "
            f"{', '.join(result.changed_without_force)} "
            "(the saved page differs from the vault copy; use --force to replace it)"
        )
    if result.unsupported_pages:
        pages = ", ".join(result.unsupported_pages)
        print(f"unsupported pages (not a week or a known round): {pages}")
    if result.out_of_scope:
        print(f"out_of_scope {result.out_of_scope} (page layout this profile does not read)")
    if result.unrecognized:
        print(f"ignored {result.unrecognized} HTML file(s) that aren't 506 week pages")


_IMPORT_506_PROFILES: dict[str, PageProfile | None] = {
    "cfb": None,
    "nfl": NFL_PROFILE,
    "mlb": MLB_PROFILE,
}
_IMPORT_506_SOURCES = {"cfb": "sports506", "nfl": "nfl_sports506", "mlb": "mlb_sports506"}
_IMPORT_506_DIRS = {
    "cfb": "raw/sports506",
    "nfl": "raw/nfl/sports506",
    "mlb": "raw/mlb/sports506",
}


def _inspect_506(args: argparse.Namespace) -> int:
    """Counts-only look at a folder of saved MLB pages; writes nothing, sends nothing."""
    profile = MLB_PROFILE
    folder = args.from_dir if args.from_dir is not None else profile.default_dir
    rows, summary = inspect_folder(profile, folder)
    for row in rows:
        print(
            f"file {row.file_index}: season {row.season}, label {row.label}, "
            f"layout {row.layout}, listings {row.listings}, non_game {row.non_game}, "
            f"crew_listed {row.crew_listed}, {row.verdict}"
        )
    print("summary: " + ", ".join(f"{k} {v}" for k, v in sorted(summary.items())))
    return 0


def _import_506(args: argparse.Namespace) -> int:
    if args.inspect:
        if args.league != "mlb":
            print("error: --inspect is MLB only (use --league mlb)", file=sys.stderr)
            return 2
        return _inspect_506(args)
    runtime = build_runtime(with_budget=False)
    try:
        league = args.league
        profile = _IMPORT_506_PROFILES[league]
        importer = (
            Sports506Importer(runtime.cache, runtime.paths, profile=profile)
            if profile is not None
            else Sports506Importer(runtime.cache, runtime.paths)
        )
        source_key = _IMPORT_506_SOURCES[league]
        vault_dir = _IMPORT_506_DIRS[league]
        incoming_dir = args.from_dir  # None: the importer's own default (D-19)

        any_problems = False
        for season in args.season:
            # D-04: hold the vault lock and commit only this season's own
            # files, so a concurrent RR refresh or another season's import
            # never races on the same working copy (T-02-02).
            with runtime.vault.lock():
                result = importer.run(season, incoming_dir=incoming_dir, force=args.force)
                _print_import_result(result)
                if league == "cfb" and result.root_pages > 0:
                    print(
                        f"warning: {result.root_pages} page(s) imported from "
                        "data/incoming/506/; move hand-saves to data/incoming/506/cfb/ "
                        "(the old folder is read through the 2026 season)"
                    )
                if league == "cfb" and result.root_shadowed:
                    print(
                        "warning: data/incoming/506/ also holds a different page for week(s) "
                        f"{', '.join(result.root_shadowed)}; "
                        "used the one in data/incoming/506/cfb/ (delete the old copy)"
                    )
                if result.has_problems:
                    any_problems = True
                if not args.no_commit:
                    message = batch_message("import", source_key, str(season), result.counts())
                    runtime.vault.commit_batch(
                        message, paths=[f"{vault_dir}/{season}", "ledger/requests.jsonl"]
                    )
        return 4 if any_problems else 0
    finally:
        runtime.client.close()


# -- import smw -----------------------------------------------------------------------------


def _print_smw_import_result(result: SmwImportResult) -> None:
    print(
        f"smw {result.season}: imported {len(result.imported)}, "
        f"skipped_existing {len(result.skipped_existing)}, "
        f"skipped_invalid {len(result.skipped_invalid)}, "
        f"changed_without_force {len(result.changed_without_force)}, "
        f"missing_charts {len(result.missing_charts)}, problems {len(result.problems)}"
    )
    for problem in result.problems:
        print(f"problem: {problem}")
    if result.changed_without_force:
        print("some files differ from the vault copy; use --force to overwrite")


def _import_smw(args: argparse.Namespace) -> int:
    runtime = build_runtime(with_budget=False)
    try:
        importer = SmwImporter(runtime.cache, runtime.paths)
        any_problems = False
        for season in args.season:
            folder = args.from_dir if args.from_dir is not None else None
            # D-04: hold the vault lock and commit only this season's own files.
            with runtime.vault.lock():
                result = importer.run(season, incoming_dir=folder, force=args.force)
                _print_smw_import_result(result)
                if result.has_problems:
                    any_problems = True
                if not args.no_commit:
                    message = batch_message("import", "smw", str(season), result.counts())
                    runtime.vault.commit_batch(
                        message, paths=[f"raw/smw/{season}", "ledger/requests.jsonl"]
                    )
        return 4 if any_problems else 0
    finally:
        runtime.client.close()


# -- import espnpr --------------------------------------------------------------------------


def _print_espnpr_import_result(result: EspnPrImportResult) -> None:
    """Counts and reasons only, never page text or file names."""
    for season in result.seasons():
        imported = [ref for ref in result.imported if ref.season == season]
        by_kind = ", ".join(
            f"{kind} {sum(ref.kind == kind for ref in imported)}"
            for kind in ("commentators", "release", "ratings")
        )
        print(
            f"espnpr {season}: imported {len(imported)} ({by_kind}), "
            f"skipped_existing {sum(r.season == season for r in result.skipped_existing)}, "
            f"changed_without_force {sum(r.season == season for r in result.changed_without_force)}"
        )
    reasons: dict[str, int] = {}
    for item in result.skipped_invalid:
        reasons[item.reason] = reasons.get(item.reason, 0) + 1
    print(
        f"imported {len(result.imported)}, skipped_existing {len(result.skipped_existing)}, "
        f"skipped_invalid {len(result.skipped_invalid)}, "
        f"changed_without_force {len(result.changed_without_force)}"
    )
    for reason, count in sorted(reasons.items()):
        print(f"skipped {count}: {reason}")
    if result.changed_without_force:
        print("some pages differ from the vault copy; use --force to overwrite")
    if result.superseded:
        print(f"--force kept the newest save; {result.superseded} older save(s) ignored")
    if result.listings:
        print(f"skipped {result.listings} {LISTING_MESSAGE}")
    if result.unrecognized:
        print(f"ignored {result.unrecognized} HTML file(s) that aren't ESPN Press Room data pages")
    for problem in result.problems:
        print(f"problem: {problem}")


def _import_espnpr(args: argparse.Namespace) -> int:
    """04.19 D-12: ESPN Press Room is hand-save only (Disney Terms of Use ban
    automated access), so no client is built here at all. Holds the vault lock
    and commits once per season, touching only raw/espnpr/<season> and the
    ledger, with a count-only message."""
    paths = DataPaths.from_env()
    vault = VaultRepo(paths.vault)
    vault.check()
    with vault.lock():
        result = EspnPrImporter(paths).run(incoming_dir=args.from_dir, force=args.force)
        _print_espnpr_import_result(result)
        if not args.no_commit:
            for season in result.seasons():
                vault.commit_batch(
                    batch_message("import", "espnpr", str(season), result.counts(season)),
                    paths=[f"raw/espnpr/{season}", "ledger/requests.jsonl"],
                )
    return 4 if result.has_problems else 0


# -- import known ---------------------------------------------------------------------------


def _import_known(args: argparse.Namespace) -> int:
    """Validate a known-disagreements file against the cached posts and copy it
    into the vault under the lock; the commit touches only that file and the
    ledger, with a count-only message. SMW's file travels with `import smw`."""
    paths = DataPaths.from_env()
    vault = VaultRepo(paths.vault)
    vault.check()
    source = cast(PostSource, args.known_source)
    with vault.lock():
        result = import_known(paths, source, args.season, args.from_file, force=args.force)
        print(
            f"known {source} {args.season}: imported {result.imported}, "
            f"skipped {result.skipped}, problems {len(result.problems)}"
        )
        for problem in result.problems:
            print(f"problem: {problem}")
        if result.changed_without_force:
            print("the vault copy differs; use --force to overwrite")
        if result.has_problems:
            return 4
        if not args.no_commit:
            vault.commit_batch(
                batch_message("import", source, str(args.season), result.counts()),
                paths=[
                    f"raw/{source}/{args.season}/{KNOWN_FILE}",
                    "ledger/requests.jsonl",
                ],
            )
    return 0


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


# -- audit overrides -----------------------------------------------------------------------


def _audit_overrides(args: argparse.Namespace) -> int:
    """Exit 1 when a crew_overrides.csv row names a telecast the vault's last
    build does not plot (the job build would fail on it), or a release
    pre-flight condition fails; 2 when that build's telecasts table is missing.
    Reads only; writes and commits nothing. Every line printed is fixed text,
    a count, or a line number."""
    if args.release and (args.vault is None or args.reference is None):
        print("crew overrides: --release needs --vault and --reference")
        return 2
    vault = args.vault if args.vault is not None else DataPaths.from_env().vault
    reference = args.reference if args.reference is not None else reference_dir()
    if args.release:
        problems = release_problems(vault, reference)
        for problem in problems:
            print(f"crew overrides: {problem}")
        if problems:
            return 1
    try:
        result = check_overrides_exist(reference, vault / TELECASTS)
    except FileNotFoundError:
        print("crew overrides: no telecasts.parquet in the vault; pull the vault first")
        return 2
    except ReferenceTableError as exc:
        print(safe_loader_message(exc))
        return 1
    bad = result.missing_lines
    print(f"crew overrides: {result.telecasts} telecasts checked, {len(bad)} missing")
    if bad:
        lines = ", ".join(str(line) for line in bad)
        print(f"crew_overrides.csv: line(s) {lines} name a telecast the build does not have")
        return 1
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
    as every other live command) or GITHUB_TOKEN (read once from the
    environment and sent only to api.github.com by the NFL pbp step)."""
    if args.update and args.site_out is None:
        print("error: --update requires --site-out", file=sys.stderr)
        return 2
    if args.trigger == "schedule" and args.mode != "auto":
        # 18-13 F15: a scheduled run takes its mode from the clock (D-17).
        print(
            "error: --mode needs --trigger manual; a scheduled run picks its own", file=sys.stderr
        )
        return 2
    # 18-13 F6: the schedule-only cap applies once the run resolves to schedule mode (cron passes
    # --mode auto), unless --max-cfbd-calls names a cap.
    max_calls = args.max_cfbd_calls
    schedule_max_calls = None if max_calls is not None else JOB_CFBD_SCHEDULE_MAX_CALLS
    if max_calls is None:
        max_calls = JOB_CFBD_MAX_CALLS
    runtime = build_runtime(
        with_budget=True, floor=CFBD_FLOOR_DEFAULT, max_calls=max_calls, tag="job"
    )
    try:
        token = None if args.dry_run else load_cfbd_key()
        github_token = os.environ.get("GITHUB_TOKEN") or None
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
            nfl_rr_cap=args.nfl_rr_cap,
            github_token=github_token,
            nfl_site=nfl_site_enabled(os.environ),
            mode=None if args.mode == "auto" else args.mode,
            schedule_max_calls=schedule_max_calls,
            # CR-02: the CFB-only outcome is written before the NFL block, so a
            # killed run (the workflow's step timeout) still leaves it to deploy.
            on_cfb_result=lambda cfb: _write_job_outputs(args, cfb),
        )
        result: JobRunResult = job.run()

        if result.exit_code == EXIT_NOTHING_DUE:
            print("nothing due since last attempt")

        _write_job_outputs(args, result)
        return result.exit_code
    finally:
        runtime.client.close()


def _write_job_outputs(args: argparse.Namespace, result: JobRunResult) -> None:
    """Write --attention-out (only when there is something to report) and
    --result-out for `result`. Called twice on a run that reaches the NFL
    block: with the CFB-only outcome, then with the final one. Each file is
    written atomically (a temp sibling, then a rename), so a run killed at
    any point leaves either the earlier complete file or the new one."""
    if args.attention_out is not None:
        body = build_attention_body(
            split_reminders(result.items)[0], generated_at=datetime.now(UTC)
        )
        if body is not None:
            atomic_write_bytes(args.attention_out, body.encode("utf-8"))

    if args.reminders_out is not None:
        reminder_body = build_attention_body(
            split_reminders(result.items)[1], generated_at=datetime.now(UTC)
        )
        if reminder_body is not None:
            atomic_write_bytes(args.reminders_out, reminder_body.encode("utf-8"))

    if args.result_out is not None:
        atomic_write_bytes(
            args.result_out,
            (
                f"deploy_ready={'true' if result.deploy_ready else 'false'}\n"
                f"stale_only={'true' if result.stale_only else 'false'}\n"
            ).encode(),
        )


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
                batch_message("budget", "cfbd", "info", {"calls": calls_made}),
                paths=list(_COLLECT_PATHS["cfbd"]),
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
    if "unrated_shipped" in outcome.counts:
        # D-11, D-13: counts only, never a name.
        plotted_dropped = outcome.counts.get("plotted_duplicates_dropped", 0)
        plotted = outcome.counts.get("plotted_telecasts", 0) - plotted_dropped
        unrated = outcome.counts["unrated_shipped"]
        print(
            f"games {plotted + unrated} shipped ({plotted} rated, {unrated} unrated), "
            f"{outcome.counts.get('unrated_left_out', 0)} unrated left out "
            "(no game or no network), "
            f"{outcome.counts.get('unrated_duplicates_dropped', 0)} duplicate unrated dropped, "
            f"{plotted_dropped} duplicate rated dropped, "
            f"rarity audit: {outcome.counts.get('rarely_rated_but_mostly_rated', 0)} "
            "flagged but mostly rated, "
            f"{outcome.counts.get('not_rarely_rated_but_mostly_unrated', 0)} "
            "unflagged but mostly unrated"
        )
    if "rivalry_games_tagged" in outcome.counts:
        # D-13: title games excluded via CFBD notes (2022 on) and later meetings
        # demoted by the first-meeting rule. Counts only.
        print(
            f"rivalries: {outcome.counts['rivalry_games_tagged']} games tagged "
            f"({outcome.counts['rivalry_telecasts_tagged']} telecasts), "
            f"title games excluded {outcome.counts['rivalry_title_games_excluded']}, "
            f"rematches demoted {outcome.counts['rivalry_rematches_demoted']}"
        )
    if "venues_shipped" in outcome.counts:
        # 04.18 D-14/D-16: where games are placed; counts only.
        print(
            f"venues: {outcome.counts['venues_shipped']} shipped "
            f"({outcome.counts['venues_abroad']} abroad), "
            f"games in Alaska {outcome.counts['venue_games_alaska']}, "
            f"in Hawaii {outcome.counts['venue_games_hawaii']}, "
            f"no venue id {outcome.counts['venue_games_no_id']}, "
            f"unlocated {outcome.counts['venue_games_unlocated']}"
        )
    if (n := outcome.counts.get("venues_malformed", 0)) > 0:
        print(f"venues skipped as malformed (their games ship unlocated): {n}")
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
    # 04.19 D-13/D-15: ESPN Press Room backup crews; counts only (the review
    # rows and the gap list stay in the vault's interim/).
    print(
        f"crew backup: filled {outcome.counts.get('crew_backup_filled', 0)}, "
        f"disagreements {outcome.counts.get('crew_backup_disagreements', 0)}, "
        f"network mismatches {outcome.counts.get('crew_backup_network_mismatch', 0)}, "
        f"sideline dropped {outcome.counts.get('crew_backup_sideline_dropped', 0)}, "
        f"gap weeks listed {outcome.counts.get('crew_backup_gap_weeks', 0)}, "
        f"rows skipped {outcome.counts.get('crew_backup_rows_skipped', 0)}, "
        f"radio dropped {outcome.counts.get('crew_backup_radio_dropped', 0)}, "
        f"pages without booths {outcome.counts.get('crew_backup_pages_without_booths', 0)}"
        + _nonzero(
            ("rejected pages", outcome.counts.get("crew_backup_rejected_pages", 0)),
            ("upcoming games filled", outcome.counts.get("crew_backup_scheduled_filled", 0)),
        )
    )
    for gate in outcome.second_source_gates:
        extras = _nonzero(
            ("unlinked prose", gate.unlinked_prose),
            ("superseded", gate.superseded),
            ("excluded by override", gate.excluded_override),
            ("rejected pages", gate.rejected_pages),
            ("accepts ignored", gate.accepts_ignored),
            ("accepts unused", gate.accepts_unused),
        )
        print(
            f"second source {gate.source} {gate.season}: shared {gate.shared}, "
            f"within 3% {gate.within_3pct}, logged {gate.logged}, "
            f"unexplained {gate.unexplained}, loaded {gate.loaded}, "
            f"held {gate.held_network}{extras}, {gate.status}"
        )
    if outcome.second_source_gates:
        print(
            f"second sources: {outcome.counts.get('second_source_loaded', 0)} loaded, "
            f"{outcome.counts.get('second_source_held_network', 0)} held for network, "
            f"{outcome.counts.get('second_source_unmatched', 0)} for review, "
            f"{outcome.counts.get('second_source_withheld_seasons', 0)} season(s) withheld"
        )
    # WR-05: an accept that placed no figure would otherwise look like a resolved
    # item forever. Only public second_source_network_accepts.csv line numbers print.
    for line, status in outcome.second_source_accept_warnings:
        why = (
            "the game has more than one main telecast, so the accept can't choose one; "
            "correct the network through the override tables instead"
            if status == "ignored"
            else "no held row needs it (the pointer is gone or its network now matches); "
            "remove the row"
        )
        print(f"warning: second_source_network_accepts.csv line {line}: {why}", file=sys.stderr)
    rejected = outcome.counts.get("second_source_rejected_pages", 0) + outcome.counts.get(
        "crew_backup_rejected_pages", 0
    )
    if rejected:
        # CR-01: an unreadable cached page is skipped, never a reason to stop the build.
        print(
            f"warning: {rejected} cached page(s) skipped as unreadable "
            "(see interim/review_second_source_rejected.csv)",
            file=sys.stderr,
        )
    for drop in outcome.explained:
        print(
            f"warning: season {drop.season}: match_rate below baseline only from "
            f"{drop.games} rated game(s) 506 lists with no crew, not blocking "
            "(see interim/review_crew_overrides.csv)",
            file=sys.stderr,
        )
    if outcome.accepted:
        print("accepted new baseline")
    for reason in outcome.reasons:
        print(reason)
    return 4 if exit_blocked else 0


def _nonzero(*fields: tuple[str, int]) -> str:
    """Build output extras: ", <label> <n>" for each field whose count is not zero."""
    return "".join(f", {label} {n}" for label, n in fields if n)


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
    nfl = bool(args.nfl) or nfl_site_enabled(os.environ)
    nfl_source: Path | None = None
    if nfl and args.fixture:
        nfl_source = nfl_fixture_path()
    elif nfl:
        nfl_source = DataPaths.from_env().processed / "nfl-data.json"
        if not nfl_source.is_file():
            raise SiteBuildError(
                "processed/nfl-data.json not found; run `booth-review nfl site-data` first"
            )
    mlb = bool(args.mlb) or mlb_site_enabled(os.environ)
    mlb_source: Path | None = None
    if mlb and args.fixture:
        mlb_source = mlb_fixture_path()
    elif mlb:
        mlb_source = DataPaths.from_env().processed / "mlb-data.json"
        if not mlb_source.is_file():
            raise SiteBuildError(
                "processed/mlb-data.json not found; run `booth-review mlb site-data` first"
            )
    try:
        result: SiteBuildResult = assemble_site(
            source=source,
            out_dir=args.out,
            site_src=site_source_dir(),
            docs=docs_dir(),
            nfl=nfl,
            nfl_payload=load_nfl_site_payload(nfl_source) if nfl_source is not None else None,
            mlb=mlb,
            mlb_payload=load_mlb_site_payload(mlb_source) if mlb_source is not None else None,
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
    if result.nfl_games is not None:
        print(f"nfl: {result.nfl_games} games")
    if result.mlb_games is not None:
        print(f"mlb: {result.mlb_games} games")
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
    if result.nfl_switched_on:
        print("nfl data: carried live copy and turned the NFL switch on")
    elif result.nfl_carried:
        print("nfl data: carried live copy")
    elif result.nfl_not_carried is not None:
        reason = result.nfl_not_carried.replace("_", " ")
        print(f"nfl data: live copy not carried ({reason}); CFB deployed without it")
    if result.mlb_switched_on:
        print("mlb data: carried live copy and turned the MLB switch on")
    elif result.mlb_carried:
        print("mlb data: carried live copy")
    elif result.mlb_not_carried is not None:
        reason = result.mlb_not_carried.replace("_", " ")
        print(f"mlb data: live copy not carried ({reason}); deployed without it")
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


def _review_smw_diff(args: argparse.Namespace) -> int:
    """Offline: reads and writes only under --root, so no vault lock."""
    folder = season_dir(args.root, args.season)
    charts = list_chart_pngs(folder)
    tdir = folder / "transcription"
    if args.check_pass is not None:
        # Self-check one pass: never opens the other pass's folder.
        covered = load_pass_dir(tdir / f"pass-{args.check_pass}")
        rows = sum(len(v) for v in covered.values())
        print(
            f"pass {args.check_pass}: charts covered "
            f"{len(set(covered) & set(charts))} of {len(charts)}, rows {rows}"
        )
        return 0
    entries = diff_passes(tdir / "pass-a", tdir / "pass-b", charts)
    write_diff_csv(tdir / "diff.csv", entries)
    kinds = [e.kind for e in entries]
    print(
        f"smw {args.season}: charts {len(charts)}, cell diffs {kinds.count('cell')}, "
        f"row-count diffs {kinds.count('row_count')}, missing charts {kinds.count('missing_chart')}"
    )
    return 0


def _review_smw_merge(args: argparse.Namespace) -> int:
    folder = season_dir(args.root, args.season)
    tdir = folder / "transcription"
    page = folder / "season-page.html"
    if not page.is_file():
        print(f"smw {args.season}: season-page.html is missing")
        return 4
    charts = list_chart_pngs(folder)
    order = parse_chart_order(page.read_text(encoding="utf-8", errors="replace"), set(charts))
    if order.unreferenced:
        print(f"smw {args.season}: {len(order.unreferenced)} chart(s) not listed on the page")
        return 4
    diff = diff_passes(tdir / "pass-a", tdir / "pass-b", charts)
    pass_c = tdir / "pass-c"
    try:
        merged = merge_rows(
            tdir / "pass-a",
            pass_c if pass_c.is_dir() else None,
            diff,
            load_resolutions(tdir / "resolutions.csv"),
            order.entries,
        )
    except SmwMergeError as exc:
        print(f"smw {args.season}: cannot merge: {exc}")
        return 4
    write_rows_csv(tdir / "rows.csv", merged)
    print(f"smw {args.season}: rows {len(merged)} from {len(charts)} chart(s)")
    return 0


def _review_teams(args: argparse.Namespace) -> int:
    if args.no_write:
        return resolve_diagnose.main(["--no-write"])
    return _with_vault_lock(lambda: resolve_diagnose.main([]))


def _review_nfl_stadiums(args: argparse.Namespace) -> int:
    from booth_review.nfl.stadium_draft import build_draft_rows, write_draft

    rows = build_draft_rows(DataPaths.from_env(), Path("data/reference"))
    target = write_draft(rows, args.out)
    filled = sum(1 for row in rows if row["lat"])
    print(f"wrote {target}: {len(rows)} rows, {filled} with coordinates")
    return 0


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
    _check_league_ceiling(parser, args)

    try:
        if args.command == "collect":
            if args.source == "506":
                return _collect_506(args)
            if args.source == "ratingsref":
                return _collect_ratingsref(args)
            if args.source == "cfbd":
                return _collect_cfbd(args)
            if args.source == "nflverse":
                return _collect_nflverse(args)
            if args.source == "wikipedia":
                return _collect_wikipedia(args)
            if args.source in ("tvrg", "aa"):
                return _collect_second(args, cast(PolicySource, args.source))
            if args.source == "retrosheet":
                return run_collect_retrosheet(args, _COLLECT_PATHS)
            if args.source == "statsapi":
                return run_collect_statsapi(args, _COLLECT_PATHS)
            raise AssertionError(f"unknown collect source: {args.source!r}")
        if args.command == "refresh":
            if args.source == "ratingsref":
                return _refresh_ratingsref(args)
            raise AssertionError(f"unknown refresh source: {args.source!r}")
        if args.command == "import":
            if args.source == "506":
                return _import_506(args)
            if args.source == "relay":
                return run_import_relay(args, _COLLECT_PATHS)
            if args.source == "smw":
                return _import_smw(args)
            if args.source == "espnpr":
                return _import_espnpr(args)
            if args.source == "known":
                return _import_known(args)
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
            if args.audit_command == "overrides":
                return _audit_overrides(args)
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
        if args.command == "nfl":
            return run_nfl_command(args)
        if args.command == "mlb":
            return run_mlb_command(args)
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
            if args.review_command == "smw-diff":
                return _review_smw_diff(args)
            if args.review_command == "nfl-stadiums":
                return _review_nfl_stadiums(args)
            if args.review_command == "smw-merge":
                return _review_smw_merge(args)
            raise AssertionError(f"unknown review command: {args.review_command!r}")
        raise AssertionError(f"unknown command: {args.command!r}")
    except BoothReviewError as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
