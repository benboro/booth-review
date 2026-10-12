/**
 * NFL view 3: AGOTW viewership (D-15).
 *
 * One line over seasons: x = season, y = mean AGOTW viewers, or (Residual)
 * viewers versus what the matchup quality predicts with +/-1.96 SE whiskers.
 * The line is split into one trace per crew segment (color and marker from
 * crewStyle), joined by a dashed connector, over alternating Nielsen-era
 * bands. Only AGOTW games are in the data; the view says so, and says the
 * figures are window-level and unnormalized. Names enter Plotly strings only
 * through escapeHover; chips, tooltip, captions and the hidden table use
 * createElement/textContent.
 */
import { agotwSeries } from '../state.js';
import { crewStyle } from '../palette.js';
import { ACCENT, MUTED, PAGE_BG, DIVIDER, ZERO_LINE } from '../../../modules/palette.js';
import { showTextTooltip, hideTooltip } from '../../../modules/tooltip.js';
import { escapeHover, formatViewers, MINUS } from '../../../modules/format.js';

const CONFIG = {
  responsive: true,
  displayModeBar: false,
  displaylogo: false,
  scrollZoom: false,
  showLink: false,
  showSendToCloud: false,
  showEditInChartStudio: false,
};

const TITLES = {
  mean: 'Mean AGOTW viewers',
  resid: 'Viewers vs. expected for game quality',
};

const BAND_FILL = {
  light: 'rgba(75, 85, 99, 0.06)',
  dark: 'rgba(156, 163, 175, 0.10)',
};

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

const refs = {
  ctx: null,
  legend: null,
  controls: null,
  yGroup: null,
  chart: null,
  gd: null,
  note: null,
  captions: null,
  dataBody: null,
  drawn: false,
  bound: false,
};

let current = null; // what the last render drew

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

function personName(model, idx) {
  return idx == null ? null : model.people[idx].name;
}

function crewLabel(model, p) {
  return [personName(model, p.pbp), personName(model, p.analyst)].filter((n) => n != null).join(' / ');
}

/** '2M', '500K', '1.5M'; signed with U+2212 for negatives when `signed`. */
function tickLabel(v, signed) {
  const a = Math.abs(v);
  let s;
  if (a === 0) s = '0';
  else if (a < 1e6) s = `${+(a / 1e3).toFixed(1)}K`;
  else s = `${+(a / 1e6).toFixed(2)}M`;
  if (v < 0) return MINUS + s;
  return signed && v > 0 ? '+' + s : s;
}

function niceStep(range, target) {
  const rough = range / Math.max(target - 1, 1);
  const mag = 10 ** Math.floor(Math.log10(rough));
  const norm = rough / mag;
  return (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10) * mag;
}

function valueText(state, v) {
  if (v == null) return 'not available';
  if (state.agotwY === 'resid') {
    const r = Math.round(v);
    if (r === 0) return '0';
    return (r < 0 ? MINUS : '+') + formatViewers(Math.abs(r));
  }
  return formatViewers(Math.round(v));
}

function hasSelectedPerson(model, state, p) {
  if (!state.people.length) return false;
  const ids = new Set(state.people);
  return [p.pbp, p.analyst].some((i) => i != null && model.people[i] && ids.has(model.people[i].id));
}

// ---- selection ----

let lastToggle = { key: null, at: 0 };

function pick(item) {
  const { ctx } = refs;
  // A touch tap reaches Plotly as touchend and again as the emulated mouseup.
  const now = Date.now();
  if (lastToggle.key === item.key && now - lastToggle.at < 500) return;
  lastToggle = { key: item.key, at: now };
  ctx.selectGames({
    kind: 'agotw',
    key: item.key,
    label: `${item.p.season} AGOTW`,
    games: item.p.gameList,
  });
}

function hoverLines(item) {
  const { state, model } = current;
  const p = item.p;
  const resid = state.agotwY === 'resid';
  const lines = [
    { text: `${p.season} · ${crewLabel(model, p)}`, kind: 'title' },
    {
      text: resid
        ? `Viewers vs. expected: ${valueText(state, item.y)}`
        : `Mean AGOTW viewers: ${valueText(state, item.y)}`,
      kind: 'body',
    },
  ];
  lines.push({
    text: `${p.games} games${p.fillIn > 0 ? `; ${p.fillIn} fill-in` : ''}`,
    kind: 'body',
  });
  lines.push({ text: `Measured under: ${model.eras[p.era].label}`, kind: 'body' });
  lines.push({ text: 'Window-level, unnormalized', kind: 'body' });
  if (p.lowN) {
    lines.push({
      text: `Fewer than ${model.constants.low_n_threshold} games. Read with care.`,
      kind: 'body',
    });
  }
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
      theme: theme(current.env),
      borderColor: ACCENT[theme(current.env)],
      clientX: e.clientX ?? 0,
      clientY: e.clientY ?? 0,
    });
  });
  gd.on('plotly_unhover', () => hideTooltip());
}

