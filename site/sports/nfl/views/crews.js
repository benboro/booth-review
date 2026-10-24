/**
 * NFL Crews view (15-09): one table of every network group's booths over the master Seasons
 * range, on the shared Crews table (modules/crews-table.js), with a chart of the first 25 rows.
 *
 * A pooled row is a play-by-play voice + analyst pair per network group (Per season splits it
 * by season). Rows come from crew-rows.js; this module only draws them, with
 * createElement/textContent, and turns clicks into `setState` / `pickBoothRow` calls. A row
 * click or Enter sets Booths to the row's catalog key (network group + play-by-play voice).
 *
 * Names enter Plotly strings only through escapeHover (crews-chart.js). The spread's value is
 * never shown; the word appears only in the Adjusted caption, hover lines and axis titles.
 */
import { buildNflCrewRows, sortNflCrewRows, NFL_SORT_SPEC } from '../crew-rows.js';
import { createReasonBar, setReason, linkDisabled } from '../reason-bar.js';
import { mountViewTools } from '../tools.js';
import { createTableState, el, renderCrewsTable, activeSort } from '../../../modules/crews-table.js';
import { networkMark } from '../../../modules/network.js';
import { formatAudienceTable, MINUS } from '../../../modules/format.js';
import { hideTooltip } from '../../../modules/tooltip.js';
import { chartModel, drawCrewsChart, theme, CHART_ROWS } from './crews-chart.js';

/** This view's table state: paging, open rows and announce memory. */
const ts = createTableState();

const CONFOUND = 'Avg viewers (rated games) mostly reflects which games a booth was assigned.';
const VIEWERS_SCOPE_NOTE =
  'Avg viewers counts rated games only; unrated games are left out. Some figures are window-level: '
  + 'AGOTW and CBS late national figures cover every game in that Sunday window.';
const ADJUSTED_NOTE =
  "Adjusted: how far each booth's games ran from what the spread predicted, for example 1.4 pts closer. "
  + 'Whiskers show plus or minus 1.96 standard errors.';
const EMPTY_COPY = {
  title: 'No games match these filters',
  body: 'Clear all filters, or widen the Seasons range.',
};

const refs = {
  ctx: null,
  root: null,
  values: null,
  adjustedButton: null,
  perSeasonBox: null,
  perSeasonLabel: null,
  reasonBar: null,
  tableHost: null,
  measure: null,
  chartWrap: null,
  chart: null,
  gd: null,
  chartCaption: null,
  notes: null,
  drawn: false,
};

/** What the last render drew (also what testModel reads). */
let current = null;

// ---- tools ----

function buildTools() {
  const { ctx } = refs;
  const values = el('div', 'segmented nfl-crews-values');
  values.setAttribute('role', 'group');
  values.setAttribute('aria-label', 'Raw or adjusted');
  for (const [key, label] of [['raw', 'Raw'], ['adjusted', 'Adjusted']]) {
    const b = el('button', null, label);
    b.type = 'button';
    b.dataset.value = key;
    b.addEventListener('click', () => {
      if (key === 'adjusted' && b.getAttribute('aria-disabled') === 'true') return;
      ctx.setState({ adjusted: key === 'adjusted' });
    });
    values.append(b);
    if (key === 'adjusted') refs.adjustedButton = b;
  }
  refs.values = values;

  const label = el('label', 'crews-perseason-label');
  const box = el('input', 'crews-perseason');
  box.type = 'checkbox';
  box.addEventListener('change', () => ctx.setState({ perseason: box.checked }));
  label.append(box, ' Per season');
  refs.perSeasonBox = box;
  refs.perSeasonLabel = label;

  const tools = el('div', 'chart-controls nfl-crews-controls');
  tools.append(values, label);
  return tools;
}

function syncTools(state, model) {
  for (const b of refs.values.querySelectorAll('button')) {
    const on = (b.dataset.value === 'adjusted') === (model.mode === 'adjusted');
    b.setAttribute('aria-pressed', String(on));
  }
  linkDisabled(refs.adjustedButton, refs.reasonBar, model.mode === 'raw' && !!state.adjusted);
  const single = !(state.seasons[1] > state.seasons[0]);
  refs.perSeasonBox.disabled = single;
  refs.perSeasonBox.checked = !single && state.perseason !== false;
  const title = single ? 'Needs two or more seasons in range' : 'One row per crew and season';
  refs.perSeasonLabel.title = title;
  refs.perSeasonBox.title = title;
}

// ---- cells ----

