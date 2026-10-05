"""ScheduledJob: the `booth-review job run` entry point (AUTO-01).

Composes the Plan 04 job modules (catchup, gaps506, attention) with the
existing collectors into one tested, catch-up-aware, count-only collect-only
run for the current season: a CFBD season-level refresh, the Ratings
Reference lastmod refresh, and a report of which 2026 506 week pages need a
hand-save -- never a 506 fetch (D-07/D-08/AUTO-01, Claude's Discretion).

Each step commits its own paths with a count-only message (batch_message);
state (`ledger/job_state.json`) is saved and committed last. A VaultCommitError
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
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TypeVar

from booth_review.audit.completeness import SOURCES
from booth_review.build.pipeline import BuildOutcome, run_build
from booth_review.build.site_assembly import (
    SiteBuildResult,
    assemble_site,
    docs_dir,
    site_source_dir,
)
from booth_review.config import CFBD_FLOOR_DEFAULT
from booth_review.errors import (
    FetchError,
    KeyLeakError,
    ParseError,
    RobotsUnavailableError,
    VaultCommitError,
    VaultStateError,
)
from booth_review.job.attention import (
    AttentionItem,
    bowls_missing,
    build_blocked,
    cfbd_failed,
    cfbd_remaining,
    cfbd_step_failed,
    error_type_name,
    failed_attempts,
    has_attention,
    missed_runs,
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
    CatchupWindow,
    JobState,
    Trigger,
    catchup_window,
    collectable_season,
    is_due,
    load_state,
    save_state,
)
from booth_review.job.gaps506 import find_506_gaps
from booth_review.job.staleness import newest_listed, newest_plotted, staleness_items
from booth_review.reference import reference_dir
from booth_review.runtime import Runtime
from booth_review.seasons import freeze_date, is_past_freeze_date, season_of
from booth_review.sources.base import BatchSummary
from booth_review.sources.cfbd.collector import CfbdCollector
from booth_review.sources.cfbd.parser import parse_games
from booth_review.sources.ratingsref.collector import (
    FIRST_SEASON,
    REFRESH_CAP_DEFAULT,
    RatingsRefCollector,
    RefreshSummary,
)
from booth_review.sources.ratingsref.lastmod import lastmod_ledger_exists
from booth_review.transport.cache import FreezeGuard
from booth_review.vault import batch_message

# The season-level CFBD endpoints the job re-fetches every run (D-09), plus
# the once-per-season set fetched only until cached. Never includes anything
# outside CfbdCollector.plan's own allow-listed endpoint names.
JOB_CFBD_REFRESH: tuple[str, ...] = ("games", "media", "lines", "wp_pregame", "rankings")
JOB_CFBD_ONCE: tuple[str, ...] = ("teams_fbs",)

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
    ) -> None:
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
        self._dry_run = dry_run
        self._commit_enabled = commit

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

        if not is_due(state, now, self._trigger):
            if self._update:
                stale_items: list[AttentionItem] = []
                self._staleness_step(stale_items, state.last_build_at, now, season)
                if has_attention(stale_items):
                    return JobRunResult(
                        exit_code=4,
                        items=stale_items,
                        counts={"skipped": 1},
                        window=window,
                        stale_only=True,
                    )
            return JobRunResult(
                exit_code=EXIT_NOTHING_DUE, items=[], counts={"skipped": 1}, window=window
            )

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

            freeze_ok = self._guarded_ok(
                items,
                lambda name: step_failed("freeze", name),
                lambda: self._check_past_freeze(today, items),
            )
            any_failed = any_failed or not freeze_ok

            if self._update and not self._dry_run:
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
            return JobRunResult(exit_code=3, items=items, counts=counts, window=window)

        deploy_ready = deploy_ready and not key_leak
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
                status = "attention"

        exit_code = 3 if key_leak else (4 if status == "attention" else 0)
        return JobRunResult(
            exit_code=exit_code,
            items=items,
            counts=counts,
            window=window,
            deploy_ready=deploy_ready,
        )

    # -- helpers ---------------------------------------------------------------

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
        try:
            result: SiteBuildResult = assemble_site(
                source=self._runtime.paths.processed / "site-data.json",
                out_dir=self._site_out,
                site_src=self._site_src or site_source_dir(),
                docs=self._docs or docs_dir(),
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
    ) -> bool:
        """`_guarded` for a step with no result: True when it completed."""

        def _ran() -> bool:
            step()
            return True

        return cls._guarded(items, on_error, _ran) is not None

    # -- CFBD step -----------------------------------------------------------

    def _run_cfbd_step(
        self, season: int, items: list[AttentionItem]
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
            summaries.append(
                collector.run(season, JOB_CFBD_REFRESH, dry_run=self._dry_run, refresh=True)
            )
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

    # -- past-freeze check (IN-02: every run, not only off-season) ---------------

    def _check_past_freeze(self, today: date, items: list[AttentionItem]) -> None:
        guard = FreezeGuard.load(self._runtime.paths.frozen)
        for past_season in range(FIRST_SEASON, season_of(today) + 1):
            if not is_past_freeze_date(past_season, today):
                continue
            if not all(guard.is_frozen(source, past_season) for source in SOURCES):
                items.append(season_past_freeze(past_season, freeze_date(past_season)))

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
