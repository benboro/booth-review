"""Offline tests for ScheduledJob (`booth-review job run`, AUTO-01).

Every test drives either ScheduledJob directly against a real RawCache/
CfbdBudget/VaultRepo wired onto a real (throwaway, git_vault-rooted) vault
and an httpx2.MockTransport (no real network, no real git push), or the CLI
end-to-end via `main([...])`. No test ever sends a request to
506sports.com -- the job never fetches it (D-07/D-08/AUTO-01).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from booth_review import cli
from booth_review.cli import main
from booth_review.config import CFBD_FLOOR_DEFAULT
from booth_review.errors import VaultCommitError, VaultStateError
from booth_review.job.catchup import JobState, load_state, save_state
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


def _seed_required_state(paths, *, cfbd_month: str, cfbd_remaining: int = 900) -> None:
    """rr_lastmod.json and cfbd_ledger.jsonl; frozen.json is already seeded by git_vault."""
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
    assert saved_state.last_status == "attention"


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
    assert "nothing due since last success" in out
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
