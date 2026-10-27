/**
 * NFL Viewership view (SPORT-09): one line per special-game category over seasons.
 *
 * x = season, y = mean viewers, or (Residual) viewers versus what the matchup
 * quality predicts with +/-1.96 SE whiskers. Window-level categories (Fox AGOTW,
 * CBS late national) draw dashed. Team, Announcers, Booths and Category picks recompute
 * each point's raw mean from the matched games; Residual is never computed in the
 * browser and is forced to Viewers under a pick (R3). Controls, legend,
 * captions and info note reuse the CFB classes and the shared legend detector
 * (D-18). Names enter Plotly strings only through escapeHover; every other
 * string goes through createElement/textContent.
 */
import { placeEraLabels, setEraCaption } from '../era-labels.js';
import { viewershipSeries } from '../state.js';
import { computePicks } from '../picks.js';
import { lowNThreshold, viewershipMode } from '../mode.js';
import { createReasonBar, setReason, linkDisabled } from '../reason-bar.js';
import { viewCategoryStyle } from '../palette.js';
import { ACCENT, MUTED, PAGE_BG, DIVIDER, ZERO_LINE } from '../../../modules/palette.js';
import { frameConfig, frameLayout, referenceLine } from '../../../modules/chart-frame.js';
import { DOT_OPACITY, MARGIN, TICK_FONT_PX } from '../../../modules/chart.js';
import { createOnlyDetector, makeLegendChip } from '../../../modules/legend.js';
import { initBandInfo, closeBandNote } from '../../../modules/band-info.js';
import { currentTheme } from '../../../modules/pill.js';
import { showTextTooltip, hideTooltip } from '../../../modules/tooltip.js';
import { escapeHover, formatMillions, MILLIONS, MINUS } from '../../../modules/format.js';
import { mountViewTools } from '../tools.js';
import { DATA_TABLE_CLASS, rebuildKeepingFocus } from '../data-table.js';

const CONFIG = frameConfig({ zoomable: false });

const TITLES = {
  mean: 'Mean viewers',
  resid: 'Viewers vs. expected for game quality',
};

const BAND_FILL = {
  light: 'rgba(75, 85, 99, 0.06)',
  dark: 'rgba(236, 231, 223, 0.06)',
};

const LINE_WIDTH = 2.5;
const BASE_SIZE = 8;
const WINDOW_NOTE = 'Dashed lines are window-level: one figure covers every game in that Sunday window.';
const MAX_CREWS = 3;

const NOTES = [
  "AGOTW: Fox's top Sunday afternoon game. Window-level figure.",
  "CBS late national: CBS's late Sunday national game. Window-level figure.",
  'SNF, MNF, TNF: Sunday, Monday and Thursday night games. Figures are for the game.',
  'Thanksgiving, Christmas, Black Friday: Holiday games. Few games each year.',
  'International: Games played abroad.',
];

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

const DODGE_STEP = 0.06;

const refs = {
  ctx: null,
  measure: null,
  residButton: null,
  reasonBar: null,
  windowKey: null,
  legend: null,
  bandButton: null,
  bandNote: null,
  chart: null,
  gd: null,
  note: null,
  noteTitle: null,
  noteHint: null,
  captions: null,
  dataBody: null,
  drawn: false,
  bound: false,
};

let current = null; // what the last render drew
let lastPick = { key: null, at: 0 };

function tickLabel(v, signed) {
  const a = Math.abs(v);
  let s;
  if (a === 0) s = '0';
  else if (a < 1e6) s = `${+(a / 1e3).toFixed(1)}K`;
  else s = `${+(a / 1e6).toFixed(2)}${MILLIONS}`;
  if (v < 0) return MINUS + s;
  return signed && v > 0 ? '+' + s : s;
}

function niceStep(range, target) {
  const rough = range / Math.max(target - 1, 1);
  const mag = 10 ** Math.floor(Math.log10(rough));
  const norm = rough / mag;
  return (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10) * mag;
}

