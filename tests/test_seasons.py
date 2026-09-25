"""Tests for season_of/season_window: the July-June CFB season window."""

from __future__ import annotations

from datetime import date

from booth_review.seasons import freeze_date, is_past_freeze_date, season_of, season_window


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


def test_freeze_date_2025_is_feb_15_2026() -> None:
    assert freeze_date(2025) == date(2026, 2, 15)


def test_freeze_date_2026_is_feb_15_2027() -> None:
    assert freeze_date(2026) == date(2027, 2, 15)


def test_is_past_freeze_date_true_on_the_freeze_date() -> None:
    assert is_past_freeze_date(2025, date(2026, 2, 15)) is True


def test_is_past_freeze_date_false_day_before() -> None:
    assert is_past_freeze_date(2026, date(2027, 2, 14)) is False
