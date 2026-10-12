/**
 * NFL view 1: Special games by team (D-12, D-13, D-24).
 *
 * A stacked horizontal Plotly bar per franchise over the selected seasons, four
 * exclusive segments (Standalone slot, AGOTW, CBS national, International (not
 * standalone)), each game counted once. Hover text, the legend chips, the
 * season breakdown and the hidden data table are all built with
 * createElement/textContent; names enter Plotly strings only through
 * escapeHover, and customdata carries row indexes, never names.
 */
import { teamBars, teamSeasonRows, rateText, EXCLUSIVE_CATEGORIES } from '../state.js';
import { categoryColor } from '../palette.js';
import { ACCENT, MUTED, PAGE_BG, DIVIDER } from '../../../modules/palette.js';
import { showTextTooltip, hideTooltip } from '../../../modules/tooltip.js';
import { escapeHover } from '../../../modules/format.js';
import { DATA_TABLE_CLASS, rebuildKeepingFocus } from '../data-table.js';

const SEGMENTS = EXCLUSIVE_CATEGORIES.filter((c) => c.key !== 'none');
const TOP_N = 15;
const FADE = 0.4;
const SLOT_ORDER = [
  'TNF', 'SNF', 'MNF', 'Thanksgiving', 'Christmas', 'Black Friday', 'Saturday',
  'International', 'Friday', 'Sunday early', 'Sunday late', 'Other',
];
const CONFIG = {
  responsive: true,
  displayModeBar: false,
  displaylogo: false,
  scrollZoom: false,
  showLink: false,
  showSendToCloud: false,
  showEditInChartStudio: false,
};

