"""04.6 SITE-40: the Result vs spread axis, data and copy half.

Exercises the served pure modules (data.js, format.js, url-state.js,
tooltip.js) against the synthetic fixture, plus the modal's spread copy.
All spread copy uses the U+2212 minus glyph.
"""

from __future__ import annotations

import re
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


_LAYOUT_JS = "() => { const l = document.getElementById('chart').layout; return l; }"
_XS_JS = """
() => {
  const gd = document.getElementById('chart');
  const byIdx = {};
  let sentinelCount = 0;
  const sentinel = gd.layout.annotations[0].x;
  for (const t of gd.data) {
    t.x.forEach((x, k) => {
      if (x === sentinel) sentinelCount += 1;
      if (t.meta && String(t.meta).startsWith('family:')) byIdx[t.customdata[k]] = [x, t.y[k]];
    });
  }
  return { byIdx, sentinel, sentinelCount };
}
"""


def test_result_axis_layout(guarded_page: Page, open_app: Callable[[Page, str], None]) -> None:
    open_app(guarded_page, "?axis=result")
    layout = guarded_page.evaluate(_LAYOUT_JS)
    assert layout["xaxis"]["title"]["text"] == (
        "Winner's closing spread (points): upsets to the right"
    )
    vals, texts = layout["xaxis"]["tickvals"], layout["xaxis"]["ticktext"]
    assert 0 in vals
    assert texts[vals.index(0)] == "0"
    for v, t in zip(vals, texts, strict=True):
        if v < 0:
            assert t.startswith(M)
        elif v > 0:
            assert t.startswith("+")
    assert layout["shapes"][0]["x0"] != 0
    assert any(
        s["x0"] == 0 and s["x1"] == 0 and s["line"]["dash"] == "solid" for s in layout["shapes"][1:]
    )
    assert layout["annotations"][0]["text"] == "N/A"
    assert [a["text"] for a in layout["annotations"][1:]] == [
        "← favorite won",
        "underdog won →",
    ]
    revisions = set()
    for q in ("", "?axis=result", "?axis=excitement"):
        open_app(guarded_page, q)
        revisions.add(
            guarded_page.evaluate("() => document.getElementById('chart').layout.uirevision")
        )
    assert len(revisions) == 3
    open_app(guarded_page, "")
    pre = guarded_page.evaluate(_LAYOUT_JS)
    assert len(pre["shapes"]) == 1
    assert [a["text"] for a in pre["annotations"]] == ["N/A"]


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_zero_line_is_solid_and_stronger_than_gridlines(
    guarded_page: Page, open_app: Callable[[Page, str], None], scheme: str
) -> None:
    """D-02: the zero line is solid, heavier, and a different color than the grid."""
    guarded_page.emulate_media(color_scheme=scheme)  # type: ignore[arg-type]
    open_app(guarded_page, "?axis=result")
    layout = guarded_page.evaluate(_LAYOUT_JS)
    zero = next(s for s in layout["shapes"][1:] if s["x0"] == 0 and s["x1"] == 0)
    assert zero["line"]["dash"] == "solid"
    assert zero["line"]["width"] > 1
    assert zero["line"]["color"] != layout["xaxis"]["gridcolor"]


