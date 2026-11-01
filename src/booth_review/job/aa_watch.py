"""Phase 25 job-side resolver for the Tuesday AA schedule reminder (D-01 to D-13).

`reminders.py` stays network-free; the scheduled job builds this resolver and passes
it to `due_reminders(..., aa_cfb=resolver)`. The resolver makes at most one
conditional feed request per run (memoized), applies the policy gate (the job never
runs a policy check), and yields exactly one comment per week: a link line when the
feed shows the week's post, or the plain blind line at the last poll. A week whose
blind line went out is recorded, so later runs that week repeat only that line
(which the workflow's WR-07 compare suppresses) and never post a different one.

Once the week's post link is known the resolver also fetches the post itself through
`fetch_week_crews` (D-01), sharing a two-request cap with the feed check. The feed
response is never cached; the crews response is. Crews errors never fail the run.

The watch ends with the 2026 season (D-13): any other season gets only the Phase 24
blind line, with no state read, policy read, request, mark or commit.
"""

from __future__ import annotations

import logging
import weakref
from datetime import datetime, time
from typing import Literal
from zoneinfo import ZoneInfo

from booth_review.errors import BoothReviewError, RobotsDisallowedError, VaultStateError
from booth_review.job.attention import (
    AttentionItem,
    aa_crews_skipped,
    aa_feed_blocked,
    aa_feed_policy_stale,
    aa_feed_unverified,
    reminder_aa_cfb,
    reminder_aa_cfb_link,
)
from booth_review.job.reminders import AaCfbResolver
from booth_review.runtime import Runtime
from booth_review.sources.aa.crews import fetch_week_crews
from booth_review.sources.aa.feed import (
    check_week,
    crews_rechecked,
    load_feed_state,
    record_blind_week,
    record_crews_recheck,
    week_key,
)
from booth_review.sources.policy import PolicyRobotsError, policy_fresh, robots_guard
from booth_review.vault import batch_message

EASTERN = ZoneInfo("America/New_York")

# D-11: the blind fallback happens only at the last poll, the 22:30 ET backup run.
# The 21:30 cron can be delayed, so a run before 22:25 ET is never the last poll;
# only the 22:30 backup (or later) falls back to the blind line.
LAST_POLL_LOCAL = time(22, 25)

# D-13 and the AGENTS.md bullet: the watch ends with the 2026 season.
AA_WATCH_SEASON = 2026

_LOG = logging.getLogger(__name__)

# D-01 and the AGENTS.md rule: at most two AA requests per run, feed check included.
AA_MAX_REQUESTS_PER_RUN = 2

# A Friday/Saturday schedule run may start late; this many hours after the slot hour
# still counts as that slot for the conditional crews re-check.
CREWS_RECHECK_WINDOW_HOURS = 3

_GUARDED_CLIENTS: weakref.WeakSet[object] = weakref.WeakSet()


def install_aa_guard(runtime: Runtime) -> None:
    """Install the AA robots guard on the runtime's client once."""
    if runtime.client in _GUARDED_CLIENTS:
        return
    runtime.client.add_robots_listener(robots_guard("aa"))
    _GUARDED_CLIENTS.add(runtime.client)


def run_crews_fetch(
    runtime: Runtime,
    *,
    season: int,
    label: str,
    now: datetime,
    mode: Literal["if_missing", "conditional", "recheck"],
    budget: int,
    commit: bool,
    recheck_slot: str | None = None,
) -> list[AttentionItem]:
    """One crews fetch plus its commit; returns attention lines. It never raises.

    With `recheck_slot` (the Friday/Saturday re-check, ET `YYYY-MM-DDTHH`), the slot
    is recorded in the feed-watch state just before its one request goes out, and a
    later run in the same slot sends nothing (Phase 27 review WR-02)."""
    marked: list[str] = []
    sent: list[bool] = []

    def mark_slot() -> None:
        sent.append(True)
        if recheck_slot is not None and record_crews_recheck(runtime.paths, recheck_slot):
            marked.append(_FEED_STATE)

    def commit_paths(paths: list[str]) -> None:
        if not commit:
            return
        try:
            runtime.vault.commit_batch(
                batch_message("job", "aa", "crews", {"requests": 1}), paths=[*paths, *marked]
            )
        except BoothReviewError as exc:
            _LOG.warning("aa crews: commit failed: %s", type(exc).__name__)

    try:
        if recheck_slot is not None and crews_rechecked(runtime.paths, recheck_slot):
            return []
        install_aa_guard(runtime)
        result = fetch_week_crews(
            runtime.cache,
            runtime.paths,
            season=season,
            label=label,
            now=now,
            mode=mode,
            budget=budget,
            on_request=mark_slot,
        )
    except (RobotsDisallowedError, PolicyRobotsError) as exc:
        _LOG.warning("aa crews: blocked: %s", type(exc).__name__)
        if sent:
            commit_paths(_FAILED_REQUEST_PATHS)
        return [aa_crews_skipped("robots")]
    except Exception as exc:
        # Phase 27 review WR-03: a failed request (HTTP error, a post that fails
        # validation, ...) still appended its audit line; commit it, as the CLI
        # does, and say so in a fixed line with no URL or page text.
        _LOG.warning("aa crews: %s", type(exc).__name__)
        if sent:
            commit_paths(_FAILED_REQUEST_PATHS)
        return [aa_crews_skipped("error")]
    items: list[AttentionItem] = []
    if result.outcome == "stale_policy":
        items.append(aa_crews_skipped("policy"))
    elif result.outcome == "not_cached":
        items.append(aa_crews_skipped("not_cached"))
    elif result.outcome == "no_validator":
        items.append(aa_crews_skipped("no_validator"))
    if result.requests:
        commit_paths(list(result.touched))
    return items


