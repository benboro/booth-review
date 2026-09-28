"""Chart-level browser tests (SITE-01, SITE-03, SITE-04, SITE-12, SITE-18,
SITE-19, SITE-20, SITE-23, SITE-25, SITE-26; D-01..D-04, D-08, D-12, D-14,
D-15, D-16) -- proven against the fixture build served by
`guarded_page`/`mobile_page`/`open_app`/`site_url`, per
`tests/fixtures/contract/site-data.fixture.json`'s 12 dots.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

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
    return {
      x: rect.left + layout._size.l + layout.xaxis.d2p(trace.x[idx]),
      y: rect.top + layout._size.t + layout.yaxis.d2p(trace.y[idx]),
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
    y: rect.top + layout._size.t + layout.yaxis.d2p(trace.y[index]),
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


def test_default_load_shows_all_dots_no_selection_pregame_axis(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-12: first load with no query shows all 12 dots, nobody highlighted,
    and the pre-game axis, with a clean URL."""
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
        guarded_page.get_attribute('#axis-toggle button[data-axis="pregame"]', "aria-pressed")
        == "true"
    )
    assert guarded_page.is_hidden("#excitement-caption")
    for t in family_traces:
        assert t["opacity"] == 1


def test_na_strip_places_missing_x_dots_in_the_reserved_band(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-03: dot 3 (pregame) / dot 2 (excitement) sit left of the divider,
    everything else sits to its right, and the strip is labelled N/A."""
    open_app(guarded_page, "")
    layout = _layout(guarded_page)
    divider = layout["shapes"][0]["x0"]
    points = _dot_x_by_customdata(_traces(guarded_page))
    assert points[3] < divider
    for customdata, x in points.items():
        if customdata != 3:
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
    assert x_title == ["Closing spread (points) — closer games to the right"]
    assert y_title == ["Viewers (log scale)"]

    guarded_page.click('#axis-toggle button[data-axis="excitement"]')
    guarded_page.wait_for_function("location.search === '?axis=excitement'")
    assert guarded_page.locator(".g-xtitle text").all_text_contents() == ["Excitement index (CFBD)"]


def test_mobile_x_axis_title_fits_the_screen_and_clears_the_legend(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """CR-02 follow-up: once the titles render, the long pre-game title is
    wider than a 390px phone, so on phones it wraps onto two lines, stays
    inside the viewport, and sits above the (below-chart) HTML chip legend
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
    assert mobile_page.locator(".g-xtitle text tspan").count() >= 2


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


def test_legend_chip_click_toggles_family_and_moves_its_dots_to_inert(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-16: clicking a legend chip toggles that family in the Networks
    filter, fades its dots to inert, round-trips through the URL, and
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
    assert sum(len(t["x"]) for t in _inert_traces(traces)) == 3

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


def test_chart_tabs_slot_is_reserved_and_empty(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-08: a 40px slot is reserved above the legend row for Phase 04.2's
    chart-tab bar; this phase leaves it empty."""
    open_app(guarded_page, "")
    box = guarded_page.locator("#chart-tabs").bounding_box()
    assert box is not None
    assert box["height"] == 40
    assert guarded_page.locator("#chart-tabs").locator("*").count() == 0

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
    fades every other passing dot to 15% opacity, keeping its color."""
    open_app(guarded_page, "")
    guarded_page.evaluate("window.__testHooks.setState({people: ['dale-harlow']})")

    traces = _traces(guarded_page)
    assert sorted(traces[-1]["customdata"]) == [0, 8]
    for t in _family_traces(traces):
        assert t["opacity"] == 0.15
    assert guarded_page.url.endswith("?people=dale-harlow")


def test_networks_filter_fades_non_matching_families_to_inert(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-13/D-14/SITE-23: `?networks=net-a` only removes nothing -- it fades
    the other 9 dots into their family's inert trace, grey at ~8% opacity,
    with hover fully suppressed on the resolved `_fullData` (both
    `hoverinfo: 'skip'` and `hovertemplate: null` are required, the 04-11
    finding)."""
    open_app(guarded_page, "?networks=net-a")
    traces = _traces(guarded_page)
    inert = _inert_traces(traces)
    assert sum(len(t["x"]) for t in inert) == 9
    for t in inert:
        assert t["opacity"] == 0.08
    assert _dot_count(_family_traces(traces)) == 3

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
    open_app(guarded_page, "?networks=net-a")
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
    assert guarded_page.evaluate("document.getElementById('detail-panel').hidden") is True


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
    assert -3.5 in disney_inert["x"]  # dot 0's pregame spread
    assert -6.5 in disney_inert["x"]  # dot 8's pregame spread


def test_hover_text_stays_minimal_and_drops_methodology_notes(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """SITE-25 (product notes 2026-09-27): the tooltip carries only the
    matchup+score, date+kickoff(+slot), networks, crew, viewers, the active
    axis value, and a closing "Click for details →" hint -- the
    measurement/scoring-source label, conferences, game type, and
    flags/combined-feed notes are dropped from the tooltip (they still show
    in the detail panel: see test_site_panel_table.py's
    test_open_panel_hook_shows_nielsen_adobe_badge,
    test_open_panel_hook_shows_flag_label,
    test_open_panel_hook_shows_alt_cast_and_combined_feeds, and
    test_panel_time_slot_shown_only_for_saturday_games)."""
    open_app(guarded_page, "")
    traces = _traces(guarded_page)

    dot0 = _hover_text(traces, 0)
    assert "Lakeview 20 at Northfield 27" in dot0
    assert "Sat, Sep 7, 2019" in dot0
    assert "Noon" in dot0
    assert dot0.endswith("Click for details →")
    assert "Measurement" not in dot0
    assert "Source" not in dot0
    assert "Selected:" not in dot0
    assert "(" not in dot0

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

    traces = _traces(guarded_page)
    dot0 = _hover_text(traces, 0)
    assert "Alpha Sports" in dot0
    assert "regional insert package" not in dot0


def test_hover_text_crew_lines_use_position_colon_name_format(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """SITE-25/CONTEXT "Claude's Discretion": one "Position: Name" line per
    main-feed crew member, pbp before analyst before sideline/other."""
    open_app(guarded_page, "")
    traces = _traces(guarded_page)
    lines = _hover_text(traces, 0).split("<br>")
    assert "Play-by-play: Dale Harlow" in lines
    assert "Analyst: Dale Harlow Jr." in lines
    assert lines.index("Play-by-play: Dale Harlow") < lines.index("Analyst: Dale Harlow Jr.")


def test_hover_text_shows_the_active_axis_value_and_closing_hint(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """SITE-25: the tooltip's sixth line is the active axis's own value,
    never the other axis's."""
    open_app(guarded_page, "")
    dot11 = _hover_text(_traces(guarded_page), 11)
    assert "Spread: 1.5" in dot11
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

    point = _dot_point(guarded_page, 0)
    guarded_page.mouse.move(point["x"], point["y"])
    guarded_page.wait_for_selector(".hoverlayer .hovertext")

    assert guarded_page.evaluate("window.__xss") is None
    assert guarded_page.locator(".hoverlayer img").count() == 0
    text = "".join(guarded_page.locator(".hoverlayer .hovertext tspan").all_text_contents())
    assert "<img" in text
