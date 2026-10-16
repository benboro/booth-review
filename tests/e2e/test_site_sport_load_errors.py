"""WR3-09: a second sport's load failure replaces the first sport's error banner."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e


def _click(page: Page, sport: str) -> None:
    page.click(f'#sport-switch button[data-sport="{sport}"]')


def test_a_second_failure_shows_its_own_sport_and_reload_target(
    both_guarded_page: Page, both_site_url: str
) -> None:
    page = both_guarded_page
    page.route("**/sports/nfl/index.js", lambda route: route.abort())
    page.route("**/sports/mlb/index.js", lambda route: route.abort())
    page.goto(f"{both_site_url}/index.html")
    page.wait_for_function("window.__testHooks && window.__testHooks.ready === true")

    _click(page, "nfl")
    page.wait_for_selector("#sport-load-error[data-sport='nfl']", state="visible")
    assert "NFL" in page.inner_text("#sport-load-error")

    _click(page, "mlb")
    page.wait_for_selector("#sport-load-error[data-sport='mlb']", state="visible")
    assert page.locator("#sport-load-error").count() == 1
    text = page.inner_text("#sport-load-error")
    assert "MLB" in text and "NFL" not in text
    assert page.evaluate("location.search") == "?sport=mlb"

    # The Reload button now targets MLB, not the first failure's sport.
    page.unroute("**/sports/mlb/index.js")
    with page.expect_navigation():
        page.get_by_role("button", name="Reload page").click()
    page.wait_for_function("window.__mlbTestHooks && window.__mlbTestHooks.ready === true")
    assert page.evaluate("location.search").startswith("?sport=mlb")
