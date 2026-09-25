"""Offline tests for `booth-review import 506`.

Every test drives `cli.main(argv)` against a real (throwaway, tmp_path-rooted)
git vault via the `git_vault`/`patched_client` fixtures, or (for tests that
need `ImportResult`'s fields directly) calls `Sports506Importer.run` against
the lighter-weight `vault_paths` fixture. `mock_transport_factory` is
configured with zero responses in every test here, so any accidental network
request raises immediately -- proving the importer never sends one (AGENTS.md:
506's automated-client block is never worked around, only imported around).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from booth_review.cli import main
from booth_review.errors import FrozenSeasonError
from booth_review.sources.sports506.collector import WEEK_LABELS
from booth_review.sources.sports506.importer import Sports506Importer, identify_page
from booth_review.transport.cache import RawCache
from booth_review.transport.client import PoliteClient

FIXTURES = Path(__file__).parent / "fixtures" / "sports506"
_WEEK_TEMPLATE = (FIXTURES / "week_synthetic.html").read_bytes()
_BOWLS_TEMPLATE = (FIXTURES / "bowls_synthetic.html").read_bytes()


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
    """Plain content: mentions `season`, no canonical link or title.

    Used only where a test needs a page that identify_page can locate solely
    by filename (the lowest-priority fallback), or where a test doesn't
    exercise the importer's D-03 smoke check at all.
    """
    return f"<html><body>506 Sports {season} week {label} synthetic page</body></html>".encode()


def _importable_page(season: int, label: str, *, nav_labels: list[str] | None = None) -> bytes:
    """A synthetic 506 page for (season, label) that both `identify_page` and
    `smoke_check` accept: the canonical link and title carry (season, label),
    substituted into the shared week/bowls fixtures (D-07: no real 506
    content), whose schedule rows already clear the D-03 crew floor.

    `nav_labels`, when given, adds a `<nav>` block of `yr={season}&wk={label}`
    anchors so `discover_season_weeks` can read an expected week list back
    out of this page.
    """
    template = _BOWLS_TEMPLATE if label == "B" else _WEEK_TEMPLATE
    template_label = "B" if label == "B" else "5"
    text = template.decode("utf-8")
    text = text.replace(f"yr=2025&wk={template_label}", f"yr={season}&wk={label}")
    text = text.replace(f"Week {template_label}, 2025", f"Week {label}, {season}")
    if nav_labels is not None:
        anchors = "".join(
            f'<a href="ncaaf.php?yr={season}&wk={nav_label}">wk {nav_label}</a>'
            for nav_label in nav_labels
        )
        text = text.replace("<body>", f"<body><nav>{anchors}</nav>", 1)
    return text.encode("utf-8")


# `_real_shaped_page` used to be a minimal canonical+title-only page (no
# schedule rows). With the D-03 smoke check now run on every import, it must
# also parse to a plausible week -- so it's built the same way as
# `_importable_page`, keeping its own name for the content-identification
# tests below that were written against it.
_real_shaped_page = _importable_page


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


def _importer_for(vault_paths, mock_transport_factory) -> Sports506Importer:
    """A Sports506Importer wired to `vault_paths` with a mock transport that
    sends nothing (every test here is offline).
    """
    handle = mock_transport_factory({})
    client = PoliteClient(transport=handle.transport, clock=lambda: 0.0, sleep=lambda _s: None)
    cache = RawCache(vault_paths, client)
    return Sports506Importer(cache, vault_paths)


# -- happy path -------------------------------------------------------------------------


def test_import_506_imports_present_weeks_writes_cache_manifest_and_commits(
    git_vault, mock_transport_factory, patched_client, tmp_path
) -> None:
    paths = git_vault
    handle = mock_transport_factory({})
    patched_client(handle)

    incoming = tmp_path / "incoming"
    for label in ("0", "1", "B"):
        _write_incoming(incoming, 2025, label, _importable_page(2025, label))

    exit_code = main(["import", "506", "--season", "2025", "--from", str(incoming)])

    assert exit_code == 4  # 15 weeks still missing
    assert handle.requests == []

    assert (paths.raw / "sports506" / "2025" / "wk-00.html").read_bytes() == _importable_page(
        2025, "0"
    )
    assert (paths.raw / "sports506" / "2025" / "wk-01.html").read_bytes() == _importable_page(
        2025, "1"
    )
    assert (paths.raw / "sports506" / "2025" / "wk-B.html").read_bytes() == _importable_page(
        2025, "B"
    )

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
        _write_incoming(incoming, 2025, label, _importable_page(2025, label))

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


def test_import_506_smoke_check_failure_skips_without_writing_or_manifest_line(
    git_vault, mock_transport_factory, patched_client, tmp_path, capsys
) -> None:
    """A page that mentions the season and looks like HTML but has no
    schedule rows (D-03) is rejected, not written, and leaves no manifest
    line -- distinct from the pre-existing HTML/season validation above.
    """
    paths = git_vault
    handle = mock_transport_factory({})
    patched_client(handle)

    incoming = tmp_path / "incoming"
    _write_incoming(
        incoming,
        2025,
        "5",
        b"<html><body>2025 week 5, saved before the schedule posted</body></html>",
    )

    exit_code = main(["import", "506", "--season", "2025", "--from", str(incoming), "--no-commit"])

    assert exit_code == 4
    assert not (paths.raw / "sports506" / "2025" / "wk-05.html").exists()
    assert _manifest_lines(paths) == []
    out = capsys.readouterr().out
    assert "skipped wk-5: parse failed:" in out


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
    _write_incoming(incoming, 2025, "1", _importable_page(2025, "1"))

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
    _write_incoming(incoming, 2025, "1", _importable_page(2025, "1"))

    exit_code = main(["import", "506", "--season", "2025", "--from", str(incoming), "--force"])

    assert exit_code == 4  # other 17 weeks still missing
    assert cached_path.read_bytes() == _importable_page(2025, "1")


# -- zero-padded filenames and --no-commit -------------------------------------------------


def test_import_506_accepts_zero_padded_filename(
    git_vault, mock_transport_factory, patched_client, tmp_path
) -> None:
    paths = git_vault
    handle = mock_transport_factory({})
    patched_client(handle)

    incoming = tmp_path / "incoming"
    incoming.mkdir(parents=True, exist_ok=True)
    (incoming / "2025-wk00.html").write_bytes(_importable_page(2025, "0"))

    exit_code = main(["import", "506", "--season", "2025", "--from", str(incoming)])

    assert exit_code == 4
    assert (paths.raw / "sports506" / "2025" / "wk-00.html").read_bytes() == _importable_page(
        2025, "0"
    )


def test_import_506_no_commit_flag_writes_files_but_does_not_commit(
    git_vault, mock_transport_factory, patched_client, tmp_path
) -> None:
    paths = git_vault
    handle = mock_transport_factory({})
    patched_client(handle)

    incoming = tmp_path / "incoming"
    _write_incoming(incoming, 2025, "0", _importable_page(2025, "0"))

    remote = paths.vault.parent / "remote.git"
    log_count = _remote_log_count(remote)

    exit_code = main(["import", "506", "--season", "2025", "--from", str(incoming), "--no-commit"])

    assert exit_code == 4
    assert (paths.raw / "sports506" / "2025" / "wk-00.html").is_file()
    assert _remote_log_count(remote) == log_count


# -- identifying pages by content ------------------------------------------------------


def test_identify_page_prefers_canonical_then_title_then_filename(tmp_path) -> None:
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


# -- D-05: expected week list from the season's own nav ------------------------------------


def test_import_506_derives_expected_weeks_from_seasons_own_nav(
    vault_paths, mock_transport_factory, tmp_path
) -> None:
    importer = _importer_for(vault_paths, mock_transport_factory)
    nav_labels = [str(n) for n in range(12)]  # 2020-style: an irregular, 12-week season

    incoming = tmp_path / "incoming"
    _write_incoming(incoming, 2020, "0", _importable_page(2020, "0", nav_labels=nav_labels))

    result = importer.run(2020, incoming_dir=incoming)

    assert result.expected_source == "nav"
    assert result.expected == nav_labels
    assert result.imported == ["0"]
    assert len(result.missing) == 11  # missing out of 12, not a fixed 18
    assert set(result.missing) == set(nav_labels) - {"0"}


def test_import_506_reports_unsupported_nav_labels_separately(
    vault_paths, mock_transport_factory, tmp_path
) -> None:
    importer = _importer_for(vault_paths, mock_transport_factory)

    incoming = tmp_path / "incoming"
    _write_incoming(incoming, 2025, "0", _importable_page(2025, "0", nav_labels=["0", "1", "17"]))

    result = importer.run(2025, incoming_dir=incoming)

    assert result.expected == ["0", "1"]
    assert result.unsupported_labels == ["17"]
    assert result.has_problems is True


def test_import_506_falls_back_to_default_week_labels_when_no_nav_found(
    vault_paths, mock_transport_factory, tmp_path
) -> None:
    importer = _importer_for(vault_paths, mock_transport_factory)

    incoming = tmp_path / "incoming"
    _write_incoming(incoming, 2025, "0", _importable_page(2025, "0"))  # no nav block

    result = importer.run(2025, incoming_dir=incoming)

    assert result.expected_source == "default"
    assert result.expected == WEEK_LABELS
    assert len(result.missing) == 17


# -- D-06/D-07: frozen seasons refuse every import ------------------------------------------


def test_import_506_frozen_season_raises_and_writes_nothing(
    vault_paths, mock_transport_factory, tmp_path
) -> None:
    vault_paths.frozen.write_text(
        json.dumps({"sports506": [2025], "ratingsref": [], "cfbd": []}), encoding="utf-8"
    )
    importer = _importer_for(vault_paths, mock_transport_factory)

    incoming = tmp_path / "incoming"
    _write_incoming(incoming, 2025, "0", _importable_page(2025, "0"))

    with pytest.raises(FrozenSeasonError):
        importer.run(2025, incoming_dir=incoming)

    assert not (vault_paths.raw / "sports506" / "2025").exists()
    assert _manifest_lines(vault_paths) == []


def test_import_506_cli_frozen_season_returns_3_and_commits_nothing(
    git_vault, mock_transport_factory, patched_client, tmp_path, capsys
) -> None:
    paths = git_vault
    remote = paths.vault.parent / "remote.git"
    paths.frozen.write_text(
        json.dumps({"sports506": [2025], "ratingsref": [], "cfbd": []}), encoding="utf-8"
    )
    log_count = _remote_log_count(remote)
    handle = mock_transport_factory({})
    patched_client(handle)

    incoming = tmp_path / "incoming"
    _write_incoming(incoming, 2025, "0", _importable_page(2025, "0"))

    exit_code = main(["import", "506", "--season", "2025", "--from", str(incoming)])

    assert exit_code == 3
    err = capsys.readouterr().err
    assert "FrozenSeasonError" in err
    assert _remote_log_count(remote) == log_count


# -- CLI print format and D-04 path-scoped concurrency-safe commits ------------------------


def test_import_506_cli_prints_nav_derived_present_missing_with_source_note(
    git_vault, mock_transport_factory, patched_client, tmp_path, capsys
) -> None:
    handle = mock_transport_factory({})
    patched_client(handle)

    nav_labels = [str(n) for n in range(12)]  # a 2020-style, 12-week irregular season
    incoming = tmp_path / "incoming"
    _write_incoming(incoming, 2020, "0", _importable_page(2020, "0", nav_labels=nav_labels))

    exit_code = main(["import", "506", "--season", "2020", "--from", str(incoming)])

    assert exit_code == 4  # 11 weeks still missing
    out = capsys.readouterr().out
    assert "season 2020: present 1/12, missing 11/12 (weeks from nav)" in out


def test_import_506_cli_falls_back_to_default_weeks_note(
    git_vault, mock_transport_factory, patched_client, tmp_path, capsys
) -> None:
    handle = mock_transport_factory({})
    patched_client(handle)

    incoming = tmp_path / "incoming"
    _write_incoming(incoming, 2025, "0", _importable_page(2025, "0"))  # no nav block

    exit_code = main(["import", "506", "--season", "2025", "--from", str(incoming)])

    assert exit_code == 4
    out = capsys.readouterr().out
    assert "season 2025: present 1/18, missing 17/18 (default 18 weeks)" in out


def test_import_506_commit_is_path_scoped_leaves_concurrent_untracked_file_untouched(
    git_vault, mock_transport_factory, patched_client, tmp_path
) -> None:
    """D-04/T-02-02: import 506 commits only raw/sports506/<season> and
    ledger/requests.jsonl -- an untracked file elsewhere in the vault
    (simulating a concurrent RR refresh's in-progress output) stays untracked.
    """
    paths = git_vault
    handle = mock_transport_factory({})
    patched_client(handle)

    concurrent_file = paths.raw / "ratingsref" / "telecast" / "2019" / "concurrent.json"
    concurrent_file.parent.mkdir(parents=True, exist_ok=True)
    concurrent_file.write_text('{"in_progress": true}', encoding="utf-8")

    incoming = tmp_path / "incoming"
    _write_incoming(incoming, 2025, "0", _importable_page(2025, "0"))

    exit_code = main(["import", "506", "--season", "2025", "--from", str(incoming)])

    assert exit_code == 4  # 17 weeks still missing
    status = subprocess.run(
        ["git", "-C", str(paths.vault), "status", "--porcelain", "--", "raw/ratingsref"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    # git collapses an entirely-untracked directory to its own path; either
    # form proves the file was never staged by the scoped import commit.
    assert status.strip() != ""
    assert concurrent_file.is_file()
