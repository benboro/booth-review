"""Chart-level browser tests (SITE-01, SITE-03, SITE-04, SITE-12, SITE-18,
SITE-19, SITE-20, SITE-23, SITE-25, SITE-26; D-01..D-04, D-08, D-12, D-14,
D-15, D-16) -- proven against the fixture build served by
`guarded_page`/`mobile_page`/`open_app`/`site_url`, per
`tests/fixtures/contract/site-data.fixture.json`'s 12 dots.
"""

from __future__ import annotations

import base64
import json
import math
import re
from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page, expect
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

pytestmark = pytest.mark.e2e

# Computes the click/hover pixel for a telecast's dot from Plotly's own
# layout (mirrors tests/e2e/test_site_panel_table.py's `_DOT_PIXEL_JS`, but
# searches every trace rather than only `family:`-prefixed ones, since a
# highlighted dot lives exclusively in the `highlight` overlay trace): the
# first trace whose `customdata` holds the telecast index gives the plotted
# x/y, converted to page pixels via the axes' own `d2p` and the chart div's
# own size/offset -- never a hardcoded pixel guess. Inert traces carry no
# `customdata` at all (D-15: they're never hovered/clicked), so they're
# skipped rather than crashing `.indexOf` on `undefined`.
_DOT_PIXEL_JS = """
(customdata) => {
  const gd = document.getElementById('chart');
  const layout = gd._fullLayout;
  const rect = gd.getBoundingClientRect();
  for (const trace of gd.data) {
    if (!trace.customdata) continue;
    const idx = trace.customdata.indexOf(customdata);
    if (idx === -1) continue;
    // band (unrated) traces ride y2: use the trace's own y axis offset
    const ya = layout[trace.yaxis === 'y2' ? 'yaxis2' : 'yaxis'];
    return {
      x: rect.left + layout._size.l + layout.xaxis.d2p(trace.x[idx]),
      y: rect.top + ya._offset + ya.l2p(ya.d2l(trace.y[idx])),
    };
  }
  return null;
}
"""


def _dot_point(page: Page, customdata: int) -> dict[str, float]:
    # The toolbar row (04.1-04, D-02) sits above the chart and pushes it
    # further down the page than the old side rail did, so a dot's computed
    # pixel position can now land past the default viewport's bottom edge.
    # Scrolling the chart into view first keeps this independent of the
    # exact toolbar height.
    page.locator("#chart").scroll_into_view_if_needed()
    point: dict[str, float] | None = page.evaluate(_DOT_PIXEL_JS, customdata)
    assert point is not None, f"no dot with customdata {customdata}"
    return point


# An inert trace's dots have no `customdata` to search by (D-15) -- this
# instead reads a specific point straight off a named trace (`inert:<family>`)
# by its position within that trace's own x/y arrays.
_INERT_DOT_PIXEL_JS = """
([meta, index]) => {
  const gd = document.getElementById('chart');
  const layout = gd._fullLayout;
  const rect = gd.getBoundingClientRect();
  const trace = gd.data.find((t) => t.meta === meta);
  if (!trace || trace.x[index] === undefined) return null;
  return {
    x: rect.left + layout._size.l + layout.xaxis.d2p(trace.x[index]),
    y: rect.top + (trace.yaxis === 'y2' ? layout.yaxis2 : layout.yaxis)._offset
      + (trace.yaxis === 'y2' ? layout.yaxis2 : layout.yaxis).l2p(
        (trace.yaxis === 'y2' ? layout.yaxis2 : layout.yaxis).d2l(trace.y[index])),
  };
}
"""


def _inert_dot_point(page: Page, meta: str, index: int = 0) -> dict[str, float]:
    # See `_dot_point`'s comment: the toolbar row can push the chart past
    # the default viewport's bottom edge.
    page.locator("#chart").scroll_into_view_if_needed()
    point: dict[str, float] | None = page.evaluate(_INERT_DOT_PIXEL_JS, [meta, index])
    assert point is not None, f"no point at {meta}[{index}]"
    return point


_TRACES_JS = (
    "() => document.getElementById('chart').data.map(t => ("
    "{meta: t.meta, x: t.x, customdata: t.customdata, text: t.text, opacity: t.marker.opacity}))"
)


def _traces(page: Page) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = page.evaluate(_TRACES_JS)
    return result


def _dot_opacity(page: Page) -> dict[str, float]:
    """The exported DOT_OPACITY tier constant, imported in-page."""
    result: dict[str, float] = page.evaluate(
        "() => import('./modules/chart.js').then((m) => ({...m.DOT_OPACITY}))"
    )
    return result


def _marker_color(page: Page, meta: str) -> str:
    result: str = page.evaluate(
        "(meta) => document.getElementById('chart').data.find((t) => t.meta === meta).marker.color",
        meta,
    )
    return result


def _inert_total(traces: list[dict[str, Any]]) -> int:
    return sum(len(t["x"]) for t in _inert_traces(traces))


def _layout(page: Page) -> dict[str, Any]:
    result: dict[str, Any] = page.evaluate("() => document.getElementById('chart').layout")
    return result


