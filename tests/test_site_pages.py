"""Tests for build/pages.py: footer/freshness chrome and the Markdown-
rendered methodology and coverage pages (D-13).

Uses the synthetic contract fixture (tests/fixtures/contract/) and this
repo's own committed docs/ directory for the happy-path methodology
render; tmp_path docs dirs cover the missing-file/marker error cases.
Never reads data/vault.
"""

from __future__ import annotations

import copy
import html
import json
import re
from pathlib import Path

import pytest

from booth_review.build.pages import (
    CREDIT_LINE_TEXT,
    NAV,
    footer_html,
    freshness_stamps,
    render_coverage,
    render_methodology,
    write_pages,
)
from booth_review.contract.models import Freshness, validate_site_data
from booth_review.errors import SiteBuildError

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "contract" / "site-data.fixture.json"


def _load_fixture() -> dict[str, object]:
    data: dict[str, object] = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return data


def _fixture_site():  # type: ignore[no-untyped-def]
    return validate_site_data(_load_fixture())


def _strip_tags(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text)).strip()


def test_freshness_stamps_with_weeks() -> None:
    freshness = Freshness(season=2026, crews_through_week="5", viewership_through_week="4")
    assert freshness_stamps(freshness) == (
        "Crews and scores through Week 5",
        "Viewership through Week 4",
    )


def test_freshness_stamps_with_none() -> None:
    freshness = Freshness(season=2026)
    assert freshness_stamps(freshness) == (
        "Crews and scores: not yet available this season",
        "Viewership: not yet available this season",
    )


def test_footer_html_has_credit_line_once_and_nav_and_credit_links() -> None:
    freshness = Freshness(season=2026, crews_through_week="5", viewership_through_week="4")
    footer = footer_html(freshness)

    plain = _strip_tags(footer)
    assert plain.count(CREDIT_LINE_TEXT) == 1

    for _label, href in NAV:
        assert f'href="{href}"' in footer

    for href in (
        "https://ratingsreference.com",
        "https://creativecommons.org/licenses/by/4.0/",
        "https://506sports.com",
        "https://collegefootballdata.com",
    ):
        assert f'href="{href}"' in footer


def test_render_methodology_includes_known_gaps_demoted_and_no_marker() -> None:
    result = render_methodology(REPO_ROOT / "docs", _fixture_site())

    assert 'id="the-2025-excitement-break"' in result
    assert 'id="known-gaps"' in result
    assert "include: known-gaps.md" not in result
    assert 'href="#known-gaps"' in result
    assert 'href="known-gaps.md"' not in result
    assert "<h3" in result
    assert "<table" in result
    assert "<script" not in result
    assert "script-src 'none'" in result
    assert 'href="style.css"' in result


def test_render_methodology_raises_without_marker(tmp_path: Path) -> None:
    (tmp_path / "methodology.md").write_text(
        "# Methodology\n\nNo include marker on this page.\n", encoding="utf-8"
    )
    (tmp_path / "known-gaps.md").write_text("# Known Gaps\n\n## Scope\n\ntext\n", encoding="utf-8")

    with pytest.raises(SiteBuildError):
        render_methodology(tmp_path, _fixture_site())


def test_render_methodology_raises_when_missing(tmp_path: Path) -> None:
    with pytest.raises(SiteBuildError):
        render_methodology(tmp_path, _fixture_site())


def test_render_coverage_table_structure() -> None:
    site = _fixture_site()
    result = render_coverage(site)

    assert "<table" in result
    assert "Total" in result
    for season in sorted({row.season for row in site.coverage}):
        assert f'<th scope="col">{season}</th>' in result
    assert "<script" not in result
    assert "script-src 'none'" in result
    assert 'href="style.css"' in result


def test_render_coverage_escapes_network_name() -> None:
    mutated_payload = copy.deepcopy(_load_fixture())
    mutated_payload["lookups"]["networks"][0]["name"] = "<script>x</script>"  # type: ignore[index]
    mutated_site = validate_site_data(mutated_payload)

    result = render_coverage(mutated_site)

    assert "<script>x</script>" not in result
    assert html.escape("<script>x</script>") in result


def test_write_pages_writes_both_files(tmp_path: Path) -> None:
    site = _fixture_site()
    written = write_pages(tmp_path, site, REPO_ROOT / "docs")

    assert written == ["methodology.html", "coverage.html"]
    for name in written:
        assert (tmp_path / name).is_file()
        assert "data/vault" not in (tmp_path / name).read_text(encoding="utf-8")


_METHODOLOGY_MD = REPO_ROOT / "docs" / "methodology.md"

# Tooltip-only facts moved to the detail panel in 628784b (chart.js
# `hoverText`): the time slot, the era/measurement label, and the flags.
_NOT_IN_HOVER_RE = re.compile(r"\bslots?\b|\beras?\b|Adobe|\bflags?\b", re.IGNORECASE)


def test_methodology_never_promises_panel_only_facts_in_the_hover() -> None:
    """WR-06: the tooltip shows only the matchup/score, date/kickoff,
    networks, crew and viewers, so no sentence of the public methodology
    that mentions the hover may send readers there for the time slot, the
    measurement era/label, or a flag."""
    text = re.sub(r"\s+", " ", _METHODOLOGY_MD.read_text(encoding="utf-8"))
    sentences = re.split(r"(?<=[.!?])\s+", text)
    offending = [
        s
        for s in sentences
        if re.search(r"\bhover\b", s, re.IGNORECASE) and _NOT_IN_HOVER_RE.search(s)
    ]
    assert offending == []


def test_methodology_describes_the_slim_tooltip() -> None:
    """WR-06: the page says what the tooltip does show, and that the rest
    lives in the detail panel."""
    text = re.sub(r"\s+", " ", _METHODOLOGY_MD.read_text(encoding="utf-8"))
    assert (
        "A dot's tooltip is kept short: the matchup and final score, the date and "
        "kickoff time, the networks, the crew, and the viewer count." in text
    )
    assert "Click or tap the dot to open its detail panel" in text
