"""Chart-level browser tests (SITE-01, SITE-03, SITE-04, SITE-12, SITE-18,
SITE-19; D-01..D-04, D-12) -- proven against the fixture build served by
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
# own size/offset -- never a hardcoded pixel guess.
_DOT_PIXEL_JS = """
(customdata) => {
  const gd = document.getElementById('chart');
  const layout = gd._fullLayout;
  const rect = gd.getBoundingClientRect();
  for (const trace of gd.data) {
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
    point: dict[str, float] | None = page.evaluate(_DOT_PIXEL_JS, customdata)
    assert point is not None, f"no dot with customdata {customdata}"
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
    return [t for t in traces if str(t["meta"]).startswith("family:")]


def _dot_count(traces: list[dict[str, Any]]) -> int:
    """Real dots across `traces`, skipping a family trace's `null` legend
    placeholder (CR-03: an otherwise-empty family keeps one null point so
    Plotly doesn't drop its legend entry)."""
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


def test_legend_click_toggles_family_and_updates_networks_url(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-01/D-05: clicking the Fox legend entry hides its 3 dots and records
    the remaining networks in the URL."""
    open_app(guarded_page, "")
    legend_entry = guarded_page.locator(".traces", has_text="Fox (FOX/FS1/BTN)")
    legend_entry.locator(".legendtoggle").click()
    guarded_page.wait_for_function("location.search.includes('networks=')")

    family_traces = _family_traces(_traces(guarded_page))
    assert _dot_count(family_traces) == 9
    assert "networks=" in guarded_page.url
    assert "net-b" not in guarded_page.url


_LEGEND_LABELS = [
    "Disney (ABC/ESPN)",
    "Fox (FOX/FS1/BTN)",
    "Conference networks",
    "Other",
]


def _legend_labels(page: Page) -> list[str]:
    return page.locator(".legend .traces .legendtext").all_text_contents()


def _family_visibility(page: Page) -> dict[str, Any]:
    result: dict[str, Any] = page.evaluate(
        "() => Object.fromEntries(document.getElementById('chart').data"
        ".filter(t => String(t.meta).startsWith('family:')).map(t => [t.meta, t.visible]))"
    )
    return result


def test_legend_entry_survives_toggle_off_and_can_be_toggled_back_on(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """CR-03: a family toggled off keeps its (greyed) legend entry, so a
    second click turns it back on, and the entries never shift position --
    a double-click then isolates exactly the family it was aimed at."""
    open_app(guarded_page, "")
    assert _legend_labels(guarded_page) == _LEGEND_LABELS

    def toggle(label: str) -> None:
        guarded_page.locator(".legend .traces", has_text=label).locator(".legendtoggle").click()

    toggle("Disney (ABC/ESPN)")
    guarded_page.wait_for_function("location.search.includes('networks=')")
    assert "net-a" not in guarded_page.url
    assert _legend_labels(guarded_page) == _LEGEND_LABELS
    assert _family_visibility(guarded_page)["family:disney"] == "legendonly"

    # Past Plotly's double-click window, so the next click reads as a single one.
    guarded_page.wait_for_timeout(500)
    toggle("Disney (ABC/ESPN)")
    guarded_page.wait_for_function("location.search === ''")
    assert _legend_labels(guarded_page) == _LEGEND_LABELS
    assert set(_family_visibility(guarded_page).values()) == {True}

    guarded_page.wait_for_timeout(500)
    guarded_page.locator(".legend .traces", has_text="Fox (FOX/FS1/BTN)").locator(
        ".legendtoggle"
    ).dblclick()
    guarded_page.wait_for_function("location.search === '?networks=net-b'")
    assert _legend_labels(guarded_page) == _LEGEND_LABELS
    visibility = _family_visibility(guarded_page)
    assert visibility["family:fox"] is True
    assert [visibility[f"family:{f}"] for f in ("disney", "conference", "other")] == [
        "legendonly"
    ] * 3


@pytest.mark.parametrize("query", ["?seasons=2021-2021", "?team=northfield"])
def test_legend_keeps_a_family_with_no_dots_of_its_own_as_on(
    guarded_page: Page, open_app: Callable[[Page, str], None], query: str
) -> None:
    """CR-03: a family left with no family-trace dots -- emptied by the
    season range (2021 has no Disney/Fox games), or because every one of its
    dots moved to the highlight overlay (Northfield's games are all Disney)
    -- still lists its legend entry, reading as on (its networks are still
    selected)."""
    open_app(guarded_page, query)
    assert _legend_labels(guarded_page) == _LEGEND_LABELS
    assert set(_family_visibility(guarded_page).values()) == {True}


def test_set_state_people_highlights_and_fades_family_traces(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """SITE-02/SITE-12: selecting a person highlights exactly their games and
    fades every other dot to 15% opacity, keeping its color."""
    open_app(guarded_page, "")
    guarded_page.evaluate("window.__testHooks.setState({people: ['dale-harlow']})")

    traces = _traces(guarded_page)
    assert sorted(traces[-1]["customdata"]) == [0, 8]
    for t in _family_traces(traces):
        assert t["opacity"] == 0.15
    assert guarded_page.url.endswith("?people=dale-harlow")


def test_hover_text_stays_minimal_and_drops_methodology_notes(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """SITE-04 (product notes 2026-09-27): the tooltip carries only the
    matchup+score, date+kickoff, networks, crew, viewers, and a closing
    "click or tap for details" hint -- the measurement/scoring-source label,
    time-slot label, axis values, and flags/combined-feed notes are dropped
    from the tooltip (they still show in the detail panel: see
    test_site_panel_table.py's test_open_panel_hook_shows_nielsen_adobe_badge,
    test_open_panel_hook_shows_flag_label,
    test_open_panel_hook_shows_alt_cast_and_combined_feeds, and
    test_panel_time_slot_shown_only_for_saturday_games)."""
    open_app(guarded_page, "")
    traces = _traces(guarded_page)

    dot0 = _hover_text(traces, 0)
    assert "Lakeview 20 at Northfield 27" in dot0
    assert "Sat, Sep 7, 2019" in dot0
    assert "Click or tap for details" in dot0
    assert dot0.endswith("Click or tap for details")

    dot5 = _hover_text(traces, 5)
    assert "Nielsen + Adobe" not in dot5
    assert "Prime time" not in dot5
    assert "Thursday" not in dot5

    dot11 = _hover_text(traces, 11)
    assert "CFBD win-probability model break" not in dot11
    assert "Excitement:" not in dot11
    assert "Spread:" not in dot11

    dot7 = _hover_text(traces, 7)
    assert "Combined across" not in dot7
    assert "Other Network / Alpha Sports / Beta Network" in dot7


def test_hover_text_network_line_is_slash_joined_primary_first(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """A multi-outlet telecast lists networks slash-delimited, primary
    first ("Alpha Sports / Beta Network"), never the old "(also ...)"
    wrapping."""
    open_app(guarded_page, "")
    traces = _traces(guarded_page)
    dot4 = _hover_text(traces, 4)
    assert "Alpha Sports / Beta Network" in dot4
    assert "(also" not in dot4


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


def test_missing_site_data_shows_load_error(guarded_page: Page, site_url: str) -> None:
    """A failed site-data.json fetch unhides #load-error with its copy."""
    guarded_page.route("**/site-data.json*", lambda route: route.fulfill(status=404))
    guarded_page.goto(f"{site_url}/index.html")
    guarded_page.wait_for_function("window.__testHooks && window.__testHooks.ready === true")

    assert guarded_page.is_visible("#load-error")
    assert "Couldn't load the site data." in guarded_page.inner_text("#load-error")


def test_mobile_layout_disables_drag_zoom_and_moves_legend_below(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """SITE-18: on phones, drag-zoom is off, axis ranges are fixed, and the
    legend renders below the chart (horizontal orientation)."""
    open_app(mobile_page, "")
    layout = _layout(mobile_page)

    assert layout["dragmode"] is False
    assert layout["xaxis"]["fixedrange"] is True
    assert layout["legend"]["orientation"] == "h"


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
    """T3/D-02: with nobody selected every dot lives in its family trace as
    normal. Once a person is selected, each highlighted dot is drawn *only*
    by the highlight overlay (its family trace drops the now-redundant
    duplicate) -- otherwise the coincident faded copy underneath and the
    highlight overlay's own dot would compete equally for hover/click, which
    is exactly what left them "treated equally" instead of snapping to the
    highlighted one."""
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
    """SITE-04/T3: hovering directly on a highlighted dot's position always
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
    """SITE-04: with a selection, faded family traces skip hover entirely, so
    a hover near a highlighted dot snaps to it rather than to a nearer faded
    dot. Plotly drops `hoverinfo` whenever `hovertemplate` is set, so this
    checks the resolved `_fullData`, not just the input trace."""
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
    # Dot 1 is not one of Dale Harlow's games: hovering right on it must never
    # surface its faded family trace.
    point = _dot_point(guarded_page, 1)
    guarded_page.mouse.move(point["x"], point["y"])
    guarded_page.wait_for_timeout(300)
    metas = guarded_page.evaluate("window.__hoverMetas")
    assert all(meta == "highlight" for meta in metas)


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
