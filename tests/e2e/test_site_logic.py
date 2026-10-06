"""In-browser proof of D-08, SITE-10, SITE-12, and the D-10..D-19 filter/
fade/matched-games semantics (SITE-41 / 04.7 D-06, D-07: filters fade a
dot by default and hide it in Hide mode, Networks always hides; D-14: a
person-matched dot that fails a filter is filtered out, the filter wins;
D-09/D-10: era-correct conference membership; D-11: School is a fade filter,
not a highlight; D-12: the matched-games table fills on person-or-school;
D-17..D-19: game_type backs the bowl/playoff control and the time-slot label).

No app.js exists yet (plan 04-07's job), so these tests exercise the served
pure JS modules (data.js, select.js, format.js, url-state.js) directly via
`page.evaluate` -- RESEARCH Pattern 5 -- against the fixture served by
`guarded_page`/`site_url`. Every scenario below is worked out by hand against
`tests/fixtures/contract/site-data.fixture.json`'s 12 dots and 10 people.
"""

from __future__ import annotations

from typing import Any

import pytest
from conftest import FIXTURE_GAMES, FIXTURE_RATED, FIXTURE_UNRATED
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
    facets: view.facets === undefined ? null : {
      total: view.facets.total,
      seasons: Object.fromEntries(view.facets.seasons),
      networks: Array.from(view.facets.networks),
      slots: view.facets.slots,
      conferences: Object.fromEntries(view.facets.conferences),
      schools: Array.from(view.facets.schools),
      postseason: view.facets.postseason,
      role: view.facets.role,
      people: Array.from(view.facets.people),
    },
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
    their own games, never a same-surname person's (the core promise).
    Index 17 and 13 are unrated games that join the same indexed model."""
    _load(guarded_page, site_url)
    assert _highlighted(guarded_page, {"people": ["dale-harlow"]}) == [0, 8, 17]
    assert _highlighted(guarded_page, {"people": ["dale-harlow-jr"]}) == [0, 8, 17]
    assert _highlighted(guarded_page, {"people": ["kris-venn"]}) == [1, 6, 9, 13]
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
    assert view["highlighted"] == [1, 2, 6, 9, 10, 13, 16, 19]
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
        "13": "circle",
        "16": "square",
        "19": "square",
    }


def test_school_filter_fades_not_highlights(guarded_page: Page, site_url: str) -> None:
    """D-11: School is a multi-select, OR-within fade filter, not a
    highlight -- it fills the matched-games table on its own (D-12) but
    never highlights a dot (it fades by default, 04.7 D-06)."""
    _load(guarded_page, site_url)
    view = _view(guarded_page, {"school": ["northfield"]})
    assert view["passesFilters"] == [0, 4, 8, 13, 16]
    assert view["highlighted"] == []
    assert view["matched"] == [0, 4, 8, 13, 16]
    assert view["hasSelection"] is True
    assert view["hasPersonSelection"] is False

    or_view = _view(guarded_page, {"school": ["northfield", "maplecrest"]})
    assert or_view["passesFilters"] == [0, 3, 4, 7, 8, 11, 13, 14, 16]


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


def test_seasons_fade_by_default_hide_removes_and_networks_always_hides(
    guarded_page: Page, site_url: str
) -> None:
    """SITE-41 / 04.7 D-06, D-07: the season range fades by default (reversing
    04.1 D-13) and removes dots only in Hide mode; Networks hides in both."""
    _load(guarded_page, site_url)
    fade = _view(guarded_page, {"seasons": [2025, 2025]})
    assert fade["visibleCount"] == FIXTURE_GAMES
    assert fade["passingCount"] == 6
    assert fade["passesFilters"] == [4, 5, 6, 7, 17, 18]
    hide = _view(guarded_page, {"seasons": [2025, 2025], "dots": "hide"})
    assert hide["visibleCount"] == 6
    assert hide["passesFilters"] == [4, 5, 6, 7, 17, 18]

    for extra in ({}, {"dots": "hide"}):
        net_view = _view(guarded_page, {"networks": ["net-a"], **extra})
        assert net_view["visibleCount"] == 6
        assert net_view["passesFilters"] == [0, 4, 8, 13, 14, 19]


@pytest.mark.parametrize(
    ("patch", "passes"),
    [
        ({"slots": ["late"]}, [2]),
        ({"conferences": ["Big Ten"]}, [1, 4, 5, 8, 13]),
        ({"school": ["northfield"]}, [0, 4, 8, 13, 16]),
        ({"postseason": "only"}, [5, 7, 15, 16]),
        ({"seasons": [2025, 2025]}, [4, 5, 6, 7, 17, 18]),
    ],
)
def test_every_fade_filter_follows_the_switch(
    guarded_page: Page, site_url: str, patch: dict[str, Any], passes: list[int]
) -> None:
    """04.7 D-05, D-06: Fade draws every dot, Hide draws only passing dots;
    passesFilters, season counts, and facets never depend on the mode."""
    _load(guarded_page, site_url)
    fade = _view(guarded_page, {**patch})
    hide = _view(guarded_page, {**patch, "dots": "hide"})
    assert fade["passesFilters"] == passes
    assert fade["visibleCount"] == FIXTURE_GAMES
    assert hide["visibleCount"] == len(passes)
    assert hide["passesFilters"] == fade["passesFilters"]
    assert hide["seasonCounts"] == fade["seasonCounts"]
    assert hide["facets"] == fade["facets"]


def test_only_the_exact_hide_value_hides(guarded_page: Page, site_url: str) -> None:
    """04.7 D-10: any dots value other than the exact string 'hide' fades."""
    _load(guarded_page, site_url)
    assert (
        _view(guarded_page, {"dots": "bogus", "seasons": [2025, 2025]})["visibleCount"]
        == FIXTURE_GAMES
    )


def test_hide_keeps_passing_dots_that_are_not_the_announcers(
    guarded_page: Page, site_url: str
) -> None:
    """04.7 D-05: Hide removes only dots failing a filter; passing dots the
    selected announcer did not call stay drawn."""
    _load(guarded_page, site_url)
    partial = {"people": ["dale-harlow"], "seasons": [2026, 2026]}
    hide = _view(guarded_page, {**partial, "dots": "hide"})
    assert hide["visibleCount"] == 5
    assert hide["passesFilters"] == [8, 9, 10, 11, 19]
    assert hide["highlighted"] == [8]
    fade = _view(guarded_page, partial)
    assert fade["visibleCount"] == FIXTURE_GAMES
    assert fade["highlighted"] == [8]


_H2H = {"school": ["northfield", "lakeview"], "h2h": True}


def test_head_to_head_keeps_only_games_between_the_two_schools(
    guarded_page: Page, site_url: str
) -> None:
    """04.7 D-14, D-12: Head-to-head ANDs exactly two schools; a stale h2h
    with one or three schools behaves as Either team."""
    _load(guarded_page, site_url)
    view = _view(guarded_page, _H2H)
    assert view["passesFilters"] == [0, 4, 16]
    assert view["matched"] == [0, 4, 16]
    assert view["visibleCount"] == FIXTURE_GAMES
    assert _view(guarded_page, {**_H2H, "dots": "hide"})["visibleCount"] == 3
    assert _view(guarded_page, {**_H2H, "h2h": False})["passesFilters"] == [
        0,
        4,
        8,
        9,
        13,
        16,
        18,
    ]
    assert _view(guarded_page, {"school": ["northfield"], "h2h": True})["passesFilters"] == [
        0,
        4,
        8,
        13,
        16,
    ]
    three = {"school": ["northfield", "lakeview", "ironpeak"], "h2h": True}
    assert _view(guarded_page, three)["passesFilters"] == [
        0,
        1,
        4,
        5,
        8,
        9,
        13,
        15,
        16,
        18,
        19,
    ]


def test_head_to_head_person_highlight_stays_within_the_matchup(
    guarded_page: Page, site_url: str
) -> None:
    """04.7 D-14: person highlighting stacks on the head-to-head set."""
    _load(guarded_page, site_url)
    assert _view(guarded_page, {**_H2H, "people": ["casey-lund"]})["highlighted"] == [4]


def test_head_to_head_facets_school_counts_ignore_school_others_narrow(
    guarded_page: Page, site_url: str
) -> None:
    """04.7 D-14, 04.2 D-08: School's own counts ignore School; every other
    facet narrows to the head-to-head games."""
    _load(guarded_page, site_url)
    facets = _view(guarded_page, _H2H)["facets"]
    assert facets["schools"] == _view(guarded_page, {})["facets"]["schools"]
    assert facets["seasons"] == {"2019": 1, "2021": 1, "2025": 1, "2026": 0}
    assert facets["networks"] == [2, 1, 0, 0, 0]
    assert facets["total"] == 3


def test_conference_filter_or_within_era_correct_membership(
    guarded_page: Page, site_url: str
) -> None:
    """D-09/D-10: Northfield was Pac-12 in 2019 and Big Ten from 2025 --
    the fixture's own era-correct membership test case -- and the
    Conference filter is OR within a multi-select."""
    _load(guarded_page, site_url)
    assert _view(guarded_page, {"conferences": ["Big Ten"]})["passesFilters"] == [
        1,
        4,
        5,
        8,
        13,
    ]
    assert _view(guarded_page, {"conferences": ["Pac-12"]})["passesFilters"] == [0]
    assert _view(guarded_page, {"conferences": ["Big Ten", "Pac-12"]})["passesFilters"] == [
        0,
        1,
        4,
        5,
        8,
        13,
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
    game_type; excluded games fade (SITE-41 / 04.7 D-06)."""
    _load(guarded_page, site_url)
    excluded = _view(guarded_page, {"postseason": "exclude"})["passesFilters"]
    assert excluded == [i for i in range(FIXTURE_GAMES) if i not in (5, 7, 15, 16)]
    assert _view(guarded_page, {"postseason": "only"})["passesFilters"] == [5, 7, 15, 16]


