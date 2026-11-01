"""Awful Announcing crews in the real build (Phase 27, AAC-03): a cached crews post
fills a crew-less telecast, agrees with or loses to a 506 crew, sits between the
overrides and the ESPN Press Room backup, and is counted without printing a name.
Synthetic data only. The synthetic vault holds 2025 games, so the crews season is
monkeypatched to 2025 here (production reads 2026 only).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from test_build_crew_backup_pipeline import _reference, _save_release
from test_cli_build import _seed_build_raw

import booth_review.build.crew_aa as crew_aa_module
from booth_review.build.crew_aa import REVIEW_CREW_AA_DISAGREEMENT_COLUMNS
from booth_review.build.pipeline import BuildOutcome, run_build
from booth_review.cli import main
from booth_review.config import DataPaths

_URL = "https://awfulannouncing.com/college-football/invented-week-10-announcing-schedule.html"
_REL = "aa/crews/2025/wk-10.html"
_AA_MODIFIED = "2025-11-05T18:30:00+00:00"
_NAMES = (
    "Rex Quill",
    "Sol Marsh",
    "Taylor Case",
    "Morgan Field",
    "Casey Vale",
    "Nia Voss",
    "Obi Trent",
)


def _page(*, modified: str | None = _AA_MODIFIED) -> str:
    meta = f'<meta property="article:modified_time" content="{modified}" />' if modified else ""
    return f"""<!DOCTYPE html>
