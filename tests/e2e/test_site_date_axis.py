"""04.11 SITE-48: the Date x-axis foundation (geometry, label rule, copy, URL).

Exercises the served pure modules (date-axis.js, data.js, format.js,
url-state.js) against the synthetic fixture; nothing here needs a rendered chart.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from itertools import pairwise

import pytest
from playwright.sync_api import Page, expect
from test_site_chart import _RING_VISIBLE, _hover_dot

pytestmark = pytest.mark.e2e


@pytest.fixture
def app_page(guarded_page: Page, open_app: Callable[[Page, str], None]) -> Page:
    """The app loaded once so `import('./modules/...')` resolves."""
    open_app(guarded_page, "")
    return guarded_page


_BASICS_JS = """
async () => {
  const A = await import('./modules/date-axis.js');
  return {
    d1: A.epochDay('1970-01-02'),
    d2: A.epochDay('2019-09-07'),
    kNull: A.kickoffFraction(null),
    kLate: A.kickoffFraction('2021-10-02T22:30:00-04:00'),
    kNoon: A.kickoffFraction('2019-09-07T12:00:00-04:00'),
    pad: A.DATE_PAD,
    gap: A.DATE_GAP,
  };
}
"""

_FIXTURE_JS = """
async () => {
  const A = await import('./modules/date-axis.js');
  const D = await import('./modules/data.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  const ax = data.dateAxis;
  return {
    blocks: ax.blocks.map((b) => [b.season, b.start, b.end]),
    pad: ax.pad,
    gap: ax.gap,
    dateX: Array.from(data.t.dateX),
    seasons: Array.from(data.t.season),
    dates: data.t.date,
    date0: data.t.date[0],
    rawHasDateX: 'dateX' in raw.telecasts,
    dividersAll: A.gapDividers(ax.blocks),
    dividersOne: A.gapDividers([ax.blocks[0]]),
    rangeAll: A.seasonRange(ax, null),
    range2526: A.seasonRange(ax, [2025, 2026]),
    range21: A.seasonRange(ax, [2021, 2021]),
    rangeNone: A.seasonRange(ax, [2000, 2000]),
    shown: A.shownBlocks(ax, [2025, 2026]).map((b) => b.season),
    shownAll: A.shownBlocks(ax, null).map((b) => b.season),
  };
}
"""

_SYNTH_JS = """
async () => {
  const A = await import('./modules/date-axis.js');
  const { axis } = A.buildDateAxis([2030, 2030], ['2030-09-07', '2030-09-07'], [null, null]);
  return axis.blocks.map((b) => [b.start, b.end]);
}
"""


def test_epoch_day_and_kickoff_fraction(app_page: Page) -> None:
    out = app_page.evaluate(_BASICS_JS)
    assert out["d1"] == 1
    assert out["d2"] == 18146
    assert out["kNull"] == 0.5
    assert out["kLate"] == 22.5 / 24
    assert out["kNoon"] == 0.5
    assert (out["pad"], out["gap"]) == (1, 7)


def test_date_x_uses_et_kickoff_fraction_and_midday_for_null(app_page: Page) -> None:
    out = app_page.evaluate(_FIXTURE_JS)
    x = out["dateX"]
    assert x[0] == pytest.approx(1.5, abs=1e-9)
    assert x[1] == pytest.approx(71 + 15.5 / 24, abs=1e-9)
    assert x[2] == pytest.approx(81 + 22.5 / 24, abs=1e-9)
    assert x[3] == pytest.approx(144.5, abs=1e-9)
    blocks = {b[0]: b for b in out["blocks"]}
    for xi, season in zip(x, out["seasons"], strict=True):
        _, start, end = blocks[season]
        assert start < xi < end


def test_season_blocks_trim_to_own_span(app_page: Page) -> None:
    out = app_page.evaluate(_FIXTURE_JS)
    assert out["blocks"] == [[2019, 0, 73], [2021, 80, 146], [2025, 153, 240], [2026, 247, 278]]
    assert (out["pad"], out["gap"]) == (1, 7)
    assert app_page.evaluate(_SYNTH_JS) == [[0, 3]]


def test_gap_dividers_sit_at_gap_centers(app_page: Page) -> None:
    out = app_page.evaluate(_FIXTURE_JS)
    assert out["dividersAll"] == [76.5, 149.5, 243.5]
    assert out["dividersOne"] == []


def test_season_range_for_filters(app_page: Page) -> None:
    out = app_page.evaluate(_FIXTURE_JS)
    assert out["rangeAll"] == [0, 278]
    assert out["range2526"] == [153, 278]
    assert out["range21"] == [80, 146]
    assert out["rangeNone"] == [0, 278]
    assert out["shown"] == [2025, 2026]
    assert out["shownAll"] == [2019, 2021, 2025, 2026]


def test_t_date_column_untouched(app_page: Page) -> None:
    out = app_page.evaluate(_FIXTURE_JS)
    assert out["date0"] == "2019-09-07"
    assert all(isinstance(d, str) for d in out["dates"])
    assert out["rawHasDateX"] is False


_TIER_JS = """
async () => {
  const A = await import('./modules/date-axis.js');
  const { axis } = A.buildDateAxis([2030, 2030], ['2030-08-30', '2031-01-29'], [null, null]);
  const b = axis.blocks[0];
  const width = b.end - b.start;
  const out = { width };
  for (const px of [1400, 700, 400, 100, 20]) {
    out[px] = A.dateAxisLabels(axis.blocks, [b.start, b.end], px, { mobile: false });
  }
  return out;
}
"""

_TICKS_JS = """
async () => {
  const A = await import('./modules/date-axis.js');
  const D = await import('./modules/data.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  const b25 = data.dateAxis.blocks.find((b) => b.season === 2025);
  const wk = A.dateAxisLabels([b25], [b25.start, b25.end], 1200, { mobile: false });
  const bi = A.dateAxisLabels([b25], [b25.start, b25.end], 600, { mobile: false });
  const mo = A.dateAxisLabels([b25], [b25.start, b25.end], 266, { mobile: true });
  const cut = A.dateAxisLabels([b25], [b25.start + 30, b25.end], 1200, { mobile: false });
  return { b25, wk, bi, mo, cut, ppd: 1200 / (b25.end - b25.start) };
}
"""

_THIRTEEN_JS = """
async () => {
  const A = await import('./modules/date-axis.js');
  const season = [];
  const date = [];
  const kickoff = [];
  for (let y = 2014; y <= 2025; y += 1) {
    season.push(y, y);
    date.push(`${y}-08-30`, `${y + 1}-01-12`);
    kickoff.push(null, null);
  }
  season.push(2026, 2026);
  date.push('2026-09-05', '2026-10-03');
  kickoff.push(null, null);
  const { axis } = A.buildDateAxis(season, date, kickoff);
  const range = A.seasonRange(axis, null);
  const run = (px, mobile) => A.dateAxisLabels(axis.blocks, range, px, { mobile });
  return {
    range,
    nBlocks: axis.blocks.length,
    phone: run(266, true),
    desktop: run(1138, false),
    again: run(266, true),
    one: A.dateAxisLabels([axis.blocks[3]], [axis.blocks[3].start, axis.blocks[3].end], 266,
      { mobile: true }),
  };
}
"""


def _boxes(res: dict, plot_px: float, lo: float, hi: float, font: int) -> list[tuple[float, float]]:
    boxes = []
    for s in res["seasons"]:
        if not s["visible"]:
            continue
        center = (s["x"] - lo) * plot_px / (hi - lo) + s["xshift"]
        half = 0.62 * font * len(s["label"]) / 2
        boxes.append((center - half, center + half))
    return boxes


def test_label_tiers_by_px_per_day(app_page: Page) -> None:
    out = app_page.evaluate(_TIER_JS)
    assert out["width"] == 155
    assert [out[str(px)]["tier"] for px in (1400, 700, 400, 100, 20)] == [1, 2, 3, 4, 5]


def test_weekly_and_month_tick_text(app_page: Page) -> None:
    out = app_page.evaluate(_TICKS_JS)
    b25 = out["b25"]
    assert out["wk"]["tier"] == 1
    assert len(out["wk"]["tickvals"]) == 13
    assert out["wk"]["ticktext"][0] == "Sep 13"
    assert out["wk"]["tickvals"][0] == b25["start"] + 1 + 0.5
    assert out["bi"]["tier"] == 2
    assert out["bi"]["ticktext"] == out["wk"]["ticktext"][::2]
    assert out["mo"]["tier"] == 3
    assert out["mo"]["ticktext"] == ["Oct", "Nov", "Dec"]
    assert all(b25["start"] <= v <= b25["end"] for v in out["mo"]["tickvals"])
    # Ticks outside the visible range are dropped.
    assert all(v >= b25["start"] + 30 for v in out["cut"]["tickvals"])
    assert len(out["cut"]["tickvals"]) < 13
    assert all(not any(c.isdigit() and t.startswith("'") for c in t) for t in out["wk"]["ticktext"])


def test_phone_13_seasons_two_digit_all_visible_no_overlap(app_page: Page) -> None:
    out = app_page.evaluate(_THIRTEEN_JS)
    assert out["nBlocks"] == 13
    phone = out["phone"]
    lo, hi = out["range"]
    assert phone["twoDigit"] is True
    assert all(s["visible"] for s in phone["seasons"])
    assert [s["label"][0] for s in phone["seasons"]] == ["'"] * 13
    boxes = _boxes(phone, 266, lo, hi, 10)
    assert len(boxes) == 13
    for (_, r), (left, _) in pairwise(boxes):
        assert r <= left
    assert all(left >= -68 and right <= 288 for left, right in boxes)
    assert all(lo <= s["x"] <= hi for s in phone["seasons"])
    assert out["again"] == phone


def test_desktop_13_seasons_full_years(app_page: Page) -> None:
    out = app_page.evaluate(_THIRTEEN_JS)
    desk = out["desktop"]
    lo, hi = out["range"]
    assert desk["twoDigit"] is False
    assert [s["label"] for s in desk["seasons"]] == [str(y) for y in range(2014, 2027)]
    assert all(s["visible"] for s in desk["seasons"])
    boxes = _boxes(desk, 1138, lo, hi, 14)
    for (_, r), (left, _) in pairwise(boxes):
        assert r <= left


def test_single_block_full_year_and_months_at_phone(app_page: Page) -> None:
    out = app_page.evaluate(_THIRTEEN_JS)
    one = out["one"]
    assert len(one["seasons"]) == 1
    assert one["seasons"][0]["label"] == "2017"
    assert one["seasons"][0]["xshift"] == 0
    assert one["twoDigit"] is False
    assert app_page.evaluate(_TICKS_JS)["mo"]["tier"] == 3


_COPY_JS = """
async () => {
  const D = await import('./modules/data.js');
  const F = await import('./modules/format.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  const rows = [];
  for (let i = 0; i < data.n; i += 1) {
    rows.push({
      date: F.axisValueText(data, i, 'date'),
      spread: F.axisValueText(data, i, 'spread'),
      exc: F.axisValueText(data, i, 'excitement'),
    });
  }
  return { rows, label: F.AXIS_LABELS.date };
}
"""

_URL_JS = """
async () => {
  const D = await import('./modules/data.js');
  const S = await import('./modules/select.js');
  const U = await import('./modules/url-state.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  const base = S.defaultState(data);
  const dec = (q) => U.decodeState(q, data).axis;
  return {
    date: dec('?axis=date'),
    excitement: dec('?axis=excitement'),
    others: ['?axis=Date', '?axis=dates', '?axis=junk', '?axis=%', ''].map(dec),
    encDate: U.encodeState({ ...base, axis: 'date' }, data),
    encDefault: U.encodeState(base, data),
    encSpread: U.encodeState({ ...base, axis: 'spread' }, data),
  };
}
"""


def test_axis_line_shows_spread_and_excitement_on_date(app_page: Page) -> None:
    out = app_page.evaluate(_COPY_JS)
    assert out["label"] == "Date"
    for row in out["rows"]:
        assert row["date"] == f"{row['spread']} · {row['exc']}"
    assert out["rows"][3]["date"] == "Spread: not available · Excitement: 4.1"
    assert out["rows"][2]["date"].endswith(" · Excitement (CFBD): not available")


def test_axis_url_round_trip_and_allowlist(app_page: Page) -> None:
    out = app_page.evaluate(_URL_JS)
    assert out["date"] == "date"
    assert out["excitement"] == "excitement"
    assert out["others"] == ["spread"] * 5
    assert out["encDate"] == "?axis=date"
    assert out["encDefault"] == ""
    assert out["encSpread"] == ""


# ---------------------------------------------------------------------------
# Plan 02: the rendered Date axis (buildFigure branch + fitDateAxis hook)
# ---------------------------------------------------------------------------

_RELAYOUT_JS = "(r) => window.Plotly.relayout(document.getElementById('chart'), r)"
_WAIT_TWO_FRAMES = "() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))"

_STATE_JS = """
(patch) => { window.__testHooks.setState(patch); }
"""

_FIG_JS = """
() => {
  const gd = document.getElementById('chart');
  const l = gd.layout;
  const xs = [];
  const byIdx = {};
  for (const t of gd.data) {
    for (const x of t.x) xs.push(x);
    if (t.customdata) t.customdata.forEach((c, k) => { byIdx[c] = t.x[k]; });
  }
  const y = gd._fullLayout.yaxis.range.slice();
  return {
    title: l.xaxis.title ?? null,
    range: gd._fullLayout.xaxis.range.slice(),
    layoutRange: l.xaxis.range.slice(),
    minallowed: l.xaxis.minallowed,
    maxallowed: l.xaxis.maxallowed,
    shapes: (l.shapes ?? []).map((s) => (
      { x: s.x0, layer: s.layer, width: s.line.width, color: s.line.color })),
    anns: (l.annotations ?? []).map((a) => ({
      name: a.name ?? null, text: a.text, yref: a.yref, y: a.y, yanchor: a.yanchor,
      capture: a.captureevents,
      visible: a.visible, x: a.x, xshift: a.xshift,
    })),
    xs, byIdx, y,
    uirevision: l.uirevision,
    traces: gd.data.length,
    tickvals: l.xaxis.tickvals,
    ticktext: l.xaxis.ticktext,
    captionHidden: document.getElementById('excitement-caption')?.hidden ?? true,
  };
}
"""


def _fig(page: Page) -> dict:  # type: ignore[type-arg]
    page.evaluate(_WAIT_TWO_FRAMES)
    page.wait_for_timeout(150)
    return page.evaluate(_FIG_JS)  # type: ignore[no-any-return]


@pytest.fixture
def date_page(guarded_page: Page, open_app: Callable[[Page, str], None]) -> Page:
    guarded_page.set_viewport_size({"width": 1280, "height": 900})
    open_app(guarded_page, "?axis=date")
    return guarded_page


def test_date_axis_has_no_title_zero_line_or_captions(date_page: Page) -> None:
    f = _fig(date_page)
    assert f["title"] is None
    texts = [a["text"] for a in f["anns"]]
    assert not {"N/A", "← favorite won", "underdog won →"} & set(texts)
    assert f["captionHidden"] is True


def test_no_na_strip_and_all_dots_plotted(date_page: Page) -> None:
    f = _fig(date_page)
    date_x = date_page.evaluate("Array.from(window.__testHooks.data.t.dateX)")
    assert len(f["byIdx"]) + 0 <= len(date_x)
    assert sorted(f["xs"]) == sorted(date_x)
    assert len(f["xs"]) == 12
    assert f["range"][0] <= min(f["xs"]) and f["range"][1] >= max(f["xs"])


def test_gap_dividers_rendered(date_page: Page) -> None:
    f = _fig(date_page)
    assert f["layoutRange"] == [0, 278]
    assert [s["x"] for s in f["shapes"]] == [76.5, 149.5, 243.5]
    assert all(s["layer"] == "below" and s["width"] == 1 for s in f["shapes"])
    assert len({s["color"] for s in f["shapes"]}) == 1


def test_season_annotations_rendered(date_page: Page) -> None:
    f = _fig(date_page)
    anns = [a for a in f["anns"] if a["name"]]
    assert [a["name"] for a in anns] == ["season-2019", "season-2021", "season-2025", "season-2026"]
    assert all(a["yref"] == "paper" and a["y"] == 0 and a["yanchor"] == "top" for a in anns)
    assert all(a["capture"] is False for a in anns)
    assert all(a["text"].startswith("<b>") and a["text"].endswith("</b>") for a in anns)
    assert anns[0]["text"] == "<b>2019</b>"


@pytest.mark.parametrize("dots", ["fade", "hide"])
def test_season_filter_limits_x_axis_fade_and_hide(date_page: Page, dots: str) -> None:
    base = _fig(date_page)
    date_page.evaluate(_STATE_JS, {"seasons": [2025, 2026], "dots": dots})
    f = _fig(date_page)
    assert f["layoutRange"] == [153, 278]
    assert f["minallowed"] == 153 and f["maxallowed"] == 278
    assert f["xs"] and min(f["xs"]) >= 153
    assert [a["name"] for a in f["anns"] if a["name"]] == ["season-2025", "season-2026"]
    assert [s["x"] for s in f["shapes"]] == [243.5]
    assert f["y"] == base["y"]


def test_single_season_range(date_page: Page) -> None:
    date_page.evaluate(_STATE_JS, {"seasons": [2025, 2025]})
    f = _fig(date_page)
    assert f["layoutRange"] == [153, 240]
    assert f["range"] == [153, 240]


def test_spread_range_ignores_season_filter(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    base = _fig(guarded_page)
    guarded_page.evaluate(_STATE_JS, {"seasons": [2025, 2026]})
    f = _fig(guarded_page)
    assert f["layoutRange"] == base["layoutRange"]
    assert len(f["xs"]) == len(base["xs"])
    assert f["minallowed"] is None


def test_uirevision_keys(date_page: Page) -> None:
    assert _fig(date_page)["uirevision"] == "date:all"
    date_page.evaluate(_STATE_JS, {"seasons": [2025, 2026]})
    assert _fig(date_page)["uirevision"] == "date:2025-2026"
    date_page.evaluate(_STATE_JS, {"axis": "spread", "seasons": None})
    assert _fig(date_page)["uirevision"] == "spread"


def test_trace_count_constant_across_axes(date_page: Page) -> None:
    for patch in ({}, {"school": [date_page.evaluate("window.__testHooks.data.teamSlugs[0]")]}):
        counts = []
        for axis in ("spread", "excitement", "date"):
            date_page.evaluate(_STATE_JS, {"axis": axis, **patch})
            counts.append(_fig(date_page)["traces"])
        assert len(set(counts)) == 1, counts
        date_page.evaluate(_STATE_JS, {"school": []})


def test_block_geometry_ignores_non_season_filters(date_page: Page) -> None:
    base = _fig(date_page)
    slug = date_page.evaluate("window.__testHooks.data.teamSlugs[0]")
    date_page.evaluate(_STATE_JS, {"school": [slug]})
    f = _fig(date_page)
    assert f["layoutRange"] == base["layoutRange"]
    for k, x in f["byIdx"].items():
        assert base["byIdx"].get(k, x) == x
    date_page.evaluate(_STATE_JS, {"school": [], "slots": ["primetime"]})
    f = _fig(date_page)
    assert f["layoutRange"] == base["layoutRange"]
    assert [s["x"] for s in f["shapes"]] == [76.5, 149.5, 243.5]


def test_tooltip_ring_and_modal_on_date(date_page: Page) -> None:
    expected = date_page.evaluate(
        "async () => { const F = await import('./modules/format.js');"
        " return F.axisValueText(window.__testHooks.data, 0, 'date'); }"
    )
    assert expected.startswith("Spread:") and "Excitement:" in expected
    point = _hover_dot(date_page, 0)
    tip = date_page.locator("#chart-tooltip")
    assert expected in tip.inner_text()
    assert tip.bounding_box()["width"] <= 320  # type: ignore[index]
    ring = date_page.locator(_RING_VISIBLE).first
    if ring.count():
        box = ring.bounding_box()
        assert box is not None
        assert abs(box["x"] + box["width"] / 2 - point["x"]) <= 1.5
    date_page.evaluate("window.__testHooks.openPanel(0)")
    expect(date_page.locator("#panel-body")).to_contain_text(expected)


# -- fitDateAxis hook --------------------------------------------------------

_WANT_JS = """
async () => {
  const A = await import('./modules/date-axis.js');
  const gd = document.getElementById('chart');
  const m = gd.boothDateAxis;
  const xa = gd._fullLayout.xaxis;
  const want = A.dateAxisLabels(m.blocks, xa.range, xa._length, { mobile: m.mobile });
  const r4 = (a) => a.map((v) => Math.round(v * 1e4) / 1e4);
  return {
    tickOk: JSON.stringify(r4(gd.layout.xaxis.tickvals)) === JSON.stringify(r4(want.tickvals))
      && JSON.stringify(gd.layout.xaxis.ticktext) === JSON.stringify(want.ticktext),
    annOk: want.seasons.every((s) => {
      const a = gd.layout.annotations.find((q) => q.name === 'season-' + s.season);
      return a && Math.abs(a.x - s.x) < 0.02 && Math.abs(a.xshift - s.xshift) <= 0.5
        && a.text === '<b>' + s.label + '</b>' && (a.visible ?? true) === s.visible;
    }),
    ticktext: gd.layout.xaxis.ticktext,
    visibleSeasons: want.seasons.filter((s) => s.visible).length,
  };
}
"""

_COUNT_JS = """
() => {
  const gd = document.getElementById('chart');
  window.__relayouts = 0;
  gd.on('plotly_relayout', () => { window.__relayouts += 1; });
}
"""


def _settle(page: Page) -> None:
    page.evaluate(_WAIT_TWO_FRAMES)
    page.wait_for_timeout(400)


def test_fit_hook_matches_pure_rule(date_page: Page) -> None:
    _settle(date_page)
    out = date_page.evaluate(_WANT_JS)
    assert out["tickOk"] and out["annOk"]
    date_page.evaluate(_STATE_JS, {"seasons": [2025, 2026]})
    _settle(date_page)
    out = date_page.evaluate(_WANT_JS)
    assert out["tickOk"] and out["annOk"]


def test_fit_hook_settles(date_page: Page) -> None:
    _settle(date_page)
    date_page.evaluate(_COUNT_JS)
    date_page.evaluate(_RELAYOUT_JS, {"xaxis.range": [153, 200]})
    _settle(date_page)
    first = date_page.evaluate("window.__relayouts")
    date_page.evaluate(_WAIT_TWO_FRAMES)
    date_page.evaluate(_WAIT_TWO_FRAMES)
    date_page.wait_for_timeout(300)
    assert date_page.evaluate("window.__relayouts") == first
    assert first <= 4


def test_label_tiers_desktop_and_phone(
    date_page: Page, mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    date_page.evaluate(_STATE_JS, {"seasons": [2025, 2025]})
    _settle(date_page)
    out = date_page.evaluate(_WANT_JS)
    texts = [t for t in out["ticktext"] if t]
    assert texts and all(re.fullmatch(r"[A-Z][a-z]{2} \d{1,2}", t) for t in texts), texts

    mobile_page.set_viewport_size({"width": 360, "height": 800})
    open_app(mobile_page, "?axis=date")
    mobile_page.evaluate(_STATE_JS, {"seasons": [2025, 2025]})
    _settle(mobile_page)
    texts = [t for t in mobile_page.evaluate(_WANT_JS)["ticktext"] if t]
    assert texts and all(re.fullmatch(r"[A-Z][a-z]{2}", t) for t in texts), texts
    mobile_page.evaluate(_STATE_JS, {"seasons": None})
    _settle(mobile_page)
    texts = mobile_page.evaluate(_WANT_JS)["ticktext"]
    assert all(t == "" for t in texts)


def test_phone_season_labels_fit_without_overlap(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    mobile_page.set_viewport_size({"width": 360, "height": 800})
    open_app(mobile_page, "?axis=date")
    _settle(mobile_page)
    out = mobile_page.evaluate(_WANT_JS)
    assert out["visibleSeasons"] == 4
    boxes = mobile_page.evaluate(
        """() => {
          const svg = document.querySelector('#chart svg.main-svg').getBoundingClientRect();
          return [...document.querySelectorAll('#chart .annotation')]
            .filter((el) => /^\\d{2,4}$/.test(el.textContent.trim()))
            .map((el) => { const r = el.getBoundingClientRect();
              const inside = r.left >= svg.left - 0.5 && r.right <= svg.right + 0.5;
              return { l: r.left, r: r.right, inside }; })
            .sort((a, b) => a.l - b.l);
        }"""
    )
    assert len(boxes) == 4
    assert all(b["inside"] for b in boxes)
    for a, b in pairwise(boxes):
        assert a["r"] <= b["l"] + 0.5


def test_labels_recompute_on_zoom_and_resize(date_page: Page) -> None:
    _settle(date_page)
    before = date_page.evaluate(_WANT_JS)["ticktext"]
    date_page.evaluate(_RELAYOUT_JS, {"xaxis.range": [153, 200]})
    _settle(date_page)
    out = date_page.evaluate(_WANT_JS)
    assert out["tickOk"] and out["annOk"]
    assert out["ticktext"] != before
    date_page.set_viewport_size({"width": 700, "height": 900})
    _settle(date_page)
    out = date_page.evaluate(_WANT_JS)
    assert out["tickOk"] and out["annOk"]


def test_autoscale_and_pan_clamp_to_filtered_range(date_page: Page) -> None:
    date_page.evaluate(_STATE_JS, {"seasons": [2025, 2026]})
    _settle(date_page)
    date_page.evaluate(_RELAYOUT_JS, {"xaxis.range": [100, 300]})
    _settle(date_page)
    lo, hi = date_page.evaluate("document.getElementById('chart')._fullLayout.xaxis.range")
    assert lo >= 153 - 1e-6 and hi <= 278 + 1e-6
    date_page.evaluate(_RELAYOUT_JS, {"xaxis.range": [160, 200]})
    _settle(date_page)
    date_page.evaluate(_RELAYOUT_JS, {"xaxis.autorange": True})
    _settle(date_page)
    res = date_page.evaluate(
        "() => { const gd = document.getElementById('chart');"
        " return { r: gd._fullLayout.xaxis.range, auto: gd._fullLayout.xaxis.autorange }; }"
    )
    assert res["auto"] is False
    assert res["r"] == [153, 278]


def test_season_change_resets_zoom_other_filters_keep_it(date_page: Page) -> None:
    _settle(date_page)
    date_page.locator("#chart").scroll_into_view_if_needed()
    box = date_page.evaluate(
        "() => { const gd = document.getElementById('chart'); const r = gd.getBoundingClientRect();"
        " const s = gd._fullLayout._size;"
        " const x = r.left + s.l; const y = r.top + s.t + s.h * 0.5;"
        " return { x0: x + s.w * 0.3, x1: x + s.w * 0.6, y }; }"
    )
    date_page.mouse.move(box["x0"], box["y"])
    date_page.mouse.down()
    date_page.mouse.move(box["x1"], box["y"], steps=8)
    date_page.mouse.up()
    _settle(date_page)
    zoomed = date_page.evaluate("document.getElementById('chart')._fullLayout.xaxis.range")
    assert zoomed[1] - zoomed[0] < 278 * 0.5
    slug = date_page.evaluate("window.__testHooks.data.teamSlugs[0]")
    date_page.evaluate(_STATE_JS, {"school": [slug]})
    _settle(date_page)
    kept = date_page.evaluate("document.getElementById('chart')._fullLayout.xaxis.range")
    assert kept == pytest.approx(zoomed, abs=1e-6)
    date_page.evaluate(_STATE_JS, {"school": [], "seasons": [2025, 2026]})
    _settle(date_page)
    assert date_page.evaluate("document.getElementById('chart')._fullLayout.xaxis.range") == [
        153,
        278,
    ]
    date_page.evaluate(_STATE_JS, {"axis": "spread", "seasons": None})
    _settle(date_page)
    rng = date_page.evaluate("document.getElementById('chart').layout.xaxis.range")
    assert date_page.evaluate(
        "document.getElementById('chart')._fullLayout.xaxis.range"
    ) == pytest.approx(rng, abs=1e-6)


def test_hook_noop_off_date(guarded_page: Page, open_app: Callable[[Page, str], None]) -> None:
    open_app(guarded_page, "")
    _settle(guarded_page)
    guarded_page.evaluate(_COUNT_JS)
    guarded_page.evaluate(_WAIT_TWO_FRAMES)
    guarded_page.wait_for_timeout(300)
    assert guarded_page.evaluate("window.__relayouts") == 0
    assert guarded_page.evaluate("document.getElementById('chart').boothDateAxis") is None


def test_date_button_click_round_trip(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    date_btn = guarded_page.locator('#axis-toggle button[data-axis="date"]')
    date_btn.click()
    guarded_page.wait_for_function("() => location.search === '?axis=date'")
    expect(date_btn).to_have_attribute("aria-pressed", "true")
    guarded_page.reload()
    guarded_page.wait_for_function("() => window.__testHooks && window.__testHooks.data")
    expect(date_btn).to_have_attribute("aria-pressed", "true")
    title = guarded_page.evaluate(
        "() => { const l = document.getElementById('chart').layout;"
        " return l && l.xaxis && l.xaxis.title && l.xaxis.title.text; }"
    )
    assert not title
    guarded_page.locator('#axis-toggle button[data-axis="spread"]').click()
    guarded_page.wait_for_function("() => !location.search.includes('axis=')")
    open_app(guarded_page, "?axis=dates")
    expect(guarded_page.locator('#axis-toggle button[data-axis="spread"]')).to_have_attribute(
        "aria-pressed", "true"
    )