def test_filter_wins_over_person_highlight(guarded_page: Page, site_url: str) -> None:
    """D-14: pat-rowan calls the playoff game at index 5, but it fails the
    postseason=exclude fade filter and is absent from highlighted -- the
    filter wins."""
    _load(guarded_page, site_url)
    view = _view(guarded_page, {"people": ["pat-rowan"], "postseason": "exclude"})
    assert view["highlighted"] == [2, 10, 19]
    assert 5 not in view["highlighted"]


def test_matched_fills_on_school_alone_not_other_filters(guarded_page: Page, site_url: str) -> None:
    """D-12: the matched-games table fills when School is set even with no
    person selected; Conference/Networks/Kickoff/Bowls-Playoffs alone never
    fill it (no-bulk rule)."""
    _load(guarded_page, site_url)
    assert _view(guarded_page, {"school": ["northfield"]})["matched"] == [0, 4, 8, 13, 16]
    assert _view(guarded_page, {"conferences": ["Big Ten"]})["matched"] == []
    assert _view(guarded_page, {"networks": ["net-a"]})["matched"] == []
    assert _view(guarded_page, {"postseason": "only"})["matched"] == []


def test_role_never_fades_only_limits_person_matching(guarded_page: Page, site_url: str) -> None:
    """04.7 D-06: Role stays what it is today -- it limits how a person matches,
    never which dots pass the fade filters, with or without a person
    selected."""
    _load(guarded_page, site_url)
    unfiltered = _view(guarded_page, {})["passesFilters"]
    assert _view(guarded_page, {"role": "analyst"})["passesFilters"] == unfiltered