function millions(v, signed) {
  const r = Math.round(v);
  if (r === 0) return '0';
  const body = formatMillions(Math.abs(r));
  if (r < 0) return MINUS + body;
  return signed ? `+${body}` : body;
}

/** Distinct "Pbp / Analyst" labels over a point's games, most games first. */
function crewLabels(model, gameList) {
  const c = model.cols;
  const counts = new Map();
  for (const g of gameList || []) {
    const crew = c.crew[g] || [];
    const pbp = crew.find((m) => m.role === 'pbp');
    const analyst = crew.find((m) => m.role === 'analyst');
    const label = [pbp, analyst]
      .filter((m) => m != null)
      .map((m) => model.people[m.person].name)
      .join(' / ');
    if (!label) continue;
    counts.set(label, (counts.get(label) || 0) + 1);
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0))
    .map(([label]) => label);
}

// ---- category hide/show rules (shared by chips and the picker) ----

function presentIds(series) {
  return series.filter((s) => s.points.length).map((s) => s.id);
}

function shownFrom(present, hidden) {
  const h = new Set(hidden);
  return present.filter((id) => !h.has(id));
}

/** The series the chart and legend draw: under a pick, Category or Team each point is recounted to its matched games. */
function recountedSeries(model, state) {
  const threshold = lowNThreshold(model);
  const picks = computePicks(model, state);
  const subset = picks.hasPick || state.cats.length > 0 || state.teams.length > 0;
  const series = viewershipSeries(model, state);
  if (subset) {
    const viewers = model.cols.viewers;
    for (const s of series) {
      s.points = s.points
        .map((p) => {
          let sum = 0;
          let count = 0;
          const gameList = [];
          for (const g of p.gameList || []) {
            if (picks.matched[g] !== 1 || viewers[g] == null) continue;
            sum += viewers[g];
            count++;
            gameList.push(g);
          }
          // gameList follows the recount so hover crews, the Crew column, the click and the probe agree with n.
          return { ...p, gameList, mean: count ? sum / count : null, games: count, lowN: count < threshold };
        })
        .filter((p) => p.games > 0);
    }
  }
  return series;
}

function onlyPatch(key, before) {
  const { ctx } = refs;
  const present = presentIds(recountedSeries(ctx.model, ctx.getState()));
  const shown = shownFrom(present, before || []);
  if (shown.length === 1 && shown[0] === key) return { hiddenCategories: [] };
  return { hiddenCategories: present.filter((id) => id !== key) };
}

function toggleCategory(key) {
  const cur = new Set(refs.ctx.getState().hiddenCategories);
  if (cur.has(key)) cur.delete(key);
  else cur.add(key);
  refs.ctx.setState({ hiddenCategories: [...cur] });
}

const detector = createOnlyDetector({
  onToggle: toggleCategory,
  onOnly: (key, before) => refs.ctx.setState(onlyPatch(key, before)),
  snapshot: () => [...refs.ctx.getState().hiddenCategories],
});

// ---- selection and hover ----

function pick(item) {
  const now = Date.now();
  if (lastPick.key === item.key && now - lastPick.at < 500) return;
  lastPick = { key: item.key, at: now };
  refs.ctx.selectGames({
    kind: 'viewership',
    key: item.key,
    label: `${item.label}, ${item.p.season}`,
    games: item.p.gameList,
  });
}

function valueText(eff, v) {
  if (v == null) return 'not available';
  return millions(v, eff === 'resid');
}

