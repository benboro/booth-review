"""Tests for the 506 inventory (SPIKE-03).

Runs build_506_inventory against a tmp vault holding the same synthetic 506
fixtures the parser tests use, plus a synthetic manifest. No real 506 row
appears in this file (D-07).
"""

from __future__ import annotations

import json
from pathlib import Path

from booth_review.config import DataPaths
from booth_review.spike.inventory_506 import build_506_inventory, write_506_inventory

FIXTURES = Path(__file__).parent / "fixtures" / "sports506"


def _build_tmp_vault(tmp_path: Path) -> DataPaths:
    paths = DataPaths(vault=tmp_path)
    season_dir = paths.raw / "sports506" / "2025"
    season_dir.mkdir(parents=True)
    (season_dir / "wk-05.html").write_bytes((FIXTURES / "week_synthetic.html").read_bytes())
    (season_dir / "wk-B.html").write_bytes((FIXTURES / "bowls_synthetic.html").read_bytes())

    manifest_lines = [
        {
            "url": "https://506sports.com/ncaaf.php?yr=2025&wk=5",
            "source": "sports506",
            "season": 2025,
            "kind": "page",
            "fetched_at": "2026-09-25T00:00:00Z",
            "status": 200,
            "etag": None,
            "last_modified": None,
            "sha256": "deadbeef",
            "path": "sports506/2025/wk-05.html",
            "bytes": 100,
            "final_url": "https://506sports.com/ncaaf.php?yr=2025&wk=5",
            "origin": "manual",
        },
        {
            "url": "https://506sports.com/ncaaf.php?yr=2025&wk=B",
            "source": "sports506",
            "season": 2025,
            "kind": "page",
            "fetched_at": "2026-09-25T00:00:00Z",
            "status": 200,
            "etag": 'W/"abc123"',
            "last_modified": "Thu, 25 Sep 2026 00:00:00 GMT",
            "sha256": "cafef00d",
            "path": "sports506/2025/wk-B.html",
            "bytes": 120,
            "final_url": "https://506sports.com/ncaaf.php?yr=2025&wk=B",
            "origin": None,
        },
        {
            "url": "https://506sports.com/ncaaf.php?yr=2025&wk=0",
            "source": "sports506",
            "season": 2025,
            "kind": "page",
            "fetched_at": "2026-09-25T00:00:00Z",
            "status": 403,
            "etag": None,
            "last_modified": None,
            "sha256": None,
            "path": None,
            "bytes": None,
            "final_url": "https://506sports.com/ncaaf.php?yr=2025&wk=0",
            "origin": None,
        },
        {
            "url": "https://ratingsreference.com/sitemap-telecasts.xml",
            "source": "ratingsref",
            "season": None,
            "kind": "page",
            "fetched_at": "2026-09-25T00:00:00Z",
            "status": 200,
            "etag": None,
            "last_modified": None,
            "sha256": "0000",
            "path": "ratingsref/sitemap.xml",
            "bytes": 10,
            "final_url": "https://ratingsreference.com/sitemap-telecasts.xml",
            "origin": None,
        },
    ]
    paths.ledger.mkdir(parents=True, exist_ok=True)
    with paths.manifest.open("w", encoding="utf-8") as fh:
        for line in manifest_lines:
            fh.write(json.dumps(line))
            fh.write("\n")
    return paths


def test_build_506_inventory_counts_pages_and_listings(tmp_path: Path) -> None:
    paths = _build_tmp_vault(tmp_path)
    inv = build_506_inventory(paths, season=2025)
    assert inv.pages_found == 2
    assert inv.pages_expected == 18
    assert inv.rows_per_week["5"] == 4
    assert inv.rows_per_week["B"] == 2
    assert inv.total_listings == 6


def test_build_506_inventory_crew_size_distribution(tmp_path: Path) -> None:
    paths = _build_tmp_vault(tmp_path)
    inv = build_506_inventory(paths, season=2025)
    # week fixture: 2, 0 (no crew), 3, 2; bowls fixture: 2, 2
    assert inv.crew_size_distribution[0] == 1
    assert inv.crew_size_distribution[2] == 4
    assert inv.crew_size_distribution[3] == 1


def test_build_506_inventory_feed_kind_counts_and_examples(tmp_path: Path) -> None:
    paths = _build_tmp_vault(tmp_path)
    inv = build_506_inventory(paths, season=2025)
    assert inv.feed_kind_counts["alt"] == 1
    assert inv.feed_kind_counts["unknown"] == 1
    assert inv.feed_kind_counts["main"] == 4
    assert "alt" in inv.feed_kind_examples
    assert len(inv.feed_kind_examples["alt"]) == 1


def test_build_506_inventory_rank_forms_includes_seed_paren(tmp_path: Path) -> None:
    paths = _build_tmp_vault(tmp_path)
    inv = build_506_inventory(paths, season=2025)
    assert inv.rank_forms.get("plain", 0) >= 1
    assert inv.rank_forms.get("seed_paren", 0) == 0  # no seed-paren form in this fixture set


def test_build_506_inventory_conditional_get_from_manifest(tmp_path: Path) -> None:
    paths = _build_tmp_vault(tmp_path)
    inv = build_506_inventory(paths, season=2025)
    assert inv.conditional_get["entries_seen"] == 3
    assert inv.conditional_get["with_etag"] == 1
    assert inv.conditional_get["with_last_modified"] == 1
    assert inv.conditional_get["manual_origin"] == 1
    assert inv.conditional_get["by_status"]["200"] == 2
    assert inv.conditional_get["by_status"]["403"] == 1


def test_write_506_inventory_writes_json_and_markdown(tmp_path: Path) -> None:
    paths = _build_tmp_vault(tmp_path)
    inv = build_506_inventory(paths, season=2025)
    write_506_inventory(paths, inv)

    json_path = paths.spike / "inventory-506.json"
    md_path = paths.spike / "inventory-506.md"
    assert json_path.is_file()
    assert md_path.is_file()

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["total_listings"] == 6
    assert "rows_per_week" in payload
    assert "crew_size_distribution" in payload
    assert "delimiters" in payload
    assert "feed_kind_counts" in payload
    assert "conditional_get" in payload

    markdown = md_path.read_text(encoding="utf-8")
    for heading in (
        "Crew delimiters",
        "Rank prefixes",
        "Alt-cast and Spanish rows",
        "Rows without crews",
        "Conditional GET",
        "Structure notes",
        "Rank-prefix poll",
    ):
        assert heading in markdown
