"""Season helpers: a CFB season runs July through the following June.

A game played in January 2026 (a bowl or the CFP title game) belongs to the
season that started in July 2025, i.e. "season 2025".
"""

from __future__ import annotations

from datetime import date


def season_of(d: date) -> int:
    """Return the season a calendar date belongs to (July-June window)."""
    return d.year if d.month >= 7 else d.year - 1


def season_window(season: int) -> tuple[date, date]:
    """Return the (start, end) calendar-date bounds of `season`, inclusive."""
    return date(season, 7, 1), date(season + 1, 6, 30)
