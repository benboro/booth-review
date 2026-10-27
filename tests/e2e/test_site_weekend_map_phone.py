"""Weekend map at 390 px, CFB and NFL, light and dark (Phase 24, plan 10): the control row, the
44 px tap areas, the map's aspect box with no blank band, the key in flow, and the phone tap model
(first tap card and ring, second tap or `Open game` opens, background tap clears only the card,
a mouse click opens at once). Synthetic fixtures only.
"""

from __future__ import annotations

import pytest
from dark_checks import set_theme, settle
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

SPORTS = ["cfb", "nfl"]
THEMES = ["light", "dark"]
# A placed game on each sport's day (CFB: Ironpeak @ Stonebridge, Pasadena; NFL: upcoming 0).
GAME = {"cfb": "cfb:t:19", "nfl": "nfl:upcoming:0"}
NFL_NOW = "2026-10-11T09:00:00-04:00"

_READY = """() => {
  const gd = document.querySelector('.wk-map-box');
  return !!(gd && gd._fullLayout && gd.data && gd.data.some((t) => t.name === 'venue-hits'));
}"""

_POINT = """(key) => {
  const gd = document.querySelector('.wk-map-box');
  gd.scrollIntoView({ block: 'center' });
  const t = gd.data.find((d) => d.name === 'venue-hits');
  const i = t.customdata.indexOf(key);
  const r = gd.getBoundingClientRect();
  const xa = gd._fullLayout.xaxis;
  const ya = gd._fullLayout.yaxis;
  return { x: r.left + xa._offset + xa.c2p(t.x[i]), y: r.top + ya._offset + ya.c2p(t.y[i]) };
}"""

_RINGS = (
    "() => document.querySelector('.wk-map-box').data.find((t) => t.name === 'wk-hover').x.length"
)

_BOX = """(sel) => {
  const r = document.querySelector(sel).getBoundingClientRect();
  return { x: r.left, y: r.top, w: r.width, h: r.height };
}"""

# How far (px) the hit area of a button reaches past its box, found by probing the element at
# points above and below it (the 44 px tap area is padding via a pseudo-element).
_HIT_HEIGHT = """(sel) => {
  const n = document.querySelector(sel);
  const r = n.getBoundingClientRect();
  const x = r.left + r.width / 2;
  const owns = (y) => {
    const hit = document.elementFromPoint(x, y);
    return !!hit && (hit === n || n.contains(hit));
  };
  let up = 0;
  while (owns(r.top - up - 1)) up += 1;
  let down = 0;
  while (owns(r.bottom + down)) down += 1;
  return r.height + up + down;
}"""


def _open_sport(
    request: pytest.FixtureRequest, sport: str, *, mobile: bool, query_extra: str = ""
) -> Page:
    """A page on the weekend map: `mobile` uses the touch phone context, otherwise a desktop
    context resized to 390 px (a mouse, so hover is available)."""
    if sport == "cfb":
        page: Page = request.getfixturevalue("mobile_page" if mobile else "guarded_page")
        request.getfixturevalue("serve_weekend_map")(page)
        open_app = request.getfixturevalue("open_app")
        if not mobile:
            page.set_viewport_size({"width": 390, "height": 844})
        open_app(page, "?view=weekend&wview=map" + query_extra)
    else:
        page = request.getfixturevalue("nfl_mobile_page" if mobile else "nfl_guarded_page")
        open_nfl = request.getfixturevalue("open_nfl_app")
        if not mobile:
            page.set_viewport_size({"width": 390, "height": 844})
        page.add_init_script(f"window.__nflWeekendNow = '{NFL_NOW}'")
        open_nfl(page, "?sport=nfl&view=weekend&wview=map" + query_extra)
    page.wait_for_function(_READY, timeout=15000)
    settle(page)
    return page


def _themed(page: Page, theme: str) -> None:
    if theme != "light":
        set_theme(page, theme)
        page.wait_for_function(_READY, timeout=15000)
        settle(page)


def _point(page: Page, key: str) -> dict[str, float]:
    page.evaluate("() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))")
    return page.evaluate(_POINT, key)  # type: ignore[no-any-return]


def _card_visible(page: Page) -> None:
    page.wait_for_selector("#chart-tooltip[data-kind='game']:not([hidden])", timeout=5000)


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("sport", SPORTS)
def test_control_row_day_tabs_on_their_own_line_switch_left_stepper_right(
    request: pytest.FixtureRequest, sport: str, theme: str
) -> None:
    page = _open_sport(request, sport, mobile=True)
    _themed(page, theme)
    days = page.evaluate(_BOX, ".wk-days")
    switch = page.evaluate(_BOX, ".wk-view-switch")
    stepper = page.evaluate(_BOX, ".wk-stepper")
    right = page.evaluate(_BOX, ".wk-controls-right")
    # The day tabs take the first line; the switch and stepper share the second.
    assert days["y"] + days["h"] <= right["y"] + 1
    assert abs((switch["y"] + switch["h"] / 2) - (stepper["y"] + stepper["h"] / 2)) <= 2
    assert switch["x"] < stepper["x"]
    assert switch["x"] - right["x"] <= 2  # left-aligned
    assert (right["x"] + right["w"]) - (stepper["x"] + stepper["w"]) <= 2  # right-aligned
    assert switch["x"] + switch["w"] < stepper["x"]
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


