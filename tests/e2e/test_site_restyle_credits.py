"""STY-03 credits guard (26-05): every footer credit is visible and legible on five pages.

CFB, NFL, MLB, Methodology and Coverage, in light and dark. Each `.credit-item` must have a
real box, sit inside the viewport once the footer is scrolled into view, not be clipped by an
ancestor, and clear WCAG 4.5:1 against the first opaque background behind it. The ratio is
computed here, not imported, so this file stands alone.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page
from test_site_required_text import RT07_TEXT

pytestmark = pytest.mark.e2e

_DARK_INIT = "localStorage.setItem('bl-theme','dark')"
_MIN_RATIO = 4.5
# Expected `.credit-item` count per page (CFB 3, NFL 4, MLB 5; static pages carry the CFB three).
_ITEM_COUNT = {"cfb": 3, "nfl": 4, "mlb": 5, "methodology": 3, "coverage": 3}

_ITEMS_JS = """
(footer) => [...footer.querySelectorAll('.credit-line .credit-item')].map((el) => {
  el.scrollIntoView({ block: 'center' });
  const parse = (s) => {
    const m = /rgba?\\(([^)]+)\\)/.exec(s || '');
    if (!m) return null;
    const p = m[1].split(',').map((x) => parseFloat(x));
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  };
  const lum = (c) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
  };
  const bgOf = (n) => {
    for (; n; n = n.parentElement) {
      const c = parse(getComputedStyle(n).backgroundColor);
      if (c && c.a >= 0.99) return c;
    }
    return { r: 255, g: 255, b: 255, a: 1 };
  };
  const box = el.getBoundingClientRect();
  let clipped = false;
  for (let n = el.parentElement; n && n !== document.documentElement; n = n.parentElement) {
    const cs = getComputedStyle(n);
    if (cs.overflowX === 'visible' && cs.overflowY === 'visible') continue;
    const r = n.getBoundingClientRect();
    if (box.left < r.left - 0.5 || box.right > r.right + 0.5
        || box.top < r.top - 0.5 || box.bottom > r.bottom + 0.5) clipped = true;
  }
  const cs = getComputedStyle(el);
  const fg = parse(cs.color);
  const bg = bgOf(el);
  const l1 = lum(fg), l2 = lum(bg);
  const links = [...el.querySelectorAll('a')].map((a) => {
    const lc = parse(getComputedStyle(a).color);
    const k = lum(lc);
    return (Math.max(k, l2) + 0.05) / (Math.min(k, l2) + 0.05);
  });
  let opacity = 1;
  for (let n = el; n; n = n.parentElement) opacity *= parseFloat(getComputedStyle(n).opacity);
  return {
    text: el.textContent.replace(/\\s+/g, ' ').trim(),
    width: box.width, height: box.height,
    inViewport: box.top >= 0 && box.bottom <= innerHeight && box.left >= 0
      && box.right <= innerWidth,
    clipped, display: cs.display, visibility: cs.visibility, opacity,
    ratio: (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05),
    linkRatios: links,
    hrefs: [...el.querySelectorAll('a')].map((a) => a.getAttribute('href')),
  };
})
"""


@pytest.fixture
def opened(
    request: pytest.FixtureRequest,
    site_url: str,
    mlb_site_url: str,
    open_app: Callable[..., None],
    open_nfl_app: Callable[..., None],
    open_mlb_app: Callable[..., None],
) -> Callable[[str, str], Page]:
    def _open(which: str, theme: str) -> Page:
        fixture = {
            "cfb": "guarded_page",
            "nfl": "nfl_guarded_page",
            "mlb": "mlb_guarded_page",
            "methodology": "mlb_guarded_page",
            "coverage": "guarded_page",
        }[which]
        page: Page = request.getfixturevalue(fixture)
        if theme == "dark":
            page.context.add_init_script(_DARK_INIT)
        if which == "cfb":
            open_app(page, "")
        elif which == "nfl":
            open_nfl_app(page, "?sport=nfl")
        elif which == "mlb":
            open_mlb_app(page, "?sport=mlb")
        else:
            base = mlb_site_url if which == "methodology" else site_url
            page.goto(f"{base}/{which}.html")
        assert page.evaluate("document.documentElement.dataset.theme") == theme
        return page

    return _open


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("which", ["cfb", "nfl", "mlb", "methodology", "coverage"])
def test_every_credit_is_visible_and_legible(
    opened: Callable[[str, str], Page], which: str, theme: str
) -> None:
    page = opened(which, theme)
    footer = page.locator("footer").first
    items: list[dict[str, Any]] = footer.evaluate(_ITEMS_JS)
    assert len(items) == _ITEM_COUNT[which], [i["text"] for i in items]
    for item in items:
        where = f"{which}/{theme}: {item['text']}"
        assert item["display"] == "block", where
        assert item["visibility"] == "visible", where
        assert item["opacity"] == 1, where
        assert item["width"] > 0
        assert item["height"] > 0, where
        assert item["inViewport"], where
        assert not item["clipped"], where
        assert item["ratio"] >= _MIN_RATIO, f"{where} text {item['ratio']:.2f}"
        for ratio in item["linkRatios"]:
            assert ratio >= _MIN_RATIO, f"{where} link {ratio:.2f}"
    texts = [i["text"] for i in items]
    if which in ("cfb", "methodology", "coverage"):
        cfbd = items[-1]
        assert cfbd["text"] == "Data provided by CollegeFootballData.com"
        assert cfbd["hrefs"] == ["https://collegefootballdata.com"]
    if which == "mlb":
        assert texts[0] == RT07_TEXT
    # Each credit is a separate line: the blocks stack, none shares a row with its neighbour.
    tops: list[float] = footer.evaluate(
        "f => [...f.querySelectorAll('.credit-line .credit-item')]"
        ".map((e) => e.getBoundingClientRect().top)"
    )
    assert tops == sorted(set(tops)), tops
