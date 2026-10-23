"""Offline tests for the deploy path (AUTO-03, AUTO-05) against local bare repos."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from booth_review.build.site_assembly import (
    assemble_site,
    load_mlb_site_payload,
    load_nfl_site_payload,
    site_sports,
)
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
    # A configured key is required for the deploy's key re-grep (WR-01); the
    # synthetic canary never appears in the default site files.
    monkeypatch.setenv("CFBD_API_KEY", CANARY)
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


def test_target_ignore_rules_never_drop_site_files(
    remote: Path, target: Path, tmp_path: Path
) -> None:
    # WR-04: the target repo's ignore rules (root .gitignore, info/exclude)
    # must not silently drop a site file from the deploy commit.
    seed = _clone(remote, tmp_path / "ignore-seed")
    (seed / ".gitignore").write_text("*.json\nvendor/\n", encoding="utf-8")
    _git(seed, "add", ".gitignore")
    _git(seed, "commit", "-q", "-m", "ignore")
    _git(seed, "push", "-q", "origin", "HEAD:refs/heads/master")
    (target / ".git" / "info" / "exclude").write_text("*.map\n", encoding="utf-8")
    site = _site(
        tmp_path,
        {
            "index.html": "<html>",
            "site-data.json": "{}",
            "vendor/lib.js": "v=1",
            "app.js.map": "{}",
        },
    )
    result = publish_site(site, target, env=ENABLED)
    assert result.status == "published"
    mirrored = sorted(p for p in _remote_tree(remote) if p.startswith("booth-review/"))
    assert mirrored == [
        "booth-review/app.js.map",
        "booth-review/index.html",
        "booth-review/site-data.json",
        "booth-review/vendor/lib.js",
    ]


def test_committed_tree_mismatch_refuses_push(
    remote: Path, target: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # WR-04: whatever drops a mirrored file before the commit, the deploy
    # compares the committed subdir with the site and refuses to push.
    original = publish._mirror

    def lossy(site: Path, tgt: Path, subdir: str, files: list[Path]) -> None:
        original(site, tgt, subdir, files)
        (tgt / subdir / "app.js").unlink()

    monkeypatch.setattr(publish, "_mirror", lossy)
    count = _remote_count(remote)
    with pytest.raises(DeployError, match=r"committed tree differs from the site \(1 paths\)"):
        publish_site(_site(tmp_path), target, env=ENABLED)
    assert _remote_count(remote) == count


def _publish_once(remote: Path, target: Path, tmp_path: Path) -> dict[str, str]:
    publish_site(_site(tmp_path), target, env=ENABLED)
    tree = _remote_tree(remote)
    assert "booth-review/index.html" in tree
    return tree


@pytest.mark.parametrize("shape", ["missing", "empty", "unmarked", "marker_only", "no_index"])
def test_incomplete_site_refused_and_live_subdir_kept(
    shape: str, remote: Path, target: Path, tmp_path: Path
) -> None:
    # CR-01: a missing or empty site must never mirror as "delete booth-review/".
    live = _publish_once(remote, target, tmp_path)
    count = _remote_count(remote)
    bad = tmp_path / "bad-site"
    if shape != "missing":
        bad.mkdir()
    if shape == "unmarked":
        (bad / "index.html").write_text("<html>", encoding="utf-8")
    if shape in ("marker_only", "no_index"):
        (bad / ".booth-review-site").write_text("", encoding="utf-8")
    if shape == "no_index":
        (bad / "app.js").write_text("x=1", encoding="utf-8")
    with pytest.raises(DeployError, match="deploy refused"):
        publish_site(bad, target, env=ENABLED)
    assert _remote_count(remote) == count
    assert _remote_tree(remote) == live


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


def test_no_key_configured_refuses_deploy(
    remote: Path,
    target: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # WR-01: with no CFBD key (env empty, no .env in the cwd) the key check
    # cannot run, so the deploy must refuse instead of publishing unchecked.
    monkeypatch.delenv("CFBD_API_KEY", raising=False)
    assert not (tmp_path / ".env").exists()
    count = _remote_count(remote)
    with pytest.raises(DeployError, match="key check could not run"):
        publish_site(_site(tmp_path), target, env=ENABLED)
    assert _remote_count(remote) == count

    monkeypatch.setenv("PUBLISH_ENABLED", "true")
    code = main(["deploy", "--site", str(_site(tmp_path)), "--target", str(target)])
    assert code == 3
    assert "key check could not run" in capsys.readouterr().err
    assert _remote_count(remote) == count


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


# -- 999.5 D-20: carry the live nfl-data.json when the staged site lacks it --------------

NFL_ENABLED = {"PUBLISH_ENABLED": "true", "NFL_SITE_ENABLED": "true"}
NFL_FIXTURE = Path(__file__).parent / "fixtures" / "contract" / "nfl-data.fixture.json"
# The synthetic contract fixture's canonical bytes: a valid live file.
LIVE_NFL = load_nfl_site_payload(NFL_FIXTURE)[1].decode("utf-8")
# A token only the NFL fixture holds, so it can stand in for a leaked key.
NFL_ONLY_TOKEN = "franchises"
# IN-04: the carry reads the built index.html's sports meta, not the flag.
SWITCH_INDEX = '<html><meta name="booth-review-sports" content="cfb,nfl">'


def _publish_live_nfl(target: Path, tmp_path: Path, body: str = LIVE_NFL) -> None:
    """Put booth-review/nfl-data.json on the remote via a first (flag-on) deploy."""
    site = _site(
        tmp_path,
        {"index.html": "<html>", "app.js": "x=1", "nfl-data.json": body},
    )
    assert publish_site(site, target, env=NFL_ENABLED, sleep=lambda _s: None).status == "published"


def _live_nfl_bytes(remote: Path) -> bytes:
    return subprocess.run(
        ["git", "-C", str(remote), "show", "master:booth-review/nfl-data.json"],
        check=True,
        capture_output=True,
    ).stdout


def test_flag_on_missing_staged_nfl_file_keeps_the_live_one_byte_identical(
    remote: Path, target: Path, tmp_path: Path
) -> None:
    _publish_live_nfl(target, tmp_path)
    seed = {p: b for p, b in _remote_tree(remote).items() if not p.startswith("booth-review/")}
    site = _site(tmp_path, {"index.html": SWITCH_INDEX, "app.js": "x=2"})
    result = publish_site(site, target, env=NFL_ENABLED, sleep=lambda _s: None)
    assert result.status == "published"
    assert result.nfl_carried is True
    assert _live_nfl_bytes(remote) == LIVE_NFL.encode()
    tree = _remote_tree(remote)
    assert sorted(p for p in tree if p.startswith("booth-review/")) == [
        "booth-review/app.js",
        "booth-review/index.html",
        "booth-review/nfl-data.json",
    ]
    assert {p: b for p, b in tree.items() if not p.startswith("booth-review/")} == seed
    assert result.outside_before == result.outside_after


def test_flag_on_no_live_nfl_file_ships_none(remote: Path, target: Path, tmp_path: Path) -> None:
    result = publish_site(_site(tmp_path), target, env=NFL_ENABLED, sleep=lambda _s: None)
    assert result.status == "published"
    assert result.nfl_carried is False
    assert "booth-review/nfl-data.json" not in _remote_tree(remote)


def test_staged_nfl_file_wins_over_the_live_one(remote: Path, target: Path, tmp_path: Path) -> None:
    _publish_live_nfl(target, tmp_path)
    site = _site(tmp_path, {"index.html": "<html>", "nfl-data.json": '{"fresh":"nfl"}'})
    result = publish_site(site, target, env=NFL_ENABLED, sleep=lambda _s: None)
    assert result.nfl_carried is False
    assert _live_nfl_bytes(remote) == b'{"fresh":"nfl"}'


def _cfb_only_deployed(remote: Path) -> None:
    tree = _remote_tree(remote)
    assert sorted(p for p in tree if p.startswith("booth-review/")) == [
        "booth-review/app.js",
        "booth-review/index.html",
    ]


def test_carried_live_file_with_key_is_dropped_and_cfb_still_deploys(
    remote: Path,
    target: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # WR-02 / D-20: a key hit in the carried file drops only that file; it never
    # deletes the CFB site or stops the CFB deploy.
    _publish_live_nfl(target, tmp_path)
    assert NFL_ONLY_TOKEN in LIVE_NFL
    monkeypatch.setenv("CFBD_API_KEY", NFL_ONLY_TOKEN)
    site = _site(tmp_path, {"index.html": SWITCH_INDEX, "app.js": "x=2"})
    result = publish_site(site, target, env=NFL_ENABLED, sleep=lambda _s: None)
    assert result.status == "published"
    assert result.nfl_carried is False
    assert result.nfl_not_carried == "key_check_failed"
    assert (site / "index.html").is_file()
    assert not (site / "nfl-data.json").exists()
    _cfb_only_deployed(remote)
    for blob in _remote_tree(remote).values():
        assert NFL_ONLY_TOKEN.encode() not in _git(remote, "cat-file", "blob", blob).encode()
    assert not list(tmp_path.glob(".*nfl-keycheck-*"))
    assert NFL_ONLY_TOKEN not in capsys.readouterr().out


def test_live_file_failing_the_contract_is_dropped_and_cfb_still_deploys(
    remote: Path, target: Path, tmp_path: Path
) -> None:
    # WR-02: an old-contract live file is never republished next to new JS.
    _publish_live_nfl(target, tmp_path, body='{"live":"nfl"}')
    site = _site(tmp_path, {"index.html": SWITCH_INDEX, "app.js": "x=2"})
    result = publish_site(site, target, env=NFL_ENABLED, sleep=lambda _s: None)
    assert result.status == "published"
    assert (result.nfl_carried, result.nfl_not_carried) == (False, "invalid")
    _cfb_only_deployed(remote)


@pytest.mark.parametrize("error", [DeployError("x"), RuntimeError("x"), OSError("x")])
def test_a_failed_live_read_is_dropped_and_cfb_still_deploys(
    remote: Path,
    target: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    _publish_live_nfl(target, tmp_path)

    def boom(*args: object, **kwargs: object) -> bytes:
        raise error

    monkeypatch.setattr(publish, "_read_live_nfl_blob", boom)
    site = _site(tmp_path, {"index.html": SWITCH_INDEX, "app.js": "x=2"})
    result = publish_site(site, target, env=NFL_ENABLED, sleep=lambda _s: None)
    assert result.status == "published"
    assert (result.nfl_carried, result.nfl_not_carried) == (False, "read_failed")
    _cfb_only_deployed(remote)


def test_carry_stages_outside_the_site_and_a_failed_stage_leaves_nothing(
    remote: Path, target: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # WR-02: the temp file never sits inside the deployed dir, even when the
    # final rename fails.
    _publish_live_nfl(target, tmp_path)
    site = _site(tmp_path, {"index.html": SWITCH_INDEX, "app.js": "x=2"})
    seen: list[Path] = []
    real_replace = Path.replace

    def failing_replace(self: Path, dest: Path) -> Path:  # type: ignore[override]
        if self.name == "nfl-data.json":
            seen.append(self)
            raise OSError("simulated kill")
        return real_replace(self, dest)

    monkeypatch.setattr(Path, "replace", failing_replace)
    result = publish_site(site, target, env=NFL_ENABLED, sleep=lambda _s: None)
    monkeypatch.undo()
    assert result.status == "published"
    assert (result.nfl_carried, result.nfl_not_carried) == (False, "stage_failed")
    assert seen and all(site.resolve() not in p.resolve().parents for p in seen)
    assert sorted(p.name for p in site.iterdir()) == [".booth-review-site", "app.js", "index.html"]
    assert not list(tmp_path.glob(".site.nfl-carry-*"))
    _cfb_only_deployed(remote)


def test_cli_deploy_prints_a_count_only_line_when_the_live_copy_is_dropped(
    remote: Path,
    target: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _publish_live_nfl(target, tmp_path, body='{"live":"nfl"}')
    monkeypatch.setenv("PUBLISH_ENABLED", "true")
    monkeypatch.setenv("NFL_SITE_ENABLED", "true")
    site = _site(tmp_path, {"index.html": SWITCH_INDEX, "app.js": "x=2"})
    assert main(["deploy", "--site", str(site), "--target", str(target)]) == 0
    out = capsys.readouterr().out
    assert "nfl data: live copy not carried (invalid); CFB deployed without it" in out
    assert "live" not in out.replace("live copy", "")


def test_flag_off_publish_is_unchanged_and_removes_a_live_nfl_file(
    remote: Path, target: Path, tmp_path: Path
) -> None:
    _publish_live_nfl(target, tmp_path)
    result = publish_site(_site(tmp_path), target, env=ENABLED, sleep=lambda _s: None)
    assert result.status == "published"
    assert result.nfl_carried is False
    assert "booth-review/nfl-data.json" not in _remote_tree(remote)
    # Only the exact string "true" turns the carry on.
    _publish_live_nfl(target, tmp_path)
    off = {"PUBLISH_ENABLED": "true", "NFL_SITE_ENABLED": "TRUE"}
    publish_site(_site(tmp_path), target, env=off, sleep=lambda _s: None)
    assert "booth-review/nfl-data.json" not in _remote_tree(remote)


def test_deploy_publishes_both_data_files_under_booth_review_only(
    remote: Path, target: Path, tmp_path: Path
) -> None:
    seed = _remote_tree(remote)
    site = _site(
        tmp_path,
        {
            "index.html": "<html>",
            "site-data.json": '{"cfb":1}',
            "nfl-data.json": '{"nfl":1}',
        },
    )
    publish_site(site, target, env=NFL_ENABLED, sleep=lambda _s: None)
    tree = _remote_tree(remote)
    for path, blob in seed.items():
        assert tree[path] == blob
    assert sorted(p for p in tree if p not in seed) == [
        "booth-review/index.html",
        "booth-review/nfl-data.json",
        "booth-review/site-data.json",
    ]


def test_key_in_nfl_data_refuses_deploy(remote: Path, target: Path, tmp_path: Path) -> None:
    site = _site(tmp_path, {"index.html": "<html>", "nfl-data.json": f'{{"k":"{CANARY}"}}'})
    count = _remote_count(remote)
    with pytest.raises(KeyLeakError):
        publish_site(site, target, env=NFL_ENABLED, sleep=lambda _s: None)
    assert _remote_count(remote) == count


def test_a_live_nfl_symlink_is_never_carried(remote: Path, target: Path, tmp_path: Path) -> None:
    seed = _clone(remote, tmp_path / "seed2")
    (seed / "booth-review").mkdir()
    (seed / "booth-review" / "nfl-data.json").symlink_to("../index.html")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-q", "-m", "symlinked nfl file")
    _git(seed, "push", "-q", "origin", "HEAD:refs/heads/master")
    count = _remote_count(remote)
    # Nothing is carried from a symlink; the existing staged-path guard then
    # refuses the mirror that would delete a symlink from the target.
    with pytest.raises(DeployError):
        publish_site(
            _site(tmp_path, {"index.html": SWITCH_INDEX}),
            target,
            env=NFL_ENABLED,
            sleep=lambda _s: None,
        )
    assert not (tmp_path / "site" / "nfl-data.json").exists()
    assert _remote_count(remote) == count


# -- iter-2 WR-02 / IN-04: the carry follows the built sports meta ---------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
CFB_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "contract" / "site-data.fixture.json"


def _tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _assembled(out: Path, **kw: object) -> Path:
    assemble_site(
        source=CFB_FIXTURE,
        out_dir=out,
        site_src=REPO_ROOT / "site",
        docs=REPO_ROOT / "docs",
        **kw,  # type: ignore[arg-type]
    )
    return out


def _publish(site: Path, target: Path, env: dict[str, str]) -> DeployResult:
    return publish_site(
        site,
        target,
        env=env,
        sleep=lambda _s: None,
        site_src=REPO_ROOT / "site",
        docs=REPO_ROOT / "docs",
    )


def test_a_switch_site_missing_its_file_carries_the_live_one_whatever_the_flag(
    remote: Path, target: Path, tmp_path: Path
) -> None:
    # IN-04: the built sports meta decides the carry, not the env flag.
    _publish_live_nfl(target, tmp_path)
    site = _site(tmp_path, {"index.html": SWITCH_INDEX, "app.js": "x=2"})
    result = publish_site(site, target, env=ENABLED, sleep=lambda _s: None)
    assert (result.nfl_carried, result.nfl_switched_on) == (True, False)
    assert _live_nfl_bytes(remote) == LIVE_NFL.encode()


def test_a_site_without_the_switch_never_gets_an_orphan_file(
    remote: Path, target: Path, tmp_path: Path
) -> None:
    # IN-04: no sports meta at all (or the flag off on a CFB-only site) means
    # no page loads nfl-data.json, so none is carried, flag on or not.
    _publish_live_nfl(target, tmp_path)
    for env in (NFL_ENABLED, ENABLED):
        site = _site(tmp_path, {"index.html": "<html>2", "app.js": "x=2"})
        result = publish_site(site, target, env=env, sleep=lambda _s: None)
        assert (result.nfl_carried, result.nfl_not_carried) == (False, None)
        _cfb_only_deployed(remote)
        _publish_live_nfl(target, tmp_path)
    site = _assembled(tmp_path / "cfb-only")
    before = _tree(site)
    result = _publish(site, target, ENABLED)
    assert (result.nfl_carried, result.nfl_switched_on) == (False, False)
    assert _tree(site) == before
    assert "booth-review/nfl-data.json" not in _remote_tree(remote)


def test_no_nfl_file_this_run_but_a_valid_live_one_is_carried_into_a_switch_site(
    remote: Path, target: Path, tmp_path: Path
) -> None:
    # Iter-2 WR-02 / D-20: neither a vault carry-over nor a fresh file, so the
    # job built a CFB-only site; the last good live file keeps NFL reachable.
    _publish_live_nfl(target, tmp_path)
    seed = {p: b for p, b in _remote_tree(remote).items() if not p.startswith("booth-review/")}
    site = _assembled(tmp_path / "cfb-only")
    assert 'content="cfb"' in (site / "index.html").read_text(encoding="utf-8")
    result = _publish(site, target, NFL_ENABLED)
    assert result.status == "published"
    assert (result.nfl_carried, result.nfl_switched_on, result.nfl_not_carried) == (
        True,
        True,
        None,
    )
    assert _live_nfl_bytes(remote) == LIVE_NFL.encode()
    direct = _assembled(
        tmp_path / "direct", nfl=True, nfl_payload=load_nfl_site_payload(NFL_FIXTURE)
    )
    assert _tree(site) == _tree(direct)
    tree = _remote_tree(remote)
    assert "booth-review/sports/nfl/index.js" in tree
    index = _git(remote, "show", "master:booth-review/index.html")
    assert '<meta name="booth-review-sports" content="cfb,nfl">' in index
    assert 'id="sport-switch"' in index
    assert {p: b for p, b in tree.items() if not p.startswith("booth-review/")} == seed
    assert not list(tmp_path.glob(".cfb-only.*"))


@pytest.mark.parametrize(
    ("body", "reason"),
    [('{"live":"nfl"}', "invalid"), (None, "switch_failed")],
)
def test_a_failed_switch_on_leaves_the_cfb_site_whole_and_deploys_it(
    remote: Path,
    target: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    body: str | None,
    reason: str,
) -> None:
    _publish_live_nfl(target, tmp_path, body=body or LIVE_NFL)
    if body is None:

        def boom(**kwargs: object) -> object:
            raise RuntimeError("private detail")

        monkeypatch.setattr(publish, "add_sport_to_site", boom)
    site = _assembled(tmp_path / "cfb-only")
    before = _tree(site)
    result = _publish(site, target, NFL_ENABLED)
    assert result.status == "published"
    assert (result.nfl_carried, result.nfl_switched_on, result.nfl_not_carried) == (
        False,
        False,
        reason,
    )
    assert _tree(site) == before
    tree = _remote_tree(remote)
    assert "booth-review/nfl-data.json" not in tree
    assert "booth-review/sports/nfl/index.js" not in tree


def test_cli_deploy_says_when_it_turned_the_switch_on(
    remote: Path,
    target: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _publish_live_nfl(target, tmp_path)
    monkeypatch.setenv("PUBLISH_ENABLED", "true")
    monkeypatch.setenv("NFL_SITE_ENABLED", "true")
    monkeypatch.setenv("BOOTH_REVIEW_SITE_SRC", str(REPO_ROOT / "site"))
    monkeypatch.setenv("BOOTH_REVIEW_DOCS", str(REPO_ROOT / "docs"))
    site = _assembled(tmp_path / "cfb-only")
    assert main(["deploy", "--site", str(site), "--target", str(target)]) == 0
    assert "nfl data: carried live copy and turned the NFL switch on" in capsys.readouterr().out


# -- 09-12 D-16 / Pitfall 9: carry the live mlb-data.json ---------------------------------

MLB_ENABLED = {"PUBLISH_ENABLED": "true", "MLB_SITE_ENABLED": "true"}
BOTH_ENABLED = {**NFL_ENABLED, **MLB_ENABLED}
MLB_FIXTURE = Path(__file__).parent / "fixtures" / "contract" / "mlb-data.fixture.json"
LIVE_MLB = load_mlb_site_payload(MLB_FIXTURE)[1].decode("utf-8")
SWITCH_META_MLB = '<meta name="booth-review-sports" content="cfb,mlb">'


@pytest.fixture
def mlb_src(tmp_path: Path) -> Path:
    """site/ plus a placeholder sports/mlb module (the real one lands in a later plan)."""
    dest = tmp_path / "_mlb_src"
    shutil.copytree(REPO_ROOT / "site", dest, ignore=shutil.ignore_patterns("node_modules"))
    (dest / "sports" / "mlb").mkdir(exist_ok=True)
    (dest / "sports" / "mlb" / "index.js").write_text("// synthetic placeholder\n", "utf-8")
    return dest


def _publish_live_sport_files(target: Path, tmp_path: Path, files: dict[str, str]) -> None:
    site = _site(tmp_path, {"index.html": "<html>", "app.js": "x=1", **files})
    assert publish_site(site, target, env=ENABLED, sleep=lambda _s: None).status == "published"


def _live_mlb_bytes(remote: Path) -> bytes:
    return subprocess.run(
        ["git", "-C", str(remote), "show", "master:booth-review/mlb-data.json"],
        check=True,
        capture_output=True,
    ).stdout


def _publish_with(site: Path, target: Path, env: dict[str, str], src: Path) -> DeployResult:
    return publish_site(
        site, target, env=env, sleep=lambda _s: None, site_src=src, docs=REPO_ROOT / "docs"
    )


def test_mlb_carry_base_cfb(remote: Path, target: Path, tmp_path: Path, mlb_src: Path) -> None:
    _publish_live_sport_files(target, tmp_path, {"mlb-data.json": LIVE_MLB})
    seed = {p: b for p, b in _remote_tree(remote).items() if not p.startswith("booth-review/")}
    site = _assembled(tmp_path / "cfb-only")
    result = _publish_with(site, target, MLB_ENABLED, mlb_src)
    assert result.status == "published"
    assert (result.mlb_carried, result.mlb_switched_on, result.mlb_not_carried) == (
        True,
        True,
        None,
    )
    assert (result.nfl_carried, result.nfl_not_carried) == (False, None)
    assert _live_mlb_bytes(remote) == LIVE_MLB.encode()
    tree = _remote_tree(remote)
    assert "booth-review/sports/mlb/index.js" in tree
    assert not [p for p in tree if p.startswith("booth-review/sports/nfl/")]
    assert "booth-review/nfl-data.json" not in tree
    assert SWITCH_META_MLB in _git(remote, "show", "master:booth-review/index.html")
    assert {p: b for p, b in tree.items() if not p.startswith("booth-review/")} == seed


def test_mlb_carry_base_cfb_nfl(remote: Path, target: Path, tmp_path: Path, mlb_src: Path) -> None:
    _publish_live_sport_files(target, tmp_path, {"mlb-data.json": LIVE_MLB})
    site = _assembled(
        tmp_path / "cfb-nfl", nfl=True, nfl_payload=load_nfl_site_payload(NFL_FIXTURE)
    )
    before = _tree(site)
    result = _publish_with(site, target, MLB_ENABLED, mlb_src)
    assert (result.mlb_carried, result.mlb_switched_on) == (True, True)
    after = _tree(site)
    kept = [k for k in before if k == "nfl-data.json" or k.startswith("sports/nfl/")]
    assert "nfl-data.json" in kept
    assert all(after[k] == before[k] for k in kept)
    index = after["index.html"].decode("utf-8")
    assert '<meta name="booth-review-sports" content="cfb,nfl,mlb">' in index
    buttons = re.findall(
        r'data-sport="(\w+)"', index.split('<header id="topbar" class="site-header">')[1]
    )
    assert buttons[:3] == ["cfb", "nfl", "mlb"]
    assert _live_mlb_bytes(remote) == LIVE_MLB.encode()


def test_mlb_carry_nfl_then_mlb(remote: Path, target: Path, tmp_path: Path, mlb_src: Path) -> None:
    _publish_live_sport_files(
        target, tmp_path, {"nfl-data.json": LIVE_NFL, "mlb-data.json": LIVE_MLB}
    )
    site = _assembled(tmp_path / "cfb-only")
    result = _publish_with(site, target, BOTH_ENABLED, mlb_src)
    assert (result.nfl_carried, result.nfl_switched_on) == (True, True)
    assert (result.mlb_carried, result.mlb_switched_on) == (True, True)
    assert _live_nfl_bytes(remote) == LIVE_NFL.encode()
    assert _live_mlb_bytes(remote) == LIVE_MLB.encode()
    assert '<meta name="booth-review-sports" content="cfb,nfl,mlb">' in _git(
        remote, "show", "master:booth-review/index.html"
    )
    assert "booth-review/sports/nfl/index.js" in _remote_tree(remote)
    assert "booth-review/sports/mlb/index.js" in _remote_tree(remote)
    assert site_sports(site) == ("cfb", "nfl", "mlb")


def test_a_failed_nfl_build_keeps_the_live_nfl_view_when_the_build_lists_mlb(
    remote: Path, target: Path, tmp_path: Path
) -> None:
    # MLB on: the built site is cfb,mlb and has no nfl-data.json of its own.
    _publish_live_sport_files(target, tmp_path, {"nfl-data.json": LIVE_NFL})
    site = _assembled(
        tmp_path / "cfb-mlb", mlb=True, mlb_payload=load_mlb_site_payload(MLB_FIXTURE)
    )
    assert site_sports(site) == ("cfb", "mlb")
    result = _publish(site, target, BOTH_ENABLED)
    assert result.status == "published"
    assert (result.nfl_carried, result.nfl_switched_on, result.nfl_not_carried) == (
        True,
        True,
        None,
    )
    assert site_sports(site) == ("cfb", "nfl", "mlb")
    assert _live_nfl_bytes(remote) == LIVE_NFL.encode()
    tree = _remote_tree(remote)
    assert "booth-review/sports/nfl/index.js" in tree
    assert "booth-review/mlb-data.json" in tree
    assert '<meta name="booth-review-sports" content="cfb,nfl,mlb">' in _git(
        remote, "show", "master:booth-review/index.html"
    )


def test_mlb_flag_off_carries_nothing(
    remote: Path, target: Path, tmp_path: Path, mlb_src: Path
) -> None:
    _publish_live_sport_files(target, tmp_path, {"mlb-data.json": LIVE_MLB})
    for env in (ENABLED, {**ENABLED, "MLB_SITE_ENABLED": "TRUE"}):
        site = _assembled(tmp_path / "cfb-only")
        before = _tree(site)
        result = _publish_with(site, target, env, mlb_src)
        assert (result.mlb_carried, result.mlb_not_carried) == (False, None)
        assert _tree(site) == before
        assert "booth-review/mlb-data.json" not in _remote_tree(remote)
        _publish_live_sport_files(target, tmp_path, {"mlb-data.json": LIVE_MLB})


def test_mlb_staged_file_wins_over_the_live_one(
    remote: Path, target: Path, tmp_path: Path, mlb_src: Path
) -> None:
    _publish_live_sport_files(target, tmp_path, {"mlb-data.json": LIVE_MLB})
    site = _site(tmp_path, {"index.html": "<html>", "mlb-data.json": '{"fresh":"mlb"}'})
    result = _publish_with(site, target, MLB_ENABLED, mlb_src)
    assert result.mlb_carried is False
    assert _live_mlb_bytes(remote) == b'{"fresh":"mlb"}'


def test_mlb_invalid_live_file_is_not_carried(
    remote: Path, target: Path, tmp_path: Path, mlb_src: Path
) -> None:
    _publish_live_sport_files(target, tmp_path, {"mlb-data.json": '{"live":"mlb"}'})
    site = _assembled(tmp_path / "cfb-only")
    before = _tree(site)
    result = _publish_with(site, target, MLB_ENABLED, mlb_src)
    assert result.status == "published"
    assert (result.mlb_carried, result.mlb_not_carried) == (False, "invalid")
    assert _tree(site) == before
    assert "booth-review/mlb-data.json" not in _remote_tree(remote)


def test_mlb_live_file_with_the_key_is_not_carried(
    remote: Path,
    target: Path,
    tmp_path: Path,
    mlb_src: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _publish_live_sport_files(target, tmp_path, {"mlb-data.json": LIVE_MLB})
    token = "apple_booths"
    assert token in LIVE_MLB
    monkeypatch.setenv("CFBD_API_KEY", token)
    site = _assembled(tmp_path / "cfb-only")
    result = _publish_with(site, target, MLB_ENABLED, mlb_src)
    assert (result.mlb_carried, result.mlb_not_carried) == (False, "key_check_failed")
    assert "booth-review/mlb-data.json" not in _remote_tree(remote)
    assert token not in capsys.readouterr().out
    assert not list(tmp_path.glob(".*mlb-keycheck-*"))


@pytest.mark.parametrize("error", [DeployError("x"), OSError("x")])
def test_mlb_failed_live_read_is_count_only(
    remote: Path,
    target: Path,
    tmp_path: Path,
    mlb_src: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    def boom(*args: object, **kwargs: object) -> bytes:
        raise error

    monkeypatch.setattr(publish, "_read_live_sport_blob", boom)
    site = _assembled(tmp_path / "cfb-only")
    result = _publish_with(site, target, MLB_ENABLED, mlb_src)
    assert result.status == "published"
    assert (result.mlb_carried, result.mlb_not_carried) == (False, "read_failed")


def test_mlb_switch_failure_leaves_the_site_whole(
    remote: Path,
    target: Path,
    tmp_path: Path,
    mlb_src: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _publish_live_sport_files(target, tmp_path, {"mlb-data.json": LIVE_MLB})

    def boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("private detail")

    monkeypatch.setattr(publish, "add_sport_to_site", boom)
    site = _assembled(tmp_path / "cfb-only")
    before = _tree(site)
    result = _publish_with(site, target, MLB_ENABLED, mlb_src)
    assert (result.mlb_carried, result.mlb_not_carried) == (False, "switch_failed")
    assert _tree(site) == before


def test_cli_deploy_reports_the_mlb_carry(
    remote: Path,
    target: Path,
    tmp_path: Path,
    mlb_src: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _publish_live_sport_files(target, tmp_path, {"mlb-data.json": LIVE_MLB})
    monkeypatch.setenv("PUBLISH_ENABLED", "true")
    monkeypatch.setenv("MLB_SITE_ENABLED", "true")
    monkeypatch.setenv("BOOTH_REVIEW_SITE_SRC", str(mlb_src))
    monkeypatch.setenv("BOOTH_REVIEW_DOCS", str(REPO_ROOT / "docs"))
    site = _assembled(tmp_path / "cfb-only")
    assert main(["deploy", "--site", str(site), "--target", str(target)]) == 0
    assert "mlb data: carried live copy and turned the MLB switch on" in capsys.readouterr().out
