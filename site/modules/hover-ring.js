/**
 * Hover ring: a single fixed, pointer-transparent DOM ring drawn over the
 * hovered scatter dot so a visitor can tell which dot the tooltip describes
 * (notes-6).
 *
 * It is a DOM overlay, not a Plotly trace or `marker.line`: showing it costs two
 * style writes (no restyle/relayout, 04.2 D-01 layout invariance, O(1) at any
 * point count), adds no trace, and being a halo outside the glyph it cannot
 * bring back the D-31 SDF edge speckles. It only ever appears for dots that
 * fire `plotly_hover` (inert/faded dots skip hover, D-15) and never on touch
 * devices (D-22; app.js gates that).
 *
 * Module scope never touches window/document; the element is built with
 * createElement/dataset/style only, never markup injection.
 */

let ringEl = null;

/**
 * Ring diameter for a marker (pure). Circles clear the glyph by 4px a side;
 * other shapes must clear the D-33 halo's corners (bounding side = size + 3).
 * @param {number} size
 * @param {string} [symbol]
 * @returns {number}
 */
export function hoverRingDiameter(size, symbol) {
  if (symbol == null || symbol === 'circle' || symbol === 'circle-open') return size + 8;
  return Math.ceil((size + 3) * Math.SQRT2) + 8;
}

/**
 * Reads the hovered point's marker size/symbol from a Plotly event point
 * (pure; guarded, since these are Plotly event fields).
 * @param {object} [point]
 * @returns {{size: number, symbol: string}}
 */
export function ringSpecFromPoint(point) {
  const fallback = { size: 6, symbol: 'circle' };
  try {
    const marker = point?.fullData?.marker ?? point?.data?.marker;
    if (!marker) return fallback;
    const at = point.pointIndex ?? point.pointNumber;
    const pick = (v) => (Array.isArray(v) ? v[at] : v);
    const size = pick(marker.size);
    const symbol = pick(marker.symbol);
    return {
      size: typeof size === 'number' && Number.isFinite(size) ? size : fallback.size,
      symbol: typeof symbol === 'string' ? symbol : fallback.symbol,
    };
  } catch {
    return fallback;
  }
}

/** Lazily creates the one ring element under <body> (outside Plotly's graph div). */
export function ensureHoverRingEl() {
  if (ringEl) return ringEl;
  ringEl = document.createElement('div');
  ringEl.id = 'chart-hover-ring';
  ringEl.className = 'chart-hover-ring';
  ringEl.setAttribute('aria-hidden', 'true');
  ringEl.hidden = true;
  document.body.appendChild(ringEl);
  return ringEl;
}

/**
 * Centers the ring on a client-pixel point and shows it.
 * @param {{i: number, clientX: number, clientY: number, diameter: number}} spec
 */
export function showHoverRing({ i, clientX, clientY, diameter }) {
  const el = ensureHoverRingEl();
  el.style.width = `${diameter}px`;
  el.style.height = `${diameter}px`;
  el.style.left = `${clientX - diameter / 2}px`;
  el.style.top = `${clientY - diameter / 2}px`;
  el.dataset.index = String(i);
  el.hidden = false;
}

/** Hides the ring; a no-op before first use. */
export function hideHoverRing() {
  if (ringEl) ringEl.hidden = true;
}
