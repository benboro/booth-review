"""Behavioral tests for VaultRepo: commit-and-push with count-only messages.

All fixtures live entirely on local disk: a `git init --bare` remote plus a
clone, both under tmp_path, with an isolated git config so the operator's
global config never leaks in. No network is involved.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from booth_review.errors import VaultBusyError, VaultCommitError, VaultStateError
from booth_review.vault import VaultRepo, batch_message


def _run_ok(args: list[str]) -> None:
    subprocess.run(args, check=True, capture_output=True, text=True)


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


@pytest.fixture
def vault_repo_env(tmp_path: Path, isolated_git_env: None) -> tuple[Path, Path]:
    """A bare remote plus a clone at tmp_path/'vault', with a seed commit pushed."""
    remote = tmp_path / "remote.git"
    _run_ok(["git", "init", "--bare", "-q", "-b", "main", str(remote)])

    vault = tmp_path / "vault"
    _run_ok(["git", "clone", "-q", str(remote), str(vault)])
    _run_ok(["git", "-C", str(vault), "config", "user.name", "Test Bot"])
    _run_ok(["git", "-C", str(vault), "config", "user.email", "test-bot@example.com"])

    (vault / "README.md").write_text("vault\n", encoding="utf-8")
    _run_ok(["git", "-C", str(vault), "add", "README.md"])
    _run_ok(["git", "-C", str(vault), "commit", "-q", "-m", "init: seed"])
    _run_ok(["git", "-C", str(vault), "push", "-q", "origin", "main"])

    return remote, vault


# -- batch_message --------------------------------------------------------------


def test_batch_message_format() -> None:
    message = batch_message(
        "collect", "sports506", "2025", {"fetched": 18, "cached": 0, "not_modified": 0}
    )
    assert message == "collect: sports506 2025 (fetched 18, cached 0, not_modified 0)"


# -- check() ----------------------------------------------------------------------


def test_check_raises_when_path_missing(tmp_path: Path, isolated_git_env: None) -> None:
    repo = VaultRepo(tmp_path / "does-not-exist")
    with pytest.raises(VaultStateError):
        repo.check()


def test_check_raises_when_not_a_git_working_copy(tmp_path: Path, isolated_git_env: None) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    repo = VaultRepo(plain)
    with pytest.raises(VaultStateError):
        repo.check()


def test_check_raises_when_path_is_plain_folder_inside_another_repo(
    tmp_path: Path, isolated_git_env: None
) -> None:
    outer = tmp_path / "outer"
    outer.mkdir()
    _run_ok(["git", "init", "-q", str(outer)])
    fake_vault = outer / "data" / "vault"
    fake_vault.mkdir(parents=True)

    repo = VaultRepo(fake_vault)
    with pytest.raises(VaultStateError):
        repo.check()


def test_check_raises_when_no_origin_remote(tmp_path: Path, isolated_git_env: None) -> None:
    vault = tmp_path / "vault"
    _run_ok(["git", "init", "-q", str(vault)])

    repo = VaultRepo(vault)
    with pytest.raises(VaultStateError):
        repo.check()


def test_check_passes_for_a_real_clone(vault_repo_env: tuple[Path, Path]) -> None:
    _remote, vault = vault_repo_env
    repo = VaultRepo(vault)
    repo.check()  # must not raise


# -- commit_batch: happy path -------------------------------------------------------


def test_commit_batch_commits_new_file_pushes_and_returns_true(
    vault_repo_env: tuple[Path, Path],
) -> None:
    remote, vault = vault_repo_env
    repo = VaultRepo(vault)
    (vault / "raw" / "sports506").mkdir(parents=True)
    (vault / "raw" / "sports506" / "wk01.html").write_text("<html></html>\n", encoding="utf-8")

    message = batch_message(
        "collect", "sports506", "2025", {"fetched": 1, "cached": 0, "not_modified": 0}
    )
    result = repo.commit_batch(message)

    assert result is True
    assert _remote_head_subject(remote) == message


def test_commit_batch_returns_false_when_nothing_changed(
    vault_repo_env: tuple[Path, Path],
) -> None:
    remote, vault = vault_repo_env
    repo = VaultRepo(vault)
    message = batch_message(
        "collect", "sports506", "2025", {"fetched": 0, "cached": 0, "not_modified": 0}
    )

    result = repo.commit_batch(message)

    assert result is False
    assert _remote_log_count(remote) == 1  # only the fixture's seed commit


# -- commit_batch: message validation ------------------------------------------------


@pytest.mark.parametrize(
    "bad_message",
    [
        "Collect: sports506 2025 (fetched 1)",  # uppercase action
        "collect sports506 2025 (fetched 1)",  # missing colon
        "collect: " + "x" * 115,  # over 120 chars
        "collect: sports506 2025 <script>alert(1)</script>",  # disallowed chars
    ],
)
def test_commit_batch_rejects_invalid_messages(
    vault_repo_env: tuple[Path, Path], bad_message: str
) -> None:
    _remote, vault = vault_repo_env
    repo = VaultRepo(vault)

    with pytest.raises(ValueError):
        repo.commit_batch(bad_message)


# -- commit_batch: push rejection / retry --------------------------------------------


def test_commit_batch_retries_once_after_push_rejection(
    tmp_path: Path, vault_repo_env: tuple[Path, Path]
) -> None:
    remote, vault = vault_repo_env

    # A second clone pushes first, moving the remote ahead of `vault`'s local branch.
    second = tmp_path / "second-clone"
    _run_ok(["git", "clone", "-q", str(remote), str(second)])
    _run_ok(["git", "-C", str(second), "config", "user.name", "Second Bot"])
    _run_ok(["git", "-C", str(second), "config", "user.email", "second-bot@example.com"])
    (second / "other.txt").write_text("other\n", encoding="utf-8")
    _run_ok(["git", "-C", str(second), "add", "other.txt"])
    _run_ok(["git", "-C", str(second), "commit", "-q", "-m", "init: second"])
    _run_ok(["git", "-C", str(second), "push", "-q"])

    repo = VaultRepo(vault)
    (vault / "raw").mkdir()
    (vault / "raw" / "a.html").write_text("a\n", encoding="utf-8")

    message = batch_message(
        "collect", "sports506", "2025", {"fetched": 1, "cached": 0, "not_modified": 0}
    )
    result = repo.commit_batch(message)

    assert result is True
    assert _remote_head_subject(remote) == message
    assert _remote_log_count(remote) == 3  # seed + second's commit + this rebased commit


def test_commit_batch_raises_vault_commit_error_when_push_times_out(
    vault_repo_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """WR-03: a hung `git push` (e.g. blocked on a credential prompt) must
    fail fast as VaultCommitError, not hang the process indefinitely."""
    _remote, vault = vault_repo_env
    repo = VaultRepo(vault)
    (vault / "raw").mkdir()
    (vault / "raw" / "a.html").write_text("a\n", encoding="utf-8")

    real_run = subprocess.run

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if args[-1] == "push":
            raise subprocess.TimeoutExpired(cmd=args, timeout=60)
        return real_run(args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("booth_review.vault.subprocess.run", fake_run)

    message = batch_message(
        "collect", "sports506", "2025", {"fetched": 1, "cached": 0, "not_modified": 0}
    )
    with pytest.raises(VaultCommitError, match="timed out"):
        repo.commit_batch(message)


def test_run_passes_stdin_devnull_timeout_and_disables_terminal_prompt(
    vault_repo_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """WR-03: every git call must redirect stdin, set a timeout, and disable
    GIT_TERMINAL_PROMPT so a credential/host-key prompt can never block."""
    _remote, vault = vault_repo_env
    repo = VaultRepo(vault)

    captured: dict[str, object] = {}
    real_run = subprocess.run

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if args[-1] == "rev-parse" or "--show-toplevel" in args:
            captured.update(kwargs)
        return real_run(args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("booth_review.vault.subprocess.run", fake_run)
    repo.check()

    assert captured["stdin"] is subprocess.DEVNULL
    assert captured["timeout"] == 60
    assert captured["env"]["GIT_TERMINAL_PROMPT"] == "0"  # type: ignore[index]


def test_commit_batch_raises_after_second_push_rejection(
    vault_repo_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _remote, vault = vault_repo_env
    repo = VaultRepo(vault, sleep=lambda _seconds: None)
    (vault / "raw").mkdir()
    (vault / "raw" / "a.html").write_text("a\n", encoding="utf-8")

    real_run = subprocess.run

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if args[-1] == "push":
            return subprocess.CompletedProcess(args, returncode=1, stdout="", stderr="rejected")
        return real_run(args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("booth_review.vault.subprocess.run", fake_run)

    message = batch_message(
        "collect", "sports506", "2025", {"fetched": 1, "cached": 0, "not_modified": 0}
    )
    with pytest.raises(VaultCommitError):
        repo.commit_batch(message)


def _competing_clone(tmp_path: Path, remote: Path) -> Path:
    second = tmp_path / "second-clone"
    _run_ok(["git", "clone", "-q", str(remote), str(second)])
    _run_ok(["git", "-C", str(second), "config", "user.name", "Second Bot"])
    _run_ok(["git", "-C", str(second), "config", "user.email", "second-bot@example.com"])
    return second


def _competing_push(second: Path, name: str) -> None:
    _run_ok(["git", "-C", str(second), "pull", "-q", "--rebase"])
    (second / name).write_text(f"{name}\n", encoding="utf-8")
    _run_ok(["git", "-C", str(second), "add", name])
    _run_ok(["git", "-C", str(second), "commit", "-q", "-m", f"init: {name}"])
    _run_ok(["git", "-C", str(second), "push", "-q"])


def _race_after_pulls(repo: VaultRepo, second: Path, pulls_to_race: int) -> None:
    """After each of the first `pulls_to_race` pull --rebase calls, a competing
    clone pushes, so the next push of `repo` is rejected again."""
    real_run = repo._run
    pulls = 0

    def racing_run(*args: str) -> subprocess.CompletedProcess[str]:
        nonlocal pulls
        result = real_run(*args)
        if args[:2] == ("pull", "--rebase"):
            pulls += 1
            if pulls <= pulls_to_race:
                _competing_push(second, f"race-{pulls}.txt")
        return result

    repo._run = racing_run  # type: ignore[method-assign]


def test_commit_batch_succeeds_on_third_push_round(
    tmp_path: Path, vault_repo_env: tuple[Path, Path]
) -> None:
    remote, vault = vault_repo_env
    second = _competing_clone(tmp_path, remote)
    _competing_push(second, "first.txt")  # round 1's push is rejected

    sleeps: list[float] = []
    repo = VaultRepo(vault, sleep=sleeps.append)
    _race_after_pulls(repo, second, pulls_to_race=1)  # round 2's push is rejected too
    (vault / "raw").mkdir()
    (vault / "raw" / "a.html").write_text("a\n", encoding="utf-8")

    message = batch_message(
        "collect", "sports506", "2025", {"fetched": 1, "cached": 0, "not_modified": 0}
    )
    assert repo.commit_batch(message) is True

    assert sleeps == [1.0, 2.0]
    assert _remote_head_subject(remote) == message
    assert _remote_log_count(remote) == 4  # seed + first + race-1 + this commit


def test_commit_batch_raises_after_three_rejected_rounds_without_rebase_left(
    tmp_path: Path, vault_repo_env: tuple[Path, Path]
) -> None:
    remote, vault = vault_repo_env
    second = _competing_clone(tmp_path, remote)
    _competing_push(second, "first.txt")

    sleeps: list[float] = []
    repo = VaultRepo(vault, sleep=sleeps.append)
    _race_after_pulls(repo, second, pulls_to_race=3)
    (vault / "raw").mkdir()
    (vault / "raw" / "a.html").write_text("a\n", encoding="utf-8")

    message = batch_message(
        "collect", "sports506", "2025", {"fetched": 1, "cached": 0, "not_modified": 0}
    )
    with pytest.raises(VaultCommitError, match="after 3 pull --rebase rounds"):
        repo.commit_batch(message)

    assert sleeps == [1.0, 2.0]
    assert not (vault / ".git" / "rebase-merge").exists()
    assert not (vault / ".git" / "rebase-apply").exists()


# -- lock() -------------------------------------------------------------------------


def test_lock_raises_vault_busy_error_when_held_by_another_process(
    vault_repo_env: tuple[Path, Path],
) -> None:
    _remote, vault = vault_repo_env
    lock_path = vault / ".git" / "booth-review.lock"

    holder_script = (
        "import fcntl, time\n"
        f"fd = open({str(lock_path)!r}, 'a+')\n"
        "fcntl.flock(fd, fcntl.LOCK_EX)\n"
        "print('locked', flush=True)\n"
        "time.sleep(2)\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", holder_script], stdout=subprocess.PIPE, text=True
    )
    try:
        line = proc.stdout.readline() if proc.stdout is not None else ""
        assert line.strip() == "locked"

        repo = VaultRepo(vault)
        with pytest.raises(VaultBusyError), repo.lock(timeout_s=0.5):
            pass
    finally:
        proc.wait(timeout=5)


def test_lock_is_reentrant_within_one_process(vault_repo_env: tuple[Path, Path]) -> None:
    _remote, vault = vault_repo_env
    repo = VaultRepo(vault)

    with repo.lock(), repo.lock():
        pass  # must not deadlock


# -- commit_batch: path-scoped commits -----------------------------------------------


def test_commit_batch_paths_scopes_commit_and_leaves_other_files_untracked(
    vault_repo_env: tuple[Path, Path],
) -> None:
    remote, vault = vault_repo_env
    repo = VaultRepo(vault)
    (vault / "raw" / "sports506" / "2025").mkdir(parents=True)
    (vault / "raw" / "sports506" / "2025" / "wk01.html").write_text("a\n", encoding="utf-8")
    (vault / "ledger").mkdir()
    (vault / "ledger" / "requests.jsonl").write_text('{"x": 1}\n', encoding="utf-8")
    (vault / "raw" / "ratingsref").mkdir()
    (vault / "raw" / "ratingsref" / "other.json").write_text("{}\n", encoding="utf-8")

    message = batch_message(
        "collect", "sports506", "2025", {"fetched": 1, "cached": 0, "not_modified": 0}
    )
    result = repo.commit_batch(message, paths=["raw/sports506/2025", "ledger/requests.jsonl"])

    assert result is True
    assert _remote_head_subject(remote) == message

    status = subprocess.run(
        ["git", "-C", str(vault), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "raw/ratingsref/" in status.stdout
    assert "raw/sports506" not in status.stdout
    assert "ledger/requests.jsonl" not in status.stdout


def test_commit_batch_paths_absolute_or_dotdot_raise_before_any_git_call(
    vault_repo_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _remote, vault = vault_repo_env
    repo = VaultRepo(vault)
    called: list[list[str]] = []
    real_run = subprocess.run

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        called.append(args)
        return real_run(args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("booth_review.vault.subprocess.run", fake_run)

    message = batch_message(
        "collect", "sports506", "2025", {"fetched": 1, "cached": 0, "not_modified": 0}
    )

    with pytest.raises(ValueError):
        repo.commit_batch(message, paths=["/etc/passwd"])
    assert called == []

    with pytest.raises(ValueError):
        repo.commit_batch(message, paths=["../outside.html"])
    assert called == []


# -- push retry: rebase abort on conflict --------------------------------------------


def test_push_retry_aborts_rebase_on_conflict_and_raises(
    tmp_path: Path, vault_repo_env: tuple[Path, Path]
) -> None:
    remote, vault = vault_repo_env

    second = tmp_path / "second-clone-conflict"
    _run_ok(["git", "clone", "-q", str(remote), str(second)])
    _run_ok(["git", "-C", str(second), "config", "user.name", "Second Bot"])
    _run_ok(["git", "-C", str(second), "config", "user.email", "second-bot@example.com"])
    (second / "README.md").write_text("remote change\n", encoding="utf-8")
    _run_ok(["git", "-C", str(second), "add", "README.md"])
    _run_ok(["git", "-C", str(second), "commit", "-q", "-m", "init: remote edit"])
    _run_ok(["git", "-C", str(second), "push", "-q"])

    repo = VaultRepo(vault)
    (vault / "README.md").write_text("local change\n", encoding="utf-8")

    message = batch_message(
        "collect", "sports506", "2025", {"fetched": 1, "cached": 0, "not_modified": 0}
    )
    with pytest.raises(VaultCommitError):
        repo.commit_batch(message, paths=["README.md"])

    status = subprocess.run(
        ["git", "-C", str(vault), "status"], capture_output=True, text=True, check=True
    )
    assert "rebase in progress" not in status.stdout
    assert not (vault / ".git" / "rebase-merge").exists()
    assert not (vault / ".git" / "rebase-apply").exists()


# -- drop_unpushed_since (CR-02 rollback) ---------------------------------------


def _git_out(vault: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(vault), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _reject_pushes(remote: Path) -> None:
    hook = remote / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)


def test_head_returns_the_current_commit(vault_repo_env: tuple[Path, Path]) -> None:
    _, vault = vault_repo_env
    assert VaultRepo(vault).head() == _git_out(vault, "rev-parse", "HEAD")


def test_drop_unpushed_since_is_a_noop_when_head_is_before(
    vault_repo_env: tuple[Path, Path],
) -> None:
    _, vault = vault_repo_env
    repo = VaultRepo(vault)
    before = repo.head()
    assert before is not None
    assert repo.drop_unpushed_since(before) is False
    assert repo.head() == before


def test_drop_unpushed_since_drops_a_commit_whose_push_failed(
    vault_repo_env: tuple[Path, Path],
) -> None:
    remote, vault = vault_repo_env
    repo = VaultRepo(vault, sleep=lambda _s: None)
    before = repo.head()
    assert before is not None
    _reject_pushes(remote)
    (vault / "nfl.csv").write_text("a,b\n", encoding="utf-8")
    with pytest.raises(VaultCommitError):
        repo.commit_batch("job: nfl (fetched 1)", paths=["nfl.csv"])
    assert repo.head() != before

    assert repo.drop_unpushed_since(before) is True

    assert repo.head() == before
    assert (vault / "nfl.csv").read_text(encoding="utf-8") == "a,b\n"
    assert _git_out(vault, "status", "--porcelain") == "?? nfl.csv"
    assert _git_out(vault, "rev-list", "--count", "@{u}..HEAD") == "0"


def test_drop_unpushed_since_keeps_an_unpushed_earlier_commit(
    vault_repo_env: tuple[Path, Path],
) -> None:
    _, vault = vault_repo_env
    repo = VaultRepo(vault)
    (vault / "cfb.csv").write_text("1\n", encoding="utf-8")
    assert repo.commit_batch("job: cfb (fetched 1)", paths=["cfb.csv"], push=False)
    before = repo.head()
    assert before is not None
    (vault / "nfl.csv").write_text("2\n", encoding="utf-8")
    assert repo.commit_batch("job: nfl (fetched 1)", paths=["nfl.csv"], push=False)
    head = repo.head()

    assert repo.drop_unpushed_since(before) is False
    assert repo.head() == head


def test_drop_unpushed_since_without_upstream_is_a_noop(
    vault_repo_env: tuple[Path, Path],
) -> None:
    _, vault = vault_repo_env
    repo = VaultRepo(vault)
    before = repo.head()
    assert before is not None
    (vault / "nfl.csv").write_text("2\n", encoding="utf-8")
    repo.commit_batch("job: nfl (fetched 1)", paths=["nfl.csv"], push=False)
    head = repo.head()
    _run_ok(["git", "-C", str(vault), "branch", "--unset-upstream"])

    assert repo.drop_unpushed_since(before) is False
    assert repo.head() == head


def _push_from_other_clone(remote: Path, tmp_path: Path, files: dict[str, str]) -> None:
    other = tmp_path / "other"
    _run_ok(["git", "clone", "-q", str(remote), str(other)])
    for rel, text in files.items():
        (other / rel).write_text(text, encoding="utf-8")
    ident = ("-c", "user.name=Other", "-c", "user.email=other@example.com")
    for args in (("add", "-A"), ("commit", "-q", "-m", "other: edit"), ("push", "-q")):
        _run_ok(["git", *ident, "-C", str(other), *args])


def test_drop_unpushed_since_after_a_conflict_leaves_no_markers_and_keeps_union_lines(
    vault_repo_env: tuple[Path, Path], tmp_path: Path
) -> None:
    remote, vault = vault_repo_env
    repo = VaultRepo(vault, sleep=lambda _s: None)
    (vault / ".gitattributes").write_text("*.jsonl merge=union\n", encoding="utf-8")
    (vault / "nfl.csv").write_text("a\n", encoding="utf-8")
    (vault / "requests.jsonl").write_text("seed\n", encoding="utf-8")
    assert repo.commit_batch(
        "job: seed (fetched 1)", paths=[".gitattributes", "nfl.csv", "requests.jsonl"]
    )
    before = repo.head()
    assert before is not None
    _push_from_other_clone(
        remote,
        tmp_path,
        {"nfl.csv": "remote\n", "requests.jsonl": "seed\nremote\n", "other.txt": "o\n"},
    )
    (vault / "nfl.csv").write_text("local\n", encoding="utf-8")
    (vault / "requests.jsonl").write_text("seed\nlocal\n", encoding="utf-8")
    (vault / "new.csv").write_text("n\n", encoding="utf-8")
    with pytest.raises(VaultCommitError):
        repo.commit_batch("job: nfl (fetched 1)", paths=["nfl.csv", "requests.jsonl", "new.csv"])

    assert repo.drop_unpushed_since(before) is True

    assert repo.head() == _git_out(vault, "rev-parse", "@{u}")
    # The conflicting file takes the remote's side, with no markers on disk.
    assert (vault / "nfl.csv").read_text(encoding="utf-8") == "remote\n"
    # The union ledger keeps both lines, and the remote-only file is on disk.
    ledger = (vault / "requests.jsonl").read_text(encoding="utf-8").splitlines()
    assert sorted(ledger) == ["local", "remote", "seed"]
    assert (vault / "other.txt").read_text(encoding="utf-8") == "o\n"
    assert (vault / "new.csv").read_text(encoding="utf-8") == "n\n"
    status = {line.strip() for line in _git_out(vault, "status", "--porcelain").splitlines()}
    assert status == {"M requests.jsonl", "?? new.csv"}
    # Re-committing the leftovers now pushes cleanly.
    assert repo.commit_batch("job: nfl (fetched 1)", paths=["requests.jsonl", "new.csv"])
    assert _git_out(vault, "rev-list", "--count", "@{u}..HEAD") == "0"
