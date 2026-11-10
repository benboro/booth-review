"""No text is clipped vertically: on every CFB and NFL tab, at desktop, mid and phone
widths, each visible text run (HTML and chart SVG) fits inside every ancestor that hides its
overflow.

A descender that hangs below a fixed line box is ink overflow, which `scrollHeight` never
counts, so this compares each text run's box (the font's full ascent-to-descent height)
with the padding box of each clipping ancestor instead. Synthetic fixture data only.

Scope: each tab's state on load; panels, popovers and modals opened later, and MLB (off in
production), are not covered. Horizontal truncation is not checked, since an ellipsis is
intended there. `test_detector_flags_clipped_text` proves the detector catches each case.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

CFB_VIEWS = ["", "bars", "butterfly", "map", "crews", "weekend"]
NFL_VIEWS = ["special", "crews", "viewership", "scatter", "weekend"]
WIDTHS = [1440, 1024, 390]

# Returns one entry per clipped text run: the clipping element, the text, and how many
# pixels of the run fall outside it. SVG text is measured by its <text>/<tspan> box. Skips
# invisible or screen-reader-only elements (1px boxes; `display: contents` wrappers have no
# box but still render their children) and ancestors that scroll on purpose (`auto`/`scroll`).
_FIND_CLIPPED = """
() => {
  const TOL = 0.5;
  const out = [];
  const visible = (el) => {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) return false;
    if (cs.display === 'contents') return true;
    const r = el.getBoundingClientRect();
    return r.width > 2 && r.height > 2;
  };
  const clips = (el) => {
    const cs = getComputedStyle(el);
    return cs.overflowY === 'hidden' || cs.overflowY === 'clip';
  };
  const classes = (el) => (typeof el.className === 'string' && el.className.trim()
    ? '.' + el.className.trim().split(/\\s+/).join('.') : '');
  const label = (el) => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + classes(el);
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const text = node.textContent.trim();
    const parent = node.parentElement;
    if (!text || !parent || parent.closest('script, style, noscript, defs, clipPath, title')) {
      continue;
    }
    const inSvg = !!parent.closest('svg');
    let hidden = false;
    for (let el = parent; el; el = el.parentElement) if (!visible(el)) { hidden = true; break; }
    if (hidden) continue;
    const range = document.createRange();
    range.selectNodeContents(node);
    const rects = inSvg ? [parent.getBoundingClientRect()] : range.getClientRects();
    for (const rect of rects) {
      if (rect.width === 0 || rect.height === 0) continue;
      for (let el = parent; el && el !== document.body; el = el.parentElement) {
        if (!clips(el)) continue;
        const box = el.getBoundingClientRect();
        const cs = getComputedStyle(el);
        const top = box.top + parseFloat(cs.borderTopWidth);
        const bottom = box.bottom - parseFloat(cs.borderBottomWidth);
        // Text scrolled or positioned wholly outside the box is hidden on purpose.
        if (rect.bottom <= top || rect.top >= bottom) break;
        const over = Math.max(top - rect.top, rect.bottom - bottom);
        if (over > TOL) {
          const px = Math.round(over * 10) / 10;
          out.push({ clipper: label(el), text: text.slice(0, 40), over: px });
        }
      }
    }
  }
  return out;
}
"""


# One clipped run per case: plain text, text under a `display: contents` wrapper, and SVG
# text, each in a 10px box that hides overflow, plus an unclipped control.
_DETECTOR_CASES = """
<div style="height:10px;overflow:hidden;font:20px serif" id="plain">games</div>
<div style="height:10px;overflow:hidden;font:20px serif" id="wrapped">
  <div style="display:contents"><span>games</span></div>
</div>
<div style="height:10px;overflow:hidden" id="chart">
  <svg width="200" height="50"><text x="0" y="18" font-size="16">games</text></svg>
</div>
<div style="height:40px;overflow:hidden;font:20px serif" id="roomy">games</div>
"""


def test_detector_flags_clipped_text(page: Page) -> None:
    page.set_content(_DETECTOR_CASES)
    found: list[dict[str, Any]] = page.evaluate(_FIND_CLIPPED)
    assert sorted({f["clipper"] for f in found}) == ["div#chart", "div#plain", "div#wrapped"]


def _assert_no_clipping(page: Page) -> None:
    page.wait_for_timeout(300)  # let charts and tables settle after the view draws
    found: list[dict[str, Any]] = page.evaluate(_FIND_CLIPPED)
    lines = sorted({f"{f['clipper']} clips {f['text']!r} by {f['over']}px" for f in found})
    assert not lines, "text clipped:\n" + "\n".join(lines)


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("view", CFB_VIEWS)
def test_cfb_text_never_clipped(
    guarded_page: Page,
    mobile_page: Page,
    open_app: Callable[..., None],
    view: str,
    width: int,
) -> None:
    page = mobile_page if width == 390 else guarded_page
    if width != 390:
        page.set_viewport_size({"width": width, "height": 900})
    open_app(page, f"?view={view}" if view else "")
    _assert_no_clipping(page)


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("view", NFL_VIEWS)
def test_nfl_text_never_clipped(
    nfl_guarded_page: Page,
    nfl_mobile_page: Page,
    open_nfl_app: Callable[..., None],
    serve_nfl_crews: Callable[[Page], None],
    view: str,
    width: int,
) -> None:
    page = nfl_mobile_page if width == 390 else nfl_guarded_page
    if width != 390:
        page.set_viewport_size({"width": width, "height": 900})
    serve_nfl_crews(page)
    open_nfl_app(page, f"?sport=nfl&view={view}")
    if view != "weekend":
        page.wait_for_function(f"window.__nflTestHooks.getViewModel('{view}')?.drawn === true")
    _assert_no_clipping(page)
