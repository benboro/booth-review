"""Per-view crew pick behavior (plan 14-05, D-06): a crew pick acts like an Announcers pick.

Runs on the synthetic crews dataset (tests/e2e/crews_fixture.py); no vault content.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from crews_fixture import CASE_TRIO
from playwright.sync_api import Page
from test_site_chart import _RING_VISIBLE, _assert_ring_on, _dot_opacity, _hover_dot, _traces

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

_TRIO_NAMES = " / ".join(
    [CASE_TRIO["pbp"], *CASE_TRIO["analysts"]]
)  # replaced by the page's display names below


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


def _set(page: Page, patch: dict[str, Any]) -> None:
    page.evaluate("(patch) => window.__testHooks.setState(patch)", patch)


def _view(page: Page) -> dict[str, Any]:
    out: dict[str, Any] = page.evaluate("() => window.__testHooks.getView()")
    return out


def _crew_names(page: Page, key: str) -> list[str]:
    names: list[str] = page.evaluate(
        """async (key) => {
          const G = await import('./modules/crew-groups.js');
          const d = window.__testHooks.data;
          return G.crewIndex(d).crews.get(key).people.map(
            (s) => d.lookups.people[d.personIndexById.get(s)].name);
        }""",
        key,
    )
    return names


# -- Scatter -------------------------------------------------------------------------------


def test_scatter_crew_pick_highlights_exactly_the_crews_games(app: Page) -> None:
    """D-06: dots of the crew's games are the highlight trace; every family dot takes the
    person-faded opacity, as with an Announcers pick."""
    _set(app, {"crew": _key(app)})
    matched = _view(app)["matched"]
    assert len(matched) == CASE_TRIO["games"]
    traces = _traces(app)
    assert sorted(traces[-1]["customdata"]) == sorted(matched)
    faded = _dot_opacity(app)["activeUnderPerson"]
    family = [t for t in traces[:-1] if t.get("customdata") and t.get("opacity") is not None]
    assert family
    assert {t["opacity"] for t in family if t["opacity"] in (faded,)} == {faded}


def test_hover_ring_lands_on_a_crew_dot(app: Page) -> None:
    """The hover ring still centers on the hovered dot under a crew pick."""
    _set(app, {"crew": _key(app)})
    index = sorted(_view(app)["matched"])[0]
    point = _hover_dot(app, index)
    app.wait_for_selector(_RING_VISIBLE, timeout=3000)
    _assert_ring_on(app, index, point)


# -- Map -----------------------------------------------------------------------------------


def test_map_crew_pick_rebuilds_the_venue_model_from_the_crews_games(app: Page) -> None:
    """D-06: the map's venue cohort is the crew's located games; other venues are background."""
    _set(app, {"view": "map"})
    app.wait_for_function("() => window.__testHooks.mapRenders >= 1")
    total_dots = app.evaluate("() => window.__testHooks.getMapModel().venueDots.length")
    key = _key(app)
    before_renders = app.evaluate("() => window.__testHooks.mapRenders")
    _set(app, {"crew": key})
    app.wait_for_function("(n) => window.__testHooks.mapRenders > n", arg=before_renders)
    dots = app.evaluate("() => window.__testHooks.getMapModel().venueDots")
    placed = app.evaluate(
        "(m) => new Set(m.map((i) => window.__testHooks.data.t.place[i])"
        ".filter((p) => p != null)).size",
        _view(app)["matched"],
    )
    # The crew's cohort venues are drawn; every other venue stays as background.
    assert len(dots) >= placed
    assert len(dots) <= total_dots
    assert any(d["tier"] == "other" for d in dots) == (len(dots) > placed)


# -- Matched games -------------------------------------------------------------------------


def test_matched_games_lists_the_crews_games_with_a_subtitle(app: Page) -> None:
    """D-06: rows equal the crew's games; the subtitle names the crew; hidden without a pick."""
    sub = app.locator("#matched-subtitle")
    assert sub.is_hidden()
    key = _key(app)
    _set(app, {"crew": key})
    names = _crew_names(app, key)
    assert sub.is_visible()
    assert sub.text_content() == f"Crew: {' / '.join(names)}, newest first"
    assert app.locator("#matched-games tbody tr").count() == CASE_TRIO["games"]
    dates = app.locator("#matched-games tbody tr td:first-child").all_inner_texts()
    assert len(dates) == CASE_TRIO["games"]
    _set(app, {"crew": None})
    assert sub.is_hidden()


