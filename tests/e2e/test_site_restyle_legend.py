"""Phase 26 round 3: legend chips are a colour mark plus a label with no outline. On = filled,
off = empty ring with a muted label, no games = dotted ring with the --legend-none label
(4.61:1 light, 5.24:1 dark). Checked on the CFB, NFL and MLB legends. Synthetic fixtures only.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from contrast import ratio
from dark_checks import set_theme
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

THEMES = ["light", "dark"]
CLEAR = "rgba(0, 0, 0, 0)"

_TOKEN_JS = """(name) => {
  const probe = document.createElement('span');
  probe.style.color = `var(${name})`;
  document.body.appendChild(probe);
  const value = getComputedStyle(probe).color;
  probe.remove();
  return value;
}"""

_LOOK_JS = """(el) => {
  const s = getComputedStyle(el);
  const d = getComputedStyle(el.querySelector('.legend-dot'));
  return {
    color: s.color, bg: s.backgroundColor, border: s.borderTopWidth,
    mark: el.style.getPropertyValue('--mark'),
    dotBg: d.backgroundColor, dotRing: d.borderTopColor, dotStyle: d.borderTopStyle,
    dotWidth: d.borderTopWidth,
  };
}"""

# The family palette values the shared legend passes in as --mark.
_PALETTE_JS = """(theme) => import(new URL('./modules/palette.js', location.href).href)
  .then((p) => p.FAMILY_COLORS[theme])"""


def _token(page: Page, name: str) -> str:
    return str(page.evaluate(_TOKEN_JS, name))


def _look(page: Page, chip_selector: str) -> dict[str, Any]:
    out: dict[str, Any] = page.locator(chip_selector).first.evaluate(_LOOK_JS)
    return out


def _force_state(page: Page, chip_selector: str, pressed: str, offered: str | None) -> None:
    """Sets the attributes the legend renders, so each state is measured on a real chip."""
    page.locator(chip_selector).first.evaluate(
        """(el, [pressed, offered]) => {
          el.setAttribute('aria-pressed', pressed);
          if (offered === null) el.removeAttribute('data-offered');
          else el.setAttribute('data-offered', offered);
        }""",
        [pressed, offered],
    )


def _assert_three_states(page: Page, chip_selector: str) -> None:
    page.locator(chip_selector).first.scroll_into_view_if_needed()
    bg = _token(page, "--bg")
    # On: a filled mark, --ink label.
    _force_state(page, chip_selector, "true", None)
    on = _look(page, chip_selector)
    assert on["bg"] == CLEAR and on["border"] == "0px", on
    assert on["dotBg"] == on["dotRing"] != CLEAR, on
    assert on["color"] == _token(page, "--ink"), on
    # Off: an empty ring (truly empty), --muted label.
    _force_state(page, chip_selector, "false", None)
    off = _look(page, chip_selector)
    assert off["dotBg"] == CLEAR and off["dotRing"] == on["dotRing"], off
    assert off["dotStyle"] == "solid" and off["dotWidth"] == "2px", off
    assert off["color"] == _token(page, "--muted"), off
    # No games: a dotted empty ring, --legend-none label, whatever the pressed state.
    for pressed in ("true", "false"):
        _force_state(page, chip_selector, pressed, "false")
        none = _look(page, chip_selector)
        assert none["dotBg"] == CLEAR and none["dotStyle"] == "dotted", none
        assert none["dotRing"] == on["dotRing"], none
        assert none["color"] == _token(page, "--legend-none"), none
        assert none["bg"] == CLEAR and none["border"] == "0px", none
    for label in (on["color"], off["color"], none["color"]):
        assert ratio(label, bg) >= 4.5, (label, bg)


@pytest.mark.parametrize("theme", THEMES)
def test_cfb_legend_states(
    guarded_page: Page, open_app: Callable[[Page, str], None], theme: str
) -> None:
    guarded_page.set_viewport_size({"width": 1440, "height": 900})
    open_app(guarded_page, "")
    set_theme(guarded_page, theme)
    _assert_three_states(guarded_page, "#legend-chips button[data-family='fox']")


@pytest.mark.parametrize("theme", THEMES)
def test_cfb_mark_equals_the_family_palette_colour(
    guarded_page: Page, open_app: Callable[[Page, str], None], theme: str
) -> None:
    guarded_page.set_viewport_size({"width": 1440, "height": 900})
    open_app(guarded_page, "")
    set_theme(guarded_page, theme)
    palette = guarded_page.evaluate(_PALETTE_JS, theme)
    for family in ("disney", "fox", "other"):
        sel = f"#legend-chips button[data-family='{family}']"
        look = _look(guarded_page, sel)
        hexv = palette[family].lstrip("#")
        r, g, b = (int(hexv[i : i + 2], 16) for i in (0, 2, 4))
        assert look["dotRing"] == f"rgb({r}, {g}, {b})", (family, look)
        assert look["mark"].strip().lower() == palette[family].lower(), (family, look)


def test_legend_label_contrast_values(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """The user's watch item: the no-games label clears 4.5:1 (4.61 light, 5.24 dark)."""
    open_app(guarded_page, "")
    for theme, expected in (("light", 4.61), ("dark", 5.24)):
        set_theme(guarded_page, theme)
        got = ratio(_token(guarded_page, "--legend-none"), _token(guarded_page, "--bg"))
        assert got == pytest.approx(expected, abs=0.02), (theme, got)


@pytest.mark.parametrize("theme", THEMES)
def test_nfl_legend_states(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], theme: str
) -> None:
    nfl_guarded_page.set_viewport_size({"width": 1440, "height": 900})
    open_nfl_app(nfl_guarded_page, "?sport=nfl&view=scatter")
    set_theme(nfl_guarded_page, theme)
    _assert_three_states(nfl_guarded_page, "#nfl-view-scatter .legend-chips button")


@pytest.mark.parametrize("theme", THEMES)
def test_mlb_legend_states(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None], theme: str
) -> None:
    mlb_guarded_page.set_viewport_size({"width": 1440, "height": 900})
    open_mlb_app(mlb_guarded_page, "?sport=mlb&view=scatter")
    set_theme(mlb_guarded_page, theme)
    _assert_three_states(mlb_guarded_page, "#mlb-view-scatter .legend-chips button")
