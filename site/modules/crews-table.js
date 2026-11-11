/**
 * Shared Crews table mechanics (Phase 15 extraction of Phase 14's crews.js): sort state,
 * 25-row paging with "View more", the row click and chevron that open a row's 10-at-a-time
 * game list (laid under the row table's columns), the filter button that picks a row, the key map, the
 * polite live-region seat and refocus after a rebuild. Sport modules (CFB crews.js, NFL
 * Crews) supply the columns, cells, game rows and pick behaviour and keep their own
 * `createTableState()` so one sport's paging never touches the other's (T-15-03).
 *
 * All DOM text goes through `textContent` (T-15-02); nothing here injects markup.
 */

import { attachScrollCue } from './scroll-cue.js';

/** Rows the table opens with, and adds per "View more" click (D-13). */
export const PAGE = 25;

/** Games a first expansion shows, and added per "View 10 more" (D-15). */
export const GAME_PAGE = 10;

/** Rows PageUp/PageDown move (CFB-04). */
const PAGE_JUMP = 10;

/** Fresh per-sport table state: shown count, open rows, row models and announce memory. */
export function createTableState() {
  return {
    shown: PAGE,
    lastSignature: null,
    /** Open rows -> games shown in each; reset with the shown count (D-13). */
    expanded: new Map(),
    /** The row model behind each `tr.crews-row`, for the key handler. */
    rowOf: new WeakMap(),
    /** Sort and mode last announced, so only a change of either speaks. */
    lastSortKey: null,
    /** Disposers for the scroll cues on the table the last render built. */
    detachCues: [],
  };
}

export function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
}

/**
 * One game's excitement cell for a sport's game list, blank when the game has none (as the
 * Avg excitement column leaves it). Sits just before Viewers; its row takes `has-exc`.
 * @param {number|null|undefined} value
 */
export function excitementCell(value) {
  const td = el('td', 'num crews-game-exc');
  if (value != null) td.append(el('span', 'crews-figure', value.toFixed(1)));
  return td;
}

/**
 * The sort the table currently shows: null state means the sport's default.
 * @param {{csort?: object|null}} state
 * @param {boolean} perSeason - whether rows are per season right now (the displayed order)
 * @param {{defaultSort: Function}} sortSpec
 */
export function activeSort(state, perSeason, sortSpec) {
  return state.csort ?? sortSpec.defaultSort(perSeason);
}

/**
 * Next csort for a click on `key`: natural, reversed, then back to the default (null).
 * The "is this the default, so store null" test follows the stored Per season preference
 * (`state.perseason !== false`), the codec's own rule, not the displayed one: otherwise a
 * Games click on a one-season range reads as the pooled default and drops csort, and
 * widening the range falls back to Season (P14-FU-2).
 */
export function nextSort(state, key, perSeason, sortSpec) {
  const natural = sortSpec.naturalDir[key];
  const reversed = natural === 'asc' ? 'desc' : 'asc';
  const current = activeSort(state, perSeason, sortSpec);
  const flip = (dir) => (dir === 'asc' ? 'desc' : 'asc');
  let next;
  if (current.key !== key) next = { key, dir: natural };
  else if (state.csort == null) next = { key, dir: flip(current.dir) };
  else if (current.dir === natural) next = { key, dir: reversed };
  else return null;
  const def = sortSpec.defaultSort(state.perseason !== false);
  return next.key === def.key && next.dir === def.dir ? null : next;
}

function sortGlyph(state, key, perSeason, sortSpec) {
  const current = activeSort(state, perSeason, sortSpec);
  if (current.key !== key) return '↕';
  return current.dir === 'desc' ? '↓' : '↑';
}

function ariaSort(state, key, perSeason, sortSpec) {
  const current = activeSort(state, perSeason, sortSpec);
  if (current.key !== key) return 'none';
  return current.dir === 'desc' ? 'descending' : 'ascending';
}

/** The module's visually hidden polite status seat, created once per container. */
export function ensureSeat(container) {
  let seat = container.querySelector(':scope > .crews-status');
  if (!seat) {
    seat = el('p', 'visually-hidden crews-status');
    seat.setAttribute('role', 'status');
    seat.setAttribute('aria-live', 'polite');
    container.prepend(seat);
  }
  return seat;
}

/** Writes `text` to the module's polite status seat. */
export function announce(container, text) {
  const seat = container.querySelector(':scope > .crews-status');
  if (seat) seat.textContent = text;
}

