/**
 * Matched-games table: the screen-reader and phone fallback for the chart's
 * current selection (D-06, D-12, SITE-13, SITE-22, SITE-26, T16). Rows come
 * from `computeView`'s own matched-games list -- a person's highlighted
 * games, or (absent a person) every game passing the fade filters once a
 * School filter is set -- and only while a person or school is selected;
 * otherwise `#table-empty`'s "Nothing selected" prompt shows instead (D-12's
 * anti-bulk-copy rule). The whole row opens the detail panel on click or
 * Enter (D-06); there is no separate Details column.
 *
 * DOM is built only with createElement/textContent/replaceChildren -- never
 * any markup-injecting DOM API (T-04-34). Every href passes through
 * `safeHref` first (T-04-35).
 */

import {
  crewEntries,
  formatDate,
  formatMatchup,
  formatViewers,
  measurementLabel,
} from './format.js';
import { safeHref } from './panel.js';
import { currentTheme, makePill, makeRolePill, nameWithRoles } from './pill.js';
import { personOnGame } from './select.js';

const tableEl = document.getElementById('games-table');
const emptyEl = document.getElementById('table-empty');
const tbody = tableEl.querySelector('tbody');
const dateSortButton = tableEl.querySelector('th button[data-sort="date"]');
const viewersSortButton = tableEl.querySelector('th button[data-sort="viewers"]');

/** The current render call's `onSort`, kept so the once-bound header listeners always call the latest one. */
let currentOnSort = null;

/** Whether the header click listeners have already been bound (bound once, not on every render). */
let listenersBound = false;

/** Binds the sort-header click listeners once; every later `renderTable` call only updates `currentOnSort`. */
function bindHeaderListeners() {
  if (listenersBound) return;
  listenersBound = true;
  dateSortButton.addEventListener('click', () => currentOnSort?.('date'));
  viewersSortButton.addEventListener('click', () => currentOnSort?.('viewers'));
}

/** Fills the crew cell: main-feed "Name [pill]" entries joined by " · " (pbp, analyst, other), plus any selected alt-cast person appended as text (D-08, D-17, CR-04). */
function buildCrewCell(td, data, state, i) {
  const nodes = [];
  const sep = () => document.createTextNode(' · ');
  for (const entry of crewEntries(data, i, { mainOnly: true })) {
    if (nodes.length > 0) nodes.push(sep());
    const name = document.createElement('span');
    name.className = 'crew-name';
    name.textContent = entry.name;
    nodes.push(nameWithRoles(name, makeRolePill(entry.role)));
  }
  for (const personId of state.people) {
    const personIndex = data.personIndexById.get(personId);
    if (personOnGame(data, i, personIndex, state.role) === 'alt') {
      if (nodes.length > 0) nodes.push(sep());
      nodes.push(document.createTextNode(`${data.lookups.people[personIndex].name} (alt-cast)`));
    }
  }
  if (nodes.length === 0) td.textContent = 'Crew not recorded';
  else td.replaceChildren(...nodes);
}

/** Source cell: the publisher link (or "Original source not recorded"), then Ratings Reference link(s). */
function buildSourceCell(data, i) {
  const t = data.t;
  const td = document.createElement('td');

  const publisherName = t.publisher[i] != null ? data.lookups.publishers[t.publisher[i]] : null;
  const sourceHref = safeHref(t.source_url[i]);
  if (sourceHref) {
    const a = document.createElement('a');
    a.href = sourceHref;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    a.textContent = publisherName ?? 'publisher unknown';
    td.appendChild(a);
  } else {
    td.appendChild(document.createTextNode('Original source not recorded'));
  }

  td.appendChild(document.createTextNode(' · '));

  const rrUrls = t.rr_urls[i];
  rrUrls.forEach((url, idx) => {
    if (idx > 0) td.appendChild(document.createTextNode(' '));
    const label = rrUrls.length > 1 ? `Ratings Reference ${idx + 1}` : 'Ratings Reference';
    const rrHref = safeHref(url);
    if (rrHref) {
      const a = document.createElement('a');
      a.href = rrHref;
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      a.textContent = label;
      td.appendChild(a);
    } else {
      td.appendChild(document.createTextNode(label));
    }
  });

  return td;
}

/** Builds one `<tr>` for telecast `i`. The whole row is the click/Enter
 * target that opens the detail panel (D-06); a click on a link inside the
 * row (the Source cell) follows the link instead. */
