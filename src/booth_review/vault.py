"""VaultRepo: commits and pushes data/vault/ after each collection batch (D-04).

Every git call is an argument-list `subprocess.run(["git", "-C", path, ...])`,
never a shell string, and commit messages are restricted to a count-only
whitelist so scraped source text can never land in a commit message or a log.

A long collector run (e.g. the RR 2014-2024 backfill) can write files for
hours while a short 506 import commits in between; without coordination, two
`git add -A` calls racing on the same working copy can sweep each other's
in-progress files into a mislabeled, count-only commit message that no longer
describes what it actually contains (T-02-02). `VaultRepo.lock()` serializes
every commit_batch call on one advisory lock file inside `.git/`, and
`commit_batch(paths=...)` lets a caller scope its `git add`/`diff`/`commit` to
only the paths it just wrote, so one process's commit never silently absorbs
another's unrelated, still-in-progress files.
"""

from __future__ import annotations

import contextlib
import fcntl
import logging
import os
import re
import subprocess
import time
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path, PurePosixPath

from booth_review.errors import VaultBusyError, VaultCommitError, VaultStateError

logger = logging.getLogger("booth_review.vault")

_MESSAGE_RE = re.compile(r"^[a-z]+: [a-z0-9 ,()_./:-]+$")
_MAX_MESSAGE_LEN = 120
_GIT_TIMEOUT_SECONDS = 60
_LOCK_POLL_INTERVAL_S = 0.25


def batch_message(action: str, source: str, season_label: str, counts: Mapping[str, int]) -> str:
    """A count-only commit message, e.g. "collect: sports506 2025 (fetched 18, cached 0)"."""
    counts_str = ", ".join(f"{key} {value}" for key, value in counts.items())
    return f"{action}: {source} {season_label} ({counts_str})"


class _LockHandle:
    """Per-process, per-vault-path lock bookkeeping: the open fd plus a
    reentrancy depth counter."""

    __slots__ = ("depth", "fd")

    def __init__(self, fd: int) -> None:
        self.fd = fd
        self.depth = 0


# Keyed by the vault's resolved path so nested `with self.lock():` blocks in
# the same process (e.g. a caller wrapping several commit_batch calls) don't
# deadlock on their own flock. fcntl.flock is POSIX-only; this project runs
# on Linux (developer machines and ubuntu-latest CI/Actions runners), so no
# Windows fallback is provided.
_VAULT_LOCKS: dict[Path, _LockHandle] = {}


