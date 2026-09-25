"""VaultRepo: commits and pushes data/vault/ after each collection batch (D-04).

Every git call is an argument-list `subprocess.run(["git", "-C", path, ...])`,
never a shell string, and commit messages are restricted to a count-only
whitelist so scraped source text can never land in a commit message or a log.
"""

from __future__ import annotations

import logging
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path

from booth_review.errors import VaultCommitError, VaultStateError

logger = logging.getLogger("booth_review.vault")

_MESSAGE_RE = re.compile(r"^[a-z]+: [a-z0-9 ,()_./:-]+$")
_MAX_MESSAGE_LEN = 120


def batch_message(action: str, source: str, season_label: str, counts: Mapping[str, int]) -> str:
    """A count-only commit message, e.g. "collect: sports506 2025 (fetched 18, cached 0)"."""
    counts_str = ", ".join(f"{key} {value}" for key, value in counts.items())
    return f"{action}: {source} {season_label} ({counts_str})"


class VaultRepo:
    """Wraps `git` operations against a single data-vault working copy."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(self._path), *args],
            check=False,
            capture_output=True,
            text=True,
        )

    def check(self) -> None:
        """Raise VaultStateError unless `self._path` is its own git toplevel with an
        origin remote. A missing vault can never make git fall through to a parent
        (e.g. the public) repo (T-01-17).
        """
        if not self._path.is_dir():
            raise VaultStateError(f"vault path does not exist: {self._path}")

        toplevel_result = self._run("rev-parse", "--show-toplevel")
        if toplevel_result.returncode != 0:
            raise VaultStateError(
                f"vault path is not a git working copy: {self._path} "
                f"(git subcommand rev-parse exited {toplevel_result.returncode})"
            )

        toplevel = Path(toplevel_result.stdout.strip()).resolve()
        if toplevel != self._path.resolve():
            raise VaultStateError(
                f"vault path is not its own git toplevel: {self._path} (toplevel is {toplevel})"
            )

        remote_result = self._run("remote", "get-url", "origin")
        if remote_result.returncode != 0:
            raise VaultStateError(f"vault has no origin remote: {self._path}")

    def commit_batch(self, message: str, *, push: bool = True) -> bool:
        """Stage everything, commit with `message`, and push. Returns True when a
        commit was made, False when there was nothing to commit.
        """
        if len(message) > _MAX_MESSAGE_LEN or not _MESSAGE_RE.match(message):
            raise ValueError(f"commit message failed the count-only whitelist: {message!r}")

        self.check()

        add_result = self._run("add", "-A")
        if add_result.returncode != 0:
            raise VaultCommitError(f"git subcommand add exited {add_result.returncode}")

        diff_result = self._run("diff", "--cached", "--quiet")
        if diff_result.returncode == 0:
            logger.info("vault: nothing to commit")
            return False

        commit_result = self._run("commit", "-m", message)
        if commit_result.returncode != 0:
            raise VaultCommitError(f"git subcommand commit exited {commit_result.returncode}")
        logger.info("vault: committed")

        if push:
            self._push_with_retry()

        return True

    def _push_with_retry(self) -> None:
        push_result = self._run("push")
        if push_result.returncode == 0:
            return

        pull_result = self._run("pull", "--rebase")
        if pull_result.returncode != 0:
            raise VaultCommitError(f"git subcommand pull --rebase exited {pull_result.returncode}")

        retry_result = self._run("push")
        if retry_result.returncode != 0:
            raise VaultCommitError(
                f"git subcommand push exited {retry_result.returncode} (after pull --rebase)"
            )
