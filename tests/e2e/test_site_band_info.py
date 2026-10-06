"""WR-03 / IN-03 (04.13 plan 23): the band info button is placed from the drawn
layout, never at a non-finite spot, and Escape closes the detail dialog first."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

_WAIT_TWO_FRAMES = "() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))"

_GEOMETRY_JS = """
() => {
  const b = document.getElementById('band-info');
  const gd = document.getElementById('chart');
  const fl = gd._fullLayout;
  const c = gd.getBoundingClientRect();
  const r = b.getBoundingClientRect();
  return {
    top: b.style.top, left: b.style.left,
    centerY: r.y + r.height / 2,
    gapCenterY: c.top + fl.yaxis2._offset - 14,
  };
}
"""


def _settle(page: Page) -> None:
    page.evaluate(_WAIT_TWO_FRAMES)
    page.wait_for_timeout(400)


def _assert_placed(page: Page) -> None:
    geo = page.evaluate(_GEOMETRY_JS)
    for key in ("top", "left"):
        assert geo[key].endswith("px")
        assert "NaN" not in geo[key]
        assert float(geo[key][:-2]) == float(geo[key][:-2])
    assert abs(geo["centerY"] - geo["gapCenterY"]) <= 1


@pytest.mark.parametrize("size", [(1280, 900), (360, 800)])
def test_band_info_is_placed_on_first_render(
    request: pytest.FixtureRequest, open_app: Callable[[Page, str], None], size: tuple[int, int]
) -> None:
    page: Page = request.getfixturevalue("guarded_page" if size[0] > 600 else "mobile_page")
    page.set_viewport_size({"width": size[0], "height": size[1]})
    open_app(page, "")
    _settle(page)
    _assert_placed(page)


def test_band_info_follows_width_changes_and_axis_switches(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    _settle(guarded_page)
    for width in (900, 1280):
        guarded_page.set_viewport_size({"width": width, "height": 900})
        _settle(guarded_page)
        _assert_placed(guarded_page)
    for axis in ("date", "excitement"):
        guarded_page.click(f'#axis-toggle button[data-axis="{axis}"]')
        _settle(guarded_page)
        _assert_placed(guarded_page)


def test_position_band_info_never_writes_a_non_finite_spot(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    _settle(guarded_page)
    result = guarded_page.evaluate(
        """
        async () => {
          const B = await import('./modules/band-info.js');
          const button = document.getElementById('band-info');
          const note = document.getElementById('band-note');
          const before = [button.style.top, button.style.left, note.style.top, note.style.left];
          const fake = { clientWidth: 800, _fullLayout: { yaxis2: {}, _size: { l: 50 } } };
          B.positionBandInfo(fake, button, note);
          const fake2 = { clientWidth: 800, _fullLayout: { yaxis2: { _offset: 100 }, _size: {} } };
          B.positionBandInfo(fake2, button, note);
          const after = [button.style.top, button.style.left, note.style.top, note.style.left];
          return { before, after };
        }
        """
    )
    assert result["after"] == result["before"]
    assert not any("NaN" in v for v in result["after"])


def test_escape_closes_the_dialog_before_the_band_note(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    _settle(guarded_page)
    guarded_page.click("#band-info")
    assert guarded_page.get_attribute("#band-info", "aria-expanded") == "true"

    # The dialog restores focus to whatever held it before opening; move it off the
    # button so only the band handler could put it back there.
    guarded_page.evaluate("document.activeElement.blur()")
    guarded_page.evaluate("window.__testHooks.openPanel(0)")
    guarded_page.wait_for_function("document.getElementById('detail-panel').open")
    guarded_page.keyboard.press("Escape")
    guarded_page.wait_for_function("!document.getElementById('detail-panel').open")
    assert guarded_page.is_visible("#band-note")
    assert guarded_page.get_attribute("#band-info", "aria-expanded") == "true"
    assert guarded_page.evaluate("document.activeElement.id") != "band-info"

    guarded_page.keyboard.press("Escape")
    assert guarded_page.is_hidden("#band-note")
    assert guarded_page.evaluate("document.activeElement.id") == "band-info"
