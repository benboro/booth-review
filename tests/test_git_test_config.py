"""The shared test gitconfig stops background gc / maintenance in synthetic repos.

A detached `git gc --auto` (after a commit) or a `receive.autogc` (after a push) repacks a
repository while a test copies its `.git`, so files vanish mid-copy. `isolated_git_env`
turns both off for every synthetic vault and bare remote.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from booth_review.config import DataPaths


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )
    return done.stdout.strip()


def _repos(git_vault: DataPaths) -> list[Path]:
    clone = git_vault.vault
    return [clone, Path(_git(clone, "remote", "get-url", "origin"))]


def test_background_gc_and_maintenance_are_off_in_clone_and_remote(git_vault: DataPaths) -> None:
    for repo in _repos(git_vault):
        assert _git(repo, "config", "--get", "gc.auto") == "0"
        assert _git(repo, "config", "--get", "gc.autoDetach") == "false"
        assert _git(repo, "config", "--get", "maintenance.auto") == "false"


def test_gc_auto_leaves_packs_alone(git_vault: DataPaths) -> None:
    vault = git_vault.vault
    packs = vault / ".git" / "objects" / "pack"
    _git(vault, "config", "gc.autoPackLimit", "1")
    for i in range(4):
        (vault / f"note-{i}.txt").write_text(str(i), encoding="utf-8")
        _git(vault, "add", f"note-{i}.txt")
        _git(vault, "commit", "-q", "-m", f"note {i}")
        _git(vault, "repack", "-q")
    before = len(list(packs.glob("*.pack")))
    assert before >= 3
    _git(vault, "-c", "gc.autoDetach=false", "gc", "--auto", "--quiet")
    assert len(list(packs.glob("*.pack"))) == before
