"""Source-text safety checks for the ranked-matchup badge module (Phase 28, D-06, D-07)."""

from __future__ import annotations

from pathlib import Path

RANK_BADGE_JS = Path(__file__).resolve().parents[1] / "site" / "modules" / "rank-badge.js"


def test_rank_badge_builds_svg_with_dom_calls_and_current_color() -> None:
    src = RANK_BADGE_JS.read_text(encoding="utf-8")
    assert "createElementNS" in src
    assert "currentColor" in src


def test_rank_badge_has_no_markup_injection_text_element_or_gold() -> None:
    src = RANK_BADGE_JS.read_text(encoding="utf-8")
    lowered = src.lower()
    for banned in ("innerhtml", "insertadjacenthtml", "outerhtml", "font-family"):
        assert banned not in lowered, banned
    for banned in ("--lead-frame", "gold", "<text", "'text'"):
        assert banned not in lowered, banned