/** Columns: [key, label, numeric?]. The chevron column is added by the shared table. */
function columnsFor(perSeason) {
  const cols = [['booth', 'Booth', false]];
  if (perSeason) cols.push(['season', 'Season', false]);
  cols.push(
    ['rank', 'Rank by season', false],
    ['network', 'Network', false],
    ['games', 'Games called', true],
    ['margin', 'Avg margin (pts)', true],
    ['exc', 'Avg excitement', true],
    ['viewers', 'Avg viewers (rated games)', true],
  );
  return cols;
}

function groupFamily(model, groupId) {
  const g = model.networkGroups.find((x) => x.id === groupId);
  const first = g && g.members && g.members.length ? model.networks[g.members[0]] : null;
  return first ? first.family : null;
}

function nameCell(row) {
  const td = el('td', 'crews-name');
  const parts = [row.pbp, row.analyst].filter((p) => p != null);
  parts.forEach((p, k) => {
    td.append(el('span', 'crews-person-name', p.name));
    if (k < parts.length - 1) td.append(' and ');
  });
  return td;
}

function networkCell(model, row) {
  const td = el('td', 'crews-network');
  td.append(networkMark({ id: row.network.id, name: row.network.name, family: groupFamily(model, row.groupId) }));
  td.title = row.network.name;
  return td;
}

function lowNTag(td) {
  td.classList.add('is-low-n');
  const tag = el('span', 'crews-tag', 'n < 8');
  tag.title = 'Fewer than 8 games have this figure';
  td.append(' ', tag);
}

/** A Raw margin, excitement or viewers cell. */
function rawCell(m, kind) {
  const td = el('td', 'num');
  if (m.blank === 'era') {
    td.classList.add('is-blank');
    td.append(el('span', 'caption', 'see Per season'));
    td.title = 'Games span more than one Nielsen measurement era';
    return td;
  }
  if (m.blank === 'none') {
    if (kind === 'viewers') {
      td.classList.add('is-blank');
      td.append(el('span', 'caption', 'none rated'));
    }
    return td;
  }
  const fig = kind === 'viewers' ? formatAudienceTable(m.mean) : m.mean.toFixed(1);
  td.append(el('span', 'crews-figure', fig));
  if (kind === 'viewers') td.append(' ', el('span', 'caption', `(${m.n})`));
  if (m.flagged) lowNTag(td);
  return td;
}

function signed(x) {
  const s = Math.abs(x).toFixed(1);
  if (Number(s) === 0) return s;
  return x < 0 ? MINUS + s : `+${s}`;
}

/** An Adjusted margin or excitement cell: the signed residual and ` ±` its standard error. */
function adjustedCell(c) {
  const td = el('td', 'num');
  if (c.resid == null) {
    td.classList.add('is-blank');
    return td;
  }
  td.append(el('span', 'crews-figure', signed(c.resid)));
  if (c.se != null) td.append(' ', el('span', 'caption', `± ${c.se.toFixed(1)}`));
  if (c.flagged) lowNTag(td);
  return td;
}

function buildCells(model, row, mode) {
  const cells = [nameCell(row)];
  if (row.season != null) cells.push(el('td', 'crews-season num-ish', String(row.season)));
  cells.push(
    el('td', 'crews-rank caption', row.rankRun || ''),
    networkCell(model, row),
    el('td', 'num', String(row.gamesCount)),
    mode === 'adjusted' ? adjustedCell(row.adjusted.margin) : rawCell(row.margin, 'margin'),
    mode === 'adjusted' ? adjustedCell(row.adjusted.exc) : rawCell(row.exc, 'exc'),
    rawCell(row.viewers, 'viewers'),
  );
  return cells;
}

function gameRow(ctx, model, row, i) {
  const c = model.cols;
  const home = model.teamNames[c.home_name[i]].name;
  const away = model.teamNames[c.away_name[i]].name;
  const matchup = `${away} at ${home}`;
  const tr = el('tr', 'crews-game');
  tr.dataset.game = String(i);
  tr.tabIndex = 0;
  tr.setAttribute('role', 'button');
  tr.setAttribute('aria-label', `Details for ${matchup}`);
  tr.append(el('td', 'date crews-game-date', c.date[i]));
  const matchupTd = el('td', 'matchup crews-game-matchup', matchup);
  if (row.fillIn.has(i)) {
    const tag = el('span', 'crews-tag is-dashed', 'fill-in');
    tag.title = 'The regular analyst was absent';
    matchupTd.append(tag);
  }
  const netIdx = c.network[i];
  const netTd = el('td', 'crews-game-network');
  if (netIdx != null) {
    const net = model.networks[netIdx];
    netTd.append(networkMark({ id: net.id, name: net.name, family: net.family }));
  }
  const viewers = el('td', 'num crews-game-viewers');
  if (c.viewers[i] == null) {
    viewers.classList.add('is-blank');
    viewers.append(el('span', 'caption', 'none rated'));
  } else {
    viewers.append(el('span', 'crews-figure', formatAudienceTable(c.viewers[i])));
    if (row.windowGames.has(i)) {
      const tag = el('span', 'crews-tag is-dashed', 'window');
      tag.title = 'One figure covers every game in that Sunday window';
      viewers.append(tag);
    }
  }
  tr.append(matchupTd, netTd, viewers);
  tr.addEventListener('click', () => ctx.openGame?.(i, tr));
  return tr;
}

