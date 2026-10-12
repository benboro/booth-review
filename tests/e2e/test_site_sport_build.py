"""Static checks of the sport switch and the NFL build flag (D-18, D-19):
the flag-off build has no switch and no NFL files; the flag-on build has the
data-driven CFB | NFL switch and nfl-data.json. App behavior is tested in
later plans.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e


def test_flag_off_build_has_no_switch_and_no_nfl_files(
    guarded_page: Page, site_url: str, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    assert guarded_page.locator("#sport-switch").count() == 0
    meta = guarded_page.locator('meta[name="booth-review-sports"]')
    assert meta.get_attribute("content") == "cfb"
    for path in ("sports/nfl/index.js", "nfl-data.json"):
        assert guarded_page.request.get(f"{site_url}/{path}").status == 404


def test_flag_on_build_has_the_switch(
    nfl_guarded_page: Page, nfl_site_url: str, open_flagon_cfb: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    open_flagon_cfb(page)
    switch = page.locator("#topbar #sport-switch")
    assert switch.get_attribute("role") == "group"
    assert switch.get_attribute("aria-label") == "Sport"
    buttons = switch.locator("button")
    assert buttons.count() == 2
    assert [buttons.nth(i).inner_text() for i in range(2)] == ["CFB", "NFL"]
    assert [buttons.nth(i).get_attribute("aria-pressed") for i in range(2)] == ["true", "false"]
    meta = page.locator('meta[name="booth-review-sports"]')
    assert meta.get_attribute("content") == "cfb,nfl"
    assert page.request.get(f"{nfl_site_url}/nfl-data.json").status == 200


def test_flag_on_cfb_page_still_boots_clean(
    nfl_guarded_page: Page, open_flagon_cfb: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    open_flagon_cfb(page)
    assert page.evaluate("window.__testHooks.ready") is True
    assert page.evaluate("window.location.search") == ""
    assert errors == []
