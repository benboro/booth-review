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
      D.gameSearchKey('Hawaiʻi Bowl'),
      D.gameSearchKey("Duke's Mayo Bowl"),
      D.gameSearchKey('Duke’s Mayo Bowl'),
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
    "lakeshore",
    "bridge-game",
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
        "Lakeshore Rivalry",
        "The Bridge Game",
    ]


def test_slug_index_and_dot_memberships(loaded: Page) -> None:
    g = _games(loaded)
    assert g["summitIndex"] == 5
    dg = g["dotGames"]
    assert dg[5] == [1, 5]
    assert dg[7] == [4]
    assert dg[0] == [6]
    assert dg[4] == [6]
    assert dg[11] == [7]
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
        "poptarts bowl",
        "rate bowl",
    ]
    assert "bayside bowl" in g["keys"]["harbor-bowl"]
    assert "northfield" in g["keys"]["lakeshore"]
    assert "lakeview" in g["keys"]["lakeshore"]
    assert g["teams"]["lakeshore"] == ["Northfield", "Lakeview"]


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
    assert v["games"] == [0, 1, 0, 0, 1, 1, 2, 1]
    assert v["matched"] == []
    assert v["hasSelection"] is False


def test_facets_postseason_exclude(loaded: Page) -> None:
    assert _view(loaded, {"postseason": "exclude"})["games"] == [0, 0, 0, 0, 0, 0, 2, 1]


def test_game_pick_fills_table_and_summary(loaded: Page) -> None:
    v = _view(loaded, {"game": "lakeshore"})
    assert v["passing"] == [0, 4]
    assert v["total"] == 2
    assert v["games"] == [0, 1, 0, 0, 1, 1, 2, 1]
    assert v["matched"] == [0, 4]
    assert v["hasSelection"] is True
    assert v["summary"]["kind"] == "matches"
    assert v["summary"]["count"] == 2
    assert v["summary"]["of"] == 12


@pytest.mark.parametrize("slug", ["cfp-semifinal", "summit-bowl"])
def test_bowl_hosted_semifinal_in_round_and_bowl(loaded: Page, slug: str) -> None:
    assert _view(loaded, {"game": slug})["passing"] == [5]


def test_fade_vs_hide(loaded: Page) -> None:
    assert _view(loaded, {"game": "lakeshore", "dots": "hide"})["visibleCount"] == 2
    assert _view(loaded, {"game": "lakeshore"})["visibleCount"] == 12


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
        "No telecasts of the Summit Bowl match these filters. "
        "Widen the seasons or clear a filter to see games."
    )
    assert v["state"]["postseason"] == "exclude"
    assert v["state"]["game"] == "summit-bowl"


def test_unknown_slug_is_no_pick(loaded: Page) -> None:
    v = _view(loaded, {"game": "no-such-game"})
    assert len(v["passing"]) == 12


def test_hook_exposes_games_facet(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    games = guarded_page.evaluate("window.__testHooks.getView().facets.games")
    assert len(games) == 8
    assert all(isinstance(x, int) for x in games)