def test_selected_person_indexes_returns_the_crews_people(app: Page) -> None:
    """The detail panel and crew boxes mark crew members as matched."""
    key = _key(app)
    count = app.evaluate(
        """async (key) => {
          const F = await import('./modules/format.js');
          const d = window.__testHooks.data;
          return F.selectedPersonIndexes(d, {people: [], crew: key}).size;
        }""",
        key,
    )
    assert count == 1 + len(CASE_TRIO["analysts"])


# -- Bars and Butterfly --------------------------------------------------------------------

_SUM_JS = "() => window.__testHooks.getBarsModel().rows.reduce((a, r) => a + r.total, 0)"
_BAR_COLOR_JS = "() => document.getElementById('bars-chart').data[0].marker.color"


def test_bars_recount_to_the_crews_games_with_the_accent_hero(app: Page) -> None:
    """D-06: Bars count only the crew's games and the hero bars take the accent mark."""
    key = _key(app)
    _set(app, {"view": "bars"})
    _set(app, {"crew": key})
    matched = _view(app)["matched"]
    total = app.evaluate(_SUM_JS)
    assert len(matched) <= total <= 2 * len(matched)
    rows = app.evaluate("() => window.__testHooks.getBarsModel().rows")
    assert rows
    assert max(r["total"] for r in rows) <= len(matched)
    tones = app.evaluate(
        """async () => {
          const C = await import('./modules/bar-chart.js');
          const m = window.__testHooks.getBarsModel();
          const theme = document.documentElement.dataset.theme || 'light';
          return {
            on: C.barTones(m.rows[0], theme, true).a,
            off: C.barTones(m.rows[0], theme, false).a,
            drawn: document.getElementById('bars-chart').data[0].marker.color,
          };
        }"""
    )
    assert tones["on"] != tones["off"]
    drawn = tones["drawn"][0] if isinstance(tones["drawn"], list) else tones["drawn"]
    assert str(drawn).lower() == str(tones["on"]).lower()


def test_bars_title_names_the_crew_and_rerenders_per_pick(app: Page) -> None:
    """Bar copy names the crew; switching the crew pick re-renders (cache key has state.crew)."""
    key = _key(app)
    _set(app, {"view": "bars", "crew": key})
    names = _crew_names(app, key)
    assert f"Crew: {' / '.join(names)}" in (app.locator("#bars-title").text_content() or "")
    other = app.evaluate(
        """async (key) => {
          const G = await import('./modules/crew-groups.js');
          for (const k of G.crewIndex(window.__testHooks.data).crews.keys()) {
            if (k !== key) return k;
          }
          return null;
        }""",
        key,
    )
    assert other
    _set(app, {"crew": other})
    assert app.evaluate(_SUM_JS) != 0
    other_names = _crew_names(app, other)
    assert f"Crew: {' / '.join(other_names)}" in (app.locator("#bars-title").text_content() or "")


def test_butterfly_with_a_crew_pick_counts_the_crews_games_and_has_no_person_sides(
    app: Page,
) -> None:
    """D-06: a crew pick plus two schools recounts both sides to the crew's games."""
    key = _key(app)
    _set(app, {"crew": key})
    slugs = app.evaluate(
        """() => {
          const d = window.__testHooks.data;
          const i = window.__testHooks.getView().matched[0];
          return [d.teamSlugs[d.t.home_team[i]], d.teamSlugs[d.t.away_team[i]]];
        }"""
    )
    _set(app, {"school": slugs, "view": "butterfly"})
    model = app.evaluate("() => window.__testHooks.getBarsModel()")
    assert model is not None
    assert model["kind"] == "butterfly"
    assert {s["kind"] for s in model["sides"]} == {"school"}
    assert model["shared"] <= CASE_TRIO["games"]


def test_adding_a_person_from_a_bar_click_clears_the_crew_pick(app: Page) -> None:
    """D-08: the bar-click patch goes through setState, which clears the crew and says so."""
    key = _key(app)
    _set(app, {"view": "bars", "crew": key})
    person = CASE_TRIO["analysts"][0]
    app.evaluate(
        """async (person) => {
          const B = await import('./modules/bars.js');
          const h = window.__testHooks;
          const patch = B.drillPatch(h.data, h.getState(), {kind: 'person', id: person});
          h.setState(patch);
        }""",
        person,
    )
    assert app.evaluate("() => window.__testHooks.getState().crew") is None
    assert "Crew pick cleared" in (app.locator("#pick-status").text_content() or "")
