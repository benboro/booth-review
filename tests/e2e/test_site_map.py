"""04.18 (SITE-72..75): end-to-end Map behavior on the synthetic fixture.

Each test's docstring names the locked decision (D-xx) it proves. Fixture only; no
vault content.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

OpenApp = Callable[[Page, str], None]

MAP_HINT = "Pick an announcer or a school to trace a path"
_FAMILIES = ["disney", "fox", "cbs", "nbc", "cw", "wbd", "conference", "other"]
_TRACE_NAMES = (
    ["outline"]
    + [f"legs:{f}" for f in _FAMILIES]
    + [f"inert:{f}" for f in _FAMILIES]
    + [f"dots:{f}" for f in _FAMILIES]
    + ["markers"]
)
# Fixture network ids by family (lookups.networks): net-a disney, net-b fox, net-c
# conference, net-d other, net-e disney (Stream Plus, the Nassau game's network).
_ALL_BUT_NET_E = ["net-a", "net-b", "net-c", "net-d"]

_TRACE_INFO = """() => document.getElementById('map-chart').data.map(
  (t) => ({name: t.name, n: (t.x || []).length, color: t.line && t.line.color,
           fill: t.fillcolor, text: t.text || null, mx: t.x, my: t.y,
           symbols: t.marker ? t.marker.symbol : null}))"""


def _open_map(page: Page, open_app: OpenApp, query: str) -> None:
    open_app(page, query)
    page.wait_for_function("() => window.__testHooks.mapRenders >= 1")


def _renders(page: Page) -> int:
    value: int = page.evaluate("() => window.__testHooks.mapRenders")
    return value


def _set(page: Page, patch: dict[str, Any]) -> None:
    before = _renders(page)
    page.evaluate("(patch) => window.__testHooks.setState(patch)", patch)
    page.wait_for_function("(n) => window.__testHooks.mapRenders > n", arg=before)
    page.evaluate("() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))")


def _model(page: Page) -> dict[str, Any]:
    model: dict[str, Any] = page.evaluate("() => window.__testHooks.getMapModel()")
    return model


def _traces(page: Page) -> dict[str, dict[str, Any]]:
    info: list[dict[str, Any]] = page.evaluate(_TRACE_INFO)
    return {t["name"]: t for t in info}


def _legs(page: Page) -> list[tuple[int, str]]:
    return [(leg["season"], leg["family"]) for leg in _model(page)["legs"]]


def _visible(page: Page, selector: str) -> bool:
    return bool(page.locator(selector).is_visible())


def _tooltip_text(page: Page) -> str | None:
    text: str | None = page.evaluate(
        """() => { const el = document.getElementById('chart-tooltip');
          return el && !el.hidden ? el.textContent : null; }"""
    )
    return text


def _tooltip_lines(page: Page) -> list[str]:
    lines: list[str] = page.evaluate(
        "() => [...document.querySelectorAll('#chart-tooltip > *')].map((n) => n.textContent)"
    )
    return lines


def _venue_pixel(page: Page, x: float, y: float) -> tuple[float, float]:
    px, py = page.evaluate(
        """([x, y]) => {
          const gd = document.getElementById('map-chart');
          const r = gd.getBoundingClientRect();
          const fl = gd._fullLayout;
          return [r.left + fl.xaxis._offset + fl.xaxis.l2p(x),
                  r.top + fl.yaxis._offset + fl.yaxis.l2p(y)];
        }""",
        [x, y],
    )
    return px, py


def _dot_point(page: Page, family: str, i_text: str) -> tuple[float, float]:
    """Plot coordinates of the first active dot in `dots:<family>` (any index if unknown)."""
    pts: list[list[float]] = page.evaluate(
        """(name) => { const t = document.getElementById('map-chart').data
            .find((d) => d.name === name); return t.x.map((x, i) => [x, t.y[i]]); }""",
        f"dots:{family}",
    )
    assert pts, i_text
    return pts[0][0], pts[0][1]


def test_map_view_shows_panel_hides_others_with_26_traces(
    guarded_page: Page, open_app: OpenApp
) -> None:
    """D-06: `?view=map` shows #map-panel, hides #chart and #bars-panel; 26 traces."""
    _open_map(guarded_page, open_app, "?view=map")
    assert _visible(guarded_page, "#map-panel")
    assert not _visible(guarded_page, "#chart")
    assert not _visible(guarded_page, "#bars-panel")
    assert list(_traces(guarded_page)) == _TRACE_NAMES
    assert len(_TRACE_NAMES) == 26