def test_season_counts_use_fade_filters_and_ignore_season_range(
    guarded_page: Page, site_url: str
) -> None:
    """Per-season counts count only dots passing the non-season filters, and
    the season range itself never changes them, in Fade or Hide (04.7 D-06)."""
    _load(guarded_page, site_url)
    net_counts = dict(_view(guarded_page, {"networks": ["net-a"]})["seasonCounts"])
    assert net_counts == {2019: 1, 2021: 2, 2025: 1, 2026: 2}

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


def test_game_type_kind(guarded_page: Page, site_url: str) -> None:
    """A1: gameTypeKind is the DOM-free enum behind the icon: null for a
    regular-season game, 'playoff' for a CFP game, 'bowl' for any other
    postseason game."""
    _load(guarded_page, site_url)
    assert guarded_page.evaluate(_FORMAT_JS, ["gameTypeKind", 0]) is None
    assert guarded_page.evaluate(_FORMAT_JS, ["gameTypeKind", 5]) == "playoff"
    assert guarded_page.evaluate(_FORMAT_JS, ["gameTypeKind", 7]) == "bowl"
    # IN-01: kind and label come from one helper, so they never disagree.
    assert guarded_page.evaluate(_FORMAT_JS, ["gameTypeInfo", 0]) is None
    assert guarded_page.evaluate(_FORMAT_JS, ["gameTypeInfo", 5]) == {
        "kind": "playoff",
        "label": "CFP semifinal",
        "atBowl": True,
    }
    assert guarded_page.evaluate(_FORMAT_JS, ["gameTypeInfo", 7]) == {
        "kind": "bowl",
        "label": "Bowl",
        "atBowl": False,
    }


_GAME_TYPE_VARIANT_JS = """
async ([gameType, round]) => {
  const D = await import('./modules/data.js');
  const F = await import('./modules/format.js');
  const raw = await (await fetch('site-data.json')).json();
  raw.telecasts.game_type[0] = gameType;
  raw.telecasts.playoff_round[0] = round;
  const data = D.prepareData(raw);
  return F.gameTypeInfo(data, 0);
}
"""


@pytest.mark.parametrize(
    ("game_type", "round_", "label", "at_bowl"),
    [
        ("playoff", "first_round", "CFP first round", False),
        ("playoff", "quarterfinal", "CFP quarterfinal", True),
        ("playoff", "semifinal", "CFP semifinal", True),
        ("playoff", "championship", "CFP championship", False),
        ("playoff", None, "College Football Playoff", False),
        ("bowl", None, "Bowl", False),
    ],
)
def test_game_type_at_bowl_rule(
    guarded_page: Page,
    site_url: str,
    game_type: str,
    round_: str | None,
    label: str,
    at_bowl: bool,
) -> None:
    """F3: a CFP quarterfinal or semifinal is played at a New Year's Six bowl,
    so `atBowl` is true for exactly those two rounds. First-round games are on
    campus, the championship is its own site, and a playoff game with no
    recorded round is never assumed to be at a bowl. A non-CFP bowl is the
    'bowl' kind already, so `atBowl` stays false (no second icon)."""
    _load(guarded_page, site_url)
    info = guarded_page.evaluate(_GAME_TYPE_VARIANT_JS, [game_type, round_])
    assert info == {
        "kind": "bowl" if game_type == "bowl" else "playoff",
        "label": label,
        "atBowl": at_bowl,
    }


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
    assert sorted(result["once"]) == ["net-a", "net-c", "net-d", "net-e"]
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


