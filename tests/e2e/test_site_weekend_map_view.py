"""In-browser smoke tests for the weekend map view (Phase 24, plan 07).

`renderWeekendMap` (site/modules/weekend-map-view.js) is mounted into a fresh host on the served
app page from synthetic WeekendGame literals built here, so the tests need no fixture data beyond
a served page and never touch vault data.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

SAT = "2026-10-31"
SUN = "2026-11-01"
NOW = "2026-10-31T09:00:00-04:00"

ATHENS = {"name": "Sanford Stadium", "city": "Athens", "state": "GA", "country": "US",
          "lat": 33.9498, "lon": -83.3733}  # fmt: skip
TUSCALOOSA = {"name": "Bryant-Denny Stadium", "city": "Tuscaloosa", "state": "AL",
              "country": "US", "lat": 33.2084, "lon": -87.5504}  # fmt: skip
LONDON = {"name": "Wembley Stadium", "city": "London", "state": None, "country": "GB",
          "lat": 51.556, "lon": -0.2796}  # fmt: skip

_MOUNT = """async (arg) => {
  const V = await import('./modules/weekend-map-view.js');
  document.documentElement.dataset.theme = arg.theme;
  const old = document.getElementById('wk-host');
  if (old) old.remove();
  const host = document.createElement('div');
  host.id = 'wk-host';
  host.style.width = arg.hostWidth + 'px';
  document.body.append(host);
  window.__wm = { opened: [], views: [], V, host, model: null, opts: null };
  window.__wm.opts = {
    width: arg.hostWidth,
    now: new Date(arg.now),
    passes: () => null,
    networksPicked: () => null,
    onDay: () => {},
    onWeek: () => {},
    onView: (v) => window.__wm.views.push(v),
    onOpen: (g, opener) => window.__wm.opened.push([g.key, opener && opener.dataset.wkId]),
  };
  const weeks = [8, 9, 10].map((n) => ({ label: 'Week ' + n, number: n }));
  window.__wm.model = {
    sport: 'cfb', weekLabel: 'Week 9', weekNumber: 9, weeks, isLatestWeek: false,
    games: arg.games, day: arg.day, past: false, missing: false, freshness: null, links: {},
  };
  window.__wm.inst = V.renderWeekendMap(host, window.__wm.model, window.__wm.opts);
  return true;
}"""

_READY = """async () => {
  for (let i = 0; i < 100; i += 1) {
    const gd = document.querySelector('.wk-map-box');
    if (gd && gd.data && window.__wm.V.weekendMapRenderCount() > 0) return true;
    await new Promise((r) => setTimeout(r, 50));
  }
  return false;
}"""


def _game(key: str, venue: dict[str, Any] | None, **kw: Any) -> dict[str, Any]:
    place = None if venue is None else sum(ord(c) for c in f"{venue['name']}|{venue['lat']}")
    base: dict[str, Any] = {
        "key": key,
        "sport": "cfb",
        "block": "scheduled",
        "index": 0,
        "date": SAT,
        "kickoffMin": 720,
        "networkId": "fox",
        "networkName": "FOX",
        "family": "fox",
        "away": f"Away {key}",
        "home": f"Home {key}",
        "awayRank": None,
        "homeRank": None,
        "neutral": False,
        "pbp": None,
        "analyst": None,
        "boothRank": None,
        "lead": False,
        "crewKnown": False,
        "past": False,
        "placeIdx": place,
        "venue": venue,
    }
    base.update(kw)
    return base


def _games() -> list[dict[str, Any]]:
    return [
        _game("a", ATHENS),
        _game(
            "b", TUSCALOOSA, kickoffMin=1170, networkId="espn", networkName="ESPN", family="disney"
        ),
        _game("c", LONDON, kickoffMin=None),
        _game("d", None),
        _game("e", None, kickoffMin=900),
        _game("s", TUSCALOOSA, date=SUN),
    ]


@pytest.fixture
def map_page(guarded_page: Page, open_app: Callable[[Page, str], None]) -> Page:
    open_app(guarded_page, "")
    return guarded_page


def _mount(page: Page, **kw: Any) -> None:
    arg = {"games": _games(), "day": SAT, "theme": "light", "hostWidth": 960, "now": NOW}
    arg.update(kw)
    page.evaluate(_MOUNT, arg)
    assert page.evaluate(_READY)


def test_mounts_shell_in_ui_spec_order(map_page: Page) -> None:
    _mount(map_page)
    out = map_page.evaluate(
        """() => {
          const root = document.querySelector('#wk-host .wk-root');
          const pick = (sel) => !!root.querySelector(sel);
          return {
            order: [...root.children].map((c) =>
              (c.classList.contains('wk-notmap') ? 'wk-notmap' : c.className.split(' ')[0])),
            switch: pick('.wk-view-switch'),
            pressed: root.querySelector('[data-wk-id="wview:map"]').getAttribute('aria-pressed'),
            label: document.querySelector('.wk-map-box').getAttribute('aria-label'),
            role: document.querySelector('.wk-map-box').getAttribute('role'),
          };
        }"""
    )
    assert out["order"] == [
        "wk-controls", "wk-stamp", "wk-map-wrap", "wk-map-key", "wk-tba", "wk-notmap",
        "wk-source",
    ]  # fmt: skip
    assert out["switch"] and out["pressed"] == "true"
    assert out["role"] == "img"
    # Three games have a venue on Saturday: Athens, Tuscaloosa and the London edge marker.
    assert out["label"].startswith("Map of 3 games on Sat. Oct. 31, colored by network.")


def test_one_point_per_placed_game(map_page: Page) -> None:
    _mount(map_page)
    counts = map_page.evaluate(
        """() => {
          const gd = document.querySelector('.wk-map-box');
          const by = {};
          for (const t of gd.data) by[t.name] = t.x.length;
          return by;
        }"""
    )
    dots = counts["dots-faded"] + counts["dots"] + counts["dots-matched"]
    assert dots == 2
    assert counts["markers"] == 1
    assert counts["venue-hits"] == 3


def test_not_on_the_map_lists_venueless_games(map_page: Page) -> None:
    _mount(map_page)
    out = map_page.evaluate(
        """() => {
          const head = document.querySelector('.wk-notmap .wk-tba-title').textContent;
          const cells = document.querySelectorAll('.wk-notmap .wk-cell').length;
          return { head, cells };
        }"""
    )
    assert out == {"head": "Not on the map (2)", "cells": 2}


def test_key_shows_only_present_windows_and_families(map_page: Page) -> None:
    _mount(map_page)
    out = map_page.evaluate(
        """() => ({
          windows: [...document.querySelectorAll('.wk-map-key-kickoff .wk-map-key-item')]
            .map((n) => n.dataset.window),
          families: [...document.querySelectorAll('.wk-map-key-networks .wk-map-key-item')]
            .map((n) => n.dataset.family),
        })"""
    )
    assert out["windows"] == ["noon", "prime", "tba"]
    assert set(out["families"]) == {"disney", "fox"}


def test_day_change_reacts_same_node_and_destroy_purges(map_page: Page) -> None:
    _mount(map_page)
    before = map_page.evaluate(
        """() => {
          window.__wm.node = document.querySelector('.wk-map-box');
          return window.__wm.V.weekendMapRenderCount();
        }"""
    )
    map_page.click('[data-wk-id="day:2026-11-01"]')
    map_page.wait_for_function(
        "(n) => window.__wm.V.weekendMapRenderCount() > n", arg=before, timeout=10000
    )
    out = map_page.evaluate(
        """() => {
          const gd = document.querySelector('.wk-map-box');
          return {
            same: gd === window.__wm.node,
            points: gd.data.find((t) => t.name === 'venue-hits').x.length,
            label: gd.getAttribute('aria-label'),
          };
        }"""
    )
    assert out["same"] is True
    assert out["points"] == 1
    assert out["label"].startswith("Map of 1 game on Sun. Nov. 1")
    purged = map_page.evaluate(
        """() => {
          window.__wm.inst.destroy();
          return { data: window.__wm.node.data ?? null, layout: !!window.__wm.node._fullLayout,
                   hostEmpty: document.getElementById('wk-host').children.length === 0 };
        }"""
    )
    assert purged == {"data": None, "layout": False, "hostEmpty": True}


def test_click_opens_game_with_map_segment_opener(map_page: Page) -> None:
    _mount(map_page)
    map_page.click('[data-wk-id="g:d"]')
    opened = map_page.evaluate("() => window.__wm.opened")
    assert opened == [["d", "g:d"]]


def test_view_switch_calls_host(map_page: Page) -> None:
    _mount(map_page)
    map_page.click('[data-wk-id="wview:timeline"]')
    assert map_page.evaluate("() => window.__wm.views") == ["timeline"]


def test_view_switch_segments_are_32px_with_min_width(map_page: Page) -> None:
    _mount(map_page)
    out = map_page.evaluate(
        """() => [...document.querySelectorAll('.wk-view-seg')].map((n) => {
          const r = n.getBoundingClientRect();
          return [Math.round(r.height), r.width >= 80];
        })"""
    )
    assert all(h in (30, 31, 32) and wide for h, wide in out)


def test_phone_map_box_follows_the_map_aspect_ratio(map_page: Page) -> None:
    map_page.set_viewport_size({"width": 390, "height": 800})
    _mount(map_page, hostWidth=358)
    box = map_page.evaluate(
        """() => {
          const gd = document.querySelector('.wk-map-box');
          const r = gd.getBoundingClientRect();
          return { w: r.width, h: r.height };
        }"""
    )
    assert abs(box["h"] / box["w"] - 610 / 975) < 0.02


def _mark_point(page: Page, key: str) -> dict[str, float]:
    page.evaluate("() => document.querySelector('.wk-map-box').scrollIntoView({block: 'center'})")
    page.evaluate("() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))")
    return page.evaluate(
        """(key) => {
          const gd = document.querySelector('.wk-map-box');
          const t = gd.data.find((d) => d.name === 'venue-hits');
          const i = t.customdata.indexOf(key);
          const r = gd.getBoundingClientRect();
          const xa = gd._fullLayout.xaxis;
          const ya = gd._fullLayout.yaxis;
          return {
            x: r.left + xa._offset + xa.c2p(t.x[i]),
            y: r.top + ya._offset + ya.c2p(t.y[i]),
          };
        }""",
        key,
    )


def test_desktop_hover_card_and_click(map_page: Page) -> None:
    _mount(map_page)
    at = _mark_point(map_page, "a")
    map_page.mouse.move(at["x"] + 40, at["y"] + 40)
    map_page.mouse.move(at["x"], at["y"], steps=4)
    map_page.wait_for_timeout(250)
    map_page.wait_for_selector("#chart-tooltip[data-kind='game']:not([hidden])", timeout=5000)
    card = map_page.evaluate(
        """() => {
          const t = document.getElementById('chart-tooltip');
          return { text: t.innerText, button: !!t.querySelector('.tt-open-game') };
        }"""
    )
    assert "Away a @ Home a" in card["text"]
    assert "Crew TBA" in card["text"]
    assert "12:00 pm ET, FOX" in card["text"]
    assert "Sanford Stadium" in card["text"]
    assert card["button"] is False
    map_page.mouse.click(at["x"], at["y"])
    opened = map_page.evaluate("() => window.__wm.opened")
    assert opened == [["a", "wview:map"]]


def test_phone_tap_model(mobile_page: Page, open_app: Callable[[Page, str], None]) -> None:
    open_app(mobile_page, "")
    _mount(mobile_page, hostWidth=358)
    at = _mark_point(mobile_page, "a")
    mobile_page.touchscreen.tap(at["x"], at["y"])
    mobile_page.wait_for_selector("#chart-tooltip[data-kind='game']:not([hidden])", timeout=5000)
    button = mobile_page.locator("#chart-tooltip .tt-open-game")
    assert button.count() == 1
    assert button.bounding_box()["height"] >= 44  # type: ignore[index]
    ring = mobile_page.evaluate(
        "() => document.querySelector('.wk-map-box').data"
        ".find((t) => t.name === 'wk-hover').x.length"
    )
    assert ring == 1
    assert mobile_page.evaluate("() => window.__wm.opened") == []
    # The button opens the panel and returns focus to the Map segment.
    button.tap()
    assert mobile_page.evaluate("() => window.__wm.opened") == [["a", "wview:map"]]
    # A tap on the background clears only the card.
    at = _mark_point(mobile_page, "a")
    mobile_page.touchscreen.tap(at["x"], at["y"])
    mobile_page.wait_for_selector("#chart-tooltip[data-kind='game']:not([hidden])", timeout=5000)
    box = mobile_page.locator(".wk-map-box").bounding_box()
    assert box is not None
    mobile_page.touchscreen.tap(box["x"] + 20, box["y"] + 20)
    mobile_page.wait_for_selector("#chart-tooltip", state="hidden", timeout=5000)
    assert mobile_page.evaluate("() => window.__wm.opened.length") == 1


def test_an_all_undated_week_still_draws_and_labels_without_a_date(map_page: Page) -> None:
    """A non-empty week whose games all have date null is valid; the map must not throw."""
    errors: list[str] = []
    map_page.on("pageerror", lambda e: errors.append(str(e)))
    undated = [_game("a", ATHENS, date=None), _game("d", None, date=None)]
    _mount(map_page, games=undated, day=None)
    out = map_page.evaluate(
        """() => ({
          label: document.querySelector('.wk-map-box').getAttribute('aria-label'),
          points: document.querySelector('.wk-map-box').data
            .find((t) => t.name === 'venue-hits').x.length,
          notMap: document.querySelector('.wk-notmap .wk-tba-title').textContent,
        })"""
    )
    assert out["label"].startswith("Map of 1 game with no listed date, colored by network.")
    assert out["points"] == 1
    assert out["notMap"] == "Not on the map (1)"
    assert errors == []


def test_a_failed_geometry_import_is_reported_and_says_so_on_the_map(map_page: Page) -> None:
    """The failure shows the overlay and is warned about. (The retry itself, resetting the cached
    promise, cannot be observed in Chromium: its module map keeps a failed import for the page.)"""
    warnings: list[str] = []
    map_page.on("console", lambda m: warnings.append(m.text) if m.type == "warning" else None)
    map_page.route("**/vendor/us-states-albers.js*", lambda route: route.abort())
    map_page.evaluate(
        _MOUNT,
        {"games": _games(), "day": SAT, "theme": "light", "hostWidth": 960, "now": NOW},
    )
    map_page.wait_for_selector(".map-overlay.wk-map-fail:not([hidden])", timeout=10000)
    assert any("weekend map geometry could not be loaded" in w for w in warnings)