<html lang="en-US"><head><meta charset="UTF-8" />
<title>Invented announcing schedule | Awful Announcing</title>
<link rel="canonical" href="{_URL}" />
<meta property="article:published_time" content="2025-11-03T15:00:00+00:00" />
{meta}
</head><body><article><div class="entry-content">
<p>Invented schedule.</p>
<h3><u>Saturday, October 11</u></h3>
<p><strong>Lakeview at Northfield (3:30 p.m., ECN): </strong>
Taylor Case (play-by-play), Morgan Field (analyst), Casey Vale (analyst)</p>
<h3><u>Saturday, November 8</u></h3>
<p><strong>No. 9 Ironpeak at Foxhollow (1:00 p.m., ECN): </strong>
Rex Quill (play-by-play), Sol Marsh (analyst)</p>
<h3><u>Saturday, December 6</u></h3>
<p><strong>Northfield at Lakeview (12:00 p.m., ECN): </strong>
Nia Voss (play-by-play), Obi Trent (analyst)</p>
</div></article></body></html>"""


def _manifest_line(paths: DataPaths, entry: dict[str, Any]) -> None:
    paths.manifest.parent.mkdir(parents=True, exist_ok=True)
    with paths.manifest.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def _save_aa(paths: DataPaths, html: str | None = None) -> None:
    page = paths.raw / _REL
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(_page() if html is None else html, encoding="utf-8")
    _manifest_line(
        paths,
        {
            "url": _URL,
            "source": "aa",
            "season": 2025,
            "kind": "page",
            "fetched_at": "2025-11-06T01:00:00Z",
            "status": 200,
            "path": _REL,
        },
    )


def _save_506_times(paths: DataPaths, saved_at: str) -> None:
    _manifest_line(
        paths,
        {
            "url": "https://506sports.com/ncaaf.php?yr=2025&wk=1",
            "source": "sports506",
            "season": 2025,
            "kind": "page",
            "fetched_at": saved_at,
            "saved_at": saved_at,
            "status": 200,
            "path": "sports506/2025/wk-01.html",
            "origin": "manual",
        },
    )


def _setup(paths: DataPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(crew_aa_module, "CREWS_SEASON", 2025)
    _seed_build_raw(paths)
    return _reference(tmp_path, monkeypatch)


def _build(paths: DataPaths, reference: Path) -> BuildOutcome:
    return run_build(paths, reference, commit=False, accept_baseline=False)


def _telecast(paths: DataPaths, game_id: int, network: str = "ecn") -> dict[str, Any]:
    frame = pl.read_parquet(paths.vault / "processed" / "telecasts.parquet")
    rows = frame.filter(
        (pl.col("game_id") == game_id)
        & (pl.col("network_id") == network)
        & (pl.col("feed_type") == "main")
    ).to_dicts()
    assert len(rows) == 1
    return rows[0]


def _csv(paths: DataPaths, name: str) -> tuple[list[str], list[dict[str, str]]]:
    with (paths.vault / "interim" / f"{name}.csv").open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames or []), list(reader)


def _main_people(paths: DataPaths, telecast_id: str) -> pl.DataFrame:
    people = pl.read_parquet(paths.vault / "processed" / "telecast_people.parquet")
    return people.filter(
        (pl.col("telecast_id") == telecast_id) & (pl.col("feed_type") == "main")
    ).sort(["crew_position", "person_id"])


def test_cached_post_fills_agrees_and_loses_to_a_newer_506_page(
    git_vault: DataPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reference = _setup(git_vault, tmp_path, monkeypatch)
    before = _build(git_vault, reference)
    target = _telecast(git_vault, 500005)
    assert not target["crew_matched"]
    agreeing = _telecast(git_vault, 500001)
    assert agreeing["crew_matched"]
    agreeing_before = _main_people(git_vault, agreeing["telecast_id"])
    assert before.counts["crew_aa_filled"] == 0
    assert before.counts["records_with_crew"] > 0

    _save_aa(git_vault)
    # 506's week page was saved after the AA post was last modified.
    _save_506_times(git_vault, "2025-11-09T00:00:00Z")
    after = _build(git_vault, reference)

    filled = _telecast(git_vault, 500005)
    assert filled["crew_aa"] is True
    assert filled["crew_matched"] is True
    assert filled["crew_patched"] is False
    assert filled["crew_backup"] is False
    assert filled["crew_source_label"] == "Awful Announcing"
    assert filled["crew_source_url"] == _URL
    rows = _main_people(git_vault, filled["telecast_id"])
    assert rows["role"].to_list() == ["pbp", "analyst"]
    assert set(rows["source"].to_list()) == {"crew_aa"}
    assert rows["s506_pointer"].null_count() == 2

    # The agreeing game keeps its 506 attribution.
    kept = _telecast(git_vault, 500001)
    assert kept["crew_aa"] is False
    assert _main_people(git_vault, kept["telecast_id"]).equals(agreeing_before)

    assert after.counts["crew_aa_filled"] == 1
    assert after.counts["crew_aa_agreements"] == 1
    assert after.counts["crew_aa_s506_won"] == 1
    assert after.counts["records_with_crew"] == (
        before.counts["records_with_crew"] + len(target["rr_telecast_ids"])
    )
    assert after.counts["crew_gaps_unpatched"] == before.counts["crew_gaps_unpatched"] - 1

    # The differing booth lost to the newer 506 page: one review row, winner 506.
    columns, disagreements = _csv(git_vault, "review_crew_aa_disagreements")
    assert tuple(columns) == REVIEW_CREW_AA_DISAGREEMENT_COLUMNS
    assert [(r["cfbd_game_id"], r["winner"]) for r in disagreements] == [("500002", "506")]

    # Provisional AA names are listed for review.
    _, new_names = _csv(git_vault, "review_people_new")
    assert {"Rex Quill", "Sol Marsh"} <= {r["name"] for r in new_names}

    # The gap row says aa, never missing.
    _, gaps = _csv(git_vault, "review_crew_overrides")
    status = {r["cfbd_game_id"]: r["override_status"] for r in gaps if r["network_id"] == "ecn"}
    assert status["500005"] == "aa"


def test_a_newer_aa_page_replaces_a_differing_506_crew(
    git_vault: DataPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reference = _setup(git_vault, tmp_path, monkeypatch)
    _save_aa(git_vault)
    # 506's week page was saved before the AA post was last modified.
    _save_506_times(git_vault, "2025-11-01T00:00:00Z")
    outcome = _build(git_vault, reference)
    assert outcome.counts["crew_aa_aa_won"] == 1
    _, rows = _csv(git_vault, "review_crew_aa_disagreements")
    assert [(r["cfbd_game_id"], r["winner"]) for r in rows] == [("500002", "aa")]
    won = _telecast(git_vault, 500002)
    assert won["crew_aa"] is True
    assert won["crew_patched"] is False


def test_a_redundant_override_beats_a_newer_aa_page(
    git_vault: DataPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase 27 review CR-01: an override equal to 506's crew (`redundant`) still
    wins over a newer, differing AA booth."""
    reference = _setup(git_vault, tmp_path, monkeypatch)
    _build(git_vault, reference)
    target = _telecast(git_vault, 500002)
    crew = _main_people(git_vault, target["telecast_id"])
    # The synthetic 506 crew is provisional; an override needs registered people.
    names = pl.read_parquet(git_vault.vault / "processed" / "people.parquet").filter(
        pl.col("person_id").is_in(crew["person_id"].to_list()) & ~pl.col("registered")
    )
    with (reference / "people.csv").open("a", encoding="utf-8", newline="") as fh:
        for row in names.iter_rows(named=True):
            name = row["canonical_name"]
            fh.write(f"{row['person_id']},{name},{name},{row['usual_role']},\n")
    _build(git_vault, reference)
    crew = _main_people(git_vault, target["telecast_id"])
    before = crew.select("person_id", "role").sort("person_id")
    rows = [
        f"500002,ecn,{position},{person},{role},correction,outlet,Outlet,https://example.com/a\n"
        for position, (person, role) in enumerate(
            zip(crew["person_id"].to_list(), crew["role"].to_list(), strict=True)
        )
    ]
    (reference / "crew_overrides.csv").write_text(
        "cfbd_game_id,network_id,crew_position,person_id,role,reason,"
        "source_kind,source_name,source_url\n" + "".join(rows),
        encoding="utf-8",
    )
    _save_aa(git_vault)
    _save_506_times(git_vault, "2025-11-01T00:00:00Z")  # the AA page is newer
    outcome = _build(git_vault, reference)

    assert outcome.counts["crew_aa_aa_won"] == 0
    assert outcome.counts["crew_aa_disagreements"] == 0
    kept = _telecast(git_vault, 500002)
    assert kept["crew_aa"] is False
    assert kept["crew_source_label"] == target["crew_source_label"]
    after = _main_people(git_vault, kept["telecast_id"])
    assert after.select("person_id", "role").sort("person_id").equals(before)
    _, review = _csv(git_vault, "review_crew_aa_disagreements")
    assert review == []


