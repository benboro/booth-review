/**
 * Crews tab (Phase 14, CFB-02..CFB-05): one table of every crew (or PBP voice, or analyst) in
 * the Seasons range. The row model is `buildCrewRows` in crew-groups.js; this module only
 * draws it with createElement/textContent (T-14-17), never markup-injecting APIs, and turns
 * header and row clicks into `setState` calls.
 *
 * Game quality per crew only: the table is never sorted by viewers by default, and a pick
 * (crew, or Announcers from a person row) highlights rows without ever dropping one.
 */

import { NATURAL_DIR, modelBreakSeason, sortCrewRows } from './crew-groups.js';
import { formatAudienceShort } from './format.js';
import { networkMark } from './network.js';
import { attachScrollCue } from './scroll-cue.js';

/** Rows the table opens with, and adds per "View more" click (D-13). */
const PAGE = 25;

/** Disposers for the scroll cues on the tables the last render built. */
const detachCues = [];

/** Rows shown before any pick reveal; reset when mode, Per season, sort or the filtered games change. */
let shown = PAGE;
let lastSignature = null;

const MODE_LABELS = { crew: 'Crew', pbp: 'PBP', analyst: 'Analyst' };

const CONFOUND = 'Avg viewers (rated games) mostly reflects which games a crew was assigned.';
const UNKNOWN_NOTE = 'Crews with a member of unknown role are kept and marked.';
const LEFT_OUT = {
  crew: (n) => `${n} telecasts list no crew and are not in this table.`,
  pbp: (n) => `${n} telecasts with no resolved play-by-play voice are not in this mode.`,
  analyst: (n) => `${n} telecasts with no resolved analyst are not in this mode.`,
};
const EMPTY_COPY = {
  title: 'No games match these filters',
  body: 'Clear all filters, or widen the Seasons range.',
};

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
}

function creditLine(text, href) {
  const p = el('p', 'caption');
  if (href) {
    const a = el('a', null, text);
    a.href = href;
    a.rel = 'noopener';
    p.append(a);
  } else {
    p.textContent = text;
  }
  return p;
}

/** Cheap fingerprint of the games the filters leave, so a filter change resets the shown count. */
function passingHash(view) {
  let h = 0;
  const mask = view.passesFilters;
  for (let i = 0; i < mask.length; i += 1) if (mask[i]) h = (h * 31 + i + 1) >>> 0;
  return h;
}

/** Columns for a mode: [key, label, numeric?]. The chevron column is added separately. */
function columnsFor(mode, perSeason) {
  const cols = [['crew', MODE_LABELS[mode], false]];
  if (perSeason) cols.push(['season', 'Season', false]);
  if (mode === 'crew') cols.push(['rank', 'Rank by season', false]);
  cols.push(
    ['network', 'Network', false],
    ['games', 'Games called', true],
    ['exc', 'Avg excitement', true],
    ['viewers', 'Avg viewers (rated games)', true],
  );
  return cols;
}

/** The sort the table currently shows: null state means Games called, descending. */
function activeSort(state) {
  return state.csort ?? { key: 'games', dir: NATURAL_DIR.games };
}

/** Next csort for a click on `key`: natural, reversed, then back to the default (null). */
function nextSort(state, key) {
  const natural = NATURAL_DIR[key];
  const reversed = natural === 'asc' ? 'desc' : 'asc';
  const current = activeSort(state);
  const isDefault = state.csort == null;
  if (isDefault && key !== 'games') return { key, dir: natural };
  if (current.key !== key) return { key, dir: natural };
  if (current.dir === natural) return { key, dir: reversed };
  return null;
}

function sortGlyph(state, key) {
  const current = activeSort(state);
  if (current.key !== key) return '↕';
  return current.dir === 'desc' ? '↓' : '↑';
}

function ariaSort(state, key) {
  const current = activeSort(state);
  if (current.key !== key) return 'none';
  return current.dir === 'desc' ? 'descending' : 'ascending';
}

