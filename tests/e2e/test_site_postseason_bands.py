"""04.17 SITE-66: postseason bands and the "Bowls & CFP" label on the Date axis.

D-01..D-08. The first group exercises the pure, DOM-free geometry in
date-axis.js and the tint constant in palette.js with synthetic dates; the
second group renders the synthetic fixture and checks the Plotly shapes,
annotation, filter independence and label fit.
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


# --- pure geometry -----------------------------------------------------------

_BUILD_JS = """
async () => {
  const A = await import('./modules/date-axis.js');
  const season = [2030, 2030, 2030, 2031, 2031];
  const date = ['2030-09-07', '2030-11-20', '2030-11-29', '2031-09-06', '2031-12-20'];
  const kick = [null, null, null, null, null];
  const three = A.buildDateAxis(season, date, kick).axis.blocks.map((b) => b.postDay);
  const gt = ['regular', 'playoff', 'regular', 'regular', 'bowl'];
  const four = A.buildDateAxis(season, date, kick, gt).axis.blocks.map((b) => b.postDay);
  const regularOnly = A.buildDateAxis(
    season, date, kick, ['regular', 'regular', 'regular', 'regular', 'regular'],
  ).axis.blocks.map((b) => b.postDay);
  const odd = A.buildDateAxis(
    season, date, kick, ['final', 'Bowl', null, 'regular', 'bowls'],
  ).axis.blocks.map((b) => b.postDay);
  return {
    three, four, regularOnly, odd,
    day1120: A.epochDay('2030-11-20'), day1220: A.epochDay('2031-12-20'),
  };
}
"""


def test_postday_null_without_game_type(app_page: Page) -> None:
    out = app_page.evaluate(_BUILD_JS)
    assert out["three"] == [None, None]


def test_postday_is_earliest_bowl_or_playoff_day(app_page: Page) -> None:
    out = app_page.evaluate(_BUILD_JS)
    # The playoff row (11-20) is earlier than the later regular row (11-29).
    assert out["four"] == [out["day1120"], out["day1220"]]


def test_postday_null_for_regular_only_and_unknown_types(app_page: Page) -> None:
    out = app_page.evaluate(_BUILD_JS)
    assert out["regularOnly"] == [None, None]
    assert out["odd"] == [None, None]


_BANDS_JS = """
async () => {
  const A = await import('./modules/date-axis.js');
  const season = [2030, 2030, 2031, 2031, 2032];
  const date = ['2030-09-07', '2030-12-20', '2031-09-06', '2031-12-20', '2032-09-05'];
  const kick = ['2030-09-07T12:00:00-04:00', null, null, null, null];
  const gt = ['regular', 'bowl', 'regular', 'playoff', 'regular'];
  const { axis } = A.buildDateAxis(season, date, kick, gt);
  const bands = A.postseasonBands(axis.blocks, 999);
  const b = axis.blocks;
  return {
    bands,
    blocks: b.map((x) => [x.season, x.start, x.end, x.minDay, x.postDay]),
    pad: A.DATE_PAD,
    none: A.postseasonBands(axis.blocks.map((x) => ({ ...x, postDay: null })), 999),
  };
}
"""


def test_band_edges_follow_d02_d03(app_page: Page) -> None:
    out = app_page.evaluate(_BANDS_JS)
    blocks = out["blocks"]
    bands = out["bands"]
    # 2032 has no postseason game, so only 2030 and 2031 get a band.
    assert [b["season"] for b in bands] == [2030, 2031]
    for band, (_s, start, _end, min_day, post_day) in zip(bands, blocks, strict=False):
        assert band["x0"] == start + out["pad"] + (post_day - min_day)
        assert band["x0"] == int(band["x0"])
    # A non-last block ends at its gap divider.
    assert bands[0]["x1"] == (blocks[0][2] + blocks[1][1]) / 2
    assert bands[1]["x1"] == (blocks[1][2] + blocks[2][1]) / 2
    assert out["none"] == []


def test_last_block_band_ends_at_right_edge(app_page: Page) -> None:
    out = app_page.evaluate(
        """
        async () => {
          const A = await import('./modules/date-axis.js');
          const { axis } = A.buildDateAxis(
            [2030, 2030], ['2030-09-07', '2030-12-20'], [null, null], ['regular', 'bowl']);
          return A.postseasonBands(axis.blocks, 123.5);
        }
        """
    )
    assert len(out) == 1
    assert out[0]["x1"] == 123.5


_LABEL_JS = """
async () => {
  const A = await import('./modules/date-axis.js');
  const bands = [{ season: 2020, x0: 10, x1: 20 }, { season: 2021, x0: 50, x1: 52 }];
  return {
    text: A.POSTSEASON_LABEL,
    wide: A.postseasonLabel(bands, [0, 100], 1000, { fontSize: 12 }),
    narrow: A.postseasonLabel(bands, [0, 100], 100, { fontSize: 12 }),
    clippedFits: A.postseasonLabel(bands, [0, 15], 2000, { fontSize: 12 }),
    clippedTight: A.postseasonLabel(bands, [0, 15], 40, { fontSize: 12 }),
    phone: A.postseasonLabel(bands, [0, 100], 1000, { fontSize: 10 }),
    phoneNarrow: A.postseasonLabel(bands, [0, 100], 150, { fontSize: 10 }),
    tall: A.postseasonLabel(bands, [0, 100], 1000, { fontSize: 12, heightPx: 90 }),
    short: A.postseasonLabel(bands, [0, 100], 1000, { fontSize: 12, heightPx: 89 }),
    measuredTall: A.postseasonLabel(
      bands, [0, 100], 3000, { fontSize: 12, measure: () => 40, heightPx: 51 }),
    measuredShort: A.postseasonLabel(
      bands, [0, 100], 3000, { fontSize: 12, measure: () => 40, heightPx: 50 }),
    measured: A.postseasonLabel(bands, [0, 100], 3000, { fontSize: 12, measure: () => 40 }),
    outside: A.postseasonLabel(bands, [60, 100], 3000, { fontSize: 12 }),
    empty: A.postseasonLabel([], [0, 100], 1000, { fontSize: 12 }),
  };
}
"""


def test_label_picks_rightmost_band_that_fits(app_page: Page) -> None:
    out = app_page.evaluate(_LABEL_JS)
    assert out["text"] == "Bowls & CFP"
    # the 2021 band is 20px wide, under the 22.5px the rotated label needs; 2020 is 100px
    assert out["wide"] == {"season": 2020, "x": 20}
    assert out["narrow"] is None
    assert out["empty"] is None
    # phone: thickness 10 + 2.5 + 8 = 20.5, so the 20px 2021 band is still too narrow
    assert out["phone"] == {"season": 2020, "x": 20}
    assert out["phoneNarrow"] is None


def test_label_needs_main_plot_height_for_its_length(app_page: Page) -> None:
    out = app_page.evaluate(_LABEL_JS)
    # default estimate: 0.6 * 12 * 11 = 79.2 text + 2.5 pad + 8 insets = 89.7
    assert out["tall"] == {"season": 2020, "x": 20}
    assert out["short"] is None
    assert out["measuredTall"] == {"season": 2021, "x": 52}
    assert out["measuredShort"] is None


def test_label_clips_to_visible_range(app_page: Page) -> None:
    out = app_page.evaluate(_LABEL_JS)
    assert out["clippedFits"] == {"season": 2020, "x": 15}
    assert out["clippedTight"] is None
    assert out["outside"] is None


def test_label_uses_measure_hook(app_page: Page) -> None:
    out = app_page.evaluate(_LABEL_JS)
    assert out["measured"] == {"season": 2021, "x": 52}


# --- palette contrast --------------------------------------------------------

_PALETTE_JS = """
async () => {
  const P = await import('./modules/palette.js');
  return {
    band: P.POSTSEASON_BAND,
    labelColor: P.POSTSEASON_LABEL,
    fam: P.FAMILY_COLORS,
    surface: P.SURFACE,
    pageBg: P.PAGE_BG,
  };
}
"""


def _parse_rgba(css: str) -> tuple[int, int, int, float]:
    inner = css[css.index("(") + 1 : css.index(")")]
    r, g, b, a = (p.strip() for p in inner.split(","))
    return int(r), int(g), int(b), float(a)


def _blend(css: str, backdrop_hex: str) -> str:
    r, g, b, a = _parse_rgba(css)
    base = [int(backdrop_hex[i : i + 2], 16) for i in (1, 3, 5)]
    out = [round(a * c + (1 - a) * bg) for c, bg in zip((r, g, b), base, strict=True)]
    return "#{:02X}{:02X}{:02X}".format(*out)


def test_band_alpha_is_faint(app_page: Page) -> None:
    pal = app_page.evaluate(_PALETTE_JS)
    assert _parse_rgba(pal["band"]["light"])[3] <= 0.10
    assert _parse_rgba(pal["band"]["dark"])[3] <= 0.14
    assert pal["band"]["light"] == "rgba(166, 120, 40, 0.07)"
    assert pal["band"]["dark"] == "rgba(212, 160, 60, 0.12)"


def _contrast(app_page: Page, a: str, b: str) -> float:
    return app_page.evaluate(
        "async ([a, b]) => (await import('./modules/palette.js')).contrastRatio(a, b)", [a, b]
    )


@pytest.mark.parametrize(
    ("theme", "surface", "floor"),
    [
        ("light", "plot", 3.0),
        ("light", "surface", 2.7),
        ("dark", "plot", 4.5),
        ("dark", "surface", 4.5),
    ],
)
def test_dots_keep_contrast_on_blended_band(
    app_page: Page, theme: str, surface: str, floor: float
) -> None:
    pal = app_page.evaluate(_PALETTE_JS)
    backdrop = pal["pageBg" if surface == "plot" else "surface"][theme]
    blended = _blend(pal["band"][theme], backdrop)
    for family in ("cbs", "other"):
        ratio = _contrast(app_page, pal["fam"][theme][family], blended)
        # The locked 0.07 tint puts Other at 2.998 (RESEARCH rounds to 3.00); allow 0.01.
        assert ratio >= floor - 0.01, (theme, surface, family, ratio)


@pytest.mark.parametrize(("theme", "floor"), [("light", 4.5), ("dark", 4.5)])
def test_label_text_has_contrast_on_blended_band(app_page: Page, theme: str, floor: float) -> None:
    pal = app_page.evaluate(_PALETTE_JS)
    assert pal["labelColor"] == {"light": "#6E4A10", "dark": "#E8BE6E"}
    blended = _blend(pal["band"][theme], pal["pageBg"][theme])
    assert _contrast(app_page, pal["labelColor"][theme], blended) >= floor
    # a darker tint on light, a lighter one on dark, relative to the band's own hue
    band = _parse_rgba(pal["band"][theme])
    label = int(pal["labelColor"][theme][1:], 16)
    brightness = sum((label >> s) & 255 for s in (0, 8, 16))
    assert (brightness < sum(band[:3])) if theme == "light" else (brightness > sum(band[:3]))


# --- rendered bands ----------------------------------------------------------

_SHAPES_JS = """
() => {
  const gd = document.getElementById('chart');
  const l = gd.layout;
  const shapes = l.shapes ?? [];
  const surface = shapes.findIndex((s) => s.type === 'rect' && s.xref === 'paper');
  return {
    surface,
    bands: shapes.map((s, i) => ({ s, i }))
      .filter((o) => String(o.s.name ?? '').startsWith('postseason-'))
      .map((o) => ({ ...o.s, index: o.i })),
    traces: gd.data.length,
    range: gd._fullLayout.xaxis.range.slice(),
    layoutRange: l.xaxis.range.slice(),
  };
}
"""

_EXPECT_JS = """
async () => {
  const A = await import('./modules/date-axis.js');
  const D = await import('./modules/data.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  const gd = document.getElementById('chart');
  const seasons = window.__testHooks.getState?.().seasons ?? null;
  const blocks = A.shownBlocks(data.dateAxis, seasons);
  return A.postseasonBands(blocks, gd.layout.xaxis.range[1]);
}
"""

_ANN_JS = """
() => {
  const gd = document.getElementById('chart');
  const xa = gd._fullLayout.xaxis;
  const anns = gd.layout.annotations;
  const a = anns.find((q) => q.name === 'postseason-label');
  return {
    count: anns.filter((q) => q.name === 'postseason-label').length,
    ann: a ? { text: a.text, x: a.x, visible: a.visible, capture: a.captureevents,
      color: a.font.color, size: a.font.size, y: a.y, yref: a.yref, yanchor: a.yanchor,
      yshift: a.yshift, xanchor: a.xanchor, xshift: a.xshift, textangle: a.textangle } : null,
    range: xa.range.slice(), length: xa._length, height: gd._fullLayout.yaxis._length,
    domain: gd.layout.yaxis.domain.slice(),
    bands: gd.boothDateAxis.bands,
    mobile: gd.boothDateAxis.mobile,
  };
}
"""

_FIT_JS = """
async ([a, b, c, d]) => {
  const A = await import('./modules/date-axis.js');
  return A.postseasonLabel(a, b, c, d);
}
"""

_RELAYOUT_JS = "(r) => window.Plotly.relayout(document.getElementById('chart'), r)"
_TWO_FRAMES = "() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))"
_COUNT_JS = """
() => {
  window.__relayouts = 0;
  document.getElementById('chart').on('plotly_relayout', () => { window.__relayouts += 1; });
}
"""


def _settle(page: Page) -> None:
    page.evaluate(_TWO_FRAMES)
    page.wait_for_timeout(400)


@pytest.fixture
def date_page(guarded_page: Page, open_app: Callable[[Page, str], None]) -> Page:
    guarded_page.set_viewport_size({"width": 1280, "height": 900})
    open_app(guarded_page, "?axis=date")
    _settle(guarded_page)
    return guarded_page


def _open(page: Page, open_app: Callable[[Page, str], None], query: str) -> None:
    page.set_viewport_size({"width": 1280, "height": 900})
    open_app(page, query)
    _settle(page)


def test_two_bands_after_surface_with_d04_d05_shape(date_page: Page) -> None:
    got = date_page.evaluate(_SHAPES_JS)
    assert [b["name"] for b in got["bands"]] == ["postseason-2021", "postseason-2025"]
    assert got["surface"] >= 0
    for band in got["bands"]:
        assert band["type"] == "rect"
        assert band["xref"] == "x"
        assert band["yref"] == "paper"
        assert band["y0"] == 0
        assert band["y1"] == 1
        assert band["layer"] == "below"
        assert band["line"]["width"] == 0
        assert band["fillcolor"] == "rgba(166, 120, 40, 0.07)"
        assert band["index"] > got["surface"] + 1  # after the SURFACE rect and its edge line


def test_band_edges_match_pure_geometry(date_page: Page) -> None:
    got = date_page.evaluate(_SHAPES_JS)
    want = date_page.evaluate(_EXPECT_JS)
    assert [(b["season"], b["x0"], b["x1"]) for b in want] == [
        (int(b["name"].split("-")[1]), b["x0"], b["x1"]) for b in got["bands"]
    ]


def test_last_season_band_ends_at_home_range_when_it_is_last_shown(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    _open(guarded_page, open_app, "?axis=date&seasons=2021-2025")
    got = guarded_page.evaluate(_SHAPES_JS)
    assert [b["name"] for b in got["bands"]] == ["postseason-2021", "postseason-2025"]
    assert got["bands"][-1]["x1"] == pytest.approx(got["layoutRange"][1], abs=1e-6)


def test_no_band_for_a_season_without_postseason_games(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    _open(guarded_page, open_app, "?axis=date&seasons=2026-2026")
    assert guarded_page.evaluate(_SHAPES_JS)["bands"] == []
    _open(guarded_page, open_app, "?axis=date&seasons=2019-2019")
    assert guarded_page.evaluate(_SHAPES_JS)["bands"] == []


@pytest.mark.parametrize(
    "extra",
    [
        "&postseason=only",
        "&postseason=exclude",
        "&dots=hide",
        "&school=northfield",
        "&networks=net-b",
    ],
)
def test_bands_ignore_every_filter_but_the_season_range(
    guarded_page: Page, open_app: Callable[[Page, str], None], date_page: Page, extra: str
) -> None:
    base = [(b["name"], b["x0"], b["x1"]) for b in date_page.evaluate(_SHAPES_JS)["bands"]]
    assert len(base) == 2
    _open(guarded_page, open_app, "?axis=date" + extra)
    again = [(b["name"], b["x0"], b["x1"]) for b in guarded_page.evaluate(_SHAPES_JS)["bands"]]
    assert again == base


def test_dark_theme_uses_dark_tint(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    guarded_page.emulate_media(color_scheme="dark")
    _open(guarded_page, open_app, "?axis=date")
    bands = guarded_page.evaluate(_SHAPES_JS)["bands"]
    assert bands
    assert all(b["fillcolor"] == "rgba(212, 160, 60, 0.12)" for b in bands)


def test_dark_theme_label_uses_light_tint(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    guarded_page.emulate_media(color_scheme="dark")
    _open(guarded_page, open_app, "?axis=date")
    assert guarded_page.evaluate(_ANN_JS)["ann"]["color"] == "#E8BE6E"


def test_trace_count_matches_other_axes(date_page: Page) -> None:
    n = date_page.evaluate(_SHAPES_JS)["traces"]
    date_page.evaluate("() => window.__testHooks.setState({ axis: 'spread' })")
    _settle(date_page)
    assert date_page.evaluate(_SHAPES_JS)["traces"] == n


# --- the label ---------------------------------------------------------------


def _label_matches_pure_rule(page: Page) -> dict:  # type: ignore[type-arg]
    got = page.evaluate(_ANN_JS)
    fit = page.evaluate(
        _FIT_JS,
        [
            got["bands"],
            got["range"],
            got["length"],
            {"fontSize": 10 if got["mobile"] else 12, "heightPx": got["height"]},
        ],
    )
    ann = got["ann"]
    assert ann is not None
    assert ann["visible"] is (fit is not None)
    if fit is not None:
        assert ann["x"] == pytest.approx(fit["x"], abs=0.01)
    return got  # type: ignore[no-any-return]


def test_label_annotation_is_always_present_with_fixed_style(date_page: Page) -> None:
    got = date_page.evaluate(_ANN_JS)
    ann = got["ann"]
    assert got["count"] == 1
    assert ann["text"] == "Bowls & CFP"
    assert ann["capture"] is False
    assert ann["color"] == "#6E4A10"
    assert ann["size"] == 12
    # rotated bottom-to-top, bottom right of the band, just above the gap row / bottom band
    assert ann["textangle"] == -90
    assert (ann["xanchor"], ann["xshift"]) == ("right", -4)
    assert (ann["yref"], ann["yanchor"], ann["yshift"]) == ("paper", "bottom", 4)
    assert ann["y"] == pytest.approx(got["domain"][0], abs=1e-6)
    _label_matches_pure_rule(date_page)


def test_label_follows_zoom_and_hides_when_no_band_fits(date_page: Page) -> None:
    bands = date_page.evaluate(_SHAPES_JS)["bands"]
    b21, b25 = bands[0], bands[1]
    # Zoom around only the 2021 band: the label moves to it.
    date_page.evaluate(_RELAYOUT_JS, {"xaxis.range": [b21["x0"] - 3, b21["x1"]]})
    _settle(date_page)
    got = _label_matches_pure_rule(date_page)
    assert got["ann"]["visible"] is True
    assert b21["x0"] <= got["ann"]["x"] <= b21["x1"]
    # Zoom around the 2025 band: it moves again.
    date_page.evaluate(_RELAYOUT_JS, {"xaxis.range": [b25["x0"] - 3, b25["x1"]]})
    _settle(date_page)
    got = _label_matches_pure_rule(date_page)
    assert got["ann"]["visible"] is True
    assert b25["x0"] <= got["ann"]["x"] <= b25["x1"]
    # A window holding no postseason day hides it.
    date_page.evaluate(_RELAYOUT_JS, {"xaxis.range": [b21["x0"] - 60, b21["x0"] - 40]})
    _settle(date_page)
    got = _label_matches_pure_rule(date_page)
    assert got["ann"]["visible"] is False


def test_label_shows_at_home_in_the_rightmost_band(date_page: Page) -> None:
    got = _label_matches_pure_rule(date_page)
    # The rotated label needs ~22px of band width, so it fits at home on a 1280 viewport.
    assert got["ann"]["visible"] is True
    assert got["ann"]["x"] == pytest.approx(got["bands"][-1]["x1"], abs=0.01)


_BBOX_JS = """
(band) => {
  const gd = document.getElementById('chart');
  const xa = gd._fullLayout.xaxis;
  const ya = gd._fullLayout.yaxis;
  const svg = document.querySelector('#chart svg.main-svg').getBoundingClientRect();
  const px = (x) => svg.left + xa._offset + xa.l2p(x);
  const label = [...document.querySelectorAll('#chart .annotation')]
    .find((el) => el.textContent.trim() === 'Bowls & CFP');
  if (!label) return { found: false };
  const r = label.querySelector('text').getBoundingClientRect();
  const seasons = [...document.querySelectorAll('#chart .annotation')]
    .filter((el) => /^'?\\d{2,4}$/.test(el.textContent.trim()))
    .map((el) => el.querySelector('text').getBoundingClientRect());
  const overlaps = seasons.some((s) =>
    r.left < s.right && r.right > s.left && r.top < s.bottom && r.bottom > s.top);
  return {
    found: true, left: r.left, right: r.right, top: r.top, bottom: r.bottom,
    width: r.width, height: r.height,
    bandLeft: px(band.x0), bandRight: px(band.x1),
    plotLeft: svg.left + xa._offset, plotRight: svg.left + xa._offset + xa._length,
    mainTop: svg.top + ya._offset, mainBottom: svg.top + ya._offset + ya._length,
    overlaps,
  };
}
"""


@pytest.mark.parametrize("font", ["default", "dejavu"])
@pytest.mark.parametrize("zoomed", [False, True])
def test_label_is_rotated_and_inside_band_and_main_plot(
    guarded_page: Page, open_app: Callable[[Page, str], None], font: str, zoomed: bool
) -> None:
    from test_site_date_axis import force_chart_font

    force_chart_font(guarded_page, font)
    _open(guarded_page, open_app, "?axis=date")
    b25 = guarded_page.evaluate(_SHAPES_JS)["bands"][-1]
    if zoomed:
        guarded_page.evaluate(_RELAYOUT_JS, {"xaxis.range": [b25["x0"] - 3, b25["x1"]]})
        _settle(guarded_page)
    out = guarded_page.evaluate(_BBOX_JS, b25)
    assert out["found"], out
    # rotated: taller than wide, reading bottom-to-top
    assert out["height"] > out["width"] > 0, out
    lo = max(out["bandLeft"], out["plotLeft"])
    hi = min(out["bandRight"], out["plotRight"])
    assert out["left"] >= lo - 0.5, out
    assert out["right"] <= hi + 0.5, out
    # at the bottom right: right edge a few px in from the band's right edge
    assert hi - out["right"] <= 12, out
    # inside the main plot, above the gap row / bottom band, not below its bottom edge
    assert out["bottom"] <= out["mainBottom"] + 0.5, out
    assert out["mainBottom"] - out["bottom"] <= 12, out
    assert out["top"] >= out["mainTop"] - 0.5, out
    assert out["overlaps"] is False


@pytest.mark.parametrize("query", ["?axis=date&seasons=2021-2025", "?axis=date&seasons=2025-2025"])
def test_label_is_drawn_when_the_band_ends_at_the_range_edge(
    guarded_page: Page, open_app: Callable[[Page, str], None], query: str
) -> None:
    # Plotly drops an annotation whose x is past the range end, so a label placed at a
    # rounded-up band edge is "visible" in the layout yet never drawn.
    _open(guarded_page, open_app, query)
    b25 = guarded_page.evaluate(_SHAPES_JS)["bands"][-1]
    out = guarded_page.evaluate(_BBOX_JS, b25)
    assert out["found"], out
    assert out["height"] > out["width"] > 0, out


def test_fit_hook_settles_with_label(date_page: Page) -> None:
    b25 = date_page.evaluate(_SHAPES_JS)["bands"][-1]
    date_page.evaluate(_COUNT_JS)
    date_page.evaluate(_RELAYOUT_JS, {"xaxis.range": [b25["x0"] - 3, b25["x1"]]})
    _settle(date_page)
    first = date_page.evaluate("window.__relayouts")
    date_page.evaluate(_TWO_FRAMES)
    date_page.wait_for_timeout(300)
    assert date_page.evaluate("window.__relayouts") == first
    assert first <= 4


# --- hover -------------------------------------------------------------------


def test_empty_band_space_shows_no_tooltip(date_page: Page) -> None:
    b25 = date_page.evaluate(_SHAPES_JS)["bands"][-1]
    date_page.evaluate(_RELAYOUT_JS, {"xaxis.range": [b25["x0"] - 3, b25["x1"]]})
    _settle(date_page)
    pt = date_page.evaluate(
        """
        (band) => {
          const gd = document.getElementById('chart');
          const svg = document.querySelector('#chart svg.main-svg').getBoundingClientRect();
          const xa = gd._fullLayout.xaxis;
          const ya = gd._fullLayout.yaxis;
          // the 28px gap row between the log axis and the bottom band holds no dots
          return {
            x: svg.left + xa._offset + xa.l2p((band.x0 + band.x1) / 2),
            y: svg.top + ya._offset + ya._length + 14,
          };
        }
        """,
        b25,
    )
    date_page.mouse.move(pt["x"] - 20, pt["y"])
    date_page.mouse.move(pt["x"], pt["y"], steps=4)
    date_page.wait_for_timeout(300)
    tip = date_page.locator("#chart-tooltip")
    assert tip.count() == 0 or tip.is_hidden()
