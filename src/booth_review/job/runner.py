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
item exists, exit 0 on a clean run).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from booth_review.audit.completeness import SOURCES
from booth_review.config import CFBD_FLOOR_DEFAULT
from booth_review.errors import BoothReviewError, ParseError, VaultCommitError, VaultStateError
from booth_review.job.attention import (
    AttentionItem,
    cfbd_remaining,
    cfbd_step_failed,
    has_attention,
    missed_runs,
    push_failed,
    rr_backlog,
    rr_failed,
    rr_step_failed,
    season_past_freeze,
    sports506_missing,
    sports506_stale,
)
from booth_review.job.catchup import (
    CatchupWindow,
    JobState,
    Trigger,
    catchup_window,
    collectable_season,
    load_state,
    save_state,
)
from booth_review.job.gaps506 import find_506_gaps
from booth_review.runtime import Runtime
from booth_review.seasons import freeze_date, season_of
from booth_review.sources.base import BatchSummary
from booth_review.sources.cfbd.collector import CfbdCollector
from booth_review.sources.cfbd.parser import parse_games
from booth_review.sources.ratingsref.collector import (
    FIRST_SEASON,
    REFRESH_CAP_DEFAULT,
    RatingsRefCollector,
    RefreshSummary,
)
from booth_review.transport.cache import FreezeGuard
from booth_review.vault import batch_message

# The season-level CFBD endpoints the job re-fetches every run (D-09), plus
# the once-per-season set fetched only until cached. Never includes anything
# outside CfbdCollector.plan's own allow-listed endpoint names.
JOB_CFBD_REFRESH: tuple[str, ...] = ("games", "media", "lines", "wp_pregame", "rankings")
JOB_CFBD_ONCE: tuple[str, ...] = ("teams_fbs",)

# A default run-cap for the job's CFBD calls: 5 refresh endpoints + 1 once
# endpoint (uncached worst case) plus headroom, well under the monthly budget
# at 2 runs/week (Claude's Discretion; CONTEXT.md's ~45 calls/month estimate).
JOB_CFBD_MAX_CALLS = 8

# Vault state files the job refuses to run without (VaultStateError, exit 3):
# a missing file never falls back to treating the vault as empty/new.
REQUIRED_LEDGER_FILES: tuple[str, ...] = ("rr_lastmod.json", "cfbd_ledger.jsonl", "frozen.json")


@dataclass(frozen=True)
class JobRunResult:
    """The outcome of one ScheduledJob.run() call."""

    exit_code: int
    items: list[AttentionItem]
    counts: dict[str, int]
    window: CatchupWindow | None


def _check_required_state(runtime: Runtime) -> None:
    paths = runtime.paths
    missing = [name for name in REQUIRED_LEDGER_FILES if not (paths.ledger / name).is_file()]
    if missing:
        raise VaultStateError(
            "job refuses to run: required vault state file(s) missing: "
            + ", ".join(f"ledger/{name}" for name in missing)
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
    ) -> None:
        self._runtime = runtime
        self._token = token
        self._now = now
        self._trigger = trigger
        self._rr_cap = rr_cap
        self._dry_run = dry_run
        self._commit_enabled = commit

    # -- public entry point ------------------------------------------------

    def run(self) -> JobRunResult:
        _check_required_state(self._runtime)

        paths = self._runtime.paths
        now = self._now()
        today = now.date()
        state = load_state(paths.job_state)

        season = collectable_season(today)
        rr_current_season = season_of(today)
        window_season = season if season is not None else rr_current_season
        window = catchup_window(state, now, window_season, self._trigger)

        items: list[AttentionItem] = []
        counts: dict[str, int] = {}
        any_failed = False

        try:
            if season is not None:
                cfbd_failed, cfbd_counts = self._run_cfbd_step(season, items)
                any_failed = any_failed or cfbd_failed
                counts.update({f"cfbd_{key}": value for key, value in cfbd_counts.items()})

            rr_failed, rr_counts = self._run_rr_step(rr_current_season, items)
            any_failed = any_failed or rr_failed
            counts.update({f"rr_{key}": value for key, value in rr_counts.items()})

            if season is not None:
                self._run_506_gap_step(season, now, items)
            else:
                self._check_past_freeze(rr_current_season, items)

            if window.missed_slots > 0:
                items.append(missed_runs(window.missed_slots))

            if self._runtime.budget is not None:
                remaining = self._runtime.budget.last_known_remaining(now.strftime("%Y-%m"))
                if remaining is not None:
                    items.append(cfbd_remaining(remaining, CFBD_FLOOR_DEFAULT))
        except VaultCommitError:
            return JobRunResult(exit_code=3, items=items, counts=counts, window=window)

        status = "attention" if has_attention(items) else "ok"

        if not self._dry_run:
            new_state = JobState(
                season=season,
                last_success_at=now if not any_failed else state.last_success_at,
                last_attempt_at=now,
                last_status=status,
                last_window_start=window.start,
            )
            try:
                self._save_state(new_state, window, window_season, items)
            except VaultCommitError:
                return JobRunResult(exit_code=3, items=items, counts=counts, window=window)

        exit_code = 4 if status == "attention" else 0
        return JobRunResult(exit_code=exit_code, items=items, counts=counts, window=window)

    # -- CFBD step -----------------------------------------------------------

    def _run_cfbd_step(
        self, season: int, items: list[AttentionItem]
    ) -> tuple[bool, dict[str, int]]:
        assert self._runtime.budget is not None
        collector = CfbdCollector(self._runtime.cache, self._runtime.budget, self._token)
        before = dict(self._runtime.cache.counters)
        summaries: list[BatchSummary] = []
        failed = False

        try:
            summaries.append(
                collector.run(season, JOB_CFBD_REFRESH, dry_run=self._dry_run, refresh=True)
            )
            summaries.append(collector.run(season, JOB_CFBD_ONCE, dry_run=self._dry_run))
        except VaultCommitError:
            raise
        except BoothReviewError as exc:
            failed = True
            items.append(cfbd_step_failed(type(exc).__name__))

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

        return failed, counts

    # -- Ratings Reference refresh step ---------------------------------------

    def _run_rr_step(
        self, current_season: int, items: list[AttentionItem]
    ) -> tuple[bool, dict[str, int]]:
        collector = RatingsRefCollector(self._runtime.cache, self._runtime.paths)
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
        except BoothReviewError as exc:
            failed = True
            items.append(rr_step_failed(type(exc).__name__))

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

    # -- off-season past-freeze check -----------------------------------------

    def _check_past_freeze(self, past_season: int, items: list[AttentionItem]) -> None:
        guard = FreezeGuard.load(self._runtime.paths.frozen)
        if not all(guard.is_frozen(source, past_season) for source in SOURCES):
            items.append(season_past_freeze(past_season, freeze_date(past_season)))

    # -- state save ------------------------------------------------------------

    def _save_state(
        self,
        state: JobState,
        window: CatchupWindow,
        window_season: int,
        items: list[AttentionItem],
    ) -> None:
        paths = self._runtime.paths
        save_state(paths.job_state, state)
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
                paths=["ledger/job_state.json"],
            )
