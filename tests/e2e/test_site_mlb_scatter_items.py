"""16-04: the MLB Scatter item model (site/sports/mlb/scatter-items.js).

In-page tests of the DOM-free module on the synthetic MLB fixture, densified by
tests/e2e/mlb_scatter_fixture.py through a route handler.
"""

# ruff: noqa: E501
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from mlb_scatter_fixture import CONTROLS, SCATTER_CASE, densify_scatter
from playwright.sync_api import Page, Route

pytestmark = pytest.mark.e2e

PRELUDE = """
const D = await import('./sports/mlb/data.js');
const S = await import('./sports/mlb/state.js');
const M = await import('./sports/mlb/scatter-items.js');
const raw = await (await fetch('mlb-data.json')).json();
const model = D.prepareMlb(raw);
const st = (o) => ({ ...S.defaultMlbState(), ...o });
"""


def _densify(route: Route) -> None:
    resp = route.fetch()
    route.fulfill(response=resp, body=json.dumps(densify_scatter(json.loads(resp.text()))))


@pytest.fixture
def run(mlb_guarded_page: Page, open_mlb_app: Callable[..., None]) -> Callable[[str], Any]:
    mlb_guarded_page.route("**/mlb-data.json", _densify)
    open_mlb_app(mlb_guarded_page)

    def _run(body: str) -> Any:
        return mlb_guarded_page.evaluate("async () => {" + PRELUDE + body + "}")

    return _run


def _ctl(name: str) -> str:
    stype, sround = CONTROLS[name]
    return json.dumps({"stype": stype, "sround": sround})


def test_family_of_maps_and_falls_back_to_other(run: Callable[[str], Any]) -> None:
    out = run(
        "model.cols.network[0] = null; model.networks[3].family = 'martian';"
        "return [M.familyOf(model, 0), M.familyOf(model, 6), M.familyOf(model, 7), M.familyOf(model, 11)];"
    )
    assert out == ["other", "tbs", "fox", "other"]


def test_color_slots_do_not_touch_palette(run: Callable[[str], Any]) -> None:
    out = run("return ['apple','tbs','disney','fox','cbs','nbc','other','zzz'].map(M.colorSlotOf);")
    assert out == ["conference", "wbd", "disney", "fox", "cbs", "nbc", "other", "other"]


def test_family_order_and_labels(run: Callable[[str], Any]) -> None:
    out = run("return [M.MLB_FAMILY_ORDER, M.MLB_FAMILY_LABELS];")
    assert out[0] == ["apple", "fox", "tbs", "disney", "nbc", "cbs", "other"]
    assert out[1] == {
        "apple": "Apple TV",
        "fox": "FOX/FS1",
        "tbs": "TBS",
        "disney": "ESPN/ABC",
        "nbc": "NBC/Peacock",
        "cbs": "CBS",
        "other": "Other",
    }


def test_pass_control_rules(run: Callable[[str], Any]) -> None:
    out = run(
        """
        const idx = (s) => [...Array(model.n).keys()].filter((i) => M.passesControl(model, i, st(s)));
        model.cols.round[5] = 'mystery';
        return { all: idx({}), post: idx({stype:'post'}), lcs: idx({stype:'post', sround:'lcs'}),
                 reg: idx({stype:'reg'}) };
        """
    )
    assert out["all"] == list(range(15))
    assert out["post"] == list(range(6, 15))
    assert out["lcs"] == [10, 13]
    assert out["reg"] == [0, 1, 2, 3, 4]  # the unknown round 5 is not regular season


def test_unknown_round_never_passes_a_narrowed_control(run: Callable[[str], Any]) -> None:
    out = run(
        "model.cols.round[5] = 'mystery';"
        "return [M.passesControl(model,5,st({stype:'post'})), M.passesControl(model,5,st({stype:'post',sround:'lcs'})),"
        " M.passesControl(model,5,st({stype:'reg'}))];"
    )
    assert out == [False, False, False]


@pytest.mark.parametrize("name", list(CONTROLS))
def test_every_game_appears_exactly_once(run: Callable[[str], Any], name: str) -> None:
    out = run(
        f"const s = st({_ctl(name)});"
        "const r = M.buildScatterItems(model, s, { hiddenFamilies: new Set() });"
        "const idx = r.items.map((it) => it.i).sort((a, b) => a - b);"
        "const lit = r.items.filter((it) => !it.faded).map((it) => it.i).sort((a, b) => a - b);"
        "const expect = [...Array(model.n).keys()].filter((i) => M.passesControl(model, i, s));"
        "return { idx, lit, expect, places: r.items.map((it) => it.place) };"
    )
    # U5: the control never removes a game; it fades the games outside it.
    assert out["idx"] == list(range(15))
    assert out["lit"] == out["expect"]
    assert len(set(out["idx"])) == len(out["idx"])
    assert len(out["places"]) == SCATTER_CASE[name]["total"]


