"""ESPN Press Room backup crews in the real build (04.19 D-13..D-15): a
hand-saved weekly release in the vault fills a crew-less telecast, a booth on
a 506 crew writes a disagreement row, the site credits the page, the 506
freshness stamp ignores the backup crew, and the D-15 gap list holds only the
ESPN family's remaining gaps. Synthetic data only: the synthetic build vault's
Example Cable Network is put in the ESPN family (`disney`) here.
"""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from test_cli_build import _seed_build_raw

from booth_review.build.crew_backup import (
    ESPNPR_BACKFILL_GAP_COLUMNS,
    REVIEW_CREW_BACKUP_DISAGREEMENT_COLUMNS,
)
from booth_review.build.pipeline import BuildOutcome, run_build
from booth_review.cli import main
from booth_review.config import DataPaths

_REFERENCE_FIXTURES = Path(__file__).parent / "fixtures" / "reference"
_SLUG = "synthetic-week-10-college-football-on-espn"
_URL = f"https://espnpressroom.com/press-release/{_SLUG}/"
_SAVED_AT = "2025-11-04T02:00:00Z"


def _reference(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    reference = tmp_path / "reference_ext"
    shutil.copytree(_REFERENCE_FIXTURES, reference)
    with (reference / "network_rarity.csv").open("a", encoding="utf-8", newline="") as fh:
        fh.write(
            "ecn,false\necn2,false\nespn,false\nespn2,false\nespnu,false\nespn-deportes,false\n"
        )
    with (reference / "networks.csv").open("a", encoding="utf-8", newline="") as fh:
        fh.write("ECN,ecn,Example Cable Network,disney,cable,main,,,\n")
        fh.write("ECN2,ecn2,Example Cable Network 2,family-ecn,cable,main,,,\n")
        fh.write("ESPN,espn,ESPN,disney,cable,main,,,\n")
        fh.write("ESPN2,espn2,ESPN2,disney,cable,main,,,\n")
        fh.write("ESPNU,espnu,ESPNU,disney,cable,main,,,\n")
        fh.write("ESPN Deportes,espn-deportes,ESPN Deportes,disney,cable,spanish,,,\n")
    monkeypatch.setenv("BOOTH_REVIEW_REFERENCE", str(reference))
    return reference


def _release(rows: str) -> str:
    return f"""<!DOCTYPE html><html><head><title>Synthetic Week 10 - ESPN Press Room</title>
<link rel="canonical" href="{_URL}" />
<meta property="article:published_time" content="2025-11-03T14:00:00-05:00" />
</head><body class="wp-singular single single-press-release"><main>
<article class="press-release-content"><div class="brxe-post-content">
<p><strong>College Football on ESPN &#8211; WEEK 10</strong></p>
<table><tbody>
<tr><td><strong>Date</strong></td><td><strong>Time (ET)</strong></td>
<td><strong>Game/Commentators</strong></td><td><strong>Platform</strong></td></tr>
{rows}
</tbody></table></div></article></main></body></html>"""


_ROWS = (
    # 500005 (no 506 crew): a 3-name line whose unknown third is the sideline.
    "<tr><td><strong>Sat, Nov 8</strong></td><td>1 p.m.</td>"
    "<td><strong>No. 9 Ironpeak at Foxhollow<br></strong>Avery Lane, Morgan Pike, Sable Wren</td>"
    "<td>ECN</td></tr>"
    # 500001 (506 lists a crew): another set of people, so one disagreement row.
    "<tr><td><strong>Sat, Oct 11</strong></td><td>3:30 p.m.</td>"
    "<td><strong>Lakeview at Northfield<br></strong>Tamsin Vale, Rowan Ellis</td>"
    "<td>ECN</td></tr>"
)


def _save_release(paths: DataPaths) -> None:
    rel = f"espnpr/2025/releases/{_SLUG}.html"
    page = paths.raw / rel
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(_release(_ROWS), encoding="utf-8")
    entry = {
        "url": _URL,
        "source": "espnpr",
        "season": 2025,
        "kind": "page",
        "fetched_at": "2026-10-13T12:00:00Z",
        "status": 200,
        "etag": None,
        "last_modified": None,
        "sha256": None,
        "path": rel,
        "bytes": None,
        "final_url": _URL,
        "origin": "manual",
        "saved_at": _SAVED_AT,
    }
    paths.manifest.parent.mkdir(parents=True, exist_ok=True)
    with paths.manifest.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def _build(paths: DataPaths, reference: Path) -> BuildOutcome:
    return run_build(paths, reference, commit=False, accept_baseline=False)


def _telecast(paths: DataPaths, game_id: int) -> dict[str, Any]:
    frame = pl.read_parquet(paths.vault / "processed" / "telecasts.parquet")
    rows = frame.filter(
        (pl.col("game_id") == game_id)
        & (pl.col("network_id") == "ecn")
        & (pl.col("feed_type") == "main")
    ).to_dicts()
    assert len(rows) == 1
    return rows[0]


def _csv(paths: DataPaths, name: str) -> tuple[list[str], list[dict[str, str]]]:
    with (paths.vault / "interim" / f"{name}.csv").open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames or []), list(reader)


def _site(paths: DataPaths) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(
        (paths.vault / "processed" / "site-data.json").read_text(encoding="utf-8")
    )
    return data


def _families(reference: Path) -> dict[str, str]:
    with (reference / "networks.csv").open(encoding="utf-8", newline="") as fh:
        return {row["network_id"]: row["family"] for row in csv.DictReader(fh)}