function networkCell(data, row) {
  const td = el('td', row.network.count > 1 ? 'crews-network has-more' : 'crews-network');
  const net = data.lookups.networks.find((n) => n.id === row.network.primaryId);
  if (net) td.append(networkMark(net));
  if (row.network.count > 1) td.append(el('span', 'crews-more-nets caption', `+${row.network.count - 1}`));
  const names = row.network.all.map((id) => data.lookups.networks.find((n) => n.id === id)?.name ?? id);
  td.title = names.join(', ');
  return td;
}

function nameCell(row, mode) {
  const td = el('td', 'crews-name');
  if (mode === 'crew') {
    const last = row.people.length - 1;
    row.people.forEach((p, k) => {
      const span = el('span', 'crews-person');
      span.append(el('span', 'crews-person-name', p.name));
      if (p.unknownTag) {
        const text =
          p.unknownTag === 'all' ? 'unknown role' : `unknown role in ${p.unknownTag.k} of ${p.unknownTag.n} games`;
        span.append(' ', el('span', 'crews-tag is-dashed', text));
      }
      td.append(span);
      if (k < last) td.append(k === last - 1 ? ' and ' : ', ');
    });
  } else {
    td.append(el('span', 'crews-person-name', row.names));
    if (row.partnersShown.length) {
      const more = row.partnersMore > 0 ? ` +${row.partnersMore}` : '';
      td.append(el('span', 'crews-partners', `with ${row.partnersShown.map((p) => p.name).join(', ')}${more}`));
    }
  }
  return td;
}

function metricCell(m, kind, data) {
  const td = el('td', 'num');
  if (m.blank === 'break' || m.blank === 'era') {
    td.classList.add('is-blank');
    td.append(el('span', 'caption', 'see Per season'));
    td.title =
      m.blank === 'break'
        ? `Games fall on both sides of the ${modelBreakSeason(data)} excitement model change`
        : 'Games span more than one Nielsen measurement era';
    return td;
  }
  if (m.blank === 'none') {
    if (kind === 'viewers') {
      td.classList.add('is-blank');
      td.append(el('span', 'caption', 'none rated'));
    }
    return td;
  }
  const fig = kind === 'viewers' ? formatAudienceShort(m.mean) : m.mean.toFixed(1);
  td.append(el('span', 'crews-figure', fig));
  if (kind === 'viewers') td.append(' ', el('span', 'caption', `(${m.n})`));
  if (m.flagged) {
    td.classList.add('is-low-n');
    const tag = el('span', 'crews-tag', 'n < 8');
    tag.title = 'Fewer than 8 games have this figure';
    td.append(' ', tag);
  }
  return td;
}

/** Whether `row` is exactly the active pick (accent rule 1). */
function isPickedRow(row, mode, state) {
  if (mode === 'crew') return state.crew != null && row.crewKey === state.crew;
  return state.people.length === 1 && state.people[0] === row.personSlug;
}

/** Whether `row` holds a picked person without being the pick itself (accent rule 2, U-06). */
function isHighlightedRow(row, mode, state) {
  if (!state.people.length) return false;
  const slugs = mode === 'crew' ? row.people.map((p) => p.slug) : [row.personSlug];
  const held = state.people.filter((id) => slugs.includes(id));
  return state.together ? held.length === state.people.length : held.length > 0;
}

