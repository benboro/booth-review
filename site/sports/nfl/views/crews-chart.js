/**
 * NFL Crews booth chart (15-09): one measure, one row per booth, for the first 25 rows of the
 * Crews table in the table's order. The plot height is fixed (25 rows x 24px plus the frame's
 * axis band), so nothing below it shifts while the table grows or the row count changes.
 * Marks have no click action (UI-SPEC): the table is where a booth is picked.
 *
 * Names enter Plotly strings only through escapeHover. The spread's value is never shown;
 * the word appears only in Adjusted hover lines and Adjusted axis titles (D-05, RT-19).
 */
import { crewStyle } from '../palette.js';
import { ACCENT, MUTED, DIVIDER } from '../../../modules/palette.js';
import { FRAME_FONT, frameConfig, frameLayout, referenceLine } from '../../../modules/chart-frame.js';
import { textWidth } from '../../../modules/bar-chart.js';
import { MARGIN, TICK_FONT_PX, DOT_OPACITY } from '../../../modules/chart.js';
import { currentTheme } from '../../../modules/pill.js';
import { showTextTooltip, hideTooltip } from '../../../modules/tooltip.js';
import { escapeHover, MINUS } from '../../../modules/format.js';

export const CONFIG = frameConfig({ zoomable: false });

/** Rows the chart plots, and each row's height in px. */
export const CHART_ROWS = 25;
export const ROW_PX = 24;

const DASH = '—';
const BASE_SIZE = 9;
// Room between the longest row label and the plot edge, and the share of the chart a label
// column may take on a phone before the plot gets too narrow.
const LABEL_PAD_PX = 14;
const PHONE_LABEL_SHARE = 0.5;
const SUFFIXES = new Set(['jr', 'jr.', 'sr', 'sr.', 'ii', 'iii', 'iv', 'v']);

export const METRICS = {
  margin: {
    key: 'margin',
    label: 'Avg margin',
    rawTitle: 'Avg final margin (points)',
    adjTitle: 'Final margin vs. what the spread predicted (points)',
  },
  excitement: {
    key: 'exc',
    label: 'Excitement',
    rawTitle: 'Excitement',
    adjTitle: 'Excitement vs. what the spread predicted',
  },
  viewers: {
    key: 'viewers',
    label: 'Avg viewers',
    rawTitle: 'Avg viewers',
    adjTitle: null,
  },
};

export function theme() {
  return currentTheme();
}

function fixed(x, digits) {
  if (x == null) return DASH;
  const s = Math.abs(x).toFixed(digits);
  return x < 0 && Number(s) !== 0 ? MINUS + s : s;
}

function viewersShort(x) {
  return `${(x / 1e6).toFixed(1)}M`;
}

function ratedGamesText(n) {
  return `${n} rated ${n === 1 ? 'game' : 'games'}`;
}

function seasonText(row) {
  if (row.season != null) return String(row.season);
  const s = row.seasons ?? [];
  if (!s.length) return '';
  const lo = Math.min(...s);
  const hi = Math.max(...s);
  return lo === hi ? String(lo) : `${lo}–${hi}`;
}

/** A person's last name: the last word, skipping a trailing Jr./Sr./II/III suffix. */
export function lastName(name) {
  const words = String(name ?? '').trim().split(/\s+/).filter(Boolean);
  while (words.length > 1 && SUFFIXES.has(words[words.length - 1].toLowerCase())) words.pop();
  return words.length ? words[words.length - 1] : '';
}

/**
 * The phone's row label: "Last / Last, YYYY" (pooled rows drop the season; a booth with no
 * analyst shows the play-by-play last name alone), so two seasons of one voice stay apart.
 */
export function compactLabel(row) {
  const names = [row.pbp, row.analyst].map((p) => lastName(p && p.name)).filter(Boolean);
  const base = names.length ? names.join(' / ') : row.names;
  return row.season != null ? `${base}, ${row.season}` : base;
}

/**
 * The chart items for the first 25 sorted table rows, in table order. `x` is the figure the
 * table cell prints: the Raw mean, the Adjusted residual for margin and excitement, and the
 * raw viewers mean always.
 * @param {object[]} rows - sorted table rows (not just the shown page)
 * @param {{metric: string, adjusted: boolean}} opts
 */