def test_saved_release_fills_a_crewless_telecast_end_to_end(
    git_vault: DataPaths,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_build_raw(git_vault)
    reference = _reference(tmp_path, monkeypatch)
    before = _build(git_vault, reference)
    target = _telecast(git_vault, 500005)
    assert target["plotted"] and not target["crew_matched"] and not target["crew_backup"]
    listed = _telecast(git_vault, 500001)
    assert listed["crew_matched"]
    people = pl.read_parquet(git_vault.vault / "processed" / "telecast_people.parquet")
    listed_people = people.filter(pl.col("telecast_id") == listed["telecast_id"])
    freshness_before = _site(git_vault)["freshness"]
    assert before.counts["crew_backup_filled"] == 0
    # D-15 before any page: the crew-less ESPN-family telecast's week is listed.
    _, weeks_before = _csv(git_vault, "espnpr_backfill_gaps")
    assert weeks_before == [
        {
            "season": "2025",
            "cfbd_week": "10",
            "espn_week_label": "Week 10",
            "telecasts": "1",
            "first_date": "2025-11-08",
            "last_date": "2025-11-08",
            "networks": "ecn",
        }
    ]
    assert before.counts["crew_backup_gap_weeks"] == 1

    _save_release(git_vault)
    after = _build(git_vault, reference)

    # The crew-less ESPN-family telecast takes the page's booth, sideline dropped.
    filled = _telecast(git_vault, 500005)
    assert filled["crew_backup"] is True
    assert filled["crew_matched"] is True
    assert filled["crew_patched"] is False
    assert filled["crew_source_label"] == "ESPN Press Room"
    assert filled["crew_source_url"] == _URL
    people = pl.read_parquet(git_vault.vault / "processed" / "telecast_people.parquet")
    rows = people.filter(pl.col("telecast_id") == filled["telecast_id"]).sort("crew_position")
    assert rows["role"].to_list() == ["pbp", "analyst"]
    assert set(rows["source"].to_list()) == {"crew_backup"}
    assert rows["s506_pointer"].null_count() == 2
    person_table = pl.read_parquet(git_vault.vault / "processed" / "people.parquet")
    assert set(rows["person_id"].to_list()) <= set(person_table["person_id"].to_list())
    assert after.counts["crew_backup_filled"] == 1
    assert after.counts["crew_backup_sideline_dropped"] == 1
    assert after.counts["records_with_crew"] == (
        before.counts["records_with_crew"] + len(target["rr_telecast_ids"])
    )
    assert after.counts["crew_gaps_unpatched"] == before.counts["crew_gaps_unpatched"] - 1

    # The 506 crew stays; the other booth is one disagreement row.
    unchanged = people.filter(pl.col("telecast_id") == listed["telecast_id"])
    assert unchanged.sort(["person_id", "feed_type"]).equals(
        listed_people.sort(["person_id", "feed_type"])
    )
    assert _telecast(git_vault, 500001)["crew_backup"] is False
    columns, disagreements = _csv(git_vault, "review_crew_backup_disagreements")
    assert tuple(columns) == REVIEW_CREW_BACKUP_DISAGREEMENT_COLUMNS
    assert [r["cfbd_game_id"] for r in disagreements] == ["500001"]
    assert after.counts["crew_backup_disagreements"] == 1

    # Unknown names on the filled booth are listed for review.
    _, new_names = _csv(git_vault, "review_people_new")
    names = {r["name"] for r in new_names}
    assert {"Avery Lane", "Morgan Pike"} <= names
    assert "Sable Wren" not in names

    # The gap list and the crew-gap review agree.
    _, gaps = _csv(git_vault, "review_crew_overrides")
    status = {r["cfbd_game_id"]: r["override_status"] for r in gaps if r["network_id"] == "ecn"}
    assert status["500005"] == "backup"
    columns, weeks = _csv(git_vault, "espnpr_backfill_gaps")
    assert tuple(columns) == ESPNPR_BACKFILL_GAP_COLUMNS
    families = _families(reference)
    missing = [
        r
        for r in gaps
        if r["override_status"] == "missing" and families.get(r["network_id"]) == "disney"
    ]
    # The only ESPN-family gap is filled now, so the list is empty.
    assert missing == []
    assert weeks == []
    assert after.counts["crew_backup_gap_weeks"] == 0

    # The site credits the page; the 506 stamp ignores the backup-only crew.
    site = _site(git_vault)
    dots = site["dots"] if "dots" in site else site["telecasts"]
    index = dots["crew_source_url"].index(_URL)
    assert dots["crew_source_label"][index] == "ESPN Press Room"
    assert dots["crew"][index]
    assert site["freshness"] == freshness_before

    # The build line is counts only.
    capsys.readouterr()
    assert main(["build", "--no-commit"]) == 0
    out = capsys.readouterr().out
    assert (
        "crew backup: filled 1, disagreements 1, network mismatches 0, sideline dropped 1, "
        "gap weeks listed 0" in out
    )
    for name in ("Avery Lane", "Morgan Pike", "Sable Wren", "Tamsin Vale", "Ironpeak"):
        assert name not in out


def test_no_saved_pages_writes_empty_review_files(
    git_vault: DataPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_build_raw(git_vault)
    reference = _reference(tmp_path, monkeypatch)
    outcome = _build(git_vault, reference)
    assert outcome.counts["crew_backup_filled"] == 0
    assert outcome.counts["crew_backup_disagreements"] == 0
    columns, rows = _csv(git_vault, "review_crew_backup_disagreements")
    assert tuple(columns) == REVIEW_CREW_BACKUP_DISAGREEMENT_COLUMNS
    assert rows == []
    telecasts = pl.read_parquet(git_vault.vault / "processed" / "telecasts.parquet")
    assert not telecasts["crew_backup"].any()
