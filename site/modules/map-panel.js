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

import { buildMapFigure, renderMap, bindMapEvents, MAP_TRACE_NAMES } from './map-chart.js';
import { MAP_EMPTY, MAP_ERROR, noLocationNote, mapAriaLabel, venueCard } from './map-model.js';
import { MAP_VENUE_DOT, PAGE_BG } from './palette.js';
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

/** Clears the pending first tap so the next tap on a dot shows its tooltip again. */
export function resetMapTap() {
  pendingTapKey = null;
}

/** How many times the figure has been drawn (test hook). */
export function mapRenderCount() {
  return renderCount;
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

  try {
    const figure = buildMapFigure(model, geometry, env);
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
