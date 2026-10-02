"""04.6 SITE-40: the Result vs spread axis, data and copy half.

Exercises the served pure modules (data.js, format.js, url-state.js,
tooltip.js) against the synthetic fixture, plus the modal's spread copy.
All spread copy uses the U+2212 minus glyph.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

M = "\u2212"


@pytest.fixture
def app_page(guarded_page: Page, open_app: Callable[[Page, str], None]) -> Page:
    """The app loaded once so `import('./modules/...')` resolves."""
    open_app(guarded_page, "")
    return guarded_page


_DATA_JS = """
async () => {
  const D = await import('./modules/data.js');
  const raw = await (await fetch('site-data.json')).json();
  const before = JSON.stringify(raw.telecasts);
  const data = D.prepareData(raw);
  return {
    result: data.t.result,
    negZero: data.t.result.some((v) => Object.is(v, -0)),
    range: data.xRange.result,
    rawHasResult: 'result' in raw.telecasts,
    unchanged: JSON.stringify(raw.telecasts) === before,
  };
}
"""

_NO_SPREAD_JS = """
async () => {
  const D = await import('./modules/data.js');
  const raw = await (await fetch('site-data.json')).json();
  delete raw.telecasts.home_spread;
  const data = D.prepareData(raw);
  return data.t.result;
}
"""

_COPY_JS = """
async () => {
  const D = await import('./modules/data.js');
  const F = await import('./modules/format.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  const out = {};
  for (const i of [0, 1, 2, 3, 7, 8, 11]) {
    out[i] = [F.spreadLabel(data, i, 'pregame'), F.spreadLabel(data, i, 'result')];
  }
  out.exc0 = F.axisValueText(data, 0, 'excitement');
  out.exc2 = F.axisValueText(data, 2, 'excitement');
  return out;
}
"""

_PICKEM_JS = """
async () => {
  const D = await import('./modules/data.js');
  const F = await import('./modules/format.js');
  const raw = await (await fetch('site-data.json')).json();
  raw.telecasts.home_spread[0] = 0;
  raw.telecasts.pregame[0] = 0;
  const data = D.prepareData(raw);
  return {
    pre: F.spreadLabel(data, 0, 'pregame'),
    res: F.spreadLabel(data, 0, 'result'),
    x: data.t.result[0],
    negZero: Object.is(data.t.result[0], -0),
  };
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
  return {
    result: U.decodeState('?axis=result', data).axis,
    excitement: U.decodeState('?axis=excitement', data).axis,
    junk: U.decodeState('?axis=junk', data).axis,
    pct: U.decodeState('?axis=%', data).axis,
    encResult: U.encodeState({ ...base, axis: 'result' }, data),
    encPregame: U.encodeState({ ...base, axis: 'pregame' }, data),
  };
}
"""

_TOOLTIP_JS = """
async (args) => {
  const D = await import('./modules/data.js');
  const T = await import('./modules/tooltip.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  return args.map((i) => T.tooltipModel(data, i, { axis: 'result' }).axisLine);
}
"""

EXPECTED_RESULT = [-3.5, 7.0, None, None, -1.0, -14.0, 5.5, 3.0, -6.5, 0.5, None, -1.5]


def test_result_x_is_the_winner_signed_closing_line(app_page: Page) -> None:
    out = app_page.evaluate(_DATA_JS)
    assert out["result"] == EXPECTED_RESULT
    assert out["negZero"] is False
    assert out["range"] == [-14, 7]
    assert out["rawHasResult"] is False
    assert out["unchanged"] is True


def test_missing_home_spread_column_gives_all_null_result(app_page: Page) -> None:
    assert app_page.evaluate(_NO_SPREAD_JS) == [None] * 12


def test_spread_copy_names_the_favorite_or_the_winner(app_page: Page) -> None:
    out = app_page.evaluate(_COPY_JS)
    assert out["0"] == [f"Spread: Northfield {M}3.5"] * 2
    assert out["1"] == [f"Spread: Foxhollow {M}7.0", "Spread: Ironpeak +7.0"]
    assert out["2"] == [f"Spread: Boulder Pass {M}2.0", "Spread: final score not recorded"]
    assert out["3"] == ["Spread: not available"] * 2
    assert out["7"] == [f"Spread: Maplecrest {M}3.0", "Spread: Boulder Pass +3.0"]
    assert out["8"] == [f"Spread: Northfield {M}6.5"] * 2
    assert out["11"] == [f"Spread: Stonebridge {M}1.5"] * 2
    assert out["exc0"] == "Excitement: 5.2"
    assert out["exc2"] == "Excitement (CFBD): not available"


def test_pickem_reads_pickem_and_never_negative_zero(app_page: Page) -> None:
    out = app_page.evaluate(_PICKEM_JS)
    assert out["pre"] == "Spread: Pick'em"
    assert out["res"] == "Spread: Pick'em"
    assert out["x"] == 0
    assert out["negZero"] is False


def test_axis_url_value_round_trips_and_falls_back(app_page: Page) -> None:
    out = app_page.evaluate(_URL_JS)
    assert out["result"] == "result"
    assert out["excitement"] == "excitement"
    assert out["junk"] == "pregame"
    assert out["pct"] == "pregame"
    assert out["encResult"] == "?axis=result"
    assert out["encPregame"] == ""


def test_tooltip_model_spread_copy_in_result_mode(app_page: Page) -> None:
    lines = app_page.evaluate(_TOOLTIP_JS, [7, 2, 3])
    assert lines == [
        "Spread: Boulder Pass +3.0",
        "Spread: final score not recorded",
        "Spread: not available",
    ]
    assert not any("-0" in line or "Pass -3" in line for line in lines)


@pytest.mark.parametrize(
    ("idx", "expected"),
    [
        (7, "Spread: Boulder Pass +3.0"),
        (2, "Spread: final score not recorded"),
        (3, "Spread: not available"),
    ],
)
def test_modal_shows_result_spread_copy(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    idx: int,
    expected: str,
) -> None:
    open_app(guarded_page, "?axis=result")
    guarded_page.evaluate(f"window.__testHooks.openPanel({idx})")
    body = guarded_page.locator("#panel-body")
    expect(body).to_contain_text(expected)
    text = body.inner_text()
    assert "Spread: Boulder Pass -3" not in text
    assert "-0" not in text.replace(M, "")
