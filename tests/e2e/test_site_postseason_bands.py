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
    clippedTight: A.postseasonLabel(bands, [0, 15], 1000, { fontSize: 12 }),
    measured: A.postseasonLabel(bands, [0, 100], 3000, { fontSize: 12, measure: () => 40 }),
    outside: A.postseasonLabel(bands, [60, 100], 3000, { fontSize: 12 }),
    empty: A.postseasonLabel([], [0, 100], 1000, { fontSize: 12 }),
  };
}
"""


def test_label_picks_rightmost_band_that_fits(app_page: Page) -> None:
    out = app_page.evaluate(_LABEL_JS)
    assert out["text"] == "Bowls & CFP"
    assert out["wide"] == {"season": 2020, "x": 15}
    assert out["narrow"] is None
    assert out["empty"] is None


def test_label_clips_to_visible_range(app_page: Page) -> None:
    out = app_page.evaluate(_LABEL_JS)
    assert out["clippedFits"] == {"season": 2020, "x": 12.5}
    assert out["clippedTight"] is None
    assert out["outside"] is None


def test_label_uses_measure_hook(app_page: Page) -> None:
    out = app_page.evaluate(_LABEL_JS)
    assert out["measured"] == {"season": 2021, "x": 51}


# --- palette contrast --------------------------------------------------------

_PALETTE_JS = """
async () => {
  const P = await import('./modules/palette.js');
  return {
    band: P.POSTSEASON_BAND,
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
        assert ratio >= floor, (theme, surface, family, ratio)
