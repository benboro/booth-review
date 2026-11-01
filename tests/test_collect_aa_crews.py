"""Phase 27: `fetch_week_crews` and `booth-review collect aa --crews` (mock transport only)."""

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
from booth_review.errors import PageRejectedError
from booth_review.runtime import build_runtime
from booth_review.sources.aa.crews import (
    CREWS_SEASON,
    crews_cache_path,
    fetch_week_crews,
)
from booth_review.sources.aa.feed import FeedWatchState, save_feed_state, week_key

FIXTURES = Path(__file__).parent / "fixtures" / "aa"
POST = (FIXTURES / "schedule_synthetic.html").read_bytes()
HOST = "https://awfulannouncing.com"
ROBOTS = f"{HOST}/robots.txt"
URL9 = f"{HOST}/college-football/invented-week-9-announcing-schedule.html"
URL10 = f"{HOST}/college-football/invented-week-10-announcing-schedule.html"
NOW = datetime(2026, 11, 3, 21, 30, tzinfo=ZoneInfo("America/New_York"))
HEADERS = {"ETag": '"abc"', "Last-Modified": "Sat, 31 Oct 2026 12:00:00 GMT"}


def _responses(url: str = URL10, body: bytes = POST) -> dict[str, Any]:
    return {
        ROBOTS: (200, b"User-agent: *\nAllow: /\n", {}),
        url: (200, body, HEADERS),
    }


def _post_requests(handle: Any) -> list[Any]:
    return [r for r in handle.requests if not r.url.endswith("/robots.txt")]


def _policy(paths: DataPaths, *, age_days: int = 1, terms_ok: bool = True) -> None:
    row = {
        "source": "aa",
        "checked_at": (NOW - timedelta(days=age_days))
        .astimezone(UTC)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "robots_ok": True,
        "crawl_delay": None,
        "terms_ok": terms_ok,
    }
    (paths.ledger / "policy_checks.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")


def _state(paths: DataPaths, weeks: dict[str, str] | None = None) -> None:
    save_feed_state(
        paths,
        FeedWatchState(
            verified_feed_url=None,
            verified_at=None,
            etag=None,
            last_modified=None,
            checked_at=None,
            weeks=weeks if weeks is not None else {week_key(2026, "10"): URL10},
            blind_weeks=[],
        ),
    )


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


@pytest.fixture(autouse=True)
def _fixed_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_feed_now", lambda: NOW)


@pytest.fixture
def commits(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, list[str]]]:
    calls: list[tuple[str, list[str]]] = []

    def fake(self: Any, message: str, *, paths: list[str] | None = None, push: bool = True) -> bool:
        calls.append((message, list(paths or [])))
        return True

    monkeypatch.setattr("booth_review.vault.VaultRepo.commit_batch", fake)
    return calls


def _fetch(
    paths: DataPaths,
    cache: Any,
    *,
    season: int = 2026,
    label: str = "10",
    mode: Any = "conditional",
    budget: int = 1,
    dry_run: bool = False,
) -> Any:
    return fetch_week_crews(
        cache,
        paths,
        season=season,
        label=label,
        now=NOW,
        mode=mode,
        budget=budget,
        dry_run=dry_run,
    )


@pytest.fixture
def runtime(git_vault, mock_transport_factory, patched_client):
    handle = mock_transport_factory(_responses())
    patched_client(handle)
    rt = build_runtime(with_budget=False)
    yield rt, handle
    rt.client.close()


def test_season_other_than_2026_is_refused(git_vault, runtime) -> None:
    rt, handle = runtime
    _policy(git_vault)
    _state(git_vault)
    result = _fetch(git_vault, rt.cache, season=2025)
    assert result.outcome == "not_season" and result.requests == 0
    assert handle.requests == []
    assert CREWS_SEASON == 2026


def test_stale_policy_sends_nothing(git_vault, runtime) -> None:
    rt, handle = runtime
    _policy(git_vault, age_days=31)
    _state(git_vault)
    assert _fetch(git_vault, rt.cache).outcome == "stale_policy"
    assert handle.requests == []