class VaultRepo:
    """Wraps `git` operations against a single data-vault working copy."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        # GIT_TERMINAL_PROMPT=0 plus stdin=DEVNULL keep an unauthenticated
        # push/pull from blocking on a credential or host-key prompt; the
        # timeout is a second line of defense (T-01: hung push shouldn't
        # hang a whole collection batch).
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        try:
            return subprocess.run(
                ["git", "-C", str(self._path), *args],
                check=False,
                capture_output=True,
                text=True,
                timeout=_GIT_TIMEOUT_SECONDS,
                stdin=subprocess.DEVNULL,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise VaultCommitError(
                f"git subcommand {args[0] if args else '<none>'} timed out after "
                f"{_GIT_TIMEOUT_SECONDS}s"
            ) from exc

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

    @contextlib.contextmanager
    def lock(self, *, timeout_s: float = 300.0) -> Iterator[None]:
        """Serialize commit_batch across booth-review processes on this vault.

        Advisory (fcntl.flock, POSIX-only), held on a file inside `.git/` so
        it can never itself be staged/committed. Reentrant within one process
        for the same resolved vault path: nested `with self.lock():` blocks
        do not deadlock, and the OS-level lock is released only when the
        outermost block exits.
        """
        git_dir = self._path / ".git"
        if not git_dir.is_dir():
            raise VaultStateError(f"vault path has no .git directory: {self._path}")
        resolved = self._path.resolve()

        existing = _VAULT_LOCKS.get(resolved)
        if existing is not None:
            existing.depth += 1
            try:
                yield
            finally:
                existing.depth -= 1
            return

        lock_path = git_dir / "booth-review.lock"
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    os.close(fd)
                    raise VaultBusyError(
                        "vault is locked by another booth-review process"
                    ) from None
                time.sleep(_LOCK_POLL_INTERVAL_S)

        handle = _LockHandle(fd)
        handle.depth = 1
        _VAULT_LOCKS[resolved] = handle
        try:
            yield
        finally:
            handle.depth -= 1
            if handle.depth == 0:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
                del _VAULT_LOCKS[resolved]

    def _validate_relative_paths(self, paths: Sequence[str]) -> list[str]:
        validated: list[str] = []
        for raw_path in paths:
            pure = PurePosixPath(raw_path)
            if pure.is_absolute() or ".." in pure.parts:
                raise ValueError(f"invalid path for commit_batch: {raw_path!r}")
            validated.append(raw_path)
        return validated

    def _existing_or_tracked(self, path: str) -> bool:
        if (self._path / path).exists():
            return True
        result = self._run("ls-files", "--error-unmatch", "--", path)
        return result.returncode == 0

    def commit_batch(
        self, message: str, *, paths: Sequence[str] | None = None, push: bool = True
    ) -> bool:
        """Commit (optionally scoped to `paths`) and push. Returns True when a
        commit was made, False when there was nothing to commit.

        `paths=None` (default) keeps today's behavior: stage everything with
        `git add -A`. When `paths` is given, only those paths are staged,
        diffed, and committed -- an untracked file elsewhere in the vault
        stays untouched (T-02-02). Every path must be a relative POSIX path
        without ".."; violations raise ValueError before any git call.
        """
        if len(message) > _MAX_MESSAGE_LEN or not _MESSAGE_RE.match(message):
            raise ValueError(f"commit message failed the count-only whitelist: {message!r}")

        validated_paths = None if paths is None else self._validate_relative_paths(paths)

        with self.lock():
            self.check()

            if validated_paths is None:
                add_result = self._run("add", "-A")
                if add_result.returncode != 0:
                    raise VaultCommitError(f"git subcommand add exited {add_result.returncode}")

                diff_result = self._run("diff", "--cached", "--quiet")
                if diff_result.returncode == 0:
                    logger.info("vault: nothing to commit")
                    return False

                commit_result = self._run("commit", "-m", message)
                if commit_result.returncode != 0:
                    raise VaultCommitError(
                        f"git subcommand commit exited {commit_result.returncode}"
                    )
            else:
                scoped = [p for p in validated_paths if self._existing_or_tracked(p)]
                if not scoped:
                    logger.info("vault: nothing to commit")
                    return False

                add_result = self._run("add", "-A", "--", *scoped)
                if add_result.returncode != 0:
                    raise VaultCommitError(f"git subcommand add exited {add_result.returncode}")

                diff_result = self._run("diff", "--cached", "--quiet", "--", *scoped)
                if diff_result.returncode == 0:
                    logger.info("vault: nothing to commit")
                    return False

                commit_result = self._run("commit", "-m", message, "--", *scoped)
                if commit_result.returncode != 0:
                    raise VaultCommitError(
                        f"git subcommand commit exited {commit_result.returncode}"
                    )

            logger.info("vault: committed")

            if push:
                self._push_with_retry()

        return True

    def _push_with_retry(self) -> None:
        push_result = self._run("push")
        if push_result.returncode == 0:
            return

        # --autostash: an unrelated dirty tracked file elsewhere in the
        # working copy must never block this retry.
        pull_result = self._run("pull", "--rebase", "--autostash")
        if pull_result.returncode != 0:
            # Never leave the vault mid-rebase (T-02-03); ignore the abort's
            # own exit code, it's best-effort cleanup.
            self._run("rebase", "--abort")
            raise VaultCommitError(
                f"git subcommand pull --rebase exited {pull_result.returncode} "
                "(rebase aborted; local commit kept, not pushed)"
            )

        retry_result = self._run("push")
        if retry_result.returncode != 0:
            raise VaultCommitError(
                f"git subcommand push exited {retry_result.returncode} (after pull --rebase)"
            )
