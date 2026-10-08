/**
 * 04.17 D-09/D-14/D-15: fixed axis caps for the Excitement, Total points and
 * Margin measures. A game above its cap is pinned at the cap for plotting only
 * (the true value stays in `data.t`, so tooltips, hover text and the modal
 * keep showing it). The "+" tick (for example "12+") appears only when some
 * game is above the cap (UI-SPEC default 4). Steps are fixed so the cap tick
 * always exists; `niceLinearTicks` would skip it. DOM-free and pure.
 */

/** Excitement cap on both axes (04.17 D-09). A fixed constant, not a percentile. */
export const EXCITEMENT_CAP = 12;

/** Per-measure cap, tick step and axis title for the Y measures (04.17 D-09, D-14, D-15). */
export const Y_MEASURES = Object.freeze({
  excitement: Object.freeze({ cap: EXCITEMENT_CAP, step: 2, title: 'Excitement index (CFBD)' }),
  points: Object.freeze({ cap: 120, step: 20, title: 'Total points (both teams)' }),
  margin: Object.freeze({ cap: 70, step: 10, title: 'Margin of victory (points)' }),
});

/**
 * Plot-only clamp: the cap when `v` is above it, else `v` unchanged
 * (null and undefined pass through).
 * @param {number|null|undefined} v
 * @param {number} cap
 * @returns {number|null|undefined}
 */
export function pin(v, cap) {
  return v != null && v > cap ? cap : v;
}

/**
 * Ticks at the multiples of `step` inside [lo, hi]; the value equal to `cap`
 * reads `${cap}+` when `anyPinned` is true.
 * @param {number} lo
 * @param {number} hi
 * @param {number} step
 * @param {number} cap
 * @param {boolean} anyPinned
 * @returns {{tickvals: number[], ticktext: string[]}}
 */
export function cappedTicks(lo, hi, step, cap, anyPinned) {
  const tickvals = [];
  const first = Math.ceil(lo / step - 1e-9);
  for (let k = first; k * step <= hi + 1e-9; k += 1) tickvals.push(k * step);
  const ticktext = tickvals.map((v) => (anyPinned && v === cap ? `${cap}+` : String(v)));
  return { tickvals, ticktext };
}
