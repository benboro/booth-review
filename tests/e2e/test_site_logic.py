"""In-browser proof of D-08, SITE-10, SITE-12, and the D-10..D-19 filter/
fade/matched-games semantics (D-13: only the season range removes a dot;
every other filter fades one; D-14: a person-matched dot that fails a fade
filter is filtered out, the filter wins; D-09/D-10: era-correct conference
membership; D-11: School is a fade filter, not a highlight; D-12: the
matched-games table fills on person-or-school; D-17..D-19: game_type backs
the bowl/playoff control and the time-slot label).

No app.js exists yet (plan 04-07's job), so these tests exercise the served
pure JS modules (data.js, select.js, format.js, url-state.js) directly via
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
  const passesFilters = [];
  view.passesFilters.forEach((v, i) => { if (v) passesFilters.push(i); });
  return {
    highlighted: view.highlighted,
    matched: view.matched,
    visibleCount: view.visibleCount,
    passingCount: view.passingCount,
    passesFilters,
    hasSelection: view.hasSelection,
    hasPersonSelection: view.hasPersonSelection,
    altGames: Array.from(view.altGames).sort((a, b) => a - b),
    symbols: Object.fromEntries(Array.from(view.symbols.entries())),
    seasonCounts: view.seasonCounts,
    summary: view.summary,
  };
}
"""

_FORMAT_JS = """
async ([fnName, i]) => {
  const D = await import('./modules/data.js');
  const F = await import('./modules/format.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  return F[fnName](data, i);
}
"""

_FBS_CONFERENCES_JS = """
async () => {
  const D = await import('./modules/data.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  return data.fbsConferences;
}
"""