function hoverLines(item) {
  const { model } = current;
  const p = item.p;
  const resid = current.eff === 'resid';
  const lines = [
    { text: `${item.label}${item.windowLevel ? ', window-level' : ''}`, kind: 'title' },
    { text: `${p.season}, ${model.eras[p.era].label}`, kind: 'body' },
    { text: `${resid ? 'Residual' : 'Viewers'}: ${valueText(current.eff, item.y)}`, kind: 'body' },
  ];
  if (resid && item.y != null && item.err == null) {
    lines.push({ text: '±1.96 standard errors: not available', kind: 'body' });
  }
  lines.push({ text: `${p.games} games`, kind: 'body' });
  const crews = crewLabels(model, p.gameList);
  if (crews.length) {
    lines.push({ text: 'Crews:', kind: 'body' });
    for (const c of crews.slice(0, MAX_CREWS)) lines.push({ text: c, kind: 'body' });
    if (crews.length > MAX_CREWS) lines.push({ text: `and ${crews.length - MAX_CREWS} more`, kind: 'body' });
  }
  if (p.lowN) lines.push({ text: 'low n: Few games, so treat with care.', kind: 'body' });
  lines.push({ text: 'Click to list games.', kind: 'hint' });
  return lines;
}

function bindEvents(gd) {
  if (refs.bound) return;
  refs.bound = true;
  gd.on('plotly_click', (ev) => {
    const k = ev.points && ev.points[0] ? ev.points[0].customdata : null;
    if (current && Number.isInteger(k) && current.items[k]) pick(current.items[k]);
  });
  gd.on('plotly_hover', (ev) => {
    const k = ev.points && ev.points[0] ? ev.points[0].customdata : null;
    if (!current || !Number.isInteger(k) || !current.items[k]) return;
    if (current.env.mobile || current.env.hoverNone) return;
    const e = ev.event || {};
    showTextTooltip(hoverLines(current.items[k]), {
      theme: current.theme,
      borderColor: ACCENT[current.theme],
      clientX: e.clientX ?? 0,
      clientY: e.clientY ?? 0,
    });
  });
  gd.on('plotly_unhover', () => hideTooltip());
}

// ---- controls ----

function buildControls() {
  const { ctx } = refs;
  const controls = el('div', 'chart-controls nfl-viewership-controls');

  const measureGroup = el('div', 'axis-group');
  measureGroup.appendChild(el('span', 'axis-caption', 'Measure'));
  refs.measure = el('div', 'segmented');
  refs.measure.setAttribute('role', 'group');
  refs.measure.setAttribute('aria-label', 'Measure');
  for (const o of [
    { key: 'mean', label: 'Viewers' },
    { key: 'resid', label: 'Residual' },
  ]) {
    const b = el('button', null, o.label);
    b.type = 'button';
    b.dataset.value = o.key;
    if (o.key === 'resid') refs.residButton = b;
    b.addEventListener('click', () => {
      if (b.getAttribute('aria-disabled') === 'true') return;
      ctx.setState({ viewY: o.key });
    });
    refs.measure.appendChild(b);
  }
  measureGroup.appendChild(refs.measure);
  controls.append(measureGroup);
  return controls;
}

function renderLegend(series, state, th) {
  const present = series.filter((s) => s.points.length);
  const shown = shownFrom(present.map((s) => s.id), state.hiddenCategories);
  const items = present.map((s) => {
    const st = viewCategoryStyle(s.id, th);
    const on = shown.includes(s.id);
    const li = el('li');
    const sole = shown.length === 1 && shown[0] === s.id;
    let hint = sole ? 'Double-click to show all' : `Double-click to show only ${s.label}`;
    if (s.windowLevel) hint += ' (window-level)';
    // The shared outlined chip with a colour dot (U6), as on CFB and MLB.
    const b = makeLegendChip({ label: s.label, color: st.color, pressed: on, hint, data: { category: s.id } });
    li.appendChild(b);
    return li;
  });
  refs.legend.replaceChildren(...items);
}

