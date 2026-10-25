/**
 * MLB Postseason booths view (SPORT-07): a season-by-round grid, 2014 onward.
 *
 * Rows are seasons, columns the rounds that appear in the data. Each cell shows the
 * outlet, the booth names (Division and Championship Series split into AL and NL),
 * games, mean excitement per game and, where Ratings Reference has one, viewers.
 * A season with an incomplete
 * crew record carries its coverage percentage, and a cell with no listed crew says so.
 *
 * Each cell (or league sub-block) is a button that selects its games into the games
 * table. On phones the grid collapses to one stacked block per season (CSS only).
 * Everything is built with createElement and textContent only.
 */
import { ROUND_LABELS, ROUND_SHORT, boothLabelOf, cellKey, cellLabel, personName } from '../data.js';
import { tableGames } from '../state.js';
import { networkMark, sortNetworks } from '../../../modules/network.js';
import { externalLink } from '../../../modules/panel-parts.js';
import { makeRolePill, nameWithRoles } from '../../../modules/pill.js';
import { attachScrollCue } from '../../../modules/scroll-cue.js';

export const PENDING_TEXT = 'pending Retrosheet 2026';
export const NO_CREW_TEXT = 'crew not listed';
const ROUND_ORDER = ['wild_card', 'division', 'lcs', 'world_series', 'tiebreak'];

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

/** Booth lines the phone Booths cell shows before a "+N more" last line (13-14 line budget). */
export const PHONE_BOOTH_LINES = 3;

const refs = {
  ctx: null, head: null, body: null, captions: null, table: null, phoneBody: null,
  status: null, wrap: null, phoneNotes: null,
};
let current = null;
/** Data key of the grid button that holds the roving tab stop (survives re-renders). */
let activeKey = null;
/** Data keys of the grid, row by row, for keyboard navigation (rebuilt on every render). */
let gridButtons = [];

const GRID_PAGE = 5;
const BTN_SEL = '.mlb-season-btn, .mlb-cell-btn[data-cell]';

function btnKey(btn) {
  return btn.dataset.seasonCell ?? btn.dataset.cell;
}

/** Select the key, or clear it when it is already picked; announce either in the live region. */
function toggleCell(key) {
  const { ctx } = refs;
  if (!current?.model.cells.has(key)) return;
  const label = cellLabel(current.model.cells.get(key));
  if (ctx.getState().cell === key) {
    ctx.clearSelection();
    announce('Selection cleared.');
    return;
  }
  ctx.setState({ cell: key });
  const n = tableGames(current.model, ctx.getState()).length;
  announce(`Selected ${label}, ${n} ${n === 1 ? 'game' : 'games'}.`);
}

function announce(text) {
  if (refs.status) refs.status.textContent = text;
}

/** Nearest non-empty column to `col` in a row (left wins a tie), or -1. */
function nearestColumn(row, col) {
  for (let d = 0; d < row.length; d += 1) {
    if (row[col - d]?.length) return col - d;
    if (row[col + d]?.length) return col + d;
  }
  return -1;
}

/**
 * Keyboard move over the Postseason grid. `grid` is rows of columns of sub-block ids (column 0
 * the Season button, an empty array for an empty cell); `pos` is `{ row, col, sub }`. Returns
 * the next position, or `pos` itself when the key does not move.
 */
export function nextGridTarget(grid, pos, key) {
  const { row, col, sub } = pos;
  const cols = grid[row] ?? [];
  const sideways = (step) => {
    for (let c = col + step; c >= 0 && c < cols.length; c += step) {
      if (cols[c].length) return { row, col: c, sub: sub < cols[c].length ? sub : 0 };
    }
    return pos;
  };
  const vertical = (target, subPick) => {
    if (target < 0 || target >= grid.length || target === row) return pos;
    const c = nearestColumn(grid[target], col);
    if (c < 0) return pos;
    const len = grid[target][c].length;
    return { row: target, col: c, sub: subPick === 'last' ? len - 1 : 0 };
  };
  switch (key) {
    case 'ArrowRight': return sideways(1);
    case 'ArrowLeft': return sideways(-1);
    case 'ArrowDown':
      return sub + 1 < cols[col].length ? { row, col, sub: sub + 1 } : vertical(row + 1, 'first');
    case 'ArrowUp':
      return sub > 0 ? { row, col, sub: sub - 1 } : vertical(row - 1, 'last');
    case 'Home': {
      const c = cols.findIndex((x) => x.length);
      return c < 0 ? pos : { row, col: c, sub: 0 };
    }
    case 'End': {
      let c = cols.length - 1;
      while (c >= 0 && !cols[c].length) c -= 1;
      // The row's last button: the final column's last sub-block (NL after AL).
      return c < 0 ? pos : { row, col: c, sub: cols[c].length - 1 };
    }
    case 'PageDown': return vertical(Math.min(row + GRID_PAGE, grid.length - 1), 'first');
    case 'PageUp': return vertical(Math.max(row - GRID_PAGE, 0), 'first');
    default: return pos;
  }
}

