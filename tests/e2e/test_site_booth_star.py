"""D-09/D-10 lead-booth stars (Phase 10, plan 10-08), proven on the synthetic booth overlay.

Overlay A games (merged index): 5 (fox, rated), 8 (disney, rated), 14 (disney, unrated).
B: 9, 13. Other: 4. Conference lead: 15.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

LEAD_RATED = {5, 8}
LEAD_UNRATED = {14}
NEVER_STAR = {9, 13, 4, 15}

_TRACES_JS = """
() => {
  const gd = document.getElementById('chart');
  return gd.data.map((t) => ({
    meta: String(t.meta),
    n: (t.x || []).length,
    customdata: Array.from(t.customdata || []),
    symbol: t.marker && (Array.isArray(t.marker.symbol)
      ? t.marker.symbol.slice() : t.marker.symbol),
    lineWidth: t.marker && t.marker.line && t.marker.line.width,
    color: t.marker && t.marker.color,
    size: t.marker && t.marker.size,
    yaxis: t.yaxis || 'y',
  }));
}
"""

_KEY_JS = """
() => {
  const el = document.getElementById('lead-key');
  const r = el.getBoundingClientRect();
  return {
    off: el.classList.contains('is-off'),
    hidden: el.hidden,
    visibility: getComputedStyle(el).visibility,
    box: [r.x, r.y, r.width, r.height].map((v) => Math.round(v * 10) / 10),
    name: el.getAttribute('aria-label'),
    text: el.textContent.trim(),
  };
}
"""


def _open(
    page: Page,
    serve_booths: Callable[[Page], None],
    open_app: Callable[[Page, str], None],
    query: str = "",
    *,
    booths: bool = True,
) -> list[dict]:
    if booths:
        serve_booths(page)
    open_app(page, query)
    page.wait_for_timeout(150)
    return page.evaluate(_TRACES_JS)


def _surface(page: Page) -> str:
    return page.evaluate(
        "async () => { const p = await import('./modules/palette.js');"
        " return p.SURFACE[document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light']; }"
    )


def _by_prefix(traces: list[dict], prefix: str) -> list[dict]:
    return [t for t in traces if t["meta"].startswith(prefix)]


def _points(traces: list[dict], prefix: str) -> set[int]:
    return {i for t in _by_prefix(traces, prefix) for i in t["customdata"]}


def _lead_points(traces: list[dict]) -> set[int]:
    return (
        _points(traces, "lead:")
        | _points(traces, "unrated-lead-filled:")
        | _points(traces, "unrated-lead:")
    )


def test_default_view_draws_a_games_as_stars(
    guarded_page: Page, serve_booths: Callable, open_app: Callable
) -> None:
    traces = _open(guarded_page, serve_booths, open_app)
    assert _points(traces, "lead:") == LEAD_RATED
    assert _points(traces, "unrated-lead:") == LEAD_UNRATED
    assert not _points(traces, "unrated-lead-filled:")
    assert _points(traces, "family:") & (LEAD_RATED | LEAD_UNRATED) == set()
    assert _points(traces, "unrated-active:") & LEAD_UNRATED == set()
    for t in traces:
        if t["meta"].startswith(("unrated-lead:", "unrated-lead-rim:")):
            # Phase 17: the no-rating star is empty, drawn as an open star with a line; its
            # filter outline (empty here) is a larger open star.
            assert t["symbol"] == "star-open", t["meta"]
            assert t["lineWidth"] > 0, t["meta"]
        elif t["meta"].startswith(("lead:", "unrated-lead")):
            assert t["symbol"] == "star", t["meta"]
            assert t["lineWidth"] == 0, t["meta"]
        else:
            assert "star-open" not in json.dumps(t["symbol"])


def test_hollow_star_is_an_empty_open_star(
    guarded_page: Page, serve_booths: Callable, open_app: Callable
) -> None:
    # Phase 17 (user sign-off): the no-rating star has an empty fill, so the band shows through.
    traces = _open(guarded_page, serve_booths, open_app)
    by_meta = {t["meta"]: t for t in traces}
    hollow = by_meta["unrated-lead:disney"]
    filled = by_meta["lead:disney"]
    assert hollow["n"] == 1
    assert hollow["symbol"] == "star-open"
    # The filled star's trace holds its casing point first, then the star itself.
    assert hollow["size"] == filled["size"][1]
    assert hollow["color"] == filled["color"][1]
    assert hollow["lineWidth"] > 0
    assert not any(t["meta"].startswith("unrated-lead-halo:") for t in traces)


def test_stars_on_every_channel_of_the_family(
    guarded_page: Page, serve_booths: Callable, open_app: Callable
) -> None:
    traces = _open(guarded_page, serve_booths, open_app)
    # 8 is net-a (disney) and 5 is net-b (fox): each sits in its own family's lead trace.
    by_meta = {t["meta"]: t for t in traces}
    assert by_meta["lead:disney"]["customdata"] == [8, 8]  # casing point, then the star
    assert by_meta["lead:fox"]["customdata"] == [5, 5]
    assert by_meta["lead:fox"]["color"][1] != by_meta["lead:disney"]["color"][1]


def test_excitement_mode_draws_unrated_a_game_filled(
    guarded_page: Page, serve_booths: Callable, open_app: Callable
) -> None:
    traces = _open(guarded_page, serve_booths, open_app, "?y=excitement")
    assert not _points(traces, "unrated-lead:")
    assert 14 in _points(traces, "unrated-lead-filled:") | _points(traces, "lead:")


def test_failed_filter_keeps_a_faded_circle(
    guarded_page: Page, serve_booths: Callable, open_app: Callable
) -> None:
    traces = _open(guarded_page, serve_booths, open_app, "?networks=net-b&dots=fade")
    assert 8 not in _lead_points(traces)
    assert 5 in _lead_points(traces)
    inert = next(t for t in _by_prefix(traces, "inert:") if t["meta"].endswith("disney"))
    assert inert["n"] >= 1
    assert inert["symbol"] in (None, "circle")  # unset means the default circle
    assert inert["size"] == 6
    assert not any(t["symbol"] == "star" and t["meta"].startswith("inert") for t in traces)


def test_hide_mode_drops_the_game_entirely(
    guarded_page: Page, serve_booths: Callable, open_app: Callable
) -> None:
    traces = _open(guarded_page, serve_booths, open_app, "?networks=net-b&dots=hide")
    assert 8 not in _lead_points(traces)
    assert 5 in _lead_points(traces)


def test_school_filter_keeps_only_passing_a_games_as_stars(
    guarded_page: Page, serve_booths: Callable, open_app: Callable
) -> None:
    base = _lead_points(_open(guarded_page, serve_booths, open_app))
    traces = _open(guarded_page, serve_booths, open_app, "?school=northfield")
    stars = _lead_points(traces)
    assert stars <= base
    for t in traces:
        if t["meta"].startswith("inert"):
            assert t["symbol"] in (None, "circle")


def test_one_announcer_highlight_uses_star_for_a_games(
    guarded_page: Page, serve_booths: Callable, open_app: Callable
) -> None:
    traces = _open(guarded_page, serve_booths, open_app, "?people=dale-harlow")
    highlight = next(t for t in traces if t["meta"] == "highlight")
    unrated = next(t for t in traces if t["meta"] == "highlight-unrated")
    pairs: dict[int, str] = {}
    for tr in (highlight, unrated):
        symbols = tr["symbol"] if isinstance(tr["symbol"], list) else [tr["symbol"]] * tr["n"]
        pairs.update(dict(zip(tr["customdata"], symbols, strict=True)))
    assert pairs[8] == "star"
    others = {i: s for i, s in pairs.items() if i not in LEAD_RATED | LEAD_UNRATED}
    assert others, "person 0 should have untiered games"
    assert set(others.values()) == {"circle"}
    # Their A game is drawn once, by the highlight overlay, never also as a lead star.
    assert 8 not in _lead_points(traces)


def test_compare_mode_has_no_lead_stars_and_keeps_person_shapes(
    guarded_page: Page, serve_booths: Callable, open_app: Callable
) -> None:
    traces = _open(
        guarded_page, serve_booths, open_app, "?people=dale-harlow,pat-rowan&mode=compare"
    )
    for t in traces:
        if t["meta"].startswith(("lead:", "unrated-lead", "unrated-lead-filled")):
            assert t["n"] == 0, t["meta"]
    highlight = next(t for t in traces if t["meta"] == "highlight")
    symbols = set(highlight["symbol"])
    assert symbols & {"square", "diamond", "triangle-up", "star", "circle"}
    assert "circle" in symbols or len(symbols) >= 1


def test_b_other_and_conference_lead_never_get_a_star(
    guarded_page: Page, serve_booths: Callable, open_app: Callable
) -> None:
    traces = _open(guarded_page, serve_booths, open_app)
    assert _lead_points(traces) & NEVER_STAR == set()
    assert _points(traces, "family:") | _points(traces, "unrated-active:") >= {9, 13, 4, 15}


@pytest.mark.parametrize(
    "query",
    [
        "?networks=net-b",
        "?networks=net-b&dots=hide",
        "?people=dale-harlow",
        "?people=dale-harlow,pat-rowan&mode=compare",
        "?y=excitement",
        "?axis=date",
    ],
)
def test_trace_count_is_constant(
    guarded_page: Page, serve_booths: Callable, open_app: Callable, query: str
) -> None:
    default = _open(guarded_page, serve_booths, open_app)
    other = _open(guarded_page, serve_booths, open_app, query)

    # Compare halos are paired points inside the highlight trace (notes 2026-11-02), and the
    # lead traces are always present, so the trace count never changes.
    assert len(other) == len(default)
    lead_metas = lambda ts: [t["meta"] for t in ts if "lead" in t["meta"]]  # noqa: E731
    assert lead_metas(other) == lead_metas(default)


def test_key_shows_with_lead_stars_and_hides_in_compare_without_shifting(
    guarded_page: Page, serve_booths: Callable, open_app: Callable
) -> None:
    _open(guarded_page, serve_booths, open_app)
    shown = guarded_page.evaluate(_KEY_JS)
    assert shown["visibility"] == "visible"
    assert "Lead booth" in shown["text"]
    assert shown["name"] == "Called by the lead booth for its network family"
    _open(guarded_page, serve_booths, open_app, "?people=dale-harlow,pat-rowan&mode=compare")
    compare = guarded_page.evaluate(_KEY_JS)
    assert compare["visibility"] == "hidden"
    assert compare["box"] == shown["box"]


def test_key_is_hidden_without_booth_data(
    guarded_page: Page, serve_booths: Callable, open_app: Callable
) -> None:
    _open(guarded_page, serve_booths, open_app, booths=False)
    plain = guarded_page.evaluate(_KEY_JS)
    assert plain["visibility"] == "hidden"
    assert plain["box"][3] > 0  # the space stays reserved


def test_map_tab_draws_no_star(
    guarded_page: Page, serve_booths: Callable, open_app: Callable
) -> None:
    serve_booths(guarded_page)
    open_app(guarded_page, "?view=map")
    guarded_page.wait_for_function(
        "document.getElementById('map-chart') && document.getElementById('map-chart').data"
    )
    assert guarded_page.evaluate(_KEY_JS)["hidden"] is True
    symbols = guarded_page.evaluate(
        """() => {
          const gd = document.getElementById('map-chart');
          const out = [];
          for (const t of (gd && gd.data) || []) {
            const s = t.marker && t.marker.symbol;
            if (s) out.push(...(Array.isArray(s) ? s : [s]));
          }
          return out;
        }"""
    )
    assert "star" not in symbols


def test_rated_lead_star_has_a_surface_casing_drawn_beneath_it(
    guarded_page: Page, serve_booths: Callable, open_app: Callable
) -> None:
    # Notes 2026-11-02: each star's casing is its own point, directly before the star in the
    # same trace, so overlapping stars never share one merged outline.
    traces = _open(guarded_page, serve_booths, open_app)
    by_meta = {t["meta"]: t for t in traces}
    order = [t["meta"] for t in traces]
    surface = _surface(guarded_page)
    assert not any(m.startswith(("lead-halo:", "unrated-lead-filled-halo:")) for m in order)
    for family, game in (("disney", 8), ("fox", 5)):
        star = by_meta[f"lead:{family}"]
        assert star["n"] == 2
        assert star["customdata"] == [game, game]  # both points hover and click as the game
        assert star["symbol"] == "star"
        assert star["lineWidth"] == 0
        casing_color, star_color = star["color"]
        assert casing_color == surface != star_color
        assert star["size"] == [18, 14]
    # The stars and their casings are drawn above every plain dot trace.
    last_dot = max(i for i, m in enumerate(order) if m.startswith(("family:", "unrated-active:")))
    assert min(order.index(f"lead:{f}") for f in ("disney", "fox")) > last_dot


# Draws two copies of the figure's own `lead:fox` star pair 8px apart on a blank probe plot,
# either as the figure draws them (one trace, each rim directly before its star) or as the old
# layering did (every rim in a trace beneath every star), then reads the pixels on the row
# through both centres. Returns how many rim-coloured pixels lie strictly between the centres.
_OVERLAP_JS = """
async ([layout]) => {
  const gd = document.getElementById('chart');
  const t = gd.data.find((tr) => String(tr.meta) === 'lead:fox');
  const m = t.marker;
  const [rim, star] = [0, 1].map((k) => ({ color: m.color[k], size: m.size[k] }));
  const old = document.getElementById('overlap-probe');
  if (old) old.remove();
  const w = 80, h = 60, cx = 34, cy = 30, gap = 8;
  const div = document.createElement('div');
  div.id = 'overlap-probe';
  div.style.cssText = `position:fixed;left:0;top:0;z-index:99999;width:${w}px;height:${h}px;`;
  document.body.appendChild(div);
  const bg = '#ffffff';
  const base = { type: 'scattergl', mode: 'markers', hoverinfo: 'skip', showlegend: false };
  const xs = [cx, cx + gap];
  const ys = [cy, cy];
  const data = layout === 'paired'
    ? [{ ...base, x: [xs[0], xs[0], xs[1], xs[1]], y: [cy, cy, cy, cy], marker: {
        symbol: 'star', line: { width: 0 }, opacity: 1,
        color: [rim.color, star.color, rim.color, star.color],
        size: [rim.size, star.size, rim.size, star.size] } }]
    : [{ ...base, x: xs, y: ys, marker: { symbol: 'star', line: { width: 0 }, opacity: 1,
          color: rim.color, size: rim.size } },
       { ...base, x: xs, y: ys, marker: { symbol: 'star', line: { width: 0 }, opacity: 1,
          color: star.color, size: star.size } }];
  await window.Plotly.newPlot(div, data, {
    width: w, height: h, margin: { l: 0, r: 0, t: 0, b: 0 },
    paper_bgcolor: bg, plot_bgcolor: bg,
    xaxis: { range: [0, w], visible: false, fixedrange: true },
    yaxis: { range: [h, 0], visible: false, fixedrange: true },
  }, { staticPlot: true });
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  return { rim: rim.color, star: star.color, cx, cy, gap, w, h };
}
"""

_ROW_JS = """
([url, y, x0, x1, rim]) => new Promise((resolve) => {
  const img = new Image();
  img.onload = () => {
    const c = document.createElement('canvas');
    c.width = img.width; c.height = img.height;
    const ctx = c.getContext('2d');
    ctx.drawImage(img, 0, 0);
    const hex = (v, k) => parseInt(v.slice(1 + 2 * k, 3 + 2 * k), 16);
    const ref = [0, 1, 2].map((k) => hex(rim, k));
    let rimPixels = 0;
    for (let x = x0 + 1; x < x1; x += 1) {
      const d = ctx.getImageData(x, y, 1, 1).data;
      if (Math.hypot(d[0] - ref[0], d[1] - ref[1], d[2] - ref[2]) < 60) rimPixels += 1;
    }
    resolve(rimPixels);
  };
  img.src = url;
})
"""


def _rim_pixels_between(page: Page, layout: str) -> int:
    info = page.evaluate(_OVERLAP_JS, [layout])
    png = page.screenshot(clip={"x": 0, "y": 0, "width": info["w"], "height": info["h"]})
    url = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    return int(
        page.evaluate(_ROW_JS, [url, info["cy"], info["cx"], info["cx"] + info["gap"], info["rim"]])
    )


def test_overlapping_stars_each_keep_their_own_casing(
    guarded_page: Page, serve_booths: Callable, open_app: Callable
) -> None:
    # Notes 2026-11-02: with dots enlarged, two overlapping stars showed one merged outline.
    # Drawn as the figure draws them, the front star's rim cuts across the star behind it.
    serve_booths(guarded_page)
    open_app(guarded_page, "?networks=net-b&dots=fade")
    guarded_page.wait_for_timeout(150)
    assert _rim_pixels_between(guarded_page, "paired") > 0, "overlapping stars share a border"
    # Control: the old layering (every rim beneath every star) leaves no rim between them, so
    # this test would catch the merged outline coming back.
    assert _rim_pixels_between(guarded_page, "separate") == 0


def test_one_announcer_highlight_keeps_the_unrated_lead_star_hollow(
    guarded_page: Page, serve_booths: Callable, open_app: Callable
) -> None:
    # Review F1: a highlighted no-rating star stays empty. It is an open family star with a line,
    # and the ACCENT highlight is a larger open star beneath it; nothing in either is filled.
    default = {t["meta"]: t for t in _open(guarded_page, serve_booths, open_app)}
    accent = guarded_page.evaluate(
        "async () => { const p = await import('./modules/palette.js');"
        " return p.ACCENT[document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light']; }"
    )
    traces = _open(guarded_page, serve_booths, open_app, "?people=casey-lund")
    order = [t["meta"] for t in traces]
    assert "highlight-unrated-hole" not in order
    unrated = next(t for t in traces if t["meta"] == "highlight-unrated")
    ring = next(t for t in traces if t["meta"] == "highlight-halo-unrated-open")
    at = unrated["customdata"].index(14)
    assert unrated["symbol"][at] == "star-open"
    assert unrated["lineWidth"][at] > 0
    assert unrated["color"][at] == default["lead:disney"]["color"][1]  # [casing, star]
    assert ring["n"] == 1
    assert ring["symbol"] == ["star-open"]
    assert ring["color"] == accent
    assert ring["lineWidth"] > 0
    assert ring["size"][0] > unrated["size"][at]
    assert ring["customdata"] == []
    # No filled ACCENT halo point is paired with the hollow star.
    assert unrated["customdata"].count(14) == 1
    assert order.index("highlight-halo-unrated-open") == order.index("highlight-unrated") - 1


@pytest.mark.parametrize(("theme", "rim"), [("light", "#000000"), ("dark", "#E5EAE8")])
def test_enlarged_dots_give_lead_stars_the_dot_outline(
    guarded_page: Page, serve_booths: Callable, open_app: Callable, theme: str, rim: str
) -> None:
    # Phase 17 (user sign-off): a filter that enlarges and outlines the dots gives the stars
    # the same outline, dark in light and light in dark.
    if theme == "dark":
        guarded_page.add_init_script("localStorage.setItem('bl-theme', 'dark')")
    traces = _open(guarded_page, serve_booths, open_app, "?networks=net-b&dots=fade")
    by_meta = {t["meta"]: t for t in traces}
    assert by_meta["family:fox"]["lineWidth"] == 1  # the dots are enlarged and outlined
    star = by_meta["lead:fox"]
    assert star["customdata"] == [5, 5]  # the rim point, then the star
    assert str(star["color"][0]).upper() == rim
    assert star["size"] == [18, 14]


@pytest.mark.parametrize(("theme", "rim"), [("light", "#000000"), ("dark", "#E5EAE8")])
def test_enlarged_dots_give_the_no_rating_star_the_dot_outline(
    guarded_page: Page, serve_booths: Callable, open_app: Callable, theme: str, rim: str
) -> None:
    # Review F2: the empty no-rating star takes the dot outline too, as a larger open star in the
    # DOT_OUTLINE colour around the family open star, so both outlines stay empty inside.
    if theme == "dark":
        guarded_page.add_init_script("localStorage.setItem('bl-theme', 'dark')")
    traces = _open(guarded_page, serve_booths, open_app, "?networks=net-a&dots=fade")
    by_meta = {t["meta"]: t for t in traces}
    order = [t["meta"] for t in traces]
    star, outline = by_meta["unrated-lead:disney"], by_meta["unrated-lead-rim:disney"]
    assert star["customdata"] == [14]
    assert star["symbol"] == "star-open"
    assert outline["n"] == 1
    assert outline["customdata"] == []
    assert outline["symbol"] == "star-open"
    assert str(outline["color"]).upper() == rim
    assert outline["lineWidth"] == 1  # the enlarged dots' outline weight
    assert outline["size"] > star["size"]
    assert order.index("unrated-lead-rim:disney") < order.index("unrated-lead:disney")
    # Without a filter the rim is empty, but its trace is still there.
    plain = {t["meta"]: t for t in _open(guarded_page, serve_booths, open_app)}
    assert plain["unrated-lead-rim:disney"]["n"] == 0