function buildLegendRow() {
  const row = el('div', 'legend-row nfl-viewership-legend');
  refs.legend = el('ul', 'legend-chips');
  refs.legend.setAttribute('aria-label', 'Categories: select to show or hide');
  refs.legend.addEventListener('click', (ev) => {
    const button = ev.target.closest('button[data-category]');
    if (!button) {
      detector.reset();
      return;
    }
    detector.click(ev, button.dataset.category);
  });

  const wrap = el('span', 'nfl-band-info-wrap');
  const btn = el('button', 'band-info');
  btn.type = 'button';
  btn.id = 'nfl-viewership-info';
  btn.setAttribute('aria-label', 'About these lines');
  btn.setAttribute('aria-expanded', 'false');
  btn.setAttribute('aria-controls', 'nfl-viewership-note');
  const glyph = el('span', 'band-info-glyph', 'i');
  glyph.setAttribute('aria-hidden', 'true');
  btn.appendChild(glyph);
  const note = el('div', 'band-note');
  note.id = 'nfl-viewership-note';
  note.hidden = true;
  const ul = el('ul');
  for (const line of NOTES) ul.appendChild(el('li', null, line));
  note.append(ul, el('p', null, 'Lines with few games are faded and marked low n.'));
  wrap.append(btn, note);
  refs.bandButton = btn;
  refs.bandNote = note;
  initBandInfo({ button: btn, note });
  refs.windowKey = el('ul', 'nfl-window-key');
  refs.windowKey.setAttribute('aria-label', 'Line styles');
  for (const [dashed, text] of [[false, 'one game'], [true, 'whole Sunday window']]) {
    const li = el('li');
    const sw = el('span', dashed ? 'swatch is-dashed' : 'swatch');
    sw.setAttribute('aria-hidden', 'true');
    li.append(sw, document.createTextNode(text));
    refs.windowKey.appendChild(li);
  }
  row.append(refs.legend, refs.windowKey, wrap);
  return row;
}

function link(text, href) {
  const a = el('a', null, text);
  a.href = href;
  a.rel = 'noopener noreferrer';
  return a;
}

function renderSubtitle(anyWindow, state) {
  const { ctx } = refs;
  if (anyWindow) {
    const a = link('methodology', ctx.methodologyHref('nfl-window-level-viewership'));
    ctx.setSubtitle([
      document.createTextNode(`${WINDOW_NOTE} Regional games have no published figure; see `),
      a,
      document.createTextNode('.'),
    ]);
  } else {
    const [lo, hi] = state.seasons;
    ctx.setSubtitle([document.createTextNode(lo === hi ? `Season ${lo}` : `Seasons ${lo}–${hi}`)]);
  }
}

function renderCaptions(effective) {
  const kids = [];
  if (effective === 'resid') {
    kids.push(el('p', 'caption', 'Residuals compare seasons within one category, not categories with each other.'));
  }
  const era = el('p', 'caption');
  era.append(
    document.createTextNode(
      'Nielsen changed how it measures viewing in 2020, 2025, and 2026, so compare seasons with care; see ',
    ),
    link('methodology', refs.ctx.methodologyHref('measurement-eras')),
    document.createTextNode('.'),
  );
  kids.push(era);
  refs.captions.replaceChildren(...kids);
}

function renderDataTable(items, eff) {
  const { dataBody } = refs;
  rebuildKeepingFocus(dataBody, () => {
    dataBody.replaceChildren();
    for (const it of items) {
      const tr = el('tr');
      const th = el('th');
      th.scope = 'row';
      const btn = el('button', null, `${it.label}, ${it.p.season}`);
      btn.type = 'button';
      btn.dataset.key = it.key;
      btn.setAttribute('aria-label', `Select ${it.label}, ${it.p.season}`);
      btn.addEventListener('click', () => pick(it));
      th.appendChild(btn);
      tr.append(
        th,
        el('td', null, it.y == null ? 'n/a' : valueText(eff, it.y)),
        el('td', null, `${it.p.games} games`),
        el('td', null, crewLabels(current.model, it.p.gameList).join('; ')),
      );
      dataBody.appendChild(tr);
    }
  });
}

function setNote(title, hint) {
  const show = title != null;
  refs.note.hidden = !show;
  refs.gd.hidden = show;
  if (show) {
    refs.noteTitle.textContent = title;
    refs.noteHint.textContent = hint;
  }
}

// ---- figure ----

