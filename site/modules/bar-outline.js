/**
 * Bar outline: one fixed, pointer-transparent DOM box drawn around the hovered
 * (or first-tapped) bar segment's whole group, like the scatter hover ring
 * (04.13 notes-2 #4).
 *
 * It is a DOM overlay, not a Plotly trace or marker.line: showing it costs a few
 * style writes (no restyle/relayout, so the trace count stays constant and
 * nothing shifts). Module scope never touches window/document; the element is
 * built with createElement/dataset/style only, never markup injection
 * (T-04.4-17), and no text from data reaches it (T-04.13-54).
 */

let outlineEl = null;

/** Extra px between the drawn bar and the outline's edge. */
const PAD = 2;

/**
 * The [start, end] count span a `{r, s, side}` reference covers on its side's axis (pure).
 * Simple bars (s = -1 or no segments) span [0, total]; a stacked segment spans the
 * counts before it to those plus its own.
 * @param {object[]} rows
 * @param {{r: number, s: number, side?: number|null}} ref
 * @returns {[number, number]}
 */
export function segmentSpan(rows, ref) {
  const row = rows[ref.r];
  if (!row) return [0, 0];
  const src = ref.side != null && ref.side >= 0 && row.sides ? row.sides[ref.side] : row;
  const segments = src.segments ?? [];
  if (ref.s < 0 || segments.length === 0 || !segments[ref.s]) return [0, src.total ?? 0];
  let before = 0;
  for (let k = 0; k < ref.s; k += 1) before += segments[k].count;
  return [before, before + segments[ref.s].count];
}

/** Lazily creates the one outline element under <body> (outside Plotly's graph div). */
export function ensureBarOutlineEl() {
  if (outlineEl) return outlineEl;
  outlineEl = document.createElement('div');
  outlineEl.id = 'bars-hover-outline';
  outlineEl.className = 'bars-hover-outline';
  outlineEl.setAttribute('aria-hidden', 'true');
  outlineEl.hidden = true;
  document.body.appendChild(outlineEl);
  return outlineEl;
}

/**
 * Outlines the referenced segment's group. `rows` must be the drawn
 * `lastShownRows` order, and the fixed positioning relies on `clearHover`
 * running on scroll and resize.
 * @param {HTMLElement} gd the Plotly graph div
 * @param {object[]} rows the drawn model rows (same order as the y categories)
 * @param {{r: number, s: number, side?: number|null}} ref
 */
export function showBarOutline(gd, rows, ref) {
  const full = gd?._fullLayout;
  if (!full || !rows.length) return;
  const xa = ref.side === 1 ? full.xaxis2 : full.xaxis;
  const ya = full.yaxis;
  if (!xa || !ya) return;
  const [from, to] = segmentSpan(rows, ref);
  const box = gd.getBoundingClientRect();
  const x1 = box.left + xa._offset + xa.l2p(from);
  const x2 = box.left + xa._offset + xa.l2p(to);
  const yc = box.top + ya._offset + ya.l2p(ref.r);
  const thick = (ya._length / rows.length) * (1 - (full.bargap ?? 0));
  const left = Math.min(x1, x2) - PAD;
  const width = Math.abs(x2 - x1) + 2 * PAD;
  const top = yc - thick / 2 - PAD;
  const height = thick + 2 * PAD;
  if (![left, width, top, height].every(Number.isFinite)) return;
  const el = ensureBarOutlineEl();
  el.style.left = `${left}px`;
  el.style.top = `${top}px`;
  el.style.width = `${width}px`;
  el.style.height = `${height}px`;
  el.hidden = false;
}

/** Hides the outline; a no-op before first use. */
export function hideBarOutline() {
  if (outlineEl) outlineEl.hidden = true;
}
