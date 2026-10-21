"""Phase 11: map-splat.js painter, synthetic venue models only."""

from __future__ import annotations

from typing import Any

import pytest
from playwright.sync_api import Page

# ruff: noqa: E501  (inline JS fixtures)

pytestmark = pytest.mark.e2e

PRELUDE = """
const S = await import('./modules/map-splat.js');
const P = await import('./modules/palette.js');
const { US_STATES } = await import('./vendor/us-states-albers.js');
const cell = 3;
const lm = S.buildLandMask(US_STATES, cell);
const at = (x, y) => Math.floor(y / cell) * lm.gw + Math.floor(x / cell);
const counts = (f, n) => { const c = new Array(8).fill(0); c[f] = n; return c; };
const venue = (x, y, c, region = 1, score = 10) => ({ x, y, region, counts: c, games: c.reduce((a, b) => a + b, 0), score });
const model = (venues) => ({ venues, medianScore: 10, maxScore: 10 });
let hawaii = -1;
for (let i = 0; i < lm.mask.length; i++) if (lm.mask[i] === 2) { hawaii = i; break; }
const hx = (hawaii % lm.gw) * cell + 1.5, hy = Math.floor(hawaii / lm.gw) * cell + 1.5;
"""


def _run(page: Page, site_url: str, body: str) -> Any:
    page.goto(f"{site_url}/index.html")
    page.wait_for_function("window.__testHooks && window.__testHooks.ready === true")
    return page.evaluate("async () => {" + PRELUDE + body + "}")


def test_painters_and_mask(guarded_page: Page, site_url: str) -> None:
    got = _run(
        guarded_page,
        site_url,
        """
        return {
          keys: Object.keys(S.PAINTERS),
          gw: lm.gw, gh: lm.gh,
          kansas: lm.mask[at(480, 300)],
          atlantic: lm.mask[at(960, 400)],
          hawaii: lm.mask[at(hx, hy)],
          cached: S.buildLandMask(US_STATES, cell) === lm,
        };
        """,
    )
    assert got["keys"] == ["smooth"]
    assert (got["gw"], got["gh"]) == (325, 204)
    assert got["kansas"] == 1
    assert got["atlantic"] == 0
    assert got["hawaii"] == 2
    assert got["cached"]


def test_field_monopoly_split_and_leaders(guarded_page: Page, site_url: str) -> None:
    got = _run(
        guarded_page,
        site_url,
        """
        const mono = S.PAINTERS.smooth(model([venue(480, 300, counts(2, 6))]), lm, P.MAP_SPLAT);
        const i = at(480, 300);
        const m = { lead: mono.lead[i], margin: mono.margin[i], density: mono.density[i] };
        const split = S.PAINTERS.smooth(model([venue(480, 300, (() => { const c = counts(1, 3); c[4] = 3; return c; })())]), lm, P.MAP_SPLAT);
        const two = S.PAINTERS.smooth(model([venue(300, 300, counts(1, 5)), venue(700, 300, counts(5, 5))]), lm, P.MAP_SPLAT);
        return { m, splitMargin: split.margin[i], l1: two.lead[at(300, 300)], l2: two.lead[at(700, 300)] };
        """,
    )
    assert got["m"]["lead"] == 2
    assert abs(got["m"]["margin"] - 1) < 1e-6
    assert got["m"]["density"] > 0.5
    assert got["splitMargin"] < 1e-6
    assert (got["l1"], got["l2"]) == (1, 5)


def test_hawaii_isolation(guarded_page: Page, site_url: str) -> None:
    got = _run(
        guarded_page,
        site_url,
        """
        const main = S.PAINTERS.smooth(model([venue(150, 470, counts(0, 5), 1, 1000)]), lm, P.MAP_SPLAT);
        let insetMax = 0, mainMax = 0, mainCells = 0;
        for (let i = 0; i < lm.mask.length; i++) if (lm.mask[i] === 2) insetMax = Math.max(insetMax, main.density[i]);
        const hi = S.PAINTERS.smooth(model([venue(hx, hy, counts(0, 5), 2, 1000)]), lm, P.MAP_SPLAT);
        for (let i = 0; i < lm.mask.length; i++) if (lm.mask[i] === 1) mainMax = Math.max(mainMax, hi.density[i]);
        let insetHit = 0;
        for (let i = 0; i < lm.mask.length; i++) if (lm.mask[i] === 2) insetHit = Math.max(insetHit, hi.density[i]);
        return { insetMax, mainMax, insetHit };
        """,
    )
    assert got["insetMax"] == 0
    assert got["mainMax"] == 0
    assert got["insetHit"] > 0