function buildFigure(model, state, env, th, lines, seasonPoints) {
  const resid = current.eff === 'resid';
  const size = env.mobile ? 10 : BASE_SIZE;
  const traces = lines.map((ln) => {
    const trace = {
      type: 'scatter',
      mode: 'lines+markers',
      name: ln.label,
      x: ln.items.map((it) => it.p.season + (resid ? ln.dodge : 0)),
      y: ln.items.map((it) => it.y),
      customdata: ln.items.map((it) => it.k),
      hoverinfo: 'none',
      connectgaps: false,
      line: { color: ln.color, width: LINE_WIDTH, ...(ln.windowLevel ? { dash: 'dash' } : {}) },
      marker: {
        symbol: ln.items.map((it) => (it.p.lowN ? `${ln.symbol}-open` : ln.symbol)),
        size,
        color: ln.color,
        opacity: ln.items.map((it) => (it.p.lowN ? DOT_OPACITY.activeUnderPerson : 1)),
        line: {
          color: ln.color,
          width: ln.items.map((it) => (it.p.lowN ? 2 : 0)),
        },
      },
    };
    if (resid) {
      trace.error_y = {
        type: 'data',
        array: ln.items.map((it) => (it.err == null ? NaN : it.err)),
        visible: true,
        color: ln.color,
        thickness: 1,
        width: 2,
      };
    }
    return trace;
  });

  // Era bands over whole seasons.
  const bandMap = new Map();
  for (const p of seasonPoints) {
    const b = bandMap.get(p.era);
    if (!b) bandMap.set(p.era, { era: p.era, from: p.season - 0.5, to: p.season + 0.5 });
    else {
      b.from = Math.min(b.from, p.season - 0.5);
      b.to = Math.max(b.to, p.season + 0.5);
    }
  }
  const seasonsAll = [...new Set(seasonPoints.map((p) => p.season))].sort((a, b) => a - b);
  const first = seasonsAll[0];
  const last = seasonsAll[seasonsAll.length - 1];
  const eraRange = [first - 0.5, last + 0.5];
  const fontPx = env.mobile ? TICK_FONT_PX.mobile : TICK_FONT_PX.desktop;
  const left = env.mobile ? 64 : MARGIN.l + 14;
  const plotPx = Math.max((refs.chart.clientWidth || (env.mobile ? 360 : 1100)) - left - 16, 100);
  const bands = [...bandMap.values()].sort((a, b) => a.from - b.from);
  const shapes = [];
  const annotations = [];
  const places = placeEraLabels(
    bands.map((b) => ({ text: model.eras[b.era].label, x0: b.from })),
    eraRange,
    plotPx,
    fontPx,
  );
  bands.forEach((b, k) => {
    if (k % 2 === 0) {
      shapes.push({
        type: 'rect', xref: 'x', yref: 'paper', x0: b.from, x1: b.to, y0: 0, y1: 1,
        fillcolor: BAND_FILL[th], line: { width: 0 }, layer: 'below',
      });
    }
    const pos = places[k];
    if (!pos) return;
    annotations.push({
      xref: 'x', yref: 'paper', x: pos.x, y: 1, xanchor: pos.xanchor, yanchor: 'top',
      xshift: pos.xshift, yshift: -2, showarrow: false, align: pos.xanchor,
      text: escapeHover(pos.text), font: { size: fontPx, color: MUTED[th] },
    });
  });
  if (resid) {
    shapes.push(referenceLine({ xref: 'paper', yref: 'y', x0: 0, x1: 1, y0: 0, y1: 0 }, th));
  }

  let lo = 0;
  let hi = 0;
  let any = false;
  for (const ln of lines) {
    for (const it of ln.items) {
      if (it.y == null) continue;
      any = true;
      const e = it.err || 0;
      lo = Math.min(lo, it.y - e);
      hi = Math.max(hi, it.y + e);
    }
  }
  if (!any) hi = 1;
  const pad = (hi - lo || 1) * 0.1;
  const range = [resid ? lo - pad : 0, hi + pad];
  const step = niceStep(range[1] - range[0], 6);
  const tickvals = [];
  for (let v = Math.ceil(range[0] / step) * step; v <= range[1] + step * 1e-9; v += step) {
    tickvals.push(Math.round(v * 1e3) / 1e3);
  }

  const bg = PAGE_BG[th];
  const layout = {
    font: { size: 14, color: ACCENT[th] },
    hovermode: 'closest',
    clickmode: 'event',
    dragmode: false,
    height: env.mobile ? 420 : 480,
    margin: { l: left, r: 16, t: 12, b: 56 },
    annotations,
    shapes,
    xaxis: {
      range: eraRange,
      tickmode: 'array',
      tickvals: seasonsAll,
      ticktext: seasonsAll.map(String),
      tickfont: { size: fontPx, color: MUTED[th] },
      showgrid: false,
      zeroline: false,
      fixedrange: true,
    },
    yaxis: {
      title: { text: TITLES[resid ? 'resid' : 'mean'], standoff: 8, font: { size: 14 } },
      range,
      tickmode: 'array',
      tickvals,
      ticktext: tickvals.map((v) => tickLabel(v, resid)),
      tickfont: { size: fontPx, color: MUTED[th] },
      gridcolor: DIVIDER[th],
      zeroline: false,
      fixedrange: true,
    },
  };
  return { traces, layout: frameLayout(layout, { theme: th }), bands, eraLabels: bands.map((b) => model.eras[b.era].label) };
}

