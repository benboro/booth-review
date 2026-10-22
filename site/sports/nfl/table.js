/**
 * NFL Matched games table (999.5-08, D-09). A self-contained component: it
 * builds and owns its DOM inside `host`, so it never touches the CFB table's
 * global ids. Rows are the shared GameRow shape.
 *
 * DOM is built only with createElement/textContent (XSS); links go through
 * the CFB panel's `safeHref`. Nothing here reads or shows a point spread.
 */

import { nameWithRoles, makeRolePill } from '../../modules/pill.js';
import { networkMark } from '../../modules/network.js';
import { attachScrollCue } from '../../modules/scroll-cue.js';
import { safeHref } from '../../modules/panel.js';
import { crewSourceText, dateShortText, flagLabels, kickoffText, scoreText, viewersText } from './game-format.js';

const ROLE_ORDER = { pbp: 0, analyst: 1 };
const NOT_RECORDED = 'Not recorded';

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function textPill(text) {
  return el('span', 'pill nfl-pill', text);
}

/** Row order: active key and direction, unrated always last, ties by date then index. */
function compareRows(sort, a, b) {
  let cmp = 0;
  if (sort.key === 'viewers') {
    if ((a.viewers == null) !== (b.viewers == null)) return a.viewers == null ? 1 : -1;
    cmp = (a.viewers ?? 0) - (b.viewers ?? 0);
  } else {
    cmp = a.date < b.date ? -1 : a.date > b.date ? 1 : 0;
  }
  if (sort.dir === 'desc') cmp = -cmp;
  if (cmp !== 0) return cmp;
  if (a.date !== b.date) return a.date < b.date ? -1 : 1;
  return a.i - b.i;
}

function crewCell(td, row) {
  const ordered = row.crew
    .map((c, idx) => ({ c, idx }))
    .sort((x, y) => (ROLE_ORDER[x.c.role] ?? 2) - (ROLE_ORDER[y.c.role] ?? 2) || x.idx - y.idx)
    .map(({ c }) => c);
  if (ordered.length === 0) {
    td.textContent = NOT_RECORDED;
    return;
  }
  const nodes = [];
  for (const c of ordered) {
    if (nodes.length > 0) nodes.push(document.createTextNode(' · '));
    nodes.push(nameWithRoles(el('span', 'crew-name', c.name), makeRolePill(c.role)));
  }
  const source = crewSourceText(row);
  if (source) nodes.push(document.createTextNode(' '), el('span', 'nfl-muted', source));
  td.replaceChildren(...nodes);
}

function sourceCell(row) {
  const td = el('td');
  const href = safeHref(row.rrUrl);
  if (href) {
    const a = el('a', null, 'Record ↗');
    a.href = href;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    td.appendChild(a);
  } else {
    td.className = 'no-rating';
    td.textContent = 'No record';
  }
  return td;
}

function buildRow(row, onOpen) {
  const tr = el('tr', 'row-link');
  // CFB parity: the whole row opens the panel. The matchup button stays as the keyboard
  // and screen-reader opener (and the focus target on close); links keep their own click.
  tr.addEventListener('click', (ev) => {
    if (ev.target instanceof Element && ev.target.closest('a, button')) return;
    onOpen?.(row.i, tr.querySelector('.nfl-matchup-btn'));
  });

  const dateTd = el('td', 'num', dateShortText(row));
  const ko = kickoffText(row);
  if (ko) {
    dateTd.appendChild(el('br'));
    dateTd.appendChild(el('span', 'nfl-muted', ko));
  }
  tr.appendChild(dateTd);

  const matchupTd = el('td');
  const button = el('button', 'nfl-matchup-btn', `${row.away} at ${row.home}`);
  button.type = 'button';
  button.setAttribute('aria-label', `Details for ${row.away} at ${row.home}`);
  button.addEventListener('click', () => onOpen?.(row.i, button));
  matchupTd.appendChild(button);
  const pills = el('div', 'nfl-pills');
  pills.appendChild(textPill(row.slot));
  for (const label of flagLabels(row)) pills.appendChild(textPill(label));
  matchupTd.appendChild(pills);
  tr.appendChild(matchupTd);

  // NFL-only column: the table shows the final score; CFB shows it only in the panel.
  tr.appendChild(el('td', null, scoreText(row)));
  // CFB parity (D-18): the network is a family-colored pill, as in CFB's table.
  const networkTd = el('td');
  if (row.network == null) networkTd.textContent = NOT_RECORDED;
  else networkTd.appendChild(networkMark({ id: row.networkId, name: row.network, family: row.networkFamily }));
  tr.appendChild(networkTd);

  const crewTd = el('td');
  crewCell(crewTd, row);
  tr.appendChild(crewTd);

  const vTd = el('td');
  const vText = viewersText(row);
  if (vText) {
    vTd.className = 'num';
    vTd.textContent = vText;
    if (row.scope === 'window') {
      vTd.appendChild(el('br'));
      vTd.appendChild(el('span', 'nfl-muted', 'window-level'));
    }
  } else {
    vTd.className = 'no-rating';
    vTd.textContent = 'No rating';
  }
  tr.appendChild(vTd);

  tr.appendChild(sourceCell(row));
  return tr;
}

