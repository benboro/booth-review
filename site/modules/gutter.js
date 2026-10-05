/**
 * 04.12 SITE-49: the scatter x-axis edge gutter. `scattergl` clips markers at
 * the plot area and ignores `cliponaxis`, so the only lever is the axis range.
 * This module converts a screen-pixel gutter into data-unit range pads.
 * DOM-free and pure.
 */

/**
 * Screen pixels kept clear between each end of the x range and the nearest
 * plotted marker. This is a marker-clearance constant, not a spacing token:
 * the largest marker is the 15px star with a +3 halo (18px, half-extent 9px),
 * plus 1px of antialiasing = 10. Do not round it to the 8px spacing step. If a
 * marker size grows, raise this; the marker-extent e2e guard fails first.
 */
export const GUTTER_PX = 10;

const finiteOr0 = (v) => (Number.isFinite(v) ? v : 0);

/**
 * Data-unit pads [padLo, padHi] that put each end of the range at least `px`
 * screen pixels beyond the data extremes on a plot `plotPx` wide, never
 * shrinking the legacy pads `minLo` / `minHi`.
 *
 * Closed form (no iteration). With T = inner + padLo + padHi the requirement
 * is pad >= px * T / plotPx. The shared gutter g is the largest of the fixed
 * points of each affine piece:
 *   g_both     = px * inner / (plotPx - 2 * px)
 *   g_loPinned = px * (inner + minLo) / (plotPx - px)
 *   g_hiPinned = px * (inner + minHi) / (plotPx - px)
 *   g_none     = px * (inner + minLo + minHi) / plotPx
 * The max of those fixed points is the fixed point of the max of the pieces
 * because every slope is below 1. Then padLo = max(minLo, g), padHi = max(minHi, g).
 * Degenerate input (non-finite, inner <= 0, plotPx <= 2 * px) returns the
 * legacy pads unchanged.
 * @param {number} inner - data extent between the two anchored extremes.
 * @param {number} plotPx - plot area width in screen pixels.
 * @param {{px?: number, minLo?: number, minHi?: number}} [opts]
 * @returns {[number, number]}
 */
export function gutterPads(inner, plotPx, { px = GUTTER_PX, minLo = 0, minHi = 0 } = {}) {
  if (
    !Number.isFinite(inner) ||
    !Number.isFinite(plotPx) ||
    !Number.isFinite(minLo) ||
    !Number.isFinite(minHi) ||
    !Number.isFinite(px) ||
    inner <= 0 ||
    plotPx <= 2 * px
  ) {
    return [finiteOr0(minLo), finiteOr0(minHi)];
  }
  const g = Math.max(
    (px * inner) / (plotPx - 2 * px),
    (px * (inner + minLo)) / (plotPx - px),
    (px * (inner + minHi)) / (plotPx - px),
    (px * (inner + minLo + minHi)) / plotPx,
  );
  return [Math.max(minLo, g), Math.max(minHi, g)];
}