function buildRow(row, mode, ctx, firstRow) {
  const { data, state, setState } = ctx;
  const tr = el('tr', 'crews-row');
  tr.dataset.rowKey = row.rowKey;
  tr.dataset.crewKey = mode === 'crew' ? row.crewKey : row.personSlug;
  tr.tabIndex = firstRow ? 0 : -1;
  const picked = isPickedRow(row, mode, state);
  tr.setAttribute('aria-pressed', String(picked));
  tr.setAttribute('aria-expanded', 'false');
  tr.setAttribute('aria-label', row.names);
  if (picked) tr.classList.add('is-picked');
  else if (isHighlightedRow(row, mode, state)) tr.classList.add('is-highlighted');

  const chevronCell = el('td', 'crews-chevron-cell');
  const chevron = el('button', 'crews-chevron');
  chevron.type = 'button';
  chevron.setAttribute('aria-label', 'Show games');
  chevron.addEventListener('click', (e) => e.stopPropagation());
  chevronCell.append(chevron);
  tr.append(chevronCell, nameCell(row, mode));
  if (ctx.model.perSeason) tr.append(el('td', 'crews-season num-ish', String(row.season)));
  if (mode === 'crew') tr.append(el('td', 'crews-rank caption', row.rankRun));
  tr.append(
    networkCell(data, row),
    el('td', 'num', String(row.gamesCount)),
    metricCell(row.exc, 'exc', data),
    metricCell(row.viewers, 'viewers', data),
  );

  tr.addEventListener('click', () => {
    if (mode === 'crew') setState({ crew: picked ? null : row.crewKey });
    else setState({ people: picked ? [] : [row.personSlug] });
  });
  return tr;
}

/** Index of the first row that must stay visible because it is the active pick (A3, D-13). */
function revealIndex(rows, mode, state) {
  return rows.findIndex((r) => isPickedRow(r, mode, state));
}

/** A selector that finds the focused control again after the table is rebuilt. */
function focusSelector(container) {
  const a = document.activeElement;
  if (!a || !container.contains(a)) return null;
  const key = (attr) => `[${attr}="${CSS.escape(a.getAttribute(attr) ?? '')}"]`;
  if (a.hasAttribute('data-sort-key')) return `button${key('data-sort-key')}`;
  if (a.hasAttribute('data-cmode')) return `button${key('data-cmode')}`;
  if (a.classList.contains('crews-perseason')) return 'input.crews-perseason';
  if (a.classList.contains('crews-row')) return `tr${key('data-row-key')}`;
  return null;
}

function seasonsInRange(data, state) {
  const [lo, hi] = state.seasons ?? [-Infinity, Infinity];
  return data.seasons.filter((s) => s >= lo && s <= hi).length;
}

function buildTools(ctx) {
  const { data, state, setState } = ctx;
  const tools = el('div', 'crews-tools');
  const group = el('div', 'segmented crews-mode');
  group.setAttribute('role', 'group');
  group.setAttribute('aria-label', 'Crews mode');
  for (const mode of ['crew', 'pbp', 'analyst']) {
    const b = el('button', null, MODE_LABELS[mode]);
    b.type = 'button';
    b.dataset.cmode = mode;
    b.setAttribute('aria-pressed', String(state.cmode === mode));
    b.addEventListener('click', () => {
      if (state.cmode !== mode) setState({ cmode: mode });
    });
    group.append(b);
  }
  const label = el('label', 'crews-perseason-label');
  const box = el('input', 'crews-perseason');
  box.type = 'checkbox';
  box.checked = state.perseason;
  const single = seasonsInRange(data, state) < 2;
  box.disabled = single;
  label.title = single ? 'Needs two or more seasons in range' : 'One row per crew and season';
  box.title = label.title;
  box.addEventListener('change', () => setState({ perseason: box.checked }));
  label.append(box, ' Per season');
  tools.append(group, label);
  return tools;
}