def test_espn_booth_does_not_replace_an_aa_filled_crew(
    git_vault: DataPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reference = _setup(git_vault, tmp_path, monkeypatch)
    _save_aa(git_vault)
    _save_release(git_vault)
    outcome = _build(git_vault, reference)

    filled = _telecast(git_vault, 500005)
    assert filled["crew_aa"] is True
    assert filled["crew_backup"] is False
    assert filled["crew_source_label"] == "Awful Announcing"
    _, rows = _csv(git_vault, "review_crew_backup_disagreements")
    assert "500005" in {r["cfbd_game_id"] for r in rows}
    # F10: the crew ESPN was compared with is AA's, and the row says so.
    (row,) = [r for r in rows if r["cfbd_game_id"] == "500005"]
    assert row["s506_person_ids"] == "" and row["aa_person_ids"]
    assert outcome.counts["crew_aa_filled"] == 1
    assert outcome.counts["crew_backup_filled"] == 0


def test_no_aa_pages_writes_a_header_only_review_file(
    git_vault: DataPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reference = _setup(git_vault, tmp_path, monkeypatch)
    outcome = _build(git_vault, reference)
    columns, rows = _csv(git_vault, "review_crew_aa_disagreements")
    assert tuple(columns) == REVIEW_CREW_AA_DISAGREEMENT_COLUMNS
    assert rows == []
    for key in ("filled", "agreements", "disagreements", "superset", "aa_won", "s506_won"):
        assert outcome.counts[f"crew_aa_{key}"] == 0
    telecasts = pl.read_parquet(git_vault.vault / "processed" / "telecasts.parquet")
    assert not telecasts["crew_aa"].any()


def test_build_line_is_counts_only(
    git_vault: DataPaths,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _setup(git_vault, tmp_path, monkeypatch)
    _save_aa(git_vault)
    _save_506_times(git_vault, "2025-11-09T00:00:00Z")
    capsys.readouterr()
    assert main(["build", "--no-commit"]) == 0
    captured = capsys.readouterr()
    assert (
        "crew aa: filled 1, agreements 1, superset 0, aa won 0, 506 won 1, "
        "network mismatches 0, unparsed lines 0, undated pages 0" in captured.out
    )
    for name in (*_NAMES, "Ironpeak", "Foxhollow"):
        assert name not in captured.out + captured.err


def test_rejected_aa_page_is_counted_and_never_stops_the_build(
    git_vault: DataPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reference = _setup(git_vault, tmp_path, monkeypatch)
    bad = git_vault.raw / "aa" / "crews" / "2025" / "wk-11.html"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("<html><body>nothing</body></html>", encoding="utf-8")
    outcome = _build(git_vault, reference)
    assert outcome.counts["crew_aa_rejected_pages"] == 1
    assert outcome.counts["crew_aa_filled"] == 0


def test_building_twice_gives_identical_tables(
    git_vault: DataPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reference = _setup(git_vault, tmp_path, monkeypatch)
    _save_aa(git_vault)
    _save_506_times(git_vault, "2025-11-09T00:00:00Z")
    _build(git_vault, reference)
    processed = git_vault.vault / "processed"
    first = (
        pl.read_parquet(processed / "telecasts.parquet"),
        pl.read_parquet(processed / "telecast_people.parquet"),
    )
    _build(git_vault, reference)
    second = (
        pl.read_parquet(processed / "telecasts.parquet"),
        pl.read_parquet(processed / "telecast_people.parquet"),
    )
    assert first[0].equals(second[0])
    assert first[1].equals(second[1])
    assert first[0].filter(pl.col("crew_aa")).height == 1