function buildRow(data, state, onDetails, i) {
  const t = data.t;
  const tr = document.createElement('tr');
  tr.className = 'row-link';
  tr.tabIndex = 0;
  tr.setAttribute('aria-label', `Details for ${formatMatchup(data, i, {})}`);
  tr.addEventListener('click', (ev) => {
    if (ev.target instanceof Element && ev.target.closest('a')) return;
    onDetails(i);
  });
  // `keyup`, not `keydown` (D-06 bug fix): `onDetails` moves focus to
  // `#panel-close` (panel.js openPanel). If that happened during this row's
  // own `keydown` handler, the still-pending `keyup` for the same physical
  // Enter press would then be dispatched to the now-focused `#panel-close`
  // button -- and a browser natively synthesizes a click from a focused
  // button's own Enter `keyup`, immediately closing the panel this same
  // keypress just opened (confirmed empirically: a trusted `click` fired on
  // `#panel-close` right after the row's Enter press). Handling this on
  // `keyup` instead means our own handler runs on the *last* event of the
  // physical keypress, so there is no further keyup left to leak to the
  // newly focused button once focus moves.
  tr.addEventListener('keyup', (ev) => {
    if (ev.key !== 'Enter') return;
    if (ev.target instanceof Element && ev.target.closest('a')) return;
    onDetails(i);
  });

  const dateTd = document.createElement('td');
  dateTd.className = 'num';
  dateTd.textContent = formatDate(t.date[i]);
  tr.appendChild(dateTd);

  const matchupTd = document.createElement('td');
  matchupTd.textContent = formatMatchup(data, i, { withScore: true });
  tr.appendChild(matchupTd);

  const networkTd = document.createElement('td');
  const net = data.lookups.networks[t.network[i]];
  networkTd.appendChild(makePill(net.name, net.family, currentTheme()));
  tr.appendChild(networkTd);

  const crewTd = document.createElement('td');
  buildCrewCell(crewTd, data, state, i);
  tr.appendChild(crewTd);

  const viewersTd = document.createElement('td');
  viewersTd.className = 'num';
  let viewersText = formatViewers(t.viewers[i]);
  if (t.measurement_type[i] === 'nielsen_adobe') {
    viewersText += ` · ${measurementLabel('nielsen_adobe')}`;
  }
  viewersTd.textContent = viewersText;
  tr.appendChild(viewersTd);

  tr.appendChild(buildSourceCell(data, i));

  return tr;
}

/** Row order: the active sort key/direction, ties broken by date then telecast index. */
function compareRows(data, sort, a, b) {
  const t = data.t;
  let cmp = sort.key === 'date' ? (t.date[a] < t.date[b] ? -1 : t.date[a] > t.date[b] ? 1 : 0) : t.viewers[a] - t.viewers[b];
  if (sort.dir === 'desc') cmp = -cmp;
  if (cmp !== 0) return cmp;
  if (t.date[a] !== t.date[b]) return t.date[a] < t.date[b] ? -1 : 1;
  return a - b;
}

/** Syncs `aria-sort` and the `▲`/`▼` glyph on both sortable headers. */
function renderSortHeaders(sort) {
  for (const [key, button] of [
    ['date', dateSortButton],
    ['viewers', viewersSortButton],
  ]) {
    const isActive = sort.key === key;
    const ariaValue = isActive ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none';
    button.closest('th').setAttribute('aria-sort', ariaValue);
    button.setAttribute('aria-sort', ariaValue);
    button.querySelector('.sort-glyph').textContent = isActive ? (sort.dir === 'asc' ? '▲' : '▼') : '';
  }
}

/**
 * Renders the matched-games table (or its empty state) from the current
 * data/state/view (D-12, SITE-13, SITE-22).
 * @param {{data: object, view: object, state: object, sort: {key: "date"|"viewers", dir: "asc"|"desc"}, onSort: (key: string) => void, onDetails: (i: number) => void}} args
 */
export function renderTable({ data, view, state, sort, onSort, onDetails }) {
  currentOnSort = onSort;
  bindHeaderListeners();
  renderSortHeaders(sort);

  if (!view.hasSelection) {
    emptyEl.hidden = false;
    tableEl.hidden = true;
    tbody.replaceChildren();
    return;
  }

  emptyEl.hidden = true;
  tableEl.hidden = false;

  const rows = [...view.matched].sort((a, b) => compareRows(data, sort, a, b));
  tbody.replaceChildren(...rows.map((i) => buildRow(data, state, onDetails, i)));
}
