"""In-browser proof of the Bars/Butterfly logic core (SITE-33..36, D-01..D-18).

Every expectation is hand-worked against the synthetic fixture
(`tests/fixtures/contract/site-data.fixture.json`): 12 rated telecasts (games 0-11) and
8 unrated games (12-19), all counted; each row also carries `rated` (04.13 D-15). The
modules under test
(`bars.js`, plus the `view`/`bars`/`group` params in `url-state.js`) are DOM-free,
so they are imported straight into the served page via `page.evaluate`.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from conftest import multichannel_raw
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
  const C = await import('./modules/bar-copy.js');
  return {
    both: B.orderedRoles(['analyst', 'pbp']),
    pbp: B.orderedRoles(['pbp']),
    other: B.orderedRoles(['unknown']),
    none: B.orderedRoles([]),
    suffix_both: C.roleSuffix(['pbp', 'analyst']),
    suffix_none: C.roleSuffix([]),
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


def _rated(model: dict[str, Any]) -> list[tuple[str, int, int]]:
    """(label, rated, total) per row; every row satisfies 0 <= rated <= total."""
    out = [(r["label"], r["rated"], r["total"]) for r in model["rows"]]
    assert all(0 <= rated <= total for _, rated, total in out)
    return out


# --------------------------------------------------------------------------
# Task 1: URL params and chartContext
# --------------------------------------------------------------------------


def test_default_state_still_encodes_empty(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    out = guarded_page.evaluate(_ENCODE_JS, {})
    assert out["encoded"] == ""
    assert out["decoded"]["view"] == "scatter"
    assert out["decoded"]["by"] is None
    assert "bars" not in out["decoded"]
    assert "group" not in out["decoded"]


def test_view_bars_group_encode_and_round_trip(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    one = guarded_page.evaluate(_ENCODE_JS, {"view": "bars"})
    assert one["encoded"] == "?view=bars"
    full = guarded_page.evaluate(
        _ENCODE_JS,
        {"axis": "excitement", "view": "butterfly", "by": "conference"},
    )
    assert full["encoded"] == "?axis=excitement&view=butterfly&by=conference"
    for out in (one, full):
        assert out["again"] == out["encoded"]
    assert full["decoded"]["view"] == "butterfly"
    assert full["decoded"]["by"] == "conference"


def test_junk_view_params_fall_to_defaults(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    junk = guarded_page.evaluate(_DECODE_JS, "?view=nonsense&by=junk")
    assert (junk["view"], junk["by"]) == ("scatter", None)
    assert guarded_page.evaluate(_DECODE_JS, "?by=announcer")["by"] is None
    assert guarded_page.evaluate(_DECODE_JS, "?by=%")["by"] is None
    legacy = guarded_page.evaluate(_DECODE_JS, "?bars=stacked&group=teams")
    assert legacy["by"] is None
    assert "bars" not in legacy
    assert "group" not in legacy


_BY_HELPERS_JS = """
async () => {
  const B = await import('./modules/bars.js');
  return {
    parts: [null, 'announcer', 'network', 'team', 'conference'].map((b) => B.byParts(b)),
    from: [['announcers', 'simple'], ['announcers', 'stacked'], ['teams', 'simple'],
           ['teams', 'stacked']].map(([g, m]) => B.byFrom(g, m)),
    patches: [
      B.byPatch('team', ['team', 'conference']),
      B.byPatch('team', B.BY_ORDER),
      B.byPatch('announcer', B.BY_ORDER),
      B.byPatch('conference', ['team', 'conference']),
    ],
    order: B.BY_ORDER,
  };
}
"""


def test_by_helpers(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    out = guarded_page.evaluate(_BY_HELPERS_JS)
    assert out["order"] == ["announcer", "network", "team", "conference"]
    assert out["parts"] == [
        {"pref": "announcers", "mode": "simple"},
        {"pref": "announcers", "mode": "simple"},
        {"pref": "announcers", "mode": "stacked"},
        {"pref": "teams", "mode": "simple"},
        {"pref": "teams", "mode": "stacked"},
    ]
    assert out["from"] == ["announcer", "network", "team", "conference"]
    assert out["patches"] == [{"by": None}, {"by": "team"}, {"by": None}, {"by": "conference"}]


_BY_CTX_CASES: list[tuple[dict[str, Any], dict[str, Any]]] = [
    ({"school": ["northfield"]}, {"byOptions": ["announcer", "network"], "by": "announcer"}),
    ({"people": ["kris-venn"]}, {"byOptions": ["team", "conference"], "by": "team"}),
    (
        {"school": ["northfield"], "people": ["kris-venn"]},
        {"byOptions": ["announcer", "network", "team", "conference"]},
    ),
    (
        {"school": ["northfield", "lakeview"], "people": ["kris-venn", "pat-rowan"]},
        {"butterflyByOptions": ["announcer", "network", "team", "conference"]},
    ),
    ({"school": ["northfield"], "by": "network"}, {"by": "network", "mode": "stacked"}),
    # D-26: the subject went away; the stacked position is kept.
    ({"people": ["kris-venn"], "by": "network"}, {"by": "conference", "mode": "stacked"}),
    ({"school": ["northfield"], "by": "conference"}, {"by": "network", "mode": "stacked"}),
    ({"school": ["northfield"], "by": "team"}, {"by": "announcer", "mode": "simple"}),
]


@pytest.mark.parametrize(("partial", "expected"), _BY_CTX_CASES)
def test_chart_context_by_options(
    guarded_page: Page, site_url: str, partial: dict[str, Any], expected: dict[str, Any]
) -> None:
    _load(guarded_page, site_url)
    ctx = guarded_page.evaluate(_CTX_JS, partial)
    for key, value in expected.items():
        assert ctx[key] == value, key


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
        {"school": ["northfield"], "people": ["kris-venn"], "by": "team"},
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
            "by": "team",
        },
        {"butterflyGroupChoice": True, "butterflyGroup": "teams"},
    ),
    (
        {"school": ["northfield", "lakeview"], "h2h": True},
        {
            "barsEnabled": True,
            "group": "announcers",
            "byOptions": ["announcer", "network"],
            "butterflyEnabled": False,
        },
    ),
    (
        {
            "school": ["northfield", "lakeview"],
            "h2h": True,
            "people": ["dale-harlow", "casey-lund"],
        },
        {"butterflyEnabled": True, "butterflyGroupChoice": False, "butterflyGroup": "teams"},
    ),
    (
        {"school": ["northfield", "lakeview"], "h2h": False},
        {"butterflyEnabled": True, "butterflyGroup": "announcers"},
    ),
    # D-15: a matchup keeps the Bars grouping to by Announcer | by Network, even
    # when a person or a Networks pick would otherwise offer by Team / Conference.
    (
        {"school": ["northfield", "lakeview"], "h2h": True, "people": ["dale-harlow"]},
        {"groupChoice": False, "group": "announcers", "byOptions": ["announcer", "network"]},
    ),
    (
        {"school": ["northfield", "lakeview"], "h2h": True, "networks": ["net-a"]},
        {"groupChoice": False, "group": "announcers", "byOptions": ["announcer", "network"]},
    ),
    (
        {
            "school": ["northfield", "lakeview"],
            "h2h": True,
            "people": ["dale-harlow"],
            "by": "conference",
        },
        {"group": "announcers", "byOptions": ["announcer", "network"], "by": "network"},
    ),
    (
        {"school": ["northfield", "lakeview"], "h2h": False, "people": ["dale-harlow"]},
        {"groupChoice": True, "byOptions": ["announcer", "network", "team", "conference"]},
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

# Northfield plays rated games 0, 4, 8 and unrated games 13 (Kris Venn, Morgan Ash) and 16
# (Pat Rowan, Sam Delgado): 9 announcers; those four call only unrated games, so rated is 0.
# Sorted by total games (rated + unrated), ties by name.
_NORTHFIELD_ANNOUNCERS = [
    ("Dale Harlow", 2),
    ("Dale Harlow Jr.", 2),
    ("Casey Lund", 1),
    ("Jamie Oaks", 1),
    ("Kris Venn", 1),
    ("Morgan Ash", 1),
    ("Pat Rowan", 1),
    ("Robin Teague", 1),
    ("Sam Delgado", 1),
]
_NORTHFIELD_RATED = [
    ("Dale Harlow", 2, 2),
    ("Dale Harlow Jr.", 2, 2),
    ("Casey Lund", 1, 1),
    ("Jamie Oaks", 1, 1),
    ("Kris Venn", 0, 1),
    ("Morgan Ash", 0, 1),
    ("Pat Rowan", 0, 1),
    ("Robin Teague", 1, 1),
    ("Sam Delgado", 0, 1),
]


def test_announcer_labels_and_constants(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    out = guarded_page.evaluate(_LABEL_JS)
    assert out["both"] == ["pbp", "analyst"]
    assert out["pbp"] == ["pbp"]
    assert out["other"] == ["unknown"]
    assert out["none"] == []
    assert out["suffix_both"] == " (PBP, Analyst)"
    assert out["suffix_none"] == ""
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
    assert _rated(model) == _NORTHFIELD_RATED
    assert model["rows"][0]["target"] == {"kind": "person", "id": "dale-harlow"}
    roles = {r["label"]: r["roles"] for r in model["rows"]}
    assert roles["Dale Harlow"] == ["pbp"]
    assert roles["Dale Harlow Jr."] == ["analyst"]
    assert roles["Robin Teague"] == ["unknown"]
    dumped = json.dumps(model)
    for old in (" \u00b7 PBP", " \u00b7 Analyst", " \u00b7 Other", "PBP/Analyst"):
        assert old not in dumped
    # D-02 cross-check: same counts as the existing facet rule.
    for row in model["rows"]:
        person = out["ids"].index(row["target"]["id"])
        assert out["personFacets"][person] == row["total"]


def _channels(segment: dict[str, Any]) -> list[tuple[str, str, int, int]]:
    return [(c["id"], c["name"], c["count"], c["shade"]) for c in segment["channels"]]


def _segs(row: dict[str, Any]) -> list[tuple[str, int, list[tuple[str, str, int, int]]]]:
    return [(s["label"], s["count"], _channels(s)) for s in row["segments"]]


_A = ("net-a", "Alpha Sports")
_E = ("net-e", "Echo Sports")

_M_NORTHFIELD = [
    ("Dale Harlow", 2, [(*_A, 1, 0), (*_E, 1, 1)]),
    ("Dale Harlow Jr.", 2, [(*_A, 1, 0), (*_E, 1, 1)]),
    ("Casey Lund", 1, [(*_A, 1, 0)]),
    ("Jamie Oaks", 1, [(*_A, 1, 0)]),
    ("Kris Venn", 1, [(*_A, 1, 0)]),
    ("Morgan Ash", 1, [(*_A, 1, 0)]),
    ("Robin Teague", 1, [(*_E, 1, 1)]),
]
# Rated part of each _M_NORTHFIELD announcer: Kris Venn and Morgan Ash call only unrated games.
_M_NORTHFIELD_RATED = [2, 2, 1, 1, 0, 0, 1]


def test_stacked_announcer_bars_are_families(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    model = _model(guarded_page, "barsModel", {"school": ["northfield"], "by": "network"})["model"]
    assert (model["rowKind"], model["segmentKind"]) == ("family", "person")
    assert [r["key"] for r in model["rows"]] == ["f:disney", "f:fox"]
    row = model["rows"][0]
    assert (row["key"], row["label"], row["family"], row["total"]) == (
        "f:disney",
        "ABC/ESPN",
        "disney",
        9,
    )
    # Disney games 0, 4, 8 (rated) and 13 (unrated): 2 + 2 + 3 + 2 = 9 announcer slots, 7 rated.
    assert row["rated"] == 7
    # Stream Plus (net-e) is a second disney channel in the fixture, so the family has 2 shades.
    assert row["shadeCount"] == 2
    # Only net-a is offered under this selection (Stream Plus has no Northfield game).
    assert row["target"] == {"kind": "family", "family": "disney", "ids": ["net-a"]}
    fox = model["rows"][1]
    assert (fox["key"], fox["total"], fox["rated"]) == ("f:fox", 2, 0)  # game 16: Pat, Sam
    assert _segs(row) == [(label, n, [(*_A, n, 0)]) for label, n, _ in _M_NORTHFIELD]
    assert [s["rated"] for s in row["segments"]] == _M_NORTHFIELD_RATED
    assert row["segments"][0]["target"] == {"kind": "person", "id": "dale-harlow"}


def test_family_row_splits_announcers_by_channel(
    guarded_page: Page, site_url: str, fixture_raw: dict[str, Any]
) -> None:
    _load(guarded_page, site_url)
    raw = multichannel_raw(fixture_raw)
    model = _model(guarded_page, "barsModel", {"school": ["northfield"], "by": "network"}, raw)[
        "model"
    ]
    assert (model["rowKind"], model["segmentKind"]) == ("family", "person")
    assert [r["key"] for r in model["rows"]] == ["f:disney", "f:fox"]
    row = model["rows"][0]
    assert (row["key"], row["name"], row["label"], row["family"], row["total"]) == (
        "f:disney",
        "ABC/ESPN",
        "ABC/ESPN",
        "disney",
        9,
    )
    assert row["rated"] == 7
    assert row["shadeCount"] == 2
    assert row["target"] == {"kind": "family", "family": "disney", "ids": ["net-a", "net-e"]}
    assert _segs(row) == _M_NORTHFIELD
    assert [s["key"] for s in row["segments"]] == [
        "p:dale-harlow",
        "p:dale-harlow-jr",
        "p:casey-lund",
        "p:jamie-oaks",
        "p:kris-venn",
        "p:morgan-ash",
        "p:robin-teague",
    ]
    for seg in row["segments"]:
        assert seg["target"] == {"kind": "person", "id": seg["key"][2:]}
        assert sum(c["count"] for c in seg["channels"]) == seg["count"]
        assert sum(c["rated"] for c in seg["channels"]) == seg["rated"]
        assert all(0 <= c["rated"] <= c["count"] for c in seg["channels"])


def test_channel_shade_follows_data_wide_order(
    guarded_page: Page, site_url: str, fixture_raw: dict[str, Any]
) -> None:
    _load(guarded_page, site_url)
    raw = multichannel_raw(fixture_raw, also_move_zero=True)
    # Data-wide net-e carries games 0, 8 and unrated 15, 18 (4), tying net-a (4, 13, 14, 19), so
    # move unrated game 14 too: net-e 5 games, net-a 3, and net-e takes shade 0.
    raw["telecasts_unrated"]["network"][2] = 4
    model = _model(guarded_page, "barsModel", {"school": ["northfield"], "by": "network"}, raw)[
        "model"
    ]
    row = model["rows"][0]
    for seg in row["segments"]:
        for c in seg["channels"]:
            assert c["shade"] == (0 if c["id"] == "net-e" else 1)
    by_label = {s["label"]: s for s in row["segments"]}
    assert _channels(by_label["Dale Harlow"]) == [(*_E, 2, 0)]
    assert _channels(by_label["Casey Lund"]) == [(*_A, 1, 1)]
    assert _channels(by_label["Kris Venn"]) == [(*_A, 1, 1)]  # unrated game 13 stays on net-a


def test_family_rows_respect_the_role_filter(
    guarded_page: Page, site_url: str, fixture_raw: dict[str, Any]
) -> None:
    _load(guarded_page, site_url)
    raw = multichannel_raw(fixture_raw)
    model = _model(
        guarded_page,
        "barsModel",
        {"school": ["northfield"], "by": "network", "role": "pbp"},
        raw,
    )["model"]
    assert [r["key"] for r in model["rows"]] == ["f:disney", "f:fox"]
    row = model["rows"][0]
    assert (row["key"], row["total"], row["rated"]) == ("f:disney", 4, 3)  # + Kris Venn, unrated 13
    assert _segs(row) == [
        ("Dale Harlow", 2, [(*_A, 1, 0), (*_E, 1, 1)]),
        ("Casey Lund", 1, [(*_A, 1, 0)]),
        ("Kris Venn", 1, [(*_A, 1, 0)]),
    ]
    assert [s["rated"] for s in row["segments"]] == [2, 1, 0]


def test_simple_rows_carry_no_channels(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    model = _model(guarded_page, "barsModel", {"school": ["northfield"]})["model"]
    assert all("channels" not in r and "shadeCount" not in r for r in model["rows"])
    stacked = _model(guarded_page, "barsModel", {"people": ["kris-venn"], "by": "conference"})[
        "model"
    ]
    assert all("shadeCount" not in r for r in stacked["rows"])
    assert all("channels" not in s for r in stacked["rows"] for s in r["segments"])


def test_simple_team_bars_for_an_announcer(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    model = _model(guarded_page, "barsModel", {"people": ["kris-venn"]})["model"]
    assert (model["group"], model["rowKind"]) == ("teams", "team")
    assert _rows(model) == [
        ("Foxhollow", 2),
        ("Ironpeak", 2),
        ("Cedar Hollow", 1),
        ("Lakeview", 1),
        ("Northfield", 1),
        ("Stonebridge", 1),
    ]
    # Kris Venn: rated games 1, 6, 9 and unrated game 13 (Ironpeak v Northfield), which adds
    # Northfield and a second Ironpeak with no rated part.
    assert _rated(model) == [
        ("Foxhollow", 2, 2),
        ("Ironpeak", 1, 2),
        ("Cedar Hollow", 1, 1),
        ("Lakeview", 1, 1),
        ("Northfield", 0, 1),
        ("Stonebridge", 1, 1),
    ]
    assert model["rows"][0]["target"] == {"kind": "team", "slug": "foxhollow"}


def test_stacked_team_bars_are_era_correct_conferences(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    model = _model(guarded_page, "barsModel", {"people": ["kris-venn"], "by": "conference"})[
        "model"
    ]
    assert (model["rowKind"], model["segmentKind"]) == ("conference", "team")
    assert _rows(model) == [
        ("Big Ten", 3),
        ("SEC", 3),
        ("FBS Independents", 1),
        ("Mountain West", 1),
    ]
    assert _rated(model)[:2] == [("Big Ten", 1, 3), ("SEC", 3, 3)]
    big_ten, sec = model["rows"][:2]
    assert [(s["label"], s["count"], s["rated"]) for s in big_ten["segments"]] == [
        ("Ironpeak", 2, 1),
        ("Northfield", 1, 0),
    ]
    assert [(s["label"], s["count"], s["rated"]) for s in sec["segments"]] == [
        ("Foxhollow", 2, 2),
        ("Lakeview", 1, 1),
    ]
    assert sec["target"] == {"kind": "conference", "name": "SEC"}


def test_non_fbs_conference_row_has_no_target(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    model = _model(
        guarded_page,
        "barsModel",
        {"school": ["maplecrest"], "networks": ["net-d"], "by": "conference"},
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
        {"school": ["maplecrest"], "networks": ["net-d"], "by": "conference"},
        raw,
    )["model"]
    row = next(r for r in model["rows"] if r["key"] == "c:__none__")
    assert (row["label"], row["target"]) == ("No conference", None)


def test_alt_feed_counts_and_role_filter_drops_it(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    rows = _rows(_model(guarded_page, "barsModel", {"school": ["maplecrest"]})["model"])
    assert ("Taylor Vance", 1) in rows
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
    # Kris Venn: games 1, 6, 9, 13; Pat Rowan: 2, 5, 10, 15, 16, 19 -> 10 games, 20 team slots
    # (Cedar Hollow 3 times); games 1, 2, 5, 6, 9, 10 are rated -> 12 rated slots.
    assert sum(r["total"] for r in union["rows"]) == 20
    assert sum(r["rated"] for r in union["rows"]) == 12
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


# --------------------------------------------------------------------------
# Task 3: Butterfly model and drill-in patches
# --------------------------------------------------------------------------


def _sides(model: dict[str, Any]) -> list[tuple[str, int, int]]:
    return [(r["label"], r["sides"][0]["total"], r["sides"][1]["total"]) for r in model["rows"]]


def test_butterfly_two_schools(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    model = _model(guarded_page, "butterflyModel", {"school": ["northfield", "lakeview"]})["model"]
    assert [s["name"] for s in model["sides"]] == ["Northfield", "Lakeview"]
    assert [s["kind"] for s in model["sides"]] == ["school", "school"]
    # Games with both schools: 0, 4 and unrated 16.
    assert model["shared"] == 3
    assert _sides(model) == [
        ("Dale Harlow", 2, 1),
        ("Dale Harlow Jr.", 2, 1),
        ("Casey Lund", 1, 1),
        ("Jamie Oaks", 1, 1),
        ("Kris Venn", 1, 1),
        ("Pat Rowan", 1, 1),
        ("Sam Delgado", 1, 1),
        ("Jax Venn", 0, 1),
        ("Morgan Ash", 1, 0),
        ("Robin Teague", 1, 0),
    ]
    assert [(r["label"], r["rated"]) for r in model["rows"]] == [
        ("Dale Harlow", 3),
        ("Dale Harlow Jr.", 3),
        ("Casey Lund", 2),
        ("Jamie Oaks", 2),
        ("Kris Venn", 1),
        ("Pat Rowan", 0),
        ("Sam Delgado", 0),
        ("Jax Venn", 1),
        ("Morgan Ash", 0),
        ("Robin Teague", 1),
    ]
    assert [(r["sides"][0]["rated"], r["sides"][1]["rated"]) for r in model["rows"]][:5] == [
        (2, 1),
        (2, 1),
        (1, 1),
        (1, 1),
        (0, 1),
    ]
    assert all(r["total"] == r["sides"][0]["total"] + r["sides"][1]["total"] for r in model["rows"])


def test_butterfly_two_announcers_and_together_is_ignored(
    guarded_page: Page, site_url: str
) -> None:
    _load(guarded_page, site_url)
    people = ["kris-venn", "pat-rowan"]
    model = _model(guarded_page, "butterflyModel", {"people": people})["model"]
    assert [s["name"] for s in model["sides"]] == ["Kris Venn", "Pat Rowan"]
    assert [s["kind"] for s in model["sides"]] == ["person", "person"]
    assert model["shared"] == 0
    assert _sides(model) == [
        ("Ironpeak", 2, 3),
        ("Foxhollow", 2, 2),
        ("Cedar Hollow", 1, 2),
        ("Boulder Pass", 0, 2),
        ("Lakeview", 1, 1),
        ("Northfield", 1, 1),
        ("Stonebridge", 1, 1),
    ]
    # Sorted by total games (5, 4, 3, 2...), so Ironpeak outranks Foxhollow.
    assert [(r["label"], r["rated"]) for r in model["rows"]] == [
        ("Ironpeak", 2),
        ("Foxhollow", 3),
        ("Cedar Hollow", 3),
        ("Boulder Pass", 2),
        ("Lakeview", 1),
        ("Northfield", 0),
        ("Stonebridge", 1),
    ]
    assert [(r["sides"][0]["rated"], r["sides"][1]["rated"]) for r in model["rows"]][:3] == [
        (1, 1),
        (2, 1),
        (1, 2),
    ]
    together = _model(guarded_page, "butterflyModel", {"people": people, "together": True})["model"]
    assert together == model


def test_butterfly_stacked_mirrors_bars_rows(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    schools = _model(
        guarded_page,
        "butterflyModel",
        {"school": ["northfield", "lakeview"], "by": "network"},
    )["model"]
    assert (schools["rowKind"], schools["segmentKind"]) == ("family", "person")
    names = {r["label"]: r for r in schools["rows"]}
    disney = names["ABC/ESPN"]
    assert disney["sides"][0]["total"] == 9
    assert disney["sides"][0]["rated"] == 7
    assert disney["total"] == 13  # 9 Northfield + 4 Lakeview
    assert [s["count"] for s in disney["sides"][0]["segments"]] == [2, 2, 1, 1, 1, 1, 1]
    assert [s["rated"] for s in disney["sides"][0]["segments"]] == [2, 2, 1, 1, 0, 0, 1]
    people = _model(
        guarded_page,
        "butterflyModel",
        {"people": ["kris-venn", "pat-rowan"], "by": "conference"},
    )["model"]
    assert (people["rowKind"], people["segmentKind"]) == ("conference", "team")
    sec = next(r for r in people["rows"] if r["label"] == "SEC")
    assert (sec["sides"][0]["total"], sec["sides"][0]["rated"]) == (3, 3)
    assert [(s["label"], s["count"]) for s in sec["sides"][0]["segments"]] == [
        ("Foxhollow", 2),
        ("Lakeview", 1),
    ]
    # Big Ten holds Kris Venn's unrated game 13 (Ironpeak v Northfield): 3 games, 1 rated.
    big_ten = next(r for r in people["rows"] if r["label"] == "Big Ten")
    assert (big_ten["sides"][0]["total"], big_ten["sides"][0]["rated"]) == (3, 1)
    assert "No conference" in [r["label"] for r in people["rows"]]  # Pat Rowan's unrated 15, 16


def test_butterfly_stacked_family_rows_with_channels(
    guarded_page: Page, site_url: str, fixture_raw: dict[str, Any]
) -> None:
    _load(guarded_page, site_url)
    raw = multichannel_raw(fixture_raw)
    model = _model(
        guarded_page,
        "butterflyModel",
        {"school": ["northfield", "lakeview"], "by": "network"},
        raw,
    )["model"]
    assert model["rowKind"] == "family"
    assert [s["name"] for s in model["sides"]] == ["Northfield", "Lakeview"]
    assert model["shared"] == 3
    assert [r["key"] for r in model["rows"]] == ["f:disney", "f:fox"]
    disney, fox = model["rows"]
    assert (disney["total"], disney["rated"], disney["shadeCount"]) == (13, 11, 2)
    assert disney["target"] == {"kind": "family", "family": "disney", "ids": ["net-a", "net-e"]}
    assert (disney["sides"][0]["total"], disney["sides"][0]["rated"]) == (9, 7)
    assert _segs(disney["sides"][0]) == _M_NORTHFIELD
    assert (disney["sides"][1]["total"], disney["sides"][1]["rated"]) == (4, 4)
    assert _segs(disney["sides"][1]) == [
        ("Casey Lund", 1, [(*_A, 1, 0)]),
        ("Dale Harlow", 1, [(*_A, 1, 0)]),
        ("Dale Harlow Jr.", 1, [(*_A, 1, 0)]),
        ("Jamie Oaks", 1, [(*_A, 1, 0)]),
    ]
    assert (fox["label"], fox["total"], fox["rated"], fox["shadeCount"]) == (
        "FOX/FS1/BTN",
        6,
        2,
        1,
    )
    assert fox["target"] == {"kind": "family", "family": "fox", "ids": ["net-b"]}
    assert (fox["sides"][0]["total"], fox["sides"][0]["rated"]) == (2, 0)  # unrated 16: Pat, Sam
    assert (fox["sides"][1]["total"], fox["sides"][1]["rated"]) == (4, 2)
    b_ch = [(*("net-b", "Beta Network"), 1, 0)]
    assert _segs(fox["sides"][1]) == [
        ("Jax Venn", 1, b_ch),
        ("Kris Venn", 1, b_ch),
        ("Pat Rowan", 1, b_ch),
        ("Sam Delgado", 1, b_ch),
    ]


@pytest.mark.parametrize(
    "partial",
    [
        {"school": ["northfield"]},
        {"school": ["northfield", "lakeview", "ironpeak"]},
        {"people": ["kris-venn"]},
    ],
)
def test_butterfly_is_null_without_exactly_two_subjects(
    guarded_page: Page, site_url: str, partial: dict[str, Any]
) -> None:
    _load(guarded_page, site_url)
    assert _model(guarded_page, "butterflyModel", partial)["model"] is None


def _drill(page: Page, partial: dict[str, Any], target: dict[str, Any] | None) -> Any:
    return page.evaluate(_DRILL_JS, [partial, target])


def test_drill_patches(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    p = guarded_page
    school = {"school": ["northfield"]}
    person = {"kind": "person", "id": "dale-harlow"}
    assert _drill(p, school, person) == {"people": ["dale-harlow"]}
    assert _drill(p, {**school, "people": ["dale-harlow"]}, person) is None
    full = ["dale-harlow", "kris-venn", "pat-rowan", "casey-lund"]
    assert (
        _drill(
            p, {**school, "compare": True, "people": full}, {"kind": "person", "id": "jamie-oaks"}
        )
        is None
    )
    team = {"kind": "team", "slug": "lakeview"}
    assert _drill(p, {"people": ["kris-venn"], "school": ["northfield"]}, team)["school"] == [
        "northfield",
        "lakeview",
    ]
    assert _drill(p, {"school": ["lakeview"]}, team) is None
    net = {"kind": "network", "id": "net-a"}
    assert _drill(p, {"school": ["northfield"]}, net) == {"networks": ["net-a"]}
    assert _drill(p, {"networks": ["net-a"]}, net) is None
    fam = {"kind": "family", "family": "disney", "ids": ["net-a", "net-e"]}
    stacked = {"school": ["northfield"], "view": "bars", "by": "network"}
    assert _drill(p, stacked, fam) == {"networks": ["net-a", "net-e"]}
    assert _drill(p, {**stacked, "networks": ["net-e", "net-a"]}, fam) is None
    assert _drill(p, stacked, {**fam, "ids": []}) is None
    sec = {"kind": "conference", "name": "SEC"}
    assert _drill(p, {"conferences": ["Big Ten"]}, sec) == {"conferences": ["Big Ten", "SEC"]}
    assert _drill(p, {"conferences": ["SEC"]}, sec) is None
    assert _drill(p, {}, {"kind": "conference", "name": "Missouri Valley"}) is None
    assert _drill(p, {}, None) is None


def test_drill_keeps_the_grouping(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    # networks narrowed -> teams group; adding a school makes Group-by a choice,
    # and the click must not flip the chart from Teams to Announcers.
    patch = _drill(
        guarded_page,
        {"view": "bars", "networks": ["net-a"]},
        {"kind": "team", "slug": "northfield"},
    )
    assert patch["school"] == ["northfield"]
    assert patch["by"] == "team"
    # school only (announcers, stored group 'teams' but unresolved): person drill
    # makes teams apply too, staying on Announcers (group null).
    patch = _drill(
        guarded_page,
        {"view": "bars", "school": ["northfield"], "by": "team"},
        {"kind": "person", "id": "dale-harlow"},
    )
    assert patch["people"] == ["dale-harlow"]
    assert patch["by"] is None


# --------------------------------------------------------------------------
# D-31: simple announcer rows carry their main network family
# --------------------------------------------------------------------------

_THREE_SCHOOLS = ["ironpeak", "foxhollow", "stonebridge"]


def _main(model: dict[str, Any]) -> list[tuple[str, int, Any]]:
    return [(r["label"], r["total"], r["mainFamily"]) for r in model["rows"]]


def test_simple_announcer_rows_carry_main_family(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    model = _model(guarded_page, "barsModel", {"school": _THREE_SCHOOLS})["model"]
    assert _main(model) == [
        ("Kris Venn", 4, "fox"),
        ("Pat Rowan", 3, "disney"),
        ("Robin Teague", 3, "other"),
        ("Casey Lund", 2, "disney"),
        ("Jax Venn", 2, "fox"),
        ("Sam Delgado", 2, "disney"),
        ("Dale Harlow", 1, "disney"),
        ("Dale Harlow Jr.", 1, "disney"),
        ("Jamie Oaks", 1, "disney"),
        ("Morgan Ash", 1, "disney"),
        ("Taylor Vance", 1, "fox"),
    ]
    assert [r["rated"] for r in model["rows"]] == [3, 1, 3, 1, 2, 1, 1, 1, 0, 0, 1]
    # The family pill is drawn for any row with `family`, so it stays null.
    assert all(r["family"] is None for r in model["rows"])


def test_main_family_tie_breaks_by_family_order(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    model = _model(guarded_page, "barsModel", {"school": ["lakeview", "maplecrest"]})["model"]
    by_label = {r["label"]: r["mainFamily"] for r in model["rows"]}
    # Casey Lund has 2 disney and 2 other games here, a tie that FAMILY_ORDER breaks to disney.
    assert by_label["Jamie Oaks"] == "disney"
    assert by_label["Casey Lund"] == "disney"


def test_main_family_honors_the_role_filter(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    model = _model(guarded_page, "barsModel", {"school": _THREE_SCHOOLS, "role": "analyst"})[
        "model"
    ]
    by_label = {r["label"]: r["mainFamily"] for r in model["rows"]}
    assert by_label["Sam Delgado"] == "disney"  # the unrated game 16 outweighs the rated one
    assert by_label["Jax Venn"] == "fox"


def test_butterfly_main_family_uses_both_sides(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    state = {"school": ["lakeview", "maplecrest"]}
    bars = _model(guarded_page, "barsModel", state)["model"]
    fly = _model(guarded_page, "butterflyModel", state)["model"]
    want = {r["key"]: r["mainFamily"] for r in bars["rows"]}
    got = {r["key"]: r["mainFamily"] for r in fly["rows"]}
    assert got == want
    by_label = {r["label"]: r["mainFamily"] for r in fly["rows"]}
    assert by_label["Casey Lund"] == "disney"  # 2-2 tie with other goes to FAMILY_ORDER
    assert by_label["Jamie Oaks"] == "disney"


def test_non_announcer_rows_have_no_main_family(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    cases = [
        ("barsModel", {"people": ["kris-venn"]}),
        ("barsModel", {"people": ["kris-venn"], "by": "conference"}),
        ("barsModel", {"school": ["northfield"], "by": "network"}),
        ("butterflyModel", {"people": ["kris-venn", "pat-rowan"]}),
        ("butterflyModel", {"people": ["kris-venn", "pat-rowan"], "by": "conference"}),
        ("butterflyModel", {"school": ["northfield", "lakeview"], "by": "network"}),
    ]
    for fn, state in cases:
        model = _model(guarded_page, fn, state)["model"]
        assert model["rows"], (fn, state)
        assert all(r.get("mainFamily") is None for r in model["rows"]), (fn, state)


def test_butterfly_row_label_unions_roles_from_both_sides(
    guarded_page: Page, site_url: str, fixture_raw: dict[str, Any]
) -> None:
    """WR-01. Kris Venn calls Lakeview's game 9 as PBP and Stonebridge's game 6
    as Analyst (changed below), so the one merged row has roles pbp then analyst,
    not the role of whichever side built the row first. Hand count: 1 game a side.
    """
    raw = copy.deepcopy(fixture_raw)
    kris = next(i for i, p in enumerate(raw["lookups"]["people"]) if p["name"] == "Kris Venn")
    entry = next(c for c in raw["telecasts"]["crew"][6] if c["person"] == kris)
    assert entry["role"] == "pbp"
    entry["role"] = "analyst"
    _load(guarded_page, site_url)
    state = {"school": ["lakeview", "stonebridge"]}
    fly = _model(guarded_page, "butterflyModel", state, raw)["model"]
    row = next(r for r in fly["rows"] if r["name"] == "Kris Venn")
    assert row["label"] == "Kris Venn"
    assert row["roles"] == ["pbp", "analyst"]
    assert [s["total"] for s in row["sides"]] == [1, 1]
    swapped = _model(guarded_page, "butterflyModel", {"school": ["stonebridge", "lakeview"]}, raw)[
        "model"
    ]
    swapped_row = next(r for r in swapped["rows"] if r["name"] == "Kris Venn")
    assert swapped_row["label"] == "Kris Venn"
    assert swapped_row["roles"] == ["pbp", "analyst"]


_TITLE_JS = """
async (partial) => {
  const D = await import('./modules/data.js');
  const S = await import('./modules/select.js');
  const B = await import('./modules/bars.js');
  const C = await import('./modules/bar-copy.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  const state = Object.assign(S.defaultState(data), partial);
  const view = S.computeView(data, state);
  const model = state.view === 'butterfly' ? B.butterflyModel(data, view, state)
    : B.barsModel(data, view, state);
  return {
    title: C.chartTitle(model, data, state),
    games: B.gamesForBars(view),
    matchup: C.matchupPhrase(data, state),
  };
}
"""

_H2H = {"school": ["northfield", "lakeview"], "h2h": True}
_MATCHUP = "in Northfield vs Lakeview games"


def test_head_to_head_bars_count_only_the_matchup(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    out = guarded_page.evaluate(_TITLE_JS, {**_H2H, "view": "bars"})
    assert sorted(out["games"]) == [0, 4, 16]  # 16 is unrated


@pytest.mark.parametrize(
    ("partial", "expected"),
    [
        ({"view": "bars"}, f"Announcers by games {_MATCHUP}"),
        (
            {"view": "bars", "people": ["dale-harlow"]},
            f"Announcers by games {_MATCHUP} with Dale Harlow",
        ),
        (
            {"view": "bars", "people": ["dale-harlow"], "networks": ["net-a"]},
            f"Announcers by games {_MATCHUP} with Dale Harlow on Alpha Sports",
        ),
        ({"view": "bars", "by": "network"}, f"Networks by games {_MATCHUP}"),
    ],
)
def test_head_to_head_titles_name_the_matchup(
    guarded_page: Page, site_url: str, partial: dict[str, Any], expected: str
) -> None:
    _load(guarded_page, site_url)
    assert guarded_page.evaluate(_TITLE_JS, {**_H2H, **partial})["title"] == expected


def test_head_to_head_butterfly_title_names_the_matchup(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    title = guarded_page.evaluate(
        _TITLE_JS, {**_H2H, "people": ["dale-harlow", "casey-lund"], "view": "butterfly"}
    )["title"]
    assert "Dale Harlow and Casey Lund in Northfield vs Lakeview games" in title
    assert " or " not in title


def test_either_team_titles_keep_the_or_join(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    title = guarded_page.evaluate(
        _TITLE_JS,
        {"school": ["northfield", "lakeview"], "networks": ["net-a"], "view": "bars"},
    )["title"]
    assert "Northfield or Lakeview" in title
    assert "vs" not in title


def test_matchup_phrase_needs_exactly_two_schools(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    one = guarded_page.evaluate(_TITLE_JS, {"school": ["northfield"], "h2h": True, "view": "bars"})
    assert one["matchup"] == ""
    two = guarded_page.evaluate(_TITLE_JS, {**_H2H, "view": "bars"})
    assert two["matchup"] == _MATCHUP


def test_team_bar_drill_is_a_no_op_under_head_to_head(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    assert (
        _drill(guarded_page, {**_H2H, "view": "bars"}, {"kind": "team", "slug": "lakeview"}) is None
    )


_NF = {"view": "bars", "school": ["northfield"]}


@pytest.mark.parametrize(
    ("partial", "expected"),
    [
        (
            {**_NF, "game": "harbor-bowl"},
            "Announcers by games of the Harbor Bowl with Northfield",
        ),
        (
            {"view": "bars", "people": ["kris-venn"], "by": "team", "game": "bridge-game"},
            "Teams by games of The Bridge Game with Kris Venn",
        ),
        (
            {"view": "bars", "people": ["kris-venn"], "by": "conference", "game": "harbor-bowl"},
            "Conferences by games in the Harbor Bowl with Kris Venn",
        ),
        (
            {**_NF, "by": "network", "game": "lakeshore"},
            "Networks by games in the Lakeshore Rivalry with Northfield",
        ),
        (
            {"view": "bars", "game": "harbor-bowl"},
            "Announcers by games of the Harbor Bowl",
        ),
        (
            {"view": "bars", "game": "lakeshore", "by": "network"},
            "Networks by games in the Lakeshore Rivalry",
        ),
        (
            {"view": "bars", "game": "cfp-semifinal"},
            "Announcers by games of CFP semifinals",
        ),
        (
            {**_NF, "game": "cfp-semifinal"},
            "Announcers by games of CFP semifinals with Northfield",
        ),
        (
            {**_NF, "game": "cfp-national-championship"},
            "Announcers by games of CFP national championships with Northfield",
        ),
        (
            {**_NF, "game": "cfp-first-round"},
            "Announcers by games of CFP first round games with Northfield",
        ),
        (
            {"view": "bars", "people": ["dale-harlow"], "by": "team", "game": "lakeshore"},
            "Teams by games of the Lakeshore Rivalry with Dale Harlow",
        ),
        (
            {**_H2H, "view": "bars", "game": "harbor-bowl"},
            f"Announcers by games of the Harbor Bowl {_MATCHUP}",
        ),
        (
            {**_NF, "game": "harbor-bowl", "networks": ["net-a"]},
            "Announcers by games of the Harbor Bowl with Northfield on Alpha Sports",
        ),
        (
            {
                "view": "butterfly",
                "people": ["dale-harlow", "casey-lund"],
                "game": "harbor-bowl",
            },
            "Teams: Dale Harlow and Casey Lund of the Harbor Bowl",
        ),
    ],
)
def test_game_titles_name_the_picked_game(
    guarded_page: Page, site_url: str, partial: dict[str, Any], expected: str
) -> None:
    _load(guarded_page, site_url)
    title = guarded_page.evaluate(_TITLE_JS, partial)["title"]
    assert title == expected
    assert " the " + "The " not in title
