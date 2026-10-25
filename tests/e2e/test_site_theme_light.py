"""SHELL-01 / SHELL-02: the site is light-only whatever the OS prefers, and the
`#theme-slot` holds the one 32x32 theme toggle at the right end of every sport
page's header (none on the static pages)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

_PAGES = ("cfb", "nfl", "mlb", "methodology", "coverage")
_SPORT_PAGES = ("cfb", "nfl", "mlb")

_NO_DARK_RULES_JS = """
() => {
  const bad = [];
  for (const sheet of document.styleSheets) {
    let rules;
    try { rules = sheet.cssRules; } catch (e) { continue; }
    for (const rule of rules) {
      if (rule.cssText.includes('prefers-color-scheme')) bad.push(rule.cssText.slice(0, 80));
    }
  }
  return bad;
}
"""


@pytest.fixture(scope="module")
def browser_context_args(browser_context_args: dict[str, Any]) -> dict[str, Any]:
    """Every test here runs with the OS asking for dark."""
    return {
        **browser_context_args,
        "color_scheme": "dark",
        "viewport": {"width": 1280, "height": 900},
    }


@pytest.fixture
def opened(
    request: pytest.FixtureRequest,
    open_app: Callable[..., None],
    open_nfl_app: Callable[..., None],
    open_mlb_app: Callable[..., None],
) -> Callable[[str], Page]:
    """Returns open(which) -> the guarded page, loaded on that sport or static page."""

    def _open(which: str) -> Page:
        if which == "cfb":
            page: Page = request.getfixturevalue("guarded_page")
            open_app(page, "")
        elif which == "nfl":
            page = request.getfixturevalue("nfl_guarded_page")
            open_nfl_app(page, "?sport=nfl")
        elif which == "mlb":
            page = request.getfixturevalue("mlb_guarded_page")
            open_mlb_app(page, "?sport=mlb")
        else:
            page = request.getfixturevalue("guarded_page")
            site_url: str = request.getfixturevalue("site_url")
            page.goto(f"{site_url}/{which}.html")
            page.evaluate("document.fonts.ready")
        return page

    return _open


@pytest.mark.parametrize("which", _PAGES)
def test_os_dark_still_renders_light(opened: Callable[[str], Page], which: str) -> None:
    page = opened(which)
    assert page.evaluate("matchMedia('(prefers-color-scheme: dark)').matches") is True
    assert page.evaluate("document.documentElement.getAttribute('data-theme')") == "light"
    assert page.evaluate("getComputedStyle(document.body).backgroundColor") == "rgb(251, 249, 245)"
    assert page.evaluate("getComputedStyle(document.documentElement).colorScheme") == "light"
    assert page.evaluate(_NO_DARK_RULES_JS) == []
    if which in ("methodology", "coverage"):
        assert page.evaluate("document.fonts.check('600 20px \"Crimson Text\"')") is True
    # The guard fixture fails the test on teardown for any off-origin request or CSP error.


@pytest.mark.parametrize("which", _SPORT_PAGES)
def test_theme_slot_holds_one_toggle_at_the_header_right(
    opened: Callable[[str], Page], which: str
) -> None:
    page = opened(which)
    slot = page.locator("#theme-slot")
    assert slot.count() == 1
    assert slot.locator("#theme-toggle").count() == 1
    assert page.locator("#theme-toggle").count() == 1
    assert slot.locator("#theme-toggle").is_visible()
    # The toggle must stay visible to assistive tech.
    assert slot.get_attribute("aria-hidden") is None
    toggle = slot.locator("#theme-toggle").bounding_box()
    assert toggle is not None
    assert round(toggle["width"]) == 32
    assert round(toggle["height"]) == 32
    box = slot.bounding_box()
    assert box is not None
    assert round(box["width"]) == 32
    assert round(box["height"]) == 32
    rights: list[float] = page.evaluate(
        """() => [...document.querySelector('#topbar').children]
             .map((el) => el.getBoundingClientRect())
             .filter((r) => r.width > 0)
             .map((r) => r.right)"""
    )
    assert box["x"] + box["width"] >= max(rights) - 0.5


@pytest.mark.parametrize("which", ("methodology", "coverage"))
def test_static_pages_hold_one_toggle(opened: Callable[[str], Page], which: str) -> None:
    page = opened(which)
    slot = page.locator("#theme-slot")
    assert slot.count() == 1
    assert page.locator("#theme-toggle").count() == 1
    assert slot.locator("#theme-toggle").count() == 1
    assert slot.locator("#theme-toggle").is_visible()
    toggle = slot.locator("#theme-toggle").bounding_box()
    assert toggle is not None
    assert round(toggle["width"]) == 32
    assert round(toggle["height"]) == 32
    box = slot.bounding_box()
    assert box is not None
    rights: list[float] = page.evaluate(
        """() => [...document.querySelector('.site-header').children]
             .map((el) => el.getBoundingClientRect())
             .filter((r) => r.width > 0)
             .map((r) => r.right)"""
    )
    assert box["x"] + box["width"] >= max(rights) - 0.5


@pytest.mark.parametrize("which", ("methodology", "coverage"))
def test_static_page_toggle_stays_top_right_on_a_phone(
    opened: Callable[[str], Page], which: str
) -> None:
    # Review F3: at 480px and below the header links are hidden; the static pages' header has
    # no #topbar, so the slot must push itself to the right edge.
    page = opened(which)
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(50)
    got: dict[str, float] = page.evaluate(
        """() => {
          const header = document.querySelector('.site-header');
          const h = header.getBoundingClientRect();
          const s = document.getElementById('theme-slot').getBoundingClientRect();
          const title = document.querySelector('.site-title').getBoundingClientRect();
          return {
            contentRight: h.right - parseFloat(getComputedStyle(header).paddingRight),
            slotRight: s.right,
            slotTop: s.top,
            titleTop: title.top,
            titleBottom: title.bottom,
          };
        }"""
    )
    assert abs(got["slotRight"] - got["contentRight"]) <= 1, got
    # Still on the title's row.
    assert got["titleTop"] - 16 <= got["slotTop"] <= got["titleBottom"], got
