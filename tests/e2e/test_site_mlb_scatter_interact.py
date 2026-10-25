"""16-08: MLB Scatter interaction (D-05, D-07): selection fade and outline, tab carry, legend chips,
hover tooltip and ring, click and touch to the panel, Reset zoom, escaping.

Runs on the densified synthetic MLB fixture; no vault data is used.
"""

# ruff: noqa: E501
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from mlb_scatter_fixture import CONTROLS, ESCAPE_NAME, SCATTER_CASE, densify_scatter
from playwright.sync_api import Page, Route
from test_site_mlb_scatter import (
    _G,
    GD,
    HOOKS,
    VIEW,
    _in_control,
    _open,
    _plot,
    _points,
    _status,
    _vm,
)

pytestmark = pytest.mark.e2e

INK_LIGHT = "#23201B"
FADED = 0.32
LEGEND = "#mlb-view-scatter .legend-chips"

_DOT_JS = """
([selector, game]) => {
  const gd = document.querySelector(selector);
  const f = gd._fullLayout;
  const rect = gd.getBoundingClientRect();
  for (const t of gd.data) {
    const k = t.customdata.indexOf(game);
    if (k === -1) continue;
    const ya = f[t.yaxis === 'y2' ? 'yaxis2' : 'yaxis'];
    return { x: rect.left + f.xaxis._offset + f.xaxis.l2p(t.x[k]), y: rect.top + ya._offset + ya.l2p(ya.d2l(t.y[k])) };
  }
  return null;
}
"""


def _opacity(plot: dict[str, Any]) -> dict[int, float]:
    out: dict[int, float] = {}
    for t in plot["data"]:
        for k, i in enumerate(t["customdata"]):
            op = t["marker"]["opacity"]
            out[i] = op[k] if isinstance(op, list) else op
    return out


def _dot(page: Page, game: int) -> dict[str, float]:
    page.locator(GD).scroll_into_view_if_needed()
    pt = page.evaluate(_DOT_JS, [GD, game])
    assert pt is not None
    return pt  # type: ignore[no-any-return]


def _hover(page: Page, game: int) -> None:
    shown = (
        "(() => { const t = document.getElementById('chart-tooltip'); return !!t && !t.hidden; })()"
    )
    for _ in range(3):
        pt = _dot(page, game)
        page.mouse.move(pt["x"] - 40, pt["y"] - 40)
        page.mouse.move(pt["x"], pt["y"], steps=6)
        try:
            page.wait_for_function(shown, timeout=3000)
            return
        except Exception:
            page.wait_for_timeout(300)
    page.wait_for_function(shown)


def _tooltip(page: Page) -> list[str]:
    return page.evaluate(  # type: ignore[no-any-return]
        "Array.from(document.getElementById('chart-tooltip').children).map(c => c.textContent)"
    )


