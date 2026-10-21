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
