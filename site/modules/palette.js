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
 * Networks named on each family's legend chip (FAMILY_LABELS), as network_ids
 * in chip order. Channel sub-shading gives these the first shades in this
 * order, so the flagship always wears the chip's own color (shade 0) and a
 * channel's shade does not move when counts shift (unrated games made FS1
 * outnumber FOX); every other channel follows by data-wide game count. A
 * change to FAMILY_LABELS must update this list.
 * @type {Readonly<Record<string, readonly string[]>>}
 */
export const FAMILY_CHANNEL_LEAD = Object.freeze({
  disney: Object.freeze(['abc', 'espn']),
  fox: Object.freeze(['fox', 'fs1', 'big-ten-network']),
  cbs: Object.freeze(['cbs', 'cbs-sports-network']),
  nbc: Object.freeze(['nbc', 'peacock']),
  cw: Object.freeze(['cw']),
  wbd: Object.freeze(['tbs', 'tnt']),
  conference: Object.freeze(['pac-12-network', 'mountain-west-network']),
  other: Object.freeze([]),
});

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

/** Outline on enlarged (filter-passing) dots; same in light and dark. */
export const DOT_OUTLINE = '#000000';

/** Result-vs-spread zero line: a step darker than DIVIDER gridlines, lighter than MUTED text (D-02). */
export const ZERO_LINE = { light: '#9CA3AF', dark: '#6B7280' };

/** UI chrome divider/border token per theme. */
export const DIVIDER = { light: '#E2E4E9', dark: '#2A2E35' };

/** UI chrome page background token per theme. */
export const PAGE_BG = { light: '#FFFFFF', dark: '#14161A' };

/** UI chrome secondary-surface token per theme (rail, top bar, panel, table header). */
export const SURFACE = { light: '#F4F5F7', dark: '#1E2126' };

/** The --muted text token per theme (axis ticks and zero lines; not a bar fill). */
export const MUTED = { light: '#4B5563', dark: '#9CA3AF' };

/**
 * Mirrors the `--special` CSS token (the Announcers toolbar button's violet, D-34); the
 * fill for announcer, team, and conference bars (04.4 D-24). A rendered test keeps the
 * two equal.
 */
export const SPECIAL = { light: '#7C3AED', dark: '#A78BFA' };

/**
 * Mixes two `#RRGGBB` colors per channel: `round(w*a + (1-w)*b)`, uppercase.
 * Tone B of a bar is `mixHex(toneA, PAGE_BG, 0.55)` (D-16): light muted gives
 * `#9CA2A9`, dark muted gives `#5F646C`.
 * @param {string} a
 * @param {string} b
 * @param {number} weightA - weight of `a`, 0..1.
 * @returns {string}
 */
export function mixHex(a, b, weightA) {
  const channel = (hex, i) => Number.parseInt(hex.slice(1 + 2 * i, 3 + 2 * i), 16);
  let out = '#';
  for (let i = 0; i < 3; i += 1) {
    const v = Math.round(weightA * channel(a, i) + (1 - weightA) * channel(b, i));
    out += v.toString(16).padStart(2, '0');
  }
  return out.toUpperCase();
}

function luminance(hex) {
  const lin = (c) => {
    const v = c / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  };
  const r = lin(Number.parseInt(hex.slice(1, 3), 16));
  const g = lin(Number.parseInt(hex.slice(3, 5), 16));
  const b = lin(Number.parseInt(hex.slice(5, 7), 16));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/**
 * WCAG contrast ratio between two `#RRGGBB` colors.
 * @param {string} hexA
 * @param {string} hexB
 * @returns {number}
 */
export function contrastRatio(hexA, hexB) {
  const la = luminance(hexA);
  const lb = luminance(hexB);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

/**
 * Text color for a fill: `#000000` or `#FFFFFF`, whichever contrasts more,
 * or null when even the better one is below 4.5:1 (the segment then carries
 * no in-bar text, D-16). Light muted `#4B5563` -> white; its Tone B `#9CA2A9`
 * -> black; dark muted `#9CA3AF` -> black; its Tone B `#5F646C` -> white.
 * @param {string} hex
 * @returns {string|null}
 */
export function readableTextOn(hex) {
  const black = contrastRatio(hex, '#000000');
  const white = contrastRatio(hex, '#FFFFFF');
  const best = black >= white ? '#000000' : '#FFFFFF';
  return Math.max(black, white) >= 4.5 ? best : null;
}

/**
 * Text color that reads at 4.5:1 over every one of `hexes` (a label that spans
 * several channel shades, D-23): black or white, whichever has the higher
 * minimum contrast, or null when even that minimum is under 4.5 or the list
 * is empty.
 * @param {string[]} hexes
 * @returns {string|null}
 */
export function readableTextOnAll(hexes) {
  if (hexes.length === 0) return null;
  const floor = (text) => Math.min(...hexes.map((h) => contrastRatio(h, text)));
  const black = floor('#000000');
  const white = floor('#FFFFFF');
  const best = black >= white ? '#000000' : '#FFFFFF';
  return Math.max(black, white) >= 4.5 ? best : null;
}

const SHADE_LADDER = [
  ['#FFFFFF', 0.6],
  ['#000000', 0.6],
  ['#FFFFFF', 0.35],
  ['#000000', 0.35],
  ['#FFFFFF', 0.8],
  ['#000000', 0.8],
  ['#FFFFFF', 0.2],
  ['#000000', 0.2],
  ['#FFFFFF', 0.5],
  ['#000000', 0.5],
];

/**
 * Channel shades of a family color (D-23): the stacked Announcers chart draws
 * one bar per network family and sub-shades each announcer segment by channel.
 * Shade 0 is the family color itself, so a one-channel family looks unchanged.
 * Further shades walk a fixed lighter/darker ladder of mixes with white or
 * black (`mixHex(base, toward, w)`, w the base weight); a candidate is skipped unless it has at least 1.15:1 contrast with
 * every shade already accepted (this drops the darker steps of a black base).
 * If the ladder runs out, the accepted list repeats cyclically.
 * @param {string} family - a `familyKey` value.
 * @param {'light'|'dark'} theme
 * @param {number} n - how many shades.
 * @returns {string[]}
 */
export function channelShades(family, theme, n) {
  if (n <= 0) return [];
  const base = FAMILY_COLORS[theme][familyKey(family)];
  const accepted = [base];
  for (const [toward, w] of SHADE_LADDER) {
    if (accepted.length >= n) break;
    const candidate = mixHex(base, toward, w);
    if (accepted.every((a) => contrastRatio(a, candidate) >= 1.15)) accepted.push(candidate);
  }
  const out = [];
  for (let i = 0; i < n; i += 1) out.push(accepted[i % accepted.length]);
  return out;
}

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