function gridIds() {
  return gridButtons.map((cols) => cols.map((subs) => subs.map(btnKey)));
}

function locate(btn) {
  for (let row = 0; row < gridButtons.length; row += 1) {
    for (let col = 0; col < gridButtons[row].length; col += 1) {
      const sub = gridButtons[row][col].indexOf(btn);
      if (sub >= 0) return { row, col, sub };
    }
  }
  return null;
}

function indexGrid() {
  gridButtons = [...refs.body.rows].map((tr) => [...tr.cells].map((cell) => [...cell.querySelectorAll(BTN_SEL)]));
  const all = gridButtons.flat(2);
  const want = all.find((b) => btnKey(b) === activeKey)
    ?? all.find((b) => b.getAttribute('aria-pressed') === 'true')
    ?? all[0];
  for (const b of all) b.tabIndex = b === want ? 0 : -1;
}

function setActive(btn) {
  activeKey = btnKey(btn);
  for (const b of gridButtons.flat(2)) b.tabIndex = b === btn ? 0 : -1;
}

function onGridKeydown(ev) {
  const btn = ev.target.closest?.(BTN_SEL);
  if (!btn || !refs.table.contains(btn)) return;
  if (ev.key === 'Enter' || ev.key === ' ') {
    ev.preventDefault();
    if (!ev.repeat) btn.click();
    return;
  }
  if (ev.key === 'Escape') {
    ev.preventDefault();
    if (refs.ctx.getState().cell != null) {
      refs.ctx.clearSelection();
      announce('Selection cleared.');
    }
    return;
  }
  const pos = locate(btn);
  if (!pos) return;
  const next = nextGridTarget(gridIds(), pos, ev.key);
  if (!['ArrowRight', 'ArrowLeft', 'ArrowDown', 'ArrowUp', 'Home', 'End', 'PageDown', 'PageUp'].includes(ev.key)) return;
  ev.preventDefault();
  const target = gridButtons[next.row]?.[next.col]?.[next.sub];
  if (!target || target === btn) return;
  setActive(target);
  target.focus();
  target.scrollIntoView({ block: 'nearest', inline: 'nearest' });
}

/** Space activates a button on keyup: swallow it so the keydown handler is the only trigger. */
function onGridKeyup(ev) {
  if (ev.key === ' ' && ev.target.closest?.(BTN_SEL)) ev.preventDefault();
}


function coveragePct(num, den) {
  return den > 0 ? Math.round((100 * num) / den) : null;
}

/** Group the postseason rows into sub-blocks keyed by cell key, merging outlets. */
function buildGrid(model) {
  const blocks = new Map();
  for (const r of model.postseason) {
    const leagueId = r.league == null ? null : model.leagues[r.league].id;
    const key = cellKey(r.season, r.round, leagueId);
    let b = blocks.get(key);
    if (!b) {
      b = {
        key, season: r.season, round: r.round, league: leagueId,
        outlets: [], outletSourceUrl: null, booths: [], games: 0, crewListed: 0,
        exciteSum: 0, exciteN: 0, viewerSum: 0, viewerN: 0,
      };
      blocks.set(key, b);
    }
    for (const idx of r.networks) {
      const net = model.networks[idx];
      if (net && !b.outlets.some((o) => o.name === net.name)) b.outlets.push({ id: net.id ?? null, name: net.name, family: net.family });
    }
    if (r.outlet_source_url && !b.outletSourceUrl) b.outletSourceUrl = r.outlet_source_url;
    for (const pair of r.booths) {
      if (!b.booths.some((p) => p[0] === pair[0] && p[1] === pair[1])) b.booths.push(pair);
    }
    b.games += r.games;
    b.crewListed += r.crew_listed;
    if (r.mean_excitement != null && r.excitement_n > 0) {
      b.exciteSum += r.mean_excitement * r.excitement_n;
      b.exciteN += r.excitement_n;
    }
    if (r.viewers_mean != null && r.viewers_n > 0) {
      b.viewerSum += r.viewers_mean * r.viewers_n;
      b.viewerN += r.viewers_n;
    }
  }
  // Several outlets read in network precedence: FOX before FS1, ABC before ESPN (U7).
  for (const b of blocks.values()) b.outlets = sortNetworks(b.outlets);
  return blocks;
}

