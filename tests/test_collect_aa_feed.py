"""Phase 25: `booth-review collect aa --feed` (synthetic feed, mock transport only)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from booth_review import cli
from booth_review.cli import main
from booth_review.config import DataPaths
from booth_review.sources.aa.feed import (
    AA_FEED_CANDIDATES,
    FeedWatchState,
    load_feed_state,
    save_feed_state,
    week_key,
)

FIXTURES = Path(__file__).parent / "fixtures" / "aa"
FEED = (FIXTURES / "feed_schedules_synthetic.xml").read_bytes()
HOST = "https://awfulannouncing.com"
SCHEDULES = AA_FEED_CANDIDATES["schedules"]
ROBOTS = f"{HOST}/robots.txt"
CURRENT = f"{HOST}/schedules/your-2026-week-10-college-football-announcing-schedule.html"
TITLE_SENTINEL = "Invented coach says something"
NOW = datetime(2026, 11, 3, 21, 30, tzinfo=ZoneInfo("America/New_York"))


def _responses(feed: bytes = FEED) -> dict[str, Any]:
    return {
        ROBOTS: (200, b"User-agent: *\nAllow: /\n", {}),
        SCHEDULES: (200, feed, {}),
        AA_FEED_CANDIDATES["site"]: (200, feed, {}),
    }


def _feed_requests(handle: Any) -> list[str]:
    return [r.url for r in handle.requests if not r.url.endswith("/robots.txt")]


@pytest.fixture(autouse=True)
def _fixed_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_feed_now", lambda: NOW)


def _policy(paths: DataPaths, *, age_days: int = 1) -> None:
    row = {
        "source": "aa",
        "checked_at": (NOW - timedelta(days=age_days))
        .astimezone(UTC)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "robots_ok": True,
        "crawl_delay": None,
        "terms_ok": True,
    }
    (paths.ledger / "policy_checks.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")


def _state(paths: DataPaths, **kw: Any) -> None:
    base: dict[str, Any] = {
        "verified_feed_url": SCHEDULES,
        "verified_at": None,
        "etag": None,
        "last_modified": None,
        "checked_at": None,
        "weeks": {},
        "blind_weeks": [],
    }
    base.update(kw)
    save_feed_state(paths, FeedWatchState(**base))


def _games(paths: DataPaths) -> None:
    rows = [(1, 9, "2026-10-31T16:00:00Z"), (2, 10, "2026-11-07T17:00:00Z")]
    games = [
        {
            "id": gid,
            "season": 2026,
            "week": week,
            "seasonType": "regular",
            "startDate": start,
            "homeTeam": "Home",
            "awayTeam": "Away",
        }
        for gid, week, start in rows
    ]
    target = paths.raw / "cfbd" / "games" / "2026.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(json.dumps(games).encode())


@pytest.fixture
def commits(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, list[str]]]:
    calls: list[tuple[str, list[str]]] = []

    def fake(self: Any, message: str, *, paths: list[str] | None = None, push: bool = True) -> bool:
        calls.append((message, list(paths or [])))
        return True

    monkeypatch.setattr("booth_review.vault.VaultRepo.commit_batch", fake)
    return calls


@pytest.mark.parametrize("extra", [["--season", "2024"], ["--policy-check"], ["--confirm-terms"]])
def test_feed_is_exclusive(
    git_vault, mock_transport_factory, patched_client, extra, capsys
) -> None:
    handle = mock_transport_factory(_responses())
    patched_client(handle)
    assert main(["collect", "aa", "--feed", *extra]) == 2
    assert "--feed runs on its own" in capsys.readouterr().err
    assert handle.requests == []


def test_verify_without_feed_is_rejected(git_vault, capsys) -> None:
    assert main(["collect", "aa", "--verify", "schedules"]) == 2


def test_tvrg_has_no_feed_flag() -> None:
    with pytest.raises(SystemExit):
        main(["collect", "tvrg", "--feed"])


def test_stale_policy_refuses_every_mode(
    git_vault, mock_transport_factory, patched_client, capsys
) -> None:
    handle = mock_transport_factory(_responses())
    patched_client(handle)
    _policy(git_vault, age_days=40)
    assert main(["collect", "aa", "--feed", "--verify", "schedules"]) == 4
    assert "policy check older than 30 days or not approved" in capsys.readouterr().err
    assert main(["collect", "aa", "--feed"]) == 4
    assert handle.requests == []


def test_verify_dry_run_sends_nothing(
    git_vault, mock_transport_factory, patched_client, capsys
) -> None:
    handle = mock_transport_factory(_responses())
    patched_client(handle)
    _policy(git_vault)
    assert main(["collect", "aa", "--feed", "--verify", "schedules", "--dry-run"]) == 0
    assert f"aa feed: planned 1 request {SCHEDULES}" in capsys.readouterr().out
    assert handle.requests == []


def test_verify_records_feed_and_prints_links_only(
    git_vault, mock_transport_factory, patched_client, commits, capsys
) -> None:
    handle = mock_transport_factory(_responses())
    patched_client(handle)
    _policy(git_vault)
    assert main(["collect", "aa", "--feed", "--verify", "schedules"]) == 0
    out = capsys.readouterr().out
    assert _feed_requests(handle) == [SCHEDULES]
    assert "aa feed schedules: status 200, entries " in out
    assert f"  {CURRENT}" in out
    assert "  other " in out
    assert f"verified {SCHEDULES}" in out
    assert TITLE_SENTINEL not in out
    assert load_feed_state(git_vault).verified_feed_url == SCHEDULES
    assert len(commits) == 1
    assert "ledger/aa_feed_watch.json" in commits[0][1]


def test_verify_no_commit(git_vault, mock_transport_factory, patched_client, commits) -> None:
    patched_client(mock_transport_factory(_responses()))
    _policy(git_vault)
    assert main(["collect", "aa", "--feed", "--verify", "schedules", "--no-commit"]) == 0
    assert commits == []


def test_verify_with_no_cfb_posts_is_not_verified(
    git_vault, mock_transport_factory, patched_client, commits, capsys
) -> None:
    empty = b'<rss version="2.0"><channel></channel></rss>'
    patched_client(mock_transport_factory(_responses(empty)))
    _policy(git_vault)
    assert main(["collect", "aa", "--feed", "--verify", "site"]) == 4
    assert "not verified; try --verify site" in capsys.readouterr().out
    assert load_feed_state(git_vault).verified_feed_url is None


def test_week_check_without_verified_feed(
    git_vault, mock_transport_factory, patched_client, capsys
) -> None:
    handle = mock_transport_factory(_responses())
    patched_client(handle)
    _policy(git_vault)
    assert main(["collect", "aa", "--feed"]) == 4
    assert "no verified feed; run --feed --verify schedules" in capsys.readouterr().err
    assert handle.requests == []


def test_week_check_matches_and_prints_url_only(
    git_vault, mock_transport_factory, patched_client, commits, capsys
) -> None:
    handle = mock_transport_factory(_responses())
    patched_client(handle)
    _policy(git_vault)
    _state(git_vault)
    _games(git_vault)
    assert main(["collect", "aa", "--feed"]) == 0
    out = capsys.readouterr().out
    assert f"aa feed week 10: status 200, matched {CURRENT}" in out
    assert TITLE_SENTINEL not in out
    assert _feed_requests(handle) == [SCHEDULES]
    assert load_feed_state(git_vault).weeks[week_key(2026, "10")] == CURRENT
    assert len(commits) == 1


def test_week_check_matched_none(
    git_vault, mock_transport_factory, patched_client, commits, capsys
) -> None:
    patched_client(mock_transport_factory(_responses(b'<rss version="2.0"><channel/></rss>')))
    _policy(git_vault)
    _state(git_vault)
    _games(git_vault)
    assert main(["collect", "aa", "--feed"]) == 0
    assert "aa feed week 10: status 200, matched none" in capsys.readouterr().out


def test_week_check_no_current_week(
    git_vault, mock_transport_factory, patched_client, commits, capsys
) -> None:
    handle = mock_transport_factory(_responses())
    patched_client(handle)
    _policy(git_vault)
    _state(git_vault)
    assert main(["collect", "aa", "--feed"]) == 0
    assert "aa feed: no current cfb week, nothing to check" in capsys.readouterr().out
    assert handle.requests == []


def test_week_check_already_linked(
    git_vault, mock_transport_factory, patched_client, commits, capsys
) -> None:
    handle = mock_transport_factory(_responses())
    patched_client(handle)
    _policy(git_vault)
    _state(git_vault, weeks={week_key(2026, "10"): CURRENT})
    _games(git_vault)
    assert main(["collect", "aa", "--feed"]) == 0
    assert f"aa feed week 10: already linked {CURRENT}" in capsys.readouterr().out
    assert handle.requests == [] and commits == []


def test_week_check_blind_week_not_polled(
    git_vault, mock_transport_factory, patched_client, commits, capsys
) -> None:
    handle = mock_transport_factory(_responses())
    patched_client(handle)
    _policy(git_vault)
    _state(git_vault, blind_weeks=[week_key(2026, "10")])
    _games(git_vault)
    assert main(["collect", "aa", "--feed"]) == 0
    assert "plain reminder already sent, not polled" in capsys.readouterr().out
    assert handle.requests == [] and commits == []


def test_week_check_dry_run(git_vault, mock_transport_factory, patched_client, capsys) -> None:
    handle = mock_transport_factory(_responses())
    patched_client(handle)
    _policy(git_vault)
    _state(git_vault)
    _games(git_vault)
    assert main(["collect", "aa", "--feed", "--dry-run"]) == 0
    assert f"aa feed: planned 1 request {SCHEDULES}" in capsys.readouterr().out
    assert handle.requests == []


def test_robots_disallow_exits_4(
    git_vault, mock_transport_factory, patched_client, commits, capsys
) -> None:
    responses = _responses()
    responses[ROBOTS] = (200, b"User-agent: *\nDisallow: /\n", {})
    patched_client(mock_transport_factory(responses))
    _policy(git_vault)
    assert main(["collect", "aa", "--feed", "--verify", "schedules"]) == 4
    assert "error:" in capsys.readouterr().err
    assert commits == []


def test_malformed_feed_exits_4_and_still_commits_the_audit_row(
    git_vault, mock_transport_factory, patched_client, commits, capsys
) -> None:
    patched_client(mock_transport_factory(_responses(b"<rss><channel><item>")))
    _policy(git_vault)
    _state(git_vault)
    _games(git_vault)
    assert main(["collect", "aa", "--feed"]) == 4
    assert "error: ParseError" in capsys.readouterr().err
    assert len(commits) == 1
    assert "ledger/requests.jsonl" in commits[0][1]
    assert "raw/_robots/awfulannouncing.com" in commits[0][1]