const SVG_NS = 'http://www.w3.org/2000/svg';

/** A small funnel drawn in currentColor, so it follows the button's state colour. */
function funnelIcon() {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('viewBox', '0 0 16 16');
  svg.setAttribute('width', '14');
  svg.setAttribute('height', '14');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  const path = document.createElementNS(SVG_NS, 'path');
  path.setAttribute('d', 'M2 3h12l-4.75 5.5V13l-2.5 1.25V8.5z');
  path.setAttribute('fill', 'none');
  path.setAttribute('stroke', 'currentColor');
  path.setAttribute('stroke-width', '1.4');
  path.setAttribute('stroke-linejoin', 'round');
  svg.append(path);
  return svg;
}

/**
 * The filter button after a row's names: it picks the row (or clears the pick) while a click
 * anywhere else on the row opens its games. Its state lives in `aria-pressed`.
 */
function pickButton(row, tr, tc, picked, firstRow) {
  const b = el('button', 'crews-pick');
  b.type = 'button';
  b.tabIndex = firstRow ? 0 : -1;
  b.setAttribute('aria-pressed', String(picked));
  const label = tc.pickLabel?.(row, picked) ?? (picked ? 'Clear the crew filter' : 'Filter to this crew');
  b.setAttribute('aria-label', `${label}: ${row.names}`);
  b.title = label;
  b.append(funnelIcon());
  b.addEventListener('click', (e) => {
    e.stopPropagation();
    tc.onPick(row, tr);
  });
  return b;
}

function buildRow(row, tc, firstRow) {
  const { ts } = tc;
  const tr = el('tr', 'crews-row');
  tr.dataset.rowKey = row.rowKey;
  tr.dataset.crewKey = tc.crewKeyOf(row);
  tr.tabIndex = firstRow ? 0 : -1;
  const picked = tc.isPicked(row);
  const open = ts.expanded.has(row.rowKey);
  tr.setAttribute('aria-expanded', String(open));
  tr.setAttribute('aria-label', row.names);
  if (picked) tr.classList.add('is-picked');
  else if (tc.isHighlighted?.(row)) tr.classList.add('is-highlighted');

  const chevronCell = el('td', 'crews-chevron-cell');
  const chevron = el('button', 'crews-chevron');
  chevron.type = 'button';
  chevron.tabIndex = firstRow ? 0 : -1;
  chevron.setAttribute('aria-label', open ? 'Hide games' : 'Show games');
  chevron.addEventListener('click', (e) => {
    e.stopPropagation();
    setExpanded(tr, !ts.expanded.has(row.rowKey), tc);
  });
  chevronCell.append(chevron);
  ts.rowOf.set(tr, row);
  const cells = tc.buildCells(row, tr);
  // The names cell, not simply the first one: MLB's first cell is the booth position.
  const names = cells.find((c) => c.classList.contains('crews-name')) ?? cells[0];
  if (names && (tc.canPick?.(row) ?? true)) {
    names.classList.add('has-pick');
    // Right after the names: before a person row's "with ..." partner list, if it has one.
    const button = pickButton(row, tr, tc, picked, firstRow);
    const partners = names.querySelector(':scope > .crews-partners');
    if (partners) partners.before(button);
    else names.append(button);
  }
  tr.append(chevronCell, ...cells);
  // Most readers click a name to see its games, so the whole row opens and closes; a link or
  // the filter button inside it keeps its own action.
  tr.addEventListener('click', (e) => {
    if (e.target instanceof Element && e.target.closest('a, .crews-pick')) return;
    // A drag that selected some of the names is a copy, not a request to open the row.
    if (window.getSelection?.()?.isCollapsed === false) return;
    setExpanded(tr, !ts.expanded.has(row.rowKey), tc);
  });
  return tr;
}

/**
 * Lays a game list's columns under the row table's columns: a text column starts where its
 * anchor column starts (so Date sits under Season), a number column ends where its anchor ends
 * (so Viewers lines up with Avg viewers), and a column with no anchor present takes its fixed
 * `width` just before the next column. `cols[k].anchor` is a parent column key or a list of
 * fallbacks. Positions are px from the holder's left edge.
 *
 * @param {Array<{anchor?: string|string[], num?: boolean, width?: number}>} cols
 * @param {Map<string, {left: number, right: number}>} parent
 * @returns {{starts: number[], ends: number[]}|null} null when a column cannot be placed
 */