def test_separable_parity_with_direct_reference(guarded_page: Page, site_url: str) -> None:
    got = _run(
        guarded_page,
        site_url,
        """
        const c2 = (a, b, n, m) => { const c = new Array(8).fill(0); c[a] = n; c[b] = m; return c; };
        const vs = [venue(400, 250, c2(0, 1, 4, 2), 1, 14), venue(470, 300, c2(2, 3, 3, 3), 1, 6), venue(600, 380, counts(5, 5), 1, 25)];
        const mdl = { venues: vs, medianScore: 14, maxScore: 25 };
        const got = S.PAINTERS.smooth(mdl, lm, P.MAP_SPLAT);
        const p = P.MAP_SPLAT, N = lm.gw * lm.gh;
        const acc = new Float64Array(N * 8), cover = new Float64Array(N);
        for (const v of vs) {
          const sv = Math.min(p.reachMax, Math.max(p.reachMin, Math.pow(v.score / mdl.medianScore, p.reachExp)));
          const s = p.spread * sv / cell, sc = Math.min(p.coreMax, p.spread * sv / 2) / cell;
          const R = Math.ceil(3 * s), cx = v.x / cell, cy = v.y / cell;
          for (let y = Math.max(0, Math.floor(cy - R)); y <= Math.min(lm.gh - 1, Math.ceil(cy + R)); y++)
            for (let x = Math.max(0, Math.floor(cx - R)); x <= Math.min(lm.gw - 1, Math.ceil(cx + R)); x++) {
              const i = y * lm.gw + x; if (lm.mask[i] !== v.region) continue;
              const d2 = (x - cx) ** 2 + (y - cy) ** 2;
              const k = Math.exp(-d2 / (2 * s * s)) + p.ownBoost * Math.exp(-d2 / (2 * sc * sc));
              for (let f = 0; f < 8; f++) if (v.counts[f]) acc[i * 8 + f] += k * v.score * v.counts[f] / v.games;
              cover[i] += k;
            }
        }
        const refs = [];
        for (let i = 0; i < N; i++) if (lm.mask[i] > 0 && cover[i] > 0.01) refs.push(cover[i]);
        refs.sort((a, b) => a - b);
        const ref = refs[Math.floor((refs.length - 1) * p.solidPercentile / 100)];
        let maxDiff = 0, leadMismatch = 0;
        for (let i = 0; i < N; i++) {
          const d = lm.mask[i] > 0 ? 1 - Math.exp(-p.densK * cover[i] / ref) : 0;
          maxDiff = Math.max(maxDiff, Math.abs(d - got.density[i]));
          let a = -1, ai = 0;
          for (let f = 0; f < 8; f++) if (acc[i * 8 + f] > a) { a = acc[i * 8 + f]; ai = f; }
          if (d > 0.05 && ai !== got.lead[i]) {
            // ties between equal families are decided by float order; ignore near-ties
            const sorted = Array.from({ length: 8 }, (_, f) => acc[i * 8 + f]).sort((x, y) => y - x);
            if (sorted[0] - sorted[1] > 1e-3 * sorted[0]) leadMismatch++;
          }
        }
        return { maxDiff, leadMismatch };
        """,
    )
    assert got["maxDiff"] < 1e-4
    assert got["leadMismatch"] == 0


def test_buffers_reused_and_zeroed(guarded_page: Page, site_url: str) -> None:
    got = _run(
        guarded_page,
        site_url,
        """
        const a = S.PAINTERS.smooth(model([venue(480, 300, counts(2, 6))]), lm, P.MAP_SPLAT);
        const leadRef = a.lead;
        const b = S.PAINTERS.smooth(model([venue(700, 300, counts(5, 6))]), lm, P.MAP_SPLAT);
        return { same: b.lead === leadRef, oldCell: b.density[at(480, 300)], newCell: b.density[at(700, 300)] };
        """,
    )
    assert got["same"]
    assert got["oldCell"] < 0.05
    assert got["newCell"] > 0.5