@pytest.mark.parametrize("name", list(CONTROLS))
def test_counts_match_scatter_case(run: Callable[[str], Any], name: str) -> None:
    out, off = run(
        f"const s = st({_ctl(name)});"
        "const r = M.buildScatterItems(model, s, {});"
        "const h = M.buildScatterItems(model, s, { hiddenFamilies: new Set(['fox']) });"
        "const litFox = h.items.filter((it) => it.hidden && !it.faded).length;"
        "return [r.counts, { ...h.counts, litFox }];"
    )
    for key, val in SCATTER_CASE[name].items():
        assert out[key] == val, (name, key)
    assert out["plotted"] + out["noRating"] + out["noExcitement"] + out["neither"] == out["total"]
    # A chip off keeps every game in the counts; only the full-strength count drops (G1).
    for key, val in SCATTER_CASE[name].items():
        if key == "highlighted":
            expect = None if val is None else val - off["litFox"]
            assert off[key] == expect, (name, key)
        else:
            assert off[key] == val, (name, key)


def test_missing_values_are_null_never_zero(run: Callable[[str], Any]) -> None:
    out = run(
        "const r = M.buildScatterItems(model, st({}), {});"
        "return r.items.map((it) => [it.i, it.place, it.x, it.y, it.window]);"
    )
    places = {p for _, p, *_ in out}
    assert places == {"plot", "bottom", "left", "corner"}
    for _, place, x, y, _w in out:
        assert (x is None) == (place in ("bottom", "corner"))
        assert (y is None) == (place in ("left", "corner"))
        assert x != 0
        assert y != 0
    # Each placement occurs at least twice.
    for p in places:
        assert sum(1 for _, q, *_ in out if q == p) >= 2
    windows = [i for i, _p, _x, _y, w in out if w]
    assert windows == [10]


def test_hidden_families_flag_items_but_still_count(run: Callable[[str], Any]) -> None:
    out = run(
        "const r = M.buildScatterItems(model, st({}), { hiddenFamilies: new Set(['tbs']) });"
        "return { hidden: r.items.filter((it) => it.hidden).map((it) => it.family), total: r.counts.total,"
        " families: r.families };"
    )
    assert set(out["hidden"]) == {"tbs"}
    assert out["total"] == 15
    assert out["families"] == ["apple", "fox", "tbs", "disney"]


def test_no_selection_means_nothing_faded(run: Callable[[str], Any]) -> None:
    out = run(
        "const r = M.buildScatterItems(model, st({}), {});"
        "return [r.items.every((it) => !it.matched && !it.faded), r.counts.matched, r.counts.faded];"
    )
    assert out == [True, 0, 0]


def test_booth_selection_marks_exactly_table_games(run: Callable[[str], Any]) -> None:
    out = run(
        "const s = st({ booth: '0' });"
        "const r = M.buildScatterItems(model, s, {});"
        "const want = new Set(S.tableGames(model, s));"
        "return { matched: r.items.filter((it) => it.matched).map((it) => it.i).sort((a,b)=>a-b),"
        " want: [...want].sort((a,b)=>a-b), fadedOk: r.items.every((it) => it.faded === !it.matched),"
        " counts: [r.counts.matched, r.counts.faded, r.counts.total] };"
    )
    assert out["matched"] == out["want"] and out["want"]
    assert out["fadedOk"]
    assert out["counts"][0] + out["counts"][1] == out["counts"][2]


def test_season_cell_selection_marks_exactly_table_games(run: Callable[[str], Any]) -> None:
    out = run(
        "const s = st({ cell: 'season-2019' });"
        "const r = M.buildScatterItems(model, s, {});"
        "return { matched: r.items.filter((it) => it.matched).map((it) => it.i).sort((a,b)=>a-b),"
        " want: [...S.tableGames(model, s)].sort((a,b)=>a-b) };"
    )
    assert out["matched"] == out["want"] == [8, 9, 10]


def test_view_selection_marks_its_games(run: Callable[[str], Any]) -> None:
    out = run(
        "const s = st({ selection: { games: [0, 7], label: 'x' } });"
        "const r = M.buildScatterItems(model, s, {});"
        "return r.items.filter((it) => it.matched).map((it) => it.i).sort((a,b)=>a-b);"
    )
    assert out == [0, 7]


def test_full_strength_needs_both_the_control_and_the_pick(run: Callable[[str], Any]) -> None:
    """U5: with a pick and a control, a dot is full strength (and outlined) only if it is in both."""
    out = run(
        """
        const pick = [0, 7, 10, 13];
        const base = { selection: { games: pick, label: 'x' } };
        const res = [];
        for (const c of [{}, {stype:'post'}, {stype:'post', sround:'lcs'}, {stype:'reg'}]) {
          const s = st({ ...base, ...c });
          const r = M.buildScatterItems(model, s, {});
          const ok = r.items.every((it) => {
            const both = pick.includes(it.i) && M.passesControl(model, it.i, s);
            return it.matched === both && it.faded === !both;
          });
          res.push([ok, r.counts.total, r.counts.highlighted, S.tableGames(model, s).length]);
        }
        return res;
        """
    )
    assert [ok for ok, *_ in out] == [True, True, True, True]
    assert [total for _, total, _, _ in out] == [15, 15, 15, 15]
    assert [lit for _, _, lit, _ in out] == [4, 3, 2, 1]
    # The control never narrows Matched games.
    assert [rows for *_, rows in out] == [4, 4, 4, 4]