function viewersText(mean) {
  return `${(mean / 1e6).toFixed(1)}M`;
}

function excitementLine(model, b) {
  if (b.exciteN > 0) {
    return `Excitement ${(b.exciteSum / b.exciteN).toFixed(2)} (${b.exciteN} ${b.exciteN === 1 ? 'game' : 'games'})`;
  }
  // Pending only for seasons Retrosheet has not reached; an older cell without a figure
  // simply lacks play-by-play, whatever the Apple booths' quality status says.
  const through = model.freshness.retrosheet_through_season;
  if (through == null || b.season > through) return PENDING_TEXT;
  return 'no excitement figure';
}

/**
 * Group a cell's crews so each person is listed once (U3). Two crews join a group when they
 * share any person (an analyst who called the series beside a fill-in play-by-play, or a
 * play-by-play who worked with two analysts); groups are the connected components of that
 * relation. A group lists its play-by-play people, then its analysts who are not already
 * listed, each in first-seen order; a person seen in both roles is listed once, with both
 * pills. Only the display groups; the crews and every game's own crew are untouched.
 * @param {Array<[number, number|null]>} pairs [pbp, analyst] person indexes
 * @returns {Array<{pbps: Array<{person: number, roles: string[]}>, analysts: Array<{person: number, roles: string[]}>}>}
 */
export function groupBooths(pairs) {
  const parent = pairs.map((_, k) => k);
  const find = (k) => {
    while (parent[k] !== k) {
      parent[k] = parent[parent[k]];
      k = parent[k];
    }
    return k;
  };
  const firstCrew = new Map();
  pairs.forEach((pair, k) => {
    for (const person of pair) {
      if (person == null) continue;
      if (!firstCrew.has(person)) firstCrew.set(person, k);
      else {
        const a = find(firstCrew.get(person));
        const b = find(k);
        if (a !== b) parent[Math.max(a, b)] = Math.min(a, b);
      }
    }
  });
  const byRoot = new Map();
  pairs.forEach((pair, k) => {
    const root = find(k);
    if (!byRoot.has(root)) byRoot.set(root, []);
    byRoot.get(root).push(pair);
  });
  // Roots are each group's first crew, so Map order is first-seen order.
  return [...byRoot.values()].map((crews) => {
    const roles = new Map();
    const add = (person, role) => {
      if (person == null) return;
      if (!roles.has(person)) roles.set(person, []);
      if (!roles.get(person).includes(role)) roles.get(person).push(role);
    };
    for (const [pbp] of crews) add(pbp, 'pbp');
    for (const [, analyst] of crews) add(analyst, 'analyst');
    const entries = [...roles].map(([person, r]) => ({ person, roles: r }));
    return {
      pbps: entries.filter((e) => e.roles.includes('pbp')),
      analysts: entries.filter((e) => !e.roles.includes('pbp')),
    };
  });
}

/** One booth line: its play-by-play people, then ' / ' and its analysts. */
function boothLine(model, group) {
  const line = el('span', 'mlb-cell-booth');
  const person = (e, last) => {
    const node = nameWithRoles(el('span', 'booth-name', personName(model, e.person)), ...e.roles.map((r) => makeRolePill(r)));
    if (!last) node.append(el('span', 'booth-comma', ','));
    return node;
  };
  group.pbps.forEach((e, k) => line.append(person(e, k === group.pbps.length - 1)));
  if (group.analysts.length) {
    if (group.pbps.length) line.append(el('span', 'booth-sep', ' / '));
    group.analysts.forEach((e, k) => line.append(person(e, k === group.analysts.length - 1)));
  }
  return line;
}

