"""git check-ignore tests for the .gitignore publish chain (FOUND-05).

Proves the deny-by-default -> allowlist chain behaves correctly against the real
`data/vault/` nested-git-repo layout (D-01), both in the actual repo and in an
isolated scratch repo that simulates publishing one cleared table.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _git_env(tmp_path: Path) -> dict[str, str]:
    """An isolated git environment so the user's global excludes/config can't affect results."""
    env = os.environ.copy()
    empty_config = tmp_path / "empty-gitconfig"
    empty_config.write_text("", encoding="utf-8")
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = str(empty_config)
    return env


def _run_git(args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    "path",
    [
        "data/vault/raw/sports506/2025/wk-01.html",
        "data/vault/ledger/cfbd_ledger.jsonl",
        "data/vault/spike/join.csv",
        "data/raw/x.json",
        "data/interim/x.csv",
        "data/processed/unlisted.csv",
        ".env",
    ],
)
def test_ignored_paths_in_real_repo(path: str, tmp_path: Path) -> None:
    env = _git_env(tmp_path)
    result = _run_git(["check-ignore", "--no-index", "-q", path], cwd=REPO_ROOT, env=env)
    assert result.returncode == 0, f"expected {path} to be ignored"


@pytest.mark.parametrize(
    "path",
    [
        "data/README.md",
        "data/reference/team_crosswalk.csv",
    ],
)
def test_not_ignored_paths_in_real_repo(path: str, tmp_path: Path) -> None:
    env = _git_env(tmp_path)
    result = _run_git(["check-ignore", "--no-index", "-q", path], cwd=REPO_ROOT, env=env)
    assert result.returncode == 1, f"expected {path} to not be ignored"


def test_publish_chain_line_order() -> None:
    """data/* comes before !data/processed/, which comes before data/processed/*."""
    lines = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    deny_all_idx = lines.index("data/*")
    allow_processed_dir_idx = lines.index("!data/processed/")
    deny_processed_files_idx = lines.index("data/processed/*")
    assert deny_all_idx < allow_processed_dir_idx < deny_processed_files_idx


def _build_scratch_repo(tmp_path: Path, env: dict[str, str], *, with_publish_line: bool) -> Path:
    """A scratch repo with the real .gitignore (plus optionally one publish line) and a
    nested git working copy at data/vault/, reproducing the real vault clone (D-01)."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    _run_git(["init", "-q"], cwd=scratch, env=env)

    gitignore_text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    if with_publish_line:
        gitignore_text += "\n!data/processed/site_bundle.json\n"
    (scratch / ".gitignore").write_text(gitignore_text, encoding="utf-8")

    (scratch / "data").mkdir()
    (scratch / "data" / "README.md").write_text("data readme\n", encoding="utf-8")

    reference_dir = scratch / "data" / "reference"
    reference_dir.mkdir()
    (reference_dir / "teams.csv").write_text("team\n", encoding="utf-8")

    processed_dir = scratch / "data" / "processed"
    processed_dir.mkdir()
    (processed_dir / "site_bundle.json").write_text("{}\n", encoding="utf-8")

    vault_raw_dir = scratch / "data" / "vault" / "raw" / "sports506" / "2025"
    vault_raw_dir.mkdir(parents=True)
    (vault_raw_dir / "wk-01.html").write_text("<html></html>\n", encoding="utf-8")

    vault_ledger_dir = scratch / "data" / "vault" / "ledger"
    vault_ledger_dir.mkdir()
    (vault_ledger_dir / "cfbd_ledger.jsonl").write_text("{}\n", encoding="utf-8")

    # Nested git working copy, reproducing the real vault clone (D-01).
    _run_git(["init", "-q"], cwd=scratch / "data" / "vault", env=env)

    return scratch


def test_scratch_repo_with_publish_line_stages_exactly_allowlisted_files(tmp_path: Path) -> None:
    env = _git_env(tmp_path)
    scratch = _build_scratch_repo(tmp_path, env, with_publish_line=True)

    _run_git(["add", "-A"], cwd=scratch, env=env)
    status = _run_git(["status", "--porcelain"], cwd=scratch, env=env)
    staged = {line[3:] for line in status.stdout.splitlines()}

    assert staged == {
        ".gitignore",
        "data/README.md",
        "data/processed/site_bundle.json",
        "data/reference/teams.csv",
    }


def test_scratch_repo_without_publish_line_keeps_processed_file_ignored(tmp_path: Path) -> None:
    """Deny by default holds: no appended allow-line means the processed file stays out."""
    env = _git_env(tmp_path)
    scratch = _build_scratch_repo(tmp_path, env, with_publish_line=False)

    result = _run_git(
        ["check-ignore", "--no-index", "-q", "data/processed/site_bundle.json"],
        cwd=scratch,
        env=env,
    )
    assert result.returncode == 0, "unlisted processed file should stay ignored by default"