def test_control_alone_fades_without_outlines(run: Callable[[str], Any]) -> None:
    out = run(
        "const r = M.buildScatterItems(model, st({ stype: 'post', sround: 'lcs' }), {});"
        "return { lit: r.items.filter((it) => !it.faded).map((it) => it.i),"
        " matched: r.counts.matched, highlighted: r.counts.highlighted, total: r.counts.total,"
        " none: M.buildScatterItems(model, st({}), {}).counts.highlighted };"
    )
    assert out == {"lit": [10, 13], "matched": 0, "highlighted": 2, "total": 15, "none": None}


def test_status_text(run: Callable[[str], Any]) -> None:
    out = run(
        """
        const c = (o) => ({ total: 0, plotted: 0, noRating: 0, noExcitement: 0, neither: 0, ...o });
        return [
          M.statusText(c({ total: 9, plotted: 5, noRating: 2, noExcitement: 1, neither: 1 })),
          M.statusText(c({ total: 1, plotted: 1 })),
          M.statusText(c({ total: 3, plotted: 2, neither: 1 })),
          M.statusText(c({ total: 3, noRating: 2, neither: 1 })),
          M.statusText(c({ total: 0 })),
          M.statusText(c({ total: 9, plotted: 5, noRating: 2, noExcitement: 1, neither: 1 }), 3),
          M.statusText(c({ total: 1, plotted: 1 }), 0),
          M.statusText(c({ total: 9, plotted: 5, noRating: 2, noExcitement: 1, neither: 1, highlighted: 4 }), 3),
          M.statusText(c({ total: 1, plotted: 1, highlighted: 0 })),
          M.statusText(c({ total: 1, plotted: 1, highlighted: null })),
        ];
        """
    )
    assert out[0] == "5 games plotted. 2 with no rating, 1 with no excitement, 1 with neither."
    assert out[1] == "1 game plotted."
    assert out[2] == "2 games plotted. 1 with neither."
    assert out[3] == "2 with no rating, 1 with neither."
    assert out[4] == ""
    # F4: games behind an off legend chip stay in the counts and are named as hidden.
    assert out[5] == (
        "5 games plotted. 2 with no rating, 1 with no excitement, 1 with neither. "
        "3 hidden by the legend."
    )
    assert out[6] == "1 game plotted."
    # U5: every game is still counted; the highlighted count comes before the hidden clause.
    assert out[7] == (
        "5 games plotted. 2 with no rating, 1 with no excitement, 1 with neither. "
        "4 highlighted. 3 hidden by the legend."
    )
    assert out[8] == "1 game plotted. 0 highlighted."
    assert out[9] == "1 game plotted."


def test_strip_jitter_is_deterministic(run: Callable[[str], Any]) -> None:
    out = run(
        "return [0, 1, 2, 17, 500].map((i) => [M.stripJitter(i), 0.12 + ((i * 0.6180339887) % 1) * 0.76]);"
    )
    for got, want in out:
        assert got == want
        assert 0 < got < 1


def test_highlighted_skips_games_the_legend_hides(run: Callable[[str], Any]) -> None:
    """G1: "N highlighted" counts only games drawn at full strength, so a game whose legend chip
    is off is not counted; `matched` stays a population count and still includes it."""
    out = run(
        """
        const out = [];
        for (const pickState of [{ selection: { games: [0, 7, 10, 13], label: 'x' }, stype: 'post' }, { booth: '0', stype: 'reg' }]) {
        const s = st(pickState);
        const all = M.buildScatterItems(model, s, {});
        const lit = all.items.filter((it) => !it.faded);
        const fam = lit[0].family;
        const r = M.buildScatterItems(model, s, { hiddenFamilies: new Set([fam]) });
        const drawnFull = r.items.filter((it) => !it.hidden && !it.faded).length;
        out.push({ before: all.counts.highlighted, after: r.counts.highlighted, drawnFull,
                 hiddenLit: lit.filter((it) => it.family === fam).length,
                 matchedBefore: all.counts.matched, matchedAfter: r.counts.matched });
        }
        return out;
        """
    )
    for case in out:  # a selection pick, then a booth pick, each with Season type set
        assert case["hiddenLit"] >= 1
        assert case["after"] == case["drawnFull"]
        assert case["after"] == case["before"] - case["hiddenLit"]
        assert case["matchedAfter"] == case["matchedBefore"]
