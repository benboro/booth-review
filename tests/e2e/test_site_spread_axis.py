"""04.8 SITE-43: the Spread axis (winner-signed closing line, the default): data, copy, layout.

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
    spread: data.t.spread,
    negZero: data.t.spread.some((v) => Object.is(v, -0)),
    range: data.xRange.spread,
    rawHasSpread: 'spread' in raw.telecasts,
    hasPregame: 'pregame' in data.xRange,
    hasResult: 'result' in data.xRange,
    unchanged: JSON.stringify(raw.telecasts) === before,
  };
}
"""

_NO_SPREAD_JS = """
async () => {
  const D = await import('./modules/data.js');
  const raw = await (await fetch('site-data.json')).json();
  delete raw.telecasts.home_spread;
  try {
    D.prepareData(raw);
    return null;
  } catch (e) {
    return String(e.message);
  }
}
"""

_COPY_JS = """
async () => {
  const D = await import('./modules/data.js');
  const F = await import('./modules/format.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  const out = {};
  for (const i of [0, 1, 2, 3, 7, 8, 10, 11]) out[i] = F.spreadLabel(data, i);
  out.arity = F.spreadLabel.length;
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
  raw.telecasts.home_spread[9] = 0;
  raw.telecasts.home_spread[2] = 0;
  raw.telecasts.home_spread[10] = 0;
  const data = D.prepareData(raw);
  return {
    decided: F.spreadLabel(data, 9),
    noScore: F.spreadLabel(data, 2),
    tied: F.spreadLabel(data, 10),
    x: data.t.spread[9],
    negZero: Object.is(data.t.spread[9], -0),
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
  const dec = (q) => U.decodeState(q, data).axis;
  return {
    defaultAxis: base.axis,
    result: dec('?axis=result'),
    pregame: dec('?axis=pregame'),
    excitement: dec('?axis=excitement'),
    junk: dec('?axis=junk'),
    pct: dec('?axis=%'),
    empty: dec(''),
    encDefault: U.encodeState(base, data),
    encExcitement: U.encodeState({ ...base, axis: 'excitement' }, data),
  };
}
"""

_TOOLTIP_JS = """
async (args) => {
  const D = await import('./modules/data.js');
  const T = await import('./modules/tooltip.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  return args.map((i) => T.tooltipModel(data, i, { axis: 'spread' }).axisLine);
}
"""

# 12 rated games, then the 8 unrated games (merged indices 12..19; 12 and 19 have no spread)
EXPECTED_SPREAD = [
    -3.5, 7.0, None, None, -1.0, -14.0, 5.5, 3.0, -6.5, 0.5, None, -1.5,
    None, -3.5, -6.0, -2.5, -1.0, -4.5, 6.5, None,
]  # fmt: skip


def test_spread_x_is_the_winner_signed_closing_line(app_page: Page) -> None:
    out = app_page.evaluate(_DATA_JS)
    assert out["spread"] == EXPECTED_SPREAD
    assert out["negZero"] is False
    assert out["range"] == [-14, 7]
    assert out["rawHasSpread"] is False
    assert out["hasPregame"] is False
    assert out["hasResult"] is False
    assert out["unchanged"] is True


