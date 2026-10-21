// Phase 11 (D-06, D-08, D-10, D-11, D-12): painter for the network splat on the CFB Map.
// The painter receives only the venue model, a land mask and params; it never imports
// map-venues.js or rebuilds the model. Only US land is painted, a Hawaii venue paints only
// inside the Hawaii inset and mainland venues never paint inside it. Canvas drawing
// takes numbers and palette colors only; no text or markup reaches the canvas.

import { FAMILY_ORDER, MAP_FAMILY_COLORS, MAP_LAND, MAP_SPLAT } from './palette.js';
import { HAWAII_INSET, MAP_HEIGHT, MAP_WIDTH } from './map-geo.js';

// 11-01 measured the PNG encode: scale 2 costs 200+ ms (580+ throttled), scale 1 about 50 ms.
const RASTER_SCALE = 1;

const FAMILIES = FAMILY_ORDER.length;

function makeCanvas(w, h) {
  if (typeof OffscreenCanvas !== 'undefined') return new OffscreenCanvas(w, h);
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  return c;
}

// ---------------------------------------------------------------- land mask

const maskCache = new WeakMap();

/**
 * Rasterizes the state outlines onto a grid of `cell` map units.
 * mask: 0 off land, 1 mainland land, 2 land inside the Hawaii inset. Cached per (states, cell).
 */
export function buildLandMask(states, cell) {
  let byCell = maskCache.get(states);
  if (!byCell) {
    byCell = new Map();
    maskCache.set(states, byCell);
  }
  const hit = byCell.get(cell);
  if (hit) return hit;

  const path = new Path2D();
  for (const state of states) {
    for (const ring of state.rings) {
      path.moveTo(ring[0], ring[1]);
      for (let i = 2; i < ring.length; i += 2) path.lineTo(ring[i], ring[i + 1]);
      path.closePath();
    }
  }
  const gw = Math.ceil(MAP_WIDTH / cell);
  const gh = Math.ceil(MAP_HEIGHT / cell);
  const canvas = makeCanvas(gw, gh);
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  ctx.scale(1 / cell, 1 / cell);
  ctx.fill(path);
  const data = ctx.getImageData(0, 0, gw, gh).data;
  const mask = new Uint8Array(gw * gh);
  for (let y = 0; y < gh; y++) {
    for (let x = 0; x < gw; x++) {
      const i = y * gw + x;
      if (data[i * 4 + 3] === 0) continue;
      const mx = (x + 0.5) * cell;
      const my = (y + 0.5) * cell;
      const inset =
        mx >= HAWAII_INSET.x0 && mx <= HAWAII_INSET.x1 && my >= HAWAII_INSET.y0 && my <= HAWAII_INSET.y1;
      mask[i] = inset ? 2 : 1;
    }
  }
  const result = { gw, gh, cell, mask, path };
  byCell.set(cell, result);
  return result;
}

// ---------------------------------------------------------------- smooth painter

let buf = { n: 0, acc: null, cover: null, lead: null, margin: null, density: null };

function buffers(n) {
  if (buf.n !== n) {
    buf = {
      n,
      acc: new Float32Array(n * FAMILIES),
      cover: new Float32Array(n),
      lead: new Int8Array(n),
      margin: new Float32Array(n),
      density: new Float32Array(n),
    };
  } else {
    buf.acc.fill(0);
    buf.cover.fill(0);
    buf.lead.fill(0);
    buf.margin.fill(0);
    buf.density.fill(0);
  }
  return buf;
}

function kernel(center, lo, hi, sigma) {
  const out = new Float32Array(hi - lo + 1);
  const two = 2 * sigma * sigma;
  for (let i = lo; i <= hi; i++) out[i - lo] = Math.exp(-((i - center) ** 2) / two);
  return out;
}

/**
 * Network splat field (sketch variant A). Each venue radiates its networks with
 * pull = score x (family games / venue games) as a separable Gaussian plus an own-venue core.
 * Returns { lead, margin, density } typed arrays that are reused between calls.
 */