def test_rasterize_pixels(guarded_page: Page, site_url: str) -> None:
    got = _run(
        guarded_page,
        site_url,
        """
        const theme = 'light';
        const colors = P.FAMILY_ORDER.map((f) => P.MAP_FAMILY_COLORS[theme][f]);
        const land = P.MAP_LAND[theme];
        const c2 = new Array(8).fill(0); c2[1] = 3; c2[4] = 3;
        const mdl = model([venue(300, 300, counts(2, 6)), venue(700, 300, c2)]);
        const field = S.PAINTERS.smooth(mdl, lm, P.MAP_SPLAT);
        const cv = S.rasterize(field, lm, { colors, land, scale: 1 });
        const px = (x, y) => Array.from(cv.getContext('2d').getImageData(x, y, 1, 1).data);
        const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
        let maxA = 0;
        const small = new OffscreenCanvas(1, 1);
        // wash alpha bound: recompute from field
        for (let i = 0; i < lm.mask.length; i++) if (lm.mask[i]) maxA = Math.max(maxA, Math.round(P.MAP_SPLAT.maxAlpha * Math.pow(field.density[i], P.MAP_SPLAT.coverExp) * Math.pow(field.margin[i], P.MAP_SPLAT.marginExp) * 255));
        const empty = S.rasterize(S.PAINTERS.smooth(model([]), lm, P.MAP_SPLAT), lm, { colors, land, scale: 1 });
        const ep = Array.from(empty.getContext('2d').getImageData(480, 300, 1, 1).data);
        const hook = S.rasterize({ ...field, colorize: () => [10, 20, 30, 1] }, lm, { colors, land, scale: 1 });
        const hp = Array.from(hook.getContext('2d').getImageData(480, 300, 1, 1).data);
        const blobRes = await S.paintSplat({ venueModel: mdl, states: US_STATES, theme, cell });
        const bmp = await createImageBitmap(blobRes.blob);
        return {
          size: [cv.width, cv.height], atlantic: px(960, 400), far: px(480, 300), near: px(300, 300), split: px(700, 300),
          colorFam: hex(colors[2]), landRgb: hex(land), maxA, ep, hp,
          blob: [blobRes.blob.type, blobRes.blob.size, bmp.width, bmp.height],
          timings: Object.values(blobRes.timings).map((t) => typeof t),
        };
        """,
    )
    assert got["size"] == [975, 610]
    assert got["atlantic"][3] == 0
    assert got["far"][3] == 255
    assert got["far"][:3] == got["landRgb"]
    near = got["near"][:3]
    fam, land = got["colorFam"], got["landRgb"]
    assert sum(abs(a - b) for a, b in zip(near, fam, strict=True)) < sum(
        abs(a - b) for a, b in zip(near, land, strict=True)
    )
    assert all(abs(a - b) <= 6 for a, b in zip(got["split"][:3], land, strict=True))
    assert got["maxA"] <= round(0.88 * 255)
    assert got["ep"][:3] == land and got["ep"][3] == 255
    assert got["blob"][0] == "image/png" and got["blob"][1] > 0
    assert got["blob"][2:] == [975, 610]
    assert got["timings"] == ["number"] * 3
    # colorize hook: result differs from the default land pixel
    assert got["hp"][:3] != land


def test_synthetic_timings_printed(guarded_page: Page, site_url: str) -> None:
    got = _run(
        guarded_page,
        site_url,
        """
        const vs = [];
        let seed = 7;
        const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
        while (vs.length < 200) {
          const x = 200 + rnd() * 700, y = 60 + rnd() * 450;
          if (lm.mask[at(x, y)] !== 1) continue;
          const c = new Array(8).fill(0); for (let k = 0; k < 4; k++) c[Math.floor(rnd() * 8)] += 1 + Math.floor(rnd() * 3);
          vs.push(venue(x, y, c, 1, 2 + rnd() * 30));
        }
        const r = await S.paintSplat({ venueModel: { venues: vs, medianScore: 12, maxScore: 32 }, states: US_STATES, theme: 'light', cell });
        return r.timings;
        """,
    )
    print(f"synthetic 200-venue timings (ms): {got}")
    assert all(v >= 0 for v in got.values())


# -- Phase 11 plan 09: the live Map (switch, URL, chips) ---------------------------------

