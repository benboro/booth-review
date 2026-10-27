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
import {
  MAP_EMPTY,
  MAP_ERROR,
  noLocationNote,
  mapAriaLabel,
  venueCard,
  venueFilterInfo,
} from './map-model.js';
import { MAP_LAND, MAP_SPLAT, MAP_VENUE_DOT, PAGE_BG } from './palette.js';
import { showVenueTooltip, hideTooltip } from './tooltip.js';

/** A touch that moves farther than this is a drag, not a tap. */
const TAP_SLOP_PX = 10;
/** How long after the pointer lifts to wait for Plotly's click on a dot before calling it background. */
const BACKGROUND_TAP_DELAY_MS = 120;
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
/** Venue dot / marker clicks seen so far; a tap that leaves it unchanged hit the background. */
let venueClickCount = 0;
/** app.js handles (Phase 11 D-05): the click filters the table through the same setState. */
let handles = { setState: null, getState: null, getMatchedCount: null };
/** Splat raster state (Phase 11 D-06): a render token coalesces paints, one image is live. */
let splatToken = 0;
let currentImageUrl = null;
let currentImageSpec = null;
let splatCount = 0;
/** Tail of the queued raster layout changes (see serialLayout). */
let layoutChain = Promise.resolve();
let splatBroken = false;
// A render that asked for a resize but was superseded hands the request to the next render.
let pendingResize = false;
let splatWarned = false;
/** The state geometry once loaded, for the key's land test. */
let loadedGeometry = null;

/** Map zoom state for the page-level Reset zoom (13-12): the unzoomed ranges and a change listener. */
let mapHome = null;
let mapZoomed = false;
let viewListener = null;
/** Set by our own draws and resizes so the next afterplot may take the live ranges as home. */
let captureHome = false;

const sameMapRange = (a, b) =>
  Array.isArray(a) && Array.isArray(b) && Math.abs(a[0] - b[0]) < 1e-6 && Math.abs(a[1] - b[1]) < 1e-6;

/** Registers the one callback run whenever the map's zoom state may have changed. */
export function onMapViewChange(fn) {
  viewListener = fn;
}

/** True while the map shows its home range (nothing for Reset zoom to undo). */
export function mapAtHome() {
  return !mapZoomed;
}

/** Puts the map back on the range it was first drawn at. */
export function resetMapZoom() {
  const gd = el('map-chart');
  if (!gd || !mapHome) return undefined;
  return window.Plotly.relayout(gd, { 'xaxis.range': mapHome.x.slice(), 'yaxis.range': mapHome.y.slice() });
}

/** Tracks the live axis ranges: they are the home range until a relayout moves them. */
function syncMapZoom(gd, fromRelayout) {
  const x = gd._fullLayout?.xaxis?.range;
  const y = gd._fullLayout?.yaxis?.range;
  if (!Array.isArray(x) || !Array.isArray(y)) return;
  if (!mapHome || (captureHome && !mapZoomed && !fromRelayout)) {
    mapHome = { x: x.slice(), y: y.slice() };
  }
  if (!fromRelayout) captureHome = false;
  mapZoomed = !(sameMapRange(x, mapHome.x) && sameMapRange(y, mapHome.y));
  viewListener?.();
}

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

/**
 * Runs one raster layout change after every earlier one has settled, so a slow older
 * relayout can never land on top of a newer render's layout. Failures do not break the chain.
 */
function serialLayout(task) {
  const run = layoutChain.then(task, task);
  layoutChain = run.catch(() => {});
  return run;
}

/** Drops the live raster (if any) from the layout and revokes its blob URL. */
async function clearSplat(gd) {
  splatToken += 1;
  // Decided when the turn comes: an in-flight paint has registered its image by then.
  await serialLayout(async () => {
    if (!currentImageUrl) return;
    const url = currentImageUrl;
    currentImageUrl = null;
    currentImageSpec = null;
    try {
      await window.Plotly.relayout(gd, { images: [] });
    } finally {
      URL.revokeObjectURL(url);
    }
  });
}

/** Draws the size-only key. */
function drawKey({ model, env }) {
  const keyEl = el('map-key');
  if (!keyEl) return;
  renderMapKey(keyEl, buildMapKey(model.venueModel, { phone: env.mobile }), {
    theme: env.theme,
  });
  if (model.emptyAll) keyEl.hidden = true;
}