export function chartModel(rows, { metric, adjusted }) {
  const f = METRICS[metric] ?? METRICS.margin;
  const useAdj = adjusted && metric !== 'viewers';
  return rows.slice(0, CHART_ROWS).map((r) => {
    const cell = useAdj ? r.adjusted[f.key] : r[f.key];
    const x = useAdj ? cell.resid : cell.mean;
    const err = useAdj && cell.se != null ? 1.96 * cell.se : null;
    return {
      rowKey: r.rowKey,
      label: r.season != null ? `${r.names}, ${r.season}` : r.names,
      compactLabel: compactLabel(r),
      seasonText: seasonText(r),
      games: r.gamesCount,
      n: cell.n,
      x: x == null ? null : x,
      err,
      hollow: !!cell.flagged,
    };
  });
}

// What the last draw drew (also what the hover handlers read).
let live = null;
const bound = new WeakSet();

function hoverLines(item) {
  const { metric, adjusted } = live;
  const lines = [
    { text: item.label, kind: 'title' },
    { text: item.seasonText, kind: 'body' },
    { text: `${item.games} ${item.games === 1 ? 'game' : 'games'}`, kind: 'body' },
  ];
  const x = item.x;
  const useAdj = adjusted && metric !== 'viewers';
  if (!useAdj) {
    let text;
    if (x == null) text = `${METRICS[metric].label}: not available`;
    else if (metric === 'margin') text = `Avg margin: ${fixed(x, 1)} pts`;
    else if (metric === 'excitement') text = `Excitement: ${fixed(x, 1)} (GEI-style, not CFBD's index)`;
    else text = `Avg viewers: ${viewersShort(x)}`;
    lines.push({ text, kind: 'body' });
    if (metric === 'viewers') lines.push({ text: ratedGamesText(item.n), kind: 'body' });
  } else {
    let text;
    if (x == null) {
      text = `${METRICS[metric].label}: not available`;
    } else {
      const abs = Math.abs(x).toFixed(1);
      if (Number(abs) === 0) {
        text = metric === 'margin' ? 'Final margin: as the spread predicted' : 'Excitement: as the spread predicted';
      } else if (metric === 'margin') {
        text = `${abs} pts ${x < 0 ? 'closer' : 'wider'} than the spread predicted`;
      } else {
        text = `${abs} ${x < 0 ? 'less' : 'more'} excitement than the spread predicted`;
      }
    }
    lines.push({ text, kind: 'body' });
    if (item.err == null || x == null) {
      lines.push({ text: '±1.96 standard errors: not available', kind: 'body' });
    } else {
      lines.push({
        text: `±1.96 standard errors: ${fixed(x - item.err, 1)} to ${fixed(x + item.err, 1)}`,
        kind: 'body',
      });
    }
  }
  if (item.hollow) lines.push({ text: 'n < 8: Fewer than 8 games have this figure', kind: 'body' });
  return lines;
}

function bindHover(gd) {
  if (bound.has(gd)) return;
  bound.add(gd);
  gd.on('plotly_hover', (ev) => {
    const k = ev.points && ev.points[0] ? ev.points[0].customdata : null;
    if (!live || !Number.isInteger(k) || !live.items[k]) return;
    live.onHoverRow?.(live.items[k].rowKey);
    if (live.env.mobile || live.env.hoverNone) return;
    const e = ev.event || {};
    showTextTooltip(hoverLines(live.items[k]), {
      theme: theme(),
      borderColor: ACCENT[theme()],
      clientX: e.clientX ?? 0,
      clientY: e.clientY ?? 0,
    });
  });
  gd.on('plotly_unhover', () => {
    hideTooltip();
    live?.onHoverRow?.(null);
  });
}

