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
 * WCAG-AA text color per family and theme (D-04, D-08, SITE-26). Light: only `disney` and
 * `conference` clear 4.5:1 with white; every other family clears it with black (disney
 * #0072B2 -> white 5.19:1; conference #000000 -> white 21.0:1). Dark: the brighter disney
 * #0A7BC0 takes white (4.56:1) and every other family takes black, including conference
 * #E4DFD6 (15.82:1).
 * @type {{light: Record<string, string>, dark: Record<string, string>}}
 */
export const PILL_TEXT_COLOR = {
  light: {
    disney: '#FFFFFF',
    fox: '#000000',
    cbs: '#000000',
    nbc: '#000000',
    cw: '#000000',
    wbd: '#000000',
    conference: '#FFFFFF',
    other: '#000000',
  },
  dark: {
    disney: '#FFFFFF',
    fox: '#000000',
    cbs: '#000000',
    nbc: '#000000',
    cw: '#000000',
    wbd: '#000000',
    conference: '#000000',
    other: '#000000',
  },
};

/**
 * Okabe-Ito dot colors per family, per theme. Hue and saturation are held
 * fixed between themes; only lightness differs, so the family-to-hue
 * identity never shifts between builds (D-01).
 * @type {{light: Record<string, string>, dark: Record<string, string>}}
 */
export const FAMILY_COLORS = {
  // Light FOX and CBS are the map-family values (Phase 26 panel F4): 3:1 or more on SURFACE.light.
  light: {
    disney: '#0072B2',
    fox: '#009970',
    cbs: '#B37C00',
    nbc: '#C972A2',
    cw: '#1D96DB',
    wbd: '#D55E00',
    conference: '#000000',
    other: '#8B8B8B',
  },
  dark: {
    disney: '#0A7BC0',
    fox: '#009E73',
    cbs: '#E69F00',
    nbc: '#CC79A7',
    cw: '#56B4E9',
    wbd: '#D55E00',
    conference: '#E4DFD6',
    other: '#9C958A',
  },
};

/** UI chrome accent token per theme (search focus ring, active states, highlight outline). */
export const ACCENT = { light: '#1E2321', dark: '#E5EAE8' };

/** The --ink text token per theme: neutral marks and unmatched bar fills (D-04). */
export const INK = { light: '#1E2321', dark: '#E5EAE8' };

/** Outline on enlarged (filter-passing) dots: black on light, ink on dark so it stays visible (D-08). */
export const DOT_OUTLINE = { light: '#000000', dark: '#E5EAE8' };

/** Result-vs-spread zero line: a step darker than DIVIDER gridlines, lighter than MUTED text (D-02). */
export const ZERO_LINE = { light: '#C0C9C5', dark: '#56605C' };

/** UI chrome divider/border token per theme. */
export const DIVIDER = { light: '#DAE0DD', dark: '#333A38' };

/**
 * Faint gold/brown tint behind each season's bowl and playoff span on the Date axis
 * (04.17 D-07). Light alpha 0.05 (was 0.07 before the green-gray ground) keeps CBS and Other
 * at 3:1 or more on the band over PAGE_BG (#F5F7F6; CBS 3.06:1, Other 3.01:1). Dark alpha 0.06
 * (was 0.07) keeps every dark family at 3:1 or more on the band over SURFACE (the "No public
 * rating" strip, #212625; Disney 3.05:1) and over PAGE_BG (#191D1C; Disney 3.39:1).
 */
export const POSTSEASON_BAND = { light: 'rgba(166, 120, 40, 0.05)', dark: 'rgba(212, 160, 60, 0.06)' };

/**
 * "Bowls & CFP" label text: a darker tint of the band hue on light, a lighter one on dark
 * (04.17 D-08, amended). 7.3:1 on the blended light plot, 8.8:1 on the blended dark plot.
 */
export const POSTSEASON_LABEL = { light: '#6E4A10', dark: '#E8BE6E' };

/** UI chrome page background token per theme. */
export const PAGE_BG = { light: '#F5F7F6', dark: '#191D1C' };

/** UI chrome secondary-surface token per theme (rail, top bar, panel, table header). */
export const SURFACE = { light: '#EBEFED', dark: '#212625' };

/** The --muted text token per theme (axis ticks and zero lines; not a bar fill). */
export const MUTED = { light: '#5A6460', dark: '#9EA8A4' };

/**
 * Map land fill per theme (04.18 D-08, UI-SPEC "Color"): barely off the page background so
 * the states read as a faint base. DEFAULTED pending the user's close-out sign-off.
 */
export const MAP_LAND = { light: '#E8EDEA', dark: '#242A28' };

/**
 * Map state outline per theme (04.18 D-08, UI-SPEC "Color"): muted, one step darker than
 * the land on light and lighter on dark. DEFAULTED pending the user's close-out sign-off.
 */
export const MAP_OUTLINE = { light: '#BCC6C2', dark: '#46504D' };

/** Edge-marker label text (04.18 D-15): the muted token, aliased so the Map can tune it alone. */
export const MAP_MARKER_LABEL = MUTED;

/**
 * Map mark opacity tiers (04.18 D-10/D-12/D-13, UI-SPEC "Mark tiers"). DEFAULTED pending
 * the user's close-out sign-off.
 */
export const MAP_OPACITY = Object.freeze({
  base: 0.6,
  other: 0.45,
  subject: 0.85,
  faded: 0.15,
  leg: 0.55,
  marker: 0.6,
});

/**
 * Dark map opacity (Phase 17 review F13): at the light 0.55 leg and 0.85 subject tiers the dark
 * family colours composited over MAP_LAND.dark fall to 1.85:1 (Disney leg). Dark draws selected
 * legs and subject dots at 0.95, which holds every dark map family, and every venue mix toward
 * MAP_DOT_NEUTRAL, at 3.08:1 or more on the land. The base, other and faded tiers stay faint
 * context on purpose.
 */
export const MAP_OPACITY_DARK = Object.freeze({ ...MAP_OPACITY, leg: 0.95, subject: 0.95 });

/**
 * Map mark opacity tiers for a theme.
 * @param {'light'|'dark'} theme
 * @returns {Readonly<Record<string, number>>}
 */
export function mapOpacity(theme) {
  return theme === 'dark' ? MAP_OPACITY_DARK : MAP_OPACITY;
}

/**
 * Map mark sizes in px (04.18 D-05/D-10, UI-SPEC "Mark tiers"). Venue dots of every shape take
 * their size from venueDotSize (Phase 17.1 D-23), so no per-shape size lives here.
 */
export const MAP_SIZE = Object.freeze({
  base: 7,
  other: 7,
  faded: 7,
  marker: 9,
});

/** Non-text mark contrast every map family colour holds against the land (Phase 24 UI-SPEC). */
const MAP_MARK_MIN_CONTRAST = 3.0;

/**
 * Each family colour mixed toward black, in 1% steps, until it holds `MAP_MARK_MIN_CONTRAST`
 * against `land`; a colour that already passes comes back unchanged (hue identity is kept, only
 * lightness drops). Phase 24: the weekend map's dots must clear 3:1 on the land.
 * @param {Record<string, string>} colors
 * @param {string} land
 * @returns {Record<string, string>}
 */
function deepenFamilies(colors, land) {
  const out = {};
  for (const [family, hex] of Object.entries(colors)) {
    let tone = hex;
    for (let w = 100; w >= 0 && contrastRatio(tone, land) < MAP_MARK_MIN_CONTRAST; w -= 1) {
      tone = mixHex(hex, '#000000', w / 100);
    }
    out[family] = tone;
  }
  return out;
}

/**
 * Map-only family colors (Phase 11 D-12): the same hues as FAMILY_COLORS except
 * `conference`, which is a violet so Pac-12 Net / MW Net would not smudge the splat in pure black.
 * @type {{light: Record<string, string>, dark: Record<string, string>}}
 */
export const MAP_FAMILY_COLORS = {
  light: Object.freeze(
    deepenFamilies({ ...FAMILY_COLORS.light, conference: '#6A5BA0' }, MAP_LAND.light),
  ),
  dark: Object.freeze(deepenFamilies({ ...FAMILY_COLORS.dark, conference: '#9A8CD0' }, MAP_LAND.dark)),
};

/** Warm neutral a venue dot fades toward as its games split evenly (Phase 11 D-01a). */
export const MAP_DOT_NEUTRAL = { light: '#B3AA9C', dark: '#8B8377' };

/** Splat and venue-score tuning (Phase 11 D-06a/D-07/D-12). */
export const MAP_SPLAT = Object.freeze({
  style: 'smooth',
  cell: Object.freeze({ desktop: 3, phone: 4 }),
  spread: 25,
  solidPercentile: 80,
  marginExp: 0.7,
  reachExp: 0.3,
  reachMin: 0.35,
  reachMax: 2.5,
  ownBoost: 4,
  coreMax: 7,
  viewersWeight: 0.35,
  unratedPercentile: 10,
  unratedFallback: 150000,
  densK: 1.6,
  coverExp: 0.85,
  maxAlpha: 0.88,
  dotMarginExp: 0.7,
});

/**
 * Venue dot sizes (px) and ring widths (Phase 11 D-12, Phase 17.1 D-02/D-16/D-20). Diameters are
 * in px and dot area is exactly proportional to games. `hitDiameter` is the smallest
 * hover and click target.
 */
export const MAP_VENUE_DOT = Object.freeze({
  maxDiameter: 20,
  phoneMaxDiameter: 10,
  hitDiameter: 12,
  opacity: 1,
  ringWidth: 1,
  hoverRingWidth: 2,
  selectedRingWidth: 2,
  selectedRingGap: 2,
  fadedSize: 6,
});

/** Map line widths in px (04.18 D-08/D-13/D-15, UI-SPEC "Mark tiers"). */
export const MAP_LINE_WIDTH = Object.freeze({
  outline: 0.6,
  leg: 1.25,
  marker: 1.5,
  subjectOutline: 1,
  dotKeyline: 1.5,
});

/**
 * Weekend map dot tuning (Phase 24 UI-SPEC "Window shape"): optical bounding size in px per
 * Plotly symbol so the five marks carry equal visual weight, the invisible hit size, and the
 * ring offsets (keyline and ink rings sit above matched dots, the hover ring is the half-weight
 * 1px ring).
 */
export const WEEKEND_MAP_DOT = Object.freeze({
  desktop: Object.freeze({ circle: 12, square: 10, diamond: 14, 'triangle-up': 13, 'circle-open': 12 }),
  phone: Object.freeze({ circle: 10, square: 8, diamond: 12, 'triangle-up': 11, 'circle-open': 10 }),
  hitDiameter: MAP_VENUE_DOT.hitDiameter,
  keyline: 1.5,
  tbaStroke: 2,
  keylineRing: Object.freeze({ offset: 6, width: 3 }),
  inkRing: Object.freeze({ offset: 10, width: 2 }),
  hoverRing: Object.freeze({ offset: 8, width: 1 }),
});

/**
 * Splat overrides for the weekend map (Phase 24 D-02): one game weighs 1 (no viewers), and the
 * shading stays light because the dots are the data. 24-11 tunes `spread`, `solidPercentile`
 * and `maxAlpha` in the critique renders, `maxAlpha` only within 0.3 to 0.5.
 */
export const MAP_SPLAT_WEEKEND = Object.freeze({
  viewersWeight: 0,
  maxAlpha: 0.4,
  spread: 25,
  solidPercentile: 80,
});


/**
 * The matched-state accent (D-04), mirroring the `--accent` CSS token. Unmatched marks read
 * INK; this colour is for a mark only while a pick matches it.
 */
export const SPECIAL = { light: '#1B4F5C', dark: '#68BACB' };

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

/** Dark only: a channel shade must clear this contrast on the dark page (D-08). */
const DARK_SHADE_MIN = 3.1;

/**
 * Dark only (Phase 17 review F6): the 3.1 floor drops the darker ladder steps, leaving 5-6
 * shades, so a 7th channel repeated an earlier shade. After the ladder, dark scans finer mixes
 * toward white then black, base weight 0.2 to 0.975 in 1/40 steps (lightest first; never paler
 * than the ladder's own 0.2 step, so the hue stays), accepting a candidate at a DARK_EXTRA_GAP
 * contrast with every accepted shade. Every family then has at least its light shade count.
 */
const DARK_EXTRA_GAP = 1.1;
const DARK_EXTRA_LADDER = Array.from({ length: 32 }, (_, k) => (k + 8) / 40)
  .flatMap((w) => [['#FFFFFF', w], ['#000000', w]]);

/**
 * Channel shades of a family color (D-23): the stacked Announcers chart draws
 * one bar per network family and sub-shades each announcer segment by channel.
 * Shade 0 is the family color itself, so a one-channel family looks unchanged.
 * Further shades walk a fixed lighter/darker ladder of mixes with white or
 * black (`mixHex(base, toward, w)`, w the base weight); a candidate is skipped unless it has at least 1.15:1 contrast with
 * every shade already accepted (and, in dark, DARK_SHADE_MIN on the page) (this drops the darker steps of a black base).
 * Dark then continues with DARK_EXTRA_LADDER at the DARK_EXTRA_GAP gap. If the ladder runs out,
 * the accepted list repeats cyclically.
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
    if (theme === 'dark' && contrastRatio(candidate, PAGE_BG.dark) < DARK_SHADE_MIN) continue;
    if (accepted.every((a) => contrastRatio(a, candidate) >= 1.15)) accepted.push(candidate);
  }
  if (theme === 'dark') {
    for (const [toward, w] of DARK_EXTRA_LADDER) {
      if (accepted.length >= n) break;
      const candidate = mixHex(base, toward, w);
      if (contrastRatio(candidate, PAGE_BG.dark) < DARK_SHADE_MIN) continue;
      if (accepted.every((a) => contrastRatio(a, candidate) >= DARK_EXTRA_GAP)) accepted.push(candidate);
    }
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

const srgbToLinear = (c) => {
  const v = c / 255;
  return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
};
const linearToSrgb = (c) => {
  const v = c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055;
  return Math.round(255 * Math.min(1, Math.max(0, v)));
};

/**
 * `#RRGGBB` to OKLab `[L, a, b]`.
 * @param {string} hex
 * @returns {number[]}
 */
export function hexToOklab(hex) {
  const r = srgbToLinear(Number.parseInt(hex.slice(1, 3), 16));
  const g = srgbToLinear(Number.parseInt(hex.slice(3, 5), 16));
  const b = srgbToLinear(Number.parseInt(hex.slice(5, 7), 16));
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  return [
    0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s,
  ];
}

/**
 * OKLab `[L, a, b]` to uppercase `#RRGGBB`, channels clamped to 0..255.
 * @param {number[]} lab
 * @returns {string}
 */
export function oklabToHex([L, A, B]) {
  const l = (L + 0.3963377774 * A + 0.2158037573 * B) ** 3;
  const m = (L - 0.1055613458 * A - 0.0638541728 * B) ** 3;
  const s = (L - 0.0894841775 * A - 1.291485548 * B) ** 3;
  const rgb = [
    4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
  ];
  return `#${rgb.map((c) => linearToSrgb(c).toString(16).padStart(2, '0')).join('')}`.toUpperCase();
}

/**
 * Mixes two `#RRGGBB` colors linearly in OKLab: `t` 0 gives `fromHex`, 1 gives `toHex`.
 * @param {string} fromHex
 * @param {string} toHex
 * @param {number} t - clamped to 0..1.
 * @returns {string}
 */
export function mixOklab(fromHex, toHex, t) {
  const k = Math.min(1, Math.max(0, t));
  const a = hexToOklab(fromHex);
  const b = hexToOklab(toHex);
  return oklabToHex(a.map((c, i) => c + (b[i] - c) * k));
}