/** Falls back to the plain land fill after a failed raster; logs once, shows nothing. */
function splatFailed(gd, err, theme, mine) {
  splatBroken = true;
  if (!splatWarned) {
    splatWarned = true;
    console.warn('booth-review: map colors could not be drawn', err);
  }
  if (latest) {
    drawKey(latest);
    positionOverlays();
  }
  currentImageSpec = null;
  const url = currentImageUrl;
  currentImageUrl = null;
  // Queued behind every other layout change; a newer render (token) owns the image and the
  // fill by the time this runs, so it only revokes the blob it was holding.
  serialLayout(async () => {
    if (mine === splatToken) {
      try {
        await window.Plotly.restyle(gd, { fill: 'toself', fillcolor: MAP_LAND[theme] }, [0]);
      } catch {
        // The relayout below still clears the image.
      }
      if (mine === splatToken) {
        try {
          await window.Plotly.relayout(gd, { images: [] });
        } catch {
          // Nothing more to fall back on.
        }
      }
    }
    if (url) URL.revokeObjectURL(url);
  });
}

/**
 * Puts one painted raster into the layout. Runs in the serialized queue, so it starts only
 * after every earlier layout change has settled; a render that has overtaken it by then
 * (token) costs only its own blob. The image is registered as live before the relayout so
 * a clear or a newer paint that follows always sees and removes it; the previous image is
 * revoked once this one is in the layout.
 */
async function applySplat(gd, mine, blob, theme) {
  const url = URL.createObjectURL(blob);
  if (mine !== splatToken) {
    URL.revokeObjectURL(url);
    return;
  }
  const spec = splatImageSpec(url);
  const prev = currentImageUrl;
  const prevSpec = currentImageSpec;
  currentImageUrl = url;
  currentImageSpec = spec;
  try {
    await window.Plotly.relayout(gd, { images: [spec] });
  } catch (err) {
    if (currentImageUrl === url) {
      currentImageUrl = prev;
      currentImageSpec = prevSpec;
    }
    URL.revokeObjectURL(url);
    if (mine === splatToken) splatFailed(gd, err, theme, mine);
    return;
  }
  if (prev) URL.revokeObjectURL(prev);
  // A newer render took over while the image went in: it re-applies or removes the image
  // and sets the fill itself, so this one leaves the fill and the shared state alone.
  if (mine !== splatToken) return;
  try {
    await window.Plotly.restyle(gd, { fill: 'none' }, [0]);
  } catch (err) {
    if (mine === splatToken) splatFailed(gd, err, theme, mine);
    return;
  }
  if (mine === splatToken) splatCount += 1;
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
      await serialLayout(() => applySplat(gd, mine, blob, env.theme));
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

/** Raises the note above any edge-marker label it would cover (Nassau sits at the bottom right). */
function liftNoteClearOfLabels(gd, panel, note) {
  const panelRect = panel.getBoundingClientRect();
  const labels = Array.from(gd.querySelectorAll('.scatterlayer .textpoint'))
    .map((n) => n.getBoundingClientRect())
    .filter((r) => r.width > 0 && r.height > 0);
  for (let pass = 0; pass < labels.length; pass++) {
    const n = note.getBoundingClientRect();
    const hit = labels.find(
      (r) => r.left < n.right && r.right > n.left && r.top < n.bottom && r.bottom > n.top,
    );
    if (!hit) return;
    note.style.bottom = `${panelRect.bottom - hit.top + OVERLAY_INSET / 2}px`;
  }
}

function positionOverlays() {
  const gd = el('map-chart');
  const full = gd && gd._fullLayout;
  if (!full || !full.xaxis || !full.yaxis) return;
  const right = full.xaxis._offset + full.xaxis._length;
  const bottom = full.yaxis._offset + full.yaxis._length;
  const panel = el('map-panel');
  const note = el('map-note');
  if (note) {
    // On a phone the key sits in flow under the chart (v2.1), so the panel runs past the
    // chart's box; the note still anchors to the chart's own bottom-right corner.
    const extraBelow = panel
      ? Math.max(0, panel.clientHeight - gd.offsetTop - gd.clientHeight)
      : 0;
    note.style.right = `${Math.max(0, gd.clientWidth - right) + OVERLAY_INSET}px`;
    note.style.bottom = `${Math.max(0, gd.clientHeight - bottom) + OVERLAY_INSET + extraBelow}px`;
  }
  const key = el('map-key');
  if (!panel || !key) return;
  placeKey(gd, full, panel);
  if (note && !note.hidden) liftNoteClearOfLabels(gd, panel, note);
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

/**
 * Filters the Matched games table to one venue or abroad group (Phase 11 D-05), then
 * scrolls to the table, moves focus to its heading and announces the count. A key that is
 * already selected only scrolls and focuses.
 */
function applyVenue(key) {
  const { setState, getState, getMatchedCount } = handles;
  if (!setState || !latest) return;
  const info = venueFilterInfo(latest.data, key);
  if (!info) return;
  if (getState().venue !== key) setState({ venue: key });
  hideTooltip();
  resetMapTap();
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  el('matched-games')?.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'start' });
  el('matched-games-title')?.focus({ preventScroll: true });
  const n = getMatchedCount();
  const status = el('venue-status');
  if (status) {
    status.textContent = `Showing ${n} ${n === 1 ? 'game' : 'games'} at ${info.name}`;
  }
}

