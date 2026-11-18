"""Offline tests for `booth-review import aa`, on synthetic pages only.

The import takes hand-saved Awful Announcing weekly announcing-schedule posts
(college football and NFL) into the vault. It sends no request: these tests run
with no transport at all and check the importer never builds a client.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from nfl_join_helpers import sched_row, schedule_csv

from booth_review.cli import main
from booth_review.config import DataPaths
from booth_review.nfl.layout import NFLVERSE_SCHEDULES_PATH
from booth_review.sources.aa import importer as importer_module
from booth_review.sources.aa.crews import hand_imported
from booth_review.sources.aa.feed import FeedWatchState, save_feed_state, week_key
from booth_review.sources.aa.importer import AaImporter, examine, nfl_crews_cache_path
from booth_review.transport.cache import Manifest

FIXTURES = Path(__file__).parent / "fixtures" / "aa"
CFB_POST = (FIXTURES / "schedule_synthetic.html").read_text(encoding="utf-8")
CFB_URL = "https://awfulannouncing.com/college-football/invented-week-10-announcing-schedule.html"
CFB_DEST = "aa/crews/2026/wk-10.html"
NFL_DEST = "nfl/aa/crews/2026/wk-09.html"
SAVED = int(datetime(2026, 11, 6, 12, 0, tzinfo=UTC).timestamp())

NFL_POST = """<!DOCTYPE html>
<!-- Synthetic: invented teams, networks and people in the NFL schedule-post structure. -->
<html lang="en-US"><head><meta charset="UTF-8" />
<title>Your 2026 NFL Week 9 announcing schedule</title>
<link rel="canonical" href="https://awfulannouncing.com/nfl/week-9-announcing-schedule-2026.html" />
<meta property="article:published_time" content="2026-11-04T14:45:00+00:00" />
<meta property="article:modified_time" content="2026-11-06T19:04:41+00:00" />
</head><body class="single single-post"><article><div class="entry-content">
<p>Here is the invented NFL schedule for the week.</p>
<h3>Thursday, November 5</h3>
<p><strong>Hill Moles at Pine Elks (8:15 p.m., Net1): </strong>Ann Archer (play-by-play),
Bo Baker (analyst), Cy Cole (reporter)</p>
<h3>Sunday, November 8</h3>
<p><strong>River Owls at Lake Foxes (1 p.m., Net2): </strong>Dee Dunn (play-by-play),
Eli Ely (analyst)</p>
<p><strong>Sand Crabs at Moss Bears (4:25 p.m., Net3): </strong>Fay Fox (play-by-play),
Gus Gray (analyst)</p>
</div></article></body></html>"""

WEEK11_POST = CFB_POST.replace("Week 10", "Week 11").replace("week-10", "week-11")

NEWS_POST = """<!DOCTYPE html><html><head><title>Invented announcer to fill in this week</title>
<link rel="canonical" href="https://awfulannouncing.com/college-football/invented-fill-in.html" />
</head><body><div class="entry-content"><p>Invented prose.</p></div></body></html>"""


def _save(folder: Path, name: str, text: str, mtime: int = SAVED) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(text, encoding="utf-8")
    os.utime(path, (mtime, mtime))
    return path


def _cfb_games(paths: DataPaths) -> None:
    """Week 9 on Oct 31, week 10 on Nov 7, week 11 on Nov 14."""
    rows = [(1, 9, "2026-10-31T16:00:00Z"), (2, 10, "2026-11-07T17:00:00Z")]
    rows.append((3, 11, "2026-11-14T17:00:00Z"))
    games = [
        {
            "id": gid,
            "season": 2026,
            "week": week,
            "seasonType": "regular",
            "startDate": start,
            "homeTeam": "Home",
            "awayTeam": "Away",
        }
        for gid, week, start in rows
    ]
    target = paths.raw / "cfbd" / "games" / "2026.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(json.dumps(games).encode())


def _nfl_schedule(paths: DataPaths) -> None:
    """Week 9: Thursday Nov 5 and Sunday Nov 8; week 10 the next Sunday."""
    rows = [
        sched_row("g9a", 9, "2026-11-05", "AAA", "BBB", season="2026", weekday="Thursday"),
        sched_row("g9b", 9, "2026-11-08", "CCC", "DDD", season="2026"),
        sched_row("g10", 10, "2026-11-15", "EEE", "FFF", season="2026"),
    ]
    target = paths.raw / NFLVERSE_SCHEDULES_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(schedule_csv(rows))


def _manifest(paths: DataPaths) -> list[dict[str, Any]]:
    if not paths.manifest.is_file():
        return []
    lines = paths.manifest.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


@pytest.fixture
def setup(git_vault: DataPaths, tmp_path: Path) -> tuple[DataPaths, Path]:
    _cfb_games(git_vault)
    _nfl_schedule(git_vault)
    return git_vault, tmp_path / "incoming"


# -- identification ---------------------------------------------------------------------


def test_examine_identifies_cfb_and_nfl_posts() -> None:
    cfb = examine(CFB_POST.encode())
    assert cfb.status == "page" and cfb.page is not None
    assert (cfb.page.league, cfb.page.season, cfb.page.week) == ("cfb", 2026, "10")
    assert cfb.page.cache_path == CFB_DEST
    nfl = examine(NFL_POST.encode())
    assert nfl.status == "page" and nfl.page is not None
    assert (nfl.page.league, nfl.page.season, nfl.page.week) == ("nfl", 2026, "9")
    assert nfl.page.cache_path == NFL_DEST == nfl_crews_cache_path(2026, "9")


def test_news_post_and_other_html_are_unrecognized() -> None:
    assert examine(NEWS_POST.encode()).status == "unrecognized"
    assert examine(b"<html><head><title>x</title></head></html>").status == "unrecognized"


def test_other_season_is_refused() -> None:
    page = NFL_POST.replace("Your 2026 NFL", "Your 2025 NFL").replace("schedule-2026", "schedule")
    examined = examine(page.encode())
    assert examined.status == "invalid" and "2026" in (examined.reason or "")


def test_post_without_week_number_is_refused() -> None:
    page = NFL_POST.replace("Week 9 ", "").replace("week-9-", "")
    assert examine(page.encode()).reason == "post names no week number"


def test_unparseable_post_is_refused() -> None:
    page = NFL_POST.replace('class="entry-content"', 'class="other"')
    assert examine(page.encode()).reason == "post does not parse as a crews schedule"


def test_importer_has_no_client() -> None:
    source = Path(importer_module.__file__).read_text(encoding="utf-8")
    for banned in ("PoliteClient", "httpx", "build_runtime", "transport.client"):
        assert banned not in source


# -- import -----------------------------------------------------------------------------


def test_imports_both_leagues_with_manual_manifest_lines(setup) -> None:
    paths, incoming = setup
    _save(incoming, "cfb.html", CFB_POST)
    _save(incoming, "nfl.html", NFL_POST)
    _save(incoming, "news.html", NEWS_POST)
    result = AaImporter(paths).run(incoming_dir=incoming)
    assert [(r.league, r.week) for r in result.imported] == [("cfb", "10"), ("nfl", "9")]
    assert result.unrecognized == 1 and not result.has_problems
    assert (paths.raw / CFB_DEST).read_text(encoding="utf-8") == CFB_POST
    assert (paths.raw / NFL_DEST).read_text(encoding="utf-8") == NFL_POST
    lines = {line["path"]: line for line in _manifest(paths)}
    cfb = lines[CFB_DEST]
    assert cfb["origin"] == "manual" and cfb["source"] == "aa" and cfb["url"] == CFB_URL
    assert cfb["etag"] is None and cfb["last_modified"] is None
    assert cfb["saved_at"] == datetime.fromtimestamp(SAVED, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert hand_imported(paths, CFB_DEST) and hand_imported(paths, NFL_DEST)


def test_second_run_skips_identical_copy(setup) -> None:
    paths, incoming = setup
    _save(incoming, "cfb.html", CFB_POST)
    AaImporter(paths).run(incoming_dir=incoming)
    again = AaImporter(paths).run(incoming_dir=incoming)
    assert again.imported == [] and len(again.skipped_existing) == 1
    assert len(_manifest(paths)) == 1


def test_dates_outside_the_titled_week_are_refused(setup) -> None:
    paths, incoming = setup
    _save(incoming, "cfb.html", WEEK11_POST)
    result = AaImporter(paths).run(incoming_dir=incoming)
    assert result.imported == []
    assert [s.reason for s in result.skipped_invalid] == [
        "game dates do not match the week in the title"
    ]


def test_missing_schedule_is_refused(git_vault: DataPaths, tmp_path: Path) -> None:
    incoming = tmp_path / "incoming"
    _save(incoming, "nfl.html", NFL_POST)
    result = AaImporter(git_vault).run(incoming_dir=incoming)
    assert [s.reason for s in result.skipped_invalid] == [
        "no nflverse schedule for the season in the vault"
    ]


def test_feed_watch_link_for_another_post_is_refused(setup) -> None:
    paths, incoming = setup
    save_feed_state(
        paths,
        FeedWatchState(
            None,
            None,
            None,
            None,
            None,
            {week_key(2026, "10"): "https://awfulannouncing.com/college-football/other.html"},
            [],
        ),
    )
    _save(incoming, "cfb.html", CFB_POST)
    result = AaImporter(paths).run(incoming_dir=incoming)
    assert result.imported == []
    assert "different post" in result.skipped_invalid[0].reason


def test_two_different_saves_of_one_week(setup) -> None:
    paths, incoming = setup
    _save(incoming, "a.html", NFL_POST, mtime=SAVED)
    later = NFL_POST.replace("Gus Gray", "Hal Hill")
    _save(incoming, "b.html", later, mtime=SAVED + 60)
    result = AaImporter(paths).run(incoming_dir=incoming)
    assert result.imported == [] and len(result.skipped_invalid) == 2
    forced = AaImporter(paths).run(incoming_dir=incoming, force=True)
    assert len(forced.imported) == 1 and forced.superseded == 1
    assert (paths.raw / NFL_DEST).read_text(encoding="utf-8") == later


def _fetched_copy(paths: DataPaths, html: str) -> None:
    """A copy as the scripted fetch writes it: an HTTP 200 line with an ETag."""
    dest = paths.raw / CFB_DEST
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(html, encoding="utf-8")
    line = {
        "url": CFB_URL,
        "source": "aa",
        "season": 2026,
        "kind": "page",
        "fetched_at": "2026-11-06T13:00:00Z",
        "status": 200,
        "etag": '"abc"',
        "last_modified": None,
        "sha256": "x",
        "path": CFB_DEST,
        "bytes": len(html),
        "final_url": CFB_URL,
    }
    with paths.manifest.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line) + "\n")


def test_newer_fetched_copy_is_left_alone_quietly(setup) -> None:
    paths, incoming = setup
    newer = CFB_POST.replace("2026-11-05T18:30:00", "2026-11-06T18:30:00").replace(
        "Gus Gray", "Hal Hill"
    )
    _fetched_copy(paths, newer)
    _save(incoming, "cfb.html", CFB_POST)
    result = AaImporter(paths).run(incoming_dir=incoming)
    assert result.imported == [] and len(result.vault_newer) == 1
    assert not result.has_problems
    assert not hand_imported(paths, CFB_DEST)


def test_newer_save_over_older_copy_needs_force(setup) -> None:
    paths, incoming = setup
    _fetched_copy(paths, CFB_POST)
    newer = CFB_POST.replace("2026-11-05T18:30:00", "2026-11-06T18:30:00").replace(
        "Gus Gray", "Hal Hill"
    )
    _save(incoming, "cfb.html", newer)
    result = AaImporter(paths).run(incoming_dir=incoming)
    assert len(result.changed_without_force) == 1 and result.has_problems
    forced = AaImporter(paths).run(incoming_dir=incoming, force=True)
    assert len(forced.imported) == 1
    assert hand_imported(paths, CFB_DEST)
    # The job copy's ETag stays, so the Friday/Saturday re-checks can still send it.
    kept = Manifest(paths.manifest).latest_validators(CFB_URL)
    assert kept is not None and kept.etag == '"abc"'


def test_uppercase_extension_is_read(setup) -> None:
    paths, incoming = setup
    _save(incoming, "NFL.HTML", NFL_POST)
    result = AaImporter(paths).run(incoming_dir=incoming)
    assert [(r.league, r.week) for r in result.imported] == [("nfl", "9")]


def test_frozen_season_is_refused(setup) -> None:
    paths, incoming = setup
    paths.frozen.write_text(json.dumps({"aa": [2026]}), encoding="utf-8")
    _save(incoming, "nfl.html", NFL_POST)
    result = AaImporter(paths).run(incoming_dir=incoming)
    assert [s.reason for s in result.skipped_invalid] == ["season is frozen"]


# -- CLI --------------------------------------------------------------------------------


def test_cli_imports_and_commits_per_league(setup, monkeypatch, capsys) -> None:
    _paths, incoming = setup
    calls: list[tuple[str, list[str]]] = []

    def fake(self: Any, message: str, *, paths: list[str] | None = None, push: bool = True) -> bool:
        calls.append((message, list(paths or [])))
        return True

    monkeypatch.setattr("booth_review.vault.VaultRepo.commit_batch", fake)
    _save(incoming, "cfb.html", CFB_POST)
    _save(incoming, "nfl.html", NFL_POST)
    assert main(["import", "aa", "--from", str(incoming)]) == 0
    out = capsys.readouterr().out
    assert "aa cfb 2026: imported 1 (weeks 10)" in out
    assert "aa nfl 2026: imported 1 (weeks 9)" in out
    assert "Ann Archer" not in out
    assert calls == [
        (
            "import: aa cfb-2026 (imported 1, skipped 0)",
            ["raw/aa/crews/2026", "ledger/requests.jsonl"],
        ),
        (
            "import: aa nfl-2026 (imported 1, skipped 0)",
            ["raw/nfl/aa/crews/2026", "ledger/requests.jsonl"],
        ),
    ]
    assert main(["import", "aa", "--from", str(incoming)]) == 0
    assert len(calls) == 2  # nothing new, no commit


def test_cli_problem_exits_4(setup, capsys) -> None:
    _paths, incoming = setup
    _save(incoming, "cfb.html", WEEK11_POST)
    assert main(["import", "aa", "--from", str(incoming), "--no-commit"]) == 4
    assert "game dates do not match" in capsys.readouterr().out


def test_cli_missing_folder(git_vault, tmp_path, capsys) -> None:
    assert main(["import", "aa", "--from", str(tmp_path / "nope"), "--no-commit"]) == 4
    assert "incoming folder not found" in capsys.readouterr().out
