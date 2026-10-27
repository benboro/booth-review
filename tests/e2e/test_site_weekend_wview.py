"""The `wview` URL key and the Timeline | Map switch of the This weekend tab (Phase 24, plan 05).
Synthetic fixtures only: the CFB weekend dataset of test_site_weekend_cfb and the flag-on NFL
build."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page
from test_site_weekend_cfb import MORNING, _weekend_raw

pytestmark = pytest.mark.e2e

NFL_NOW = "2026-10-11T09:00:00-04:00"


# ---- CFB ----


def _open_cfb(
    page: Page,
    fixture_raw: dict[str, Any],
    open_app: Callable[[Page, str], None],
    query: str,
) -> None:
    raw = _weekend_raw(fixture_raw)
    page.clock.set_fixed_time(MORNING)
    page.route("**/site-data.json*", lambda route: route.fulfill(json=raw))
    page.set_viewport_size({"width": 1440, "height": 900})
    open_app(page, query)


def _cfb_state(page: Page) -> dict[str, Any]:
    return page.evaluate("window.__testHooks.getState()")  # type: ignore[no-any-return]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("?view=weekend&wview=map", "map"),
        ("?view=weekend&wview=MAP", None),
        ("?view=weekend&wview=1", None),
        ("?view=weekend&wview=timeline", None),
        ("?view=crews&wview=map", None),
        ("?view=weekend", None),
    ],
)
def test_cfb_decode_allowlists_map(
    guarded_page: Page,
    fixture_raw: dict[str, Any],
    open_app: Callable[[Page, str], None],
    query: str,
    expected: str | None,
) -> None:
    _open_cfb(guarded_page, fixture_raw, open_app, query)
    assert _cfb_state(guarded_page)["wview"] == expected


def test_cfb_encode_only_on_weekend_with_map(
    guarded_page: Page,
    fixture_raw: dict[str, Any],
    open_app: Callable[[Page, str], None],
) -> None:
    _open_cfb(guarded_page, fixture_raw, open_app, "?view=weekend")
    page = guarded_page
    page.evaluate("window.__testHooks.setState({ wview: 'map' })")
    assert page.evaluate("location.search") == "?view=weekend&wview=map"
    page.evaluate("window.__testHooks.setState({ wview: null })")
    assert page.evaluate("location.search") == "?view=weekend"
    page.evaluate("window.__testHooks.setState({ wview: 'map', view: 'crews' })")
    assert "wview" not in page.evaluate("location.search")


def test_cfb_default_state_has_wview_null(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
) -> None:
    open_app(guarded_page, "")
    assert _cfb_state(guarded_page)["wview"] is None


# ---- NFL ----


def _open_nfl(page: Page, open_nfl_app: Callable[..., None], query: str) -> None:
    page.add_init_script(f"window.__nflWeekendNow = '{NFL_NOW}'")
    open_nfl_app(page, query)


def _nfl_state(page: Page) -> dict[str, Any]:
    return page.evaluate("window.__nflTestHooks.getState()")  # type: ignore[no-any-return]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("?sport=nfl&view=weekend&wview=map", "map"),
        ("?sport=nfl&view=weekend&wview=MAP", None),
        ("?sport=nfl&view=weekend&wview=1", None),
        ("?sport=nfl&view=weekend&wview=timeline", None),
        ("?sport=nfl&view=scatter&wview=map", None),
        ("?sport=nfl&wview=map&view=weekend", "map"),
        ("?sport=nfl&view=weekend", None),
    ],
)
def test_nfl_decode_allowlists_map(
    nfl_guarded_page: Page,
    open_nfl_app: Callable[..., None],
    query: str,
    expected: str | None,
) -> None:
    _open_nfl(nfl_guarded_page, open_nfl_app, query)
    assert _nfl_state(nfl_guarded_page)["wview"] == expected


def test_nfl_encode_and_leaving_clears_wview(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    _open_nfl(page, open_nfl_app, "?sport=nfl&view=weekend")
    page.evaluate("window.__nflTestHooks.setState({ wview: 'map' })")
    assert page.evaluate("location.search") == "?sport=nfl&view=weekend&wview=map"
    page.evaluate("window.__nflTestHooks.setState({ wview: null })")
    assert "wview" not in page.evaluate("location.search")
    page.evaluate("window.__nflTestHooks.setState({ wview: 'map' })")
    page.evaluate("window.__nflTestHooks.setState({ view: 'scatter' })")
    assert _nfl_state(page)["wview"] is None
    assert "wview" not in page.evaluate("location.search")
    page.evaluate("window.__nflTestHooks.setState({ view: 'weekend' })")
    assert _nfl_state(page)["wview"] is None


def test_nfl_default_state_has_wview_null(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    open_nfl_app(nfl_guarded_page, "?sport=nfl")
    assert _nfl_state(nfl_guarded_page)["wview"] is None


# ---- The Timeline | Map switch and the map-mode source line ----

_MOUNT = """async (arg) => {
  const V = await import('./modules/weekend-view.js');
  const old = document.getElementById('wk-host');
  if (old) old.remove();
  const host = document.createElement('div');
  host.id = 'wk-host';
  document.body.append(host);
  window.__wk = { views: [] };
  const opts = { width: 1440, now: new Date(arg.now), onWeek: () => {} };
  if (arg.switch) {
    opts.onView = (v) => {
      window.__wk.views.push(v);
      opts.wview = v === 'map' ? 'map' : null;
      window.__wk.inst = V.renderWeekend(host, model, opts);
    };
    opts.wview = arg.wview;
  }
  const weeks = [8, 9, 10].map((n) => ({ label: 'Week ' + n, number: n }));
  const model = Object.assign({
    sport: 'cfb', weekLabel: 'Week 9', weekNumber: 9, weeks, isLatestWeek: false,
    games: arg.games, day: '2026-10-31', past: false, missing: false, freshness: null,
    links: {},
  }, arg.model || {});
  window.__wk.inst = V.renderWeekend(host, model, opts);
  return true;
}"""

_GAME = {
    "key": "g",
    "sport": "cfb",
    "block": "scheduled",
    "index": 0,
    "date": "2026-10-31",
    "kickoffMin": 720,
    "networkId": "fox",
    "networkName": "FOX",
    "family": "fox",
    "away": "Away",
    "home": "Home",
    "awayRank": None,
    "homeRank": None,
    "neutral": False,
    "pbp": None,
    "analyst": None,
    "boothRank": None,
    "lead": False,
    "crewKnown": False,
    "past": False,
}


def _mount(
    page: Page,
    *,
    switch: bool = True,
    wview: str | None = None,
    model: dict[str, Any] | None = None,
) -> None:
    page.evaluate(
        _MOUNT,
        {
            "now": "2026-10-31T09:00:00-04:00",
            "games": [_GAME],
            "switch": switch,
            "wview": wview,
            "model": model,
        },
    )


@pytest.fixture
def wk_page(guarded_page: Page, open_app: Callable[[Page, str], None]) -> Page:
    guarded_page.set_viewport_size({"width": 1440, "height": 900})
    open_app(guarded_page, "")
    return guarded_page


def _pressed(page: Page) -> list[str | None]:
    return [page.locator(".wk-view-seg").nth(i).get_attribute("aria-pressed") for i in range(2)]


def test_switch_absent_without_on_view(wk_page: Page) -> None:
    _mount(wk_page, switch=False)
    assert wk_page.locator(".wk-view-switch").count() == 0
    assert wk_page.locator(".wk-stepper").count() == 1


def test_switch_order_labels_and_pressed_state(wk_page: Page) -> None:
    _mount(wk_page)
    group = wk_page.locator(".wk-controls-right > .wk-view-switch")
    assert group.get_attribute("role") == "group"
    assert group.get_attribute("aria-label") == "Weekend view"
    assert wk_page.locator(".wk-view-seg").all_inner_texts() == ["Timeline", "Map"]
    assert _pressed(wk_page) == ["true", "false"]
    kids = wk_page.eval_on_selector(
        ".wk-controls-right", "(n) => [...n.children].map((c) => c.className)"
    )
    assert kids == ["wk-view-switch", "wk-stepper"]
    _mount(wk_page, wview="map")
    assert _pressed(wk_page) == ["false", "true"]


def test_clicking_and_keys_switch_and_keep_focus(wk_page: Page) -> None:
    _mount(wk_page)
    wk_page.locator('[data-wk-id="wview:timeline"]').click()  # already pressed: nothing
    assert wk_page.evaluate("window.__wk.views") == []
    wk_page.locator('[data-wk-id="wview:map"]').click()
    assert wk_page.evaluate("window.__wk.views") == ["map"]
    assert _pressed(wk_page) == ["false", "true"]
    focused = wk_page.evaluate("document.activeElement?.dataset?.wkId")
    assert focused == "wview:map"
    wk_page.locator('[data-wk-id="wview:timeline"]').focus()
    wk_page.keyboard.press("Enter")
    assert wk_page.evaluate("window.__wk.views") == ["map", "timeline"]
    wk_page.locator('[data-wk-id="wview:map"]').focus()
    wk_page.keyboard.press("Space")
    assert wk_page.evaluate("window.__wk.views") == ["map", "timeline", "map"]


def _source(page: Page) -> str:
    return page.locator(".wk-source").inner_text()


def test_nfl_source_line_in_map_mode(wk_page: Page) -> None:
    wiki = "https://en.wikipedia.org/wiki/2026_NFL_season"
    base = {"sport": "nfl"}
    _mount(wk_page, wview="map", model=base)
    line = _source(wk_page)
    assert line.endswith("Stadium locations: Wikipedia (CC BY-SA 4.0)")
    assert "CollegeFootballData" not in line
    _mount(wk_page, wview="map", model={**base, "links": {"wikipedia": wiki}})
    line = _source(wk_page)
    assert "Networks and stadium locations: Wikipedia (CC BY-SA 4.0)" in line
    assert "CollegeFootballData" not in line
    hrefs = wk_page.eval_on_selector_all(".wk-source a", "(as) => as.map((a) => a.href)")
    assert wiki in hrefs
    assert any(h.endswith("data/reference/nfl_stadium_locations.csv") for h in hrefs)
    # Timeline mode is unchanged.
    _mount(wk_page, wview=None, model={**base, "links": {"wikipedia": wiki}})
    assert "Networks: Wikipedia (CC BY-SA 4.0)" in _source(wk_page)
    assert "stadium" not in _source(wk_page).lower()
    _mount(wk_page, wview=None, model=base)
    assert "Wikipedia" not in _source(wk_page)


def test_cfb_source_line_identical_in_both_modes(wk_page: Page) -> None:
    _mount(wk_page, wview=None)
    timeline = _source(wk_page)
    _mount(wk_page, wview="map")
    assert _source(wk_page) == timeline
    assert "CollegeFootballData.com" in timeline