// ---- controls, legend, captions, table ----

function buildControls() {
  const { ctx } = refs;
  refs.yGroup = el('div', 'segmented');
  refs.yGroup.setAttribute('role', 'group');
  refs.yGroup.setAttribute('aria-label', 'Y axis');
  for (const o of [
    { key: 'mean', label: 'Mean viewers' },
    { key: 'resid', label: 'vs. expected for game quality' },
  ]) {
    const b = el('button', null, o.label);
    b.type = 'button';
    b.dataset.value = o.key;
    b.addEventListener('click', () => ctx.setState({ agotwY: o.key }));
    refs.yGroup.appendChild(b);
  }
  refs.controls.appendChild(refs.yGroup);
}

function renderLegend(crews, hidden, th) {
  const { ctx, legend } = refs;
  const chips = crews.map((c) => {
    const b = el('button', 'legend-chip pill', c.label);
    b.type = 'button';
    b.dataset.crew = c.crewKey;
    const on = !hidden.has(c.crewKey);
    b.setAttribute('aria-pressed', String(on));
    b.style.borderColor = c.color;
    if (on) {
      b.style.backgroundColor = c.color;
      b.style.color = textOn(c.color);
    }
    b.addEventListener('click', () => {
      const cur = new Set(ctx.getState().hiddenCrews);
      if (cur.has(c.crewKey)) cur.delete(c.crewKey);
      else cur.add(c.crewKey);
      ctx.setState({ hiddenCrews: [...cur] });
    });
    return b;
  });
  legend.replaceChildren(...chips);
  void th;
}

function link(text, href) {
  const a = el('a', null, text);
  a.href = href;
  a.rel = 'noopener noreferrer';
  return a;
}

function renderCaptions() {
  const { ctx, captions } = refs;
  const first = el('p');
  first.append(
    link('Window-level', ctx.methodologyHref('nfl-window-level-viewership')),
    document.createTextNode(', unnormalized viewers. Only AGOTW games are compared.'),
  );
  const second = el('p');
  second.append(
    document.createTextNode(
      'Nielsen changed how it measures viewing in 2020, 2025, and 2026, so compare seasons with care; see ',
    ),
    link('methodology', ctx.methodologyHref('nfl-measurement-eras')),
    document.createTextNode('.'),
  );
  captions.replaceChildren(first, second);
}

function renderDataTable(items, state) {
  const { dataBody } = refs;
  const { model } = current;
  dataBody.replaceChildren();
  for (const it of items) {
    const tr = el('tr');
    const th = el('th', null, String(it.p.season));
    th.scope = 'row';
    tr.append(
      th,
      el('td', null, crewLabel(model, it.p)),
      el('td', null, it.y == null ? 'n/a' : valueText(state, it.y)),
      el('td', null, model.eras[it.p.era].label),
    );
    dataBody.appendChild(tr);
  }
}

function setNote(show) {
  refs.note.hidden = !show;
  refs.gd.hidden = show;
}

// ---- figure ----