export function layoutGameCols(cols, parent) {
  const n = cols.length;
  const starts = new Array(n).fill(null);
  const ends = new Array(n).fill(null);
  const anchorOf = (k) => [].concat(cols[k].anchor ?? []).find((key) => parent.has(key)) ?? null;
  const anchors = cols.map((_, k) => anchorOf(k));
  cols.forEach((c, k) => {
    const a = anchors[k];
    if (a == null) return;
    if (c.num) ends[k] = parent.get(a).right;
    else starts[k] = parent.get(a).left;
  });
  // A column with no anchor sits just before the next placed text column.
  for (let k = n - 1; k >= 0; k -= 1) {
    if (anchors[k] != null || cols[k].num) continue;
    if (k + 1 >= n || starts[k + 1] == null || cols[k].width == null) return null;
    starts[k] = starts[k + 1] - cols[k].width;
  }
  for (let k = 0; k < n; k += 1) {
    if (cols[k].num) {
      if (k === 0 || ends[k - 1] == null) return null;
      starts[k] = ends[k - 1];
    } else if (k + 1 < n && !cols[k + 1].num) {
      ends[k] = starts[k + 1];
    } else {
      ends[k] = anchors[k] != null ? parent.get(anchors[k]).right : starts[k] + (cols[k].width ?? 0);
    }
  }
  for (let k = 0; k < n; k += 1) if (!(ends[k] > starts[k])) return null;
  return { starts, ends };
}

/**
 * Sizes every aligned game list under `table` to its row table's columns. A phone's stacked
 * game items (display: block) keep their own layout, so their sizes are cleared instead.
 * @param {HTMLTableElement} table - a `table.crews-table`
 */
export function alignGameLists(table) {
  const lists = table.querySelectorAll('table.crews-games[data-aligned]');
  if (!lists.length) return;
  const heads = new Map();
  for (const th of table.querySelectorAll(':scope > thead th[data-col]')) {
    const r = th.getBoundingClientRect();
    heads.set(th.dataset.col, { left: r.left, right: r.right });
  }
  for (const list of lists) {
    const cols = list.querySelectorAll(':scope > colgroup > col');
    const clear = () => {
      list.style.removeProperty('width');
      list.style.removeProperty('margin-left');
      list.classList.remove('is-aligned');
      for (const col of cols) col.style.removeProperty('width');
    };
    const holder = list.parentElement;
    if (!holder || getComputedStyle(list).display !== 'table') {
      clear();
      continue;
    }
    const origin = holder.getBoundingClientRect().left;
    const parent = new Map([...heads].map(([k, v]) => [k, { left: v.left - origin, right: v.right - origin }]));
    const placed = layoutGameCols(list.gameCols ?? [], parent);
    if (!placed) {
      clear();
      continue;
    }
    const { starts, ends } = placed;
    cols.forEach((col, k) => {
      col.style.width = `${ends[k] - starts[k]}px`;
    });
    list.style.marginLeft = `${starts[0]}px`;
    list.style.width = `${ends[ends.length - 1] - starts[0]}px`;
    list.classList.add('is-aligned');
  }
}

/** Aligns the game lists of the row table that holds `node`, once it is in the page. */
function alignWithin(node) {
  const table = node.isConnected ? node.closest('table.crews-table') : null;
  if (table) alignGameLists(table);
}

