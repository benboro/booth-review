"""Offline tests for `booth-review import espnpr` (04.19 D-12), on synthetic pages only.

ESPN Press Room is hand-save only (Disney Terms of Use ban automated access), so
these tests also prove there is no fetch path: no collect subcommand, no host
policy, no client in the importer, and zero requests on a mock transport.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from booth_review.cli import build_parser, main
from booth_review.config import HOST_POLICIES, HOST_SOURCE, DataPaths
from booth_review.sources.espnpr import importer as importer_module
from booth_review.sources.espnpr.importer import (
    DEFAULT_INCOMING_DIR,
    EspnPrImporter,
    examine,
    identify_page,
    sanitize_slug,
    season_of_release,
)

FIXTURES = Path(__file__).parent / "fixtures" / "espnpr"
COMMENTATORS = (FIXTURES / "commentators_synthetic.html").read_text(encoding="utf-8")
RELEASE = (FIXTURES / "release_synthetic.html").read_text(encoding="utf-8")
RATINGS = (FIXTURES / "ratings_synthetic.html").read_text(encoding="utf-8")

SEASON_URL = "https://espnpressroom.com/2026-27-espn-college-football-commentators-schedule/"
RELEASE_SLUG = "synthetic-week-6-college-football-coverage-across-espn-networks"
RATINGS_SLUG = "synthetic-saturday-viewership-grows-on-espn-networks"

SAVED = 1_790_000_000
SAVED_ISO = datetime.fromtimestamp(SAVED, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

LISTING = """<!DOCTYPE html><html><head><title>College Football - ESPN Press Room</title>
<link rel="canonical" href="https://espnpressroom.com/press-release-category/college-football/" />
<link rel="next" href="https://espnpressroom.com/press-release-category/college-football/page/2/" />
<meta property="og:title" content="Synthetic First Listed Item" />
</head><body class="archive tax-press-release-category term-college-football">
<h1 class="title">Press Release Category: <span>College Football</span></h1>
<ul class="bricks-layout-wrapper"><li class="bricks-layout-item">
<h3><a href="https://espnpressroom.com/press-release/synthetic-item/">Synthetic item</a></h3>
<span>October 1, 2026</span><p>Synthetic excerpt averaged 5.2 million viewers.</p></li></ul>
</body></html>"""

CHALLENGE = """<!DOCTYPE html><html><head><title>Just a moment...</title></head>
<body><div id="cf-chl-widget">Checking your browser</div></body></html>"""


def _save(folder: Path, name: str, text: str, mtime: int = SAVED) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(text, encoding="utf-8")
    os.utime(path, (mtime, mtime))
    return path


def _manifest(paths: DataPaths) -> list[dict]:
    if not paths.manifest.is_file():
        return []
    return [json.loads(x) for x in paths.manifest.read_text(encoding="utf-8").splitlines()]


def _written(paths: DataPaths) -> list[Path]:
    root = paths.raw / "espnpr"
    return sorted(p for p in root.rglob("*") if p.is_file()) if root.exists() else []


def _remote(paths: DataPaths) -> list[str]:
    return ["git", "--git-dir", str(paths.vault.parent / "remote.git")]


def _subjects(paths: DataPaths, count: int) -> list[str]:
    out = subprocess.run(
        [*_remote(paths), "log", f"-{count}", "--format=%s"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return out.splitlines()


def _touched(paths: DataPaths, rev: str) -> list[str]:
    return subprocess.run(
        [*_remote(paths), "show", "--name-only", "--format=", rev],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()


# -- identification -------------------------------------------------------------------


def test_identifies_three_kinds_by_content() -> None:
    page = identify_page(COMMENTATORS)
    assert page is not None
    assert (page.kind, page.season, page.key, page.week_label) == ("commentators", 2026, "7", "7")
    assert page.canonical_url == SEASON_URL
    assert page.rel == "commentators/wk-7.html"
    assert page.published is not None and page.published.date().isoformat() == "2026-10-12"

    release = identify_page(RELEASE)
    assert release is not None
    assert (release.kind, release.season, release.key) == ("release", 2022, RELEASE_SLUG)
    assert release.week_label == "6"
    assert release.rel == f"releases/{RELEASE_SLUG}.html"

    ratings = identify_page(RATINGS)
    assert ratings is not None
    assert (ratings.kind, ratings.season, ratings.key) == ("ratings", 2022, RATINGS_SLUG)
    assert ratings.rel == f"ratings/{RATINGS_SLUG}.html"


def test_release_season_uses_published_not_modified_date() -> None:
    january = RATINGS.replace("2022-11-01T13:00:00-04:00", "2023-01-10T13:00:00-05:00")
    page = identify_page(january)
    assert page is not None and page.season == 2022  # the CFP final runs into January
    assert season_of_release(datetime(2024, 8, 24, tzinfo=UTC)) == 2024
    assert season_of_release(datetime(2025, 1, 21, tzinfo=UTC)) == 2024


def test_ratings_without_a_table_are_recognized_from_viewer_wording() -> None:
    prose_only = re.sub(r"<table>.*?</table>", "", RATINGS, flags=re.DOTALL)
    page = identify_page(prose_only)
    assert page is not None and page.kind == "ratings"


def test_listing_and_unrelated_pages_are_not_data_pages() -> None:
    listing = examine(LISTING.encode())
    assert listing.status == "listing"
    assert listing.reason is not None and "not a data page" in listing.reason
    no_canonical = examine(b"<!DOCTYPE html><html><body><p>unrelated</p></body></html>")
    assert no_canonical.status == "unrecognized"
    other_release = re.sub(
        r'<div class="brxe-post-content">.*?</div>',
        '<div class="brxe-post-content"><p>Synthetic hire announcement.</p></div>',
        RELEASE,
        flags=re.DOTALL,
    )
    assert examine(other_release.encode()).status == "unrecognized"


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("", "empty file"),
        (CHALLENGE, "looks like a challenge or error page"),
        ("WEEK 7 plain text, not a saved page", "does not look like HTML"),
        (
            COMMENTATORS.replace("https://espnpressroom.com/", "https://espnpressroom.example/"),
            "canonical link is not on espnpressroom.com",
        ),
        (
            COMMENTATORS.replace("https://espnpressroom.com/", "http://espnpressroom.com/"),
            "canonical link is not on espnpressroom.com",
        ),
        (COMMENTATORS.replace("2026-27-espn", "2026-29-espn"), "malformed"),
        (COMMENTATORS.replace("single-post", "single-other"), "body class"),
        (RELEASE.replace("single-press-release", "single-post"), "body class"),
        (COMMENTATORS.replace("<strong>WEEK 7</strong>", "<strong>Soon</strong>"), "no WEEK"),
        (
            RELEASE.replace("2022-10-03T14:00:00-04:00", "not-a-date"),
            "no published date",
        ),
    ],
)
def test_invalid_pages_are_rejected_with_a_reason(text: str, reason: str) -> None:
    examined = examine(text.encode())
    assert examined.status == "invalid"
    assert examined.reason is not None and reason in examined.reason


def test_slugs_are_sanitized_to_a_safe_charset() -> None:
    assert sanitize_slug("Week%206_Recap..%2F..%2Fetc") == "week-6-recap-etc"
    assert sanitize_slug("..") == ""
    tricky = RELEASE.replace(
        f"/press-release/{RELEASE_SLUG}/", "/press-release/Week%206%2F..%2F..%2Fescape/"
    )
    page = identify_page(tricky)
    assert page is not None
    assert re.fullmatch(r"[a-z0-9-]+", page.key)
    assert ".." not in page.rel and page.rel.startswith("releases/")


# -- import ---------------------------------------------------------------------------


def test_imports_each_kind_with_manual_provenance(git_vault, tmp_path) -> None:
    paths = git_vault
    folder = tmp_path / "in"
    # File names are browser defaults or arbitrary: identity comes from content.
    _save(folder, "Saved Page (3).html", COMMENTATORS)
    _save(folder, "release.htm", RELEASE)
    _save(folder, "zz.html", RATINGS)
    result = EspnPrImporter(paths).run(incoming_dir=folder)

    assert not result.has_problems
    assert result.seasons() == [2022, 2026]
    assert result.counts(2026) == {"imported": 1, "skipped": 0}
    assert result.counts(2022) == {"imported": 2, "skipped": 0}
    root = paths.raw / "espnpr"
    assert (root / "2026" / "commentators" / "wk-7.html").read_text() == COMMENTATORS
    assert (root / "2022" / "releases" / f"{RELEASE_SLUG}.html").read_text() == RELEASE
    assert (root / "2022" / "ratings" / f"{RATINGS_SLUG}.html").read_text() == RATINGS

    entries = {e["path"]: e for e in _manifest(paths)}
    assert set(entries) == {
        "espnpr/2026/commentators/wk-7.html",
        f"espnpr/2022/releases/{RELEASE_SLUG}.html",
        f"espnpr/2022/ratings/{RATINGS_SLUG}.html",
    }
    week = entries["espnpr/2026/commentators/wk-7.html"]
    assert week["url"] == week["final_url"] == SEASON_URL
    for entry in entries.values():
        assert entry["origin"] == "manual"
        assert entry["saved_at"] == SAVED_ISO
        assert entry["source"] == "espnpr"
        assert entry["kind"] == "page"
        assert entry["url"].startswith("https://espnpressroom.com/")
        assert len(entry["sha256"]) == 64


def test_invalid_and_off_host_files_are_skipped(git_vault, tmp_path) -> None:
    folder = tmp_path / "in"
    offhost = COMMENTATORS.replace("https://espnpressroom.com/", "https://mirror.example.com/")
    _save(folder, "2026-27-espn-college-football-commentators-schedule.html", offhost)
    _save(folder, "challenge.html", CHALLENGE)
    _save(folder, "empty.html", "")
    _save(folder, "listing.html", LISTING)
    _save(folder, "notes.html", "<!DOCTYPE html><html><body>unrelated</body></html>")
    result = EspnPrImporter(git_vault).run(incoming_dir=folder)

    assert result.imported == []
    assert sorted(item.reason for item in result.skipped_invalid) == [
        "canonical link is not on espnpressroom.com",
        "empty file",
        "looks like a challenge or error page",
    ]
    assert result.listings == 1
    assert result.unrecognized == 1
    assert result.has_problems
    assert _written(git_vault) == []


def test_listing_alone_is_skipped_without_failing(git_vault, tmp_path) -> None:
    folder = tmp_path / "in"
    _save(folder, "listing.html", LISTING)
    _save(folder, "week.html", COMMENTATORS)
    result = EspnPrImporter(git_vault).run(incoming_dir=folder)
    assert result.listings == 1
    assert len(result.imported) == 1
    assert not result.has_problems


def test_two_files_claiming_one_week_are_both_rejected(git_vault, tmp_path) -> None:
    folder = tmp_path / "in"
    _save(folder, "a.html", COMMENTATORS, mtime=SAVED)
    newer = COMMENTATORS.replace("Noon&nbsp;", "12:30 p.m.&nbsp;")
    _save(folder, "b.html", newer, mtime=SAVED + 3600)
    _save(folder, "c.html", COMMENTATORS, mtime=SAVED - 60)  # identical copy collapses
    importer = EspnPrImporter(git_vault)

    refused = importer.run(incoming_dir=folder)
    assert refused.imported == []
    assert [item.reason for item in refused.skipped_invalid] == [
        "two different files claim this page"
    ] * 2
    assert all(item.season == 2026 for item in refused.skipped_invalid)
    assert refused.has_problems
    assert _written(git_vault) == []

    forced = importer.run(incoming_dir=folder, force=True)
    assert not forced.has_problems
    assert forced.superseded == 1
    dest = git_vault.raw / "espnpr" / "2026" / "commentators" / "wk-7.html"
    assert dest.read_text() == newer
    newest_iso = datetime.fromtimestamp(SAVED + 3600, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert _manifest(git_vault)[-1]["saved_at"] == newest_iso


def test_reimport_skips_identical_and_changed_needs_force(git_vault, tmp_path) -> None:
    folder = tmp_path / "in"
    _save(folder, "week.html", COMMENTATORS)
    importer = EspnPrImporter(git_vault)
    assert len(importer.run(incoming_dir=folder).imported) == 1

    again = importer.run(incoming_dir=folder)
    assert again.imported == []
    assert len(again.skipped_existing) == 1
    assert not again.has_problems
    assert len(_manifest(git_vault)) == 1

    resaved = COMMENTATORS.replace("ESPN+&nbsp;", "ESPNU&nbsp;")
    _save(folder, "week.html", resaved, mtime=SAVED + 86400)
    refused = importer.run(incoming_dir=folder)
    assert refused.has_problems
    assert len(refused.changed_without_force) == 1
    dest = git_vault.raw / "espnpr" / "2026" / "commentators" / "wk-7.html"
    assert dest.read_text() == COMMENTATORS

    forced = importer.run(incoming_dir=folder, force=True)
    assert not forced.has_problems
    assert dest.read_text() == resaved
    assert len(_manifest(git_vault)) == 2


def test_frozen_season_is_skipped_but_others_import(git_vault, tmp_path) -> None:
    git_vault.frozen.write_text(json.dumps({"espnpr": [2022]}), encoding="utf-8")
    folder = tmp_path / "in"
    _save(folder, "r.html", RELEASE)
    _save(folder, "w.html", COMMENTATORS)
    result = EspnPrImporter(git_vault).run(incoming_dir=folder)
    assert [ref.season for ref in result.imported] == [2026]
    assert [(i.reason, i.season) for i in result.skipped_invalid] == [("season is frozen", 2022)]
    assert result.has_problems


def test_missing_folder_is_a_problem(git_vault, tmp_path) -> None:
    result = EspnPrImporter(git_vault).run(incoming_dir=tmp_path / "absent")
    assert result.problems == ["incoming folder not found"]
    assert result.has_problems


def test_default_folder_is_data_incoming_espnpr(git_vault, tmp_path) -> None:
    assert Path("data/incoming/espnpr") == DEFAULT_INCOMING_DIR
    _save(tmp_path / DEFAULT_INCOMING_DIR, "w.html", COMMENTATORS)  # git_vault chdirs to tmp_path
    result = EspnPrImporter(git_vault).run()
    assert len(result.imported) == 1


# -- no fetch path --------------------------------------------------------------------


def test_no_fetch_path_exists() -> None:
    assert not any("espnpressroom" in host for host in HOST_POLICIES)
    assert not any("espnpressroom" in host for host in HOST_SOURCE)
    source = Path(importer_module.__file__).read_text(encoding="utf-8")
    for needle in ("PoliteClient", "httpx", "RawCache", "urlopen", "requests."):
        assert needle not in source
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["collect", "espnpr"])
    assert exc.value.code == 2


def test_import_help_exits_zero(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["import", "espnpr", "--help"])
    assert exc.value.code == 0
    assert "--force" in capsys.readouterr().out


# -- CLI ------------------------------------------------------------------------------


def test_cli_commits_per_season_count_only_and_sends_nothing(
    git_vault, mock_transport_factory, patched_client, tmp_path, capsys
) -> None:
    paths = git_vault
    handle = mock_transport_factory({})
    patched_client(handle)
    folder = tmp_path / "in"
    _save(folder, "w.html", COMMENTATORS)
    _save(folder, "r.html", RELEASE)
    _save(folder, "v.html", RATINGS)
    _save(folder, "l.html", LISTING)

    assert main(["import", "espnpr", "--from", str(folder)]) == 0
    assert handle.requests == []

    newest, older = _subjects(paths, 2)
    assert older == "import: espnpr 2022 (imported 2, skipped 0)"
    assert newest == "import: espnpr 2026 (imported 1, skipped 0)"
    first = _touched(paths, "HEAD~1")
    second = _touched(paths, "HEAD")
    assert all(t.startswith("raw/espnpr/2022/") or t == "ledger/requests.jsonl" for t in first)
    assert all(t.startswith("raw/espnpr/2026/") or t == "ledger/requests.jsonl" for t in second)
    assert "raw/espnpr/2026/commentators/wk-7.html" in second

    out = capsys.readouterr().out
    assert "espnpr 2026: imported 1 (commentators 1, release 0, ratings 0)" in out
    assert "category listing, not a data page" in out
    for secret in ("Silverlake", "Avery Quill", "5.2", RELEASE_SLUG, "w.html"):
        assert secret not in out


def test_cli_problems_exit_4_and_no_commit_writes_nothing_to_remote(
    git_vault, mock_transport_factory, patched_client, tmp_path, capsys
) -> None:
    paths = git_vault
    patched_client(mock_transport_factory({}))
    before = _subjects(paths, 1)
    folder = tmp_path / "in"
    _save(folder, "a.html", COMMENTATORS)
    _save(folder, "b.html", COMMENTATORS.replace("Noon&nbsp;", "1 p.m.&nbsp;"))
    _save(folder, "c.html", CHALLENGE)

    assert main(["import", "espnpr", "--from", str(folder), "--no-commit"]) == 4
    out = capsys.readouterr().out
    assert "skipped 2: two different files claim this page" in out
    assert "skipped 1: looks like a challenge or error page" in out
    assert _written(paths) == []
    assert _subjects(paths, 1) == before
