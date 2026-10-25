/**
 * The shared chart frame (SHELL-06, 12-DECISIONS D-08/D-09): one place that supplies the
 * base Plotly layout and config for every chart, so no chart sets its own title, font,
 * modebar, gridlines or outline colour.
 *
 * - Roboto Condensed 12px `--muted` for tick, axis and hover text (axis titles inherit `layout.font`) (12px is the floor on
 *   every viewport); no `layout.title`, no legend box, no modebar.
 * - Horizontal `--rule` hairline gridlines only; no vertical gridlines, no zero line.
 * - Reference lines are dashed and drawn behind the data (`referenceLine`).
 * - Text on data takes a halo in the page background (`haloText`), never a filled box or
 *   a literal white.
 * - `waitForFonts` / `onLateFont` stop tick labels and margins shifting after font swap.
 *
 * DOM-free apart from `document.fonts` inside the two font helpers, and never references
 * `window.Plotly`, so `frameLayout` / `frameConfig` stay importable from node.
 */

import { DIVIDER, INK, MUTED, PAGE_BG, SURFACE, ZERO_LINE } from './palette.js';

/** The `--plot` stack from style.css. */
export const FRAME_FONT = 'Roboto Condensed, Arial, sans-serif';

/** Smallest font size any chart text may use, on every viewport. */
export const FRAME_MIN_FONT_PX = 12;

/** Default wait for the faces before the first draw, in ms (T-13-27: a failed font never blocks). */
export const FONT_WAIT_MS = 1500;

const isPlain = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);

/** Deep-merges `over` onto a copy of `base`; arrays and scalars in `over` replace. */
function merge(base, over) {
  const out = { ...base };
  for (const [key, value] of Object.entries(over ?? {})) {
    out[key] = isPlain(value) && isPlain(out[key]) ? merge(out[key], value) : value;
  }
  return out;
}

/** Raises every `font.size`/`tickfont.size`/`textfont.size` in a layout fragment to the 12px floor. */
function clampFonts(node) {
  if (Array.isArray(node)) {
    for (const item of node) clampFonts(item);
    return node;
  }
  if (!isPlain(node)) return node;
  for (const [key, value] of Object.entries(node)) {
    if ((key === 'font' || key === 'tickfont' || key === 'textfont') && isPlain(value)) {
      if (typeof value.size === 'number' && value.size < FRAME_MIN_FONT_PX) value.size = FRAME_MIN_FONT_PX;
    }
    clampFonts(value);
  }
  return node;
}

/**
 * The text halo: a Plotly `textfont.shadow` ring in the page background colour, so labels
 * read over dots and bands without a filled box. Never a literal white (Color rule).
 * @param {'light'|'dark'} theme
 * @returns {{shadow: string}}
 */
export function haloText(theme) {
  const bg = PAGE_BG[theme];
  return { shadow: `-1px -1px 0 ${bg}, 1px -1px 0 ${bg}, -1px 1px 0 ${bg}, 1px 1px 0 ${bg}` };
}

/**
 * A dashed reference or zero line drawn behind the data.
 * @param {object} line - Plotly shape fields (xref, x0, x1, yref, y0, y1, ...).
 * @param {'light'|'dark'} theme
 * @returns {object}
 */
export function referenceLine(line, theme) {
  return { type: 'line', layer: 'below', ...line, line: { width: 1, color: ZERO_LINE[theme], dash: 'dash' } };
}

/**
 * The base layout merged with a chart's own overrides. Overrides win per key; any font size
 * below 12px is raised to 12.
 * @param {object} overrides - chart-specific layout.
 * @param {{theme: 'light'|'dark'}} env
 * @returns {object} a new layout object.
 */
export function frameLayout(overrides, env) {
  const theme = env.theme;
  const muted = MUTED[theme];
  const tickfont = { family: FRAME_FONT, size: FRAME_MIN_FONT_PX, color: muted };
  const base = {
    font: { family: FRAME_FONT, size: FRAME_MIN_FONT_PX, color: muted },
    paper_bgcolor: PAGE_BG[theme],
    plot_bgcolor: PAGE_BG[theme],
    showlegend: false,
    hoverlabel: {
      font: { family: FRAME_FONT, size: FRAME_MIN_FONT_PX, color: INK[theme] },
      bgcolor: SURFACE[theme],
      bordercolor: DIVIDER[theme],
    },
    xaxis: {
      showline: false,
      mirror: false,
      showgrid: false,
      zeroline: false,
      tickfont,
    },
    yaxis: {
      showline: false,
      mirror: false,
      showgrid: true,
      gridcolor: DIVIDER[theme],
      zeroline: false,
      tickfont,
    },
  };
  const layout = merge(base, overrides);
  delete layout.title;
  return clampFonts(layout);
}

/**
 * The base Plotly config: no modebar anywhere, the page-level Reset zoom replaces it.
 * @param {{zoomable?: boolean, extras?: object}} [opts]
 * @returns {object}
 */
export function frameConfig({ zoomable = false, extras = {} } = {}) {
  return {
    responsive: true,
    displaylogo: false,
    scrollZoom: false,
    showSendToCloud: false,
    showEditInChartStudio: false,
    showLink: false,
    ...extras,
    displayModeBar: false,
    doubleClick: zoomable ? 'reset' : false,
  };
}

/**
 * Resolves when the four faces have loaded, or when `timeoutMs` passes, whichever is first;
 * never rejects, so a failed font cannot block the first draw.
 * @param {number} [timeoutMs]
 * @returns {Promise<boolean>} true when every face loaded in time, false on timeout or error.
 */
export async function waitForFonts(timeoutMs = FONT_WAIT_MS) {
  const fonts = typeof document !== 'undefined' ? document.fonts : null;
  if (!fonts || typeof fonts.load !== 'function') return true;
  let timer = null;
  const timeout = new Promise((resolve) => {
    timer = setTimeout(() => resolve(false), timeoutMs);
  });
  const loaded = Promise.all([
    fonts.load('12px "Roboto Condensed"'),
    fonts.load('14px "Roboto"'),
    fonts.load('600 14px "Roboto"'),
    fonts.load('600 20px "Crimson Text"'),
  ]).then(
    () => true,
    () => false,
  );
  const ok = await Promise.race([loaded, timeout]);
  clearTimeout(timer);
  return ok;
}

/**
 * Calls `callback` once on the next `loadingdone` (a font that arrived after the first draw)
 * and then removes the listener.
 * @param {() => void} callback
 */
export function onLateFont(callback) {
  const fonts = typeof document !== 'undefined' ? document.fonts : null;
  if (!fonts || typeof fonts.addEventListener !== 'function') return;
  const handler = () => {
    fonts.removeEventListener('loadingdone', handler);
    callback();
  };
  fonts.addEventListener('loadingdone', handler);
}
