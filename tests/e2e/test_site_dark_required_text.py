"""DARK-01 / D10 (17-06): required text stays present and legible in dark on all five pages.

Stored dark is set through an init script, as a returning visitor would have it. Each
required string (RT ids from tests/test_site_required_text.py) is found by its exact text
and its links, and every text-bearing element (the paragraph and its links) must clear
WCAG 4.5:1 against the first non-transparent ancestor background, with no opacity below 1.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page
from test_site_required_text import (
    RT01_ITEMS,
    RT01_TEXT,
    RT07_TEXT,
    RT20_TEXT,
    RT21_TEXT,
    RT23_TEXT,
    RT24_TEXT,
)

pytestmark = pytest.mark.e2e

_DARK_INIT = "localStorage.setItem('bl-theme','dark')"
_MIN_RATIO = 4.5

# Footer lines on every page, plus the page-specific rows.
_FOOTER_ROWS = {
    "footer p.credit-line": RT01_TEXT,
    "footer p.trademark-line": RT23_TEXT,
    "footer p.type-line": RT24_TEXT,
}
_PAGE_ROWS: dict[str, dict[str, str]] = {
    "cfb": {"#excitement-caption": RT20_TEXT, "#era-note": RT21_TEXT},
    "methodology": {"p:has-text('is copyrighted by Retrosheet')": RT07_TEXT},
}

_CONTRAST_JS = """
(root) => {
  const lum = (r, g, b) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const parse = (s) => {
    const m = /rgba?\\(([^)]+)\\)/.exec(s || '');
    if (!m) return null;
    const p = m[1].split(',').map((x) => parseFloat(x));
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  };
  const bgOf = (el) => {
    for (let n = el; n; n = n.parentElement) {
      const c = parse(getComputedStyle(n).backgroundColor);
      if (c && c.a >= 0.99) return c;
    }
    return { r: 255, g: 255, b: 255, a: 1 };
  };
  const out = [];
  {
    const els = [root, ...root.querySelectorAll('a')];
    for (const el of els) {
      const cs = getComputedStyle(el);
      const fg = parse(cs.color);
      const bg = bgOf(el);
      const l1 = lum(fg.r, fg.g, fg.b), l2 = lum(bg.r, bg.g, bg.b);
      let opacity = 1;
      for (let n = el; n; n = n.parentElement) opacity *= parseFloat(getComputedStyle(n).opacity);
      out.push({
        tag: el.tagName, color: cs.color, bg: `rgb(${bg.r}, ${bg.g}, ${bg.b})`,
        ratio: (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05), opacity,
      });
    }
  }
  return out;
}
"""


def _check_row(page: Page, selector: str, text: str, *, must_be_visible: bool = True) -> None:
    node = page.locator(selector)
    assert node.count() >= 1, f"{selector}: missing"
    normalized = " ".join((node.first.text_content() or "").split())
    assert text in normalized, f"{selector}: text differs"
    if not must_be_visible and not node.first.is_visible():
        return
    results: list[dict[str, Any]] = node.first.evaluate(_CONTRAST_JS)
    assert results
    for r in results:
        assert r["ratio"] >= _MIN_RATIO, f"{selector} {r}"
        assert r["opacity"] == 1, f"{selector} {r}"


@pytest.fixture
def dark_opened(
    request: pytest.FixtureRequest,
    site_url: str,
    nfl_site_url: str,
    mlb_site_url: str,
    open_app: Callable[..., None],
    open_nfl_app: Callable[..., None],
    open_mlb_app: Callable[..., None],
) -> Callable[[str], Page]:
    def _open(which: str) -> Page:
        fixture = {
            "cfb": "guarded_page",
            "nfl": "nfl_guarded_page",
            "mlb": "mlb_guarded_page",
            "methodology": "mlb_guarded_page",
            "coverage": "guarded_page",
        }[which]
        page: Page = request.getfixturevalue(fixture)
        page.context.add_init_script(_DARK_INIT)
        if which == "cfb":
            open_app(page, "")
        elif which == "nfl":
            open_nfl_app(page, "?sport=nfl")
        elif which == "mlb":
            open_mlb_app(page, "?sport=mlb")
        else:
            # The MLB flag-on build carries the Retrosheet notice (RT-07) in methodology.
            base = mlb_site_url if which == "methodology" else site_url
            page.goto(f"{base}/{which}.html")
        assert page.evaluate("document.documentElement.dataset.theme") == "dark"
        return page

    return _open


@pytest.mark.parametrize("which", ["cfb", "nfl", "mlb", "methodology", "coverage"])
def test_required_text_present_and_legible_in_dark(
    dark_opened: Callable[[str], Page], which: str
) -> None:
    page = dark_opened(which)
    for selector, text in _FOOTER_ROWS.items():
        # NFL and MLB footers swap in their own credit lines (RT-04); the lead credit stays.
        if which in ("nfl", "mlb") and selector.endswith("credit-line"):
            text = RT01_ITEMS[0]
        _check_row(page, selector, text)
    for selector, text in _PAGE_ROWS.get(which, {}).items():
        # RT-20 and RT-21 captions are shown only for some chart states.
        _check_row(page, selector, text, must_be_visible=which != "cfb")
    assert page.locator("footer p.freshness").count() == 1
    results: list[dict[str, Any]] = page.locator("footer p.freshness").first.evaluate(_CONTRAST_JS)
    assert all(r["ratio"] >= _MIN_RATIO for r in results), results
