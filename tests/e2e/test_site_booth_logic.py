"""In-browser proof of the Phase 10 booth tier data model, Booth filter logic, facets and URL
state (D-12), on the synthetic booth overlay (plan 10-03). Like test_site_logic.py, these
exercise the served pure modules through `page.evaluate`.

Merged indices: rated 0..11, then unrated 12..19. With the overlay: tier a at 5, 8, 14;
b at 9, 13; other at 4 and 15 (15 is the conference-network lead); the rest are untiered.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

_TIERS_JS = """
async () => {
  const D = await import('./modules/data.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  return { tier: Array.from(data.boothTier), conf: Array.from(data.boothIsConfLead) };
}
"""

_VIEW_JS = """
async (partial) => {
  const D = await import('./modules/data.js');
  const S = await import('./modules/select.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  const state = Object.assign(S.defaultState(data), partial);
  const view = S.computeView(data, state);
  const passes = [];
  view.passesFilters.forEach((v, i) => { if (v) passes.push(i); });
  return {
    passes,
    visibleCount: view.visibleCount,
    filterActive: view.filterActive,
    booth: view.facets.booth,
    personShapes: view.personShapes,
  };
}
"""

_URL_JS = """
async ([partial, search]) => {
  const D = await import('./modules/data.js');
  const S = await import('./modules/select.js');
  const U = await import('./modules/url-state.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  const encoded = U.encodeState(Object.assign(S.defaultState(data), partial), data);
  const dflt = U.encodeState(S.defaultState(data), data);
  let decoded = null;
  let threw = false;
  try {
    decoded = U.decodeState(search, data).booth;
  } catch (e) {
    threw = true;
  }
  return { encoded, dflt, decoded, threw };
}
"""

_GUARD_JS = """
async () => {
  const D = await import('./modules/data.js');
  const raw = await (await fetch('site-data.json')).json();
  delete raw.lookups.booths;
  try {
    D.prepareData(raw);
    return null;
  } catch (e) {
    return e.message;
  }
}
"""

A, B, OTHER = [5, 8, 14], [9, 13], [4, 15]


def _open(page: Page, open_app: Callable[[Page, str], None]) -> None:
    open_app(page, "")


def _view(page: Page, partial: dict[str, Any]) -> dict[str, Any]:
    return page.evaluate(_VIEW_JS, partial)  # type: ignore[no-any-return]


def test_tiers_derived_from_merged_columns(
    guarded_page: Page, serve_booths: Callable[[Page], None], open_app: Callable[[Page, str], None]
) -> None:
    serve_booths(guarded_page)
    _open(guarded_page, open_app)
    out = guarded_page.evaluate(_TIERS_JS)
    expected = [0] * 20
    for i in A:
        expected[i] = 1
    for i in B:
        expected[i] = 2
    for i in OTHER:
        expected[i] = 3
    assert out["tier"] == expected
    assert [i for i, v in enumerate(out["conf"]) if v] == [15]


def test_default_facets_count_each_tier(
    guarded_page: Page, serve_booths: Callable[[Page], None], open_app: Callable[[Page, str], None]
) -> None:
    serve_booths(guarded_page)
    _open(guarded_page, open_app)
    view = _view(guarded_page, {})
    assert view["booth"] == {"a": 3, "b": 2, "other": 2}
    assert view["filterActive"] is False


def test_picking_a_tier_keeps_only_that_tier(
    guarded_page: Page, serve_booths: Callable[[Page], None], open_app: Callable[[Page, str], None]
) -> None:
    serve_booths(guarded_page)
    _open(guarded_page, open_app)
    view = _view(guarded_page, {"booth": ["a"]})
    assert view["passes"] == A
    assert view["filterActive"] is True
    # The facet excludes its own constraint.
    assert view["booth"] == {"a": 3, "b": 2, "other": 2}


def test_hide_mode_draws_only_the_picked_tier(
    guarded_page: Page, serve_booths: Callable[[Page], None], open_app: Callable[[Page, str], None]
) -> None:
    serve_booths(guarded_page)
    _open(guarded_page, open_app)
    fade = _view(guarded_page, {"booth": ["a"], "dots": "fade"})
    hide = _view(guarded_page, {"booth": ["a"], "dots": "hide"})
    assert hide["visibleCount"] == 3
    assert fade["visibleCount"] == 19  # the unplayed game is never drawn (v2.1)


def test_other_includes_the_conference_lead(
    guarded_page: Page, serve_booths: Callable[[Page], None], open_app: Callable[[Page, str], None]
) -> None:
    serve_booths(guarded_page)
    _open(guarded_page, open_app)
    assert _view(guarded_page, {"booth": ["other"]})["passes"] == OTHER


def test_all_tiers_picked_still_fails_untiered(
    guarded_page: Page, serve_booths: Callable[[Page], None], open_app: Callable[[Page, str], None]
) -> None:
    serve_booths(guarded_page)
    _open(guarded_page, open_app)
    view = _view(guarded_page, {"booth": ["a", "b", "other"]})
    assert view["passes"] == sorted(A + B + OTHER)


def test_person_shapes_follow_compare_mode(
    guarded_page: Page, serve_booths: Callable[[Page], None], open_app: Callable[[Page, str], None]
) -> None:
    serve_booths(guarded_page)
    _open(guarded_page, open_app)
    assert _view(guarded_page, {})["personShapes"] is False
    assert _view(guarded_page, {"compare": True})["personShapes"] is False
    people = guarded_page.evaluate(
        """async () => {
          const raw = await (await fetch('site-data.json')).json();
          return raw.lookups.people.slice(0, 2).map((p) => p.id);
        }"""
    )
    assert _view(guarded_page, {"compare": True, "people": people})["personShapes"] is True
    assert _view(guarded_page, {"people": people})["personShapes"] is False


def test_url_encoding_and_hostile_decoding(
    guarded_page: Page, serve_booths: Callable[[Page], None], open_app: Callable[[Page, str], None]
) -> None:
    serve_booths(guarded_page)
    _open(guarded_page, open_app)
    out = guarded_page.evaluate(_URL_JS, [{"booth": ["other", "a"]}, "?booth=other,a,a,x,"])
    assert out["dflt"] == ""
    assert out["encoded"] == "?booth=a,other"
    assert out["decoded"] == ["a", "other"]
    assert out["threw"] is False
    for hostile in ("?booth=%", "?booth=", "?booth=%E0%A4%A", "?booth=A,B"):
        res = guarded_page.evaluate(_URL_JS, [{}, hostile])
        assert res["threw"] is False
        assert res["decoded"] == []


def test_shared_fixture_has_no_tiers(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    _open(guarded_page, open_app)
    assert set(guarded_page.evaluate(_TIERS_JS)["tier"]) == {0}
    assert _view(guarded_page, {})["booth"] == {"a": 0, "b": 0, "other": 0}


def test_missing_booths_fail_loudly(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    _open(guarded_page, open_app)
    message = guarded_page.evaluate(_GUARD_JS)
    assert message is not None
    assert "contract 2.6.0" in message
