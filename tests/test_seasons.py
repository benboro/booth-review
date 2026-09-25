"""Tests for season_of/season_window: the July-June CFB season window."""

from __future__ import annotations

from datetime import date

from booth_review.seasons import season_of, season_window


def test_season_of_within_season_start_year() -> None:
    assert season_of(date(2025, 8, 30)) == 2025


def test_season_of_january_belongs_to_prior_season() -> None:
    assert season_of(date(2026, 1, 19)) == 2025


def test_season_of_july_starts_the_new_season() -> None:
    assert season_of(date(2026, 7, 1)) == 2026


def test_season_of_june_still_belongs_to_prior_season() -> None:
    assert season_of(date(2026, 6, 30)) == 2025


def test_season_window_bounds() -> None:
    assert season_window(2025) == (date(2025, 7, 1), date(2026, 6, 30))
