"""DARK-01 (sport pages): the header toggle switches to the dark tokens, the choice
persists with no light frame, a blocked or invalid store reads light, and the
toggle is keyboard reachable and phone sized. The static pages carry the same toggle
behind a hash-pinned inline script."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from playwright.sync_api import Browser, Page

pytestmark = pytest.mark.e2e

_SPORT_PAGES = ("cfb", "nfl", "mlb")
_DARK_BG = "rgb(29, 27, 24)"
_LIGHT_BG = "rgb(251, 249, 245)"

_RECORD_JS = """
(() => {
  window.__themeLog = [];
  new MutationObserver(() => {
    window.__themeLog.push(document.documentElement.getAttribute('data-theme'));
  }).observe(document, { subtree: true, attributes: true, attributeFilter: ['data-theme'] });
  document.addEventListener('DOMContentLoaded', () => {
    window.__bgAtDcl = getComputedStyle(document.body).backgroundColor;
  });
})();
"""

_BLOCK_STORAGE_JS = """
(() => {
  const boom = () => { throw new DOMException('blocked', 'SecurityError'); };
  Storage.prototype.getItem = boom;
  Storage.prototype.setItem = boom;
})();
"""


@pytest.fixture
def opened(
    request: pytest.FixtureRequest,
    open_app: Callable[..., None],
    open_nfl_app: Callable[..., None],
    open_mlb_app: Callable[..., None],
) -> Callable[..., Page]:
    """open(which, init=None, size=None) -> the guarded sport page, with an optional
    init script registered before navigation and an optional (width, height)."""

    def _open(which: str, init: str | None = None, size: tuple[int, int] | None = None) -> Page:
        fixture, query = {
            "cfb": ("guarded_page", ""),
            "nfl": ("nfl_guarded_page", "?sport=nfl"),
            "mlb": ("mlb_guarded_page", "?sport=mlb"),
        }[which]
        page: Page = request.getfixturevalue(fixture)
        if init:
            page.context.add_init_script(init)
        if size:
            page.set_viewport_size({"width": size[0], "height": size[1]})
        opener = {"cfb": open_app, "nfl": open_nfl_app, "mlb": open_mlb_app}[which]
        opener(page, query)
        return page

    return _open


def _state(page: Page) -> dict[str, str | None]:
    result: dict[str, str | None] = page.evaluate(
        """() => ({
          theme: document.documentElement.getAttribute('data-theme'),
          bg: getComputedStyle(document.body).backgroundColor,
          scheme: getComputedStyle(document.documentElement).colorScheme,
          label: document.getElementById('theme-toggle').getAttribute('aria-label'),
          title: document.getElementById('theme-toggle').title,
        })"""
    )
    return result


@pytest.mark.parametrize("which", _SPORT_PAGES)
def test_toggle_switches_theme_and_back(opened: Callable[..., Page], which: str) -> None:
    page = opened(which)
    toggle = page.locator("#theme-toggle")
    assert _state(page) == {
        "theme": "light",
        "bg": _LIGHT_BG,
        "scheme": "light",
        "label": "Switch to dark theme",
        "title": "Switch to dark theme",
    }
    toggle.click()
    assert _state(page) == {
        "theme": "dark",
        "bg": _DARK_BG,
        "scheme": "dark",
        "label": "Switch to light theme",
        "title": "Switch to light theme",
    }
    assert toggle.get_attribute("aria-pressed") is None
    toggle.click()
    state = _state(page)
    assert state["theme"] == "light"
    assert state["bg"] == _LIGHT_BG
    assert state["label"] == "Switch to dark theme"


@pytest.mark.parametrize("which", _SPORT_PAGES)
def test_dark_choice_persists_across_reload_with_no_light_frame(
    opened: Callable[..., Page], which: str
) -> None:
    page = opened(which, init=_RECORD_JS)
    page.locator("#theme-toggle").click()
    assert page.evaluate("localStorage.getItem('bl-theme')") == "dark"
    page.reload()
    page.wait_for_function("document.getElementById('theme-toggle') !== null")
    assert page.evaluate("window.__themeLog[0]") == "dark"
    assert page.evaluate("window.__bgAtDcl") == _DARK_BG
    assert _state(page)["theme"] == "dark"


@pytest.mark.parametrize("which", _SPORT_PAGES)
def test_blocked_storage_loads_light_and_still_toggles(
    opened: Callable[..., Page], which: str
) -> None:
    errors: list[str] = []
    page = opened(which, init=_BLOCK_STORAGE_JS)
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    assert _state(page)["theme"] == "light"
    page.locator("#theme-toggle").click()
    state = _state(page)
    assert state["theme"] == "dark"
    assert state["bg"] == _DARK_BG
    assert errors == []


@pytest.mark.parametrize("stored", ["banana", "DARK"])
def test_invalid_stored_value_reads_light(opened: Callable[..., Page], stored: str) -> None:
    page = opened("cfb", init=f"localStorage.setItem('bl-theme', '{stored}');")
    state = _state(page)
    assert state["theme"] == "light"
    assert state["bg"] == _LIGHT_BG


@pytest.mark.parametrize("which", _SPORT_PAGES)
def test_keyboard_reaches_toggle_last_and_switches(opened: Callable[..., Page], which: str) -> None:
    page = opened(which)
    last_id = page.evaluate(
        """() => {
          const items = [...document.querySelectorAll(
            '#topbar a[href], #topbar button:not([hidden]), #topbar [tabindex]')];
          return items[items.length - 1].id;
        }"""
    )
    assert last_id == "theme-toggle"
    for _ in range(60):
        page.keyboard.press("Tab")
        if page.evaluate("document.activeElement && document.activeElement.id") == "theme-toggle":
            break
    else:
        pytest.fail("Tab never reached #theme-toggle")
    ring = page.evaluate(
        """() => {
          const s = getComputedStyle(document.activeElement);
          const a = getComputedStyle(document.documentElement).getPropertyValue('--accent');
          return [s.outlineWidth, s.outlineStyle, s.outlineColor, a.trim()];
        }"""
    )
    assert ring[0] == "2px"
    assert ring[1] == "solid"
    assert ring[2] == "rgb(27, 79, 92)"  # light --accent #1B4F5C
    page.keyboard.press("Enter")
    assert _state(page)["theme"] == "dark"
    page.keyboard.press("Space")
    assert _state(page)["theme"] == "light"


@pytest.mark.parametrize("which", _SPORT_PAGES)
def test_phone_toggle_is_top_right_with_44px_hit_area(
    opened: Callable[..., Page], which: str
) -> None:
    page = opened(which, size=(390, 844))
    header_before = page.locator("#topbar").bounding_box()
    box = page.locator("#theme-toggle").bounding_box()
    assert header_before is not None and box is not None
    assert box["width"] == 32 and box["height"] == 32
    assert box["x"] + box["width"] >= header_before["x"] + header_before["width"] - 24
    assert box["y"] < 60
    hit = page.evaluate(
        """() => {
          const s = getComputedStyle(document.getElementById('theme-toggle'), '::after');
          return [parseFloat(s.width), parseFloat(s.height)];
        }"""
    )
    assert hit[0] >= 44 and hit[1] >= 44
    page.locator("#theme-toggle").click()
    assert _state(page)["theme"] == "dark"
    header_after = page.locator("#topbar").bounding_box()
    assert header_after is not None
    assert header_after["height"] == header_before["height"]


_STATIC_PAGES = ("methodology", "coverage")


@pytest.mark.parametrize("which", _STATIC_PAGES)
def test_static_page_toggle_switches_theme_without_csp_errors(
    guarded_page: Page, site_url: str, which: str
) -> None:
    page = guarded_page
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(f"{site_url}/{which}.html")
    assert _state(page)["theme"] == "light"
    page.locator("#theme-toggle").click()
    assert _state(page) == {
        "theme": "dark",
        "bg": _DARK_BG,
        "scheme": "dark",
        "label": "Switch to light theme",
        "title": "Switch to light theme",
    }
    assert errors == []
    # The guard fixture also fails teardown on any CSP console error.


def test_dark_follows_the_user_from_the_sport_page_to_both_static_pages(
    opened: Callable[..., Page],
) -> None:
    page = opened("cfb", init=_RECORD_JS)
    page.locator("#theme-toggle").click()
    assert _state(page)["theme"] == "dark"
    page.locator(".header-links a[href='methodology.html']").click()
    page.wait_for_url("**/methodology.html")
    assert page.evaluate("window.__themeLog[0]") == "dark"
    assert _state(page)["theme"] == "dark"
    page.locator(".header-links a[href='coverage.html']").click()
    page.wait_for_url("**/coverage.html")
    assert page.evaluate("window.__themeLog[0]") == "dark"
    assert _state(page)["theme"] == "dark"


def test_stored_dark_renders_coverage_dark_at_domcontentloaded(
    guarded_page: Page, site_url: str
) -> None:
    guarded_page.context.add_init_script(_RECORD_JS)
    guarded_page.context.add_init_script("localStorage.setItem('bl-theme', 'dark');")
    guarded_page.goto(f"{site_url}/coverage.html")
    assert guarded_page.evaluate("window.__themeLog[0]") == "dark"
    # No later script blocks DCL on a static page, so the stylesheet may land after it:
    # check the attribute that drives the tokens, then the painted ground once loaded.
    assert _state(guarded_page)["theme"] == "dark"
    assert _state(guarded_page)["bg"] == _DARK_BG


def test_without_javascript_coverage_is_light_and_toggle_hidden(
    browser: Browser, site_url: str
) -> None:
    context = browser.new_context(java_script_enabled=False)
    try:
        page = context.new_page()
        page.goto(f"{site_url}/coverage.html")
        assert page.locator("#theme-toggle").is_visible() is False
        assert page.locator("html").get_attribute("data-theme") == "light"
    finally:
        context.close()


def test_dark_theme_prints_with_the_light_tokens(guarded_page: Page, site_url: str) -> None:
    # Review 6e: a dark-theme page prints light: the light ink on white-ish paper, light scheme.
    page = guarded_page
    page.context.add_init_script("localStorage.setItem('bl-theme', 'dark');")
    page.goto(f"{site_url}/methodology.html")
    assert _state(page)["theme"] == "dark"
    assert page.evaluate("getComputedStyle(document.body).color") == "rgb(236, 231, 223)"
    page.emulate_media(media="print")
    got = page.evaluate(
        """() => ({
          ink: getComputedStyle(document.body).color,
          bg: getComputedStyle(document.body).backgroundColor,
          scheme: getComputedStyle(document.documentElement).colorScheme,
          theme: document.documentElement.dataset.theme,
        })"""
    )
    assert got == {"ink": "rgb(35, 32, 27)", "bg": _LIGHT_BG, "scheme": "light", "theme": "dark"}