function smooth(venueModel, landMask, params) {
  const { gw, gh, cell, mask } = landMask;
  const n = gw * gh;
  const { acc, cover, lead, margin, density } = buffers(n);
  const median = venueModel.medianScore > 0 ? venueModel.medianScore : 1;
  const amp = new Float64Array(FAMILIES);

  for (const v of venueModel.venues) {
    if (!(v.games > 0) || (v.region !== 1 && v.region !== 2)) continue;
    for (let f = 0; f < FAMILIES; f++) amp[f] = (v.score * (v.counts[f] || 0)) / v.games;
    const reach = Math.min(
      params.reachMax,
      Math.max(params.reachMin, Math.pow(v.score / median, params.reachExp)),
    );
    const s = (params.spread * reach) / cell;
    const sc = Math.min(params.coreMax, (params.spread * reach) / 2) / cell;
    const R = Math.ceil(3 * s);
    const cx = v.x / cell;
    const cy = v.y / cell;
    const x0 = Math.max(0, Math.floor(cx - R));
    const x1 = Math.min(gw - 1, Math.ceil(cx + R));
    const y0 = Math.max(0, Math.floor(cy - R));
    const y1 = Math.min(gh - 1, Math.ceil(cy + R));
    if (x1 < x0 || y1 < y0) continue;
    const kx = kernel(cx, x0, x1, s);
    const ky = kernel(cy, y0, y1, s);
    const kxc = kernel(cx, x0, x1, sc);
    const kyc = kernel(cy, y0, y1, sc);
    for (let y = y0; y <= y1; y++) {
      for (let x = x0; x <= x1; x++) {
        const i = y * gw + x;
        if (mask[i] !== v.region) continue;
        const k = ky[y - y0] * kx[x - x0] + params.ownBoost * kyc[y - y0] * kxc[x - x0];
        const o = i * FAMILIES;
        for (let f = 0; f < FAMILIES; f++) if (amp[f] > 0) acc[o + f] += k * amp[f];
        cover[i] += k;
      }
    }
  }

  const refs = [];
  for (let i = 0; i < n; i++) {
    let t = 0;
    let a = -1;
    let b = 0;
    let ai = 0;
    const o = i * FAMILIES;
    for (let f = 0; f < FAMILIES; f++) {
      const val = acc[o + f];
      t += val;
      if (val > a) {
        b = a < 0 ? 0 : a;
        a = val;
        ai = f;
      } else if (val > b) b = val;
    }
    lead[i] = ai;
    margin[i] = t > 0 ? (a - b) / t : 0;
    if (mask[i] > 0 && cover[i] > 0.01) refs.push(cover[i]);
  }
  refs.sort((p, q) => p - q);
  const ref = refs.length
    ? refs[Math.floor(((refs.length - 1) * params.solidPercentile) / 100)]
    : 1;
  for (let i = 0; i < n; i++) {
    density[i] = mask[i] > 0 ? 1 - Math.exp((-params.densK * cover[i]) / ref) : 0;
  }
  return { lead, margin, density };
}

/** Painters by style; a later territories painter registers here without touching the model. */
export const PAINTERS = Object.freeze({ smooth });

// ---------------------------------------------------------------- rasterizer

function parseHex(hex) {
  return [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
}

/**
 * Turns a painter's field into a land-filled, land-clipped canvas of
 * (MAP_WIDTH x scale) x (MAP_HEIGHT x scale).
 */
export function rasterize(field, landMask, { colors, land, scale = RASTER_SCALE, params = MAP_SPLAT }) {
  const { gw, gh, cell, mask, path } = landMask;
  const rgb = colors.map(parseHex);
  const img = new ImageData(gw, gh);
  const px = img.data;
  for (let i = 0; i < gw * gh; i++) {
    if (mask[i] === 0) continue;
    let r;
    let g;
    let b;
    let a;
    if (typeof field.colorize === 'function') {
      [r, g, b, a] = field.colorize(i);
    } else {
      a =
        params.maxAlpha *
        Math.pow(field.density[i], params.coverExp) *
        Math.pow(field.margin[i], params.marginExp);
      [r, g, b] = rgb[field.lead[i]];
    }
    if (!(a > 0)) continue;
    px[i * 4] = r;
    px[i * 4 + 1] = g;
    px[i * 4 + 2] = b;
    px[i * 4 + 3] = Math.round(a * 255);
  }
  const small = makeCanvas(gw, gh);
  small.getContext('2d').putImageData(img, 0, 0);

  const out = makeCanvas(Math.round(MAP_WIDTH * scale), Math.round(MAP_HEIGHT * scale));
  const ctx = out.getContext('2d');
  ctx.setTransform(scale, 0, 0, scale, 0, 0);
  ctx.fillStyle = land;
  ctx.fill(path);
  ctx.save();
  ctx.clip(path);
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = 'high';
  ctx.drawImage(small, 0, 0, gw * cell, gh * cell);
  ctx.restore();
  return out;
}

function encode(canvas) {
  if (typeof canvas.convertToBlob === 'function') return canvas.convertToBlob({ type: 'image/png' });
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error('PNG encode failed'))), 'image/png');
  });
}

/** Paints the splat for a venue model and encodes it as a PNG blob, with stage timings in ms. */
export async function paintSplat({
  venueModel,
  states,
  theme,
  cell,
  scale = RASTER_SCALE,
  params = MAP_SPLAT,
}) {
  const landMask = buildLandMask(states, cell);
  const t0 = performance.now();
  const field = PAINTERS[params.style](venueModel, landMask, params);
  const t1 = performance.now();
  const canvas = rasterize(field, landMask, {
    colors: FAMILY_ORDER.map((f) => MAP_FAMILY_COLORS[theme][f]),
    land: MAP_LAND[theme],
    scale,
    params,
  });
  const t2 = performance.now();
  const blob = await encode(canvas);
  const t3 = performance.now();
  return { blob, timings: { field: t1 - t0, raster: t2 - t1, encode: t3 - t2 } };
}
