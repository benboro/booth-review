"""Copy strings and Plotly figures for the Bars and Butterfly tabs (SITE-34,
SITE-35; D-01, D-06, D-15, D-16, D-18, D-20).

Builder tests import the DOM-free modules into the served page; tests with
`rendered` in the name open the real app and draw with `window.Plotly`.
"""

from __future__ import annotations

import json
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
    ({"school": ["northfield"], "bars": "stacked"}, "Networks by announcer · Northfield"),
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
        "Networks by announcer: Northfield and Lakeview",
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
    assert stacked[1] == {"text": "2 rated telecasts on Alpha Sports", "kind": "body"}
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
        "Bar chart: announcers by rated telecasts, Northfield, 2019–2026. Showing 5 of 5. "
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
        "Butterfly chart: announcers for Northfield and Lakeview, 2019–2026. Showing 7 of 7. "
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
