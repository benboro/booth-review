"""Job-side AA resolver (Phase 25): gates, one-comment-per-week, season guard, commit.

Synthetic feed and fakes only; no real request is ever made.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import httpx2
import pytest

from booth_review.config import DataPaths
from booth_review.errors import VaultBusyError, VaultCommitError
from booth_review.job.aa_watch import AA_WATCH_SEASON, LAST_POLL_LOCAL, make_aa_cfb_resolver
from booth_review.job.attention import reminder_aa_cfb
from booth_review.job.reminders import due_reminders
from booth_review.sources.aa.feed import (
    AA_FEED_CANDIDATES,
    FeedWatchState,
    load_feed_state,
    save_feed_state,
)
from booth_review.transport.cache import RawCache
from booth_review.transport.client import PoliteClient

ET = ZoneInfo("America/New_York")
FIXTURES = Path(__file__).parent / "fixtures" / "aa"
FEED = (FIXTURES / "feed_schedules_synthetic.xml").read_bytes()
POST = (FIXTURES / "schedule_synthetic.html").read_bytes()
EMPTY_FEED = b'<rss version="2.0"><channel></channel></rss>'
CURRENT = "https://awfulannouncing.com/schedules/your-2026-week-10-college-football-announcing-schedule.html"
T2130 = datetime(2026, 11, 3, 21, 30, tzinfo=ET)
T2230 = datetime(2026, 11, 3, 22, 30, tzinfo=ET)
T2330 = datetime(2026, 11, 3, 23, 30, tzinfo=ET)
FEED_URL = AA_FEED_CANDIDATES["schedules"]


class _Server:
    def __init__(self, feed: bytes = FEED, status: int = 200, robots: bytes | None = None) -> None:
        self.feed = feed
        self.status = status
        self.robots = robots if robots is not None else b"User-agent: *\nAllow: /\n"
        self.feed_requests = 0
        self.robots_requests = 0
        self.post_requests = 0
        self.post_status = 200

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/robots.txt":
            self.robots_requests += 1
            return httpx2.Response(200, content=self.robots)
        if request.url.path == "/schedules/feed/" or "feed" in request.url.path:
            self.feed_requests += 1
            return httpx2.Response(self.status, content=self.feed)
        self.post_requests += 1
        if request.headers.get("If-None-Match") == '"p1"':
            return httpx2.Response(304)
        return httpx2.Response(self.post_status, content=POST, headers={"ETag": '"p1"'})

    @property
    def total(self) -> int:
        return self.feed_requests + self.robots_requests + self.post_requests

    @property
    def aa_requests(self) -> int:
        """Feed plus post requests (robots.txt is not counted against the cap)."""
        return self.feed_requests + self.post_requests


class _Vault:
    def __init__(self, fail: bool = False, exc: Exception | None = None) -> None:
        self.calls: list[tuple[str, list[str]]] = []
        self.fail = fail
        self.exc = exc

    def commit_batch(self, message: str, *, paths: list[str] | None = None, push: bool = True):
        self.calls.append((message, list(paths or [])))
        if self.exc is not None:
            raise self.exc
        if self.fail:
            raise VaultCommitError("boom")
        return True


def _runtime(paths: DataPaths, server: _Server, vault: _Vault | None = None) -> Any:
    client = PoliteClient(
        transport=httpx2.MockTransport(server), clock=lambda: 0.0, sleep=lambda s: None
    )
    return SimpleNamespace(
        paths=paths, client=client, vault=vault or _Vault(), cache=RawCache(paths, client)
    )


def _policy(
    paths: DataPaths, *, now: datetime, age_days: int = 1, terms: bool | None = True
) -> None:
    row = {
        "source": "aa",
        "checked_at": (now - timedelta(days=age_days))
        .astimezone(UTC)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "robots_ok": True,
        "crawl_delay": None,
        "terms_ok": terms,
    }
    ledger = paths.ledger / "policy_checks.jsonl"
    ledger.write_text(json.dumps(row) + "\n", encoding="utf-8")


def _state(paths: DataPaths, **kw: Any) -> None:
    base: dict[str, Any] = {
        "verified_feed_url": FEED_URL,
        "verified_at": None,
        "etag": None,
        "last_modified": None,
        "checked_at": None,
        "weeks": {},
        "blind_weeks": [],
    }
    base.update(kw)
    save_feed_state(paths, FeedWatchState(**base))


def _ready(paths: DataPaths, **kw: Any) -> None:
    _policy(paths, now=T2130)
    _state(paths, **kw)


def _kinds(items: list) -> list[str]:
    return [i.kind for i in items]


BLIND = reminder_aa_cfb(2026, "10")


def test_constants() -> None:
    assert AA_WATCH_SEASON == 2026
    assert (LAST_POLL_LOCAL.hour, LAST_POLL_LOCAL.minute) == (22, 25)


def test_match_yields_link_line_with_one_feed_request(vault_paths: DataPaths) -> None:
    _ready(vault_paths)
    server = _Server()
    items = make_aa_cfb_resolver(_runtime(vault_paths, server), commit=False)(2026, "10", T2130)
    assert _kinds(items) == ["reminder_aa_cfb_link"]
    assert CURRENT in items[0].line and "week 10" in items[0].line
    assert server.feed_requests == 1


def test_no_match_before_last_poll_is_silent_and_unmarked(vault_paths: DataPaths) -> None:
    _ready(vault_paths)
    server = _Server(EMPTY_FEED)
    assert (
        make_aa_cfb_resolver(_runtime(vault_paths, server), commit=False)(2026, "10", T2130) == []
    )
    assert load_feed_state(vault_paths).blind_weeks == []


def test_no_match_at_last_poll_is_blind_and_marked(vault_paths: DataPaths) -> None:
    _ready(vault_paths)
    server = _Server(EMPTY_FEED)
    items = make_aa_cfb_resolver(_runtime(vault_paths, server), commit=False)(2026, "10", T2230)
    assert items == [BLIND]
    assert "https://awfulannouncing.com/schedules/" in items[0].line
    assert load_feed_state(vault_paths).blind_weeks == ["2026-10"]


def test_blind_line_then_later_post_stays_blind_with_zero_requests(vault_paths: DataPaths) -> None:
    _ready(vault_paths)
    first = _Server(EMPTY_FEED)
    assert make_aa_cfb_resolver(_runtime(vault_paths, first), commit=False)(2026, "10", T2230) == [
        BLIND
    ]
    later = _Server(FEED)  # the post now exists
    items = make_aa_cfb_resolver(_runtime(vault_paths, later), commit=False)(2026, "10", T2330)
    assert items == [BLIND]
    assert later.total == 0
    assert "reminder_aa_cfb_link" not in _kinds(items)


def test_week_already_linked_makes_zero_requests(vault_paths: DataPaths) -> None:
    _ready(vault_paths, weeks={"2026-10": CURRENT})
    server = _Server()
    items = make_aa_cfb_resolver(_runtime(vault_paths, server), commit=False)(2026, "10", T2230)
    assert _kinds(items) == ["reminder_aa_cfb_link"] and CURRENT in items[0].line
    assert server.feed_requests == 0  # only the crews post is fetched (Phase 27)


@pytest.mark.parametrize("variant", ["none", "old", "terms_null", "unreadable"])
def test_stale_policy_gates_and_marks_week(vault_paths: DataPaths, variant: str) -> None:
    _state(vault_paths)
    ledger = vault_paths.ledger / "policy_checks.jsonl"
    if variant == "old":
        _policy(vault_paths, now=T2130, age_days=40)
    elif variant == "terms_null":
        _policy(vault_paths, now=T2130, terms=None)
    elif variant == "unreadable":
        ledger.write_text("not json\n", encoding="utf-8")
    server = _Server()
    items = make_aa_cfb_resolver(_runtime(vault_paths, server), commit=False)(2026, "10", T2130)
    assert _kinds(items) == ["reminder_aa_cfb", "aa_feed_policy_stale"]
    assert server.total == 0
    assert load_feed_state(vault_paths).blind_weeks == ["2026-10"]
    # A later run that week (even with fresh policy) repeats only the blind line.
    _policy(vault_paths, now=T2130)
    again = make_aa_cfb_resolver(_runtime(vault_paths, server), commit=False)(2026, "10", T2230)
    assert again == [BLIND] and server.total == 0


def test_unverified_feed_gate(vault_paths: DataPaths) -> None:
    _policy(vault_paths, now=T2130)
    _state(vault_paths, verified_feed_url=None)
    server = _Server()
    items = make_aa_cfb_resolver(_runtime(vault_paths, server), commit=False)(2026, "10", T2130)
    assert _kinds(items) == ["reminder_aa_cfb", "aa_feed_unverified"]
    assert server.total == 0
    assert load_feed_state(vault_paths).blind_weeks == ["2026-10"]


def test_robots_refusal_yields_blocked_line(vault_paths: DataPaths) -> None:
    _ready(vault_paths)
    server = _Server(robots=b"User-agent: *\nDisallow: /\n")
    items = make_aa_cfb_resolver(_runtime(vault_paths, server), commit=False)(2026, "10", T2130)
    assert _kinds(items) == ["reminder_aa_cfb", "aa_feed_blocked"]
    assert server.feed_requests == 0
    assert load_feed_state(vault_paths).blind_weeks == ["2026-10"]


def test_long_crawl_delay_yields_blocked_line(vault_paths: DataPaths) -> None:
    _ready(vault_paths)
    server = _Server(robots=b"User-agent: *\nCrawl-delay: 600\nAllow: /\n")
    items = make_aa_cfb_resolver(_runtime(vault_paths, server), commit=False)(2026, "10", T2130)
    assert _kinds(items) == ["reminder_aa_cfb", "aa_feed_blocked"]


def test_fetch_error_is_silent_early_and_blind_at_last_poll(
    vault_paths: DataPaths, caplog: pytest.LogCaptureFixture
) -> None:
    _ready(vault_paths)
    server = _Server(status=500)
    with caplog.at_level(logging.WARNING):
        early = make_aa_cfb_resolver(_runtime(vault_paths, server), commit=False)(2026, "10", T2130)
    assert early == [] and load_feed_state(vault_paths).blind_weeks == []
    assert "FeedStatusError" in caplog.text
    late = make_aa_cfb_resolver(_runtime(vault_paths, _Server(status=500)), commit=False)(
        2026, "10", T2230
    )
    assert late == [BLIND]
    assert load_feed_state(vault_paths).blind_weeks == ["2026-10"]


def test_malformed_feed_is_handled(vault_paths: DataPaths) -> None:
    _ready(vault_paths)
    server = _Server(b"<rss><channel><item>")
    resolver = make_aa_cfb_resolver(_runtime(vault_paths, server), commit=False)
    assert resolver(2026, "10", T2130) == []


def test_season_2027_makes_no_request_and_keeps_phase24_line(
    vault_paths: DataPaths,
) -> None:
    server = _Server()
    vault = _Vault()
    resolver = make_aa_cfb_resolver(_runtime(vault_paths, server, vault), commit=True)
    now = datetime(2027, 9, 7, 21, 30, tzinfo=ET)
    assert resolver(2027, "2", now) == [reminder_aa_cfb(2027, "2")]
    assert server.total == 0 and vault.calls == []
    assert not (vault_paths.ledger / "aa_feed_watch.json").exists()
    assert not (vault_paths.ledger / "policy_checks.jsonl").exists()


def test_season_2027_via_due_reminders(vault_paths: DataPaths) -> None:
    rows = [(1, 1, "2027-09-04T16:00:00Z"), (2, 2, "2027-09-11T16:00:00Z")]
    games = [
        {
            "id": gid,
            "season": 2027,
            "week": wk,
            "seasonType": "regular",
            "startDate": start,
            "homeTeam": "Home",
            "awayTeam": "Away",
        }
        for gid, wk, start in rows
    ]
    target = vault_paths.raw / "cfbd" / "games" / "2027.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(json.dumps(games).encode())
    server = _Server()
    resolver = make_aa_cfb_resolver(_runtime(vault_paths, server), commit=True)
    now = datetime(2027, 9, 7, 21, 30, tzinfo=ET)
    items = due_reminders(vault_paths, now, aa_cfb=resolver)
    assert [i.kind for i in items] == ["reminder_aa_cfb"]
    assert server.total == 0
    assert not (vault_paths.ledger / "aa_feed_watch.json").exists()


def test_calling_twice_makes_one_request(vault_paths: DataPaths) -> None:
    _ready(vault_paths)
    server = _Server()
    resolver = make_aa_cfb_resolver(_runtime(vault_paths, server), commit=False)
    one = resolver(2026, "10", T2130)
    two = resolver(2026, "10", T2130)
    assert one == two and server.feed_requests == 1


def test_commit_after_request_scopes_paths(vault_paths: DataPaths) -> None:
    _ready(vault_paths)
    vault = _Vault()
    make_aa_cfb_resolver(_runtime(vault_paths, _Server(), vault), commit=True)(2026, "10", T2130)
    assert len(vault.calls) == 2  # feed paths, then the crews post (Phase 27)
    assert vault.calls[0][1] == [
        "ledger/aa_feed_watch.json",
        "ledger/requests.jsonl",
        "raw/_robots/awfulannouncing.com",
    ]


def test_commit_for_blind_mark_without_request(vault_paths: DataPaths) -> None:
    _state(vault_paths)
    vault = _Vault()
    make_aa_cfb_resolver(_runtime(vault_paths, _Server(), vault), commit=True)(2026, "10", T2130)
    assert [c[1] for c in vault.calls] == [["ledger/aa_feed_watch.json"]]


def test_commit_failure_is_swallowed(vault_paths: DataPaths) -> None:
    _ready(vault_paths)
    vault = _Vault(fail=True)
    items = make_aa_cfb_resolver(_runtime(vault_paths, _Server(), vault), commit=True)(
        2026, "10", T2130
    )
    assert _kinds(items) == ["reminder_aa_cfb_link"]


def test_no_commit_when_commit_false(vault_paths: DataPaths) -> None:
    _ready(vault_paths)
    vault = _Vault()
    make_aa_cfb_resolver(_runtime(vault_paths, _Server(), vault), commit=False)(2026, "10", T2130)
    assert vault.calls == []


def test_resolver_never_raises(vault_paths: DataPaths) -> None:
    _ready(vault_paths)
    runtime = SimpleNamespace(paths=vault_paths, client=None, vault=_Vault())
    resolver = make_aa_cfb_resolver(runtime, commit=True)  # type: ignore[arg-type]
    assert resolver(2026, "10", T2230) == [BLIND]
    other = make_aa_cfb_resolver(runtime, commit=True)  # type: ignore[arg-type]
    assert other(2026, "11", T2130) == []


def test_vault_busy_on_commit_keeps_the_link_and_never_double_marks(
    vault_paths: DataPaths,
) -> None:
    _ready(vault_paths)
    vault = _Vault(exc=VaultBusyError("busy"))
    items = make_aa_cfb_resolver(_runtime(vault_paths, _Server(), vault), commit=True)(
        2026, "10", T2130
    )
    assert _kinds(items) == ["reminder_aa_cfb_link"]
    later = make_aa_cfb_resolver(_runtime(vault_paths, _Server(), vault), commit=True)(
        2026, "10", T2230
    )
    assert _kinds(later) == ["reminder_aa_cfb_link"]
    state = load_feed_state(vault_paths)
    assert "2026-10" in state.weeks and "2026-10" not in state.blind_weeks


def test_linked_week_never_becomes_blind(vault_paths: DataPaths) -> None:
    too_long = "https://awfulannouncing.com/schedules/" + "a" * 200
    _ready(vault_paths, weeks={"2026-10": too_long})
    items = make_aa_cfb_resolver(_runtime(vault_paths, _Server()), commit=False)(2026, "10", T2230)
    assert items == [BLIND]
    assert load_feed_state(vault_paths).blind_weeks == []


def test_late_21_30_cron_at_22_05_is_not_the_last_poll(vault_paths: DataPaths) -> None:
    _ready(vault_paths)
    t2205 = datetime(2026, 11, 3, 22, 5, tzinfo=ET)
    items = make_aa_cfb_resolver(_runtime(vault_paths, _Server(EMPTY_FEED)), commit=False)(
        2026, "10", t2205
    )
    assert items == []
    assert load_feed_state(vault_paths).blind_weeks == []


def test_22_30_backup_is_the_last_poll(vault_paths: DataPaths) -> None:
    _ready(vault_paths)
    items = make_aa_cfb_resolver(_runtime(vault_paths, _Server(EMPTY_FEED)), commit=False)(
        2026, "10", T2230
    )
    assert items == [BLIND]
    assert load_feed_state(vault_paths).blind_weeks == ["2026-10"]


def test_commit_paths_name_only_the_aa_robots_file(vault_paths: DataPaths) -> None:
    _ready(vault_paths)
    vault = _Vault()
    make_aa_cfb_resolver(_runtime(vault_paths, _Server(), vault), commit=True)(2026, "10", T2130)
    assert "raw/_robots/awfulannouncing.com" in vault.calls[0][1]
    assert "raw/_robots" not in vault.calls[0][1]


# -- Phase 27 plan 08: the crews post fetch ----------------------------------

CREWS_FILE = "raw/aa/crews/2026/wk-10.html"


def _crews_cached(paths: DataPaths) -> bool:
    return (paths.raw / "aa" / "crews" / "2026" / "wk-10.html").is_file()


def test_crews_tuesday_first_find_fetches_post_within_cap(vault_paths: DataPaths) -> None:
    _ready(vault_paths)
    server, vault = _Server(), _Vault()
    items = make_aa_cfb_resolver(_runtime(vault_paths, server, vault), commit=True)(
        2026, "10", T2130
    )
    assert _kinds(items) == ["reminder_aa_cfb_link"]
    assert (server.feed_requests, server.post_requests) == (1, 1)
    assert server.aa_requests <= 2
    assert _crews_cached(vault_paths)
    assert len(vault.calls) == 2
    assert "aa crews" in vault.calls[1][0] or "crews" in vault.calls[1][0]
    assert any(p == CREWS_FILE for p in vault.calls[1][1])
    assert not any(p == CREWS_FILE for p in vault.calls[0][1])


def test_crews_backup_run_sends_nothing_when_cached(vault_paths: DataPaths) -> None:
    _ready(vault_paths)
    first = _Server()
    resolver = make_aa_cfb_resolver(_runtime(vault_paths, first), commit=False)
    resolver(2026, "10", T2130)
    backup = _Server()
    items = make_aa_cfb_resolver(_runtime(vault_paths, backup), commit=False)(2026, "10", T2230)
    assert _kinds(items) == ["reminder_aa_cfb_link"]
    assert backup.aa_requests == 0


def test_crews_linked_but_uncached_fetches_exactly_one_post(vault_paths: DataPaths) -> None:
    _ready(vault_paths, weeks={"2026-10": CURRENT})
    server = _Server()
    items = make_aa_cfb_resolver(_runtime(vault_paths, server), commit=False)(2026, "10", T2230)
    assert _kinds(items) == ["reminder_aa_cfb_link"]
    assert (server.feed_requests, server.post_requests) == (0, 1)
    assert _crews_cached(vault_paths)


def test_crews_post_error_is_swallowed(vault_paths: DataPaths) -> None:
    _ready(vault_paths)
    server = _Server()
    server.post_status = 403
    items = make_aa_cfb_resolver(_runtime(vault_paths, server), commit=False)(2026, "10", T2130)
    assert _kinds(items) == ["reminder_aa_cfb_link"]
    assert server.aa_requests <= 2
    assert not _crews_cached(vault_paths)


def test_crews_robots_disallow_posts_skipped_line(vault_paths: DataPaths) -> None:
    _ready(vault_paths, weeks={"2026-10": CURRENT})
    server = _Server(robots=b"User-agent: *\nDisallow: /schedules/\n")
    items = make_aa_cfb_resolver(_runtime(vault_paths, server), commit=False)(2026, "10", T2230)
    assert _kinds(items) == ["reminder_aa_cfb_link", "aa_crews_skipped_robots"]
    assert server.post_requests == 0


def test_crews_stale_policy_sends_no_post_request(vault_paths: DataPaths) -> None:
    _state(vault_paths)
    server = _Server()
    items = make_aa_cfb_resolver(_runtime(vault_paths, server), commit=False)(2026, "10", T2230)
    assert _kinds(items) == ["reminder_aa_cfb", "aa_feed_policy_stale"]
    assert server.aa_requests == 0


def test_crews_linked_with_stale_policy_names_it_and_sends_nothing(vault_paths: DataPaths) -> None:
    _state(vault_paths, weeks={"2026-10": CURRENT})
    server = _Server()
    items = make_aa_cfb_resolver(_runtime(vault_paths, server), commit=False)(2026, "10", T2230)
    assert _kinds(items) == ["reminder_aa_cfb_link", "aa_crews_skipped_policy"]
    assert server.aa_requests == 0


def test_crews_other_season_touches_nothing(vault_paths: DataPaths) -> None:
    _ready(vault_paths, weeks={"2025-10": CURRENT})
    server, vault = _Server(), _Vault()
    t = datetime(2025, 11, 4, 21, 30, tzinfo=ET)
    items = make_aa_cfb_resolver(_runtime(vault_paths, server, vault), commit=True)(2025, "10", t)
    assert _kinds(items) == ["reminder_aa_cfb"]
    assert server.total == 0 and vault.calls == []