def test_unconfirmed_terms_send_nothing(git_vault, runtime) -> None:
    rt, handle = runtime
    _policy(git_vault, terms_ok=False)
    _state(git_vault)
    assert _fetch(git_vault, rt.cache).outcome == "stale_policy"
    assert handle.requests == []


def test_no_recorded_link(git_vault, runtime) -> None:
    rt, handle = runtime
    _policy(git_vault)
    _state(git_vault)
    result = _fetch(git_vault, rt.cache, label="9")
    assert result.outcome == "no_link" and result.requests == 0
    assert handle.requests == []


def test_off_host_stored_url_is_refused(git_vault, runtime) -> None:
    rt, handle = runtime
    _policy(git_vault)
    (git_vault.ledger / "aa_feed_watch.json").write_text(
        json.dumps(
            {
                "verified_feed_url": None,
                "weeks": {"2026-10": "https://evil.example/college-football/x.html"},
                "blind_weeks": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="off-host"):
        _fetch(git_vault, rt.cache)
    assert handle.requests == []


def test_first_fetch_caches_the_post(git_vault, runtime) -> None:
    rt, handle = runtime
    _policy(git_vault)
    _state(git_vault)
    result = _fetch(git_vault, rt.cache)
    assert result.outcome == "fetched" and result.requests == 1
    assert result.url == URL10
    cached = git_vault.raw / "aa" / "crews" / "2026" / "wk-10.html"
    assert cached.read_bytes() == POST
    assert crews_cache_path(2026, "10") == "aa/crews/2026/wk-10.html"
    assert "raw/aa/crews/2026/wk-10.html" in result.touched
    assert "ledger/requests.jsonl" in result.touched
    posts = _post_requests(handle)
    assert len(posts) == 1
    assert "booth-review/" in posts[0].headers["user-agent"]


def test_conditional_refetch_gets_304(git_vault, mock_transport_factory, patched_client) -> None:
    responses = _responses()
    handle = mock_transport_factory(responses)
    patched_client(handle)
    rt = build_runtime(with_budget=False)
    try:
        _policy(git_vault)
        _state(git_vault)
        assert _fetch(git_vault, rt.cache).outcome == "fetched"
        responses[URL10] = (304, b"", HEADERS)
        result = _fetch(git_vault, rt.cache)
        assert result.outcome == "not_modified" and result.requests == 1
        second = _post_requests(handle)[1]
        assert "if-none-match" in second.headers or "if-modified-since" in second.headers
        cached = git_vault.raw / "aa" / "crews" / "2026" / "wk-10.html"
        assert cached.read_bytes() == POST
    finally:
        rt.client.close()


def test_if_missing_with_cached_file_sends_nothing(git_vault, runtime) -> None:
    rt, handle = runtime
    _policy(git_vault)
    _state(git_vault)
    _fetch(git_vault, rt.cache)
    before = len(handle.requests)
    result = _fetch(git_vault, rt.cache, mode="if_missing")
    assert result.outcome == "cached" and result.requests == 0
    assert len(handle.requests) == before


def test_zero_budget_sends_nothing(git_vault, runtime) -> None:
    rt, handle = runtime
    _policy(git_vault)
    _state(git_vault)
    assert _fetch(git_vault, rt.cache, budget=0).outcome == "no_budget"
    assert handle.requests == []


def test_dry_run_sends_nothing(git_vault, runtime) -> None:
    rt, handle = runtime
    _policy(git_vault)
    _state(git_vault)
    result = _fetch(git_vault, rt.cache, dry_run=True)
    assert result.outcome == "dry_run" and result.requests == 0
    assert handle.requests == []


def test_body_without_canonical_is_not_cached(
    git_vault, mock_transport_factory, patched_client
) -> None:
    handle = mock_transport_factory(_responses(body=b"<html><body>nothing</body></html>"))
    patched_client(handle)
    rt = build_runtime(with_budget=False)
    try:
        _policy(git_vault)
        _state(git_vault)
        with pytest.raises(PageRejectedError):
            _fetch(git_vault, rt.cache)
        assert not (git_vault.raw / "aa" / "crews" / "2026" / "wk-10.html").exists()
    finally:
        rt.client.close()


def test_header_drift_page_is_not_cached(git_vault, mock_transport_factory, patched_client) -> None:
    """Phase 27 review WR-04: a post whose day headers no longer parse yields no
    booth, so it fails validation and is never cached as a good page."""
    drifted = POST.replace(b"Friday November 6", b"Friday the sixth").replace(
        b"Saturday, November 7", b"Saturday the seventh"
    )
    handle = mock_transport_factory(_responses(body=drifted))
    patched_client(handle)
    rt = build_runtime(with_budget=False)
    try:
        _policy(git_vault)
        _state(git_vault)
        with pytest.raises(PageRejectedError):
            _fetch(git_vault, rt.cache)
        assert not (git_vault.raw / "aa" / "crews" / "2026" / "wk-10.html").exists()
    finally:
        rt.client.close()


# --- CLI ---


def _cli_setup(git_vault: DataPaths, mock_transport_factory, patched_client, **kw: Any) -> Any:
    responses = _responses()
    responses[URL9] = (200, POST, HEADERS)
    handle = mock_transport_factory(responses)
    patched_client(handle)
    _policy(git_vault)
    _state(git_vault, **kw)
    _games(git_vault)
    return handle


def test_cli_fetches_current_week(
    git_vault, mock_transport_factory, patched_client, commits, capsys
) -> None:
    handle = _cli_setup(git_vault, mock_transport_factory, patched_client)
    assert main(["collect", "aa", "--crews"]) == 0
    out = capsys.readouterr().out
    assert "aa crews week 10: fetched" in out and URL10 in out
    assert "requests 1" in out
    assert len(_post_requests(handle)) == 1
    assert len(commits) == 1
    assert "raw/aa/crews/2026/wk-10.html" in commits[0][1]
    assert "crews" in commits[0][0]


def test_cli_second_run_is_conditional(
    git_vault, mock_transport_factory, patched_client, commits, capsys
) -> None:
    handle = _cli_setup(git_vault, mock_transport_factory, patched_client)
    assert main(["collect", "aa", "--crews"]) == 0
    assert main(["collect", "aa", "--crews"]) == 0
    second = _post_requests(handle)[1]
    assert "if-none-match" in second.headers or "if-modified-since" in second.headers


def test_cli_week_targets_recorded_week(
    git_vault, mock_transport_factory, patched_client, commits, capsys
) -> None:
    handle = _cli_setup(
        git_vault,
        mock_transport_factory,
        patched_client,
        weeks={week_key(2026, "9"): URL9, week_key(2026, "10"): URL10},
    )
    assert main(["collect", "aa", "--crews", "--week", "9"]) == 0
    assert "aa crews week 9: fetched" in capsys.readouterr().out
    assert [r.url for r in _post_requests(handle)] == [URL9]


def test_cli_week_without_link(
    git_vault, mock_transport_factory, patched_client, commits, capsys
) -> None:
    handle = _cli_setup(git_vault, mock_transport_factory, patched_client)
    assert main(["collect", "aa", "--crews", "--week", "12"]) == 0
    assert "no recorded link" in capsys.readouterr().out
    assert handle.requests == [] and commits == []


def test_cli_week_needs_crews(git_vault, capsys) -> None:
    assert main(["collect", "aa", "--week", "9"]) == 2


@pytest.mark.parametrize(
    "extra", [["--feed"], ["--season", "2026"], ["--policy-check"], ["--confirm-terms"]]
)
def test_cli_crews_is_exclusive(
    git_vault, mock_transport_factory, patched_client, extra, capsys
) -> None:
    handle = mock_transport_factory(_responses())
    patched_client(handle)
    assert main(["collect", "aa", "--crews", *extra]) == 2
    assert "--crews runs on its own" in capsys.readouterr().err
    assert handle.requests == []


def test_cli_stale_policy_exits_4(
    git_vault, mock_transport_factory, patched_client, capsys
) -> None:
    handle = mock_transport_factory(_responses())
    patched_client(handle)
    _policy(git_vault, age_days=40)
    _state(git_vault)
    assert main(["collect", "aa", "--crews"]) == 4
    assert "policy check older than 30 days or not approved" in capsys.readouterr().err
    assert handle.requests == []


def test_cli_robots_disallow_prints_type_only(
    git_vault, mock_transport_factory, patched_client, commits, capsys
) -> None:
    responses = _responses()
    responses[ROBOTS] = (200, b"User-agent: *\nDisallow: /\n", {})
    patched_client(mock_transport_factory(responses))
    _policy(git_vault)
    _state(git_vault)
    _games(git_vault)
    assert main(["collect", "aa", "--crews"]) == 4
    err = capsys.readouterr().err
    assert err.startswith("error: ") and "Robots" in err


def test_cli_dry_run(git_vault, mock_transport_factory, patched_client, commits, capsys) -> None:
    handle = _cli_setup(git_vault, mock_transport_factory, patched_client)
    assert main(["collect", "aa", "--crews", "--dry-run"]) == 0
    assert "aa crews: planned 1 request" in capsys.readouterr().out
    assert handle.requests == [] and commits == []


def test_cli_no_commit(git_vault, mock_transport_factory, patched_client, commits) -> None:
    _cli_setup(git_vault, mock_transport_factory, patched_client)
    assert main(["collect", "aa", "--crews", "--no-commit"]) == 0
    assert commits == []


def test_cli_no_current_week(
    git_vault, mock_transport_factory, patched_client, commits, capsys
) -> None:
    handle = mock_transport_factory(_responses())
    patched_client(handle)
    _policy(git_vault)
    _state(git_vault)
    assert main(["collect", "aa", "--crews"]) == 0
    assert "no current cfb week, nothing to fetch" in capsys.readouterr().out
    assert handle.requests == []


def test_cli_rejected_body_exits_4_and_commits_audit(
    git_vault, mock_transport_factory, patched_client, commits, capsys
) -> None:
    patched_client(mock_transport_factory(_responses(body=b"<html></html>")))
    _policy(git_vault)
    _state(git_vault)
    _games(git_vault)
    assert main(["collect", "aa", "--crews"]) == 4
    assert "error: PageRejectedError" in capsys.readouterr().err
    assert len(commits) == 1
    assert "ledger/requests.jsonl" in commits[0][1]


# -- Adversarial panel F7: a scheduled re-check is conditional or not sent ---------


def test_headerless_304_keeps_the_stored_etag_for_the_next_recheck(
    git_vault, mock_transport_factory, patched_client
) -> None:
    """Fetched with ETag p1, then a 304 with no validators: the next re-check still
    sends If-None-Match "p1" (the real cache logic, mock transport only)."""
    responses = _responses()
    responses[URL10] = (200, POST, {"ETag": '"p1"'})
    handle = mock_transport_factory(responses)
    patched_client(handle)
    rt = build_runtime(with_budget=False)
    try:
        _policy(git_vault)
        _state(git_vault)
        assert _fetch(git_vault, rt.cache).outcome == "fetched"
        responses[URL10] = (304, b"", {})
        assert _fetch(git_vault, rt.cache, mode="recheck").outcome == "not_modified"
        assert _fetch(git_vault, rt.cache, mode="recheck").outcome == "not_modified"
        posts = _post_requests(handle)
        assert len(posts) == 3
        assert [p.headers.get("if-none-match") for p in posts] == [None, '"p1"', '"p1"']
    finally:
        rt.client.close()


def test_recheck_without_a_stored_validator_sends_nothing(
    git_vault, mock_transport_factory, patched_client
) -> None:
    responses = _responses()
    responses[URL10] = (200, POST, {})
    handle = mock_transport_factory(responses)
    patched_client(handle)
    rt = build_runtime(with_budget=False)
    try:
        _policy(git_vault)
        _state(git_vault)
        assert _fetch(git_vault, rt.cache).outcome == "fetched"
        result = _fetch(git_vault, rt.cache, mode="recheck")
        assert result.outcome == "no_validator" and result.requests == 0
        assert result.touched == ()
        assert len(_post_requests(handle)) == 1
    finally:
        rt.client.close()
