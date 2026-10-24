/**
 * MLB view 3: Scatter (D-04..D-10). MLB-only: the NFL scatter helpers it needs are copied, not imported.
 *
 * One svg `scatter` dot per game that passes the Season type / Round control. X is
 * Retrosheet excitement (linear), Y is viewers (log). A game with no public rating sits
 * in the bottom strip, a game with a rating but no excitement in the 72px left strip,
 * and a game with neither in the corner where the strips meet, so no game is dropped and
 * a missing value is never drawn at 0. Dots are coloured by network family; window-scope
 * figures draw as open dots. Game data never reaches Plotly as text: `customdata` holds
 * game indexes only, hover is off, and every label here is a fixed string set with
 * textContent.
 */
import { FAMILY_COLORS, MUTED, PAGE_BG, DIVIDER } from '../../../modules/palette.js';
import { frameConfig, frameLayout, referenceLine } from '../../../modules/chart-frame.js';
import { bandLayout, marginFor } from '../../../modules/chart.js';
import { positionBandInfo } from '../../../modules/band-info.js';
import { mountViewTools } from '../tools.js';
import {
  buildScatterItems, colorSlotOf, statusText, stripJitter, MLB_FAMILY_ORDER,
} from '../scatter-items.js';

const CONFIG = frameConfig({ zoomable: true });

const VIEWER_TICKS = [
  [5e5, '500K'], [1e6, '1M'], [2e6, '2M'], [5e6, '5M'], [1e7, '10M'], [2e7, '20M'],
];
const BASE_SIZE = 6;
const STRIP_PX = 72; // the left strip's width
const STRIP_GAP_PX = 8; // between the strip's divider and excitement 0
const EDGE_PAD_PX = 8; // right padding so a dot at the maximum is not clipped
const PLOT_HEIGHT = { desktop: 480, phone: 360 };

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

const refs = {
  ctx: null,
  controls: null,
  chart: null,
  gd: null,
  note: null,
  status: null,
  drawn: false,
  bound: false,
  home: null,
  lastWidth: 0,
};

let current = null; // what the last render drew

function theme(env) {
  return env.dark ? 'dark' : 'light';
}

function familyColor(family, th) {
  return FAMILY_COLORS[th][colorSlotOf(family)];
}

// ---- axes ----

/** Viewers axis from the rated items: log range padded 25%, ticks that fall inside it. */
function yAxisFor(items) {
  let lo = Infinity;
  let hi = -Infinity;
  for (const it of items) {
    if (it.x == null) continue;
    if (it.x < lo) lo = it.x;
    if (it.x > hi) hi = it.x;
  }
  const all = { tickvals: VIEWER_TICKS.map((t) => t[0]), ticktext: VIEWER_TICKS.map((t) => t[1]) };
  if (!(hi > 0)) return { range: [Math.log10(5e5), Math.log10(2e7)], ...all };
  const rLo = lo / 1.25;
  const rHi = hi * 1.25;
  const ticks = VIEWER_TICKS.filter(([v]) => v >= rLo && v <= rHi);
  if (ticks.length >= 2) {
    return {
      range: [Math.log10(rLo), Math.log10(rHi)],
      tickvals: ticks.map((t) => t[0]),
      ticktext: ticks.map((t) => t[1]),
    };
  }
  return { range: [Math.log10(Math.min(rLo, 5e5)), Math.log10(Math.max(rHi, 2e7))], ...all };
}

function tickText(v) {
  return Number.isInteger(v) ? String(v) : v.toFixed(1);
}

/** X geometry: excitement 0..xHi on the main plot, the 72px strip at negative x. */
function xGeometry(items, plotW) {
  let top = 0;
  for (const it of items) if (it.y != null && it.y > top) top = it.y;
  const xHi = top > 0 ? Math.ceil(top * 2) / 2 : 1;
  const mainPx = Math.max(plotW - STRIP_PX - STRIP_GAP_PX - EDGE_PAD_PX, 120);
  const scale = xHi / mainPx;
  const step = xHi < 4 ? 0.5 : 1;
  const tickvals = [];
  for (let v = 0; v <= xHi + 1e-9; v += step) tickvals.push(Math.round(v * 1e6) / 1e6);
  return {
    xHi,
    scale,
    lo: -(STRIP_PX + STRIP_GAP_PX) * scale,
    edge: -STRIP_GAP_PX * scale,
    hi: xHi + EDGE_PAD_PX * scale,
    tickvals,
    ticktext: tickvals.map(tickText),
  };
}

