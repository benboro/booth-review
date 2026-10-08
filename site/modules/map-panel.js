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

import { buildMapFigure, renderMap, bindMapEvents } from './map-chart.js';
import {
  MAP_HINT,
  MAP_EMPTY,
  MAP_ERROR,
  noLocationNote,
  mapAriaLabel,
  venueTooltipLines,
} from './map-model.js';
import { FAMILY_COLORS } from './palette.js';
import { showTextTooltip, hideTooltip } from './tooltip.js';

const TAP_DEBOUNCE_MS = 350;
/** Gap between the map space's edge and the hint / note (UI-SPEC section 5). */
const OVERLAY_INSET = 8;

const hoverNone = () => window.matchMedia('(hover: none)').matches;
const el = (id) => document.getElementById(id);

let geometryPromise = null;
let latest = null;
let bound = false;
let renderCount = 0;
let pendingTapKey = null;
let pendingTapAt = 0;

/** Clears the pending first tap so the next tap on a dot shows its tooltip again. */
export function resetMapTap() {
  pendingTapKey = null;
  pendingTapAt = 0;
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
  const left = full.xaxis._offset;
  const right = full.xaxis._offset + full.xaxis._length;
  const bottom = full.yaxis._offset + full.yaxis._length;
  const hint = el('map-hint');
  const note = el('map-note');
  if (hint) {
    hint.style.left = `${left + OVERLAY_INSET}px`;
    hint.style.bottom = `${Math.max(0, gd.clientHeight - bottom) + OVERLAY_INSET}px`;
  }
  if (note) {
    note.style.right = `${Math.max(0, gd.clientWidth - right) + OVERLAY_INSET}px`;
    note.style.bottom = `${Math.max(0, gd.clientHeight - bottom) + OVERLAY_INSET}px`;
  }
}

function familyBorder(family, env) {
  const palette = FAMILY_COLORS[env.theme] || FAMILY_COLORS.light;
  return palette[family];
}

function onVenueHover(venue, family, ev) {
  if (hoverNone() || !latest) return;
  const { data, model, env } = latest;
  showTextTooltip(venueTooltipLines(data, model, venue), {
    theme: env.theme,
    borderColor: familyBorder(family, env),
    clientX: ev.event?.clientX ?? 0,
    clientY: ev.event?.clientY ?? 0,
  });
}

function onVenueClick(venue, family, ev) {
  // A tap does nothing but show or hide the tooltip: no filter, table or panel change.
  if (!hoverNone() || !latest) return;
  const { data, model, env } = latest;
  const tapKey = `${venue}:${family}`;
  const now = performance.now();
  if (tapKey === pendingTapKey && now - pendingTapAt < TAP_DEBOUNCE_MS) return;
  if (tapKey !== pendingTapKey) {
    pendingTapKey = tapKey;
    pendingTapAt = now;
    showTextTooltip(venueTooltipLines(data, model, venue), {
      theme: env.theme,
      borderColor: familyBorder(family, env),
      clientX: ev.event?.clientX ?? 0,
      clientY: ev.event?.clientY ?? 0,
    });
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
  const hint = el('map-hint');
  if (hint) {
    hint.textContent = MAP_HINT;
    hint.hidden = model.hasSubject;
  }
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

  await renderMap(gd, buildMapFigure(model, geometry, env));
  if (!bound) {
    bindMapEvents(gd, {
      onVenueClick,
      onVenueHover,
      // On touch the tap tooltip must outlive Plotly's synthetic unhover.
      onVenueUnhover: () => {
        if (!hoverNone()) hideTooltip();
      },
    });
    gd.on('plotly_afterplot', positionOverlays);
    bound = true;
  }
  if (resize) window.Plotly.Plots.resize(gd);
  positionOverlays();
  renderCount += 1;
}