_WAIT_FRAMES = "() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))"


def _open_map(page: Page, open_app: Any, query: str = "?view=map") -> None:
    open_app(page, query)
    page.wait_for_function("() => window.__testHooks.mapRenders >= 1")


def _pressed(page: Page) -> list[str]:
    result: list[str] = page.evaluate(
        "() => [...document.querySelectorAll('#colors-toggle button')]"
        ".filter((b) => b.getAttribute('aria-pressed') === 'true').map((b) => b.dataset.colors)"
    )
    return result


def test_colors_switch_visible_only_on_map_and_round_trips_url(
    guarded_page: Page, open_app: Any
) -> None:
    open_app(guarded_page)
    assert (
        guarded_page.evaluate(
            "() => getComputedStyle(document.getElementById('colors-toggle')).visibility"
        )
        == "hidden"
    )
    _open_map(guarded_page, open_app)
    assert guarded_page.locator("#colors-toggle").is_visible()
    assert _pressed(guarded_page) == ["on"]
    guarded_page.click("#colors-toggle button[data-colors=off]")
    guarded_page.wait_for_function("() => location.search.includes('colors=off')")
    assert _pressed(guarded_page) == ["off"]
    guarded_page.click("#colors-toggle button[data-colors=on]")
    guarded_page.wait_for_function("() => !location.search.includes('colors')")
    assert _pressed(guarded_page) == ["on"]


def test_colors_off_and_bogus_urls(guarded_page: Page, open_app: Any) -> None:
    _open_map(guarded_page, open_app, "?view=map&colors=off")
    assert _pressed(guarded_page) == ["off"]
    _open_map(guarded_page, open_app, "?view=map&colors=bogus")
    assert _pressed(guarded_page) == ["on"]


def test_map_conference_chip_uses_map_violet(guarded_page: Page, open_app: Any) -> None:
    _open_map(guarded_page, open_app)
    got = guarded_page.evaluate(
        """async () => {
          const P = await import('./modules/palette.js');
          const chip = document.querySelector('#legend-chips button[data-family=conference]');
          const probe = document.createElement('span');
          probe.style.color = P.MAP_FAMILY_COLORS.light.conference;
          document.body.appendChild(probe);
          const want = getComputedStyle(probe).color;
          probe.remove();
          return {bg: getComputedStyle(chip).backgroundColor, want};
        }"""
    )
    assert got["bg"] == got["want"]


# -- Phase 11 plan 09: raster scheduling and image lifecycle ----------------------------

_IMAGES = "() => (document.getElementById('map-chart').layout.images || []).map((i) => i.source)"
_OUTLINE_FILL = "() => document.getElementById('map-chart').data[0].fill"
_TRACE_COUNT = "() => document.getElementById('map-chart').data.length"


def _splats(page: Page) -> int:
    n: int = page.evaluate("() => window.__testHooks.mapSplatRenders")
    return n


def _wait_splat(page: Page, after: int) -> None:
    page.wait_for_function("(n) => window.__testHooks.mapSplatRenders > n", arg=after)


def _set_state(page: Page, patch: dict[str, Any]) -> None:
    page.evaluate("(patch) => window.__testHooks.setState(patch)", patch)


def _open_splat(page: Page, open_app: Any, query: str = "?view=map") -> None:
    _open_map(page, open_app, query)
    _wait_splat(page, 0)


def test_default_map_has_one_blob_image_and_no_outline_fill(
    guarded_page: Page, open_app: Any
) -> None:
    _open_splat(guarded_page, open_app)
    images = guarded_page.evaluate(_IMAGES)
    assert len(images) == 1
    assert images[0].startswith("blob:")
    assert guarded_page.evaluate(_OUTLINE_FILL) == "none"


def test_colors_off_has_no_image_and_on_restores_it(guarded_page: Page, open_app: Any) -> None:
    _open_map(guarded_page, open_app, "?view=map&colors=off")
    assert guarded_page.evaluate(_IMAGES) == []
    assert guarded_page.evaluate(_OUTLINE_FILL) == "toself"
    guarded_page.click("#colors-toggle button[data-colors=on]")
    _wait_splat(guarded_page, 0)
    assert len(guarded_page.evaluate(_IMAGES)) == 1
    assert guarded_page.evaluate(_OUTLINE_FILL) == "none"
    revoked_source = guarded_page.evaluate(_IMAGES)[0]
    guarded_page.click("#colors-toggle button[data-colors=off]")
    guarded_page.wait_for_function(
        "() => (document.getElementById('map-chart').layout.images || []).length === 0"
    )
    assert guarded_page.evaluate(_OUTLINE_FILL) == "toself"
    assert guarded_page.evaluate(_FETCH_OK, revoked_source) is False