function buildFigure(model, state, env, th, drawnSegments, seasonsAll, items) {
  const resid = state.agotwY === 'resid';
  const bg = PAGE_BG[th];
  const size = env.mobile ? 10 : 8;
  const traces = [];

  // Ring underlay for points whose crew includes a selected announcer.
  const ringItems = items.filter((it) => it.ring && it.y != null);
  const rings = {
    type: 'scatter',
    mode: 'markers',
    name: 'Selected',
    x: ringItems.map((it) => it.p.season),
    y: ringItems.map((it) => it.y),
    hoverinfo: 'skip',
    marker: { symbol: 'circle-open', size: size + 9, color: ACCENT[th], line: { color: ACCENT[th], width: 1.5 } },
  };
  traces.push(rings);

  // Connectors (dashed) between consecutive drawn segments.
  const cx = [];
  const cy = [];
  for (let k = 1; k < drawnSegments.length; k++) {
    const a = drawnSegments[k - 1].points.at(-1);
    const b = drawnSegments[k].points[0];
    const ya = resid ? a.values.resid : a.values.mean;
    const yb = resid ? b.values.resid : b.values.mean;
    if (ya == null || yb == null) continue;
    cx.push(a.season, b.season, null);
    cy.push(ya, yb, null);
  }
  traces.push({
    type: 'scatter',
    mode: 'lines',
    name: 'Crew change',
    x: cx,
    y: cy,
    hoverinfo: 'skip',
    connectgaps: false,
    line: { color: DIVIDER[th], width: 1, dash: 'dash' },
  });

  let idx = 0;
  for (const seg of drawnSegments) {
    const segItems = items.slice(idx, idx + seg.points.length);
    idx += seg.points.length;
    const trace = {
      type: 'scatter',
      mode: 'lines+markers',
      name: seg.label,
      x: segItems.map((it) => it.p.season),
      y: segItems.map((it) => it.y),
      customdata: segItems.map((it) => it.k),
      hoverinfo: 'none',
      connectgaps: false,
      line: { color: seg.color, width: 2 },
      marker: {
        symbol: seg.symbol,
        size,
        color: segItems.map((it) => (it.p.lowN ? 'rgba(0,0,0,0)' : seg.color)),
        opacity: segItems.map((it) => (it.p.lowN ? 0.5 : 1)),
        line: { color: seg.color, width: segItems.map((it) => (it.p.lowN ? 2 : 0)) },
      },
    };
    if (resid) {
      trace.error_y = {
        type: 'data',
        array: segItems.map((it) => (it.err == null ? 0 : it.err)),
        visible: true,
        color: MUTED[th],
        thickness: 1.5,
        width: 4,
      };
    }
    traces.push(trace);
  }

  // Era bands over whole seasons.
  const bandMap = new Map();
  for (const s of seasonsAll) {
    const b = bandMap.get(s.era);
    if (!b) bandMap.set(s.era, { era: s.era, from: s.season - 0.5, to: s.season + 0.5 });
    else {
      b.from = Math.min(b.from, s.season - 0.5);
      b.to = Math.max(b.to, s.season + 0.5);
    }
  }
  const bands = [...bandMap.values()].sort((a, b) => a.from - b.from);
  const shapes = [];
  const annotations = [];
  bands.forEach((b, k) => {
    if (k % 2 === 0) {
      shapes.push({
        type: 'rect', xref: 'x', yref: 'paper', x0: b.from, x1: b.to, y0: 0, y1: 1,
        fillcolor: BAND_FILL[th], line: { width: 0 }, layer: 'below',
      });
    }
    annotations.push({
      xref: 'x', yref: 'paper', x: b.from, y: 1, xanchor: 'left', yanchor: 'top',
      xshift: 4, yshift: -2 - (env.mobile ? (k % 2) * 13 : 0), showarrow: false, align: 'left',
      text: escapeHover(model.eras[b.era].label), font: { size: env.mobile ? 10 : 12, color: MUTED[th] },
    });
  });
  if (resid) {
    shapes.push({ type: 'line', xref: 'paper', yref: 'y', x0: 0, x1: 1, y0: 0, y1: 0, line: { color: ZERO_LINE[th], width: 1.5 } });
  }

  // y range and ticks.
  let lo = 0;
  let hi = 0;
  let any = false;
  for (const it of items) {
    if (it.y == null) continue;
    any = true;
    const e = it.err || 0;
    lo = Math.min(lo, it.y - e);
    hi = Math.max(hi, it.y + e);
  }
  if (!any) hi = 1;
  const pad = (hi - lo || 1) * 0.1;
  const range = [resid ? lo - pad : 0, hi + pad];
  const step = niceStep(range[1] - range[0], 6);
  const tickvals = [];
  for (let v = Math.ceil(range[0] / step) * step; v <= range[1] + step * 1e-9; v += step) {
    tickvals.push(Math.round(v * 1e3) / 1e3);
  }

  const first = Math.min(...seasonsAll.map((s) => s.season));
  const last = Math.max(...seasonsAll.map((s) => s.season));
  const seasonTicks = [...new Set(seasonsAll.map((s) => s.season))].sort((a, b) => a - b);
  const font = { family: getComputedStyle(document.body).fontFamily, size: 14, color: ACCENT[th] };
  const layout = {
    paper_bgcolor: bg,
    plot_bgcolor: bg,
    font,
    showlegend: false,
    hovermode: 'closest',
    clickmode: 'event',
    dragmode: false,
    height: env.mobile ? 420 : 480,
    margin: { l: env.mobile ? 64 : 84, r: 16, t: 12, b: 56 },
    annotations,
    shapes,
    xaxis: {
      range: [first - 0.5, last + 0.5],
      tickmode: 'array',
      tickvals: seasonTicks,
      ticktext: seasonTicks.map(String),
      tickfont: { color: MUTED[th] },
      showgrid: false,
      zeroline: false,
      fixedrange: true,
    },
    yaxis: {
      title: { text: TITLES[resid ? 'resid' : 'mean'], standoff: 8 },
      range,
      tickmode: 'array',
      tickvals,
      ticktext: tickvals.map((v) => tickLabel(v, resid)),
      tickfont: { color: MUTED[th] },
      gridcolor: DIVIDER[th],
      zeroline: false,
      fixedrange: true,
    },
  };
  return { traces, layout, bands };
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
  refs.note.append(
    el('p', 'season-empty-title', 'No AGOTW viewership in these seasons.'),
    el('p', 'season-empty-hint', 'Widen the season range or reset Seasons.'),
  );
  refs.chart.append(refs.gd, refs.note);
  refs.captions = el('div', 'nfl-captions');
  const dataWrap = el('div', 'visually-hidden');
  const dataTable = el('table');
  dataTable.appendChild(el('caption', null, 'AGOTW viewership'));
  const thead = el('thead');
  const hr = el('tr');
  for (const h of ['Season', 'Crew', 'Value', 'Era']) {
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

  for (const b of refs.yGroup.querySelectorAll('button')) {
    b.setAttribute('aria-pressed', String(b.dataset.value === state.agotwY));
  }
  renderCaptions();

  const series = agotwSeries(model, state);
  // Crew order of first appearance across the seasons in range.
  const order = new Map();
  const crews = [];
  for (const p of series.points) {
    if (order.has(p.crewKey)) continue;
    const st = crewStyle(order.size, th);
    order.set(p.crewKey, order.size);
    crews.push({ crewKey: p.crewKey, label: crewLabel(model, p), color: st.color, symbol: st.symbol });
  }
  const hidden = new Set(state.hiddenCrews);
  renderLegend(crews, hidden, th);

  const resid = state.agotwY === 'resid';
  const drawnSegments = series.segments
    .filter((s) => !hidden.has(s.crewKey))
    .map((s) => {
      const c = crews[s.order];
      return { ...s, label: c.label, color: c.color, symbol: c.symbol };
    });
  const items = [];
  for (const seg of drawnSegments) {
    for (const p of seg.points) {
      const y = resid ? p.values.resid : p.values.mean;
      items.push({
        k: items.length,
        p,
        seg,
        y: y == null ? null : y,
        err: resid && p.values.se != null ? 1.96 * p.values.se : resid ? 0 : null,
        key: `${p.season}:${p.crewKey}`,
        ring: hasSelectedPerson(model, state, p),
      });
    }
  }
  current = { items, env, theme: th, state, model, series, drawnSegments };
  renderDataTable(items, state);

  if (!series.points.length) {
    refs.drawn = false;
    current.bands = [];
    setNote(true);
    return;
  }
  setNote(false);
  const fig = buildFigure(model, state, env, th, drawnSegments, series.points, items);
  current.bands = fig.bands;
  refs.drawn = true;
  window.Plotly.react(refs.gd, fig.traces, fig.layout, CONFIG);
  bindEvents(refs.gd);
}

export function resize() {
  if (refs.drawn && refs.gd && window.Plotly && refs.gd.data) window.Plotly.Plots.resize(refs.gd);
}

export function testModel() {
  const s = refs.ctx ? refs.ctx.getState() : null;
  const y = s ? s.agotwY : 'mean';
  if (!current || !refs.drawn) {
    return { view: 'agotw', drawn: false, y, segments: [], bands: [], points: [] };
  }
  const { model, drawnSegments, items, bands } = current;
  return {
    view: 'agotw',
    drawn: true,
    y,
    axisTitle: TITLES[y],
    segments: drawnSegments.map((seg) => ({
      crew: seg.label,
      color: seg.color,
      symbol: seg.symbol,
      seasons: seg.points.map((p) => p.season),
    })),
    bands: bands.map((b) => ({ era: model.eras[b.era].label, from: b.from, to: b.to })),
    points: items.map((it) => ({
      season: it.p.season,
      y: it.y,
      err: it.err,
      lowN: it.p.lowN,
      ring: it.ring,
      crew: crewLabel(model, it.p),
      games: it.p.gameList.length,
    })),
  };
}
