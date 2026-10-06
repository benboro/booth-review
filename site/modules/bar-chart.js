/**
 * Plotly figures for the Bars and Butterfly tabs (SITE-34, SITE-35). The
 * builders are pure and DOM-free; `window.Plotly` is referenced only inside
 * `renderBars` and `bindBarEvents`.
 *
 * D-01: every number is a count of rated telecasts; nothing here reads or
 * draws a per-telecast audience figure. D-06: butterfly stacked rows use the
 * same rank-layer trace builder as Bars, per side. D-15: row labels are plain
 * 14/400 annotations; the bar fill carries a network row's family color.
 * D-16: Tone A / Tone B alternation (violet for non-network rows, D-24), page-background separators (D-28: 3px desktop, 2px phone), in-bar
 * text only where it fits (uniformtext hide) and reads at 4.5:1. D-18: every
 * labelled row with a drill target is a clickable annotation and every point
 * carries customdata `{r, s, side}`. D-20: phones put each label on its own
 * line above its bar(s); desktop butterflies use a center spine built with
 * two x-axis domains (04.4-01 spine spike).
 *
 * D-23 (supersedes D-15 for the stacked Announcers view): one bar per network
 * family whose announcer segments are sub-shaded by channel. A trace stack
 * cannot nest two segmentations, so every stacked bar (family or plain) is three
 * layers (04.13 notes-2 #2, #4; review WR-02):
 *   1. pieces on the base axis (`x`, `x2`): per row, segment by segment, each
 *      segment's rated channel pieces then its unrated channel pieces, so one
 *      segment is one contiguous run, never scattered across the bar;
 *   2. one transparent overlay per segment rank on an overlaying axis (`x3`,
 *      `x4`): the page-background separator between segments, plus the only
 *      customdata `{r, s, side}`, so hover and click resolve to the segment;
 *   3. part-text traces on a second overlaying axis (`x5`, `x6`): two per segment
 *      rank (rated part, unrated part); the label goes on the wider part (ties to
 *      rated) in a color readable on that part, so a mostly unrated segment keeps
 *      its label.
 * Pieces and text use hoverinfo 'skip'. Every piece carries a 1.5px border in its
 * own tone (rated: same color as its fill; unrated: 25% fill), except a
 * zero-width piece, which gets border width 0 so it never paints a sliver.
 *
 * D-29 (supersedes the UI-SPEC's "total count not drawn outside"): every
 * stacked row shows its total just past the bar's outer end, as an annotation
 * built only from the integer count (T-04.4-45). D-31 (refines D-24): a simple
 * announcer bar takes its main network family's color.
 *
 * D-15 (04.13): every bar has a solid rated part next to the axis (Butterfly:
 * toward the spine) and an unrated part after it in the same hue at 25% fill
 * with a 1.5px full-hue border; the rated part has the same 1.5px border in its
 * own color so both parts look equally thick (notes-2 #2). Every piece is always
 * emitted (zero-length when there are none) so the trace count never depends on
 * the data's rating split. Every value is a count of games, never a viewer
 * figure.
 *
 * Name safety (T-04.4-13): every name goes through `escapeHover` before it
 * enters a Plotly string.
 */

import {
  ACCENT,
  DIVIDER,
  FAMILY_COLORS,
  MUTED,
  PAGE_BG,
  SPECIAL,
  channelShades,
  familyKey,
  mixHex,
  readableTextOnAll,
} from './palette.js';
import { escapeHover, niceLinearTicks } from './format.js';
import { segmentText } from './bar-copy.js';

const FONT_FAMILY =
  'system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji"';

const LABEL_MAX = 30;
const SPINE_LABEL_MAX = 22;
// Pixel caps beside the character caps: a wide font can make a label within its
// character cap too wide for the margin or spine gap it has to fit in.
const LABEL_MAX_PX = 224;
const SPINE_LABEL_MAX_PX = 200;
// Fallback width per character at 14px, used only when there is no DOM to
// measure in. The page's font is never assumed: `textWidth` measures it.
const CHAR_PX = 7.6;
const CHART_FONT_SIZE = 14;
const MARGIN_T = 32;
const MARGIN_B = 40;
const DESKTOP_PITCH = 32;
const DESKTOP_BARGAP = 0.25;
const PHONE_BARS_PITCH = 44;
// 22px bars: with an ~18px label line above, 28px bars would overlap the row
// above's bar at the 44px pitch (04.4-04 deviation from the UI-SPEC's 28).
const PHONE_BARS_THICKNESS = 22;
const PHONE_FLY_PITCH = 64;
const PHONE_FLY_THICKNESS = 32;
// D-28: a page-background stroke centered on each segment edge leaves a gap as
// wide as the stroke; channel pieces inside one announcer keep line width 0 so
// they stay flush. Supersedes D-16's 1px separators.
const SEGMENT_GAP = { desktop: 3, phone: 2 };
const LABEL_LINE = 18;
const LABEL_GAP = 2;

