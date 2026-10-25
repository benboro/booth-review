"""U6: every chart legend (CFB, NFL and MLB) uses the one outlined chip with a colour dot.

The 13-12 CFB chip (tests/e2e/test_site_legend_dblclick.py) is the model: an outlined 28px
chip on --bg, never filled with the series colour, an 8px dot in that colour beside the label,
and an off chip with muted text and its dot at 32%. Synthetic fixtures only.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

BG = "rgb(251, 249, 245)"  # --bg (light)

_LOOK_JS = """
(sel) => [...document.querySelectorAll(sel + ' button')].map((el) => {
  const s = getComputedStyle(el);
  const d = el.querySelector(':scope > .legend-dot');
  const ds = d ? getComputedStyle(d) : null;
  const r = d ? d.getBoundingClientRect() : null;
  return {
    cls: el.className, h: el.getBoundingClientRect().height, border: s.borderTopWidth,
    bg: s.backgroundColor, color: s.color, pressed: el.getAttribute('aria-pressed'),
    dot: d ? { bg: ds.backgroundColor, w: r.width, h: r.height, opacity: ds.opacity } : null,
    label: el.querySelector(':scope > .legend-label')?.textContent ?? null,
    text: el.textContent,
  };
})
"""


def _assert_shared_chips(page: Page, sel: str) -> list[dict[str, Any]]:
    chips: list[dict[str, Any]] = page.evaluate(_LOOK_JS, sel)
    assert chips, f"no legend chips under {sel}"
    for c in chips:
        assert c["cls"] == "legend-chip", c
        assert c["h"] >= 28 and c["border"] == "1px", c
        assert c["bg"] == BG, c  # outlined: never the series fill
        assert c["dot"] is not None and (c["dot"]["w"], c["dot"]["h"]) == (8, 8), c
        assert c["dot"]["bg"] not in (BG, "rgba(0, 0, 0, 0)"), c
        assert c["label"] and c["text"] == c["label"], c
        assert c["dot"]["opacity"] == ("1" if c["pressed"] == "true" else "0.32"), c
    return chips


def _toggle_first_off(page: Page, sel: str) -> None:
    page.locator(f"{sel} button").first.click()
    page.wait_for_function(
        "sel => document.querySelector(sel + ' button').getAttribute('aria-pressed') === 'false'",
        arg=sel,
    )
    page.wait_for_timeout(400)  # past the double-click window
    chips = _assert_shared_chips(page, sel)
    off = chips[0]
    on = next(c for c in chips if c["pressed"] == "true")
    assert off["color"] != on["color"]  # muted text when off


def test_cfb_legend_chips(guarded_page: Page, open_app: Callable[..., None]) -> None:
    open_app(guarded_page, "")
    _assert_shared_chips(guarded_page, "#legend-chips")


@pytest.mark.parametrize(
    ("view", "sel"),
    [
        ("special", "#nfl-view-special .legend-chips"),
        ("scatter", "#nfl-view-scatter .legend-chips"),
        ("viewership", "#nfl-view-viewership .legend-chips"),
    ],
)
def test_nfl_legend_chips(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], view: str, sel: str
) -> None:
    page = nfl_guarded_page
    open_nfl_app(page, f"?sport=nfl&view={view}")
    page.wait_for_selector(f"{sel} button")
    _assert_shared_chips(page, sel)
    _toggle_first_off(page, sel)


def test_mlb_scatter_legend_chips(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    page = mlb_guarded_page
    open_mlb_app(page, "?sport=mlb&view=scatter")
    sel = "#mlb-view-scatter .legend-chips"
    page.wait_for_selector(f"{sel} button")
    _assert_shared_chips(page, sel)
    _toggle_first_off(page, sel)