function buildFigure(items, metric, adjusted, env, th, widthPx = 0) {
  const f = METRICS[metric];
  const useAdj = adjusted && metric !== 'viewers';
  const size = env.mobile ? BASE_SIZE + 3 : BASE_SIZE;
  const styles = items.map((_, k) => crewStyle(k, th));
  const ys = items.map((_, k) => k);
  const err = items.map((it) => (useAdj && it.err != null ? it.err : 0));

  const main = {
    type: 'scatter',
    mode: 'markers',
    name: 'Booths',
    x: items.map((it) => it.x),
    y: ys,
    customdata: items.map((_, k) => k),
    hoverinfo: 'none',
    marker: {
      symbol: items.map((it, k) => (it.hollow ? `${styles[k].symbol}-open` : styles[k].symbol)),
      size,
      color: styles.map((s) => s.color),
      opacity: items.map((it) => (it.hollow ? DOT_OPACITY.activeUnderPerson : DOT_OPACITY.active)),
      line: { color: styles.map((s) => s.color), width: items.map((it) => (it.hollow ? 2 : 0)) },
    },
  };
  if (useAdj) {
    main.error_x = { type: 'data', array: err, visible: true, color: MUTED[th], thickness: 1.5, width: 6 };
  }

  let lo = Infinity;
  let hi = -Infinity;
  items.forEach((it, k) => {
    if (it.x == null) return;
    lo = Math.min(lo, it.x - err[k]);
    hi = Math.max(hi, it.x + err[k]);
  });
  if (!Number.isFinite(lo)) {
    lo = 0;
    hi = 1;
  }
  lo = Math.min(lo, 0);
  if (useAdj) hi = Math.max(hi, 0);
  const pad = (hi - lo || 1) * 0.08;
  const range = [lo === 0 && !useAdj ? 0 : lo - pad, hi + pad];

  const tick = env.mobile ? TICK_FONT_PX.mobile : TICK_FONT_PX.desktop;
  const titleText = useAdj ? f.adjTitle : f.rawTitle;
  // Full names on desktop, "Last / Last, YYYY" on a phone; the margin is sized from the
  // measured text so no label is ever cut.
  const labels = items.map((it) => (env.mobile ? it.compactLabel : it.label));
  const labelPx = labels.reduce(
    (m, s) => Math.max(m, textWidth(s, { size: tick, family: FRAME_FONT })), 0,
  );
  let left = Math.ceil(labelPx) + LABEL_PAD_PX;
  if (env.mobile && widthPx) {
    left = Math.min(left, Math.floor(widthPx * PHONE_LABEL_SHARE));
  }
  const rows = Math.max(1, Math.min(CHART_ROWS, items.length));
  const layout = {
    font: { size: tick, color: ACCENT[th] },
    hovermode: 'closest',
    clickmode: 'none',
    dragmode: false,
    // Fixed: 25 rows x 24px, plus the frame's margins and the axis-title band.
    height: CHART_ROWS * ROW_PX + MARGIN.t + MARGIN.b + 20,
    // Fewer rows shrink the plot and push the extra height below the axis, so the axis sits
    // right under the last row and the module's height still does not change.
    margin: { ...MARGIN, l: Math.max(MARGIN.l, left), b: MARGIN.b + (CHART_ROWS - rows) * ROW_PX },
    shapes: useAdj
      ? [referenceLine({ xref: 'x', yref: 'paper', x0: 0, x1: 0, y0: 0, y1: 1 }, th)]
      : [],
    xaxis: {
      title: { text: escapeHover(titleText), standoff: 4, font: { size: tick } },
      range,
      gridcolor: DIVIDER[th],
      tickfont: { color: MUTED[th], size: tick },
      zeroline: false,
      fixedrange: true,
    },
    yaxis: {
      // Rows keep their 24px slot whatever the count.
      range: [rows - 0.5, -0.5],
      tickmode: 'array',
      tickvals: ys,
      ticktext: items.map((it, k) => escapeHover(labels[k])),
      tickfont: { color: MUTED[th], size: tick },
      showgrid: false,
      zeroline: false,
      fixedrange: true,
    },
  };
  return { traces: [main], layout: frameLayout(layout, { theme: th }) };
}

/**
 * Draws the chart into `refs.gd` and sizes `refs.chart` to the fixed figure height.
 * @param {{gd: HTMLElement, chart: HTMLElement}} refs
 * @param {object[]} items - from chartModel
 * @param {{metric: string, adjusted: boolean, env: object, th: string,
 *   onHoverRow?: (rowKey: string|null) => void}} opts
 */
export function drawCrewsChart(refs, items, { metric, adjusted, env, th, onHoverRow }) {
  live = { items, metric, adjusted, env, onHoverRow };
  const fig = buildFigure(items, metric, adjusted, env, th, refs.chart.clientWidth);
  refs.chart.style.minHeight = `${fig.layout.height}px`;
  window.Plotly.react(refs.gd, fig.traces, fig.layout, CONFIG);
  bindHover(refs.gd);
}