def test_no_selection_every_dot_is_full_strength(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    page = mlb_guarded_page
    _open(page, open_mlb_app)
    plot = _plot(page)
    assert set(_opacity(plot).values()) == {1}
    assert _vm(page)["counts"]["faded"] == 0
    for p in _points(plot):
        assert p["line_w"] in (0, 1.5)
        if p["line_w"] == 1.5:
            assert p["line_c"] == p["color"] or _G["scope"][p["i"]] == "window"


def test_booth_pick_carries_to_scatter_and_fades_the_rest(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    page = mlb_guarded_page
    _open(page, open_mlb_app, "&booth=p2")
    assert page.evaluate(f"{HOOKS}.getState().booth") == "1"
    rows = page.evaluate(f"{HOOKS}.getTableIndexes()")
    plot = _plot(page)
    op = _opacity(plot)
    matched = {i for i, v in op.items() if v == 1}
    assert matched == set(rows) & set(op)
    assert {i for i, v in op.items() if v == FADED} == set(op) - matched
    counts = _vm(page)["counts"]
    assert counts["matched"] == len(rows) and counts["faded"] == counts["total"] - len(rows)
    for p in _points(plot):
        if p["i"] in matched:
            assert p["line_w"] == 1.5 and p["line_c"].upper() == INK_LIGHT
        else:
            assert p["line_c"].upper() != INK_LIGHT


def test_tab_switch_keeps_booth_and_postseason_drops_it(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    page = mlb_guarded_page
    open_mlb_app(page, "?sport=mlb&booth=p2")
    page.route("**/mlb-data.json", lambda r: r.continue_())
    rows_before = page.evaluate(f"{HOOKS}.getTableIndexes()")
    page.click("#mlb-tab-scatter")
    page.wait_for_function(f"{HOOKS}.getViewModel('scatter').drawn === true")
    assert page.evaluate(f"{HOOKS}.getState().booth") == "1"
    assert page.evaluate(f"{HOOKS}.getTableIndexes()") == rows_before
    assert _vm(page)["counts"]["faded"] > 0
    page.click("#mlb-tab-apple")
    assert page.evaluate(f"{HOOKS}.getState().booth") == "1"
    page.click("#mlb-tab-scatter")
    page.click("#mlb-tab-postseason")
    assert page.evaluate(f"{HOOKS}.getState().booth") is None


@pytest.mark.parametrize("cell", ["season-2019", "2019-lcs-NL"])
def test_cell_and_season_picks_fade(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None], cell: str
) -> None:
    page = mlb_guarded_page
    _open(page, open_mlb_app, f"&cell={cell}")
    rows = set(page.evaluate(f"{HOOKS}.getTableIndexes()"))
    assert rows
    op = _opacity(_plot(page))
    assert {i for i, v in op.items() if v == 1} == rows & set(op)
    assert {i for i, v in op.items() if v == FADED} == set(op) - rows


def test_open_game_highlights_itself_only_without_other_selection(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    page = mlb_guarded_page
    _open(page, open_mlb_app)
    page.evaluate(f"{HOOKS}.openGame(1)")
    page.wait_for_function(f"{HOOKS}.getViewModel('scatter').counts.matched === 1")
    op = _opacity(_plot(page))
    assert op[1] == 1 and all(v == FADED for i, v in op.items() if i != 1)
    page.evaluate(f"{HOOKS}.closePanel()")
    page.wait_for_function(f"{HOOKS}.getViewModel('scatter').counts.faded === 0")


def test_chips_show_present_families_toggle_and_isolate(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    page = mlb_guarded_page
    _open(page, open_mlb_app)
    labels = page.eval_on_selector_all(f"{LEGEND} button", "els => els.map(e => e.textContent)")
    assert labels == ["Apple TV", "FOX/FS1", "TBS", "ESPN/ABC"]
    assert page.locator("#mlb-view-scatter").get_by_text("Fade", exact=True).count() == 0
    before = _vm(page)["counts"]
    page.click(f"{LEGEND} button[data-family='fox']")
    page.wait_for_function(
        "document.querySelector('#mlb-view-scatter .js-plotly-plot').data.every(t => t.meta !== 'fox')"
    )
    assert _vm(page)["counts"] == before
    assert (
        page.locator(f"{LEGEND} button[data-family='fox']").get_attribute("aria-pressed") == "false"
    )
    # F4: the counts keep the hidden family, and the status line says how many it hides.
    drawn = sum(1 for t in _plot(page)["data"] for _ in t["customdata"])
    hidden = before["total"] - drawn
    status = page.inner_text("#mlb-view-scatter p.mlb-scatter-status")
    assert hidden > 0
    assert status.endswith(f" {hidden} hidden by the legend.")
    page.click(f"{LEGEND} button[data-family='fox']")
    page.wait_for_function(
        "document.querySelector('#mlb-view-scatter .js-plotly-plot').data.some(t => t.meta === 'fox')"
    )
    page.locator(f"{LEGEND} button[data-family='tbs']").dblclick()
    page.wait_for_function(
        "(() => { const m = new Set(document.querySelector('#mlb-view-scatter .js-plotly-plot').data.map(t => t.meta)); return m.size === 1 && m.has('tbs'); })()"
    )
    page.locator(f"{LEGEND} button[data-family='tbs']").dblclick()
    page.wait_for_function(
        "new Set(document.querySelector('#mlb-view-scatter .js-plotly-plot').data.map(t => t.meta)).size === 4"
    )


def test_hover_tooltip_ring_and_variants(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    page = mlb_guarded_page
    page.set_viewport_size({"width": 1440, "height": 900})
    _open(page, open_mlb_app)
    page.wait_for_timeout(300)
    # Game 1: rated and with excitement.
    _hover(page, 1)
    lines = _tooltip(page)
    assert page.locator("#chart-tooltip .tooltip-networks").count() == 1
    assert " at " in lines[1] and "Apr 10, 2026" in lines[1] and "·" in lines[1]
    assert lines[2] == "2MM viewers · Excitement 0.5"
    ring = page.evaluate(
        "(() => { const r = document.getElementById('chart-hover-ring').getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; })()"
    )
    dot = _dot(page, 1)
    assert abs(ring["x"] - dot["x"]) <= 1 and abs(ring["y"] - dot["y"]) <= 1
    page.mouse.move(5, 5)
    page.wait_for_function("document.getElementById('chart-tooltip').hidden")
    cases = {
        10: "5.5MM viewers, whole window · Excitement 1.1",
        6: "No public rating · Excitement 1.2",
        4: "1.1MM viewers · Excitement pending Retrosheet 2026",
        8: "3MM viewers · Excitement not available",
    }
    for game, text in cases.items():
        _hover(page, game)
        assert _tooltip(page)[2] == text, game
        page.mouse.move(5, 5)
        page.wait_for_function("document.getElementById('chart-tooltip').hidden")


def test_click_opens_the_panel_and_escape_returns_focus(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    page = mlb_guarded_page
    page.set_viewport_size({"width": 1440, "height": 900})
    _open(page, open_mlb_app)
    page.wait_for_timeout(300)
    pt = _dot(page, 1)
    page.mouse.click(pt["x"], pt["y"])
    page.wait_for_function(f"{HOOKS}.getState().game === 1")
    assert page.evaluate(f"{HOOKS}.getState().booth") is None
    assert page.evaluate(f"{HOOKS}.getState().selection") is None
    page.keyboard.press("Escape")
    page.wait_for_function(f"{HOOKS}.getState().game === null")
    assert page.evaluate("document.activeElement.closest('#mlb-view-scatter') !== null")


def test_booth_picked_dot_escape_returns_focus_to_the_chart(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    """F2: with a booth picked the game is also in Matched games; focus still returns to the chart."""
    page = mlb_guarded_page
    page.set_viewport_size({"width": 1440, "height": 900})
    _open(page, open_mlb_app, "&booth=p2")
    page.wait_for_timeout(300)
    game = page.evaluate(f"{HOOKS}.getTableIndexes()")[0]
    pt = _dot(page, game)
    page.mouse.click(pt["x"], pt["y"])
    page.wait_for_function(f"{HOOKS}.getState().game === {game}")
    assert page.locator(f"#mlb-matched-games .nfl-matchup-btn[data-game='{game}']").count() == 1
    page.keyboard.press("Escape")
    page.wait_for_function(f"{HOOKS}.getState().game === null")
    assert page.evaluate("document.activeElement.closest('#mlb-view-scatter') !== null")


def test_touch_first_tap_tooltip_second_tap_opens(
    mlb_mobile_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    page = mlb_mobile_page
    _open(page, open_mlb_app)
    page.wait_for_timeout(300)
    pt = _dot(page, 1)
    page.touchscreen.tap(pt["x"], pt["y"])
    page.wait_for_function("!document.getElementById('chart-tooltip').hidden")
    assert page.evaluate(f"{HOOKS}.getState().game") is None
    assert page.locator("#chart-tooltip .tooltip-hint").count() == 1
    page.wait_for_timeout(600)
    page.touchscreen.tap(pt["x"], pt["y"])
    page.wait_for_function(f"{HOOKS}.getState().game === 1")
    page.evaluate(f"{HOOKS}.closePanel()")
    page.wait_for_timeout(600)
    pt = _dot(page, 1)
    page.touchscreen.tap(pt["x"], pt["y"])
    page.wait_for_function("!document.getElementById('chart-tooltip').hidden")
    page.touchscreen.tap(8, 8)
    page.wait_for_function("document.getElementById('chart-tooltip').hidden")


def test_reset_zoom_disabled_at_home_enabled_after_zoom(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    page = mlb_guarded_page
    page.set_viewport_size({"width": 1440, "height": 900})
    _open(page, open_mlb_app)
    page.wait_for_timeout(400)
    btn = '#mlb-chart-tools [data-tools-for="scatter"] .reset-zoom'
    assert page.get_attribute(btn, "aria-disabled") == "true"
    info = page.evaluate(
        "sel => { const gd = document.querySelector(sel); const r = gd.getBoundingClientRect(); const f = gd._fullLayout; return { l: r.left, t: r.top, size: f._size, yr: [...f.yaxis.range] }; }",
        GD,
    )
    s = info["size"]
    x = info["l"] + s["l"] + s["w"] * 0.5
    y0 = info["t"] + s["t"] + s["h"] * 0.16
    y1 = info["t"] + s["t"] + s["h"] * 0.6
    page.mouse.move(x, y0)
    page.mouse.down()
    page.mouse.move(x + 30, (y0 + y1) / 2, steps=5)
    page.mouse.move(x + 60, y1, steps=5)
    page.mouse.up()
    page.wait_for_function(
        "sel => document.querySelector(sel).getAttribute('aria-disabled') === 'false'", arg=btn
    )
    page.click(btn)
    page.wait_for_function(
        "sel => document.querySelector(sel).getAttribute('aria-disabled') === 'true'", arg=btn
    )
    yr = page.evaluate("sel => [...document.querySelector(sel)._fullLayout.yaxis.range]", GD)
    assert yr == info["yr"]


def test_zoom_survives_rerenders_and_control_changes(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    """F3: a dot click, panel close, chip toggle or same-width re-render keeps the viewers zoom.

    U5: the Season type / Round control only fades dots and the axes come from every game, so
    the home range no longer depends on it: a control change keeps the zoom too, and Reset zoom
    still returns to the one home range."""
    page = mlb_guarded_page
    page.set_viewport_size({"width": 1440, "height": 900})
    _open(page, open_mlb_app)
    page.wait_for_timeout(400)
    btn = '#mlb-chart-tools [data-tools-for="scatter"] .reset-zoom'
    yr = "sel => [...document.querySelector(sel)._fullLayout.yaxis.range]"
    home = page.evaluate(yr, GD)
    zoom = [home[0] + (home[1] - home[0]) * 0.2, home[1] - (home[1] - home[0]) * 0.3]
    page.evaluate(
        "([sel, r]) => window.Plotly.relayout(document.querySelector(sel), {'yaxis.range': r})",
        [GD, zoom],
    )
    page.wait_for_function(
        "sel => document.querySelector(sel).getAttribute('aria-disabled') === 'false'", arg=btn
    )

    def kept(step: str) -> None:
        page.wait_for_timeout(300)
        assert page.evaluate(yr, GD) == pytest.approx(zoom), step
        assert page.get_attribute(btn, "aria-disabled") == "false", step

    # A dot in the bottom strip (no rating) stays on screen whatever the viewers zoom.
    game = next(
        i
        for i in range(len(_G["viewers"]))
        if _G["viewers"][i] is None and _G["wp_excitement"][i] is not None
    )
    pt = _dot(page, game)
    page.mouse.click(pt["x"], pt["y"])
    page.wait_for_function(f"{HOOKS}.getState().game === {game}")
    kept("dot click")
    page.keyboard.press("Escape")
    page.wait_for_function(f"{HOOKS}.getState().game === null")
    kept("panel close")
    page.locator(f"{LEGEND} button[data-family]").first.click()
    page.wait_for_timeout(600)  # past the double-click window
    kept("chip toggle")
    page.evaluate(f"{HOOKS}.setState({{}})")
    kept("same-width re-render")
    page.click(btn)
    page.wait_for_function(
        "sel => document.querySelector(sel).getAttribute('aria-disabled') === 'true'", arg=btn
    )
    assert page.evaluate(yr, GD) == home
    # A control change keeps the zoom, and Reset zoom still goes to the same home range.
    page.evaluate(
        "([sel, r]) => window.Plotly.relayout(document.querySelector(sel), {'yaxis.range': r})",
        [GD, zoom],
    )
    page.wait_for_function(
        "sel => document.querySelector(sel).getAttribute('aria-disabled') === 'false'", arg=btn
    )
    page.evaluate(f"{HOOKS}.setState({{ stype: 'reg' }})")
    kept("season type")
    page.evaluate(f"{HOOKS}.setState({{ stype: 'post', sround: 'lcs' }})")
    kept("round")
    page.click(btn)
    page.wait_for_function(
        "sel => document.querySelector(sel).getAttribute('aria-disabled') === 'true'", arg=btn
    )
    assert page.evaluate(yr, GD) == home


def test_tooltip_text_is_escaped(mlb_guarded_page: Page, open_mlb_app: Callable[..., None]) -> None:
    page = mlb_guarded_page
    page.set_viewport_size({"width": 1440, "height": 900})

    def handler(route: Route) -> None:
        resp = route.fetch()
        data = densify_scatter(json.loads(resp.text()))
        data["lookups"]["clubs"][2]["name"] = ESCAPE_NAME
        for t in data["lookups"]["team_names"]:
            if t["club"] == 2:
                t["name"] = ESCAPE_NAME
        route.fulfill(response=resp, body=json.dumps(data))

    page.route("**/mlb-data.json", handler)
    open_mlb_app(page, "?sport=mlb&view=scatter")
    page.wait_for_function(f"{HOOKS}.getViewModel('scatter').drawn === true")
    page.wait_for_timeout(300)
    _hover(page, 1)
    assert ESCAPE_NAME in _tooltip(page)[1]
    assert page.locator("#chart-tooltip b").count() == 0


def test_legend_chip_keyboard_toggle_keeps_focus(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    """F20: Space on a chip re-renders the legend; focus moves to the same family's new chip."""
    page = mlb_guarded_page
    _open(page, open_mlb_app)
    chip = f"{LEGEND} button[data-family='fox']"
    page.focus(chip)
    page.keyboard.press("Space")
    page.wait_for_function(
        "sel => document.querySelector(sel).getAttribute('aria-pressed') === 'false'", arg=chip
    )
    page.wait_for_timeout(600)  # past the double-click window
    assert page.evaluate("document.activeElement.dataset.family") == "fox"
    page.keyboard.press("Space")
    page.wait_for_function(
        "sel => document.querySelector(sel).getAttribute('aria-pressed') === 'true'", arg=chip
    )
    assert page.evaluate("document.activeElement.dataset.family") == "fox"


def test_tooltip_pending_follows_retrosheet_freshness(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    """F21: once Retrosheet reaches 2026, a 2026 game with no play-by-play is not 'pending'."""
    page = mlb_guarded_page
    page.set_viewport_size({"width": 1440, "height": 900})

    def handler(route: Route) -> None:
        resp = route.fetch()
        data = densify_scatter(json.loads(resp.text()))
        data["freshness"]["retrosheet_through_season"] = 2026
        data["games"]["lineup_status"][4] = "missing"
        route.fulfill(response=resp, body=json.dumps(data))

    page.route("**/mlb-data.json", handler)
    open_mlb_app(page, "?sport=mlb&view=scatter")
    page.wait_for_function(f"{HOOKS}.getViewModel('scatter').drawn === true")
    page.wait_for_timeout(300)
    _hover(page, 4)
    assert _tooltip(page)[2] == "1.1MM viewers · Excitement not available"


@pytest.mark.parametrize("name", ["post", "post+lcs", "reg"])
def test_control_highlights_and_fades_without_removing_or_rescaling(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None], name: str
) -> None:
    """U5: every game stays plotted; games outside the control fade; axes and chips hold."""
    page = mlb_guarded_page
    page.set_viewport_size({"width": 1440, "height": 900})
    _open(page, open_mlb_app)
    page.wait_for_timeout(300)
    layout = lambda: page.evaluate(  # noqa: E731
        "sel => { const l = document.querySelector(sel)._fullLayout;"
        " return [l.xaxis.range, l.yaxis.range]; }",
        GD,
    )
    before = layout()
    chips = page.eval_on_selector_all(f"{LEGEND} button", "els => els.map(e => e.dataset.family)")
    stype, sround = CONTROLS[name]
    page.evaluate(f"{HOOKS}.setState({json.dumps({'stype': stype, 'sround': sround})})")
    want = SCATTER_CASE[name]["highlighted"]
    page.wait_for_function(f"{HOOKS}.getViewModel('scatter').counts.highlighted === {want}")
    page.wait_for_timeout(300)
    pts = _points(_plot(page))
    assert sorted(p["i"] for p in pts) == list(range(len(_G["viewers"])))
    lit = {i for i in range(len(_G["round"])) if _in_control(i, name)}
    assert len(lit) == want
    op = _opacity(_plot(page))
    for p in pts:
        assert op[p["i"]] == (1 if p["i"] in lit else FADED), p["i"]
        assert p["line_c"].upper() != INK_LIGHT  # no pick, so no ink outline
    assert layout() == before
    assert (
        page.eval_on_selector_all(f"{LEGEND} button", "els => els.map(e => e.dataset.family)")
        == chips
    )
    status = page.locator(f"{VIEW} .mlb-scatter-status").inner_text()
    assert status == _status(SCATTER_CASE["all"]) + f" {want} highlighted."
    # A faded dot still opens its game.
    faded = next(p["i"] for p in pts if p["i"] not in lit)
    pt = _dot(page, faded)
    page.mouse.click(pt["x"], pt["y"])
    page.wait_for_function(f"{HOOKS}.getState().game === {faded}")