_TOGGLE_FAMILY_JS = """
async (family) => {
  const D = await import('./modules/data.js');
  const S = await import('./modules/select.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  const state = S.defaultState(data);
  const once = S.toggleFamilyNetworks(data, state, family);
  const twice = S.toggleFamilyNetworks(data, { ...state, networks: once }, family);
  const allIds = data.primaryNetworks.map((idx) => data.lookups.networks[idx].id).sort();
  return { once, twiceIsAllIds: [...twice].sort().join(',') === allIds.join(',') };
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


def test_school_filter_fades_not_highlights(guarded_page: Page, site_url: str) -> None:
    """D-11: School is a multi-select, OR-within fade filter, not a
    highlight -- it fills the matched-games table on its own (D-12) but
    never highlights a dot."""
    _load(guarded_page, site_url)
    view = _view(guarded_page, {"school": ["northfield"]})
    assert view["passesFilters"] == [0, 4, 8]
    assert view["highlighted"] == []
    assert view["matched"] == [0, 4, 8]
    assert view["hasSelection"] is True
    assert view["hasPersonSelection"] is False

    or_view = _view(guarded_page, {"school": ["northfield", "maplecrest"]})
    assert or_view["passesFilters"] == [0, 3, 4, 7, 8, 11]


def test_school_and_person_combine_highlight_within_school(
    guarded_page: Page, site_url: str
) -> None:
    """D-11: person highlighting still stacks on top of a School fade
    filter -- highlighted is that person's games within the school's
    passing set, and matched mirrors highlighted whenever a person is
    selected (D-12)."""
    _load(guarded_page, site_url)
    view = _view(guarded_page, {"school": ["northfield"], "people": ["casey-lund"]})
    assert view["highlighted"] == [4]
    assert view["matched"] == view["highlighted"]


def test_season_range_is_the_only_filter_that_removes_dots(
    guarded_page: Page, site_url: str
) -> None:
    """D-13: the season range shrinks visibleCount; every other filter
    leaves visibleCount at 12 and only narrows passesFilters, never
    removing a dot."""
    _load(guarded_page, site_url)
    season_view = _view(guarded_page, {"seasons": [2025, 2025]})
    assert season_view["visibleCount"] == 4

    net_view = _view(guarded_page, {"networks": ["net-a"]})
    assert net_view["visibleCount"] == 12
    assert net_view["passesFilters"] == [0, 4, 8]


def test_conference_filter_or_within_era_correct_membership(
    guarded_page: Page, site_url: str
) -> None:
    """D-09/D-10: Northfield was Pac-12 in 2019 and Big Ten from 2025 --
    the fixture's own era-correct membership test case -- and the
    Conference filter is OR within a multi-select."""
    _load(guarded_page, site_url)
    assert _view(guarded_page, {"conferences": ["Big Ten"]})["passesFilters"] == [1, 4, 5, 8]
    assert _view(guarded_page, {"conferences": ["Pac-12"]})["passesFilters"] == [0]
    assert _view(guarded_page, {"conferences": ["Big Ten", "Pac-12"]})["passesFilters"] == [
        0,
        1,
        4,
        5,
        8,
    ]


def test_fcs_conference_never_listed(guarded_page: Page, site_url: str) -> None:
    """D-10: fbsConferences holds only FBS conferences (plus FBS
    Independents); the fixture's Missouri Valley (is_fbs false) is left
    out, and the list is alphabetical."""
    _load(guarded_page, site_url)
    fbs_conferences = guarded_page.evaluate(_FBS_CONFERENCES_JS)
    assert "Missouri Valley" not in fbs_conferences
    assert fbs_conferences == sorted(fbs_conferences)
    assert "Big Ten" in fbs_conferences
    assert "FBS Independents" in fbs_conferences


def test_postseason_exclude_and_only(guarded_page: Page, site_url: str) -> None:
    """D-17/D-18: the three-way Bowls/Playoffs control is backed by
    game_type; excluded games fade, per D-13."""
    _load(guarded_page, site_url)
    excluded = _view(guarded_page, {"postseason": "exclude"})["passesFilters"]
    assert excluded == [i for i in range(12) if i not in (5, 7)]
    assert _view(guarded_page, {"postseason": "only"})["passesFilters"] == [5, 7]


def test_filter_wins_over_person_highlight(guarded_page: Page, site_url: str) -> None:
    """D-14: pat-rowan calls the playoff game at index 5, but it fails the
    postseason=exclude fade filter and is absent from highlighted -- the
    filter wins."""
    _load(guarded_page, site_url)
    view = _view(guarded_page, {"people": ["pat-rowan"], "postseason": "exclude"})
    assert view["highlighted"] == [2, 10]
    assert 5 not in view["highlighted"]


def test_matched_fills_on_school_alone_not_other_filters(guarded_page: Page, site_url: str) -> None:
    """D-12: the matched-games table fills when School is set even with no
    person selected; Conference/Networks/Kickoff/Bowls-Playoffs alone never
    fill it (no-bulk rule)."""
    _load(guarded_page, site_url)
    assert _view(guarded_page, {"school": ["northfield"]})["matched"] == [0, 4, 8]
    assert _view(guarded_page, {"conferences": ["Big Ten"]})["matched"] == []
    assert _view(guarded_page, {"networks": ["net-a"]})["matched"] == []
    assert _view(guarded_page, {"postseason": "only"})["matched"] == []


def test_role_never_fades_only_limits_person_matching(guarded_page: Page, site_url: str) -> None:
    """D-13: Role stays what it is today -- it limits how a person matches,
    never which dots pass the fade filters, with or without a person
    selected."""
    _load(guarded_page, site_url)
    unfiltered = _view(guarded_page, {})["passesFilters"]
    assert _view(guarded_page, {"role": "analyst"})["passesFilters"] == unfiltered


def test_season_counts_use_fade_filters_and_ignore_season_range(
    guarded_page: Page, site_url: str
) -> None:
    """Per-season counts count only dots passing the fade filters, and the
    season range itself never changes them."""
    _load(guarded_page, site_url)
    net_counts = dict(_view(guarded_page, {"networks": ["net-a"]})["seasonCounts"])
    assert net_counts == {2019: 1, 2021: 0, 2025: 1, 2026: 1}

    unfiltered_counts = _view(guarded_page, {})["seasonCounts"]
    ranged_counts = _view(guarded_page, {"seasons": [2025, 2025]})["seasonCounts"]
    assert unfiltered_counts == ranged_counts


def test_shows_time_slot_gates_on_game_type_and_saturday(guarded_page: Page, site_url: str) -> None:
    """D-19: the time-slot label shows only for a regular-season Saturday
    game, via one shared helper -- never a Saturday bowl/playoff game or a
    non-Saturday game, and never with no recorded slot."""
    _load(guarded_page, site_url)
    assert guarded_page.evaluate(_FORMAT_JS, ["showsTimeSlot", 0]) is True
    assert guarded_page.evaluate(_FORMAT_JS, ["showsTimeSlot", 2]) is True
    assert guarded_page.evaluate(_FORMAT_JS, ["showsTimeSlot", 7]) is False
    assert guarded_page.evaluate(_FORMAT_JS, ["showsTimeSlot", 5]) is False
    assert guarded_page.evaluate(_FORMAT_JS, ["showsTimeSlot", 3]) is False


def test_late_slot_labels(guarded_page: Page, site_url: str) -> None:
    """D-20: the After dark slot's short and long labels."""
    _load(guarded_page, site_url)
    result = guarded_page.evaluate(
        """
        async () => {
          const F = await import('./modules/format.js');
          return { short: F.SLOT_SHORT_LABELS.late, long: F.SLOT_LABELS.late };
        }
        """
    )
    assert result["short"] == "After dark"
    assert result["long"] == "After dark (10 PM ET or later)"