// ---- contract ----

export function mount(container, ctx) {
  refs.ctx = ctx;
  const controls = buildControls();
  const legendRow = buildLegendRow();
  refs.chart = el('div', 'nfl-chart');
  refs.gd = el('div');
  refs.note = el('div', 'season-empty-note');
  refs.note.setAttribute('role', 'status');
  refs.noteTitle = el('p', 'season-empty-title');
  refs.noteHint = el('p', 'season-empty-hint');
  refs.note.append(refs.noteTitle, refs.noteHint);
  refs.note.hidden = true;
  refs.chart.append(refs.gd, refs.note);
  refs.captions = el('div', 'nfl-captions');
  const dataWrap = el('div', DATA_TABLE_CLASS);
  const dataTable = el('table');
  dataTable.appendChild(el('caption', null, 'Viewership by category'));
  const thead = el('thead');
  const hr = el('tr');
  for (const h of ['Category and season', 'Value', 'Games', 'Crews']) {
    const th = el('th', null, h);
    th.scope = 'col';
    hr.appendChild(th);
  }
  thead.appendChild(hr);
  refs.dataBody = el('tbody');
  dataTable.append(thead, refs.dataBody);
  dataWrap.appendChild(dataTable);
  refs.reasonBar = createReasonBar('nfl-reason-viewership');
  container.append(refs.reasonBar, legendRow, refs.chart, refs.captions, dataWrap);
  mountViewTools(ctx, 'viewership', [controls], container);
}

