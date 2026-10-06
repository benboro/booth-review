"""DOM-free proof of the named-game model and Game filter semantics
(SITE-44, SITE-45; 04.9 D-03..D-05, D-08, D-09, D-11, D-14, D-17, D-19, D-20).

Exercises the served pure JS modules (data.js, select.js, format.js) via
`page.evaluate` against the fixture. Every expectation is worked out by hand
from `tests/fixtures/contract/site-data.fixture.json` (12 dots).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from conftest import FIXTURE_GAMES
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

_GAMES_JS = """
async (mutation) => {
  const D = await import('./modules/data.js');
  const F = await import('./modules/format.js');
  const raw = await (await fetch('site-data.json')).json();
  if (mutation) new Function('raw', mutation)(raw);
  let data;
  try {
    data = D.prepareData(raw);
  } catch (e) {
    return { error: String(e.message) };
  }
  return {
    slugs: data.games.map((g) => g.slug),
    labels: data.games.map((g) => g.label),
    sections: data.games.map((g) => g.section),
    keys: Object.fromEntries(data.games.map((g) => [g.slug, g.keys])),
    teams: Object.fromEntries(data.games.map((g) => [g.slug, g.teams ?? null])),
    summitIndex: data.gameIndexBySlug.get('summit-bowl'),
    dotGames: data.dotGames,
    searchKeys: [
      D.gameSearchKey('Hawai\\u02BBi Bowl'),
      D.gameSearchKey("Duke's Mayo Bowl"),
      D.gameSearchKey('Duke\\u2019s Mayo Bowl'),
      D.gameSearchKey('Pop-Tarts Bowl'),
      D.gameSearchKey('  Rate   BOWL '),
    ],
    phrases: [
      F.gameTitlePhrase(data.games[data.gameIndexBySlug.get('harbor-bowl')]),
      F.gameTitlePhrase(data.games[data.gameIndexBySlug.get('bridge-game')]),
      F.gameTitlePhrase(data.games[data.gameIndexBySlug.get('lakeshore')]),
      F.gameTitlePhrase(data.games[data.gameIndexBySlug.get('cfp-semifinal')]),
      F.gameTitlePhrase(data.games[data.gameIndexBySlug.get('cfp-national-championship')]),
      F.gameTitlePhrase(data.games[data.gameIndexBySlug.get('cfp-quarterfinal')]),
      F.gameTitlePhrase(data.games[data.gameIndexBySlug.get('cfp-first-round')]),
    ],
  };
}
"""

_VIEW_JS = """
async (partial) => {
  const D = await import('./modules/data.js');
  const S = await import('./modules/select.js');
  const F = await import('./modules/format.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  const initial = S.defaultState(data);
  const state = Object.assign(S.defaultState(data), partial);
  const view = S.computeView(data, state);
  const passing = [];
  view.passesFilters.forEach((v, i) => { if (v) passing.push(i); });
  return {
    defaultGame: initial.game,
    state,
    passing,
    matched: view.matched,
    hasSelection: view.hasSelection,
    visibleCount: view.visibleCount,
    total: view.facets.total,
    games: Array.from(view.facets.games),
    summary: view.summary,
    copy: F.summaryCopy(view.summary),
  };
}
"""

_SLUGS = [
    "cfp-national-championship",
    "cfp-semifinal",
    "cfp-quarterfinal",
    "cfp-first-round",
    "harbor-bowl",
    "summit-bowl",
    "bridge-game",
    "lakeshore",
]

_REORDER = """
const f = raw.lookups.bowl_franchises;
const old = f.slice();
const byslug = Object.fromEntries(old.map((x, i) => [x.slug, i]));
const extra = [
  { slug: 'aloha-bowl', name: 'Aloha Bowl', former: [] },
  { slug: 'peach-bowl', name: 'Peach Bowl', former: [] },
  { slug: 'rose-bowl', name: 'Rose Bowl', former: [] },
];
const next = [...extra, old[byslug['harbor-bowl']], old[byslug['summit-bowl']]];
raw.lookups.bowls.forEach((b) => {
  b.franchise = next.findIndex((x) => x.slug === old[b.franchise].slug);
});
raw.lookups.bowl_franchises = next;
"""


def _games(page: Page, mutation: str = "") -> dict[str, Any]:
    result: dict[str, Any] = page.evaluate(_GAMES_JS, mutation)
    return result


def _view(page: Page, partial: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = page.evaluate(_VIEW_JS, partial)
    return result


@pytest.fixture
def loaded(guarded_page: Page, site_url: str) -> Page:
    guarded_page.goto(f"{site_url}/index.html")
    return guarded_page


def test_game_list_order_and_labels(loaded: Page) -> None:
    g = _games(loaded)
    assert g["slugs"] == _SLUGS
    assert g["sections"] == ["playoff"] * 4 + ["bowls"] * 2 + ["rivalries"] * 2
    assert g["labels"] == [
        "CFP National Championship",
        "CFP Semifinal",
        "CFP Quarterfinal",
        "CFP First Round",
        "Harbor Bowl",
        "Summit Bowl",
        "The Bridge Game",
        "Lakeshore Rivalry",
    ]


_RIVALRY_NAMES_JS = """
async (names) => {
  const D = await import('./modules/data.js');
  const raw = await (await fetch('site-data.json')).json();
  raw.lookups.rivalries.forEach((r, i) => { r.name = names[i]; });
  return D.prepareData(raw).games.filter((g) => g.section === 'rivalries')
    .map((g) => g.label);
}
"""


@pytest.mark.parametrize(
    ("names", "expected"),
    [
        # D-06: the key drops a leading "The ", the label is unchanged.
        (["The Zebra Cup", "Alpha Trophy"], ["Alpha Trophy", "The Zebra Cup"]),
        (["the Game", "Hat Trick"], ["the Game", "Hat Trick"]),
        (["Hat Trick", "the Game"], ["the Game", "Hat Trick"]),
    ],
)
def test_rivalries_sort_without_leading_the(
    loaded: Page, names: list[str], expected: list[str]
) -> None:
    assert loaded.evaluate(_RIVALRY_NAMES_JS, names) == expected


def test_slug_index_and_dot_memberships(loaded: Page) -> None:
    g = _games(loaded)
    assert g["summitIndex"] == 5
    dg = g["dotGames"]
    assert dg[5] == [1, 5]
    assert dg[7] == [4]
    assert dg[0] == [7]
    assert dg[4] == [7]
    assert dg[11] == [6]
    assert dg[3] == []


def test_new_years_six_first_then_alphabetical(loaded: Page) -> None:
    g = _games(loaded, _REORDER)
    assert g["slugs"][4:9] == [
        "rose-bowl",
        "peach-bowl",
        "aloha-bowl",
        "harbor-bowl",
        "summit-bowl",
    ]


def test_search_keys(loaded: Page) -> None:
    g = _games(loaded)
    assert g["searchKeys"] == [
        "hawaii bowl",
        "dukes mayo bowl",
        "dukes mayo bowl",
        "pop tarts bowl",
        "rate bowl",
    ]
    assert "bayside bowl" in g["keys"]["harbor-bowl"]
    assert "northfield" in g["keys"]["lakeshore"]
    assert "lakeview" in g["keys"]["lakeshore"]
    assert g["teams"]["lakeshore"] == ["Northfield", "Lakeview"]


_MATCH_JS = """
async (pairs) => {
  const D = await import('./modules/data.js');
  return pairs.map(([name, query]) =>
    D.gameKeyMatches(D.gameSearchKey(name), D.gameSearchKey(query)));
}
"""


@pytest.mark.parametrize(
    ("name", "query", "hit"),
    [
        # Separators read as spaces (WR-01): the natural spaced query finds the name.
        ("Pine-Ridge Game", "pine ridge", True),
        ("Glass-Jar Bowl", "glass jar", True),
        ("Plain, Old-Timey Feud", "plain old timey", True),
        ("Governor's Mug (NF\u2013LV)", "nf lv", True),
        # The hyphen-dropped and hyphenated spellings still match.
        ("Glass-Jar Bowl", "glassjar", True),
        ("Pine-Ridge Game", "pine-ridge", True),
        ("Plain, Old-Timey Feud", "oldtimey", True),
        # Apostrophes and the okina are still dropped, not spaced.
        ("Duke's Mayo Bowl", "dukes", True),
        ("Hawai\u02bbi Bowl", "hawaii", True),
        ("Glass-Jar Bowl", "jar glass", False),
        ("Pine-Ridge Game", "zzz", False),
    ],
)
def test_search_matches_spaced_and_hyphenated(
    loaded: Page, name: str, query: str, hit: bool
) -> None:
    assert loaded.evaluate(_MATCH_JS, [[name, query]]) == [hit]


_ROW_TITLE_JS = """
async () => {
  const F = await import('./modules/format.js');
  const riv = { label: 'Lakeshore Rivalry', teams: ['Northfield', 'Lakeview'] };
  const bowl = { label: 'Harbor Bowl' };
  return [
    F.gameRowTitle(riv, false),
    F.gameRowTitle(riv, true),
    F.gameRowTitle(bowl, false),
    F.gameRowTitle(bowl, true),
  ];
}
"""


def test_game_row_title(loaded: Page) -> None:
    assert loaded.evaluate(_ROW_TITLE_JS) == [
        "Northfield vs Lakeview",
        "Lakeshore Rivalry: Northfield vs Lakeview",
        None,
        "Harbor Bowl",
    ]


def test_title_phrases(loaded: Page) -> None:
    assert _games(loaded)["phrases"] == [
        "the Harbor Bowl",
        "The Bridge Game",
        "the Lakeshore Rivalry",
        "CFP semifinals",
        "CFP national championships",
        "CFP quarterfinals",
        "CFP first round games",
    ]


@pytest.mark.parametrize(
    ("mutation", "phrase"),
    [
        # Curated article (WR-02): a standalone or possessive name takes none.
        ("raw.lookups.rivalries[1].article = null;", "Lakeshore Rivalry"),
        (
            "raw.lookups.rivalries[1].article = null;"
            'raw.lookups.rivalries[1].name = "Old Pete\'s Paddle";',
            "Old Pete's Paddle",
        ),
        ("raw.lookups.rivalries[1].name = 'Lakeshore Brawl';", "the Lakeshore Brawl"),
    ],
)
def test_rivalry_title_phrase_follows_the_curated_article(
    loaded: Page, mutation: str, phrase: str
) -> None:
    assert _games(loaded, mutation)["phrases"][2] == phrase


@pytest.mark.parametrize(
    "mutation",
    [
        "delete raw.telecasts.rivalry;",
        "delete raw.lookups.bowl_franchises;",
        "delete raw.lookups.rivalries;",
    ],
)
def test_missing_v210_fields_throw(loaded: Page, mutation: str) -> None:
    assert "contract v2.1.0" in _games(loaded, mutation)["error"]


def test_default_state_and_facets(loaded: Page) -> None:
    v = _view(loaded, {})
    assert v["defaultGame"] is None
    # Harbor Bowl = 1 rated + unrated 16 (Bayside) = 2; Bridge Game = 1 rated + unrated 14 = 2
    assert v["games"] == [0, 1, 0, 0, 2, 1, 2, 2]
    assert v["matched"] == []
    assert v["hasSelection"] is False


def test_facets_postseason_exclude(loaded: Page) -> None:
    assert _view(loaded, {"postseason": "exclude"})["games"] == [
        0,
        0,
        0,
        0,
        0,
        0,
        2,
        2,  # rivalries have no postseason games, so both keep their 2 (rated + unrated)
    ]


def test_game_pick_fills_table_and_summary(loaded: Page) -> None:
    v = _view(loaded, {"game": "lakeshore"})
    assert v["passing"] == [0, 4]
    assert v["total"] == 2
    # Harbor Bowl = 1 rated + unrated 16 (Bayside) = 2; Bridge Game = 1 rated + unrated 14 = 2
    assert v["games"] == [0, 1, 0, 0, 2, 1, 2, 2]
    assert v["matched"] == [0, 4]
    assert v["hasSelection"] is True
    assert v["summary"]["kind"] == "matches"
    assert v["summary"]["count"] == 2
    assert v["summary"]["rated"] == 2  # matched games 0 and 4 are both rated (indices < 12)


@pytest.mark.parametrize("slug", ["cfp-semifinal", "summit-bowl"])
def test_bowl_hosted_semifinal_in_round_and_bowl(loaded: Page, slug: str) -> None:
    assert _view(loaded, {"game": slug})["passing"] == [5]


def test_fade_vs_hide(loaded: Page) -> None:
    assert _view(loaded, {"game": "lakeshore", "dots": "hide"})["visibleCount"] == 2
    assert (
        _view(loaded, {"game": "lakeshore"})["visibleCount"] == FIXTURE_GAMES
    )  # fade keeps all 12 rated + 8 unrated drawn


def test_game_ands_with_school_without_editing_it(loaded: Page) -> None:
    v = _view(loaded, {"game": "lakeshore", "school": ["northfield"]})
    assert v["passing"] == [0, 4]
    assert v["state"]["school"] == ["northfield"]
    v = _view(loaded, {"game": "bridge-game", "school": ["northfield"]})
    assert v["passing"] == []
    assert v["summary"]["kind"] == "filtered-out"
    assert v["summary"]["selectionLabel"] == "Northfield + The Bridge Game"


def test_no_game_match_copy_and_state_untouched(loaded: Page) -> None:
    v = _view(loaded, {"game": "summit-bowl", "postseason": "exclude"})
    assert v["passing"] == []
    assert v["summary"] == {"kind": "no-game-match", "phrase": "the Summit Bowl"}
    assert v["copy"]["detail"] == (
        "No games of the Summit Bowl match these filters. "
        "Widen the seasons or clear a filter to see games."
    )
    assert v["state"]["postseason"] == "exclude"
    assert v["state"]["game"] == "summit-bowl"


def test_unknown_slug_is_no_pick(loaded: Page) -> None:
    v = _view(loaded, {"game": "no-such-game"})
    assert len(v["passing"]) == FIXTURE_GAMES  # no pick: 12 rated + 8 unrated all pass


def test_hook_exposes_games_facet(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    games = guarded_page.evaluate("window.__testHooks.getView().facets.games")
    assert len(games) == 8
    assert all(isinstance(x, int) for x in games)


_URL_JS = """
async ({ search, partial }) => {
  const D = await import('./modules/data.js');
  const S = await import('./modules/select.js');
  const U = await import('./modules/url-state.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  const out = {};
  if (search !== null) {
    const st = U.decodeState(search, data);
    out.game = st.game;
    out.school = st.school;
    out.h2h = st.h2h;
    out.postseason = st.postseason;
  }
  if (partial !== null) {
    const st = Object.assign(S.defaultState(data), partial);
    out.encoded = U.encodeState(st, data);
    out.roundTrip = U.decodeState(out.encoded, data).game;
  }
  out.defaultEncoded = U.encodeState(S.defaultState(data), data);
  return out;
}
"""


def _url(page: Page, search: str | None, partial: dict[str, Any] | None) -> dict[str, Any]:
    result: dict[str, Any] = page.evaluate(_URL_JS, {"search": search, "partial": partial})
    return result


def test_game_encodes_only_when_picked(loaded: Page) -> None:
    r = _url(loaded, None, {"game": "harbor-bowl"})
    assert "game=harbor-bowl" in r["encoded"]
    assert r["encoded"].count("=") == 1
    assert "game" not in r["defaultEncoded"]


@pytest.mark.parametrize("slug", _SLUGS)
def test_game_round_trips(loaded: Page, slug: str) -> None:
    r = _url(loaded, f"?game={slug}", {"game": slug})
    assert r["game"] == slug
    assert r["roundTrip"] == slug


def test_game_keeps_other_params(loaded: Page) -> None:
    r = _url(loaded, "?game=lakeshore&school=northfield&h2h=1", None)
    assert r["game"] == "lakeshore"
    assert r["school"] == ["northfield"]
    assert r["h2h"] is False
    r = _url(loaded, "?game=harbor-bowl&postseason=exclude", None)
    assert r["game"] == "harbor-bowl"
    assert r["postseason"] == "exclude"


@pytest.mark.parametrize(
    "search",
    ["?game=nope", "?game=%3Cscript%3E", "?game=%", "?game=", "?game=Harbor-Bowl"],
)
def test_bad_game_decodes_to_no_pick(loaded: Page, search: str) -> None:
    assert _url(loaded, search, None)["game"] is None