# connect-src is 'self', so a blob is probed through an image element (img-src allows blob:).
_FETCH_OK = """(u) => new Promise((resolve) => {
  const img = new Image();
  img.onload = () => resolve(true);
  img.onerror = () => resolve(false);
  img.src = u;
})"""


def test_seasons_change_swaps_image_and_revokes_previous(guarded_page: Page, open_app: Any) -> None:
    _open_splat(guarded_page, open_app)
    first = guarded_page.evaluate(_IMAGES)[0]
    assert guarded_page.evaluate(_FETCH_OK, first) is True
    n = _splats(guarded_page)
    _set_state(guarded_page, {"seasons": [2021, 2021]})
    _wait_splat(guarded_page, n)
    second = guarded_page.evaluate(_IMAGES)
    assert len(second) == 1
    assert second[0] != first
    assert guarded_page.evaluate(_FETCH_OK, first) is False
    assert guarded_page.evaluate(_TRACE_COUNT) == 13


def test_rapid_changes_coalesce_and_never_blank(guarded_page: Page, open_app: Any) -> None:
    _open_splat(guarded_page, open_app)
    guarded_page.evaluate(
        """() => {
          const gd = document.getElementById('map-chart');
          window.__imageCounts = [];
          gd.on('plotly_relayout', () => window.__imageCounts.push((gd.layout.images || []).length));
        }"""
    )
    n = _splats(guarded_page)
    guarded_page.evaluate(
        "() => { window.__testHooks.setState({seasons: [2021, 2021]});"
        " window.__testHooks.setState({seasons: [2022, 2022]}); }"
    )
    _wait_splat(guarded_page, n)
    guarded_page.evaluate(_WAIT_FRAMES)
    guarded_page.evaluate(_WAIT_FRAMES)
    assert _splats(guarded_page) == n + 1
    counts = guarded_page.evaluate("() => window.__imageCounts")
    assert counts
    assert 0 not in counts


def test_zoom_survives_a_filter_change(guarded_page: Page, open_app: Any) -> None:
    _open_splat(guarded_page, open_app)
    box = guarded_page.evaluate(
        """() => { const f = document.getElementById('map-chart')._fullLayout;
          const r = document.getElementById('map-chart').getBoundingClientRect();
          return {x: r.x + f.xaxis._offset, y: r.y + f.yaxis._offset,
                  w: f.xaxis._length, h: f.yaxis._length}; }"""
    )
    x0, y0 = box["x"] + box["w"] * 0.3, box["y"] + box["h"] * 0.3
    guarded_page.mouse.move(x0, y0)
    guarded_page.mouse.down()
    guarded_page.mouse.move(x0 + box["w"] * 0.3, y0 + box["h"] * 0.3, steps=5)
    guarded_page.mouse.up()
    zoomed = guarded_page.evaluate("() => document.getElementById('map-chart').layout.xaxis.range")
    assert zoomed[1] - zoomed[0] < 900
    n = _splats(guarded_page)
    _set_state(guarded_page, {"seasons": [2021, 2021]})
    _wait_splat(guarded_page, n)
    after = guarded_page.evaluate("() => document.getElementById('map-chart').layout.xaxis.range")
    assert [round(v) for v in after] == [round(v) for v in zoomed]


def test_all_filtered_clears_image(guarded_page: Page, open_app: Any) -> None:
    _open_splat(guarded_page, open_app)
    _set_state(guarded_page, {"networks": [], "dots": "hide"})
    guarded_page.wait_for_function(
        "() => (document.getElementById('map-chart').layout.images || []).length === 0"
    )
    assert guarded_page.evaluate(_OUTLINE_FILL) == "toself"
    assert guarded_page.locator("#map-empty-note").is_visible()


