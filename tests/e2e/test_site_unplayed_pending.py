"""v2.1 user rule (2026-10-26): an unplayed pending game with a crew is left out of Scatter,
Bars, Map, Crews, the facets and the counts until it is played or rated; This weekend still
shows it. The contract fixture's merged index 19 (2026, cause pending, no score, crew persons
4 and 5) is that game."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from conftest import FIXTURE_GAMES, FIXTURE_SHOWN, FIXTURE_UNPLAYED
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

UNPLAYED = FIXTURE_GAMES - 1  # merged index 19
OpenApp = Callable[[Page, str], None]


def _view(page: Page) -> dict[str, Any]:
    return page.evaluate("window.__testHooks.getView()")  # type: ignore[no-any-return]


def test_data_marks_the_one_unplayed_pending_game(guarded_page: Page, open_app: OpenApp) -> None:
    open_app(guarded_page, "")
    got = guarded_page.evaluate(
        """(k) => { const d = window.__testHooks.data;
           return { n: d.n, unplayed: Array.from(d.unplayed), cause: d.t.cause[k],
                    pts: [d.t.home_points[k], d.t.away_points[k]] }; }""",
        UNPLAYED,
    )
    assert got["n"] == FIXTURE_GAMES
    assert sum(got["unplayed"]) == FIXTURE_UNPLAYED
    assert got["unplayed"][UNPLAYED] == 1
    assert got["cause"] == "pending" and got["pts"] == [None, None]


def test_scatter_never_draws_or_counts_it(guarded_page: Page, open_app: OpenApp) -> None:
    open_app(guarded_page, "")
    v = _view(guarded_page)
    assert UNPLAYED not in v["passesFilters"]
    assert v["visibleCount"] == FIXTURE_SHOWN
    assert v["facets"]["total"] == FIXTURE_SHOWN
    assert v["summary"] == {"kind": "all", "count": FIXTURE_SHOWN, "rated": 12}
    # Hide mode draws exactly the passing games, so it is not drawn there either.
    open_app(guarded_page, "?dots=hide")
    assert _view(guarded_page)["visibleCount"] == FIXTURE_SHOWN
    band = guarded_page.evaluate(
        """() => { const gd = document.getElementById('chart');
           return (gd.data || []).filter((t) => (t.meta || '').startsWith('unrated-'))
             .flatMap((t) => (t.customdata || []).map((c) => Array.isArray(c) ? c[0] : c)); }"""
    )
    assert UNPLAYED not in band


def test_an_announcer_pick_does_not_match_it(guarded_page: Page, open_app: OpenApp) -> None:
    open_app(guarded_page, "")
    person = guarded_page.evaluate("window.__testHooks.data.lookups.people[4].id")
    guarded_page.evaluate("(id) => window.__testHooks.setState({ people: [id] })", person)
    v = _view(guarded_page)
    assert UNPLAYED not in v["highlighted"]
    assert UNPLAYED not in v["matched"]
    assert v["facets"]["total"] <= FIXTURE_SHOWN


def test_crews_and_map_leave_it_out(guarded_page: Page, open_app: OpenApp) -> None:
    open_app(guarded_page, "?view=crews")
    rows = guarded_page.evaluate(
        """async () => {
          const G = await import('./modules/crew-groups.js');
          const { data } = window.__testHooks; const view = window.__testHooks.getView();
          const m = G.buildCrewRows(data, view, { mode: 'crew', perSeason: false });
          return m.rows.map((r) => r.games);
        }"""
    )
    assert rows and all(UNPLAYED not in games for games in rows)
    open_app(guarded_page, "?view=map")
    guarded_page.wait_for_function("() => window.__testHooks.mapRenders >= 1")
    assert UNPLAYED not in _view(guarded_page)["passesFilters"]


def test_this_weekend_still_shows_it_with_its_crew(guarded_page: Page, open_app: OpenApp) -> None:
    guarded_page.clock.set_fixed_time("2026-10-03T09:00:00-04:00")
    open_app(guarded_page, "?view=weekend")
    cell = guarded_page.locator(f'[data-wk-id="g:cfb:t:{UNPLAYED}"]')
    assert cell.count() == 1
    person = guarded_page.evaluate("window.__testHooks.data.lookups.people[4].id")
    guarded_page.evaluate("(id) => window.__testHooks.setState({ people: [id] })", person)
    assert "is-match" in (cell.get_attribute("class") or "")
