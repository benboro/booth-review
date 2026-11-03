"""The build's no-logo check for FBS conferences (Phase 28, user decision 2026-11-03)."""

from __future__ import annotations

from booth_review.build.conf_logos import (
    CONFERENCE_LOGO_NAMES,
    FBS_INDEPENDENTS,
    missing_conference_logos,
)


def test_unknown_fbs_conference_is_reported_with_sorted_seasons() -> None:
    got = missing_conference_logos({"New League": {2026, 2024, 2025}})
    assert got == [("New League", (2024, 2025, 2026))]


def test_known_names_and_fbs_independents_are_not_reported() -> None:
    seasons = {name: {2024} for name in CONFERENCE_LOGO_NAMES}
    seasons[FBS_INDEPENDENTS] = {2024}
    assert missing_conference_logos(seasons) == []


def test_reports_are_sorted_by_name() -> None:
    got = missing_conference_logos({"Zeta League": {2025}, "SEC": {2025}, "Alpha League": {2023}})
    assert got == [("Alpha League", (2023,)), ("Zeta League", (2025,))]


def test_names_match_exactly() -> None:
    """A spelling the logo map does not hold is reported, not silently matched."""
    assert missing_conference_logos({"sec": {2024}, "Pac 12": {2024}}) == [
        ("Pac 12", (2024,)),
        ("sec", (2024,)),
    ]
