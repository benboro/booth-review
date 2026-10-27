"""The `wview` URL key and the Timeline | Map switch of the This weekend tab (Phase 24, plan 05).
Synthetic fixtures only: the CFB weekend dataset of test_site_weekend_cfb and the flag-on NFL
build."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page
from test_site_weekend_cfb import MORNING, _weekend_raw

pytestmark = pytest.mark.e2e

NFL_NOW = "2026-10-11T09:00:00-04:00"


# ---- CFB ----


def _open_cfb(
    page: Page,
    fixture_raw: dict[str, Any],
    open_app: Callable[[Page, str], None],
    query: str,
) -> None:
    raw = _weekend_raw(fixture_raw)
    page.clock.set_fixed_time(MORNING)
    page.route("**/site-data.json*", lambda route: route.fulfill(json=raw))
    page.set_viewport_size({"width": 1440, "height": 900})
    open_app(page, query)


def _cfb_state(page: Page) -> dict[str, Any]:
    return page.evaluate("window.__testHooks.getState()")  # type: ignore[no-any-return]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("?view=weekend&wview=map", "map"),
        ("?view=weekend&wview=MAP", None),
        ("?view=weekend&wview=1", None),
        ("?view=weekend&wview=timeline", None),
        ("?view=crews&wview=map", None),
        ("?view=weekend", None),
    ],
)
def test_cfb_decode_allowlists_map(
    guarded_page: Page,
    fixture_raw: dict[str, Any],
    open_app: Callable[[Page, str], None],
    query: str,
    expected: str | None,
) -> None:
    _open_cfb(guarded_page, fixture_raw, open_app, query)
    assert _cfb_state(guarded_page)["wview"] == expected


def test_cfb_encode_only_on_weekend_with_map(
    guarded_page: Page,
    fixture_raw: dict[str, Any],
    open_app: Callable[[Page, str], None],
) -> None:
    _open_cfb(guarded_page, fixture_raw, open_app, "?view=weekend")
    page = guarded_page
    page.evaluate("window.__testHooks.setState({ wview: 'map' })")
    assert page.evaluate("location.search") == "?view=weekend&wview=map"
    page.evaluate("window.__testHooks.setState({ wview: null })")
    assert page.evaluate("location.search") == "?view=weekend"
    page.evaluate("window.__testHooks.setState({ wview: 'map', view: 'crews' })")
    assert "wview" not in page.evaluate("location.search")


def test_cfb_default_state_has_wview_null(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
) -> None:
    open_app(guarded_page, "")
    assert _cfb_state(guarded_page)["wview"] is None


# ---- NFL ----


def _open_nfl(page: Page, open_nfl_app: Callable[..., None], query: str) -> None:
    page.add_init_script(f"window.__nflWeekendNow = '{NFL_NOW}'")
    open_nfl_app(page, query)


def _nfl_state(page: Page) -> dict[str, Any]:
    return page.evaluate("window.__nflTestHooks.getState()")  # type: ignore[no-any-return]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("?sport=nfl&view=weekend&wview=map", "map"),
        ("?sport=nfl&view=weekend&wview=MAP", None),
        ("?sport=nfl&view=weekend&wview=1", None),
        ("?sport=nfl&view=weekend&wview=timeline", None),
        ("?sport=nfl&view=scatter&wview=map", None),
        ("?sport=nfl&wview=map&view=weekend", "map"),
        ("?sport=nfl&view=weekend", None),
    ],
)
def test_nfl_decode_allowlists_map(
    nfl_guarded_page: Page,
    open_nfl_app: Callable[..., None],
    query: str,
    expected: str | None,
) -> None:
    _open_nfl(nfl_guarded_page, open_nfl_app, query)
    assert _nfl_state(nfl_guarded_page)["wview"] == expected


def test_nfl_encode_and_leaving_clears_wview(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    _open_nfl(page, open_nfl_app, "?sport=nfl&view=weekend")
    page.evaluate("window.__nflTestHooks.setState({ wview: 'map' })")
    assert page.evaluate("location.search") == "?sport=nfl&view=weekend&wview=map"
    page.evaluate("window.__nflTestHooks.setState({ wview: null })")
    assert "wview" not in page.evaluate("location.search")
    page.evaluate("window.__nflTestHooks.setState({ wview: 'map' })")
    page.evaluate("window.__nflTestHooks.setState({ view: 'scatter' })")
    assert _nfl_state(page)["wview"] is None
    assert "wview" not in page.evaluate("location.search")
    page.evaluate("window.__nflTestHooks.setState({ view: 'weekend' })")
    assert _nfl_state(page)["wview"] is None


def test_nfl_default_state_has_wview_null(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    open_nfl_app(nfl_guarded_page, "?sport=nfl")
    assert _nfl_state(nfl_guarded_page)["wview"] is None