def test_missing_home_spread_fails_to_load(
    app_page: Page, guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    message = app_page.evaluate(_NO_SPREAD_JS)
    assert message is not None
    assert "home_spread" in message

    def strip(route) -> None:  # type: ignore[no-untyped-def]
        response = route.fetch()
        payload = response.json()
        del payload["telecasts"]["home_spread"]
        route.fulfill(response=response, json=payload)

    guarded_page.route("**/site-data.json*", strip)
    guarded_page.goto(guarded_page.url.split("?")[0])
    expect(guarded_page.locator("#load-error")).to_be_visible()
    guarded_page.wait_for_function("window.__testHooks && window.__testHooks.failed != null")


def test_spread_copy_names_the_winner(app_page: Page) -> None:
    out = app_page.evaluate(_COPY_JS)
    assert out["arity"] == 2
    assert out["0"] == f"Spread: Northfield {M}3.5"
    assert out["1"] == "Spread: Ironpeak +7.0"
    assert out["3"] == "Spread: not available"
    assert out["7"] == "Spread: Boulder Pass +3.0"
    assert out["8"] == f"Spread: Northfield {M}6.5"
    assert out["11"] == f"Spread: Stonebridge {M}1.5"
    assert out["exc0"] == "Excitement: 5.2"
    assert out["exc2"] == "Excitement (CFBD): not available"


def test_undecided_dots_name_the_favorite_and_the_reason(app_page: Page) -> None:
    out = app_page.evaluate(_COPY_JS)
    assert out["2"] == f"Spread: Boulder Pass {M}2.0 (no final score yet)"
    assert out["10"] == f"Spread: Boulder Pass {M}2.5 (game tied)"
    pick = app_page.evaluate(_PICKEM_JS)
    assert pick["noScore"] == "Spread: Pick'em (no final score yet)"
    assert pick["tied"] == "Spread: Pick'em (game tied)"


def test_pickem_reads_pickem_and_never_negative_zero(app_page: Page) -> None:
    out = app_page.evaluate(_PICKEM_JS)
    assert out["decided"] == "Spread: Pick'em"
    assert out["x"] == 0
    assert out["negZero"] is False


def test_axis_url_value_round_trips_and_falls_back(app_page: Page) -> None:
    out = app_page.evaluate(_URL_JS)
    assert out["defaultAxis"] == "spread"
    assert out["excitement"] == "excitement"
    for key in ("result", "pregame", "junk", "pct", "empty"):
        assert out[key] == "spread"
    assert out["encDefault"] == ""
    assert out["encExcitement"] == "?axis=excitement"


def test_tooltip_model_spread_copy_in_spread_mode(app_page: Page) -> None:
    lines = app_page.evaluate(_TOOLTIP_JS, [7, 2, 10, 3])
    assert lines == [
        "Spread: Boulder Pass +3.0",
        f"Spread: Boulder Pass {M}2.0 (no final score yet)",
        f"Spread: Boulder Pass {M}2.5 (game tied)",
        "Spread: not available",
    ]
    assert not any("-0" in line or "Pass -3" in line for line in lines)


@pytest.mark.parametrize(
    ("idx", "expected"),
    [
        (7, "Spread: Boulder Pass +3.0"),
        (2, f"Spread: Boulder Pass {M}2.0 (no final score yet)"),
        (10, f"Spread: Boulder Pass {M}2.5 (game tied)"),
        (3, "Spread: not available"),
    ],
)
def test_modal_shows_spread_copy(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    idx: int,
    expected: str,
) -> None:
    open_app(guarded_page, "")
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


def test_spread_axis_layout(guarded_page: Page, open_app: Callable[[Page, str], None]) -> None:
    open_app(guarded_page, "")
    layout = guarded_page.evaluate(_LAYOUT_JS)
    assert layout["xaxis"]["title"]["text"] == "Winner's closing spread (points)"
    assert layout["margin"]["t"] == 40
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
    revisions = []
    for q in ("", "?axis=result", "?axis=excitement"):
        open_app(guarded_page, q)
        revisions.append(
            guarded_page.evaluate("() => document.getElementById('chart').layout.uirevision")
        )
    assert revisions[0] == revisions[1]
    assert len(set(revisions)) == 2
    exc = guarded_page.evaluate(_LAYOUT_JS)
    # 1 existing shape + 2 band shapes (rect + top line) from plan 07
    assert len(exc["shapes"]) == 3
    assert [a["text"] for a in exc["annotations"]] == ["N/A"]
    assert exc["margin"]["t"] == 40


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_zero_line_is_solid_and_stronger_than_gridlines(
    guarded_page: Page, open_app: Callable[[Page, str], None], scheme: str
) -> None:
    """D-02: the zero line is solid, heavier, and a different color than the grid."""
    guarded_page.emulate_media(color_scheme=scheme)  # type: ignore[arg-type]
    open_app(guarded_page, "")
    layout = guarded_page.evaluate(_LAYOUT_JS)
    zero = next(s for s in layout["shapes"][1:] if s["x0"] == 0 and s["x1"] == 0)
    assert zero["line"]["dash"] == "solid"
    assert zero["line"]["width"] > 1
    assert zero["line"]["color"] != layout["xaxis"]["gridcolor"]


def test_spread_axis_title_is_one_line_on_phone(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(mobile_page, "")
    title = mobile_page.evaluate(_LAYOUT_JS)["xaxis"]["title"]["text"]
    assert "<br>" not in title
    box = mobile_page.evaluate(
        """() => {
          const t = document.querySelector('#chart .g-xtitle text');
          const r = t.getBoundingClientRect();
          return { l: r.left, r: r.right, lines: t.querySelectorAll('tspan').length };
        }"""
    )
    assert box["lines"] <= 1
    assert box["l"] >= 0
    assert box["r"] <= 390


def test_spread_axis_na_strip(guarded_page: Page, open_app: Callable[[Page, str], None]) -> None:
    open_app(guarded_page, "")
    got = guarded_page.evaluate(_XS_JS)
    by_idx, sentinel = got["byIdx"], got["sentinel"]
    for i in ("2", "3", "10"):
        assert by_idx[i][0] == sentinel
        assert by_idx[i][1] > 0
    assert by_idx["1"][0] == 7.0
    assert by_idx["8"][0] == -6.5
    # 3 rated n/a games (2, 3, 10) + 2 unrated games with no spread (12, 19)
    assert got["sentinelCount"] == 5
    open_app(guarded_page, "?school=northfield")
    faded = guarded_page.evaluate(_XS_JS)
    assert faded["sentinelCount"] == 5


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
    open_app(guarded_page, "")
    _assert_captions_inside(guarded_page)


@pytest.mark.parametrize("font_setting", ["default", "wide"], indirect=True)
@pytest.mark.parametrize("edge", ["right", "left"])
def test_captions_stay_inside_when_zero_hugs_an_edge(
    guarded_page: Page, open_app: Callable[[Page, str], None], edge: str
) -> None:
    """A range that puts zero right at a plot edge (a zoom, or a lopsided
    season) slides the caption on that side back inside the chart."""
    guarded_page.set_viewport_size({"width": 360, "height": 800})
    open_app(guarded_page, "")
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
        "spread",
        "excitement",
        "date",
    ]
    assert buttons.evaluate_all("els => els.map(e => e.getAttribute('aria-label'))") == [
        "Spread",
        "Excitement",
        "Date",
    ]
    assert buttons.evaluate_all("els => els.map(e => e.getAttribute('aria-pressed'))") == [
        "true",
        "false",
        "false",
    ]


def test_spread_axis_url_round_trip(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    guarded_page.locator("#axis-toggle button[data-axis=excitement]").click()
    expect(guarded_page).to_have_url(re.compile(r"[?&]axis=excitement"))
    guarded_page.reload()
    guarded_page.wait_for_function("window.__testHooks && window.__testHooks.ready === true")
    expect(guarded_page.locator("#axis-toggle button[data-axis=excitement]")).to_have_attribute(
        "aria-pressed", "true"
    )
    guarded_page.locator("#axis-toggle button[data-axis=spread]").click()
    expect(guarded_page).not_to_have_url(re.compile(r"axis="))
    open_app(guarded_page, "?axis=pregame")
    expect(guarded_page.locator("#axis-toggle button[data-axis=spread]")).to_have_attribute(
        "aria-pressed", "true"
    )


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
    y_info = guarded_page.evaluate(
        """() => {
          const rects = [...document.querySelectorAll('#y-toggle button')]
            .map((b) => b.getBoundingClientRect());
          const groups = [...document.querySelectorAll('.axis-group')].map((g) => ({
            wrap: g.scrollWidth > g.clientWidth,
            tops: [...g.children].map((c) => Math.round(c.getBoundingClientRect().top)),
            heights: [...g.querySelectorAll('button')]
              .map((b) => b.getBoundingClientRect().height),
          }));
          return {tops: rects.map((r) => Math.round(r.top)), groups};
        }"""
    )
    assert len(y_info["tops"]) == 4 and len(set(y_info["tops"])) == 1
    for g in y_info["groups"]:
        assert not g["wrap"]
        assert all(h >= 44 for h in g["heights"])