def test_result_axis_layout_on_phone(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(mobile_page, "?axis=result")
    title = mobile_page.evaluate(_LAYOUT_JS)["xaxis"]["title"]["text"]
    assert "<br>" in title


def test_result_axis_na_strip(guarded_page: Page, open_app: Callable[[Page, str], None]) -> None:
    open_app(guarded_page, "?axis=result")
    got = guarded_page.evaluate(_XS_JS)
    by_idx, sentinel = got["byIdx"], got["sentinel"]
    for i in ("2", "3", "10"):
        assert by_idx[i][0] == sentinel
        assert by_idx[i][1] > 0
    assert by_idx["1"][0] == 7.0
    assert by_idx["8"][0] == -6.5
    open_app(guarded_page, "?axis=result&school=northfield")
    faded = guarded_page.evaluate(_XS_JS)
    assert faded["sentinelCount"] == 3


_CAPTION_BOXES_JS = """() => {
  const svg = document.querySelector('#chart svg.main-svg').getBoundingClientRect();
  return [...document.querySelectorAll('#chart .annotation')]
    .filter((a) => /won/.test(a.textContent))
    .map((a) => { const r = a.getBoundingClientRect();
      return { l: r.left - svg.left, r: svg.right - r.right, t: r.top - svg.top }; });
}"""


def _assert_captions_inside(page: Page) -> None:
    """Both zero-line captions lie fully inside the chart SVG. Polled, since
    `fitZeroCaptions` nudges them in a relayout right after the draw."""
    page.wait_for_function(
        """() => {
          const svg = document.querySelector('#chart svg.main-svg');
          if (!svg) return false;
          const box = svg.getBoundingClientRect();
          const caps = [...document.querySelectorAll('#chart .annotation')]
            .filter((a) => /won/.test(a.textContent));
          return caps.length === 2 && caps.every((a) => {
            const r = a.getBoundingClientRect();
            return r.left >= box.left && r.right <= box.right && r.top >= box.top;
          });
        }""",
        timeout=5000,
    )
    boxes = page.evaluate(_CAPTION_BOXES_JS)
    assert len(boxes) == 2
    for b in boxes:
        assert b["l"] >= 0 and b["r"] >= 0 and b["t"] >= 0


@pytest.mark.parametrize("font_setting", ["default", "dejavu", "wide"], indirect=True)
@pytest.mark.parametrize("width", [1280, 360])
def test_captions_not_clipped(
    guarded_page: Page, open_app: Callable[[Page, str], None], width: int
) -> None:
    guarded_page.set_viewport_size({"width": width, "height": 800})
    open_app(guarded_page, "?axis=result")
    _assert_captions_inside(guarded_page)


@pytest.mark.parametrize("font_setting", ["default", "wide"], indirect=True)
@pytest.mark.parametrize("edge", ["right", "left"])
def test_captions_stay_inside_when_zero_hugs_an_edge(
    guarded_page: Page, open_app: Callable[[Page, str], None], edge: str
) -> None:
    """A range that puts zero right at a plot edge (a zoom, or a lopsided
    season) slides the caption on that side back inside the chart."""
    guarded_page.set_viewport_size({"width": 360, "height": 800})
    open_app(guarded_page, "?axis=result")
    rng = "[-30, 0.5]" if edge == "right" else "[-0.5, 30]"
    guarded_page.evaluate(
        f"() => window.Plotly.relayout(document.getElementById('chart'), {{'xaxis.range': {rng}}})"
    )
    _assert_captions_inside(guarded_page)


def test_toggle_has_three_buttons_in_order(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    buttons = guarded_page.locator("#axis-toggle button")
    assert buttons.evaluate_all("els => els.map(e => e.dataset.axis)") == [
        "pregame",
        "result",
        "excitement",
    ]
    assert buttons.evaluate_all("els => els.map(e => e.getAttribute('aria-label'))") == [
        "Pre-game (spread)",
        "Result vs spread",
        "Excitement (CFBD)",
    ]
    assert buttons.evaluate_all("els => els.map(e => e.getAttribute('aria-pressed'))") == [
        "true",
        "false",
        "false",
    ]


def test_result_axis_url_round_trip(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    guarded_page.locator("#axis-toggle button[data-axis=result]").click()
    expect(guarded_page).to_have_url(re.compile(r"[?&]axis=result"))
    guarded_page.reload()
    guarded_page.wait_for_function("window.__testHooks && window.__testHooks.ready === true")
    expect(guarded_page.locator("#axis-toggle button[data-axis=result]")).to_have_attribute(
        "aria-pressed", "true"
    )
    guarded_page.locator("#axis-toggle button[data-axis=pregame]").click()
    expect(guarded_page).not_to_have_url(re.compile(r"axis="))


@pytest.mark.parametrize("font_setting", ["default", "dejavu", "wide"], indirect=True)
@pytest.mark.parametrize("width", [360, 390])
def test_axis_toggle_fits_one_row_on_phones(
    guarded_page: Page, open_app: Callable[[Page, str], None], width: int
) -> None:
    guarded_page.set_viewport_size({"width": width, "height": 800})
    open_app(guarded_page, "")
    info = guarded_page.evaluate(
        """() => {
          const bs = [...document.querySelectorAll('#axis-toggle button')];
          const rects = bs.map((b) => b.getBoundingClientRect());
          return {
            tops: rects.map((r) => Math.round(r.top)),
            heights: rects.map((r) => r.height),
            overflow: bs.some((b) => b.scrollWidth > b.clientWidth),
            group: document.getElementById('axis-toggle').scrollWidth
              > document.getElementById('axis-toggle').clientWidth,
          };
        }"""
    )
    assert len(set(info["tops"])) == 1
    assert all(h >= 44 for h in info["heights"])
    assert not info["overflow"]
    assert not info["group"]