def test_no_subject_draws_dots_only_with_tab_hint(guarded_page: Page, open_app: OpenApp) -> None:
    """D-02: no subject draws no legs; only the tab hint shows, nothing over the map."""
    _open_map(guarded_page, open_app, "?view=map")
    traces = _traces(guarded_page)
    assert all(traces[f"legs:{f}"]["n"] == 0 for f in _FAMILIES)
    assert _model(guarded_page)["legs"] == []
    assert sum(traces[f"dots:{f}"]["n"] for f in _FAMILIES) > 0
    assert guarded_page.locator("#map-hint").count() == 0
    assert guarded_page.locator("#tab-hint").text_content() == MAP_HINT


def test_person_paths_split_by_season_and_colored_by_destination(
    guarded_page: Page, open_app: OpenApp
) -> None:
    """D-01/D-03/D-04/D-14: Pat Rowan's three legs, none across seasons, destination colors."""
    _open_map(guarded_page, open_app, "?view=map&people=pat-rowan")
    model = _model(guarded_page)
    assert _legs(guarded_page) == [(2021, "disney"), (2021, "fox"), (2026, "disney")]
    assert all(leg["pointCount"] >= 2 for leg in model["legs"])
    inset: dict[str, float] = guarded_page.evaluate(
        "async () => (await import('./modules/map-model.js')).HAWAII_INSET"
    )
    first = model["legs"][0]["first"]
    assert inset["x0"] <= first["x"] <= inset["x1"]
    assert inset["y0"] <= first["y"] <= inset["y1"]
    light_disney: str = guarded_page.evaluate(
        "async () => (await import('./modules/palette.js')).FAMILY_COLORS.light.disney"
    )
    assert _traces(guarded_page)["legs:disney"]["color"] == light_disney
    assert guarded_page.locator("#map-hint").count() == 0


def test_school_path_starts_at_the_dublin_anchor(guarded_page: Page, open_app: OpenApp) -> None:
    """D-01/D-15: Boulder Pass traces one 2025 leg of family other from the Dublin anchor."""
    _open_map(guarded_page, open_app, "?view=map&school=boulder-pass")
    model = _model(guarded_page)
    assert _legs(guarded_page) == [(2025, "other")]
    first = model["legs"][0]["first"]
    assert (round(first["x"]), round(first["y"])) == (955, 30)
    assert model["subjects"][0]["kind"] == "school"


def test_network_filter_skips_instead_of_cutting(guarded_page: Page, open_app: OpenApp) -> None:
    """D-12: excluding the Nassau game's network joins Honolulu straight to Atlanta."""
    _open_map(guarded_page, open_app, "?view=map&people=pat-rowan&seasons=2021-2021")
    assert _legs(guarded_page) == [(2021, "disney"), (2021, "fox")]
    _set(guarded_page, {"networks": _ALL_BUT_NET_E})
    model = _model(guarded_page)
    assert _legs(guarded_page) == [(2021, "fox")]
    leg = model["legs"][0]
    # Honolulu (Hawaii inset) straight to Atlanta, not to Nassau.
    assert leg["first"]["x"] < 340
    assert round(leg["last"]["x"]) == 715
    assert round(leg["last"]["y"]) == 405


def test_fade_keeps_excluded_venues_hide_removes_them_legs_unchanged(
    guarded_page: Page, open_app: OpenApp
) -> None:
    """D-12: Fade keeps excluded venues faint, Hide removes them, legs stay identical."""
    _open_map(guarded_page, open_app, "?view=map&people=pat-rowan&seasons=2021-2021")
    fade_legs = _legs(guarded_page)
    traces = _traces(guarded_page)
    assert sum(traces[f"inert:{f}"]["n"] for f in _FAMILIES) > 0
    assert {season for season, _ in fade_legs} == {2021}
    _set(guarded_page, {"dots": "hide"})
    hidden = _traces(guarded_page)
    assert all(hidden[f"inert:{f}"]["n"] == 0 for f in _FAMILIES)
    assert _legs(guarded_page) == fade_legs


def test_no_location_note_follows_the_filters(guarded_page: Page, open_app: OpenApp) -> None:
    """D-16: the unlocated game's note shows, and hides when that game is filtered out."""
    _open_map(guarded_page, open_app, "?view=map")
    assert _visible(guarded_page, "#map-note")
    assert guarded_page.locator("#map-note").text_content() == "1 game has no venue location"
    _open_map(guarded_page, open_app, "?view=map&seasons=2019-2019&dots=hide")
    assert not _visible(guarded_page, "#map-note")