function blockButton(model, b, label, picked, maxLines = Infinity) {
  const btn = el('button', 'mlb-cell-btn');
  btn.type = 'button';
  btn.dataset.cell = b.key;
  btn.setAttribute('aria-pressed', String(picked));
  const where = b.league ? `${b.season} ${ROUND_LABELS[b.round]} ${b.league}` : `${b.season} ${ROUND_LABELS[b.round]}`;
  btn.setAttribute('aria-label', `${where}, ${b.games} ${b.games === 1 ? 'game' : 'games'}`);
  const head = el('span', 'mlb-cell-head');
  if (label) head.append(el('span', 'mlb-cell-league', label));
  for (const o of b.outlets) head.append(networkMark(o));
  btn.append(head);

  const booths = el('span', 'mlb-cell-booths');
  const groups = groupBooths(b.booths);
  if (groups.length) {
    const shown = groups.slice(0, maxLines);
    for (const g of shown) booths.append(boothLine(model, g));
    if (groups.length > shown.length) {
      booths.append(el('span', 'mlb-booth-more', `+${groups.length - shown.length} more`));
    }
  } else {
    booths.append(el('span', 'mlb-no-crew', NO_CREW_TEXT));
  }
  if (b.booths.length && b.crewListed < b.games) {
    booths.append(el('span', 'mlb-no-crew', `${NO_CREW_TEXT} for ${b.games - b.crewListed} of ${b.games}`));
  }
  btn.append(booths);

  const stats = el('span', 'mlb-cell-stats');
  stats.append(el('span', null, `${b.games} ${b.games === 1 ? 'game' : 'games'}`));
  const ex = el('span', b.exciteN > 0 ? null : 'mlb-pending', excitementLine(model, b));
  if (b.exciteN === 0) ex.dataset.pending = 'true';
  stats.append(ex);
  if (b.viewerN > 0) {
    stats.append(el('span', null, `Avg ${viewersText(b.viewerSum / b.viewerN)} viewers, ${b.viewerN} of ${b.games} games rated`));
  }
  btn.append(stats);

  btn.addEventListener('click', () => toggleCell(b.key));
  return btn;
}

function roundsPresent(model) {
  const have = new Set(model.postseason.map((r) => r.round));
  return ROUND_ORDER.filter((r) => r !== 'tiebreak' || have.has('tiebreak'));
}

/**
 * A season's coverage line (`data-low` under the coverage bar) and its per-season Wikipedia
 * outlets credit (RT-13), built fresh for each grid so the phone twin carries both too.
 */
function seasonNotes(s, blocks, bar) {
  const pct = coveragePct(s.coverage_num, s.coverage_den);
  // Counts come from the builder's season table: every postseason game of the season.
  const cov = el(
    'span',
    'mlb-season-coverage',
    pct == null ? '' : `Crews listed for ${s.coverage_num} of ${s.coverage_den} postseason games (${pct}%)`,
  );
  if (s.coverage_den > 0 && s.coverage_num / s.coverage_den < bar) cov.dataset.low = 'true';
  const wikiUrl = [...blocks.values()].find((b) => b.season === s.season && b.outletSourceUrl)?.outletSourceUrl;
  const credit = wikiUrl ? externalLink(wikiUrl, `Outlets: Wikipedia ${s.season} postseason (CC BY-SA 4.0) ↗`) : null;
  if (credit) credit.className = 'mlb-season-credit';
  return credit ? [cov, credit] : [cov];
}

/** A Season button (desktop grid or phone notes): the year, plus any coverage line inside it. */
function seasonButton(key, season, picked, dataName, inside) {
  const btn = el('button', 'mlb-season-btn');
  btn.type = 'button';
  btn.dataset[dataName] = key;
  btn.setAttribute('aria-pressed', String(picked));
  btn.append(el('span', 'mlb-season', String(season)), ...inside);
  if (dataName === 'phoneSeasonCell') btn.addEventListener('click', () => toggleCell(key));
  return btn;
}

/** The focused phone control (season note or round cell) as its container, attribute and key. */
function phoneFocusKey() {
  const a = document.activeElement;
  if (!a || !a.closest) return null;
  const season = a.closest('[data-phone-season-cell]');
  if (season && refs.phoneNotes.contains(season)) {
    return { box: refs.phoneNotes, attr: 'data-phone-season-cell', key: season.dataset.phoneSeasonCell };
  }
  const cell = a.closest('[data-phone-cell]');
  if (cell && refs.phoneBody.contains(cell)) {
    return { box: refs.phoneBody, attr: 'data-phone-cell', key: cell.dataset.phoneCell };
  }
  return null;
}