function buildTable(rows, ctx, cols) {
  const { state, setState, model } = ctx;
  const wrap = el('div', 'crews-table-wrap table-scroll');
  const table = el('table', 'games-table crews-table');
  table.setAttribute('role', 'grid');
  table.classList.add(`crews-table--${model.mode}`);
  if (model.perSeason) table.classList.add('has-season');
  const headRow = el('tr');
  const chevronTh = el('th', 'crews-chevron-cell');
  chevronTh.scope = 'col';
  chevronTh.append(el('span', 'visually-hidden', 'Show games'));
  headRow.append(chevronTh);
  for (const [key, label, numeric] of cols) {
    const th = el('th', `crews-col-${key}${numeric ? ' num' : ''}`);
    th.scope = 'col';
    th.setAttribute('aria-sort', ariaSort(state, key));
    const b = el('button');
    b.type = 'button';
    b.dataset.sortKey = key;
    b.append(el('span', 'crews-sort-label', label), el('span', 'sort-glyph', sortGlyph(state, key)));
    b.addEventListener('click', () => setState({ csort: nextSort(state, key) }));
    th.append(b);
    headRow.append(th);
  }
  const thead = el('thead');
  thead.append(headRow);
  const tbody = el('tbody');
  rows.forEach((row, k) => tbody.append(buildRow(row, model.mode, ctx, k === 0)));
  table.append(thead, tbody);
  wrap.append(table);
  detachCues.push(attachScrollCue(wrap, null));
  return wrap;
}

/**
 * Renders the Crews panel into `container`.
 * @param {HTMLElement} container
 * @param {ReturnType<import('./crew-groups.js').buildCrewRows>} model
 * @param {{data: object, state: object, view: object, setState: Function, openGame?: Function}} ctx
 */
export function renderCrewsPanel(container, model, ctx) {
  const { state, view } = ctx;
  const full = { ...ctx, model };
  const signature = `${model.mode}|${model.perSeason}|${JSON.stringify(state.csort)}|${passingHash(view)}`;
  if (signature !== lastSignature) {
    shown = PAGE;
    lastSignature = signature;
  }

  const refocus = focusSelector(container);
  // Every render rebuilds the table, so release the old one's scroll-cue observers first.
  detachCues.splice(0).forEach((detach) => detach());
  container.replaceChildren();
  container.append(buildTools(full));

  const cols = columnsFor(model.mode, model.perSeason);
  if (model.totalRows === 0) {
    const note = el('div', 'season-empty-note crews-empty');
    note.setAttribute('role', 'status');
    note.append(el('p', 'season-empty-title', EMPTY_COPY.title), el('p', 'season-empty-hint', EMPTY_COPY.body));
    container.append(note);
  } else {
    const sorted = sortCrewRows(model.rows, state.csort);
    const reveal = revealIndex(sorted, model.mode, state);
    const count = Math.min(sorted.length, Math.max(shown, reveal + 1));
    container.append(buildTable(sorted.slice(0, count), full, cols));
    const left = sorted.length - count;
    if (left > 0) {
      const step = Math.min(PAGE, left);
      const more = el('button', 'crews-more', `View ${step} more (${left} left)`);
      more.type = 'button';
      more.addEventListener('click', () => {
        shown = count + step;
        renderCrewsPanel(container, model, ctx);
        const rowsNow = container.querySelectorAll('tbody tr.crews-row');
        rowsNow[count]?.focus();
      });
      container.append(more);
    }
    container.append(el('p', 'caption crews-count', `Showing ${count} of ${sorted.length} rows.`));
    if (model.leftOut > 0) container.append(el('p', 'caption crews-left-out', LEFT_OUT[model.mode](model.leftOut)));
  }
  container.append(el('p', 'caption crews-confound', CONFOUND));
  if (model.mode === 'crew') container.append(el('p', 'caption crews-unknown-note', UNKNOWN_NOTE));
  const credits = el('div', 'crews-credits');
  credits.append(
    creditLine('Data provided by CollegeFootballData.com', 'https://collegefootballdata.com'),
    creditLine("Viewership figures: Ratings Reference and the second sources credited in each game's detail panel."),
    creditLine('Booth order from network press releases, cited per season in data/reference/cfb_booth_ranks.csv.'),
  );
  container.append(credits);

  if (refocus) container.querySelector(refocus)?.focus();
}
