"""Crew pick state (plan 14-04): URL grammar, computeView wiring, D-08 exclusion, live region.

Runs in the page on the synthetic crews dataset (tests/e2e/crews_fixture.py).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from crews_fixture import CASE_TRIO
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

_KEY_JS = """
() => {
  const data = window.__testHooks.data;
  return import('./modules/crew-groups.js').then((G) => {
    const want = WANT;
    for (const [key, crew] of G.crewIndex(data).crews) {
      const same = crew.people.length === want.length;
      if (same && want.every((s) => crew.people.includes(s))) return key;
    }
    return null;
  });
}
""".replace("WANT", json.dumps([CASE_TRIO["pbp"], *CASE_TRIO["analysts"]]))

_URL_JS = """
async ({search, pre}) => {
  const U = await import('./modules/url-state.js');
  const S = await import('./modules/select.js');
  const data = window.__testHooks.data;
  const decoded = U.decodeState(search, data);
  return {
    decoded,
    encoded: U.encodeState(decoded, data),
    defaultEncoded: U.encodeState(S.defaultState(data), data),
    defaultDecodedEq:
      JSON.stringify(U.decodeState('', data)) === JSON.stringify(S.defaultState(data)),
  };
}
"""


@pytest.fixture
def app(
    guarded_page: Page,
    serve_crews: Callable[[Page], None],
    open_app: Callable[[Page, str], None],
) -> Page:
    serve_crews(guarded_page)
    open_app(guarded_page, "")
    return guarded_page


def _key(page: Page) -> str:
    key = page.evaluate(_KEY_JS)
    assert key
    return str(key)


def _url(page: Page, search: str) -> dict[str, Any]:
    return page.evaluate(_URL_JS, {"search": search, "pre": None})  # type: ignore[no-any-return]


def _people(page: Page) -> list[str]:
    return list(page.evaluate("window.__testHooks.data.lookups.people.map((p) => p.id)"))


# -- URL grammar -----------------------------------------------------------------------------


def test_default_state_encodes_empty(app: Page) -> None:
    out = _url(app, "")
    assert out["defaultEncoded"] == ""
    assert out["defaultDecodedEq"] is True
    s = out["decoded"]
    assert (s["crew"], s["cmode"], s["perseason"], s["csort"]) == (None, "crew", False, None)


def test_crew_round_trip_after_colors(app: Page) -> None:
    key = _key(app)
    out = _url(app, f"?colors=off&crew={key}")
    assert out["decoded"]["crew"] == key
    assert out["encoded"] == f"?colors=off&crew={key}"
    assert _url(app, f"?crew={key}")["encoded"] == f"?crew={key}"


@pytest.mark.parametrize("bad", ["disney:nobody.nobody", "<script>", "DISNEY:X", "%E0%A4%A", ""])
def test_bad_crew_drops(app: Page, bad: str) -> None:
    assert _url(app, f"?crew={bad}")["decoded"]["crew"] is None


def test_people_win_over_crew(app: Page) -> None:
    key = _key(app)
    pid = _people(app)[0]
    s = _url(app, f"?people={pid}&crew={key}")["decoded"]
    assert s["people"] == [pid]
    assert s["crew"] is None


def test_cmode(app: Page) -> None:
    assert _url(app, "?cmode=pbp")["decoded"]["cmode"] == "pbp"
    assert _url(app, "?cmode=analyst")["encoded"] == "?cmode=analyst"
    assert _url(app, "?cmode=crew")["decoded"]["cmode"] == "crew"
    assert _url(app, "?cmode=x")["encoded"] == ""


def test_perseason_needs_two_seasons(app: Page) -> None:
    assert _url(app, "?perseason=1")["decoded"]["perseason"] is True
    assert _url(app, "?perseason=1")["encoded"] == "?perseason=1"
    assert _url(app, "?perseason=yes")["decoded"]["perseason"] is False
    season = app.evaluate("window.__testHooks.data.seasons[0]")
    one = _url(app, f"?perseason=1&seasons={season}-{season}")["decoded"]
    assert one["perseason"] is False


def test_csort(app: Page) -> None:
    assert _url(app, "?csort=viewers")["decoded"]["csort"] == {"key": "viewers", "dir": "desc"}
    assert _url(app, "?csort=viewers")["encoded"] == "?csort=viewers"
    asc = _url(app, "?csort=viewers.asc")
    assert asc["decoded"]["csort"] == {"key": "viewers", "dir": "asc"}
    assert asc["encoded"] == "?csort=viewers.asc"
    assert _url(app, "?csort=games")["encoded"] == ""
    assert _url(app, "?csort=games.asc")["encoded"] == "?csort=games.asc"
    assert _url(app, "?csort=rank&cmode=pbp")["decoded"]["csort"] is None
    assert _url(app, "?csort=rank")["decoded"]["csort"] == {"key": "rank", "dir": "asc"}
    assert _url(app, "?csort=season")["decoded"]["csort"] is None
    assert _url(app, "?csort=season&perseason=1")["decoded"]["csort"] == {
        "key": "season",
        "dir": "asc",
    }
    assert _url(app, "?csort=bogus")["decoded"]["csort"] is None


def test_crews_params_survive_view_change(app: Page) -> None:
    key = _key(app)
    app.evaluate(
        "(k) => window.__testHooks.setState({crew: k, cmode: 'pbp', view: 'scatter'})", key
    )
    app.evaluate("() => window.__testHooks.setState({view: 'bars'})")
    s = app.evaluate("window.__testHooks.getState()")
    assert (s["crew"], s["cmode"], s["view"]) == (_key(app), "pbp", "bars")


# -- computeView wiring ----------------------------------------------------------------------

_VIEW_JS = """
async ({partial, probe}) => {
  const S = await import('./modules/select.js');
  const G = await import('./modules/crew-groups.js');
  const D = await import('./modules/data.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  const state = Object.assign(S.defaultState(data), partial);
  const view = S.computeView(data, state);
  const keys = probe ? null : G.crewIndex(data).keys;
  const pass = [];
  for (let i = 0; i < data.n; i += 1) if (view.passesFilters[i]) pass.push(i);
  return {
    highlighted: view.highlighted, matched: view.matched, hasSelection: view.hasSelection,
    hasPerson: view.hasPersonSelection, hasCrew: view.hasCrewSelection,
    total: view.summary.totalGames ?? null, summary: view.summary, facetTotal: view.facets.total,
    pass, keys, seasonCounts: view.seasonCounts, seasons: data.seasons,
    season: Array.from(data.t.season),
  };
}
"""


def test_crew_pick_highlights_its_games(app: Page) -> None:
    key = _key(app)
    out = app.evaluate(_VIEW_JS, {"partial": {"crew": key}, "probe": False})
    expect = [i for i in out["pass"] if out["keys"][i] == key]
    assert len(expect) == CASE_TRIO["games"]
    assert out["highlighted"] == expect
    assert out["matched"] == expect
    assert out["hasSelection"] and out["hasPerson"] and out["hasCrew"]
    assert out["facetTotal"] == len(expect)
    assert out["seasonCounts"] and sum(c for _, c in out["seasonCounts"]) == len(expect)


def test_crew_pick_respects_narrowed_seasons(app: Page) -> None:
    key = _key(app)
    full = app.evaluate(_VIEW_JS, {"partial": {"crew": key}, "probe": False})
    seasons = sorted({full["season"][i] for i in full["highlighted"]})
    assert len(seasons) == 1
    # Range covering the crew's season: unchanged. A range holding only another season: the pick
    # is kept in state (D-09) but highlights nothing.
    cover = app.evaluate(
        _VIEW_JS, {"partial": {"crew": key, "seasons": [seasons[0], seasons[0]]}, "probe": False}
    )
    assert cover["highlighted"] == full["highlighted"]
    other = next(s for s in full["seasons"] if s != seasons[0])
    out = app.evaluate(
        _VIEW_JS, {"partial": {"crew": key, "seasons": [other, other]}, "probe": False}
    )
    assert out["highlighted"] == [] and out["hasCrew"] is True


_PROBE_JS = """
async ({crew}) => {
  const S = await import('./modules/select.js');
  const U = await import('./modules/url-state.js');
  const D = await import('./modules/data.js');
  const raw = await (await fetch('site-data.json')).json();
  const real = D.prepareData(raw);
  let reads = 0;
  // crewIndex is the only reader of data.boothOf on these paths; count reads of it.
  const data = new Proxy(real, { get(t, k) { if (k === 'boothOf') reads += 1; return t[k]; } });
  const state = S.defaultState(data);
  U.decodeState('?view=bars&seasons=2024-2025', data);
  S.computeFacets(data, state);
  S.computeView(data, state);
  const idle = reads;
  S.computeView(data, Object.assign(S.defaultState(data), { crew }));
  return { idle, afterPick: reads };
}
"""


def test_no_crew_pick_does_no_grouping(app: Page) -> None:
    out = app.evaluate(_PROBE_JS, {"crew": _key(app)})
    assert out["idle"] == 0
    assert out["afterPick"] > 0


# -- setState exclusion and the live region --------------------------------------------------


def _status(page: Page) -> str:
    return page.locator("#pick-status").text_content() or ""


def _names(page: Page, ids: list[str]) -> list[str]:
    return list(
        page.evaluate(
            """(ids) => ids.map(
              (id) => window.__testHooks.data.lookups.people.find((p) => p.id === id).name)""",
            ids,
        )
    )


def test_pick_status_seat_is_a_hidden_polite_status(app: Page) -> None:
    seat = app.locator("#pick-status")
    assert seat.get_attribute("role") == "status"
    assert seat.get_attribute("aria-live") == "polite"
    assert "visually-hidden" in (seat.get_attribute("class") or "")


def test_crew_pick_clears_people_compare_together(app: Page) -> None:
    key = _key(app)
    a, b = _people(app)[:2]
    app.evaluate(
        "([a, b]) => window.__testHooks.setState({people: [a, b], compare: true, together: true})",
        [a, b],
    )
    s = app.evaluate("window.__testHooks.getState()")
    assert s["people"] == [a, b] and s["compare"] and s["together"]
    app.evaluate("(k) => window.__testHooks.setState({crew: k})", key)
    s = app.evaluate("window.__testHooks.getState()")
    assert (s["people"], s["compare"], s["together"], s["crew"]) == ([], False, False, key)
    assert app.evaluate("window.__testHooks.getView().hasCrewSelection") is True
    assert app.evaluate("window.__testHooks.getView().hasPersonSelection") is True
    crew_people = app.evaluate(
        """async (k) => (await import('./modules/crew-groups.js'))
          .crewIndex(window.__testHooks.data).crews.get(k).people""",
        key,
    )
    names = _names(app, crew_people)
    joined = f"{', '.join(names[:-1])} and {names[-1]}"
    assert _status(app) == (
        f"Crew pick set to {joined}. Announcers pick cleared."
        " Compare cleared. Called together cleared."
    )


def test_people_pick_clears_crew(app: Page) -> None:
    key = _key(app)
    x = _people(app)[0]
    app.evaluate("(k) => window.__testHooks.setState({crew: k})", key)
    assert _status(app).startswith("Crew pick set to ")
    app.evaluate("(x) => window.__testHooks.setState({people: [x]})", x)
    s = app.evaluate("window.__testHooks.getState()")
    assert s["people"] == [x] and s["crew"] is None
    assert _status(app) == f"Announcers pick set to {_names(app, [x])[0]}. Crew pick cleared."


def test_clear_messages(app: Page) -> None:
    key = _key(app)
    app.evaluate("(k) => window.__testHooks.setState({crew: k})", key)
    app.evaluate("() => window.__testHooks.setState({crew: null})")
    assert _status(app) == "Crew pick cleared."
    x = _people(app)[0]
    app.evaluate("(x) => window.__testHooks.setState({people: [x]})", x)
    app.evaluate("() => window.__testHooks.setState({people: []})")
    assert _status(app) == "Announcers pick cleared."


def test_has_crew_selection_hook_defaults_false(app: Page) -> None:
    assert app.evaluate("window.__testHooks.getView().hasCrewSelection") is False