def test_dots_and_h2h_round_trip_and_are_omitted_at_default(
    guarded_page: Page, site_url: str
) -> None:
    """04.7 D-10, D-14: dots=hide and h2h=1 round-trip; the defaults omit both
    and h2h is never encoded without exactly two schools."""
    _load(guarded_page, site_url)
    assert guarded_page.evaluate(_ENCODE_DEFAULT_JS) == ""

    hide = guarded_page.evaluate(_ROUND_TRIP_JS, {"dots": "hide"})
    assert hide["encoded"] == "?dots=hide"
    assert hide["decoded"]["dots"] == "hide"
    assert guarded_page.evaluate(_ROUND_TRIP_JS, {"dots": "fade"})["encoded"] == ""

    both = guarded_page.evaluate(
        _ROUND_TRIP_JS, {"school": ["northfield", "lakeview"], "h2h": True}
    )
    assert both["encoded"] == "?school=northfield,lakeview&h2h=1"
    assert both["decoded"]["h2h"] is True

    for school in (["northfield"], ["northfield", "lakeview", "ironpeak"]):
        stale = guarded_page.evaluate(_ROUND_TRIP_JS, {"school": school, "h2h": True})
        assert "h2h" not in stale["encoded"]
        assert stale["decoded"]["h2h"] is False


@pytest.mark.parametrize(
    ("query", "key", "expected"),
    [
        ("?h2h=1&school=northfield", "h2h", False),
        ("?h2h=yes&school=northfield,lakeview", "h2h", False),
        ("?h2h=1&school=northfield,nowhere", "h2h", False),
        ("?h2h=1&school=lakeview,northfield", "h2h", True),
        ("?team=lakeview&school=northfield&h2h=1", "h2h", True),
        ("?dots=bogus", "dots", "fade"),
        ("?dots=HIDE", "dots", "fade"),
        ("?dots=", "dots", "fade"),
        ("?dots=hide", "dots", "hide"),
    ],
)
def test_decode_allowlists_dots_and_h2h(
    guarded_page: Page, site_url: str, query: str, key: str, expected: Any
) -> None:
    """T-04.7-01: dots is 'hide' only for the literal 'hide'; h2h is true only
    for the literal '1' with exactly two valid schools."""
    _load(guarded_page, site_url)
    assert guarded_page.evaluate(_DECODE_SEARCH_JS, query)[key] == expected


_SNAP_BACK_JS = """
async () => {
  const D = await import('./modules/data.js');
  const S = await import('./modules/select.js');
  const U = await import('./modules/url-state.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  const setState = (state, school) =>
    U.decodeState(U.encodeState({ ...state, school }, data), data);
  const base = Object.assign(S.defaultState(data), {
    school: ['northfield', 'lakeview'],
    h2h: true,
  });
  const three = setState(base, ['northfield', 'lakeview', 'ironpeak']);
  const back = setState(three, ['northfield', 'lakeview']);
  const removed = setState(base, ['northfield']);
  return { start: setState(base, base.school).h2h, three: three.h2h, back: back.h2h,
           removed: removed.h2h };
}
"""


def test_head_to_head_snaps_back_when_the_school_count_changes(
    guarded_page: Page, site_url: str
) -> None:
    """04.7 D-12: a third school or a removal drops h2h through the setState
    round trip, and re-adding a second school does not restore it."""
    _load(guarded_page, site_url)
    result = guarded_page.evaluate(_SNAP_BACK_JS)
    assert result == {"start": True, "three": False, "back": False, "removed": False}


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
    assert view["matched"] == [0, 4, 8, 13, 16]


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
        "?h2h=1&school=northfield",
        "?dots=bogus",
        "?dots=hide&h2h=1",
        "?h2h=1&school=northfield,lakeview,ironpeak",
        "?h2h=1&dots=hide&school=northfield,lakeview&seasons=2025-2025&networks=none",
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
    if "northfield" not in query:
        assert state["school"] == []


def test_url_state_keeps_a_comma_inside_an_id(guarded_page: Page, site_url: str) -> None:
    """CR-01: list params split on the literal `,` before decoding, so an id
    whose own comma encodes to `%2C` round-trips as one id, not two."""
    _load(guarded_page, site_url)
    assert guarded_page.evaluate(_COMMA_ID_ROUND_TRIP_JS) == ["harlow,dale", "kris-venn"]


def test_summary_networks_ordered_by_matched_count_then_alphabetical(
    guarded_page: Page, site_url: str
) -> None:
    """A6: networks list dominant first (matched-telecast count desc), ties alphabetical."""
    _load(guarded_page, site_url)
    pat = _view(guarded_page, {"people": ["pat-rowan"]})["summary"]["networks"]
    # Pat: Beta 2 (rated 5, unrated 16), Conference 2 (rated 2, 10), Alpha 1, Stream Plus 1.
    assert pat == ["Beta Network", "Conference Network", "Alpha Sports", "Stream Plus"]
    robin = _view(guarded_page, {"people": ["robin-teague"]})["summary"]["networks"]
    assert robin == ["Other Network", "Alpha Sports"]
    tie = _view(guarded_page, {"people": ["jamie-oaks"]})["summary"]["networks"]
    # Jamie: Alpha 2 (rated 4, unrated 14), Other 1 (rated 7).
    assert tie == ["Alpha Sports", "Other Network"]


_SUMMARY_COPY_JS = """
async (summary) => {
  const F = await import('./modules/format.js');
  return F.summaryCopy(summary);
}
"""


