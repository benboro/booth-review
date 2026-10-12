/**
 * NFL data-color tokens (UI-SPEC Color). DOM-free: data and pure lookups only.
 * The CFB palette (site/modules/palette.js) is not touched.
 */

/** Exclusive-category colors, keyed by the builder's category names. */
export const NFL_CATEGORY_COLORS = Object.freeze({
  standalone: Object.freeze({ light: '#0072B2', dark: '#0072B2' }),
  agotw: Object.freeze({ light: '#D55E00', dark: '#D55E00' }),
  cbs_national: Object.freeze({ light: '#BD8300', dark: '#E69F00' }),
  international_other: Object.freeze({ light: '#C972A2', dark: '#CC79A7' }),
});

/** Games in no special category (scatter only). */
export const NFL_OTHER_COLOR = Object.freeze({ light: '#8F8F8F', dark: '#999999' });

/** AGOTW crew styles by order of first appearance; the fifth repeats. */
export const NFL_CREW_STYLES = Object.freeze([
  Object.freeze({ light: '#0072B2', dark: '#0072B2', symbol: 'circle' }),
  Object.freeze({ light: '#D55E00', dark: '#D55E00', symbol: 'square' }),
  Object.freeze({ light: '#009E73', dark: '#009E73', symbol: 'diamond' }),
  Object.freeze({ light: '#C972A2', dark: '#CC79A7', symbol: 'triangle-up' }),
  Object.freeze({ light: '#BD8300', dark: '#E69F00', symbol: 'star' }),
]);

/**
 * Hex color for an exclusive category key ('none' or unknown gives the grey).
 * @param {string} key
 * @param {'light'|'dark'} theme
 * @returns {string}
 */
export function categoryColor(key, theme) {
  const t = theme === 'dark' ? 'dark' : 'light';
  const entry = Object.prototype.hasOwnProperty.call(NFL_CATEGORY_COLORS, key)
    ? NFL_CATEGORY_COLORS[key]
    : NFL_OTHER_COLOR;
  return entry[t];
}

/**
 * Color and marker for the crew at `order` (0-based, first appearance).
 * @param {number} order
 * @param {'light'|'dark'} theme
 * @returns {{color: string, symbol: string}}
 */
export function crewStyle(order, theme) {
  const t = theme === 'dark' ? 'dark' : 'light';
  const k = Math.max(0, Math.min(NFL_CREW_STYLES.length - 1, Math.trunc(order) || 0));
  const s = NFL_CREW_STYLES[k];
  return { color: s[t], symbol: s.symbol };
}
