"""Mirror dist/site into `booth-review/` of an already-checked-out target repo.

Every safety rule lives here so it can be tested offline against local bare
repos: the PUBLISH_ENABLED gate, the CFBD key re-grep, symlink refusal, the
staged-path guard, the idempotence skip, the before/after proof that nothing
outside the subdirectory changed, and a race-tolerant push.

D-02 refinement: a rejected push is retried by re-applying the mirror on the
fresh tip (fetch, hard reset, re-mirror, re-guard) rather than pull-rebase.
That works with a depth-1 checkout and re-runs the path guard every attempt.

Output and exception messages are count-only: git stderr, the target URL, and
file names are never echoed.
"""

from __future__ import annotations

import hashlib
import os
import random
import re
import shutil
import subprocess
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from booth_review.build.site_assembly import BUILD_MARKER, check_no_key_leak
from booth_review.errors import DeployError
from booth_review.vault import batch_message

SUBDIR_DEFAULT = "booth-review"
_SUBDIR_RE = re.compile(r"^[a-z0-9-]+$")
MAX_PUSH_ATTEMPTS = 4
_GIT_TIMEOUT_SECONDS = 120
_REJECTION_MARKERS = ("rejected", "non-fast-forward", "fetch first")
_BOT_NAME = "booth-review-publish[bot]"
_BOT_EMAIL = "booth-review-publish@users.noreply.github.com"


@dataclass(frozen=True)
class DeployResult:
    status: Literal["skipped", "no_change", "published"]
    files: int
    bundle_sha256: str | None
    outside_before: str | None
    outside_after: str | None
    attempts: int


def _site_files(site: Path) -> list[Path]:
    return sorted(
        p for p in site.rglob("*") if p.is_file() and p.relative_to(site).as_posix() != BUILD_MARKER
    )


def bundle_sha256(site: Path) -> str:
    """sha256 over sorted "relative-path NUL file-sha256 LF" records, marker excluded."""
    digest = hashlib.sha256()
    for path in _site_files(site):
        rel = path.relative_to(site).as_posix()
        file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        digest.update(f"{rel}\0{file_hash}\n".encode())
    return digest.hexdigest()


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            stdin=subprocess.DEVNULL,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except subprocess.TimeoutExpired as exc:
        raise DeployError("deploy git command timed out") from exc


def _git_ok(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    result = _git(repo, *args)
    if result.returncode != 0:
        raise DeployError(f"deploy git step failed (exit {result.returncode})")
    return result


def tree_hash_excluding(repo: Path, subdir: str) -> str:
    """sha256 over `git ls-tree -r -z HEAD` records whose path is not under `<subdir>/`."""
    out = _git_ok(repo, "ls-tree", "-r", "-z", "HEAD").stdout
    digest = hashlib.sha256()
    for record in out.split("\0"):
        if not record:
            continue
        _meta, _, path = record.partition("\t")
        if path == subdir or path.startswith(subdir + "/"):
            continue
        digest.update(record.encode() + b"\0")
    return digest.hexdigest()


def check_staged_paths(repo: Path, subdir: str) -> None:
    """Refuse any staged path outside `<subdir>/`, with a '..' part, or a symlink."""
    names = [
        n
        for n in _git_ok(
            repo, "diff", "--cached", "--name-only", "-z", "--no-renames"
        ).stdout.split("\0")
        if n
    ]
    bad = 0
    for name in names:
        parts = PurePosixPath(name).parts
        if not parts or parts[0] != subdir or ".." in parts:
            bad += 1
    summary = _git_ok(repo, "diff", "--cached", "--summary").stdout
    if "120000" in summary:
        bad += 1
    if bad:
        _git(repo, "reset", "-q")
        raise DeployError(f"deploy refused: {bad} staged path(s) outside {subdir}/ or unsafe")


def _validate_subdir(subdir: str) -> None:
    if not _SUBDIR_RE.match(subdir):
        raise ValueError("invalid subdir")


def _refuse_symlinks(site: Path) -> None:
    count = sum(1 for p in site.rglob("*") if p.is_symlink())
    if count:
        raise DeployError(f"deploy refused: {count} symlink(s) in site output")


def _mirror(site: Path, target: Path, subdir: str, files: list[Path]) -> None:
    root = target.resolve()
    dest = target / subdir
    if dest.is_symlink():
        raise DeployError("deploy refused: target subdir is a symlink")
    resolved = dest.resolve()
    if resolved.parent != root:
        raise DeployError("deploy refused: target subdir escapes the checkout")
    if dest.exists():
        shutil.rmtree(dest)
    for path in files:
        out = dest / path.relative_to(site)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, out)


def publish_site(
    site: Path,
    target: Path,
    *,
    subdir: str = SUBDIR_DEFAULT,
    env: Mapping[str, str] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    before_push: Callable[[int], None] | None = None,
) -> DeployResult:
    _validate_subdir(subdir)
    if (env if env is not None else os.environ).get("PUBLISH_ENABLED") != "true":
        return DeployResult("skipped", 0, None, None, None, 0)

    check_no_key_leak(site)
    _refuse_symlinks(site)
    files = _site_files(site)
    bundle = bundle_sha256(site)
    short = bundle[:12]

    branch = _git_ok(target, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if branch == "HEAD":
        raise DeployError("deploy refused: target checkout is on a detached HEAD")

    for attempt in range(1, MAX_PUSH_ATTEMPTS + 1):
        _git_ok(target, "fetch", "--depth=1", "origin", branch)
        _git_ok(target, "reset", "--hard", "FETCH_HEAD")
        _git_ok(target, "clean", "-fd")
        before = tree_hash_excluding(target, subdir)

        _mirror(site, target, subdir, files)
        _git_ok(target, "add", "-A", "--", subdir)
        check_staged_paths(target, subdir)

        if _git(target, "diff", "--cached", "--quiet").returncode == 0:
            return DeployResult("no_change", len(files), bundle, before, before, attempt)

        message = batch_message("deploy", "booth-review", f"bundle {short}", {"files": len(files)})
        _git_ok(
            target,
            "-c",
            f"user.name={_BOT_NAME}",
            "-c",
            f"user.email={_BOT_EMAIL}",
            "commit",
            "-q",
            "-m",
            message,
        )
        after = tree_hash_excluding(target, subdir)
        if before != after:
            raise DeployError("deploy refused: content outside the subdir changed")

        if before_push is not None:
            before_push(attempt)
        pushed = _git(target, "push", "origin", f"HEAD:refs/heads/{branch}")
        if pushed.returncode == 0:
            return DeployResult("published", len(files), bundle, before, after, attempt)
        if not any(marker in pushed.stderr for marker in _REJECTION_MARKERS):
            raise DeployError(f"deploy push failed (exit {pushed.returncode})")
        if attempt < MAX_PUSH_ATTEMPTS:
            sleep(random.uniform(2, 10))

    raise DeployError(f"deploy push rejected {MAX_PUSH_ATTEMPTS} times; nothing published")