@pytest.mark.parametrize("sport", SPORTS)
def test_switch_and_stepper_hit_areas_are_at_least_44px(
    request: pytest.FixtureRequest, sport: str
) -> None:
    page = _open_sport(request, sport, mobile=True)
    for sel in ('[data-wk-id="wview:timeline"]', '[data-wk-id="wview:map"]'):
        assert page.evaluate(_HIT_HEIGHT, sel) >= 44, sel
        assert page.evaluate(_BOX, sel)["w"] >= 80
    for sel in (".wk-step--prev", ".wk-step--next"):
        box = page.evaluate(_BOX, sel)
        assert box["h"] >= 44
        assert box["w"] >= 44


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("sport", SPORTS)
def test_map_box_follows_the_aspect_ratio_with_no_blank_band(
    request: pytest.FixtureRequest, sport: str, theme: str
) -> None:
    page = _open_sport(request, sport, mobile=True)
    _themed(page, theme)
    box = page.evaluate(_BOX, ".wk-map-box")
    assert abs(box["h"] - box["w"] * 610 / 975) <= 2
    size = page.evaluate("document.querySelector('.wk-map-box')._fullLayout._size")
    # The plot fills the box: no band above, below or beside the map.
    assert abs(size["h"] - box["h"]) <= 2
    assert abs(size["w"] - box["w"]) <= 2
    assert size["t"] == size["b"] == size["l"] == size["r"] == 0
    # The fixed phone map: no zoom or pan controls.
    assert page.locator(".wk-map-box .modebar").count() == 0


@pytest.mark.parametrize("sport", SPORTS)
def test_the_key_sits_in_flow_below_the_map(request: pytest.FixtureRequest, sport: str) -> None:
    page = _open_sport(request, sport, mobile=True)
    box = page.evaluate(_BOX, ".wk-map-box")
    key = page.evaluate(_BOX, ".wk-map-key")
    assert key["y"] >= box["y"] + box["h"] - 1
    assert page.evaluate("getComputedStyle(document.querySelector('.wk-map-key')).position") == (
        "static"
    )
    assert abs(key["x"] - box["x"]) <= 1
    assert key["w"] <= box["w"] + 1


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("sport", SPORTS)
def test_first_tap_shows_the_card_with_open_game_and_the_ring_second_tap_opens(
    request: pytest.FixtureRequest, sport: str, theme: str
) -> None:
    page = _open_sport(request, sport, mobile=True)
    _themed(page, theme)
    at = _point(page, GAME[sport])
    page.touchscreen.tap(at["x"], at["y"])
    _card_visible(page)
    button = page.locator("#chart-tooltip .tt-open-game")
    assert button.count() == 1
    assert button.inner_text() == "Open game"
    assert button.bounding_box()["height"] >= 44  # type: ignore[index]
    assert page.evaluate(_RINGS) == 1
    expect(page.locator("dialog[open]")).to_have_count(0)
    # The second tap on the same mark opens the panel.
    page.touchscreen.tap(at["x"], at["y"])
    expect(page.locator("dialog[open]")).to_be_visible()


@pytest.mark.parametrize("sport", SPORTS)
def test_the_open_game_button_opens_the_panel_and_escape_returns_focus(
    request: pytest.FixtureRequest, sport: str
) -> None:
    page = _open_sport(request, sport, mobile=True)
    at = _point(page, GAME[sport])
    page.touchscreen.tap(at["x"], at["y"])
    _card_visible(page)
    page.locator("#chart-tooltip .tt-open-game").tap()
    dialog = page.locator("dialog[open]")
    expect(dialog).to_be_visible()
    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    page.wait_for_function(
        "document.activeElement && document.activeElement.dataset.wkId === 'wview:map'",
        timeout=5000,
    )


@pytest.mark.parametrize("sport", SPORTS)
def test_a_background_tap_clears_only_the_card(request: pytest.FixtureRequest, sport: str) -> None:
    page = _open_sport(request, sport, mobile=True)
    at = _point(page, GAME[sport])
    page.touchscreen.tap(at["x"], at["y"])
    _card_visible(page)
    box = page.locator(".wk-map-box").bounding_box()
    assert box is not None
    page.touchscreen.tap(box["x"] + 6, box["y"] + 6)
    page.wait_for_selector("#chart-tooltip", state="hidden", timeout=5000)
    expect(page.locator("dialog[open]")).to_have_count(0)
    assert page.evaluate(_RINGS) == 0
    # The map is still mounted and in map mode.
    assert "wview=map" in page.evaluate("location.search")
    assert page.locator(".wk-map-box").count() == 1


@pytest.mark.parametrize("sport", SPORTS)
def test_a_mouse_click_at_phone_width_opens_the_panel_at_once(
    request: pytest.FixtureRequest, sport: str
) -> None:
    page = _open_sport(request, sport, mobile=False)
    at = _point(page, GAME[sport])
    page.mouse.move(at["x"] + 30, at["y"] + 30)
    page.mouse.move(at["x"], at["y"], steps=4)
    page.wait_for_timeout(250)
    page.mouse.click(at["x"], at["y"])
    expect(page.locator("dialog[open]")).to_be_visible()
    # No tap card (and no Open game button) on a pointer that can hover.
    assert page.locator("#chart-tooltip .tt-open-game").count() == 0
