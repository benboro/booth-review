/**
 * MLB Matched games table (D-02, D-22). Selection-driven: rows come from the
 * picked booth or postseason cell. A self-contained component that builds and
 * owns its DOM inside `host`.
 *
 * DOM is built only with createElement/textContent; there are no external
 * links in the table (the panel carries the credits).
 */

import { nameWithRoles, makeRolePill, makePill, currentTheme } from '../../modules/pill.js';
import { dateShortText } from './format.js';
import { CAUSE_COPY, crewSourceTag, viewersText } from './data.js';

const ROLE_ORDER = { pbp: 0, analyst: 1 };

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
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
  if (row.crew.length === 0) {
    td.className = 'no-rating';
    td.textContent = 'crew not listed';
    return;
  }
  const ordered = row.crew
    .map((c, idx) => ({ c, idx }))
    .sort((x, y) => (ROLE_ORDER[x.c.role] ?? 2) - (ROLE_ORDER[y.c.role] ?? 2) || x.idx - y.idx)
    .map(({ c }) => c);
  const nodes = [];
  for (const c of ordered) {
    if (nodes.length > 0) nodes.push(document.createTextNode(' · '));
    nodes.push(nameWithRoles(el('span', 'crew-name', c.name), makeRolePill(c.role)));
  }
  const tag = crewSourceTag(row.crewSource);
  if (tag) {
    const t = el('span', 'nfl-muted mlb-source-tag', tag);
    t.dataset.source = row.crewSource;
    nodes.push(document.createTextNode(' '), t);
  }
  td.replaceChildren(...nodes);
}

function roundCell(td, row) {
  if (!row.roundLabel) return;
  td.textContent = row.roundLabel;
  const bits = [];
  if (row.seriesLeague) bits.push(row.seriesLeague);
  if (row.seriesGame != null) bits.push(`game ${row.seriesGame}`);
  if (bits.length) {
    td.appendChild(el('br'));
    td.appendChild(el('span', 'nfl-muted', bits.join(', ')));
  }
}

function buildRow(row, onOpen) {
  const tr = el('tr', 'row-link');
  tr.addEventListener('click', (ev) => {
    if (ev.target instanceof Element && ev.target.closest('a, button')) return;
    onOpen?.(row.i, tr.querySelector('.nfl-matchup-btn'));
  });

  tr.appendChild(el('td', 'num', dateShortText(row)));

  const matchupTd = el('td');
  const button = el('button', 'nfl-matchup-btn', `${row.away} at ${row.home}`);
  button.type = 'button';
  button.dataset.game = String(row.i);
  button.setAttribute('aria-label', `Details for ${row.away} at ${row.home}`);
  button.addEventListener('click', () => onOpen?.(row.i, button));
  matchupTd.appendChild(button);
  tr.appendChild(matchupTd);

  const roundTd = el('td');
  roundCell(roundTd, row);
  tr.appendChild(roundTd);

  const outletTd = el('td');
  if (row.network == null) {
    outletTd.className = 'no-rating';
    outletTd.textContent = 'Not recorded';
  } else {
    outletTd.appendChild(makePill(row.network, row.networkFamily, currentTheme()));
  }
  tr.appendChild(outletTd);

  const crewTd = el('td');
  crewCell(crewTd, row);
  tr.appendChild(crewTd);

  const vTd = el('td');
  const vText = viewersText(row.viewers);
  if (vText) {
    vTd.className = 'num';
    vTd.textContent = vText;
  } else {
    vTd.className = 'no-rating';
    vTd.textContent = CAUSE_COPY[row.cause] ?? CAUSE_COPY.none;
  }
  tr.appendChild(vTd);
  return tr;
}

function summaryText(rows) {
  const seasons = rows.map((r) => r.season);
  const rated = rows.filter((r) => r.viewers != null).length;
  const lo = Math.min(...seasons);
  const hi = Math.max(...seasons);
  let text = `${rows.length} ${rows.length === 1 ? 'game' : 'games'} · ${lo === hi ? lo : `${lo}–${hi}`}`;
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
    ['Round', null],
    ['Outlet', null],
    ['Crew', null],
    ['Viewers', 'viewers'],
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
  section.append(heading, summary, empty, table);
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
    render(rows, { emptyKind = 'nothing', selectionLabel = '' } = {}) {
      current = rows;
      if (rows.length === 0) {
        table.hidden = true;
        empty.hidden = false;
        summary.textContent = '';
        if (emptyKind === 'filtered') {
          empty.replaceChildren(
            el('h3', null, 'No matching games'),
            el('p', null, `No games are listed for ${selectionLabel}.`),
          );
        } else {
          empty.replaceChildren(
            el('h3', null, 'Nothing selected'),
            el('p', null, 'Pick a booth or a postseason cell from the chart to list its games.'),
          );
        }
        tbody.replaceChildren();
        syncHeaders();
        return;
      }
      empty.hidden = true;
      table.hidden = false;
      summary.textContent = summaryText(rows);
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
