/**
 * Plotly figures for the Bars and Butterfly tabs (SITE-34, SITE-35). The
 * builders are pure and DOM-free; `window.Plotly` is referenced only inside
 * `renderBars` and `bindBarEvents`.
 *
 * D-01: every number is a count of rated telecasts; nothing here reads or
 * draws a per-telecast audience figure. D-06: butterfly stacked rows use the
 * same rank-layer trace builder as Bars, per side. D-15: row labels are plain
 * 14/400 annotations; the bar fill carries a network row's family color.
 * D-16: Tone A / Tone B alternation (violet for non-network rows, D-24), 1px page-background separators, in-bar
 * text only where it fits (uniformtext hide) and reads at 4.5:1. D-18: every
 * labelled row with a drill target is a clickable annotation and every point
 * carries customdata `{r, s, side}`. D-20: phones put each label on its own
 * line above its bar(s); desktop butterflies use a center spine built with
 * two x-axis domains (04.4-01 spine spike).
 *
 * Name safety (T-04.4-13): every name goes through `escapeHover` before it
 * enters a Plotly string.
 */

import { ACCENT, DIVIDER, FAMILY_COLORS, MUTED, PAGE_BG, SPECIAL, familyKey, mixHex, readableTextOn } from './palette.js';
import { escapeHover, niceLinearTicks } from './format.js';
import { segmentText } from './bar-copy.js';

const FONT_FAMILY =
  'system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji"';

const LABEL_MAX = 30;
const SPINE_LABEL_MAX = 22;
const CHAR_PX = 7.6;
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

/**
 * Tone A / Tone B fills for a row (D-16): a network row uses its family
 * color, every other row the violet special-filter pair (D-24, superseding
 * D-16's neutral ink tone).
 * @param {{family: string|null}} row
 * @param {'light'|'dark'} theme
 * @returns {{a: string, b: string}}
 */
export function barTones(row, theme) {
  const base =
    row.family != null ? FAMILY_COLORS[theme][familyKey(row.family)] : SPECIAL[theme];
  return { a: base, b: mixHex(base, PAGE_BG[theme], 0.55) };
}

/** The padded x-axis maximum for a count, with room for outside text. */
function padded(max, factor) {
  return Math.max(max, 1) * factor;
}

/** Integer ticks only: these are counts. */
function countTicks(max) {
  const ticks = niceLinearTicks(0, max, 6).filter((v) => Number.isInteger(v));
  return ticks.length > 0 ? ticks : [0];
}

/** One trace of single-color bars for one side (or the only side). */
function simpleTrace(rows, totalOf, side, theme, xaxis) {
  const values = rows.map(totalOf);
  return {
    type: 'bar',
    orientation: 'h',
    xaxis,
    yaxis: 'y',
    x: values,
    y: rows.map((r) => r.key),
    text: values.map((v) => (v > 0 ? String(v) : '')),
    textposition: 'outside',
    cliponaxis: false,
    textfont: { size: 14, color: ACCENT[theme] },
    marker: { color: rows.map((r) => barTones(r, theme).a) },
    hoverinfo: 'none',
    showlegend: false,
    customdata: rows.map((_, r) => (values[r] > 0 ? { r, s: -1, side } : null)),
  };
}

/**
 * Stacked bars as one trace per segment rank (D-16, D-06). Shared by Bars and
 * both butterfly sides, so the styling cannot drift.
 */