const CONFIG = {
  responsive: true,
  displayModeBar: false,
  displaylogo: false,
  scrollZoom: false,
  showLink: false,
  showSendToCloud: false,
  showEditInChartStudio: false,
};

function truncate(text, max) {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

/** The page's own font family (the chart text must match what is measured). */
function chartFontFamily() {
  if (typeof document === 'undefined' || !document.body) return FONT_FAMILY;
  return getComputedStyle(document.body).fontFamily || FONT_FAMILY;
}

let measureCtx = null;
const measureCache = new Map();

/**
 * Rendered width in px of `text` in the page's font, by canvas `measureText`
 * with the body's computed family and letter-spacing, so the same call is right
 * under any system font. Falls back to `CHAR_PX` per character (scaled by size)
 * when there is no DOM or canvas.
 * @param {string} text
 * @param {{size?: number, weight?: number}} [opts]
 * @returns {number}
 */
export function textWidth(text, { size = CHART_FONT_SIZE, weight = 400 } = {}) {
  const str = String(text);
  const fallback = CHAR_PX * (size / CHART_FONT_SIZE) * str.length;
  if (typeof document === 'undefined' || !document.body) return fallback;
  if (measureCtx === null) measureCtx = document.createElement('canvas').getContext('2d');
  if (measureCtx == null) return fallback;
  const cs = getComputedStyle(document.body);
  const spacing = Number.parseFloat(cs.letterSpacing) || 0;
  const font = `${weight} ${size}px ${cs.fontFamily || FONT_FAMILY}`;
  const key = `${font}|${spacing}|${str}`;
  let width = measureCache.get(key);
  if (width === undefined) {
    measureCtx.font = font;
    width = measureCtx.measureText(str).width + spacing * str.length;
    if (measureCache.size > 2000) measureCache.clear();
    measureCache.set(key, width);
  }
  return width;
}

/**
 * `truncate` that also keeps the text within `maxPx` as rendered.
 * @param {string} text
 * @param {number} maxChars
 * @param {number} maxPx
 * @param {{size?: number, weight?: number}} [opts]
 * @returns {string}
 */
function truncateFit(text, maxChars, maxPx, opts) {
  let n = Math.min(text.length, maxChars);
  const candidate = (len) => (len < text.length ? `${text.slice(0, len - 1)}…` : text);
  while (n > 1 && textWidth(candidate(n), opts) > maxPx) n -= 1;
  return candidate(n);
}

/** Width in px of the widest of `labels`. */
function widest(labels, opts) {
  return labels.reduce((m, l) => Math.max(m, textWidth(l, opts)), 0);
}

/**
 * Tone A / Tone B fills for a row (D-16): a network row uses its family
 * color, an announcer row its main family color (D-31), every other row the
 * violet special-filter pair (D-24, superseding D-16's neutral ink tone).
 * @param {{family: string|null, mainFamily?: string|null}} row
 * @param {'light'|'dark'} theme
 * @returns {{a: string, b: string}}
 */
export function barTones(row, theme) {
  const family = row.family ?? row.mainFamily ?? null;
  const base = family != null ? FAMILY_COLORS[theme][familyKey(family)] : SPECIAL[theme];
  return { a: base, b: mixHex(base, PAGE_BG[theme], 0.55) };
}

/**
 * The x-axis maximum for a count (D-29): the padding factor, or more when the
 * total's text (measured in the page font, plus a 4px offset and margin) would
 * not fit in the `lengthPx` of axis past the longest bar.
 * @param {number} max
 * @param {number} lengthPx - drawn length of the axis.
 * @param {number} factor
 * @returns {number}
 */
export function rangeTop(max, lengthPx, factor) {
  const peak = Math.max(max, 1);
  const reserve = Math.ceil(textWidth(String(peak))) + 8;
  const length = Math.max(lengthPx, reserve * 2);
  return peak * Math.max(factor, length / (length - reserve));
}

/**
 * Total annotations (D-29): one per row whose total is above zero, just past
 * the bar's outer end. Text is `String()` of an integer count, never a name
 * (T-04.4-45); `captureevents: false` keeps them out of row-label clicks.
 * @param {object[]} rows
 * @param {(row: object) => number} totalOf
 * @param {'left'|'right'} side - 'left' is the reversed butterfly half.
 * @param {'light'|'dark'} theme
 * @param {string} axis - x axis id the total is positioned on.
 * @returns {object[]}
 */
export function totalAnnotations(rows, totalOf, side, theme, axis) {
  const out = [];
  rows.forEach((row, i) => {
    const total = totalOf(row);
    if (!(total > 0)) return;
    out.push({
      name: 'total',
      xref: axis,
      yref: 'y',
      x: total,
      y: i,
      xanchor: side === 'left' ? 'right' : 'left',
      xshift: side === 'left' ? -4 : 4,
      yanchor: 'middle',
      text: String(total),
      showarrow: false,
      captureevents: false,
      borderpad: 0,
      font: { size: 14, color: ACCENT[theme] },
    });
  });
  return out;
}

/** Integer ticks only: these are counts. */
function countTicks(max) {
  const ticks = niceLinearTicks(0, max, 6).filter((v) => Number.isInteger(v));
  return ticks.length > 0 ? ticks : [0];
}

/**
 * Style for an unrated part (D-15): the hue at 25% fill, 1.5px border in the
 * full hue. `tone` is a '#rrggbb' hex.
 * @param {string} tone
 * @returns {{color: string, line: {width: number, color: string}}}
 */
function unratedStyle(tone) {
  const hex = String(tone).replace('#', '');
  const full = hex.length === 3 ? hex.replace(/./g, (c) => c + c) : hex;
  const n = Number.parseInt(full, 16);
  const rgba = `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},0.25)`;
  return { color: rgba, line: { width: 1.5, color: tone } };
}

const unratedOf = (total, rated) => Math.max(0, (total ?? 0) - (rated ?? 0));

/** Border widths for a piece: 1.5px where it has length, 0 where it has none. */
const borderWidths = (widths) => widths.map((w) => (w > 0 ? 1.5 : 0));

/** Rated and unrated traces of single-color bars for one side (or the only side). */
function simpleTraces(rows, totalOf, ratedOf, side, theme, xaxis) {
  const totals = rows.map(totalOf);
  const rated = rows.map((r, i) => Math.min(totals[i], ratedOf(r) ?? 0));
  const unrated = totals.map((t, i) => t - rated[i]);
  const tones = rows.map((r) => barTones(r, theme).a);
  const base = {
    type: 'bar',
    orientation: 'h',
    xaxis,
    yaxis: 'y',
    y: rows.map((r) => r.key),
    cliponaxis: false,
    hoverinfo: 'none',
    showlegend: false,
    customdata: rows.map((_, r) => (totals[r] > 0 ? { r, s: -1, side } : null)),
  };
  const styles = tones.map(unratedStyle);
  return [
    {
      ...base,
      x: rated,
      marker: { color: tones, line: { width: borderWidths(rated), color: tones } },
    },
    {
      ...base,
      x: unrated,
      marker: {
        color: styles.map((st) => st.color),
        line: { width: borderWidths(unrated), color: tones },
      },
    },
  ];
}

const TRANSPARENT = 'rgba(0,0,0,0)';

/**
 * Stacked bars for one side (or the only side) as the three layers described in
 * the D-23 header note. Shared by plain stacked and family stacked bars, in Bars
 * and in both Butterfly halves, so the styling cannot drift.
 * @param {object[]} rows
 * @param {(row: object) => object[]} segmentsOf
 * @param {(row: object, i: number, seg: object, k: number) => {count: number, rated: number, tone: string}[]} partsOf
 *   the pieces of a segment: one per channel with games (family), or one (plain).
 * @param {number|null} side
 * @param {'light'|'dark'} theme
 * @param {{piece: string, overlay: string, text: string}} axes
 * @param {number} gap - separator stroke width in px (D-28).
 * @returns {object[]}
 */
function stackedTraces(rows, segmentsOf, partsOf, side, theme, axes, gap) {
  const bg = PAGE_BG[theme];
  const y = rows.map((r) => r.key);
  const segs = rows.map(segmentsOf);
  const ratedW = (c) => Math.min(c.count, c.rated ?? 0);
  const parts = segs.map((list, i) => list.map((seg, k) => partsOf(rows[i], i, seg, k)));

  // Layer 1: per row, segment by segment, rated pieces then unrated pieces.
  const pieceLists = parts.map((rowParts) =>
    rowParts.flatMap((chans) => [
      ...chans.map((c) => ({ w: ratedW(c), tone: c.tone, unrated: false })),
      ...chans.map((c) => ({ w: unratedOf(c.count, c.rated), tone: c.tone, unrated: true })),
    ]),
  );
  const pieceDepth = pieceLists.reduce((m, list) => Math.max(m, list.length), 0);
  const traces = [];
  for (let j = 0; j < pieceDepth; j += 1) {
    const cells = pieceLists.map((list, i) => list[j] ?? { w: 0, tone: barTones(rows[i], theme).a, unrated: false });
    traces.push({
      type: 'bar',
      orientation: 'h',
      xaxis: axes.piece,
      yaxis: 'y',
      x: cells.map((c) => c.w),
      y,
      cliponaxis: false,
      marker: {
        color: cells.map((c) => (c.unrated ? unratedStyle(c.tone).color : c.tone)),
        line: { width: borderWidths(cells.map((c) => c.w)), color: cells.map((c) => c.tone) },
      },
      hoverinfo: 'skip',
      showlegend: false,
    });
  }

  // Layer 2: one transparent overlay per segment rank (separator, hover, click).
  const depth = segs.reduce((m, list) => Math.max(m, list.length), 0);
  for (let k = 0; k < depth; k += 1) {
    traces.push({
      type: 'bar',
      orientation: 'h',
      xaxis: axes.overlay,
      yaxis: 'y',
      x: segs.map((list) => (list[k] ? list[k].count : 0)),
      y,
      cliponaxis: false,
      marker: { color: TRANSPARENT, line: { width: gap, color: bg } },
      hoverinfo: 'none',
      showlegend: false,
      customdata: segs.map((list, r) => (list[k] ? { r, s: k, side } : null)),
    });
  }

  // Layer 3: the label on each segment's wider part (WR-02).
  for (let k = 0; k < depth; k += 1) {
    const cells = segs.map((list, i) => {
      const seg = list[k];
      if (!seg) return null;
      const chans = parts[i][k];
      const rated = chans.filter((c) => ratedW(c) > 0);
      const unrated = chans.filter((c) => unratedOf(c.count, c.rated) > 0);
      const rw = rated.reduce((n, c) => n + ratedW(c), 0);
      const uw = unrated.reduce((n, c) => n + unratedOf(c.count, c.rated), 0);
      const onRated = rw >= uw;
      const fills = onRated
        ? rated.map((c) => c.tone)
        : unrated.map((c) => mixHex(c.tone, bg, 0.25));
      const color = seg.count > 0 ? readableTextOnAll(fills) : null;
      return { rw, uw, onRated, color, text: color != null ? escapeHover(segmentText(seg)) : '' };
    });
    for (const unrated of [false, true]) {
      const mine = cells.map((c) => (c && c.onRated !== unrated ? c : null));
      traces.push({
        type: 'bar',
        orientation: 'h',
        xaxis: axes.text,
        yaxis: 'y',
        x: cells.map((c) => (c ? (unrated ? c.uw : c.rw) : 0)),
        y,
        text: mine.map((c) => (c ? c.text : '')),
        textposition: 'inside',
        insidetextanchor: 'middle',
        constraintext: 'inside',
        cliponaxis: false,
        textfont: { size: 14, color: mine.map((c) => (c && c.color) || '#000000') },
        marker: { color: TRANSPARENT, line: { width: 0 } },
        hoverinfo: 'skip',
        showlegend: false,
      });
    }
  }
  return traces;
}

/** Pieces of a plain stacked segment: one, in the segment's Tone A/B (D-16). */
function plainParts(theme) {
  return (row, _i, seg, k) => {
    const t = barTones(row, theme);
    return [{ count: seg.count, rated: seg.rated ?? 0, tone: k % 2 === 0 ? t.a : t.b }];
  };
}

/** Pieces of a family segment: one per channel with games, shaded by `channelShades`. */
function familyParts(theme) {
  const cache = new Map();
  return (row, _i, seg) => {
    if (!cache.has(row)) cache.set(row, channelShades(row.family, theme, row.shadeCount ?? 1));
    const shades = cache.get(row);
    return (seg.channels ?? [])
      .filter((c) => c.count > 0)
      .map((c) => ({ count: c.count, rated: c.rated ?? 0, tone: shades[c.shade] ?? shades[0] }));
  };
}

/** An invisible axis overlaying `base` with the same range (D-23 overlay). */
function overlayAxis(base, range) {
  return {
    overlaying: base,
    anchor: 'y',
    visible: false,
    fixedrange: true,
    showgrid: false,
    zeroline: false,
    range,
  };
}

function labelAnnotation(row, i, text, extra) {
  return {
    xref: 'paper',
    yref: 'y',
    y: i,
    text,
    showarrow: false,
    captureevents: row.target != null,
    borderpad: 0,
    borderwidth: 0,
    ...extra,
  };
}

function baseLayout(theme, env, rows, pitch, margin, bargap) {
  return {
    datarevision: env.revision,
    paper_bgcolor: PAGE_BG[theme],
    plot_bgcolor: PAGE_BG[theme],
    font: { family: chartFontFamily(), size: CHART_FONT_SIZE, color: ACCENT[theme] },
    showlegend: false,
    hovermode: 'closest',
    clickmode: 'event',
    dragmode: false,
    bargap,
    uniformtext: { mode: 'hide', minsize: 14 },
    height: rows.length * pitch + MARGIN_T + MARGIN_B,
    margin,
    meta: { rowCount: rows.length },
    yaxis: {
      type: 'category',
      categoryorder: 'array',
      categoryarray: rows.map((r) => r.key),
      // Explicit reversed range: exactly one pitch per row (autorange pads).
      autorange: false,
      range: [rows.length - 0.5, -0.5],
      showticklabels: false,
      showgrid: false,
      zeroline: false,
      fixedrange: true,
    },
  };
}

function xAxis(theme, range, extra) {
  return {
    title: { text: 'Games', standoff: 4 },
    automargin: false,
    range,
    tickmode: 'array',
    tickvals: countTicks(Math.max(range[0], range[1])),
    gridcolor: DIVIDER[theme],
    tickfont: { color: MUTED[theme] },
    zeroline: true,
    zerolinecolor: MUTED[theme],
    zerolinewidth: 2,
    fixedrange: true,
    ...extra,
  };
}

/** The bargap that yields `thickness` px bars in a `pitch` px slot. */
function gapFor(pitch, thickness) {
  return 1 - thickness / pitch;
}

/**
 * Figure for the Bars tab, simple or stacked.
 * @param {object} model - a `barsModel` result.
 * @param {object[]} rows - the shown rows.
 * @param {{theme: 'light'|'dark', mobile: boolean, revision: number, width: number}} env
 * @returns {{traces: object[], layout: object, config: object}}
 */
export function buildBarFigure(model, rows, env) {
  const { theme, mobile } = env;
  const stacked = model.mode === 'stacked';
  const gap = mobile ? SEGMENT_GAP.phone : SEGMENT_GAP.desktop;
  const labels = rows.map((r) => (mobile
    ? truncate(r.label, LABEL_MAX)
    : truncateFit(r.label, LABEL_MAX, LABEL_MAX_PX)));
  const pitch = mobile ? PHONE_BARS_PITCH : DESKTOP_PITCH;
  const bargap = mobile ? gapFor(PHONE_BARS_PITCH, PHONE_BARS_THICKNESS) : DESKTOP_BARGAP;
  const margin = mobile
    ? { l: 8, r: 8, t: MARGIN_T, b: MARGIN_B }
    : { l: Math.min(240, 16 + Math.ceil(widest(labels))), r: 48, t: MARGIN_T, b: MARGIN_B };

  const family = stacked && model.rowKind === 'family';
  let traces;
  const barAxes = { piece: 'x', overlay: 'x3', text: 'x5' };
  if (stacked) {
    const parts = family ? familyParts(theme) : plainParts(theme);
    traces = stackedTraces(rows, (r) => r.segments, parts, null, theme, barAxes, gap);
  } else traces = simpleTraces(rows, (r) => r.total, (r) => r.rated, null, theme, 'x');
  const maxTotal = rows.reduce((m, r) => Math.max(m, r.total), 0);

  const layout = baseLayout(theme, env, rows, pitch, margin, bargap);
  layout.barmode = 'stack';
  layout.xaxis = xAxis(
    theme,
    [0, rangeTop(maxTotal, env.width - margin.l - margin.r, 1.12)],
    {},
  );
  if (stacked) {
    layout.xaxis3 = overlayAxis('x', layout.xaxis.range);
    layout.xaxis5 = overlayAxis('x', layout.xaxis.range);
  }
  layout.annotations = rows.map((row, i) => {
    const text = escapeHover(labels[i]);
    const font = { size: 14, color: ACCENT[theme] };
    if (mobile) {
      return labelAnnotation(row, i, text, {
        x: 0,
        xanchor: 'left',
        yanchor: 'bottom',
        yshift: PHONE_BARS_THICKNESS / 2 + LABEL_GAP,
        font,
      });
    }
    return labelAnnotation(row, i, text, {
      x: 0,
      xanchor: 'right',
      xshift: -8,
      yanchor: 'middle',
      font,
    });
  });
  layout.annotations = layout.annotations.concat(
    totalAnnotations(rows, (r) => r.total, 'right', theme, 'x'),
  );
  return { traces, layout, config: { ...CONFIG } };
}

/**
 * Desktop spine gap in px: wide enough for the longest spine label as rendered
 * (plus padding), never under the UI-SPEC's 160. The UI-SPEC's fixed 160px
 * overlapped labels of 30 characters (04.4-01 spike), and a per-character
 * estimate overlapped them again in a wider font, hence the measured size.
 * @param {number} longestPx - rendered width of the longest spine label.
 * @returns {number}
 */
export function spineGapPx(longestPx) {
  return Math.max(160, Math.ceil(longestPx) + 24);
}

/**
 * Figure for the Butterfly tab (two-domain technique from the 04.4-01 spine
 * spike): left traces on `x` (reversed), right traces on `x2`, one shared
 * category `y` axis, both halves on one magnitude scale.
 * @param {object} model - a `butterflyModel` result.
 * @param {object[]} rows - the shown rows.
 * @param {{theme: 'light'|'dark', mobile: boolean, revision: number, width: number}} env
 * @returns {{traces: object[], layout: object, config: object}}
 */
export function buildButterflyFigure(model, rows, env) {
  const { theme, mobile } = env;
  const stacked = model.mode === 'stacked';
  const gap = mobile ? SEGMENT_GAP.phone : SEGMENT_GAP.desktop;
  const labelMax = mobile ? LABEL_MAX : SPINE_LABEL_MAX;
  const labels = rows.map((r) => (mobile
    ? truncate(r.label, labelMax)
    : truncateFit(r.label, labelMax, SPINE_LABEL_MAX_PX)));
  const pitch = mobile ? PHONE_FLY_PITCH : DESKTOP_PITCH;
  const bargap = mobile ? gapFor(PHONE_FLY_PITCH, PHONE_FLY_THICKNESS) : DESKTOP_BARGAP;
  const margin = { l: 8, r: 8, t: MARGIN_T, b: MARGIN_B };

  let traces = [];
  const family = stacked && model.rowKind === 'family';
  const sideRows = [0, 1].map((side) => rows.map((r) => r.sides[side]));
  for (const side of [0, 1]) {
    const wrapped = rows.map((r, i) => ({ ...r, __side: sideRows[side][i] }));
    if (stacked) {
      const axes = side === 0
        ? { piece: 'x', overlay: 'x3', text: 'x5' }
        : { piece: 'x2', overlay: 'x4', text: 'x6' };
      const parts = family ? familyParts(theme) : plainParts(theme);
      traces = traces.concat(
        stackedTraces(wrapped, (r) => r.__side.segments, parts, side, theme, axes, gap),
      );
    } else {
      const axis = side === 0 ? 'x' : 'x2';
      traces = traces.concat(
        simpleTraces(wrapped, (r) => r.__side.total, (r) => r.__side.rated, side, theme, axis),
      );
    }
  }
  const maxSide = rows.reduce(
    (m, r) => Math.max(m, r.sides[0].total, r.sides[1].total),
    0,
  );

  const gapPx = mobile ? 0 : spineGapPx(widest(labels));
  const g = mobile ? 0 : Math.min(0.4, gapPx / Math.max(1, env.width - 16));
  const top = rangeTop(maxSide, (env.width - 16) * (0.5 - g / 2), 1.1);

  const layout = baseLayout(theme, env, rows, pitch, margin, bargap);
  layout.barmode = 'stack';
  layout.xaxis = xAxis(theme, [top, 0], { domain: [0, 0.5 - g / 2], anchor: 'y' });
  layout.xaxis2 = xAxis(theme, [0, top], { domain: [0.5 + g / 2, 1], anchor: 'y' });
  if (stacked) {
    layout.xaxis3 = overlayAxis('x', layout.xaxis.range);
    layout.xaxis4 = overlayAxis('x2', layout.xaxis2.range);
    layout.xaxis5 = overlayAxis('x', layout.xaxis.range);
    layout.xaxis6 = overlayAxis('x2', layout.xaxis2.range);
  }

  const font = { size: 14, color: ACCENT[theme] };
  const rowLabels = rows.map((row, i) => {
    const text = escapeHover(labels[i]);
    if (mobile) {
      return labelAnnotation(row, i, text, {
        x: 0.5,
        xanchor: 'center',
        yanchor: 'bottom',
        yshift: PHONE_FLY_THICKNESS / 2 + LABEL_GAP,
        font,
      });
    }
    return labelAnnotation(row, i, text, {
      x: 0.5,
      xanchor: 'center',
      yanchor: 'middle',
      bgcolor: PAGE_BG[theme],
      borderpad: 2,
      font,
    });
  });
  // A phone half is ~170px wide and a title grows away from the spine, so cap
  // its rendered width (bold 14px) by the half's width.
  const headerPx = mobile ? Math.max(0, (env.width - 16) / 2 - 12) : Infinity;
  const headerFont = { weight: 600 };
  // D-26: each side title sits against the spine edge of its own half.
  const headers = [0, 1].map((side) => ({
    xref: 'paper',
    yref: 'paper',
    x: side === 0 ? 0.5 - g / 2 : 0.5 + g / 2,
    xanchor: side === 0 ? 'right' : 'left',
    xshift: mobile ? (side === 0 ? -4 : 4) : 0,
    borderpad: 0,
    y: 1,
    yanchor: 'bottom',
    text: escapeHover(truncateFit(model.sides[side].name, SPINE_LABEL_MAX, headerPx, headerFont)),
    showarrow: false,
    captureevents: false,
    font: { size: 14, color: ACCENT[theme], weight: 600 },
  }));
  layout.annotations = rowLabels.concat(headers);
  layout.annotations = layout.annotations.concat(
    totalAnnotations(rows, (r) => r.sides[0].total, 'left', theme, 'x'),
    totalAnnotations(rows, (r) => r.sides[1].total, 'right', theme, 'x2'),
  );
  return { traces, layout, config: { ...CONFIG } };
}

/**
 * Draws the figure.
 * @param {HTMLElement} gd
 * @param {{traces: object[], layout: object, config: object}} figure
 * @returns {*} the Plotly promise.
 */
export function renderBars(gd, figure) {
  gd.__barsRowCount = figure.layout.meta.rowCount;
  return window.Plotly.react(gd, figure.traces, figure.layout, figure.config);
}

/**
 * Binds Plotly events once, after the first `renderBars`.
 * @param {HTMLElement} gd
 * @param {{onPointClick?: Function, onPointHover?: Function, onPointUnhover?: Function, onLabelClick?: Function}} handlers
 */
export function bindBarEvents(gd, handlers = {}) {
  const { onPointClick, onPointHover, onPointUnhover, onLabelClick } = handlers;
  gd.on('plotly_click', (ev) => {
    const ref = ev.points && ev.points[0] ? ev.points[0].customdata : null;
    if (ref != null) onPointClick?.(ref, ev);
  });
  gd.on('plotly_hover', (ev) => {
    const ref = ev.points && ev.points[0] ? ev.points[0].customdata : null;
    if (ref != null) onPointHover?.(ref, ev);
  });
  gd.on('plotly_unhover', () => onPointUnhover?.());
  gd.on('plotly_clickannotation', (ev) => {
    if (ev.index < (gd.__barsRowCount ?? 0)) onLabelClick?.(ev.index);
  });
}
