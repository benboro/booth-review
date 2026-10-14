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
from collections.abc import Callable, Iterator, Mapping, Sequence
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
# Pull-rebase-push rounds a rejected push gets before commit_batch gives up.
_PUSH_ROUNDS = 3

_VAULT_LOCKS: dict[Path, _LockHandle] = {}


class VaultRepo:
    """Wraps `git` operations against a single data-vault working copy."""

    def __init__(self, path: Path, *, sleep: Callable[[float], None] = time.sleep) -> None:
        self._path = path
        self._sleep = sleep

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

    def head(self) -> str | None:
        """The commit HEAD points at, or None when the vault has no commits."""
        result = self._run("rev-parse", "--verify", "HEAD")
        return result.stdout.strip() if result.returncode == 0 else None

    def drop_unpushed_since(self, before: str) -> bool:
        """Drop the unpushed commits made after `before`; True when HEAD moved.

        For a step whose push failed and whose commit must not linger on the
        local branch, where the next push would replay it. Moves the branch to
        @{u} with `reset --mixed`, never `--hard`, and lays the dropped commits'
        changes back on disk merged onto @{u} (`merge-tree`, so `merge=union`
        ledgers keep both sides' lines): the next scoped commit re-commits
        them. A path that truly conflicts with the remote takes the remote's
        version, so no later `pull --rebase --autostash` can pop conflict
        markers into a data file. Files the remote changed are brought up to
        @{u} on disk too, unless they hold an unrelated local edit.

        Acts only when `before` is an ancestor of @{u}, i.e. everything up to
        the step is already on the remote, so an unpushed earlier commit is
        never reset away. With no upstream, or HEAD == `before`, it does
        nothing and returns False.
        """
        with self.lock():
            tip = self.head()
            if tip is None or tip == before:
                return False
            if self._run("rev-parse", "--verify", "@{u}").returncode != 0:
                return False
            if self._run("merge-base", "--is-ancestor", before, "@{u}").returncode != 0:
                return False
            upstream = self._run("rev-parse", "--verify", "@{u}").stdout.strip()
            base_result = self._run("merge-base", tip, upstream)
            base = base_result.stdout.strip()
            if base_result.returncode != 0 or not base:
                return False

            merge_result = self._run(
                "merge-tree", "--write-tree", "--name-only", "--no-messages", "-z", upstream, tip
            )
            if merge_result.returncode not in (0, 1):
                raise VaultCommitError(
                    f"git subcommand merge-tree exited {merge_result.returncode}"
                )
            merged_tree, *conflicted_list = merge_result.stdout.split("\0")
            conflicted = {path for path in conflicted_list if path}
            dropped = self._changed_paths(base, tip)
            remote_changed = self._changed_paths(base, upstream)

            reset_result = self._run("reset", "--mixed", "--quiet", upstream)
            if reset_result.returncode != 0:
                raise VaultCommitError(f"git subcommand reset exited {reset_result.returncode}")

            for rel in sorted(dropped | remote_changed):
                target = self._path / rel
                if rel not in dropped and self._read_disk(target) != self._blob(base, rel):
                    continue  # an unrelated local edit to a file the remote changed
                source = upstream if rel in conflicted else merged_tree
                self._write_disk(target, self._blob(source, rel))
            logger.info("vault: dropped unpushed commit(s), %d conflicted", len(conflicted))
            return True

    def _changed_paths(self, old: str, new: str) -> set[str]:
        result = self._run("diff", "--name-only", "--no-renames", "-z", old, new)
        if result.returncode != 0:
            raise VaultCommitError(f"git subcommand diff exited {result.returncode}")
        return {path for path in result.stdout.split("\0") if path}

    def _blob(self, rev: str, rel: str) -> bytes | None:
        """The bytes of `rel` at `rev`, or None when `rev` has no such file."""
        try:
            result = subprocess.run(
                ["git", "-C", str(self._path), "cat-file", "blob", f"{rev}:{rel}"],
                check=False,
                capture_output=True,
                timeout=_GIT_TIMEOUT_SECONDS,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired as exc:
            raise VaultCommitError(
                f"git subcommand cat-file timed out after {_GIT_TIMEOUT_SECONDS}s"
            ) from exc
        return result.stdout if result.returncode == 0 else None

    @staticmethod
    def _read_disk(target: Path) -> bytes | None:
        return target.read_bytes() if target.is_file() else None

    @staticmethod
    def _write_disk(target: Path, content: bytes | None) -> None:
        if content is None:
            target.unlink(missing_ok=True)
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    def _push_with_retry(self) -> None:
        """Up to 3 rounds of push; a rejected push is followed by pull --rebase.

        Backoff of 1s then 2s sits between rounds. The update pipeline adds a
        build commit to every run, so a single retry is too thin against the
        user's local runs pushing at the same time.
        """
        for round_number in range(1, _PUSH_ROUNDS + 1):
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

            if round_number == _PUSH_ROUNDS:
                raise VaultCommitError(
                    f"git subcommand push exited {push_result.returncode} "
                    f"(after {_PUSH_ROUNDS} pull --rebase rounds)"
                )
            self._sleep(float(round_number))