@pytest.mark.parametrize(
    ("partial", "kind", "count", "rated"),
    [
        # No filter or selection: every game, 12 rated of 20.
        ({}, "all", FIXTURE_GAMES, FIXTURE_RATED),
        # Networks = [net-e] (Stream Plus): unrated games 15 and 18 only.
        ({"networks": ["net-e"]}, "matches", 2, 0),
        # School Northfield: rated 0, 4, 8 plus unrated 13 (U1), 16 (U4) -> 5 games.
        ({"school": ["northfield"]}, "matches", 5, 3),
        # net-a: rated 0, 4, 8 plus unrated 13, 14, 19 -> 6 games.
        ({"networks": ["net-a"]}, "matches", 6, 3),
        # Season 2025: rated 4-7 plus unrated 17 (U5), 18 (U6) -> 6 games.
        ({"seasons": [2025, 2025]}, "matches", 6, 4),
        # Dale Harlow: rated 0, 8 plus unrated 17 -> 3 games; with 2026 only: 8.
        ({"people": ["dale-harlow"]}, "matches", 3, 2),
        ({"people": ["dale-harlow"], "seasons": [2026, 2026]}, "matches", 1, 1),
        # Morgan Ash is on unrated game 13 only; Stream Plus is on unrated 15 and 18.
        ({"people": ["morgan-ash"]}, "matches", 1, 0),
    ],
)
def test_summary_reads_n_of_m_whenever_a_filter_is_active(
    guarded_page: Page,
    site_url: str,
    partial: dict[str, Any],
    kind: str,
    count: int,
    rated: int,
) -> None:
    """04.13 D-07: `count` is every passing game, `rated` the rated subset."""
    _load(guarded_page, site_url)
    summary = _view(guarded_page, partial)["summary"]
    assert summary["kind"] == kind
    assert summary["count"] == count
    assert summary["rated"] == rated
    assert "of" not in summary


_NO_GAMES_PERSON_JS = """
async () => {
  const D = await import('./modules/data.js');
  const S = await import('./modules/select.js');
  const raw = await (await fetch('site-data.json')).json();
  raw.lookups.people.push({
    id: 'nobody-here', name: 'Nobody Here', variants: ['Nobody Here'], usual_role: 'pbp',
  });
  const data = D.prepareData(raw);
  const state = Object.assign(S.defaultState(data), { people: ['nobody-here'] });
  return S.computeView(data, state).summary;
}
"""


def test_person_with_no_games_gets_the_no_games_summary(guarded_page: Page, site_url: str) -> None:
    """04.13 D-07: only a person with no games at all reads 'has no games'."""
    _load(guarded_page, site_url)
    summary = guarded_page.evaluate(_NO_GAMES_PERSON_JS)
    assert summary == {"kind": "no-rated", "name": "Nobody Here"}
    assert guarded_page.evaluate(_SUMMARY_COPY_JS, summary)["detail"] == (
        "Nobody Here has no games in this sample."
    )


def test_role_alone_is_not_a_filter_for_the_summary(guarded_page: Page, site_url: str) -> None:
    """Role alone leaves the summary at the all-games view."""
    _load(guarded_page, site_url)
    everything = {"kind": "all", "count": FIXTURE_GAMES, "rated": FIXTURE_RATED}
    assert _view(guarded_page, {})["summary"] == everything
    assert _view(guarded_page, {"role": "pbp"})["summary"] == everything


def test_summary_shows_for_filters_alone_without_filling_the_table(
    guarded_page: Page, site_url: str
) -> None:
    """04.7 D-09: filter-only states get a summary; matched stays empty (no-bulk rule)."""
    _load(guarded_page, site_url)
    view = _view(guarded_page, {"networks": ["net-a"]})
    summary = view["summary"]
    assert view["matched"] == []
    assert summary["count"] == 6  # net-a: rated 0, 4, 8 plus unrated 13, 14, 19
    assert summary["rated"] == 3
    assert "of" not in summary
    assert (summary["seasonMin"], summary["seasonMax"]) == (2019, 2026)
    assert summary["networks"] == ["Alpha Sports"]