// ---- notes ----

function link(text, href) {
  const a = el('a', null, text);
  a.href = href;
  a.rel = 'noopener noreferrer';
  return a;
}

function renderNotes(ctx, mode, anyPublished) {
  const kids = [
    el('p', 'caption nfl-crews-confound', CONFOUND),
    el('p', 'caption nfl-viewers-note', VIEWERS_SCOPE_NOTE),
  ];
  const rt17 = el('p', 'caption nfl-crews-rt17');
  rt17.append(
    "NFL excitement is GEI-style, built from win probability. It is not CFBD's excitementIndex; see ",
    link('methodology', ctx.methodologyHref('nfl-gei-style-excitement')),
    '.',
  );
  kids.push(rt17);
  if (mode === 'adjusted') kids.push(el('p', 'caption nfl-crews-adjusted', ADJUSTED_NOTE));
  if (anyPublished) kids.push(el('p', 'caption nfl-published-note', 'Booth order from a published lineup.'));
  refs.notes.replaceChildren(...kids);
}

// ---- contract ----

export function mount(container, ctx) {
  refs.ctx = ctx;
  refs.root = container;
  refs.reasonBar = createReasonBar('nfl-reason-crews');
  refs.tableHost = el('div', 'nfl-crews-table');

  const measure = el('div', 'segmented nfl-crews-measure');
  measure.setAttribute('role', 'group');
  measure.setAttribute('aria-label', 'Chart measure');
  for (const o of [
    { key: 'margin', label: 'Avg margin' },
    { key: 'excitement', label: 'Excitement', short: 'Excite.' },
    { key: 'viewers', label: 'Avg viewers' },
  ]) {
    const b = el('button');
    b.type = 'button';
    b.dataset.value = o.key;
    if (o.short) {
      b.setAttribute('aria-label', o.label);
      b.title = o.label;
      b.append(el('span', 'axis-long', o.label), el('span', 'axis-short', o.short));
    } else {
      b.textContent = o.label;
    }
    b.addEventListener('click', () => ctx.setState({ metric: o.key }));
    measure.append(b);
  }
  refs.measure = measure;

  refs.chart = el('div', 'nfl-chart');
  refs.gd = el('div');
  refs.chart.append(refs.gd);
  refs.chartCaption = el('p', 'caption nfl-crews-chart-caption', 'Hollow marks are booths with few games.');
  refs.chartWrap = el('div', 'nfl-crews-chart-block');
  refs.chartWrap.append(measure, refs.chart, refs.chartCaption);
  refs.notes = el('div', 'nfl-captions nfl-crews-notes');

  container.append(refs.reasonBar, refs.tableHost, refs.chartWrap, refs.notes);
  // Raw or Adjusted and Per season live in the module header tools.
  mountViewTools(ctx, 'crews', [buildTools()], container);
}

function setHover(rowKey) {
  for (const tr of refs.tableHost.querySelectorAll('tr.crews-row.is-hover')) tr.classList.remove('is-hover');
  if (rowKey == null) return;
  for (const tr of refs.tableHost.querySelectorAll('tr.crews-row')) {
    if (tr.dataset.rowKey === rowKey) tr.classList.add('is-hover');
  }
}

