"""Tests for ops/release-job.sh using local temp repos and a stubbed `gh`."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path("ops/release-job.sh").resolve()
VAULT_URL = "git@github.com:owner/vault-name.git"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash unavailable")


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


class Env:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.origin = tmp_path / "origin.git"
        self.repo = tmp_path / "repo"
        self.log = tmp_path / "gh.log"
        subprocess.run(
            ["git", "init", "--bare", "-q", "-b", "main", str(self.origin)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "clone", "-q", str(self.origin), str(self.repo)],
            check=True,
            capture_output=True,
        )
        _git(self.repo, "config", "user.name", "Test Bot")
        _git(self.repo, "config", "user.email", "bot@example.com")
        _git(self.repo, "checkout", "-q", "-b", "main")
        (self.repo / "pyproject.toml").write_text(
            '[project]\nname = "x"\nversion = "0.5.0"\n', encoding="utf-8"
        )
        (self.repo / ".gitignore").write_text("data/\n", encoding="utf-8")
        _git(self.repo, "add", "pyproject.toml", ".gitignore")
        _git(self.repo, "commit", "-q", "-m", "init")
        _git(self.repo, "push", "-q", "-u", "origin", "main")
        vault = self.repo / "data" / "vault"
        vault.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(vault)], check=True, capture_output=True)
        _git(vault, "remote", "add", "origin", VAULT_URL)

        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        gh = bin_dir / "gh"
        gh.write_text(
            '#!/usr/bin/env bash\necho "$*" >> "$GH_LOG"\n'
            'if [ "$1 $2" = "variable list" ]; then echo "$GH_TAG"; fi\n',
            encoding="utf-8",
        )
        gh.chmod(0o755)
        # `uv run booth-review audit overrides --release ...` is the pre-flight: the
        # stub logs its arguments, runs UV_SIDE_EFFECT, and exits with UV_EXIT.
        self.uv_log = tmp_path / "uv.log"
        uv = bin_dir / "uv"
        uv.write_text(
            '#!/usr/bin/env bash\necho "$*" >> "$UV_LOG"\n'
            'if [ -n "${UV_SIDE_EFFECT:-}" ]; then eval "$UV_SIDE_EFFECT"; fi\n'
            'exit "${UV_EXIT:-0}"\n',
            encoding="utf-8",
        )
        uv.chmod(0o755)
        monkeypatch.setenv("UV_LOG", str(self.uv_log))
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
        monkeypatch.setenv("GH_LOG", str(self.log))

    def run(
        self,
        *args: str,
        tag_env: str | None = None,
        uv_exit: int = 0,
        uv_side_effect: str = "",
    ) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env["GH_TAG"] = tag_env or (args[-1] if args else "")
        env["UV_EXIT"] = str(uv_exit)
        env["UV_SIDE_EFFECT"] = uv_side_effect
        return subprocess.run(
            ["bash", str(SCRIPT), *args],
            cwd=self.repo,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def gh_calls(self) -> list[str]:
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []

    def uv_calls(self) -> list[str]:
        if not self.uv_log.exists():
            return []
        return self.uv_log.read_text(encoding="utf-8").splitlines()

    def remote_tags(self) -> str:
        return _git(self.origin, "tag", "--list")


@pytest.fixture
def env(tmp_path: Path, isolated_git_env: None, monkeypatch: pytest.MonkeyPatch) -> Env:
    return Env(tmp_path, monkeypatch)


def test_dry_run_plans_without_tagging_or_calling_gh(env: Env) -> None:
    result = env.run("--dry-run", "v0.5.0")
    assert result.returncode == 0, result.stderr
    assert "would tag v0.5.0" in result.stdout
    assert "would set JOB_REF" in result.stdout
    assert "owner/vault-name" not in result.stdout + result.stderr
    assert env.remote_tags() == ""
    assert _git(env.repo, "tag", "--list") == ""
    assert env.gh_calls() == []


def test_real_run_tags_origin_and_sets_job_ref(env: Env) -> None:
    result = env.run("v0.5.0")
    assert result.returncode == 0, result.stderr
    assert "JOB_REF set to v0.5.0" in result.stdout
    assert env.remote_tags() == "v0.5.0"
    assert _git(env.repo, "cat-file", "-t", "v0.5.0") == "tag"
    assert "variable set JOB_REF --repo owner/vault-name --body v0.5.0" in env.gh_calls()
    # gh 2.45 has no `variable get`; the check must read back through `variable list`.
    calls = env.gh_calls()
    readback = "variable list --repo owner/vault-name --json name,value"
    assert any(c.startswith(readback) for c in calls)
    assert not any(c.startswith("variable get") for c in calls)


def _refused(env: Env, result: subprocess.CompletedProcess[str], tags: str = "") -> None:
    assert result.returncode == 1
    assert env.remote_tags() == tags
    assert env.gh_calls() == []


def test_refuses_dirty_worktree(env: Env) -> None:
    (env.repo / "pyproject.toml").write_text('version = "0.5.0"\n# x\n', encoding="utf-8")
    _refused(env, env.run("v0.5.0"))


def test_refuses_branch_not_main(env: Env) -> None:
    _git(env.repo, "checkout", "-q", "-b", "feature")
    _refused(env, env.run("v0.5.0"))


def test_refuses_head_ahead_of_origin(env: Env) -> None:
    (env.repo / "extra.txt").write_text("x", encoding="utf-8")
    _git(env.repo, "add", "extra.txt")
    _git(env.repo, "commit", "-q", "-m", "local only")
    _refused(env, env.run("v0.5.0"))


def test_refuses_tag_not_matching_pyproject(env: Env) -> None:
    _refused(env, env.run("v0.5.1"))


def test_refuses_malformed_tag(env: Env) -> None:
    _refused(env, env.run("0.5.0"))


def test_refuses_tag_already_on_origin(env: Env) -> None:
    other = env.repo.parent / "other"
    subprocess.run(
        ["git", "clone", "-q", str(env.origin), str(other)], check=True, capture_output=True
    )
    _git(other, "config", "user.name", "Other")
    _git(other, "config", "user.email", "o@example.com")
    _git(other, "tag", "v0.5.0")
    _git(other, "push", "-q", "origin", "v0.5.0")
    # The script's own fetch pulls the tag in, so it is refused as existing.
    _refused(env, env.run("v0.5.0"), tags="v0.5.0")


def test_refuses_missing_vault(env: Env) -> None:
    shutil.rmtree(env.repo / "data" / "vault")
    _refused(env, env.run("v0.5.0"))


PREFLIGHT = (
    "run booth-review audit overrides --release --vault data/vault --reference data/reference"
)


def test_preflight_runs_with_explicit_paths(env: Env) -> None:
    result = env.run("v0.5.0")
    assert result.returncode == 0, result.stderr
    assert env.uv_calls() == [PREFLIGHT]


def test_refuses_when_preflight_fails(env: Env) -> None:
    _refused(env, env.run("v0.5.0", uv_exit=1))
    assert _git(env.repo, "tag", "--list") == ""
    assert env.uv_calls() == [PREFLIGHT]


def test_dry_run_also_runs_preflight(env: Env) -> None:
    result = env.run("--dry-run", "v0.5.0", uv_exit=1)
    assert result.returncode == 1
    assert "would tag" not in result.stdout
    assert "pre-flight failed" in result.stderr
    assert env.uv_calls() == [PREFLIGHT]


def test_preflight_runs_before_tagging(env: Env) -> None:
    # The pre-flight sees no tag yet: it runs before `git tag`.
    marker = env.repo.parent / "seen-tags.txt"
    result = env.run("v0.5.0", uv_side_effect=f"git tag --list > '{marker}'")
    assert result.returncode == 0, result.stderr
    assert marker.read_text(encoding="utf-8") == ""
    assert env.remote_tags() == "v0.5.0"


def test_preflight_ignores_redirecting_env(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOOTH_REVIEW_VAULT", "/elsewhere/vault")
    monkeypatch.setenv("BOOTH_REVIEW_REFERENCE", "/elsewhere/reference")
    assert env.run("v0.5.0").returncode == 0
    assert env.uv_calls() == [PREFLIGHT]