def test_desktop_hover_shows_venue_tooltip(guarded_page: Page, open_app: OpenApp) -> None:
    """D-11: hovering the Nassau dot shows title, family counts and the subject's games."""
    guarded_page.set_viewport_size({"width": 1280, "height": 900})
    _open_map(guarded_page, open_app, "?view=map&people=pat-rowan")
    nassau = next(m for m in _model(guarded_page)["markers"] if m["label"] == "Nassau")
    px, py = _venue_pixel(guarded_page, nassau["x"], nassau["y"])
    guarded_page.mouse.move(px - 80, py - 80)
    guarded_page.mouse.move(px, py, steps=5)
    guarded_page.wait_for_function(
        "() => { const e = document.getElementById('chart-tooltip'); return !!e && !e.hidden; }"
    )
    lines = _tooltip_lines(guarded_page)
    assert lines[0] == "Island Stadium · Nassau, Bahamas"
    assert "ABC/ESPN" in lines[1]
    assert "── Pat Rowan here ──" in lines
    assert any(line.startswith("2021-12-18  Ironpeak vs Foxhollow") for line in lines)
    assert "viewers" not in (_tooltip_text(guarded_page) or "").lower()


def test_faded_dot_shows_no_tooltip(guarded_page: Page, open_app: OpenApp) -> None:
    """D-11: a faded (inert) dot shows nothing on hover."""
    guarded_page.set_viewport_size({"width": 1280, "height": 900})
    _open_map(guarded_page, open_app, "?view=map&school=boulder-pass")
    inert: dict[str, Any] = _traces(guarded_page)["inert:disney"]
    assert inert["n"] > 0
    px, py = _venue_pixel(guarded_page, inert["mx"][0], inert["my"][0])
    guarded_page.mouse.move(px - 60, py - 60)
    guarded_page.mouse.move(px, py, steps=5)
    guarded_page.wait_for_timeout(300)
    assert _tooltip_text(guarded_page) is None


def test_edge_markers_are_labelled_at_their_anchors(guarded_page: Page, open_app: OpenApp) -> None:
    """D-15: the markers trace holds 'Dublin' at (955, 30) and 'Nassau' at its projected point."""
    _open_map(guarded_page, open_app, "?view=map")
    markers = _traces(guarded_page)["markers"]
    assert markers["text"] == ["Dublin", "Nassau"]
    assert (markers["mx"][0], markers["my"][0]) == (955, 30)
    nassau = next(m for m in _model(guarded_page)["markers"] if m["label"] == "Nassau")
    assert (markers["mx"][1], markers["my"][1]) == (nassau["x"], nassau["y"])
    assert 0 < nassau["x"] < 975 and 0 < nassau["y"] < 610


def test_two_people_compare_shapes_and_legend(guarded_page: Page, open_app: OpenApp) -> None:
    """D-05: two announcers get circle and square symbols and a two-item shape legend."""
    _open_map(guarded_page, open_app, "?view=map&people=pat-rowan,kris-venn")
    symbols = [s["symbol"] for s in _model(guarded_page)["subjects"]]
    assert symbols == ["circle", "square"]
    assert _visible(guarded_page, "#shape-legend")
    assert guarded_page.locator("#shape-legend li").count() == 2


def test_shared_booth_star_and_legend_item(guarded_page: Page, open_app: OpenApp) -> None:
    """D-05: a game two picked announcers called is a star, with a 'Shared booth' item."""
    _open_map(guarded_page, open_app, "?view=map&people=pat-rowan,sam-delgado")
    model = _model(guarded_page)
    assert model["hasShared"] is True
    traces = _traces(guarded_page)
    stars = sum(
        1 for f in _FAMILIES for sym in (traces[f"dots:{f}"]["symbols"] or []) if sym == "star"
    )
    assert stars > 0
    labels = guarded_page.locator("#shape-legend li").all_text_contents()
    assert any("Shared booth" in label for label in labels)


def test_more_than_four_schools_shows_the_shapes_caption(
    guarded_page: Page, open_app: OpenApp
) -> None:
    """D-05: beyond four schools the legend carries the first-4 caption."""
    schools = "northfield,lakeview,ironpeak,foxhollow,boulder-pass"
    _open_map(guarded_page, open_app, f"?view=map&school={schools}")
    assert _model(guarded_page)["shapesCapped"] is True
    assert "Shapes shown for the first 4 schools" in (
        guarded_page.locator("#shape-legend").text_content() or ""
    )