_FEED_STATE = "ledger/aa_feed_watch.json"
# What a failed crews request leaves behind: its audit line and the robots copy.
_FAILED_REQUEST_PATHS = ["ledger/requests.jsonl", "raw/_robots/awfulannouncing.com"]

_REQUEST_PATHS = [
    "ledger/aa_feed_watch.json",
    "ledger/requests.jsonl",
    "raw/_robots/awfulannouncing.com",
]
_MARK_PATHS = ["ledger/aa_feed_watch.json"]


def make_aa_cfb_resolver(runtime: Runtime, *, commit: bool) -> AaCfbResolver:
    """A resolver for the Tuesday AA slot. It never raises."""
    memo: dict[tuple[int, str], list[AttentionItem]] = {}

    def resolve(season: int, label: str, now: datetime) -> list[AttentionItem]:
        key = (season, label)
        if key not in memo:
            memo[key] = _resolve(season, label, now)
        return list(memo[key])

    def _resolve(season: int, label: str, now: datetime) -> list[AttentionItem]:
        if season != AA_WATCH_SEASON:
            return [reminder_aa_cfb(season, label)]

        paths = runtime.paths
        wkey = week_key(season, label)
        last_poll = now.astimezone(EASTERN).time() >= LAST_POLL_LOCAL
        marked_new = False
        requested = False

        def blind(*extra: AttentionItem) -> list[AttentionItem]:
            nonlocal marked_new
            try:
                if wkey in load_feed_state(paths).weeks:
                    return [reminder_aa_cfb(season, label), *extra]
                if record_blind_week(paths, season=season, label=label):
                    marked_new = True
            except (VaultStateError, OSError) as exc:
                _LOG.warning("aa feed watch: blind mark failed: %s", type(exc).__name__)
            return [reminder_aa_cfb(season, label), *extra]

        def link(url: str) -> list[AttentionItem]:
            try:
                return [reminder_aa_cfb_link(season, label, url)]
            except ValueError:
                return blind()

        def finish(items: list[AttentionItem]) -> list[AttentionItem]:
            if commit:
                if requested:
                    _commit(_REQUEST_PATHS, {"requests": 1})
                elif marked_new:
                    _commit(_MARK_PATHS, {"blind": 1})
            return items

        def with_crews(items: list[AttentionItem]) -> list[AttentionItem]:
            """Commit the feed paths, then fetch the post within the shared cap."""
            out = finish(items)
            budget = AA_MAX_REQUESTS_PER_RUN - (1 if requested else 0)
            extra = run_crews_fetch(
                runtime,
                season=season,
                label=label,
                now=now,
                mode="if_missing",
                budget=budget,
                commit=commit,
            )
            # The feed path already reports a stale policy; skip the duplicate line.
            return [
                *out,
                *(i for i in extra if i.kind != "aa_crews_skipped_policy" or not requested),
            ]

        def _commit(commit_paths: list[str], counts: dict[str, int]) -> None:
            try:
                runtime.vault.commit_batch(
                    batch_message("job", "aa", "feed", counts), paths=commit_paths
                )
            except BoothReviewError as exc:
                _LOG.warning("aa feed watch: commit failed: %s", type(exc).__name__)

        try:
            state = None
            try:
                state = load_feed_state(paths)
            except VaultStateError as exc:
                _LOG.warning("aa feed watch: state unreadable: %s", type(exc).__name__)
            if state is not None:
                if wkey in state.weeks:
                    return with_crews(link(state.weeks[wkey]))
                if wkey in state.blind_weeks:
                    return [reminder_aa_cfb(season, label)]

                try:
                    fresh = policy_fresh(paths, "aa", now)
                except VaultStateError:
                    fresh = False
                if not fresh:
                    return finish(blind(aa_feed_policy_stale()))
                if state.verified_feed_url is None:
                    return finish(blind(aa_feed_unverified()))

                install_aa_guard(runtime)
                try:
                    requested = True
                    result = check_week(runtime.client, paths, season=season, label=label, now=now)
                except (RobotsDisallowedError, PolicyRobotsError) as exc:
                    _LOG.warning("aa feed watch: blocked: %s", type(exc).__name__)
                    return finish(blind(aa_feed_blocked()))
                except Exception as exc:
                    _LOG.warning("aa feed watch: %s", type(exc).__name__)
                else:
                    requested = result.requested
                    if result.url is not None:
                        return with_crews(link(result.url))
            return finish(blind() if last_poll else [])
        except Exception as exc:
            _LOG.warning("aa feed watch: %s", type(exc).__name__)
            try:
                return finish(blind() if last_poll else [])
            except Exception:
                return [reminder_aa_cfb(season, label)] if last_poll else []

    return resolve
