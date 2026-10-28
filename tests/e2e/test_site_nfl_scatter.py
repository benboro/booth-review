# ruff: noqa: E501  (embedded JS lines and the UI copy's typographic characters)
"""999.5-16: NFL view 4, Game scatter.

Synthetic nfl-data fixture only; no vault rows. Expected values are recomputed
from the fixture's `games` block.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from itertools import pairwise
from typing import Any

import pytest
from playwright.sync_api import Page, Route
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from test_site_chart import _RING_VISIBLE, _assert_ring_on

pytestmark = pytest.mark.e2e

VIEW = "#nfl-view-scatter"
TOOLS = "#nfl-chart-tools [data-tools-for='scatter']"  # view tools sit in the module header (13-13)
GD = f"{VIEW} .nfl-chart > div"
CAUSES = ("pending", "regional", "none")


def _open(page: Page, open_nfl_app: Callable[..., None], query: str = "") -> None:
    open_nfl_app(page, "?sport=nfl&view=scatter" + query)


def _vm(page: Page) -> dict[str, Any]:
    page.wait_for_function("window.__nflTestHooks.getViewModel('scatter').drawn === true")
    return page.evaluate("window.__nflTestHooks.getViewModel('scatter')")  # type: ignore[no-any-return]


def _set(page: Page, patch: dict[str, Any]) -> None:
    page.evaluate("p => window.__nflTestHooks.setState(p)", patch)


def _g(raw: dict[str, Any]) -> dict[str, list[Any]]:
    return raw["games"]  # type: ignore[no-any-return]


def _emit(page: Page, event: str, i: int) -> None:
    page.evaluate(
        """([ev, i, sel]) => {
          const gd = document.querySelector(sel);
          gd.emit(ev, { points: [{ customdata: i }], event: { clientX: 300, clientY: 200 } });
        }""",
        [event, i, GD],
    )


def _tooltip(page: Page) -> list[str]:
    page.wait_for_function("!document.getElementById('chart-tooltip').hidden")
    return page.evaluate(  # type: ignore[no-any-return]
        "Array.from(document.getElementById('chart-tooltip').children).map(c => c.textContent)"
    )


def _panel_open(page: Page) -> bool:
    return page.evaluate("document.getElementById('nfl-detail-panel').open")  # type: ignore[no-any-return]


# The NFL twin of test_site_chart's `_DOT_PIXEL_JS`, reading the NFL graph div.
_NFL_DOT_PIXEL_JS = """
([selector, customdata]) => {
  const gd = document.querySelector(selector);
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

# Client-pixel centre of the rated (y) or band (y2) subplot.
_NFL_SUBPLOT_CENTER_JS = """
([selector, band]) => {
  const gd = document.querySelector(selector);
  const layout = gd._fullLayout;
  const rect = gd.getBoundingClientRect();
  const ya = band ? layout.yaxis2 : layout.yaxis;
  return {
    x: rect.left + layout.xaxis._offset + layout.xaxis._length / 2,
    y: rect.top + ya._offset + ya._length / 2,
  };
}
"""

# True when the point lies on Plotly's drag/hover layer inside the graph div.
_NFL_HOVER_LAYER_JS = """
([selector, x, y]) => {
  const gd = document.querySelector(selector);
  const hit = document.elementFromPoint(x, y);
  return hit !== null && gd.contains(hit) && hit.closest('.draglayer') !== null;
}
"""

_TWO_FRAMES_JS = (
    "() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
)


def _nfl_dot_point(page: Page, customdata: int) -> dict[str, float]:
    """Client pixel of game `customdata`'s dot, computed from the trace data and the
    axes (not from any hover event), so it is an independent reference for the ring."""
    page.locator(GD).first.scroll_into_view_if_needed()
    point: dict[str, float] | None = page.evaluate(_NFL_DOT_PIXEL_JS, [GD, customdata])
    assert point is not None, f"no NFL dot with customdata {customdata}"
    return point


def _offset_hover_target(page: Page, band: bool) -> tuple[int, dict[str, float], dict[str, float]]:
    """A game, its dot pixel, and a pointer pixel a few px off that dot.

    Picks the most isolated dot of the case (rated log axis, or the unrated band) so
    it stays the unique nearest dot within Plotly's 20 px hover distance, then offsets
    the pointer 6 px in x and 5 px in y toward the subplot centre, onto the hover layer.
    """
    case = "unrated-band" if band else "rated-log-axis"
    items = _vm(page)["items"]
    candidates = [it["i"] for it in items if it["band"] is band and not it["faded"]]
    pixels = {i: _nfl_dot_point(page, i) for i in candidates}

    def clearance(i: int) -> float:
        others = [
            math.hypot(pixels[i]["x"] - pixels[j]["x"], pixels[i]["y"] - pixels[j]["y"])
            for j in candidates
            if j != i
        ]
        return min(others, default=math.inf)

    centre = page.evaluate(_NFL_SUBPLOT_CENTER_JS, [GD, band])
    best = 0.0
    for i in sorted(candidates, key=clearance, reverse=True):
        room = clearance(i)
        best = max(best, room)
        if room < 24:
            break
        dot = pixels[i]
        pointer = {
            "x": dot["x"] + (6.0 if centre["x"] >= dot["x"] else -6.0),
            "y": dot["y"] + (5.0 if centre["y"] >= dot["y"] else -5.0),
        }
        if page.evaluate(_NFL_HOVER_LAYER_JS, [GD, pointer["x"], pointer["y"]]):
            return i, dot, pointer
    raise AssertionError(
        f"{case}: no isolated dot with a hoverable offset (best clearance {best:.1f} px)"
    )


# --------------------------------------------------------------- task 1


def test_plots_every_game_with_unrated_band(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    _open(nfl_guarded_page, open_nfl_app)
    vm = _vm(nfl_guarded_page)
    g = _g(nfl_fixture_raw)
    n = len(g["season"])
    null_viewers = sum(v is None for v in g["viewers"])
    assert vm["counts"]["plotted"] + vm["counts"]["band"] == n
    assert vm["counts"]["band"] == null_viewers
    assert vm["yType"] == "log"
    assert vm["axisTitles"]["y"] == "Viewers"
    assert vm["dateAxis"] == "reused"
    for cause in CAUSES:
        want = sum(
            1 for v, c in zip(g["viewers"], g["cause"], strict=True) if v is None and c == cause
        )
        assert vm["bandCauses"][cause] == want
    assert sum(vm["bandCauses"].values()) == null_viewers
    # Nothing missing is plotted: every band item has no viewer figure.
    banded = {it["i"] for it in vm["items"] if it["band"]}
    assert banded == {i for i, v in enumerate(g["viewers"]) if v is None}
    # The log axis keeps its exact tick labels.
    nfl_guarded_page.wait_for_selector(f"{GD} .ytick text", state="attached")
    ticks = nfl_guarded_page.evaluate(
        f"Array.from(document.querySelectorAll('{GD} .ytick text')).map(t => t.textContent)"
    )
    assert ticks
    assert set(ticks) <= {"500K", "1MM", "2MM", "5MM", "10MM", "20MM"}
    assert nfl_guarded_page.locator(f"{GD} svg").count() >= 1
    assert nfl_guarded_page.locator(f"{GD} canvas").count() == 0  # svg scatter, never scattergl


def test_excitement_mode_moves_only_null_excitement_to_band(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    _open(nfl_guarded_page, open_nfl_app, "&y=excitement")
    vm = _vm(nfl_guarded_page)
    g = _g(nfl_fixture_raw)
    null_exc = {i for i, v in enumerate(g["excitement"]) if v is None}
    assert vm["y"] == "excitement"
    assert vm["yType"] == "linear"
    assert vm["axisTitles"]["y"] == "Excitement"
    assert vm["counts"]["band"] == len(null_exc)
    assert {it["i"] for it in vm["items"] if it["band"]} == null_exc
    assert vm["counts"]["plotted"] + vm["counts"]["band"] == len(g["season"])
    btn = nfl_guarded_page.locator(f"{VIEW} .band-info")
    assert btn.inner_text().replace("\ni", "").strip().startswith("No excitement value")
    assert btn.get_attribute("aria-label") == "Why do some games have no excitement value?"


def test_margin_axis_and_na_strip(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    _open(nfl_guarded_page, open_nfl_app, "&x=margin")
    vm = _vm(nfl_guarded_page)
    g = _g(nfl_fixture_raw)
    null_margin = {i for i, m in enumerate(g["final_margin"]) if m is None}
    assert null_margin
    assert vm["axisTitles"]["x"] == "Final margin (points)"
    assert {it["i"] for it in vm["items"] if it["na"]} == null_margin
    assert vm["counts"]["naStrip"] == len(null_margin)
    # No game is dropped.
    assert len(vm["items"]) == len(g["season"])
    title = nfl_guarded_page.locator(f"{GD} .g-xtitle").text_content()
    assert title == "Final margin (points)"


def test_team_filter_fades_and_hide_removes(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    _open(nfl_guarded_page, open_nfl_app)
    g = _g(nfl_fixture_raw)
    fid = nfl_fixture_raw["lookups"]["franchises"][0]["id"]
    _set(nfl_guarded_page, {"teams": [fid]})
    n = len(g["season"])
    matching = sum(1 for i in range(n) if g["home"][i] == 0 or g["away"][i] == 0)
    nfl_guarded_page.wait_for_function(
        "window.__nflTestHooks.getViewModel('scatter').counts.faded > 0"
    )
    vm = _vm(nfl_guarded_page)
    assert vm["counts"]["faded"] == n - matching
    assert vm["counts"]["plotted"] + vm["counts"]["band"] == n
    _set(nfl_guarded_page, {"dots": "hide"})
    nfl_guarded_page.wait_for_function(
        "window.__nflTestHooks.getViewModel('scatter').counts.hidden > 0"
    )
    vm = _vm(nfl_guarded_page)
    assert vm["counts"]["hidden"] == n - matching
    assert vm["counts"]["faded"] == 0
    assert vm["counts"]["plotted"] + vm["counts"]["band"] == matching


_CFB_OPACITY_JS = "import('./modules/chart.js').then(c => c.DOT_OPACITY)"
_BOOTH_GAMES_JS = """async (key) => {
  const D = await import('./sports/nfl/data.js');
  const S = await import('./sports/nfl/state.js');
  const raw = await (await fetch('nfl-data.json')).json();
  return S.boothGames(D.prepareNfl(raw), [key]);
}"""


def test_announcer_and_booth_picks_fade_like_cfb(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    g = _g(nfl_fixture_raw)
    pid = nfl_fixture_raw["lookups"]["people"][0]["id"]
    n = len(g["season"])
    called = {i for i in range(n) if any(m["person"] == 0 for m in g["crew"][i])}
    assert called and len(called) < n
    opacity = page.evaluate(_CFB_OPACITY_JS)
    _set(page, {"people": [pid]})
    page.wait_for_function("window.__nflTestHooks.getViewModel('scatter').counts.matched > 0")
    vm = _vm(page)
    assert vm["counts"]["matched"] == len(called)
    assert vm["counts"]["faded"] == n - len(called)
    for it in vm["items"]:
        if it["i"] in called:
            assert it["matched"] and it["opacity"] == opacity["active"]
        else:
            assert not it["matched"] and it["opacity"] == opacity["activeUnderPerson"]
    # No dot grows because of a pick.
    sizes = page.evaluate(f"Array.from(document.querySelector('{GD}').data, t => t.marker.size)")
    assert {z for arr in sizes for z in arr} == {6}
    # Booths alone, then both: the intersection.
    key = page.evaluate("window.__nflTestHooks.getBoothCatalog()[0].key")
    booth = set(page.evaluate(_BOOTH_GAMES_JS, key))
    assert booth
    _set(page, {"people": [], "booths": [key]})
    page.wait_for_function(
        f"window.__nflTestHooks.getViewModel('scatter').counts.matched === {len(booth)}"
    )
    _set(page, {"people": [pid], "booths": [key]})
    both = called & booth
    page.wait_for_function(
        f"window.__nflTestHooks.getViewModel('scatter').counts.matched === {len(both)}"
    )
    vm = _vm(page)
    assert {it["i"] for it in vm["items"] if it["matched"]} == both


def test_hide_removes_unmatched_under_a_pick(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    g = _g(nfl_fixture_raw)
    pid = nfl_fixture_raw["lookups"]["people"][0]["id"]
    called = {i for i in range(len(g["season"])) if any(m["person"] == 0 for m in g["crew"][i])}
    _set(page, {"people": [pid], "dots": "hide"})
    page.wait_for_function(
        f"window.__nflTestHooks.getViewModel('scatter').items.length === {len(called)}"
    )
    vm = _vm(page)
    assert {it["i"] for it in vm["items"]} == called
    assert vm["counts"]["faded"] == 0


def test_empty_state_copy(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    _vm(page)
    g = _g(nfl_fixture_raw)
    people = nfl_fixture_raw["lookups"]["people"]
    # A season in which some person called nothing: picking them matches no game.
    season, who = next(
        (se, k)
        for se in sorted(set(g["season"]))
        for k in range(len(people))
        if not any(
            g["season"][i] == se and any(m["person"] == k for m in g["crew"][i])
            for i in range(len(g["season"]))
        )
    )
    _set(page, {"dots": "hide", "seasons": [season, season], "people": [people[who]["id"]]})
    note = page.locator(f"{VIEW} .season-empty-note")
    note.wait_for(state="visible")
    assert note.locator(".season-empty-title").inner_text() == "No games match these filters"
    assert (
        note.locator(".season-empty-hint").inner_text()
        == "Clear all filters, or widen the Seasons range."
    )


def test_legend_chip_hides_a_category(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    _open(nfl_guarded_page, open_nfl_app)
    chips = nfl_guarded_page.locator(f"{VIEW} ul.legend-chips > li > button.legend-chip")
    assert chips.all_inner_texts() == [
        "Thursday night",
        "Sunday night",
        "Monday night",
        "Holiday",
        "Other solo slot",
        "Fox AGOTW",
        "CBS late national",
        "International",
        "Other games",
    ]
    before = _vm(nfl_guarded_page)
    in_agotw = sum(1 for it in before["items"] if it["category"] == "agotw")
    assert in_agotw > 0
    chips.nth(5).click()
    nfl_guarded_page.wait_for_function(
        "window.__nflTestHooks.getViewModel('scatter').hiddenCategories.length === 1"
    )
    after = _vm(nfl_guarded_page)
    assert after["hiddenCategories"] == ["agotw"]
    assert all(it["category"] != "agotw" for it in after["items"])
    assert len(after["items"]) == len(before["items"]) - in_agotw
    assert chips.nth(5).get_attribute("aria-pressed") == "false"
    nfl_guarded_page.wait_for_timeout(400)  # past the 300 ms double-tap window
    chips.nth(5).click()  # restore for later tests in this page
    nfl_guarded_page.wait_for_function(
        "window.__nflTestHooks.getViewModel('scatter').hiddenCategories.length === 0"
    )


def test_band_note_text_and_links_exact(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    _open(nfl_guarded_page, open_nfl_app)
    _vm(nfl_guarded_page)
    btn = nfl_guarded_page.locator(f"{VIEW} .band-info")
    note = nfl_guarded_page.locator(f"{VIEW} .band-note")
    assert btn.is_visible()
    assert btn.get_attribute("aria-label") == "Why do some games have no public rating?"
    assert note.is_hidden()
    btn.click()
    assert note.is_visible()
    shown = nfl_guarded_page.locator(f"{VIEW} .band-note > div:not([hidden])")
    assert shown.locator("p").all_inner_texts() == [
        "No public rating",
        "We found no published viewer count for these games. The reason is shown for each game. The most common ones:",
        "How we count games",
    ]
    assert shown.locator("li").all_inner_texts() == [
        "Ratings Reference compiles national windows, not every regional game.",
        "The figure is not posted yet. This is for the newest games of the current season.",
        "No figure was published.",
    ]
    href = shown.locator("a").get_attribute("href")
    assert href is not None and href.endswith("#nfl-games-with-no-public-rating")
    nfl_guarded_page.keyboard.press("Escape")
    assert note.is_hidden()
    # Excitement copy.
    _set(nfl_guarded_page, {"scatterY": "excitement"})
    nfl_guarded_page.wait_for_function(
        "window.__nflTestHooks.getViewModel('scatter').y === 'excitement'"
    )
    btn.click()
    shown = nfl_guarded_page.locator(f"{VIEW} .band-note > div:not([hidden])")
    assert shown.locator("p").all_inner_texts() == [
        "No excitement value",
        "No win-probability data exists for these games, so they have no height on this chart. They are drawn here instead of being left out. Their viewer figures are unchanged.",
        "How the Y axis works",
    ]
    href = shown.locator("a").get_attribute("href")
    assert href is not None and href.endswith("#nfl-gei-style-excitement")


def test_controls_use_cfb_markup_and_wording(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    _vm(page)
    groups = page.locator(f"{TOOLS} .chart-controls .axis-group")
    assert groups.locator(".axis-caption").all_inner_texts() == ["X axis", "Y axis"]
    assert groups.locator(".segmented").evaluate_all(
        "els => els.map(e => e.getAttribute('aria-label'))"
    ) == ["X-axis measure", "Y-axis measure"]
    exc = page.locator(f"{TOOLS} button[data-y=excitement]")
    assert exc.get_attribute("aria-label") == "Excitement"
    assert exc.get_attribute("title") == "Excitement"
    assert exc.locator(".axis-long").inner_text() == "Excitement"
    assert exc.locator(".axis-short").inner_text() == "Excite."
    assert page.locator(f"{VIEW} .dots-toggle .dots-caption").inner_text() == "Filtered-out dots"
    dots = page.locator(f"{VIEW} .dots-toggle .segmented")
    assert dots.get_attribute("aria-label") == "Filtered-out dots"
    assert dots.locator("button[data-dots]").all_inner_texts() == ["Fade", "Hide"]
    # D-17: the GEI-style qualifier is in the caption only, never a button, axis title or header.
    for sel in (f"{VIEW} button", f"{TOOLS} button", f"{VIEW} th"):
        assert not any("GEI-style" in t for t in page.locator(sel).all_text_contents())
    assert "GEI-style" in page.locator(f"{VIEW} p.caption").nth(1).inner_text()
    _set(page, {"scatterY": "excitement"})
    assert _vm(page)["axisTitles"]["y"] == "Excitement"


def test_other_games_draw_hollow(nfl_guarded_page: Page, open_nfl_app: Callable[..., None]) -> None:
    _open(nfl_guarded_page, open_nfl_app)
    _vm(nfl_guarded_page)
    symbols = nfl_guarded_page.evaluate(
        f"[...new Set(document.querySelector('{GD}').data.flatMap(t => t.marker.symbol))]"
    )
    assert "circle-open" in symbols and "circle" in symbols


def test_no_spread_text_anywhere(nfl_guarded_page: Page, open_nfl_app: Callable[..., None]) -> None:
    _open(nfl_guarded_page, open_nfl_app)
    _vm(nfl_guarded_page)
    assert "spread" not in nfl_guarded_page.locator(VIEW).inner_text().lower()
    nfl_guarded_page.locator(f"{TOOLS} [aria-label='X-axis measure']").locator(
        "button[data-axis=margin]"
    ).click()
    nfl_guarded_page.wait_for_function(
        "window.__nflTestHooks.getViewModel('scatter').x === 'margin'"
    )
    assert "spread" not in nfl_guarded_page.locator(VIEW).inner_text().lower()
    html = nfl_guarded_page.evaluate(f"document.querySelector('{VIEW}').textContent.toLowerCase()")
    assert "spread" not in html


def test_hidden_table_wrapper_not_the_table(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    _open(nfl_guarded_page, open_nfl_app)
    _vm(nfl_guarded_page)
    assert nfl_guarded_page.locator(f"{VIEW} div.visually-hidden > table").count() == 1
    assert nfl_guarded_page.locator(f"{VIEW} table.visually-hidden").count() == 0


# --------------------------------------------------------------- task 2


def test_hover_lines_rated_window_and_unrated_regional(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    _open(nfl_guarded_page, open_nfl_app)
    _vm(nfl_guarded_page)
    g = _g(nfl_fixture_raw)
    names = nfl_fixture_raw["lookups"]["team_names"]
    people = nfl_fixture_raw["lookups"]["people"]
    networks = nfl_fixture_raw["lookups"]["networks"]
    rated = next(
        i
        for i in range(len(g["season"]))
        if g["scope"][i] == "window" and g["crew"][i] and g["network"][i] is not None
    )
    _emit(nfl_guarded_page, "plotly_hover", rated)
    lines = _tooltip(nfl_guarded_page)
    assert (
        lines[0]
        == f"{names[g['away_name'][rated]]['name']} at {names[g['home_name'][rated]]['name']}"
    )
    assert lines[1].endswith(f" ET, Week {g['week'][rated]}")
    net_name = networks[g["network"][rated]]["name"]
    # D-09: the network line is a mark (logo img with alt/title = name, or dot plus name).
    net = nfl_guarded_page.evaluate(
        """() => {
          const row = document.querySelector('#chart-tooltip .tooltip-networks');
          const img = row.querySelector('img');
          return {
            alt: img ? img.getAttribute('alt') : null,
            title: img ? img.getAttribute('title') : null,
            name: row.querySelector('.net-name')?.textContent ?? null,
            text: row.textContent,
          };
        }"""
    )
    if net["alt"] is not None:
        assert net["alt"] == net_name and net["title"] == net_name and net["text"] == ""
    else:
        assert net["name"] == net_name
    pbp = next(m for m in g["crew"][rated] if m["role"] == "pbp")
    analyst = next(m for m in g["crew"][rated] if m["role"] == "analyst")
    # D-01 crew box: neutral unless a picked announcer is in it.
    box = nfl_guarded_page.evaluate(
        """() => {
          const b = document.querySelector('#chart-tooltip .crew-box');
          return {
            matched: b.classList.contains('is-matched'),
            names: [...b.querySelectorAll('.crew-name')].map((n) => n.textContent),
          };
        }"""
    )
    assert box == {
        "matched": False,
        "names": [people[pbp["person"]]["name"], people[analyst["person"]]["name"]],
    }
    assert f"Viewers: {g['viewers'][rated] / 1e6:.1f}MM, window-level" in lines
    exc = g["excitement"][rated]
    assert f"Excitement: {exc:.1f} (GEI-style, not CFBD's index)" in lines
    assert lines[-1].startswith("Excitement:")
    assert not any("Click for details" in ln for ln in lines)
    assert not nfl_guarded_page.locator("#chart-hover-ring").is_hidden()
    _emit(nfl_guarded_page, "plotly_unhover", rated)
    assert nfl_guarded_page.locator("#chart-hover-ring").is_hidden()

    regional = next(
        i
        for i in range(len(g["season"]))
        if g["cause"][i] == "regional" and g["viewers"][i] is None
    )
    _emit(nfl_guarded_page, "plotly_hover", regional)
    lines = _tooltip(nfl_guarded_page)
    assert "Viewers: not available (not compiled for regional games)" in lines
    assert not any("window-level" in ln for ln in lines)
    exc = g["excitement"][regional]
    want = (
        f"Excitement: {exc:.1f} (GEI-style, not CFBD's index)"
        if exc is not None
        else "Excitement: not available"
    )
    assert want in lines


def test_faded_dot_has_no_hover_or_click(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    _open(nfl_guarded_page, open_nfl_app)
    _vm(nfl_guarded_page)
    fid = nfl_fixture_raw["lookups"]["franchises"][0]["id"]
    _set(nfl_guarded_page, {"teams": [fid]})
    nfl_guarded_page.wait_for_function(
        "window.__nflTestHooks.getViewModel('scatter').counts.faded > 0"
    )
    vm = _vm(nfl_guarded_page)
    faded = next(it["i"] for it in vm["items"] if it["faded"])
    _emit(nfl_guarded_page, "plotly_hover", faded)
    assert nfl_guarded_page.locator("#chart-tooltip").is_hidden()
    _emit(nfl_guarded_page, "plotly_click", faded)
    assert not _panel_open(nfl_guarded_page)


@pytest.mark.parametrize("band", [False, True], ids=["rated-log-axis", "unrated-band"])
def test_hover_ring_centres_on_the_dot_not_the_pointer(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], band: bool
) -> None:
    """notes-14: the ring centres on the hovered dot even when the pointer is off it, on the log axis and in the band."""
    page = nfl_guarded_page
    page.set_viewport_size({"width": 1280, "height": 900})
    _open(page, open_nfl_app)
    vm = _vm(page)
    assert vm["yType"] == "log"
    assert any(it["band"] is band and not it["faded"] for it in vm["items"])
    # Same scripted-hover quirks as test_site_chart._hover_dot: leave the chart first,
    # and let a coalesced scroll event settle before hovering.
    page.mouse.move(5, 5)
    page.locator(GD).first.scroll_into_view_if_needed()
    page.evaluate(_TWO_FRAMES_JS)
    i, dot, pointer = _offset_hover_target(page, band)
    assert math.hypot(pointer["x"] - dot["x"], pointer["y"] - dot["y"]) >= 6
    for attempt in range(2):
        page.mouse.move(pointer["x"], pointer["y"])
        try:
            page.wait_for_selector(_RING_VISIBLE, timeout=3000)
            break
        except PlaywrightTimeoutError:
            if attempt == 1:
                raise
            page.mouse.move(5, 5)
    _assert_ring_on(page, i, dot)


def test_click_opens_panel_and_accumulates_picks(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    _open(nfl_guarded_page, open_nfl_app)
    vm = _vm(nfl_guarded_page)
    ids = [it["i"] for it in vm["items"] if not it["band"]][:2]
    _emit(nfl_guarded_page, "plotly_click", ids[0])
    assert _panel_open(nfl_guarded_page)
    nfl_guarded_page.wait_for_function("window.__nflTestHooks.getTableIndexes().length === 1")
    assert nfl_guarded_page.evaluate("window.__nflTestHooks.getTableIndexes()") == [ids[0]]
    nfl_guarded_page.locator("#nfl-detail-panel .panel-close").click()
    nfl_guarded_page.wait_for_timeout(600)  # past the 500 ms same-target guard
    _emit(nfl_guarded_page, "plotly_click", ids[1])
    nfl_guarded_page.wait_for_function("window.__nflTestHooks.getTableIndexes().length === 2")
    assert set(nfl_guarded_page.evaluate("window.__nflTestHooks.getTableIndexes()")) == set(ids)
    # A repeat click on the same game does not duplicate it.
    nfl_guarded_page.locator("#nfl-detail-panel .panel-close").click()
    nfl_guarded_page.wait_for_timeout(600)
    _emit(nfl_guarded_page, "plotly_click", ids[1])
    assert len(nfl_guarded_page.evaluate("window.__nflTestHooks.getTableIndexes()")) == 2


def test_caption_text_and_links_exact(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    _open(nfl_guarded_page, open_nfl_app)
    _vm(nfl_guarded_page)
    cap = nfl_guarded_page.locator(f"{VIEW} p.caption")
    assert cap.all_inner_texts() == [
        "Viewers are window-level where marked and unnormalized; see methodology.",
        "NFL excitement is GEI-style, built from win probability. It is not CFBD\u2019s excitementIndex; see methodology.",
    ]
    hrefs = cap.locator("a").evaluate_all("els => els.map(a => a.getAttribute('href'))")
    assert [h.split("#")[1] for h in hrefs] == [
        "nfl-window-level-viewership",
        "nfl-gei-style-excitement",
    ]


def test_reset_zoom_is_disabled_at_home_and_enabled_after_a_zoom(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    """SHELL-06: the NFL scatter's page-level Reset zoom is aria-disabled at the home range,
    enabled once the plot is zoomed, and restores the home range."""
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    _vm(page)
    button = page.locator(
        "#nfl-chart-tools button.reset-zoom, #nfl-view-scatter button.reset-zoom"
    ).first
    assert button.get_attribute("aria-disabled") == "true"
    home = page.evaluate(f"document.querySelector('{GD}')._fullLayout.xaxis.range")
    page.evaluate(
        """([sel, lo, hi]) => window.Plotly.relayout(document.querySelector(sel), {'xaxis.range': [lo, hi]})""",
        [GD, home[0] + 1, home[1] - 1],
    )
    handle = button.element_handle()
    page.wait_for_function("b => b.getAttribute('aria-disabled') === 'false'", arg=handle)
    button.click()
    page.wait_for_function("b => b.getAttribute('aria-disabled') === 'true'", arg=handle)
    assert page.evaluate(
        f"document.querySelector('{GD}')._fullLayout.xaxis.range"
    ) == pytest.approx(home, abs=1e-6)


def test_mobile_tap_opens_panel(nfl_mobile_page: Page, open_nfl_app: Callable[..., None]) -> None:
    _open(nfl_mobile_page, open_nfl_app)
    vm = _vm(nfl_mobile_page)
    i = next(it["i"] for it in vm["items"] if not it["band"])
    _emit(nfl_mobile_page, "plotly_hover", i)
    assert (
        nfl_mobile_page.locator("#chart-tooltip").count() == 0
        or nfl_mobile_page.locator("#chart-tooltip").is_hidden()
    )
    _emit(nfl_mobile_page, "plotly_click", i)
    assert _panel_open(nfl_mobile_page)
    layout = nfl_mobile_page.evaluate(f"document.querySelector('{GD}')._fullLayout.dragmode")
    assert layout is False


def test_resize_repositions_band_button(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    _open(nfl_guarded_page, open_nfl_app)
    _vm(nfl_guarded_page)
    nfl_guarded_page.wait_for_function(
        f"document.querySelector('{VIEW} .band-info').style.top !== ''"
    )
    top = nfl_guarded_page.evaluate(
        f"parseFloat(document.querySelector('{VIEW} .band-info').style.top)"
    )
    assert top > 0


def test_mobile_era_labels_inside_plot_scatter(
    nfl_mobile_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_mobile_page

    labels = [f"Synthetic Nielsen measurement era {c} with a long label" for c in "ABC"]

    def _long_eras(route: Route) -> None:
        resp = route.fetch()
        raw = json.loads(resp.text())
        eras = raw["lookups"]["eras"]
        eras[:] = [{**eras[0], "id": f"era-{k}", "label": lab} for k, lab in enumerate(labels)]
        rank = {s: k for k, s in enumerate(sorted(set(raw["games"]["season"])))}
        for block in (raw["games"], raw["viewership"]):
            col = block["era"]
            for i, s in enumerate(block["season"]):
                if col[i] is not None:
                    col[i] = min(rank[s], len(labels) - 1)
        route.fulfill(response=resp, body=json.dumps(raw))

    page.route("**/nfl-data.json", _long_eras)
    open_nfl_app(page, "?sport=nfl&view=scatter")
    page.wait_for_function("window.__nflTestHooks.getViewModel('scatter').drawn === true")
    boxes = page.evaluate(
        """() => {
          const view = document.querySelector('#nfl-view-scatter .nfl-chart > div');
          const c = view.getBoundingClientRect();
          return [...view.querySelectorAll('.annotation-text')]
            .filter((n) => n.textContent.includes('Nielsen'))
            .map((n) => {
              const b = n.getBoundingClientRect();
              return { text: n.textContent, left: b.left - c.left, right: c.right - b.right, w: b.width };
            });
        }"""
    )
    assert boxes
    for b in boxes:
        assert b["left"] >= -0.5 and b["right"] >= -0.5, b
    ordered = sorted(boxes, key=lambda b: b["left"])
    for prev, nxt in pairwise(ordered):
        assert prev["w"] + prev["left"] <= nxt["left"], (prev, nxt)
    caption = page.locator("#nfl-view-scatter .nfl-era-caption").inner_text()
    for lab in labels:
        assert lab in caption


def test_keyboard_opens_a_game_from_the_scatter_table(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    """JS-WR-04: the scatter table's Details buttons are one roving tab stop and open the panel."""
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    vm = _vm(page)
    passing = [it["i"] for it in vm["items"] if not it["faded"]]
    wrap = page.locator(f"{VIEW} div.nfl-data-table")
    buttons = wrap.locator("tbody button[data-key]")
    assert buttons.count() == len(passing)
    stops = wrap.locator("tbody button[tabindex='0']")
    assert stops.count() == 1
    stops.first.focus()
    box = wrap.bounding_box()
    assert box is not None and box["width"] > 100
    page.keyboard.press("ArrowDown")
    key = page.evaluate("document.activeElement.dataset.key")
    assert key == buttons.nth(1).get_attribute("data-key")
    assert wrap.locator("tbody button[tabindex='0']").count() == 1
    page.keyboard.press("Enter")
    page.wait_for_function("document.getElementById('nfl-detail-panel').open")
    assert int(key) in page.evaluate("window.__nflTestHooks.getTableIndexes()")
    page.keyboard.press("Escape")
    page.wait_for_function("!document.getElementById('nfl-detail-panel').open")
    assert page.evaluate("document.activeElement.dataset.key") == key
