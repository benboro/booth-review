/**
 * Crews tab (Phase 14, CFB-02..CFB-05): one table of every crew (or PBP voice, or analyst) in
 * the Seasons range. The row model is `buildCrewRows` in crew-groups.js; this module only
 * draws it with createElement/textContent (T-14-17), never markup-injecting APIs, and turns
 * header and row clicks into `setState` calls.
 *
 * Game quality per crew only: the table is never sorted by viewers by default. A crew pick
 * (a Crew-mode row click) narrows the table to that crew, as the NFL Booths pick does (user
 * rule 2026-10-27); an Announcers pick (a PBP or Analyst row click) highlights rows without
 * dropping one (U-06).
 */

import { NATURAL_DIR, defaultSort, modelBreakSeason, sortCrewRows } from './crew-groups.js';
import { crewEntries, figureSourceOf, formatAudienceTable, formatMatchup } from './format.js';
import { networkMark } from './network.js';
import { safeHref } from './panel.js';
import { createTableState, el, renderCrewsTable } from './crews-table.js';

/** This sport's table state: paging, open rows and announce memory (shared mechanics in crews-table.js). */
const ts = createTableState();

const SORT_SPEC = { naturalDir: NATURAL_DIR, defaultSort };

const MODE_LABELS = { crew: 'Crew', pbp: 'PBP', analyst: 'Analyst' };

const CONFOUND = 'Avg viewers (rated games) mostly reflects which games a crew was assigned.';
// A2(a): unknown-role people drop from a row with a play-by-play voice; no-PBP rows mark them.
const UNKNOWN_NOTE =
  'A person of unknown role on a telecast with a play-by-play voice is not shown. Telecasts with no play-by-play voice are grouped by their exact people, and unknown roles are marked.';
const LEFT_OUT = {
  crew: (n) => `${n} telecasts list no crew and are not in this table.`,
  pbp: (n) => `${n} telecasts with no resolved play-by-play voice are not in this mode.`,
  analyst: (n) => `${n} telecasts with no resolved analyst are not in this mode.`,
};
const EMPTY_COPY = {
  title: 'No games match these filters',
  body: 'Clear all filters, or widen the Seasons range.',
};

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
  const fig = kind === 'viewers' ? formatAudienceTable(m.mean) : m.mean.toFixed(1);
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

/**
 * Whether `row` holds a picked person without being the pick itself (accent rule 2, U-06),
 * and at least one of its games is a matched game on which a picked person the row itself
 * holds matches Role (P14-FU-1). `computeView`'s `highlighted` alone is not enough: another
 * picked person may supply the match, which must not light a row whose own person did not.
 * Called together still needs every picked person on the row.
 */
function isHighlightedRow(row, mode, state, highlightedSet, view, data) {
  if (!state.people.length) return false;
  const slugs = mode === 'crew' ? row.people.map((p) => p.slug) : [row.personSlug];
  const held = state.people.filter((id) => slugs.includes(id));
  const holds = state.together ? held.length === state.people.length : held.length > 0;
  if (!holds) return false;
  return row.games.some((i) => {
    if (!highlightedSet.has(i)) return false;
    const onGame = view.peopleOnGame?.get(i) ?? [];
    return onGame.some((idx) => held.includes(data.lookups.people[idx].id));
  });
}

/** Sets the pick to this row, or clears it when this row is the pick. */
function togglePick(tr, row, mode, setState) {
  const picked = tr.getAttribute('aria-pressed') === 'true';
  if (mode === 'crew') setState({ crew: picked ? null : row.crewKey });
  else setState({ people: picked ? [] : [row.personSlug] });
}

/** The other main-feed people on game `i`, for the Crew column of a person's game list. */
function otherCrew(data, i, slug) {
  return crewEntries(data, i, { mainOnly: true })
    .filter((e) => data.lookups.people[e.person].id !== slug)
    .map((e) => e.name)
    .join(', ');
}

function viewersCell(data, i) {
  const td = el('td', 'num');
  if (!data.rated[i]) {
    td.classList.add('is-blank');
    td.append(el('span', 'caption', 'none rated'));
    return td;
  }
  td.append(el('span', 'crews-figure', formatAudienceTable(data.t.viewers[i])));
  // A second-source figure keeps the publisher link the Matched games table gives it (RT-10).
  if (figureSourceOf(data, i) !== 'rr') {
    const t = data.t;
    const name = t.publisher[i] != null ? data.lookups.publishers[t.publisher[i]] : null;
    const href = safeHref(t.source_url[i]);
    if (href) {
      const a = el('a', 'crews-source caption', name ?? 'publisher unknown');
      a.href = href;
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      td.append(a);
    }
  }
  return td;
}

