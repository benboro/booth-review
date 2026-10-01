"""In-browser proof of the Bars/Butterfly logic core (SITE-33..36, D-01..D-18).

Every expectation is hand-worked against the 12-telecast synthetic fixture
(`tests/fixtures/contract/site-data.fixture.json`). The modules under test
(`bars.js`, plus the `view`/`bars`/`group` params in `url-state.js`) are DOM-free,
so they are imported straight into the served page via `page.evaluate`.
"""

from __future__ import annotations

import copy
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


# --------------------------------------------------------------------------
# Task 2: Bars tab counting model
# --------------------------------------------------------------------------

_NORTHFIELD_ANNOUNCERS = [
    ("Dale Harlow · PBP", 2),
    ("Dale Harlow Jr. · Analyst", 2),
    ("Casey Lund · PBP", 1),
    ("Jamie Oaks · Analyst", 1),
    ("Robin Teague · Other", 1),
]


def test_announcer_labels_and_constants(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    out = guarded_page.evaluate(_LABEL_JS)
    assert out["both"] == "Joe Davis · PBP/Analyst"
    assert out["pbp"] == "A · PBP"
    assert out["other"] == "B · Other"
    assert out["none"] == "C"
    assert out["top"] == 15
    assert out["none_key"] == "c:__none__"


def test_bars_is_null_without_a_subject(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    assert _model(guarded_page, "barsModel", {})["model"] is None


def test_simple_announcer_bars_for_a_school(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    out = _model(guarded_page, "barsModel", {"school": ["northfield"]})
    model = out["model"]
    assert (model["group"], model["mode"], model["rowKind"]) == ("announcers", "simple", "person")
    assert _rows(model) == _NORTHFIELD_ANNOUNCERS
    assert model["rows"][0]["target"] == {"kind": "person", "id": "dale-harlow"}
    # D-02 cross-check: same counts as the existing facet rule.
    for row in model["rows"]:
        person = out["ids"].index(row["target"]["id"])
        assert out["personFacets"][person] == row["total"]


def test_stacked_announcer_bars_are_networks(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    model = _model(guarded_page, "barsModel", {"school": ["northfield"], "bars": "stacked"})[
        "model"
    ]
    assert (model["rowKind"], model["segmentKind"]) == ("network", "person")
    assert len(model["rows"]) == 1
    row = model["rows"][0]
    assert (row["label"], row["family"], row["total"]) == ("Alpha Sports", "disney", 7)
    assert row["target"] == {"kind": "network", "id": "net-a"}
    assert [(s["label"], s["count"]) for s in row["segments"]] == _NORTHFIELD_ANNOUNCERS
    assert row["segments"][0]["target"] == {"kind": "person", "id": "dale-harlow"}


def test_simple_team_bars_for_an_announcer(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    model = _model(guarded_page, "barsModel", {"people": ["kris-venn"]})["model"]
    assert (model["group"], model["rowKind"]) == ("teams", "team")
    assert _rows(model) == [
        ("Foxhollow", 2),
        ("Cedar Hollow", 1),
        ("Ironpeak", 1),
        ("Lakeview", 1),
        ("Stonebridge", 1),
    ]
    assert model["rows"][0]["target"] == {"kind": "team", "slug": "foxhollow"}


def test_stacked_team_bars_are_era_correct_conferences(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    model = _model(guarded_page, "barsModel", {"people": ["kris-venn"], "bars": "stacked"})["model"]
    assert (model["rowKind"], model["segmentKind"]) == ("conference", "team")
    assert _rows(model) == [
        ("SEC", 3),
        ("Big Ten", 1),
        ("FBS Independents", 1),
        ("Mountain West", 1),
    ]
    sec = model["rows"][0]
    assert [(s["label"], s["count"]) for s in sec["segments"]] == [
        ("Foxhollow", 2),
        ("Lakeview", 1),
    ]
    assert sec["target"] == {"kind": "conference", "name": "SEC"}


def test_non_fbs_conference_row_has_no_target(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    model = _model(
        guarded_page,
        "barsModel",
        {"school": ["maplecrest"], "group": "teams", "networks": ["net-d"], "bars": "stacked"},
    )["model"]
    row = next(r for r in model["rows"] if r["label"] == "Missouri Valley")
    assert row["target"] is None
    assert [s["label"] for s in row["segments"]] == ["Maplecrest"]


def test_null_conference_row(
    guarded_page: Page, site_url: str, fixture_raw: dict[str, Any]
) -> None:
    raw = copy.deepcopy(fixture_raw)
    raw["telecasts"]["home_conference"][3] = None  # Maplecrest at home, game 3
    _load(guarded_page, site_url)
    model = _model(
        guarded_page,
        "barsModel",
        {"school": ["maplecrest"], "group": "teams", "networks": ["net-d"], "bars": "stacked"},
        raw,
    )["model"]
    row = next(r for r in model["rows"] if r["key"] == "c:__none__")
    assert (row["label"], row["target"]) == ("No conference", None)


def test_alt_feed_counts_and_role_filter_drops_it(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    rows = _rows(_model(guarded_page, "barsModel", {"school": ["maplecrest"]})["model"])
    assert ("Taylor Vance · Analyst", 1) in rows
    only_pbp = _rows(
        _model(guarded_page, "barsModel", {"school": ["maplecrest"], "role": "pbp"})["model"]
    )
    names = " ".join(label for label, _ in only_pbp)
    assert "Taylor Vance" not in names
    assert "Robin Teague" not in names


def test_called_together_narrows_the_counted_games(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    people = ["kris-venn", "pat-rowan"]
    together = _model(guarded_page, "barsModel", {"people": people, "together": True})["model"]
    assert together["rows"] == []
    union = _model(guarded_page, "barsModel", {"people": people})["model"]
    # games 1, 6, 9 and 2, 5, 10 -> 12 team slots, Cedar Hollow 3 times.
    assert sum(r["total"] for r in union["rows"]) == 12
    assert ("Cedar Hollow", 3) in _rows(union)


@pytest.mark.parametrize(
    ("count", "expanded", "shown"),
    [(20, False, 15), (20, True, 20), (15, False, 15), (15, True, 15)],
)
def test_visible_rows_limit(
    guarded_page: Page, site_url: str, count: int, expanded: bool, shown: int
) -> None:
    _load(guarded_page, site_url)
    assert guarded_page.evaluate(_VISIBLE_JS, [count, expanded]) == shown
