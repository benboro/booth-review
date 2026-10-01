"""Copy strings and Plotly figures for the Bars and Butterfly tabs (SITE-34,
SITE-35; D-01, D-06, D-15, D-16, D-18, D-20).

Builder tests import the DOM-free modules into the served page; tests with
`rendered` in the name open the real app and draw with `window.Plotly`.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

# Runs `body(ctx)` where ctx = {B, C, P, F, data, state, view, bars, fly}; bars/fly are
# the Bars and Butterfly models for `partial`.
_RUN_JS = """
async ([partial, body]) => {
  const D = await import('./modules/data.js');
  const S = await import('./modules/select.js');
  const B = await import('./modules/bars.js');
  const C = await import('./modules/bar-copy.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  const state = Object.assign(S.defaultState(data), partial);
  const view = S.computeView(data, state);
  const ctx = { B, C, data, state, view, S };
  ctx.bars = B.barsModel(data, view, state);
  ctx.fly = B.butterflyModel(data, view, state);
  return await (new Function('ctx', `return (${body})(ctx);`))(ctx);
}
"""


def _run(page: Page, site_url: str, partial: dict[str, Any], body: str) -> Any:
    page.goto(f"{site_url}/")
    return page.evaluate(_RUN_JS, [partial, body])


_TITLE_BARS = "(c) => c.C.chartTitle(c.bars, c.data, c.state)"
_TITLE_FLY = "(c) => c.C.chartTitle(c.fly, c.data, c.state)"

_BARS_TITLES: list[tuple[dict[str, Any], str]] = [
    ({"school": ["northfield"]}, "Announcers by rated telecasts · Northfield"),
    ({"school": ["northfield"], "bars": "stacked"}, "Network families by announcer · Northfield"),
    ({"people": ["kris-venn"]}, "Teams by rated telecasts · Kris Venn"),
    ({"people": ["kris-venn"], "bars": "stacked"}, "Conferences by team · Kris Venn"),
    ({"networks": ["net-a", "net-b"]}, "Teams by rated telecasts · 2 networks"),
    (
        {"school": ["northfield", "lakeview"]},
        "Announcers by rated telecasts · Northfield and Lakeview",
    ),
    (
        {"school": ["northfield", "lakeview", "ironpeak"]},
        "Announcers by rated telecasts · 3 schools",
    ),
    (
        {"school": ["northfield"], "networks": ["net-a"], "group": "teams"},
        "Teams by rated telecasts · Alpha Sports",
    ),
]


@pytest.mark.parametrize(("partial", "expected"), _BARS_TITLES)
def test_bars_chart_titles(
    guarded_page: Page, site_url: str, partial: dict[str, Any], expected: str
) -> None:
    assert _run(guarded_page, site_url, partial, _TITLE_BARS) == expected


_FLY_TITLES: list[tuple[dict[str, Any], str]] = [
    (
        {"school": ["northfield", "lakeview"]},
        "Announcers: Northfield and Lakeview",
    ),
    (
        {"school": ["northfield", "lakeview"], "bars": "stacked"},
        "Network families by announcer: Northfield and Lakeview",
    ),
    ({"people": ["kris-venn", "pat-rowan"]}, "Teams: Kris Venn and Pat Rowan"),
    (
        {"people": ["kris-venn", "pat-rowan"], "bars": "stacked"},
        "Conferences by team: Kris Venn and Pat Rowan",
    ),
]


@pytest.mark.parametrize(("partial", "expected"), _FLY_TITLES)
def test_butterfly_chart_titles(
    guarded_page: Page, site_url: str, partial: dict[str, Any], expected: str
) -> None:
    assert _run(guarded_page, site_url, partial, _TITLE_FLY) == expected


def test_row_count_caption_and_show_all(guarded_page: Page, site_url: str) -> None:
    out = _run(
        guarded_page,
        site_url,
        {"school": ["northfield"]},
        """(c) => {
          const mk = (n) => ({ rowKind: 'person', rows: Array.from({ length: n }, () => ({})) });
          return {
            collapsed: c.C.rowCountCaption(mk(20), false),
            expanded: c.C.rowCountCaption(mk(20), true),
            five: c.C.rowCountCaption(mk(5), false),
            one: c.C.rowCountCaption(mk(1), false),
            teams: c.C.rowCountCaption({ rowKind: 'team', rows: new Array(3) }, false),
            nets: c.C.rowCountCaption({ rowKind: 'network', rows: new Array(3) }, false),
            confs: c.C.rowCountCaption({ rowKind: 'conference', rows: new Array(3) }, false),
            all20: c.C.showAllLabel(20, false),
            top20: c.C.showAllLabel(20, true),
            none15: c.C.showAllLabel(15, false),
            count1: c.C.telecastCount(1),
            count7: c.C.telecastCount(7),
          };
        }""",
    )
    assert out == {
        "collapsed": "Showing top 15 of 20 announcers",
        "expanded": "Showing all 20 announcers",
        "five": "Showing all 5 announcers",
        "one": "Showing 1 announcer",
        "teams": "Showing all 3 teams",
        "nets": "Showing all 3 networks",
        "confs": "Showing all 3 conferences",
        "all20": "Show all 20",
        "top20": "Show top 15",
        "none15": None,
        "count1": "1 rated telecast",
        "count7": "7 rated telecasts",
    }


_STACK_SUM = (
    "Each telecast counts once for every announcer in it, so a bar can be longer than its "
    "number of telecasts."
)
_TEAM_COUNT = (
    "Each game counts once for every team in it, so team totals can add up to more than the "
    "number of games."
)
_NON_FILTER = "Non-FBS and unlisted conferences can't be used as a filter."


def test_caption_lines(guarded_page: Page, site_url: str) -> None:
    page = guarded_page
    cap = "(c) => c.C.captionLines(c.bars ?? c.fly, (c.bars ?? c.fly).rows)"
    assert _run(page, site_url, {"school": ["northfield"]}, cap) == []
    assert _run(page, site_url, {"school": ["northfield"], "bars": "stacked"}, cap) == [_STACK_SUM]
    assert _run(page, site_url, {"people": ["kris-venn"]}, cap) == [_TEAM_COUNT]
    assert _run(page, site_url, {"people": ["kris-venn"], "bars": "stacked"}, cap) == [_TEAM_COUNT]
    fly = _run(
        page,
        site_url,
        {"school": ["northfield", "lakeview"]},
        "(c) => c.C.captionLines(c.fly, c.fly.rows)",
    )
    assert fly == ["2 games include both."]
    out = _run(
        page,
        site_url,
        {"school": ["northfield", "lakeview"]},
        """(c) => [0, 1, 2].map((n) => c.C.captionLines({ ...c.fly, shared: n }, []))""",
    )
    assert out == [["0 games include both."], ["1 game includes both."], ["2 games include both."]]
    non = _run(
        page,
        site_url,
        {"school": ["maplecrest"], "group": "teams", "networks": ["net-d"], "bars": "stacked"},
        cap,
    )
    assert _NON_FILTER in non


def test_tooltip_lines(guarded_page: Page, site_url: str) -> None:
    page = guarded_page
    simple = _run(
        page,
        site_url,
        {"school": ["northfield"]},
        """(c) => [
          c.C.tooltipLines(c.bars, c.bars.rows, { r: 0, s: -1, side: null }, {}),
          c.C.tooltipLines(c.bars, c.bars.rows, { r: 0, s: -1, side: null }, { touch: true }),
        ]""",
    )
    assert simple[0] == [
        {"text": "Dale Harlow · PBP", "kind": "title"},
        {"text": "2 rated telecasts", "kind": "body"},
        {"text": "Click to filter →", "kind": "hint"},
    ]
    assert simple[1][2] == {"text": "Tap again to filter →", "kind": "hint"}
    stacked = _run(
        page,
        site_url,
        {"school": ["northfield"], "bars": "stacked"},
        "(c) => c.C.tooltipLines(c.bars, c.bars.rows, { r: 0, s: 0, side: null }, {})",
    )
    assert stacked[0] == {"text": "Dale Harlow · PBP", "kind": "title"}
    assert stacked[1] == {"text": "2 rated telecasts on ABC/ESPN", "kind": "body"}
    fly = _run(
        page,
        site_url,
        {"school": ["northfield", "lakeview"]},
        "(c) => c.C.tooltipLines(c.fly, c.fly.rows, { r: 0, s: -1, side: 0 }, {})",
    )
    assert fly[1] == {"text": "Northfield: 2 rated telecasts", "kind": "body"}
    conf = _run(
        page,
        site_url,
        {"school": ["maplecrest"], "group": "teams", "networks": ["net-d"], "bars": "stacked"},
        """(c) => {
          const i = c.bars.rows.findIndex((r) => r.target == null);
          return c.C.tooltipLines(c.bars, c.bars.rows, { r: i, s: -1, side: null }, {});
        }""",
    )
    assert [line["kind"] for line in conf] == ["title", "body"]


def test_counts_list_names(guarded_page: Page, site_url: str) -> None:
    out = _run(
        guarded_page,
        site_url,
        {"school": ["northfield", "lakeview"]},
        """(c) => ({
          person: c.C.countsListName({ kind: 'person', id: 'x' }, 'Dale Harlow', 2),
          team: c.C.countsListName({ kind: 'team', slug: 'x' }, 'Foxhollow', 2),
          network: c.C.countsListName({ kind: 'network', id: 'x' }, 'Alpha Sports', 7),
          conf: c.C.countsListName({ kind: 'conference', name: 'SEC' }, 'SEC', 3),
          text: c.C.butterflyRowText(c.fly.rows[0], c.fly),
          name: c.C.butterflyCountsName(c.fly.rows[0], c.fly),
        })""",
    )
    assert out == {
        "person": "Add Dale Harlow as a filter, 2 rated telecasts",
        "team": "Add Foxhollow to the School filter, 2 rated telecasts",
        "network": "Show only Alpha Sports, 7 rated telecasts",
        "conf": "Add SEC to the Conference filter, 3 rated telecasts",
        "text": "Dale Harlow · PBP: Northfield 2, Lakeview 1 rated telecasts",
        "name": "Add Dale Harlow as a filter, Northfield 2, Lakeview 1 rated telecasts",
    }


def test_aria_summaries(guarded_page: Page, site_url: str) -> None:
    page = guarded_page
    aria = "(c) => c.C.ariaSummary(c.bars ?? c.fly, c.data, c.state, (c.bars ?? c.fly).rows.length)"
    assert _run(page, site_url, {"school": ["northfield"]}, aria) == (
        "Bar chart: announcers by rated telecasts, Northfield, 2019\u20132026. Showing 5 of 5. "
        "Top: Dale Harlow · PBP 2, Dale Harlow Jr. · Analyst 2, Casey Lund · PBP 1."
    )
    one_year = _run(page, site_url, {"school": ["northfield"], "seasons": [2025, 2025]}, aria)
    assert "Northfield, 2025." in one_year
    fly = _run(
        page,
        site_url,
        {"school": ["northfield", "lakeview"]},
        "(c) => c.C.ariaSummary(c.fly, c.data, c.state, c.fly.rows.length)",
    )
    assert fly == (
        "Butterfly chart: announcers for Northfield and Lakeview, 2019\u20132026. Showing 7 of 7. "
        "2 games include both. Top: Dale Harlow · PBP 2 and 1, Dale Harlow Jr. · Analyst 2 and 1."
    )
    zero = _run(
        page,
        site_url,
        {"school": ["northfield"]},
        "(c) => c.C.ariaSummary({ ...c.bars, rows: [] }, c.data, c.state, 0)",
    )
    assert zero.endswith("Showing 0 of 0.")


def test_copy_never_mentions_viewers(guarded_page: Page, site_url: str) -> None:
    out = _run(
        guarded_page,
        site_url,
        {"school": ["northfield", "lakeview"]},
        """(c) => JSON.stringify([
          c.C.EMPTY_COPY,
          c.C.chartTitle(c.fly, c.data, c.state),
          c.C.captionLines(c.fly, c.fly.rows),
          c.C.ariaSummary(c.fly, c.data, c.state, 7),
          c.C.tooltipLines(c.fly, c.fly.rows, { r: 0, s: -1, side: 0 }, {}),
        ])""",
    )
    assert "viewer" not in out.lower()
    assert "No rated telecasts for this selection" in out
    assert "Widen the season range" in out


# --------------------------------------------------------------------------
# Task 2: palette helpers and the Bars figure builder
# --------------------------------------------------------------------------

_FIG_JS = """
async ([partial, fn, env]) => {
  const D = await import('./modules/data.js');
  const S = await import('./modules/select.js');
  const B = await import('./modules/bars.js');
  const F = await import('./modules/bar-chart.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  const state = Object.assign(S.defaultState(data), partial);
  const view = S.computeView(data, state);
  const model = B[fn](data, view, state);
  const rows = B.visibleRows(model.rows, false);
  const build = fn === 'barsModel' ? F.buildBarFigure : F.buildButterflyFigure;
  return { model, figure: build(model, rows, env) };
}
"""

_DESKTOP = {"theme": "light", "mobile": False, "revision": 1, "width": 1280}
_PHONE = {"theme": "light", "mobile": True, "revision": 1, "width": 390}


def _figure(
    page: Page,
    site_url: str,
    partial: dict[str, Any],
    fn: str = "barsModel",
    env: dict[str, Any] | None = None,
) -> dict[str, Any]:
    page.goto(f"{site_url}/")
    out: dict[str, Any] = page.evaluate(_FIG_JS, [partial, fn, env or _DESKTOP])
    assert "viewer" not in json.dumps(out["figure"]).lower()  # D-01
    return out


def test_palette_helpers(guarded_page: Page, site_url: str) -> None:
    guarded_page.goto(f"{site_url}/")
    out = guarded_page.evaluate(
        """async () => {
          const P = await import('./modules/palette.js');
          const F = await import('./modules/bar-chart.js');
          let worst = 99;
          for (let v = 0; v < 256; v += 1) {
            const h = '#' + v.toString(16).padStart(2, '0').repeat(3);
            const best = Math.max(P.contrastRatio(h, '#000000'), P.contrastRatio(h, '#FFFFFF'));
            worst = Math.min(worst, best);
          }
          return {
            lightA: P.readableTextOn('#4B5563'),
            lightB: P.readableTextOn(P.mixHex('#4B5563', '#FFFFFF', 0.55)),
            mixLight: P.mixHex('#4B5563', '#FFFFFF', 0.55),
            darkA: P.readableTextOn('#9CA3AF'),
            darkB: P.readableTextOn(P.mixHex('#9CA3AF', '#14161A', 0.55)),
            mixDark: P.mixHex('#9CA3AF', '#14161A', 0.55),
            worst,
            netTones: F.barTones({ family: 'disney' }, 'light'),
            netMix: P.mixHex('#0072B2', '#FFFFFF', 0.55),
            plainTones: F.barTones({ family: null }, 'light'),
          };
        }"""
    )
    assert out["lightA"] == "#FFFFFF"
    assert out["lightB"] == "#000000"
    assert out["mixLight"] == "#9CA2A9"
    assert out["darkA"] == "#000000"
    assert out["darkB"] == "#FFFFFF"
    assert out["mixDark"] == "#5F646C"
    # No grey fails 4.5:1 for both black and white (the best of the two is
    # always >= sqrt(21) ~ 4.58), so readableTextOn's null branch is a guard only.
    assert out["worst"] >= 4.5
    assert out["netTones"] == {"a": "#0072B2", "b": out["netMix"]}
    assert out["plainTones"] == {"a": "#4B5563", "b": "#9CA2A9"}


def test_simple_bar_figure_shape(guarded_page: Page, site_url: str) -> None:
    out = _figure(guarded_page, site_url, {"school": ["northfield"]})
    figure, rows = out["figure"], out["model"]["rows"]
    (trace,) = figure["traces"]
    assert (trace["type"], trace["orientation"], trace["textposition"]) == ("bar", "h", "outside")
    assert trace["x"] == [r["total"] for r in rows]
    assert trace["y"] == [r["key"] for r in rows]
    assert set(trace["marker"]["color"]) == {"#4B5563"}  # Tone A only
    assert trace["hoverinfo"] == "none"
    assert trace["customdata"] == [{"r": i, "s": -1, "side": None} for i in range(len(rows))]
    layout = figure["layout"]
    assert layout["yaxis"]["range"] == [4.5, -0.5]  # reversed, one pitch per row
    assert layout["yaxis"]["showticklabels"] is False
    assert layout["dragmode"] is False
    assert figure["config"]["displayModeBar"] is False
    assert layout["height"] == 5 * 32 + 72
    assert len(layout["annotations"]) == 5
    assert all(a["captureevents"] is True for a in layout["annotations"])
    assert "transition" not in layout


def test_stacked_bar_figure_shape(guarded_page: Page, site_url: str) -> None:
    out = _figure(guarded_page, site_url, {"people": ["kris-venn"], "bars": "stacked"})
    figure, rows = out["figure"], out["model"]["rows"]
    layout = figure["layout"]
    assert layout["barmode"] == "stack"
    assert layout["uniformtext"] == {"mode": "hide", "minsize": 14}
    depth = max(len(r["segments"]) for r in rows)
    assert len(figure["traces"]) == depth
    for k, trace in enumerate(figure["traces"]):
        assert set(trace["marker"]["color"]) == {"#4B5563" if k % 2 == 0 else "#9CA2A9"}
        assert trace["marker"]["line"] == {"width": 1, "color": "#FFFFFF"}
        for i, row in enumerate(rows):
            if k < len(row["segments"]):
                assert trace["x"][i] == row["segments"][k]["count"]
                assert trace["customdata"][i] == {"r": i, "s": k, "side": None}
                assert (
                    trace["text"][i]
                    == f"{row['segments'][k]['label']} {row['segments'][k]['count']}"
                )
            else:
                assert trace["x"][i] == 0
                assert trace["customdata"][i] is None
                assert trace["text"][i] == ""
    # Non-FBS conference rows have no target, so their labels are not clickable.
    assert [a["captureevents"] for a in layout["annotations"]] == [
        r["target"] is not None for r in rows
    ]


def test_network_rows_use_family_color(guarded_page: Page, site_url: str) -> None:
    out = _figure(guarded_page, site_url, {"school": ["northfield"], "bars": "stacked"})
    first = out["figure"]["traces"][0]
    assert set(first["marker"]["color"]) == {"#0072B2"}
    assert set(out["figure"]["traces"][1]["marker"]["color"]) == {"#73B1D5"}


def test_phone_bar_figure_layout(guarded_page: Page, site_url: str) -> None:
    out = _figure(guarded_page, site_url, {"school": ["northfield"]}, env=_PHONE)
    layout = out["figure"]["layout"]
    assert layout["margin"]["l"] == 8 and layout["margin"]["r"] == 8
    assert layout["height"] == 5 * 44 + 72
    assert all(a["yanchor"] == "bottom" and a["xanchor"] == "left" for a in layout["annotations"])


def test_bar_labels_are_escaped_in_figure(guarded_page: Page, site_url: str) -> None:
    guarded_page.goto(f"{site_url}/")
    text = guarded_page.evaluate(
        """async () => {
          const F = await import('./modules/bar-chart.js');
          const row = { key: 'k', name: 'x', label: '<img src=x onerror=alert(1)>', family: null,
                        total: 1, target: null, segments: [] };
          const fig = F.buildBarFigure({ mode: 'simple' }, [row], { theme: 'light', mobile: false,
                                                                    revision: 1, width: 800 });
          return fig.layout.annotations[0];
        }"""
    )
    assert text["text"] == "&lt;img src=x onerror=alert(1)&gt;"
    assert text["captureevents"] is False


# --------------------------------------------------------------------------
# Task 3: Butterfly figure builder
# --------------------------------------------------------------------------


def test_butterfly_simple_figure_shape(guarded_page: Page, site_url: str) -> None:
    out = _figure(guarded_page, site_url, {"school": ["northfield", "lakeview"]}, "butterflyModel")
    figure, rows = out["figure"], out["model"]["rows"]
    left, right = figure["traces"]
    assert left["xaxis"] == "x" and right["xaxis"] == "x2"
    assert left["x"] == [r["sides"][0]["total"] for r in rows]
    assert right["x"] == [r["sides"][1]["total"] for r in rows]
    for i, row in enumerate(rows):
        for side, trace in enumerate((left, right)):
            ref = trace["customdata"][i]
            if row["sides"][side]["total"] == 0:
                assert ref is None
            else:
                assert ref == {"r": i, "s": -1, "side": side}
    assert any(r["sides"][0]["total"] == 0 or r["sides"][1]["total"] == 0 for r in rows)
    layout = figure["layout"]
    top = max(max(r["sides"][0]["total"], r["sides"][1]["total"]) for r in rows) * 1.1
    assert layout["xaxis"]["range"] == pytest.approx([top, 0])
    assert layout["xaxis2"]["range"] == pytest.approx([0, top])
    annos = layout["annotations"]
    assert len(annos) == len(rows) + 2
    assert [a["text"] for a in annos[-2:]] == ["Northfield", "Lakeview"]
    assert (annos[-2]["xanchor"], annos[-1]["xanchor"]) == ("left", "right")
    assert layout["meta"]["rowCount"] == 7


def test_butterfly_stacked_figure_matches_bars_builder(guarded_page: Page, site_url: str) -> None:
    out = _figure(
        guarded_page,
        site_url,
        {"people": ["kris-venn", "pat-rowan"], "bars": "stacked"},
        "butterflyModel",
    )
    figure = out["figure"]
    assert figure["layout"]["barmode"] == "stack"
    assert figure["layout"]["uniformtext"] == {"mode": "hide", "minsize": 14}
    for trace in figure["traces"]:
        assert trace["marker"]["line"] == {"width": 1, "color": "#FFFFFF"}
        assert trace["textposition"] == "inside"
    assert {t["xaxis"] for t in figure["traces"]} == {"x", "x2"}


def test_butterfly_desktop_spine_gap_grows_with_labels(guarded_page: Page, site_url: str) -> None:
    guarded_page.goto(f"{site_url}/")
    out = guarded_page.evaluate(
        """async () => {
          const F = await import('./modules/bar-chart.js');
          return [F.spineGapPx(5), F.spineGapPx(22), F.spineGapPx(30)];
        }"""
    )
    assert out[0] == 160
    assert out[1] > 160
    assert out[2] > out[1]


def test_butterfly_side_name_escaped_in_figure(guarded_page: Page, site_url: str) -> None:
    guarded_page.goto(f"{site_url}/")
    text = guarded_page.evaluate(
        """async () => {
          const F = await import('./modules/bar-chart.js');
          const side = (name) => ({ total: 1, segments: [] });
          const row = { key: 'k', name: 'x', label: 'x', family: null, total: 2, target: null,
                        sides: [side(), side()] };
          const model = { mode: 'simple', sides: [{ name: '<b>x</b>' }, { name: 'B' }] };
          const fig = F.buildButterflyFigure(model, [row], { theme: 'dark', mobile: false,
                                                             revision: 1, width: 1000 });
          return fig.layout.annotations[1].text;
        }"""
    )
    assert text == "&lt;b&gt;x&lt;/b&gt;"


# --------------------------------------------------------------------------
# Rendered geometry (open the real app; Plotly loaded)
# --------------------------------------------------------------------------

_RENDER_JS = """
async ([partial, fn, env, longLabels, extraHtml]) => {
  const D = await import('./modules/data.js');
  const S = await import('./modules/select.js');
  const B = await import('./modules/bars.js');
  const F = await import('./modules/bar-chart.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  const state = Object.assign(S.defaultState(data), partial);
  const view = S.computeView(data, state);
  const model = B[fn](data, view, state);
  if (longLabels) {
    model.rows.forEach((r, i) => { r.label = `Long Announcer Name Number ${i} PBP`; });
  }
  const rows = B.visibleRows(model.rows, false);
  const build = fn === 'barsModel' ? F.buildBarFigure : F.buildButterflyFigure;
  const figure = build(model, rows, env);
  document.getElementById('test-bars')?.remove();
  const gd = document.createElement('div');
  gd.id = 'test-bars';
  gd.style.cssText = `width:${env.width}px;position:relative;`;
  document.body.appendChild(gd);
  await F.renderBars(gd, figure);
  const rect = (el) => {
    const r = el.getBoundingClientRect();
    return { l: r.left, r: r.right, t: r.top, b: r.bottom, w: r.width, h: r.height };
  };
  const bars = Array.from(gd.querySelectorAll('.bars .point path'))
    .map(rect).filter((r) => r.w > 0.5);
  const expected = figure.traces.reduce(
    (n, t) => n + t.x.filter((v) => v > 0).length, 0);
  const annos = Array.from(gd.querySelectorAll('g.annotation')).map((el) => ({
    text: el.textContent, ...rect(el) }));
  const full = gd._fullLayout;
  const gdRect = gd.getBoundingClientRect();
  const center = (i) => gdRect.top + full._size.t + full.yaxis.d2p(i);
  const out = {
    bars, expected, annos,
    rowCount: rows.length,
    centers: rows.map((_, i) => center(i)),
    imgs: gd.querySelectorAll('img').length,
    scrollWidth: gd.scrollWidth,
    clientWidth: gd.clientWidth,
    plotLeft: gdRect.left + full._size.l,
    plotRight: gdRect.left + full._size.l + full._size.w,
    height: gd.getBoundingClientRect().height,
    x1End: full.xaxis ? gdRect.left + full.xaxis._offset + full.xaxis._length : null,
    x2Start: full.xaxis2 ? gdRect.left + full.xaxis2._offset : null,
    x2End: full.xaxis2 ? gdRect.left + full.xaxis2._offset + full.xaxis2._length : null,
    x1Start: gdRect.left + full.xaxis._offset,
  };
  return out;
}
"""


def _render(
    page: Page,
    open_app: Callable[[Page, str], None],
    partial: dict[str, Any],
    fn: str,
    env: dict[str, Any],
    long_labels: bool = False,
) -> dict[str, Any]:
    open_app(page, "")
    out: dict[str, Any] = page.evaluate(_RENDER_JS, [partial, fn, env, long_labels, ""])
    return out


def _overlaps(a: dict[str, float], b: dict[str, float]) -> bool:
    return (
        a["l"] < b["r"] - 0.5
        and b["l"] < a["r"] - 0.5
        and a["t"] < b["b"] - 0.5
        and b["t"] < a["b"] - 0.5
    )


def _row_annos(out: dict[str, Any]) -> list[dict[str, Any]]:
    return out["annos"][: out["rowCount"]]


@pytest.mark.parametrize("stacked", [False, True])
def test_rendered_bars_geometry_desktop(
    guarded_page: Page, open_app: Callable[[Page, str], None], stacked: bool
) -> None:
    partial = {"school": ["northfield"], **({"bars": "stacked"} if stacked else {})}
    out = _render(guarded_page, open_app, partial, "barsModel", _DESKTOP)
    assert len(out["bars"]) == out["expected"]
    for anno in _row_annos(out):
        assert not any(_overlaps(anno, bar) for bar in out["bars"])
        assert anno["r"] <= out["plotLeft"] + 1
    assert all(
        b["l"] >= out["plotLeft"] - 1 and b["r"] <= out["plotRight"] + 1 for b in out["bars"]
    )


@pytest.mark.parametrize("stacked", [False, True])
def test_rendered_bars_geometry_phone(
    guarded_page: Page, open_app: Callable[[Page, str], None], stacked: bool
) -> None:
    partial = {"school": ["northfield"], **({"bars": "stacked"} if stacked else {})}
    out = _render(guarded_page, open_app, partial, "barsModel", _PHONE, long_labels=True)
    assert len(out["bars"]) == out["expected"]
    for i, anno in enumerate(_row_annos(out)):
        assert not any(_overlaps(anno, bar) for bar in out["bars"]), anno
        bar_top = out["centers"][i] - 22 / 2
        assert anno["b"] <= bar_top + 1
    assert out["scrollWidth"] <= out["clientWidth"]
    assert all(
        b["l"] >= out["plotLeft"] - 1 and b["r"] <= out["plotRight"] + 1 for b in out["bars"]
    )


def test_rendered_bar_label_with_markup_creates_no_element(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    imgs = guarded_page.evaluate(
        """async () => {
          const F = await import('./modules/bar-chart.js');
          const row = { key: 'k', name: 'x', label: '<img src=x onerror=alert(1)>', family: null,
                        total: 1, target: null, segments: [] };
          const fig = F.buildBarFigure({ mode: 'simple' }, [row],
            { theme: 'light', mobile: false, revision: 1, width: 700 });
          const gd = document.createElement('div');
          gd.style.width = '700px';
          document.body.appendChild(gd);
          await F.renderBars(gd, fig);
          return { imgs: gd.querySelectorAll('img').length,
                   text: gd.querySelector('g.annotation').textContent };
        }"""
    )
    assert imgs["imgs"] == 0
    assert imgs["text"] == "<img src=x onerror=alert(1)>"


def test_rendered_bind_bar_events(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    page = guarded_page
    open_app(page, "")
    page.evaluate(
        """async () => {
          const D = await import('./modules/data.js');
          const S = await import('./modules/select.js');
          const B = await import('./modules/bars.js');
          const F = await import('./modules/bar-chart.js');
          const raw = await (await fetch('site-data.json')).json();
          const data = D.prepareData(raw);
          const state = Object.assign(S.defaultState(data), { school: ['northfield'] });
          const model = B.barsModel(data, S.computeView(data, state), state);
          const fig = F.buildBarFigure(model, model.rows,
            { theme: 'light', mobile: false, revision: 1, width: 900 });
          const gd = document.createElement('div');
          gd.id = 'test-bars';
          gd.style.cssText = 'width:900px;position:relative;';
          document.body.appendChild(gd);
          await F.renderBars(gd, fig);
          window.__ev = { clicks: [], hovers: [], labels: [], unhover: 0 };
          F.bindBarEvents(gd, {
            onPointClick: (ref) => window.__ev.clicks.push(ref),
            onPointHover: (ref) => window.__ev.hovers.push(ref),
            onPointUnhover: () => { window.__ev.unhover += 1; },
            onLabelClick: (i) => window.__ev.labels.push(i),
          });
        }"""
    )
    page.locator("#test-bars").scroll_into_view_if_needed()
    bar = page.locator("#test-bars .bars .point path").first.bounding_box()
    assert bar is not None
    page.mouse.move(bar["x"] + bar["width"] / 2, bar["y"] + bar["height"] / 2)
    page.mouse.click(bar["x"] + bar["width"] / 2, bar["y"] + bar["height"] / 2)
    label = page.locator("#test-bars g.annotation").first.bounding_box()
    assert label is not None
    page.mouse.click(label["x"] + label["width"] / 2, label["y"] + label["height"] / 2)
    ev = page.evaluate("window.__ev")
    assert {"r": 0, "s": -1, "side": None} in ev["hovers"]
    assert ev["clicks"][0] == {"r": 0, "s": -1, "side": None}
    assert ev["labels"] == [0]


@pytest.mark.parametrize("width", [1280, 800])
@pytest.mark.parametrize("long_labels", [False, True])
def test_rendered_butterfly_spine_desktop(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    width: int,
    long_labels: bool,
) -> None:
    env = {**_DESKTOP, "width": width}
    out = _render(
        guarded_page,
        open_app,
        {"school": ["northfield", "lakeview"]},
        "butterflyModel",
        env,
        long_labels,
    )
    assert len(out["bars"]) == out["expected"]
    col_l, col_r = out["x1End"], out["x2Start"]
    for anno in _row_annos(out):
        assert anno["l"] >= col_l - 4 and anno["r"] <= col_r + 4, (anno, col_l, col_r)
        assert not any(_overlaps(anno, bar) for bar in out["bars"]), anno
        assert len(anno["text"]) <= 22
    mid = (col_l + col_r) / 2
    assert abs((mid - col_l) - (col_r - mid)) <= 2
    assert abs((out["x1End"] - out["x1Start"]) - (out["x2End"] - out["x2Start"])) <= 2


def test_rendered_butterfly_stacked_spine_has_no_overlap(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    out = _render(
        guarded_page,
        open_app,
        {"people": ["kris-venn", "pat-rowan"], "bars": "stacked"},
        "butterflyModel",
        _DESKTOP,
        long_labels=True,
    )
    assert len(out["bars"]) == out["expected"]
    for anno in _row_annos(out):
        assert not any(_overlaps(anno, bar) for bar in out["bars"])


def test_rendered_butterfly_phone_labels_above(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    out = _render(
        guarded_page,
        open_app,
        {"school": ["northfield", "lakeview"]},
        "butterflyModel",
        _PHONE,
        long_labels=True,
    )
    assert len(out["bars"]) == out["expected"]
    for i, anno in enumerate(_row_annos(out)):
        assert not any(_overlaps(anno, bar) for bar in out["bars"]), anno
        assert anno["b"] <= out["centers"][i] - 32 / 2 + 1
    span = out["x2End"] - out["x1Start"]
    assert span == pytest.approx(390 - 16, abs=2)
    assert out["scrollWidth"] <= out["clientWidth"]


def test_rendered_butterfly_side_name_is_escaped(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    res = guarded_page.evaluate(
        """async () => {
          const F = await import('./modules/bar-chart.js');
          const side = () => ({ total: 1, segments: [] });
          const row = { key: 'k', name: 'x', label: 'x', family: null, total: 2, target: null,
                        sides: [side(), side()] };
          const model = { mode: 'simple', sides: [{ name: '<b>x</b>' }, { name: 'B' }] };
          const fig = F.buildButterflyFigure(model, [row],
            { theme: 'light', mobile: false, revision: 1, width: 900 });
          const gd = document.createElement('div');
          gd.style.width = '900px';
          document.body.appendChild(gd);
          await F.renderBars(gd, fig);
          return { bold: gd.querySelectorAll('b').length,
                   texts: Array.from(gd.querySelectorAll('g.annotation'))
                     .map((e) => e.textContent) };
        }"""
    )
    assert res["bold"] == 0
    assert "<b>x</b>" in res["texts"]
