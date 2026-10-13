/**
 * NFL data-color tokens (UI-SPEC Color). DOM-free: data and pure lookups only.
 * The CFB palette (site/modules/palette.js) is not touched.
 */

/**
 * Segment colors for the eight exclusive stack segments, keyed by the builder's
 * segment names. The hues are positional Okabe-Ito picks and imply no CFB network
 * family. Sunday night (from #1D96DB) and the greys (from #8F8F8F) are darkened in
 * the light theme because they measured 2.99 and 2.96 against --surface, under the
 * 3:1 check (NFL-only style, D-18).
 */
export const NFL_CATEGORY_COLORS = Object.freeze({
  solo_thursday: Object.freeze({ light: '#0072B2', dark: '#0072B2' }),
  solo_sunday: Object.freeze({ light: '#1C94D8', dark: '#56B4E9' }),
  solo_monday: Object.freeze({ light: '#009E73', dark: '#009E73' }),
  solo_holiday: Object.freeze({ light: '#8A7A00', dark: '#F0E442' }),
  solo_other: Object.freeze({ light: '#8C8C8C', dark: '#999999' }),
  agotw: Object.freeze({ light: '#D55E00', dark: '#D55E00' }),
  cbs_national: Object.freeze({ light: '#BD8300', dark: '#E69F00' }),
  international_other: Object.freeze({ light: '#C972A2', dark: '#CC79A7' }),
});

/** Games in no special category (scatter only). */
export const NFL_OTHER_COLOR = Object.freeze({ light: '#8C8C8C', dark: '#999999' });

/**
 * Viewership view category -> segment color plus marker symbol. Lines that share a hue
 * (the three holidays, Saturday/Friday/Other) also differ in marker shape and carry their
 * own shade of the family hue (`shade`), so they stay apart. Every shade reaches 3:1
 * against --bg and --surface in both themes (e2e: test_view_category_colors_reach_3_to_1).
 * Dashes stay reserved for window-level lines.
 */
export const VIEW_CATEGORY_STYLE = Object.freeze({
  agotw: { segment: 'agotw', symbol: 'circle' },
  cbs_national: { segment: 'cbs_national', symbol: 'circle' },
  snf: { segment: 'solo_sunday', symbol: 'circle' },
  mnf: { segment: 'solo_monday', symbol: 'circle' },
  tnf: { segment: 'solo_thursday', symbol: 'circle' },
  thanksgiving: { segment: 'solo_holiday', symbol: 'circle' },
  christmas: { segment: 'solo_holiday', symbol: 'square', shade: { light: '#6B5F00', dark: '#C9BD1F' } },
  black_friday: { segment: 'solo_holiday', symbol: 'diamond', shade: { light: '#9A8800', dark: '#FFF59A' } },
  international: { segment: 'international_other', symbol: 'circle' },
  saturday: { segment: 'solo_other', symbol: 'circle', shade: { light: '#5F5F5F', dark: '#8A8A8A' } },
  friday: { segment: 'solo_other', symbol: 'square', shade: { light: '#8C8C8C', dark: '#B0B0B0' } },
  other: { segment: 'solo_other', symbol: 'diamond', shade: { light: '#444444', dark: '#D2D2D2' } },
});

/**
 * Color and marker for a view category id.
 * @param {string} id
 * @param {'light'|'dark'} theme
 * @returns {{color: string, symbol: string}}
 */
export function viewCategoryStyle(id, theme) {
  const st = Object.prototype.hasOwnProperty.call(VIEW_CATEGORY_STYLE, id)
    ? VIEW_CATEGORY_STYLE[id]
    : { segment: 'none', symbol: 'circle' };
  const t = theme === 'dark' ? 'dark' : 'light';
  return { color: st.shade ? st.shade[t] : categoryColor(st.segment, theme), symbol: st.symbol };
}

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