def test_fade_and_hide_give_the_same_summary(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    fade = _view(guarded_page, {"seasons": [2025, 2025]})["summary"]
    hide = _view(guarded_page, {"seasons": [2025, 2025], "dots": "hide"})["summary"]
    assert fade == hide


def test_filter_only_zero_matches_has_its_own_kind(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    summary = _view(guarded_page, {"slots": ["late"], "postseason": "only"})["summary"]
    assert summary["kind"] == "no-filter-match"


def test_head_to_head_selection_label_names_the_matchup(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    state = {"school": ["northfield", "lakeview"], "h2h": True, "people": ["kris-venn"]}
    summary = _view(guarded_page, state)["summary"]
    assert summary == {
        "kind": "filtered-out",
        "selectionLabel": "Kris Venn + Northfield vs Lakeview",
    }
    summary = _view(guarded_page, {**state, "h2h": False})["summary"]
    assert summary["kind"] == "matches"
    assert summary["count"] == 2
    assert "of" not in summary


def test_summary_copy_formats_n_of_m(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    base = {"kind": "matches", "seasonMin": 2014, "seasonMax": 2025, "networks": ["ESPN", "FOX"]}
    big = {**base, "count": 10583, "rated": 3491, "altCount": 0}
    assert guarded_page.evaluate(_SUMMARY_COPY_JS, big) == {
        "count": "3,491 rated of 10,583 games",
        "detail": "2014\u20132025 \u00b7 ESPN, FOX",
    }
    one = {**base, "count": 1, "rated": 1, "altCount": 0}
    assert guarded_page.evaluate(_SUMMARY_COPY_JS, one)["count"] == "1 rated of 1 game"
    zero = {**base, "count": 1, "rated": 0, "altCount": 0}
    assert guarded_page.evaluate(_SUMMARY_COPY_JS, zero)["count"] == "0 rated of 1 game"
    two = {**base, "count": 2, "rated": 0, "altCount": 0}
    assert guarded_page.evaluate(_SUMMARY_COPY_JS, two)["count"] == "0 rated of 2 games"
    everything = {"kind": "all", "count": 20, "rated": 12}
    assert guarded_page.evaluate(_SUMMARY_COPY_JS, everything) == {
        "count": "12 rated of 20 games",
        "detail": "",
    }
    assert guarded_page.evaluate(_SUMMARY_COPY_JS, {"kind": "no-filter-match"}) == {
        "count": "",
        "detail": "No games match these filters.",
    }
    no_games = guarded_page.evaluate(_SUMMARY_COPY_JS, {"kind": "no-rated", "name": "Pat Doe"})
    assert no_games == {"count": "", "detail": "Pat Doe has no games in this sample."}
    for summary in (big, everything, {"kind": "no-filter-match"}):
        copy = guarded_page.evaluate(_SUMMARY_COPY_JS, summary)
        assert "telecast" not in copy["count"] + copy["detail"]


def test_summary_copy_caps_a_long_network_list(guarded_page: Page, site_url: str) -> None:
    """WR-01: a broad filter can pass games on many networks; the detail names the
    first three (most telecasts first) and counts the rest, so it never wraps the
    selection band. Three or fewer are listed in full."""
    _load(guarded_page, site_url)
    base = {"kind": "matches", "seasonMin": 2014, "seasonMax": 2025, "count": 900, "rated": 400}
    three = {**base, "networks": ["ESPN", "FOX", "ABC"], "altCount": 0}
    assert guarded_page.evaluate(_SUMMARY_COPY_JS, three)["detail"] == (
        "2014\u20132025 \u00b7 ESPN, FOX, ABC"
    )
    networks = ["ESPN", "FOX", "ABC", "CBS", "NBC", "FS1", "ESPN2"]
    many = {**base, "networks": networks, "altCount": 2}
    assert guarded_page.evaluate(_SUMMARY_COPY_JS, many)["detail"] == (
        "2014\u20132025 \u00b7 ESPN, FOX, ABC +4 more \u00b7 includes 2 alt-cast games"
    )


def _facets(page: Page, partial: dict[str, Any]) -> dict[str, Any]:
    facets = _view(page, partial)["facets"]
    assert facets is not None, "view.facets is missing"
    return facets  # type: ignore[no-any-return]


def test_facet_default_state_counts(guarded_page: Page, site_url: str) -> None:
    """Default state: every telecast counts once in each facet (D-12)."""
    _load(guarded_page, site_url)
    facets = _facets(guarded_page, {})
    assert facets["total"] == FIXTURE_GAMES
    assert facets["networks"] == [6, 5, 4, 3, 2]
    assert facets["postseason"] == {"all": 20, "exclude": 16, "only": 4}
    assert facets["seasons"] == {"2019": 3, "2021": 6, "2025": 6, "2026": 5}
    assert facets["slots"] == {"noon": 5, "afternoon": 6, "prime": 7, "late": 1}
    assert facets["role"] == {"pbp": 17, "analyst": 15}


def test_facet_selected_person_narrows_other_facets_not_people(
    guarded_page: Page, site_url: str
) -> None:
    """D-09: dale-harlow (dots 0 and 8 on net-a, unrated dot 17 on net-c) narrows every facet but
    the People facet, which ignores the person constraint."""
    _load(guarded_page, site_url)
    default = _facets(guarded_page, {})
    facets = _facets(guarded_page, {"people": ["dale-harlow"]})
    assert facets["total"] == 3
    assert facets["networks"] == [2, 0, 1, 0, 0]
    assert facets["seasons"] == {"2019": 1, "2021": 0, "2025": 1, "2026": 1}
    assert facets["people"] == default["people"]


def test_facet_ignores_only_its_own_constraint(guarded_page: Page, site_url: str) -> None:
    """D-08: checking a network never changes the Networks counts but does
    change every other facet's."""
    _load(guarded_page, site_url)
    default = _facets(guarded_page, {})
    facets = _facets(guarded_page, {"networks": ["net-b"]})
    assert facets["networks"] == default["networks"]
    assert facets["seasons"] == {"2019": 2, "2021": 1, "2025": 1, "2026": 1}
    assert facets["total"] == 5


def test_facet_union_versus_together_versus_compare(guarded_page: Page, site_url: str) -> None:
    """D-10: several announcers are a union by default and in compare mode,
    an intersection in called-together mode."""
    _load(guarded_page, site_url)
    people = ["dale-harlow", "robin-teague"]
    union = _facets(guarded_page, {"people": people})
    together = _facets(guarded_page, {"people": people, "together": True})
    compare = _facets(guarded_page, {"people": people, "compare": True})
    assert union["networks"] == [2, 0, 1, 2, 0]
    assert together["networks"] == [1, 0, 0, 0, 0]
    assert compare["networks"] == union["networks"]


def test_facet_role_limits_person_match_and_role_facet_ignores_state_role(
    guarded_page: Page, site_url: str
) -> None:
    """D-10: pat-rowan is play-by-play on dots 2, 5, 10 and unrated 15, 16, 19; Role limits how the
    person matches, and the Role facet reports both roles regardless."""
    _load(guarded_page, site_url)
    as_pbp = _facets(guarded_page, {"people": ["pat-rowan"], "role": "pbp"})
    as_analyst = _facets(guarded_page, {"people": ["pat-rowan"], "role": "analyst"})
    assert as_pbp["networks"] == [1, 2, 2, 0, 1]
    assert as_analyst["networks"] == [0, 0, 0, 0, 0]
    assert as_pbp["role"] == {"pbp": 6, "analyst": 0}
    assert as_analyst["role"] == as_pbp["role"]


def test_facet_season_range_constrains_other_facets_only(guarded_page: Page, site_url: str) -> None:
    """A season range narrows non-season facets; the Seasons facet ignores it."""
    _load(guarded_page, site_url)
    facets = _facets(guarded_page, {"seasons": [2019, 2019]})
    assert facets["networks"] == [1, 2, 0, 0, 0]
    assert facets["seasons"] == {"2019": 3, "2021": 6, "2025": 6, "2026": 5}


def test_facet_season_counts_derive_from_seasons_facet(guarded_page: Page, site_url: str) -> None:
    """seasonCounts is the Seasons facet, so it is person-aware (D-14)."""
    _load(guarded_page, site_url)
    view = _view(guarded_page, {"people": ["dale-harlow"]})
    assert dict(view["seasonCounts"]) == {2019: 1, 2021: 0, 2025: 1, 2026: 1}
    for season, count in view["seasonCounts"]:
        assert view["facets"]["seasons"][str(season)] == count


def test_facet_people_counts_reflect_other_filters(guarded_page: Page, site_url: str) -> None:
    """People counts are telecasts per person under the other filters."""
    _load(guarded_page, site_url)
    facets = _facets(guarded_page, {"networks": ["net-a"]})
    # net-a dots are 0, 4, 8, 13, 14, 19: people 0,1 (dots 0, 8), 7,8 (dots 4, 14),
    # 6 (dot 8), 2,10 (dot 13), 4,5 (dot 19).
    assert facets["people"] == [2, 2, 1, 0, 1, 1, 1, 2, 2, 0, 1]


def test_named_game_info_and_rivalry_name(guarded_page: Page, site_url: str) -> None:
    """D-10/D-12: one DOM-free helper names every named game: a rivalry by its
    name, a bowl by its core name, a CFP game at a bowl by core + round."""
    _load(guarded_page, site_url)
    named = "namedGameInfo"
    assert guarded_page.evaluate(_FORMAT_JS, [named, 0]) == {
        "icons": ["rivalry"],
        "text": "Lakeshore Rivalry",
    }
    assert guarded_page.evaluate(_FORMAT_JS, [named, 11]) == {
        "icons": ["rivalry"],
        "text": "The Bridge Game",
    }
    assert guarded_page.evaluate(_FORMAT_JS, [named, 7]) == {
        "icons": ["bowl"],
        "text": "Harbor Bowl",
    }
    assert guarded_page.evaluate(_FORMAT_JS, [named, 5]) == {
        "icons": ["bowl", "playoff"],
        "text": "Summit Bowl · CFP semifinal",
    }
    assert guarded_page.evaluate(_FORMAT_JS, [named, 1]) is None
    assert guarded_page.evaluate(_FORMAT_JS, [named, 3]) is None
    assert guarded_page.evaluate(_FORMAT_JS, ["rivalryName", 0]) == "Lakeshore Rivalry"
    assert guarded_page.evaluate(_FORMAT_JS, ["rivalryName", 3]) is None


_NAMED_VARIANT_JS = """
async ([index, field, value]) => {
  const D = await import('./modules/data.js');
  const F = await import('./modules/format.js');
  const raw = await (await fetch('site-data.json')).json();
  raw.telecasts[field][index] = value;
  const data = D.prepareData(raw);
  return F.namedGameInfo(data, index);
}
"""


@pytest.mark.parametrize(
    ("index", "field", "value", "expected"),
    [
        (7, "bowl", None, {"icons": ["bowl"], "text": "Bowl"}),
        (5, "playoff_round", "first_round", {"icons": ["playoff"], "text": "CFP first round"}),
        (5, "playoff_round", None, {"icons": ["playoff"], "text": "College Football Playoff"}),
    ],
)
def test_named_game_info_fallbacks(
    guarded_page: Page,
    site_url: str,
    index: int,
    field: str,
    value: Any,
    expected: dict[str, Any],
) -> None:
    """An unknown bowl falls back to 'Bowl'; a CFP game not at a bowl shows the
    round label alone."""
    _load(guarded_page, site_url)
    assert guarded_page.evaluate(_NAMED_VARIANT_JS, [index, field, value]) == expected


_MERGE_JS = """
async () => {
  const D = await import('./modules/data.js');
  const raw = await (await fetch('site-data.json')).json();
  const a = D.prepareData(raw);
  const b = D.prepareData(raw);
  const lens = Object.values(a.t).map((c) => c.length);
  return {
    n: a.n, nRated: a.nRated, rated: Array.from(a.rated),
    lensOk: lens.every((l) => l === a.n),
    viewers: a.t.viewers, rawViewers: raw.telecasts.viewers,
    rrUrls15: a.t.rr_urls[15], flags15: a.t.flags[15],
    cause: a.t.cause, jitter: a.jitter, jitter2: b.jitter,
    rawLen: raw.telecasts.season.length,
    viewersMin: a.viewersMin, viewersMax: a.viewersMax,
    xs: a.xRange.spread, xe: a.xRange.excitement,
    ratedMin: Math.min(...raw.telecasts.viewers.filter((v) => v != null)),
    ratedMax: Math.max(...raw.telecasts.viewers.filter((v) => v != null)),
  };
}
"""

_MISSING_BLOCK_JS = """
async () => {
  const D = await import('./modules/data.js');
  const raw = await (await fetch('site-data.json')).json();
  delete raw.telecasts_unrated;
  try { D.prepareData(raw); return null; } catch (e) { return e.message; }
}
"""

_CAUSE_JS = """
async () => {
  const D = await import('./modules/data.js');
  const F = await import('./modules/format.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  return {
    c: [0, 12, 13, 15, 17, 19].map((i) => F.causeText(data, i)),
    line: F.noRatingLine(data, 12),
    fv: F.formatViewers(null),
  };
}
"""

_FIGURE_JS = """
async () => {
  const D = await import('./modules/data.js');
  const S = await import('./modules/select.js');
  const C = await import('./modules/chart.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  const state = S.defaultState(data);
  const view = S.computeView(data, state);
  const fig = C.buildFigure(data, view, state, { theme: 'light', mobile: false, revision: 1 });
  return fig.traces.reduce((acc, tr) => acc + (Array.isArray(tr.x) ? tr.x.length : 0), 0);
}
"""


def test_prepare_merges_unrated_block(guarded_page: Page, site_url: str) -> None:
    """Rated indices stay put; the 8 unrated games append with a rated mask and cause."""
    _load(guarded_page, site_url)
    r = guarded_page.evaluate(_MERGE_JS)
    assert r["n"] == FIXTURE_GAMES
    assert r["nRated"] == FIXTURE_RATED
    assert r["rated"] == [1] * FIXTURE_RATED + [0] * FIXTURE_UNRATED
    assert r["lensOk"]
    assert r["rawLen"] == FIXTURE_RATED
    assert r["viewers"][:FIXTURE_RATED] == r["rawViewers"]
    assert r["viewers"][FIXTURE_RATED:] == [None] * FIXTURE_UNRATED
    assert r["rrUrls15"] == []
    assert r["flags15"] == []
    assert r["cause"][:FIXTURE_RATED] == [None] * FIXTURE_RATED
    assert r["cause"][FIXTURE_RATED:] == [
        "none",
        "rr_dip",
        "rr_dip",
        "rarely_rated",
        "rr_dip",
        "rarely_rated",
        "rarely_rated",
        "pending",
    ]
    assert r["viewersMin"] == r["ratedMin"]
    assert r["viewersMax"] == r["ratedMax"]
    assert r["xs"] == [-14, 7]
    assert r["xe"] == [3.0, 9.9]


def test_unrated_jitter_is_fixed(guarded_page: Page, site_url: str) -> None:
    """D-05: jitter is null for rated games, in [0, 1) for unrated, same on every load."""
    _load(guarded_page, site_url)
    r = guarded_page.evaluate(_MERGE_JS)
    assert r["jitter"] == r["jitter2"]
    assert r["jitter"][:FIXTURE_RATED] == [None] * FIXTURE_RATED
    tail = r["jitter"][FIXTURE_RATED:]
    assert all(isinstance(v, float) and 0 <= v < 1 for v in tail)
    assert len(set(tail)) > 1


def test_prepare_rejects_missing_unrated_block(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    msg = guarded_page.evaluate(_MISSING_BLOCK_JS)
    assert msg is not None
    assert "telecasts_unrated" in msg
    assert "v2.2.0" in msg


def test_cause_wording_and_format_viewers_null(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    r = guarded_page.evaluate(_CAUSE_JS)
    assert r["c"] == [
        None,
        "no figure was published",
        "few figures were compiled for 2021\u201324",
        "Stream Plus games are rarely rated",
        "Conference Network games are rarely rated",
        "viewership not posted yet",
    ]
    assert r["line"] == "No public rating \u00b7 no figure was published"
    assert r["fv"] == "No public rating"


def test_scatter_draws_only_rated_dots(guarded_page: Page, site_url: str) -> None:
    """Until the band exists the figure holds exactly the rated dots."""
    _load(guarded_page, site_url)
    assert guarded_page.evaluate(_FIGURE_JS) == FIXTURE_RATED
