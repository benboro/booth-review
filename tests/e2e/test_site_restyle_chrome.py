"""Phase 26 chrome treatment T3 "Frame + recede", measured by computed styles in light and dark:
the ink rules on the header, footer and panels, the quiet module, segmented and tab rules, the
panel and tooltip surfaces. Synthetic fixtures only.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from conftest import WEEKEND_MAP_NOW
from dark_checks import set_theme
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

THEMES = ["light", "dark"]


# Chromium snaps a border to whole CSS pixels (a 1.5px border reads back as 1px at any device
# scale), so a 1.5px rule is checked two ways: the stylesheet declares 1.5px, and the computed
# width is a solid 1px or 1.5px in the ink colour (what Safari and Firefox render at scale 2).
_DECLARED_JS = """(args) => {
  const [selector, prop] = args;
  const el = document.querySelector(selector);
  let found = null;
  for (const sheet of document.styleSheets) {
    for (const rule of sheet.cssRules) {
      if (rule.type !== CSSRule.STYLE_RULE) continue;
      if (!el.matches(rule.selectorText)) continue;
      const v = rule.style.getPropertyValue(prop);
      if (v) found = v;
    }
  }
  return found;
}"""

_TOKEN_JS = """(name) => {
  const probe = document.createElement('span');
  probe.style.color = `var(${name})`;
  document.body.appendChild(probe);
  const value = getComputedStyle(probe).color;
  probe.remove();
  return value;
}"""

_STYLE_JS = """(args) => {
  const [selector, props] = args;
  const el = document.querySelector(selector);
  if (!el) return null;
  const cs = getComputedStyle(el);
  return Object.fromEntries(props.map((p) => [p, cs.getPropertyValue(p)]));
}"""


def token(page: Page, name: str) -> str:
    """The computed rgb() of a colour token in the page's current theme."""
    return str(page.evaluate(_TOKEN_JS, name))


def style(page: Page, selector: str, *props: str) -> dict[str, str]:
    got = page.evaluate(_STYLE_JS, [selector, list(props)])
    assert got is not None, f"{selector} not found"
    return dict(got)


def declared(page: Page, selector: str, prop: str) -> str | None:
    """The last top-level stylesheet value of `prop` for a rule matching `selector`."""
    value = page.evaluate(_DECLARED_JS, [selector, prop])
    return None if value is None else str(value)


def assert_rule(page: Page, selector: str, side: str) -> None:
    """The element carries a solid 1.5px ink rule on `side` (top or bottom)."""
    width = style(page, selector, f"border-{side}-width")[f"border-{side}-width"]
    assert width in ("1px", "1.5px"), (selector, width)
    # A shorthand with var() leaves its longhands empty, so read the shorthand's text.
    assert (declared(page, selector, f"border-{side}") or "").startswith("1.5px solid"), (
        selector,
        side,
    )
    color = style(page, selector, f"border-{side}-color")[f"border-{side}-color"]
    assert color == token(page, "--ink"), (selector, side, color)
    assert style(page, selector, f"border-{side}-style")[f"border-{side}-style"] == "solid"


def assert_ink_top(page: Page, selector: str) -> None:
    got = style(page, selector, "border-top-style", "border-top-color", "border-radius")
    assert_rule(page, selector, "top")
    assert got["border-top-style"] == "solid", (selector, got)
    assert got["border-top-color"] == token(page, "--ink"), (selector, got)


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("page_name", ["methodology", "coverage"])
def test_static_pages_header_and_footer_ink_rules(
    guarded_page: Page, site_url: str, page_name: str, theme: str
) -> None:
    guarded_page.goto(f"{site_url}/{page_name}.html")
    set_theme(guarded_page, theme)
    assert_rule(guarded_page, ".site-header", "bottom")
    head = style(guarded_page, ".site-header", "background-color")
    assert head["background-color"] in ("rgba(0, 0, 0, 0)", token(guarded_page, "--bg")), head
    assert_rule(guarded_page, ".site-footer", "top")


