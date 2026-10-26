"""DARK-01 (17-05): the CFB charts, strips, controls, pills, legend and open panels in dark.

Each test flips the theme on a live page (no reload) and checks the colours the UI-SPEC
"Plotly theming (D-11)" table sets. Synthetic fixture only; the page guard fails any
request that leaves the origin.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from dark_checks import chart_layout, click_toggle, rgb, set_theme, white_box_offenders
from playwright.sync_api import Page
from test_site_chart import _hover_dot

pytestmark = pytest.mark.e2e

OpenApp = Callable[[Page, str], None]

PAGE_BG = "#1D1B18"
GRID = "#3A3632"
MUTED = "#A59E94"
SURFACE = "#26231F"
INK = "#ECE7DF"

_PALETTE_JS = """
async () => {
  const p = await import(new URL('./modules/palette.js', location.href).href);
  return { family: p.FAMILY_COLORS.dark, pillText: p.PILL_TEXT_COLOR.dark,
           mapFamily: p.MAP_FAMILY_COLORS.dark };
}
"""


def _palette(page: Page) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = page.evaluate(_PALETTE_JS)
    return result


def _assert_dark_frame(page: Page, selector: str = "#chart") -> None:
    lay = chart_layout(page, selector)
    assert lay["paper"] == PAGE_BG and lay["plot"] == PAGE_BG, lay
    assert lay["font"] == MUTED, lay
    assert lay["gridY"] == GRID, lay
    assert lay["tick"] == MUTED, lay
    assert lay["hoverBg"] == SURFACE and lay["hoverInk"] == INK, lay


def test_scatter_repaints_dark_after_toggle_click_and_keeps_zoom(
    guarded_page: Page, open_app: OpenApp
) -> None:
    open_app(guarded_page, "")
    before = chart_layout(guarded_page)
    click_toggle(guarded_page)
    assert guarded_page.evaluate("document.documentElement.dataset.theme") == "dark"
    _assert_dark_frame(guarded_page)
    after = chart_layout(guarded_page)
    assert after["xrange"] == before["xrange"] and after["yrange"] == before["yrange"]
    assert white_box_offenders(guarded_page) == []


def test_scatter_tooltip_is_dark_ink_on_surface(guarded_page: Page, open_app: OpenApp) -> None:
    open_app(guarded_page, "")
    set_theme(guarded_page, "dark")
    _hover_dot(guarded_page, 0)
    tip = guarded_page.evaluate(
        "(() => { const t = document.getElementById('chart-tooltip');"
        " const s = getComputedStyle(t); return [s.backgroundColor, s.color]; })()"
    )
    assert tip == [rgb(SURFACE), rgb(INK)]
    assert white_box_offenders(guarded_page) == []


def test_strips_and_reset_zoom_in_dark(guarded_page: Page, open_app: OpenApp) -> None:
    open_app(guarded_page, "")
    set_theme(guarded_page, "dark")
    shapes = chart_layout(guarded_page)["shapes"]
    assert any(s["type"] == "rect" and s["fill"] == SURFACE for s in shapes), shapes
    assert any(s["type"] == "line" and s["line"] == GRID for s in shapes), shapes
    label = guarded_page.evaluate(
        "(() => { const s = getComputedStyle(document.querySelector('.band-info'));"
        " return s.color; })()"
    )
    assert label == rgb(MUTED)
    reset = guarded_page.evaluate(
        "(() => { const s = getComputedStyle(document.getElementById('reset-zoom'));"
        " const r = getComputedStyle(document.documentElement);"
        " return [s.color, s.borderTopColor,"
        " r.getPropertyValue('--ink').trim(), r.getPropertyValue('--rule-strong').trim(),"
        " r.getPropertyValue('--disabled').trim()]; })()"
    )
    # At the home range Reset zoom is disabled, so its label takes --disabled.
    assert reset[0] == rgb(reset[4]) and reset[1] == rgb(reset[3]), reset
    assert white_box_offenders(guarded_page) == []


def test_excitement_strip_in_dark(guarded_page: Page, open_app: OpenApp) -> None:
    open_app(guarded_page, "?axis=excitement")
    set_theme(guarded_page, "dark")
    shapes = chart_layout(guarded_page)["shapes"]
    assert any(s["type"] == "rect" and s["fill"] == SURFACE for s in shapes), shapes
    assert white_box_offenders(guarded_page) == []


def test_bars_and_butterfly_dark_tone_a_and_no_white_boxes(
    guarded_page: Page, open_app: OpenApp
) -> None:
    for query in ("?school=northfield&view=bars", "?school=northfield,lakeview&view=butterfly"):
        open_app(guarded_page, query)
        click_toggle(guarded_page)
        _assert_dark_frame(guarded_page, "#bars-chart")
        colors = guarded_page.evaluate(
            "Array.from(document.querySelectorAll('#bars-chart .trace.bars .point path'))"
            ".map(p => getComputedStyle(p).fill)"
        )
        family = {rgb(v) for v in _palette(guarded_page)["family"].values()}
        assert colors and any(c in family for c in colors), (query, colors)
        assert white_box_offenders(guarded_page) == []
        click_toggle(guarded_page)  # leave light for the next navigation


def test_legend_dots_pills_and_network_dots_repaint_without_reload(
    guarded_page: Page, open_app: OpenApp
) -> None:
    open_app(guarded_page, "?school=northfield")
    guarded_page.evaluate("window.__testHooks.openPanel(0)")
    guarded_page.locator("#detail-panel").wait_for(state="visible")
    palette = _palette(guarded_page)
    set_theme(guarded_page, "dark")
    legend = guarded_page.evaluate(
        "Array.from(document.querySelectorAll('#legend-chips .legend-chip')).map(c =>"
        " [c.dataset.family, getComputedStyle(c.querySelector('.legend-dot')).backgroundColor])"
    )
    assert legend
    for family, color in legend:
        assert color == rgb(palette["family"][family]), (family, color)
    paints = guarded_page.evaluate(
        """Array.from(document.querySelectorAll(
            '#detail-panel .pill[data-family], #detail-panel .net-dot[data-family]'))
            .map(e => [e.className, e.dataset.family, getComputedStyle(e).backgroundColor,
                       getComputedStyle(e).color])"""
    )
    assert paints, "the open panel shows no family pill or dot"
    for cls, family, bg, fg in paints:
        assert bg == rgb(palette["family"][family]), (cls, family, bg)
        if "pill" in cls.split():
            assert fg == rgb(palette["pillText"][family]), (cls, family, fg)
    # Closing and reopening also shows dark.
    guarded_page.keyboard.press("Escape")
    guarded_page.evaluate("window.__testHooks.openPanel(0)")
    again = guarded_page.evaluate(
        "Array.from(document.querySelectorAll('#detail-panel .pill[data-family]'))"
        ".map(e => [e.dataset.family, getComputedStyle(e).backgroundColor])"
    )
    for family, bg in again:
        assert bg == rgb(palette["family"][family])


def test_table_pills_repaint_without_reload(guarded_page: Page, open_app: OpenApp) -> None:
    open_app(guarded_page, "?school=northfield")
    palette = _palette(guarded_page)
    set_theme(guarded_page, "dark")
    paints = guarded_page.evaluate(
        "Array.from(document.querySelectorAll('.pill[data-family]'))"
        ".map(e => [e.dataset.family, getComputedStyle(e).backgroundColor])"
    )
    for family, bg in paints:
        assert bg == rgb(palette["family"][family]), (family, bg)


def test_bars_counts_swatches_repaint(guarded_page: Page, open_app: OpenApp) -> None:
    open_app(guarded_page, "?school=northfield&by=network&view=bars")
    guarded_page.locator("#bars-data summary").click()
    palette = _palette(guarded_page)
    set_theme(guarded_page, "dark")
    paints = guarded_page.evaluate(
        "Array.from(document.querySelectorAll('#bars-counts .pill[data-family],"
        " #bars-counts .net-dot[data-family]'))"
        ".map(e => [e.dataset.family, getComputedStyle(e).backgroundColor])"
    )
    assert paints, "the counts list shows no family pill or dot"
    for family, bg in paints:
        assert bg == rgb(palette["family"][family]), (family, bg)


# -- The splat map in dark (D-10) -------------------------------------------------------

_MAP_TRACES = """() => document.getElementById('map-chart').data.map(
  (t) => ({name: t.name, linecolor: t.line && t.line.color, fill: t.fillcolor,
           mcolor: t.marker ? t.marker.color : null,
           textcolor: t.textfont ? t.textfont.color : null, n: (t.x || []).length}))"""
_MAP_IMAGES = (
    "() => (document.getElementById('map-chart').layout.images || []).map((i) => i.source)"
)
MAP_LAND = "#2A2722"
MAP_OUTLINE = "#4A453E"
MAP_NEUTRAL = "#8B8377"


def _open_dark_map(page: Page, open_app: OpenApp, query: str) -> None:
    page.add_init_script("localStorage.setItem('bl-theme', 'dark')")
    open_app(page, query)
    page.wait_for_function("() => window.__testHooks.mapRenders >= 1")
    page.wait_for_function("() => window.__testHooks.mapSplatRenders >= 1")
    page.wait_for_timeout(300)


@pytest.mark.parametrize("live_flip", [True, False])
def test_map_dark_base_dots_and_splat(
    guarded_page: Page, open_app: OpenApp, live_flip: bool
) -> None:
    query = "?view=map&people=pat-rowan"
    if live_flip:
        open_app(guarded_page, query)
        guarded_page.wait_for_function("() => window.__testHooks.mapSplatRenders >= 1")
        light_image = guarded_page.evaluate(_MAP_IMAGES)
    else:
        light_image = None
    if live_flip:
        _flip_map_dark(guarded_page)
    else:
        _open_dark_map(guarded_page, open_app, query)
    palette = _palette(guarded_page)
    traces = {t["name"]: t for t in guarded_page.evaluate(_MAP_TRACES)}
    # The splat paints the land as an image, so the outline carries the land fill only as the
    # fallback; either way it must be the dark land value, never the light one.
    assert traces["outline"]["linecolor"] == MAP_OUTLINE, traces["outline"]
    assert traces["outline"]["fill"] in (MAP_LAND, None, "rgba(0,0,0,0)"), traces["outline"]
    for family in ("disney", "fox"):
        leg = traces.get(f"legs:{family}")
        if leg and leg["n"]:
            assert leg["linecolor"] == palette["mapFamily"][family], leg
    dots = traces["venue-dots"]
    assert dots["n"] > 0
    model = guarded_page.evaluate("() => window.__testHooks.getMapModel()")
    assert dots["mcolor"] == [d["dotColor"]["dark"] for d in model["venueDots"]], dots["mcolor"]
    neutral = guarded_page.evaluate(
        "import(new URL('./modules/palette.js', location.href).href)"
        ".then(p => p.MAP_DOT_NEUTRAL.dark)"
    )
    assert neutral == MAP_NEUTRAL
    bg = guarded_page.evaluate(
        "getComputedStyle(document.getElementById('map-chart')).backgroundColor"
    )
    assert chart_layout(guarded_page, "#map-chart")["paper"] == PAGE_BG, bg
    images = guarded_page.evaluate(_MAP_IMAGES)
    assert len(images) == 1 and images[0].startswith("blob:")
    if light_image is not None:
        assert images[0] != light_image[0], "the splat was not regenerated for dark"
    assert white_box_offenders(guarded_page) == []


def _flip_map_dark(page: Page) -> None:
    renders = page.evaluate("() => window.__testHooks.mapSplatRenders")
    set_theme(page, "dark")
    page.wait_for_function(
        "(n) => window.__testHooks.mapSplatRenders > n", arg=renders, timeout=15000
    )
    page.wait_for_timeout(300)


def test_map_labels_are_live_svg_text_in_dark(guarded_page: Page, open_app: OpenApp) -> None:
    # The labels are live SVG text, never raster pixels in the splat image. They are not
    # user-selectable, in light or dark: Plotly sets `user-select: none` on its charts, and dark
    # matches light here. The Range text below proves the text is live, not that it selects.
    open_app(guarded_page, "?view=map&people=pat-rowan")
    guarded_page.wait_for_function("() => window.__testHooks.mapSplatRenders >= 1")
    _flip_map_dark(guarded_page)
    result = guarded_page.evaluate(
        """() => {
          const nodes = [...document.querySelectorAll('#map-chart text')]
            .filter((n) => (n.textContent || '').trim().length > 0 && n.closest('.main-svg'));
          if (!nodes.length) return null;
          const node = nodes.find((n) => n.closest('.textpoint')) || nodes[0];
          const range = document.createRange();
          range.selectNodeContents(node);
          return { text: range.toString(), tag: node.tagName.toLowerCase(),
                   fill: getComputedStyle(node).fill };
        }"""
    )
    assert result is not None, "no SVG text node on the dark map"
    assert result["tag"] == "text" and result["text"].strip(), result
    assert result["fill"] == rgb(MUTED), result
    marker_text = guarded_page.evaluate(
        "(document.getElementById('map-chart').data.find((t) => t.name === 'markers') || {})"
        ".textfont?.color ?? null"
    )
    assert marker_text in (None, MUTED), marker_text


def test_map_land_fill_is_dark_when_the_raster_fails(guarded_page: Page, open_app: OpenApp) -> None:
    """Colours are always on, so the plain land fill shows only on the raster-failure fallback."""
    guarded_page.add_init_script("localStorage.setItem('bl-theme', 'dark')")
    guarded_page.add_init_script(
        """
        if (typeof OffscreenCanvas !== 'undefined') {
          OffscreenCanvas.prototype.convertToBlob = () => Promise.reject(new Error('boom'));
        }
        HTMLCanvasElement.prototype.toBlob = function (cb) { cb(null); };
        """
    )
    open_app(guarded_page, "?view=map")
    guarded_page.wait_for_function("() => window.__testHooks.mapRenders >= 1")
    guarded_page.wait_for_function(
        "() => document.getElementById('map-chart').data[0].fill === 'toself'"
    )
    outline = next(t for t in guarded_page.evaluate(_MAP_TRACES) if t["name"] == "outline")
    assert outline["fill"] == MAP_LAND and outline["linecolor"] == MAP_OUTLINE, outline
