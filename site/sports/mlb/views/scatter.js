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
import { initBandInfo, positionBandInfo, closeBandNote } from '../../../modules/band-info.js';
import { mountViewTools } from '../tools.js';
import { ROUND_SHORT } from '../data.js';
import { MLB_SROUNDS } from '../state.js';
import { RETROSHEET_NOTICE, RETROSHEET_CONTACT } from '../panel.js';
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

// Fixed copy (RT-29..RT-34); no data string is ever written into it.
const ROUND_DISABLED_TITLE = 'Round applies to postseason games';
const NOTE_BOTTOM = 'No viewership figure for these games: Ratings Reference has none, the figure is not posted yet, or it is window-level only.';
const NOTE_LEFT = "Retrosheet's 2026 files are released late in 2026, and some older games have no play-by-play.";
const CAPTION_VIEWERS = "Viewership figures: Ratings Reference; each game's detail panel links its record and the figure's original source. Open dots are window-level: one figure covers the whole broadcast window, not this game alone.";
const CAPTION_NETWORKS = "Networks: 506 Sports and Wikipedia (CC BY-SA 4.0); each game's detail panel links its source.";
// The real MLB eras break at the same years as CFB's (2020, 2025, 2026), so the CFB era
// note (RT-21) is used as written (checked against the local build, 16-07).
const CAPTION_ERAS = 'Nielsen changed how it measures viewing in 2020, 2025, and 2026, so compare seasons with care; see ';

const STYPE_OPTIONS = [
  { key: 'all', label: 'All games' },
  { key: 'post', label: 'Postseason' },
  { key: 'reg', label: 'Reg. Season' },
];

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
    for (const info of [refs.bottomInfo, refs.leftInfo]) {
      info.button.hidden = true;
      closeBandNote(info);
    }
  }
}

/** A strip label that doubles as a 44px info button (the CFB band pattern). */
function stripInfo(className, label, ariaLabel, noteText) {
  const button = el('button', `band-info ${className}`);
  button.type = 'button';
  button.hidden = true;
  button.setAttribute('aria-label', ariaLabel);
  button.setAttribute('aria-expanded', 'false');
  const glyph = el('span', 'band-info-glyph', 'i');
  glyph.setAttribute('aria-hidden', 'true');
  button.append(el('span', 'band-info-text', label), glyph);
  const note = el('div', `band-note ${className.replace('info', 'note')}`);
  note.hidden = true;
  note.id = `${className}-note`;
  note.appendChild(el('p', null, noteText));
  button.setAttribute('aria-controls', note.id);
  initBandInfo({ button, note });
  return { button, note };
}

/** Bottom label in the gap row above the bottom strip; left label at the top of the left strip. */
function placeStripInfo() {
  if (!refs.drawn) return;
  const gd = refs.gd;
  const full = gd._fullLayout;
  if (!full || !full._size || !full.xaxis) return;
  if (!refs.bottomInfo.button.hidden) positionBandInfo(gd, refs.bottomInfo.button, refs.bottomInfo.note);
  const left = refs.leftInfo.button;
  if (!left.hidden) {
    const x = Math.round(full._size.l + 2);
    const y = Math.round(full._size.t + 2);
    left.style.left = `${x}px`;
    left.style.top = `${y}px`;
    const note = refs.leftInfo.note;
    const noteW = note.offsetWidth || 280;
    note.style.left = `${Math.round(Math.min(x, Math.max(0, gd.clientWidth - noteW - 4)))}px`;
    note.style.top = `${y + left.offsetHeight}px`;
  }
}

// ---- controls and captions ----

function segmented(label, options, onPick) {
  const group = el('div', 'segmented');
  group.setAttribute('role', 'group');
  group.setAttribute('aria-label', label);
  for (const o of options) {
    const b = el('button', null, o.label);
    b.type = 'button';
    b.dataset.value = o.key;
    b.addEventListener('click', () => onPick(o.key, b));
    group.appendChild(b);
  }
  return group;
}