export function render(ctx) {
  const { model } = ctx;
  const state = ctx.getState();
  const env = ctx.env();
  const th = theme();
  hideTooltip();

  const built = buildNflCrewRows(model, state);
  // The shared table lists a row's `games` newest first, which is the row's `gamesList`.
  const rows = sortNflCrewRows(built.rows, state.csort, built.perSeason, built.mode)
    .map((r) => ({ ...r, games: r.gamesList }));
  const columns = columnsFor(built.perSeason);
  const metric = ['margin', 'excitement', 'viewers'].includes(state.metric) ? state.metric : 'margin';

  setReason(refs.reasonBar, built.reason);
  syncTools(state, built);
  for (const b of refs.measure.querySelectorAll('button')) {
    b.setAttribute('aria-pressed', String(b.dataset.value === metric));
  }

  const empty = built.totalRows === 0;
  const signature = JSON.stringify([
    built.perSeason, built.mode, state.csort, state.seasons, state.teams, state.cats,
    state.people, state.booths, state.perseason, state.adjusted,
  ]);
  renderCrewsTable(refs.tableHost, {
    ts,
    state,
    perSeason: built.perSeason,
    sortSpec: NFL_SORT_SPEC,
    rows: empty ? [] : rows,
    signature,
    columns,
    label: 'Crews',
    modeKey: built.mode,
    colCount: columns.length + 1,
    tableClasses: ['is-nfl', ...(built.perSeason ? ['has-season'] : [])],
    gameHeads: ['Date', 'Matchup', 'Network', 'Viewers'],
    buildTools: () => document.createDocumentFragment(),
    buildEmpty: () => {
      const note = el('div', 'season-empty-note crews-empty nfl-crews-empty');
      note.setAttribute('role', 'status');
      note.append(el('p', 'season-empty-title', EMPTY_COPY.title), el('p', 'season-empty-hint', EMPTY_COPY.body));
      return note;
    },
    isPicked: (r) => r.boothKey != null && state.booths.length === 1 && state.booths[0] === r.boothKey,
    crewKeyOf: (r) => r.boothKey ?? r.rowKey,
    buildCells: (r) => buildCells(model, r, built.mode),
    gameRow: (r, i) => gameRow(ctx, model, r, i),
    onPick: (r) => {
      if (r.boothKey) ctx.pickBoothRow(r.boothKey);
    },
    onSort: (csort) => ctx.setState({ csort }),
    openGame: (i) => ctx.openGame(i),
    rerender: () => render(ctx),
  });

  const shownKeys = new Set(
    [...refs.tableHost.querySelectorAll('tr.crews-row')].map((tr) => tr.dataset.rowKey),
  );
  const shown = shownKeys.size;
  const anyPublished = rows.some((r) => r.published && shownKeys.has(r.rowKey));

  refs.chartWrap.hidden = empty;
  refs.notes.hidden = empty;
  let items = [];
  if (empty) {
    refs.drawn = false;
  } else {
    items = chartModel(rows, { metric, adjusted: built.mode === 'adjusted' });
    renderNotes(ctx, built.mode, anyPublished);
    drawCrewsChart(refs, items, {
      metric, adjusted: built.mode === 'adjusted', env, th, onHoverRow: setHover,
    });
    refs.drawn = true;
  }

  current = {
    state, model, built, rows, columns, shown, metric, items,
    sort: activeSort(state, built.perSeason, NFL_SORT_SPEC),
  };
}

export function resize() {
  if (refs.drawn && refs.gd && window.Plotly && refs.gd.data) window.Plotly.Plots.resize(refs.gd);
}

export function testModel() {
  const s = refs.ctx ? refs.ctx.getState() : null;
  if (!current) {
    return {
      view: 'crews', drawn: false, perSeason: false, mode: 'raw', reason: null, totalRows: 0, shown: 0,
      sort: null, columns: [], rows: [],
      chart: { metric: s ? s.metric : 'margin', adjusted: false, points: [] },
    };
  }
  const { built, state } = current;
  const pickedKey = state.booths.length === 1 ? state.booths[0] : null;
  return {
    view: 'crews',
    drawn: refs.drawn || built.totalRows === 0,
    perSeason: built.perSeason,
    mode: built.mode,
    reason: built.reason,
    totalRows: built.totalRows,
    shown: current.shown,
    sort: current.sort,
    columns: current.columns.map((c) => c[1]),
    rows: current.rows.map((r) => ({
      rowKey: r.rowKey,
      boothKey: r.boothKey,
      names: r.names,
      season: r.season,
      network: r.network,
      gamesCount: r.gamesCount,
      rankRun: r.rankRun,
      margin: r.margin,
      exc: r.exc,
      viewers: r.viewers,
      adjusted: r.adjusted,
      published: r.published,
      picked: pickedKey != null && r.boothKey === pickedKey,
    })),
    chart: {
      metric: current.metric,
      adjusted: built.mode === 'adjusted' && current.metric !== 'viewers',
      points: current.items.map((it) => ({
        rowKey: it.rowKey, x: it.x, err: it.err == null ? 0 : it.err, hollow: it.hollow,
      })),
      rowsPlotted: Math.min(CHART_ROWS, current.rows.length),
    },
  };
}
