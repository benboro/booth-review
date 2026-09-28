"""In-browser proof of D-05..D-08, SITE-10, and SITE-12 semantics.

No app.js exists yet (plan 04-07's job), so these tests exercise the served
pure JS modules (data.js, select.js, url-state.js) directly via
`page.evaluate` -- RESEARCH Pattern 5 -- against the fixture served by
`guarded_page`/`site_url`. Every scenario below is worked out by hand against
`tests/fixtures/contract/site-data.fixture.json`'s 12 dots and 10 people.
"""

from __future__ import annotations

from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

_VIEW_JS = """
async (partial) => {
  const D = await import('./modules/data.js');
  const S = await import('./modules/select.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  const state = Object.assign(S.defaultState(data), partial);
  const view = S.computeView(data, state);
  return {
    highlighted: view.highlighted,
    visibleCount: view.visibleCount,
    altGames: Array.from(view.altGames).sort((a, b) => a - b),
    symbols: Object.fromEntries(Array.from(view.symbols.entries())),
  };
}
"""

_SEARCH_PEOPLE_JS = """
async (query) => {
  const D = await import('./modules/data.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  return D.searchPeople(data, query).map((r) => r.id);
}
"""

_ENCODE_DEFAULT_JS = """
async () => {
  const D = await import('./modules/data.js');
  const S = await import('./modules/select.js');
  const U = await import('./modules/url-state.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  return U.encodeState(S.defaultState(data), data);
}
"""

_ROUND_TRIP_JS = """
async (partial) => {
  const D = await import('./modules/data.js');
  const S = await import('./modules/select.js');
  const U = await import('./modules/url-state.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  const state = Object.assign(S.defaultState(data), partial);
  const encoded = U.encodeState(state, data);
  const decoded = U.decodeState(encoded, data);
  return { state, decoded, encoded };
}
"""


def _load(page: Page, site_url: str) -> None:
    page.goto(f"{site_url}/index.html")


