"""Methodology page: the map section describes the venue map (Phase 11 D-09)."""

from __future__ import annotations

from pathlib import Path

import pytest

from booth_review.cli import main

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = REPO_ROOT / "docs"
SITE_SRC = REPO_ROOT / "site"
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "contract" / "site-data.fixture.json"


def _map_section() -> str:
    text = (DOCS_DIR / "methodology.md").read_text(encoding="utf-8")
    start = text.index("## The map")
    end = text.index("<!-- nfl:start -->", start)
    return text[start:end]


def test_map_section_structure() -> None:
    section = _map_section()
    assert "### How the map is colored" in section
    assert "carries no viewer figures" not in section
    assert "—" not in section
    assert "where each game's figure is credited to the page it came from" in section
    assert "the figure is not shown anywhere" in section


def test_built_page_has_anchor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BOOTH_REVIEW_SITE_SRC", str(SITE_SRC))
    monkeypatch.setenv("BOOTH_REVIEW_DOCS", str(DOCS_DIR))
    monkeypatch.setenv("BOOTH_REVIEW_SITE_FIXTURE", str(FIXTURE_PATH))
    monkeypatch.delenv("CFBD_API_KEY", raising=False)
    monkeypatch.delenv("BOOTH_REVIEW_VAULT", raising=False)
    out = tmp_path / "out"
    assert main(["site", "--fixture", "--out", str(out)]) == 0
    html = (out / "methodology.html").read_text(encoding="utf-8")
    assert 'id="how-the-map-is-colored"' in html
