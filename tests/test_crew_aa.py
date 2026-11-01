"""Awful Announcing crews pass (Phase 27, AAC-03): loaders and the decision table.
Synthetic data only: invented teams, people and posts."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from booth_review.build.crew_aa import (
    load_506_times,
    load_aa_pages,
)
from booth_review.build.crew_backup import CREW_BACKUP_LABEL, ScheduledCrew
from booth_review.build.telecasts import TELECASTS_SCHEMA
from booth_review.config import DataPaths

FIXTURE = Path(__file__).parent / "fixtures" / "aa" / "schedule_synthetic.html"
REL = "aa/crews/2026/wk-10.html"


def _paths(tmp_path: Path) -> DataPaths:
    paths = DataPaths(vault=tmp_path)
    paths.raw.mkdir(parents=True)
    return paths


def _manifest(paths: DataPaths, *lines: dict[str, object]) -> None:
    paths.manifest.parent.mkdir(parents=True, exist_ok=True)
    paths.manifest.write_text("\n".join(json.dumps(line) for line in lines) + "\n")


def _save(paths: DataPaths, html: str, rel: str = REL) -> None:
    target = paths.raw / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding="utf-8")


def _line(rel: str, status: int, fetched_at: str, **extra: object) -> dict[str, object]:
    return {"source": "aa", "path": rel, "status": status, "fetched_at": fetched_at, **extra}


def test_schema_has_crew_aa_boolean() -> None:
    assert "crew_aa" in TELECASTS_SCHEMA


def test_scheduled_crew_label_defaults_to_espn_and_can_be_overridden() -> None:
    assert ScheduledCrew((), "u").label == CREW_BACKUP_LABEL == "ESPN Press Room"
    assert ScheduledCrew((), "u", label="Awful Announcing").label == "Awful Announcing"


def test_modified_meta_is_the_page_time(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _save(paths, FIXTURE.read_text(encoding="utf-8"))
    _manifest(paths, _line(REL, 200, "2026-11-06T01:00:00Z"))
    loaded = load_aa_pages(paths)
    assert len(loaded.pages) == 1
    page = loaded.pages[0]
    assert page.aa_time == datetime(2026, 11, 5, 18, 30, tzinfo=UTC)
    assert page.aa_time_source == "modified"
    assert not loaded.rejected


def test_undated_page_uses_last_200_fetch_not_a_304(tmp_path: Path) -> None:
    html = FIXTURE.read_text(encoding="utf-8")
    html = "\n".join(
        ln for ln in html.splitlines() if "modified_time" not in ln and "dateModified" not in ln
    )
    paths = _paths(tmp_path)
    _save(paths, html)
    _manifest(
        paths,
        _line(REL, 200, "2026-11-04T10:00:00Z"),
        _line(REL, 200, "2026-11-05T11:00:00Z"),
        _line(REL, 304, "2026-11-06T12:00:00Z"),
    )
    page = load_aa_pages(paths).pages[0]
    assert page.aa_time == datetime(2026, 11, 5, 11, 0, tzinfo=UTC)
    assert page.aa_time_source == "fetched"


def test_undated_page_without_manifest_has_no_time(tmp_path: Path) -> None:
    html = "\n".join(
        ln
        for ln in FIXTURE.read_text(encoding="utf-8").splitlines()
        if "modified_time" not in ln and "dateModified" not in ln
    )
    paths = _paths(tmp_path)
    _save(paths, html)
    page = load_aa_pages(paths).pages[0]
    assert page.aa_time is None
    assert page.aa_time_source == "none"


def test_bad_pages_are_rejected_not_loaded(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _save(paths, "<html><body>nothing</body></html>", "aa/crews/2026/wk-01.html")
    off = FIXTURE.read_text(encoding="utf-8").replace("awfulannouncing.com", "example.org")
    _save(paths, off, "aa/crews/2026/wk-02.html")
    nobody = FIXTURE.read_text(encoding="utf-8").replace("entry-content", "other")
    _save(paths, nobody, "aa/crews/2026/wk-03.html")
    loaded = load_aa_pages(paths)
    assert loaded.pages == []
    assert sorted((r.path, r.reason) for r in loaded.rejected) == [
        ("aa/crews/2026/wk-01.html", "no_canonical_url"),
        ("aa/crews/2026/wk-02.html", "off_host_url"),
        ("aa/crews/2026/wk-03.html", "parse_error"),
    ]


def test_only_2026_is_read(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _save(paths, FIXTURE.read_text(encoding="utf-8"), "aa/crews/2025/wk-10.html")
    assert load_aa_pages(paths).pages == []


def test_506_times_prefer_saved_at_and_normalise_labels(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _manifest(
        paths,
        {
            "source": "sports506",
            "path": "sports506/2026/wk-09.html",
            "status": 200,
            "fetched_at": "2026-11-02T00:00:00Z",
            "saved_at": "2026-11-01T09:00:00Z",
        },
        {
            "source": "sports506",
            "path": "sports506/2026/wk-10.html",
            "status": 200,
            "fetched_at": "2026-11-02T08:00:00Z",
        },
        {
            "source": "sports506",
            "path": "sports506/2026/wk-B.html",
            "status": 200,
            "fetched_at": "2026-12-20T08:00:00Z",
        },
    )
    times = load_506_times(paths)
    assert times[(2026, "9")] == datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
    assert times[(2026, "10")] == datetime(2026, 11, 2, 8, 0, tzinfo=UTC)
    assert times[(2026, "B")] == datetime(2026, 12, 20, 8, 0, tzinfo=UTC)


def test_missing_vault_pieces_are_empty(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    assert load_aa_pages(paths).pages == []
    assert load_506_times(paths) == {}