function summaryText(rows) {
  const seasons = rows.map((r) => r.season);
  const rated = rows.filter((r) => r.viewers != null).length;
  let text = `${rows.length} ${rows.length === 1 ? 'game' : 'games'} · ${Math.min(...seasons)}–${Math.max(...seasons)}`;
  if (rated > 0) text += ` · ${rated} rated`;
  return text;
}

/**
 * @param {HTMLElement} host
 * @param {{onOpen?: (i: number, button: HTMLElement) => void}} opts
 */
export function createGamesTable(host, { onOpen } = {}) {
  const section = el('section', 'nfl-games');
  const heading = el('h2', null, 'Matched games');
  const summary = el('p', 'nfl-games-summary');
  const empty = el('div', 'empty-state');
  empty.hidden = true;
  const table = el('table', 'games-table');
  const thead = el('thead');
  const headRow = el('tr');
  const sortButtons = {};
  for (const [label, key] of [
    ['Date', 'date'],
    ['Matchup', null],
    ['Score', null],
    ['Network', null],
    ['Crew', null],
    ['Viewers', 'viewers'],
    ['Source', null],
  ]) {
    const th = el('th');
    th.scope = 'col';
    if (key) {
      const b = el('button');
      b.type = 'button';
      b.dataset.sort = key;
      b.appendChild(document.createTextNode(label));
      b.appendChild(el('span', 'sort-glyph'));
      th.appendChild(b);
      sortButtons[key] = b;
    } else {
      th.textContent = label;
    }
    headRow.appendChild(th);
  }
  thead.appendChild(headRow);
  const tbody = el('tbody');
  table.append(thead, tbody);
  const head = el('div', 'module-head');
  head.append(heading);
  const scroll = el('div', 'table-scroll');
  scroll.append(table);
  section.append(head, summary, empty, scroll);
  attachScrollCue(scroll, head);
  host.appendChild(section);

  let sort = { key: 'date', dir: 'desc' };
  let current = [];

  function syncHeaders() {
    for (const [key, b] of Object.entries(sortButtons)) {
      const active = sort.key === key;
      const value = active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none';
      b.closest('th').setAttribute('aria-sort', value);
      b.setAttribute('aria-sort', value);
      b.querySelector('.sort-glyph').textContent = active ? (sort.dir === 'asc' ? '▲' : '▼') : '';
    }
  }

  function paint() {
    syncHeaders();
    const sorted = [...current].sort((a, b) => compareRows(sort, a, b));
    tbody.replaceChildren(...sorted.map((r) => buildRow(r, onOpen)));
  }

  for (const [key, b] of Object.entries(sortButtons)) {
    b.addEventListener('click', () => {
      sort = sort.key === key ? { key, dir: sort.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: 'desc' };
      paint();
    });
  }

  return {
    render(rows, { emptyKind = 'nothing', selectionLabel = '', summary: summaryOverride } = {}) {
      current = rows;
      if (rows.length === 0) {
        table.hidden = true;
        empty.hidden = false;
        summary.textContent = '';
        if (emptyKind === 'filtered') {
          empty.replaceChildren(
            el('h3', null, 'No matching games'),
            el('p', null, `No games match the current filters for ${selectionLabel}.`),
            el('p', null, 'Try widening the season range, or clear a filter.'),
          );
        } else {
          empty.replaceChildren(
            el('h3', null, 'Nothing selected'),
            el('p', null, 'Pick a team, a booth, or a game from the chart to list matching games.'),
            el('p', null, 'You can also search announcers above.'),
          );
        }
        tbody.replaceChildren();
        syncHeaders();
        return;
      }
      empty.hidden = true;
      table.hidden = false;
      summary.textContent = typeof summaryOverride === 'string' ? summaryOverride : summaryText(rows);
      paint();
    },
    getSort() {
      return { ...sort };
    },
    destroy() {
      section.remove();
    },
  };
}
