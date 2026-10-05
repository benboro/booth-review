"""New Year's Six band in the Game picker (SITE-46; 04.10 D-07..D-09).

Uses the synthetic contract fixture with bowl franchise slugs renamed to NY6 slugs
(`serve_ny6`); the shared fixture has none.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from playwright.sync_api import Page
from test_site_chart import _ratio, _rgb_of

pytestmark = pytest.mark.e2e

BOTH = {"harbor-bowl": "rose-bowl", "summit-bowl": "sugar-bowl"}
BAND = "#game-options .game-ny6"
_SLUGS_JS = (
    "() => [...document.querySelectorAll('#game-options .game-ny6 [data-game]')]"
    ".map((b) => b.dataset.game)"
)
_SHAPE_JS = """
() => [document.getElementById('toolbar').getBoundingClientRect().height,
  document.getElementById('chart-area').getBoundingClientRect().top,
  document.getElementById('pop-game').getBoundingClientRect().top,
  document.getElementById('pop-game').getBoundingClientRect().left]
"""


def _open_game(page: Page) -> None:
    page.click("#trigger-game")
    page.wait_for_function("document.getElementById('pop-game').matches(':popover-open')")


def _search(page: Page, text: str) -> None:
    page.fill("#game-search", text)


def _visible_rows(page: Page) -> int:
    n: int = page.evaluate(
        "() => [...document.querySelectorAll('.game-ny6 [data-game]')]"
        ".filter((b) => b.offsetParent !== null).length"
    )
    return n


def _open_with(
    page: Page, serve: Callable[..., None], open_app: Callable[..., None], m: dict[str, str]
) -> None:
    serve(page, m)
    open_app(page, "")
    _open_game(page)


def test_default_fixture_has_no_band(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    _open_game(guarded_page)
    assert guarded_page.locator(BAND).count() == 0


def test_band_structure_and_style(
    guarded_page: Page, open_app: Callable[..., None], serve_ny6: Callable[..., None]
) -> None:
    _open_with(guarded_page, serve_ny6, open_app, BOTH)
    band = guarded_page.locator("#game-rows-bowls > .game-ny6")
    assert band.count() == 1
    assert band.get_attribute("role") == "group"
    assert band.get_attribute("aria-label") == "New Year's Six"
    label = band.locator("> :first-child")
    assert label.get_attribute("class") == "game-ny6-label"
    assert label.inner_text() == "New Year's Six"
    assert label.get_attribute("aria-hidden") == "true"
    assert label.get_attribute("tabindex") is None
    assert guarded_page.evaluate(_SLUGS_JS) == ["rose-bowl", "sugar-bowl"]
    style = band.evaluate(
        "el => { const c = getComputedStyle(el); return [c.borderTopWidth, c.borderTopStyle,"
        " c.borderBottomWidth, c.borderBottomStyle, c.borderTopColor, c.borderBottomColor]; }"
    )
    assert style[:4] == ["1px", "solid", "1px", "solid"]
    assert style[4] == style[5]
    lab = label.evaluate(
        "el => { const c = getComputedStyle(el); return [c.fontStyle, c.fontWeight, c.color]; }"
    )
    assert lab[:2] == ["italic", "400"]
    assert lab[2] == guarded_page.evaluate(
        "() => { const e = document.createElement('i');"
        " e.style.color = 'var(--game-playoff-text)'; document.body.append(e);"
        " const c = getComputedStyle(e).color; e.remove(); return c; }"
    )


def test_partial_band_holds_only_present_franchises(
    guarded_page: Page, open_app: Callable[..., None], serve_ny6: Callable[..., None]
) -> None:
    _open_with(guarded_page, serve_ny6, open_app, {"harbor-bowl": "rose-bowl"})
    assert guarded_page.evaluate(_SLUGS_JS) == ["rose-bowl"]
    after = guarded_page.evaluate(
        "() => document.querySelector('#game-rows-bowls > .game-ny6')"
        ".nextElementSibling.dataset.game"
    )
    assert after == "summit-bowl"


def test_search_wraps_visible_rows_and_hides_empty_band(
    guarded_page: Page, open_app: Callable[..., None], serve_ny6: Callable[..., None]
) -> None:
    _open_with(guarded_page, serve_ny6, open_app, BOTH)
    band = guarded_page.locator(BAND)
    _search(guarded_page, "harbor")
    assert band.is_visible()
    assert _visible_rows(guarded_page) == 1
    assert guarded_page.locator(".game-ny6-label").is_visible()
    _search(guarded_page, "summit")
    assert band.is_visible()
    assert _visible_rows(guarded_page) == 1
    assert guarded_page.locator("#game-options [data-game='sugar-bowl']").is_visible()
    _search(guarded_page, "lakeshore")
    assert not band.is_visible()
    assert not guarded_page.locator("[data-game-section='bowls']").is_visible()
    _search(guarded_page, "")
    assert band.is_visible()
    assert _visible_rows(guarded_page) == 2


def test_band_collapses_with_bowls(
    guarded_page: Page, open_app: Callable[..., None], serve_ny6: Callable[..., None]
) -> None:
    _open_with(guarded_page, serve_ny6, open_app, BOTH)
    shape = guarded_page.evaluate(_SHAPE_JS)
    guarded_page.click("#game-head-bowls")
    assert not guarded_page.locator(BAND).is_visible()
    assert guarded_page.evaluate(_SHAPE_JS) == shape
    guarded_page.click("#game-head-bowls")
    assert guarded_page.locator(BAND).is_visible()
    _search(guarded_page, "harbor")
    assert guarded_page.evaluate(_SHAPE_JS) == shape


def test_keyboard_skips_band_and_label(
    guarded_page: Page, open_app: Callable[..., None], serve_ny6: Callable[..., None]
) -> None:
    _open_with(guarded_page, serve_ny6, open_app, BOTH)
    guarded_page.locator("#game-options [data-game='cfp-semifinal']").focus()
    for expected in ("rose-bowl", "sugar-bowl"):
        guarded_page.keyboard.press("ArrowDown")
        assert guarded_page.evaluate("() => document.activeElement.dataset.game") == expected
    tab_stops: int = guarded_page.evaluate(
        "() => [...document.querySelectorAll('#game-options [role=radio]')]"
        ".filter((b) => b.tabIndex === 0).length"
    )
    assert tab_stops == 1
    inert: int = guarded_page.evaluate(
        "() => [...document.querySelectorAll('.game-ny6, .game-ny6-label')]"
        ".filter((e) => e.tabIndex >= 0).length"
    )
    assert inert == 0


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_label_contrast(
    guarded_page: Page,
    open_app: Callable[..., None],
    serve_ny6: Callable[..., None],
    scheme: str,
) -> None:
    guarded_page.emulate_media(color_scheme=scheme)  # type: ignore[arg-type]
    _open_with(guarded_page, serve_ny6, open_app, BOTH)
    fg = _rgb_of(guarded_page, ".game-ny6-label", "color")
    bg = _rgb_of(guarded_page, "#pop-game", "backgroundColor")
    assert _ratio(fg, bg) >= 4.5


def test_phone_band(
    mobile_page: Page, open_app: Callable[..., None], serve_ny6: Callable[..., None]
) -> None:
    serve_ny6(mobile_page, BOTH)
    open_app(mobile_page, "")
    mobile_page.click("#filters-button")
    assert mobile_page.locator(BAND).is_visible()
    heights: list[float] = mobile_page.evaluate(
        "() => [...document.querySelectorAll('.game-ny6 [data-game]')]"
        ".map((b) => b.getBoundingClientRect().height)"
    )
    assert all(h >= 44 for h in heights)
    fits: bool = mobile_page.evaluate(
        "() => document.documentElement.scrollWidth <= window.innerWidth"
    )
    assert fits
