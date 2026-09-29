/**
 * Dot-encoding palette and UI chrome color tokens (D-01, UI-SPEC Color).
 *
 * DOM-free: this module holds only data and a pure lookup function, no
 * reference to window/document/Plotly, so it can be imported from node for
 * quick checks or from the browser for the chart itself.
 */

/**
 * Canonical network-family order. Determines legend order and which
 * families are considered "known" (anything else folds into `other`).
 * The eighth Okabe-Ito hue (yellow, low contrast on white) is deliberately
 * never used as a dot color anywhere in FAMILY_COLORS (UI-SPEC Color).
 * @type {string[]}
 */
export const FAMILY_ORDER = [
  'disney',
  'fox',
  'cbs',
  'nbc',
  'cw',
  'wbd',
  'conference',
  'other',
];

/**
 * Legend display label per family key (D-04): the networks in the family,
 * slash-delimited, never the parent company. Label rule: the family's
 * flagship broadcast network first, then its one or two most-carried cable
 * networks, in on-air short brands; the "conference" family (Pac-12
 * Network, Mountain West Network, CUSA Digital) names its two main
 * networks.
 * @type {Record<string, string>}
 */
export const FAMILY_LABELS = {
  disney: 'ABC/ESPN',
  fox: 'FOX/FS1/BTN',
  cbs: 'CBS/CBSSN',
  nbc: 'NBC/Peacock',
  cw: 'The CW',
  wbd: 'TBS/TNT',
  conference: 'Pac-12 Net/MW Net',
  other: 'Other',
};

/**
 * WCAG-AA text color per family, same in both themes (D-04, SITE-26): only
 * `disney` and `conference` clear 4.5:1 with white; every other family
 * clears it with black. Verified against the real sRGB relative-luminance
 * formula for every family/theme fill in FAMILY_COLORS (UI-SPEC Color):
 * disney #0072B2 -> white 5.19:1 (both themes); fox #009E73 -> black
 * 6.14:1 (both); cbs light #BD8300 -> black 6.41:1, dark #E69F00 -> black
 * 9.32:1; nbc light #C972A2 -> black 6.41:1, dark #CC79A7 -> black 6.86:1;
 * cw light #1D96DB -> black 6.44:1, dark #56B4E9 -> black 9.10:1; wbd
 * #D55E00 -> black 5.43:1 (both); conference light #000000 -> white
 * 21.0:1, dark #696969 -> white 5.49:1; other light #8F8F8F -> black
 * 6.49:1, dark #999999 -> black 7.37:1.
 * @type {Record<string, string>}
 */
export const PILL_TEXT_COLOR = {
  disney: '#FFFFFF',
  fox: '#000000',
  cbs: '#000000',
  nbc: '#000000',
  cw: '#000000',
  wbd: '#000000',
  conference: '#FFFFFF',
  other: '#000000',
};

/**
 * Okabe-Ito dot colors per family, per theme. Hue and saturation are held
 * fixed between themes; only lightness differs, so the family-to-hue
 * identity never shifts between builds (D-01).
 * @type {{light: Record<string, string>, dark: Record<string, string>}}
 */
export const FAMILY_COLORS = {
  light: {
    disney: '#0072B2',
    fox: '#009E73',
    cbs: '#BD8300',
    nbc: '#C972A2',
    cw: '#1D96DB',
    wbd: '#D55E00',
    conference: '#000000',
    other: '#8F8F8F',
  },
  dark: {
    disney: '#0072B2',
    fox: '#009E73',
    cbs: '#E69F00',
    nbc: '#CC79A7',
    cw: '#56B4E9',
    wbd: '#D55E00',
    conference: '#696969',
    other: '#999999',
  },
};

/** UI chrome accent token per theme (search focus ring, active states, highlight outline). */
export const ACCENT = { light: '#111827', dark: '#E5E7EB' };

/** UI chrome divider/border token per theme. */
export const DIVIDER = { light: '#E2E4E9', dark: '#2A2E35' };

/** UI chrome page background token per theme. */
export const PAGE_BG = { light: '#FFFFFF', dark: '#14161A' };

/** UI chrome secondary-surface token per theme (rail, top bar, panel, table header). */
export const SURFACE = { light: '#F4F5F7', dark: '#1E2126' };

/**
 * Compare-mode marker symbols, assigned to selected people in selection
 * order (D-07). Named symbols only -- numeric codes misrender in scattergl.
 * @type {string[]}
 */
export const COMPARE_SYMBOLS = ['circle', 'square', 'diamond', 'triangle-up'];

/**
 * Unicode glyphs paired with COMPARE_SYMBOLS, same order, for the shape
 * legend and any text-only rendering.
 * @type {string[]}
 */
export const COMPARE_GLYPHS = ['●', '■', '◆', '▲'];

/** Marker symbol for a game shared by more than one selected person (D-07). */
export const SHARED_SYMBOL = 'star';

/** Unicode glyph paired with SHARED_SYMBOL for the shape legend. */
export const SHARED_GLYPH = '★';

/**
 * Maps a raw network family string to one of FAMILY_ORDER's known keys,
 * folding anything unrecognized into "other" (D-01).
 * @param {string} family - the raw `lookups.networks[].family` value.
 * @returns {string} a key in FAMILY_ORDER.
 */
export function familyKey(family) {
  return FAMILY_ORDER.includes(family) ? family : 'other';
}
