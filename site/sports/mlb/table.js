/**
 * MLB Matched games table (D-02, D-22). Selection-driven: rows come from the
 * picked booth or postseason cell. A self-contained component that builds and
 * owns its DOM inside `host`.
 *
 * DOM is built only with createElement/textContent; there are no external
 * links in the table (the panel carries the credits).
 */

import { crewList, nameWithRoles, makeRolePill } from '../../modules/pill.js';
import { networkMark } from '../../modules/network.js';
import { attachScrollCue } from '../../modules/scroll-cue.js';
import { dateShortText } from './format.js';
import { formatViewers } from '../../modules/format.js';
import { CAUSE_COPY } from './data.js';

const ROLE_ORDER = { pbp: 0, analyst: 1 };

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

/** Row order: active key and direction, unrated (then window-level) always last, ties by date then index. */
function compareRows(sort, a, b) {
  let cmp = 0;
  if (sort.key === 'viewers') {
    // Unrated rows last, then window-level figures (a whole broadcast window's audience),
    // so they are never ranked against true per-game figures.
    const tier = (r) => (r.viewers == null ? 2 : r.scope === 'window' ? 1 : 0);
    if (tier(a) !== tier(b)) return tier(a) - tier(b);
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
  const notes = [];
  for (const c of ordered) {
    nodes.push(nameWithRoles(el('span', 'crew-name', c.name), makeRolePill(c.role)));
  }
  td.replaceChildren(crewList(nodes, notes));
}

function roundCell(td, row) {
  if (!row.roundLabel) return;
  td.textContent = row.roundShort;
  td.title = row.roundLabel;
  const bits = [];
  if (row.seriesLeague) bits.push(row.seriesLeague);
  if (row.seriesGame != null) bits.push(`Game ${row.seriesGame}`);
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

  tr.appendChild(el('td', 'date', dateShortText(row)));

  const matchupTd = el('td', 'matchup');
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
    outletTd.appendChild(networkMark({ id: row.networkId, name: row.network, family: row.networkFamily }));
  }
  tr.appendChild(outletTd);

  const crewTd = el('td');
  crewCell(crewTd, row);
  tr.appendChild(crewTd);

  const vTd = el('td');
  if (row.viewers != null) {
    vTd.className = 'num';
    vTd.textContent = formatViewers(row.viewers);
    if (row.scope === 'window') vTd.append(document.createTextNode(' '), windowTag());
  } else {
    vTd.className = 'num no-rating';
    vTd.textContent = CAUSE_COPY[row.cause] ?? CAUSE_COPY.none;
  }
  tr.appendChild(vTd);
  return tr;
}

/** How the subtitle reads the active sort (same wording as the CFB table). */
function sortPhrase(sort) {
  if (sort.key === 'viewers') return sort.dir === 'desc' ? 'most viewers first' : 'fewest viewers first';
  return sort.dir === 'desc' ? 'newest first' : 'oldest first';
}

function summaryText(rows) {
  const seasons = rows.map((r) => r.season);
  const rated = rows.filter((r) => r.viewers != null).length;
  const lo = Math.min(...seasons);
  const hi = Math.max(...seasons);
  let text = `${rows.length} ${rows.length === 1 ? 'game' : 'games'}, ${lo === hi ? lo : `${lo}–${hi}`}`;
  if (rated > 0) text += `, ${rated} rated`;
  return text;
}

/**
 * @param {HTMLElement} host
 * @param {{onOpen?: (i: number, button: HTMLElement) => void}} opts
 */
/** The `window` tag for an audience that covers the whole broadcast window (also used by the Apple rows). */
export function windowTag() {
  const tag = el('span', 'nfl-muted mlb-source-tag', 'window');
  tag.dataset.scope = 'window';
  tag.title = 'Audience of the whole broadcast window, not this game alone';
  return tag;
}

export function createGamesTable(host, { onOpen } = {}) {
  const section = el('section', 'nfl-games');
  const heading = el('h2', null, 'Matched games');
  const subtitle = el('p', 'module-subtitle');
  subtitle.id = 'mlb-matched-subtitle';
  subtitle.hidden = true;
  const summary = el('p', 'nfl-games-summary');
  const empty = el('div', 'empty-state');
  empty.hidden = true;
  const table = el('table', 'games-table');
  const thead = el('thead');
  const headRow = el('tr');
  const sortButtons = {};
  // Viewers holds numbers, so its head aligns right like its cells; Date is a text date
  // ("Sun, Aug 31"), left-aligned and never wrapped (brief §5).
  for (const [label, key, numeric] of [
    ['Date', 'date'],
    ['Matchup', null],
    ['Round', null],
    ['Network', null],
    ['Crew', null],
    ['Viewers', 'viewers', true],
  ]) {
    const th = el('th', numeric ? 'num' : null);
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
  section.append(head, subtitle, summary, empty, scroll);
  attachScrollCue(scroll, head);
  host.appendChild(section);

  let sort = { key: 'date', dir: 'desc' };
  let current = [];
  let selectionLabelNow = '';
  let lastKey = null;

  function syncHeaders() {
    for (const [key, b] of Object.entries(sortButtons)) {
      const active = sort.key === key;
      const value = active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none';
      b.closest('th').setAttribute('aria-sort', value);
      b.setAttribute('aria-sort', value);
      b.querySelector('.sort-glyph').textContent = active ? (sort.dir === 'asc' ? '▲' : '▼') : '';
    }
  }

  function syncSubtitle() {
    if (!selectionLabelNow || current.length === 0) {
      subtitle.hidden = true;
      subtitle.textContent = '';
      subtitle.removeAttribute('title');
      return;
    }
    subtitle.textContent = `${selectionLabelNow}, ${sortPhrase(sort)}`;
    subtitle.title = subtitle.textContent;
    subtitle.hidden = false;
  }

  function paint() {
    syncHeaders();
    syncSubtitle();
    const sorted = [...current].sort((a, b) => compareRows(sort, a, b));
    tbody.replaceChildren(...sorted.map((r) => buildRow(r, onOpen)));
  }

  for (const [key, b] of Object.entries(sortButtons)) {
    b.addEventListener('click', () => {
      sort = sort.key === key ? { key, dir: sort.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: key === 'date' ? 'asc' : 'desc' };
      paint();
    });
  }

  return {
    render(rows, { emptyKind = 'nothing', selectionLabel = '', selectionKey = null } = {}) {
      current = rows;
      selectionLabelNow = selectionLabel;
      if (selectionKey !== lastKey) sort = { key: 'date', dir: 'desc' };
      lastKey = selectionKey;
      if (rows.length === 0) {
        table.hidden = true;
        empty.hidden = false;
        summary.textContent = '';
        syncSubtitle();
        if (emptyKind === 'filtered') {
          empty.replaceChildren(
            el('h3', null, 'No matching games'),
            el('p', null, `No games are listed for ${selectionLabel}.`),
          );
        } else {
          empty.replaceChildren(
            el('h3', null, 'Nothing selected'),
            el('p', null, 'Pick a booth, a postseason cell or a season to list its games.'),
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
