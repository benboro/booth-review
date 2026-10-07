"""Double-click / double-tap on a network legend pill (04.15 D-05..D-08).

D-05: a second click on the same pill isolates the family; one click stays instant;
no history entry is added. D-06: the result equals the Networks popover family
Only/All button. D-07: two taps within 300ms count as a double-click; pills carry
`touch-action: manipulation`. D-08: `title` / `aria-description` hints, no visible
caption. Synthetic fixtures only.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

OpenApp = Callable[[Page, str], None]

URL = "?school=northfield"
CHIPS = "#legend-chips button[data-family]"

_SYNTHETIC_CLICKS = """
([family, details]) => {
  for (const detail of details) {
    const pill = document.querySelector(
      `#legend-chips button[data-family='${family}']`);
    pill.dispatchEvent(new MouseEvent('click', {bubbles: true, detail}));
  }
}
"""

_SYNTHETIC_CLICKS_ON = """
([families, detail]) => {
  for (const family of families) {
    const pill = document.querySelector(
      `#legend-chips button[data-family='${family}']`);
    pill.dispatchEvent(new MouseEvent('click', {bubbles: true, detail}));
  }
}
"""


def _pill(page: Page, family: str) -> Any:
    return page.locator(f"#legend-chips button[data-family='{family}']")


def _state(page: Page) -> dict[str, Any]:
    return page.evaluate("window.__testHooks.getState()")  # type: ignore[no-any-return]


def _networks(page: Page) -> list[str] | None:
    nets = _state(page)["networks"]
    return None if nets is None else sorted(nets)


def _families(page: Page, offered: bool = True) -> list[str]:
    return page.eval_on_selector_all(  # type: ignore[no-any-return]
        CHIPS,
        "(els, offered) => els.filter(e => (e.dataset.offered === 'true') === offered)"
        ".map(e => e.dataset.family)",
        offered,
    )


def _synthetic_double(page: Page, family: str, details: list[int]) -> None:
    """Dispatch clicks in one evaluate, re-querying the pill (the first click rerenders it)."""
    page.evaluate(_SYNTHETIC_CLICKS, [family, details])


def _popover_only(page: Page, family: str) -> list[str] | None:
    page.click("#trigger-networks")
    page.wait_for_function("document.getElementById('pop-networks').matches(':popover-open')")
    page.locator(f".check-item:has(input[data-family-checkbox='{family}']) .only-btn").click()
    page.keyboard.press("Escape")
    return _networks(page)


def test_mouse_double_click_isolates_family_like_only(
    guarded_page: Page, open_app: OpenApp
) -> None:
    page = guarded_page
    open_app(page, URL)
    families = _families(page)
    assert families
    for family in families:
        open_app(page, URL)
        expected = _popover_only(page, family)
        open_app(page, URL)
        _pill(page, family).dblclick()
        page.wait_for_function("window.__testHooks.getState().networks !== null")
        assert _networks(page) == expected, family


def test_double_click_on_the_only_family_restores_all(
    guarded_page: Page, open_app: OpenApp
) -> None:
    page = guarded_page
    open_app(page, URL)
    family = _families(page)[0]
    _pill(page, family).dblclick()
    page.wait_for_function("window.__testHooks.getState().networks !== null")
    page.wait_for_timeout(350)
    _pill(page, family).dblclick()
    page.wait_for_function("window.__testHooks.getState().networks === null")
    assert _networks(page) is None


def test_narrowed_channel_becomes_the_family_offered_set(
    guarded_page: Page, open_app: OpenApp, serve_multichannel: Callable[..., None]
) -> None:
    page = guarded_page
    serve_multichannel(page)
    open_app(page, URL + "&networks=net-a")
    assert _networks(page) == ["net-a"]
    _pill(page, "disney").dblclick()
    page.wait_for_function("window.__testHooks.getState().networks.length === 2")
    assert _networks(page) == ["net-a", "net-e"]


def test_greyed_family_double_click_changes_nothing(
    guarded_page: Page, open_app: OpenApp, fixture_raw: dict[str, Any]
) -> None:
    page = guarded_page
    raw = copy.deepcopy(fixture_raw)
    nets = raw["telecasts"]["network"]
    raw["telecasts"]["network"] = [0] * len(nets)
    page.route("**/site-data.json*", lambda route: route.fulfill(json=raw))
    open_app(page, URL)
    greyed = _families(page, offered=False)
    assert greyed
    family = greyed[0]
    before = _networks(page)
    _synthetic_double(page, family, [1, 2])
    page.wait_for_timeout(100)
    assert _networks(page) == before
    # A single click still toggles the greyed family.
    page.wait_for_timeout(350)
    _pill(page, family).click()
    page.wait_for_function(
        "(b) => JSON.stringify(window.__testHooks.getState().networks) !== b",
        arg=json.dumps(before),
    )


def test_double_click_adds_no_history_entry(guarded_page: Page, open_app: OpenApp) -> None:
    page = guarded_page
    open_app(page, URL)
    length = page.evaluate("history.length")
    _pill(page, _families(page)[0]).dblclick()
    page.wait_for_function("window.__testHooks.getState().networks !== null")
    assert page.evaluate("history.length") == length
    assert page.evaluate("location.search.split('networks=').length - 1") == 1


def test_synthetic_double_tap_isolates_and_different_pills_do_not(
    mobile_page: Page, open_app: OpenApp
) -> None:
    page = mobile_page
    open_app(page, URL)
    families = _families(page)
    assert len(families) >= 2
    first, second = families[0], families[1]
    # The Networks popover is desktop-only; [1, 2] is the reference result.
    open_app(page, URL)
    _synthetic_double(page, first, [1, 2])
    expected = _networks(page)
    assert expected is not None
    open_app(page, URL)
    _synthetic_double(page, first, [1, 1])
    assert _networks(page) == expected
    # Two different pills: both just toggle.
    open_app(page, URL)
    page.evaluate(_SYNTHETIC_CLICKS_ON, [[first, second], 1])
    toggled = _state(page)["networks"]
    assert toggled is not None
    assert sorted(toggled) != expected
    assert _pill(page, first).get_attribute("aria-pressed") == "false"
    assert _pill(page, second).get_attribute("aria-pressed") == "false"
    # A real tap toggles once, instantly.
    open_app(page, URL)
    _pill(page, first).tap()
    page.wait_for_function("window.__testHooks.getState().networks !== null")
    assert _pill(page, first).get_attribute("aria-pressed") == "false"


def test_keyboard_never_counts_as_double(guarded_page: Page, open_app: OpenApp) -> None:
    page = guarded_page
    open_app(page, URL)
    family = _families(page)[0]
    start = _networks(page)
    _pill(page, family).focus()
    page.keyboard.press("Enter")
    page.wait_for_function("window.__testHooks.getState().networks !== null")
    off = _networks(page)
    assert _pill(page, family).get_attribute("aria-pressed") == "false"
    page.locator(f"#legend-chips button[data-family='{family}']").focus()
    page.keyboard.press("Enter")
    page.wait_for_function("window.__testHooks.getState().networks === null")
    assert _networks(page) == start
    assert off is not None


def test_triple_click_does_not_toggle_again(guarded_page: Page, open_app: OpenApp) -> None:
    page = guarded_page
    open_app(page, URL)
    family = _families(page)[0]
    _synthetic_double(page, family, [1, 2])
    isolated = _networks(page)
    assert isolated is not None
    _synthetic_double(page, family, [3])
    page.wait_for_timeout(100)
    assert _networks(page) == isolated


def test_pill_hint_title_and_aria_description(guarded_page: Page, open_app: OpenApp) -> None:
    page = guarded_page
    open_app(page, URL)
    before = page.locator("#legend-row").bounding_box()
    pills = page.locator(CHIPS)
    for i in range(pills.count()):
        pill = pills.nth(i)
        label = pill.inner_text().strip()
        hint = f"Double-click to show only {label}"
        assert pill.get_attribute("title") == hint
        assert pill.get_attribute("aria-description") == hint
        assert pill.evaluate("e => getComputedStyle(e).touchAction") == "manipulation"
        assert pill.evaluate("e => getComputedStyle(e).userSelect") == "none"
    family = _families(page)[0]
    _pill(page, family).dblclick()
    page.wait_for_function("window.__testHooks.getState().networks !== null")
    pill = _pill(page, family)
    assert pill.get_attribute("title") == "Double-click to show all networks"
    assert pill.get_attribute("aria-description") == "Double-click to show all networks"
    assert page.locator("#legend-row").bounding_box() == before