function gameRow(row, mode, ctx, i) {
  const { data } = ctx;
  const matchup = formatMatchup(data, i, {});
  const tr = el('tr', 'crews-game');
  tr.dataset.game = String(i);
  tr.tabIndex = 0;
  tr.setAttribute('role', 'button');
  tr.setAttribute('aria-label', `Details for ${matchup}`);
  tr.append(el('td', 'date crews-game-date', data.t.date[i]));
  const matchupTd = el('td', 'matchup crews-game-matchup', matchup);
  if (mode === 'crew' && row.fillInGames.has(i)) {
    const tag = el('span', 'crews-tag is-dashed', 'fill-in');
    tag.title = 'The regular analyst was absent';
    matchupTd.append(tag);
  }
  const net = data.lookups.networks[data.t.network[i]];
  const netTd = el('td', 'crews-game-network');
  netTd.append(networkMark({ id: net.id, name: net.name, family: net.family }));
  tr.append(matchupTd, netTd);
  if (mode !== 'crew') tr.append(el('td', 'crews-game-crew', otherCrew(data, i, row.personSlug)));
  const viewers = viewersCell(data, i);
  viewers.classList.add('crews-game-viewers');
  tr.append(viewers);
  tr.addEventListener('click', (e) => {
    if (e.target instanceof Element && e.target.closest('a')) return;
    ctx.openGame?.(i);
  });
  return tr;
}

function seasonsInRange(data, state) {
  const [lo, hi] = state.seasons ?? [-Infinity, Infinity];
  return data.seasons.filter((s) => s >= lo && s <= hi).length;
}

/** Per season is on by default but changes nothing on a one-season range, so it applies only with two or more (D-10). */
export function perSeasonApplies(data, state) {
  return state.perseason && seasonsInRange(data, state) >= 2;
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
  box.checked = perSeasonApplies(data, state);
  const single = seasonsInRange(data, state) < 2;
  box.disabled = single;
  label.title = single ? 'Needs two or more seasons in range' : 'One row per crew and season';
  box.title = label.title;
  box.addEventListener('change', () => setState({ perseason: box.checked }));
  label.append(box, ' Per season');
  tools.append(group, label);
  return tools;
}

/**
 * Renders the Crews panel into `container`.
 * @param {HTMLElement} container
 * @param {ReturnType<import('./crew-groups.js').buildCrewRows>} model
 * @param {{data: object, state: object, view: object, setState: Function, openGame?: Function}} ctx
 */
export function renderCrewsPanel(container, model, ctx) {
  const { data, state, view, setState } = ctx;
  const mode = model.mode;
  const full = { ...ctx, model, highlightedSet: new Set(view.highlighted ?? []) };
  const cols = columnsFor(mode, model.perSeason);
  renderCrewsTable(container, {
    ts,
    state,
    perSeason: model.perSeason,
    sortSpec: SORT_SPEC,
    rows: model.totalRows === 0 ? [] : sortCrewRows(model.rows, state.csort),
    signature: `${mode}|${model.perSeason}|${JSON.stringify(state.csort)}|${passingHash(view)}`,
    columns: cols,
    label: 'Crews',
    modeKey: mode,
    colCount: cols.length + 1,
    tableClasses: ['crews-table--' + mode, ...(model.perSeason ? ['has-season'] : [])],
    gameHeads: ['Date', 'Matchup', 'Network', ...(mode === 'crew' ? [] : ['Crew']), 'Viewers'],
    buildTools: () => buildTools(full),
    buildEmpty: () => {
      const note = el('div', 'season-empty-note crews-empty');
      note.setAttribute('role', 'status');
      note.append(el('p', 'season-empty-title', EMPTY_COPY.title), el('p', 'season-empty-hint', EMPTY_COPY.body));
      return note;
    },
    isPicked: (row) => isPickedRow(row, mode, state),
    isHighlighted: (row) => isHighlightedRow(row, mode, state, full.highlightedSet, view, data),
    crewKeyOf: (row) => (mode === 'crew' ? row.crewKey : row.personSlug),
    buildCells: (row) => {
      const cells = [nameCell(row, mode)];
      if (model.perSeason) cells.push(el('td', 'crews-season num-ish', String(row.season)));
      if (mode === 'crew') cells.push(el('td', 'crews-rank caption', row.rankRun));
      cells.push(
        networkCell(data, row),
        el('td', 'num', String(row.gamesCount)),
        metricCell(row.exc, 'exc', data),
        metricCell(row.viewers, 'viewers', data),
      );
      return cells;
    },
    gameRow: (row, i) => gameRow(row, mode, full, i),
    subHead: (row) => {
      if (mode === 'crew' || !row.partners.length) return [];
      const list = el('p', 'crews-worked');
      row.partners.forEach((p, k) => {
        if (k > 0) list.append(', ');
        list.append(el('span', 'crews-worked-name', p.name), ' ', el('span', 'crews-worked-count', `(${p.games})`));
      });
      return [el('p', 'crews-worked-label', 'Worked with'), list];
    },
    onPick: (row, tr) => togglePick(tr, row, mode, setState),
    onSort: (next) => setState({ csort: next }),
    openGame: ctx.openGame,
    rerender: () => renderCrewsPanel(container, model, ctx),
    // Shown with or without rows: an empty person mode still says which telecasts it left out.
    footer: (box) => {
      if (model.leftOut > 0) box.append(el('p', 'caption crews-left-out', LEFT_OUT[mode](model.leftOut)));
      box.append(el('p', 'caption crews-confound', CONFOUND));
      if (mode === 'crew') box.append(el('p', 'caption crews-unknown-note', UNKNOWN_NOTE));
      const credits = el('div', 'crews-credits');
      credits.append(
        creditLine('Data provided by CollegeFootballData.com', 'https://collegefootballdata.com'),
        creditLine("Viewership figures: Ratings Reference and the second sources credited in each game's detail panel."),
        creditLine('Booth order from network press releases, cited per season in data/reference/cfb_booth_ranks.csv.'),
      );
      box.append(credits);
    },
  });
}