def _family_traces(traces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The active traces (dots that pass every fade filter, D-14) -- these
    are the only traces carrying `customdata`/`text`."""
    return [t for t in traces if str(t["meta"]).startswith("family:")]


def _inert_traces(traces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The filtered-out traces (D-14/D-15) -- `x`/`opacity` only, no
    `customdata`/`text` (never hovered or clicked)."""
    return [t for t in traces if str(t["meta"]).startswith("inert:")]


def _dot_count(traces: list[dict[str, Any]]) -> int:
    """Real dots across `traces` (pass a `_family_traces` result -- inert
    traces carry no `customdata` key at all)."""
    return sum(1 for t in traces for cd in t["customdata"] if cd is not None)


def _dot_x_by_customdata(traces: list[dict[str, Any]]) -> dict[int, float]:
    points: dict[int, float] = {}
    for t in _family_traces(traces):
        for customdata, x in zip(t["customdata"], t["x"], strict=True):
            if customdata is not None:
                points[customdata] = x
    return points


def _hover_text(traces: list[dict[str, Any]], index: int) -> str:
    for t in _family_traces(traces):
        for customdata, text in zip(t["customdata"], t["text"], strict=True):
            if customdata == index:
                return str(text)
    raise AssertionError(f"no dot with customdata {index}")


def _hover_dot(
    page: Page, customdata: int, *, wait_for: str = "#chart-tooltip:not([hidden])"
) -> dict[str, float]:
    """Moves the mouse onto telecast `customdata`'s dot and waits for the
    D-22 HTML tooltip (or the `wait_for` selector) to show. Returns the
    dot's own pixel, for a caller that needs it afterward.

    Two vendored-Plotly quirks confirmed empirically this session, both
    specific to a page that has scrolled (D-22's own close-on-scroll feature
    means every hover test scrolls, via `_dot_point`'s own
    `scroll_into_view_if_needed()`):

    1. `scroll_into_view_if_needed()` can leave a *coalesced* `scroll` DOM
       event pending for a frame or two after the scroll position itself has
       already settled (`window.scrollY` is correct immediately, but the
       `scroll` event callback fires a frame later). Hovering immediately
       afterward raced that deferred event against our own close-on-scroll
       handler, which would hide the tooltip the instant it finally fired.
       Waiting two animation frames first lets it fire and settle before the
       tooltip ever shows.
    2. If the mouse never actually leaves a dot's pixel (a real native
       mousemove/mouseleave) before the page scrolls out from under it,
       Plotly's own gl2d hover picking gets stuck and never fires
       `plotly_hover` again at the dot's new (post-scroll) pixel, even
       though a click at that exact pixel still works. A real user's mouse
       is never frozen on a dot while the page independently scrolls, so
       this never happens outside a scripted test. Moving the mouse off the
       chart first forces a clean native mouseleave, which resets it.
    """
    page.mouse.move(5, 5)
    point = _dot_point(page, customdata)
    page.evaluate(
        "() => new Promise((resolve) => "
        "requestAnimationFrame(() => requestAnimationFrame(resolve)))"
    )
    for attempt in range(2):
        page.mouse.move(point["x"], point["y"])
        try:
            page.wait_for_selector(wait_for, timeout=3000)
            return point
        except PlaywrightTimeoutError:
            if attempt == 1:
                raise
            page.mouse.move(5, 5)
    return point


def _use_plotly_tooltip(page: Page) -> None:
    """Flips `TOOLTIP_MODE` to the D-22 fallback path at runtime
    (`window.__testHooks.setTooltipMode`) and waits for the highlight
    trace's own `hovertemplate` to reflect it, so a test reading Plotly's
    hover label/trace `text` right after this call never races the mode
    switch's own re-render."""
    page.evaluate("window.__testHooks.setTooltipMode('plotly')")
    page.wait_for_function(
        "document.getElementById('chart').data.at(-1).hovertemplate === '%{text}<extra></extra>'"
    )


def test_default_load_shows_all_dots_no_selection_spread_axis(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-12: first load with no query shows all 12 dots, nobody highlighted,
    and the Spread axis, with a clean URL."""
    open_app(guarded_page, "")
    traces = _traces(guarded_page)
    family_traces = _family_traces(traces)

    assert _dot_count(family_traces) == 12
    assert {t["meta"] for t in family_traces} == {
        "family:disney",
        "family:fox",
        "family:conference",
        "family:other",
    }
    assert traces[-1]["meta"] == "highlight"
    assert len(traces[-1]["x"]) == 0
    assert "?" not in guarded_page.url
    assert (
        guarded_page.get_attribute('#axis-toggle button[data-axis="spread"]', "aria-pressed")
        == "true"
    )
    assert guarded_page.is_hidden("#excitement-caption")
    for t in family_traces:
        assert t["opacity"] == 1


def test_na_strip_places_missing_x_dots_in_the_reserved_band(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-08: dots 2, 3, 10 (Spread: no score, no line, tie) / dot 2 (excitement)
    sit left of the divider, everything else sits to its right, and the strip
    is labelled N/A."""
    open_app(guarded_page, "")
    layout = _layout(guarded_page)
    divider = layout["shapes"][0]["x0"]
    points = _dot_x_by_customdata(_traces(guarded_page))
    for missing in (2, 3, 10):
        assert points[missing] < divider
    for customdata, x in points.items():
        if customdata not in (2, 3, 10):
            assert x > divider
    assert any(a["text"] == "N/A" for a in layout["annotations"])

    open_app(guarded_page, "?axis=excitement")
    layout2 = _layout(guarded_page)
    divider2 = layout2["shapes"][0]["x0"]
    points2 = _dot_x_by_customdata(_traces(guarded_page))
    assert points2[2] < divider2
    for customdata, x in points2.items():
        if customdata != 2:
            assert x > divider2


def test_axis_toggle_shows_excitement_caption_and_persists_on_reload(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """SITE-03/SITE-12, D-04: toggling to excitement busts the URL and shows
    the 2025-break caption with a methodology link; reload keeps it pressed."""
    open_app(guarded_page, "")
    guarded_page.click('#axis-toggle button[data-axis="excitement"]')
    guarded_page.wait_for_function("location.search === '?axis=excitement'")

    assert guarded_page.url.endswith("?axis=excitement")
    assert guarded_page.is_visible("#excitement-caption")
    href = guarded_page.get_attribute("#excitement-caption a", "href")
    assert href is not None
    assert href.endswith("methodology.html#the-2025-excitement-break")

    guarded_page.reload()
    guarded_page.wait_for_function("window.__testHooks && window.__testHooks.ready === true")
    assert (
        guarded_page.get_attribute('#axis-toggle button[data-axis="excitement"]', "aria-pressed")
        == "true"
    )


def test_y_axis_ticks_use_short_labels_not_raw_exponents(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """SITE-01: log-viewers ticks read like '1M', never a raw exponent."""
    open_app(guarded_page, "")
    # SVG <text> nodes have no `innerText`; use `textContent` via
    # `all_text_contents` instead of `all_inner_texts`.
    texts = guarded_page.locator(".ytick text").all_text_contents()
    assert any("1M" in text for text in texts)
    assert not any(re.search(r"e[+-]?\d", text) for text in texts)


def test_y_axis_ticks_show_thousands_as_k_below_one_million(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """Below 1M, ticks read "500K"/"200K" -- never "0.5M"/"0.2M" -- and stay
    "1M"/"2M"/... at/above 1M."""
    open_app(guarded_page, "")
    texts = guarded_page.locator(".ytick text").all_text_contents()
    assert any("500K" in text for text in texts)
    assert any("1M" in text for text in texts)
    assert not any(re.search(r"0\.\dM", text) for text in texts)


def test_axis_titles_render_for_both_axes(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """CR-02: Plotly 4 drops a bare-string axis title, so both titles must be
    passed as `{text: ...}` and actually render in the SVG; the x title
    follows the axis toggle."""
    open_app(guarded_page, "")
    x_title = guarded_page.locator(".g-xtitle text").all_text_contents()
    y_title = guarded_page.locator(".g-ytitle text").all_text_contents()
    assert x_title == ["Winner's closing spread (points)"]
    assert y_title == ["Viewers (log scale)"]

    guarded_page.click('#axis-toggle button[data-axis="excitement"]')
    guarded_page.wait_for_function("location.search === '?axis=excitement'")
    assert guarded_page.locator(".g-xtitle text").all_text_contents() == ["Excitement index (CFBD)"]


def test_mobile_x_axis_title_fits_the_screen_and_clears_the_legend(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """CR-02 follow-up / D-09: the Spread title fits one line on a 390px phone,
    stays inside the viewport, and sits above the (below-chart) HTML chip legend
    (D-04: Plotly's own `.legend` is off everywhere now)."""
    open_app(mobile_page, "")
    boxes = mobile_page.evaluate(
        "() => ['.g-xtitle', '#legend-chips'].map(s => {"
        " const r = document.querySelector(s).getBoundingClientRect();"
        " return {left: r.left, right: r.right, top: r.top, bottom: r.bottom}; })"
    )
    title, legend = boxes
    width = mobile_page.evaluate("document.documentElement.clientWidth")
    assert title["left"] >= 0
    assert title["right"] <= width
    # A 1px tolerance absorbs sub-pixel rounding between the SVG title's own
    # bounding box and the immediately-following flex item's box -- the two
    # can land a fraction of a pixel apart with no real overlap.
    assert title["bottom"] <= legend["top"] + 1
    assert mobile_page.locator(".g-xtitle text tspan").count() <= 1
    title_text = mobile_page.evaluate("document.getElementById('chart').layout.xaxis.title.text")
    assert "<br>" not in title_text


_LEGEND_CHIP_LABELS = ["ABC/ESPN", "FOX/FS1/BTN", "Pac-12 Net/MW Net", "Other"]


def _chip_pressed_states(page: Page) -> list[str | None]:
    result: list[str | None] = page.locator("#legend-chips button").evaluate_all(
        "els => els.map(el => el.getAttribute('aria-pressed'))"
    )
    return result


def test_legend_chip_labels_are_slash_delimited_network_names(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-04: chip text names the networks in the family, slash-delimited,
    never the parent company (e.g. "ABC/ESPN", not "Disney (ABC/ESPN)")."""
    open_app(guarded_page, "")
    assert guarded_page.locator("#legend-chips button").all_text_contents() == _LEGEND_CHIP_LABELS
    assert _chip_pressed_states(guarded_page) == ["true"] * len(_LEGEND_CHIP_LABELS)


def test_legend_chip_click_toggles_family_and_hides_its_dots(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-16: clicking a legend chip toggles that family in the Networks
    filter, hides its dots (D-07), round-trips through the URL, and
    clicking it again clears the filter."""
    open_app(guarded_page, "")
    fox_chip = guarded_page.locator('#legend-chips button[data-family="fox"]')
    assert fox_chip.get_attribute("aria-pressed") == "true"

    fox_chip.click()
    guarded_page.wait_for_function("location.search.includes('networks=')")
    assert fox_chip.get_attribute("aria-pressed") == "false"
    assert "networks=" in guarded_page.url
    assert "net-b" not in guarded_page.url

    traces = _traces(guarded_page)
    assert _dot_count(_family_traces(traces)) == 9
    assert sum(len(t["x"]) for t in _inert_traces(traces)) == 0

    # Two clicks on one pill inside 300ms are a double-click (04.15 D-05); space them.
    guarded_page.wait_for_timeout(350)
    fox_chip.click()
    guarded_page.wait_for_function("location.search === ''")
    assert fox_chip.get_attribute("aria-pressed") == "true"
    assert _dot_count(_family_traces(_traces(guarded_page))) == 12


def test_legend_chip_enter_key_toggles_family(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-16: a chip is a native `<button>`, so Enter (like Space) activates
    it for free -- no separate keydown handler needed."""
    open_app(guarded_page, "")
    chip = guarded_page.locator('#legend-chips button[data-family="disney"]')
    chip.focus()
    guarded_page.keyboard.press("Enter")
    guarded_page.wait_for_function("location.search.includes('networks=')")
    assert chip.get_attribute("aria-pressed") == "false"
    assert "net-a" not in guarded_page.url


def test_legend_chip_greyed_when_family_has_no_offered_channel(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-16: with only dale-harlow (net-a) picked, other chips grey out but stay toggles."""
    open_app(guarded_page, "?people=dale-harlow")
    disney = guarded_page.locator('#legend-chips button[data-family="disney"]')
    expect(disney).to_have_attribute("data-offered", "true")
    # dale-harlow also works unrated game 17 (a conference network), so that chip stays offered
    conf = guarded_page.locator('#legend-chips button[data-family="conference"]')
    expect(conf).to_have_attribute("data-offered", "true")
    for family in ("fox", "other"):
        chip = guarded_page.locator(f'#legend-chips button[data-family="{family}"]')
        expect(chip).to_have_attribute("data-offered", "false")
        expect(chip).to_have_attribute("aria-pressed", "true")
        style = chip.evaluate(
            "el => { const s = getComputedStyle(el);"
            " return [s.backgroundColor, s.borderTopStyle]; }"
        )
        assert style[0] in ("rgba(0, 0, 0, 0)", "transparent")
        assert style[1] == "dashed"

    fox = guarded_page.locator('#legend-chips button[data-family="fox"]')
    fox.click()
    guarded_page.wait_for_function("window.__testHooks.getState().networks !== null")
    expect(guarded_page.locator('#legend-chips button[data-family="fox"]')).to_have_attribute(
        "aria-pressed", "false"
    )


def test_legend_chips_all_offered_by_default(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    values = guarded_page.locator("#legend-chips button").evaluate_all(
        "els => els.map(el => el.dataset.offered)"
    )
    assert values == ["true"] * 4


@pytest.mark.parametrize("query", ["?seasons=2021-2021", "?school=northfield"])
def test_legend_chips_all_read_pressed_when_a_non_network_filter_is_active(
    guarded_page: Page, open_app: Callable[[Page, str], None], query: str
) -> None:
    """A season range or School fade filter never touches the Networks
    filter, so every chip still reads pressed regardless of how many of that
    family's dots the other filter leaves passing."""
    open_app(guarded_page, query)
    assert guarded_page.locator("#legend-chips button").all_text_contents() == _LEGEND_CHIP_LABELS
    assert _chip_pressed_states(guarded_page) == ["true"] * len(_LEGEND_CHIP_LABELS)


def test_legend_chip_row_sits_above_the_chart_on_desktop(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-04/SITE-20: on desktop the chip row sits above the chart, never
    overlapping it."""
    open_app(guarded_page, "")
    legend_box = guarded_page.locator("#legend-chips").bounding_box()
    chart_box = guarded_page.locator("#chart").bounding_box()
    assert legend_box is not None
    assert chart_box is not None
    assert legend_box["y"] + legend_box["height"] <= chart_box["y"]


def test_legend_chip_row_sits_below_the_chart_on_mobile(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """On phones the chip row renders below the chart (unchanged from
    Phase 4's legend placement, `research/FEATURES.md` T15)."""
    open_app(mobile_page, "")
    legend_box = mobile_page.locator("#legend-chips").bounding_box()
    chart_box = mobile_page.locator("#chart").bounding_box()
    assert legend_box is not None
    assert chart_box is not None
    assert legend_box["y"] >= chart_box["y"] + chart_box["height"]


def test_chart_tabs_slot_holds_three_tabs(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """Phase 04.4 D-10: the slot Phase 04.2 reserved now holds the three chart
    tabs at a fixed 40px height, still above the legend row."""
    open_app(guarded_page, "")
    box = guarded_page.locator("#chart-tabs").bounding_box()
    assert box is not None
    assert box["height"] == 40
    assert guarded_page.locator("#chart-tabs [role=tab]").count() == 3

    legend_box = guarded_page.locator("#legend-chips").bounding_box()
    assert legend_box is not None
    assert box["y"] + box["height"] <= legend_box["y"]


# SITE-26: light-theme fill/text as `rgb(...)` strings (WCAG-AA verified,
# `04.1-UI-SPEC.md` Color: Pill text color -- disney/conference need white
# text, every other family needs black).
_PILL_CONTRAST = {
    "disney": ("rgb(0, 114, 178)", "rgb(255, 255, 255)"),
    "fox": ("rgb(0, 158, 115)", "rgb(0, 0, 0)"),
    "conference": ("rgb(0, 0, 0)", "rgb(255, 255, 255)"),
    "other": ("rgb(143, 143, 143)", "rgb(0, 0, 0)"),
}


def test_legend_chip_pill_fill_and_text_meet_wcag_aa_contrast(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """SITE-26: each pressed chip's computed background/text colors match
    the family's Okabe-Ito fill and its verified WCAG-AA pill text color."""
    open_app(guarded_page, "")
    for family, (bg, color) in _PILL_CONTRAST.items():
        chip = guarded_page.locator(f'#legend-chips button[data-family="{family}"]')
        styles = chip.evaluate(
            "el => { const s = getComputedStyle(el); return [s.backgroundColor, s.color]; }"
        )
        assert styles == [bg, color], family


def test_set_state_people_highlights_and_fades_family_traces(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """SITE-02/SITE-12: selecting a person highlights exactly their games and
    fades every other passing dot to the person-faded tier (D-02), keeping its color."""
    open_app(guarded_page, "")
    guarded_page.evaluate("window.__testHooks.setState({people: ['dale-harlow']})")

    traces = _traces(guarded_page)
    assert sorted(traces[-1]["customdata"]) == [0, 8]
    for t in _family_traces(traces):
        assert t["opacity"] == _dot_opacity(guarded_page)["activeUnderPerson"]
    assert guarded_page.url.endswith("?people=dale-harlow")


def test_networks_filter_hides_and_fade_filters_keep_family_color(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-07/D-01/D-03: `?networks=net-a` hides the other dots (no inert
    points); a fade filter such as `?slot=late` draws failing dots in their
    own family color at the inert tier, with hover fully suppressed on the
    resolved `_fullData` (both `hoverinfo: 'skip'` and `hovertemplate: null`
    are required, the 04-11 finding)."""
    open_app(guarded_page, "?networks=net-a")
    traces = _traces(guarded_page)
    assert sum(len(t["x"]) for t in _inert_traces(traces)) == 0
    assert _dot_count(_family_traces(traces)) == 3

    open_app(guarded_page, "?slot=late")
    tiers = _dot_opacity(guarded_page)
    traces = _traces(guarded_page)
    fox = next(t for t in _inert_traces(traces) if t["meta"] == "inert:fox")
    assert len(fox["x"]) == 3
    assert fox["opacity"] == tiers["inert"]
    assert _marker_color(guarded_page, "inert:fox") == "#009E73"

    full = guarded_page.evaluate(
        "() => document.getElementById('chart')._fullData"
        ".filter(t => String(t.meta).startsWith('inert:'))"
        ".map(t => [t.hoverinfo, t.hovertemplate])"
    )
    for hoverinfo, hovertemplate in full:
        assert hoverinfo == "skip"
        # Plotly's resolved `_fullData` reflects a `hovertemplate: null` input
        # back as `''`, not `null` -- either reads as "no template set".
        assert not hovertemplate


def test_inert_dots_take_no_hover_and_are_not_clickable(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-15: a filtered-out dot never fires `plotly_hover` and a click on its
    exact pixel leaves the detail panel closed."""
    open_app(guarded_page, "?slot=late")
    guarded_page.evaluate(
        "() => { window.__hoverMetas = []; "
        "document.getElementById('chart').on('plotly_hover', "
        "(ev) => { window.__hoverMetas.push(ev.points[0].data.meta); }); }"
    )
    point = _inert_dot_point(guarded_page, "inert:fox", 0)
    guarded_page.mouse.move(point["x"], point["y"])
    guarded_page.wait_for_timeout(300)
    assert guarded_page.evaluate("window.__hoverMetas") == []

    guarded_page.mouse.click(point["x"], point["y"])
    guarded_page.wait_for_timeout(200)
    assert guarded_page.evaluate("document.getElementById('detail-panel').open") is False


def test_person_matched_dot_that_fails_a_filter_renders_as_filtered_out(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-14 ("the filter wins"): Dale Harlow's two games (0, 8) are both
    regular-season, so a postseason-only filter fails them -- the highlight
    overlay is empty and both dots sit in their family's inert trace instead
    of being drawn highlighted."""
    open_app(guarded_page, "")
    guarded_page.evaluate(
        "window.__testHooks.setState({people: ['dale-harlow'], postseason: 'only'})"
    )
    traces = _traces(guarded_page)
    assert traces[-1]["meta"] == "highlight"
    assert len(traces[-1]["x"]) == 0

    disney_inert = next(t for t in _inert_traces(traces) if t["meta"] == "inert:disney")
    assert -3.5 in disney_inert["x"]  # dot 0's spread (home favorite won)
    assert -6.5 in disney_inert["x"]  # dot 8's spread (away favorite won)
    # Filter wins (04.1 D-14) at the person-faded inert tier (04.7 D-02),
    # still in the family's own color (D-01).
    assert disney_inert["opacity"] == _dot_opacity(guarded_page)["inertUnderPerson"]
    assert _marker_color(guarded_page, "inert:disney") == _marker_color(
        guarded_page, "family:disney"
    )


def test_hover_text_stays_minimal_and_drops_methodology_notes(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """SITE-25 (product notes 2026-09-27): the tooltip carries only the
    matchup+score, date+kickoff (+ Bowl / CFP round for postseason games,
    never a time-slot label), networks, crew, viewers, the active
    axis value, and a closing "Click for details →" hint -- the
    measurement/scoring-source label, conferences, game type, and
    flags/combined-feed notes are dropped from the tooltip (they still show
    in the detail panel: see test_site_panel_table.py's
    test_open_panel_hook_shows_nielsen_adobe_badge,
    test_open_panel_hook_shows_flag_label,
    test_open_panel_hook_shows_alt_cast_and_combined_feeds, and
    test_panel_time_slot_shown_only_for_saturday_games)."""
    open_app(guarded_page, "")
    _use_plotly_tooltip(guarded_page)
    traces = _traces(guarded_page)

    dot0 = _hover_text(traces, 0)
    assert "Lakeview 20 at Northfield 27" in dot0
    assert "Sat, Sep 7, 2019" in dot0
    assert "Noon" not in dot0
    assert dot0.endswith("Click for details →")
    assert "Measurement" not in dot0
    assert "Source" not in dot0
    assert "Selected:" not in dot0
    # Only the crew lines carry a parenthetical (the role), never a methodology note.
    assert "(" not in "".join(
        ln for ln in dot0.split("<br>") if not ln.endswith(("(PBP)", "(Analyst)"))
    )

    dot5 = _hover_text(traces, 5)
    assert "Nielsen + Adobe" not in dot5
    assert "Prime time" not in dot5
    assert "Thursday" not in dot5

    dot7 = _hover_text(traces, 7)
    assert "Combined across" not in dot7
    assert "Noon" not in dot7
    assert "Afternoon" not in dot7
    assert "Prime time" not in dot7
    assert (
        '<span style="color:#8F8F8F">Other Network</span>'
        '/<span style="color:#0072B2">Alpha Sports</span>'
        '/<span style="color:#009E73">Beta Network</span>'
    ) in dot7


def test_hover_text_network_line_is_slash_joined_primary_first(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """SITE-26: a multi-outlet telecast lists networks slash-delimited (no
    spaces around '/'), primary first, each colored by its own family --
    the tooltip stand-in for a filled pill, since Plotly's hover renderer
    can't draw one."""
    open_app(guarded_page, "")
    _use_plotly_tooltip(guarded_page)
    traces = _traces(guarded_page)
    dot4 = _hover_text(traces, 4)
    assert (
        '<span style="color:#0072B2">Alpha Sports</span>'
        '/<span style="color:#009E73">Beta Network</span>'
    ) in dot4
    assert "(also" not in dot4
    assert " / " not in dot4


def test_hover_text_strips_nested_network_notes(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    fixture_raw: dict[str, Any],
) -> None:
    """A network's display name can carry a methodology aside (e.g.
    `data/reference/networks.csv`'s "ESPN Plus (regional insert package,
    pre-2018)"); the tooltip strips that nested parenthetical -- tooltip
    only, the panel/table keep the fuller name."""
    mutated = json.loads(json.dumps(fixture_raw))
    mutated["lookups"]["networks"][0]["name"] = "Alpha Sports (regional insert package)"
    body = json.dumps(mutated)

    guarded_page.route(
        "**/site-data.json*",
        lambda route: route.fulfill(status=200, content_type="application/json", body=body),
    )
    open_app(guarded_page, "")
    _use_plotly_tooltip(guarded_page)

    traces = _traces(guarded_page)
    dot0 = _hover_text(traces, 0)
    assert "Alpha Sports" in dot0
    assert "regional insert package" not in dot0


def test_hover_text_crew_lines_use_name_then_role(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """Plotly-fallback hover text: one "Name (Role)" line per main-feed crew
    member, pbp before analyst before sideline/other."""
    open_app(guarded_page, "")
    _use_plotly_tooltip(guarded_page)
    traces = _traces(guarded_page)
    lines = _hover_text(traces, 0).split("<br>")
    assert "Dale Harlow (PBP)" in lines
    assert "Dale Harlow Jr. (Analyst)" in lines
    assert lines.index("Dale Harlow (PBP)") < lines.index("Dale Harlow Jr. (Analyst)")


def test_hover_text_shows_the_active_axis_value_and_closing_hint(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """SITE-25: the tooltip's sixth line is the active axis's own value,
    never the other axis's."""
    open_app(guarded_page, "")
    _use_plotly_tooltip(guarded_page)
    dot11 = _hover_text(_traces(guarded_page), 11)
    assert "Spread: Stonebridge \u22121.5" in dot11
    assert "Excitement:" not in dot11
    assert dot11.endswith("Click for details →")

    guarded_page.click('#axis-toggle button[data-axis="excitement"]')
    guarded_page.wait_for_function("location.search === '?axis=excitement'")
    dot11 = _hover_text(_traces(guarded_page), 11)
    assert "Excitement: 3.0" in dot11
    assert "Spread:" not in dot11


def test_missing_site_data_shows_load_error(guarded_page: Page, site_url: str) -> None:
    """A failed site-data.json fetch unhides #load-error with its copy."""
    guarded_page.route("**/site-data.json*", lambda route: route.fulfill(status=404))
    guarded_page.goto(f"{site_url}/index.html")
    guarded_page.wait_for_function("window.__testHooks && window.__testHooks.ready === true")

    assert guarded_page.is_visible("#load-error")
    assert "Couldn't load the site data." in guarded_page.inner_text("#load-error")


def test_plotly_failing_to_load_shows_load_error(guarded_page: Page, site_url: str) -> None:
    """WR-04: if the Plotly bundle never loads (blocked, or an SRI mismatch),
    the first render can't run -- the app shows #load-error instead of an
    empty chart."""
    guarded_page.route("**/vendor/plotly-*.js", lambda route: route.abort())
    guarded_page.goto(f"{site_url}/index.html")
    guarded_page.wait_for_function("window.__testHooks && window.__testHooks.ready === true")

    assert guarded_page.evaluate("window.__testHooks.failed") is True
    assert guarded_page.is_visible("#load-error")
    assert guarded_page.is_hidden("#chart")


def test_payload_that_breaks_prepare_data_shows_load_error(
    guarded_page: Page, site_url: str, fixture_raw: dict[str, Any]
) -> None:
    """WR-04: a parseable site-data.json whose shape still breaks startup
    (here: no crew column) shows #load-error rather than failing silently."""
    mutated = json.loads(json.dumps(fixture_raw))
    del mutated["telecasts"]["crew"]
    body = json.dumps(mutated)
    guarded_page.route(
        "**/site-data.json*",
        lambda route: route.fulfill(status=200, content_type="application/json", body=body),
    )
    guarded_page.goto(f"{site_url}/index.html")
    guarded_page.wait_for_function("window.__testHooks && window.__testHooks.ready === true")

    assert guarded_page.evaluate("window.__testHooks.failed") is True
    assert guarded_page.is_visible("#load-error")


def test_mobile_layout_disables_drag_zoom_and_moves_legend_below(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """SITE-18/D-04: on phones, drag-zoom is off, axis ranges are fixed,
    Plotly's own legend stays off (`showlegend: false`, unchanged from
    desktop), and the HTML chip legend renders below the chart."""
    open_app(mobile_page, "")
    layout = _layout(mobile_page)

    assert layout["dragmode"] is False
    assert layout["xaxis"]["fixedrange"] is True
    assert layout["showlegend"] is False

    legend_box = mobile_page.locator("#legend-chips").bounding_box()
    chart_box = mobile_page.locator("#chart").bounding_box()
    assert legend_box is not None
    assert chart_box is not None
    assert legend_box["y"] >= chart_box["y"] + chart_box["height"]


def test_mobile_page_has_no_horizontal_scroll(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """SITE-18: the chart fits the phone viewport; a grid track sized to the
    Plotly SVG's own width must not push the page wider than the screen."""
    open_app(mobile_page, "")
    widths = mobile_page.evaluate(
        "() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]"
    )

    assert widths[0] <= widths[1]


def test_highlighted_dots_are_not_duplicated_in_their_faded_family_trace(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """T3/D-02: with nobody selected every dot lives in its family's active
    trace as normal. Once a person is selected, each highlighted dot is
    drawn *only* by the highlight overlay (its family trace drops the
    now-redundant duplicate) -- otherwise the coincident faded copy
    underneath and the highlight overlay's own dot would compete equally for
    hover/click, which is exactly what left them "treated equally" instead
    of snapping to the highlighted one."""
    open_app(guarded_page, "")
    traces = _traces(guarded_page)
    assert _dot_count(_family_traces(traces)) == 12
    assert len(traces[-1]["x"]) == 0

    guarded_page.evaluate("window.__testHooks.setState({people: ['dale-harlow']})")
    traces = _traces(guarded_page)
    highlighted_customdata = set(traces[-1]["customdata"])
    assert highlighted_customdata == {0, 8}
    family_customdata = {
        cd for t in _family_traces(traces) for cd in t["customdata"] if cd is not None
    }
    assert family_customdata.isdisjoint(highlighted_customdata)
    # every non-highlighted dot is still there, just not the highlighted two
    assert family_customdata == set(range(12)) - highlighted_customdata


def test_hover_snaps_to_highlighted_dot_over_a_coincident_faded_dot(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """SITE-25/T3: hovering directly on a highlighted dot's position always
    reports the highlight overlay trace, never a coincident duplicate in its
    (now-faded) family trace. Dot 0 is one of Dale Harlow's two highlighted
    games."""
    open_app(guarded_page, "")
    _use_plotly_tooltip(guarded_page)
    guarded_page.evaluate("window.__testHooks.setState({people: ['dale-harlow']})")

    guarded_page.evaluate(
        "() => { window.__hoverMeta = null; "
        "document.getElementById('chart').on('plotly_hover', "
        "(ev) => { window.__hoverMeta = ev.points[0].data.meta; }); }"
    )
    point = _dot_point(guarded_page, 0)
    guarded_page.mouse.move(point["x"], point["y"])
    guarded_page.wait_for_function("window.__hoverMeta !== null")

    assert guarded_page.evaluate("window.__hoverMeta") == "highlight"


def test_faded_dots_take_no_hover_while_a_selection_exists(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """SITE-25: with a selection, faded active family traces skip hover
    entirely, so a hover near a highlighted dot snaps to it rather than to a
    nearer faded dot. Plotly drops `hoverinfo` whenever `hovertemplate` is
    set, so this checks the resolved `_fullData`, not just the input trace."""
    open_app(guarded_page, "")
    _use_plotly_tooltip(guarded_page)
    full_js = (
        "() => document.getElementById('chart')._fullData"
        ".filter(t => String(t.meta).startsWith('family:')).map(t => t.hoverinfo)"
    )
    assert "skip" not in guarded_page.evaluate(full_js)

    guarded_page.evaluate("window.__testHooks.setState({people: ['dale-harlow']})")
    assert set(guarded_page.evaluate(full_js)) == {"skip"}

    guarded_page.evaluate(
        "() => { window.__hoverMetas = []; "
        "document.getElementById('chart').on('plotly_hover', "
        "(ev) => { window.__hoverMetas.push(ev.points[0].data.meta); }); }"
    )
    # Positive control (WR-11): in this same state a hover on a highlighted
    # dot (dot 0) does fire, so an empty log further down means "the faded
    # dot took no hover", not "hover events never fire at all".
    point0 = _dot_point(guarded_page, 0)
    guarded_page.mouse.move(point0["x"], point0["y"])
    guarded_page.wait_for_function("window.__hoverMetas.length > 0", timeout=5000)
    assert guarded_page.evaluate("window.__hoverMetas") == ["highlight"]

    # Off the plot area (the chart's top-left margin), then start a fresh log.
    box = guarded_page.locator("#chart").bounding_box()
    assert box is not None
    guarded_page.mouse.move(box["x"] + 2, box["y"] + 2)
    guarded_page.wait_for_selector(".hoverlayer .hovertext", state="detached")
    guarded_page.evaluate("window.__hoverMetas = []")

    # Dot 1 is not one of Dale Harlow's games: hovering right on it must never
    # surface its faded family trace -- no family-trace hover event, and no
    # hover label showing dot 1's own matchup.
    dot1_matchup = re.sub(r"</?b>", "", _hover_text(_traces(guarded_page), 1).split("<br>")[0])
    point1 = _dot_point(guarded_page, 1)
    guarded_page.mouse.move(point1["x"], point1["y"])
    guarded_page.wait_for_timeout(300)
    metas: list[str] = guarded_page.evaluate("window.__hoverMetas")
    assert all(meta == "highlight" for meta in metas)
    label = "".join(guarded_page.locator(".hoverlayer .hovertext").all_text_contents())
    assert dot1_matchup not in label


def test_hover_label_renders_readable_multiline_text_without_literal_markup(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """T-04-06: the rendered hover label is multi-line (the template's own
    `<br>` tags render as real line breaks) and never shows literal markup
    text like `<br>` or `&lt;br&gt;` (previously the whole joined string,
    including those tags, was HTML-escaped before being handed to Plotly)."""
    open_app(guarded_page, "")
    _use_plotly_tooltip(guarded_page)
    point = _dot_point(guarded_page, 0)
    guarded_page.mouse.move(point["x"], point["y"])
    guarded_page.wait_for_selector(".hoverlayer .hovertext")

    lines = guarded_page.locator(".hoverlayer .hovertext tspan").all_text_contents()
    joined = "".join(lines)
    assert len(lines) >= 4, "expected a multi-line hover label"
    assert "<" not in joined
    assert "&lt;" not in joined
    assert "Lakeview" in joined


def test_hover_label_resists_injection_from_a_mutated_team_name(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    fixture_raw: dict[str, Any],
) -> None:
    """SITE-19/T-04-06: a malicious team name renders as literal text in the
    hover label (matching the panel/table injection guarantee in
    tests/e2e/test_site_panel_table.py::test_injection_resistant_team_name_and_javascript_url),
    never as a real `<img>` element, and its `onerror` never executes."""
    mutated = json.loads(json.dumps(fixture_raw))
    mutated["lookups"]["teams"][0]["name"] = '<img src=x onerror="window.__xss=1">'
    body = json.dumps(mutated)

    guarded_page.route(
        "**/site-data.json*",
        lambda route: route.fulfill(status=200, content_type="application/json", body=body),
    )
    open_app(guarded_page, "")
    _use_plotly_tooltip(guarded_page)

    point = _dot_point(guarded_page, 0)
    guarded_page.mouse.move(point["x"], point["y"])
    guarded_page.wait_for_selector(".hoverlayer .hovertext")

    assert guarded_page.evaluate("window.__xss") is None
    assert guarded_page.locator(".hoverlayer img").count() == 0
    text = "".join(guarded_page.locator(".hoverlayer .hovertext tspan").all_text_contents())
    assert "<img" in text


def test_hover_label_resists_injection_from_a_mutated_network_name(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    fixture_raw: dict[str, Any],
) -> None:
    """T-04.1-09: a malicious network name is escaped individually before
    being wrapped in the tooltip's family-colored `<span>` (SITE-26 pill
    stand-in) -- the surrounding markup is always `<span style="color:HEX">`
    with HEX pulled only from the FAMILY_COLORS constant, never from data,
    so it renders as literal text, never a real `<img>` element."""
    mutated = json.loads(json.dumps(fixture_raw))
    mutated["lookups"]["networks"][0]["name"] = '<img src=x onerror="window.__xss=1">'
    body = json.dumps(mutated)

    guarded_page.route(
        "**/site-data.json*",
        lambda route: route.fulfill(status=200, content_type="application/json", body=body),
    )
    open_app(guarded_page, "")
    _use_plotly_tooltip(guarded_page)

    point = _dot_point(guarded_page, 0)
    guarded_page.mouse.move(point["x"], point["y"])
    guarded_page.wait_for_selector(".hoverlayer .hovertext")

    assert guarded_page.evaluate("window.__xss") is None
    assert guarded_page.locator(".hoverlayer img").count() == 0
    text = "".join(guarded_page.locator(".hoverlayer .hovertext tspan").all_text_contents())
    assert "<img" in text


# ---------- D-22: the default HTML tooltip ----------


def test_html_tooltip_is_the_default_and_plotly_label_is_off(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-22: `TOOLTIP_MODE`/`__testHooks.tooltipMode` starts as `'html'`, a
    hover shows the custom tooltip, and Plotly's own hover label never
    renders alongside it."""
    open_app(guarded_page, "")
    assert guarded_page.evaluate("window.__testHooks.tooltipMode") == "html"

    _hover_dot(guarded_page, 0)

    assert guarded_page.locator(".hoverlayer .hovertext").count() == 0


def test_html_tooltip_content_is_minimal_with_network_pills(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-22/SITE-25/SITE-26: the tooltip holds the matchup, a "Position:
    Name" crew line, and the closing hint, with no conference/game-type/
    methodology text; each network in `.tooltip-networks` renders as a real
    `pill.js` pill with the family's verified WCAG-AA fill/text colors."""
    open_app(guarded_page, "")

    _hover_dot(guarded_page, 0)

    text = guarded_page.inner_text("#chart-tooltip")
    assert "Lakeview 20 at Northfield 27" in text
    assert "Dale Harlow" in text
    assert "Play-by-play:" not in text
    assert "Click for details →" in text
    assert "Conference" not in text
    assert "Bowl" not in text
    assert "Nielsen" not in text

    networks_text = guarded_page.inner_text("#chart-tooltip .tooltip-networks")
    assert networks_text == "Alpha Sports"

    disney_bg, disney_color = _PILL_CONTRAST["disney"]
    pill0 = guarded_page.locator("#chart-tooltip .tooltip-networks .pill").first
    assert pill0.evaluate(
        "el => { const s = getComputedStyle(el); return [s.backgroundColor, s.color]; }"
    ) == [disney_bg, disney_color]

    _hover_dot(guarded_page, 1)
    guarded_page.wait_for_function(
        "document.querySelector('#chart-tooltip .tooltip-title')?.textContent.includes('Foxhollow')"
    )
    fox_bg, fox_color = _PILL_CONTRAST["fox"]
    pill1 = guarded_page.locator("#chart-tooltip .tooltip-networks .pill").first
    assert pill1.evaluate(
        "el => { const s = getComputedStyle(el); return [s.backgroundColor, s.color]; }"
    ) == [fox_bg, fox_color]


def test_html_tooltip_names_every_named_game(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-19/D-10 (04.10 reverses 04.2 D-22's icon-only rule): the tooltip never
    shows a time-slot label; a rivalry, bowl or CFP game shows its decorative
    icons plus its visible name (no role/aria-label wrapper); a regular game
    shows neither icon nor name."""
    open_app(guarded_page, "")
    icon = "#chart-tooltip svg.game-type-icon"
    marker = guarded_page.locator("#chart-tooltip .tooltip-game-type")

    _hover_dot(guarded_page, 7)
    text = guarded_page.inner_text("#chart-tooltip")
    assert "Prime time" not in text
    assert "After dark" not in text
    assert "Harbor Bowl" in text
    assert "Acme" not in text
    bowl = guarded_page.locator(f'{icon}[data-kind="bowl"]')
    assert bowl.count() == 1
    assert bowl.get_attribute("aria-hidden") == "true"
    assert marker.get_attribute("role") is None
    assert marker.get_attribute("aria-label") is None
    assert guarded_page.locator(icon).count() == 1

    _hover_dot(guarded_page, 5)
    guarded_page.wait_for_selector(f'{icon}[data-kind="playoff"]')
    # The fixture's CFP game is a semifinal played at a bowl: bowl icon, trophy,
    # and the core bowl name with the round.
    assert guarded_page.locator(icon).count() == 2
    assert marker.text_content() == "Summit Bowl \u00b7 CFP semifinal"

    _hover_dot(guarded_page, 0)
    guarded_page.wait_for_selector(f'{icon}[data-kind="rivalry"]')
    assert marker.text_content() == "Lakeshore Rivalry"
    assert marker.get_attribute("role") is None
    assert marker.get_attribute("aria-label") is None
    assert guarded_page.locator(icon).count() == 1
    assert (
        guarded_page.locator(f'{icon}[data-kind="rivalry"]').get_attribute("aria-hidden") == "true"
    )
    text = guarded_page.inner_text("#chart-tooltip")
    for label in ("Noon", "Afternoon", "Prime time", "After dark"):
        assert label not in text

    _hover_dot(guarded_page, 1)
    guarded_page.wait_for_function(
        "document.querySelector('#chart-tooltip .tooltip-title')?.textContent.includes('Foxhollow')"
    )
    assert guarded_page.locator(icon).count() == 0
    assert guarded_page.locator("#chart-tooltip .tooltip-game-type").count() == 0


def _rgb_of(page: Page, selector: str, prop: str) -> tuple[float, float, float]:
    css: str = page.locator(selector).first.evaluate(f"el => getComputedStyle(el).{prop}")
    match = re.match(r"rgba?\((\d+), (\d+), (\d+)", css)
    assert match, css
    return (float(match[1]), float(match[2]), float(match[3]))


def _luminance(rgb: tuple[float, float, float]) -> float:
    def channel(c: float) -> float:
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(rgb[0]) + 0.7152 * channel(rgb[1]) + 0.0722 * channel(rgb[2])


def _ratio(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    hi, lo = sorted((_luminance(a) + 0.05, _luminance(b) + 0.05), reverse=True)
    return hi / lo


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_game_type_icons_have_own_colors_meeting_non_text_contrast(
    guarded_page: Page, open_app: Callable[[Page, str], None], scheme: str
) -> None:
    """WCAG 1.4.11: the trophy (playoff), bowl and rivalry icons carry their own
    colors, distinct from each other and from the text color, and each
    reaches 3:1 against both the tooltip and the detail-panel background in
    both themes."""
    guarded_page.emulate_media(color_scheme=scheme)  # type: ignore[arg-type]
    open_app(guarded_page, "")
    icon_colors: dict[str, tuple[float, float, float]] = {}

    for kind, index in (("bowl", 7), ("playoff", 5), ("rivalry", 0)):
        _hover_dot(guarded_page, index)
        guarded_page.wait_for_selector(f'#chart-tooltip svg.game-type-icon[data-kind="{kind}"]')
        icon = f'#chart-tooltip svg.game-type-icon[data-kind="{kind}"]'
        fg = _rgb_of(guarded_page, icon, "color")
        bg = _rgb_of(guarded_page, "#chart-tooltip", "backgroundColor")
        assert _ratio(fg, bg) >= 3, (scheme, kind, "tooltip")
        icon_colors[kind] = fg

        guarded_page.evaluate(f"window.__testHooks.openPanel({index})")
        panel_icon = f'#panel-body .panel-game-type svg.game-type-icon[data-kind="{kind}"]'
        assert _rgb_of(guarded_page, panel_icon, "color") == fg
        panel_bg = _rgb_of(guarded_page, "#detail-panel", "backgroundColor")
        assert _ratio(fg, panel_bg) >= 3, (scheme, kind, "panel")
        # The modal makes the page inert, so close it before the next hover.
        guarded_page.click("#panel-close")

    assert len(set(icon_colors.values())) == 3
    text = _rgb_of(guarded_page, "#chart-tooltip", "color")
    assert all(color != text for color in icon_colors.values())


@pytest.mark.parametrize(
    ("round_", "kinds", "name"),
    [
        ("first_round", ["playoff"], "CFP first round"),
        ("quarterfinal", ["bowl", "playoff"], "Summit Bowl \u00b7 CFP quarterfinal"),
        ("semifinal", ["bowl", "playoff"], "Summit Bowl \u00b7 CFP semifinal"),
        ("championship", ["playoff"], "CFP championship"),
        (None, ["playoff"], "College Football Playoff"),
    ],
)
def test_html_tooltip_cfp_game_at_a_bowl_shows_both_icons(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    serve_round: Callable[[Page, str | None], None],
    round_: str | None,
    kinds: list[str],
    name: str,
) -> None:
    """F3: a CFP quarterfinal or semifinal is played at a bowl, so its tooltip
    marker is the bowl icon then the trophy plus "<core> \u00b7 <round>"; first
    round, championship and an unrecorded round show the trophy and the round
    label. The icons are aria-hidden and the span has no role (D-10)."""
    serve_round(guarded_page, round_)
    open_app(guarded_page, "")
    _hover_dot(guarded_page, 5)
    icons = guarded_page.locator("#chart-tooltip .tooltip-game-type svg.game-type-icon")
    guarded_page.wait_for_selector("#chart-tooltip .tooltip-game-type svg.game-type-icon")
    assert icons.evaluate_all("els => els.map(e => e.dataset.kind)") == kinds
    assert icons.evaluate_all("els => els.map(e => e.getAttribute('aria-hidden'))") == [
        "true"
    ] * len(kinds)
    marker = guarded_page.locator("#chart-tooltip .tooltip-game-type")
    assert marker.get_attribute("role") is None
    assert marker.get_attribute("aria-label") is None
    assert marker.text_content() == name


def test_html_tooltip_named_game_sits_on_its_own_line_under_the_date(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """notes-2 #6: the date child holds only the date and kickoff; a named game
    (bowl, CFP, rivalry) is the next child, a block element; a regular game has
    none; the tooltip stays within its fixed max width."""
    open_app(guarded_page, "")
    probe = """
      () => {
        const kids = [...document.querySelector('#chart-tooltip').children];
        const date = kids[1];
        const next = kids[2];
        const marker = document.querySelector('#chart-tooltip .tooltip-game-type');
        return {
          dateText: date.textContent,
          nextIsMarker: next === marker,
          display: marker ? getComputedStyle(marker).display : null,
          leftEdge: marker
            ? marker.getBoundingClientRect().left - date.getBoundingClientRect().left : null,
          width: document.querySelector('#chart-tooltip').getBoundingClientRect().width,
        };
      }
    """
    for index in (7, 5, 0):
        _hover_dot(guarded_page, index)
        got = guarded_page.evaluate(probe)
        assert " \u00b7 " in got["dateText"]  # date and kickoff only, one separator
        assert got["dateText"].count(" \u00b7 ") == 1
        assert not any(w in got["dateText"] for w in ("Bowl", "Rivalry", "CFP"))
        assert got["nextIsMarker"] is True
        assert got["display"] == "block"
        assert abs(got["leftEdge"]) < 1
        assert got["width"] <= 320.5

    _hover_dot(guarded_page, 1)
    guarded_page.wait_for_function(
        "document.querySelector('#chart-tooltip .tooltip-title')?.textContent.includes('Foxhollow')"
    )
    assert guarded_page.evaluate(probe)["nextIsMarker"] is False


def test_html_tooltip_falls_back_to_text_when_an_icon_cannot_be_built(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """WR-01 / F3: if any icon in the marker can't be built (unknown kind),
    the tooltip shows the visible name with no icons instead of a partial
    marker."""
    open_app(guarded_page, "")
    result = guarded_page.evaluate(
        """
        async () => {
          const T = await import('./modules/tooltip.js');
          const el = document.createElement('div');
          const model = {
            title: 't', dateText: 'd',
            networks: [{ name: 'N', family: 'other' }], crew: [], crewLines: [],
            viewersLine: 'v', axisLine: 'a', hint: 'h',
            gameType: { icons: ['playoff', 'nope'], text: 'Summit Bowl \\u00b7 CFP semifinal' },
          };
          T.renderTooltipContent(el, model, 'light');
          const span = el.querySelector('.tooltip-game-type');
          return {
            text: span.textContent,
            svgs: span.querySelectorAll('svg').length,
            role: span.getAttribute('role'),
          };
        }
        """
    )
    assert result == {"text": "Summit Bowl \u00b7 CFP semifinal", "svgs": 0, "role": None}


def test_tooltip_model_adds_excitement_line_for_excitement_y(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-17: with y = Excitement on Spread x the axis line shows both plotted
    measures (the Date-line form); the viewers line and every other mode are
    unchanged."""
    open_app(guarded_page, "")
    result = guarded_page.evaluate(
        """async () => {
          const T = await import('./modules/tooltip.js');
          const F = await import('./modules/format.js');
          const d = window.__testHooks.data;
          const n = d.n;
          const find = (pred) => { for (let i = 0; i < n; i++) if (pred(i)) return i; return -1; };
          const both = find((i) => d.rated[i] && d.t.excitement[i] != null);
          const unrated = find((i) => !d.rated[i]);
          const nullExc = find((i) => d.t.excitement[i] == null);
          const m = (i, o) => T.tooltipModel(d, i, o);
          return {
            idx: [both, unrated, nullExc],
            spreadExc: m(both, { axis: 'spread', y: 'excitement' }).axisLine,
            dateForm: F.axisValueText(d, both, 'date'),
            nullLine: m(nullExc, { axis: 'spread', y: 'excitement' }).axisLine,
            nullTail: F.formatAxisValue('excitement', d.t.excitement[nullExc]),
            dateExc: m(both, { axis: 'date', y: 'excitement' }).axisLine,
            dateOnly: m(both, { axis: 'date' }).axisLine,
            spreadOnly: m(both, { axis: 'spread' }).axisLine,
            spreadViewers: m(both, { axis: 'spread', y: 'viewers' }).axisLine,
            vRated: [
              m(both, { axis: 'spread' }).viewersLine,
              m(both, { axis: 'spread', y: 'excitement' }).viewersLine,
            ],
            vUnrated: [
              m(unrated, { axis: 'spread' }).viewersLine,
              m(unrated, { axis: 'spread', y: 'excitement' }).viewersLine,
            ],
          };
        }"""
    )
    assert min(result["idx"]) >= 0
    assert result["spreadExc"] == result["dateForm"]
    assert result["nullLine"].endswith(result["nullTail"])
    assert result["dateExc"] == result["dateOnly"]
    assert result["spreadOnly"] == result["spreadViewers"]
    assert result["spreadOnly"] != result["spreadExc"]
    assert result["vRated"][0] == result["vRated"][1]
    assert result["vRated"][0].startswith("Viewers: ")
    assert result["vUnrated"][0] == result["vUnrated"][1]
    assert result["vUnrated"][0].startswith("No public rating")


def test_plotly_fallback_tooltip_shows_game_type_text_without_slot_label(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """A1/D-10: the plotly-hovertemplate fallback shows the same named text (no
    slot label) -- text only, it cannot draw an icon."""
    open_app(guarded_page, "")
    _use_plotly_tooltip(guarded_page)
    traces = _traces(guarded_page)

    assert "Noon" not in _hover_text(traces, 0)
    assert "Lakeshore Rivalry" in _hover_text(traces, 0)
    assert "Summit Bowl \u00b7 CFP semifinal" in _hover_text(traces, 5)
    assert "Harbor Bowl" in _hover_text(traces, 7)
    # notes-2 #6: the named game is its own <br> line, not on the date line.
    lines = _hover_text(traces, 7).split("<br>")
    assert "Harbor Bowl" not in lines[1]
    assert lines[2] == "Harbor Bowl"


def test_html_tooltip_hides_on_mouse_out_scroll_and_panel_open(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-22: the tooltip closes on mouse-out, page scroll, and when the
    detail panel opens."""
    open_app(guarded_page, "")

    _hover_dot(guarded_page, 0)
    guarded_page.mouse.move(5, 5)
    guarded_page.wait_for_selector("#chart-tooltip[hidden]", state="attached")

    _hover_dot(guarded_page, 0)
    guarded_page.evaluate("window.scrollBy(0, 40)")
    guarded_page.wait_for_selector("#chart-tooltip[hidden]", state="attached")

    # Click the position measured after the scroll, not the pre-scroll pixel.
    point = _hover_dot(guarded_page, 0)
    guarded_page.mouse.click(point["x"], point["y"])
    guarded_page.wait_for_function("document.getElementById('detail-panel').open")
    assert guarded_page.is_hidden("#chart-tooltip")


def test_html_tooltip_stays_inside_the_viewport(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-22: at an 800x900 viewport, hovering the right-most dot keeps the
    tooltip fully on-screen -- clamped at least 8px from the right edge."""
    guarded_page.set_viewport_size({"width": 800, "height": 900})
    open_app(guarded_page, "")

    points = _dot_x_by_customdata(_traces(guarded_page))
    rightmost = max(points, key=lambda cd: points[cd])
    _hover_dot(guarded_page, rightmost)

    box = guarded_page.locator("#chart-tooltip").bounding_box()
    assert box is not None
    assert box["x"] >= 8
    assert box["x"] + box["width"] <= 800 - 8


def test_html_tooltip_never_shows_for_inert_or_person_faded_dots(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-15 (carried forward): a filtered-out dot never shows the tooltip,
    and neither does a person-faded (50%-opacity) active dot -- only the
    highlighted dot does."""
    open_app(guarded_page, "?slot=late")
    inert_point = _inert_dot_point(guarded_page, "inert:fox", 0)
    guarded_page.mouse.move(inert_point["x"], inert_point["y"])
    guarded_page.wait_for_timeout(300)
    assert guarded_page.is_hidden("#chart-tooltip")

    open_app(guarded_page, "?people=dale-harlow")
    # Dot 1 passes the filters but isn't one of Dale Harlow's two highlighted
    # games (0, 8), so it's a 50%-faded active dot, not highlighted.
    point1 = _dot_point(guarded_page, 1)
    guarded_page.mouse.move(point1["x"], point1["y"])
    guarded_page.wait_for_timeout(300)
    assert guarded_page.is_hidden("#chart-tooltip")

    _hover_dot(guarded_page, 0)


def test_html_tooltip_resists_injection_from_mutated_team_and_network_names(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    fixture_raw: dict[str, Any],
) -> None:
    """T-04.1-25: a malicious team name and a malicious network name both
    render as literal text inside the custom tooltip, `#chart-tooltip`
    never gains a real `<img>` element, and the payload's `onerror`/`alert`
    never fires."""
    dialogs: list[str] = []

    def _record_dialog(dialog: object) -> None:
        dialogs.append(dialog.message)  # type: ignore[attr-defined]
        dialog.dismiss()  # type: ignore[attr-defined]

    guarded_page.on("dialog", _record_dialog)

    payload = "<img src=x onerror=alert(1)>"
    mutated = json.loads(json.dumps(fixture_raw))
    mutated["lookups"]["teams"][0]["name"] = payload
    mutated["lookups"]["networks"][0]["name"] = payload
    body = json.dumps(mutated)

    guarded_page.route(
        "**/site-data.json*",
        lambda route: route.fulfill(status=200, content_type="application/json", body=body),
    )
    open_app(guarded_page, "")

    _hover_dot(guarded_page, 0)

    text = guarded_page.inner_text("#chart-tooltip")
    # The team name (title line) keeps the full payload. The network name
    # goes through `stripNetworkNote` first (tooltip-only formatting that
    # drops a trailing "(...)" methodology aside) -- unrelated to injection
    # safety, it just means the payload's own "(1)" is stripped from that
    # one occurrence too, same as any other parenthetical would be.
    assert payload in text
    assert "<img src=x onerror=alert>" in text
    assert guarded_page.locator("#chart-tooltip img").count() == 0
    assert dialogs == []


def test_html_tooltip_long_bowl_name_wraps_inside_max_width(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    fixture_raw: dict[str, Any],
) -> None:
    """D-10: a long game name wraps inside the tooltip's 320px max-width; the
    tooltip never grows past it and never overflows horizontally."""
    raw = json.loads(json.dumps(fixture_raw))
    raw["lookups"]["bowls"][1]["core"] = "Cotton Bowl Classic"
    raw["lookups"]["bowls"][1]["name"] = "Goodyear Cotton Bowl Classic"
    guarded_page.route("**/site-data.json*", lambda route: route.fulfill(json=raw))
    open_app(guarded_page, "")

    _hover_dot(guarded_page, 5)

    assert (
        guarded_page.locator("#chart-tooltip .tooltip-game-type").text_content()
        == "Cotton Bowl Classic \u00b7 CFP semifinal"
    )
    metrics = guarded_page.locator("#chart-tooltip").evaluate(
        """el => {
          const s = getComputedStyle(el);
          const extra = parseFloat(s.paddingLeft) + parseFloat(s.paddingRight)
            + parseFloat(s.borderLeftWidth) + parseFloat(s.borderRightWidth);
          return { width: el.offsetWidth, bound: parseFloat(s.maxWidth) + extra,
                   scroll: el.scrollWidth, client: el.clientWidth };
        }"""
    )
    assert metrics["width"] <= metrics["bound"]
    assert metrics["scroll"] <= metrics["client"]


def test_html_tooltip_resists_injection_from_a_hostile_rivalry_name(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    fixture_raw: dict[str, Any],
) -> None:
    """T-04.10-01: a hostile rivalry name renders as literal text in the
    tooltip; no element is injected and no dialog fires."""
    dialogs: list[str] = []

    def _record_dialog(dialog: object) -> None:
        dialogs.append(dialog.message)  # type: ignore[attr-defined]
        dialog.dismiss()  # type: ignore[attr-defined]

    guarded_page.on("dialog", _record_dialog)
    payload = "<img src=x onerror=alert(1)>"
    raw = json.loads(json.dumps(fixture_raw))
    raw["lookups"]["rivalries"][1]["name"] = payload
    guarded_page.route("**/site-data.json*", lambda route: route.fulfill(json=raw))
    open_app(guarded_page, "")

    _hover_dot(guarded_page, 0)

    assert guarded_page.locator("#chart-tooltip .tooltip-game-type").text_content() == payload
    assert guarded_page.locator("#chart-tooltip img").count() == 0
    assert dialogs == []


def test_mobile_tap_opens_panel_without_a_hover_tooltip(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-22: a touch device (`hover: none`) never gets the hover tooltip --
    tapping a dot opens the detail panel directly."""
    open_app(mobile_page, "")
    point = _dot_point(mobile_page, 0)
    mobile_page.touchscreen.tap(point["x"], point["y"])
    mobile_page.wait_for_function("document.getElementById('detail-panel').open")
    assert mobile_page.is_hidden("#chart-tooltip")


def test_tooltip_mode_trace_config(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-22: the default html mode's active (family) traces and the
    highlight trace carry `hoverinfo: 'none'` (or `'skip'` once a person is
    selected, D-15) and a falsy `hovertemplate`; switching to the plotly
    fallback restores `hovertemplate: '%{text}<extra></extra>'` with a
    `text` array matching `customdata`'s length. Inert traces stay
    `hoverinfo: 'skip'` with a falsy `hovertemplate` in both modes."""
    open_app(guarded_page, "")
    full_js = (
        "() => document.getElementById('chart')._fullData.map(t => "
        "({meta: t.meta, hoverinfo: t.hoverinfo, hovertemplate: t.hovertemplate, "
        "text: t.text, customdata: t.customdata}))"
    )

    html_full = guarded_page.evaluate(full_js)
    for t in html_full:
        if str(t["meta"]).startswith(("inert:", "unrated-inert:", "highlight-halo")):
            assert t["hoverinfo"] == "skip"
            assert not t["hovertemplate"]
        else:
            assert t["hoverinfo"] == "none"
            assert not t["hovertemplate"]

    _use_plotly_tooltip(guarded_page)

    # No selection: every family trace is non-empty (12 dots across 4
    # families) and carries the exact fallback hovertemplate/text. The
    # highlight trace has zero points here (nobody's highlighted) -- the
    # vendored Plotly build resets an empty trace's own hovertemplate on
    # `_fullData` regardless of what was requested, so its string equality
    # is checked below instead, once a selection makes it non-empty.
    plotly_full = guarded_page.evaluate(full_js)
    for t in plotly_full:
        meta = str(t["meta"])
        if meta.startswith(("inert:", "unrated-inert:", "highlight-halo")):
            assert t["hoverinfo"] == "skip"
            assert not t["hovertemplate"]
        elif meta.startswith(("family:", "unrated-active:")):
            # an empty trace (unrated-active:other) has its template reset by Plotly
            if t["customdata"]:
                assert t["hovertemplate"] == "%{text}<extra></extra>"
                assert len(t["text"]) == len(t["customdata"])

    # A person selection fades every family trace to 'skip' (D-15) and
    # fills the highlight trace, which now carries the fallback template.
    guarded_page.evaluate("window.__testHooks.setState({people: ['dale-harlow']})")
    plotly_full_selected = guarded_page.evaluate(full_js)
    for t in plotly_full_selected:
        meta = str(t["meta"])
        if meta.startswith(("inert:", "family:", "unrated-inert:", "unrated-active:")):
            assert t["hoverinfo"] == "skip"
            assert not t["hovertemplate"]
        elif meta.startswith("highlight-halo"):
            assert t["hoverinfo"] == "skip"  # halos are never hoverable
        else:
            assert meta in ("highlight", "highlight-unrated")
            if t["customdata"] and len(t["customdata"]) > 0:
                assert t["hovertemplate"] == "%{text}<extra></extra>"
                assert len(t["text"]) == len(t["customdata"])


# D-31: mirrors `site/modules/palette.js`'s ACCENT/PAGE_BG tokens -- a pure
# JS module can't be imported from a Python test, so these are the same hex
# literals, kept in sync by `test_compare_highlight_trace_config` and
# `test_compare_shapes_have_no_edge_speckles` both exercising the real
# built page (never a hand-rendered swatch).
_ACCENT = {"light": "#111827", "dark": "#E5E7EB"}
_PAGE_BG = {"light": "#FFFFFF", "dark": "#14161A"}

# The fixture compare selection that assigns every COMPARE_SYMBOLS shape
# plus the shared-game star (04.1-CONTEXT.md interfaces, confirmed against
# `window.__testHooks.getView().symbols` rather than assumed): kris-venn,
# sam-delgado, dale-harlow, casey-lund, in that selection order.
_COMPARE_ALL_SHAPES_QUERY = "?people=kris-venn,sam-delgado,dale-harlow,casey-lund&mode=compare"

# Reads every point on the highlight trace (`data.at(-1)`, `meta:
# 'highlight'`) -- its raw x (to detect the D-03 n/a-strip sentinel), its
# per-point symbol/size, and its page pixel via the same d2p conversion
# `_DOT_PIXEL_JS` uses.
_HIGHLIGHT_POINTS_JS = """
() => {
  const gd = document.getElementById('chart');
  const layout = gd._fullLayout;
  const rect = gd.getBoundingClientRect();
  const trace = gd.data.at(-1);
  const sentinel = gd.layout.annotations[0].x;
  const out = [];
  for (let i = 0; i < trace.x.length; i += 1) {
    const symbol = Array.isArray(trace.marker.symbol)
      ? trace.marker.symbol[i] : trace.marker.symbol;
    const size = Array.isArray(trace.marker.size) ? trace.marker.size[i] : trace.marker.size;
    out.push({
      customdata: trace.customdata[i],
      naSentinel: trace.x[i] === sentinel,
      symbol,
      size,
      px: rect.left + layout._size.l + layout.xaxis.d2p(trace.x[i]),
      py: rect.top + layout._size.t + layout.yaxis.d2p(trace.y[i]),
    });
  }
  return out;
}
"""

# Decodes a base64 PNG data URL (a `page.screenshot(clip=...)` capture)
# through an in-page `Image`/canvas (CSP allows `img-src data: blob:`, so no
# Pillow dependency is needed) and counts accent-like pixels in the ring from
# `innerR` to `outerR` px from the image center. A pixel counts when it is at
# least 60 (RGB distance) away from the theme's page background and either
# within 60 of the theme's accent color or closer to the accent than half its
# distance to the background (an anti-aliased accent edge blended toward the
# page). Pixels within `other.half + 3` px of another highlighted point's own
# center (translated into this crop's local coordinates) are excluded, so a
# marker close enough to sit inside this 40x40 crop never contaminates the
# count.
#
# The predicate is color-only, so it cannot tell the accent from any other
# dark-on-light (or light-on-dark) ink: the light theme's `conference` family
# fill `#000000` sits 49 from ACCENT `#111827`, and `--muted` text (light
# `#4B5563`, dark `#9CA3AF`) passes the half-distance clause in both themes.
# A bare count is therefore not proof of a halo; the halo-border test compares
# each marker's count against the same crop with the halo trace hidden.
_RING_SPECKLE_JS = """
([dataUrl, accentHex, bgHex, innerR, outerR, others]) => new Promise((resolve) => {
  const hexToRgb = (h) => [
    parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16),
  ];
  const accent = hexToRgb(accentHex);
  const bg = hexToRgb(bgHex);
  const img = new Image();
  img.onload = () => {
    const canvas = document.createElement('canvas');
    canvas.width = img.width;
    canvas.height = img.height;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(img, 0, 0);
    const data = ctx.getImageData(0, 0, img.width, img.height).data;
    const cx = img.width / 2;
    const cy = img.height / 2;
    let count = 0;
    for (let py = 0; py < img.height; py += 1) {
      for (let px = 0; px < img.width; px += 1) {
        const dist = Math.hypot(px - cx, py - cy);
        if (dist < innerR || dist > outerR) continue;
        let skip = false;
        for (const o of others) {
          if (Math.hypot(px - o.x, py - o.y) < o.half + 3) { skip = true; break; }
        }
        if (skip) continue;
        const idx = (py * img.width + px) * 4;
        const dAccent = Math.hypot(data[idx] - accent[0], data[idx + 1] - accent[1],
          data[idx + 2] - accent[2]);
        const dBg = Math.hypot(data[idx] - bg[0], data[idx + 1] - bg[1], data[idx + 2] - bg[2]);
        // Anti-aliased halo edge pixels blend toward the page background (a spiky
        // star's tips land on fractional pixels); count a pixel that is more than
        // two-thirds accent as well as one that is nearly pure accent.
        if ((dAccent < 60 || dAccent < dBg * 0.5) && dBg >= 60) count += 1;
      }
    }
    resolve(count);
  };
  img.src = dataUrl;
})
"""


def _speckle_count(
    page: Page,
    center_px: float,
    center_py: float,
    theme: str,
    ring_inner_radius: float,
    other_points: list[dict[str, Any]],
) -> int:
    """Screenshots a 40x40 box centered on one highlight marker and returns
    the ring-speckle pixel count from `ring_inner_radius` px from center out
    to the crop's own edge (D-31/D-33: the caller is responsible for
    placing `ring_inner_radius` outside the halo's own visible shape, not
    just outside a naive circular half-size -- see `_halo_ring_inner_radius`
    below)."""
    clip_x = center_px - 20
    clip_y = center_py - 20
    shot = page.screenshot(clip={"x": clip_x, "y": clip_y, "width": 40, "height": 40})
    data_url = "data:image/png;base64," + base64.b64encode(shot).decode("ascii")
    others = [
        {"x": other["px"] - clip_x, "y": other["py"] - clip_y, "half": other["size"] / 2}
        for other in other_points
    ]
    count = page.evaluate(
        _RING_SPECKLE_JS,
        [data_url, _ACCENT[theme], _PAGE_BG[theme], ring_inner_radius, 20, others],
    )
    return int(count)


def _halo_ring_inner_radius(size: float) -> float:
    """The D-31 speckle ring's inner radius for a non-circle highlight point
    of highlight `size` (D-33): must clear the halo's own visible shape
    (`(size + 3) / 2` half-size), not just a naive circular boundary at
    that half-size. Square and diamond halos are drawn with their
    bounding-box side equal to the marker `size` value (confirmed
    empirically against this real build), so a square's own corner sits
    `sqrt(2)` times its half-side from center -- about 41% farther out than
    the half-size alone. Multiplying by `sqrt(2)` plus a 2px anti-aliasing
    allowance keeps the ring outside every shape's own corner (empirically
    confirmed against every non-circle shape in `_COMPARE_ALL_SHAPES_QUERY`,
    both themes: the farthest accent-colored pixel measured for any shape
    was 10.63px from center against a computed boundary of 12.61-14.73px)
    without needing a per-symbol lookup table."""
    halo_half = (size + 3) / 2
    return halo_half * math.sqrt(2) + 2


def _boxes_overlap(a: dict[str, Any], b: dict[str, Any], pad: float = 4) -> bool:
    """Whether two highlight markers' own boxes (size, padded by `pad` on
    each side) overlap -- a point this close to another is skipped entirely
    rather than tested, since its own 40x40 crop would be contaminated no
    matter how the ring-pixel exclusion above is tuned."""
    half_a = a["size"] / 2 + pad
    half_b = b["size"] / 2 + pad
    return abs(a["px"] - b["px"]) < half_a + half_b and abs(a["py"] - b["py"]) < half_a + half_b


@pytest.mark.parametrize("color_scheme", ["light", "dark"])
def test_compare_shapes_have_no_edge_speckles(
    guarded_page: Page, open_app: Callable[[Page, str], None], color_scheme: str
) -> None:
    """D-31: in compare mode, every non-circle highlight marker (square,
    diamond, triangle-up, star) renders with no accent-colored speckle
    pixels in the ring just outside its own edge, in both themes.

    Diagnosed empirically against this real headless build before writing
    the assertion (04.1-13-SUMMARY.md): headless Chromium (SwiftShader)
    does reproduce a small version of the artifact -- 1 ring-speckle pixel
    on each of the fixture's two diamond markers (2 total), zero on the
    square/triangle-up/star markers, with the pre-fix 1.5px accent
    `marker.line` border; 0 total with the border removed. Confirms the
    UAT's suspected cause (04.1-CONTEXT.md interfaces) rather than assuming
    it.

    D-33 brought a solid accent halo back around these same markers, so the
    ring measured here now starts outside the halo's own outer edge
    (`(size + 3) / 2 + 3`), not the bare highlight glyph's edge -- the
    halo's own expected solid ring must never be mistaken for a speckle.
    """
    guarded_page.set_viewport_size({"width": 1280, "height": 800})
    guarded_page.emulate_media(color_scheme=color_scheme)
    open_app(guarded_page, _COMPARE_ALL_SHAPES_QUERY)
    guarded_page.locator("#chart").scroll_into_view_if_needed()
    points = guarded_page.evaluate(_HIGHLIGHT_POINTS_JS)
    # Move the mouse off the chart first so no tooltip/hover label is
    # showing in any of the screenshots below.
    guarded_page.mouse.move(5, 5)
    guarded_page.wait_for_timeout(100)

    total = 0
    tested = 0
    for point in points:
        if point["symbol"] == "circle" or point["naSentinel"]:
            continue
        others = [p for p in points if p["customdata"] != point["customdata"]]
        if any(_boxes_overlap(point, other) for other in others):
            continue
        tested += 1
        total += _speckle_count(
            guarded_page,
            point["px"],
            point["py"],
            color_scheme,
            _halo_ring_inner_radius(point["size"]),
            others,
        )

    assert tested > 0, "no non-circle highlight marker was testable in this fixture selection"
    assert total == 0, f"{total} speckle pixel(s) found around compare-mode highlight markers"


# Sets the D-33 halo trace's (`gd.data.at(-2)`, `meta: 'highlight-halo'`)
# marker opacity, leaving every other trace and the layout untouched, so the
# halo-border test can measure the same crops with and without the halo.
# Resolves false when the halo trace is not where D-33 puts it.
_SET_HALO_OPACITY_JS = """
(opacity) => {
  const gd = document.getElementById('chart');
  const index = gd.data.length - 2;
  if (index < 0 || gd.data[index].meta !== 'highlight-halo') return false;
  return window.Plotly.restyle(gd, { 'marker.opacity': opacity }, [index]).then(() => true);
}
"""

# The fewest band pixels the halo must add around each non-circle marker.
# Measured on the fixture compare selection, the halo adds 5-38 per marker
# (the light-theme star: 15 with the halo, 2 without); a star halo shrunk to
# the star's own size adds only 1, which a bare `> 0` difference would pass.
_MIN_HALO_BORDER_PIXELS = 3


def _border_pixel_count(
    page: Page,
    center_px: float,
    center_py: float,
    theme: str,
    marker_half: float,
    halo_half: float,
    other_points: list[dict[str, Any]],
) -> int:
    """Screenshots a 40x40 box centered on one highlight marker and counts
    accent-like pixels in the band between the highlight glyph's own
    half-size and the halo's half-size (D-33) -- the halo's own visible
    border, reusing the same in-page pixel decode `_RING_SPECKLE_JS` uses
    for the D-31 speckle count, just with the band's inner/outer radii
    swapped to the border's own expected location instead of just past
    it. The count also picks up a near-accent marker fill (see the
    `_RING_SPECKLE_JS` comment), so callers compare it against the count
    with the halo hidden rather than reading it alone."""
    clip_x = center_px - 20
    clip_y = center_py - 20
    shot = page.screenshot(clip={"x": clip_x, "y": clip_y, "width": 40, "height": 40})
    data_url = "data:image/png;base64," + base64.b64encode(shot).decode("ascii")
    others = [
        {"x": other["px"] - clip_x, "y": other["py"] - clip_y, "half": other["size"] / 2}
        for other in other_points
    ]
    count = page.evaluate(
        _RING_SPECKLE_JS,
        [data_url, _ACCENT[theme], _PAGE_BG[theme], marker_half, halo_half, others],
    )
    return int(count)


@pytest.mark.parametrize("color_scheme", ["light", "dark"])
def test_compare_shapes_have_accent_halo_border(
    guarded_page: Page, open_app: Callable[[Page, str], None], color_scheme: str
) -> None:
    """D-33: in compare mode, every non-circle highlight marker (square,
    diamond, triangle-up, star) shows a solid ACCENT-colored halo border --
    the same border the circle highlight markers already carry via
    `marker.line` -- in the band between the marker's own edge and the
    halo's outer edge, in both themes. Restored as a separate halo trace
    (D-33) so it never reintroduces the D-31 SDF-glyph speckle fringe a
    `marker.line` border on these symbols caused."""
    guarded_page.set_viewport_size({"width": 1280, "height": 800})
    guarded_page.emulate_media(color_scheme=color_scheme)
    open_app(guarded_page, _COMPARE_ALL_SHAPES_QUERY)
    # This is a pixel-fidelity check on the glyph edges; the stable scrollbar
    # gutter (SITE-28) shifts the chart by a half pixel, which this
    # band-counting decode is sensitive to, so it is switched off here.
    guarded_page.evaluate(
        "() => { document.documentElement.style.scrollbarGutter = 'auto'; "
        "window.dispatchEvent(new Event('resize')); }"
    )
    guarded_page.wait_for_timeout(500)
    guarded_page.locator("#chart").scroll_into_view_if_needed()
    points = guarded_page.evaluate(_HIGHLIGHT_POINTS_JS)
    guarded_page.mouse.move(5, 5)
    guarded_page.wait_for_timeout(100)

    def band_counts() -> dict[Any, int]:
        counts: dict[Any, int] = {}
        for point in points:
            if point["symbol"] == "circle" or point["naSentinel"]:
                continue
            others = [p for p in points if p["customdata"] != point["customdata"]]
            if any(_boxes_overlap(point, other) for other in others):
                continue
            counts[point["customdata"]] = _border_pixel_count(
                guarded_page,
                point["px"],
                point["py"],
                color_scheme,
                point["size"] / 2,
                (point["size"] + 3) / 2,
                others,
            )
        return counts

    with_halo = band_counts()
    assert with_halo, "no non-circle highlight marker was testable in this fixture selection"

    # A near-accent marker fill (the light theme's black `conference` star)
    # counts in the band with or without a halo, so each marker's count is
    # compared against the same crop with the halo trace hidden: the
    # difference is the halo's own border.
    assert guarded_page.evaluate(_SET_HALO_OPACITY_JS, 0), "halo trace not found at data.at(-2)"
    guarded_page.wait_for_timeout(300)
    without_halo = band_counts()

    for customdata, count in with_halo.items():
        added = count - without_halo[customdata]
        assert added >= _MIN_HALO_BORDER_PIXELS, (
            f"halo adds only {added} ACCENT border pixel(s) around customdata {customdata} "
            f"({count} with the halo, {without_halo[customdata]} without)"
        )


def test_compare_highlight_trace_config(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-31: the highlight trace (`data.at(-1)`, `meta: 'highlight'`) never
    sets a `marker.line` width above 0 on a non-circle compare-mode point --
    `marker.line.width` is either an array (0 at every non-circle index) or
    a scalar 0 -- and every non-circle highlight marker is at least 12px so
    it still reads as highlighted without the border."""
    open_app(guarded_page, _COMPARE_ALL_SHAPES_QUERY)
    trace = guarded_page.evaluate(
        "() => { const t = document.getElementById('chart').data.at(-1); "
        "return { meta: t.meta, symbol: t.marker.symbol, size: t.marker.size, "
        "lineWidth: t.marker.line.width }; }"
    )
    assert trace["meta"] == "highlight"
    symbols = trace["symbol"]
    sizes = trace["size"]
    line_width = trace["lineWidth"]
    assert isinstance(symbols, list) and len(symbols) > 0
    assert any(symbol != "circle" for symbol in symbols), (
        "fixture selection has no non-circle compare shape to check"
    )

    for i, symbol in enumerate(symbols):
        if symbol == "circle":
            continue
        width = line_width[i] if isinstance(line_width, list) else line_width
        assert width == 0, f"non-circle point {i} ({symbol}) has marker.line.width {width}"
        assert sizes[i] >= 12, f"non-circle point {i} ({symbol}) has size {sizes[i]} < 12"


def test_compare_halo_trace_config(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-33: with at least one non-circle highlight point, a halo trace
    (`meta: 'highlight-halo'`) sits at `gd.data.at(-2)`, immediately before
    the `highlight` trace at `gd.data.at(-1)`. It carries exactly the
    non-circle highlight points, with the same x/y and symbol, a solid
    ACCENT[theme] fill, each point's own highlight size + 3, `line.width`
    0, `opacity` 1, and is inert to hover/click (`hoverinfo: 'skip'`,
    `hovertemplate: null`). The highlight trace itself is unchanged: still
    `line.width` 0 on every non-circle point and >= 12px."""
    guarded_page.emulate_media(color_scheme="light")
    open_app(guarded_page, _COMPARE_ALL_SHAPES_QUERY)
    result = guarded_page.evaluate(
        "() => { const gd = document.getElementById('chart'); "
        "const highlight = gd.data.at(-1); "
        "const halo = gd.data.at(-2); "
        "return { highlightMeta: highlight.meta, haloMeta: halo.meta, "
        "haloX: halo.x, haloY: halo.y, haloSymbol: halo.marker.symbol, "
        "haloSize: halo.marker.size, haloColor: halo.marker.color, "
        "haloLineWidth: halo.marker.line.width, haloOpacity: halo.marker.opacity, "
        "haloHoverinfo: halo.hoverinfo, haloHovertemplate: halo.hovertemplate, "
        "haloShowlegend: halo.showlegend, "
        "highlightX: highlight.x, highlightY: highlight.y, "
        "highlightSymbol: highlight.marker.symbol, "
        "highlightSize: highlight.marker.size, "
        "highlightLineWidth: highlight.marker.line.width }; }"
    )

    assert result["highlightMeta"] == "highlight"
    assert result["haloMeta"] == "highlight-halo"
    assert result["haloShowlegend"] is False
    assert result["haloHoverinfo"] == "skip"
    assert not result["haloHovertemplate"]
    assert result["haloOpacity"] == 1

    # The halo's points are exactly the non-circle highlight points, same
    # x/y and symbol, in the same order.
    non_circle_idx = [i for i, s in enumerate(result["highlightSymbol"]) if s != "circle"]
    assert len(non_circle_idx) > 0, "fixture selection has no non-circle compare shape to check"
    assert len(result["haloX"]) == len(non_circle_idx)
    for halo_i, hi in enumerate(non_circle_idx):
        assert result["haloX"][halo_i] == result["highlightX"][hi]
        assert result["haloY"][halo_i] == result["highlightY"][hi]
        assert result["haloSymbol"][halo_i] == result["highlightSymbol"][hi]

        halo_size = (
            result["haloSize"][halo_i]
            if isinstance(result["haloSize"], list)
            else result["haloSize"]
        )
        highlight_size = (
            result["highlightSize"][hi]
            if isinstance(result["highlightSize"], list)
            else result["highlightSize"]
        )
        assert halo_size == highlight_size + 3

        halo_line_width = (
            result["haloLineWidth"][halo_i]
            if isinstance(result["haloLineWidth"], list)
            else result["haloLineWidth"]
        )
        assert halo_line_width == 0

    halo_color = result["haloColor"]
    halo_colors = halo_color if isinstance(halo_color, list) else [halo_color] * len(non_circle_idx)
    assert all(c == _ACCENT["light"] for c in halo_colors)

    # The highlight trace itself is unchanged by the halo's addition: still
    # line.width 0 and size >= 12 on every non-circle point.
    for hi in non_circle_idx:
        hl_width = (
            result["highlightLineWidth"][hi]
            if isinstance(result["highlightLineWidth"], list)
            else result["highlightLineWidth"]
        )
        assert hl_width == 0
        hl_size = (
            result["highlightSize"][hi]
            if isinstance(result["highlightSize"], list)
            else result["highlightSize"]
        )
        assert hl_size >= 12


def test_no_halo_trace_with_no_selection(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-33: with no non-circle highlight points (nobody selected here), the
    halo trace either doesn't exist or has zero points -- either way,
    `data.at(-1)` is still the `highlight` trace, unchanged from before this
    plan."""
    open_app(guarded_page, "")
    result = guarded_page.evaluate(
        "() => { const gd = document.getElementById('chart'); "
        "const highlight = gd.data.at(-1); "
        "const halo = gd.data.find(t => t.meta === 'highlight-halo'); "
        "return { highlightMeta: highlight.meta, highlightX: highlight.x, "
        "haloXLength: halo ? halo.x.length : 0 }; }"
    )
    assert result["highlightMeta"] == "highlight"
    assert result["highlightX"] == []
    assert result["haloXLength"] == 0


# ---------- D-29: space-separated tooltip pills, family-colored border ----------

# `FAMILY_COLORS[theme]` for the three families exercised below (palette.js
# literal hex, as `rgb(...)` -- disney/fox are shared between themes; only
# `other` differs light `#8F8F8F` vs dark `#999999`).
_BORDER_COLOR = {
    "light": {
        "disney": "rgb(0, 114, 178)",
        "fox": "rgb(0, 158, 115)",
        "other": "rgb(143, 143, 143)",
    },
    "dark": {
        "disney": "rgb(0, 114, 178)",
        "fox": "rgb(0, 158, 115)",
        "other": "rgb(153, 153, 153)",
    },
}


def test_html_tooltip_pills_are_space_separated(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-29: the tooltip's network pills are visually separated only by the
    flex row's own gap -- no `.tooltip-sep` element, and no literal "/" in
    the row's text."""
    open_app(guarded_page, "")
    _hover_dot(guarded_page, 4)

    assert guarded_page.locator("#chart-tooltip .tooltip-sep").count() == 0
    networks_text = guarded_page.inner_text("#chart-tooltip .tooltip-networks")
    assert "/" not in networks_text

    pills = guarded_page.locator("#chart-tooltip .tooltip-networks .pill")
    expect(pills).to_have_count(2)
    box0 = pills.nth(0).bounding_box()
    box1 = pills.nth(1).bounding_box()
    assert box0 is not None
    assert box1 is not None
    gap = box1["x"] - (box0["x"] + box0["width"])
    assert 4 <= gap <= 12, gap


@pytest.mark.parametrize("color_scheme", ["light", "dark"])
def test_html_tooltip_border_is_primary_family_color(
    guarded_page: Page, open_app: Callable[[Page, str], None], color_scheme: str
) -> None:
    """D-29: the tooltip's ~2px border is the primary network's own family
    color, in both themes and whether or not a person is selected."""
    guarded_page.emulate_media(color_scheme=color_scheme)
    open_app(guarded_page, "")

    _hover_dot(guarded_page, 0)
    styles = guarded_page.eval_on_selector(
        "#chart-tooltip",
        "el => { const s = getComputedStyle(el); return [s.borderTopWidth, s.borderTopColor]; }",
    )
    assert styles[0] == "2px"
    assert styles[1] == _BORDER_COLOR[color_scheme]["disney"]

    _hover_dot(guarded_page, 1)
    styles = guarded_page.eval_on_selector(
        "#chart-tooltip", "el => getComputedStyle(el).borderTopColor"
    )
    assert styles == _BORDER_COLOR[color_scheme]["fox"]

    _hover_dot(guarded_page, 7)
    styles = guarded_page.eval_on_selector(
        "#chart-tooltip", "el => getComputedStyle(el).borderTopColor"
    )
    assert styles == _BORDER_COLOR[color_scheme]["other"]

    open_app(guarded_page, "?people=dale-harlow")
    _hover_dot(guarded_page, 0)
    styles = guarded_page.eval_on_selector(
        "#chart-tooltip", "el => getComputedStyle(el).borderTopColor"
    )
    assert styles == _BORDER_COLOR[color_scheme]["disney"]


def test_plotly_tooltip_border_is_primary_family_color(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-29: the plotly-fallback hover label's own border stroke matches the
    primary network's family color too, with or without a highlight."""
    open_app(guarded_page, "")
    _use_plotly_tooltip(guarded_page)

    point = _dot_point(guarded_page, 0)
    guarded_page.mouse.move(point["x"], point["y"])
    guarded_page.wait_for_selector(".hoverlayer .hovertext path")
    stroke = guarded_page.eval_on_selector(
        ".hoverlayer .hovertext path", "el => getComputedStyle(el).stroke"
    )
    assert stroke == _BORDER_COLOR["light"]["disney"]

    open_app(guarded_page, "?people=dale-harlow")
    _use_plotly_tooltip(guarded_page)
    point = _dot_point(guarded_page, 0)
    guarded_page.mouse.move(point["x"], point["y"])
    guarded_page.wait_for_selector(".hoverlayer .hovertext path")
    stroke = guarded_page.eval_on_selector(
        ".hoverlayer .hovertext path", "el => getComputedStyle(el).stroke"
    )
    assert stroke == _BORDER_COLOR["light"]["disney"]


def _token_rgb(page: Page, name: str) -> tuple[float, float, float]:
    css: str = page.evaluate(
        "(n) => { const s = document.createElement('span'); s.style.color = `var(${n})`;"
        "document.body.append(s); const c = getComputedStyle(s).color; s.remove(); return c; }",
        name,
    )
    match = re.match(r"rgba?\((\d+), (\d+), (\d+)", css)
    assert match, css
    return (float(match[1]), float(match[2]), float(match[3]))


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_dashed_legend_chip_text_follows_its_toggle(
    guarded_page: Page, open_app: Callable[[Page, str], None], scheme: str
) -> None:
    """D-37: a dashed chip reads --text when on and --muted-weak when off."""
    guarded_page.emulate_media(color_scheme=scheme)  # type: ignore[arg-type]
    open_app(guarded_page, "?people=dale-harlow")
    sel = '#legend-chips button[data-family="fox"]'
    chip = guarded_page.locator(sel)
    expect(chip).to_have_attribute("data-offered", "false")
    expect(chip).to_have_attribute("aria-pressed", "true")
    bg = _token_rgb(guarded_page, "--bg")
    on = _rgb_of(guarded_page, sel, "color")
    assert on == _token_rgb(guarded_page, "--text")
    assert _ratio(on, bg) >= 4.5
    chip.click()
    expect(chip).to_have_attribute("aria-pressed", "false")
    off = _rgb_of(guarded_page, sel, "color")
    assert off == _token_rgb(guarded_page, "--muted-weak")
    assert _ratio(off, bg) >= 4.5
    disney = '#legend-chips button[data-family="disney"]'
    disney_color: str = guarded_page.locator(disney).evaluate("el => getComputedStyle(el).color")
    assert disney_color == _PILL_CONTRAST["disney"][1]


# --- Hover ring (notes-6) ---------------------------------------------------


def _rgb(hex_color: str) -> str:
    """`#RRGGBB` as the `rgb(r, g, b)` string getComputedStyle returns."""
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    return f"rgb({r}, {g}, {b})"


def _ring_box(page: Page) -> dict[str, Any]:
    """The hover ring's bounding box plus its `dataset.index`."""
    result: dict[str, Any] = page.evaluate(
        "() => { const el = document.getElementById('chart-hover-ring');"
        " const r = el.getBoundingClientRect();"
        " return {x: r.x, y: r.y, width: r.width, height: r.height, index: el.dataset.index}; }"
    )
    return result


def _center(box: dict[str, Any]) -> tuple[float, float]:
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def _assert_ring_on(page: Page, index: int, point: dict[str, float]) -> dict[str, Any]:
    box = _ring_box(page)
    assert box["index"] == str(index)
    cx, cy = _center(box)
    assert abs(cx - point["x"]) <= 1.5
    assert abs(cy - point["y"]) <= 1.5
    return box


_RING = "#chart-hover-ring"
_RING_VISIBLE = "#chart-hover-ring:not([hidden])"


@pytest.mark.parametrize("color_scheme", ["light", "dark"])
def test_hover_ring_marks_the_hovered_dot(
    guarded_page: Page, open_app: Callable[[Page, str], None], color_scheme: str
) -> None:
    """notes-6: hovering an active dot draws an accent ring centered on it, in both
    themes, and it clears when the pointer leaves."""
    guarded_page.emulate_media(color_scheme=color_scheme)  # type: ignore[arg-type]
    open_app(guarded_page, "")
    point = _hover_dot(guarded_page, 0)
    guarded_page.wait_for_selector(_RING_VISIBLE, timeout=3000)
    box = _assert_ring_on(guarded_page, 0, point)
    assert box["width"] == box["height"]
    assert box["width"] >= 12
    style = guarded_page.eval_on_selector(
        _RING,
        "el => { const s = getComputedStyle(el); return [s.borderTopColor, s.pointerEvents]; }",
    )
    assert style[0] == _rgb(_ACCENT[color_scheme])
    assert style[1] == "none"
    guarded_page.mouse.move(5, 5)
    guarded_page.wait_for_selector(f"{_RING}[hidden]", state="attached")


def test_hover_ring_follows_the_hovered_dot(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """notes-6: moving to another dot moves the ring to that dot's own pixel."""
    open_app(guarded_page, "")
    _hover_dot(guarded_page, 0)
    point = _hover_dot(guarded_page, 1)
    guarded_page.wait_for_selector(_RING_VISIBLE, timeout=3000)
    _assert_ring_on(guarded_page, 1, point)


def test_hover_ring_clears_on_scroll_and_modal_open(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-22 close triggers: scroll and opening the detail modal both clear the ring."""
    open_app(guarded_page, "")
    _hover_dot(guarded_page, 0)
    guarded_page.wait_for_selector(_RING_VISIBLE, timeout=3000)
    guarded_page.evaluate("window.scrollBy(0, 40)")
    guarded_page.wait_for_selector(f"{_RING}[hidden]", state="attached")

    point = _hover_dot(guarded_page, 0)
    guarded_page.wait_for_selector(_RING_VISIBLE, timeout=3000)
    guarded_page.mouse.click(point["x"], point["y"])
    guarded_page.wait_for_function("document.getElementById('detail-panel').open")
    assert guarded_page.is_hidden(_RING)


def test_hover_ring_clears_on_zoom(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """A zoom's plotly_relayout moves dots out from under the ring, so it clears."""
    open_app(guarded_page, "")
    _hover_dot(guarded_page, 0)
    guarded_page.wait_for_selector(_RING_VISIBLE, timeout=3000)
    guarded_page.evaluate(
        "() => { const gd = document.getElementById('chart');"
        " const r = gd._fullLayout.xaxis.range;"
        " return window.Plotly.relayout(gd, {'xaxis.range': [r[0], r[0] + (r[1] - r[0]) / 2]}); }"
    )
    guarded_page.wait_for_selector(f"{_RING}[hidden]", state="attached")


def test_zero_captions_settle_when_zoomed_off_zero(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """Regression: zooming so x = 0 leaves the range must not start an endless
    afterplot -> relayout loop in fitZeroCaptions; the relayout count settles."""
    open_app(guarded_page, "")
    guarded_page.evaluate(
        "() => { const gd = document.getElementById('chart');"
        " window.__relayouts = 0;"
        " gd.on('plotly_relayout', () => { window.__relayouts += 1; });"
        " const r = gd._fullLayout.xaxis.range;"
        " return window.Plotly.relayout(gd, {'xaxis.range': [r[0], r[0] + (r[1] - r[0]) / 4]}); }"
    )
    guarded_page.wait_for_timeout(500)
    first = guarded_page.evaluate("window.__relayouts")
    guarded_page.wait_for_timeout(500)
    assert guarded_page.evaluate("window.__relayouts") == first
    assert first <= 3


_COUNTERS_JS = """
() => {
  const gd = document.getElementById('chart');
  const counts = {};
  for (const name of ['react', 'restyle', 'relayout', 'update', 'redraw', 'newPlot']) {
    counts[name] = 0;
    const orig = window.Plotly[name];
    window.Plotly[name] = function (...args) { counts[name] += 1; return orig.apply(this, args); };
  }
  counts.plotly_relayout = 0;
  gd.on('plotly_relayout', () => { counts.plotly_relayout += 1; });
  window.__hoverCounts = counts;
  const rect = (id) => JSON.stringify(document.getElementById(id).getBoundingClientRect());
  window.__hoverSnapshot = () => ({
    traces: gd.data.length,
    layout: JSON.stringify(gd.layout),
    chart: rect('chart'),
    area: rect('chart-area'),
    sw: document.documentElement.scrollWidth,
    sh: document.documentElement.scrollHeight,
  });
  window.__hoverBefore = window.__hoverSnapshot();
}
"""


def test_hover_ring_makes_no_plotly_call_and_shifts_nothing(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """04.2 D-01: showing/hiding the ring calls no Plotly API, fires no
    plotly_relayout, and leaves traces, layout, and page geometry untouched."""
    open_app(guarded_page, "")
    guarded_page.locator("#chart").scroll_into_view_if_needed()
    guarded_page.evaluate(_COUNTERS_JS)
    _hover_dot(guarded_page, 0)
    guarded_page.wait_for_selector(_RING_VISIBLE, timeout=3000)
    guarded_page.mouse.move(5, 5)
    guarded_page.wait_for_selector(f"{_RING}[hidden]", state="attached")
    counts = guarded_page.evaluate("window.__hoverCounts")
    assert all(v == 0 for v in counts.values()), counts
    assert guarded_page.evaluate(
        "JSON.stringify(window.__hoverSnapshot()) === JSON.stringify(window.__hoverBefore)"
    )


def test_hover_ring_never_shows_on_inert_or_faded_dots(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-15: an inert or person-faded dot takes no hover, so it never gets the ring."""
    open_app(guarded_page, "?slot=late")
    inert = _inert_dot_point(guarded_page, "inert:fox", 0)
    guarded_page.mouse.move(5, 5)
    guarded_page.mouse.move(inert["x"], inert["y"])
    guarded_page.wait_for_timeout(300)
    assert guarded_page.is_hidden(_RING)

    open_app(guarded_page, "?people=dale-harlow")
    faded = _dot_point(guarded_page, 1)
    guarded_page.mouse.move(5, 5)
    guarded_page.mouse.move(faded["x"], faded["y"])
    guarded_page.wait_for_timeout(300)
    assert guarded_page.is_hidden(_RING)
    _hover_dot(guarded_page, 0)
    guarded_page.wait_for_selector(_RING_VISIBLE, timeout=3000)


@pytest.mark.parametrize("color_scheme", ["light", "dark"])
def test_hover_ring_on_compare_shapes_clears_the_halo(
    guarded_page: Page, open_app: Callable[[Page, str], None], color_scheme: str
) -> None:
    """D-31/D-33: a hovered compare shape gets a ring that clears its halo's
    corners, and the highlight trace gains no marker.line (no speckles)."""
    guarded_page.emulate_media(color_scheme=color_scheme)  # type: ignore[arg-type]
    open_app(guarded_page, _COMPARE_ALL_SHAPES_QUERY)
    points: list[dict[str, Any]] = guarded_page.evaluate(_HIGHLIGHT_POINTS_JS)
    target = next(
        (
            p
            for p in points
            if p["symbol"] != "circle"
            and not p["naSentinel"]
            and not any(_boxes_overlap(p, o) for o in points if o is not p)
        ),
        None,
    )
    assert target is not None, "no testable non-circle compare point"
    line_js = (
        "() => { const t = document.getElementById('chart').data.at(-1);"
        " return [JSON.stringify(t.marker.line), document.getElementById('chart').data.length]; }"
    )
    before = guarded_page.evaluate(line_js)
    point = _hover_dot(guarded_page, target["customdata"])
    guarded_page.wait_for_selector(_RING_VISIBLE, timeout=3000)
    box = _assert_ring_on(guarded_page, target["customdata"], point)
    assert box["width"] >= (target["size"] + 3) * math.sqrt(2) + 4
    assert guarded_page.evaluate(line_js) == before


def test_hover_ring_shows_in_plotly_fallback_mode(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """The ring is independent of TOOLTIP_MODE: it shows beside Plotly's own label."""
    open_app(guarded_page, "")
    _use_plotly_tooltip(guarded_page)
    point = _hover_dot(guarded_page, 0, wait_for=_RING_VISIBLE)
    _assert_ring_on(guarded_page, 0, point)
    assert guarded_page.locator(".hoverlayer .hovertext").count() >= 1
    assert guarded_page.is_hidden("#chart-tooltip")


def test_hover_ring_never_shows_on_touch(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-22: a touch device keeps tap-to-open and never sees the ring."""
    open_app(mobile_page, "")
    point = _dot_point(mobile_page, 0)
    mobile_page.touchscreen.tap(point["x"], point["y"])
    mobile_page.wait_for_function("document.getElementById('detail-panel').open")
    assert mobile_page.is_hidden(_RING)


_RANGES_JS = (
    "() => { const l = document.getElementById('chart')._fullLayout;"
    " return [l.xaxis.range.slice(), l.yaxis.range.slice()]; }"
)


def test_dot_opacity_tiers_match_the_ui_spec_and_are_ordered(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-02: the one place the literal tier values are pinned."""
    open_app(guarded_page, "")
    tiers = _dot_opacity(guarded_page)
    assert tiers == {"active": 1, "activeUnderPerson": 0.5, "inert": 0.3, "inertUnderPerson": 0.15}
    assert tiers["active"] > tiers["activeUnderPerson"] > tiers["inert"] > tiers["inertUnderPerson"]


def test_dot_tiers_stay_separable_in_both_themes(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """UI-SPEC: every adjacent tier pair and each faint tier against the page
    background keeps a composite contrast ratio of at least 1.10."""
    open_app(guarded_page, "")
    minima: dict[str, float] = guarded_page.evaluate(
        """async () => {
          const chart = await import('./modules/chart.js');
          const pal = await import('./modules/palette.js');
          const O = chart.DOT_OPACITY;
          const out = {};
          const note = (k, v) => { out[k] = Math.min(out[k] ?? Infinity, v); };
          for (const theme of ['light', 'dark']) {
            const bg = pal.PAGE_BG[theme];
            for (const color of Object.values(pal.FAMILY_COLORS[theme])) {
              const c = (o) => pal.mixHex(color, bg, o);
              note('active_vs_inert', pal.contrastRatio(c(O.active), c(O.inert)));
              const r = (a, b) => pal.contrastRatio(c(a), c(b));
              note('active_vs_activeUnderPerson', r(O.active, O.activeUnderPerson));
              note('under_person_pair', r(O.activeUnderPerson, O.inertUnderPerson));
              note('inert_vs_bg', pal.contrastRatio(c(O.inert), bg));
              note('inertUnderPerson_vs_bg', pal.contrastRatio(c(O.inertUnderPerson), bg));
            }
          }
          return out;
        }"""
    )
    assert len(minima) == 5
    for pair, ratio in minima.items():
        assert ratio >= 1.10, (pair, ratio)


def test_fade_mode_tiers_without_an_announcer(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-01/D-02: failing dots keep their family color at the inert tier."""
    open_app(guarded_page, "?slot=late")
    tiers = _dot_opacity(guarded_page)
    traces = _traces(guarded_page)
    assert _inert_total(traces) == 11
    for t in _inert_traces(traces):
        assert t["opacity"] == tiers["inert"]
    conference = next(t for t in _family_traces(traces) if t["meta"] == "family:conference")
    assert conference["customdata"] == [2]
    assert conference["opacity"] == tiers["active"]
    assert _marker_color(guarded_page, "inert:fox") == "#009E73"


def test_fade_mode_tiers_with_an_announcer_on_a_filter(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-02: with an announcer selected, passing dots drop to 0.5 and failing
    dots to 0.15; the announcer's own dot sits in the highlight overlay."""
    open_app(guarded_page, "?seasons=2026-2026&people=dale-harlow")
    tiers = _dot_opacity(guarded_page)
    traces = _traces(guarded_page)
    assert _inert_total(traces) == 8
    for t in _inert_traces(traces):
        assert t["opacity"] == tiers["inertUnderPerson"]
    family = _family_traces(traces)
    assert _dot_count(family) == 3
    for t in family:
        assert t["opacity"] == tiers["activeUnderPerson"]
    assert traces[-1]["meta"] == "highlight"
    assert traces[-1]["customdata"] == [8]


def test_hide_mode_drops_filter_failures_but_keeps_the_announcer_pass_tier(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-05: Hide empties the inert traces; the 0.5 tier still shows."""
    open_app(guarded_page, "?seasons=2026-2026&people=dale-harlow&dots=hide")
    tiers = _dot_opacity(guarded_page)
    traces = _traces(guarded_page)
    assert _inert_total(traces) == 0
    family = _family_traces(traces)
    assert _dot_count(family) == 3
    for t in family:
        assert t["opacity"] == tiers["activeUnderPerson"]


@pytest.mark.parametrize("query", ["?networks=net-a", "?networks=net-a&dots=hide"])
def test_networks_hide_in_both_modes(
    guarded_page: Page, open_app: Callable[[Page, str], None], query: str
) -> None:
    """D-07: Networks always removes the other dots."""
    open_app(guarded_page, query)
    traces = _traces(guarded_page)
    assert _inert_total(traces) == 0
    assert sorted(cd for t in _family_traces(traces) for cd in t["customdata"]) == [0, 4, 8]


def test_seasons_fade_in_fade_mode_and_hide_in_hide_mode(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?seasons=2025-2025")
    traces = _traces(guarded_page)
    assert _inert_total(traces) == 8
    assert _dot_count(_family_traces(traces)) == 4

    open_app(guarded_page, "?seasons=2025-2025&dots=hide")
    traces = _traces(guarded_page)
    assert _inert_total(traces) == 0
    assert _dot_count(_family_traces(traces)) == 4


def test_trace_count_is_constant_across_fade_and_hide(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?slot=late")
    fade = len(_traces(guarded_page))
    open_app(guarded_page, "?slot=late&dots=hide")
    assert len(_traces(guarded_page)) == fade


@pytest.mark.parametrize("query", ["", "?axis=excitement"])
def test_axes_never_move_with_filters_or_mode(
    guarded_page: Page, open_app: Callable[[Page, str], None], query: str
) -> None:
    """D-08: filters, Fade/Hide, and head-to-head never change axis ranges."""
    open_app(guarded_page, query)
    original = guarded_page.evaluate(_RANGES_JS)
    for patch in (
        "{seasons: [2025, 2025]}",
        "{dots: 'hide'}",
        "{networks: ['net-a']}",
        "{networks: null, school: ['northfield', 'lakeview'], h2h: true}",
    ):
        guarded_page.evaluate(f"window.__testHooks.setState({patch})")
        guarded_page.wait_for_timeout(150)
        assert guarded_page.evaluate(_RANGES_JS) == original, patch


@pytest.mark.parametrize("query", ["?slot=late", "?seasons=2026-2026&people=dale-harlow"])
def test_faded_traces_draw_under_every_active_trace(
    guarded_page: Page, open_app: Callable[[Page, str], None], query: str
) -> None:
    """D-03: all inert traces come before every family trace."""
    open_app(guarded_page, query)
    metas = [str(t["meta"]) for t in _traces(guarded_page)]
    inert = [i for i, m in enumerate(metas) if m.startswith("inert:")]
    family = [i for i, m in enumerate(metas) if m.startswith("family:")]
    assert max(inert) < min(family)
