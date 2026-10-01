"""In-browser proof of the Bars/Butterfly logic core (SITE-33..36, D-01..D-18).

Every expectation is hand-worked against the 12-telecast synthetic fixture
(`tests/fixtures/contract/site-data.fixture.json`). The modules under test
(`bars.js`, plus the `view`/`bars`/`group` params in `url-state.js`) are DOM-free,
so they are imported straight into the served page via `page.evaluate`.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

_ENCODE_JS = """
async (partial) => {
  const D = await import('./modules/data.js');
  const S = await import('./modules/select.js');
  const U = await import('./modules/url-state.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  const state = Object.assign(S.defaultState(data), partial);
  const encoded = U.encodeState(state, data);
  const decoded = U.decodeState(encoded, data);
  return { encoded, decoded, again: U.encodeState(decoded, data) };
}
"""

_DECODE_JS = """
async (search) => {
  const D = await import('./modules/data.js');
  const U = await import('./modules/url-state.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  return U.decodeState(search, data);
}
"""

_CTX_JS = """
async (partial) => {
  const D = await import('./modules/data.js');
  const S = await import('./modules/select.js');
  const B = await import('./modules/bars.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  const state = Object.assign(S.defaultState(data), partial);
  return B.chartContext(data, state);
}
"""

# Runs one bars.js model builder over the page's data, optionally against a
# replacement raw payload (for the null-conference case).
_MODEL_JS = """
async ([fn, partial, rawOverride]) => {
  const D = await import('./modules/data.js');
  const S = await import('./modules/select.js');
  const B = await import('./modules/bars.js');
  const raw = rawOverride ?? await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  const state = Object.assign(S.defaultState(data), partial);
  const view = S.computeView(data, state);
  const model = B[fn](data, view, state);
  const personFacets = Array.from(view.facets.people);
  return { model, personFacets, ids: data.lookups.people.map((p) => p.id) };
}
"""

_VISIBLE_JS = """
async ([count, expanded]) => {
  const B = await import('./modules/bars.js');
  const rows = Array.from({ length: count }, (_, i) => ({ key: `r${i}` }));
  return B.visibleRows(rows, expanded).length;
}
"""

_LABEL_JS = """
async () => {
  const B = await import('./modules/bars.js');
  return {
    both: B.announcerLabel('Joe Davis', ['pbp', 'analyst']),
    pbp: B.announcerLabel('A', ['pbp']),
    other: B.announcerLabel('B', ['unknown']),
    none: B.announcerLabel('C', []),
    top: B.TOP_N,
    none_key: B.NO_CONFERENCE_KEY,
  };
}
"""

_DRILL_JS = """
async ([partial, target]) => {
  const D = await import('./modules/data.js');
  const S = await import('./modules/select.js');
  const B = await import('./modules/bars.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  const state = Object.assign(S.defaultState(data), partial);
  return B.drillPatch(data, state, target);
}
"""


def _load(page: Page, site_url: str) -> None:
    page.goto(f"{site_url}/")


def _model(page: Page, fn: str, partial: dict[str, Any], raw: Any = None) -> dict[str, Any]:
    out = page.evaluate(_MODEL_JS, [fn, partial, raw])
    assert "viewers" not in json.dumps(out["model"])  # D-01
    return out


def _rows(model: dict[str, Any]) -> list[tuple[str, int]]:
    return [(r["label"], r["total"]) for r in model["rows"]]


# --------------------------------------------------------------------------
# Task 1: URL params and chartContext
# --------------------------------------------------------------------------


def test_default_state_still_encodes_empty(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    out = guarded_page.evaluate(_ENCODE_JS, {})
    assert out["encoded"] == ""
    assert out["decoded"]["view"] == "scatter"
    assert out["decoded"]["bars"] == "simple"
    assert out["decoded"]["group"] is None


def test_view_bars_group_encode_and_round_trip(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    one = guarded_page.evaluate(_ENCODE_JS, {"view": "bars"})
    assert one["encoded"] == "?view=bars"
    full = guarded_page.evaluate(
        _ENCODE_JS,
        {"axis": "excitement", "view": "butterfly", "bars": "stacked", "group": "teams"},
    )
    assert full["encoded"] == "?axis=excitement&view=butterfly&bars=stacked&group=teams"
    for out in (one, full):
        assert out["again"] == out["encoded"]
    assert full["decoded"]["view"] == "butterfly"
    assert full["decoded"]["bars"] == "stacked"
    assert full["decoded"]["group"] == "teams"


def test_junk_view_params_fall_to_defaults(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    junk = guarded_page.evaluate(_DECODE_JS, "?view=nonsense&bars=x&group=y")
    assert (junk["view"], junk["bars"], junk["group"]) == ("scatter", "simple", None)
    assert guarded_page.evaluate(_DECODE_JS, "?group=announcers")["group"] is None


def test_stale_view_is_never_rejected_for_applicability(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    assert guarded_page.evaluate(_DECODE_JS, "?view=bars")["view"] == "bars"
    assert guarded_page.evaluate(_DECODE_JS, "?view=butterfly")["view"] == "butterfly"


_CTX_CASES: list[tuple[dict[str, Any], dict[str, Any]]] = [
    ({}, {"barsEnabled": False, "butterflyEnabled": False}),
    (
        {"school": ["northfield"]},
        {"barsEnabled": True, "group": "announcers", "groupChoice": False},
    ),
    ({"networks": ["net-a"]}, {"barsEnabled": True, "group": "teams"}),
    ({"networks": []}, {"barsEnabled": True, "group": "teams"}),
    ({"people": ["kris-venn"]}, {"barsEnabled": True, "group": "teams"}),
    (
        {"school": ["northfield"], "people": ["kris-venn"]},
        {"groupChoice": True, "group": "announcers"},
    ),
    (
        {"school": ["northfield"], "people": ["kris-venn"], "group": "teams"},
        {"groupChoice": True, "group": "teams"},
    ),
    (
        {"school": ["northfield", "lakeview"]},
        {"butterflyEnabled": True, "butterflyGroup": "announcers", "butterflyGroupChoice": False},
    ),
    (
        {"people": ["kris-venn", "pat-rowan"]},
        {"butterflyEnabled": True, "butterflyGroup": "teams"},
    ),
    (
        {"people": ["kris-venn", "pat-rowan", "casey-lund"]},
        {"butterflyEnabled": False},
    ),
    (
        {"school": ["northfield", "lakeview"], "people": ["kris-venn", "pat-rowan"]},
        {"butterflyGroupChoice": True, "butterflyGroup": "announcers"},
    ),
    (
        {
            "school": ["northfield", "lakeview"],
            "people": ["kris-venn", "pat-rowan"],
            "group": "teams",
        },
        {"butterflyGroupChoice": True, "butterflyGroup": "teams"},
    ),
]


@pytest.mark.parametrize(("partial", "expected"), _CTX_CASES)
def test_chart_context_matrix(
    guarded_page: Page, site_url: str, partial: dict[str, Any], expected: dict[str, Any]
) -> None:
    _load(guarded_page, site_url)
    ctx = guarded_page.evaluate(_CTX_JS, partial)
    for key, value in expected.items():
        assert ctx[key] == value, (partial, key, ctx)
