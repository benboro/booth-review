"""Networks rollup by family (04.16 D-10..D-14): families open collapsed, a caret
expands one without touching the selection, a collapsed partly-on family shows an
"N of M on" hint, single-channel families keep a blank caret slot, and the phone
drawer matches. Synthetic contract fixture only.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable

import pytest
from conftest import FONT_CSS, _assert_guard_clean, _install_guard, expand_family
from playwright.sync_api import Browser, Page, Route, expect

pytestmark = pytest.mark.e2e

CARET = ".family-caret[data-family='disney']"
DISNEY_HINT = "fieldset.family-group:has(input[data-family-checkbox='disney']) .family-on-hint"


def _open_networks(page: Page) -> None:
    page.click("#trigger-networks")
    page.wait_for_function("document.getElementById('pop-networks').matches(':popover-open')")


def _open_sheet(page: Page) -> None:
    page.click("#filters-button")
    page.wait_for_function("document.getElementById('filters-sheet').matches(':popover-open')")


def _networks(page: Page) -> list[str] | None:
    return page.evaluate("window.__testHooks.getState().networks")


def _storage(page: Page) -> str:
    return page.evaluate("JSON.stringify([{...localStorage}, {...sessionStorage}])")


def _assert_all_collapsed(page: Page) -> None:
    carets = page.locator(".family-caret")
    assert carets.count() == 1
    expect(carets.first).to_have_attribute("aria-expanded", "false")
    for ul in page.locator("ul.network-list").all():
        expect(ul).to_be_hidden()
    expect(page.locator("input[data-network-id]:visible")).to_have_count(0)


def test_popover_opens_with_every_family_collapsed(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    _open_networks(guarded_page)
    _assert_all_collapsed(guarded_page)
    assert guarded_page.locator(".family-caret-spacer").count() == 3
    # Expand, reopen, and read the very first frame at beforetoggle time.
    expand_family(guarded_page, "disney")
    guarded_page.keyboard.press("Escape")
    guarded_page.wait_for_function(
        "!document.getElementById('pop-networks').matches(':popover-open')"
    )
    snapshot = guarded_page.evaluate(
        """() => {
          document.getElementById('trigger-networks').click();
          return {
            expanded: document.querySelector('.family-caret').getAttribute('aria-expanded'),
            hidden: document.getElementById('family-rows-disney').hidden,
          };
        }"""
    )
    assert snapshot == {"expanded": "false", "hidden": True}


def test_reopen_collapses_again(guarded_page: Page, open_app: Callable[[Page, str], None]) -> None:
    open_app(guarded_page, "")
    _open_networks(guarded_page)
    expand_family(guarded_page, "disney")
    guarded_page.keyboard.press("Escape")
    guarded_page.wait_for_function(
        "!document.getElementById('pop-networks').matches(':popover-open')"
    )
    _open_networks(guarded_page)
    _assert_all_collapsed(guarded_page)
    expand_family(guarded_page, "disney")
    guarded_page.mouse.click(5, 5)
    guarded_page.wait_for_function(
        "!document.getElementById('pop-networks').matches(':popover-open')"
    )
    _open_networks(guarded_page)
    _assert_all_collapsed(guarded_page)


def test_caret_toggles_rows_without_changing_networks(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?networks=net-a,net-b")
    _open_networks(guarded_page)
    before = (_networks(guarded_page), guarded_page.evaluate("location.search"))
    caret = guarded_page.locator(CARET)
    caret.click()
    expect(caret).to_have_attribute("aria-expanded", "true")
    expect(caret).to_have_attribute("title", "Hide channels")
    expect(guarded_page.locator("#family-rows-disney")).to_be_visible()
    expect(guarded_page.locator("input[data-network-id='net-a']")).to_be_visible()
    expect(guarded_page.locator("input[data-network-id='net-e']")).to_be_visible()
    assert (_networks(guarded_page), guarded_page.evaluate("location.search")) == before
    caret.click()
    expect(caret).to_have_attribute("aria-expanded", "false")
    expect(caret).to_have_attribute("title", "Show channels")
    expect(guarded_page.locator("#family-rows-disney")).to_be_hidden()
    assert (_networks(guarded_page), guarded_page.evaluate("location.search")) == before


def test_family_checkbox_still_toggles_the_family_and_not_the_collapse(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    _open_networks(guarded_page)
    guarded_page.locator("input[data-family-checkbox='disney']").uncheck()
    guarded_page.wait_for_function(
        "!(window.__testHooks.getState().networks ?? ['net-a']).includes('net-a')"
    )
    nets = _networks(guarded_page) or []
    assert "net-a" not in nets
    assert "net-e" not in nets
    expect(guarded_page.locator(CARET)).to_have_attribute("aria-expanded", "false")
    guarded_page.locator(".check-item:has(input[data-family-checkbox='disney']) .only-btn").click()
    guarded_page.wait_for_function(
        "JSON.stringify(window.__testHooks.getState().networks.slice().sort())"
        " === JSON.stringify(['net-a','net-e'])"
    )


def test_partial_family_hint(guarded_page: Page, open_app: Callable[[Page, str], None]) -> None:
    open_app(guarded_page, "?networks=net-a,net-b")
    _open_networks(guarded_page)
    hint = guarded_page.locator(DISNEY_HINT)
    expect(guarded_page.locator("input[data-family-checkbox='disney']")).to_have_js_property(
        "indeterminate", True
    )
    expect(hint).to_be_visible()
    expect(hint).to_have_text("1 of 2 on")
    guarded_page.locator(CARET).click()
    expect(hint).to_be_hidden()
    guarded_page.locator(CARET).click()
    expect(hint).to_be_visible()
    for query in ("?networks=net-a,net-e,net-b", "?networks=net-b"):
        open_app(guarded_page, query)
        _open_networks(guarded_page)
        expect(guarded_page.locator(DISNEY_HINT)).to_be_hidden()


def test_hint_stays_out_of_the_checkbox_name(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?networks=net-a,net-b")
    _open_networks(guarded_page)
    box = guarded_page.locator("input[data-family-checkbox='disney']")
    expect(guarded_page.locator(DISNEY_HINT)).to_be_visible()
    expect(box).not_to_have_accessible_name(re.compile(r"of 2 on"))
    expect(box).to_have_accessible_name(re.compile(r"^ABC/ESPN"))


def _x(page: Page, family: str) -> float:
    box = page.locator(f"input[data-family-checkbox='{family}']").bounding_box()
    assert box is not None
    return box["x"]


def _check_single_channel(page: Page) -> None:
    fox_row = page.locator(".check-item:has(input[data-family-checkbox='fox'])")
    assert fox_row.locator(".family-caret").count() == 0
    assert fox_row.locator(".family-caret-spacer").count() == 1
    expand_family(page, "disney")
    expect(page.locator("#family-rows-fox")).to_be_hidden()
    assert abs(_x(page, "fox") - _x(page, "disney")) <= 1


def test_single_channel_family_has_no_caret_and_aligns(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    guarded_page.set_viewport_size({"width": 1280, "height": 900})
    open_app(guarded_page, "")
    _open_networks(guarded_page)
    _check_single_channel(guarded_page)


def test_single_channel_family_aligns_on_phone(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(mobile_page, "")
    _open_sheet(mobile_page)
    _check_single_channel(mobile_page)


def test_keyboard_enter_and_space_toggle_the_caret(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    _open_networks(guarded_page)
    first = guarded_page.evaluate("document.activeElement.matches('input[data-family-checkbox]')")
    assert first
    caret = guarded_page.locator(CARET)
    caret.focus()
    guarded_page.keyboard.press("Enter")
    expect(caret).to_have_attribute("aria-expanded", "true")
    guarded_page.keyboard.press("Space")
    expect(caret).to_have_attribute("aria-expanded", "false")
    assert guarded_page.evaluate("document.activeElement.classList.contains('family-caret')")


def test_collapse_is_not_stored(guarded_page: Page, open_app: Callable[[Page, str], None]) -> None:
    open_app(guarded_page, "")
    _open_networks(guarded_page)
    url, store = guarded_page.evaluate("location.search"), _storage(guarded_page)
    expand_family(guarded_page, "disney")
    assert guarded_page.evaluate("location.search") == url
    assert _storage(guarded_page) == store
    json.loads(store)


def test_phone_drawer_rows_collapse_and_carets_are_touch_targets(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(mobile_page, "")
    _open_sheet(mobile_page)
    _assert_all_collapsed(mobile_page)
    box = mobile_page.locator(CARET).bounding_box()
    assert box is not None
    assert box["width"] >= 44
    assert box["height"] >= 44
    mobile_page.locator(CARET).tap()
    expect(mobile_page.locator(CARET)).to_have_attribute("aria-expanded", "true")
    expect(mobile_page.locator("#family-rows-disney")).to_be_visible()
    assert mobile_page.evaluate(
        "(() => { const b = document.querySelector('#filters-sheet .sheet-body');"
        " return b.scrollWidth <= b.clientWidth; })()"
    )
    mobile_page.click("#filters-show-results")
    mobile_page.wait_for_function(
        "!document.getElementById('filters-sheet').matches(':popover-open')"
    )
    _open_sheet(mobile_page)
    _assert_all_collapsed(mobile_page)


def test_trigger_label_still_counts_channels(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?networks=net-a,net-b")
    trigger = guarded_page.locator("#trigger-networks")
    label = trigger.inner_text()
    _open_networks(guarded_page)
    guarded_page.locator(CARET).click()
    assert trigger.inner_text() == label
    guarded_page.locator(CARET).click()
    assert trigger.inner_text() == label


def test_narrow_phone_hint_wraps_under_the_name_without_scrolling(
    browser: Browser, site_url: str, open_app: Callable[[Page, str], None]
) -> None:
    """04.16 D-12 at 360px with the widest font: a partly-on family keeps its "N of M on" hint,
    the hint wraps under the name, and the drawer never scrolls sideways."""
    context = browser.new_context(
        viewport={"width": 360, "height": 800}, has_touch=True, is_mobile=True
    )
    page = context.new_page()
    off_origin, csp_errors = _install_guard(page, site_url)

    def _route(route: Route) -> None:
        response = route.fetch()
        route.fulfill(response=response, body=response.text() + "\n" + FONT_CSS["wide"])

    page.route("**/style.css*", _route)
    try:
        open_app(page, "")
        _open_sheet(page)
        page.locator(f"#filters-sheet {CARET}").tap()
        page.locator("#filters-sheet #family-rows-disney input[data-network-id]").first.uncheck()
        page.locator(f"#filters-sheet {CARET}").tap()
        hint = page.locator(f"#filters-sheet {DISNEY_HINT}")
        expect(hint).to_be_visible()
        fits = page.evaluate(
            "(() => { const b = document.querySelector('#filters-sheet .sheet-body');"
            " return b.scrollWidth <= b.clientWidth; })()"
        )
        name_box = page.locator(
            "#filters-sheet .family-item:has(input[data-family-checkbox='disney']) .option-name"
        ).bounding_box()
        hint_box = hint.bounding_box()
        assert fits
        assert name_box is not None
        assert hint_box is not None
        assert hint_box["y"] >= name_box["y"] + name_box["height"] - 1
    finally:
        context.close()
    _assert_guard_clean(off_origin, csp_errors)
