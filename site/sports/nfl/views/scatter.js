/**
 * NFL view 4: Game scatter (D-16, D-17).
 *
 * One svg `scatter` dot per regular-season NFL game. Y is viewers (log) or
 * GEI-style excitement (linear); X is date or absolute final margin, never the
 * spread. Games with no Y value sit in a strip under the plot (the unrated
 * band) and games with no final score sit in an N/A strip at the left of the
 * margin axis. A missing value is never plotted at 0. Dots are colored by
 * exclusive category, fade (or hide) under the Seasons, Team and Category
 * filters and highlight under Announcers.
 *
 * Date X reuses the CFB `buildDateAxis` for the block geometry: it keys blocks
 * by the season column and measures days from each season's first game, so a
 * September to January NFL season (January games carry the start-year season)
 * lays out as one contiguous block (RESEARCH A2 verified on the fixture). Its
 * lower tick row is Saturday-based and wired to the CFB chart, so the tick and
 * label rows are built here. Game strings only reach the DOM through
 * textContent/createElement; customdata holds game indexes only.
 */
import { gamePasses, personHighlight, EXCLUSIVE_CATEGORIES } from '../state.js';
import { gameRow } from '../data.js';
import { categoryColor } from '../palette.js';
import { CAUSE_COPY, slotLabel, flagLabels, viewersText, kickoffText, dateShortText } from '../game-format.js';
import { ACCENT, MUTED, PAGE_BG, DIVIDER, ZERO_LINE } from '../../../modules/palette.js';
import { showTextTooltip, hideTooltip } from '../../../modules/tooltip.js';
import { showHoverRing, hideHoverRing, ringSpecFromPoint, hoverRingDiameter } from '../../../modules/hover-ring.js';
import { initBandInfo, positionBandInfo, closeBandNote } from '../../../modules/band-info.js';
import { bandLayout } from '../../../modules/chart.js';
import { buildDateAxis, seasonRange, shownBlocks, gapDividers } from '../../../modules/date-axis.js';
import { MONTHS, escapeHover } from '../../../modules/format.js';

const CONFIG = {
  responsive: true,
  displayModeBar: false,
  displaylogo: false,
  scrollZoom: false,
  showLink: false,
  showSendToCloud: false,
  showEditInChartStudio: false,
};

const Y_TITLES = { viewers: 'Viewers', excitement: 'GEI-style excitement' };
const X_TITLE_MARGIN = 'Final margin (points)';
const VIEWER_TICKS = [
  [5e5, '500K'], [1e6, '1M'], [2e6, '2M'], [5e6, '5M'], [1e7, '10M'], [2e7, '20M'],
];
const BAND_FILL = { light: 'rgba(75, 85, 99, 0.06)', dark: 'rgba(156, 163, 175, 0.10)' };
const FADED_OPACITY = 0.15;
const BASE_SIZE = 6;
const HIGHLIGHT_SIZE = 10;
const NA_X = -2.5; // the N/A strip's center on the margin axis
const NA_EDGE = -1; // the strip's right divider

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function link(text, href) {
  const a = el('a', null, text);
  a.href = href;
  a.rel = 'noopener noreferrer';
  return a;
}

const refs = {
  ctx: null,
  legend: null,
  controls: null,
  yGroup: null,
  xGroup: null,
  dotsGroup: null,
  chips: null,
  chart: null,
  gd: null,
  note: null,
  bandButton: null,
  bandText: null,
  bandNote: null,
  noteViewers: null,
  noteExcitement: null,
  captions: null,
  dataBody: null,
  drawn: false,
  bound: false,
};

const hiddenCats = new Set(); // exclusive-category keys toggled off by their legend chips
let current = null; // what the last render drew
let dateCache = { model: null, dateX: null, axis: null };
let lastToggle = { key: null, at: 0 };

function theme(env) {
  return env.dark ? 'dark' : 'light';
}