function onVenueClick(key, ev) {
  venueClickCount += 1;
  if (!latest) return;
  if (!hoverNone()) {
    applyVenue(key);
    return;
  }
  // The touch pointerdown is cancelled (initMapPanel), so a tap reaches Plotly once, from
  // its touch events. A compatibility mouse click that still arrives says it came from
  // touch; dropping it by its source, not by time, means no queue order or delay lets it
  // count as a second tap, and a real mouse's clicks are never held back.
  const src = ev?.event;
  if (src?.type?.startsWith('mouse') && src.sourceCapabilities?.firesTouchEvents) return;
  if (key !== pendingTapKey) {
    pendingTapKey = key;
    cardAt(key, ev, TAP_HINT);
    return;
  }
  applyVenue(key);
}

/** Wires the outside-tap and map-background-tap listeners once. */
export function initMapPanel({ setState, getState, getMatchedCount } = {}) {
  handles = { setState, getState, getMatchedCount };
  /** The touch in progress inside the map: where it began and how many venue clicks preceded it. */
  let down = null;
  /** Settles the last tap's background check now; null when none is waiting. */
  let settleBackground = null;
  document.addEventListener('pointerdown', (ev) => {
    // Input arrives in order, so the last tap's Plotly click (if any) is in by now: settle
    // its background check before this tap, or a tap inside the wait would find the old
    // venue still armed and filter it.
    settleBackground?.();
    if (!ev.target.closest('#map-chart')) {
      down = null;
      if (pendingTapKey != null) {
        resetMapTap();
        hideTooltip();
      }
      return;
    }
    // Cancelling a touch pointerdown stops the browser's compatibility mouse events (Pointer
    // Events), so Plotly sees each tap once. Scrolling and pinch follow touch-action instead.
    if (ev.pointerType === 'touch') ev.preventDefault();
    down = hoverNone() ? { x: ev.clientX, y: ev.clientY, clicks: venueClickCount } : null;
  });
  document.addEventListener('pointercancel', () => {
    down = null;
  });
  document.addEventListener('pointerup', (ev) => {
    const start = down;
    down = null;
    if (!start || Math.hypot(ev.clientX - start.x, ev.clientY - start.y) > TAP_SLOP_PX) return;
    // UI-SPEC: a tap on the map that lands on no dot or marker clears only the card. Plotly
    // reports a hit through plotly_click a moment after the pointer lifts, so look afterwards.
    const settle = () => {
      clearTimeout(timer);
      if (settleBackground === settle) settleBackground = null;
      if (venueClickCount !== start.clicks) return;
      resetMapTap();
      hideTooltip();
    };
    const timer = setTimeout(settle, BACKGROUND_TAP_DELAY_MS);
    settleBackground = settle;
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
  if (resize) pendingResize = true;
  const gd = el('map-chart');
  if (!gd) return;

  gd.setAttribute('aria-label', mapAriaLabel(model.drawnCount));
  const note = el('map-note');
  if (note) {
    note.textContent = noLocationNote(model.noLocationCount);
    note.hidden = model.noLocationCount === 0;
  }
  // A new render is a new chance for the colors: a failed raster no longer sticks.
  splatBroken = false;
  drawKey(args);
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
      // D-21: the plot size in pixels, so edge markers can be spaced by label height.
      plot: { w: gd.clientWidth, h: gd.clientHeight },
      // The land stays filled until the raster that replaces it is in the layout.
      splat: wantSplat && currentImageSpec !== null,
      images: wantSplat && currentImageSpec ? [currentImageSpec] : [],
    });
    const dots = figure.traces[DOTS_TRACE];
    baseRing = { width: dots.marker.line.width, color: dots.marker.line.color };
    captureHome = true;
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
      gd.on('plotly_afterplot', () => {
        positionOverlays();
        syncMapZoom(gd, false);
      });
      gd.on('plotly_relayout', (ev) => {
        if (ev && Object.keys(ev).some((k) => k.startsWith('xaxis.') || k.startsWith('yaxis.'))) {
          syncMapZoom(gd, true);
        }
      });
      bound = true;
    }
    // A newer render owns the raster, the overlays and any pending resize.
    if (latest !== args) return;
    if (pendingResize) {
      pendingResize = false;
      captureHome = true;
      await window.Plotly.Plots.resize(gd);
      if (latest !== args) {
        pendingResize = true;
        return;
      }
    }
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
