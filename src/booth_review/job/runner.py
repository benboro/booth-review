"""ScheduledJob: the `booth-review job run` entry point (AUTO-01).

Composes the Plan 04 job modules (catchup, gaps506, attention) with the
existing collectors into one tested, catch-up-aware, count-only collect-only
run for the current season: a CFBD season-level refresh, the Ratings
Reference lastmod refresh, and a report of which 2026 506 week pages need a
hand-save -- never a 506 fetch (D-07/D-08/AUTO-01, Claude's Discretion) --
plus the week's ESPN Press Room commentators page when it is not saved yet,
never fetched either (04.19 D-14).

Each step commits its own paths with a count-only message (batch_message);
the CFB state (`ledger/job_state.json`) is saved and committed after every CFB
step and before any NFL step. A VaultCommitError
at any commit stops the run immediately (exit 3); every other step failure
becomes an attention item and the run continues (exit 4 when any attention
item exists, exit 0 on a clean run). "Every other" includes exceptions that
aren't BoothReviewError (a JSONDecodeError, KeyError, ValueError, OSError...):
each step boundary turns them into a count-only item naming only the
exception class, never its message, and the state is still saved (WR-12).
A VaultStateError raised while committing (the vault lock or check) still
propagates, as the CLI's exit 3.

GitHub's own scheduler is lossy, so the workflow template also fires backup
cron slots between the two main slots (Sunday 10:00 / Wednesday 20:00 ET,
D-11). `EXIT_NOTHING_DUE = 5` is returned by a `trigger="schedule"` run that
finds no main slot has occurred since its last attempt (`job.catchup.is_due`):
it exits before any CFBD, RR, or 506 step, any vault commit, or the
`ledger/job_state.json` save, so a dropped main slot's next backup slot is the
only run that actually does anything.

Due-ness is measured from the last *attempt* (`last_attempt_at`, saved by
every run that gets as far as the state save, failed steps included), not
the last success: each main slot gets at most one scheduled attempt, so a
step that keeps failing is retried at the next main slot (or by a manual
run, which is always due) instead of re-running the whole job at every
backup slot. The exception is a transient CFBD failure (a 5xx, 429, or network
error, `_is_transient_cfbd_error`): the saved state's `retry_pending` makes
every backup slot retry until a run gets past it. A run that stops with exit 3
before the state save records no attempt, so the next backup slot retries it.

NFL steps (999.4 D-07/D-08) run after every CFB step and CFB commit, the CFB
state save and push included, once the
vault is NFL-bootstrapped (an nflverse schedules file exists) and inside the NFL
collectable season: nflverse schedules, 2026 play-by-play (Wednesday/Thursday
ET slots and manual runs only), the Ratings Reference NFL refresh under its own
cap, the Wikipedia season article, the NFL 506 gap list, the schedule-drift and
past-freeze checks, and in update mode the NFL build (no deploy). Each is its
own guarded block with no passthrough, so any NFL exception, a VaultCommitError
or VaultStateError from an NFL commit included, becomes an attention item. NFL
results never touch the CFB failure flags, retry state, build time, deploy or
key-leak result: they can add attention items (exit 4), never exit 3, a
"failed" last_status or a held-back last_success_at.

Running the NFL block only after the CFB state is pushed (CR-02) means an NFL
commit whose push fails (it is rolled back onto the remote, its files merged
onto the remote's on disk), a lock wait or a slow or killed NFL step can no
longer fail or lose the CFB state push. Because the NFL items are known only
after that save, `ledger/job_state.json` and `ledger/run_reports.jsonl`
describe the CFB run alone; the NFL block appends its own count-only line
(attention count and `nfl_*` counts) to `ledger/nfl_run_reports.jsonl` in a
final `job: nfl_state` commit, and its items still reach the run's attention
report and exit code (4 at most).
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TypeVar

from booth_review.audit.completeness import SOURCES
from booth_review.build.pipeline import BuildOutcome, run_build
from booth_review.build.site_assembly import (
    BUILD_MARKER,
    SiteBuildResult,
    add_nfl_to_site,
    assemble_site,
    check_nfl_file_key,
    docs_dir,
    load_nfl_site_payload,
    refresh_nfl_data,
    site_source_dir,
    site_sports,
)
from booth_review.config import CFBD_FLOOR_DEFAULT
from booth_review.contract.nfl_models import NflSiteData
from booth_review.errors import (
    FetchError,
    KeyLeakError,
    ParseError,
    RobotsUnavailableError,
    SiteBuildError,
    VaultCommitError,
    VaultStateError,
)
from booth_review.job.aa_watch import make_aa_cfb_resolver
from booth_review.job.attention import (
    AttentionItem,
    bowls_missing,
    build_blocked,
    cfbd_failed,
    cfbd_remaining,
    cfbd_step_failed,
    error_type_name,
    espnpr_week_unsaved,
    failed_attempts,
    has_attention,
    has_reminders,
    missed_runs,
    nfl_506_missing,
    nfl_506_stale,
    nfl_build_blocked,
    nfl_review_due,
    nfl_rr_backlog,
    nfl_schedule_drift,
    nfl_season_past_freeze,
    nfl_site_failed,
    nfl_site_key_check_failed,
    nfl_site_switch_off,
    people_review_due,
    push_failed,
    rr_backlog,
    rr_failed,
    rr_step_failed,
    season_past_freeze,
    site_key_check_failed,
    site_key_check_skipped,
    sports506_missing,
    sports506_stale,
    step_failed,
    unresolved_teams,
)
from booth_review.job.catchup import (
    EASTERN,
    CatchupWindow,
    JobState,
    RunMode,
    Trigger,
    catchup_window,
    collectable_season,
    load_state,
    resolve_mode,
    save_state,
)
from booth_review.job.gaps506 import find_506_gaps
from booth_review.job.gaps_espnpr import espnpr_page_week, find_espnpr_gap
from booth_review.job.reminders import AaCfbResolver, due_reminders
from booth_review.job.staleness import newest_listed, newest_plotted, staleness_items
from booth_review.nfl.freeze import schedule_drift
from booth_review.nfl.gaps import find_nfl_506_gaps
from booth_review.nfl.layout import NFL_FIRST_SEASON, NFL_SOURCES, NFLVERSE_SCHEDULES_PATH
from booth_review.nfl.pipeline import run_nfl_build
from booth_review.nfl.seasons import nfl_collectable_season, nfl_freeze_date
from booth_review.reference import reference_dir
from booth_review.runtime import Runtime
from booth_review.seasons import freeze_date, is_past_freeze_date, season_of
from booth_review.sources.base import BatchSummary
from booth_review.sources.cfbd.collector import CfbdCollector
from booth_review.sources.cfbd.parser import parse_games
from booth_review.sources.nflverse.collector import NflverseCollector
from booth_review.sources.ratingsref.collector import (
    FIRST_SEASON,
    NFL_REFRESH_CAP_DEFAULT,
    REFRESH_CAP_DEFAULT,
    RatingsRefCollector,
    RefreshSummary,
)
from booth_review.sources.ratingsref.lastmod import lastmod_ledger_exists
from booth_review.sources.wikipedia.collector import WikipediaCollector
from booth_review.transport.cache import FreezeGuard
from booth_review.vault import batch_message

# The season-level CFBD endpoints the job re-fetches every run (D-09), plus
# the once-per-season set fetched only until cached. Never includes anything
# outside CfbdCollector.plan's own allow-listed endpoint names.
JOB_CFBD_REFRESH: tuple[str, ...] = ("games", "media", "lines", "wp_pregame", "rankings")
JOB_CFBD_ONCE: tuple[str, ...] = ("teams_fbs",)

# Schedule-only runs (Phase 18 D-14/D-15): just the whole-season games and media
# lists, 2 counted requests, plus a possible /info on a month's first run.
JOB_CFBD_SCHEDULE: tuple[str, ...] = ("games", "media")
JOB_CFBD_SCHEDULE_MAX_CALLS = 3

# A default run-cap for the job's CFBD calls: 5 refresh endpoints + 1 once
# endpoint (uncached worst case) + 1 /info on a month's first run (when the
# month's remaining budget is still unknown) plus headroom, well under the monthly budget
# at 2 runs/week (Claude's Discretion; CONTEXT.md's ~45 calls/month estimate).
JOB_CFBD_MAX_CALLS = 8

# Vault state files the job refuses to run without (VaultStateError, exit 3):
# a missing file never falls back to treating the vault as empty/new. The RR
# lastmod ledger counts as present in either form (the pre-0.2.2
# rr_lastmod.json snapshot or the rr_lastmod.jsonl log; see
# sources.ratingsref.lastmod).
REQUIRED_LEDGER_FILES: tuple[str, ...] = ("cfbd_ledger.jsonl", "frozen.json")

# Exceptions a step boundary never turns into an attention item: a vault
# commit/push failure (exit 3), and a VaultStateError, which can only reach a
# step boundary from a commit (lock timeout, vault check) because each
# step's own collection code already catches everything it raises.
_COMMIT_PASSTHROUGH: tuple[type[Exception], ...] = (VaultCommitError, VaultStateError)

_T = TypeVar("_T")

# A scheduled run with nothing due since its last attempt (job.catchup.is_due
# is False) exits here -- a cheap no-op for a backup cron slot -- before any
# CFBD, RR, or 506 step, commit, or ledger/job_state.json save.
EXIT_NOTHING_DUE = 5

# 999.4 (Claude's Discretion): 2026 play-by-play is re-downloaded only on the
# Wednesday/Thursday ET slots (Wednesday main, Thursday backups), once the
# weekend's games are in, to limit vault growth; the Sunday slot skips it and a
# manual run always does it. Python weekday numbers: Monday is 0.
NFL_PBP_REFRESH_WEEKDAYS = frozenset({2, 3})

# The NFL block's own count-only run report (CR-02): written after the CFB state
# save, so it never shares a commit or a file with ledger/run_reports.jsonl.
NFL_RUN_REPORTS = "nfl_run_reports.jsonl"

# Vault paths each NFL job step commits (never a CFB path; RESEARCH Pitfall 4).
_NFL_SCHEDULES_PATHS: tuple[str, ...] = ("raw/nfl/nflverse", "raw/_robots", "ledger/requests.jsonl")
_NFL_PBP_PATHS: tuple[str, ...] = (*_NFL_SCHEDULES_PATHS, "ledger/nfl_nflverse_assets.jsonl")
_NFL_RR_PATHS: tuple[str, ...] = (
    "raw/nfl/ratingsref",
    "raw/ratingsref/sitemap",
    "raw/_robots",
    "ledger/requests.jsonl",
    "ledger/rr_lastmod.json",
    "ledger/rr_lastmod.jsonl",
)
_NFL_WIKIPEDIA_PATHS: tuple[str, ...] = (
    "raw/nfl/wikipedia",
    "raw/_robots",
    "ledger/requests.jsonl",
)


@dataclass(frozen=True)
class JobRunResult:
    """The outcome of one ScheduledJob.run() call."""

    exit_code: int
    items: list[AttentionItem]
    counts: dict[str, int]
    window: CatchupWindow | None
    deploy_ready: bool = False
    """Update mode only: the build and site both passed with the key check run (D-09/D-10)."""
    stale_only: bool = False
    """A nothing-due run that found D-14 staleness: exit 4, nothing written."""


# Update mode also needs the accepted build baseline and a cached RR sitemap
# (never re-crawl the sitemap from scratch, AUTO-02 / Pitfall 4).
_BASELINE_RELATIVE = "audit/build_baseline.csv"


def _remaining_text(value: int | None) -> str:
    return "unknown" if value is None else str(value)


def _exit_code(key_leak: bool, items: Sequence[AttentionItem]) -> int:
    """A finished run's exit code: 3 on a key leak, else 4 with attention, else 0."""
    return 3 if key_leak else (4 if has_attention(items) else 0)


