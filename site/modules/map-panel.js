/**
 * Map panel: renders the Map model through the figure into #map-chart, keeps the
 * overlays (hint, no-location note, empty/error note) in step, and wires the hover
 * and tap tooltip (04.18 D-02, D-07, D-09, D-11, D-16).
 *
 * The state-boundary geometry is a lazy same-origin import cached in one promise, so
 * a failed import shows the MAP_ERROR note and leaves the rest of the page working.
 *
 * DOM safety: textContent / setAttribute / numeric style values only, never
 * markup-injecting APIs (T-04.18-21).
 */

import {
  buildMapFigure,
  renderMap,
  bindMapEvents,
  splatImageSpec,
  MAP_TRACE_NAMES,
} from './map-chart.js';
import { buildLandMask, paintSplat } from './map-splat.js';
import { buildMapKey, renderMapKey } from './map-key.js';
import { HAWAII_INSET } from './map-geo.js';
import { MAP_EMPTY, MAP_ERROR, noLocationNote, mapAriaLabel, venueCard } from './map-model.js';
import { MAP_LAND, MAP_SPLAT, MAP_VENUE_DOT, PAGE_BG } from './palette.js';
import { showVenueTooltip, hideTooltip } from './tooltip.js';

const TAP_DEBOUNCE_MS = 350;
const DOTS_TRACE = MAP_TRACE_NAMES.indexOf('venue-dots');
const HOVER_HINT = 'Click to list these games';
const TAP_HINT = 'Tap again to list these games';
/** Gap between the map space's edge and the hint / note (UI-SPEC section 5). */
const OVERLAY_INSET = 8;

const hoverNone = () => window.matchMedia('(hover: none)').matches;
const el = (id) => document.getElementById(id);

let geometryPromise = null;
let latest = null;
let bound = false;
let renderCount = 0;
let pendingTapKey = null;
/** The venue-dots ring arrays from the last draw, restored on unhover. */
let baseRing = null;
let lastTapActionAt = -Infinity;
/** Splat raster state (Phase 11 D-06): a render token coalesces paints, one image is live. */
let splatToken = 0;
let currentImageUrl = null;
let currentImageSpec = null;
let splatCount = 0;
let splatBroken = false;
let splatWarned = false;
/** The state geometry once loaded, for the key's land test. */
let loadedGeometry = null;

/** Clears the pending first tap so the next tap on a dot shows its tooltip again. */
export function resetMapTap() {
  pendingTapKey = null;
}

/** How many times the figure has been drawn (test hook). */
export function mapRenderCount() {
  return renderCount;
}

/** How many splat rasters have been applied to the layout (test hook). */
export function mapSplatCount() {
  return splatCount;
}

