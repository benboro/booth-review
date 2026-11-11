"""Lint, manifest and dark-variant checks for the game marks under site/logos/marks/.

Today that is one file: the CFP national championship emblem, cut from the title game's logo
(its lettering removed) and shown beside the trophy on the title game. Like the network and
conference logos it ships to every visitor, so it is held to the same lint and recorded with
its source, edit, SHA-256 and the user's approval. These tests read only public files.
"""

from __future__ import annotations

import csv
import hashlib
import re
from pathlib import Path

import pytest
from test_logos_dark import contrast
from test_site_logos import _view_box, lint_svg

from booth_review.build import logos_dark
from booth_review.build.logos_dark import DARK_BACKGROUNDS, dark_variant

REPO_ROOT = Path(__file__).resolve().parents[1]
MARKS_DIR = REPO_ROOT / "site" / "logos" / "marks"
MANIFEST = MARKS_DIR / "manifest.csv"
TITLE_JS = REPO_ROOT / "site" / "modules" / "title-mark.js"

HEADER = (
    "mark,file,source_file,source_url,retrieved,licence,render_box,edit,check,approved,"
    "sha256,dark_sha256"
)


def mark_files() -> list[Path]:
    return sorted(MARKS_DIR.glob("*.svg"))


def rows() -> list[dict[str, str]]:
    with MANIFEST.open(newline="") as handle:
        return list(csv.DictReader(handle))


def test_header() -> None:
    assert MANIFEST.read_text(encoding="utf-8").splitlines()[0] == HEADER


@pytest.mark.parametrize("path", mark_files(), ids=lambda p: p.name)
def test_lint_clean(path: Path) -> None:
    data = path.read_bytes()
    assert lint_svg(data) == []
    assert b"<text" not in data


def test_manifest_matches_files_and_hashes() -> None:
    files = {p.name: p for p in mark_files()}
    assert files
    assert sorted(r["file"] for r in rows()) == sorted(files)
    for row in rows():
        assert row["check"] == "pass", row["file"]
        for field in ("source_url", "licence", "approved", "retrieved", "edit"):
            assert row[field].strip(), (row["file"], field)
        data = files[row["file"]].read_bytes()
        assert row["sha256"] == hashlib.sha256(data).hexdigest(), row["file"]
        assert row["dark_sha256"] == hashlib.sha256(dark_variant(data)).hexdigest(), row["file"]


@pytest.mark.parametrize("path", mark_files(), ids=lambda p: p.name)
def test_dark_variant_meets_the_dark_contrast(path: Path) -> None:
    for paint in logos_dark._paints(dark_variant(path.read_bytes()).decode()):
        low = min(contrast(paint, bg) for bg in DARK_BACKGROUNDS)
        assert low >= 3.0, f"{path.name}: {paint} only {low:.2f}:1"


def test_title_mark_js_points_at_the_file_and_keeps_its_ratio() -> None:
    text = TITLE_JS.read_text(encoding="utf-8")
    assert "'logos/marks/cfp-national-championship.svg'" in text
    assert "'logos/dark/marks/cfp-national-championship.svg'" in text
    width = int(re.search(r"const WIDTH = (\d+);", text).group(1))  # type: ignore[union-attr]
    height = int(re.search(r"const HEIGHT = (\d+);", text).group(1))  # type: ignore[union-attr]
    vb_w, vb_h = _view_box(MARKS_DIR / "cfp-national-championship.svg")
    assert round(height * vb_w / vb_h) == width
