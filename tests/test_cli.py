"""Offline end-to-end tests for the booth-review CLI.

Every test drives `cli.main(argv)` directly against a real (throwaway,
tmp_path-rooted) git vault and a PoliteClient built on httpx2.MockTransport
via the `patched_client`/`git_vault` fixtures, so no real network request or
git push is ever sent. `test_budget_live_call_sentinel_key_never_leaks`
proves the CFBD key never reaches stdout, stderr, log records, or any file
written under the vault.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from booth_review import cli
from booth_review.cli import main, parse_season_spec
from booth_review.sources.ratingsref.collector import SITEMAP_URL
from booth_review.sources.sports506.collector import WEEK_LABELS

FIXTURES_RR = Path(__file__).parent / "fixtures" / "ratingsref" / "sitemap_synthetic.xml"


def _cfbd_info_body(remaining: int) -> bytes:
    return json.dumps(
        {
            "patronLevel": "free",
            "tierName": "Free",
            "monthlyLimit": 1000,
            "remainingCalls": remaining,
            "usedCalls": 1000 - remaining,
            "resetAt": "2026-10-01T00:00:00.000Z",
        }
    ).encode()


def _remote_head_subject(remote: Path) -> str:
    result = subprocess.run(
        ["git", "--git-dir", str(remote), "log", "-1", "--format=%s"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _remote_log_count(remote: Path) -> int:
    result = subprocess.run(
        ["git", "--git-dir", str(remote), "log", "--oneline"],
        capture_output=True,
        text=True,
        check=True,
    )
    return len(result.stdout.splitlines())


def _sports506_responses() -> dict[str, tuple[int, bytes, dict[str, str]]]:
    responses: dict[str, tuple[int, bytes, dict[str, str]]] = {
        "https://506sports.com/robots.txt": (404, b"nf", {})
    }
    for label in WEEK_LABELS:
        url = f"https://506sports.com/ncaaf.php?yr=2025&wk={label}"
        responses[url] = (200, b"<html>ok</html>", {})
    return responses


# -- collect 506 ----------------------------------------------------------------------


def test_collect_506_dry_run_prints_18_urls_and_sends_nothing(
    git_vault, mock_transport_factory, patched_client, capsys
) -> None:
    handle = mock_transport_factory({})
    patched_client(handle)

    exit_code = main(["collect", "506", "--season", "2025", "--dry-run"])

    assert exit_code == 0
    out = capsys.readouterr().out
    url_lines = [line for line in out.splitlines() if line.startswith("https://506sports.com/")]
    assert len(url_lines) == 18
    assert "new 18" in out
    assert handle.requests == []


def test_collect_506_real_run_commits_and_rerun_is_a_noop(
    git_vault, mock_transport_factory, patched_client
) -> None:
    paths = git_vault
    remote = paths.vault.parent / "remote.git"
    responses = _sports506_responses()
    handle = mock_transport_factory(responses)
    patched_client(handle)

    exit_code = main(["collect", "506", "--season", "2025"])

    assert exit_code == 0
    assert _remote_head_subject(remote) == (
        "collect: sports506 2025 (fetched 18, cached 0, not_modified 0, failed 0)"
    )

    log_count = _remote_log_count(remote)
    handle2 = mock_transport_factory(responses)
    patched_client(handle2)

    exit_code2 = main(["collect", "506", "--season", "2025"])

    assert exit_code2 == 0
    assert handle2.requests == []
    assert _remote_log_count(remote) == log_count


def test_collect_506_one_404_fetches_others_commits_and_returns_4(
    git_vault, mock_transport_factory, patched_client, capsys
) -> None:
    paths = git_vault
    responses = _sports506_responses()
    missing_url = "https://506sports.com/ncaaf.php?yr=2025&wk=5"
    responses[missing_url] = (404, b"not found", {})
    handle = mock_transport_factory(responses)
    patched_client(handle)

    exit_code = main(["collect", "506", "--season", "2025"])

    assert exit_code == 4
    out = capsys.readouterr().out
    assert f"failed: {missing_url}" in out

    remote = paths.vault.parent / "remote.git"
    assert "collect: sports506 2025" in _remote_head_subject(remote)
    assert (paths.raw / "sports506" / "2025" / "wk-16.html").is_file()


# -- collect ratingsref -----------------------------------------------------------------


def test_collect_ratingsref_sitemap_only_then_dry_run_reports_same_count(
    git_vault, mock_transport_factory, patched_client, capsys
) -> None:
    sitemap_xml = FIXTURES_RR.read_bytes()
    responses = {
        "https://ratingsreference.com/robots.txt": (404, b"nf", {}),
        SITEMAP_URL: (200, sitemap_xml, {}),
    }
    handle = mock_transport_factory(responses)
    patched_client(handle)

    exit_code = main(["collect", "ratingsref", "--season", "2025", "--sitemap-only"])

    assert exit_code == 0
    assert len(handle.requests) == 2
    out = capsys.readouterr().out
    assert "new 3" in out

    handle2 = mock_transport_factory({})
    patched_client(handle2)

    exit_code2 = main(["collect", "ratingsref", "--season", "2025", "--dry-run"])

    assert exit_code2 == 0
    assert handle2.requests == []
    out2 = capsys.readouterr().out
    assert "new 3" in out2


# -- collect cfbd -------------------------------------------------------------------------


def test_collect_cfbd_without_key_returns_3_and_sends_nothing(
    git_vault, mock_transport_factory, patched_client, capsys
) -> None:
    handle = mock_transport_factory({})
    patched_client(handle)

    exit_code = main(["collect", "cfbd", "--season", "2025"])

    assert exit_code == 3
    err = capsys.readouterr().err
    assert "MissingApiKeyError" in err
    assert handle.requests == []


def test_collect_cfbd_run_cap_commits_partial_files_and_raises(
    git_vault, mock_transport_factory, patched_client, monkeypatch, capsys
) -> None:
    paths = git_vault
    monkeypatch.setenv("CFBD_API_KEY", "test-token")

    budget_responses = {
        "https://api.collegefootballdata.com/robots.txt": (404, b"nf", {}),
        "https://api.collegefootballdata.com/info": (200, _cfbd_info_body(600), {}),
    }
    budget_handle = mock_transport_factory(budget_responses)
    patched_client(budget_handle)
    assert main(["budget"]) == 0
    capsys.readouterr()

    collect_responses = {
        "https://api.collegefootballdata.com/robots.txt": (404, b"nf", {}),
        "https://api.collegefootballdata.com/games?seasonType=both&year=2025": (200, b"[]", {}),
        "https://api.collegefootballdata.com/games/media?seasonType=both&year=2025": (
            200,
            b"[]",
            {},
        ),
        "https://api.collegefootballdata.com/metrics/wp/pregame?seasonType=both&year=2025": (
            200,
            b"[]",
            {},
        ),
    }
    collect_handle = mock_transport_factory(collect_responses)
    patched_client(collect_handle)

    exit_code = main(["collect", "cfbd", "--season", "2025", "--max-calls", "3", "--tag", "spike"])

    assert exit_code == 3
    err = capsys.readouterr().err
    assert "RunCapError" in err

    assert (paths.raw / "cfbd" / "games" / "2025.json").is_file()
    assert (paths.raw / "cfbd" / "media" / "2025.json").is_file()
    assert (paths.raw / "cfbd" / "wp_pregame" / "2025.json").is_file()

    remote = paths.vault.parent / "remote.git"
    assert "collect: cfbd 2025" in _remote_head_subject(remote)


def test_collect_cfbd_below_floor_raises_and_sends_no_data_request(
    git_vault, mock_transport_factory, patched_client, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("CFBD_API_KEY", "test-token")

    budget_responses = {
        "https://api.collegefootballdata.com/robots.txt": (404, b"nf", {}),
        "https://api.collegefootballdata.com/info": (200, _cfbd_info_body(250), {}),
    }
    budget_handle = mock_transport_factory(budget_responses)
    patched_client(budget_handle)
    assert main(["budget"]) == 0
    capsys.readouterr()

    collect_responses = {
        "https://api.collegefootballdata.com/robots.txt": (404, b"nf", {}),
        "https://api.collegefootballdata.com/games?seasonType=both&year=2025": (200, b"[]", {}),
    }
    collect_handle = mock_transport_factory(collect_responses)
    patched_client(collect_handle)

    exit_code = main(["collect", "cfbd", "--season", "2025"])

    assert exit_code == 3
    err = capsys.readouterr().err
    assert "BudgetFloorError" in err

    data_requests = [
        r for r in collect_handle.requests if r.url.endswith("/games?seasonType=both&year=2025")
    ]
    assert data_requests == []


# -- budget ----------------------------------------------------------------------------------


def test_budget_live_call_sentinel_key_never_leaks(
    git_vault, mock_transport_factory, patched_client, monkeypatch, capsys, caplog
) -> None:
    paths = git_vault
    monkeypatch.setenv("CFBD_API_KEY", "SENTINEL-KEY-XYZ")
    responses = {
        "https://api.collegefootballdata.com/robots.txt": (404, b"nf", {}),
        "https://api.collegefootballdata.com/info": (200, _cfbd_info_body(600), {}),
    }
    handle = mock_transport_factory(responses)
    patched_client(handle)

    with caplog.at_level("DEBUG"):
        exit_code = main(["budget"])

    assert exit_code == 0
    info_requests = [r for r in handle.requests if r.url.endswith("/info")]
    assert len(info_requests) == 1

    captured = capsys.readouterr()
    assert "SENTINEL-KEY-XYZ" not in captured.out
    assert "SENTINEL-KEY-XYZ" not in captured.err
    for record in caplog.records:
        assert "SENTINEL-KEY-XYZ" not in record.getMessage()
    for path in paths.vault.rglob("*"):
        if path.is_file():
            assert b"SENTINEL-KEY-XYZ" not in path.read_bytes()


def test_budget_probe_info_cost_calls_info_twice_and_commits_count_2(
    git_vault, mock_transport_factory, patched_client, monkeypatch
) -> None:
    """WR-06: --probe-info-cost must go through collector.probe_info_cost()
    (not a duplicated inline copy) -- two /info calls, and a batch commit
    that reflects both."""
    paths = git_vault
    monkeypatch.setenv("CFBD_API_KEY", "test-token")
    responses = {
        "https://api.collegefootballdata.com/robots.txt": (404, b"nf", {}),
        "https://api.collegefootballdata.com/info": (200, _cfbd_info_body(600), {}),
    }
    handle = mock_transport_factory(responses)
    patched_client(handle)

    exit_code = main(["budget", "--probe-info-cost"])

    assert exit_code == 0
    info_requests = [r for r in handle.requests if r.url.endswith("/info")]
    assert len(info_requests) == 2

    remote = paths.vault.parent / "remote.git"
    assert _remote_head_subject(remote) == "budget: cfbd info (calls 2)"


# -- missing vault ------------------------------------------------------------------------


def test_collect_with_missing_vault_returns_3(
    tmp_path, monkeypatch, isolated_git_env, capsys
) -> None:
    monkeypatch.setenv("BOOTH_REVIEW_VAULT", str(tmp_path / "does-not-exist"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CFBD_API_KEY", raising=False)

    exit_code = main(["collect", "506", "--season", "2025", "--dry-run"])

    assert exit_code == 3
    err = capsys.readouterr().err
    assert "VaultStateError" in err


# -- parse_season_spec ----------------------------------------------------------------------


def test_parse_season_spec_range_returns_11_seasons() -> None:
    assert parse_season_spec("2014-2024") == list(range(2014, 2025))


@pytest.mark.parametrize("text", ["2024-2014", "1999", "abc"])
def test_parse_season_spec_rejects_bad_input(text: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        parse_season_spec(text)


def test_current_season_ceiling_uses_july_start_season_not_calendar_year(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WR-05: the CLI's own season ceiling must match seasons.season_of's
    July-June window -- in February 2026, season 2026 hasn't started yet."""

    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            return cls(2026, 2, 1, tzinfo=UTC)

    monkeypatch.setattr(cli, "datetime", _FrozenDateTime)
    assert cli._current_season_ceiling() == 2025


def test_parse_season_spec_rejects_next_season_before_july(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            return cls(2026, 2, 1, tzinfo=UTC)

    monkeypatch.setattr(cli, "datetime", _FrozenDateTime)
    with pytest.raises(argparse.ArgumentTypeError, match=r"\[2013, 2025\]"):
        parse_season_spec("2026")