@pytest.mark.parametrize("theme", THEMES)
def test_cfb_header_footer_toolbar_and_module(
    guarded_page: Page, open_app: Callable[[Page, str], None], theme: str
) -> None:
    guarded_page.set_viewport_size({"width": 1440, "height": 900})
    open_app(guarded_page, "")
    set_theme(guarded_page, theme)
    ink = token(guarded_page, "--ink")
    rule = token(guarded_page, "--rule")
    bg = token(guarded_page, "--bg")
    transparent = ("rgba(0, 0, 0, 0)", bg)

    assert_rule(guarded_page, "#topbar", "bottom")
    assert_rule(guarded_page, ".site-footer", "top")

    bar = style(guarded_page, "#toolbar", "background-color", "border-bottom-width")
    assert bar["background-color"] in transparent, bar
    assert bar["border-bottom-width"] == "1px", bar
    assert style(guarded_page, "#toolbar", "border-bottom-color")["border-bottom-color"] == rule

    mod = style(
        guarded_page,
        ".module",
        "border-top-width",
        "border-top-color",
        "border-radius",
        "box-shadow",
        "padding-top",
        "padding-left",
        "margin-bottom",
    )
    assert mod["border-top-width"] == "1px", mod
    assert mod["border-top-color"] == rule, mod
    assert mod["border-radius"] == "0px", mod
    assert mod["box-shadow"] == "none", mod
    assert (mod["padding-top"], mod["padding-left"]) == ("20px", "24px"), mod
    assert mod["margin-bottom"] == "32px", mod

    tabs = style(guarded_page, ".chart-tabs", "border-bottom-color", "border-bottom-width")
    assert tabs == {"border-bottom-color": rule, "border-bottom-width": "1px"}

    selected = guarded_page.locator(".segmented button[aria-pressed='true']").first
    shadow = selected.evaluate("(e) => getComputedStyle(e).boxShadow")
    assert ink in shadow and "inset" in shadow, shadow
    assert selected.evaluate("(e) => getComputedStyle(e).backgroundColor") == token(
        guarded_page, "--surface"
    )
    weights = guarded_page.evaluate(
        "[...document.querySelectorAll('.segmented button')]"
        ".map((b) => getComputedStyle(b).fontWeight)"
    )
    assert len(set(weights)) == 1, weights


