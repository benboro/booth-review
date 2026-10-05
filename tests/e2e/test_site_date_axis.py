"""04.11 SITE-48: the Date x-axis foundation (geometry, label rule, copy, URL).

Exercises the served pure modules (date-axis.js, data.js, format.js,
url-state.js) against the synthetic fixture; nothing here needs a rendered chart.
"""

from __future__ import annotations

from collections.abc import Callable

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