function textOn(hex) {
  const lin = (v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  const n = parseInt(hex.slice(1), 16);
  const lum = 0.2126 * lin(n >> 16) + 0.7152 * lin((n >> 8) & 255) + 0.0722 * lin(n & 255);
  return 1.05 / (lum + 0.05) >= (lum + 0.05) / 0.05 ? '#FFFFFF' : '#111111';
}

function dateGeometry(model) {
  if (dateCache.model !== model) {
    const c = model.cols;
    const { dateX, axis } = buildDateAxis(c.season, c.date, c.kickoff);
    dateCache = { model, dateX, axis };
  }
  return dateCache;
}

/** Era index owning most of a season's rated games, or null. */
function seasonEras(model) {
  const c = model.cols;
  const tally = new Map();
  for (let i = 0; i < model.n; i++) {
    if (c.era[i] == null) continue;
    const m = tally.get(c.season[i]) || new Map();
    m.set(c.era[i], (m.get(c.era[i]) || 0) + 1);
    tally.set(c.season[i], m);
  }
  const out = new Map();
  for (const [season, m] of tally) {
    let best = null;
    for (const [era, n] of m) if (best == null || n > best[1]) best = [era, n];
    out.set(season, best[0]);
  }
  return out;
}

// ---- items ----

function buildItems(model, state) {
  const c = model.cols;
  const geo = state.scatterX === 'date' ? dateGeometry(model) : null;
  const items = [];
  const counts = { plotted: 0, band: 0, faded: 0, hidden: 0, highlighted: 0, naStrip: 0 };
  const bandCauses = { pending: 0, regional: 0, none: 0 };
  const yKey = state.scatterY;
  for (let i = 0; i < model.n; i++) {
    const cat = EXCLUSIVE_CATEGORIES[model.category[i]];
    if (hiddenCats.has(cat.key)) {
      counts.hidden += 1;
      continue;
    }
    const pass = gamePasses(model, state, i);
    if (!pass && state.dots === 'hide') {
      counts.hidden += 1;
      continue;
    }
    const y = yKey === 'viewers' ? c.viewers[i] : c.excitement[i];
    let x;
    let na = false;
    if (geo) x = geo.dateX[i];
    else if (c.final_margin[i] == null) {
      x = NA_X;
      na = true;
    } else x = Math.abs(c.final_margin[i]);
    const band = y == null;
    const highlight = pass && personHighlight(model, state, i);
    items.push({ i, x, y: band ? null : y, band, na, pass, highlight, cat });
    if (band) {
      counts.band += 1;
      if (c.viewers[i] == null) {
        const cause = c.cause[i];
        bandCauses[cause in bandCauses ? cause : 'none'] += 1;
      }
    } else counts.plotted += 1;
    if (na) counts.naStrip += 1;
    if (!pass) counts.faded += 1;
    if (highlight) counts.highlighted += 1;
  }
  return { items, counts, bandCauses };
}

/** Deterministic vertical spread inside the band so overlapping dots stay countable. */
function bandY(i) {
  return 0.12 + ((i * 0.6180339887) % 1) * 0.76;
}

// ---- selection and hover ----

function pickGame(i) {
  const { ctx } = refs;
  // A touch tap reaches Plotly as touchend and again as the emulated mouseup.
  const now = Date.now();
  if (lastToggle.key === i && now - lastToggle.at < 500) return;
  lastToggle = { key: i, at: now };
  const sel = ctx.getState().selection;
  const prev = sel && sel.kind === 'games' && sel.key === 'scatter' && Array.isArray(sel.games) ? sel.games : [];
  const games = prev.includes(i) ? prev : [...prev, i];
  ctx.selectGames({ kind: 'games', key: 'scatter', label: 'Picked games', games });
  ctx.openGame(i, refs.gd);
}

function hoverLines(model, i) {
  const row = gameRow(model, i);
  const lines = [{ text: `${row.away} at ${row.home}`, kind: 'title' }];
  const kick = kickoffText(row);
  lines.push({
    text: `${dateShortText(row)}${kick ? `, ${kick}` : ''} · Week ${row.week}`,
    kind: 'body',
  });
  lines.push({ text: [slotLabel(row.slot), ...flagLabels(row)].join(' · '), kind: 'body' });
  if (row.network) lines.push({ text: row.network, kind: 'body' });
  const pbp = row.crew.find((m) => m.role === 'pbp');
  const analyst = row.crew.find((m) => m.role === 'analyst');
  const crew = [pbp, analyst].filter(Boolean).map((m) => m.name).join(' / ');
  if (crew) lines.push({ text: crew, kind: 'body' });
  if (row.viewers != null) {
    lines.push({
      text: `Viewers: ${viewersText(row)}${row.scope === 'window' ? ' · window-level' : ''}`,
      kind: 'body',
    });
  } else {
    const cause = CAUSE_COPY[row.cause] ?? CAUSE_COPY.none;
    lines.push({ text: `Viewers: not available (${cause.hover})`, kind: 'body' });
  }
  lines.push({
    text: row.excitement != null
      ? `GEI-style excitement: ${row.excitement.toFixed(1)}`
      : 'GEI-style excitement: not available',
    kind: 'body',
  });
  lines.push({ text: 'Click for details.', kind: 'hint' });
  return lines;
}

function itemFor(ev) {
  const pt = ev.points && ev.points[0] ? ev.points[0] : null;
  const k = pt ? pt.customdata : null;
  if (!current || !Number.isInteger(k)) return null;
  return current.byGame.get(k) || null;
}

function bindEvents(gd) {
  if (refs.bound) return;
  refs.bound = true;
  gd.on('plotly_click', (ev) => {
    const it = itemFor(ev);
    if (it && it.pass) pickGame(it.i);
  });
  gd.on('plotly_hover', (ev) => {
    const it = itemFor(ev);
    if (!it || !it.pass) return;
    if (current.env.mobile || current.env.hoverNone) return;
    const e = ev.event || {};
    const clientX = e.clientX ?? 0;
    const clientY = e.clientY ?? 0;
    showTextTooltip(hoverLines(current.model, it.i), {
      theme: theme(current.env),
      borderColor: ACCENT[theme(current.env)],
      clientX,
      clientY,
    });
    const spec = ringSpecFromPoint(ev.points[0]);
    showHoverRing({ i: it.i, clientX, clientY, diameter: hoverRingDiameter(spec.size, spec.symbol) });
  });
  gd.on('plotly_unhover', () => {
    hideTooltip();
    hideHoverRing();
  });
  gd.on('plotly_afterplot', () => placeBandInfo());
}

// ---- controls, legend, captions, table ----

function segmented(label, options, onPick) {
  const group = el('div', 'segmented');
  group.setAttribute('role', 'group');
  group.setAttribute('aria-label', label);
  for (const o of options) {
    const b = el('button', null, o.label);
    b.type = 'button';
    b.dataset.value = o.key;
    b.addEventListener('click', () => onPick(o.key));
    group.appendChild(b);
  }
  return group;
}

function pressGroup(group, value) {
  for (const b of group.querySelectorAll('button')) {
    b.setAttribute('aria-pressed', String(b.dataset.value === value));
  }
}

function buildControls() {
  const { ctx } = refs;
  refs.yGroup = segmented(
    'Y axis',
    [{ key: 'viewers', label: 'Viewers' }, { key: 'excitement', label: 'GEI-style excitement' }],
    (k) => ctx.setState({ scatterY: k }),
  );
  refs.xGroup = segmented(
    'X axis',
    [{ key: 'date', label: 'Date' }, { key: 'margin', label: 'Final margin' }],
    (k) => ctx.setState({ scatterX: k }),
  );
  refs.dotsGroup = segmented(
    'Filtered-out dots',
    [{ key: 'fade', label: 'Fade' }, { key: 'hide', label: 'Hide' }],
    (k) => ctx.setState({ dots: k }),
  );
  refs.controls.append(el('span', 'nfl-control-label', 'Y'), refs.yGroup, el('span', 'nfl-control-label', 'X'), refs.xGroup);
}

function renderLegend(th, state) {
  const { ctx, legend } = refs;
  const chips = EXCLUSIVE_CATEGORIES.map((cat) => {
    const color = categoryColor(cat.key, th);
    const b = el('button', 'legend-chip pill', cat.label);
    b.type = 'button';
    b.dataset.category = cat.key;
    const on = !hiddenCats.has(cat.key);
    b.setAttribute('aria-pressed', String(on));
    b.style.borderColor = color;
    if (on) {
      b.style.backgroundColor = color;
      b.style.color = textOn(color);
    }
    b.addEventListener('click', () => {
      if (hiddenCats.has(cat.key)) hiddenCats.delete(cat.key);
      else hiddenCats.add(cat.key);
      ctx.setState({});
    });
    return b;
  });
  pressGroup(refs.dotsGroup, state.dots);
  legend.replaceChildren(...chips, refs.dotsGroup);
}

function renderCaptions() {
  const { ctx, captions } = refs;
  const p = el('p');
  p.append(
    document.createTextNode('Viewers are '),
    link('window-level', ctx.methodologyHref('nfl-window-level-viewership')),
    document.createTextNode(" where marked and unnormalized. GEI-style excitement is not CFBD's excitement index; see "),
    link('methodology', ctx.methodologyHref('nfl-gei-style-excitement')),
    document.createTextNode('.'),
  );
  captions.replaceChildren(p);
}

function fillBandNote() {
  const { ctx } = refs;
  const v = refs.noteViewers;
  v.append(
    el('p', 'band-note-title', 'No public rating'),
    el(
      'p',
      null,
      'We found no published viewer count for these games. The reason is shown for each game. The most common ones:',
    ),
  );
  const ul = el('ul');
  for (const t of [
    'Ratings Reference compiles national windows, not every regional game.',
    'The figure is not posted yet. This is for the newest games of the current season.',
    'No figure was published.',
  ]) ul.appendChild(el('li', null, t));
  const vp = el('p');
  vp.appendChild(link('How we count games', ctx.methodologyHref('nfl-games-with-no-public-rating')));
  v.append(ul, vp);
  const x = refs.noteExcitement;
  const xp = el('p');
  xp.appendChild(link('How the Y axis works', ctx.methodologyHref('nfl-gei-style-excitement')));
  x.append(
    el('p', 'band-note-title', 'No excitement value'),
    el(
      'p',
      null,
      'No win-probability data exists for these games, so they have no height on this chart. They are drawn here instead of being left out. Their viewer figures are unchanged.',
    ),
    xp,
  );
}

function renderDataTable(items, model) {
  const frag = document.createDocumentFragment();
  for (const it of items) {
    const row = gameRow(model, it.i);
    const tr = el('tr');
    const th = el('th', null, `${row.away} at ${row.home}`);
    th.scope = 'row';
    tr.append(
      th,
      el('td', null, dateShortText(row)),
      el('td', null, it.cat.label),
      el('td', null, viewersText(row) ?? 'not available'),
      el('td', null, row.excitement != null ? row.excitement.toFixed(1) : 'not available'),
      el('td', null, row.awayPoints != null && row.homePoints != null ? String(Math.abs(row.awayPoints - row.homePoints)) : 'not available'),
    );
    frag.appendChild(tr);
  }
  refs.dataBody.replaceChildren(frag);
}

function setEmpty(show) {
  refs.note.hidden = !show;
  refs.gd.hidden = show;
  if (show) {
    refs.bandButton.hidden = true;
    refs.bandNote.hidden = true;
  }
}

function placeBandInfo() {
  if (!refs.drawn || refs.bandButton.hidden) return;
  positionBandInfo(refs.gd, refs.bandButton, refs.bandNote);
}

// ---- figure ----

function niceStep(range, target) {
  const rough = range / Math.max(target - 1, 1);
  const mag = 10 ** Math.floor(Math.log10(rough));
  const norm = rough / mag;
  return (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10) * mag;
}

function yAxisFor(model, yKey) {
  const c = model.cols;
  let lo = Infinity;
  let hi = -Infinity;
  const col = yKey === 'viewers' ? c.viewers : c.excitement;
  for (let i = 0; i < model.n; i++) {
    const v = col[i];
    if (v == null) continue;
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  if (yKey === 'viewers') {
    if (!(hi > 0)) return { type: 'log', range: [Math.log10(5e5), Math.log10(2e7)], tickvals: VIEWER_TICKS.map((t) => t[0]), ticktext: VIEWER_TICKS.map((t) => t[1]) };
    let ticks = VIEWER_TICKS.filter(([v]) => v >= lo / 1.5 && v <= hi * 1.5);
    if (ticks.length < 2) ticks = VIEWER_TICKS;
    return {
      type: 'log',
      range: [Math.log10(lo / 1.4), Math.log10(hi * 1.4)],
      tickvals: ticks.map((t) => t[0]),
      ticktext: ticks.map((t) => t[1]),
    };
  }
  if (!(hi >= lo)) return { type: 'linear', range: [0, 1], tickvals: [0, 0.5, 1], ticktext: ['0', '0.5', '1'] };
  const pad = (hi - lo || 1) * 0.1;
  const range = [lo - pad, hi + pad];
  const step = niceStep(range[1] - range[0], 6);
  const tickvals = [];
  for (let v = Math.ceil(range[0] / step) * step; v <= range[1] + step * 1e-9; v += step) {
    tickvals.push(Math.round(v * 1e6) / 1e6);
  }
  return { type: 'linear', range, tickvals, ticktext: tickvals.map((v) => String(v)) };
}

function dateXAxis(model, state, env, th, plotPx) {
  const { axis } = dateGeometry(model);
  const blocks = shownBlocks(axis, state.seasons);
  const use = blocks.length ? blocks : axis.blocks;
  const range = blocks.length ? seasonRange(axis, state.seasons) : [0, 1];
  const [lo, hi] = range;
  const ppd = plotPx / Math.max(hi - lo, 1);
  const tickvals = [];
  const ticktext = [];
  if (ppd * 30 >= 30) {
    for (const b of use) {
      for (let day = b.minDay; day <= b.maxDay; day++) {
        const dt = new Date(day * 86400000);
        if (dt.getUTCDate() !== 1) continue;
        tickvals.push(b.start + axis.pad + (day - b.minDay));
        ticktext.push(MONTHS[dt.getUTCMonth()]);
      }
    }
  }
  const shapes = gapDividers(use).map((x) => ({
    type: 'line', xref: 'x', yref: 'paper', x0: x, x1: x, y0: 0, y1: 1, layer: 'below',
    line: { color: DIVIDER[th], width: 1 },
  }));
  const annotations = [];
  const wide = (plotPx / Math.max(use.length, 1)) >= 44;
  for (const b of use) {
    annotations.push({
      xref: 'x', yref: 'paper', x: (b.start + b.end) / 2, y: 0, yanchor: 'top', yshift: -36,
      showarrow: false, font: { size: env.mobile ? 10 : 12, color: MUTED[th] },
      text: wide ? String(b.season) : `'${String(b.season).slice(-2)}`,
    });
  }
  // Nielsen-era bands over whole seasons (alternating fills, label top-left).
  const eras = seasonEras(model);
  const merged = [];
  use.forEach((b, k) => {
    const era = eras.get(b.season);
    if (era == null) return;
    const x0 = k === 0 ? b.start : (use[k - 1].end + b.start) / 2;
    const x1 = k === use.length - 1 ? b.end : (b.end + use[k + 1].start) / 2;
    const last = merged[merged.length - 1];
    if (last && last.era === era && last.lastIdx === k - 1) {
      last.x1 = x1;
      last.lastIdx = k;
    } else merged.push({ era, x0, x1, lastIdx: k });
  });
  merged.forEach((band, k) => {
    if (k % 2 === 0) {
      shapes.push({
        type: 'rect', xref: 'x', yref: 'paper', x0: band.x0, x1: band.x1, y0: 0, y1: 1,
        fillcolor: BAND_FILL[th], line: { width: 0 }, layer: 'below',
      });
    }
    annotations.push({
      xref: 'x', yref: 'paper', x: band.x0, y: 1, xanchor: 'left', yanchor: 'top',
      xshift: 4, yshift: -2 - (env.mobile ? (k % 2) * 13 : 0), showarrow: false, align: 'left',
      text: escapeHover(model.eras[band.era].label),
      font: { size: env.mobile ? 10 : 12, color: MUTED[th] },
    });
  });
  return {
    xaxis: {
      range, tickmode: 'array', tickvals, ticktext, ticks: 'outside', ticklen: 4,
      tickcolor: ZERO_LINE[th], tickangle: 0, tickfont: { size: env.mobile ? 10 : 12, color: MUTED[th] },
      showgrid: false, zeroline: false, fixedrange: true, anchor: 'y2',
    },
    shapes,
    annotations,
  };
}

function marginXAxis(model, th, env) {
  const c = model.cols;
  let hi = 0;
  for (let i = 0; i < model.n; i++) if (c.final_margin[i] != null) hi = Math.max(hi, Math.abs(c.final_margin[i]));
  const top = Math.max(hi + 1, 10);
  const step = niceStep(top, 6);
  const tickvals = [];
  for (let v = 0; v <= top; v += step) tickvals.push(v);
  return {
    xaxis: {
      title: { text: X_TITLE_MARGIN, standoff: 8 },
      range: [-4, top], tickmode: 'array', tickvals, ticktext: tickvals.map(String),
      tickfont: { color: MUTED[th] }, gridcolor: DIVIDER[th], zeroline: false, fixedrange: true, anchor: 'y2',
    },
    shapes: [{
      type: 'line', xref: 'x', yref: 'paper', x0: NA_EDGE, x1: NA_EDGE, y0: 0, y1: 1, layer: 'below',
      line: { color: DIVIDER[th], width: 1 },
    }],
    annotations: [{
      xref: 'x', yref: 'paper', x: NA_X, y: 1, xanchor: 'center', yanchor: 'top', yshift: -2,
      showarrow: false, text: 'N/A', font: { size: env.mobile ? 10 : 12, color: MUTED[th] },
    }],
  };
}

function buildFigure(model, state, env, th, items) {
  const bg = PAGE_BG[th];
  const height = env.mobile ? 440 : 520;
  const margin = { l: env.mobile ? 64 : 84, r: 16, t: 12, b: 64 };
  const plotH = height - margin.t - margin.b;
  const bandGeo = bandLayout(plotH);
  const plotW = Math.max((refs.chart.clientWidth || (env.mobile ? 360 : 1100)) - margin.l - margin.r, 100);
  const isDate = state.scatterX === 'date';
  const yAxis = yAxisFor(model, state.scatterY);
  const xPart = isDate ? dateXAxis(model, state, env, th, plotW) : marginXAxis(model, th, env);

  const build = (subset, yFn, yaxis) => ({
    type: 'scatter',
    mode: 'markers',
    x: subset.map((it) => it.x),
    y: subset.map(yFn),
    yaxis,
    customdata: subset.map((it) => it.i),
    hoverinfo: 'none',
    showlegend: false,
    marker: {
      symbol: 'circle',
      size: subset.map((it) => (it.highlight ? HIGHLIGHT_SIZE : BASE_SIZE)),
      color: subset.map((it) => categoryColor(it.cat.key, th)),
      opacity: subset.map((it) => (it.pass ? 1 : FADED_OPACITY)),
      line: {
        width: subset.map((it) => (it.highlight ? 1.5 : 0)),
        color: ACCENT[th],
      },
    },
  });
  const main = items.filter((it) => !it.band);
  const band = items.filter((it) => it.band);
  const traces = [build(main, (it) => it.y, 'y'), build(band, (it) => bandY(it.i), 'y2')];

  const layout = {
    paper_bgcolor: bg,
    plot_bgcolor: bg,
    font: { family: getComputedStyle(document.body).fontFamily, size: 14, color: ACCENT[th] },
    showlegend: false,
    hovermode: 'closest',
    clickmode: 'event',
    dragmode: false,
    height,
    margin,
    annotations: xPart.annotations,
    shapes: xPart.shapes,
    xaxis: xPart.xaxis,
    yaxis: {
      domain: [bandGeo.logBottom, 1],
      type: yAxis.type,
      title: { text: Y_TITLES[state.scatterY], standoff: 8 },
      range: yAxis.range,
      tickmode: 'array',
      tickvals: yAxis.tickvals,
      ticktext: yAxis.ticktext,
      tickfont: { color: MUTED[th] },
      gridcolor: DIVIDER[th],
      zeroline: false,
      fixedrange: true,
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
  return { traces, layout, yAxis };
}

// ---- contract ----

export function mount(container, ctx) {
  refs.ctx = ctx;
  refs.legend = el('div', 'nfl-legend-row');
  refs.controls = el('div', 'nfl-view-controls');
  buildControls();
  refs.chart = el('div', 'nfl-chart');
  refs.gd = el('div');
  refs.note = el('div', 'season-empty-note');
  refs.note.setAttribute('role', 'status');
  refs.note.hidden = true;
  refs.note.append(
    el('p', 'season-empty-title', 'No NFL games match.'),
    el('p', 'season-empty-hint', 'Widen the season range or reset the filters.'),
  );
  refs.bandButton = el('button', 'band-info');
  refs.bandButton.type = 'button';
  refs.bandButton.hidden = true;
  refs.bandButton.setAttribute('aria-expanded', 'false');
  refs.bandText = el('span', 'band-info-text', 'No public rating');
  const glyph = el('span', 'band-info-glyph', 'i');
  glyph.setAttribute('aria-hidden', 'true');
  refs.bandButton.append(refs.bandText, glyph);
  refs.bandNote = el('div', 'band-note');
  refs.bandNote.hidden = true;
  refs.noteViewers = el('div');
  refs.noteExcitement = el('div');
  refs.noteExcitement.hidden = true;
  refs.bandNote.append(refs.noteViewers, refs.noteExcitement);
  fillBandNote();
  refs.bandButton.setAttribute('aria-controls', 'nfl-scatter-band-note');
  refs.bandNote.id = 'nfl-scatter-band-note';
  initBandInfo({ button: refs.bandButton, note: refs.bandNote });
  refs.chart.append(refs.gd, refs.note, refs.bandButton, refs.bandNote);
  refs.captions = el('div', 'nfl-captions');
  const dataWrap = el('div', 'visually-hidden');
  const dataTable = el('table');
  dataTable.appendChild(el('caption', null, 'Game scatter'));
  const thead = el('thead');
  const hr = el('tr');
  for (const h of ['Matchup', 'Date', 'Category', 'Viewers', 'GEI-style excitement', 'Final margin']) {
    const th = el('th', null, h);
    th.scope = 'col';
    hr.appendChild(th);
  }
  thead.appendChild(hr);
  refs.dataBody = el('tbody');
  dataTable.append(thead, refs.dataBody);
  dataWrap.appendChild(dataTable);
  container.append(refs.legend, refs.controls, refs.chart, refs.captions, dataWrap);
}

export function render(ctx) {
  const model = ctx.model;
  const state = ctx.getState();
  const env = ctx.env();
  const th = theme(env);
  hideTooltip();
  hideHoverRing();

  pressGroup(refs.yGroup, state.scatterY);
  pressGroup(refs.xGroup, state.scatterX);
  renderLegend(th, state);
  renderCaptions();

  const { items, counts, bandCauses } = buildItems(model, state);
  const byGame = new Map(items.map((it) => [it.i, it]));
  const excitement = state.scatterY === 'excitement';
  // Band label and note follow the Y mode; close the note when the mode changes.
  const mode = excitement ? 'excitement' : 'viewers';
  if (refs.bandButton.dataset.yMode && refs.bandButton.dataset.yMode !== mode) {
    closeBandNote({ button: refs.bandButton, note: refs.bandNote });
  }
  refs.bandButton.dataset.yMode = mode;
  refs.bandText.textContent = excitement ? 'No excitement value' : 'No public rating';
  refs.bandButton.setAttribute(
    'aria-label',
    excitement ? 'Why do some games have no excitement value?' : 'Why do some games have no public rating?',
  );
  refs.noteViewers.hidden = excitement;
  refs.noteExcitement.hidden = !excitement;

  current = { items, byGame, counts, bandCauses, env, model, state, axisTitles: null };
  renderDataTable(items, model);

  if (!items.length) {
    refs.drawn = false;
    setEmpty(true);
    return;
  }
  setEmpty(false);
  const fig = buildFigure(model, state, env, th, items);
  current.axisTitles = {
    x: state.scatterX === 'margin' ? X_TITLE_MARGIN : null,
    y: Y_TITLES[state.scatterY],
  };
  current.fig = { yType: fig.yAxis.type };
  refs.bandButton.hidden = counts.band === 0;
  if (counts.band === 0) closeBandNote({ button: refs.bandButton, note: refs.bandNote });
  refs.drawn = true;
  const done = window.Plotly.react(refs.gd, fig.traces, fig.layout, CONFIG);
  bindEvents(refs.gd);
  if (done && typeof done.then === 'function') done.then(placeBandInfo);
}

export function resize() {
  if (refs.drawn && refs.gd && window.Plotly && refs.gd.data) {
    window.Plotly.Plots.resize(refs.gd);
    placeBandInfo();
  }
}

export function testModel() {
  const s = refs.ctx ? refs.ctx.getState() : null;
  const x = s ? s.scatterX : 'date';
  const y = s ? s.scatterY : 'viewers';
  if (!current || !refs.drawn) {
    return {
      view: 'scatter', drawn: false, x, y,
      counts: { plotted: 0, band: 0, faded: 0, hidden: 0, highlighted: 0 },
      bandCauses: { pending: 0, regional: 0, none: 0 },
      axisTitles: null, dateAxis: 'reused', items: [],
    };
  }
  const { items, counts, bandCauses, axisTitles } = current;
  return {
    view: 'scatter',
    drawn: true,
    x,
    y,
    counts: { ...counts },
    bandCauses: { ...bandCauses },
    axisTitles,
    dateAxis: 'reused',
    yType: current.fig.yType,
    bandLabel: refs.bandText.textContent,
    hiddenCategories: [...hiddenCats],
    items: items.map((it) => ({
      i: it.i, band: it.band, na: it.na, faded: !it.pass, highlighted: it.highlight, category: it.cat.key,
    })),
  };
}