function axisGroup(caption, group) {
  const wrap = el('div', 'axis-group');
  const cap = el('span', 'axis-caption', caption);
  cap.setAttribute('aria-hidden', 'true');
  wrap.append(cap, group);
  return wrap;
}

function presentRounds(model) {
  const seen = new Set(model.cols.round);
  return MLB_SROUNDS.filter((r) => seen.has(r));
}

function buildControls(ctx) {
  refs.stypeGroup = segmented('Season type', STYPE_OPTIONS, (k) => {
    ctx.setState(k === 'all' ? { stype: null, sround: null } : { stype: k });
  });
  const rounds = [{ key: 'all', label: 'All rounds' }, ...presentRounds(ctx.model).map((r) => ({ key: r, label: ROUND_SHORT[r] }))];
  refs.roundGroup = segmented('Round', rounds, (k, b) => {
    if (b.getAttribute('aria-disabled') === 'true') return;
    ctx.setState({ sround: k === 'all' ? null : k });
  });
  const wrap = el('div', 'scatter-controls');
  wrap.append(axisGroup('Season type', refs.stypeGroup), axisGroup('Round', refs.roundGroup));
  refs.controls.appendChild(wrap);
}

function press(group, value) {
  for (const b of group.querySelectorAll('button')) {
    b.setAttribute('aria-pressed', String(b.dataset.value === value));
  }
}

/** Pressed state, and the Round group's disabled look (no reflow: the buttons stay). */
function syncControls(state) {
  press(refs.stypeGroup, state.stype ?? 'all');
  const post = state.stype === 'post';
  press(refs.roundGroup, post ? state.sround ?? 'all' : 'all');
  for (const b of refs.roundGroup.querySelectorAll('button')) {
    if (post) {
      b.removeAttribute('aria-disabled');
      b.removeAttribute('title');
    } else {
      b.setAttribute('aria-disabled', 'true');
      b.title = ROUND_DISABLED_TITLE;
    }
  }
}

function link(text, href) {
  const a = el('a', null, text);
  a.href = href;
  a.rel = 'noopener noreferrer';
  return a;
}

/** Captions 1-3 always (Retrosheet, Ratings Reference, networks); caption 4 with more than one era. */
function buildCaptions(ctx) {
  const retro = el('p', 'caption');
  retro.append(
    document.createTextNode(`${RETROSHEET_NOTICE} ${RETROSHEET_CONTACT}`),
    link('www.retrosheet.org', 'https://www.retrosheet.org'),
  );
  const lines = [retro, el('p', 'caption', CAPTION_VIEWERS), el('p', 'caption', CAPTION_NETWORKS)];
  if (ctx.model.lookups.eras.length > 1) {
    const eras = el('p', 'caption');
    eras.append(
      document.createTextNode(CAPTION_ERAS),
      link('methodology', ctx.methodologyHref('measurement-eras')),
      document.createTextNode('.'),
    );
    lines.push(eras);
  }
  return lines;
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
  refs.bottomInfo = stripInfo(
    'mlb-bottom-info', 'No public rating', 'Why do some games have no public rating?', NOTE_BOTTOM,
  );
  refs.leftInfo = stripInfo(
    'mlb-left-info', 'No excitement', 'Why do some games have no excitement figure?', NOTE_LEFT,
  );
  refs.chart.append(
    refs.gd, refs.note,
    refs.bottomInfo.button, refs.bottomInfo.note, refs.leftInfo.button, refs.leftInfo.note,
  );
  refs.status = el('p', 'mlb-scatter-status');
  refs.status.setAttribute('role', 'status');
  buildControls(ctx);
  container.append(refs.chart, refs.status, ...buildCaptions(ctx));
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
  syncControls(state);

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
  if (refs.bottomInfo.button.hidden) closeBandNote(refs.bottomInfo);
  refs.leftInfo.button.hidden = counts.noExcitement + counts.neither === 0;
  if (refs.leftInfo.button.hidden) closeBandNote(refs.leftInfo);
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