/** Deterministic x inside the left strip (12..60px of its 72px) for a game with no excitement. */
function stripX(geo, i) {
  const j = (stripJitter(i) - 0.12) / 0.76;
  return geo.lo + geo.scale * (12 + j * 48);
}

// ---- figure ----

function buildFigure(items, env, th) {
  const height = env.mobile ? PLOT_HEIGHT.phone : PLOT_HEIGHT.desktop;
  const margin = marginFor(env.mobile);
  const plotH = height - margin.t - margin.b;
  const bandGeo = bandLayout(plotH);
  const plotW = Math.max((refs.chart.clientWidth || (env.mobile ? 360 : 1100)) - margin.l - margin.r, 200);
  const yAxis = yAxisFor(items);
  const geo = xGeometry(items, plotW);
  const bg = PAGE_BG[th];

  const traces = [];
  const present = MLB_FAMILY_ORDER.filter((f) => items.some((it) => it.family === f));
  const coords = (it) => {
    const left = it.place === 'left' || it.place === 'corner';
    const strip = it.place === 'bottom' || it.place === 'corner';
    return {
      x: left ? stripX(geo, it.i) : it.y,
      y: strip ? stripJitter(it.i) : it.x,
    };
  };
  const build = (family, subset, yaxis) => {
    const color = familyColor(family, th);
    const pts = subset.map(coords);
    return {
      type: 'scatter',
      mode: 'markers',
      meta: family,
      x: pts.map((p) => p.x),
      y: pts.map((p) => p.y),
      yaxis,
      customdata: subset.map((it) => it.i),
      hoverinfo: 'none',
      showlegend: false,
      marker: {
        symbol: 'circle',
        size: subset.map(() => BASE_SIZE),
        // Window-scope figures cover a whole broadcast window: open dots, page-colour fill.
        color: subset.map((it) => (it.window ? bg : color)),
        line: {
          width: subset.map((it) => (it.window ? 1.5 : 0)),
          color: subset.map(() => color),
        },
      },
    };
  };
  for (const family of present) {
    const mine = items.filter((it) => it.family === family && !it.hidden);
    const main = mine.filter((it) => it.place === 'plot' || it.place === 'left');
    const strip = mine.filter((it) => it.place === 'bottom' || it.place === 'corner');
    if (main.length) traces.push(build(family, main, 'y'));
    if (strip.length) traces.push(build(family, strip, 'y2'));
  }

  const zoomable = !env.mobile;
  const layout = {
    hovermode: 'closest',
    clickmode: 'event',
    dragmode: zoomable ? 'zoom' : false,
    height,
    margin,
    annotations: [],
    shapes: [referenceLine({ xref: 'x', yref: 'paper', x0: geo.edge, x1: geo.edge, y0: 0, y1: 1 }, th)],
    xaxis: {
      title: { text: 'Excitement', standoff: 8 },
      range: [geo.lo, geo.hi],
      tickmode: 'array',
      tickvals: geo.tickvals,
      ticktext: geo.ticktext,
      ticks: 'outside',
      ticklen: 4,
      tickfont: { color: MUTED[th] },
      showgrid: false,
      zeroline: false,
      anchor: 'y2',
      // Zoom is vertical only (viewers): the excitement axis shares the left strip, so zooming
      // it would scroll the strip out of view. Spike result, 16-07 (RESEARCH A3).
      fixedrange: true,
    },
    yaxis: {
      domain: [bandGeo.logBottom, 1],
      type: 'log',
      title: { text: 'Viewers', standoff: 8 },
      range: yAxis.range,
      tickmode: 'array',
      tickvals: yAxis.tickvals,
      ticktext: yAxis.ticktext,
      tickfont: { color: MUTED[th] },
      gridcolor: DIVIDER[th],
      zeroline: false,
      fixedrange: !zoomable,
      ...(zoomable ? { minallowed: yAxis.range[0], maxallowed: yAxis.range[1] } : {}),
    },
    yaxis2: {
      domain: [0, bandGeo.bandTop],
      range: bandGeo.y2range,
      anchor: 'x',
      fixedrange: true,
      showticklabels: false,
      showgrid: false,
      zeroline: false,
    },
  };
  return { traces, layout: frameLayout(layout, { theme: th }), geo, yAxis, families: present };
}

function liveRanges(gd) {
  const full = gd && gd._fullLayout;
  if (!full || !full.xaxis || !full.yaxis) return null;
  return { x: [...full.xaxis.range], y: [...full.yaxis.range] };
}

function setEmpty(show) {
  refs.note.hidden = !show;
  refs.gd.hidden = show;
  if (show) {
    refs.bottomInfo.button.hidden = true;
    refs.leftInfo.button.hidden = true;
  }
}