/** Draws the game list and its "View 10 more" into `holder` for a row showing `count` games. */
function drawGames(holder, row, tc, count) {
  const { ts } = tc;
  holder.replaceChildren();
  const shownGames = row.games.slice(0, count);
  const table = el('table', 'games-table crews-games');
  // `gameCols` (label, anchor, numeric, hidden label) lines the list up under the row table;
  // a sport that passes only `gameHeads` keeps the list's own column widths.
  const cols = tc.gameCols ?? tc.gameHeads.map((head) => ({ head, num: head === 'Viewers' || head === 'Excitement' }));
  const head = el('tr');
  for (const c of cols) {
    const th = el('th', [c.num ? 'num' : null, c.cls].filter(Boolean).join(' ') || null);
    if (c.srHead) th.append(el('span', 'visually-hidden', c.srHead));
    else th.textContent = c.head;
    th.scope = 'col';
    head.append(th);
  }
  if (tc.gameCols) {
    const group = el('colgroup');
    for (const c of cols) group.append(el('col', c.cls ? `${c.cls}-col` : null));
    table.append(group);
    table.dataset.aligned = '';
    table.gameCols = cols;
  }
  const thead = el('thead');
  thead.append(head);
  const tbody = el('tbody');
  for (const i of shownGames) tbody.append(tc.gameRow(row, i));
  table.append(thead, tbody);
  holder.append(table);
  alignWithin(holder);
  const left = row.games.length - shownGames.length;
  if (left > 0) {
    const step = Math.min(GAME_PAGE, left);
    const more = el('button', 'crews-more crews-games-more', `View ${step} more (${left} left)`);
    more.type = 'button';
    more.addEventListener('click', () => {
      ts.expanded.set(row.rowKey, count + step);
      drawGames(holder, row, tc, count + step);
      holder.querySelectorAll('tr.crews-game')[count]?.focus();
      // CFB announces on its panel; any other sport on the nearest ancestor that owns the status seat.
      announce(holder.closest('#crews-panel') ?? holder.closest(':has(> .crews-status)') ?? holder, `${step} more games shown, ${left - step} left.`);
    });
    holder.append(more);
  }
}

/** The full-width sub-row under a row: the sport's extra head (partners) and the paged game list. */
function buildSubRow(row, tc) {
  const tr = el('tr', 'crews-expanded');
  tr.dataset.subFor = row.rowKey;
  const td = el('td');
  td.colSpan = tc.colCount;
  const inner = el('div', 'crews-expanded-inner');
  for (const node of tc.subHead?.(row) ?? []) inner.append(node);
  const holder = el('div', 'crews-games-holder');
  drawGames(holder, row, tc, tc.ts.expanded.get(row.rowKey) ?? GAME_PAGE);
  inner.append(holder);
  td.append(inner);
  tr.append(td);
  return tr;
}

/** Opens or closes a row's sub-row in place; the open state lives in `ts.expanded`. */
function setExpanded(tr, open, tc) {
  const { ts } = tc;
  const row = ts.rowOf.get(tr);
  if (!row || open === ts.expanded.has(row.rowKey)) return;
  const next = tr.nextElementSibling;
  const sub = next?.classList.contains('crews-expanded') ? next : null;
  if (open) {
    ts.expanded.set(row.rowKey, GAME_PAGE);
    tr.after(buildSubRow(row, tc));
    alignWithin(tr);
  } else {
    ts.expanded.delete(row.rowKey);
    sub?.remove();
  }
  tr.setAttribute('aria-expanded', String(open));
  tr.querySelector('.crews-chevron')?.setAttribute('aria-label', open ? 'Hide games' : 'Show games');
}

/** Moves the roving tab stop to `tr` (its chevron and filter button follow it). */
function setActive(tbody, tr) {
  for (const r of tbody.querySelectorAll(':scope > tr.crews-row')) {
    const on = r === tr;
    r.tabIndex = on ? 0 : -1;
    for (const b of r.querySelectorAll('.crews-chevron, .crews-pick')) b.tabIndex = on ? 0 : -1;
  }
}

