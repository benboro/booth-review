# ruff: noqa: E501, RUF001
"""Answer 10b: the footer freshness line never leaves a lone last word (the lone "7" at 390px).

The line is built in three places: pages.py (the CFB static pages) and the NFL and MLB runtime
footers. The test narrows the line through a sweep of widths, because which word lands last
depends on the font and the data; at every width the last line must hold more than one word.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

_LAST_LINE_JS = """() => {
  const p = document.querySelector('footer .freshness');
  const text = p.textContent;
  const out = [];
  for (let w = 110; w <= 380; w += 5) {
    p.style.width = w + 'px';
    p.style.maxWidth = w + 'px';
    const tokens = [];
    const re = /[^ ]+/g;
    let m;
    const node = p.firstChild;
    while ((m = re.exec(text))) {
      const r = document.createRange();
      r.setStart(node, m.index);
      r.setEnd(node, m.index + m[0].length);
      const rects = r.getClientRects();
      tokens.push({ word: m[0], top: Math.round(rects[rects.length - 1].top), pieces: rects.length });
    }
    const bottom = Math.max(...tokens.map((t) => t.top));
    const last = tokens.filter((t) => t.top === bottom).map((t) => t.word).join(' ');
    out.push({ w, last, words: last.split(/\\s+/).length });
  }
  p.style.width = '';
  p.style.maxWidth = '';
  return out;
}"""


def _assert_no_lone_last_word(page: Page) -> None:
    page.evaluate("() => document.fonts.ready")
    sweep = page.evaluate(_LAST_LINE_JS)
    bad = [s for s in sweep if s["words"] < 2]
    assert not bad, bad


@pytest.mark.parametrize("page_name", ["index.html", "methodology.html"])
def test_cfb_static_footer_freshness_keeps_week_and_number_together(
    mobile_page: Page, site_url: str, page_name: str
) -> None:
    mobile_page.goto(f"{site_url}/{page_name}")
    _assert_no_lone_last_word(mobile_page)
    assert "Week " in mobile_page.inner_text("footer .freshness") or "Week " in (
        mobile_page.evaluate("document.querySelector('footer .freshness').textContent")
    )


def test_nfl_runtime_footer_freshness_keeps_week_and_number_together(
    nfl_mobile_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    open_nfl_app(nfl_mobile_page)
    _assert_no_lone_last_word(nfl_mobile_page)
    text = nfl_mobile_page.evaluate("document.querySelector('footer .freshness').textContent")
    assert "Week " in text and "Week " not in text


def test_mlb_runtime_footer_freshness_never_ends_on_a_lone_word(
    mlb_mobile_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    open_mlb_app(mlb_mobile_page)
    _assert_no_lone_last_word(mlb_mobile_page)