/** Round tick step (1, 2, 5, 10, 20, 25, 50, ...) giving 4-8 ticks over max. */
export function niceStep(max) {
  const steps = [];
  for (let m = 1; m <= 1e6; m *= 10) steps.push(m, 2 * m, 5 * m, ...(m >= 10 ? [2.5 * m] : []));
  steps.sort((a, b) => a - b);
  for (const st of steps) if (max / st <= 8) return st;
  return steps[steps.length - 1];
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

const refs = {
  ctx: null,
  legend: null,
  chart: null,
  gd: null,
  note: null,
  noteTitle: null,
  noteHint: null,
  showAll: null,
  breakdown: null,
  captions: null,
  dataBody: null,
  bound: false,
};

// What the last render drew (also what the event handlers read).
let drawn = null; // { rows, env, theme, state, model }

function theme(env) {
  return env.dark ? 'dark' : 'light';
}

/** Black or white, whichever reads better on `hex`. */
function textOn(hex) {
  const lin = (v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  const n = parseInt(hex.slice(1), 16);
  const lum = 0.2126 * lin(n >> 16) + 0.7152 * lin((n >> 8) & 255) + 0.0722 * lin(n & 255);
  return (1.05) / (lum + 0.05) >= (lum + 0.05) / 0.05 ? '#FFFFFF' : '#111111';
}

/** The franchise's display name: its latest, or that season's when one is picked. */
function teamLabel(model, state, fIdx) {
  const [lo, hi] = state.seasons;
  if (lo === hi) {
    const c = model.cols;
    for (const i of model.franchiseGames.get(fIdx) || []) {
      if (c.season[i] !== lo) continue;
      return model.teamNames[c.home[i] === fIdx ? c.home_name[i] : c.away_name[i]].name;
    }
  }
  return model.franchises[fIdx].name;
}

/** Every game of the franchise in the season range that is special or international. */
function teamGames(model, state, fIdx) {
  const c = model.cols;
  const [lo, hi] = state.seasons;
  return (model.franchiseGames.get(fIdx) || []).filter(
    (i) =>
      c.season[i] >= lo
      && c.season[i] <= hi
      && (c.standalone[i] || c.agotw[i] || c.cbs_national[i] || c.international[i]),
  );
}

function slotText(slots) {
  const ordered = [...slots].sort((a, b) => SLOT_ORDER.indexOf(a.label) - SLOT_ORDER.indexOf(b.label));
  return ordered.map((s) => `${s.label === 'Other' ? 'other' : s.label} ${s.count}`).join(', ');
}

/** The hover lines (UI-SPEC order) for a bar entry, without the click hint. */
function hoverLines(state, label, bar) {
  const [lo, hi] = state.seasons;
  const title = lo === hi ? `${label}, ${lo}` : `${label}, ${lo}–${hi}`;
  const slots = bar.slots.length ? ` (${slotText(bar.slots)})` : '';
  const c = bar.counts;
  return [
    { text: title, kind: 'title' },
    { text: `Special games: ${bar.total}`, kind: 'body' },
    { text: `Standalone: ${c.standalone}${c.standalone > 0 ? slots : ''}`, kind: 'body' },
    { text: `AGOTW: ${c.agotw} · ${rateText(bar.agotwRate.count, bar.agotwRate.denom)}`, kind: 'body' },
    { text: `CBS national: ${c.cbs_national} · ${rateText(bar.cbsRate.count, bar.cbsRate.denom)}`, kind: 'body' },
    { text: `International (not standalone): ${c.international_other}`, kind: 'body' },
    {
      text: `International, any slot: ${bar.international}. Standalone international games count under Standalone.`,
      kind: 'body',
    },
    { text: `Flexed: ${bar.flexed}`, kind: 'body' },
  ];
}

function selectedKey(state) {
  const s = state.selection;
  return s && s.kind === 'team' ? s.key : null;
}

let lastToggle = { id: null, at: 0 };

function toggleTeam(row) {
  const { ctx } = refs;
  // A touch tap reaches Plotly as touchend and again as the emulated mouseup.
  const now = Date.now();
  if (lastToggle.id === row.id && now - lastToggle.at < 500) return;
  lastToggle = { id: row.id, at: now };
  const { model, state } = drawn;
  const id = model.franchises[row.bar.franchise].id;
  if (selectedKey(ctx.getState()) === id) {
    ctx.clearSelection();
    return;
  }
  ctx.selectGames({
    kind: 'team',
    key: id,
    label: row.label,
    games: teamGames(model, state, row.bar.franchise),
  });
}

function bindEvents(gd) {
  if (refs.bound) return;
  refs.bound = true;
  gd.on('plotly_click', (ev) => {
    const k = ev.points && ev.points[0] ? ev.points[0].customdata : null;
    if (drawn && Number.isInteger(k) && drawn.rows[k]) toggleTeam(drawn.rows[k]);
  });
  gd.on('plotly_hover', (ev) => {
    const k = ev.points && ev.points[0] ? ev.points[0].customdata : null;
    if (!drawn || !Number.isInteger(k) || !drawn.rows[k]) return;
    if (drawn.env.mobile || drawn.env.hoverNone) return;
    const row = drawn.rows[k];
    const lines = hoverLines(drawn.state, row.label, row.bar);
    lines.push({ text: 'Click to see seasons and games.', kind: 'hint' });
    const e = ev.event || {};
    showTextTooltip(lines, {
      theme: theme(drawn.env),
      borderColor: ACCENT[theme(drawn.env)],
      clientX: e.clientX ?? 0,
      clientY: e.clientY ?? 0,
    });
  });
  gd.on('plotly_unhover', () => hideTooltip());
}

// ---- pieces ----

function renderLegend(state, th) {
  const { ctx, legend } = refs;
  const hidden = new Set(state.hiddenSegments);
  const chips = SEGMENTS.map((seg) => {
    const color = categoryColor(seg.key, th);
    const b = el('button', 'legend-chip pill', seg.label);
    b.type = 'button';
    b.dataset.segment = seg.key;
    const on = !hidden.has(seg.key);
    b.setAttribute('aria-pressed', String(on));
    b.style.borderColor = color;
    if (on) {
      b.style.backgroundColor = color;
      b.style.color = textOn(color);
    }
    b.addEventListener('click', () => {
      const cur = new Set(ctx.getState().hiddenSegments);
      if (cur.has(seg.key)) cur.delete(seg.key);
      else cur.add(seg.key);
      ctx.setState({ hiddenSegments: SEGMENTS.map((s) => s.key).filter((k) => cur.has(k)) });
    });
    return b;
  });
  legend.replaceChildren(...chips);
}

function setNote(title, hint) {
  const { note, noteTitle, noteHint, gd } = refs;
  if (title == null) {
    note.hidden = true;
    gd.hidden = false;
    return;
  }
  noteTitle.textContent = title;
  noteHint.textContent = hint;
  note.hidden = false;
  gd.hidden = true;
}

function cell(tag, text, className) {
  return el(tag, className || null, text);
}

function agotwCell(count, denom) {
  return denom > 0 ? rateText(count, denom) : `${count} · n/a`;
}

function renderBreakdown(model, state, env, rows) {
  const { ctx, breakdown } = refs;
  breakdown.replaceChildren();
  const key = selectedKey(state);
  if (key == null || !model.franchiseIndex.has(key)) {
    breakdown.hidden = true;
    return;
  }
  const fIdx = model.franchiseIndex.get(key);
  const label = teamLabel(model, state, fIdx);
  breakdown.hidden = false;
  breakdown.appendChild(el('h3', null, `${label}: season by season`));

  const bar = (rows.find((r) => r.bar.franchise === fIdx) || {}).bar
    || teamBars(model, state).find((b) => b.franchise === fIdx);
  if ((env.mobile || env.hoverNone) && bar) {
    const lines = el('div', 'nfl-breakdown-lines');
    for (const l of hoverLines(state, label, bar).slice(1)) lines.appendChild(el('p', null, l.text));
    breakdown.appendChild(lines);
  }

  const table = el('table', 'games-table');
  const head = el('tr');
  for (const h of [
    'Season', 'Special games', 'Standalone', 'AGOTW', 'CBS national',
    'International (not standalone)', 'Flexed',
  ]) {
    const th = cell('th', h);
    th.scope = 'col';
    head.appendChild(th);
  }
  const thead = el('thead');
  thead.appendChild(head);
  const tbody = el('tbody');
  for (const r of teamSeasonRows(model, state, fIdx)) {
    const tr = el('tr');
    tr.dataset.season = String(r.season);
    const season = cell('th', String(r.season));
    season.scope = 'row';
    tr.append(
      season,
      cell('td', String(r.total), 'num'),
      cell('td', String(r.counts.standalone), 'num'),
      cell('td', agotwCell(r.agotwRate.count, r.agotwRate.denom)),
      cell('td', agotwCell(r.cbsRate.count, r.cbsRate.denom)),
      cell('td', String(r.counts.international_other), 'num'),
      cell('td', String(r.flexed), 'num'),
    );
    tbody.appendChild(tr);
  }
  table.append(thead, tbody);
  breakdown.appendChild(table);

  const caption = el('p', 'nfl-muted');
  caption.append(
    document.createTextNode('Rates count doubleheader weeks only. Weeks that cannot be classified are left out; see '),
  );
  const a = el('a', null, 'methodology');
  a.href = ctx.methodologyHref('nfl-doubleheader-weeks-and-rates');
  a.rel = 'noopener noreferrer';
  caption.append(a, document.createTextNode('.'));
  breakdown.appendChild(caption);
}

function renderDataTable(rows) {
  const { dataBody } = refs;
  rebuildKeepingFocus(dataBody, () => {
    dataBody.replaceChildren();
    for (const r of rows) {
      const tr = el('tr');
      const th = el('th');
      th.scope = 'row';
      const btn = el('button', null, r.label);
      btn.type = 'button';
      btn.dataset.key = r.id;
      btn.setAttribute('aria-label', `Select ${r.label}`);
      btn.addEventListener('click', () => toggleTeam(r));
      th.appendChild(btn);
      tr.append(
        th,
        cell('td', String(r.bar.counts.standalone)),
        cell('td', String(r.bar.counts.agotw)),
        cell('td', String(r.bar.counts.cbs_national)),
        cell('td', String(r.bar.counts.international_other)),
        cell('td', String(r.bar.total)),
      );
      dataBody.appendChild(tr);
    }
  });
}

function renderShowAll(total, state) {
  const { ctx, showAll } = refs;
  if (total <= TOP_N) {
    showAll.hidden = true;
    return;
  }
  showAll.hidden = false;
  showAll.textContent = state.showAllTeams ? `Show top ${TOP_N}` : `Show all ${total} teams`;
  showAll.setAttribute('aria-pressed', String(state.showAllTeams));
  showAll.onclick = () => ctx.setState({ showAllTeams: !ctx.getState().showAllTeams });
}

function buildFigure(rows, state, env, th) {
  const hidden = new Set(state.hiddenSegments);
  const selected = selectedKey(state);
  const bg = PAGE_BG[th];
  const ids = rows.map((r) => r.id);
  const traces = SEGMENTS.map((seg) => ({
    type: 'bar',
    orientation: 'h',
    name: seg.label,
    visible: hidden.has(seg.key) ? false : true,
    x: rows.map((r) => r.bar.counts[seg.key]),
    y: ids,
    customdata: rows.map((_, k) => k),
    hoverinfo: 'none',
    marker: {
      color: categoryColor(seg.key, th),
      opacity: rows.map((r) => (r.faded || r.bar.segmentFaded[seg.key] || (selected && r.id !== selected) ? FADE : 1)),
      line: {
        color: rows.map((r) => (r.id === selected ? ACCENT[th] : bg)),
        width: rows.map((r) => (r.id === selected ? 1.5 : 1)),
      },
    },
  }));
  let max = 0;
  for (const r of rows) {
    const sum = SEGMENTS.reduce((a, seg) => a + (hidden.has(seg.key) ? 0 : r.bar.counts[seg.key]), 0);
    if (sum > max) max = sum;
  }
  const pitch = env.mobile ? 44 : 32;
  const thickness = env.mobile ? 28 : 20;
  const font = { family: getComputedStyle(document.body).fontFamily, size: 14, color: ACCENT[th] };
  const layout = {
    paper_bgcolor: bg,
    plot_bgcolor: bg,
    font,
    showlegend: false,
    barmode: 'stack',
    bargap: 1 - thickness / pitch,
    hovermode: 'closest',
    clickmode: 'event',
    dragmode: false,
    height: rows.length * pitch + 70,
    margin: { l: 8, r: 24, t: 8, b: 56 },
    xaxis: {
      title: { text: 'Special games', standoff: 4 },
      range: [0, Math.max(1, max) * 1.05],
      tickmode: 'linear',
      tick0: 0,
      dtick: niceStep(max),
      tickformat: ',d',
      gridcolor: DIVIDER[th],
      tickfont: { color: MUTED[th] },
      zeroline: true,
      zerolinecolor: MUTED[th],
      fixedrange: true,
    },
    yaxis: {
      type: 'category',
      categoryorder: 'array',
      categoryarray: ids,
      tickmode: 'array',
      tickvals: ids,
      ticktext: rows.map((r) => escapeHover(r.label)),
      autorange: 'reversed',
      automargin: true,
      showgrid: false,
      zeroline: false,
      fixedrange: true,
    },
  };
  return { traces, layout };
}

export function mount(container, ctx) {
  refs.ctx = ctx;
  refs.legend = el('div', 'nfl-legend-row');
  const controls = el('div', 'nfl-view-controls');
  refs.chart = el('div', 'nfl-chart');
  refs.gd = el('div');
  refs.note = el('div', 'season-empty-note');
  refs.note.setAttribute('role', 'status');
  refs.noteTitle = el('p', 'season-empty-title');
  refs.noteHint = el('p', 'season-empty-hint');
  refs.note.append(refs.noteTitle, refs.noteHint);
  refs.chart.append(refs.gd, refs.note);
  refs.showAll = el('button', 'toggle nfl-show-all');
  refs.showAll.type = 'button';
  refs.showAll.hidden = true;
  refs.breakdown = el('div', 'nfl-breakdown');
  refs.breakdown.hidden = true;
  refs.captions = el('div', 'nfl-captions');
  const dataWrap = el('div', DATA_TABLE_CLASS);
  const dataTable = el('table');
  dataWrap.appendChild(dataTable);
  dataTable.appendChild(el('caption', null, 'Special games by team'));
  const thead = el('thead');
  const hr = el('tr');
  for (const h of ['Team', ...SEGMENTS.map((s) => s.label), 'Total']) {
    const th = el('th', null, h);
    th.scope = 'col';
    hr.appendChild(th);
  }
  thead.appendChild(hr);
  refs.dataBody = el('tbody');
  dataTable.append(thead, refs.dataBody);
  container.append(refs.legend, controls, refs.chart, refs.showAll, refs.breakdown, refs.captions, dataWrap);
}

export function render(ctx) {
  const model = ctx.model;
  const state = ctx.getState();
  const env = ctx.env();
  const th = theme(env);
  hideTooltip();

  // Keep a selected team's games in step with the season range.
  const key = selectedKey(state);
  if (key != null && model.franchiseIndex.has(key)) {
    const fresh = teamGames(model, state, model.franchiseIndex.get(key));
    const cur = state.selection.games || [];
    if (fresh.length !== cur.length || fresh.some((g, k) => g !== cur[k])) {
      ctx.selectGames({ ...state.selection, games: fresh });
      return;
    }
  }

  renderLegend(state, th);
  const bars = teamBars(model, state);
  const hasGames = bars.some((b) => b.total > 0);
  const rowsAll = bars.map((bar) => ({
    bar,
    id: model.franchises[bar.franchise].id,
    label: teamLabel(model, state, bar.franchise),
    faded: bar.teamFaded,
  }));
  const rows = state.showAllTeams ? rowsAll : rowsAll.slice(0, TOP_N);
  drawn = { rows, env, theme: th, state, model };
  renderShowAll(rowsAll.length, state);
  renderDataTable(rows);
  renderBreakdown(model, state, env, rowsAll);

  let anyShown = false;
  if (!model.n || !model.special.some((r) => r.season >= state.seasons[0] && r.season <= state.seasons[1])) {
    setNote('No NFL games in these seasons.', 'Widen the season range or reset Seasons.');
  } else if (!hasGames) {
    setNote('No teams match these filters.', 'Clear a Team or Category filter.');
  } else {
    anyShown = true;
    setNote(null);
  }
  refs.drawn = anyShown;
  if (!anyShown) {
    refs.showAll.hidden = true;
    return;
  }
  const fig = buildFigure(rows, state, env, th);
  window.Plotly.react(refs.gd, fig.traces, fig.layout, CONFIG);
  bindEvents(refs.gd);
}

export function resize() {
  if (refs.drawn && refs.gd && window.Plotly && refs.gd.data) window.Plotly.Plots.resize(refs.gd);
}

export function testModel() {
  if (!drawn || !refs.drawn) {
    const s = refs.ctx ? refs.ctx.getState() : null;
    return {
      view: 'special',
      drawn: false,
      rows: [],
      hiddenSegments: s ? [...s.hiddenSegments] : [],
      selected: s ? selectedKey(s) : null,
    };
  }
  const s = refs.ctx.getState();
  return {
    view: 'special',
    drawn: true,
    rows: drawn.rows.map((r) => ({
      franchise: r.id,
      label: r.label,
      counts: { ...r.bar.counts },
      total: r.bar.total,
      faded: r.faded,
      segmentFaded: { ...r.bar.segmentFaded },
    })),
    hiddenSegments: [...s.hiddenSegments],
    selected: selectedKey(s),
    totalTeams: teamBars(drawn.model, s).length,
  };
}
