"""Automated drills for `booth-review job run --update` (AUTO-02, AUTO-03, AUTO-05).

Each drill runs end to end through the in-process CLI against the synthetic update
vault from tests/test_job_runner.py and a local bare deploy target. No network, no
real vault, no real GitHub repo; docs/LAUNCH.md cites these test names as evidence.
"""

from __future__ import annotations

import csv
import json
import logging
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_job_runner import (  # noqa: F401  (update_vault is a shared fixture)
    _BUILD_DIR,
    _REFERENCE_DIR,
    _REPO_ROOT,
    _SPIKE_DIR,
    _cli_update_setup,
    _freeze_cli_clock,
    _update_cfbd_responses,
    update_vault,
)

from booth_review.cli import main
from booth_review.job.attention import AttentionItem, build_attention_body

DRILL_NOW = datetime(2025, 10, 8, 12, 0, tzinfo=UTC)
CANARY = "drill-canary-not-a-real-key-0001"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


def _commit_count(repo: Path, ref: str = "main") -> int:
    return int(_git(repo, "rev-list", "--count", ref).strip())


def _make_deploy_target(tmp_path: Path) -> tuple[Path, Path]:
    """A bare `-b master` remote seeded with index.html and dashboard/x, plus a clone."""
    bare = tmp_path / "deploy-remote.git"
    subprocess.run(
        ["git", "init", "--bare", "-q", "-b", "master", str(bare)], check=True, capture_output=True
    )
    seed = tmp_path / "deploy-seed"
    subprocess.run(["git", "clone", "-q", str(bare), str(seed)], check=True, capture_output=True)
    _git(seed, "config", "user.name", "Test")
    _git(seed, "config", "user.email", "t@example.com")
    (seed / "index.html").write_text("home\n", encoding="utf-8")
    (seed / "dashboard").mkdir()
    (seed / "dashboard" / "x").write_text("enc\n", encoding="utf-8")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-q", "-m", "seed")
    _git(seed, "push", "-q", "origin", "HEAD:refs/heads/master")
    target = tmp_path / "deploy-target"
    subprocess.run(["git", "clone", "-q", str(bare), str(target)], check=True, capture_output=True)
    _git(target, "config", "user.name", "Test")
    _git(target, "config", "user.email", "t@example.com")
    return bare, target


def _refs(bare: Path) -> str:
    return _git(bare, "for-each-ref", "--format=%(refname) %(objectname)")


def _update_argv(tmp_path: Path, *, extra: list[str] | None = None) -> list[str]:
    return [
        "job",
        "run",
        "--trigger",
        "manual",
        "--no-commit",
        "--update",
        "--site-out",
        str(tmp_path / "site-out"),
        "--result-out",
        str(tmp_path / "result.txt"),
        *(extra or []),
    ]


# -- Task 1: remove-state and key-plant drills ----------------------------------------------


_REMOVE_CASES = [
    pytest.param(["ledger/cfbd_ledger.jsonl"], "ledger/cfbd_ledger.jsonl", id="cfbd-ledger"),
    pytest.param(["ledger/frozen.json"], "ledger/frozen.json", id="frozen"),
    pytest.param(
        ["ledger/rr_lastmod.json", "ledger/rr_lastmod.jsonl"],
        "ledger/rr_lastmod.json(l)",
        id="rr-lastmod",
    ),
    pytest.param(["audit/build_baseline.csv"], "audit/build_baseline.csv", id="build-baseline"),
    pytest.param(["raw/ratingsref/sitemap"], "raw/ratingsref/sitemap", id="rr-sitemap"),
]


@pytest.mark.parametrize(("remove", "fragment"), _REMOVE_CASES)
def test_remove_state_drill_fails_loudly_without_requests(
    update_vault,  # noqa: F811
    mock_transport_factory,
    patched_client,
    monkeypatch,
    tmp_path,
    capsys,
    remove,
    fragment,
) -> None:
    paths = update_vault
    _freeze_cli_clock(monkeypatch, DRILL_NOW)
    handle = mock_transport_factory(_update_cfbd_responses())
    patched_client(handle)

    for rel in remove:
        target = paths.vault / rel
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink(missing_ok=True)
    remote = tmp_path / "remote.git"
    commits_before = _commit_count(remote)
    vault_head = _git(paths.vault, "rev-parse", "HEAD")
    capsys.readouterr()

    code = main(
        [
            "job",
            "run",
            "--trigger",
            "manual",
            "--update",
            "--site-out",
            str(tmp_path / "site-out"),
            "--result-out",
            str(tmp_path / "result.txt"),
        ]
    )

    assert code == 3
    err = capsys.readouterr().err
    assert err.startswith("error: VaultStateError")
    assert fragment in err
    assert handle.requests == []
    status = [line for line in _git(paths.vault, "status", "--porcelain").splitlines() if line]
    assert status
    assert all(line.startswith(" D") for line in status), status
    assert _git(paths.vault, "rev-parse", "HEAD") == vault_head
    assert _commit_count(remote) == commits_before
    assert not (tmp_path / "site-out").exists()
    assert not (tmp_path / "result.txt").exists()


