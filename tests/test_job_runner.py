"""Offline tests for ScheduledJob (`booth-review job run`, AUTO-01).

Every test drives either ScheduledJob directly against a real RawCache/
CfbdBudget/VaultRepo wired onto a real (throwaway, git_vault-rooted) vault
and an httpx2.MockTransport (no real network, no real git push), or the CLI
end-to-end via `main([...])`. No test ever sends a request to
506sports.com -- the job never fetches it (D-07/D-08/AUTO-01).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from booth_review import cli
from booth_review.cli import main
from booth_review.config import CFBD_FLOOR_DEFAULT
from booth_review.errors import VaultCommitError, VaultStateError
from booth_review.job import runner as runner_module
from booth_review.job.catchup import JobState, load_state, save_state
from booth_review.job.gaps506 import Gaps506, find_506_gaps
from booth_review.job.runner import (
    JOB_CFBD_MAX_CALLS,
    JOB_CFBD_SCHEDULE_MAX_CALLS,
    ScheduledJob,
)
from booth_review.runtime import Runtime
from booth_review.sources.aa.feed import (
    AA_FEED_CANDIDATES,
    FeedWatchState,
    load_feed_state,
    save_feed_state,
)
from booth_review.sources.ratingsref.collector import SITEMAP_URL
from booth_review.transport.budget import CfbdBudget
from booth_review.transport.cache import FreezeGuard, RawCache
from booth_review.transport.client import PoliteClient
from booth_review.vault import VaultRepo

RUNNER_SRC = Path("src/booth_review/job/runner.py").read_text(encoding="utf-8")


# -- helpers ------------------------------------------------------------------------------


def _client(handle, *, fake_clock=None) -> PoliteClient:
    kwargs: dict = {"transport": handle.transport}
    if fake_clock is not None:
        kwargs["clock"] = fake_clock.now
        kwargs["sleep"] = fake_clock.sleep
    else:
        kwargs["clock"] = lambda: 0.0
        kwargs["sleep"] = lambda seconds: None
    return PoliteClient(**kwargs)


def _runtime(
    paths,
    handle,
    *,
    now,
    fake_clock=None,
    max_calls: int | None = None,
    floor: int = CFBD_FLOOR_DEFAULT,
) -> Runtime:
    client = _client(handle, fake_clock=fake_clock)
    budget = CfbdBudget(paths.cfbd_ledger, floor=floor, max_calls=max_calls, now=now)
    freeze = FreezeGuard.load(paths.frozen)
    cache = RawCache(paths, client, guards=[budget], freeze=freeze)
    vault = VaultRepo(paths.vault)
    return Runtime(paths=paths, client=client, cache=cache, budget=budget, vault=vault)


def _seed_cfbd_ledger(paths, *, month: str, remaining: int = 900) -> None:
    paths.cfbd_ledger.parent.mkdir(parents=True, exist_ok=True)
    line = {
        "event": "call",
        "endpoint": "/info",
        "params": {},
        "called_at": f"{month}-01T00:00:00Z",
        "month": month,
        "status": 200,
        "call_limit_remaining_header": None,
        "info_remaining_calls": remaining,
        "info_reset_at": None,
        "counted_against_quota": True,
        "discrepancy": False,
        "tag": None,
    }
    paths.cfbd_ledger.write_text(json.dumps(line) + "\n", encoding="utf-8")


def _freeze_seasons(paths, seasons) -> None:
    years = sorted(seasons)
    paths.frozen.write_text(
        json.dumps({"sports506": years, "ratingsref": years, "cfbd": years}), encoding="utf-8"
    )


def _seed_required_state(paths, *, cfbd_month: str, cfbd_remaining: int = 900) -> None:
    """rr_lastmod.json and cfbd_ledger.jsonl, with 2014-2025 frozen (IN-02 checks every
    past season on every run); frozen.json itself is already seeded by git_vault."""
    _freeze_seasons(paths, range(2014, 2026))
    paths.rr_lastmod.write_text("{}", encoding="utf-8")
    _seed_cfbd_ledger(paths, month=cfbd_month, remaining=cfbd_remaining)


def _cfbd_ok_responses(
    season: int, *, include_teams_fbs: bool = True
) -> dict[str, tuple[int, bytes, dict[str, str]]]:
    endpoints = ["/games", "/games/media", "/lines", "/metrics/wp/pregame", "/rankings"]
    responses: dict[str, tuple[int, bytes, dict[str, str]]] = {
        "https://api.collegefootballdata.com/robots.txt": (404, b"nf", {})
    }
    for path in endpoints:
        url = f"https://api.collegefootballdata.com{path}?seasonType=both&year={season}"
        responses[url] = (200, b"[]", {})
    if include_teams_fbs:
        responses[f"https://api.collegefootballdata.com/teams/fbs?year={season}"] = (
            200,
            b"[]",
            {},
        )
    return responses


def _sitemap_xml(entries: list[tuple[str, str]]) -> bytes:
    urls = "".join(
        f"<url><loc>https://ratingsreference.com/telecast/{slug}</loc>"
        f"<lastmod>{lastmod}</lastmod></url>\n"
        for slug, lastmod in entries
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}</urlset>\n"
    ).encode()


def _empty_sitemap_xml() -> bytes:
    return _sitemap_xml([])


def _precache_cfbd_season(paths, season: int) -> None:
    for name in ("games", "media", "lines", "wp_pregame", "rankings", "teams_fbs"):
        path = paths.raw / "cfbd" / name / f"{season}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"[]")


# -- static source checks ------------------------------------------------------------------


def test_runner_defines_scheduled_job_and_never_references_506sports() -> None:
    assert "class ScheduledJob" in RUNNER_SRC
    assert "506sports" not in RUNNER_SRC


def test_runner_never_names_the_espn_press_room_host() -> None:
    # 04.19 D-14: the reminder is read-only; the URL lives only in the attention line.
    assert "espnpressroom" not in RUNNER_SRC


def test_job_cfbd_max_calls_constant_is_8() -> None:
    assert JOB_CFBD_MAX_CALLS == 8


# -- CLI --help ----------------------------------------------------------------------------


def test_job_run_help_lists_all_flags(capsys) -> None:
    try:
        main(["job", "run", "--help"])
    except SystemExit as exc:
        assert exc.code == 0
    out = capsys.readouterr().out
    flags = (
        "--trigger",
        "--rr-cap",
        "--max-cfbd-calls",
        "--attention-out",
        "--dry-run",
        "--no-commit",
        "--update",
        "--site-out",
        "--result-out",
    )
    for flag in flags:
        assert flag in out


# -- required vault state -------------------------------------------------------------------


def test_scheduled_job_missing_required_state_raises_vault_state_error(
    git_vault, mock_transport_factory, fake_clock
) -> None:
    paths = git_vault
    now_value = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    handle = mock_transport_factory({})
    runtime = _runtime(paths, handle, now=lambda: now_value, fake_clock=fake_clock)

    job = ScheduledJob(runtime, token=None, now=lambda: now_value, trigger="manual")
    with pytest.raises(VaultStateError):
        job.run()
    assert handle.requests == []


# -- D-13 catch-up from backdated state ------------------------------------------------------


def test_scheduled_job_catchup_from_backdated_state_sends_expected_requests(
    git_vault, mock_transport_factory, fake_clock
) -> None:
    paths = git_vault
    _seed_required_state(paths, cfbd_month="2026-10")

    last_success = datetime(2026, 10, 4, 14, 5, tzinfo=UTC)
    save_state(
        paths.job_state,
        JobState(
            season=2026,
            last_success_at=last_success,
            last_attempt_at=last_success,
            last_status="ok",
            last_window_start=last_success,
        ),
    )

    now_value = datetime(2026, 10, 15, 0, 10, tzinfo=UTC)
    _precache_cfbd_season(paths, 2026)

    slugs = [f"cfb-new-team-{i:02d}-2026-09-{10 + i:02d}" for i in range(6)]
    sitemap_xml = _sitemap_xml([(slug, "2026-09-25T00:00:00+00:00") for slug in slugs])

    responses = _cfbd_ok_responses(2026, include_teams_fbs=False)
    responses["https://ratingsreference.com/robots.txt"] = (404, b"nf", {})
    responses[SITEMAP_URL] = (200, sitemap_xml, {})
    for slug in slugs:
        responses[f"https://ratingsreference.com/api/telecast/{slug}.json"] = (
            200,
            json.dumps({"telecast": {"id": slug}}).encode(),
            {},
        )

    handle = mock_transport_factory(responses)
    runtime = _runtime(paths, handle, now=lambda: now_value, fake_clock=fake_clock)

    job = ScheduledJob(runtime, token="test-token", now=lambda: now_value, trigger="schedule")
    result = job.run()

    cfbd_data_requests = [
        r
        for r in handle.requests
        if r.url.startswith("https://api.collegefootballdata.com")
        and not r.url.endswith("robots.txt")
    ]
    assert len(cfbd_data_requests) == 5  # teams_fbs already cached, never requested

    rr_requests = [r for r in handle.requests if "/api/telecast/" in r.url]
    assert len(rr_requests) == 6

    assert all("506sports.com" not in r.url for r in handle.requests)

    assert result.window is not None
    assert result.window.missed_slots == 2

    saved_state = load_state(paths.job_state)
    assert saved_state.last_success_at == now_value
    assert saved_state.last_window_start == last_success


# -- CFBD budget-floor failure: attention, RR still runs, success not advanced ----------------


def test_scheduled_job_cfbd_budget_floor_is_attention_rr_still_runs_exit4(
    git_vault, mock_transport_factory, fake_clock
) -> None:
    paths = git_vault
    _seed_required_state(paths, cfbd_month="2026-10", cfbd_remaining=250)

    prior_success = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    save_state(
        paths.job_state,
        JobState(
            season=2026,
            last_success_at=prior_success,
            last_attempt_at=prior_success,
            last_status="ok",
            last_window_start=prior_success,
        ),
    )

    now_value = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    responses = {
        "https://api.collegefootballdata.com/robots.txt": (404, b"nf", {}),
        "https://ratingsreference.com/robots.txt": (404, b"nf", {}),
        SITEMAP_URL: (200, _empty_sitemap_xml(), {}),
    }
    handle = mock_transport_factory(responses)
    runtime = _runtime(paths, handle, now=lambda: now_value, fake_clock=fake_clock, floor=250)

    job = ScheduledJob(runtime, token="test-token", now=lambda: now_value, trigger="manual")
    result = job.run()

    assert result.exit_code == 4
    kinds = {item.kind for item in result.items}
    assert "cfbd_step_failed" in kinds

    rr_requests = [r for r in handle.requests if r.url == SITEMAP_URL]
    assert rr_requests  # RR step still ran

    saved_state = load_state(paths.job_state)
    assert saved_state.last_success_at == prior_success  # not advanced
    assert saved_state.last_status == "failed"  # IN-05


# -- CR-01: a new month with no ledger line yet calls /info before the data calls --------------


def test_scheduled_job_new_month_without_ledger_line_calls_info_first(
    git_vault, mock_transport_factory, fake_clock
) -> None:
    paths = git_vault
    # Only the *previous* month has a ledger line: the first run of October.
    _seed_required_state(paths, cfbd_month="2026-09")
    now_value = datetime(2026, 10, 4, 14, 5, tzinfo=UTC)

    info_url = "https://api.collegefootballdata.com/info"
    responses = _cfbd_ok_responses(2026)
    responses[info_url] = (
        200,
        json.dumps({"remainingCalls": 1000, "monthlyLimit": 1000, "usedCalls": 0}).encode(),
        {},
    )
    responses["https://ratingsreference.com/robots.txt"] = (404, b"nf", {})
    responses[SITEMAP_URL] = (200, _empty_sitemap_xml(), {})

    handle = mock_transport_factory(responses)
    runtime = _runtime(
        paths, handle, now=lambda: now_value, fake_clock=fake_clock, max_calls=JOB_CFBD_MAX_CALLS
    )

    job = ScheduledJob(runtime, token="test-token", now=lambda: now_value, trigger="manual")
    result = job.run()

    assert result.exit_code == 0
    assert "cfbd_step_failed" not in {item.kind for item in result.items}

    cfbd_urls = [
        r.url
        for r in handle.requests
        if r.url.startswith("https://api.collegefootballdata.com")
        and not r.url.endswith("robots.txt")
    ]
    assert cfbd_urls.count(info_url) == 1
    assert cfbd_urls[0] == info_url  # before any data call
    assert len(cfbd_urls) == 7  # /info + 5 refresh + teams_fbs
    assert runtime.budget is not None
    assert runtime.budget.last_known_remaining("2026-10") is not None


def test_scheduled_job_known_month_budget_never_calls_info(
    git_vault, mock_transport_factory, fake_clock
) -> None:
    paths = git_vault
    _seed_required_state(paths, cfbd_month="2026-10")
    now_value = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)

    responses = _cfbd_ok_responses(2026)
    responses["https://ratingsreference.com/robots.txt"] = (404, b"nf", {})
    responses[SITEMAP_URL] = (200, _empty_sitemap_xml(), {})

    handle = mock_transport_factory(responses)
    runtime = _runtime(paths, handle, now=lambda: now_value, fake_clock=fake_clock)

    job = ScheduledJob(runtime, token="test-token", now=lambda: now_value, trigger="manual")
    result = job.run()

    assert result.exit_code == 0
    assert all(not r.url.endswith("/info") for r in handle.requests)


# -- CR-02: CFBD 4xx (revoked key) is attention, never a clean exit 0 ---------------------------


def test_scheduled_job_cfbd_401_is_attention_exit4_success_not_advanced(
    git_vault, mock_transport_factory, fake_clock
) -> None:
    paths = git_vault
    _seed_required_state(paths, cfbd_month="2026-10")

    prior_success = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    save_state(
        paths.job_state,
        JobState(
            season=2026,
            last_success_at=prior_success,
            last_attempt_at=prior_success,
            last_status="ok",
            last_window_start=prior_success,
        ),
    )
    now_value = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)

    responses = {
        url: (401, b'{"message": "Unauthorized"}', {})
        for url in _cfbd_ok_responses(2026)
        if not url.endswith("robots.txt")
    }
    responses["https://api.collegefootballdata.com/robots.txt"] = (404, b"nf", {})
    responses["https://ratingsreference.com/robots.txt"] = (404, b"nf", {})
    responses[SITEMAP_URL] = (200, _empty_sitemap_xml(), {})

    handle = mock_transport_factory(responses)
    runtime = _runtime(paths, handle, now=lambda: now_value, fake_clock=fake_clock)

    job = ScheduledJob(runtime, token="test-token", now=lambda: now_value, trigger="manual")
    result = job.run()

    assert result.exit_code == 4
    failed_items = [item for item in result.items if item.kind == "cfbd_failed"]
    assert len(failed_items) == 1
    assert failed_items[0].severity == "attention"
    assert failed_items[0].line == "cfbd calls failed: 6"
    assert result.counts["cfbd_failed"] == 6

    saved_state = load_state(paths.job_state)
    assert saved_state.last_success_at == prior_success  # not advanced
    assert saved_state.last_status == "failed"  # IN-05
    assert saved_state.retry_pending is False  # a revoked key won't fix itself


# -- WR-02: the RR lastmod log (jsonl) is accepted and committed ----------------------------------


def test_scheduled_job_accepts_jsonl_only_lastmod_ledger_and_commits_it(
    git_vault, mock_transport_factory, fake_clock
) -> None:
    paths = git_vault
    _seed_cfbd_ledger(paths, month="2026-10")
    _freeze_seasons(paths, range(2014, 2026))
    paths.rr_lastmod_log.write_text("", encoding="utf-8")  # a post-0.2.2 vault: no .json
    now_value = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    _precache_cfbd_season(paths, 2026)

    slug = "cfb-new-team-a-2026-09-12"
    responses = _cfbd_ok_responses(2026, include_teams_fbs=False)
    responses["https://ratingsreference.com/robots.txt"] = (404, b"nf", {})
    responses[SITEMAP_URL] = (200, _sitemap_xml([(slug, "2026-09-25T00:00:00+00:00")]), {})
    responses[f"https://ratingsreference.com/api/telecast/{slug}.json"] = (200, b"{}", {})

    handle = mock_transport_factory(responses)
    runtime = _runtime(paths, handle, now=lambda: now_value, fake_clock=fake_clock)

    job = ScheduledJob(runtime, token="test-token", now=lambda: now_value, trigger="manual")
    result = job.run()

    assert result.exit_code == 0
    assert not paths.rr_lastmod.is_file()
    tracked = subprocess.run(
        ["git", "-C", str(paths.vault), "ls-files", "ledger/rr_lastmod.jsonl"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert tracked.strip() == "ledger/rr_lastmod.jsonl"
    status = subprocess.run(
        ["git", "-C", str(paths.vault), "status", "--porcelain", "ledger/rr_lastmod.jsonl"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert status == ""  # committed, not left dirty


# -- RR backlog over cap: attention, exit 4 ---------------------------------------------------


def test_scheduled_job_rr_backlog_over_cap_is_attention_exit4(
    git_vault, mock_transport_factory, fake_clock
) -> None:
    paths = git_vault
    _seed_required_state(paths, cfbd_month="2026-10")
    now_value = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    _precache_cfbd_season(paths, 2026)

    slug_a = "cfb-old-team-a-2019-09-07"
    slug_b = "cfb-old-team-b-2019-09-14"
    sitemap_xml = _sitemap_xml(
        [(slug_a, "2026-01-01T00:00:00+00:00"), (slug_b, "2026-02-01T00:00:00+00:00")]
    )

    responses = _cfbd_ok_responses(2026, include_teams_fbs=False)
    responses["https://ratingsreference.com/robots.txt"] = (404, b"nf", {})
    responses[SITEMAP_URL] = (200, sitemap_xml, {})
    responses[f"https://ratingsreference.com/api/telecast/{slug_a}.json"] = (200, b"{}", {})
    responses[f"https://ratingsreference.com/api/telecast/{slug_b}.json"] = (200, b"{}", {})

    handle = mock_transport_factory(responses)
    runtime = _runtime(paths, handle, now=lambda: now_value, fake_clock=fake_clock)

    job = ScheduledJob(
        runtime, token="test-token", now=lambda: now_value, trigger="manual", rr_cap=1
    )
    result = job.run()

    assert result.exit_code == 4
    kinds = {item.kind for item in result.items}
    assert "rr_backlog" in kinds


# -- clean run: no attention, exit 0 -----------------------------------------------------------


def test_scheduled_job_clean_run_no_attention_exit0(
    git_vault, mock_transport_factory, fake_clock
) -> None:
    paths = git_vault
    _seed_required_state(paths, cfbd_month="2026-10")
    now_value = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)

    responses = _cfbd_ok_responses(2026)
    responses["https://ratingsreference.com/robots.txt"] = (404, b"nf", {})
    responses[SITEMAP_URL] = (200, _empty_sitemap_xml(), {})

    handle = mock_transport_factory(responses)
    runtime = _runtime(paths, handle, now=lambda: now_value, fake_clock=fake_clock)

    job = ScheduledJob(runtime, token="test-token", now=lambda: now_value, trigger="manual")
    result = job.run()

    assert result.exit_code == 0
    assert not any(item.severity == "attention" for item in result.items)

    saved_state = load_state(paths.job_state)
    assert saved_state.last_status == "ok"
    assert saved_state.last_success_at == now_value


# -- dry-run: zero requests, writes nothing ----------------------------------------------------


def test_scheduled_job_dry_run_sends_zero_requests_and_writes_nothing(
    git_vault, mock_transport_factory, fake_clock
) -> None:
    paths = git_vault
    _seed_required_state(paths, cfbd_month="2026-10")
    now_value = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)

    handle = mock_transport_factory({})
    runtime = _runtime(paths, handle, now=lambda: now_value, fake_clock=fake_clock)

    job = ScheduledJob(runtime, token=None, now=lambda: now_value, trigger="manual", dry_run=True)
    result = job.run()

    assert handle.requests == []
    assert not paths.job_state.is_file()
    assert not (paths.raw / "cfbd").exists()
    assert result.exit_code == 0


# -- off-season: no CFBD calls, RR still runs, season_past_freeze attention --------------------


def test_scheduled_job_off_season_season_past_freeze_attention(
    git_vault, mock_transport_factory, fake_clock
) -> None:
    paths = git_vault
    _seed_required_state(paths, cfbd_month="2027-03")
    now_value = datetime(2027, 3, 1, tzinfo=UTC)

    responses = {
        "https://ratingsreference.com/robots.txt": (404, b"nf", {}),
        SITEMAP_URL: (200, _empty_sitemap_xml(), {}),
    }
    handle = mock_transport_factory(responses)
    runtime = _runtime(paths, handle, now=lambda: now_value, fake_clock=fake_clock)

    job = ScheduledJob(runtime, token="test-token", now=lambda: now_value, trigger="manual")
    result = job.run()

    assert result.exit_code == 4
    kinds = {item.kind for item in result.items}
    assert "season_past_freeze" in kinds
    assert all("collegefootballdata.com" not in r.url for r in handle.requests)


# -- VaultCommitError on push: push_failed, exit 3 ----------------------------------------------


def test_scheduled_job_vault_commit_error_on_push_records_push_failed_exit3(
    git_vault, mock_transport_factory, fake_clock, monkeypatch
) -> None:
    paths = git_vault
    _seed_required_state(paths, cfbd_month="2026-10")
    now_value = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)

    responses = _cfbd_ok_responses(2026)
    responses["https://ratingsreference.com/robots.txt"] = (404, b"nf", {})
    responses[SITEMAP_URL] = (200, _empty_sitemap_xml(), {})

    handle = mock_transport_factory(responses)
    runtime = _runtime(paths, handle, now=lambda: now_value, fake_clock=fake_clock)

    def _raise_commit(*args, **kwargs):
        raise VaultCommitError("git subcommand push exited 1")

    monkeypatch.setattr(runtime.vault, "commit_batch", _raise_commit)

    job = ScheduledJob(runtime, token="test-token", now=lambda: now_value, trigger="manual")
    result = job.run()

    assert result.exit_code == 3
    kinds = {item.kind for item in result.items}
    assert "push_failed" in kinds
    assert not paths.job_state.is_file()


# -- nothing-due no-op (backup cron slots) -----------------------------------------------------


def test_scheduled_job_schedule_trigger_nothing_due_is_exit5_no_requests_no_state_change(
    git_vault, mock_transport_factory, fake_clock
) -> None:
    paths = git_vault
    _seed_required_state(paths, cfbd_month="2026-10")

    last_success = datetime(2026, 10, 29, 0, 0, tzinfo=UTC)  # Wed 2026-10-28 20:00 ET slot
    save_state(
        paths.job_state,
        JobState(
            season=2026,
            last_success_at=last_success,
            last_attempt_at=last_success,
            last_status="ok",
            last_window_start=last_success,
        ),
    )
    before_bytes = paths.job_state.read_bytes()

    now_value = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)  # Friday backup slot: nothing due
    handle = mock_transport_factory({})
    runtime = _runtime(paths, handle, now=lambda: now_value, fake_clock=fake_clock)

    job = ScheduledJob(runtime, token="test-token", now=lambda: now_value, trigger="schedule")
    result = job.run()

    assert result.exit_code == 5
    assert result.items == []
    assert result.counts == {"skipped": 1}
    assert handle.requests == []
    assert paths.job_state.read_bytes() == before_bytes


def test_scheduled_job_backup_slot_after_failed_attempt_is_exit5_no_requests(
    git_vault, mock_transport_factory, fake_clock
) -> None:
    paths = git_vault
    _seed_required_state(paths, cfbd_month="2026-10")

    # The Sunday 10:00 ET main slot ran at 14:05Z and a step failed, so
    # last_success_at is still the previous Wednesday's run.
    save_state(
        paths.job_state,
        JobState(
            season=2026,
            last_success_at=datetime(2026, 10, 1, 0, 5, tzinfo=UTC),
            last_attempt_at=datetime(2026, 10, 4, 14, 5, tzinfo=UTC),
            last_status="attention",
            last_window_start=datetime(2026, 10, 1, 0, 5, tzinfo=UTC),
        ),
    )
    before_bytes = paths.job_state.read_bytes()

    now_value = datetime(2026, 10, 4, 16, 0, tzinfo=UTC)  # Sunday backup slot
    handle = mock_transport_factory({})
    runtime = _runtime(paths, handle, now=lambda: now_value, fake_clock=fake_clock)

    job = ScheduledJob(runtime, token="test-token", now=lambda: now_value, trigger="schedule")
    result = job.run()

    assert result.exit_code == 5
    assert handle.requests == []
    assert paths.job_state.read_bytes() == before_bytes


def test_scheduled_job_cfbd_502_sets_retry_pending_and_next_backup_slot_retries(
    git_vault, mock_transport_factory, fake_clock
) -> None:
    paths = git_vault
    _seed_required_state(paths, cfbd_month="2026-10")
    prior_success = datetime(2026, 10, 1, 0, 5, tzinfo=UTC)  # Wed 2026-09-30 20:05 ET
    save_state(
        paths.job_state,
        JobState(
            season=2026,
            last_success_at=prior_success,
            last_attempt_at=prior_success,
            last_status="ok",
            last_window_start=prior_success,
        ),
    )

    # Sunday 10:00 ET main slot: CFBD's gateway answers 502 on every attempt.
    main_slot = datetime(2026, 10, 4, 14, 5, tzinfo=UTC)
    down = _cfbd_ok_responses(2026)
    games_url = "https://api.collegefootballdata.com/games?seasonType=both&year=2026"
    down[games_url] = (502, b"<html>Bad Gateway</html>", {})
    down["https://ratingsreference.com/robots.txt"] = (404, b"nf", {})
    down[SITEMAP_URL] = (200, _empty_sitemap_xml(), {})
    handle = mock_transport_factory(down)
    runtime = _runtime(paths, handle, now=lambda: main_slot, fake_clock=fake_clock)
    result = ScheduledJob(
        runtime, token="test-token", now=lambda: main_slot, trigger="schedule"
    ).run()

    assert result.exit_code == 4
    assert [item.kind for item in result.items if item.kind == "cfbd_step_failed"] == [
        "cfbd_step_failed"
    ]
    state = load_state(paths.job_state)
    assert state.retry_pending is True
    assert state.last_success_at == prior_success

    # The 16:00 ET backup slot is due again and, with CFBD back, clears the flag.
    backup_slot = datetime(2026, 10, 4, 20, 0, tzinfo=UTC)
    up = _cfbd_ok_responses(2026)
    up["https://ratingsreference.com/robots.txt"] = (404, b"nf", {})
    up[SITEMAP_URL] = (200, _empty_sitemap_xml(), {})
    handle = mock_transport_factory(up)
    runtime = _runtime(paths, handle, now=lambda: backup_slot, fake_clock=fake_clock)
    result = ScheduledJob(
        runtime, token="test-token", now=lambda: backup_slot, trigger="schedule"
    ).run()

    assert result.exit_code != 5
    assert any(req.url == games_url for req in handle.requests)
    assert result.counts["cfbd_failed"] == 0
    state = load_state(paths.job_state)
    assert state.retry_pending is False
    assert state.last_success_at == backup_slot

    # With the flag cleared, the next backup slot is a no-op again.
    later = datetime(2026, 10, 4, 22, 0, tzinfo=UTC)
    handle = mock_transport_factory({})
    runtime = _runtime(paths, handle, now=lambda: later, fake_clock=fake_clock)
    result = ScheduledJob(runtime, token="test-token", now=lambda: later, trigger="schedule").run()
    assert result.exit_code == 5
    assert handle.requests == []


def test_scheduled_job_manual_trigger_always_runs_even_with_no_main_slot_due(
    git_vault, mock_transport_factory, fake_clock
) -> None:
    paths = git_vault
    _seed_required_state(paths, cfbd_month="2026-10")

    last_success = datetime(2026, 10, 29, 0, 0, tzinfo=UTC)
    save_state(
        paths.job_state,
        JobState(
            season=2026,
            last_success_at=last_success,
            last_attempt_at=last_success,
            last_status="ok",
            last_window_start=last_success,
        ),
    )

    now_value = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
    responses = _cfbd_ok_responses(2026)
    responses["https://ratingsreference.com/robots.txt"] = (404, b"nf", {})
    responses[SITEMAP_URL] = (200, _empty_sitemap_xml(), {})

    handle = mock_transport_factory(responses)
    runtime = _runtime(paths, handle, now=lambda: now_value, fake_clock=fake_clock)

    job = ScheduledJob(runtime, token="test-token", now=lambda: now_value, trigger="manual")
    result = job.run()

    assert result.exit_code != 5
    saved_state = load_state(paths.job_state)
    assert saved_state.last_success_at == now_value


def test_cli_job_run_exit5_prints_nothing_due_message(
    git_vault, mock_transport_factory, patched_client, monkeypatch, capsys
) -> None:
    paths = git_vault
    _seed_required_state(paths, cfbd_month="2026-10")

    last_success = datetime(2026, 10, 29, 0, 0, tzinfo=UTC)
    save_state(
        paths.job_state,
        JobState(
            season=2026,
            last_success_at=last_success,
            last_attempt_at=last_success,
            last_status="ok",
            last_window_start=last_success,
        ),
    )

    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            return cls(2026, 10, 30, 12, 0, tzinfo=UTC)

    monkeypatch.setattr(cli, "datetime", _FixedDateTime)

    handle = mock_transport_factory({})
    patched_client(handle)

    exit_code = main(["job", "run", "--trigger", "schedule", "--no-commit", "--dry-run"])

    assert exit_code == 5
    out = capsys.readouterr().out
    assert "nothing due since last attempt" in out
    assert handle.requests == []


# -- CLI: dummy CFBD key never leaks ------------------------------------------------------------


def test_cli_job_run_dummy_key_never_leaks(
    git_vault, mock_transport_factory, patched_client, monkeypatch, capsys, caplog
) -> None:
    paths = git_vault
    real_now = datetime.now(UTC)
    season = cli.season_of(real_now.date())
    _seed_required_state(paths, cfbd_month=real_now.strftime("%Y-%m"))
    monkeypatch.setenv("CFBD_API_KEY", "SENTINEL-JOB-KEY-XYZ")

    responses = _cfbd_ok_responses(season)
    responses["https://ratingsreference.com/robots.txt"] = (404, b"nf", {})
    responses[SITEMAP_URL] = (200, _empty_sitemap_xml(), {})

    handle = mock_transport_factory(responses)
    patched_client(handle)

    with caplog.at_level("DEBUG"):
        exit_code = main(["job", "run", "--trigger", "manual", "--no-commit"])

    assert exit_code == 0

    for req in handle.requests:
        if req.url.endswith("robots.txt") or "/api/telecast/" in req.url or req.url == SITEMAP_URL:
            continue
        assert req.headers.get("authorization") == "Bearer SENTINEL-JOB-KEY-XYZ"

    captured = capsys.readouterr()
    assert "SENTINEL-JOB-KEY-XYZ" not in captured.out
    assert "SENTINEL-JOB-KEY-XYZ" not in captured.err
    for record in caplog.records:
        assert "SENTINEL-JOB-KEY-XYZ" not in record.getMessage()
    for path in paths.vault.rglob("*"):
        if path.is_file():
            assert b"SENTINEL-JOB-KEY-XYZ" not in path.read_bytes()


# -- CLI: --attention-out writes the body outside the vault -------------------------------------


def test_cli_job_run_attention_out_writes_season_past_freeze_body(
    git_vault, mock_transport_factory, patched_client, monkeypatch, tmp_path
) -> None:
    paths = git_vault
    _seed_required_state(paths, cfbd_month="2027-03")

    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            return cls(2027, 3, 1, tzinfo=UTC)

    monkeypatch.setattr(cli, "datetime", _FrozenDateTime)
    monkeypatch.delenv("CFBD_API_KEY", raising=False)

    handle = mock_transport_factory({})
    patched_client(handle)

    out_path = tmp_path / "attention.md"
    exit_code = main(
        [
            "job",
            "run",
            "--trigger",
            "manual",
            "--no-commit",
            "--dry-run",
            "--attention-out",
            str(out_path),
        ]
    )

    assert exit_code == 4
    body = out_path.read_text(encoding="utf-8")
    assert "past its freeze date" in body
    assert str(paths.vault) not in str(out_path)


# -- WR-12: non-BoothReviewError exceptions at a step boundary -----------------------------------


def _wr12_job(paths, handle, fake_clock, now_value) -> ScheduledJob:
    runtime = _runtime(paths, handle, now=lambda: now_value, fake_clock=fake_clock)
    return ScheduledJob(runtime, token="test-token", now=lambda: now_value, trigger="manual")


def _wr12_responses() -> dict:
    responses = _cfbd_ok_responses(2026, include_teams_fbs=False)
    responses["https://ratingsreference.com/robots.txt"] = (404, b"nf", {})
    responses[SITEMAP_URL] = (200, _empty_sitemap_xml(), {})
    return responses


_SECRET_MESSAGE = "leak https://example.invalid/x?key=abc123 Team Example"


def test_scheduled_job_unexpected_506_step_error_is_count_only_attention_state_saved(
    git_vault, mock_transport_factory, fake_clock, monkeypatch
) -> None:
    paths = git_vault
    _seed_required_state(paths, cfbd_month="2026-10")
    _precache_cfbd_season(paths, 2026)
    now_value = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)

    def _boom(*args, **kwargs):
        raise ValueError(_SECRET_MESSAGE)

    monkeypatch.setattr("booth_review.job.runner.find_506_gaps", _boom)

    handle = mock_transport_factory(_wr12_responses())
    result = _wr12_job(paths, handle, fake_clock, now_value).run()

    assert result.exit_code == 4
    step_items = [item for item in result.items if item.kind == "sports506_step_failed"]
    assert [item.line for item in step_items] == ["sports506 step failed: ValueError"]
    assert all("key=" not in item.line and "Team" not in item.line for item in result.items)

    saved_state = load_state(paths.job_state)
    assert saved_state.last_attempt_at == now_value
    assert saved_state.last_success_at is None  # a failed step never advances success
    assert saved_state.last_status == "failed"  # IN-05


def test_scheduled_job_unexpected_rr_step_error_still_runs_506_step(
    git_vault, mock_transport_factory, fake_clock, monkeypatch
) -> None:
    paths = git_vault
    _seed_required_state(paths, cfbd_month="2026-10")
    _precache_cfbd_season(paths, 2026)
    now_value = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)

    def _boom(self, **kwargs):
        raise KeyError(_SECRET_MESSAGE)

    monkeypatch.setattr(
        "booth_review.sources.ratingsref.collector.RatingsRefCollector.refresh", _boom
    )
    gap_calls: list[int] = []

    def _record_gaps(paths_arg, season, games, now):
        gap_calls.append(season)
        return find_506_gaps(paths_arg, season, games, now)

    monkeypatch.setattr("booth_review.job.runner.find_506_gaps", _record_gaps)

    handle = mock_transport_factory(_wr12_responses())
    result = _wr12_job(paths, handle, fake_clock, now_value).run()

    assert result.exit_code == 4
    assert "rr step failed: KeyError" in [item.line for item in result.items]
    assert gap_calls == [2026]
    assert load_state(paths.job_state).last_attempt_at == now_value


def test_scheduled_job_unexpected_error_with_unsafe_class_name_reports_exception(
    git_vault, mock_transport_factory, fake_clock, monkeypatch
) -> None:
    paths = git_vault
    _seed_required_state(paths, cfbd_month="2026-10")
    _precache_cfbd_season(paths, 2026)
    now_value = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)

    class Odd_Error2(Exception):  # deliberately off-whitelist
        pass

    def _boom(*args, **kwargs):
        raise Odd_Error2(_SECRET_MESSAGE)

    monkeypatch.setattr("booth_review.job.runner.find_506_gaps", _boom)

    handle = mock_transport_factory(_wr12_responses())
    result = _wr12_job(paths, handle, fake_clock, now_value).run()

    assert result.exit_code == 4
    assert "sports506 step failed: Exception" in [item.line for item in result.items]


def test_scheduled_job_state_save_oserror_is_attention_exit4(
    git_vault, mock_transport_factory, fake_clock, monkeypatch
) -> None:
    paths = git_vault
    _seed_required_state(paths, cfbd_month="2026-10")
    _precache_cfbd_season(paths, 2026)
    now_value = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)

    def _boom(*args, **kwargs):
        raise OSError(_SECRET_MESSAGE)

    monkeypatch.setattr("booth_review.job.runner.save_state", _boom)

    handle = mock_transport_factory(_wr12_responses())
    result = _wr12_job(paths, handle, fake_clock, now_value).run()

    assert result.exit_code == 4
    assert "state step failed: OSError" in [item.line for item in result.items]


def test_scheduled_job_commit_vault_state_error_still_propagates(
    git_vault, mock_transport_factory, fake_clock, monkeypatch
) -> None:
    paths = git_vault
    _seed_required_state(paths, cfbd_month="2026-10")
    _precache_cfbd_season(paths, 2026)
    now_value = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)

    handle = mock_transport_factory(_wr12_responses())
    job = _wr12_job(paths, handle, fake_clock, now_value)

    def _busy(*args, **kwargs):
        raise VaultStateError("vault is locked by another booth-review process")

    monkeypatch.setattr(job._runtime.vault, "commit_batch", _busy)

    with pytest.raises(VaultStateError):
        job.run()


# -- update mode (Plan 05-07): build, site, deploy_ready, staleness, run report ------------------

_REPO_ROOT = Path(__file__).parent.parent
_SPIKE_DIR = Path(__file__).parent / "fixtures" / "spike"
_BUILD_DIR = Path(__file__).parent / "fixtures" / "build"
_REFERENCE_DIR = Path(__file__).parent / "fixtures" / "reference"
UPDATE_NOW = datetime(2025, 10, 8, 12, 0, tzinfo=UTC)
_KEY_CANARY = "SENTINEL-UPDATE-KEY-ABC"
_COUNT_KINDS = {
    "people_review_due",
    "unresolved_teams",
    "sports506_missing",
    "sports506_stale",
    "espnpr_week_unsaved",
}


def _git(paths, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(paths.vault), *args], check=True, capture_output=True, text=True
    ).stdout


def _update_cfbd_responses(season: int = 2025) -> dict[str, tuple[int, bytes, dict[str, str]]]:
    """The build fixture's own bytes as CFBD's answers, so the refresh leaves the
    season inputs byte-identical."""
    base = "https://api.collegefootballdata.com"
    files = {
        "/games": _SPIKE_DIR / "cfbd_games_2025.json",
        "/games/media": _BUILD_DIR / "cfbd" / "media_2025.json",
        "/lines": _BUILD_DIR / "cfbd" / "lines_2025.json",
        "/metrics/wp/pregame": _BUILD_DIR / "cfbd" / "wp_pregame_2025.json",
        "/rankings": _BUILD_DIR / "cfbd" / "rankings_2025.json",
    }
    responses: dict[str, tuple[int, bytes, dict[str, str]]] = {
        f"{base}/robots.txt": (404, b"nf", {}),
        "https://ratingsreference.com/robots.txt": (404, b"nf", {}),
        SITEMAP_URL: (200, _empty_sitemap_xml(), {}),
    }
    for path, fixture in files.items():
        responses[f"{base}{path}?seasonType=both&year={season}"] = (200, fixture.read_bytes(), {})
    responses[f"{base}/teams/fbs?year={season}"] = (
        200,
        (_BUILD_DIR / "cfbd" / "teams_fbs_2025.json").read_bytes(),
        {},
    )
    return responses


@pytest.fixture
def update_vault(git_vault, tmp_path, monkeypatch):
    """A git vault ready for `ScheduledJob(update=True)` at UPDATE_NOW: the 2025 build
    inputs, a cached RR sitemap, the required ledgers, 2014-2024 frozen, and one
    accepted baseline from a plain build."""
    from test_cli_build import _seed_build_raw

    from booth_review.build.pipeline import run_build

    paths = git_vault
    _seed_build_raw(paths)
    reference = tmp_path / "reference_ext"
    shutil.copytree(_REFERENCE_DIR, reference)
    with (reference / "network_rarity.csv").open("a", encoding="utf-8", newline="") as rarity_fh:
        rarity_fh.write(
            "ecn,false\necn2,false\nespn,false\nespn2,false\nespnu,false\nespn-deportes,false\n"
        )
    with (reference / "networks.csv").open("a", encoding="utf-8", newline="") as fh:
        fh.write("ECN,ecn,Example Cable Network,family-ecn,cable,main,,,\n")
        fh.write("ECN2,ecn2,Example Cable Network 2,family-ecn,cable,main,,,\n")
        fh.write("ESPN,espn,ESPN,family-espn,cable,main,,,\n")
        fh.write("ESPN2,espn2,ESPN2,family-espn,cable,main,,,\n")
        fh.write("ESPNU,espnu,ESPNU,family-espn,cable,main,,,\n")
        fh.write("ESPN Deportes,espn-deportes,ESPN Deportes,family-espn,cable,spanish,,,\n")
    monkeypatch.setenv("BOOTH_REVIEW_REFERENCE", str(reference))
    monkeypatch.setenv("BOOTH_REVIEW_SITE_SRC", str(_REPO_ROOT / "site"))
    monkeypatch.setenv("BOOTH_REVIEW_DOCS", str(_REPO_ROOT / "docs"))
    monkeypatch.setenv("CFBD_API_KEY", _KEY_CANARY)

    _seed_required_state(paths, cfbd_month="2025-10")
    _freeze_seasons(paths, range(2014, 2025))
    sitemap = paths.raw / "ratingsref" / "sitemap" / "2025-10-01.xml"
    sitemap.parent.mkdir(parents=True, exist_ok=True)
    sitemap.write_bytes(_empty_sitemap_xml())
    run_build(paths, reference, commit=False, accept_baseline=True)
    _git(paths, "add", "-A")
    _git(paths, "commit", "-q", "-m", "test: seed update vault")
    _git(paths, "push", "-q", "origin", "main")
    return paths


def _update_job(paths, handle, fake_clock, tmp_path, *, now=UPDATE_NOW, trigger="manual", **kw):
    runtime = _runtime(paths, handle, now=lambda: now, fake_clock=fake_clock)
    kw.setdefault("token", "test-token")
    kw.setdefault("site_out", tmp_path / "site-out")
    return ScheduledJob(runtime, now=lambda: now, trigger=trigger, update=True, **kw)


def _kinds(result) -> set[str]:
    return {item.kind for item in result.items}


def _build_commits(paths) -> int:
    return _git(paths, "log", "--format=%s").count("build: all")


def test_update_requires_site_out(git_vault, mock_transport_factory, fake_clock) -> None:
    runtime = _runtime(
        git_vault, mock_transport_factory({}), now=lambda: UPDATE_NOW, fake_clock=fake_clock
    )
    with pytest.raises(ValueError):
        ScheduledJob(runtime, token=None, now=lambda: UPDATE_NOW, trigger="manual", update=True)


def test_update_clean_run_builds_assembles_and_reports_deploy_ready(
    update_vault, mock_transport_factory, fake_clock, tmp_path, capsys
) -> None:
    paths = update_vault
    before = _build_commits(paths)
    handle = mock_transport_factory(_update_cfbd_responses())
    job = _update_job(paths, handle, fake_clock, tmp_path)
    result = job.run()

    assert result.deploy_ready is True
    assert result.exit_code in (0, 4)
    assert _kinds(result) <= _COUNT_KINDS | {"cfbd_remaining", "missed_runs", "failed_attempts"}
    assert (tmp_path / "site-out" / "index.html").is_file()
    assert load_state(paths.job_state).last_build_at == UPDATE_NOW
    assert _build_commits(paths) == before + 1
    out = capsys.readouterr().out
    assert "build: telecasts " in out
    assert "build: season 2025 " in out
    assert "review: people new " in out
    assert "cfbd key check: passed" in out
    assert _KEY_CANARY not in out


def test_update_regression_block_holds_deploy_and_keeps_site_data(
    update_vault, mock_transport_factory, fake_clock, tmp_path
) -> None:
    paths = update_vault
    site_data = paths.processed / "site-data.json"
    before = site_data.read_bytes()
    state_before = load_state(paths.job_state)
    next(iter(sorted((paths.raw / "ratingsref" / "telecast" / "2025").glob("*.json")))).unlink()

    handle = mock_transport_factory(_update_cfbd_responses())
    result = _update_job(paths, handle, fake_clock, tmp_path).run()

    assert result.deploy_ready is False
    assert "build_blocked" in _kinds(result)
    assert result.exit_code == 4
    assert site_data.read_bytes() == before
    state_after = load_state(paths.job_state)
    assert state_after.last_build_at == state_before.last_build_at
    # D-09 / WR-06: a guard-blocked build is attention, not a failed run.
    assert state_after.last_status == "attention"
    assert state_after.last_success_at == UPDATE_NOW
    assert not (tmp_path / "site-out").exists()


def test_update_missing_bowl_row_is_a_count_item_and_deploy_stays_ready(
    update_vault, mock_transport_factory, fake_clock, tmp_path, monkeypatch
) -> None:
    paths = update_vault
    reference = tmp_path / "reference_nobowls"
    shutil.copytree(Path(__import__("os").environ["BOOTH_REVIEW_REFERENCE"]), reference)
    (reference / "bowls.csv").write_text(
        "cfbd_game_id,official_name,core_name,at_bowl,franchise\n", encoding="utf-8"
    )
    monkeypatch.setenv("BOOTH_REVIEW_REFERENCE", str(reference))

    handle = mock_transport_factory(_update_cfbd_responses())
    result = _update_job(paths, handle, fake_clock, tmp_path).run()

    assert "bowls_missing" in _kinds(result)
    assert result.deploy_ready is True


def test_update_people_review_and_missing_506_never_hold_the_deploy(
    update_vault, mock_transport_factory, fake_clock, tmp_path, monkeypatch
) -> None:
    paths = update_vault
    from booth_review.build.pipeline import BuildOutcome

    real = __import__("booth_review.job.runner", fromlist=["run_build"]).run_build

    def _with_review(*args, **kwargs) -> BuildOutcome:
        outcome = real(*args, **kwargs)
        counts = {**outcome.counts, "review_people_new": 3}
        return BuildOutcome(
            blocked=outcome.blocked,
            accepted=outcome.accepted,
            reasons=outcome.reasons,
            counts=counts,
            written=outcome.written,
            committed=outcome.committed,
        )

    monkeypatch.setattr("booth_review.job.runner.run_build", _with_review)
    handle = mock_transport_factory(_update_cfbd_responses())
    result = _update_job(paths, handle, fake_clock, tmp_path).run()

    assert "people_review_due" in _kinds(result)
    assert "sports506_missing" in _kinds(result)
    assert result.deploy_ready is True


def test_update_key_check_skipped_holds_deploy(
    update_vault, mock_transport_factory, fake_clock, tmp_path, monkeypatch
) -> None:
    monkeypatch.delenv("CFBD_API_KEY", raising=False)
    handle = mock_transport_factory(_update_cfbd_responses())
    result = _update_job(update_vault, handle, fake_clock, tmp_path).run()

    assert "site_key_check_skipped" in _kinds(result)
    assert result.deploy_ready is False
    assert result.exit_code == 4


def test_update_key_leak_records_item_saves_state_exit3(
    update_vault, mock_transport_factory, fake_clock, tmp_path, monkeypatch
) -> None:
    from booth_review.errors import KeyLeakError

    def _leak(**kwargs):
        raise KeyLeakError("CFBD key found in build output: x; output removed")

    monkeypatch.setattr("booth_review.job.runner.assemble_site", _leak)
    handle = mock_transport_factory(_update_cfbd_responses())
    result = _update_job(update_vault, handle, fake_clock, tmp_path).run()

    assert "site_key_check_failed" in _kinds(result)
    assert result.exit_code == 3
    assert result.deploy_ready is False
    state = load_state(update_vault.job_state)
    assert state.last_attempt_at == UPDATE_NOW
    # WR-06: a key leak is a failed run, so it never counts as a success.
    assert state.last_status == "failed"
    assert state.last_success_at != UPDATE_NOW


def test_update_build_state_error_is_an_item_and_a_failed_run(
    update_vault, mock_transport_factory, fake_clock, tmp_path, monkeypatch
) -> None:
    def _boom(*args, **kwargs):
        raise VaultStateError("secret detail that must not print")

    monkeypatch.setattr("booth_review.job.runner.run_build", _boom)
    handle = mock_transport_factory(_update_cfbd_responses())
    before = load_state(update_vault.job_state)
    result = _update_job(update_vault, handle, fake_clock, tmp_path).run()

    lines = [item.line for item in result.items if item.kind == "build_step_failed"]
    assert lines == ["build step failed: VaultStateError"]
    assert result.deploy_ready is False
    assert result.exit_code == 4
    # WR-06: a crashed build produced no site, so the run is not a success.
    state = load_state(update_vault.job_state)
    assert state.last_status == "failed"
    assert state.last_success_at == before.last_success_at
    assert state.last_attempt_at == UPDATE_NOW


def test_update_site_step_crash_is_a_failed_run(
    update_vault, mock_transport_factory, fake_clock, tmp_path, monkeypatch
) -> None:
    def _boom(**kwargs):
        raise OSError("secret detail that must not print")

    monkeypatch.setattr("booth_review.job.runner.assemble_site", _boom)
    handle = mock_transport_factory(_update_cfbd_responses())
    before = load_state(update_vault.job_state)
    result = _update_job(update_vault, handle, fake_clock, tmp_path).run()

    assert [i.line for i in result.items if i.kind == "site_step_failed"] == [
        "site step failed: OSError"
    ]
    assert result.deploy_ready is False
    assert result.exit_code == 4
    state = load_state(update_vault.job_state)
    assert state.last_status == "failed"
    assert state.last_success_at == before.last_success_at


def test_update_build_commit_error_is_push_failed_exit3(
    update_vault, mock_transport_factory, fake_clock, tmp_path, monkeypatch
) -> None:
    def _boom(*args, **kwargs):
        raise VaultCommitError("git subcommand push exited 1")

    monkeypatch.setattr("booth_review.job.runner.run_build", _boom)
    handle = mock_transport_factory(_update_cfbd_responses())
    result = _update_job(update_vault, handle, fake_clock, tmp_path).run()

    assert result.exit_code == 3
    assert "push_failed" in _kinds(result)
    assert any(item.line == "vault push failed at step build" for item in result.items)


@pytest.mark.parametrize("missing", ["audit/build_baseline.csv", "raw/ratingsref/sitemap"])
def test_update_missing_build_state_fails_before_any_request(
    update_vault, mock_transport_factory, fake_clock, tmp_path, missing
) -> None:
    paths = update_vault
    target = paths.vault / missing
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    head = _git(paths, "rev-parse", "HEAD")
    handle = mock_transport_factory(_update_cfbd_responses())

    with pytest.raises(VaultStateError):
        _update_job(paths, handle, fake_clock, tmp_path).run()

    assert handle.requests == []
    assert _git(paths, "rev-parse", "HEAD") == head


def test_non_update_run_does_not_build_or_assemble(
    update_vault, mock_transport_factory, fake_clock, tmp_path
) -> None:
    paths = update_vault
    before = _build_commits(paths)
    handle = mock_transport_factory(_update_cfbd_responses())
    runtime = _runtime(paths, handle, now=lambda: UPDATE_NOW, fake_clock=fake_clock)
    result = ScheduledJob(
        runtime, token="test-token", now=lambda: UPDATE_NOW, trigger="manual"
    ).run()

    assert result.deploy_ready is False
    assert _build_commits(paths) == before
    assert not (tmp_path / "site-out").exists()
    assert load_state(paths.job_state).last_build_at is None


# -- Task 2: staleness, run report, cfbd remaining, IN-02/04/05 -----------------------------------


def _save_build_state(paths, last_build_at, *, last_attempt_at=None) -> None:
    save_state(
        paths.job_state,
        JobState(
            season=2025,
            last_success_at=last_attempt_at or last_build_at,
            last_attempt_at=last_attempt_at or last_build_at,
            last_status="ok",
            last_window_start=last_build_at,
            retry_pending=False,
            last_build_at=last_build_at,
        ),
    )


def test_update_nothing_due_stale_build_exits_4_stale_only_writes_nothing(
    update_vault, mock_transport_factory, fake_clock, tmp_path
) -> None:
    paths = update_vault
    # Last attempt after the most recent main slot, so a backup slot has nothing due.
    now = datetime(2025, 10, 9, 12, 0, tzinfo=UTC)  # Thursday, after Wednesday 20:00 ET
    _save_build_state(paths, datetime(2025, 10, 4, 12, 0, tzinfo=UTC))
    paths_state = paths.job_state
    save_state(
        paths_state,
        JobState(
            season=2025,
            last_success_at=datetime(2025, 10, 9, 1, 0, tzinfo=UTC),
            last_attempt_at=datetime(2025, 10, 9, 1, 0, tzinfo=UTC),
            last_status="ok",
            last_window_start=datetime(2025, 10, 4, 12, 0, tzinfo=UTC),
            retry_pending=False,
            last_build_at=datetime(2025, 10, 4, 12, 0, tzinfo=UTC),
        ),
    )
    _git(paths, "add", "-A")
    _git(paths, "commit", "-q", "-m", "test: state")
    head = _git(paths, "rev-parse", "HEAD")
    handle = mock_transport_factory(_update_cfbd_responses())

    result = _update_job(paths, handle, fake_clock, tmp_path, now=now, trigger="schedule").run()

    assert result.exit_code == 4
    assert result.stale_only is True
    assert "build_stale" in _kinds(result)
    assert handle.requests == []
    assert _git(paths, "rev-parse", "HEAD") == head
    assert _git(paths, "status", "--porcelain") == ""
    assert not (tmp_path / "site-out").exists()


def test_update_nothing_due_fresh_build_exits_5(
    update_vault, mock_transport_factory, fake_clock, tmp_path
) -> None:
    paths = update_vault
    now = datetime(2025, 10, 9, 12, 0, tzinfo=UTC)
    stamp = datetime(2025, 10, 9, 1, 0, tzinfo=UTC)
    _save_build_state(paths, stamp)
    handle = mock_transport_factory(_update_cfbd_responses())

    result = _update_job(paths, handle, fake_clock, tmp_path, now=now, trigger="schedule").run()

    assert result.exit_code == 5
    assert result.stale_only is False
    assert handle.requests == []


def test_update_trail_staleness_item_does_not_change_deploy_ready(
    update_vault, mock_transport_factory, fake_clock, tmp_path, monkeypatch
) -> None:
    from datetime import date

    monkeypatch.setattr(
        "booth_review.job.runner.newest_listed", lambda paths, season: (date(2026, 6, 1), 9)
    )
    handle = mock_transport_factory(_update_cfbd_responses())
    result = _update_job(update_vault, handle, fake_clock, tmp_path).run()

    assert "plotted_trails_listed" in _kinds(result)
    assert result.deploy_ready is True


def test_update_staleness_helper_error_is_an_item_and_state_still_saved(
    update_vault, mock_transport_factory, fake_clock, tmp_path, monkeypatch
) -> None:
    def _boom(paths, season):
        raise ValueError("secret detail")

    monkeypatch.setattr("booth_review.job.runner.newest_listed", _boom)
    handle = mock_transport_factory(_update_cfbd_responses())
    result = _update_job(update_vault, handle, fake_clock, tmp_path).run()

    assert [i.line for i in result.items if i.kind == "staleness_step_failed"] == [
        "staleness step failed: ValueError"
    ]
    assert load_state(update_vault.job_state).last_attempt_at == UPDATE_NOW


def test_update_run_appends_one_count_only_report_line_in_the_state_commit(
    update_vault, mock_transport_factory, fake_clock, tmp_path
) -> None:
    paths = update_vault
    handle = mock_transport_factory(_update_cfbd_responses())
    _update_job(paths, handle, fake_clock, tmp_path).run()

    lines = (paths.ledger / "run_reports.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    report = json.loads(lines[0])
    assert set(report) == {
        "run_at",
        "trigger",
        "update",
        "mode",
        "deploy_ready",
        "cfbd_remaining_start",
        "cfbd_remaining_end",
        "attention",
        "counts",
    }
    assert report["update"] is True
    assert report["deploy_ready"] is True
    assert all(isinstance(v, int) and not isinstance(v, bool) for v in report["counts"].values())
    assert isinstance(report["attention"], int)
    assert _KEY_CANARY not in lines[0]
    changed = _git(paths, "show", "--name-only", "--format=%s", "HEAD").splitlines()
    assert changed[0].startswith("job: state")
    assert {"ledger/job_state.json", "ledger/run_reports.jsonl"} <= set(changed[1:])


def test_update_run_logs_cfbd_remaining_at_start_and_end(
    update_vault, mock_transport_factory, fake_clock, tmp_path, capsys
) -> None:
    handle = mock_transport_factory(_update_cfbd_responses())
    _update_job(update_vault, handle, fake_clock, tmp_path).run()
    out = capsys.readouterr().out
    assert "cfbd remaining at start: " in out
    assert "cfbd remaining at end: " in out


def test_state_commit_failure_adds_push_failed_state_exit3(
    git_vault, mock_transport_factory, fake_clock, monkeypatch
) -> None:
    paths = git_vault
    _seed_required_state(paths, cfbd_month="2026-10")
    now_value = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    responses = _cfbd_ok_responses(2026)
    responses["https://ratingsreference.com/robots.txt"] = (404, b"nf", {})
    responses[SITEMAP_URL] = (200, _empty_sitemap_xml(), {})
    handle = mock_transport_factory(responses)
    runtime = _runtime(paths, handle, now=lambda: now_value, fake_clock=fake_clock)
    real_commit = runtime.vault.commit_batch

    def _commit(message, *, paths):
        if message.startswith("job: state"):
            raise VaultCommitError("git subcommand push exited 1")
        return real_commit(message, paths=paths)

    monkeypatch.setattr(runtime.vault, "commit_batch", _commit)
    result = ScheduledJob(runtime, token="t", now=lambda: now_value, trigger="manual").run()

    assert result.exit_code == 3
    assert any(i.line == "vault push failed at step state" for i in result.items)


def test_failed_slots_add_a_failed_attempts_item(
    git_vault, mock_transport_factory, fake_clock
) -> None:
    paths = git_vault
    _seed_required_state(paths, cfbd_month="2026-10")
    success = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
    attempt = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    save_state(
        paths.job_state,
        JobState(
            season=2026,
            last_success_at=success,
            last_attempt_at=attempt,
            last_status="failed",
            last_window_start=success,
            retry_pending=False,
        ),
    )
    now_value = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    responses = _cfbd_ok_responses(2026)
    responses["https://ratingsreference.com/robots.txt"] = (404, b"nf", {})
    responses[SITEMAP_URL] = (200, _empty_sitemap_xml(), {})
    handle = mock_transport_factory(responses)
    runtime = _runtime(paths, handle, now=lambda: now_value, fake_clock=fake_clock)
    result = ScheduledJob(runtime, token="t", now=lambda: now_value, trigger="manual").run()

    assert "failed_attempts" in _kinds(result)


def test_past_freeze_check_runs_in_season_and_names_only_unfrozen_seasons(
    git_vault, mock_transport_factory, fake_clock
) -> None:
    paths = git_vault
    now_value = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    responses = _cfbd_ok_responses(2026)
    responses["https://ratingsreference.com/robots.txt"] = (404, b"nf", {})
    responses[SITEMAP_URL] = (200, _empty_sitemap_xml(), {})

    _seed_required_state(paths, cfbd_month="2026-10")
    handle = mock_transport_factory(responses)
    runtime = _runtime(paths, handle, now=lambda: now_value, fake_clock=fake_clock)
    clean = ScheduledJob(runtime, token="t", now=lambda: now_value, trigger="manual").run()
    assert "season_past_freeze" not in _kinds(clean)

    _freeze_seasons(paths, [y for y in range(2014, 2026) if y != 2024])
    handle = mock_transport_factory(responses)
    runtime = _runtime(paths, handle, now=lambda: now_value, fake_clock=fake_clock)
    result = ScheduledJob(runtime, token="t", now=lambda: now_value, trigger="manual").run()
    lines = [i.line for i in result.items if i.kind == "season_past_freeze"]
    assert len(lines) == 1
    assert lines[0].startswith("season 2024 is past its freeze date")


# -- Task 3: `job run --update --site-out --result-out` ------------------------------------------


def _freeze_cli_clock(monkeypatch, moment: datetime) -> None:
    class _Frozen(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            return moment

    monkeypatch.setattr(cli, "datetime", _Frozen)


def _cli_update_setup(paths, monkeypatch, mock_transport_factory, patched_client, moment):
    _freeze_cli_clock(monkeypatch, moment)
    real_month = datetime.now(UTC).strftime("%Y-%m")
    _seed_cfbd_ledger(paths, month=real_month)  # the budget reads the real clock
    handle = mock_transport_factory(_update_cfbd_responses())
    patched_client(handle)
    return handle


def test_cli_update_without_site_out_is_a_usage_error_and_sends_nothing(
    update_vault, mock_transport_factory, patched_client, monkeypatch
) -> None:
    handle = _cli_update_setup(
        update_vault, monkeypatch, mock_transport_factory, patched_client, UPDATE_NOW
    )
    assert main(["job", "run", "--trigger", "manual", "--update", "--no-commit"]) == 2
    assert handle.requests == []


def test_cli_update_writes_the_two_line_result_file(
    update_vault, mock_transport_factory, patched_client, monkeypatch, tmp_path
) -> None:
    _cli_update_setup(update_vault, monkeypatch, mock_transport_factory, patched_client, UPDATE_NOW)
    result_file = tmp_path / "out" / "result.txt"
    code = main(
        [
            "job",
            "run",
            "--trigger",
            "manual",
            "--no-commit",
            "--update",
            "--site-out",
            str(tmp_path / "site"),
            "--result-out",
            str(result_file),
        ]
    )
    assert code in (0, 4)
    assert result_file.read_text(encoding="utf-8").splitlines() == [
        "deploy_ready=true",
        "stale_only=false",
    ]
    assert (tmp_path / "site" / "index.html").is_file()


def test_cli_nothing_due_stale_run_writes_stale_only_and_attention_file(
    update_vault, mock_transport_factory, patched_client, monkeypatch, tmp_path
) -> None:
    moment = datetime(2025, 10, 9, 12, 0, tzinfo=UTC)
    _cli_update_setup(update_vault, monkeypatch, mock_transport_factory, patched_client, moment)
    attempt = datetime(2025, 10, 9, 1, 0, tzinfo=UTC)
    save_state(
        update_vault.job_state,
        JobState(
            season=2025,
            last_success_at=attempt,
            last_attempt_at=attempt,
            last_status="ok",
            last_window_start=attempt,
            retry_pending=False,
            last_build_at=datetime(2025, 10, 4, 12, 0, tzinfo=UTC),
        ),
    )
    result_file = tmp_path / "result.txt"
    attention = tmp_path / "attention.md"
    code = main(
        [
            "job",
            "run",
            "--trigger",
            "schedule",
            "--no-commit",
            "--update",
            "--site-out",
            str(tmp_path / "site"),
            "--result-out",
            str(result_file),
            "--attention-out",
            str(attention),
        ]
    )
    assert code == 4
    assert result_file.read_text(encoding="utf-8").splitlines() == [
        "deploy_ready=false",
        "stale_only=true",
    ]
    assert "days old" in attention.read_text(encoding="utf-8")


def test_cli_nothing_due_fresh_run_writes_not_ready_not_stale(
    update_vault, mock_transport_factory, patched_client, monkeypatch, tmp_path
) -> None:
    moment = datetime(2025, 10, 9, 12, 0, tzinfo=UTC)
    _cli_update_setup(update_vault, monkeypatch, mock_transport_factory, patched_client, moment)
    attempt = datetime(2025, 10, 9, 1, 0, tzinfo=UTC)
    _save_build_state(update_vault, attempt)
    result_file = tmp_path / "result.txt"
    code = main(
        [
            "job",
            "run",
            "--trigger",
            "schedule",
            "--no-commit",
            "--update",
            "--site-out",
            str(tmp_path / "site"),
            "--result-out",
            str(result_file),
        ]
    )
    assert code == 5
    assert result_file.read_text(encoding="utf-8").splitlines() == [
        "deploy_ready=false",
        "stale_only=false",
    ]


def test_cli_update_with_missing_state_exits_3_without_a_result_file(
    update_vault, mock_transport_factory, patched_client, monkeypatch, tmp_path
) -> None:
    _cli_update_setup(update_vault, monkeypatch, mock_transport_factory, patched_client, UPDATE_NOW)
    (update_vault.vault / "audit" / "build_baseline.csv").unlink()
    result_file = tmp_path / "result.txt"
    code = main(
        [
            "job",
            "run",
            "--trigger",
            "manual",
            "--no-commit",
            "--update",
            "--site-out",
            str(tmp_path / "site"),
            "--result-out",
            str(result_file),
        ]
    )
    assert code == 3
    assert not result_file.exists()


def test_cli_update_run_never_leaks_the_key_into_output(
    update_vault, mock_transport_factory, patched_client, monkeypatch, tmp_path, capsys, caplog
) -> None:
    _cli_update_setup(update_vault, monkeypatch, mock_transport_factory, patched_client, UPDATE_NOW)
    with caplog.at_level("DEBUG"):
        code = main(
            [
                "job",
                "run",
                "--trigger",
                "manual",
                "--no-commit",
                "--update",
                "--site-out",
                str(tmp_path / "site"),
                "--result-out",
                str(tmp_path / "result.txt"),
            ]
        )
    assert code in (0, 4)
    captured = capsys.readouterr()
    assert _KEY_CANARY not in captured.out
    assert _KEY_CANARY not in captured.err
    for record in caplog.records:
        assert _KEY_CANARY not in record.getMessage()
    for path in (tmp_path / "site").rglob("*"):
        if path.is_file():
            assert _KEY_CANARY.encode() not in path.read_bytes()


# -- 999.4-19: --nfl-rr-cap and GITHUB_TOKEN plumbing ---------------------------------------------


def _record_job_kwargs(monkeypatch) -> list[dict]:
    from booth_review.job.runner import JobRunResult

    calls: list[dict] = []

    class _RecordingJob:
        def __init__(self, runtime, **kwargs) -> None:
            calls.append(kwargs)

        def run(self) -> JobRunResult:
            return JobRunResult(exit_code=0, items=[], counts={}, window=None)

    monkeypatch.setattr(cli, "ScheduledJob", _RecordingJob)
    return calls


def test_cli_job_run_passes_nfl_rr_cap_and_the_github_token_without_printing_it(
    git_vault, mock_transport_factory, patched_client, monkeypatch, capsys, caplog
) -> None:
    from booth_review.sources.ratingsref.collector import REFRESH_CAP_DEFAULT

    _seed_required_state(git_vault, cfbd_month="2026-10")
    calls = _record_job_kwargs(monkeypatch)
    monkeypatch.setenv("GITHUB_TOKEN", "SENTINEL-GH-CLI-TOKEN")
    handle = mock_transport_factory({})
    patched_client(handle)

    with caplog.at_level("DEBUG"):
        code = main(["job", "run", "--nfl-rr-cap", "25", "--dry-run", "--no-commit"])

    assert code == 0
    assert calls[0]["nfl_rr_cap"] == 25
    assert calls[0]["rr_cap"] == REFRESH_CAP_DEFAULT
    assert calls[0]["github_token"] == "SENTINEL-GH-CLI-TOKEN"
    assert handle.requests == []
    captured = capsys.readouterr()
    assert "SENTINEL-GH-CLI-TOKEN" not in captured.out + captured.err
    assert all("SENTINEL-GH-CLI-TOKEN" not in r.getMessage() for r in caplog.records)


def test_cli_job_run_nfl_rr_cap_defaults_to_40_and_a_missing_token_is_none(
    git_vault, mock_transport_factory, patched_client, monkeypatch
) -> None:
    from booth_review.sources.ratingsref.collector import NFL_REFRESH_CAP_DEFAULT

    _seed_required_state(git_vault, cfbd_month="2026-10")
    calls = _record_job_kwargs(monkeypatch)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    patched_client(mock_transport_factory({}))

    assert main(["job", "run", "--rr-cap", "60", "--dry-run", "--no-commit"]) == 0

    assert calls[0]["nfl_rr_cap"] == NFL_REFRESH_CAP_DEFAULT == 40
    assert calls[0]["rr_cap"] == 60
    assert calls[0]["github_token"] is None


def test_job_run_help_lists_the_nfl_rr_cap_flag(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["job", "run", "--help"])
    assert exc.value.code == 0
    assert "--nfl-rr-cap" in capsys.readouterr().out


# -- 04.19 D-14: the ESPN Press Room hand-save reminder (read-only) ------------------------------

# Wednesday 2026-10-14 10:00 ET: ESPN Week 7's page is up (week 7 games Thu Oct 15 and
# Sat Oct 17); weeks 2 and 6 are already played, so 506 has pages to list too.
_ESPNPR_NOW = datetime(2026, 10, 14, 14, 0, tzinfo=UTC)


def _espnpr_games_json() -> bytes:
    rows = [
        (1, 2, "2026-09-12T16:00:00Z"),
        (2, 6, "2026-10-10T16:00:00Z"),
        (3, 7, "2026-10-15T23:30:00Z"),
        (4, 7, "2026-10-17T16:00:00Z"),
    ]
    return json.dumps(
        [
            {
                "id": game_id,
                "season": 2026,
                "week": week,
                "seasonType": "regular",
                "startDate": start,
                "homeTeam": "Home",
                "awayTeam": "Away",
            }
            for game_id, week, start in rows
        ]
    ).encode()


def _espnpr_responses() -> dict:
    responses = _cfbd_ok_responses(2026)
    responses["https://ratingsreference.com/robots.txt"] = (404, b"nf", {})
    responses[SITEMAP_URL] = (200, _empty_sitemap_xml(), {})
    games_url = "https://api.collegefootballdata.com/games?seasonType=both&year=2026"
    responses[games_url] = (200, _espnpr_games_json(), {})
    return responses


def _espnpr_run(paths, mock_transport_factory, fake_clock):
    handle = mock_transport_factory(_espnpr_responses())
    result = _wr12_job(paths, handle, fake_clock, _ESPNPR_NOW).run()
    return result, handle


def _save_espnpr_week(paths, label: str) -> None:
    page = paths.raw / "espnpr" / "2026" / "commentators" / f"wk-{label}.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_bytes(b"<html>synthetic</html>")
    _git(paths, "add", "-A")
    _git(paths, "commit", "-q", "-m", "test: seed espnpr page")
    _git(paths, "push", "-q", "origin", "main")


def test_espnpr_unsaved_week_is_one_item_and_no_request_reaches_the_site(
    git_vault, mock_transport_factory, fake_clock, capsys
) -> None:
    paths = git_vault
    _seed_required_state(paths, cfbd_month="2026-10")

    result, handle = _espnpr_run(paths, mock_transport_factory, fake_clock)

    espnpr = [item for item in result.items if item.kind == "espnpr_week_unsaved"]
    assert [item.line for item in espnpr] == [
        "espn pr 2026 commentators page not saved for week 7 (save "
        "https://espnpressroom.com/2026-27-espn-college-football-commentators-schedule/ "
        "by Monday, then booth-review import espnpr)"
    ]
    assert espnpr[0].severity == "attention"
    assert result.exit_code == 4
    assert not any(item.kind == "espnpr_gaps_step_failed" for item in result.items)
    assert all("espnpressroom" not in request.url for request in handle.requests)
    out = capsys.readouterr().out
    assert "espnpr: week 7 not saved" in out
    assert not (paths.raw / "espnpr").exists()  # read-only: nothing written
    assert load_state(paths.job_state).last_status == "attention"  # not a failed run


def test_espnpr_saved_week_adds_nothing(
    git_vault, mock_transport_factory, fake_clock, capsys
) -> None:
    paths = git_vault
    _seed_required_state(paths, cfbd_month="2026-10")
    _save_espnpr_week(paths, "7")

    result, handle = _espnpr_run(paths, mock_transport_factory, fake_clock)

    assert not any(item.kind.startswith("espnpr") for item in result.items)
    assert all("espnpressroom" not in request.url for request in handle.requests)
    assert "espnpr: current week saved" in capsys.readouterr().out


def test_espnpr_step_leaves_the_506_items_unchanged(
    git_vault, mock_transport_factory, fake_clock, monkeypatch
) -> None:
    # 04.5 D-10: every missing or stale 506 week is still listed, whatever ESPN PR holds.
    paths = git_vault
    _seed_required_state(paths, cfbd_month="2026-10")
    _save_espnpr_week(paths, "6")  # ESPN PR covers week 6; 506 must still list it

    with_step, _ = _espnpr_run(paths, mock_transport_factory, fake_clock)
    monkeypatch.setattr(ScheduledJob, "_run_espnpr_gap_step", lambda *args, **kwargs: None)
    without_step, _ = _espnpr_run(paths, mock_transport_factory, fake_clock)

    def _506(result) -> list:
        return [item for item in result.items if item.kind.startswith("sports506")]

    assert _506(with_step) == _506(without_step)
    assert [item.line for item in _506(with_step)] == ["506 2026 pages to save: weeks 2, 6"]
    assert [item.kind for item in with_step.items if item.kind.startswith("espnpr")] == [
        "espnpr_week_unsaved"
    ]
    assert not any(item.kind.startswith("espnpr") for item in without_step.items)


def test_espnpr_step_error_is_one_count_only_item_and_the_run_continues(
    git_vault, mock_transport_factory, fake_clock, monkeypatch
) -> None:
    paths = git_vault
    _seed_required_state(paths, cfbd_month="2026-10")

    def _boom(*args, **kwargs):
        raise ValueError(_SECRET_MESSAGE)

    monkeypatch.setattr("booth_review.job.runner.find_espnpr_gap", _boom)
    result, _ = _espnpr_run(paths, mock_transport_factory, fake_clock)

    step_items = [item for item in result.items if item.kind == "espnpr_gaps_step_failed"]
    assert [item.line for item in step_items] == ["espnpr_gaps step failed: ValueError"]
    assert not any(item.kind == "espnpr_week_unsaved" for item in result.items)
    assert "sports506_missing" in {item.kind for item in result.items}
    assert all("key=" not in item.line and "Team" not in item.line for item in result.items)
    assert result.exit_code == 4
    saved_state = load_state(paths.job_state)
    assert saved_state.last_attempt_at == _ESPNPR_NOW
    assert saved_state.last_status == "failed"


# -- schedule-only and rebuild-only modes (Phase 18 D-14/D-15/D-17) -------------------------


_FRI_NOW = datetime(2026, 10, 30, 22, 5, tzinfo=UTC)  # Fri 18:05 EDT
_WED_RUN = datetime(2026, 10, 29, 0, 5, tzinfo=UTC)  # Wed 20:05 EDT


def _seed_wednesday_run(paths) -> JobState:
    state = JobState(
        season=2026,
        last_success_at=_WED_RUN,
        last_attempt_at=_WED_RUN,
        last_status="ok",
        last_window_start=_WED_RUN,
    )
    save_state(paths.job_state, state)
    return state


def test_scheduled_job_schedule_mode_pulls_only_games_and_media(
    git_vault, mock_transport_factory, fake_clock
) -> None:
    paths = git_vault
    _seed_required_state(paths, cfbd_month="2026-10")
    before = _seed_wednesday_run(paths)

    handle = mock_transport_factory(_cfbd_ok_responses(2026))
    runtime = _runtime(paths, handle, now=lambda: _FRI_NOW, fake_clock=fake_clock, max_calls=3)
    result = ScheduledJob(
        runtime, token="test-token", now=lambda: _FRI_NOW, trigger="schedule"
    ).run()

    assert result.exit_code != 5
    urls = [r.url for r in handle.requests]
    data = [
        u
        for u in urls
        if u.startswith("https://api.collegefootballdata.com") and not u.endswith("robots.txt")
    ]
    assert sorted(u.split("?")[0] for u in data) == [
        "https://api.collegefootballdata.com/games",
        "https://api.collegefootballdata.com/games/media",
    ]
    for banned in ("506sports.com", "ratingsreference.com", "espn", "wikipedia", "retrosheet"):
        assert all(banned not in u for u in urls)

    after = load_state(paths.job_state)
    assert after.last_schedule_at == _FRI_NOW
    assert after.last_success_at == before.last_success_at
    assert after.last_attempt_at == before.last_attempt_at
    assert after.last_status == before.last_status


def test_auto_resolved_schedule_mode_lowers_the_cfbd_cap(
    git_vault, mock_transport_factory, fake_clock
) -> None:
    # 18-13 F6: the workflow passes --mode auto on cron, so the 3-call cap is chosen after the
    # mode resolves, not from the flag.
    paths = git_vault
    _seed_required_state(paths, cfbd_month="2026-10")
    _seed_wednesday_run(paths)
    handle = mock_transport_factory(_cfbd_ok_responses(2026))
    runtime = _runtime(
        paths, handle, now=lambda: _FRI_NOW, fake_clock=fake_clock, max_calls=JOB_CFBD_MAX_CALLS
    )
    ScheduledJob(
        runtime,
        token="test-token",
        now=lambda: _FRI_NOW,
        trigger="schedule",
        schedule_max_calls=JOB_CFBD_SCHEDULE_MAX_CALLS,
    ).run()
    assert runtime.budget is not None
    assert runtime.budget.run_cap == JOB_CFBD_SCHEDULE_MAX_CALLS


def test_cli_job_run_rejects_a_mode_on_a_scheduled_trigger(capsys) -> None:
    # 18-13 F15: a scheduled run picks its own mode from the clock; a --mode would be ignored.
    for mode in ("full", "schedule", "rebuild"):
        assert main(["job", "run", "--trigger", "schedule", "--mode", mode, "--dry-run"]) == 2
        assert "--mode" in capsys.readouterr().err


def test_failed_schedule_pull_leaves_last_schedule_at_so_a_backup_slot_retries(
    git_vault, mock_transport_factory, fake_clock
) -> None:
    # 18-13 F11: a schedule-only run whose CFBD pull failed must not mark the slot done, or the
    # 20:00/22:00 backups no-op.
    paths = git_vault
    _seed_required_state(paths, cfbd_month="2026-10")
    before = _seed_wednesday_run(paths)
    responses = _cfbd_ok_responses(2026)
    responses["https://api.collegefootballdata.com/games?seasonType=both&year=2026"] = (
        502,
        b"bad gateway",
        {},
    )
    handle = mock_transport_factory(responses)
    runtime = _runtime(paths, handle, now=lambda: _FRI_NOW, fake_clock=fake_clock, max_calls=3)
    ScheduledJob(runtime, token="test-token", now=lambda: _FRI_NOW, trigger="schedule").run()
    assert load_state(paths.job_state).last_schedule_at == before.last_schedule_at

    later = datetime(2026, 10, 31, 0, 5, tzinfo=UTC)  # Fri 20:05 EDT backup
    retry = mock_transport_factory(_cfbd_ok_responses(2026))
    runtime = _runtime(paths, retry, now=lambda: later, fake_clock=fake_clock, max_calls=3)
    result = ScheduledJob(runtime, token="test-token", now=lambda: later, trigger="schedule").run()
    assert result.exit_code != 5
    assert any("/games" in r.url for r in retry.requests)
    assert load_state(paths.job_state).last_schedule_at == later


def test_scheduled_job_schedule_mode_backup_slot_is_nothing_due(
    git_vault, mock_transport_factory, fake_clock
) -> None:
    paths = git_vault
    _seed_required_state(paths, cfbd_month="2026-10")
    state = _seed_wednesday_run(paths)
    save_state(paths.job_state, replace(state, last_schedule_at=_FRI_NOW))

    handle = mock_transport_factory({})
    later = datetime(2026, 10, 31, 0, 5, tzinfo=UTC)  # Fri 20:05 EDT backup
    runtime = _runtime(paths, handle, now=lambda: later, fake_clock=fake_clock)
    result = ScheduledJob(runtime, token="test-token", now=lambda: later, trigger="schedule").run()

    assert result.exit_code == 5
    assert handle.requests == []


def test_update_rebuild_mode_collects_nothing_and_deploys(
    update_vault, mock_transport_factory, fake_clock, tmp_path
) -> None:
    paths = update_vault
    before = load_state(paths.job_state)
    handle = mock_transport_factory({})
    later = UPDATE_NOW.replace(hour=18)
    job = _update_job(paths, handle, fake_clock, tmp_path, now=later, mode="rebuild")
    result = job.run()

    assert handle.requests == []
    assert result.deploy_ready is True
    assert (tmp_path / "site-out" / "index.html").is_file()
    after = load_state(paths.job_state)
    # 18-13 F11: a rebuild pulls no schedule, so it never stands in for a schedule slot.
    assert after.last_schedule_at == before.last_schedule_at
    assert after.last_build_at == later
    assert after.last_success_at == before.last_success_at
    assert after.last_attempt_at == before.last_attempt_at


def test_update_schedule_mode_requests_only_games_and_media_then_deploys(
    update_vault, mock_transport_factory, fake_clock, tmp_path
) -> None:
    paths = update_vault
    before = load_state(paths.job_state)
    handle = mock_transport_factory(_update_cfbd_responses())
    later = UPDATE_NOW.replace(hour=18)
    job = _update_job(paths, handle, fake_clock, tmp_path, now=later, mode="schedule")
    result = job.run()

    paths_requested = {
        u.split("?")[0].removeprefix("https://api.collegefootballdata.com")
        for u in (r.url for r in handle.requests)
        if "collegefootballdata" in u and not u.endswith("robots.txt")
    }
    assert paths_requested == {"/games", "/games/media"}
    assert all("ratingsreference" not in r.url for r in handle.requests)
    assert result.deploy_ready is True
    after = load_state(paths.job_state)
    assert after.last_schedule_at == later
    assert after.last_success_at == before.last_success_at


# -- Phase 24: hand-save reminders ride the comment-only path ----------------------------------

# Mon 2026-10-12 17:30 EDT: ESPN Week 7's commentators page is the one up now.
_REMINDER_MON = datetime(2026, 10, 12, 21, 30, tzinfo=UTC)
# Tue 2026-10-13 21:30 EDT: the Awful Announcing CFB slot, same week.
_REMINDER_TUE = datetime(2026, 10, 14, 1, 30, tzinfo=UTC)


def _reminder_vault(paths, *, last_attempt: datetime) -> str:
    """A committed vault with the 2026 games file and a saved state with nothing due."""
    _seed_required_state(paths, cfbd_month="2026-10")
    games = paths.raw / "cfbd" / "games" / "2026.json"
    games.parent.mkdir(parents=True, exist_ok=True)
    games.write_bytes(_espnpr_games_json())
    save_state(
        paths.job_state,
        JobState(
            season=2026,
            last_success_at=last_attempt,
            last_attempt_at=last_attempt,
            last_status="ok",
            last_window_start=last_attempt,
            retry_pending=False,
            last_build_at=last_attempt,
        ),
    )
    _git(paths, "add", "-A")
    _git(paths, "commit", "-q", "-m", "test: reminder vault")
    return _git(paths, "rev-parse", "HEAD")


def test_reminder_slot_exits_4_stale_only_and_writes_nothing(
    git_vault, mock_transport_factory, fake_clock
) -> None:
    paths = git_vault
    head = _reminder_vault(paths, last_attempt=datetime(2026, 10, 12, 12, 0, tzinfo=UTC))
    state_bytes = paths.job_state.read_bytes()
    handle = mock_transport_factory(_espnpr_responses())

    runtime = _runtime(paths, handle, now=lambda: _REMINDER_MON, fake_clock=fake_clock)
    result = ScheduledJob(
        runtime, token="test-token", now=lambda: _REMINDER_MON, trigger="schedule"
    ).run()

    assert result.exit_code == 4
    assert result.stale_only is True
    assert result.deploy_ready is False
    reminders = [item for item in result.items if item.kind == "reminder_espnpr"]
    assert [item.line for item in reminders] == [
        "reminder 2026 cfb week 7: save the espn pr commentators release "
        "https://espnpressroom.com/press-release-category/college-football/, "
        "then booth-review import espnpr"
    ]
    assert handle.requests == []
    assert _git(paths, "rev-parse", "HEAD") == head
    assert _git(paths, "status", "--porcelain") == ""
    assert paths.job_state.read_bytes() == state_bytes


def test_reminder_slot_with_the_page_saved_is_quiet(
    git_vault, mock_transport_factory, fake_clock
) -> None:
    paths = git_vault
    _reminder_vault(paths, last_attempt=datetime(2026, 10, 12, 12, 0, tzinfo=UTC))
    page = paths.raw / "espnpr" / "2026" / "commentators" / "wk-7.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_bytes(b"<html>synthetic</html>")
    handle = mock_transport_factory(_espnpr_responses())

    runtime = _runtime(paths, handle, now=lambda: _REMINDER_MON, fake_clock=fake_clock)
    result = ScheduledJob(
        runtime, token="test-token", now=lambda: _REMINDER_MON, trigger="schedule"
    ).run()

    assert result.exit_code == 5
    assert result.stale_only is False
    assert result.items == []


def test_outside_every_reminder_window_nothing_is_due(
    git_vault, mock_transport_factory, fake_clock
) -> None:
    paths = git_vault
    _reminder_vault(paths, last_attempt=datetime(2026, 10, 12, 12, 0, tzinfo=UTC))
    handle = mock_transport_factory(_espnpr_responses())
    moment = datetime(2026, 10, 12, 18, 0, tzinfo=UTC)  # Monday 14:00 EDT, before the slot

    runtime = _runtime(paths, handle, now=lambda: moment, fake_clock=fake_clock)
    result = ScheduledJob(runtime, token="test-token", now=lambda: moment, trigger="schedule").run()

    assert result.exit_code == 5
    assert result.stale_only is False
    assert handle.requests == []


def test_reminder_and_staleness_items_merge_into_one_result(
    update_vault, mock_transport_factory, fake_clock, tmp_path
) -> None:
    paths = update_vault
    old_build = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    _reminder_vault(paths, last_attempt=datetime(2026, 10, 12, 12, 0, tzinfo=UTC))
    save_state(
        paths.job_state,
        replace(load_state(paths.job_state), last_build_at=old_build),
    )
    _git(paths, "add", "-A")
    _git(paths, "commit", "-q", "-m", "test: old build")
    head = _git(paths, "rev-parse", "HEAD")
    handle = mock_transport_factory(_update_cfbd_responses())

    result = _update_job(
        paths, handle, fake_clock, tmp_path, now=_REMINDER_MON, trigger="schedule"
    ).run()

    assert result.exit_code == 4
    assert result.stale_only is True
    assert {"build_stale", "reminder_espnpr"} <= _kinds(result)
    assert handle.requests == []
    assert _git(paths, "rev-parse", "HEAD") == head
    assert not (tmp_path / "site-out").exists()


# -- Phase 25: the AA feed watch at the Tue slot (D-02, D-05, D-06, D-12) --------------------------

_AA_FEED_URL = AA_FEED_CANDIDATES["schedules"]
_AA_POST = "https://awfulannouncing.com/schedules/your-2026-week-10-college-football-announcing-schedule.html"
_REMINDER_TUE_LATE = datetime(2026, 10, 14, 2, 30, tzinfo=UTC)  # Tue 22:30 EDT
_AA_FEED = (
    Path(__file__)
    .parent.joinpath("fixtures", "aa", "feed_schedules_synthetic.xml")
    .read_text(encoding="utf-8")
    .replace("Tue, 03 Nov 2026", "Tue, 13 Oct 2026")
    .replace("Tue, 27 Oct 2026", "Tue, 06 Oct 2026")
    .replace("-0500", "-0400")
    .encode("utf-8")
)


def _seed_aa_ready(paths, *, weeks: dict[str, str] | None = None) -> None:
    """A fresh AA policy line and a verified feed, as the Phase 25 job needs them."""
    checked = (_REMINDER_TUE - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    row = {
        "source": "aa",
        "checked_at": checked,
        "robots_ok": True,
        "crawl_delay": None,
        "terms_ok": True,
    }
    paths.ledger.mkdir(parents=True, exist_ok=True)
    with (paths.ledger / "policy_checks.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")
    save_feed_state(
        paths,
        FeedWatchState(_AA_FEED_URL, None, None, None, None, dict(weeks or {}), []),
    )


def _aa_responses(base: dict | None = None) -> dict:
    responses = dict(base or {})
    responses["https://awfulannouncing.com/robots.txt"] = (
        200,
        b"User-agent: *\nAllow: /\n",
        {},
    )
    responses[_AA_FEED_URL] = (200, _AA_FEED, {})
    return responses


def _aa_requests(handle) -> list[str]:
    return [r.url for r in handle.requests if "awfulannouncing" in r.url]


def _comment_only_tue(paths, handle, fake_clock, when, *, dry_run=False):
    runtime = _runtime(paths, handle, now=lambda: when, fake_clock=fake_clock)
    return ScheduledJob(
        runtime, token="test-token", now=lambda: when, trigger="schedule", dry_run=dry_run
    ).run()


def _seeded_reminder_vault(paths, *, weeks: dict[str, str] | None = None) -> None:
    _reminder_vault(paths, last_attempt=datetime(2026, 10, 12, 12, 0, tzinfo=UTC))
    _seed_aa_ready(paths, weeks=weeks)
    _git(paths, "add", "-A")
    _git(paths, "commit", "-q", "-m", "test: aa ready")


def test_comment_only_tue_run_polls_once_and_posts_the_link_line(
    git_vault, mock_transport_factory, fake_clock
) -> None:
    paths = git_vault
    _seeded_reminder_vault(paths)
    state_bytes = paths.job_state.read_bytes()
    budget_bytes = paths.cfbd_ledger.read_bytes()
    handle = mock_transport_factory(_aa_responses())

    result = _comment_only_tue(paths, handle, fake_clock, _REMINDER_TUE)

    assert result.exit_code == 4
    assert result.stale_only is True
    link = [i for i in result.items if i.kind == "reminder_aa_cfb_link"]
    assert len(link) == 1
    assert _AA_POST in link[0].line
    assert _aa_requests(handle).count(_AA_FEED_URL) == 1
    assert "reminder_aa_cfb" not in _kinds(result)
    # No job state, budget or build writes; the only vault write is the feed-watch commit.
    assert paths.job_state.read_bytes() == state_bytes
    assert paths.cfbd_ledger.read_bytes() == budget_bytes
    assert load_feed_state(paths).weeks["2026-7"] == _AA_POST
    assert _git(paths, "status", "--porcelain") == ""
    changed = _git(paths, "show", "--name-only", "--format=", "HEAD").split()
    assert "ledger/aa_feed_watch.json" in changed
    assert "ledger/job_state.json" not in changed
    assert "ledger/cfbd_ledger.jsonl" not in changed


def test_dry_run_tue_makes_no_aa_request_and_keeps_the_blind_line(
    git_vault, mock_transport_factory, fake_clock
) -> None:
    paths = git_vault
    _seeded_reminder_vault(paths)
    head = _git(paths, "rev-parse", "HEAD")
    handle = mock_transport_factory(_aa_responses())

    result = _comment_only_tue(paths, handle, fake_clock, _REMINDER_TUE, dry_run=True)

    assert _aa_requests(handle) == []
    assert "reminder_aa_cfb" in _kinds(result)
    assert "reminder_aa_cfb_link" not in _kinds(result)
    assert _git(paths, "rev-parse", "HEAD") == head


def test_late_run_with_the_week_in_the_ledger_makes_no_aa_request(
    git_vault, mock_transport_factory, fake_clock
) -> None:
    paths = git_vault
    _seeded_reminder_vault(paths, weeks={"2026-7": _AA_POST})
    handle = mock_transport_factory(_aa_responses())

    result = _comment_only_tue(paths, handle, fake_clock, _REMINDER_TUE_LATE)

    assert _aa_requests(handle) == []
    link = [i for i in result.items if i.kind == "reminder_aa_cfb_link"]
    assert len(link) == 1
    assert _AA_POST in link[0].line


def test_full_run_at_the_tue_slot_without_a_policy_ledger_makes_no_aa_request(
    git_vault, mock_transport_factory, fake_clock
) -> None:
    paths = git_vault
    _seed_required_state(paths, cfbd_month="2026-10")
    handle = mock_transport_factory(_espnpr_responses())

    result = _wr12_job(paths, handle, fake_clock, _REMINDER_TUE).run()

    assert _aa_requests(handle) == []
    assert {"reminder_aa_cfb", "aa_feed_policy_stale"} <= set(_kinds(result))


def test_schedule_run_at_the_tue_slot_polls_once_and_posts_the_link_line(
    git_vault, mock_transport_factory, fake_clock
) -> None:
    paths = git_vault
    _seed_required_state(paths, cfbd_month="2026-10")
    _seed_aa_ready(paths)
    handle = mock_transport_factory(_aa_responses(_espnpr_responses()))
    runtime = _runtime(paths, handle, now=lambda: _REMINDER_TUE, fake_clock=fake_clock)

    result = ScheduledJob(
        runtime, token="test-token", now=lambda: _REMINDER_TUE, trigger="manual", mode="schedule"
    ).run()

    assert _aa_requests(handle).count(_AA_FEED_URL) == 1
    assert [i.kind for i in result.items].count("reminder_aa_cfb_link") == 1


def test_a_run_outside_the_tue_window_makes_no_aa_request(
    git_vault, mock_transport_factory, fake_clock
) -> None:
    paths = git_vault
    _seeded_reminder_vault(paths)
    handle = mock_transport_factory(_aa_responses())

    result = _comment_only_tue(paths, handle, fake_clock, datetime(2026, 10, 12, 18, 0, tzinfo=UTC))

    assert _aa_requests(handle) == []
    assert result.items == []


def test_every_due_reminders_call_receives_the_resolver() -> None:
    import re

    calls = re.findall(r"due_reminders\([^\n]*\)", RUNNER_SRC)
    assert len(calls) >= 5
    assert all("aa_cfb=self._aa_cfb_resolver()" in call for call in calls)


def test_a_full_run_at_a_reminder_time_adds_the_due_reminders_to_its_items(
    git_vault, mock_transport_factory, fake_clock
) -> None:
    """Collision: the full run wins the slot and the reminder lines join its comment."""
    paths = git_vault
    _seed_required_state(paths, cfbd_month="2026-10")

    handle = mock_transport_factory(_espnpr_responses())
    result = _wr12_job(paths, handle, fake_clock, _REMINDER_TUE).run()

    kinds = [item.kind for item in result.items]
    assert kinds.count("reminder_aa_cfb") == 1
    assert "cfb week 7" in next(i.line for i in result.items if i.kind == "reminder_aa_cfb")
    assert "espnpr_week_unsaved" in kinds  # the full run's own line is untouched
    assert result.exit_code == 4
    assert all("awfulannouncing" not in request.url for request in handle.requests)


def test_a_schedule_run_at_a_reminder_time_adds_the_due_reminders_to_its_items(
    git_vault, mock_transport_factory, fake_clock
) -> None:
    paths = git_vault
    _seed_required_state(paths, cfbd_month="2026-10")

    handle = mock_transport_factory(_espnpr_responses())
    runtime = _runtime(paths, handle, now=lambda: _REMINDER_TUE, fake_clock=fake_clock)
    result = ScheduledJob(
        runtime,
        token="test-token",
        now=lambda: _REMINDER_TUE,
        trigger="manual",
        mode="schedule",
    ).run()

    kinds = [item.kind for item in result.items]
    assert kinds.count("reminder_aa_cfb") == 1
    # Phase 25: with no AA policy ledger the resolver gates (no request) and adds one
    # attention line, so this schedule run now exits 4 instead of 0.
    assert kinds.count("aa_feed_policy_stale") == 1
    assert result.exit_code == 4
    assert all("awfulannouncing" not in request.url for request in handle.requests)


def test_a_clean_full_run_keeps_exit_0_ok_and_zero_attention_with_a_reminder_due(
    git_vault, mock_transport_factory, fake_clock, monkeypatch
) -> None:
    """The reminder lines still come out for commenting but change nothing about the run."""
    paths = git_vault
    monkeypatch.setattr(
        runner_module,
        "find_506_gaps",
        lambda *_a, **_k: Gaps506(season=2026, missing=[], stale=[], judged=0),
    )
    _seed_required_state(paths, cfbd_month="2026-10")
    page = paths.raw / "espnpr" / "2026" / "commentators" / "wk-7.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_bytes(b"<html>synthetic</html>")

    # Phase 25: a fresh AA policy check and a verified feed keep the Tue slot clean.
    _seed_aa_ready(paths)
    handle = mock_transport_factory(_aa_responses(_espnpr_responses()))
    result = _wr12_job(paths, handle, fake_clock, _REMINDER_TUE).run()

    assert [i.kind for i in result.items].count("reminder_aa_cfb_link") == 1
    assert not [i for i in result.items if i.severity == "attention"]
    assert result.exit_code == 0
    assert load_state(paths.job_state).last_status == "ok"
    report = (paths.ledger / "run_reports.jsonl").read_text(encoding="utf-8").splitlines()[-1]
    assert json.loads(report)["attention"] == 0


def test_reminders_go_to_their_own_output_file_and_never_the_attention_body(tmp_path) -> None:
    from types import SimpleNamespace

    from booth_review.job.attention import reminder_aa_cfb, sports506_missing
    from booth_review.job.runner import JobRunResult

    args = SimpleNamespace(
        attention_out=tmp_path / "attention.md",
        reminders_out=tmp_path / "reminders.md",
        result_out=None,
    )
    items = [sports506_missing(2026, ["2"]), reminder_aa_cfb(2026, "7")]
    cli._write_job_outputs(args, JobRunResult(exit_code=4, items=items, counts={}, window=None))
    assert "reminder 2026" not in args.attention_out.read_text(encoding="utf-8")
    assert "reminder 2026" in args.reminders_out.read_text(encoding="utf-8")

    only = SimpleNamespace(
        attention_out=tmp_path / "a2.md", reminders_out=tmp_path / "r2.md", result_out=None
    )
    cli._write_job_outputs(only, JobRunResult(exit_code=0, items=items[1:], counts={}, window=None))
    assert not only.attention_out.exists()
    assert only.reminders_out.exists()


# -- a failed push still carries the slot's due reminders (panel F9) -------------------------------


def test_a_full_run_that_fails_its_push_still_carries_the_due_reminders(
    git_vault, mock_transport_factory, fake_clock, monkeypatch
) -> None:
    paths = git_vault
    _seed_required_state(paths, cfbd_month="2026-10")
    handle = mock_transport_factory(_espnpr_responses())
    job = _wr12_job(paths, handle, fake_clock, _REMINDER_TUE)

    def _raise_commit(*args, **kwargs):
        raise VaultCommitError("git subcommand push exited 1")

    monkeypatch.setattr(job._runtime.vault, "commit_batch", _raise_commit)
    result = job.run()

    assert result.exit_code == 3
    assert [i.kind for i in result.items].count("reminder_aa_cfb") == 1
    assert all(i.severity == "reminder" for i in result.items if i.kind == "reminder_aa_cfb")


def test_a_schedule_run_that_fails_its_push_still_carries_the_due_reminders(
    git_vault, mock_transport_factory, fake_clock, monkeypatch
) -> None:
    paths = git_vault
    _seed_required_state(paths, cfbd_month="2026-10")
    handle = mock_transport_factory(_espnpr_responses())
    runtime = _runtime(paths, handle, now=lambda: _REMINDER_TUE, fake_clock=fake_clock)

    def _boom(*args, **kwargs):
        raise VaultCommitError("git subcommand push exited 1")

    monkeypatch.setattr(runtime.vault, "commit_batch", _boom)
    monkeypatch.setattr(runner_module, "run_build", _boom, raising=False)
    result = ScheduledJob(
        runtime, token="test-token", now=lambda: _REMINDER_TUE, trigger="manual", mode="schedule"
    ).run()

    assert result.exit_code == 3
    assert [i.kind for i in result.items].count("reminder_aa_cfb") == 1