function phoneRows(model, state, seasons, rounds, blocks) {
  const out = [];
  for (const s of seasons) {
    for (const r of rounds) {
      const here = [...blocks.values()].filter((b) => b.season === s.season && b.round === r);
      here.sort((x, y) => String(x.league).localeCompare(String(y.league)));
      for (const b of here) {
        const tr = el('tr');
        tr.dataset.season = String(s.season);
        const th = el('th', 'mlb-merged-col');
        th.scope = 'row';
        th.append(el('span', 'mlb-merged-line', `${s.season} ${ROUND_SHORT[r]}`));
        th.append(el('span', 'mlb-merged-line mlb-merged-league', b.league ?? ''));
        const td = el('td', 'mlb-booths-col');
        const btn = blockButton(model, b, null, state.cell === b.key, PHONE_BOOTH_LINES);
        // The desktop grid owns data-cell; the phone twin must not double-match it.
        btn.dataset.phoneCell = b.key;
        delete btn.dataset.cell;
        td.append(btn);
        tr.append(th, td);
        out.push(tr);
      }
    }
  }
  return out;
}

export function mount(container, ctx) {
  refs.ctx = ctx;
  const wrap = el('div', 'mlb-grid-wrap');
  wrap.tabIndex = 0;
  wrap.setAttribute('aria-label', 'Postseason booths grid');
  const table = el('table', 'games-table mlb-grid');
  table.setAttribute('role', 'grid');
  table.appendChild(el('caption', 'visually-hidden', 'Postseason booths by season and round'));
  refs.head = el('tr');
  const thead = el('thead');
  thead.appendChild(refs.head);
  refs.body = el('tbody');
  table.append(thead, refs.body);
  wrap.appendChild(table);
  // Phone twin (480px and under, CSS swaps the two): one row per season, round and league
  // block with a merged pinned first column and a Booths column.
  const phone = el('table', 'games-table mlb-phone-grid');
  phone.appendChild(el('caption', 'visually-hidden', 'Postseason booths by season, round and league'));
  const phoneHead = el('tr');
  for (const [text, cls] of [['Season and round', 'mlb-merged-col'], ['Booths', 'mlb-booths-col']]) {
    const th = el('th', cls, text);
    th.scope = 'col';
    phoneHead.appendChild(th);
  }
  const phoneThead = el('thead');
  phoneThead.appendChild(phoneHead);
  refs.phoneBody = el('tbody');
  phone.append(phoneThead, refs.phoneBody);
  const phoneWrap = el('div', 'mlb-phone-wrap');
  phoneWrap.appendChild(phone);
  wrap.classList.add('table-scroll');
  attachScrollCue(wrap, null);
  refs.table = table;
  refs.wrap = wrap;
  // One delegated listener: a Season cell selects its whole season, but a click on the
  // Wikipedia credit link only follows the link (RT-13).
  refs.body.addEventListener('click', (ev) => {
    if (ev.target.closest('a')) return;
    const th = ev.target.closest('th.mlb-season-col');
    if (th) toggleCell(`season-${th.parentElement.dataset.season}`);
  });
  table.addEventListener('keydown', onGridKeydown);
  table.addEventListener('keyup', onGridKeyup);
  table.addEventListener('focusin', (ev) => {
    const btn = ev.target.closest?.(BTN_SEL);
    if (btn) setActive(btn);
  });
  refs.status = el('p', 'visually-hidden mlb-grid-status');
  refs.status.setAttribute('role', 'status');
  // The phone twin's 96px pinned column has no room for each season's coverage line and
  // Wikipedia credit, and a row inside the scroller would sit under its fades: they follow
  // the table as a per-season list (CSS shows it at 480px and under only).
  refs.phoneNotes = el('ul', 'mlb-phone-season-notes');
  refs.captions = el('div', 'nfl-captions');
  container.append(wrap, refs.status, phoneWrap, refs.phoneNotes, refs.captions);
}

