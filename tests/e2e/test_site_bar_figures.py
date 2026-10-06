"""Copy strings and Plotly figures for the Bars and Butterfly tabs (SITE-34,
SITE-35; D-01, D-06, D-15, D-16, D-18, D-20).

Builder tests import the DOM-free modules into the served page; tests with
`rendered` in the name open the real app and draw with `window.Plotly`.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from itertools import pairwise
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


def _run(
    page: Page,
    site_url: str,
    partial: dict[str, Any],
    body: str,
    raw: dict[str, Any] | None = None,
) -> Any:
    if raw is not None:
        page.route("**/site-data.json*", lambda route: route.fulfill(json=raw))
    page.goto(f"{site_url}/")
    return page.evaluate(_RUN_JS, [partial, body])


_TITLE_BARS = "(c) => c.C.chartTitle(c.bars, c.data, c.state)"
_TITLE_FLY = "(c) => c.C.chartTitle(c.fly, c.data, c.state)"

_BARS_TITLES: list[tuple[dict[str, Any], str]] = [
    ({"school": ["northfield"]}, "Announcers by games with Northfield"),
    (
        {"school": ["northfield"], "by": "network"},
        "Networks by games with Northfield",
    ),
    ({"people": ["kris-venn"]}, "Teams by games with Kris Venn"),
    ({"people": ["kris-venn"], "by": "conference"}, "Conferences by games with Kris Venn"),
    ({"networks": ["net-a", "net-b"]}, "Teams by games on Alpha Sports or Beta Network"),
    (
        {"networks": ["net-a", "net-b", "net-c", "net-d"]},
        "Teams by games on 4 networks",
    ),
    ({"networks": []}, "Teams by games on no networks"),
    (
        {"school": ["northfield", "lakeview"]},
        "Announcers by games with Northfield or Lakeview",
    ),
    (
        {"school": ["northfield", "lakeview", "ironpeak"]},
        "Announcers by games with Northfield or Lakeview or Ironpeak",
    ),
    (
        {"school": ["northfield"], "networks": ["net-a"], "by": "team"},
        "Teams by games with Northfield on Alpha Sports",
    ),
    (
        {"school": ["northfield"], "people": ["dale-harlow"]},
        "Announcers by games with Dale Harlow and Northfield",
    ),
    (
        {"school": ["northfield"], "people": ["dale-harlow"], "by": "team"},
        "Teams by games with Dale Harlow and Northfield",
    ),
    (
        {"people": ["kris-venn", "jax-venn"], "together": True},
        "Teams by games with Kris Venn and Jax Venn",
    ),
    (
        {"people": ["kris-venn", "pat-rowan"], "compare": True},
        "Teams by games with Kris Venn or Pat Rowan",
    ),
    (
        {"people": ["kris-venn", "pat-rowan"]},
        "Teams by games with Kris Venn or Pat Rowan",
    ),
    (
        {
            "people": ["kris-venn", "jax-venn"],
            "together": True,
            "school": ["ironpeak", "foxhollow"],
        },
        "Announcers by games with (Kris Venn and Jax Venn) and (Ironpeak or Foxhollow)",
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
        {"school": ["northfield", "lakeview"], "by": "network"},
        "Networks by games: Northfield and Lakeview",
    ),
    ({"people": ["kris-venn", "pat-rowan"]}, "Teams: Kris Venn and Pat Rowan"),
    (
        {"people": ["kris-venn", "pat-rowan"], "by": "conference"},
        "Conferences by games: Kris Venn and Pat Rowan",
    ),
    (
        {"school": ["northfield", "lakeview"], "people": ["dale-harlow"]},
        "Announcers: Northfield and Lakeview with Dale Harlow",
    ),
    (
        {"people": ["kris-venn", "pat-rowan"], "school": ["ironpeak"]},
        "Teams: Kris Venn and Pat Rowan with Ironpeak",
    ),
    (
        {
            "school": ["northfield", "lakeview"],
            "people": ["kris-venn", "jax-venn"],
            "together": True,
            "by": "team",
        },
        "Teams: Kris Venn and Jax Venn with Northfield or Lakeview",
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
            count1: c.C.gameCount(1, 1),
            count7: c.C.gameCount(6, 14),
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
        "count1": "1 rated of 1 game",
        "count7": "6 rated of 14 games",
    }


_KEY = "Solid bars are games with a public rating. Outlined bars are games with no public rating."
_STACK_SUM = (
    "Each game counts once for every announcer in it, so a bar can be longer than its "
    "number of games."
)
_TEAM_COUNT = (
    "Each game counts once for every team in it, so team totals can add up to more than the "
    "number of games."
)
_NON_FILTER = "Non-FBS and unlisted conferences can't be used as a filter."


def test_caption_lines(guarded_page: Page, site_url: str) -> None:
    page = guarded_page
    cap = "(c) => c.C.captionLines(c.bars ?? c.fly, (c.bars ?? c.fly).rows)"
    assert _run(page, site_url, {"school": ["northfield"]}, cap) == [_KEY]
    assert _run(page, site_url, {"school": ["northfield"], "by": "network"}, cap) == [
        _KEY,
        _STACK_SUM,
        _SHADE_CAPTION,
    ]
    assert _run(page, site_url, {"people": ["kris-venn"]}, cap) == [_KEY, _TEAM_COUNT]
    assert _run(page, site_url, {"people": ["kris-venn"], "by": "conference"}, cap) == [
        _KEY,
        _TEAM_COUNT,
    ]
    fly = _run(
        page,
        site_url,
        {"school": ["northfield", "lakeview"]},
        "(c) => c.C.captionLines(c.fly, c.fly.rows)",
    )
    assert fly == [_KEY, "3 games include both."]
    out = _run(
        page,
        site_url,
        {"school": ["northfield", "lakeview"]},
        """(c) => [0, 1, 2].map((n) => c.C.captionLines({ ...c.fly, shared: n }, []))""",
    )
    assert out == [
        [_KEY, "0 games include both."],
        [_KEY, "1 game includes both."],
        [_KEY, "2 games include both."],
    ]
    non = _run(
        page,
        site_url,
        {"school": ["maplecrest"], "networks": ["net-d"], "by": "conference"},
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
        {"text": "Dale Harlow", "kind": "title", "roles": ["pbp"]},
        {"text": "2 rated of 2 games", "kind": "body"},
        {"text": "Click to filter →", "kind": "hint"},
    ]
    assert simple[1][2] == {"text": "Tap again to filter →", "kind": "hint"}
    stacked = _run(
        page,
        site_url,
        {"school": ["northfield"], "by": "network"},
        "(c) => c.C.tooltipLines(c.bars, c.bars.rows, { r: 0, s: 0, side: null }, {})",
    )
    assert stacked[0] == {"text": "Dale Harlow", "kind": "title", "roles": ["pbp"]}
    assert stacked[1] == {"text": "Alpha Sports: 2 rated of 2 games", "kind": "body", "shade": 0}
    assert stacked[2] == {"text": "2 rated of 2 games on ABC/ESPN", "kind": "body"}
    fly = _run(
        page,
        site_url,
        {"school": ["northfield", "lakeview"]},
        "(c) => c.C.tooltipLines(c.fly, c.fly.rows, { r: 0, s: -1, side: 0 }, {})",
    )
    assert fly[1] == {"text": "Northfield: 2 rated of 2 games", "kind": "body"}
    conf = _run(
        page,
        site_url,
        {"school": ["maplecrest"], "networks": ["net-d"], "by": "conference"},
        """(c) => {
          const i = c.bars.rows.findIndex((r) => r.target == null);
          return c.C.tooltipLines(c.bars, c.bars.rows, { r: i, s: -1, side: null }, {});
        }""",
    )
    assert [line["kind"] for line in conf] == ["title", "body"]


_SHADE_CAPTION = (
    "Shades within a network family's bar mark its channels. "
    "Hover or tap a segment for each channel's count."
)


def test_family_tooltip_lines(
    guarded_page: Page, site_url: str, multichannel: dict[str, Any]
) -> None:
    page = guarded_page
    body = "(c) => c.C.tooltipLines(c.{m}, c.{m}.rows, {ref}, {opts})"
    stacked = {"school": ["northfield"], "by": "network"}
    ref0 = _run(
        page,
        site_url,
        stacked,
        body.format(m="bars", ref="{ r: 0, s: 0, side: null }", opts="{}"),
        multichannel,
    )
    assert ref0 == [
        {"text": "Dale Harlow", "kind": "title", "roles": ["pbp"]},
        {"text": "Alpha Sports: 1 rated of 1 game", "kind": "body", "shade": 0},
        {"text": "Echo Sports: 1 rated of 1 game", "kind": "body", "shade": 1},
        {"text": "2 rated of 2 games on ABC/ESPN", "kind": "body"},
        {"text": "Click to filter →", "kind": "hint"},
    ]
    touch = _run(
        page,
        site_url,
        stacked,
        body.format(m="bars", ref="{ r: 0, s: 0, side: null }", opts="{ touch: true }"),
        multichannel,
    )
    assert touch[-1] == {"text": "Tap again to filter →", "kind": "hint"}
    robin = _run(
        page,
        site_url,
        stacked,
        body.format(m="bars", ref="{ r: 0, s: 6, side: null }", opts="{}"),
        multichannel,
    )
    assert robin == [
        {"text": "Robin Teague", "kind": "title", "roles": ["unknown"]},
        {"text": "Echo Sports: 1 rated of 1 game", "kind": "body", "shade": 1},
        {"text": "1 rated of 1 game on ABC/ESPN", "kind": "body"},
        {"text": "Click to filter →", "kind": "hint"},
    ]
    fly = _run(
        page,
        site_url,
        {"school": ["northfield", "lakeview"], "by": "network"},
        body.format(m="fly", ref="{ r: 0, s: 0, side: 1 }", opts="{}"),
        multichannel,
    )
    assert fly == [
        {"text": "Casey Lund", "kind": "title", "roles": ["pbp"]},
        {"text": "Alpha Sports: 1 rated of 1 game", "kind": "body", "shade": 0},
        {"text": "Lakeview: 1 rated of 1 game on ABC/ESPN", "kind": "body"},
        {"text": "Click to filter →", "kind": "hint"},
    ]


def test_family_caption_and_counts_text(
    guarded_page: Page, site_url: str, multichannel: dict[str, Any]
) -> None:
    page = guarded_page
    cap = "(c) => c.C.captionLines(c.{m}, c.{m}.rows)"
    bars = _run(
        page,
        site_url,
        {"school": ["northfield"], "by": "network"},
        cap.format(m="bars"),
        multichannel,
    )
    assert bars == [_KEY, _STACK_SUM, _SHADE_CAPTION]
    fly = _run(
        page,
        site_url,
        {"school": ["northfield", "lakeview"], "by": "network"},
        cap.format(m="fly"),
        multichannel,
    )
    assert fly[0] == _KEY and _STACK_SUM in fly and _SHADE_CAPTION in fly
    plain = _run(page, site_url, {"school": ["northfield"], "by": "network"}, cap.format(m="bars"))
    assert _SHADE_CAPTION in plain  # stacked Announcers are family rows on the shared fixture too
    simple = _run(page, site_url, {"school": ["northfield"]}, cap.format(m="bars"))
    assert _SHADE_CAPTION not in simple
    out = _run(
        page,
        site_url,
        {"school": ["northfield"]},
        """(c) => ({
          line: c.C.channelLineText({ name: 'Alpha Sports', count: 1, rated: 1 }),
          name: c.C.countsListName({ kind: 'family', family: 'disney', ids: ['net-a'] },
                                   'ABC/ESPN', 7, 9),
        })""",
    )
    assert out == {
        "line": "Alpha Sports: 1 rated of 1 game",
        "name": "Show only ABC/ESPN, 7 rated of 9 games",
    }


def test_counts_list_names(guarded_page: Page, site_url: str) -> None:
    out = _run(
        guarded_page,
        site_url,
        {"school": ["northfield", "lakeview"]},
        """(c) => ({
          person: c.C.countsListName({ kind: 'person', id: 'x' }, 'Dale Harlow', 2, 2),
          team: c.C.countsListName({ kind: 'team', slug: 'x' }, 'Foxhollow', 2, 3),
          network: c.C.countsListName({ kind: 'network', id: 'x' }, 'Alpha Sports', 7, 9),
          conf: c.C.countsListName({ kind: 'conference', name: 'SEC' }, 'SEC', 3, 4),
          text: c.C.butterflyRowText(c.fly.rows[0], c.fly),
          name: c.C.butterflyCountsName(c.fly.rows[0], c.fly),
        })""",
    )
    assert out == {
        "person": "Add Dale Harlow as a filter, 2 rated of 2 games",
        "team": "Add Foxhollow to the School filter, 2 rated of 3 games",
        "network": "Show only Alpha Sports, 7 rated of 9 games",
        "conf": "Add SEC to the Conference filter, 3 rated of 4 games",
        "text": "Dale Harlow (PBP): Northfield 2 rated of 2 games, Lakeview 1 rated of 1 game",
        "name": (
            "Add Dale Harlow as a filter, Northfield 2 rated of 2 games, Lakeview 1 rated of 1 game"
        ),
    }


def test_aria_summaries(guarded_page: Page, site_url: str) -> None:
    page = guarded_page
    aria = "(c) => c.C.ariaSummary(c.bars ?? c.fly, c.data, c.state, (c.bars ?? c.fly).rows.length)"
    assert _run(page, site_url, {"school": ["northfield"]}, aria) == (
        "Bar chart: announcers by games with Northfield, 2019\u20132026. Showing 9 of 9. "
        "Top: Dale Harlow (PBP) 2 rated of 2 games, Dale Harlow Jr. (Analyst) 2 rated of 2 games, "
        "Casey Lund (PBP) 1 rated of 1 game."
    )
    one_year = _run(page, site_url, {"school": ["northfield"], "seasons": [2025, 2025]}, aria)
    assert "with Northfield, 2025." in one_year
    fly = _run(
        page,
        site_url,
        {"school": ["northfield", "lakeview"]},
        "(c) => c.C.ariaSummary(c.fly, c.data, c.state, c.fly.rows.length)",
    )
    assert fly == (
        "Butterfly chart: announcers: Northfield and Lakeview, 2019\u20132026. Showing 10 of 10. "
        "3 games include both. Top: Dale Harlow (PBP) 2 rated of 2 games and 1 rated of 1 game, "
        "Dale Harlow Jr. (Analyst) 2 rated of 2 games and 1 rated of 1 game."
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
    assert "No games for this selection." in out
    assert "Widen the season range" in out


# --------------------------------------------------------------------------
# Task 2: palette helpers and the Bars figure builder
# --------------------------------------------------------------------------

_FIG_JS = """
async ([partial, fn, env, inflate]) => {
  const D = await import('./modules/data.js');
  const S = await import('./modules/select.js');
  const B = await import('./modules/bars.js');
  const F = await import('./modules/bar-chart.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  const state = Object.assign(S.defaultState(data), partial);
  const view = S.computeView(data, state);
  const model = B[fn](data, view, state);
  if (inflate && inflate !== 1) {
    const side = (o) => {
      o.total *= inflate;
      (o.segments ?? []).forEach((g) => {
        g.count *= inflate;
        (g.channels ?? []).forEach((c) => { c.count *= inflate; });
      });
    };
    model.rows.forEach((r) => { side(r); (r.sides ?? []).forEach(side); });
  }
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
    raw: dict[str, Any] | None = None,
    inflate: int = 1,
) -> dict[str, Any]:
    if raw is not None:
        page.route("**/site-data.json*", lambda route: route.fulfill(json=raw))
    page.goto(f"{site_url}/")
    out: dict[str, Any] = page.evaluate(_FIG_JS, [partial, fn, env or _DESKTOP, inflate])
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
            mainTones: F.barTones({ family: null, mainFamily: 'fox' }, 'light'),
            mainMix: P.mixHex('#009E73', '#FFFFFF', 0.55),
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
    assert out["plainTones"] == {"a": "#7C3AED", "b": "#B793F5"}
    assert out["mainTones"] == {"a": "#009E73", "b": out["mainMix"]}  # D-31


def test_channel_shades(guarded_page: Page, site_url: str) -> None:
    guarded_page.goto(f"{site_url}/")
    out = guarded_page.evaluate(
        """async () => {
          const P = await import('./modules/palette.js');
          const res = { pairs: [], base: [], same: true, n1: [], n0: null };
          for (const theme of ['light', 'dark']) {
            for (const fam of P.FAMILY_ORDER) {
              const s = P.channelShades(fam, theme, 5);
              res.base.push([s[0], P.FAMILY_COLORS[theme][fam]]);
              res.same = res.same
                && JSON.stringify(s) === JSON.stringify(P.channelShades(fam, theme, 5));
              res.pairs.push([fam, theme, new Set(s).size, s.length,
                Math.min(...s.flatMap((a, i) =>
                  s.slice(i + 1).map((b) => P.contrastRatio(a, b))))]);
            }
          }
          res.n1 = P.channelShades('disney', 'light', 1);
          res.n0 = P.channelShades('disney', 'light', 0);
          return res;
        }"""
    )
    assert all(a == b for a, b in out["base"])
    assert out["same"]
    assert len(out["pairs"]) == 16
    for fam, theme, distinct, length, worst in out["pairs"]:
        assert distinct == length == 5, (fam, theme)
        assert worst >= 1.15, (fam, theme, worst)
    assert out["n1"] == ["#0072B2"]
    assert out["n0"] == []


def test_readable_text_on_all(guarded_page: Page, site_url: str) -> None:
    guarded_page.goto(f"{site_url}/")
    out = guarded_page.evaluate(
        """async () => {
          const P = await import('./modules/palette.js');
          return {
            one: [P.readableTextOnAll(['#0072B2']), P.readableTextOn('#0072B2')],
            empty: P.readableTextOnAll([]),
            ok: P.readableTextOnAll(['#0072B2', '#004A73']),
            bad: P.readableTextOnAll(['#000000', '#FFFFFF']),
          };
        }"""
    )
    assert out["one"][0] == out["one"][1]
    assert out["empty"] is None
    assert out["ok"] == "#FFFFFF"
    assert out["bad"] is None


_THEMES = ["light", "dark"]
_VIOLET_CASES = [
    ({"people": ["kris-venn"]}, "barsModel"),
    ({"people": ["kris-venn"], "by": "conference"}, "barsModel"),
    ({"people": ["kris-venn", "pat-rowan"]}, "butterflyModel"),
    ({"people": ["kris-venn", "pat-rowan"], "by": "conference"}, "butterflyModel"),
]


@pytest.mark.parametrize("theme", _THEMES)
@pytest.mark.parametrize(("partial", "fn"), _VIOLET_CASES)
def test_non_network_bars_are_violet(
    guarded_page: Page, site_url: str, theme: str, partial: dict[str, Any], fn: str
) -> None:
    guarded_page.goto(f"{site_url}/")
    tones = guarded_page.evaluate(
        """async (theme) => {
          const P = await import('./modules/palette.js');
          const mix = (h, bg) => P.mixHex(h, bg, 0.55);
          return {
            a: P.SPECIAL[theme], b: mix(P.SPECIAL[theme], P.PAGE_BG[theme]),
            ma: P.MUTED[theme], mb: mix(P.MUTED[theme], P.PAGE_BG[theme]),
          };
        }""",
        theme,
    )
    out = _figure(guarded_page, site_url, partial, fn, {**_DESKTOP, "theme": theme})
    colors: set[str] = set()
    for trace in out["figure"]["traces"]:
        hexes = {c for c in trace["marker"]["color"] if c.startswith("#")}
        colors |= hexes
        if not hexes:  # an unrated part: 25% fill, border in the full tone (D-15)
            assert set(trace["marker"]["line"]["color"]) <= {tones["a"], tones["b"]}
    assert colors <= {tones["a"], tones["b"]}
    assert colors
    assert not colors & {tones["ma"], tones["mb"]}


@pytest.mark.parametrize("theme", _THEMES)
def test_violet_text_contrast(guarded_page: Page, site_url: str, theme: str) -> None:
    guarded_page.goto(f"{site_url}/")
    want = guarded_page.evaluate(
        """async (theme) => {
          const P = await import('./modules/palette.js');
          const b = P.mixHex(P.SPECIAL[theme], P.PAGE_BG[theme], 0.55);
          return { a: P.readableTextOn(P.SPECIAL[theme]), b: P.readableTextOn(b),
                   ra: P.contrastRatio(P.SPECIAL[theme], P.readableTextOn(P.SPECIAL[theme])),
                   rb: P.contrastRatio(b, P.readableTextOn(b)) };
        }""",
        theme,
    )
    expected = ("#FFFFFF", "#000000") if theme == "light" else ("#000000", "#FFFFFF")
    assert (want["a"], want["b"]) == expected
    assert want["ra"] >= 4.5 and want["rb"] >= 4.5
    out = _figure(
        guarded_page,
        site_url,
        {"people": ["kris-venn"], "by": "conference"},
        env={**_DESKTOP, "theme": theme},
    )
    texted = [t for t in out["figure"]["traces"] if "textfont" in t]  # rated layers only
    assert texted
    for k, trace in enumerate(texted):
        assert set(trace["textfont"]["color"]) == {expected[k % 2]}
    assert all(
        not t.get("text") or not any(t["text"])
        for t in out["figure"]["traces"]
        if "textfont" not in t
    )


@pytest.mark.parametrize("theme", _THEMES)
def test_rendered_violet_matches_css_token(
    guarded_page: Page, open_app: Callable[[Page, str], None], theme: str
) -> None:
    guarded_page.emulate_media(color_scheme=theme)  # type: ignore[arg-type]
    out = _render(
        guarded_page,
        open_app,
        {"people": ["kris-venn"]},
        "barsModel",
        {**_DESKTOP, "theme": theme},
    )
    assert out["bars"]
    res = guarded_page.evaluate(
        """async () => {
          const P = await import('./modules/palette.js');
          const css = getComputedStyle(document.documentElement)
            .getPropertyValue('--special').trim().toUpperCase();
          const fill = getComputedStyle(
            document.querySelector('#test-bars .bars .point path')).fill;
          const hex = '#' + fill.match(/\\d+/g).slice(0, 3)
            .map((n) => Number(n).toString(16).padStart(2, '0')).join('').toUpperCase();
          return { css, hex, light: P.SPECIAL.light, dark: P.SPECIAL.dark };
        }"""
    )
    assert res["css"] == res[theme]
    assert res["hex"] == res[theme]


def test_simple_bar_figure_shape(guarded_page: Page, site_url: str) -> None:
    out = _figure(guarded_page, site_url, {"school": ["northfield"]})
    figure, rows = out["figure"], out["model"]["rows"]
    n = len(rows)
    rated, unrated = figure["traces"]  # D-15: always one rated and one unrated trace
    assert (rated["type"], rated["orientation"]) == ("bar", "h")
    assert rated["x"] == [r["rated"] for r in rows]
    assert unrated["x"] == [r["total"] - r["rated"] for r in rows]
    assert rated["y"] == unrated["y"] == [r["key"] for r in rows]
    assert any(v == 0 for v in rated["x"]) and any(v > 0 for v in unrated["x"])
    # D-31: Northfield's games are all net-a (Disney), so announcer bars are Disney blue.
    # (the crews of the unrated FOX games take the FOX family's green)
    assert set(rated["marker"]["color"]) == {"#0072B2", "#009E73"}
    assert set(unrated["marker"]["color"]) == {"rgba(0,114,178,0.25)", "rgba(0,158,115,0.25)"}
    assert unrated["marker"]["line"] == {"width": 1.5, "color": rated["marker"]["color"]}
    assert "text" not in unrated and "text" not in rated
    assert rated["hoverinfo"] == unrated["hoverinfo"] == "none"
    assert not rated["showlegend"] and not unrated["showlegend"]
    refs = [{"r": i, "s": -1, "side": None} for i in range(n)]
    assert rated["customdata"] == unrated["customdata"] == refs
    layout = figure["layout"]
    assert layout["barmode"] == "stack"
    assert layout["xaxis"]["title"]["text"] == "Games"
    assert layout["yaxis"]["range"] == [n - 0.5, -0.5]  # reversed, one pitch per row
    assert layout["yaxis"]["showticklabels"] is False
    assert layout["dragmode"] is False
    assert figure["config"]["displayModeBar"] is False
    assert layout["height"] == n * 32 + 72
    annos = layout["annotations"]
    assert len(annos) == 2 * n  # row labels, then one total of games per row (D-29)
    assert all(a["captureevents"] is True for a in annos[:n])
    assert [a["text"] for a in annos[n:]] == [str(r["total"]) for r in rows]
    assert "transition" not in layout


def test_stacked_bar_figure_shape(guarded_page: Page, site_url: str) -> None:
    out = _figure(guarded_page, site_url, {"people": ["kris-venn"], "by": "conference"})
    figure, rows = out["figure"], out["model"]["rows"]
    layout = figure["layout"]
    assert layout["barmode"] == "stack"
    assert layout["uniformtext"] == {"mode": "hide", "minsize": 14}
    depth = max(len(r["segments"]) for r in rows)
    assert len(figure["traces"]) == 2 * depth  # rated layers, then unrated layers (D-15)
    for k, un in enumerate(figure["traces"][depth:]):
        tone = "#7C3AED" if k % 2 == 0 else "#B793F5"
        assert un["marker"]["line"] == {"width": 1.5, "color": [tone] * len(rows)}
        assert not any(un["text"])
        for i, row in enumerate(rows):
            seg = row["segments"][k] if k < len(row["segments"]) else None
            assert un["x"][i] == (seg["count"] - seg["rated"] if seg else 0)
            assert un["customdata"][i] == ({"r": i, "s": k, "side": None} if seg else None)
    for k, trace in enumerate(figure["traces"][:depth]):
        assert set(trace["marker"]["color"]) == {"#7C3AED" if k % 2 == 0 else "#B793F5"}
        assert trace["marker"]["line"] == {"width": 3, "color": "#FFFFFF"}  # D-28
        for i, row in enumerate(rows):
            if k < len(row["segments"]):
                assert trace["x"][i] == row["segments"][k]["rated"]
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
    # D-29 appends total annotations after the row labels; those never capture events.
    n = len(rows)
    assert [a["captureevents"] for a in layout["annotations"][:n]] == [
        r["target"] is not None for r in rows
    ]
    assert all(a["name"] == "total" for a in layout["annotations"][n:])


_MAIN_FAMILY_LIGHT = [
    "#009E73", "#0072B2", "#8F8F8F", "#0072B2", "#009E73",
    "#0072B2", "#0072B2", "#0072B2", "#0072B2", "#0072B2", "#009E73",
]  # fmt: skip
_MAIN_FAMILY_DARK = [
    "#009E73", "#0072B2", "#999999", "#0072B2", "#009E73",
    "#0072B2", "#0072B2", "#0072B2", "#0072B2", "#0072B2", "#009E73",
]  # fmt: skip


@pytest.mark.parametrize("theme", _THEMES)
def test_simple_announcer_bars_use_main_family_color(
    guarded_page: Page, site_url: str, theme: str
) -> None:
    out = _figure(
        guarded_page,
        site_url,
        {"school": ["ironpeak", "foxhollow", "stonebridge"]},
        env={**_DESKTOP, "theme": theme},
    )
    trace, unrated = out["figure"]["traces"]
    tones = _MAIN_FAMILY_LIGHT if theme == "light" else _MAIN_FAMILY_DARK
    assert trace["marker"]["color"] == tones
    assert unrated["marker"]["line"]["color"] == tones  # same hue, outlined (D-15)
    accent = {"light": "#111827", "dark": "#E5E7EB"}[theme]
    totals = [a for a in out["figure"]["layout"]["annotations"] if a.get("name") == "total"]
    assert totals and all(a["font"]["color"] == accent for a in totals)


def test_butterfly_announcer_bars_use_main_family_color(guarded_page: Page, site_url: str) -> None:
    out = _figure(guarded_page, site_url, {"school": ["lakeview", "maplecrest"]}, "butterflyModel")
    left, left_unrated, right, right_unrated = out["figure"]["traces"]
    by_label = {r["label"]: i for i, r in enumerate(out["model"]["rows"])}
    casey = by_label["Robin Teague"]  # main family "other" (grey)
    jamie = by_label["Jamie Oaks"]
    for trace in (left, right):
        assert trace["marker"]["color"][casey] == "#8F8F8F"
        assert trace["marker"]["color"][jamie] == "#0072B2"
    for trace in (left_unrated, right_unrated):
        assert trace["marker"]["line"]["color"][casey] == "#8F8F8F"
        assert trace["marker"]["line"]["color"][jamie] == "#0072B2"


def _totals(figure: dict[str, Any], axis: str) -> list[tuple[int, str]]:
    return [
        (a["y"], a["text"])
        for a in figure["layout"]["annotations"]
        if a.get("name") == "total" and a["xref"] == axis
    ]


@pytest.mark.parametrize(
    ("partial", "expected"),
    [
        ({"school": ["northfield"], "by": "network"}, [(0, "9"), (1, "2")]),
        (
            {"people": ["kris-venn"], "by": "conference"},
            [(0, "3"), (1, "3"), (2, "1"), (3, "1")],
        ),
    ],
)
def test_stacked_totals_on_bars(
    guarded_page: Page, site_url: str, partial: dict[str, Any], expected: list[tuple[int, str]]
) -> None:
    out = _figure(guarded_page, site_url, partial)
    annos = out["figure"]["layout"]["annotations"]
    n = len(out["model"]["rows"])
    assert [a.get("name") for a in annos[:n]] == [None] * n
    totals = annos[n:]
    assert [(a["y"], a["text"]) for a in totals] == expected
    for a in totals:
        assert a["name"] == "total" and a["xref"] == "x" and a["yref"] == "y"
        assert a["x"] == int(a["text"])
        assert a["xanchor"] == "left" and a["showarrow"] is False
        assert a["captureevents"] is False
    simple = _figure(guarded_page, site_url, {"school": ["northfield"]})
    simple_totals = [
        a for a in simple["figure"]["layout"]["annotations"] if a.get("name") == "total"
    ]
    assert len(simple_totals) == len(simple["model"]["rows"])  # D-29 covers simple bars too


@pytest.mark.parametrize(
    ("partial", "left", "right"),
    [
        (
            {"school": ["northfield", "lakeview"], "by": "network"},
            [(0, "9"), (1, "2")],
            [(0, "4"), (1, "4")],
        ),
        (
            {"people": ["kris-venn", "pat-rowan"], "by": "conference"},
            [(0, "1"), (1, "3"), (3, "3"), (4, "1")],
            [(0, "4"), (1, "1"), (2, "4"), (3, "1"), (4, "1"), (5, "1")],
        ),
    ],
)
def test_stacked_totals_on_butterfly(
    guarded_page: Page,
    site_url: str,
    partial: dict[str, Any],
    left: list[tuple[int, str]],
    right: list[tuple[int, str]],
) -> None:
    out = _figure(guarded_page, site_url, partial, "butterflyModel")
    figure = out["figure"]
    n = len(out["model"]["rows"])
    annos = figure["layout"]["annotations"]
    assert [a["yref"] for a in annos[n : n + 2]] == ["paper", "paper"]  # side titles
    assert _totals(figure, "x") == left
    assert _totals(figure, "x2") == right
    for a in annos[n + 2 :]:
        assert a["name"] == "total" and a["captureevents"] is False
        assert (a["xanchor"] == "right") == (a["xref"] == "x")


@pytest.mark.parametrize("env", [_DESKTOP, {**_DESKTOP, "width": 800}, _PHONE])
@pytest.mark.parametrize(
    ("partial", "fn"),
    [
        ({"people": ["kris-venn"], "by": "conference"}, "barsModel"),
        ({"people": ["kris-venn"]}, "barsModel"),
        ({"people": ["kris-venn", "pat-rowan"], "by": "conference"}, "butterflyModel"),
    ],
)
def test_total_text_has_room_in_the_range(
    guarded_page: Page, site_url: str, env: dict[str, Any], partial: dict[str, Any], fn: str
) -> None:
    out = _figure(guarded_page, site_url, partial, fn, env, inflate=100)
    layout = out["figure"]["layout"]
    rows = out["model"]["rows"]
    if fn == "barsModel":
        peak = max(r["total"] for r in rows)
        length = env["width"] - layout["margin"]["l"] - layout["margin"]["r"]
        top = layout["xaxis"]["range"][1]
        assert top >= peak * 1.12 - 1e-9
    else:
        peak = max(max(r["sides"][0]["total"], r["sides"][1]["total"]) for r in rows)
        dom = layout["xaxis"]["domain"]
        length = (env["width"] - 16) * (dom[1] - dom[0])
        top = layout["xaxis2"]["range"][1]
        assert top >= peak * 1.1 - 1e-9
    reserve = math.ceil(7.6 * len(str(peak))) + 8
    assert top >= peak * length / (length - reserve) - 1e-9


def test_network_rows_use_family_color(guarded_page: Page, site_url: str) -> None:
    out = _figure(guarded_page, site_url, {"school": ["northfield"], "by": "network"})
    first = out["figure"]["traces"][0]
    # Shade 0 is each row's family color: ABC/ESPN blue, FOX/FS1/BTN green.
    assert set(first["marker"]["color"]) == {"#0072B2", "#009E73"}
    assert first["marker"]["line"] == {"width": 0}


def test_phone_bar_figure_layout(guarded_page: Page, site_url: str) -> None:
    out = _figure(guarded_page, site_url, {"school": ["northfield"]}, env=_PHONE)
    layout = out["figure"]["layout"]
    assert layout["margin"]["l"] == 8 and layout["margin"]["r"] == 8
    n = len(out["model"]["rows"])
    assert layout["height"] == n * 44 + 72
    labels = layout["annotations"][:n]
    assert all(a["yanchor"] == "bottom" and a["xanchor"] == "left" for a in labels)


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
    left, left_un, right, right_un = figure["traces"]  # rated then unrated per half (D-15)
    assert left["xaxis"] == left_un["xaxis"] == "x"
    assert right["xaxis"] == right_un["xaxis"] == "x2"
    for side, (rated, unrated) in enumerate(((left, left_un), (right, right_un))):
        assert rated["x"] == [r["sides"][side]["rated"] for r in rows]
        assert unrated["x"] == [r["sides"][side]["total"] - r["sides"][side]["rated"] for r in rows]
        assert unrated["marker"]["line"]["width"] == 1.5
        for i, row in enumerate(rows):
            for trace in (rated, unrated):
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
    assert layout["xaxis"]["title"]["text"] == layout["xaxis2"]["title"]["text"] == "Games"
    n = len(rows)
    annos = layout["annotations"]
    assert [a["text"] for a in annos[n : n + 2]] == ["Northfield", "Lakeview"]
    assert (annos[n]["xanchor"], annos[n + 1]["xanchor"]) == ("right", "left")
    assert all(a["name"] == "total" for a in annos[n + 2 :])
    assert layout["meta"]["rowCount"] == n == 10


def test_butterfly_stacked_figure_matches_bars_builder(guarded_page: Page, site_url: str) -> None:
    out = _figure(
        guarded_page,
        site_url,
        {"people": ["kris-venn", "pat-rowan"], "by": "conference"},
        "butterflyModel",
    )
    figure = out["figure"]
    assert figure["layout"]["barmode"] == "stack"
    assert figure["layout"]["uniformtext"] == {"mode": "hide", "minsize": 14}
    rated = [t for t in figure["traces"] if "textposition" in t]
    unrated = [t for t in figure["traces"] if "textposition" not in t]
    assert rated and len(rated) == len(unrated)  # same layers either way (D-15)
    for trace in rated:
        assert trace["marker"]["line"] == {"width": 3, "color": "#FFFFFF"}  # D-28
        assert trace["textposition"] == "inside"
    for trace in unrated:
        assert trace["marker"]["line"]["width"] == 1.5
    assert {t["xaxis"] for t in figure["traces"]} == {"x", "x2"}


def test_butterfly_desktop_spine_gap_grows_with_labels(guarded_page: Page, site_url: str) -> None:
    guarded_page.goto(f"{site_url}/")
    out = guarded_page.evaluate(
        """async () => {
          const F = await import('./modules/bar-chart.js');
          const w = (n) => F.textWidth('W'.repeat(n));
          return [F.spineGapPx(w(5)), F.spineGapPx(w(22)), F.spineGapPx(w(30))];
        }"""
    )
    assert out[0] == 160
    assert out[1] > 160
    assert out[2] > out[1]


@pytest.mark.parametrize("font_setting", ["default", "dejavu", "wide"], indirect=True)
def test_text_width_tracks_the_rendered_font(guarded_page: Page, site_url: str) -> None:
    """`textWidth` must agree with what the browser lays out in the page's font."""
    guarded_page.goto(f"{site_url}/")
    out = guarded_page.evaluate(
        """async () => {
          const F = await import('./modules/bar-chart.js');
          const text = 'Long Announcer Name Number 12 PBP';
          const probe = document.createElement('span');
          probe.style.cssText = 'font:14px/1.4 ' + getComputedStyle(document.body).fontFamily
            + ';white-space:pre;position:absolute;visibility:hidden';
          probe.textContent = text;
          document.body.appendChild(probe);
          const real = probe.getBoundingClientRect().width;
          probe.remove();
          return { real, measured: F.textWidth(text), estimate: 7.6 * text.length };
        }"""
    )
    assert out["measured"] == pytest.approx(out["real"], abs=1.5)


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
async ([partial, fn, env, longLabels, sideName, inflate]) => {
  const D = await import('./modules/data.js');
  const S = await import('./modules/select.js');
  const B = await import('./modules/bars.js');
  const F = await import('./modules/bar-chart.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  const state = Object.assign(S.defaultState(data), partial);
  const view = S.computeView(data, state);
  const model = B[fn](data, view, state);
  if (inflate && inflate !== 1) {
    const side = (o) => {
      o.total *= inflate;
      (o.segments ?? []).forEach((g) => {
        g.count *= inflate;
        (g.channels ?? []).forEach((c) => { c.count *= inflate; });
      });
    };
    model.rows.forEach((r) => { side(r); (r.sides ?? []).forEach(side); });
  }
  if (longLabels) {
    model.rows.forEach((r, i) => { r.label = `Long Announcer Name Number ${i} PBP`; });
  }
  if (sideName && model.sides) {
    model.sides.forEach((side) => { side.name = sideName; });
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
  const paths = Array.from(gd.querySelectorAll('.bars .point path')).map((el) => {
    const cs = getComputedStyle(el);
    return { ...rect(el), fill: cs.fill, fo: Number(cs.fillOpacity), stroke: cs.stroke,
             sw: Number.parseFloat(cs.strokeWidth) };
  }).filter((r) => r.w > 0.5);
  const P = await import('./modules/palette.js');
  const shades = rows.map((r) => (r.family != null && r.shadeCount != null
    ? P.channelShades(r.family, env.theme, r.shadeCount) : null));
  const expected = figure.traces.reduce(
    (n, t) => n + t.x.filter((v) => v > 0).length, 0);
  const annos = Array.from(gd.querySelectorAll('g.annotation')).map((el) => ({
    text: el.textContent, index: Number(el.getAttribute('data-index')), ...rect(el) }));
  const full = gd._fullLayout;
  const gdRect = gd.getBoundingClientRect();
  const center = (i) => gdRect.top + full._size.t + full.yaxis.d2p(i);
  const out = {
    bars, expected, annos, paths, shades,
    model: { rowKind: model.rowKind, rows: JSON.parse(JSON.stringify(rows)) },
    rowCount: rows.length,
    centers: rows.map((_, i) => center(i)),
    imgs: gd.querySelectorAll('img').length,
    scrollWidth: gd.scrollWidth,
    clientWidth: gd.clientWidth,
    gdLeft: gdRect.left,
    gdTop: gdRect.top,
    figAnnos: figure.layout.annotations.map(
      (a) => ({ name: a.name ?? null, y: a.y, xref: a.xref })),
    gdRight: gdRect.right,
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


GEOMETRY_FONTS = ["default", "dejavu", "wide"]


def _render(
    page: Page,
    open_app: Callable[[Page, str], None],
    partial: dict[str, Any],
    fn: str,
    env: dict[str, Any],
    long_labels: bool = False,
    side_name: str = "",
    raw: dict[str, Any] | None = None,
    inflate: int = 1,
) -> dict[str, Any]:
    if raw is not None:
        page.route("**/site-data.json*", lambda route: route.fulfill(json=raw))
    open_app(page, "")
    out: dict[str, Any] = page.evaluate(
        _RENDER_JS, [partial, fn, env, long_labels, side_name, inflate]
    )
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


@pytest.mark.parametrize("font_setting", GEOMETRY_FONTS, indirect=True)
@pytest.mark.parametrize("stacked", [False, True])
def test_rendered_bars_geometry_desktop(
    guarded_page: Page, open_app: Callable[[Page, str], None], stacked: bool
) -> None:
    partial = {"school": ["northfield"], **({"by": "network"} if stacked else {})}
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
    partial = {"school": ["northfield"], **({"by": "network"} if stacked else {})}
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


@pytest.mark.parametrize("font_setting", GEOMETRY_FONTS, indirect=True)
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


@pytest.mark.parametrize("font_setting", GEOMETRY_FONTS, indirect=True)
def test_rendered_butterfly_stacked_spine_has_no_overlap(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    out = _render(
        guarded_page,
        open_app,
        {"people": ["kris-venn", "pat-rowan"], "by": "conference"},
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


@pytest.mark.parametrize("mobile", [False, True])
def test_butterfly_headers_hug_the_spine(guarded_page: Page, site_url: str, mobile: bool) -> None:
    env = {**_PHONE, "width": 358} if mobile else _DESKTOP
    out = _figure(
        guarded_page, site_url, {"school": ["northfield", "lakeview"]}, "butterflyModel", env
    )
    layout = out["figure"]["layout"]
    n = len(out["model"]["rows"])
    left, right = layout["annotations"][n : n + 2]
    g = 0 if mobile else layout["xaxis2"]["domain"][0] - 0.5
    assert left["x"] == pytest.approx(0.5 - g)
    assert right["x"] == pytest.approx(0.5 + g)
    assert (left["xanchor"], right["xanchor"]) == ("right", "left")
    assert left["borderpad"] == 0 and right["borderpad"] == 0
    assert (left.get("xshift", 0), right.get("xshift", 0)) == ((-4, 4) if mobile else (0, 0))
    guarded_page.goto(f"{site_url}/")
    text = guarded_page.evaluate(
        """async () => {
          const F = await import('./modules/bar-chart.js');
          const side = () => ({ total: 1, segments: [] });
          const row = { key: 'k', name: 'x', label: 'x', family: null, total: 2, target: null,
                        sides: [side(), side()] };
          const model = { mode: 'simple', sides: [{ name: 'A'.repeat(40) }, { name: 'B' }] };
          const fig = F.buildButterflyFigure(model, [row], { theme: 'light', mobile: false,
                                                             revision: 1, width: 1000 });
          return fig.layout.annotations[1].text;
        }"""
    )
    assert text == "A" * 21 + "\u2026"


_HEADER_CASES = [
    {"school": ["northfield", "lakeview"]},
    {"people": ["kris-venn", "pat-rowan"]},
]


@pytest.mark.parametrize("long_name", [False, True])
@pytest.mark.parametrize("stacked", [False, True])
@pytest.mark.parametrize("partial", _HEADER_CASES)
@pytest.mark.parametrize("width", [1280, 800, 358])
def test_rendered_butterfly_headers_hug_the_spine(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    width: int,
    partial: dict[str, Any],
    stacked: bool,
    long_name: bool,
) -> None:
    mobile = width == 358
    env = {**_DESKTOP, "width": width, "mobile": mobile}
    out = _render(
        guarded_page,
        open_app,
        {
            **partial,
            **({"by": "conference" if "people" in partial else "network"} if stacked else {}),
        },
        "butterflyModel",
        env,
        side_name="N" * 40 if long_name else "",
    )
    n = out["rowCount"]
    by_index = {a["index"]: a for a in out["annos"]}
    left, right = by_index[n], by_index[n + 1]
    if mobile:
        assert out["x1End"] - 7 <= left["r"] <= out["x1End"] + 1
        assert out["x2Start"] - 1 <= right["l"] <= out["x2Start"] + 7
    else:
        assert abs(left["r"] - out["x1End"]) <= 2
        assert abs(right["l"] - out["x2Start"]) <= 2
    assert left["r"] <= right["l"]
    assert left["l"] >= out["gdLeft"] - 1 and right["r"] <= out["gdRight"] + 1


# --------------------------------------------------------------------------
# D-23: family bars with channel shades under announcer segments (Plan 10)
# --------------------------------------------------------------------------

_FAM_BARS = {"school": ["northfield"], "by": "network"}
_FAM_FLY = {"school": ["northfield", "lakeview"], "by": "network"}
_TRANSPARENT = "rgba(0,0,0,0)"


def _split_traces(figure: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pieces = [t for t in figure["traces"] if t["hoverinfo"] == "skip"]
    overlays = [t for t in figure["traces"] if t["hoverinfo"] == "none"]
    assert len(pieces) + len(overlays) == len(figure["traces"])
    return pieces, overlays


def _halves(traces: list[dict[str, Any]], axis: str) -> tuple[list[Any], list[Any]]:
    """The rated and unrated traces on `axis`: always emitted in equal numbers (D-15)."""
    on = [t for t in traces if t["xaxis"] == axis]
    assert len(on) % 2 == 0
    return on[: len(on) // 2], on[len(on) // 2 :]


def _nonzero(traces: list[dict[str, Any]], axis: str) -> int:
    return sum(1 for t in traces if t["xaxis"] == axis for v in t["x"] if v > 0)


def test_family_stack_figure_shape(
    guarded_page: Page, site_url: str, multichannel: dict[str, Any]
) -> None:
    out = _figure(guarded_page, site_url, _FAM_BARS, raw=multichannel)
    figure = out["figure"]
    pieces, overlays = _split_traces(figure)
    rated_p, unrated_p = _halves(pieces, "x")
    rated_o, unrated_o = _halves(overlays, "x3")
    assert (_nonzero(rated_p, "x"), _nonzero(unrated_p, "x")) == (7, 4)
    assert (_nonzero(rated_o, "x3"), _nonzero(unrated_o, "x3")) == (5, 4)
    assert {t["xaxis"] for t in pieces} == {"x"}
    for t in rated_p:
        assert t["marker"]["line"]["width"] == 0
        assert not any(t.get("text", []))
    for t in unrated_p:
        assert t["marker"]["line"]["width"] == 1.5
        assert not any(t.get("text", []))
    colors = {c for t in rated_p for c in t["marker"]["color"]}
    assert colors == {"#0072B2", "#66AAD1", "#009E73"}  # net-a, net-e shade 1, FOX family
    assert {c for t in unrated_p for c in t["marker"]["line"]["color"]} == colors
    assert all(
        c.startswith("rgba(") and c.endswith(",0.25)")
        for t in unrated_p
        for c in t["marker"]["color"]
    )
    depth = len(rated_o)
    for k, t in enumerate(overlays):
        assert t["xaxis"] == "x3"
        assert t["marker"]["color"] == _TRANSPARENT
        assert t["marker"]["line"] == {"width": 3, "color": "#FFFFFF"}  # D-28
        assert t["customdata"][0] == {"r": 0, "s": k % depth, "side": None}
    assert not any(any(t["text"]) for t in unrated_o if "text" in t)
    layout = figure["layout"]
    x3 = layout["xaxis3"]
    assert x3["overlaying"] == "x" and x3["anchor"] == "y"
    assert x3["visible"] is False and x3["fixedrange"] is True
    assert x3["range"] == layout["xaxis"]["range"]


def test_family_butterfly_figure_shape(
    guarded_page: Page, site_url: str, multichannel: dict[str, Any]
) -> None:
    out = _figure(guarded_page, site_url, _FAM_FLY, "butterflyModel", raw=multichannel)
    figure = out["figure"]
    pieces, overlays = _split_traces(figure)
    counts = [
        tuple(_nonzero(half, axis) for half in _halves(group, axis))
        for group, axis in ((pieces, "x"), (pieces, "x2"), (overlays, "x3"), (overlays, "x4"))
    ]
    assert counts == [(7, 4), (6, 2), (5, 4), (6, 2)]
    assert {t["xaxis"] for t in pieces} == {"x", "x2"}
    assert {t["xaxis"] for t in overlays} == {"x3", "x4"}
    sides = {
        t["customdata"][i]["side"]
        for t in overlays
        for i in range(len(t["x"]))
        if t["customdata"][i] is not None
    }
    assert sides == {0, 1}
    layout = figure["layout"]
    assert layout["xaxis3"]["overlaying"] == "x"
    assert layout["xaxis4"]["overlaying"] == "x2"
    assert layout["xaxis3"]["range"] == layout["xaxis"]["range"]
    assert layout["xaxis4"]["range"] == layout["xaxis2"]["range"]
    assert layout["meta"]["rowCount"] == len(out["model"]["rows"])


def test_trace_count_ignores_whether_unrated_games_exist(
    guarded_page: Page, site_url: str, multichannel: dict[str, Any]
) -> None:
    """D-15: unrated traces are always emitted, so the layer count never depends on the data."""
    guarded_page.route("**/site-data.json*", lambda route: route.fulfill(json=multichannel))
    guarded_page.goto(f"{site_url}/")
    cases = [
        ({"school": ["northfield"]}, "barsModel"),
        ({"people": ["kris-venn"], "by": "conference"}, "barsModel"),
        ({"school": ["northfield"], "by": "network"}, "barsModel"),
        ({"school": ["northfield", "lakeview"]}, "butterflyModel"),
        ({"school": ["northfield", "lakeview"], "by": "network"}, "butterflyModel"),
    ]
    for partial, fn in cases:
        counts = guarded_page.evaluate(
            """async ([partial, fn]) => {
              const D = await import('./modules/data.js');
              const S = await import('./modules/select.js');
              const B = await import('./modules/bars.js');
              const F = await import('./modules/bar-chart.js');
              const raw = await (await fetch('site-data.json')).json();
              const data = D.prepareData(raw);
              const state = Object.assign(S.defaultState(data), partial);
              const env = { theme: 'light', mobile: false, revision: 1, width: 1280 };
              const build = fn === 'barsModel' ? F.buildBarFigure : F.buildButterflyFigure;
              const make = () => B[fn](data, S.computeView(data, state), state);
              const count = (model) => build(model, model.rows, env).traces.length;
              const full = (o) => {
                o.rated = o.total ?? o.count;
                (o.segments ?? []).forEach(full);
                (o.channels ?? []).forEach((c) => { c.rated = c.count; });
              };
              const flat = make();
              flat.rows.forEach((r) => { full(r); (r.sides ?? []).forEach(full); });
              return [count(make()), count(flat)];
            }""",
            [partial, fn],
        )
        assert counts[0] == counts[1], (partial, fn)


def test_conference_stack_still_uses_stack_traces(guarded_page: Page, site_url: str) -> None:
    out = _figure(guarded_page, site_url, {"people": ["kris-venn"], "by": "conference"})
    assert "xaxis3" not in out["figure"]["layout"]
    assert all(t["hoverinfo"] == "none" for t in out["figure"]["traces"])


def _hex(rgb: str) -> str:
    nums = [int(v) for v in rgb[rgb.index("(") + 1 : rgb.index(")")].split(",")[:3]]
    return "#" + "".join(f"{v:02X}" for v in nums)


def _row_groups(out: dict[str, Any], fn: str, spine: float) -> dict[tuple[int, int], Any]:
    """Pieces and overlay paths grouped by (row, side), ordered away from the spine/zero."""
    groups: dict[tuple[int, int], dict[str, list[dict[str, Any]]]] = {}
    for p in out["paths"]:
        yc = (p["t"] + p["b"]) / 2
        row = min(range(out["rowCount"]), key=lambda i: abs(out["centers"][i] - yc))
        side = 0 if fn == "barsModel" or (p["l"] + p["r"]) / 2 < spine else 1
        kind = "overlay" if p["fo"] == 0 else "piece"
        groups.setdefault((row, side), {"piece": [], "overlay": []})[kind].append(p)
    for g in groups.values():
        for lst in g.values():
            lst.sort(key=lambda p: p["l"])
    return groups


def _expected_parts(out: dict[str, Any], fn: str) -> dict[tuple[int, int], list[Any]]:
    """Per (row, side): (segment, rated?) parts in drawing order: every rated part
    (segment order), then every unrated part (D-15). Zero-width parts are left out."""
    exp: dict[tuple[int, int], list[Any]] = {}
    for i, row in enumerate(out["model"]["rows"]):
        sides = [row] if fn == "barsModel" else row["sides"]
        for side, src in enumerate(sides):
            segs = src["segments"]
            exp[(i, side)] = [(s, True) for s in segs if s["rated"] > 0] + [
                (s, False) for s in segs if s["count"] - s["rated"] > 0
            ]
    return exp


def _part_channels(seg: dict[str, Any], rated: bool) -> list[dict[str, Any]]:
    return [c for c in seg["channels"] if (c["rated"] if rated else c["count"] - c["rated"]) > 0]


@pytest.mark.parametrize("theme", _THEMES)
@pytest.mark.parametrize("width", [1280, 800, 358])
@pytest.mark.parametrize(
    ("partial", "fn"), [(_FAM_BARS, "barsModel"), (_FAM_FLY, "butterflyModel")]
)
def test_rendered_family_segments_align_with_channel_pieces(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    multichannel: dict[str, Any],
    theme: str,
    width: int,
    partial: dict[str, Any],
    fn: str,
) -> None:
    env = {"theme": theme, "mobile": width < 600, "revision": 1, "width": width}
    out = _render(guarded_page, open_app, partial, fn, env, raw=multichannel)
    assert len(out["bars"]) == out["expected"]
    spine = (out["x1End"] + out["x2Start"]) / 2 if fn == "butterflyModel" else 0
    groups = _row_groups(out, fn, spine)
    expected = _expected_parts(out, fn)
    n_pieces = sum(len(g["piece"]) for g in groups.values())
    n_over = sum(len(g["overlay"]) for g in groups.values())
    # 7 + 4 (Bars) and 13 + 6 (Butterfly) pieces; 5 + 4 and 11 + 6 announcer overlays.
    assert (n_pieces, n_over) == ((11, 9) if fn == "barsModel" else (19, 17))
    bg = {"light": "#FFFFFF", "dark": "#14161A"}[theme]
    for key, segs in expected.items():
        if not segs:
            assert key not in groups
            continue
        g = groups[key]
        row_index, side = key
        shades = out["shades"][row_index]
        # Left butterfly side runs right-to-left: walk from the spine outward.
        rev = fn == "butterflyModel" and side == 0
        pieces = sorted(g["piece"], key=lambda p: -p["l"] if rev else p["l"])
        overlays = sorted(g["overlay"], key=lambda p: -p["l"] if rev else p["l"])
        assert len(overlays) == len(segs)
        cursor = 0
        for (seg, rated), over in zip(segs, overlays, strict=True):
            chans = _part_channels(seg, rated)
            mine = pieces[cursor : cursor + len(chans)]
            cursor += len(chans)
            assert len(mine) == len(chans)
            assert min(p["l"] for p in mine) == pytest.approx(over["l"], abs=1)
            assert max(p["r"] for p in mine) == pytest.approx(over["r"], abs=1)
            assert [_hex(p["fill"]) for p in mine] == [shades[c["shade"]] for c in chans]
            if rated:  # solid
                assert all(p["fo"] == pytest.approx(1) for p in mine)
            else:  # 25% fill with a 1.5px border in the channel shade (D-15)
                assert all(p["fo"] == pytest.approx(0.25) for p in mine)
                assert [_hex(p["stroke"]) for p in mine] == [shades[c["shade"]] for c in chans]
                assert all(p["sw"] == pytest.approx(1.5, abs=0.01) for p in mine)
            assert _hex(over["stroke"]) == bg
            assert over["sw"] == pytest.approx(2 if width < 600 else 3, abs=0.01)  # D-28
    assert out["shades"][0][0] == "#0072B2"


@pytest.mark.parametrize(
    ("partial", "fn"), [(_FAM_BARS, "barsModel"), (_FAM_FLY, "butterflyModel")]
)
def test_rendered_family_segment_events(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    multichannel: dict[str, Any],
    partial: dict[str, Any],
    fn: str,
) -> None:
    page = guarded_page
    page.route("**/site-data.json*", lambda route: route.fulfill(json=multichannel))
    open_app(page, "")
    page.evaluate(
        """async ([partial, fn]) => {
          const D = await import('./modules/data.js');
          const S = await import('./modules/select.js');
          const B = await import('./modules/bars.js');
          const F = await import('./modules/bar-chart.js');
          const raw = await (await fetch('site-data.json')).json();
          const data = D.prepareData(raw);
          const state = Object.assign(S.defaultState(data), partial);
          const model = B[fn](data, S.computeView(data, state), state);
          const build = fn === 'barsModel' ? F.buildBarFigure : F.buildButterflyFigure;
          const fig = build(model, model.rows,
            { theme: 'light', mobile: false, revision: 1, width: 1000 });
          const gd = document.createElement('div');
          gd.id = 'test-bars';
          gd.style.cssText = 'width:1000px;position:relative;';
          document.body.appendChild(gd);
          await F.renderBars(gd, fig);
          window.__ev = { clicks: [], hovers: [] };
          F.bindBarEvents(gd, {
            onPointClick: (ref) => window.__ev.clicks.push(ref),
            onPointHover: (ref) => window.__ev.hovers.push(ref),
          });
        }""",
        [partial, fn],
    )
    page.locator("#test-bars").scroll_into_view_if_needed()
    boxes = page.evaluate(
        """() => Array.from(document.querySelectorAll('#test-bars .bars .point path'))
          .filter((el) => getComputedStyle(el).fillOpacity === '0')
          .map((el) => { const r = el.getBoundingClientRect();
            return { x: r.left, y: r.top, w: r.width, h: r.height }; })
          .filter((r) => r.w > 0.5)"""
    )
    # Segment 0 of row 0 (Bars) is the widest-first bar; pick the first overlay path in DOM order.
    box = boxes[0]
    cx, cy = box["x"] + box["w"] / 2, box["y"] + box["h"] / 2
    page.mouse.move(cx - 3, cy)
    page.mouse.move(cx, cy)
    page.mouse.click(cx, cy)
    ev = page.evaluate("window.__ev")
    assert ev["clicks"], ev
    assert ev["hovers"], ev
    ref = ev["clicks"][0]
    assert ref["r"] == 0 and ref["s"] >= 0
    assert ev["hovers"][-1] == ref
    if fn == "barsModel":
        assert ref == {"r": 0, "s": 0, "side": None}
    else:
        assert ref["side"] in (0, 1)


def test_rendered_family_segment_markup_creates_no_element(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    imgs = guarded_page.evaluate(
        """async () => {
          const F = await import('./modules/bar-chart.js');
          const seg = { key: 'k', label: '<img src=x onerror=alert(1)>', count: 1, target: null,
                        channels: [{ id: 'a', name: 'A', count: 1, shade: 0 }] };
          const row = { key: 'f:disney', label: 'ABC/ESPN', family: 'disney', total: 1,
                        shadeCount: 1, target: null, segments: [seg] };
          const fig = F.buildBarFigure({ mode: 'stacked', rowKind: 'family' }, [row],
            { theme: 'light', mobile: false, revision: 1, width: 700 });
          const gd = document.createElement('div');
          gd.style.width = '700px';
          document.body.appendChild(gd);
          await F.renderBars(gd, fig);
          return gd.querySelectorAll('img').length;
        }"""
    )
    assert imgs == 0


def test_stacked_segment_text_escapes_markup_in_both_builders(
    guarded_page: Page, site_url: str
) -> None:
    """CR-01: a scraped name with markup is literal text in segment `text`."""
    guarded_page.goto(f"{site_url}/")
    out = guarded_page.evaluate(
        """async () => {
          const F = await import('./modules/bar-chart.js');
          const env = { theme: 'light', mobile: false, revision: 1, width: 700 };
          const plain = { key: 'k', label: '<b>Y</b>', count: 2, target: null };
          const person = { key: 'p:1', name: 'n', label: 'n', family: null, total: 2,
                           target: null, segments: [plain] };
          const seg = { key: 's', label: '<a href="https://x">X</a>', count: 3, target: null,
                        channels: [{ id: 'a', name: 'A', count: 3, shade: 0 }] };
          const fam = { key: 'f:disney', label: 'ABC/ESPN', family: 'disney', total: 3,
                        shadeCount: 1, target: null, segments: [seg] };
          const a = F.buildBarFigure({ mode: 'stacked', rowKind: 'person' }, [person], env);
          const b = F.buildBarFigure({ mode: 'stacked', rowKind: 'family' }, [fam], env);
          const texts = (fig) => fig.traces.flatMap((t) => (t.text ? t.text : []));
          return { a: texts(a), b: texts(b) };
        }"""
    )
    assert "&lt;b&gt;Y&lt;/b&gt; 2" in out["a"]
    assert '&lt;a href="https://x"&gt;X&lt;/a&gt; 3' in out["b"]
    for t in out["a"] + out["b"]:
        assert "<" not in t


# --------------------------------------------------------------------------
# D-28 segment gaps and D-29 total placement, measured on the rendered chart
# --------------------------------------------------------------------------

_PIXELS_JS = """
async ([b64, ys]) => {
  const img = new Image();
  img.src = 'data:image/png;base64,' + b64;
  await img.decode();
  const canvas = document.createElement('canvas');
  canvas.width = img.width;
  canvas.height = img.height;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(img, 0, 0);
  return {
    width: img.width,
    rows: ys.map((y) => Array.from(ctx.getImageData(0, y, img.width, 1).data)),
  };
}
"""

_PAGE_BG = {"light": (255, 255, 255), "dark": (20, 22, 26)}
_STACK_CASES = [
    (_FAM_BARS, "barsModel", True),
    (_FAM_FLY, "butterflyModel", True),
    ({"people": ["kris-venn"], "by": "conference"}, "barsModel", False),
    ({"people": ["kris-venn", "pat-rowan"], "by": "conference"}, "butterflyModel", False),
]


def _bg_run(rgba: list[int], x: float, half: int, bg: tuple[int, int, int]) -> int:
    """Longest run of page-background pixels within +-half px of column x."""
    best = run = 0
    for px in range(max(0, round(x) - half), min(len(rgba) // 4, round(x) + half + 1)):
        if all(abs(rgba[px * 4 + c] - bg[c]) <= 6 for c in range(3)):
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


@pytest.mark.parametrize("theme", _THEMES)
@pytest.mark.parametrize("width", [1280, 800, 358])
@pytest.mark.parametrize(("partial", "fn", "multi"), _STACK_CASES)
def test_rendered_stacked_segment_gaps(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    request: pytest.FixtureRequest,
    theme: str,
    width: int,
    partial: dict[str, Any],
    fn: str,
    multi: bool,
) -> None:
    import base64

    guarded_page.emulate_media(color_scheme=theme)  # type: ignore[arg-type]
    raw = request.getfixturevalue("multichannel") if multi else None
    env = {"theme": theme, "mobile": width < 600, "revision": 1, "width": width}
    out = _render(guarded_page, open_app, partial, fn, env, raw=raw)
    guarded_page.add_style_tag(content="#test-bars .bars text { display: none !important; }")
    spine = (out["x1End"] + out["x2Start"]) / 2 if fn == "butterflyModel" else 0
    announcer: list[tuple[int, float]] = []  # (row, x relative to the chart)
    channel: list[tuple[int, float]] = []
    for (row, _side), g in _row_groups(out, fn, spine).items():
        # Only the solid (rated) block has page-background separators; outlined unrated
        # parts after it are bordered in their own hue (D-15).
        solid = [p for p in g["piece"] if p["fo"] > 0.9]
        if not solid:
            continue
        lo, hi = min(p["l"] for p in solid), max(p["r"] for p in solid)
        segs = (
            [o for o in g["overlay"] if o["l"] >= lo - 1 and o["r"] <= hi + 1]
            if g["overlay"]
            else solid
        )
        edges = [(a["r"] + b["l"]) / 2 for a, b in pairwise(segs)]
        announcer += [(row, e - out["gdLeft"]) for e in edges]
        if g["overlay"]:
            pieces = solid
            for a, b in pairwise(pieces):
                e = (a["r"] + b["l"]) / 2
                if all(abs(e - x) > 2 for x in edges):
                    channel.append((row, e - out["gdLeft"]))
    assert announcer
    assert channel or not multi
    png = guarded_page.locator("#test-bars").screenshot()
    ys = [round(out["centers"][i] - out["gdTop"]) for i in range(out["rowCount"])]
    shot = guarded_page.evaluate(_PIXELS_JS, [base64.b64encode(png).decode(), ys])
    assert shot["width"] == round(out["gdRight"] - out["gdLeft"])  # device scale 1
    bg = _PAGE_BG[theme]
    need = 2 if width < 600 else 3
    for row, x in announcer:
        run = _bg_run(shot["rows"][row], x, 6, bg)
        assert run >= need, (row, x, run)
    for row, x in channel:
        assert _bg_run(shot["rows"][row], x, 2, bg) == 0, (row, x)


@pytest.mark.parametrize("inflate", [1, 100])
@pytest.mark.parametrize("width", [1280, 800, 358])
@pytest.mark.parametrize(("partial", "fn", "multi"), _STACK_CASES)
def test_rendered_stacked_totals_sit_past_the_bar_end(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    request: pytest.FixtureRequest,
    width: int,
    partial: dict[str, Any],
    fn: str,
    multi: bool,
    inflate: int,
) -> None:
    raw = request.getfixturevalue("multichannel") if multi else None
    env = {"theme": "light", "mobile": width < 600, "revision": 1, "width": width}
    out = _render(guarded_page, open_app, partial, fn, env, raw=raw, inflate=inflate)
    n = out["rowCount"]
    first = n + (2 if fn == "butterflyModel" else 0)
    spine = (out["x1End"] + out["x2Start"]) / 2 if fn == "butterflyModel" else 0
    groups = _row_groups(out, fn, spine)
    by_index = {a["index"]: a for a in out["annos"]}
    others = [a for a in out["annos"] if a["index"] < first]
    totals = out["figAnnos"][first:]
    assert totals
    assert all(t["name"] == "total" for t in totals)
    for k, t in enumerate(totals):
        anno = by_index[first + k]
        assert anno["text"] == str(round(float(anno["text"])))
        row, left = t["y"], t["xref"] == "x" and fn == "butterflyModel"
        g = groups[(row, 0 if left or fn == "barsModel" else 1)]
        paths = g["piece"] + g["overlay"]
        assert abs((anno["t"] + anno["b"]) / 2 - out["centers"][row]) <= 3
        if left:
            outer = min(p["l"] for p in paths)
            assert 0 <= outer - anno["r"] <= 12, (row, anno, outer)
        else:
            outer = max(p["r"] for p in paths)
            assert 0 <= anno["l"] - outer <= 12, (row, anno, outer)
        assert out["gdLeft"] <= anno["l"] and anno["r"] <= out["gdRight"]
        assert not any(_overlaps(anno, bar) for bar in out["bars"])
        assert not any(_overlaps(anno, other) for other in others)


def test_rendered_unrated_part_click_resolves_like_the_rated_part(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-15: hover and click on an outlined unrated part resolve to its segment."""
    page = guarded_page
    open_app(page, "")
    row = page.evaluate(
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
            { theme: 'light', mobile: false, revision: 1, width: 1000 });
          const gd = document.createElement('div');
          gd.id = 'test-bars';
          gd.style.cssText = 'width:1000px;position:relative;';
          document.body.appendChild(gd);
          await F.renderBars(gd, fig);
          window.__ev = { clicks: [], hovers: [] };
          F.bindBarEvents(gd, {
            onPointClick: (ref) => window.__ev.clicks.push(ref),
            onPointHover: (ref) => window.__ev.hovers.push(ref),
          });
          return model.rows.findIndex((r) => r.rated === 0 && r.total > 0);
        }"""
    )
    assert row >= 0  # a bar that is only an unrated part
    page.locator("#test-bars").scroll_into_view_if_needed()
    target = page.evaluate(
        """(row) => {
          const gd = document.getElementById('test-bars');
          const cy = gd.getBoundingClientRect().top
            + gd._fullLayout._size.t + gd._fullLayout.yaxis.d2p(row);
          const boxes = Array.from(gd.querySelectorAll('.bars .point path'))
            .map((el) => { const r = el.getBoundingClientRect();
              return { x: r.left, y: r.top, w: r.width, h: r.height }; })
            .filter((r) => r.w > 0.5 && Math.abs(r.y + r.h / 2 - cy) < 3);
          return boxes[0];
        }""",
        row,
    )
    assert target is not None
    cx, cy = target["x"] + target["w"] / 2, target["y"] + target["h"] / 2
    page.mouse.move(cx - 2, cy)
    page.mouse.move(cx, cy)
    page.mouse.click(cx, cy)
    ev = page.evaluate("window.__ev")
    assert ev["clicks"] and ev["hovers"], ev
    assert ev["clicks"][0] == {"r": row, "s": -1, "side": None}
    assert ev["hovers"][-1] == ev["clicks"][0]


_SPLIT_JS = """() => {
  const gd = document.getElementById('bars-chart');
  const sums = {};
  let negative = 0;
  for (const t of gd.data) {
    if (t.xaxis !== 'x' && t.xaxis !== 'x2') continue; // the overlay axes carry no extra games
    sums[t.xaxis] ??= t.y.map(() => 0);
    t.x.forEach((v, i) => { sums[t.xaxis][i] += v; if (v < 0) negative += 1; });
  }
  const totals = {};
  for (const a of gd.layout.annotations) {
    if (a.name !== 'total') continue;
    (totals[a.xref] ??= {})[a.y] = Number(a.text);
  }
  const keyCaptions = Array.from(document.querySelectorAll('#bars-captions .caption'))
    .filter((el) => el.textContent.startsWith('Solid bars') && el.getClientRects().length > 0);
  return { sums, totals, negative, keyCount: keyCaptions.length,
           scrollWidth: gd.scrollWidth, clientWidth: gd.clientWidth,
           title: gd.layout.xaxis.title.text };
}"""


@pytest.mark.parametrize("size", [(360, 800), (1280, 900)], ids=["phone", "desktop"])
@pytest.mark.parametrize(
    "query",
    ["?school=northfield&view=bars", "?school=northfield,lakeview&view=butterfly"],
    ids=["bars", "butterfly"],
)
def test_rendered_split_adds_up_at_phone_and_desktop_widths(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    size: tuple[int, int],
    query: str,
) -> None:
    """D-15: no negative parts, rated + unrated == total per row, one key, no overflow."""
    guarded_page.set_viewport_size({"width": size[0], "height": size[1]})
    open_app(guarded_page, query)
    guarded_page.wait_for_selector("#bars-chart .trace.bars .point path")
    out = guarded_page.evaluate(_SPLIT_JS)
    assert out["negative"] == 0
    assert out["title"] == "Games"
    assert out["keyCount"] == 1
    assert out["scrollWidth"] <= out["clientWidth"]
    assert out["sums"]
    for axis, sums in out["sums"].items():
        for i, total in enumerate(sums):
            if total > 0:
                assert out["totals"].get(axis, {}).get(str(i), out["totals"][axis].get(i)) == total
