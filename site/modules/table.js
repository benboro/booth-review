/**
 * Matched-games table: the screen-reader and phone fallback for the chart's
 * current selection (D-11, SITE-13, T16). Rows only for `view.highlighted`,
 * and only while a person or team is selected -- otherwise `#table-empty`'s
 * "Nothing selected" prompt shows instead (D-11's anti-bulk-copy rule).
 *
 * DOM is built only with createElement/textContent/replaceChildren -- never
 * any markup-injecting DOM API (T-04-34). Every href passes through
 * `safeHref` first (T-04-35).
 */

import {
  ROLE_LABELS,
  crewByRole,
  formatDate,
  formatMatchup,
  formatViewers,
  measurementLabel,
} from './format.js';
import { safeHref } from './panel.js';
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

/** Main-feed "PBP: ... · Analyst: ... · Sideline/other: ..." text, plus any selected alt-cast person appended (D-08, CR-04). */
function crewCellText(data, state, i) {
  const crew = crewByRole(data, i);
  const parts = [];
  if (crew.pbp.length > 0) parts.push(`PBP: ${crew.pbp.join(', ')}`);
  if (crew.analyst.length > 0) parts.push(`Analyst: ${crew.analyst.join(', ')}`);
  if (crew.other.length > 0) parts.push(`${ROLE_LABELS.unknown}: ${crew.other.join(', ')}`);
  for (const personId of state.people) {
    const personIndex = data.personIndexById.get(personId);
    if (personOnGame(data, i, personIndex, state.role) === 'alt') {
      parts.push(`${data.lookups.people[personIndex].name} (alt-cast)`);
    }
  }
  return parts.length > 0 ? parts.join(' · ') : 'Crew not recorded';
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

/** Builds one `<tr>` for telecast `i`. */
function buildRow(data, state, onDetails, i) {
  const t = data.t;
  const tr = document.createElement('tr');

  const dateTd = document.createElement('td');
  dateTd.className = 'num';
  dateTd.textContent = formatDate(t.date[i]);
  tr.appendChild(dateTd);

  const matchupTd = document.createElement('td');
  matchupTd.textContent = formatMatchup(data, i, { withScore: true });
  tr.appendChild(matchupTd);

  const networkTd = document.createElement('td');
  networkTd.textContent = data.lookups.networks[t.network[i]].name;
  tr.appendChild(networkTd);

  const crewTd = document.createElement('td');
  crewTd.textContent = crewCellText(data, state, i);
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

  const detailsTd = document.createElement('td');
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'details-button';
  button.textContent = 'Details';
  button.setAttribute('aria-label', `Details for ${formatMatchup(data, i, {})}`);
  button.addEventListener('click', () => onDetails(i));
  detailsTd.appendChild(button);
  tr.appendChild(detailsTd);

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
 * data/state/view (D-11, SITE-13).
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

  const rows = [...view.highlighted].sort((a, b) => compareRows(data, sort, a, b));
  tbody.replaceChildren(...rows.map((i) => buildRow(data, state, onDetails, i)));
}