def test_trace_names_are_constant_across_states(guarded_page: Page, open_app: OpenApp) -> None:
    """D-06: the 26 trace names never change with subject, filters or Hide."""
    _open_map(guarded_page, open_app, "?view=map")
    seen = [list(_traces(guarded_page))]
    for patch in (
        {"people": ["pat-rowan"]},
        {"people": [], "school": ["boulder-pass"]},
        {"school": [], "dots": "hide"},
        {"dots": "fade", "seasons": [2021, 2021]},
    ):
        _set(guarded_page, patch)
        seen.append(list(_traces(guarded_page)))
    assert all(names == _TRACE_NAMES for names in seen)


def test_map_url_survives_setstate_and_reload(guarded_page: Page, open_app: OpenApp) -> None:
    """D-06: `?view=map&people=pat-rowan` survives a setState and a reload."""
    _open_map(guarded_page, open_app, "?view=map&people=pat-rowan")
    _set(guarded_page, {"seasons": [2021, 2026]})
    search: str = guarded_page.evaluate("() => location.search")
    assert "view=map" in search
    assert "people=pat-rowan" in search
    guarded_page.reload()
    guarded_page.wait_for_function("() => window.__testHooks.ready === true")
    guarded_page.wait_for_function("() => window.__testHooks.mapRenders >= 1")
    assert _visible(guarded_page, "#map-panel")
    state: dict[str, Any] = guarded_page.evaluate("() => window.__testHooks.getState()")
    assert state["view"] == "map"
    assert state["people"] == ["pat-rowan"]


def test_dark_theme_uses_dark_land_and_family_colors(guarded_page: Page, open_app: OpenApp) -> None:
    """D-08: dark scheme draws the outline in MAP_LAND dark and legs in FAMILY_COLORS dark."""
    guarded_page.emulate_media(color_scheme="dark")
    _open_map(guarded_page, open_app, "?view=map&people=pat-rowan")
    palette: dict[str, Any] = guarded_page.evaluate(
        """async () => { const P = await import('./modules/palette.js');
          return {land: P.MAP_LAND.dark, disney: P.FAMILY_COLORS.dark.disney,
                  fox: P.FAMILY_COLORS.dark.fox}; }"""
    )
    traces = _traces(guarded_page)
    assert palette["land"] == "#1B1E23"
    assert traces["outline"]["fill"] == palette["land"]
    assert traces["legs:disney"]["color"] == palette["disney"]
    assert traces["legs:fox"]["color"] == palette["fox"]


def test_every_game_hidden_shows_the_empty_note(guarded_page: Page, open_app: OpenApp) -> None:
    """D-09: with every game hidden the empty note replaces the figure's message."""
    _open_map(guarded_page, open_app, "?view=map&networks=none&dots=hide")
    note = guarded_page.locator("#map-empty-note")
    assert note.is_visible()
    assert "No games match these filters." in (note.text_content() or "")


def test_geometry_failure_shows_error_and_table_still_renders(
    guarded_page: Page, open_app: OpenApp
) -> None:
    """D-08/T-04.18-40: a failed geometry import shows the error note; the table renders."""
    guarded_page.route(
        "**/vendor/us-states-albers.js*", lambda route: route.fulfill(status=500, body="")
    )
    open_app(guarded_page, "?view=map&people=pat-rowan")
    guarded_page.wait_for_function("() => !document.getElementById('map-empty-note').hidden")
    note = guarded_page.locator("#map-empty-note")
    assert "The map could not be drawn." in (note.text_content() or "")
    assert guarded_page.locator("#games-table tbody tr").count() > 0


def test_desktop_drag_zoom_and_double_click_reset(guarded_page: Page, open_app: OpenApp) -> None:
    """D-07: desktop keeps drag-zoom and a modebar; a double-click restores the full extent."""
    guarded_page.set_viewport_size({"width": 1280, "height": 900})
    _open_map(guarded_page, open_app, "?view=map&people=pat-rowan")
    layout: dict[str, Any] = guarded_page.evaluate(
        "() => ({drag: document.getElementById('map-chart').layout.dragmode})"
    )
    assert layout["drag"] == "zoom"
    assert guarded_page.locator("#map-chart .modebar").is_visible()
    x0, y0 = _venue_pixel(guarded_page, 300, 200)
    x1, y1 = _venue_pixel(guarded_page, 600, 400)
    guarded_page.mouse.move(x0, y0)
    guarded_page.mouse.down()
    guarded_page.mouse.move(x1, y1, steps=8)
    guarded_page.mouse.up()
    guarded_page.wait_for_timeout(300)
    zoomed: list[float] = guarded_page.evaluate(
        "() => document.getElementById('map-chart')._fullLayout.xaxis.range"
    )
    assert zoomed[1] - zoomed[0] < 600
    cx, cy = _venue_pixel(guarded_page, (zoomed[0] + zoomed[1]) / 2, 300)
    guarded_page.mouse.dblclick(cx, cy)
    guarded_page.wait_for_timeout(400)
    rng: list[float] = guarded_page.evaluate(
        "() => document.getElementById('map-chart')._fullLayout.xaxis.range"
    )
    assert abs(rng[0]) <= 0.5
    assert abs(rng[1] - 975) <= 0.5


