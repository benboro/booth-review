"""The Phase 14 synthetic crews dataset loads in the CFB app (plan 14-01)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from crews_fixture import (
    CASE_PAST_CUT,
    N_FILLER_CREWS,
    build_crews_raw,
)
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e


def test_crews_dataset_loads(
    guarded_page: Page,
    serve_crews: Callable[[Page], None],
    open_app: Callable[[Page, str], None],
    fixture_raw: dict[str, Any],
) -> None:
    raw = build_crews_raw(fixture_raw)
    expected = len(raw["telecasts"]["season"]) + len(raw["telecasts_unrated"]["season"])
    serve_crews(guarded_page)
    open_app(guarded_page, "?view=crews")
    assert not guarded_page.evaluate("window.__testHooks.failed")
    assert guarded_page.evaluate("window.__testHooks.nGames") == expected


def test_dataset_shape(fixture_raw: dict[str, Any]) -> None:
    raw = build_crews_raw(fixture_raw)
    assert len(raw["telecasts"]["season"]) > 8
    assert len(raw["telecasts_unrated"]["season"]) > 0
    assert {2022, 2023, 2024, 2025} <= set(raw["telecasts"]["season"])
    assert N_FILLER_CREWS + 1 > 25
    assert CASE_PAST_CUT["games"] == 1
    # the shared fixture keeps its counts
    assert len(fixture_raw["telecasts"]["season"]) == 12
    assert len(fixture_raw["telecasts_unrated"]["season"]) == 8


def test_support_module_imports_from_an_e2e_file() -> None:
    from cfb_booth_support import run

    assert callable(run)