_DECODE = """async ([name, which]) => {
  const gd = document.getElementById('map-chart');
  const bmp = await new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = gd.layout.images[0].source; });
  const c = document.createElement('canvas'); c.width = bmp.naturalWidth; c.height = bmp.naturalHeight;
  const ctx = c.getContext('2d'); ctx.drawImage(bmp, 0, 0);
  const sx = c.width / 975, sy = c.height / 610;
  const dots = gd.data.find((t) => t.name === 'venue-dots');
  const px = (x, y) => [...ctx.getImageData(Math.floor(x * sx), Math.floor(y * sy), 1, 1).data];
  // Far land pixel: Kansas-ish interior, then the nearest dot's pixel.
  return { dot: px(dots.x[0], dots.y[0]), land: px(480, 300), nx: dots.x[0], ny: dots.y[0] };
}"""


def _near(a: list[int], hex_color: str, tol: int) -> bool:
    want = [int(hex_color[i : i + 2], 16) for i in (1, 3, 5)]
    return all(abs(a[i] - want[i]) <= tol for i in range(3))


def test_dark_theme_redraws_with_dark_land(guarded_page: Page, open_app: Any) -> None:
    _open_splat(guarded_page, open_app)
    n = _splats(guarded_page)
    guarded_page.emulate_media(color_scheme="dark")
    _wait_splat(guarded_page, n)
    land_dark = guarded_page.evaluate(
        "async () => (await import('./modules/palette.js')).MAP_LAND.dark"
    )
    # Find a land pixel far from every venue: scan the mask for one.
    px = guarded_page.evaluate(
        """async (land) => {
          const gd = document.getElementById('map-chart');
          const bmp = await new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = gd.layout.images[0].source; });
          const c = document.createElement('canvas'); c.width = bmp.naturalWidth; c.height = bmp.naturalHeight;
          const ctx = c.getContext('2d'); ctx.drawImage(bmp, 0, 0);
          const want = [1, 3, 5].map((i) => parseInt(land.slice(i, i + 2), 16));
          const d = ctx.getImageData(0, 0, c.width, c.height).data;
          let best = null;
          for (let i = 0; i < d.length; i += 4) {
            if (d[i + 3] === 255 && [0, 1, 2].every((k) => Math.abs(d[i + k] - want[k]) <= 3)) {
              return true;
            }
          }
          return false;
        }""",
        land_dark,
    )
    assert px is True


def test_raster_pixel_at_venue_leans_to_family_hue(guarded_page: Page, open_app: Any) -> None:
    _open_splat(guarded_page, open_app)
    got = guarded_page.evaluate(_DECODE, ["x", 0])
    land = guarded_page.evaluate(
        "async () => (await import('./modules/palette.js')).MAP_LAND.light"
    )
    fams = guarded_page.evaluate(
        "async () => Object.values((await import('./modules/palette.js')).MAP_FAMILY_COLORS.light)"
    )

    def dist(a: list[int], h: str) -> int:
        w = [int(h[i : i + 2], 16) for i in (1, 3, 5)]
        return sum(abs(a[i] - w[i]) for i in range(3))

    assert min(dist(got["dot"], f) for f in fams) < dist(got["dot"], land)


def test_raster_failure_falls_back_to_land_fill(guarded_page: Page, open_app: Any) -> None:
    messages: list[str] = []
    guarded_page.on("console", lambda m: messages.append(m.text) if m.type == "warning" else None)
    guarded_page.add_init_script(
        """
        if (typeof OffscreenCanvas !== 'undefined') {
          OffscreenCanvas.prototype.convertToBlob = () => Promise.reject(new Error('boom'));
        }
        HTMLCanvasElement.prototype.toBlob = function (cb) { cb(null); };
        """
    )
    _open_map(guarded_page, open_app)
    guarded_page.wait_for_function(
        "() => document.getElementById('map-chart').data[0].fill === 'toself'"
    )
    guarded_page.evaluate(_WAIT_FRAMES)
    assert guarded_page.evaluate(_TRACE_COUNT) == 13
    assert (
        guarded_page.evaluate(
            "() => document.getElementById('map-chart').data.find((t) => t.name === 'venue-dots').x.length"
        )
        > 0
    )
    assert guarded_page.locator("#map-empty-note").is_hidden()
    _set_state(guarded_page, {"seasons": [2021, 2021]})
    guarded_page.evaluate(_WAIT_FRAMES)
    assert len([m for m in messages if "map colors" in m]) == 1