def test_module_padding_is_16px_on_a_phone(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    guarded_page.set_viewport_size({"width": 390, "height": 844})
    open_app(guarded_page, "")
    mod = style(guarded_page, ".module", "padding-top", "padding-left", "padding-right")
    assert set(mod.values()) == {"16px"}, mod


@pytest.mark.parametrize("theme", THEMES)
def test_scatter_panel_and_tooltip(
    guarded_page: Page, open_app: Callable[[Page, str], None], theme: str
) -> None:
    guarded_page.set_viewport_size({"width": 1440, "height": 900})
    open_app(guarded_page, "")
    set_theme(guarded_page, theme)
    guarded_page.evaluate("window.__testHooks.openPanel(2)")
    guarded_page.wait_for_function("document.getElementById('detail-panel').open")
    assert_ink_top(guarded_page, "#detail-panel")
    got = style(
        guarded_page,
        "#detail-panel",
        "border-radius",
        "background-color",
        "border-left-color",
        "border-left-width",
    )
    assert got["border-radius"] == "4px", got
    assert got["background-color"] == token(guarded_page, "--bg"), got
    assert got["border-left-color"] == token(guarded_page, "--rule"), got
    assert got["border-left-width"] == "1px", got


@pytest.mark.parametrize("theme", THEMES)
def test_tooltip_sits_on_the_page_colour(
    guarded_page: Page, open_app: Callable[[Page, str], None], theme: str
) -> None:
    guarded_page.set_viewport_size({"width": 1440, "height": 900})
    open_app(guarded_page, "")
    set_theme(guarded_page, theme)
    guarded_page.evaluate(
        "() => { const t = document.createElement('div'); t.className = 'chart-tooltip';"
        " t.id = 'probe-tooltip'; document.body.appendChild(t); }"
    )
    got = style(guarded_page, "#probe-tooltip", "background-color", "border-radius", "box-shadow")
    assert got["background-color"] == token(guarded_page, "--bg"), got
    assert got["border-radius"] == "4px", got
    assert got["box-shadow"] == "none", got


@pytest.mark.parametrize("theme", THEMES)
def test_this_weekend_cell_and_map_panels(
    guarded_page: Page,
    serve_weekend_map: Callable[..., None],
    open_app: Callable[[Page, str], None],
    theme: str,
) -> None:
    guarded_page.set_viewport_size({"width": 1440, "height": 900})
    serve_weekend_map(guarded_page, WEEKEND_MAP_NOW)
    open_app(guarded_page, "?view=weekend")
    set_theme(guarded_page, theme)
    guarded_page.wait_for_selector(".wk-cell")
    guarded_page.locator(".wk-cell").first.click()
    dialog = guarded_page.locator("dialog[open]")
    expect(dialog).to_be_visible()
    assert_ink_top(guarded_page, "dialog[open]")
    assert style(guarded_page, "dialog[open]", "border-radius")["border-radius"] == "4px"
    guarded_page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)

    open_app(guarded_page, "?view=weekend&wview=map")
    guarded_page.wait_for_selector(".wk-notmap .wk-cell")
    set_theme(guarded_page, theme)
    guarded_page.locator(".wk-notmap .wk-cell").first.click()
    expect(guarded_page.locator("dialog[open]")).to_be_visible()
    assert_ink_top(guarded_page, "dialog[open]")
    assert style(guarded_page, "dialog[open]", "border-radius")["border-radius"] == "4px"


@pytest.mark.parametrize("theme", THEMES)
def test_nfl_panel_and_toolbar(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], theme: str
) -> None:
    nfl_guarded_page.set_viewport_size({"width": 1440, "height": 900})
    open_nfl_app(nfl_guarded_page, "?sport=nfl&view=scatter")
    set_theme(nfl_guarded_page, theme)
    bar = style(nfl_guarded_page, "#nfl-toolbar", "background-color", "border-bottom-width")
    assert bar["background-color"] in ("rgba(0, 0, 0, 0)", token(nfl_guarded_page, "--bg")), bar
    assert bar["border-bottom-width"] == "1px", bar
    nfl_guarded_page.evaluate("window.__nflTestHooks.openGame(0)")
    nfl_guarded_page.locator("#nfl-detail-panel").wait_for(state="visible")
    assert_ink_top(nfl_guarded_page, "#nfl-detail-panel")
    got = style(nfl_guarded_page, "#nfl-detail-panel", "border-radius", "background-color")
    assert got["border-radius"] == "4px", got
    assert got["background-color"] == token(nfl_guarded_page, "--bg"), got


@pytest.mark.parametrize("theme", THEMES)
def test_mlb_panel(mlb_guarded_page: Page, open_mlb_app: Callable[..., None], theme: str) -> None:
    mlb_guarded_page.set_viewport_size({"width": 1440, "height": 900})
    open_mlb_app(mlb_guarded_page, "?sport=mlb&view=scatter")
    set_theme(mlb_guarded_page, theme)
    mlb_guarded_page.evaluate("window.__mlbTestHooks.openGame(0)")
    mlb_guarded_page.locator("#mlb-detail-panel").wait_for(state="visible")
    assert_ink_top(mlb_guarded_page, "#mlb-detail-panel")
    got: Any = style(mlb_guarded_page, "#mlb-detail-panel", "border-radius")
    assert got["border-radius"] == "4px", got