def test_game_type_label(guarded_page: Page, site_url: str) -> None:
    """D-17: the panel's game-type label distinguishes a CFP round from a
    plain bowl, and is omitted (null) for a regular-season game."""
    _load(guarded_page, site_url)
    assert guarded_page.evaluate(_FORMAT_JS, ["gameTypeLabel", 5]) == "CFP semifinal"
    assert guarded_page.evaluate(_FORMAT_JS, ["gameTypeLabel", 7]) == "Bowl"
    assert guarded_page.evaluate(_FORMAT_JS, ["gameTypeLabel", 0]) is None


def test_conference_line_is_away_first(guarded_page: Page, site_url: str) -> None:
    """D-09: the panel's conference row reads away vs. home, matching
    formatMatchup's "Away at Home" order (amended 2026-09-28)."""
    _load(guarded_page, site_url)
    assert guarded_page.evaluate(_FORMAT_JS, ["conferenceLine", 0]) == "SEC vs Pac-12"


def test_toggle_family_networks_matches_legend_click_semantics(
    guarded_page: Page, site_url: str
) -> None:
    """D-16: toggleFamilyNetworks reproduces the app's legend-click handling
    exactly, so a legend chip and the Networks filter checklist always
    agree."""
    _load(guarded_page, site_url)
    result = guarded_page.evaluate(_TOGGLE_FAMILY_JS, "fox")
    assert sorted(result["once"]) == ["net-a", "net-c", "net-d"]
    assert result["twiceIsAllIds"] is True


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
    -- including the new conferences/school/postseason params, no team --
    round-trips through encodeState/decodeState unchanged."""
    _load(guarded_page, site_url)
    assert guarded_page.evaluate(_ENCODE_DEFAULT_JS) == ""

    full_state = {
        "people": ["kris-venn", "sam-delgado"],
        "compare": True,
        "together": True,
        "role": "analyst",
        "conferences": ["Big Ten", "Pac-12"],
        "school": ["northfield", "lakeview"],
        "postseason": "exclude",
        "seasons": [2021, 2025],
        "networks": ["net-a", "net-b"],
        "slots": ["noon", "prime", "late"],
        "axis": "excitement",
    }
    round_trip = guarded_page.evaluate(_ROUND_TRIP_JS, full_state)
    assert round_trip["encoded"] != ""
    assert round_trip["decoded"] == round_trip["state"]
    assert "team=" not in round_trip["encoded"]


_CONFERENCES_ROUND_TRIP_JS = """
async (partial) => {
  const D = await import('./modules/data.js');
  const S = await import('./modules/select.js');
  const U = await import('./modules/url-state.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  const state = Object.assign(S.defaultState(data), partial);
  const encoded = U.encodeState(state, data);
  return { encoded, decoded: U.decodeState(encoded, data) };
}
"""


def test_conferences_encode_in_fbs_conferences_order(guarded_page: Page, site_url: str) -> None:
    """D-10: conferences encode/decode ordered by data.fbsConferences, not
    selection order."""
    _load(guarded_page, site_url)
    result = guarded_page.evaluate(
        _CONFERENCES_ROUND_TRIP_JS, {"conferences": ["Pac-12", "Big Ten"]}
    )
    assert result["encoded"] == "?conferences=Big%20Ten,Pac-12"
    assert result["decoded"]["conferences"] == ["Big Ten", "Pac-12"]


def test_school_encodes_in_team_index_order(guarded_page: Page, site_url: str) -> None:
    """D-11: school encodes/decodes ordered by team index."""
    _load(guarded_page, site_url)
    result = guarded_page.evaluate(
        _CONFERENCES_ROUND_TRIP_JS, {"school": ["lakeview", "northfield"]}
    )
    assert result["encoded"] == "?school=northfield,lakeview"
    assert result["decoded"]["school"] == ["northfield", "lakeview"]


_DECODE_SEARCH_JS = """
async (search) => {
  const D = await import('./modules/data.js');
  const U = await import('./modules/url-state.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  return U.decodeState(search, data);
}
"""


def test_decode_conferences_reorders_to_fbs_conferences_order(
    guarded_page: Page, site_url: str
) -> None:
    """D-10: a raw conferences value in any order reorders to fbsConferences
    order on decode, and `+` reads as a space (form encoding)."""
    _load(guarded_page, site_url)
    decoded = guarded_page.evaluate(_DECODE_SEARCH_JS, "?conferences=SEC,Big+Ten")
    assert decoded["conferences"] == ["Big Ten", "SEC"]


def test_decode_slot_drops_unknown_values(guarded_page: Page, site_url: str) -> None:
    """D-20/T-04.1-22: `late` is accepted only through the SLOT_ORDER
    allowlist; an unrecognized value is dropped, and an all-unrecognized
    param decodes to null (no filter)."""
    _load(guarded_page, site_url)
    assert guarded_page.evaluate(_DECODE_SEARCH_JS, "?slot=late,bogus")["slots"] == ["late"]
    assert guarded_page.evaluate(_DECODE_SEARCH_JS, "?slot=bogus")["slots"] is None


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("?conferences=Missouri%20Valley", []),
        ("?conferences=%", []),
        ("?school=../x", []),
    ],
)
def test_decode_conferences_and_school_never_throw_on_bad_input(
    guarded_page: Page, open_app: Any, query: str, expected: list[str]
) -> None:
    """T-04.1-05: an FCS conference, a malformed escape, and a path-shaped
    school value all decode to an empty list rather than throwing or
    matching anything."""
    open_app(guarded_page, query)
    state = guarded_page.evaluate("window.__testHooks.getState()")
    key = "conferences" if "conferences" in query else "school"
    assert state[key] == expected


def test_legacy_team_link_migrates_to_school_fade_not_highlight(
    guarded_page: Page, open_app: Any
) -> None:
    """Pitfall 4: an old `?team=<slug>` link decodes into a one-element
    school selection -- fading other games, never highlighting -- through
    the identical path a fresh School selection takes."""
    open_app(guarded_page, "?team=northfield")
    state = guarded_page.evaluate("window.__testHooks.getState()")
    assert state["school"] == ["northfield"]
    view = guarded_page.evaluate("window.__testHooks.getView()")
    assert view["highlighted"] == []
    assert view["matched"] == [0, 4, 8]


def test_legacy_team_unions_with_a_fresh_school_param_legacy_first(
    guarded_page: Page, open_app: Any
) -> None:
    """Pitfall 4: `?team=northfield&school=lakeview` unions both into
    school, legacy first."""
    open_app(guarded_page, "?team=northfield&school=lakeview")
    state = guarded_page.evaluate("window.__testHooks.getState()")
    assert state["school"] == ["northfield", "lakeview"]


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
        "?conferences=%",
        "?conferences=Missouri%20Valley",
        "?school=../x",
        "?postseason=%3Cscript%3E",
        "?team=nope&school=%",
    ],
)
def test_crafted_url_never_breaks_the_app(guarded_page: Page, open_app: Any, query: str) -> None:
    """CR-01/T-04.1-05: a malformed percent-escape in any param drops just
    that value; the app still boots (no URIError from a second decode), and
    a valid id next to a malformed one is kept."""
    open_app(guarded_page, query)
    assert guarded_page.evaluate("window.__testHooks.failed") is None
    assert guarded_page.locator("#load-error").is_hidden()
    state = guarded_page.evaluate("window.__testHooks.getState()")
    assert state["people"] == (["dale-harlow"] if "dale-harlow" in query else [])
    assert state["school"] == []


def test_url_state_keeps_a_comma_inside_an_id(guarded_page: Page, site_url: str) -> None:
    """CR-01: list params split on the literal `,` before decoding, so an id
    whose own comma encodes to `%2C` round-trips as one id, not two."""
    _load(guarded_page, site_url)
    assert guarded_page.evaluate(_COMMA_ID_ROUND_TRIP_JS) == ["harlow,dale", "kris-venn"]