def _phone(page: Page, open_app: OpenApp, query: str) -> None:
    page.set_viewport_size({"width": 360, "height": 800})
    _open_map(page, open_app, query)


def test_phone_map_is_fixed_and_has_no_overflow(mobile_page: Page, open_app: OpenApp) -> None:
    """D-07/SITE-75: on a 360px phone the map is fixed, has no modebar, and the page fits."""
    _phone(mobile_page, open_app, "?view=map&people=pat-rowan")
    fixed: dict[str, Any] = mobile_page.evaluate(
        """() => { const l = document.getElementById('map-chart').layout;
          return {drag: l.dragmode, x: l.xaxis.fixedrange, y: l.yaxis.fixedrange}; }"""
    )
    assert fixed == {"drag": False, "x": True, "y": True}
    assert not mobile_page.locator("#map-chart .modebar").is_visible()
    width: int = mobile_page.evaluate("() => document.documentElement.scrollWidth")
    assert width <= 360


def test_phone_wheel_over_map_scrolls_the_page(mobile_page: Page, open_app: OpenApp) -> None:
    """D-07/SITE-75: a wheel over the fixed map scrolls the page."""
    _phone(mobile_page, open_app, "?view=map&people=pat-rowan")
    box = mobile_page.locator("#map-chart").bounding_box()
    assert box is not None
    mobile_page.mouse.move(box["x"] + box["width"] / 2, min(box["y"] + 100, 700))
    before: float = mobile_page.evaluate("() => window.scrollY")
    mobile_page.mouse.wheel(0, 300)
    mobile_page.wait_for_timeout(400)
    after: float = mobile_page.evaluate("() => window.scrollY")
    assert after > before


def test_phone_tap_shows_then_hides_tooltip(mobile_page: Page, open_app: OpenApp) -> None:
    """D-07/D-11: a first tap shows the tooltip, a second hides it, a tap elsewhere hides it."""
    _phone(mobile_page, open_app, "?view=map&people=pat-rowan")
    mobile_page.evaluate("() => document.getElementById('map-chart').scrollIntoView()")
    x, y = _dot_point(mobile_page, "disney", "disney dot")
    px, py = _venue_pixel(mobile_page, x, y)
    mobile_page.touchscreen.tap(px, py)
    mobile_page.wait_for_function(
        "() => { const e = document.getElementById('chart-tooltip'); return e && !e.hidden; }"
    )
    assert _tooltip_text(mobile_page)
    mobile_page.wait_for_timeout(450)
    mobile_page.touchscreen.tap(px, py)
    mobile_page.wait_for_function("() => document.getElementById('chart-tooltip').hidden")
    mobile_page.wait_for_timeout(450)
    mobile_page.touchscreen.tap(px, py)
    mobile_page.wait_for_function("() => !document.getElementById('chart-tooltip').hidden")
    mobile_page.wait_for_timeout(450)
    mobile_page.evaluate("() => window.scrollTo(0, 0)")
    mobile_page.touchscreen.tap(5, 5)
    mobile_page.wait_for_function("() => document.getElementById('chart-tooltip').hidden")


def test_phone_plot_is_centered_in_a_520px_panel(mobile_page: Page, open_app: OpenApp) -> None:
    """D-09: the plot's top and bottom gaps match and the map panel is 520px tall."""
    _phone(mobile_page, open_app, "?view=map&people=pat-rowan")
    box: dict[str, float] = mobile_page.evaluate(
        """() => { const gd = document.getElementById('map-chart');
          const fl = gd._fullLayout; const r = gd.getBoundingClientRect();
          return {above: fl.yaxis._offset,
                  below: r.height - fl.yaxis._offset - fl.yaxis._length,
                  panel: document.getElementById('map-panel').getBoundingClientRect().height}; }"""
    )
    assert abs(box["above"] - box["below"]) <= 2
    assert box["panel"] == 520