def _is_transient_cfbd_error(exc: Exception) -> bool:
    """Whether a CFBD step failure is an outage a later backup slot may clear:
    a network error (FetchError with no status), a 5xx or 429 that survived
    the client's own retries, or robots.txt answering 5xx. A 4xx, budget
    refusal, or anything else is not, since retrying it changes nothing."""
    if isinstance(exc, RobotsUnavailableError):
        return True
    if isinstance(exc, FetchError):
        status = exc.status_code
        return status is None or status >= 500 or status == 429
    return False


def _check_required_state(runtime: Runtime, *, update: bool = False) -> None:
    paths = runtime.paths
    missing = [
        f"ledger/{name}" for name in REQUIRED_LEDGER_FILES if not (paths.ledger / name).is_file()
    ]
    if not lastmod_ledger_exists(paths):
        missing.insert(0, "ledger/rr_lastmod.json(l)")
    if update:
        if not (paths.vault / _BASELINE_RELATIVE).is_file():
            missing.append(_BASELINE_RELATIVE)
        sitemap_dir = paths.raw / "ratingsref" / "sitemap"
        if not sitemap_dir.is_dir() or not any(sitemap_dir.glob("*.xml")):
            missing.append("raw/ratingsref/sitemap")
    if missing:
        raise VaultStateError(
            "job refuses to run: required vault state file(s) missing: " + ", ".join(missing)
        )


def _sum_batch_counts(summaries: Sequence[BatchSummary]) -> dict[str, int]:
    totals = {"fetched": 0, "cached": 0, "not_modified": 0, "failed": 0}
    for summary in summaries:
        for key, value in summary.counts().items():
            totals[key] += value
    return totals