/** Key map for the rows and their game lists (CFB-04); bound once per tbody. */
function bindKeys(tbody, tc) {
  const { ts } = tc;
  let armed = null;
  const rows = () => [...tbody.querySelectorAll(':scope > tr.crews-row')];
  tbody.addEventListener('focusin', (e) => {
    const r = e.target instanceof Element ? e.target.closest('tr.crews-row') : null;
    if (r) setActive(tbody, r);
  });
  tbody.addEventListener('keydown', (e) => {
    const t = e.target;
    if (!(t instanceof Element)) return;
    const rowEl = t.closest('tr.crews-row');
    const sub = t.closest('tr.crews-expanded');
    if (e.key === 'Escape') {
      const owner = rowEl ?? (sub ? sub.previousElementSibling : null);
      if (owner && owner.getAttribute('aria-expanded') === 'true') {
        e.preventDefault();
        setExpanded(owner, false, tc);
        owner.focus();
      }
      return;
    }
    if (t.classList.contains('crews-game')) {
      if ((e.key === 'Enter' || e.key === ' ') && !e.repeat) {
        e.preventDefault();
        armed = t;
      }
      return;
    }
    if (t !== rowEl) return;
    const all = rows();
    const at = all.indexOf(rowEl);
    let target = null;
    if (e.key === 'ArrowDown') target = all[Math.min(at + 1, all.length - 1)];
    else if (e.key === 'ArrowUp') target = all[Math.max(at - 1, 0)];
    else if (e.key === 'Home') target = all[0];
    else if (e.key === 'End') target = all[all.length - 1];
    else if (e.key === 'PageDown') target = all[Math.min(at + PAGE_JUMP, all.length - 1)];
    else if (e.key === 'PageUp') target = all[Math.max(at - PAGE_JUMP, 0)];
    else if (e.key === 'ArrowRight') setExpanded(rowEl, true, tc);
    else if (e.key === 'ArrowLeft') setExpanded(rowEl, false, tc);
    else if ((e.key === 'Enter' || e.key === ' ') && !e.repeat) {
      setExpanded(rowEl, rowEl.getAttribute('aria-expanded') !== 'true', tc);
    }
    else return;
    e.preventDefault();
    if (target) {
      setActive(tbody, target);
      target.focus();
    }
  });
  // A game row opens on keyup, once its own keydown armed it: opening on keydown would move
  // focus into the modal and leak this key's keyup to the modal's close button, and a keyup
  // that began elsewhere (closing the modal with Enter) must not reopen it.
  tbody.addEventListener('keyup', (e) => {
    if (!armed || e.target !== armed || (e.key !== 'Enter' && e.key !== ' ')) return;
    const i = Number(armed.dataset.game);
    armed = null;
    tc.openGame?.(i);
  });
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
  for (const cls of ['crews-chevron', 'crews-pick']) {
    if (!a.classList.contains(cls)) continue;
    const owner = a.closest('tr.crews-row');
    return owner ? `tr[data-row-key="${CSS.escape(owner.dataset.rowKey)}"] .${cls}` : null;
  }
  return null;
}

function buildTable(rows, tc) {
  const { ts, state, perSeason, sortSpec } = tc;
  const wrap = el('div', 'crews-table-wrap table-scroll');
  const table = el('table', 'games-table crews-table');
  table.setAttribute('role', 'grid');
  for (const c of tc.tableClasses ?? []) table.classList.add(c);
  const headRow = el('tr');
  const chevronTh = el('th', 'crews-chevron-cell');
  chevronTh.scope = 'col';
  chevronTh.append(el('span', 'visually-hidden', 'Show games'));
  headRow.append(chevronTh);
  for (const [key, label, numeric] of tc.columns) {
    const th = el('th', `crews-col-${key}${numeric ? ' num' : ''}`);
    th.scope = 'col';
    th.dataset.col = key;
    th.setAttribute('aria-sort', ariaSort(state, key, perSeason, sortSpec));
    const b = el('button');
    b.type = 'button';
    b.dataset.sortKey = key;
    b.append(
      el('span', 'crews-sort-label', label),
      el('span', 'sort-glyph', sortGlyph(state, key, perSeason, sortSpec)),
    );
    b.addEventListener('click', () => tc.onSort(nextSort(state, key, perSeason, sortSpec)));
    th.append(b);
    headRow.append(th);
  }
  const thead = el('thead');
  thead.append(headRow);
  const tbody = el('tbody');
  rows.forEach((row, k) => {
    tbody.append(buildRow(row, tc, k === 0));
    if (ts.expanded.has(row.rowKey)) tbody.append(buildSubRow(row, tc));
  });
  bindKeys(tbody, tc);
  table.append(thead, tbody);
  wrap.append(table);
  // The expanded sub-row is as wide as the scroller's visible width, so it stays in view on a phone.
  if (typeof ResizeObserver === 'function') {
    const ro = new ResizeObserver(() => {
      wrap.style.setProperty('--crews-scroll-w', `${wrap.clientWidth}px`);
      alignGameLists(table);
    });
    ro.observe(wrap);
    ts.detachCues.push(() => ro.disconnect());
  }
  ts.detachCues.push(attachScrollCue(wrap, null));
  return wrap;
}