def _view(page: Page, partial: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = page.evaluate(_VIEW_JS, partial)
    return result


def _highlighted(page: Page, partial: dict[str, Any]) -> list[int]:
    return _view(page, partial)["highlighted"]  # type: ignore[no-any-return]


def test_same_surname_people_stay_distinct(guarded_page: Page, site_url: str) -> None:
    """dale-harlow / dale-harlow-jr / kris-venn / jax-venn each highlight
    their own games, never a same-surname person's (the core promise)."""
    _load(guarded_page, site_url)
    assert _highlighted(guarded_page, {"people": ["dale-harlow"]}) == [0, 8]
    assert _highlighted(guarded_page, {"people": ["dale-harlow-jr"]}) == [0, 8]
    assert _highlighted(guarded_page, {"people": ["kris-venn"]}) == [1, 6, 9]
    assert _highlighted(guarded_page, {"people": ["jax-venn"]}) == [1, 9]


def test_alt_cast_matches_combined_feed_and_role_filters_main_feed_only(
    guarded_page: Page, site_url: str
) -> None:
    """D-08: taylor-vance's alt-cast appearance on the combined-feed dot 7
    matches with no role filter, but a PBP/analyst role filter only ever
    matches main-feed crew."""
    _load(guarded_page, site_url)
    view = _view(guarded_page, {"people": ["taylor-vance"]})
    assert view["highlighted"] == [5, 7]
    assert view["altGames"] == [7]
    assert _highlighted(guarded_page, {"people": ["taylor-vance"], "role": "pbp"}) == []
    assert _highlighted(guarded_page, {"people": ["taylor-vance"], "role": "analyst"}) == [5]


def test_sideline_role_unknown_never_matches_a_role_filter(
    guarded_page: Page, site_url: str
) -> None:
    """D-08: robin-teague's role is "unknown" (sideline); a role filter never
    matches them, with or without one set."""
    _load(guarded_page, site_url)
    assert _highlighted(guarded_page, {"people": ["robin-teague"], "role": "pbp"}) == []
    assert _highlighted(guarded_page, {"people": ["robin-teague"], "role": "analyst"}) == []
    assert _highlighted(guarded_page, {"people": ["robin-teague"]}) == [3, 8, 11]


def test_multi_person_or_default_and_together_mode_and_compare_symbols(
    guarded_page: Page, site_url: str
) -> None:
    """Multi-select is OR by default; "called together" (SITE-10) is an AND
    toggle; compare mode assigns each person a shape and shared games a
    distinct star (D-07)."""
    _load(guarded_page, site_url)
    view = _view(guarded_page, {"people": ["kris-venn", "sam-delgado"]})
    assert view["highlighted"] == [1, 2, 6, 9, 10]
    assert _highlighted(
        guarded_page, {"people": ["kris-venn", "sam-delgado"], "together": True}
    ) == [6]

    compare_view = _view(guarded_page, {"people": ["kris-venn", "sam-delgado"], "compare": True})
    assert compare_view["symbols"] == {
        "1": "circle",
        "2": "square",
        "6": "star",
        "9": "circle",
        "10": "square",
    }


def test_team_highlight_and_person_intersection(guarded_page: Page, site_url: str) -> None:
    """D-05: a team selection highlights every one of its games; combined
    with a person, the highlight is their intersection."""
    _load(guarded_page, site_url)
    assert _highlighted(guarded_page, {"team": "northfield"}) == [0, 4, 8]
    assert _highlighted(guarded_page, {"team": "northfield", "people": ["casey-lund"]}) == [4]


def test_hide_filters_remove_dots_and_shrink_visible_count(
    guarded_page: Page, site_url: str
) -> None:
    """D-05: season/network/slot filters hide dots (reduce visibleCount and
    intersect with highlighting); they never widen a person's own matches."""
    _load(guarded_page, site_url)
    net_view = _view(guarded_page, {"networks": ["net-a"], "people": ["dale-harlow"]})
    assert net_view["visibleCount"] == 3
    assert net_view["highlighted"] == [0, 8]

    slot_view = _view(guarded_page, {"slots": ["prime"]})
    assert slot_view["visibleCount"] == 4

    assert _highlighted(guarded_page, {"seasons": [2025, 2026], "people": ["dale-harlow"]}) == [8]


def test_search_people_matches_name_and_variant(guarded_page: Page, site_url: str) -> None:
    """Search matches canonical names and variants (accent/case-insensitive
    normalization lives in data.js)."""
    _load(guarded_page, site_url)
    assert guarded_page.evaluate(_SEARCH_PEOPLE_JS, "dale harlow") == [
        "dale-harlow",
        "dale-harlow-jr",
    ]
    result = guarded_page.evaluate(_SEARCH_PEOPLE_JS, "kristopher")
    assert result[0] == "kris-venn"


def test_url_state_round_trips(guarded_page: Page, site_url: str) -> None:
    """SITE-12: the default state encodes to '', and a fully-populated state
    round-trips through encodeState/decodeState unchanged."""
    _load(guarded_page, site_url)
    assert guarded_page.evaluate(_ENCODE_DEFAULT_JS) == ""

    full_state = {
        "people": ["kris-venn", "sam-delgado"],
        "compare": True,
        "together": True,
        "role": "analyst",
        "team": "northfield",
        "seasons": [2021, 2025],
        "networks": ["net-a", "net-b"],
        "slots": ["noon", "prime"],
        "axis": "excitement",
    }
    round_trip = guarded_page.evaluate(_ROUND_TRIP_JS, full_state)
    assert round_trip["encoded"] != ""
    assert round_trip["decoded"] == round_trip["state"]


_COMMA_ID_ROUND_TRIP_JS = """
async () => {
  const D = await import('./modules/data.js');
  const S = await import('./modules/select.js');
  const U = await import('./modules/url-state.js');
  const raw = await (await fetch('site-data.json')).json();
  raw.lookups.people[0].id = 'harlow,dale';
  const data = D.prepareData(raw);
  const state = Object.assign(S.defaultState(data), { people: ['harlow,dale', 'kris-venn'] });
  return U.decodeState(U.encodeState(state, data), data).people;
}
"""


@pytest.mark.parametrize(
    "query",
    [
        "?people=%25",
        "?team=%25",
        "?networks=%E0%A4%A",
        "?seasons=%&slot=%&mode=%&role=%&axis=%",
        "?%=x&people=dale-harlow,%25",
    ],
)
def test_crafted_url_never_breaks_the_app(guarded_page: Page, open_app: Any, query: str) -> None:
    """CR-01: a malformed percent-escape in any param drops just that value;
    the app still boots (no URIError from a second decode), and a valid id
    next to a malformed one is kept."""
    open_app(guarded_page, query)
    assert guarded_page.evaluate("window.__testHooks.failed") is None
    assert guarded_page.locator("#load-error").is_hidden()
    state = guarded_page.evaluate("window.__testHooks.getState()")
    assert state["people"] == (["dale-harlow"] if "dale-harlow" in query else [])
    assert state["team"] is None


def test_url_state_keeps_a_comma_inside_an_id(guarded_page: Page, site_url: str) -> None:
    """CR-01: list params split on the literal `,` before decoding, so an id
    whose own comma encodes to `%2C` round-trips as one id, not two."""
    _load(guarded_page, site_url)
    assert guarded_page.evaluate(_COMMA_ID_ROUND_TRIP_JS) == ["harlow,dale", "kris-venn"]
