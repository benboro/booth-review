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
from datetime import UTC, datetime
from pathlib import Path

import pytest

from booth_review import cli
from booth_review.cli import main
from booth_review.config import CFBD_FLOOR_DEFAULT
from booth_review.errors import VaultCommitError, VaultStateError
from booth_review.job.catchup import JobState, load_state, save_state
from booth_review.job.gaps506 import find_506_gaps
from booth_review.job.runner import JOB_CFBD_MAX_CALLS, ScheduledJob
from booth_review.runtime import Runtime
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
_COUNT_KINDS = {"people_review_due", "unresolved_teams", "sports506_missing", "sports506_stale"}


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