/** Drops the live raster (if any) from the layout and revokes its blob URL. */
async function clearSplat(gd) {
  splatToken += 1;
  if (!currentImageUrl) return;
  const url = currentImageUrl;
  currentImageUrl = null;
  currentImageSpec = null;
  try {
    await window.Plotly.relayout(gd, { images: [] });
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** Falls back to the plain land fill after a failed raster; logs once, shows nothing. */
function splatFailed(gd, err, theme) {
  splatBroken = true;
  if (!splatWarned) {
    splatWarned = true;
    console.warn('booth-review: map colors could not be drawn', err);
  }
  currentImageSpec = null;
  const url = currentImageUrl;
  currentImageUrl = null;
  const restyle = window.Plotly.restyle(gd, { fill: 'toself', fillcolor: MAP_LAND[theme] }, [0]);
  Promise.resolve(restyle)
    .catch(() => {})
    .then(() => window.Plotly.relayout(gd, { images: [] }))
    .catch(() => {})
    .then(() => {
      if (url) URL.revokeObjectURL(url);
    });
}

/**
 * Paints the splat behind one requestAnimationFrame; the render token discards a paint a
 * newer render has overtaken, and the previous image stays in place until the new one is in.
 */
function scheduleSplat(args, geometry) {
  const gd = el('map-chart');
  const { model, env } = args;
  const mine = ++splatToken;
  requestAnimationFrame(async () => {
    if (mine !== splatToken || latest !== args) return;
    try {
      const { blob } = await paintSplat({
        venueModel: model.venueModel,
        states: geometry,
        theme: env.theme,
        cell: env.mobile ? MAP_SPLAT.cell.phone : MAP_SPLAT.cell.desktop,
      });
      if (mine !== splatToken) return;
      const url = URL.createObjectURL(blob);
      const spec = splatImageSpec(url);
      try {
        await window.Plotly.relayout(gd, { images: [spec] });
        await window.Plotly.restyle(gd, { fill: 'none' }, [0]);
      } catch (err) {
        URL.revokeObjectURL(url);
        throw err;
      }
      const prev = currentImageUrl;
      currentImageUrl = url;
      currentImageSpec = spec;
      if (prev) URL.revokeObjectURL(prev);
      splatCount += 1;
    } catch (err) {
      if (mine === splatToken) splatFailed(gd, err, env.theme);
    }
  });
}

function loadGeometry() {
  if (!geometryPromise) {
    geometryPromise = import('../vendor/us-states-albers.js').then((m) => m.US_STATES);
  }
  return geometryPromise;
}

function showNote(copy) {
  const note = el('map-empty-note');
  if (!note) return;
  note.querySelector('.season-empty-title').textContent = copy.title;
  note.querySelector('.season-empty-hint').textContent = copy.hint;
  note.hidden = false;
}

function hideNote() {
  const note = el('map-empty-note');
  if (note) note.hidden = true;
}

/** Key anchor on desktop: bottom-left corner at these map units (open Pacific water). */
const KEY_ANCHOR = Object.freeze({ x: 20, y: 515 });
const KEY_PHONE_INSET = 8;

const boxesIntersect = (a, b) =>
  a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;

/** True when the key's box (panel pixels) lies on water and clear of the Hawaii inset. */
function keyClearOfLand(full, box) {
  if (!loadedGeometry) return false;
  const xa = full.xaxis;
  const ya = full.yaxis;
  const mapBox = {
    x0: xa.p2l(box.left - xa._offset),
    x1: xa.p2l(box.right - xa._offset),
    y0: ya.p2l(box.top - ya._offset),
    y1: ya.p2l(box.bottom - ya._offset),
  };
  const lo = { x: Math.min(mapBox.x0, mapBox.x1), y: Math.min(mapBox.y0, mapBox.y1) };
  const hi = { x: Math.max(mapBox.x0, mapBox.x1), y: Math.max(mapBox.y0, mapBox.y1) };
  if (
    lo.x < HAWAII_INSET.x1 &&
    hi.x > HAWAII_INSET.x0 &&
    lo.y < HAWAII_INSET.y1 &&
    hi.y > HAWAII_INSET.y0
  ) {
    return false;
  }
  const cell = MAP_SPLAT.cell.desktop;
  const { gw, gh, mask } = buildLandMask(loadedGeometry, cell);
  const c0 = Math.max(0, Math.floor(lo.x / cell));
  const c1 = Math.min(gw - 1, Math.floor(hi.x / cell));
  const r0 = Math.max(0, Math.floor(lo.y / cell));
  const r1 = Math.min(gh - 1, Math.floor(hi.y / cell));
  for (let r = r0; r <= r1; r++) {
    for (let c = c0; c <= c1; c++) if (mask[r * gw + c] !== 0) return false;
  }
  return true;
}

function placeKey(gd, full, panel) {
  const key = el('map-key');
  if (!key || key.hidden) return;
  const panelRect = panel.getBoundingClientRect();
  const boxOf = () => {
    const r = key.getBoundingClientRect();
    return {
      left: r.left - panelRect.left,
      right: r.right - panelRect.left,
      top: r.top - panelRect.top,
      bottom: r.bottom - panelRect.top,
    };
  };
  const corner = () => {
    key.style.left = `${KEY_PHONE_INSET}px`;
    key.style.bottom = `${KEY_PHONE_INSET}px`;
  };
  if (latest && latest.env.mobile) {
    corner();
    return;
  }
  const xa = full.xaxis;
  const ya = full.yaxis;
  key.style.left = `${Math.round(xa._offset + xa.l2p(KEY_ANCHOR.x))}px`;
  key.style.bottom = `${Math.round(panel.clientHeight - (ya._offset + ya.l2p(KEY_ANCHOR.y)))}px`;
  if (!keyClearOfLand(full, boxOf())) corner();
}

function positionOverlays() {
  const gd = el('map-chart');
  const full = gd && gd._fullLayout;
  if (!full || !full.xaxis || !full.yaxis) return;
  const right = full.xaxis._offset + full.xaxis._length;
  const bottom = full.yaxis._offset + full.yaxis._length;
  const note = el('map-note');
  if (note) {
    note.style.right = `${Math.max(0, gd.clientWidth - right) + OVERLAY_INSET}px`;
    note.style.bottom = `${Math.max(0, gd.clientHeight - bottom) + OVERLAY_INSET}px`;
  }
  const panel = el('map-panel');
  const key = el('map-key');
  if (!panel || !key) return;
  placeKey(gd, full, panel);
  if (note && !note.hidden && !key.hidden) {
    const panelRect = panel.getBoundingClientRect();
    const k = key.getBoundingClientRect();
    const n = note.getBoundingClientRect();
    const box = (r) => ({
      left: r.left - panelRect.left,
      right: r.right - panelRect.left,
      top: r.top - panelRect.top,
      bottom: r.bottom - panelRect.top,
    });
    if (boxesIntersect(box(k), box(n))) {
      note.style.bottom = `${panelRect.bottom - k.top + OVERLAY_INSET}px`;
    }
  }
}

function cardAt(key, ev, hint) {
  if (!latest) return;
  const { data, model, env } = latest;
  const card = venueCard(data, model, key);
  if (!card) return;
  showVenueTooltip(card, {
    theme: env.theme,
    clientX: ev.event?.clientX ?? 0,
    clientY: ev.event?.clientY ?? 0,
    hint,
  });
}

/** Sets (key) or clears (null) the 2px hover ring on one venue dot; one restyle, no re-render. */
function setHoverRing(key) {
  const gd = el('map-chart');
  if (!gd || !baseRing || !window.Plotly) return;
  let width = baseRing.width;
  let color = baseRing.color;
  if (key != null && latest) {
    const at = latest.model.venueDots.findIndex((d) => d.key === key);
    if (at < 0 || latest.model.venueDots[at].tier === 'subject') return;
    width = baseRing.width.slice();
    color = baseRing.color.slice();
    width[at] = MAP_VENUE_DOT.hoverRingWidth;
    color[at] = PAGE_BG[latest.env.theme];
  }
  window.Plotly.restyle(gd, { 'marker.line.width': [width], 'marker.line.color': [color] }, [
    DOTS_TRACE,
  ]);
}

function onVenueHover(key, ev) {
  if (hoverNone() || !latest) return;
  cardAt(key, ev, HOVER_HINT);
  setHoverRing(key);
}

function onVenueClick(key, ev) {
  // Desktop: the click does nothing in this plan. Phone: first tap shows the card.
  if (!hoverNone() || !latest) return;
  const now = performance.now();
  // One physical tap reaches Plotly twice (the touch, then the compatibility mouse
  // click); the second must not undo the first, whether that showed or hid the card.
  if (now - lastTapActionAt < TAP_DEBOUNCE_MS) return;
  lastTapActionAt = now;
  if (key !== pendingTapKey) {
    pendingTapKey = key;
    cardAt(key, ev, TAP_HINT);
    return;
  }
  resetMapTap();
  hideTooltip();
}

/** Wires the outside-tap listener once. */
export function initMapPanel() {
  document.addEventListener('pointerdown', (ev) => {
    if (pendingTapKey != null && !ev.target.closest('#map-chart')) {
      resetMapTap();
      hideTooltip();
    }
  });
}

/**
 * Renders one Map cycle. The overlays update synchronously; the figure follows once
 * the geometry import settles.
 * @param {{data: object, model: object, env: object, resize: boolean}} args
 */
export async function renderMapPanel(args) {
  latest = args;
  const { model, env, resize } = args;
  const gd = el('map-chart');
  if (!gd) return;

  gd.setAttribute('aria-label', mapAriaLabel(model.drawnCount));
  const note = el('map-note');
  if (note) {
    note.textContent = noLocationNote(model.noLocationCount);
    note.hidden = model.noLocationCount === 0;
  }
  const keyEl = el('map-key');
  if (keyEl) {
    renderMapKey(keyEl, buildMapKey(model.venueModel, { phone: env.mobile, colorsOn: env.splat }), {
      theme: env.theme,
    });
    if (model.emptyAll) keyEl.hidden = true;
  }
  if (model.emptyAll) showNote(MAP_EMPTY);
  else hideNote();

  let geometry;
  try {
    geometry = await loadGeometry();
  } catch {
    showNote(MAP_ERROR);
    return;
  }
  if (latest !== args) return;
  loadedGeometry = geometry;

  try {
    const wantSplat =
      Boolean(env.splat) &&
      !splatBroken &&
      !model.emptyAll &&
      model.venueModel.venues.length > 0;
    const figure = buildMapFigure(model, geometry, {
      ...env,
      // The land stays filled until the raster that replaces it is in the layout.
      splat: wantSplat && currentImageSpec !== null,
      images: wantSplat && currentImageSpec ? [currentImageSpec] : [],
    });
    const dots = figure.traces[DOTS_TRACE];
    baseRing = { width: dots.marker.line.width, color: dots.marker.line.color };
    await renderMap(gd, figure);
    if (!bound) {
      bindMapEvents(gd, {
        onVenueClick,
        onVenueHover,
        // On touch the tap tooltip must outlive Plotly's synthetic unhover.
        onVenueUnhover: () => {
          if (!hoverNone()) {
            hideTooltip();
            setHoverRing(null);
          }
        },
      });
      gd.on('plotly_afterplot', positionOverlays);
      bound = true;
    }
    if (resize) await window.Plotly.Plots.resize(gd);
    if (wantSplat) scheduleSplat(args, geometry);
    else await clearSplat(gd);
  } catch {
    // Plotly can reject (a zero-width container, say): show the same note as a
    // failed geometry import rather than leave an empty map and an unhandled
    // rejection. `bound` stays false only if the first draw failed, so the next
    // render binds the events.
    if (latest === args) showNote(MAP_ERROR);
    return;
  }
  positionOverlays();
  renderCount += 1;
}
