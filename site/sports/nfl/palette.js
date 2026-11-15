/**
 * NFL data-color tokens (UI-SPEC Color). DOM-free: data and pure lookups only.
 * The CFB palette (site/modules/palette.js) is not touched; the network families read their
 * colours from it, so a network looks the same on both pages.
 */
import {
  FAMILY_COLORS, FAMILY_LABELS, MUTED, PAGE_BG, SURFACE, contrastRatio, familyKey, mixHex,
} from '../../modules/palette.js';
import { NO_NETWORK_NAME } from './data.js';

/** How far the no-network neutral sits from the page toward the muted text tone. */
const TBA_WEIGHT = 0.45;

/**
 * Network family labels on the NFL page: the shared ones, except that Fox and CBS carry NFL
 * games on one network each, and a game with no network is its own entry.
 */
export const NFL_FAMILY_LABELS = Object.freeze({
  ...FAMILY_LABELS,
  fox: 'FOX',
  cbs: 'CBS',
  tba: NO_NETWORK_NAME,
});

/** The label of a network family key ('tba' included); unknown keys read as Other. */
export function familyLabel(family) {
  return Object.prototype.hasOwnProperty.call(NFL_FAMILY_LABELS, family)
    ? NFL_FAMILY_LABELS[family]
    : NFL_FAMILY_LABELS.other;
}

/**
 * The colour of a network family on the all-games bars and their chips: the shared family
 * colour, and for a game with no network, which is no network's colour, a pale neutral a clear step
 * lighter than Other's grey (the muted text tone mixed toward the page).
 * @param {string} family
 * @param {'light'|'dark'} theme
 * @returns {string}
 */
export function familyColor(family, theme) {
  const t = theme === 'dark' ? 'dark' : 'light';
  return family === 'tba' ? mixHex(MUTED[t], PAGE_BG[t], TBA_WEIGHT) : FAMILY_COLORS[t][familyKey(family)];
}

/**
 * Segment colors for the eight exclusive stack segments, keyed by the builder's segment
 * names. Each category wears the family colour of the network that carries most of its
 * games, so a category looks like its network on the all-games bars (user 2026-11-15):
 * Sunday night NBC, Monday night ESPN, Fox AGOTW FOX, CBS late national CBS. Thursday
 * night (Prime Video), Other solo slot and International (NFL Network) are all in the
 * Other family, so they take three greys a clear step apart, every one at 3:1 or more on
 * --bg and --surface (e2e: test_segment_colors_reach_3_to_1); a network colour under that
 * is deepened just enough to reach it (familyPair). Holiday games split almost
 * evenly between FOX, CBS and NBC, so Holiday keeps an olive no network uses (user
 * 2026-11-15).
 */
const SEGMENT_MIN_CONTRAST = 3;

/**
 * A network family's colour pair for a category. The light tone is deepened toward black,
 * one step at a time, until it reaches 3:1 on --surface (NBC's #C972A2 measured 2.82); a
 * family that already clears it keeps its own colour.
 */
function familyPair(family) {
  const base = FAMILY_COLORS.light[family];
  let light = base;
  for (let w = 100; w >= 0 && contrastRatio(light, SURFACE.light) < SEGMENT_MIN_CONTRAST; w -= 1) {
    light = mixHex(base, '#000000', w / 100);
  }
  return Object.freeze({ light, dark: FAMILY_COLORS.dark[family] });
}

export const NFL_CATEGORY_COLORS = Object.freeze({
  solo_thursday: Object.freeze({ light: '#444444', dark: '#D2D2D2' }),
  solo_sunday: familyPair('nbc'),
  solo_monday: familyPair('disney'),
  solo_holiday: Object.freeze({ light: '#8A7A00', dark: '#F0E442' }),
  solo_other: Object.freeze({ light: '#888888', dark: '#999999' }),
  agotw: familyPair('fox'),
  cbs_national: familyPair('cbs'),
  international_other: Object.freeze({ light: '#5F5F5F', dark: '#B0B0B0' }),
});

/** Games in no special category (scatter only). */
export const NFL_OTHER_COLOR = Object.freeze({ light: '#888888', dark: '#999999' });

/**
 * Viewership view category -> segment color plus marker symbol. Lines that share a hue
 * (the three holidays, Saturday/Friday/Other) also differ in marker shape and carry their
 * own shade of the family hue (`shade`), so they stay apart. The greys also keep clear of
 * Thursday night's and International's: International is a triangle, and the Other-slot
 * lines take shades and shapes neither of those uses. Every shade reaches 3:1
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
  international: { segment: 'international_other', symbol: 'triangle-up' },
  saturday: { segment: 'solo_other', symbol: 'circle' },
  friday: { segment: 'solo_other', symbol: 'square', shade: { light: '#767676', dark: '#7E7E7E' } },
  other: { segment: 'solo_other', symbol: 'diamond', shade: { light: '#2B2B2B', dark: '#EDEDED' } },
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
