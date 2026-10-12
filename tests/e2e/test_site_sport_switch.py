"""999.5-11: the CFB | NFL switch, sport resolution, state handoff and request separation."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e


def _track(page: Page) -> list[str]:
    urls: list[str] = []
    page.on("request", lambda r: urls.append(r.url))
    return urls


def _count(urls: list[str], name: str) -> int:
    return sum(1 for u in urls if name in u.split("?")[0])


def _click(page: Page, sport: str) -> None:
    page.click(f'#sport-switch button[data-sport="{sport}"]')


def _pressed(page: Page, sport: str) -> str | None:
    return page.get_attribute(f'#sport-switch button[data-sport="{sport}"]', "aria-pressed")


def test_cfb_load_never_requests_nfl_data(
    nfl_guarded_page: Page, open_flagon_cfb: Callable[..., None]
) -> None:
    urls = _track(nfl_guarded_page)
    open_flagon_cfb(nfl_guarded_page)
    assert _count(urls, "nfl-data.json") == 0
    assert nfl_guarded_page.evaluate("location.search") == ""
    assert _pressed(nfl_guarded_page, "cfb") == "true"


def test_click_nfl_mounts_and_sets_url_title(
    nfl_guarded_page: Page, open_flagon_cfb: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    urls = _track(page)
    open_flagon_cfb(page)
    _click(page, "nfl")
    page.wait_for_function("window.__nflTestHooks && window.__nflTestHooks.ready === true")
    assert _pressed(page, "nfl") == "true"
    assert _pressed(page, "cfb") == "false"
    assert page.inner_text("#sport-status") == "Showing NFL games."
    assert "NFL" in page.title()
    assert page.evaluate("location.search") == "?sport=nfl"
    assert _count(urls, "nfl-data.json") == 1


def test_direct_nfl_never_requests_site_data(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    urls = _track(page)
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    open_nfl_app(page)
    assert _count(urls, "nfl-data.json") == 1
    assert _count(urls, "site-data.json") == 0
    assert _pressed(page, "nfl") == "true"
    assert errors == []


def test_cfb_state_round_trip(nfl_guarded_page: Page, open_flagon_cfb: Callable[..., None]) -> None:
    page = nfl_guarded_page
    open_flagon_cfb(page)
    page.evaluate("window.__testHooks.setState({ view: 'bars' })")
    state = page.evaluate("window.__testHooks.getState()")
    search = page.evaluate("location.search")
    assert "view=bars" in search
    _click(page, "nfl")
    page.wait_for_function("window.__nflTestHooks && window.__nflTestHooks.ready === true")
    _click(page, "cfb")
    page.wait_for_function("location.search === " + repr(search))
    assert page.evaluate("window.__testHooks.getState()") == state
    assert "NFL" not in page.title()
    assert page.evaluate("document.body.dataset.sport") == "cfb"


def test_nfl_state_kept_across_cfb_detour(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    open_nfl_app(page)
    page.evaluate("window.__nflTestHooks.setState({ view: 'fox' })")
    _click(page, "cfb")
    page.wait_for_function("window.__testHooks && window.__testHooks.ready === true")
    assert "sport=nfl" not in page.evaluate("location.search")
    _click(page, "nfl")
    page.wait_for_function("location.search.includes('sport=nfl')")
    assert page.evaluate("window.__nflTestHooks.getState().view") == "fox"
    assert "view=fox" in page.evaluate("location.search")