function stackTraces(rows, segmentsOf, side, theme, xaxis) {
  const segs = rows.map(segmentsOf);
  const depth = segs.reduce((m, list) => Math.max(m, list.length), 0);
  const traces = [];
  for (let k = 0; k < depth; k += 1) {
    const tones = rows.map((row) => {
      const t = barTones(row, theme);
      return k % 2 === 0 ? t.a : t.b;
    });
    const textColors = tones.map((tone) => readableTextOn(tone));
    traces.push({
      type: 'bar',
      orientation: 'h',
      xaxis,
      yaxis: 'y',
      x: segs.map((list) => (list[k] ? list[k].count : 0)),
      y: rows.map((r) => r.key),
      text: segs.map((list, i) => (list[k] && textColors[i] != null ? segmentText(list[k]) : '')),
      textposition: 'inside',
      insidetextanchor: 'middle',
      constraintext: 'inside',
      cliponaxis: false,
      textfont: { size: 14, color: textColors.map((c) => c ?? '#000000') },
      marker: { color: tones, line: { width: 1, color: PAGE_BG[theme] } },
      hoverinfo: 'none',
      showlegend: false,
      customdata: segs.map((list, r) => (list[k] ? { r, s: k, side } : null)),
    });
  }
  return traces;
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
    font: { family: FONT_FAMILY, size: 14, color: ACCENT[theme] },
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
    title: { text: 'Rated telecasts', standoff: 4 },
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
  const labels = rows.map((r) => truncate(r.label, LABEL_MAX));
  const longest = labels.reduce((m, l) => Math.max(m, l.length), 0);
  const pitch = mobile ? PHONE_BARS_PITCH : DESKTOP_PITCH;
  const bargap = mobile ? gapFor(PHONE_BARS_PITCH, PHONE_BARS_THICKNESS) : DESKTOP_BARGAP;
  const margin = mobile
    ? { l: 8, r: 8, t: MARGIN_T, b: MARGIN_B }
    : { l: Math.min(240, 16 + Math.ceil(CHAR_PX * longest)), r: 48, t: MARGIN_T, b: MARGIN_B };

  const traces = stacked
    ? stackTraces(rows, (r) => r.segments, null, theme, 'x')
    : [simpleTrace(rows, (r) => r.total, null, theme, 'x')];
  const maxTotal = rows.reduce((m, r) => Math.max(m, r.total), 0);

  const layout = baseLayout(theme, env, rows, pitch, margin, bargap);
  layout.barmode = stacked ? 'stack' : 'group';
  layout.xaxis = xAxis(theme, [0, padded(maxTotal, stacked ? 1.02 : 1.12)], {});
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
  return { traces, layout, config: { ...CONFIG } };
}

/**
 * Desktop spine gap in px: wide enough for the longest spine label (about
 * 7.6px per character at 14px, plus padding), never under the UI-SPEC's 160.
 * The UI-SPEC's fixed 160px overlapped labels of 30 characters (04.4-01
 * spike), hence the label-driven size.
 * @param {number} longest - characters in the longest spine label.
 * @returns {number}
 */
export function spineGapPx(longest) {
  return Math.max(160, Math.ceil(CHAR_PX * longest) + 24);
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
  const labelMax = mobile ? LABEL_MAX : SPINE_LABEL_MAX;
  const labels = rows.map((r) => truncate(r.label, labelMax));
  const longest = labels.reduce((m, l) => Math.max(m, l.length), 0);
  const pitch = mobile ? PHONE_FLY_PITCH : DESKTOP_PITCH;
  const bargap = mobile ? gapFor(PHONE_FLY_PITCH, PHONE_FLY_THICKNESS) : DESKTOP_BARGAP;
  const margin = { l: 8, r: 8, t: MARGIN_T, b: MARGIN_B };

  let traces = [];
  const sideRows = [0, 1].map((side) => rows.map((r) => r.sides[side]));
  for (const side of [0, 1]) {
    const axis = side === 0 ? 'x' : 'x2';
    if (stacked) {
      const wrapped = rows.map((r, i) => ({ ...r, __side: sideRows[side][i] }));
      traces = traces.concat(stackTraces(wrapped, (r) => r.__side.segments, side, theme, axis));
    } else {
      const wrapped = rows.map((r, i) => ({ ...r, __side: sideRows[side][i] }));
      traces.push(simpleTrace(wrapped, (r) => r.__side.total, side, theme, axis));
    }
  }
  const maxSide = rows.reduce(
    (m, r) => Math.max(m, r.sides[0].total, r.sides[1].total),
    0,
  );
  const top = Math.max(maxSide, 1) * 1.1;

  const gapPx = mobile ? 0 : spineGapPx(longest);
  const g = mobile ? 0 : Math.min(0.4, gapPx / Math.max(1, env.width - 16));

  const layout = baseLayout(theme, env, rows, pitch, margin, bargap);
  layout.barmode = stacked ? 'stack' : 'group';
  layout.xaxis = xAxis(theme, [top, 0], { domain: [0, 0.5 - g / 2], anchor: 'y' });
  layout.xaxis2 = xAxis(theme, [0, top], { domain: [0.5 + g / 2, 1], anchor: 'y' });

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
  const headers = [0, 1].map((side) => ({
    xref: 'paper',
    yref: 'paper',
    x: side === 0 ? 0 : 1,
    xanchor: side === 0 ? 'left' : 'right',
    y: 1,
    yanchor: 'bottom',
    text: escapeHover(model.sides[side].name),
    showarrow: false,
    captureevents: false,
    font: { size: 14, color: ACCENT[theme], weight: 600 },
  }));
  layout.annotations = rowLabels.concat(headers);
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
