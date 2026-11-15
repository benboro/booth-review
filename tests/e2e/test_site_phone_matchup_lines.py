"""The This weekend phone row shows every line of its matchup (user 2026-11-14).

iPhone Safari drew the old two-line clamp's ellipsis after a matchup that wrapped onto exactly
two lines ("@ #25 Oklahoma State…" with nothing cut), and the clamp hid the whole home side of a
matchup that needs three. The matchup line has no clamp now: the row grows to the lines the text
needs, no ellipsis is ever drawn, and the ranked badge centres on all of the lines. Checked in
Chromium and in WebKit (Safari's engine) on synthetic games.
"""

from __future__ import annotations

import io
import os
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from conftest import _assert_guard_clean, _install_guard
from PIL import Image
from playwright.sync_api import Browser, Error, Page, Playwright
from test_site_weekend_render import _known, _mount_phone

pytestmark = pytest.mark.e2e

OpenApp = Callable[[Page, str], None]

# (away, home) at a list width that puts the matchup on exactly two lines (the reported row),
# and one that needs more than two.
_TWO_LINES = ("Texas Tech", "Oklahoma State")
_LONG = ("Southern Mississippi Golden Eagles of Hattiesburg", "Louisiana-Monroe Warhawks")
_HOST_WIDTH = 300

# Each matchup line's geometry: its lines (distinct character bottoms), whether anything is cut
# (a character outside the box, or content taller than the box), its clamp, the last
# character's box (an ellipsis would be drawn after it) and the ranked badge's middle.
_GEOM_JS = """(sel) => {
  const row = document.querySelector(sel);
  // Into view, so the rects below are the screenshot's coordinates.
  row.scrollIntoView({ block: 'center' });
  const l1 = row.querySelector('.wk-item-l1');
  const box = l1.getBoundingClientRect();
  const bottoms = new Set();
  let outside = 0;
  let last = null;
  const walk = document.createTreeWalker(l1, NodeFilter.SHOW_TEXT);
  for (let n = walk.nextNode(); n; n = walk.nextNode()) {
    for (let k = 0; k < n.length; k += 1) {
      if (/\\s/.test(n.data[k])) continue;
      const range = document.createRange();
      range.setStart(n, k);
      range.setEnd(n, k + 1);
      const r = range.getBoundingClientRect();
      bottoms.add(Math.round(r.bottom));
      if (r.top < box.top - 0.5 || r.bottom > box.bottom + 0.5 || r.right > box.right + 0.5) {
        outside += 1;
      }
      last = { left: r.left, right: r.right, top: r.top, bottom: r.bottom };
    }
  }
  const mark = row.querySelector('.rk-badge');
  const badge = mark ? mark.getBoundingClientRect() : box;
  const cs = getComputedStyle(l1);
  return {
    lines: bottoms.size, outside, cut: l1.scrollHeight > l1.clientHeight + 1,
    clamp: cs.webkitLineClamp, overflow: cs.overflowY, last,
    box: { left: box.left, right: box.right, top: box.top, bottom: box.bottom },
    linesMid: (box.top + box.bottom) / 2, badgeMid: (badge.top + badge.bottom) / 2,
    rowH: row.getBoundingClientRect().height,
  };
}"""


def _mount(page: Page, open_app: OpenApp) -> None:
    open_app(page, "")
    _mount_phone(
        page,
        [
            _known(key="two", away=_TWO_LINES[0], home=_TWO_LINES[1], awayRank=12, homeRank=25),
            _known(key="long", away=_LONG[0], home=_LONG[1], awayRank=20, homeRank=5),
            _known(key="one", away="UNLV", home="New Mexico"),
        ],
        host_width=_HOST_WIDTH,
    )


def _geom(page: Page, key: str) -> dict[str, Any]:
    got: dict[str, Any] = page.evaluate(_GEOM_JS, f'#wk-host .wk-item[data-wk-id="g:{key}"]')
    return got


def _ink_after_last_character(page: Page, geom: dict[str, Any]) -> set[tuple[int, ...]]:
    """The colours on the last line between its last character and the line's end: one colour
    (the page) unless something, such as an ellipsis, is drawn there."""
    last, box = geom["last"], geom["box"]
    x = last["right"] + 1
    clip = {
        "x": x,
        "y": last["top"],
        "width": box["right"] - x,
        "height": last["bottom"] - last["top"],
    }
    assert clip["width"] > 4, geom  # room an ellipsis would take
    with Image.open(io.BytesIO(page.screenshot(clip=clip))) as img:
        rgb = img.convert("RGB")
        return {rgb.getpixel((i, j)) for i in range(rgb.width) for j in range(rgb.height)}


def _assert_every_line_shows(page: Page) -> None:
    two, long_, one = (_geom(page, k) for k in ("two", "long", "one"))
    assert two["lines"] == 2, two
    assert long_["lines"] >= 3, long_
    assert one["lines"] == 1, one
    for g in (two, long_, one):
        assert g["clamp"] == "none", g
        assert (g["outside"], g["cut"]) == (0, False), g
    for key in ("two", "long"):
        # Nothing is drawn after the last word, and the badge centres on all of the lines.
        g = _geom(page, key)
        assert len(_ink_after_last_character(page, g)) == 1, g
        assert abs(g["badgeMid"] - g["linesMid"]) <= 1, g
    # The row grows with its lines (the phone list has no fixed row height).
    assert one["rowH"] < two["rowH"] < long_["rowH"]


def test_phone_matchup_shows_every_line(guarded_page: Page, open_app: OpenApp) -> None:
    guarded_page.set_viewport_size({"width": 390, "height": 844})
    _mount(guarded_page, open_app)
    _assert_every_line_shows(guarded_page)


@pytest.fixture(scope="module")
def webkit_browser(playwright: Playwright) -> Iterator[Browser]:
    """WebKit, the engine the report came from. The CI image ships it; a machine missing its
    system libraries skips locally."""
    try:
        browser = playwright.webkit.launch()
    except Error as exc:
        if os.environ.get("CI"):
            raise
        pytest.skip(f"WebKit cannot launch here: {str(exc).splitlines()[0]}")
    yield browser
    browser.close()


@pytest.fixture
def webkit_phone(webkit_browser: Browser, site_url: str) -> Iterator[Page]:
    context = webkit_browser.new_context(
        viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True
    )
    page = context.new_page()
    off_origin, csp_errors = _install_guard(page, site_url)
    try:
        yield page
    finally:
        context.close()
    _assert_guard_clean(off_origin, csp_errors)


def test_phone_matchup_shows_every_line_in_webkit(webkit_phone: Page, open_app: OpenApp) -> None:
    _mount(webkit_phone, open_app)
    _assert_every_line_shows(webkit_phone)