def _partial_counts(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    return {
        "fetched": after["fetched"] - before["fetched"],
        "cached": after["cached"] - before["cached"],
        "not_modified": after["not_modified"] - before["not_modified"],
        "failed": 0,
    }


def _partial_refresh_counts(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    return {
        "fetched": after["fetched"] - before["fetched"],
        "not_modified": after["not_modified"] - before["not_modified"],
        "failed": 0,
        "backlog": 0,
    }


class ScheduledJob:
    """Runs one collect-only pass for the current season (AUTO-01)."""

    def __init__(
        self,
        runtime: Runtime,
        *,
        token: str | None,
        now: Callable[[], datetime],
        trigger: Trigger,
        rr_cap: int = REFRESH_CAP_DEFAULT,
        dry_run: bool = False,
        commit: bool = True,
        update: bool = False,
        site_out: Path | None = None,
        reference_directory: Path | None = None,
        site_src: Path | None = None,
        docs: Path | None = None,
        nfl_rr_cap: int = NFL_REFRESH_CAP_DEFAULT,
        github_token: str | None = None,
        on_cfb_result: Callable[[JobRunResult], None] | None = None,
        nfl_site: bool = False,
        mode: RunMode | None = None,
        schedule_max_calls: int | None = None,
    ) -> None:
        """`github_token` (optional GITHUB_TOKEN) goes only to the nflverse
        play-by-play listing on api.github.com; it is never logged or stored.

        `on_cfb_result` gets the CFB-only outcome once the CFB state is saved
        and before the NFL block starts (CR-02), so the caller can write its
        result files early: an NFL step that hangs until it is killed can then
        never cost the run's CFB deploy. `run()` still returns the final outcome.

        `nfl_site` (NFL_SITE_ENABLED exactly true, D-18) adds nfl-data.json to
        the site dir: carried over from the vault, then refreshed after the NFL
        build. The NFL switch ships only with a valid file (WR-01): with no
        valid carry-over the site is built CFB-only, and the NFL block turns
        the switch on in the same run once it has a valid fresh file (iter-2
        WR-02). NFL site problems are items that join the final outcome only.

        `mode` (D-17): None derives it from the trigger and clock
        (`resolve_mode`); "schedule" re-pulls only CFBD games/media and the
        nflverse schedule, "rebuild" collects nothing; both then build and
        deploy and never move `last_success_at` or `last_attempt_at`.

        `schedule_max_calls` lowers the CFBD run cap once the run resolves to
        "schedule" mode, however the mode was chosen (18-13 F6)."""
        if update and site_out is None:
            raise ValueError("update mode requires site_out")
        self._update = update
        self._site_out = site_out
        self._reference_directory = reference_directory
        self._site_src = site_src
        self._docs = docs
        self._runtime = runtime
        self._token = token
        self._now = now
        self._trigger = trigger
        self._rr_cap = rr_cap
        self._nfl_rr_cap = nfl_rr_cap
        self._github_token = github_token
        self._dry_run = dry_run
        self._commit_enabled = commit
        self._aa_resolver: AaCfbResolver | None = None
        self._on_cfb_result = on_cfb_result
        self._nfl_site = nfl_site
        self._mode = mode
        self._schedule_max_calls = schedule_max_calls
        self._nfl_carry_items: list[AttentionItem] = []

    def _aa_cfb_resolver(self) -> AaCfbResolver | None:
        """The shared AA feed resolver, built once per run; none in a dry run."""
        if self._dry_run:
            return None
        if self._aa_resolver is None:
            self._aa_resolver = make_aa_cfb_resolver(self._runtime, commit=self._commit_enabled)
        return self._aa_resolver

    # -- public entry point ------------------------------------------------

    def run(self) -> JobRunResult:
        _check_required_state(self._runtime, update=self._update)

        paths = self._runtime.paths
        now = self._now()
        today = now.date()
        state = load_state(paths.job_state)

        season = collectable_season(today)
        rr_current_season = season_of(today)
        window_season = season if season is not None else rr_current_season
        window = catchup_window(state, now, window_season, self._trigger)

        mode = resolve_mode(state, now, self._trigger, self._mode)
        if mode is None:
            # Phase 24 D-12..D-16: hand-save reminders on the comment-only path, ahead of
            # every budget, CFBD, vault-commit, state, build and deploy line, so a reminder
            # slot is never a missed or failed collection run. Phase 25 D-02/D-12: the AA
            # Tue slot may make one feed request and commit ledger/aa_feed_watch.json;
            # nothing else on this path writes.
            quiet_items: list[AttentionItem] = []
            if self._update:
                self._staleness_step(quiet_items, state.last_build_at, now, season)
            quiet_items.extend(due_reminders(paths, now, aa_cfb=self._aa_cfb_resolver()))
            if has_attention(quiet_items) or has_reminders(quiet_items):
                return JobRunResult(
                    exit_code=4,
                    items=quiet_items,
                    counts={"skipped": 1},
                    window=window,
                    stale_only=True,
                )
            return JobRunResult(
                exit_code=EXIT_NOTHING_DUE, items=[], counts={"skipped": 1}, window=window
            )

        budget = self._runtime.budget
        if mode == "schedule" and self._schedule_max_calls is not None and budget is not None:
            budget.limit_run_calls(self._schedule_max_calls)
        if mode != "full":
            return self._run_light(mode, state, now, season, window, window_season)

        items: list[AttentionItem] = []
        counts: dict[str, int] = {}
        any_failed = False
        retry_pending = False
        deploy_ready = False
        key_leak = False
        new_last_build_at: datetime | None = None
        remaining_start = self._remaining(now)
        print(f"cfbd remaining at start: {_remaining_text(remaining_start)}")

        try:
            if season is not None:
                cfbd_season = season
                cfbd_result = self._guarded(
                    items,
                    cfbd_step_failed,
                    lambda: self._run_cfbd_step(cfbd_season, items),
                    passthrough=_COMMIT_PASSTHROUGH,
                )
                if cfbd_result is None:
                    any_failed = True
                else:
                    cfbd_failed, retry_pending, cfbd_counts = cfbd_result
                    any_failed = any_failed or cfbd_failed
                    counts.update({f"cfbd_{key}": value for key, value in cfbd_counts.items()})

            rr_result = self._guarded(
                items,
                rr_step_failed,
                lambda: self._run_rr_step(rr_current_season, items),
                passthrough=_COMMIT_PASSTHROUGH,
            )
            if rr_result is None:
                any_failed = True
            else:
                rr_failed, rr_counts = rr_result
                any_failed = any_failed or rr_failed
                counts.update({f"rr_{key}": value for key, value in rr_counts.items()})

            if season is not None:
                gap_season = season
                gap_ok = self._guarded_ok(
                    items,
                    lambda name: step_failed("sports506", name),
                    lambda: self._run_506_gap_step(gap_season, now, items),
                )
                any_failed = any_failed or not gap_ok
                # 04.19 D-14: the week's ESPN Press Room commentators page, read-only.
                espnpr_ok = self._guarded_ok(
                    items,
                    lambda name: step_failed("espnpr_gaps", name),
                    lambda: self._run_espnpr_gap_step(gap_season, now, items),
                )
                any_failed = any_failed or not espnpr_ok

            freeze_ok = self._guarded_ok(
                items,
                lambda name: step_failed("freeze", name),
                lambda: self._check_past_freeze(today, items),
            )
            any_failed = any_failed or not freeze_ok

            if self._update and not self._dry_run:
                build_failed, new_last_build_at, deploy_ready, key_leak = self._build_and_site(
                    items, counts, now
                )
                any_failed = any_failed or build_failed

            if self._update:
                self._staleness_step(items, new_last_build_at or state.last_build_at, now, season)

            if window.missed_slots > 0:
                items.append(missed_runs(window.missed_slots))
            if window.failed_slots > 0:
                items.append(failed_attempts(window.failed_slots))

            remaining_end: int | None = None
            budget = self._runtime.budget
            if budget is not None:
                # None both when the month is unknown and when reading the
                # ledger failed (the latter already added a budget item).
                remaining_end = self._guarded(
                    items,
                    lambda name: step_failed("budget", name),
                    lambda: budget.last_known_remaining(now.strftime("%Y-%m")),
                )
                if remaining_end is not None:
                    items.append(cfbd_remaining(remaining_end, CFBD_FLOOR_DEFAULT))
            print(f"cfbd remaining at end: {_remaining_text(remaining_end)}")
        except VaultCommitError:
            # A failed push still posts this slot's reminders (severity "reminder", so the
            # exit code stays 3); the +1h backup may itself be a failing retry.
            items.extend(due_reminders(paths, now, aa_cfb=self._aa_cfb_resolver()))
            return JobRunResult(exit_code=3, items=items, counts=counts, window=window)

        deploy_ready = deploy_ready and not key_leak
        items.extend(
            due_reminders(paths, now, aa_cfb=self._aa_cfb_resolver())
        )  # a due reminder joins the run's comment
        status = "attention" if has_attention(items) else "ok"

        if not self._dry_run:
            new_state = JobState(
                season=season,
                last_success_at=now if not any_failed else state.last_success_at,
                last_attempt_at=now,
                last_status="failed" if any_failed else status,
                last_window_start=window.start,
                retry_pending=retry_pending,
                last_build_at=new_last_build_at or state.last_build_at,
            )
            report = {
                "run_at": now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "trigger": self._trigger,
                "update": self._update,
                "mode": "full",
                "deploy_ready": deploy_ready,
                "cfbd_remaining_start": remaining_start,
                "cfbd_remaining_end": remaining_end,
                "attention": sum(1 for item in items if item.severity == "attention"),
                "counts": dict(counts),
            }
            try:
                self._save_state(new_state, window, window_season, items, report)
            except VaultCommitError:
                items.append(push_failed("state"))
                return JobRunResult(
                    exit_code=3, items=items, counts=counts, window=window, deploy_ready=False
                )
            except VaultStateError:
                raise
            except Exception as exc:
                items.append(step_failed("state", error_type_name(exc)))

        # CR-02: the CFB-only outcome goes to the caller before any NFL step,
        # so its result files exist even if an NFL step hangs and is killed.
        self._report_cfb_result(
            JobRunResult(
                exit_code=_exit_code(key_leak, items),
                items=list(items),
                counts=dict(counts),
                window=window,
                deploy_ready=deploy_ready,
            ),
            items,
        )

        # D-08 / CR-02: the NFL block runs only once the CFB state is saved and
        # pushed, so nothing it does (an unpushed NFL commit, a lock wait, a
        # slow or killed step) can fail or lose that push. It can only add
        # items, which make the run exit 4 at most.
        nfl_counts: dict[str, int] = {}
        items.extend(self._nfl_carry_items)
        self._run_nfl_phase(now, window_season, items, nfl_counts)
        counts.update(nfl_counts)
        if self._update and not self._dry_run and self._nfl_site:
            self._guarded_ok(
                items,
                lambda name: step_failed("nfl_site", name),
                lambda: self._note_switch_off(items),
                passthrough=(),
            )

        return JobRunResult(
            exit_code=_exit_code(key_leak, items),
            items=items,
            counts=counts,
            window=window,
            deploy_ready=deploy_ready,
        )

    def _build_and_site(
        self, items: list[AttentionItem], counts: dict[str, int], now: datetime
    ) -> tuple[bool, datetime | None, bool, bool]:
        """The build then site steps. Returns (failed, last_build_at,
        deploy_ready, key_leak); the VaultCommitError of a build push passes
        through."""
        any_failed = False
        new_last_build_at: datetime | None = None
        deploy_ready = False
        key_leak = False
        outcome = self._guarded(
            items,
            lambda name: step_failed("build", name),
            lambda: self._run_build_step(items, counts),
            passthrough=(VaultCommitError,),
        )
        # WR-06: a crashed build or site step, or a key leak, is a
        # failed run (state, failed_attempts, catch-up window); a
        # guard-blocked build (D-09) stays attention only.
        if outcome is None:
            any_failed = True
        elif not outcome.blocked:
            new_last_build_at = now
            site_result = self._guarded(
                items,
                lambda name: step_failed("site", name),
                lambda: self._run_site_step(items),
                passthrough=(VaultCommitError,),
            )
            if site_result is None:
                any_failed = True
            else:
                deploy_ready, key_leak = site_result
                any_failed = any_failed or key_leak
        return any_failed, new_last_build_at, deploy_ready, key_leak

    def _run_light(
        self,
        mode: RunMode,
        state: JobState,
        now: datetime,
        season: int | None,
        window: CatchupWindow,
        window_season: int,
    ) -> JobRunResult:
        """A schedule-only or rebuild-only run (D-14/D-15/D-17).

        "schedule" re-pulls CFBD games and media (when in season), then the
        NFL block runs only the nflverse schedule; "rebuild" collects nothing.
        Both then build and deploy under the same gates as a full run. Neither
        calls Ratings Reference, 506, ESPN Press Room, Wikipedia, the gap or
        freeze steps. The saved state moves only `last_schedule_at` (a clean
        schedule run only) and `last_build_at`, so the Sunday/Wednesday slot
        logic is untouched."""
        items: list[AttentionItem] = []
        counts: dict[str, int] = {}
        any_failed = False
        deploy_ready = False
        key_leak = False
        new_last_build_at: datetime | None = None
        remaining_start = self._remaining(now)
        print(f"mode: {mode}")
        print(f"cfbd remaining at start: {_remaining_text(remaining_start)}")

        try:
            if mode == "schedule" and season is not None:
                cfbd_season = season
                cfbd_result = self._guarded(
                    items,
                    cfbd_step_failed,
                    lambda: self._run_cfbd_step(
                        cfbd_season, items, endpoints=JOB_CFBD_SCHEDULE, include_once=False
                    ),
                    passthrough=_COMMIT_PASSTHROUGH,
                )
                if cfbd_result is None:
                    any_failed = True
                else:
                    cfbd_failed, _transient, cfbd_counts = cfbd_result
                    any_failed = any_failed or cfbd_failed
                    counts.update({f"cfbd_{key}": value for key, value in cfbd_counts.items()})

            if self._update and not self._dry_run:
                build_failed, new_last_build_at, deploy_ready, key_leak = self._build_and_site(
                    items, counts, now
                )
                any_failed = any_failed or build_failed

            if self._update:
                self._staleness_step(items, new_last_build_at or state.last_build_at, now, season)

            remaining_end: int | None = None
            budget = self._runtime.budget
            if budget is not None:
                remaining_end = self._guarded(
                    items,
                    lambda name: step_failed("budget", name),
                    lambda: budget.last_known_remaining(now.strftime("%Y-%m")),
                )
                if remaining_end is not None:
                    items.append(cfbd_remaining(remaining_end, CFBD_FLOOR_DEFAULT))
            print(f"cfbd remaining at end: {_remaining_text(remaining_end)}")
        except VaultCommitError:
            items.extend(due_reminders(self._runtime.paths, now, aa_cfb=self._aa_cfb_resolver()))
            return JobRunResult(exit_code=3, items=items, counts=counts, window=window)

        deploy_ready = deploy_ready and not key_leak
        items.extend(due_reminders(self._runtime.paths, now, aa_cfb=self._aa_cfb_resolver()))
        if not self._dry_run:
            # 18-13 F11: only a schedule run that pulled and built cleanly marks its slot done;
            # a failed pull or a rebuild leaves it, so the next backup slot still pulls.
            schedule_done = mode == "schedule" and not any_failed
            new_state = replace(
                state,
                last_schedule_at=now if schedule_done else state.last_schedule_at,
                last_build_at=new_last_build_at or state.last_build_at,
            )
            report = {
                "run_at": now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "trigger": self._trigger,
                "update": self._update,
                "mode": mode,
                "deploy_ready": deploy_ready,
                "cfbd_remaining_start": remaining_start,
                "cfbd_remaining_end": remaining_end,
                "attention": sum(1 for item in items if item.severity == "attention"),
                "counts": dict(counts),
            }
            try:
                self._save_state(new_state, window, window_season, items, report)
            except VaultCommitError:
                items.append(push_failed("state"))
                return JobRunResult(
                    exit_code=3, items=items, counts=counts, window=window, deploy_ready=False
                )
            except VaultStateError:
                raise
            except Exception as exc:
                items.append(step_failed("state", error_type_name(exc)))

        self._report_cfb_result(
            JobRunResult(
                exit_code=_exit_code(key_leak, items),
                items=list(items),
                counts=dict(counts),
                window=window,
                deploy_ready=deploy_ready,
            ),
            items,
        )

        nfl_counts: dict[str, int] = {}
        items.extend(self._nfl_carry_items)
        self._run_nfl_phase(now, window_season, items, nfl_counts, mode)
        counts.update(nfl_counts)
        if self._update and not self._dry_run and self._nfl_site:
            self._guarded_ok(
                items,
                lambda name: step_failed("nfl_site", name),
                lambda: self._note_switch_off(items),
                passthrough=(),
            )

        return JobRunResult(
            exit_code=_exit_code(key_leak, items),
            items=items,
            counts=counts,
            window=window,
            deploy_ready=deploy_ready,
        )

    # -- helpers ---------------------------------------------------------------

    def _report_cfb_result(self, cfb: JobRunResult, items: list[AttentionItem]) -> None:
        """Hand the CFB-only outcome to `on_cfb_result`. A failure there (say,
        an unwritable result file) is one attention item; the NFL block still
        runs, and the caller writes the final outcome afterward."""
        callback = self._on_cfb_result
        if callback is None:
            return
        self._guarded_ok(
            items,
            lambda name: step_failed("result_out", name),
            lambda: callback(cfb),
            passthrough=(),
        )

    def _remaining(self, now: datetime) -> int | None:
        """The last known CFBD remaining-call count (a ledger read, no call)."""
        budget = self._runtime.budget
        if budget is None:
            return None
        try:
            return budget.last_known_remaining(now.strftime("%Y-%m"))
        except Exception:
            return None

    # -- build and site (update mode) -----------------------------------------

    def _run_build_step(self, items: list[AttentionItem], counts: dict[str, int]) -> BuildOutcome:
        reference = self._reference_directory or reference_dir()
        try:
            outcome = run_build(
                self._runtime.paths,
                reference,
                commit=self._commit_enabled,
                accept_baseline=False,
                bowl_crosswalk="lenient",
            )
        except VaultCommitError:
            items.append(push_failed("build"))
            raise

        built = outcome.counts
        blocked = outcome.blocked and not outcome.accepted
        print(
            f"build: telecasts {built.get('plotted_telecasts', 0)} plotted, "
            f"blocked {'yes' if blocked else 'no'}"
        )
        print(
            f"build: season {built.get('current_season', 0)} "
            f"games {built.get('games_current_season', 0)}, "
            f"final {built.get('games_final_current_season', 0)}, "
            f"telecasts {built.get('telecasts_current_season', 0)}, "
            f"rated {built.get('rated_current_season', 0)}, "
            f"plotted {built.get('plotted_current_season', 0)}"
        )
        people_new = built.get("review_people_new", 0)
        teams_unresolved = built.get("review_unresolved_teams", 0)
        bowls = built.get("bowls_missing", 0) + built.get("bowls_no_franchise", 0)
        print(
            f"review: people new {people_new}, unresolved teams {teams_unresolved}, "
            f"bowls missing {bowls}"
        )
        counts.update({f"build_{key}": int(value) for key, value in built.items()})

        if blocked:
            items.append(build_blocked(len(outcome.reasons)))
        if people_new > 0:
            items.append(people_review_due(people_new))
        if teams_unresolved > 0:
            items.append(unresolved_teams(teams_unresolved))
        if bowls > 0:
            items.append(bowls_missing(bowls))
        return outcome

    def _run_site_step(self, items: list[AttentionItem]) -> tuple[bool, bool]:
        """Returns (deploy_ready, key_leak)."""
        assert self._site_out is not None
        # WR-01 / D-18: the switch is decided by the data, not the flag alone.
        # Without a valid carry-over the site is CFB-only, so it never ships a
        # switch whose nfl-data.json fetch would 404; the NFL block can still
        # turn the switch on with a fresh file (`_turn_nfl_on`, iter-2 WR-02).
        carry = self._nfl_carry_over() if self._nfl_site else None
        try:
            result: SiteBuildResult = assemble_site(
                source=self._runtime.paths.processed / "site-data.json",
                out_dir=self._site_out,
                site_src=self._site_src or site_source_dir(),
                docs=self._docs or docs_dir(),
                nfl=carry is not None,
                nfl_payload=carry,
            )
        except KeyLeakError:
            items.append(site_key_check_failed())
            return False, True
        if not result.key_checked:
            items.append(site_key_check_skipped())
            return False, False
        print(f"site: {result.telecasts} telecasts, {len(result.files)} files")
        print("cfbd key check: passed")
        return True, False

    def _nfl_carry_over(self) -> tuple[NflSiteData, bytes] | None:
        """The vault's last good nfl-data.json, parsed and validated once, if
        it passes the contract and the key check, else None. `assemble_site`
        gets these exact bytes and never re-reads the file (WR-03).

        Never raises (D-20): every exception, not only the expected ones,
        becomes a count-only item held in `_nfl_carry_items` (joined after the
        CFB result is reported), so CFB's site step is unaffected."""
        held = self._nfl_carry_items
        try:
            return self._load_nfl_carry_over(held)
        except Exception as exc:
            held.append(step_failed("nfl_site", error_type_name(exc)))
            return None

    def _load_nfl_carry_over(self, held: list[AttentionItem]) -> tuple[NflSiteData, bytes] | None:
        assert self._site_out is not None
        carry = self._runtime.paths.processed / "nfl-data.json"
        if not carry.is_file():
            return None
        try:
            payload = load_nfl_site_payload(carry)
        except (SiteBuildError, OSError, ValueError):
            held.append(nfl_site_failed("carry_over_invalid"))
            return None
        try:
            check_nfl_file_key(payload[1], scratch_parent=self._site_out.parent)
        except KeyLeakError:
            held.append(nfl_site_key_check_failed())
            return None
        except OSError:
            held.append(nfl_site_failed("carry_over_invalid"))
            return None
        return payload

    def _note_switch_off(self, items: list[AttentionItem]) -> None:
        """A flag-on site whose sports meta still lists CFB only, after the NFL
        block had its chance to turn the switch on, is one attention item."""
        site = self._site_out
        if site is None or not (site / BUILD_MARKER).is_file():
            return
        if "nfl" not in site_sports(site):
            items.append(nfl_site_switch_off())

    # -- staleness (D-14) -------------------------------------------------------

    def _staleness_step(
        self,
        items: list[AttentionItem],
        last_build_at: datetime | None,
        now: datetime,
        season: int | None,
    ) -> None:
        paths = self._runtime.paths

        def _check() -> None:
            listed_date: date | None = None
            listed_count = 0
            plotted: date | None = None
            if season is not None:
                listed_date, listed_count = newest_listed(paths, season)
                plotted = newest_plotted(paths, season)
            items.extend(
                staleness_items(
                    last_build_at=last_build_at,
                    now=now,
                    season=season,
                    newest_listed=listed_date,
                    listed_count=listed_count,
                    newest_plotted=plotted,
                )
            )

        self._guarded_ok(items, lambda name: step_failed("staleness", name), _check)

    # -- step boundary ---------------------------------------------------------

    @staticmethod
    def _guarded(
        items: list[AttentionItem],
        on_error: Callable[[str], AttentionItem],
        step: Callable[[], _T],
        *,
        passthrough: tuple[type[Exception], ...] = (VaultCommitError,),
    ) -> _T | None:
        """Run one step. Any exception except `passthrough` becomes one
        count-only attention item naming only its class (`on_error`), and
        None is returned so the caller records the step as failed (WR-12)."""
        try:
            return step()
        except passthrough:
            raise
        except Exception as exc:
            items.append(on_error(error_type_name(exc)))
            return None

    @classmethod
    def _guarded_ok(
        cls,
        items: list[AttentionItem],
        on_error: Callable[[str], AttentionItem],
        step: Callable[[], None],
        *,
        passthrough: tuple[type[Exception], ...] = (VaultCommitError,),
    ) -> bool:
        """`_guarded` for a step with no result: True when it completed."""

        def _ran() -> bool:
            step()
            return True

        return cls._guarded(items, on_error, _ran, passthrough=passthrough) is not None

    # -- CFBD step -----------------------------------------------------------

    def _run_cfbd_step(
        self,
        season: int,
        items: list[AttentionItem],
        *,
        endpoints: tuple[str, ...] = JOB_CFBD_REFRESH,
        include_once: bool = True,
    ) -> tuple[bool, bool, dict[str, int]]:
        """Returns (failed, transient, counts); `transient` marks a failure
        the next backup slot should retry (`_is_transient_cfbd_error`)."""
        assert self._runtime.budget is not None
        collector = CfbdCollector(self._runtime.cache, self._runtime.budget, self._token)
        before = dict(self._runtime.cache.counters)
        summaries: list[BatchSummary] = []
        failed = False
        transient = False

        try:
            if not self._dry_run:
                # A new month has no ledger line yet; /info records one so the
                # data calls below aren't refused with BudgetUnknownError.
                collector.ensure_budget_known()
            summaries.append(collector.run(season, endpoints, dry_run=self._dry_run, refresh=True))
            if include_once:
                summaries.append(collector.run(season, JOB_CFBD_ONCE, dry_run=self._dry_run))
        except VaultCommitError:
            raise
        except Exception as exc:
            failed = True
            transient = _is_transient_cfbd_error(exc)
            items.append(cfbd_step_failed(error_type_name(exc)))

        # run_requests records a 4xx (other than 429) as failed and carries on
        # without raising, so a revoked key (401) never reaches the except
        # above; count those failures here so they still need attention.
        failed_calls = sum(summary.failed for summary in summaries)
        if failed_calls:
            failed = True
            items.append(cfbd_failed(failed_calls))

        counts = (
            _sum_batch_counts(summaries)
            if summaries
            else _partial_counts(before, self._runtime.cache.counters)
        )

        if self._dry_run:
            planned = sum(summary.cfbd_calls for summary in summaries)
            print(f"cfbd: planned {planned}")
        else:
            print(
                f"cfbd: fetched {counts['fetched']}, cached {counts['cached']}, "
                f"not_modified {counts['not_modified']}, failed {counts['failed']}"
            )
            if self._commit_enabled:
                try:
                    self._runtime.vault.commit_batch(
                        batch_message("job", "cfbd", str(season), counts),
                        paths=[
                            "raw/cfbd",
                            "raw/_robots",
                            "ledger/requests.jsonl",
                            "ledger/cfbd_ledger.jsonl",
                        ],
                    )
                except VaultCommitError:
                    items.append(push_failed("cfbd"))
                    raise

        return failed, transient, counts

    # -- Ratings Reference refresh step ---------------------------------------

    def _run_rr_step(
        self, current_season: int, items: list[AttentionItem]
    ) -> tuple[bool, dict[str, int]]:
        collector = RatingsRefCollector(
            self._runtime.cache, self._runtime.paths, lock=self._runtime.vault.lock, now=self._now
        )
        season_label = f"{FIRST_SEASON}-{current_season}"
        before = dict(self._runtime.cache.counters)
        summary: RefreshSummary | None = None
        failed = False

        try:
            summary = collector.refresh(
                current_season=current_season, cap=self._rr_cap, dry_run=self._dry_run
            )
        except VaultCommitError:
            raise
        except Exception as exc:
            failed = True
            items.append(rr_step_failed(error_type_name(exc)))

        if summary is not None:
            counts = summary.counts()
            if summary.backlog > 0:
                items.append(rr_backlog(summary.backlog, self._rr_cap))
            if summary.failed > 0:
                items.append(rr_failed(summary.failed))
        else:
            counts = _partial_refresh_counts(before, self._runtime.cache.counters)

        if self._dry_run:
            if summary is not None:
                print(
                    f"ratingsref: qualifying {summary.qualifying}, selected {summary.selected}, "
                    f"backlog {summary.backlog}"
                )
        else:
            print(
                f"ratingsref: fetched {counts['fetched']}, "
                f"not_modified {counts['not_modified']}, failed {counts['failed']}"
            )
            if self._commit_enabled:
                try:
                    self._runtime.vault.commit_batch(
                        batch_message("job", "ratingsref", season_label, counts),
                        paths=[
                            "raw/ratingsref",
                            "raw/_robots",
                            "ledger/requests.jsonl",
                            "ledger/rr_lastmod.json",
                            "ledger/rr_lastmod.jsonl",
                        ],
                    )
                except VaultCommitError:
                    items.append(push_failed("ratingsref"))
                    raise

        return failed, counts

    # -- 506 gap report (read-only; the job never sends 506 a request) --------

    def _run_506_gap_step(self, season: int, now: datetime, items: list[AttentionItem]) -> None:
        games_path = self._runtime.paths.raw / "cfbd" / "games" / f"{season}.json"
        if not games_path.is_file():
            return
        try:
            games = parse_games(games_path.read_bytes())
        except ParseError:
            return

        gaps = find_506_gaps(self._runtime.paths, season, games, now)
        print(f"sports506: missing {len(gaps.missing)}, stale {len(gaps.stale)}")
        if gaps.missing:
            items.append(sports506_missing(season, gaps.missing))
        if gaps.stale:
            items.append(sports506_stale(season, gaps.stale))

    # -- ESPN Press Room reminder (04.19 D-14; read-only, never fetches the site) --

    def _run_espnpr_gap_step(self, season: int, now: datetime, items: list[AttentionItem]) -> None:
        games_path = self._runtime.paths.raw / "cfbd" / "games" / f"{season}.json"
        if not games_path.is_file():
            return
        try:
            games = parse_games(games_path.read_bytes())
        except ParseError:
            return

        if espnpr_page_week(games, season, now) is None:
            print("espnpr: no current week")
            return
        label = find_espnpr_gap(self._runtime.paths, season, games, now)
        if label is None:
            print("espnpr: current week saved")
            return
        print(f"espnpr: week {label} not saved")
        items.append(espnpr_week_unsaved(season, label))

    # -- past-freeze check (IN-02: every run, not only off-season) ---------------

    def _check_past_freeze(self, today: date, items: list[AttentionItem]) -> None:
        guard = FreezeGuard.load(self._runtime.paths.frozen)
        for past_season in range(FIRST_SEASON, season_of(today) + 1):
            if not is_past_freeze_date(past_season, today):
                continue
            if not all(guard.is_frozen(source, past_season) for source in SOURCES):
                items.append(season_past_freeze(past_season, freeze_date(past_season)))

    # -- NFL block (999.4 D-07 to D-10; isolated from CFB, D-08) -----------------

    def _run_nfl_phase(
        self,
        now: datetime,
        window_season: int,
        items: list[AttentionItem],
        nfl_counts: dict[str, int],
        mode: RunMode = "full",
    ) -> None:
        """The NFL block, then its own report line. Any exception becomes an
        attention item; a skipped block (CFB-only vault, off-season) writes nothing."""
        first = len(items)
        label = window_season
        try:
            ran = self._run_nfl_block(now, items, nfl_counts, mode)
        except Exception as exc:
            items.append(step_failed("nfl", error_type_name(exc)))
        else:
            if ran is None:
                return
            label = ran
        if self._dry_run:
            return
        nfl_items = items[first:]
        self._guarded_ok(
            items,
            lambda name: step_failed("nfl_state", name),
            lambda: self._save_nfl_report(now, label, nfl_items, nfl_counts, items),
            passthrough=(),
        )

    def _save_nfl_report(
        self,
        now: datetime,
        season: int,
        nfl_items: Sequence[AttentionItem],
        nfl_counts: dict[str, int],
        items: list[AttentionItem],
    ) -> None:
        """Append the NFL block's count-only report line and commit it alone.
        A failed push is an attention item, never re-raised (D-08)."""
        paths = self._runtime.paths
        attention = sum(1 for item in nfl_items if item.severity == "attention")
        report = {
            "run_at": now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "trigger": self._trigger,
            "update": self._update,
            "attention": attention,
            "counts": dict(nfl_counts),
        }
        with (paths.ledger / NFL_RUN_REPORTS).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(report, sort_keys=True) + "\n")
        self._nfl_commit(
            "nfl_state", str(season), {"attention": attention}, [f"ledger/{NFL_RUN_REPORTS}"], items
        )

    def _run_nfl_block(
        self,
        now: datetime,
        items: list[AttentionItem],
        counts: dict[str, int],
        mode: RunMode = "full",
    ) -> int | None:
        """Every NFL step, each guarded with no passthrough. Skipped (None)
        until the vault is NFL-bootstrapped and outside the NFL collectable
        season; otherwise returns the NFL season it ran for. A "schedule" run
        does only the nflverse schedule, a "rebuild" run only the build and
        site (D-17)."""
        paths = self._runtime.paths
        if not (paths.raw / NFLVERSE_SCHEDULES_PATH).is_file():
            return None
        nfl_season = nfl_collectable_season(now.astimezone(EASTERN).date())
        if nfl_season is None:
            return None

        def _merge(prefix: str, result: dict[str, int] | None) -> None:
            if result is not None:
                counts.update({f"nfl_{prefix}{key}": value for key, value in result.items()})

        if mode != "rebuild":
            _merge(
                "schedules_",
                self._guarded(
                    items,
                    lambda name: step_failed("nflverse", name),
                    lambda: self._nfl_schedules_step(nfl_season, items),
                    passthrough=(),
                ),
            )
        if mode == "full":
            _merge(
                "pbp_",
                self._guarded(
                    items,
                    lambda name: step_failed("nflverse", name),
                    lambda: self._nfl_pbp_step(nfl_season, now, items),
                    passthrough=(),
                ),
            )
            _merge(
                "rr_",
                self._guarded(
                    items,
                    lambda name: step_failed("nfl_rr", name),
                    lambda: self._nfl_rr_step(nfl_season, items),
                    passthrough=(),
                ),
            )
            _merge(
                "wikipedia_",
                self._guarded(
                    items,
                    lambda name: step_failed("nfl_wikipedia", name),
                    lambda: self._nfl_wikipedia_step(nfl_season, items),
                    passthrough=(),
                ),
            )
            _merge(
                "",
                self._guarded(
                    items,
                    lambda name: step_failed("nfl_gaps", name),
                    lambda: self._nfl_gaps_step(nfl_season, now, items),
                    passthrough=(),
                ),
            )
            _merge(
                "",
                self._guarded(
                    items,
                    lambda name: step_failed("nfl_freeze", name),
                    lambda: self._nfl_checks_step(nfl_season, now, items),
                    passthrough=(),
                ),
            )
        if self._update and not self._dry_run:
            _merge(
                "build_",
                self._guarded(
                    items,
                    lambda name: step_failed("nfl_build", name),
                    lambda: self._nfl_build_step(nfl_season, now, items),
                    passthrough=(),
                ),
            )
            if self._nfl_site:
                _merge(
                    "site_",
                    self._guarded(
                        items,
                        lambda name: step_failed("nfl_site", name),
                        lambda: self._nfl_site_step(items),
                        passthrough=(),
                    ),
                )
        return nfl_season

    def _nfl_commit(
        self,
        step: str,
        label: str,
        counts: dict[str, int],
        commit_paths: Sequence[str],
        items: list[AttentionItem],
    ) -> None:
        """Commit one NFL step's own paths. A failed push is an attention item,
        never re-raised (D-08)."""
        if self._dry_run or not self._commit_enabled:
            return
        before = self._runtime.vault.head()
        try:
            self._runtime.vault.commit_batch(
                batch_message("job", step, label, counts), paths=list(commit_paths)
            )
        except VaultCommitError:
            items.append(push_failed(step))
            self._drop_unpushed_nfl(before)

    def _drop_unpushed_nfl(self, before: str | None) -> None:
        """Roll back the NFL commit whose push just failed (CR-02). The files
        stay on disk for the next run's commit. Never raises: the push_failed
        item already reports the failure (D-08), and a CFB commit that was never
        pushed is never touched (drop_unpushed_since checks that)."""
        if before is None:
            return
        with contextlib.suppress(VaultCommitError):
            self._runtime.vault.drop_unpushed_since(before)

    def _nfl_collect(
        self,
        step: str,
        label: str,
        commit_paths: Sequence[str],
        items: list[AttentionItem],
        collect: Callable[[], dict[str, int]],
    ) -> dict[str, int]:
        """Run `collect` and commit its paths. On an exception, commit what was
        written so far (partial counts) and re-raise for the step guard, so no
        NFL line in the shared request ledger is left for a CFB commit."""
        cache = self._runtime.cache
        before = dict(cache.counters)
        try:
            result = collect()
        except Exception:
            self._nfl_commit(
                step, label, _partial_counts(before, cache.counters), commit_paths, items
            )
            raise
        self._nfl_commit(step, label, result, commit_paths, items)
        return result

    def _nflverse_collector(self) -> NflverseCollector:
        return NflverseCollector(
            self._runtime.cache,
            self._runtime.paths,
            lock=self._runtime.vault.lock,
            now=self._now,
            token=self._github_token,
        )

    def _nfl_schedules_step(self, season: int, items: list[AttentionItem]) -> dict[str, int]:
        def _collect() -> dict[str, int]:
            summary = self._nflverse_collector().run_schedules(refresh=True, dry_run=self._dry_run)
            if summary.failed > 0:
                items.append(step_failed("nflverse", "FetchError"))
            return summary.counts()

        result = self._nfl_collect(
            "nfl_schedules", str(season), _NFL_SCHEDULES_PATHS, items, _collect
        )
        print(f"nfl schedules: fetched {result['fetched']}, not_modified {result['not_modified']}")
        return result

    def _nfl_pbp_step(
        self, season: int, now: datetime, items: list[AttentionItem]
    ) -> dict[str, int]:
        weekday = now.astimezone(EASTERN).weekday()
        if self._trigger != "manual" and weekday not in NFL_PBP_REFRESH_WEEKDAYS:
            print("nfl pbp: skipped (Wednesday/Thursday slots only)")
            return {"skipped": 1}

        def _collect() -> dict[str, int]:
            summary = self._nflverse_collector().run_pbp([season], dry_run=self._dry_run)
            if summary.failed > 0:
                items.append(step_failed("nflverse", "FetchError"))
            full = summary.counts()
            return {
                "fetched": full["fetched"],
                "unchanged": full["unchanged"],
                "not_modified": full["not_modified"],
                "failed": full["failed"],
            }

        result = self._nfl_collect("nfl_pbp", str(season), _NFL_PBP_PATHS, items, _collect)
        print(f"nfl pbp: fetched {result['fetched']}, unchanged {result['unchanged']}")
        return result

    def _nfl_rr_step(self, season: int, items: list[AttentionItem]) -> dict[str, int]:
        collector = RatingsRefCollector(
            self._runtime.cache,
            self._runtime.paths,
            lock=self._runtime.vault.lock,
            now=self._now,
            league="nfl",
        )

        def _collect() -> dict[str, int]:
            summary = collector.refresh(
                current_season=season, cap=self._nfl_rr_cap, dry_run=self._dry_run
            )
            if summary.backlog > 0:
                items.append(nfl_rr_backlog(summary.backlog, self._nfl_rr_cap))
            if summary.failed > 0:
                items.append(step_failed("nfl_rr", "FetchError"))
            return summary.counts()

        result = self._nfl_collect(
            "nfl_rr", f"{NFL_FIRST_SEASON}-{season}", _NFL_RR_PATHS, items, _collect
        )
        print(
            f"nfl ratingsref: fetched {result['fetched']}, not_modified {result['not_modified']}, "
            f"backlog {result['backlog']}"
        )
        return result

    def _nfl_wikipedia_step(self, season: int, items: list[AttentionItem]) -> dict[str, int]:
        def _collect() -> dict[str, int]:
            summaries = WikipediaCollector(self._runtime.cache).run(
                [season], refresh=True, dry_run=self._dry_run
            )
            totals = _sum_batch_counts(summaries)
            if totals["failed"] > 0:
                items.append(step_failed("nfl_wikipedia", "FetchError"))
            return totals

        result = self._nfl_collect(
            "nfl_wikipedia", str(season), _NFL_WIKIPEDIA_PATHS, items, _collect
        )
        print(f"nfl wikipedia: fetched {result['fetched']}, not_modified {result['not_modified']}")
        return result

    def _nfl_gaps_step(
        self, season: int, now: datetime, items: list[AttentionItem]
    ) -> dict[str, int]:
        """Read-only: which played NFL 506 weeks need a hand-save (D-10)."""
        gaps = find_nfl_506_gaps(self._runtime.paths, season, now)
        if gaps is None:
            return {}
        print(f"nfl 506: missing {len(gaps.missing)}, stale {len(gaps.stale)}")
        if gaps.missing:
            items.append(nfl_506_missing(season, gaps.missing))
        if gaps.stale:
            items.append(nfl_506_stale(season, gaps.stale))
        return {"506_missing": len(gaps.missing), "506_stale": len(gaps.stale)}

    def _nfl_checks_step(
        self, season: int, now: datetime, items: list[AttentionItem]
    ) -> dict[str, int]:
        """Read-only: frozen-season schedule drift and unfrozen past-freeze seasons (D-11)."""
        drifted = schedule_drift(self._runtime.paths)
        if drifted:
            items.append(nfl_schedule_drift(len(drifted)))
        today = now.astimezone(EASTERN).date()
        guard = FreezeGuard.load(self._runtime.paths.frozen)
        past = 0
        for past_season in range(NFL_FIRST_SEASON, season):
            if today < nfl_freeze_date(past_season):
                continue
            if not all(guard.is_frozen(source, past_season) for source in NFL_SOURCES):
                items.append(nfl_season_past_freeze(past_season, nfl_freeze_date(past_season)))
                past += 1
        print(f"nfl checks: drifted {len(drifted)}, past freeze {past}")
        return {"schedule_drift": len(drifted), "past_freeze": past}

    def _nfl_build_step(
        self, season: int, now: datetime, items: list[AttentionItem]
    ) -> dict[str, int]:
        """Update mode only: rebuild the NFL tables in the vault (no site, no deploy)."""
        before = self._runtime.vault.head() if self._commit_enabled else None
        try:
            outcome = run_nfl_build(
                self._runtime.paths,
                self._reference_directory or reference_dir(),
                seasons=list(range(NFL_FIRST_SEASON, season + 1)),
                include_playoffs=False,
                commit=self._commit_enabled,
                check_acceptance=False,
                now=now,
                site_data=self._nfl_site,
            )
        except VaultCommitError:
            items.append(push_failed("nfl_build"))
            self._drop_unpushed_nfl(before)
            return {}
        built = {key: int(value) for key, value in outcome.counts.items()}
        unresolved = built.get("unresolved_crew_names", 0)
        print(
            f"nfl build: games {built.get('games', 0)}, standalone {built.get('standalone', 0)}, "
            f"blocked {'yes' if outcome.blocked else 'no'}, crew names to review {unresolved}"
        )
        if outcome.blocked:
            items.append(nfl_build_blocked(built.get("override_errors", 0)))
        if unresolved > 0:
            items.append(nfl_review_due(unresolved))
        if built.get("site_data_failed"):
            items.append(nfl_site_failed("invalid"))
        return built

    def _nfl_site_step(self, items: list[AttentionItem]) -> dict[str, int]:
        """Replace the site dir's nfl-data.json with the freshly built vault
        file. Every failure keeps whatever file the site dir already holds.

        A site built without the switch (the vault carry-over was missing or
        unusable at CFB's site step, WR-01) gets the switch, the NFL modules
        and the file now, once the fresh vault file validates and passes the
        key check (iter-2 WR-02, D-20), so a one-off vault-side failure never
        hides NFL. A failure leaves the switch-less CFB site exactly as built."""
        site = self._site_out
        if site is None or not (site / BUILD_MARKER).is_file():
            return {}
        source = self._runtime.paths.processed / "nfl-data.json"
        if not source.is_file():
            items.append(nfl_site_failed("missing"))
            return {}
        if "nfl" not in site_sports(site):
            return self._turn_nfl_on(site, source, items)
        try:
            result = refresh_nfl_data(site_out=site, source=source)
        except KeyLeakError:
            items.append(nfl_site_key_check_failed())
            return {}
        except SiteBuildError:
            items.append(nfl_site_failed("invalid"))
            return {}
        if not result.replaced:
            items.append(nfl_site_key_check_failed())
            return {}
        print(f"nfl site: {result.games} games")
        return {"games": result.games}

    def _turn_nfl_on(self, site: Path, source: Path, items: list[AttentionItem]) -> dict[str, int]:
        """Add the NFL switch and the fresh vault file to a switch-less site."""
        try:
            payload = load_nfl_site_payload(source)
        except (SiteBuildError, OSError, ValueError):
            items.append(nfl_site_failed("invalid"))
            return {}
        try:
            result = add_nfl_to_site(
                site_out=site,
                site_src=self._site_src or site_source_dir(),
                docs=self._docs or docs_dir(),
                nfl_payload=payload,
            )
        except KeyLeakError:
            items.append(nfl_site_key_check_failed())
            return {}
        except SiteBuildError:
            items.append(nfl_site_failed("invalid"))
            return {}
        if not result.replaced:
            items.append(nfl_site_key_check_failed())
            return {}
        print(f"nfl site: {result.games} games, switch on")
        return {"games": result.games, "switch_on": 1}

    # -- state save ------------------------------------------------------------

    def _save_state(
        self,
        state: JobState,
        window: CatchupWindow,
        window_season: int,
        items: list[AttentionItem],
        report: dict[str, object],
    ) -> None:
        paths = self._runtime.paths
        save_state(paths.job_state, state)
        # One count-only line per run (ints, bools, null, fixed strings only).
        with (paths.ledger / "run_reports.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(report, sort_keys=True) + "\n")
        if self._commit_enabled:
            attention_count = sum(1 for item in items if item.severity == "attention")
            season_label = str(window_season)
            self._runtime.vault.commit_batch(
                batch_message(
                    "job",
                    "state",
                    season_label,
                    {"missed": window.missed_slots, "attention": attention_count},
                ),
                paths=["ledger/job_state.json", "ledger/run_reports.jsonl"],
            )