def test_key_plant_drill_fails_hard_and_deploys_nothing(
    update_vault,  # noqa: F811
    mock_transport_factory,
    patched_client,
    monkeypatch,
    tmp_path,
    capsys,
    caplog,
) -> None:
    paths = update_vault
    tainted = tmp_path / "site_src_tainted"
    shutil.copytree(_REPO_ROOT / "site", tainted)
    leak = next(tainted.rglob("*.js"))
    with leak.open("a", encoding="utf-8") as fh:
        fh.write(f"\n// {CANARY}\n")
    monkeypatch.setenv("BOOTH_REVIEW_SITE_SRC", str(tainted))
    monkeypatch.setenv("CFBD_API_KEY", CANARY)
    _cli_update_setup(paths, monkeypatch, mock_transport_factory, patched_client, DRILL_NOW)
    bare, target = _make_deploy_target(tmp_path)
    refs_before = _refs(bare)
    count_before = _commit_count(bare, "master")
    attention = tmp_path / "attention.md"

    with caplog.at_level(logging.DEBUG):
        code = main(_update_argv(tmp_path, extra=["--attention-out", str(attention)]))
    out = capsys.readouterr()

    assert code == 3
    result = tmp_path / "result.txt"
    assert "deploy_ready=false" in result.read_text(encoding="utf-8").splitlines()
    assert not (tmp_path / "site-out").exists()

    monkeypatch.setenv("PUBLISH_ENABLED", "true")
    deploy_code = main(["deploy", "--site", str(tmp_path / "site-out"), "--target", str(target)])
    deploy_out = capsys.readouterr()
    assert deploy_code != 0 or "skipped" in deploy_out.out
    assert _commit_count(bare, "master") == count_before
    assert _refs(bare) == refs_before

    haystacks = [out.out, out.err, deploy_out.out, deploy_out.err]
    haystacks += [record.getMessage() for record in caplog.records]
    if attention.exists():
        haystacks.append(attention.read_text(encoding="utf-8"))
    reports = paths.ledger / "run_reports.jsonl"
    if reports.exists():
        haystacks.append(reports.read_text(encoding="utf-8"))
    for text in haystacks:
        assert CANARY not in text


# -- Task 2: count-only logs and publishing-off proof ---------------------------------------


_STOP_NAMES = {"team", "name", "none", "null", "true", "false", "home", "away", "game"}


def _harvest_names() -> set[str]:
    names: set[str] = set()
    with (_REFERENCE_DIR / "people.csv").open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            names.add(row["canonical_name"])
            names.update(v for v in row["variants"].split("|") if v)
    with (_REFERENCE_DIR / "team_crosswalk.csv").open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            names.update({row["variant"], row["canonical"]})
    games = json.loads((_SPIKE_DIR / "cfbd_games_2025.json").read_text(encoding="utf-8"))
    for game in games:
        for key in ("homeTeam", "awayTeam"):
            if isinstance(game.get(key), str):
                names.add(game[key])
    teams = json.loads((_BUILD_DIR / "cfbd" / "teams_fbs_2025.json").read_text(encoding="utf-8"))
    for team in teams:
        for key in ("school", "mascot"):
            if isinstance(team.get(key), str):
                names.add(team[key])
    return {n for n in names if len(n) >= 4 and n.lower() not in _STOP_NAMES}


def test_update_run_logs_are_count_only(
    update_vault,  # noqa: F811
    mock_transport_factory,
    patched_client,
    monkeypatch,
    tmp_path,
    capsys,
    caplog,
) -> None:
    names = _harvest_names()
    assert len(names) >= 5
    monkeypatch.setenv("CFBD_API_KEY", CANARY)
    _cli_update_setup(update_vault, monkeypatch, mock_transport_factory, patched_client, DRILL_NOW)
    attention = tmp_path / "attention.md"
    caplog.set_level(logging.INFO)
    capsys.readouterr()

    code = main(_update_argv(tmp_path, extra=["--attention-out", str(attention)]))

    assert code in (0, 4)
    captured = capsys.readouterr()
    lines = captured.out.splitlines() + captured.err.splitlines()
    lines += [record.getMessage() for record in caplog.records]
    assert lines
    for line in lines:
        lowered = line.lower()
        for name in names:
            assert name.lower() not in lowered, f"name {name!r} in log line {line!r}"
        assert not ("?" in line and "=" in line.split("?", 1)[1]), line
        assert CANARY not in line
    if attention.exists():
        body = attention.read_text(encoding="utf-8")
        body_lines = [ln[2:] for ln in body.splitlines()[1:] if ln.startswith("- ")]
        rebuilt = build_attention_body(
            [AttentionItem(kind="check", severity="attention", line=ln) for ln in body_lines],
            generated_at=DRILL_NOW,
        )
        assert rebuilt is not None
        assert CANARY not in body


def test_publishing_off_deploys_nothing_end_to_end(
    update_vault,  # noqa: F811
    mock_transport_factory,
    patched_client,
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    monkeypatch.delenv("PUBLISH_ENABLED", raising=False)
    _cli_update_setup(update_vault, monkeypatch, mock_transport_factory, patched_client, DRILL_NOW)
    bare, target = _make_deploy_target(tmp_path)
    refs_before = _refs(bare)

    code = main(_update_argv(tmp_path))
    assert code in (0, 4)
    assert "deploy_ready=true" in (tmp_path / "result.txt").read_text(encoding="utf-8").splitlines()
    capsys.readouterr()

    deploy_code = main(["deploy", "--site", str(tmp_path / "site-out"), "--target", str(target)])

    assert deploy_code == 0
    assert capsys.readouterr().out.strip() == "deploy skipped: publishing disabled"
    assert _refs(bare) == refs_before