export function render(ctx) {
  const { model } = ctx;
  const state = ctx.getState();
  const env = ctx.env();
  const th = currentTheme();
  hideTooltip();
  closeBandNote({ button: refs.bandButton, note: refs.bandNote });

  const mode = viewershipMode(state);
  const eff = mode.effective;
  for (const b of refs.measure.querySelectorAll('button')) {
    b.setAttribute('aria-pressed', String(b.dataset.value === eff));
  }
  linkDisabled(refs.residButton, refs.reasonBar, mode.forced);
  setReason(refs.reasonBar, mode.reason);

  const series = recountedSeries(model, state);
  renderLegend(series, state, th);

  const resid = eff === 'resid';
  const present = series.filter((s) => s.points.length);
  const hidden = new Set(state.hiddenCategories);
  const shown = present.filter((s) => !hidden.has(s.id));
  // The Fox AGOTW line is drawn last so it sits on top.
  const ordered = [...shown.filter((s) => s.id !== 'agotw'), ...shown.filter((s) => s.id === 'agotw')];

  const items = [];
  // Residual mode: each line's points sit slightly left or right of the season tick, so their
  // whiskers do not stack on one vertical (DODGE_STEP per line, kept inside the season band).
  const dodgeStep = Math.min(DODGE_STEP, 0.7 / Math.max(ordered.length, 1));
  const lines = ordered.map((s, k) => {
    const st = viewCategoryStyle(s.id, th);
    const dodge = (k - (ordered.length - 1) / 2) * dodgeStep;
    const ln = { id: s.id, label: s.label, windowLevel: s.windowLevel, color: st.color, symbol: st.symbol, dodge, items: [] };
    for (const p of s.points) {
      const y = resid ? p.resid : p.mean;
      const it = {
        k: items.length,
        p,
        id: s.id,
        label: s.label,
        windowLevel: s.windowLevel,
        key: `${s.id}:${p.season}`,
        y: y == null ? null : y,
        err: resid && y != null && p.se != null ? 1.96 * p.se : null,
      };
      items.push(it);
      ln.items.push(it);
    }
    return ln;
  });
  current = { items, lines, env, theme: th, state, model, bands: [], eff, mode, anyWindow: false };
  renderDataTable(items, eff);
  const anyWindow = lines.some((l) => l.windowLevel);
  current.anyWindow = anyWindow;
  renderSubtitle(anyWindow, state);
  refs.windowKey.classList.toggle('is-reserved', !anyWindow);
  if (anyWindow) refs.windowKey.removeAttribute('aria-hidden');
  else refs.windowKey.setAttribute('aria-hidden', 'true');
  renderCaptions(eff);

  if (!present.length) {
    refs.drawn = false;
    setNote('No games match these filters', 'Clear all filters, or widen the Seasons range.');
    return;
  }
  if (!shown.length) {
    refs.drawn = false;
    setNote('No categories shown.', 'Turn on a category above.');
    return;
  }
  setNote(null);
  const seasonPoints = present.flatMap((s) => s.points);
  const fig = buildFigure(model, state, env, th, lines, seasonPoints);
  current.bands = fig.bands;
  refs.drawn = true;
  setEraCaption(refs.captions, fig.eraLabels, env.mobile);
  // The container follows the figure height (rows x pitch + margins), not the 520px CSS minimum,
  // so a short chart leaves no blank band below the plot.
  refs.chart.style.minHeight = `${fig.layout.height}px`;
  window.Plotly.react(refs.gd, fig.traces, fig.layout, CONFIG);
  bindEvents(refs.gd);
}

export function resize() {
  if (refs.drawn && refs.gd && window.Plotly && refs.gd.data) window.Plotly.Plots.resize(refs.gd);
}

export function testModel() {
  const s = refs.ctx ? refs.ctx.getState() : null;
  const viewY = current ? current.eff : s ? s.viewY : 'mean';
  if (!current) return { view: 'viewership', drawn: false, viewY, categories: [] };
  const { items, lines, model, bands } = current;
  return {
    view: 'viewership',
    drawn: refs.drawn,
    viewY,
    mode: { stored: current.mode.stored, effective: current.mode.effective, reason: current.mode.reason },
    subtitle: document.getElementById('nfl-chart-subtitle')?.textContent ?? '',
    subtitleHref: document.querySelector('#nfl-chart-subtitle a')?.getAttribute('href') ?? null,
    windowKey: {
      shown: !refs.windowKey.classList.contains('is-reserved'),
      labels: [...refs.windowKey.querySelectorAll('li')].map((li) => li.textContent),
    },
    axisTitle: TITLES[viewY],
    bands: bands.map((b) => ({ era: model.eras[b.era].label, from: b.from, to: b.to })),
    categories: lines.map((ln) => ({
      id: ln.id,
      label: ln.label,
      windowLevel: ln.windowLevel,
      hidden: false,
      points: ln.items.map((it) => ({
        season: it.p.season,
        y: it.y,
        err: it.err,
        lowN: it.p.lowN,
        n: it.p.games,
        games: it.p.gameList.length,
      })),
    })),
    hiddenIds: s ? s.hiddenCategories : [],
    order: items.map((it) => it.id),
  };
}
