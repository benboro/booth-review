"""Offline tests for the deploy path (AUTO-03, AUTO-05) against local bare repos."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from booth_review.cli import main
from booth_review.deploy import publish
from booth_review.deploy.publish import (
    DeployResult,
    check_staged_paths,
    publish_site,
    tree_hash_excluding,
)
from booth_review.errors import DeployError, KeyLeakError

ENABLED = {"PUBLISH_ENABLED": "true"}
CANARY = "canary-key-0123456789abcdef"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )
    return result.stdout


def _clone(remote: Path, dest: Path) -> Path:
    subprocess.run(["git", "clone", "-q", str(remote), str(dest)], check=True, capture_output=True)
    _git(dest, "config", "user.name", "Test")
    _git(dest, "config", "user.email", "t@example.com")
    return dest


@pytest.fixture
def remote(tmp_path: Path, isolated_git_env: None, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CFBD_API_KEY", raising=False)
    monkeypatch.delenv("PUBLISH_ENABLED", raising=False)
    bare = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "-q", "-b", "master", str(bare)], check=True, capture_output=True
    )
    seed = _clone(bare, tmp_path / "seed")
    (seed / "index.html").write_text("home\n", encoding="utf-8")
    (seed / "CNAME").write_text("example.com\n", encoding="utf-8")
    (seed / "dashboard").mkdir()
    (seed / "dashboard" / "x.enc").write_text("enc\n", encoding="utf-8")
    (seed / ".github" / "workflows").mkdir(parents=True)
    (seed / ".github" / "workflows" / "pages.yml").write_text("name: p\n", encoding="utf-8")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-q", "-m", "seed")
    _git(seed, "push", "-q", "origin", "HEAD:refs/heads/master")
    return bare


@pytest.fixture
def target(remote: Path, tmp_path: Path) -> Path:
    return _clone(remote, tmp_path / "target")


def _site(tmp_path: Path, files: dict[str, str] | None = None) -> Path:
    site = tmp_path / "site"
    if site.exists():
        import shutil

        shutil.rmtree(site)
    site.mkdir()
    for name, text in (files or {"index.html": "<html>", "app.js": "x=1"}).items():
        path = site / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (site / ".booth-review-site").write_text("", encoding="utf-8")
    return site


def _remote_count(remote: Path) -> int:
    return int(_git(remote, "rev-list", "--count", "master").strip())


def _remote_tree(remote: Path) -> dict[str, str]:
    out = _git(remote, "ls-tree", "-r", "master")
    return {line.split("\t")[1]: line.split()[2] for line in out.splitlines()}


def test_publishing_disabled_deploys_nothing(remote: Path, tmp_path: Path) -> None:
    site = _site(tmp_path)
    not_a_repo = tmp_path / "plain"
    not_a_repo.mkdir()
    before = _remote_count(remote)
    for env in (
        {},
        {"PUBLISH_ENABLED": "TRUE"},
        {"PUBLISH_ENABLED": "1"},
        {"PUBLISH_ENABLED": "false"},
    ):
        result = publish_site(site, not_a_repo, env=env)
        assert result.status == "skipped"
    assert _remote_count(remote) == before


def test_deploy_touches_only_booth_review(remote: Path, target: Path, tmp_path: Path) -> None:
    seed_tree = _remote_tree(remote)
    before = _remote_count(remote)
    result = publish_site(_site(tmp_path), target, env=ENABLED, sleep=lambda _s: None)
    assert result.status == "published"
    assert _remote_count(remote) == before + 1
    tree = _remote_tree(remote)
    for path, blob in seed_tree.items():
        assert tree[path] == blob
    mirrored = sorted(p for p in tree if p.startswith("booth-review/"))
    assert mirrored == ["booth-review/app.js", "booth-review/index.html"]


def test_mirror_deletes_stale_files(remote: Path, target: Path, tmp_path: Path) -> None:
    publish_site(_site(tmp_path), target, env=ENABLED)
    publish_site(_site(tmp_path, {"index.html": "<html>2"}), target, env=ENABLED)
    tree = _remote_tree(remote)
    assert "booth-review/app.js" not in tree
    assert "booth-review/index.html" in tree


def test_second_identical_deploy_makes_no_commit(
    remote: Path, target: Path, tmp_path: Path
) -> None:
    site = _site(tmp_path)
    publish_site(site, target, env=ENABLED)
    count = _remote_count(remote)
    result = publish_site(site, target, env=ENABLED)
    assert result.status == "no_change"
    assert _remote_count(remote) == count


def test_path_guard_refuses_outside_path(
    remote: Path, target: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (target / "CNAME").write_text("evil.example\n", encoding="utf-8")
    _git(target, "add", "CNAME")
    with pytest.raises(DeployError, match=r"1 staged path\(s\)"):
        check_staged_paths(target, "booth-review")
    _git(target, "checkout", "-q", "--", "CNAME")

    original = publish._mirror

    def sneaky(site: Path, tgt: Path, subdir: str, files: list[Path]) -> None:
        original(site, tgt, subdir, files)
        (tgt / "README.md").write_text("x\n", encoding="utf-8")
        _git(tgt, "add", "README.md")

    monkeypatch.setattr(publish, "_mirror", sneaky)
    count = _remote_count(remote)
    with pytest.raises(DeployError):
        publish_site(_site(tmp_path), target, env=ENABLED)
    assert _remote_count(remote) == count


def test_symlink_in_site_refused(remote: Path, target: Path, tmp_path: Path) -> None:
    site = _site(tmp_path)
    (site / "link.js").symlink_to(site / "app.js")
    count = _remote_count(remote)
    with pytest.raises(DeployError, match="symlink"):
        publish_site(site, target, env=ENABLED)
    assert _remote_count(remote) == count


def _dashboard_pusher(remote: Path, tmp_path: Path, times: int | None) -> tuple[list[int], object]:
    other = _clone(remote, tmp_path / "other")
    calls: list[int] = []

    def hook(attempt: int) -> None:
        if times is not None and len(calls) >= times:
            return
        calls.append(attempt)
        _git(other, "pull", "-q", "--rebase", "origin", "master")
        (other / "dashboard" / f"n{len(calls)}.enc").write_text("e\n", encoding="utf-8")
        _git(other, "add", "-A")
        _git(other, "commit", "-q", "-m", "dash")
        _git(other, "push", "-q", "origin", "HEAD:refs/heads/master")

    return calls, hook


def test_push_race_reapplies_on_fresh_tip(remote: Path, target: Path, tmp_path: Path) -> None:
    _calls, hook = _dashboard_pusher(remote, tmp_path, times=1)
    sleeps: list[float] = []
    before = _remote_count(remote)
    result = publish_site(
        _site(tmp_path),
        target,
        env=ENABLED,
        sleep=sleeps.append,
        before_push=hook,  # type: ignore[arg-type]
    )
    assert result.status == "published"
    assert result.attempts == 2
    assert _remote_count(remote) == before + 2
    tree = _remote_tree(remote)
    assert "dashboard/x.enc" in tree
    assert "dashboard/n1.enc" in tree
    assert "booth-review/index.html" in tree
    assert len(sleeps) == 1


def test_push_gives_up_after_four_rejections(remote: Path, target: Path, tmp_path: Path) -> None:
    calls, hook = _dashboard_pusher(remote, tmp_path, times=None)
    with pytest.raises(DeployError, match="rejected 4 times"):
        publish_site(
            _site(tmp_path),
            target,
            env=ENABLED,
            sleep=lambda _s: None,
            before_push=hook,  # type: ignore[arg-type]
        )
    assert len(calls) == 4
    assert not any(p.startswith("booth-review/") for p in _remote_tree(remote))


def test_key_in_site_refuses_deploy(
    remote: Path,
    target: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("CFBD_API_KEY", CANARY)
    site = _site(tmp_path, {"index.html": "<html>", "leak.js": f"// {CANARY}"})
    count = _remote_count(remote)
    with pytest.raises(KeyLeakError) as info:
        publish_site(site, target, env=ENABLED)
    assert CANARY not in str(info.value)
    assert _remote_count(remote) == count
    captured = capsys.readouterr()
    assert CANARY not in captured.out + captured.err


@pytest.mark.parametrize("subdir", ["", ".", "../x", "Booth"])
def test_subdir_validation(subdir: str, target: Path, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="invalid subdir"):
        publish_site(_site(tmp_path), target, subdir=subdir, env=ENABLED)


def test_untouched_proof_hashes_match(target: Path, tmp_path: Path) -> None:
    result = publish_site(_site(tmp_path), target, env=ENABLED)
    assert isinstance(result, DeployResult)
    assert result.outside_before is not None
    assert result.outside_before == result.outside_after
    assert result.outside_after == tree_hash_excluding(target, "booth-review")


# --- CLI level -------------------------------------------------------------


def test_cli_deploy_disabled_prints_skip(
    target: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["deploy", "--site", str(_site(tmp_path)), "--target", str(target)])
    assert code == 0
    assert capsys.readouterr().out.strip() == "deploy skipped: publishing disabled"


def test_cli_deploy_publishes_then_reports_no_change(
    target: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("PUBLISH_ENABLED", "true")
    argv = ["deploy", "--site", str(_site(tmp_path)), "--target", str(target)]
    assert main(argv) == 0
    out = capsys.readouterr().out
    assert "deploy: published bundle " in out
    assert "(files 2, attempts 1)" in out
    assert "outside booth-review unchanged: yes (before " in out
    assert str(target) not in out
    assert main(argv) == 0
    again = capsys.readouterr().out
    assert "deploy: no change (bundle " in again
    assert "files 2)" in again


def test_cli_deploy_bad_subdir_exits_nonzero(
    remote: Path,
    target: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("PUBLISH_ENABLED", "true")
    count = _remote_count(remote)
    code = main(
        ["deploy", "--site", str(_site(tmp_path)), "--target", str(target), "--subdir", "../x"]
    )
    assert code == 2
    assert "invalid --subdir" in capsys.readouterr().err
    assert _remote_count(remote) == count


def test_cli_deploy_error_exits_3(
    target: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("PUBLISH_ENABLED", "true")
    site = _site(tmp_path)
    (site / "link.js").symlink_to(site / "app.js")
    code = main(["deploy", "--site", str(site), "--target", str(target)])
    assert code == 3
    assert "error: DeployError:" in capsys.readouterr().err
