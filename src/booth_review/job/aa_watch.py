"""Phase 25 job-side resolver for the Tuesday AA schedule reminder (D-01 to D-13).

`reminders.py` stays network-free; the scheduled job builds this resolver and passes
it to `due_reminders(..., aa_cfb=resolver)`. The resolver makes at most one
conditional feed request per run (memoized), applies the policy gate (the job never
runs a policy check), and yields exactly one comment per week: a link line when the
feed shows the week's post, or the plain blind line at the last poll. A week whose
blind line went out is recorded, so later runs that week repeat only that line
(which the workflow's WR-07 compare suppresses) and never post a different one.

The watch ends with the 2026 season (D-13): any other season gets only the Phase 24
blind line, with no state read, policy read, request, mark or commit.
"""

from __future__ import annotations

import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

from booth_review.errors import BoothReviewError, RobotsDisallowedError, VaultStateError
from booth_review.job.attention import (
    AttentionItem,
    aa_feed_blocked,
    aa_feed_policy_stale,
    aa_feed_unverified,
    reminder_aa_cfb,
    reminder_aa_cfb_link,
)
from booth_review.job.reminders import AaCfbResolver
from booth_review.runtime import Runtime
from booth_review.sources.aa.feed import (
    check_week,
    load_feed_state,
    record_blind_week,
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

_REQUEST_PATHS = [
    "ledger/aa_feed_watch.json",
    "ledger/requests.jsonl",
    "raw/_robots/awfulannouncing.com",
]
_MARK_PATHS = ["ledger/aa_feed_watch.json"]


def make_aa_cfb_resolver(runtime: Runtime, *, commit: bool) -> AaCfbResolver:
    """A resolver for the Tuesday AA slot. It never raises."""
    memo: dict[tuple[int, str], list[AttentionItem]] = {}
    guard_installed = False

    def resolve(season: int, label: str, now: datetime) -> list[AttentionItem]:
        key = (season, label)
        if key not in memo:
            memo[key] = _resolve(season, label, now)
        return list(memo[key])

    def _resolve(season: int, label: str, now: datetime) -> list[AttentionItem]:
        nonlocal guard_installed
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
                    return finish(link(state.weeks[wkey]))
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

                if not guard_installed:
                    runtime.client.add_robots_listener(robots_guard("aa"))
                    guard_installed = True
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
                        return finish(link(result.url))
            return finish(blind() if last_poll else [])
        except Exception as exc:
            _LOG.warning("aa feed watch: %s", type(exc).__name__)
            try:
                return finish(blind() if last_poll else [])
            except Exception:
                return [reminder_aa_cfb(season, label)] if last_poll else []

    return resolve
