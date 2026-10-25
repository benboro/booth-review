"""Phase 11: map-splat.js painter, synthetic venue models only."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page

# ruff: noqa: E501  (inline JS fixtures)

pytestmark = pytest.mark.e2e

# Review screenshots go to a scratch folder (never committed); tmp_path-free on purpose.
_SHOTS = Path(
    os.environ.get(
        "BOOTH_REVIEW_SHOTS",
        "/tmp/claude-1000/-home-ben-projects-booth-review/8f1ddb8d-4483-4a07-97ba-c49bc76eb3a6/scratchpad",
    )
)

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


def test_old_colors_param_is_ignored(guarded_page: Page, open_app: Any) -> None:
    """An old ?colors=off link draws the colours, logs nothing and never re-encodes the param."""
    _open_map(guarded_page, open_app, "?view=map&colors=off")
    _wait_splat(guarded_page, 0)
    assert len(guarded_page.evaluate(_IMAGES)) == 1
    assert guarded_page.evaluate(_OUTLINE_FILL) == "none"
    assert guarded_page.locator("#colors-toggle").count() == 0
    _set_state(guarded_page, {"seasons": [2021, 2021]})
    guarded_page.evaluate(_WAIT_FRAMES)
    assert "colors" not in guarded_page.evaluate("() => location.search")


def test_map_conference_chip_dot_uses_map_violet(guarded_page: Page, open_app: Any) -> None:
    _open_map(guarded_page, open_app)
    got = guarded_page.evaluate(
        """async () => {
          const P = await import('./modules/palette.js');
          const chip = document.querySelector('#legend-chips button[data-family=conference] .legend-dot');
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
    assert guarded_page.evaluate(_TRACE_COUNT) == 14


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
        window.__failRaster = true;
        if (typeof OffscreenCanvas !== 'undefined') {
          const real = OffscreenCanvas.prototype.convertToBlob;
          OffscreenCanvas.prototype.convertToBlob = function (...a) {
            return window.__failRaster ? Promise.reject(new Error('boom')) : real.apply(this, a);
          };
        }
        const realToBlob = HTMLCanvasElement.prototype.toBlob;
        HTMLCanvasElement.prototype.toBlob = function (cb, ...a) {
          if (window.__failRaster) cb(null);
          else realToBlob.call(this, cb, ...a);
        };
        """
    )
    _open_map(guarded_page, open_app)
    guarded_page.wait_for_function(
        "() => document.getElementById('map-chart').data[0].fill === 'toself'"
    )
    guarded_page.evaluate(_WAIT_FRAMES)
    assert guarded_page.evaluate(_TRACE_COUNT) == 14
    assert (
        guarded_page.evaluate(
            "() => document.getElementById('map-chart').data.find((t) => t.name === 'venue-dots').x.length"
        )
        > 0
    )
    assert guarded_page.locator("#map-empty-note").is_hidden()
    _set_state(guarded_page, {"seasons": [2021, 2021]})
    guarded_page.evaluate(_WAIT_FRAMES)
    _settle(guarded_page)
    assert len([m for m in messages if "map colors" in m]) == 1
    assert guarded_page.evaluate(_OUTLINE_FILL) == "toself"
    # The next paint retries: once the raster works again the colors come back.
    guarded_page.evaluate("() => { window.__failRaster = false; }")
    _set_state(guarded_page, {"seasons": [2022, 2022]})
    _wait_splat(guarded_page, 0)
    assert len(guarded_page.evaluate(_IMAGES)) == 1
    assert guarded_page.evaluate(_OUTLINE_FILL) == "none"
    assert len([m for m in messages if "map colors" in m]) == 1


# -- Review fix: the raster race (a slow older relayout must not undo a newer render) ----------

# Holds the next `n` raster layout calls (relayout with images, restyle with fill) on the
# map. "resolve" calls Plotly at once and resolves its promise on release; "apply" calls
# Plotly only on release, so the held change lands after anything newer.
_GATE = """(mode) => {
  const P = window.Plotly;
  const gate = (window.__gate = { n: 0, mode, held: 0, release: null, waiting: [] });
  const wrap = (name, key) => {
    const real = P[name].bind(P);
    P[name] = (gd, ...rest) => {
      const raster = gd && gd.id === 'map-chart' && rest[0] && key in rest[0];
      if (!raster || gate.n <= 0) return real(gd, ...rest);
      gate.n -= 1;
      gate.held += 1;
      return new Promise((resolve, reject) => {
        if (gate.mode === 'apply') gate.waiting.push(() => real(gd, ...rest).then(resolve, reject));
        else {
          const p = real(gd, ...rest);
          gate.waiting.push(() => p.then(resolve, reject));
        }
      });
    };
  };
  wrap('relayout', 'images');
  wrap('restyle', 'fill');
  gate.release = () => gate.waiting.splice(0).forEach((f) => f());
}"""


def _hold_next(page: Page, mode: str) -> None:
    page.evaluate(f"({_GATE})('{mode}')")
    page.evaluate("() => { window.__gate.n = 1; }")


def _settle(page: Page, frames: int = 12) -> None:
    for _ in range(frames):
        page.evaluate(_WAIT_FRAMES)
    page.wait_for_timeout(150)


def _release_and_settle(page: Page) -> None:
    page.evaluate("() => window.__gate.release()")
    _settle(page)


@pytest.mark.parametrize("mode", ["resolve", "apply"])
def test_stale_paint_suspended_in_relayout_does_not_revoke_the_newer_image(
    guarded_page: Page, open_app: Any, mode: str
) -> None:
    """Paint A is held in its relayout while paint B is requested; once A resumes the live
    image is B's, still loadable, and A has not recorded itself or revoked B."""
    _open_splat(guarded_page, open_app)
    n = _splats(guarded_page)
    _hold_next(guarded_page, mode)
    _set_state(guarded_page, {"seasons": [2021, 2021]})
    guarded_page.wait_for_function("() => window.__gate.held === 1")
    _set_state(guarded_page, {"seasons": [2022, 2022]})
    _settle(guarded_page)
    _release_and_settle(guarded_page)
    _wait_splat(guarded_page, n)
    images = guarded_page.evaluate(_IMAGES)
    assert len(images) == 1
    assert guarded_page.evaluate(_FETCH_OK, images[0]) is True
    assert guarded_page.evaluate(_OUTLINE_FILL) == "none"
    assert _splats(guarded_page) == n + 1


# -- Review fix WR-01: a superseded render must not cancel the current render's raster ---------

# Plotly.react on the map: the first call resolves only on `__releaseFirst()`, the rest at once.
_HOLD_FIRST_REACT = """() => {
  const P = window.Plotly;
  const real = P.react.bind(P);
  const s = (window.__react = { calls: 0, release: null, second: null });
  P.react = (gd, ...rest) => {
    if (!gd || gd.id !== 'map-chart') return real(gd, ...rest);
    s.calls += 1;
    const p = real(gd, ...rest);
    if (s.calls === 1) return new Promise((resolve) => { s.release = () => p.then(resolve); });
    if (s.calls === 2) s.second = p;
    return p;
  };
}"""


def test_render_finishing_out_of_order_does_not_cancel_the_newer_raster(
    guarded_page: Page, open_app: Any
) -> None:
    """Render A's Plotly.react resolves after render B's: A must not schedule a paint that
    bumps the token past B's, or B's raster is dropped and the land stays unpainted."""
    _open_splat(guarded_page, open_app)
    n = _splats(guarded_page)
    guarded_page.evaluate(_HOLD_FIRST_REACT)
    _set_state(guarded_page, {"seasons": [2021, 2021]})
    guarded_page.wait_for_function("() => window.__react.calls === 1")
    _set_state(guarded_page, {"seasons": [2022, 2022]})
    guarded_page.evaluate(
        """async () => {
          while (!window.__react.second) await new Promise((r) => setTimeout(r, 0));
          await window.__react.second;
          window.__react.release();
        }"""
    )
    _settle(guarded_page)
    _wait_splat(guarded_page, n)
    assert len(guarded_page.evaluate(_IMAGES)) == 1
    assert guarded_page.evaluate(_OUTLINE_FILL) == "none"


def test_superseded_first_open_hands_its_resize_to_the_next_render(
    guarded_page: Page, open_app: Any
) -> None:
    """The render that opens the Map tab asks for a resize; a second render lands before
    it gets past the geometry import. The map must still be resized once."""
    open_app(guarded_page, "")
    guarded_page.evaluate(
        """() => {
          const P = window.Plotly;
          const real = P.Plots.resize.bind(P.Plots);
          window.__mapResizes = 0;
          P.Plots.resize = (gd, ...rest) => {
            if (gd && gd.id === 'map-chart') window.__mapResizes += 1;
            return real(gd, ...rest);
          };
          window.__testHooks.setState({ view: 'map' });
          window.__testHooks.setState({ seasons: [2021, 2021] });
        }"""
    )
    _settle(guarded_page)
    assert guarded_page.evaluate("() => window.__mapResizes") >= 1


def test_raster_failure_cleanup_does_not_strip_a_newer_image(
    guarded_page: Page, open_app: Any
) -> None:
    """WR-04: paint A's relayout rejects and its cleanup is still restyling the land fill when
    paint B is requested. The cleanup runs in the layout queue, so B's image goes in after it
    instead of being stripped by its late relayout."""
    _open_splat(guarded_page, open_app)
    n = _splats(guarded_page)
    guarded_page.evaluate(
        """() => {
          const P = window.Plotly;
          const real = P.relayout.bind(P);
          const s = (window.__fail = { armed: true, reject: null, held: [] });
          const realRestyle = P.restyle.bind(P);
          // The failure cleanup's land-fill restyle is held so it would land after B's image.
          P.restyle = (gd, upd, ...rest) =>
            gd && gd.id === 'map-chart' && upd && upd.fill === 'toself'
              ? new Promise((resolve) => s.held.push(() => realRestyle(gd, upd, ...rest).then(resolve)))
              : realRestyle(gd, upd, ...rest);
          P.relayout = (gd, upd, ...rest) => {
            if (gd && gd.id === 'map-chart' && upd && upd.images && upd.images.length && s.armed) {
              s.armed = false;
              return new Promise((_, rej) => { s.reject = () => rej(new Error('boom')); });
            }
            return real(gd, upd, ...rest);
          };
        }"""
    )
    _set_state(guarded_page, {"seasons": [2021, 2021]})
    guarded_page.wait_for_function("() => window.__fail.reject !== null")
    guarded_page.evaluate("() => window.__fail.reject()")
    guarded_page.wait_for_function("() => window.__fail.held.length === 1")
    _set_state(guarded_page, {"seasons": [2022, 2022]})
    _settle(guarded_page)
    guarded_page.evaluate("() => window.__fail.held.splice(0).forEach((f) => f())")
    _settle(guarded_page)
    _wait_splat(guarded_page, n)
    images = guarded_page.evaluate(_IMAGES)
    assert len(images) == 1
    assert guarded_page.evaluate(_FETCH_OK, images[0]) is True


# -- Phase 11 plan 09: the key overlay ---------------------------------------------------

_KEY_BOXES = """async () => {
  const gd = document.getElementById('map-chart');
  const full = gd._fullLayout;
  const panel = document.getElementById('map-panel').getBoundingClientRect();
  const rel = (r) => ({ left: r.left - panel.left, right: r.right - panel.left,
                        top: r.top - panel.top, bottom: r.bottom - panel.top });
  const key = document.getElementById('map-key');
  const note = document.getElementById('map-note');
  const G = await import('./modules/map-geo.js');
  const xa = full.xaxis, ya = full.yaxis;
  const px = (x, y) => ({ x: xa._offset + xa.l2p(x), y: ya._offset + ya.l2p(y) });
  const a = px(G.HAWAII_INSET.x0, G.HAWAII_INSET.y0), b = px(G.HAWAII_INSET.x1, G.HAWAII_INSET.y1);
  const { US_STATES } = await import('./vendor/us-states-albers.js');
  const S = await import('./modules/map-splat.js');
  const cell = 3, lm = S.buildLandMask(US_STATES, cell);
  const k = rel(key.getBoundingClientRect());
  const m = (p, o) => o.p2l(p);
  const x0 = xa.p2l(k.left - xa._offset), x1 = xa.p2l(k.right - xa._offset);
  const y0 = ya.p2l(k.top - ya._offset), y1 = ya.p2l(k.bottom - ya._offset);
  let land = 0;
  for (let r = Math.max(0, Math.floor(Math.min(y0, y1) / cell)); r <= Math.min(lm.gh - 1, Math.floor(Math.max(y0, y1) / cell)); r++)
    for (let c = Math.max(0, Math.floor(Math.min(x0, x1) / cell)); c <= Math.min(lm.gw - 1, Math.floor(Math.max(x0, x1) / cell)); c++)
      if (lm.mask[r * lm.gw + c] !== 0) land++;
  return { key: k, note: note.hidden ? null : rel(note.getBoundingClientRect()),
           hawaii: { left: Math.min(a.x, b.x), right: Math.max(a.x, b.x), top: Math.min(a.y, b.y), bottom: Math.max(a.y, b.y) },
           land, panelW: panel.width, panelH: panel.height,
           visible: !key.hidden, text: key.innerText };
}"""


def _hits(a: dict[str, float], b: dict[str, float]) -> bool:
    return bool(
        a["left"] < b["right"]
        and a["right"] > b["left"]
        and a["top"] < b["bottom"]
        and a["bottom"] > b["top"]
    )


def test_key_desktop_over_water_clear_of_inset(guarded_page: Page, open_app: Any) -> None:
    guarded_page.set_viewport_size({"width": 1280, "height": 900})
    _open_splat(guarded_page, open_app)
    guarded_page.evaluate(_WAIT_FRAMES)
    got = guarded_page.evaluate(_KEY_BOXES)
    assert got["visible"]
    assert "Dot size" in got["text"]
    labels = guarded_page.locator("#map-key .map-key-label").all_inner_texts()
    assert 1 <= len(labels) <= 3
    assert all(t.endswith(("game", "games")) for t in labels)
    assert got["land"] == 0
    assert not _hits(got["key"], got["hawaii"])
    if got["note"]:
        assert not _hits(got["key"], got["note"])


def test_key_phone_sits_in_panel_corner(mobile_page: Page, open_app: Any) -> None:
    _open_splat(mobile_page, open_app)
    mobile_page.evaluate(_WAIT_FRAMES)
    got = mobile_page.evaluate(_KEY_BOXES)
    key = got["key"]
    assert key["left"] >= 0 and key["right"] <= got["panelW"]
    assert key["bottom"] <= got["panelH"] and key["top"] >= 0
    assert abs(key["left"] - 8) <= 1
    assert abs(got["panelH"] - key["bottom"] - 8) <= 1
    if got["note"]:
        assert not _hits(key, got["note"])
    mobile_page.screenshot(path=str(_SHOTS / "map-key-390.png"))


def test_key_hidden_when_every_game_filtered(guarded_page: Page, open_app: Any) -> None:
    _open_splat(guarded_page, open_app)
    _set_state(guarded_page, {"networks": [], "dots": "hide"})
    guarded_page.wait_for_function("() => document.getElementById('map-key').hidden")


def test_key_desktop_screenshot(guarded_page: Page, open_app: Any) -> None:
    guarded_page.set_viewport_size({"width": 1280, "height": 900})
    _open_splat(guarded_page, open_app)
    guarded_page.evaluate(_WAIT_FRAMES)
    guarded_page.locator("#map-panel").screenshot(path=str(_SHOTS / "map-key-1280.png"))


_NOTE_VS_LABELS = """() => {
  const note = document.getElementById('map-note');
  const r = note.getBoundingClientRect();
  const labels = Array.from(document.querySelectorAll('#map-chart .scatterlayer .textpoint'))
    .map((n) => n.getBoundingClientRect()).filter((b) => b.width > 0);
  return { shown: !note.hidden, note: { left: r.left, right: r.right, top: r.top, bottom: r.bottom },
           labels: labels.map((b) => ({ left: b.left, right: b.right, top: b.top, bottom: b.bottom })) };
}"""


def _assert_note_clear_of_labels(page: Page) -> None:
    got = page.evaluate(_NOTE_VS_LABELS)
    assert got["shown"] and got["labels"]
    for label in got["labels"]:
        assert not _hits(got["note"], label), (got["note"], label)


def test_note_clears_edge_marker_labels_desktop(guarded_page: Page, open_app: Any) -> None:
    guarded_page.set_viewport_size({"width": 1280, "height": 900})
    _open_splat(guarded_page, open_app)
    guarded_page.evaluate(_WAIT_FRAMES)
    _assert_note_clear_of_labels(guarded_page)


def test_note_clears_edge_marker_labels_phone(mobile_page: Page, open_app: Any) -> None:
    _open_splat(mobile_page, open_app)
    mobile_page.evaluate(_WAIT_FRAMES)
    _assert_note_clear_of_labels(mobile_page)