/**
 * Renders tools, the paged sortable table (or the empty note) and the footer into `container`.
 *
 * @param {HTMLElement} container
 * @param {object} opts
 * @param {ReturnType<typeof createTableState>} opts.ts - this sport's table state
 * @param {{csort?: object|null, perseason?: boolean}} opts.state - the URL state (sort and Per season preference)
 * @param {boolean} opts.perSeason - whether rows are per season right now
 * @param {{naturalDir: object, defaultSort: Function}} opts.sortSpec
 * @param {object[]} opts.rows - already sorted
 * @param {string} opts.signature - changes whenever paging and open rows must reset
 * @param {Array<[string, string, boolean]>} opts.columns - [key, label, numeric]
 * @param {string} opts.label - sort announcement noun, e.g. `Crews`
 * @param {string} opts.modeKey - mode part of the announce key
 * @param {number} opts.colCount - columns incl. the chevron, for the sub-row colSpan
 * @param {string[]} [opts.tableClasses]
 * @param {string[]} [opts.gameHeads] - the expanded game list's column labels (unaligned)
 * @param {Array<{head?: string, srHead?: string, cls?: string, anchor?: string|string[], num?: boolean, width?: number}>} [opts.gameCols]
 *   - the game list's columns laid under the row table's (see `layoutGameCols`); wins over gameHeads
 * @param {() => HTMLElement} opts.buildTools
 * @param {() => HTMLElement|null} [opts.buildEmpty] - drawn instead of the table when `rows` is empty
 * @param {(container: HTMLElement) => void} [opts.footer]
 * @param {(row: object) => boolean} opts.isPicked
 * @param {(row: object) => boolean} [opts.isHighlighted]
 * @param {(row: object) => string} opts.crewKeyOf
 * @param {(row: object, tr: HTMLElement) => HTMLElement[]} opts.buildCells - cells after the chevron
 * @param {(row: object, i: number) => HTMLElement} opts.gameRow
 * @param {(row: object) => HTMLElement[]} [opts.subHead]
 * @param {(row: object, tr: HTMLElement) => void} opts.onPick - the filter button's action
 * @param {(row: object) => boolean} [opts.canPick] - false hides a row's filter button
 * @param {(row: object, picked: boolean) => string} [opts.pickLabel] - the filter button's label
 * @param {(next: object|null) => void} opts.onSort
 * @param {(i: number) => void} [opts.openGame]
 * @param {() => void} opts.rerender - redraws the whole panel (View more)
 */
export function renderCrewsTable(container, opts) {
  const { ts, rows } = opts;
  if (opts.signature !== ts.lastSignature) {
    ts.shown = PAGE;
    ts.expanded.clear();
    ts.lastSignature = opts.signature;
  }

  const refocus = focusSelector(container);
  // Every render rebuilds the table, so release the old one's scroll-cue observers first.
  ts.detachCues.splice(0).forEach((detach) => detach());
  // The status seat is kept across renders so a message written just before one is not lost.
  const seat = ensureSeat(container);
  for (const child of [...container.children]) if (child !== seat) child.remove();
  container.append(opts.buildTools());

  if (rows.length === 0) {
    const empty = opts.buildEmpty?.();
    if (empty) container.append(empty);
  } else {
    const reveal = rows.findIndex((r) => opts.isPicked(r));
    const count = Math.min(rows.length, Math.max(ts.shown, reveal + 1));
    const wrap = buildTable(rows.slice(0, count), opts);
    container.append(wrap);
    alignGameLists(wrap.querySelector('table.crews-table'));
    const sortNow = activeSort(opts.state, opts.perSeason, opts.sortSpec);
    const sortKey = `${opts.modeKey}|${sortNow.key}|${sortNow.dir}`;
    if (ts.lastSortKey !== null && sortKey !== ts.lastSortKey) {
      const label = opts.columns.find((c) => c[0] === sortNow.key)?.[1] ?? sortNow.key;
      const dir = sortNow.dir === 'desc' ? 'descending' : 'ascending';
      seat.textContent = `${opts.label} sorted by ${label}, ${dir}, ${count} of ${rows.length} rows shown.`;
    }
    ts.lastSortKey = sortKey;
    const left = rows.length - count;
    if (left > 0) {
      const step = Math.min(PAGE, left);
      const more = el('button', 'crews-more', `View ${step} more (${left} left)`);
      more.type = 'button';
      more.addEventListener('click', () => {
        ts.shown = count + step;
        opts.rerender();
        const rowsNow = container.querySelectorAll('tbody tr.crews-row');
        rowsNow[count]?.focus();
        announce(container, `${step} more rows shown, ${left - step} left.`);
      });
      container.append(more);
    }
    container.append(el('p', 'caption crews-count', `Showing ${count} of ${rows.length} rows.`));
  }
  opts.footer?.(container);

  if (refocus) container.querySelector(refocus)?.focus();
}