export function render(ctx) {
  const { model } = ctx;
  const state = ctx.getState();
  const rounds = roundsPresent(model);
  const blocks = buildGrid(model);
  const bar = model.constants.coverage_bar;

  const roundHead = (r) => {
    const th = el('th');
    th.append(el('span', 'mlb-round-long', ROUND_LABELS[r]));
    if (ROUND_SHORT[r] !== ROUND_LABELS[r]) {
      th.append(el('span', 'mlb-round-short', ROUND_SHORT[r]));
      th.title = ROUND_LABELS[r];
      // Only a head with a short form swaps below 1280px; the others keep their full name.
      th.classList.add('has-short');
    }
    return th;
  };
  const heads = [el('th', 'mlb-season-col', 'Season'), ...rounds.map(roundHead)];
  heads.forEach((th) => { th.scope = 'col'; });
  refs.head.replaceChildren(...heads);

  const seasons = [...model.postseasonSeasons].sort((a, b) => b.season - a.season);
  const rows = [];
  const summary = [];
  for (const s of seasons) {
    const tr = el('tr');
    tr.dataset.season = String(s.season);
    const th = el('th', 'mlb-season-col');
    th.scope = 'row';
    const [cov, ...credit] = seasonNotes(s, blocks, bar);
    const seasonKey = `season-${s.season}`;
    const sBtn = seasonButton(seasonKey, s.season, state.cell === seasonKey, 'seasonCell', [cov]);
    th.append(sBtn, ...credit);
    if (state.cell === seasonKey) th.dataset.picked = 'true';
    tr.appendChild(th);
    for (const r of rounds) {
      const td = el('td', 'mlb-cell');
      td.dataset.round = r;
      const here = [...blocks.values()].filter((b) => b.season === s.season && b.round === r);
      if (!here.length) {
        td.classList.add('mlb-cell-empty');
        td.append(el('span', 'mlb-cell-label', ROUND_LABELS[r]), el('span', 'mlb-empty-mark', '—'));
      } else {
        td.append(el('span', 'mlb-cell-label', ROUND_LABELS[r]));
        here.sort((x, y) => String(x.league).localeCompare(String(y.league)));
        const split = here.length > 1 || here[0].league != null;
        for (const b of here) {
          td.append(blockButton(model, b, split ? b.league : null, state.cell === b.key));
          summary.push({
            key: b.key, season: b.season, round: b.round, league: b.league, games: b.games,
            outlets: b.outlets.map((o) => o.name), outletSourceUrl: b.outletSourceUrl,
            booths: b.booths.map(([p, a]) => boothLabelOf(model, p, a)),
            boothLines: groupBooths(b.booths).length,
            crewListed: b.crewListed, excitementN: b.exciteN,
            excitement: b.exciteN ? b.exciteSum / b.exciteN : null,
            viewersN: b.viewerN, pending: b.exciteN === 0 && excitementLine(model, b) === PENDING_TEXT,
          });
        }
      }
      tr.appendChild(td);
    }
    rows.push(tr);
  }
  const focusKey = refs.table.contains(document.activeElement) ? btnKey(document.activeElement.closest(BTN_SEL) ?? document.activeElement) : null;
  if (focusKey) activeKey = focusKey;
  // The phone twin's buttons are rebuilt too; keep a focused one focused (G4).
  const phoneFocus = phoneFocusKey();
  refs.body.replaceChildren(...rows);
  refs.phoneBody.replaceChildren(...phoneRows(model, state, seasons, rounds, blocks));
  refs.phoneNotes.replaceChildren(
    ...seasons.map((s) => {
      const li = el('li');
      li.dataset.season = String(s.season);
      const seasonKey = `season-${s.season}`;
      const [cov, ...credit] = seasonNotes(s, blocks, bar);
      li.append(seasonButton(seasonKey, s.season, state.cell === seasonKey, 'phoneSeasonCell', []), cov, ...credit);
      return li;
    }),
  );

  refs.captions.replaceChildren(
    el('p', 'caption', 'Excitement is the mean per game from win probability, a tendency, not proof.'),
    el('p', 'caption', `Season percentages count every postseason game of the season, including games with no outlet listed; a cell counts only the games it shows. Seasons with crews listed for fewer than ${Math.round(bar * 100)}% of those games are marked; their booths are partial.`),
  );
  indexGrid();
  if (focusKey) {
    refs.body.querySelector(`[data-season-cell="${CSS.escape(focusKey)}"], [data-cell="${CSS.escape(focusKey)}"]`)?.focus();
  }
  if (phoneFocus) {
    const { box, attr, key } = phoneFocus;
    box.querySelector(`[${attr}="${CSS.escape(key)}"]`)?.focus();
  }
  current = { model, state, summary, seasons: seasons.map((s) => s.season), rounds };
}

export function resize() {}

export function testModel() {
  if (!current) return { view: 'postseason', seasons: [], rounds: [], cells: [] };
  return {
    view: 'postseason',
    seasons: current.seasons,
    rounds: current.rounds,
    cells: current.summary,
    picked: current.state.cell,
  };
}