/** A strip label that doubles as a 44px info button (the CFB band pattern). */
function stripInfo(className, label, ariaLabel) {
  const button = el('button', `band-info ${className}`);
  button.type = 'button';
  button.hidden = true;
  button.setAttribute('aria-label', ariaLabel);
  button.setAttribute('aria-expanded', 'false');
  const glyph = el('span', 'band-info-glyph', 'i');
  glyph.setAttribute('aria-hidden', 'true');
  button.append(el('span', 'band-info-text', label), glyph);
  return { button };
}

/** Bottom label in the gap row above the bottom strip; left label at the top of the left strip. */
function placeStripInfo() {
  if (!refs.drawn) return;
  const gd = refs.gd;
  const full = gd._fullLayout;
  if (!full || !full._size || !full.xaxis) return;
  if (!refs.bottomInfo.button.hidden) positionBandInfo(gd, refs.bottomInfo.button, null);
  const left = refs.leftInfo.button;
  if (!left.hidden) {
    left.style.left = `${Math.round(full._size.l + 2)}px`;
    left.style.top = `${Math.round(full._size.t + 2)}px`;
  }
}

function bindEvents(gd) {
  if (refs.bound) return;
  refs.bound = true;
  gd.on('plotly_afterplot', () => placeStripInfo());
}

// ---- contract ----

export function mount(container, ctx) {
  refs.ctx = ctx;
  container.classList.add('mlb-scatter');
  refs.controls = el('div', 'chart-controls mlb-scatter-controls');
  refs.chart = el('div', 'nfl-chart mlb-scatter-plot');
  refs.gd = el('div');
  refs.note = el('div', 'season-empty-note');
  refs.note.setAttribute('role', 'status');
  refs.note.hidden = true;
  refs.note.append(
    el('p', 'season-empty-title', 'No games in this view'),
    el('p', 'season-empty-hint', 'Choose All games or another round.'),
  );
  refs.bottomInfo = stripInfo('mlb-bottom-info', 'No public rating', 'Why do some games have no public rating?');
  refs.leftInfo = stripInfo('mlb-left-info', 'No excitement', 'Why do some games have no excitement figure?');
  refs.chart.append(refs.gd, refs.note, refs.bottomInfo.button, refs.leftInfo.button);
  refs.status = el('p', 'mlb-scatter-status');
  refs.status.setAttribute('role', 'status');
  container.append(refs.chart, refs.status);
  mountViewTools(ctx, 'scatter', [refs.controls], container);
  // The strip is a fixed 72px, so a width change re-lays the figure out.
  if (typeof ResizeObserver !== 'undefined') {
    let frame = 0;
    new ResizeObserver(() => {
      const w = refs.chart.clientWidth;
      if (!refs.drawn || !w || Math.abs(w - refs.lastWidth) < 2) return;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => render(refs.ctx));
    }).observe(refs.chart);
  }
}

export function render(ctx) {
  const model = ctx.model;
  const state = ctx.getState();
  const env = ctx.env();
  const th = theme(env);

  const built = buildScatterItems(model, state, { hiddenFamilies: new Set() });
  const { items, counts, families } = built;
  current = { items, counts, families, env, model, state };
  refs.status.textContent = statusText(counts);

  if (!items.length) {
    refs.drawn = false;
    setEmpty(true);
    return;
  }
  setEmpty(false);
  const fig = buildFigure(items, env, th);
  current.fig = fig;
  refs.drawn = true;
  refs.lastWidth = refs.chart.clientWidth;
  refs.bottomInfo.button.hidden = counts.noRating + counts.neither === 0;
  refs.leftInfo.button.hidden = counts.noExcitement + counts.neither === 0;
  const done = window.Plotly.react(refs.gd, fig.traces, fig.layout, CONFIG);
  bindEvents(refs.gd);
  if (done && typeof done.then === 'function') {
    done.then(() => {
      placeStripInfo();
      refs.home = liveRanges(refs.gd);
    });
  }
}

export function resize() {
  if (refs.drawn && refs.gd && window.Plotly && refs.gd.data) {
    render(refs.ctx);
    placeStripInfo();
  }
}

export function testModel() {
  if (!current || !refs.drawn) {
    return { view: 'scatter', drawn: false, counts: { total: 0, plotted: 0, noRating: 0, noExcitement: 0, neither: 0 }, families: [], status: refs.status ? refs.status.textContent : '' };
  }
  const { counts, families, fig } = current;
  return {
    view: 'scatter',
    drawn: true,
    counts: { ...counts },
    families: [...families],
    status: refs.status.textContent,
    yType: 'log',
    xRange: [...fig.layout.xaxis.range],
  };
}
