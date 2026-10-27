"""Phase 26 type swap: Latin Modern Demi renders in every serif slot on every page, loads
same-origin under the unchanged CSP, and the guard fixtures see no off-origin request."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

_OLD = "crim" + "son"
_FACE = '"Latin Modern Demi"'
_CHECK_JS = (
    "document.fonts.ready.then(() => document.fonts.check('600 22px \"Latin Modern Demi\"'))"
)
_STYLE_JS = """(sel) => {
  const el = document.querySelector(sel);
  if (!el) return null;
  const cs = getComputedStyle(el);
  return {family: cs.fontFamily, weight: cs.fontWeight, synthesis: cs.fontSynthesis};
}"""
_PRELOAD_JS = (
    "[...document.querySelectorAll('link[rel=preload][as=font]')]"
    ".map((l) => l.getAttribute('href'))"
)


def _assert_serif(page: Page, selector: str) -> None:
    got = page.evaluate(_STYLE_JS, selector)
    assert got is not None, f"{selector} not found"
    assert got["family"].startswith(_FACE), (selector, got)
    assert got["weight"] == "600", (selector, got)


def _assert_loaded(page: Page) -> None:
    assert page.evaluate(_CHECK_JS) is True


def test_cfb_serif_slots_and_preload(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    _assert_loaded(guarded_page)
    for selector in (".site-title", ".summary-count", ".module-title"):
        _assert_serif(guarded_page, selector)
    guarded_page.evaluate("window.__testHooks.openPanel(2)")
    guarded_page.wait_for_function("document.getElementById('detail-panel').open")
    _assert_serif(guarded_page, "#panel-title")
    preloads = guarded_page.evaluate(_PRELOAD_JS)
    assert any(h.endswith("lm-roman-demi-latin-600-normal.woff2") for h in preloads), preloads
    assert not any(_OLD in h for h in preloads)
    html_synthesis = guarded_page.evaluate(
        "getComputedStyle(document.documentElement).fontSynthesis"
    )
    assert "none" in html_synthesis


def test_nfl_serif_slots(nfl_guarded_page: Page, open_nfl_app: Callable[..., None]) -> None:
    open_nfl_app(nfl_guarded_page, "?sport=nfl")
    _assert_loaded(nfl_guarded_page)
    for selector in (".site-title", "#nfl-summary"):
        _assert_serif(nfl_guarded_page, selector)


def test_mlb_serif_slots(mlb_guarded_page: Page, open_mlb_app: Callable[..., None]) -> None:
    open_mlb_app(mlb_guarded_page, "?sport=mlb")
    _assert_loaded(mlb_guarded_page)
    for selector in (".site-title", "#mlb-summary"):
        _assert_serif(mlb_guarded_page, selector)


@pytest.mark.parametrize("page_name", ["methodology", "coverage"])
def test_static_page_serif_slots(guarded_page: Page, site_url: str, page_name: str) -> None:
    guarded_page.goto(f"{site_url}/{page_name}.html")
    _assert_loaded(guarded_page)
    for selector in (".site-title", ".page h1"):
        _assert_serif(guarded_page, selector)
    preloads = guarded_page.evaluate(_PRELOAD_JS)
    assert not any(_OLD in h for h in preloads)
