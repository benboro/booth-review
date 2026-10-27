"""NFL weekend map end to end on the flag-on build (Phase 24, plan 10): window shapes by slot,
the international game as an edge marker labelled by city, a venue-less game in Not on the map,
non-intersecting edge markers and labels at 390 px, the map-mode credit, picks, the upcoming panel
and week stepping. Synthetic fixture only (week 5, Sunday 2026-10-11).

Fixture facts (24-06): upcoming 0, 1 and 8 are CBS 1:00 pm (early) at the two US stadiums; 4 and
5 are FOX 4:25 pm (late); 6 is the NBC Sunday-night game; 2 is a 1:00 pm game at the GB venue and
9 is the 9:30 am London game (night, a standalone slot); 3 has no venue and 7 has no kickoff or
venue.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from dark_checks import set_theme, settle
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

THEMES = ["light", "dark"]
NOW = "2026-10-11T09:00:00-04:00"
OpenNfl = Callable[..., None]

EARLY_A = "nfl:upcoming:0"
EARLY_B = "nfl:upcoming:1"
LATE_A = "nfl:upcoming:4"
NIGHT = "nfl:upcoming:6"
LONDON_NIGHT = "nfl:upcoming:9"
LONDON_EARLY = "nfl:upcoming:2"
US_DOTS = ["nfl:upcoming:0", "nfl:upcoming:1", "nfl:upcoming:4", "nfl:upcoming:5", "nfl:upcoming:6"]

_READY = """() => {
  const gd = document.querySelector('.wk-map-box');
  return !!(gd && gd._fullLayout && gd.data && gd.data.some((t) => t.name === 'venue-hits'));
}"""

_TRACES = """() => {
  const out = {};
  for (const t of document.querySelector('.wk-map-box').data) {
    if (t.name === 'outline') continue;
    const m = t.marker || {};
    out[t.name] = {
      keys: t.customdata ? [...t.customdata] : [],
      symbol: m.symbol ? [...m.symbol].map(String) : [],
      opacity: Array.isArray(m.opacity) ? [...m.opacity] : [],
      x: [...t.x], y: [...t.y], text: t.text ? [...t.text] : [],
    };
  }
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

# Rendered bounding boxes of the edge markers' symbols and city labels (the last scatter trace).
_MARKER_BOXES = """() => {
  const gd = document.querySelector('.wk-map-box');
  const traces = gd.querySelectorAll('.scatterlayer .trace');
  const markers = traces[traces.length - 1];
  const box = (n) => {
    const r = n.getBoundingClientRect();
    return { l: r.left, t: r.top, r: r.right, b: r.bottom };
  };
  return {
    symbols: [...markers.querySelectorAll('.points path.point')].map(box),
    labels: [...markers.querySelectorAll('.textpoint text')]
      .filter((n) => (n.textContent || '').trim() !== '')
      .map((n) => ({ ...box(n), text: n.textContent })),
  };
}"""


def _open(
    page: Page, open_nfl_app: OpenNfl, query: str = "&wview=map", theme: str = "light"
) -> None:
    page.add_init_script(f"window.__nflWeekendNow = '{NOW}'")
    open_nfl_app(page, f"?sport=nfl&view=weekend{query}")
    if "wview=map" in query:
        _drawn(page)
        if theme != "light":
            set_theme(page, theme)
            _drawn(page)


def _drawn(page: Page) -> None:
    page.wait_for_function(_READY, timeout=15000)
    settle(page)


def _traces(page: Page) -> dict[str, dict[str, Any]]:
    return page.evaluate(_TRACES)  # type: ignore[no-any-return]


def _symbols(page: Page) -> dict[str, str]:
    t = _traces(page)
    out: dict[str, str] = {}
    for name in ("dots-faded", "dots", "dots-matched", "markers"):
        out.update(zip(t[name]["keys"], t[name]["symbol"], strict=True))
    return out


def _point(page: Page, key: str) -> dict[str, float]:
    page.evaluate("() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))")
    return page.evaluate(_POINT, key)  # type: ignore[no-any-return]


def _hover(page: Page, key: str) -> None:
    at = _point(page, key)
    page.mouse.move(at["x"] + 40, at["y"] + 40)
    page.mouse.move(at["x"], at["y"], steps=6)
    page.wait_for_selector("#chart-tooltip[data-kind='game']:not([hidden])", timeout=5000)
    page.wait_for_timeout(250)  # the card follows the closest mark; let it settle on the last


def _intersect(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return bool(a["l"] < b["r"] and b["l"] < a["r"] and a["t"] < b["b"] and b["t"] < a["b"])


def test_map_mode_url_and_switch_state(nfl_guarded_page: Page, open_nfl_app: OpenNfl) -> None:
    page = nfl_guarded_page
    page.set_viewport_size({"width": 1440, "height": 900})
    _open(page, open_nfl_app, query="")
    assert page.locator('[data-wk-id="wview:timeline"]').get_attribute("aria-pressed") == "true"
    assert "wview" not in page.evaluate("location.search")
    page.click('[data-wk-id="wview:map"]')
    page.wait_for_function("location.search.includes('wview=map')")
    _drawn(page)
    search = page.evaluate("location.search")
    assert "view=weekend" in search
    assert page.locator(".wk-day[aria-selected=true]").inner_text().startswith("Sun. Oct. 11")
    page.click('[data-wk-id="wview:timeline"]')
    page.wait_for_function("!location.search.includes('wview')")
    page.wait_for_selector(".wk-grid")
    assert page.locator(".wk-map-box").count() == 0


@pytest.mark.parametrize("theme", THEMES)
def test_early_late_and_night_games_render_circle_square_and_diamond(
    nfl_guarded_page: Page, open_nfl_app: OpenNfl, theme: str
) -> None:
    page = nfl_guarded_page
    page.set_viewport_size({"width": 1440, "height": 900})
    _open(page, open_nfl_app, theme=theme)
    symbols = _symbols(page)
    assert symbols[EARLY_A] == "circle"
    assert symbols[EARLY_B] == "circle"
    assert symbols[LATE_A] == "square"
    assert symbols["nfl:upcoming:5"] == "square"
    assert symbols[NIGHT] == "diamond"
    assert symbols[LONDON_NIGHT] == "diamond"
    assert symbols[LONDON_EARLY] == "circle"
    windows = page.evaluate(
        """() => [...document.querySelectorAll('.wk-map-key-kickoff .wk-map-key-item')]
          .map((n) => n.dataset.window)"""
    )
    assert windows == ["early", "late", "night"]


@pytest.mark.parametrize("theme", THEMES)
def test_the_gb_games_are_edge_markers_labelled_by_city(
    nfl_guarded_page: Page, open_nfl_app: OpenNfl, theme: str
) -> None:
    page = nfl_guarded_page
    page.set_viewport_size({"width": 1440, "height": 900})
    _open(page, open_nfl_app, theme=theme)
    t = _traces(page)
    assert sorted(t["markers"]["keys"]) == sorted([LONDON_NIGHT, LONDON_EARLY])
    assert [x for x in t["markers"]["text"] if x] == ["London"]  # one label per site
    assert sorted(t["dots"]["keys"] + t["dots-faded"]["keys"]) == sorted(
        [*US_DOTS, "nfl:upcoming:8"]
    )
    # Hover and click work on an edge marker.
    _hover(page, LONDON_NIGHT)
    assert "London" in page.locator("#chart-tooltip").inner_text()
    at = _point(page, LONDON_NIGHT)
    page.mouse.click(at["x"], at["y"])
    expect(page.locator("dialog[open]")).to_be_visible()


def test_a_game_with_no_venue_is_in_not_on_the_map(
    nfl_guarded_page: Page, open_nfl_app: OpenNfl
) -> None:
    page = nfl_guarded_page
    page.set_viewport_size({"width": 1440, "height": 900})
    _open(page, open_nfl_app)
    section = page.locator(".wk-notmap")
    cells = section.locator(".wk-cell")
    assert section.locator(".wk-tba-title").inner_text() == "Not on the map (2)"
    assert cells.count() == 2
    text = section.inner_text()
    assert "Northfield Lanterns @ Granite Bay Owls" in text
    assert "Mesa Comets @ Harbor City Gulls" in text
    # The Time TBA game with no venue is in both lists; the placed games are in neither.
    assert page.locator(".wk-tba:not(.wk-notmap) .wk-cell").count() == 2


@pytest.mark.parametrize("theme", THEMES)
def test_no_two_edge_marker_or_label_boxes_intersect_at_390px(
    nfl_mobile_page: Page, open_nfl_app: OpenNfl, theme: str
) -> None:
    page = nfl_mobile_page
    _open(page, open_nfl_app, theme=theme)
    boxes = page.evaluate(_MARKER_BOXES)
    symbols, labels = boxes["symbols"], boxes["labels"]
    assert len(symbols) == 2
    assert [label["text"] for label in labels] == ["London"]
    for i, a in enumerate(symbols):
        for b in symbols[i + 1 :]:
            assert not _intersect(a, b), (a, b)
    for i, a in enumerate(labels):
        for b in labels[i + 1 :]:
            assert not _intersect(a, b), (a, b)
    # A label touches only the marker it belongs to: the mark nearest its centre.
    for label in labels:
        cx, cy = (label["l"] + label["r"]) / 2, (label["t"] + label["b"]) / 2

        def gap(s: dict[str, float], cx: float = cx, cy: float = cy) -> float:
            return abs((s["l"] + s["r"]) / 2 - cx) + abs((s["t"] + s["b"]) / 2 - cy)

        others = sorted(symbols, key=gap)[1:]
        for other in others:
            assert not _intersect(label, other), (label, other)


def test_the_source_line_credits_wikipedia_and_stadium_locations_only_in_map_mode(
    nfl_guarded_page: Page, open_nfl_app: OpenNfl
) -> None:
    page = nfl_guarded_page
    page.set_viewport_size({"width": 1440, "height": 900})
    _open(page, open_nfl_app, query="")
    timeline = page.locator(".wk-source").inner_text()
    assert "Networks: Wikipedia (CC BY-SA 4.0)" in timeline
    assert "stadium locations" not in timeline
    page.click('[data-wk-id="wview:map"]')
    _drawn(page)
    source = page.locator(".wk-source")
    text = source.inner_text()
    assert "Networks and stadium locations: Wikipedia (CC BY-SA 4.0)" in text
    assert "nflverse" in text
    assert "506 Sports" in text
    assert "CollegeFootballData" not in text
    assert "CollegeFootballData" not in page.locator(".wk-root").inner_text()
    hrefs = source.locator("a").evaluate_all("(n) => n.map((a) => a.href)")
    assert "https://en.wikipedia.org/wiki/2026_NFL_season" in hrefs
    # The stadium-location credit links the location table (24-08 swaps in the article link).
    assert any("nfl_stadiums.csv" in h for h in hrefs)


@pytest.mark.parametrize("theme", THEMES)
def test_a_team_pick_fades_and_rings_as_on_cfb(
    nfl_guarded_page: Page, open_nfl_app: OpenNfl, theme: str
) -> None:
    page = nfl_guarded_page
    page.set_viewport_size({"width": 1440, "height": 900})
    _open(page, open_nfl_app, theme=theme)
    team = page.evaluate(
        "(async () => { const r = await fetch('nfl-data.json'); const j = await r.json();"
        " return j.lookups.franchises.find((f) => f.name.includes('Granite Bay')).id; })()"
    )
    page.evaluate("(id) => window.__nflTestHooks.setState({ teams: [id] })", team)
    page.wait_for_function(
        "() => document.querySelector('.wk-map-box').data"
        ".find((t) => t.name === 'ring-ink').x.length > 0",
        timeout=15000,
    )
    settle(page)
    t = _traces(page)
    matched = t["dots-matched"]["keys"]
    assert matched
    assert t["dots-faded"]["keys"]
    assert set(t["dots-faded"]["opacity"]) == {0.15}
    assert set(t["dots-matched"]["opacity"]) == {1}
    assert len(t["ring-ink"]["x"]) == len(t["ring-keyline"]["x"]) >= 1
    assert set(matched).isdisjoint(t["dots-faded"]["keys"])


def test_clicking_an_upcoming_game_opens_the_not_played_yet_panel(
    nfl_guarded_page: Page, open_nfl_app: OpenNfl
) -> None:
    page = nfl_guarded_page
    page.set_viewport_size({"width": 1440, "height": 900})
    _open(page, open_nfl_app)
    _hover(page, EARLY_A)
    card = page.locator("#chart-tooltip").inner_text()
    assert "Granite Bay Owls" in card or "Northfield Lanterns" in card
    assert "CBS" in card
    assert "Fixture Field" in card
    at = _point(page, EARLY_A)
    page.mouse.click(at["x"], at["y"])
    dialog = page.locator("dialog[open]")
    expect(dialog).to_be_visible()
    assert "Not played yet." in dialog.inner_text()
    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    page.wait_for_function(
        "document.activeElement && document.activeElement.dataset.wkId === 'wview:map'",
        timeout=5000,
    )


def test_week_stepping_keeps_wview(nfl_guarded_page: Page, open_nfl_app: OpenNfl) -> None:
    page = nfl_guarded_page
    page.set_viewport_size({"width": 1440, "height": 900})
    _open(page, open_nfl_app)
    page.locator(".wk-step--prev").click()
    expect(page.locator("#nfl-chart-subtitle")).to_contain_text("Week 4")
    search = page.evaluate("location.search")
    assert "wview=map" in search
    assert "week=4" in search
    assert page.locator('[data-wk-id="wview:map"]').get_attribute("aria-pressed") == "true"
    _drawn(page)


def test_view_and_switch_make_no_request(nfl_guarded_page: Page, open_nfl_app: OpenNfl) -> None:
    page = nfl_guarded_page
    page.set_viewport_size({"width": 1440, "height": 900})
    _open(page, open_nfl_app, query="")
    seen: list[str] = []
    page.on("request", lambda req: seen.append(req.url))
    page.click('[data-wk-id="wview:map"]')
    _drawn(page)
    _hover(page, EARLY_A)
    page.click('[data-wk-id="wview:timeline"]')
    page.wait_for_selector(".wk-grid")
    static = ("/logos/", "/vendor/")
    assert [u for u in seen if not any(m in u for m in static) and not u.startswith("blob:")] == []
