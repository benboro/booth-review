"""Offline tests for `booth-review import 506`.

Every test drives `cli.main(argv)` against a real (throwaway, tmp_path-rooted)
git vault via the `git_vault`/`patched_client` fixtures. `mock_transport_factory`
is configured with zero responses in every test here, so any accidental network
request raises immediately -- proving the importer never sends one (AGENTS.md:
506's automated-client block is never worked around, only imported around).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from booth_review.cli import main
from booth_review.sources.sports506.collector import WEEK_LABELS


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


def _page(season: int, label: str) -> bytes:
    return f"<html><body>506 Sports {season} week {label} synthetic page</body></html>".encode()


def _challenge_page() -> bytes:
    return (
        b"<html><head><title>Just a moment...</title></head>"
        b"<body>Checking your browser before accessing 506sports.com. cf-chl-bypass</body></html>"
    )


def _write_incoming(incoming_dir: Path, season: int, label: str, content: bytes) -> None:
    incoming_dir.mkdir(parents=True, exist_ok=True)
    (incoming_dir / f"{season}-wk{label}.html").write_bytes(content)


def _manifest_lines(paths) -> list[dict]:
    if not paths.manifest.is_file():
        return []
    return [json.loads(line) for line in paths.manifest.read_text(encoding="utf-8").splitlines()]


# -- happy path -------------------------------------------------------------------------


def test_import_506_imports_present_weeks_writes_cache_manifest_and_commits(
    git_vault, mock_transport_factory, patched_client, tmp_path
) -> None:
    paths = git_vault
    handle = mock_transport_factory({})
    patched_client(handle)

    incoming = tmp_path / "incoming"
    for label in ("0", "1", "B"):
        _write_incoming(incoming, 2025, label, _page(2025, label))

    exit_code = main(["import", "506", "--season", "2025", "--from", str(incoming)])

    assert exit_code == 4  # 15 weeks still missing
    assert handle.requests == []

    assert (paths.raw / "sports506" / "2025" / "wk-00.html").read_bytes() == _page(2025, "0")
    assert (paths.raw / "sports506" / "2025" / "wk-01.html").read_bytes() == _page(2025, "1")
    assert (paths.raw / "sports506" / "2025" / "wk-B.html").read_bytes() == _page(2025, "B")

    lines = _manifest_lines(paths)
    imported_urls = {
        "https://506sports.com/ncaaf.php?yr=2025&wk=0",
        "https://506sports.com/ncaaf.php?yr=2025&wk=1",
        "https://506sports.com/ncaaf.php?yr=2025&wk=B",
    }
    manual_lines = [line for line in lines if line.get("origin") == "manual"]
    assert {line["url"] for line in manual_lines} == imported_urls
    for line in manual_lines:
        assert line["status"] == 200
        assert line["kind"] == "page"
        assert line["source"] == "sports506"
        assert line["season"] == 2025
        assert line["path"] is not None
        assert line["sha256"] is not None
        assert line["bytes"] > 0

    # incoming files are never deleted
    assert (incoming / "2025-wk0.html").is_file()
    assert (incoming / "2025-wk1.html").is_file()
    assert (incoming / "2025-wkB.html").is_file()

    remote = paths.vault.parent / "remote.git"
    assert _remote_head_subject(remote) == "import: sports506 2025 (imported 3, skipped 0)"


def test_import_506_full_season_returns_0_and_rerun_is_a_noop(
    git_vault, mock_transport_factory, patched_client, tmp_path
) -> None:
    paths = git_vault
    handle = mock_transport_factory({})
    patched_client(handle)

    incoming = tmp_path / "incoming"
    for label in WEEK_LABELS:
        _write_incoming(incoming, 2025, label, _page(2025, label))

    exit_code = main(["import", "506", "--season", "2025", "--from", str(incoming)])
    assert exit_code == 0
    assert len(list((paths.raw / "sports506" / "2025").glob("*.html"))) == 18

    remote = paths.vault.parent / "remote.git"
    assert _remote_head_subject(remote) == "import: sports506 2025 (imported 18, skipped 0)"
    log_count = _remote_log_count(remote)

    handle2 = mock_transport_factory({})
    patched_client(handle2)
    exit_code2 = main(["import", "506", "--season", "2025", "--from", str(incoming)])

    assert exit_code2 == 0
    assert handle2.requests == []
    assert _remote_log_count(remote) == log_count  # nothing new to commit


# -- validation ---------------------------------------------------------------------------


def test_import_506_rejects_cloudflare_challenge_page(
    git_vault, mock_transport_factory, patched_client, tmp_path, capsys
) -> None:
    paths = git_vault
    handle = mock_transport_factory({})
    patched_client(handle)

    incoming = tmp_path / "incoming"
    _write_incoming(incoming, 2025, "2", _challenge_page())

    exit_code = main(["import", "506", "--season", "2025", "--from", str(incoming)])

    assert exit_code == 4
    assert not (paths.raw / "sports506" / "2025" / "wk-02.html").exists()
    out = capsys.readouterr().out
    assert "Cloudflare" in out
    assert "skipped wk-2" in out


def test_import_506_rejects_empty_and_non_html_and_wrong_season_files(
    git_vault, mock_transport_factory, patched_client, tmp_path
) -> None:
    paths = git_vault
    handle = mock_transport_factory({})
    patched_client(handle)

    incoming = tmp_path / "incoming"
    incoming.mkdir(parents=True, exist_ok=True)
    (incoming / "2025-wk3.html").write_bytes(b"")
    (incoming / "2025-wk4.html").write_bytes(b"not html at all, just text")
    (incoming / "2025-wk5.html").write_bytes(b"<html>this is season 2024's page</html>")

    exit_code = main(["import", "506", "--season", "2025", "--from", str(incoming)])

    assert exit_code == 4
    for name in ("wk-03", "wk-04", "wk-05"):
        assert not (paths.raw / "sports506" / "2025" / f"{name}.html").exists()


# -- overwrite protection -----------------------------------------------------------------


def test_import_506_never_overwrites_existing_cache_without_force(
    git_vault, mock_transport_factory, patched_client, tmp_path
) -> None:
    paths = git_vault
    handle = mock_transport_factory({})
    patched_client(handle)

    cached_path = paths.raw / "sports506" / "2025" / "wk-01.html"
    cached_path.parent.mkdir(parents=True, exist_ok=True)
    cached_path.write_bytes(b"<html>already cached from a real fetch</html>")

    incoming = tmp_path / "incoming"
    _write_incoming(incoming, 2025, "1", _page(2025, "1"))

    exit_code = main(["import", "506", "--season", "2025", "--from", str(incoming)])

    assert exit_code == 4
    assert cached_path.read_bytes() == b"<html>already cached from a real fetch</html>"


def test_import_506_force_overwrites_existing_cache(
    git_vault, mock_transport_factory, patched_client, tmp_path
) -> None:
    paths = git_vault
    handle = mock_transport_factory({})
    patched_client(handle)

    cached_path = paths.raw / "sports506" / "2025" / "wk-01.html"
    cached_path.parent.mkdir(parents=True, exist_ok=True)
    cached_path.write_bytes(b"<html>stale</html>")

    incoming = tmp_path / "incoming"
    _write_incoming(incoming, 2025, "1", _page(2025, "1"))

    exit_code = main(["import", "506", "--season", "2025", "--from", str(incoming), "--force"])

    assert exit_code == 4  # other 17 weeks still missing
    assert cached_path.read_bytes() == _page(2025, "1")


# -- zero-padded filenames and --no-commit -------------------------------------------------


def test_import_506_accepts_zero_padded_filename(
    git_vault, mock_transport_factory, patched_client, tmp_path
) -> None:
    paths = git_vault
    handle = mock_transport_factory({})
    patched_client(handle)

    incoming = tmp_path / "incoming"
    incoming.mkdir(parents=True, exist_ok=True)
    (incoming / "2025-wk00.html").write_bytes(_page(2025, "0"))

    exit_code = main(["import", "506", "--season", "2025", "--from", str(incoming)])

    assert exit_code == 4
    assert (paths.raw / "sports506" / "2025" / "wk-00.html").read_bytes() == _page(2025, "0")


def test_import_506_no_commit_flag_writes_files_but_does_not_commit(
    git_vault, mock_transport_factory, patched_client, tmp_path
) -> None:
    paths = git_vault
    handle = mock_transport_factory({})
    patched_client(handle)

    incoming = tmp_path / "incoming"
    _write_incoming(incoming, 2025, "0", _page(2025, "0"))

    remote = paths.vault.parent / "remote.git"
    log_count = _remote_log_count(remote)

    exit_code = main(["import", "506", "--season", "2025", "--from", str(incoming), "--no-commit"])

    assert exit_code == 4
    assert (paths.raw / "sports506" / "2025" / "wk-00.html").is_file()
    assert _remote_log_count(remote) == log_count


# -- identifying pages by content ------------------------------------------------------


def _real_shaped_page(season: int, label: str) -> bytes:
    # Synthetic, but shaped like a saved 506 week page: canonical link plus title.
    return (
        f"<html><head><title>506 Sports - College Football: Week {label}, {season}</title>"
        f'<link rel="canonical" href="https://506sports.com/ncaaf.php?yr={season}&wk={label}" />'
        f"</head><body>synthetic schedule {season}</body></html>"
    ).encode()


def test_identify_page_prefers_canonical_then_title_then_filename(tmp_path) -> None:
    from booth_review.sources.sports506.importer import identify_page

    default_name = tmp_path / "506 Sports - College Football_ Week 12, 2025.html"
    assert identify_page(default_name, _real_shaped_page(2025, "12")) == (2025, "12")
    title_only = b"<html><title>506 Sports - College Football: Week B, 2024</title></html>"
    assert identify_page(tmp_path / "x.html", title_only) == (2024, "B")
    assert identify_page(tmp_path / "2023-wk07.html", _page(2023, "7")) == (2023, "7")
    assert identify_page(tmp_path / "other.html", b"<html>not 506</html>") is None


def test_import_506_uses_page_content_not_browser_filenames(
    git_vault, mock_transport_factory, patched_client, tmp_path
) -> None:
    paths = git_vault
    handle = mock_transport_factory({})
    patched_client(handle)

    incoming = tmp_path / "Downloads"
    incoming.mkdir()
    for label in WEEK_LABELS:
        name = f"506 Sports - College Football_ Week {label}, 2025.html"
        (incoming / name).write_bytes(_real_shaped_page(2025, label))
    (incoming / "2024 page.html").write_bytes(_real_shaped_page(2024, "3"))  # other season
    (incoming / "unrelated.html").write_bytes(b"<html>a receipt</html>")

    exit_code = main(["import", "506", "--season", "2025", "--from", str(incoming)])

    assert exit_code == 0
    assert handle.requests == []
    assert (paths.raw / "sports506/2025/wk-12.html").read_bytes() == _real_shaped_page(2025, "12")
    assert not (paths.raw / "sports506/2024").exists()


def test_import_506_content_overrides_a_mislabeled_filename(
    git_vault, mock_transport_factory, patched_client, tmp_path
) -> None:
    paths = git_vault
    patched_client(mock_transport_factory({}))

    incoming = tmp_path / "incoming"
    incoming.mkdir()
    (incoming / "2025-wk3.html").write_bytes(_real_shaped_page(2025, "4"))

    main(["import", "506", "--season", "2025", "--from", str(incoming), "--no-commit"])

    assert (paths.raw / "sports506/2025/wk-04.html").is_file()
    assert not (paths.raw / "sports506/2025/wk-03.html").exists()


def test_import_506_rejects_two_different_files_for_one_week(
    git_vault, mock_transport_factory, patched_client, tmp_path, capsys
) -> None:
    paths = git_vault
    patched_client(mock_transport_factory({}))

    incoming = tmp_path / "incoming"
    incoming.mkdir()
    (incoming / "a.html").write_bytes(_real_shaped_page(2025, "5"))
    (incoming / "b.html").write_bytes(_real_shaped_page(2025, "5") + b"<!-- resaved -->")

    main(["import", "506", "--season", "2025", "--from", str(incoming), "--no-commit"])

    assert not (paths.raw / "sports506/2025/wk-05.html").exists()
    assert "skipped wk-5: two different files claim this week" in capsys.readouterr().out
