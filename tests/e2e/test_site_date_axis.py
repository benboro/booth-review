"""04.11 SITE-48: the Date x-axis foundation (geometry, label rule, copy, URL).

Exercises the served pure modules (date-axis.js, data.js, format.js,
url-state.js) against the synthetic fixture; nothing here needs a rendered chart.
"""

from __future__ import annotations

from collections.abc import Callable
from itertools import pairwise

import pytest
from playwright.sync_api import Page

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
