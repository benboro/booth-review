"""CFB weekend map end to end at 1440 px, light and dark (Phase 24, plan 10): the Timeline | Map
switch and its URL, carry-over of week, day and picks, the dot per placed game, window symbols,
the Time TBA ring, shared-venue rows, picks (fade, ring, splat), the hover card, the panel and
focus return, edge markers, Not on the map, the compact table, the request guard and the credit.

Synthetic fixture only: `weekend_map_raw` in conftest.py (a deep copy of the contract fixture,
never vault data). Saturday 2026-10-03 layout is documented beside it.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import pytest
from conftest import (
    WEEKEND_MAP_MARKERS,
    WEEKEND_MAP_NO_VENUE,
    WEEKEND_MAP_PLACED_DOTS,
)
from dark_checks import set_theme, settle
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

THEMES = ["light", "dark"]
MAP_URL = "?view=weekend&wview=map"

NOON_A = "cfb:scheduled:0"
NOON_B = "cfb:scheduled:1"  # same Lincoln venue as NOON_A
TBA = "cfb:scheduled:3"
PRIME = "cfb:scheduled:5"
AFTERNOON = "cfb:scheduled:6"
ESPN_PLUS = "cfb:scheduled:10"
LATE = "cfb:scheduled:11"
LONDON = "cfb:scheduled:12"
PLAYED_NOON = "cfb:t:11"
LEAD = "cfb:t:19"  # Ironpeak @ Stonebridge, tier-a booth Rowan / Delgado
PASADENA_B = "cfb:scheduled:7"

_READY = """() => {
  const gd = document.querySelector('.wk-map-box');
  return !!(gd && gd._fullLayout && gd.data && gd.data.some((t) => t.name === 'venue-hits'));
}"""

_SPLAT_READY = """() => {
  const gd = document.querySelector('.wk-map-box');
  return !!(gd && gd._fullLayout && gd._fullLayout.images && gd._fullLayout.images.length > 0);
}"""

_TRACES = """() => {
  const gd = document.querySelector('.wk-map-box');
  const out = {};
  for (const t of gd.data) {
    if (t.name === 'outline') continue;
    const m = t.marker || {};
    out[t.name] = {
      keys: t.customdata ? [...t.customdata] : [],
      symbol: m.symbol ? [...m.symbol].map(String) : [],
      opacity: Array.isArray(m.opacity) ? [...m.opacity] : [],
      color: Array.isArray(m.color) ? [...m.color] : [],
      x: [...t.x], y: [...t.y], text: t.text ? [...t.text] : [],
    };
  }
  return out;
}"""

_SPLAT = """async () => {
  const gd = document.querySelector('.wk-map-box');
  const spec = gd._fullLayout.images[0];
  const img = new Image();
  img.src = spec.source;
  await img.decode();
  const c = document.createElement('canvas');
  c.width = img.naturalWidth;
  c.height = img.naturalHeight;
  const g = c.getContext('2d');
  g.drawImage(img, 0, 0);
  const hits = gd.data.find((t) => t.name === 'venue-hits');
  const out = {};
  hits.customdata.forEach((k, i) => {
    const px = Math.round((hits.x[i] / 975) * c.width);
    const py = Math.round((hits.y[i] / 610) * c.height);
    out[k] = Array.from(g.getImageData(px, py, 1, 1).data);
  });
  return out;
}"""

_POINT = """(key) => {
  const gd = document.querySelector('.wk-map-box');
  gd.scrollIntoView({ block: 'center' });
  const t = gd.data.find((d) => d.name === 'venue-hits');
  const i = t.customdata.indexOf(key);
  const r = gd.getBoundingClientRect();
  const xa = gd._fullLayout.xaxis;
  const ya = gd._fullLayout.yaxis;
  return { x: r.left + xa._offset + xa.c2p(t.x[i]), y: r.top + ya._offset + ya.c2p(t.y[i]) };
}"""

_RENDERS = """async () => (await import('./modules/weekend-map-view.js')).weekendMapRenderCount()"""

Wk = Callable[..., Page]


@pytest.fixture
def wkmap(
    guarded_page: Page,
    serve_weekend_map: Callable[..., None],
    open_app: Callable[[Page, str], None],
) -> Wk:
    guarded_page.set_viewport_size({"width": 1440, "height": 900})

    def _open(query: str = MAP_URL, theme: str = "light") -> Page:
        serve_weekend_map(guarded_page)
        open_app(guarded_page, query)
        if "wview=map" in query:
            wait_drawn(guarded_page)
            if theme != "light":
                set_theme(guarded_page, theme)
                wait_drawn(guarded_page)
        elif theme != "light":
            set_theme(guarded_page, theme)
        return guarded_page

    return _open


def wait_drawn(page: Page) -> None:
    page.wait_for_function(_READY, timeout=15000)
    settle(page)


def traces(page: Page) -> dict[str, dict[str, Any]]:
    return page.evaluate(_TRACES)  # type: ignore[no-any-return]


def dot_symbols(page: Page) -> dict[str, str]:
    """Symbol per game key across the three dot layers and the edge markers."""
    t = traces(page)
    out: dict[str, str] = {}
    for name in ("dots-faded", "dots", "dots-matched", "markers"):
        out.update(zip(t[name]["keys"], t[name]["symbol"], strict=True))
    return out


def point(page: Page, key: str) -> dict[str, float]:
    page.evaluate("() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))")
    return page.evaluate(_POINT, key)  # type: ignore[no-any-return]


def hover(page: Page, key: str) -> None:
    at = point(page, key)
    page.mouse.move(at["x"] + 40, at["y"] + 40)
    page.mouse.move(at["x"], at["y"], steps=6)
    page.wait_for_selector("#chart-tooltip[data-kind='game']:not([hidden])", timeout=5000)
    page.wait_for_timeout(250)  # the card follows the closest mark; let it settle on the last


def pick_person(page: Page, person_id: str = "pat-rowan") -> None:
    page.evaluate("(id) => window.__testHooks.setState({ people: [id] })", person_id)
    page.wait_for_function(
        "() => document.querySelector('.wk-map-box').data"
        ".find((t) => t.name === 'ring-ink').x.length > 0",
        timeout=15000,
    )
    settle(page)


def test_timeline_is_the_default_and_the_url_has_no_wview(wkmap: Wk) -> None:
    page = wkmap("?view=weekend")
    expect(page.locator(".wk-grid")).to_be_visible()
    assert page.locator(".wk-map-box").count() == 0
    assert page.locator('[data-wk-id="wview:timeline"]').get_attribute("aria-pressed") == "true"
    assert page.locator('[data-wk-id="wview:map"]').get_attribute("aria-pressed") == "false"
    assert "wview" not in page.evaluate("location.search")


def test_map_switch_adds_wview_and_carries_week_day_and_picks(wkmap: Wk) -> None:
    page = wkmap("?view=weekend&day=fri")
    page.evaluate("window.__testHooks.setState({ people: ['pat-rowan'] })")
    before = page.evaluate("window.__testHooks.getState()")
    page.click('[data-wk-id="wview:map"]')
    page.wait_for_function("location.search.includes('wview=map')")
    wait_drawn(page)
    search = page.evaluate("location.search")
    assert "view=weekend" in search
    assert "day=fri" in search
    assert "people=" in search
    after = page.evaluate("window.__testHooks.getState()")
    assert after["day"] == "fri"
    assert after["people"] == before["people"]
    assert page.locator(".wk-day[aria-selected=true]").inner_text().startswith("Fri.")
    # Friday has one game, a faded dot under the Rowan pick.
    assert traces(page)["dots-faded"]["keys"] == ["cfb:scheduled:9"]
    page.click('[data-wk-id="wview:timeline"]')
    page.wait_for_function("!location.search.includes('wview')")
    page.wait_for_selector(".wk-grid")
    kept = page.evaluate("location.search")
    assert "day=fri" in kept
    assert "people=" in kept
    assert page.locator(".wk-map-box").count() == 0


def test_the_week_stepper_keeps_the_map(wkmap: Wk) -> None:
    page = wkmap()
    page.locator(".wk-step--prev").click()
    expect(page.locator("#chart-subtitle")).to_contain_text("Week 4")
    assert "wview=map" in page.evaluate("location.search")
    assert page.locator('[data-wk-id="wview:map"]').get_attribute("aria-pressed") == "true"


@pytest.mark.parametrize("theme", THEMES)
def test_one_dot_per_placed_game(wkmap: Wk, theme: str) -> None:
    page = wkmap(theme=theme)
    t = traces(page)
    dots = sum(len(t[n]["keys"]) for n in ("dots-faded", "dots", "dots-matched"))
    assert dots == WEEKEND_MAP_PLACED_DOTS
    assert len(t["markers"]["keys"]) == WEEKEND_MAP_MARKERS
    assert len(t["venue-hits"]["keys"]) == WEEKEND_MAP_PLACED_DOTS + WEEKEND_MAP_MARKERS
    label = page.locator(".wk-map-box").get_attribute("aria-label") or ""
    assert label.startswith(f"Map of {dots + len(t['markers']['keys'])} games on Sat. Oct. 3")


@pytest.mark.parametrize("theme", THEMES)
def test_each_window_renders_its_symbol(wkmap: Wk, theme: str) -> None:
    page = wkmap(theme=theme)
    symbols = dot_symbols(page)
    assert symbols[PLAYED_NOON] == "circle"
    assert symbols[NOON_A] == "circle"
    assert symbols[AFTERNOON] == "square"
    assert symbols[ESPN_PLUS] == "square"
    assert symbols[PRIME] == "diamond"
    assert symbols[LEAD] == "diamond"
    assert symbols[LATE] == "arrow-up"
    assert symbols[LONDON] == "circle"
    # The key lists the same five shapes, each drawn once.
    key = page.evaluate(
        """() => [...document.querySelectorAll('.wk-map-key-kickoff .wk-map-key-item')]
          .map((n) => [n.dataset.window, n.querySelectorAll('svg').length])"""
    )
    assert [w for w, _ in key] == ["noon", "afternoon", "prime", "late", "tba"]
    assert all(n == 1 for _, n in key)


@pytest.mark.parametrize("theme", THEMES)
def test_time_tba_game_draws_the_open_ring_and_stays_in_the_strip(wkmap: Wk, theme: str) -> None:
    page = wkmap(theme=theme)
    assert dot_symbols(page)[TBA] == "circle-open"
    strip = page.locator(".wk-tba:not(.wk-notmap)")
    assert strip.locator('[data-wk-id="g:cfb:scheduled:3"]').count() == 1
    assert page.locator(".wk-notmap").locator('[data-wk-id="g:cfb:scheduled:3"]').count() == 0


def test_shared_venue_games_get_distinct_x_and_the_same_y(wkmap: Wk) -> None:
    page = wkmap()
    hits = traces(page)["venue-hits"]
    at = dict(zip(hits["keys"], zip(hits["x"], hits["y"], strict=True), strict=True))
    (xa, ya), (xb, yb) = at[NOON_A], at[NOON_B]
    assert xa != xb
    assert ya == yb
    # The Pasadena pair (one prime game each) is nudged the same way.
    (xc, yc), (xd, yd) = at[LEAD], at[PASADENA_B]
    assert xc != xd
    assert yc == yd


@pytest.mark.parametrize("theme", THEMES)
def test_announcers_pick_fades_rings_and_empties_the_splat(wkmap: Wk, theme: str) -> None:
    page = wkmap(theme=theme)
    page.wait_for_function(_SPLAT_READY, timeout=15000)
    before = page.evaluate(_SPLAT)
    assert before[NOON_A][3] > 0
    pick_person(page)
    t = traces(page)
    assert t["dots-matched"]["keys"] == [LEAD]
    assert sorted(t["dots-faded"]["keys"]) == sorted(
        k for k in dot_symbols(page) if k not in (LEAD, LONDON)
    )
    assert set(t["dots-faded"]["opacity"]) == {0.15}
    assert set(t["dots-matched"]["opacity"]) == {1}
    assert t["markers"]["opacity"] == [0.15]  # the London game is not Rowan's
    assert len(t["ring-ink"]["x"]) == 1
    assert len(t["ring-keyline"]["x"]) == 1
    # The splat counts only the matching game: once repainted, the Lincoln venue (two games, no
    # match) reads exactly like Atlanta (no match either: bare land), and the Pasadena venue where
    # Rowan calls still carries shading.
    after: dict[str, list[int]] = {}
    for _ in range(60):
        after = page.evaluate(_SPLAT)
        if after[NOON_A] == after[PRIME] and after[LEAD] != after[PRIME]:
            break
        page.wait_for_timeout(250)
    assert after[NOON_A] == after[PRIME], (after[NOON_A], after[PRIME])
    assert after[LEAD] != after[PRIME]
    assert before[NOON_A] != after[NOON_A]


def test_networks_pick_fades_non_matching_dots(wkmap: Wk) -> None:
    page = wkmap()
    page.evaluate("window.__testHooks.setState({ networks: ['espn'] })")
    page.wait_for_function(
        "() => document.querySelector('.wk-map-box').data"
        ".find((t) => t.name === 'dots-faded').x.length > 0",
        timeout=15000,
    )
    settle(page)
    t = traces(page)
    matching = {AFTERNOON, LEAD}
    assert set(t["dots"]["keys"]) | set(t["dots-matched"]["keys"]) == matching
    assert set(t["dots-faded"]["keys"]) == set(dot_symbols(page)) - matching - {LONDON}
    assert set(t["dots-faded"]["opacity"]) == {0.15}
    assert t["markers"]["opacity"] == [1]  # the London game is on net-a (espn)


@pytest.mark.parametrize("theme", THEMES)
def test_hover_card_shows_matchup_booth_kickoff_network_and_venue(wkmap: Wk, theme: str) -> None:
    page = wkmap(theme=theme)
    hover(page, LEAD)
    card = page.locator("#chart-tooltip").inner_text()
    assert "Ironpeak @ Stonebridge" in card
    assert "Pat Rowan · Sam Delgado" in card
    assert "7:30 pm ET, Alpha Sports" in card
    assert "Stonebridge Stadium, Pasadena, CA" in card
    assert page.locator("#chart-tooltip .tt-open-game").count() == 0


@pytest.mark.parametrize("theme", THEMES)
def test_click_opens_the_panel_with_the_crew_credit_and_escape_returns_focus(
    wkmap: Wk, theme: str
) -> None:
    page = wkmap(theme=theme)
    hover(page, LEAD)
    at = point(page, LEAD)
    page.mouse.click(at["x"], at["y"])
    dialog = page.locator("dialog[open]")
    expect(dialog).to_be_visible()
    text = dialog.inner_text()
    assert "Ironpeak at Stonebridge" in text
    assert "Crew from 506 Sports" in text
    assert "Not played yet." in text
    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    page.wait_for_function(
        "document.activeElement && document.activeElement.dataset.wkId === 'wview:map'",
        timeout=5000,
    )


def test_not_on_the_map_lists_the_venueless_games_and_the_count_matches(wkmap: Wk) -> None:
    page = wkmap()
    section = page.locator(".wk-notmap")
    heading = section.locator(".wk-tba-title").inner_text()
    cells = section.locator(".wk-cell")
    assert heading == f"Not on the map ({WEEKEND_MAP_NO_VENUE})"
    assert cells.count() == WEEKEND_MAP_NO_VENUE
    ids = cells.evaluate_all("(n) => n.map((c) => c.dataset.wkId)")
    assert sorted(ids) == ["g:cfb:scheduled:2", "g:cfb:scheduled:4", "g:cfb:scheduled:8"]
    assert "No venue is listed for these games yet." in section.inner_text()
    # A venue-less cell opens the same panel.
    cells.first.click()
    expect(page.locator("dialog[open]")).to_be_visible()


def test_espn_plus_game_is_dotted_and_still_in_the_compact_table(wkmap: Wk) -> None:
    page = wkmap()
    assert dot_symbols(page)[ESPN_PLUS] == "square"
    table = page.locator(".wk-compact-table")
    assert table.is_visible()
    assert "Northfield @ Lakeview" in table.inner_text()
    assert "6:00 pm" in table.inner_text()


@pytest.mark.parametrize("theme", THEMES)
def test_the_gb_game_is_an_edge_marker_labelled_by_city(wkmap: Wk, theme: str) -> None:
    page = wkmap(theme=theme)
    t = traces(page)
    assert t["markers"]["keys"] == [LONDON]
    assert t["marker-labels"]["text"] == ["London"]
    assert t["marker-labels"]["y"] == t["markers"]["y"]  # a label stays on its row
    assert LONDON not in t["dots"]["keys"] + t["dots-faded"]["keys"]
    hover(page, LONDON)
    assert "London" in page.locator("#chart-tooltip").inner_text()
    at = point(page, LONDON)
    page.mouse.click(at["x"], at["y"])
    expect(page.locator("dialog[open]")).to_be_visible()


def test_view_and_switch_make_no_request(
    guarded_page: Page,
    serve_weekend_map: Callable[..., None],
    open_app: Callable[[Page, str], None],
) -> None:
    guarded_page.set_viewport_size({"width": 1440, "height": 900})
    serve_weekend_map(guarded_page)
    open_app(guarded_page, "?view=weekend")
    seen: list[str] = []
    guarded_page.on("request", lambda req: seen.append(req.url))
    guarded_page.click('[data-wk-id="wview:map"]')
    wait_drawn(guarded_page)
    hover(guarded_page, LEAD)
    guarded_page.click('[data-wk-id="wview:timeline"]')
    guarded_page.wait_for_selector(".wk-grid")
    guarded_page.click('[data-wk-id="wview:map"]')
    wait_drawn(guarded_page)
    # The guard also fails the test on any off-origin request at teardown. The only same-origin
    # requests are static assets (network marks and the lazily loaded state outlines): no data
    # file, API or other fetch.
    static = ("/logos/", "/vendor/")
    assert [u for u in seen if not any(m in u for m in static) and not u.startswith("blob:")] == []


def test_cfb_source_line_is_unchanged_in_map_mode(wkmap: Wk) -> None:
    page = wkmap("?view=weekend")
    timeline = page.locator(".wk-source").inner_text()
    page.click('[data-wk-id="wview:map"]')
    wait_drawn(page)
    source = page.locator(".wk-source")
    assert source.inner_text() == timeline
    assert "CollegeFootballData.com" in timeline
    assert "Wikipedia" not in timeline
    assert "Stadium locations" not in timeline
    href = source.locator("a", has_text="CollegeFootballData.com").first.get_attribute("href")
    assert href == "https://collegefootballdata.com"


def test_theme_flip_repaints_the_same_node(wkmap: Wk) -> None:
    page = wkmap()
    page.evaluate("() => { window.__node = document.querySelector('.wk-map-box'); }")
    before_count = page.evaluate(_RENDERS)
    light_colour = traces(page)["dots"]["color"][0]
    set_theme(page, "dark")
    page.wait_for_function(
        """async (n) => (await import('./modules/weekend-map-view.js'))
          .weekendMapRenderCount() > n""",
        arg=before_count,
        timeout=15000,
    )
    settle(page)
    assert page.evaluate("document.querySelector('.wk-map-box') === window.__node")
    assert traces(page)["dots"]["color"][0] != light_colour
    set_theme(page, "light")
    settle(page)
    assert re.fullmatch(r"#[0-9A-Fa-f]{6}", traces(page)["dots"]["color"][0])


def test_desktop_hover_draws_the_ink_ring_and_unhover_clears_it(wkmap: Wk) -> None:
    page = wkmap()
    rings = "() => document.querySelector('.wk-map-box').data.find((t) => t.name === 'wk-hover')"
    at = page.evaluate(_POINT, NOON_A)
    page.mouse.move(at["x"] + 60, at["y"] + 60)
    page.mouse.move(at["x"], at["y"], steps=4)
    page.wait_for_function(rings + ".x.length === 1", timeout=5000)
    ring = page.evaluate(rings + ".marker")
    assert ring["symbol"] == "circle-open"
    assert ring["line"]["width"] == 1
    renders = page.evaluate(_RENDERS)
    page.mouse.move(at["x"] + 80, at["y"] + 80, steps=4)
    page.wait_for_function(rings + ".x.length === 0", timeout=5000)
    assert page.evaluate(_RENDERS) == renders  # a restyle, never a full react


def test_map_to_timeline_keeps_focus_on_the_timeline_segment(wkmap: Wk) -> None:
    page = wkmap()
    page.locator('[data-wk-id="wview:timeline"]').focus()
    page.keyboard.press("Enter")
    page.wait_for_selector(".wk-map-box", state="detached", timeout=5000)
    assert page.evaluate("document.activeElement?.dataset?.wkId") == "wview:timeline"


_MARK_CENTRES = """(keys) => {
  // Rendered centre (CSS px) of each key's drawn mark and of its venue-hits twin, which shares
  // the point the rings centre on.
  const out = {};
  for (const g of document.querySelectorAll('.wk-map-box .scatterlayer .trace')) {
    const trace = g.__data__[0].trace;
    const pts = g.querySelectorAll('path.point');
    (trace.customdata || []).forEach((key, i) => {
      if (!keys.includes(key) || !pts[i]) return;
      const b = pts[i].getBoundingClientRect();
      const kind = trace.name === 'venue-hits' ? 'hit' : 'mark';
      out[key] = { ...(out[key] || {}), [kind]: [b.x + b.width / 2, b.y + b.height / 2] };
    });
  }
  return out;
}"""


@pytest.mark.parametrize("theme", THEMES)
def test_triangle_mark_is_centred_on_its_ring(wkmap: Wk, theme: str) -> None:
    # Plotly's arrow-up hangs from its tip; the map lifts it so it centres on its point like the
    # circle, and so the hover ring (centred on that point) surrounds it.
    page = wkmap(theme=theme)
    centres = page.evaluate(_MARK_CENTRES, [LATE, NOON_A])
    for key in (LATE, NOON_A):
        (mx, my), (hx, hy) = centres[key]["mark"], centres[key]["hit"]
        assert abs(mx - hx) <= 1.0, key
        assert abs(my - hy) <= 1.0, key


def _click_in_place(page: Page, wk_id: str) -> None:
    """A real mouse click at the control's centre: locator.click() would scroll it into view."""
    box = page.locator(f'[data-wk-id="{wk_id}"]').first.bounding_box()
    assert box is not None, wk_id
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)


def test_view_day_and_week_changes_keep_the_scroll_position(wkmap: Wk) -> None:
    # A rebuild empties the panel (or moves the map node out of it) and then reads a size, so the
    # page used to shrink for one layout and the browser clamped the scroll to the top.
    page = wkmap()
    page.wait_for_function(_SPLAT_READY, timeout=15000)
    steps = [
        "wview:timeline",  # Map -> Timeline (destroy, then a fresh mount)
        "wview:map",  # Timeline -> Map
        "day:2026-10-02",  # day pick: the view rebuilds itself, outside the app's render
        "day:2026-10-03",
        "step:prev",  # week step, Map -> Map in place
        "step:next",
    ]
    for wk_id in steps:
        page.evaluate("window.scrollTo(0, 250)")
        assert page.evaluate("scrollY") == 250, wk_id
        _click_in_place(page, wk_id)
        assert page.evaluate("scrollY") == 250, wk_id
        if wk_id == "wview:timeline":
            settle(page)
        else:
            wait_drawn(page)
        assert page.evaluate("scrollY") == 250, wk_id
