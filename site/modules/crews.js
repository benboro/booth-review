/**
 * Crews tab (Phase 10, D-13..D-15): one row per booth-season for the games the active
 * filters show, grouped by network family and season. Game quality per booth only:
 * the table is never sorted or ranked by viewers and has no viewers column (D-14).
 *
 * `buildCrewsModel` is pure and DOM-free; `renderCrewsPanel` builds the DOM with
 * createElement/textContent only (T-10-21), never markup-injecting APIs.
 */

import { FAMILY_ORDER } from './palette.js';
import { BOOTH_FAMILY_NAMES, stripNetworkNote } from './format.js';
import { makeRolePill, nameWithRoles } from './pill.js';
import { attachScrollCue } from './scroll-cue.js';

/**
 * Rows with fewer games than this are faded and tagged "low n" (D-15). Off (0) by user choice
 * (2026-10-18): mid-season most booths have under 8 games. 8 mirrors the NFL LOW_N.
 */
export const CREWS_LOW_N = 0;

const TIER_KEYS = ['a', 'b', 'conf', 'other'];

/** Shown in the Crews module's subtitle (13-11); Phase 14 replaces the behaviour it describes. */
export const CREWS_HINT =
  'Booths by network family and season, for the games your filters show. Selected announcers do not change this table.';

/** Disposers for the scroll cues on the tables the last render built. */
const detachCues = [];

const RATED_NOTE = 'Rated shows how many games have a viewership figure. It is context, not a ranking.';
const NO_MATCH = {
  title: 'No booths match these filters',
  body: 'Booth tiers cover ESPN/ABC, FOX, CBS and NBC games with a published booth order. Clear a filter or pick another season to see crews.',
};
const NO_ORDER = {
  title: 'No booth order yet',
  body: 'This build has no published booth orders, so crews are not tiered.',
};

/**
 * Median of the non-null numbers: the middle value, or the mean of the two middles.
 * @param {Array<number|null|undefined>} values
 * @returns {number|null} null when there is nothing to take a median of.
 */
export function median(values) {
  const nums = values.filter((v) => v != null && Number.isFinite(v)).sort((a, b) => a - b);
  if (nums.length === 0) return null;
  const mid = nums.length >> 1;
  return nums.length % 2 ? nums[mid] : (nums[mid - 1] + nums[mid]) / 2;
}

function personName(data, idx) {
  return idx == null ? null : (data.lookups.people[idx]?.name ?? null);
}

function tierKeyOf(booth) {
  if (booth.tier === 'a') return 'a';
  if (booth.tier === 'b') return 'b';
  return booth.lead_network != null ? 'conf' : 'other';
}

function chipText(booth, key, data) {
  if (key === 'a') return 'Lead';
  if (key === 'b') return 'No. 2';
  if (key === 'conf') {
    const net = data.lookups.networks[booth.lead_network];
    return net ? `Lead ${stripNetworkNote(net.name)}` : 'Lead';
  }
  return '';
}

/**
 * Builds the Crews model from the filtered games. Ignores the person selection, since
 * `view.passesFilters` is the pre-selection filter mask.
 * @param {object} data - a `prepareData` result.
 * @param {{passesFilters: Uint8Array}} view
 * @param {{lowN?: number}} [opts]
 * @returns {{state: 'no-order'|'no-match'|'rows', groups: Array, lowN: number}}
 */
export function buildCrewsModel(data, view, { lowN = CREWS_LOW_N } = {}) {
  if (!data.booths || data.booths.length === 0) return { state: 'no-order', groups: [], lowN };
  const byBooth = new Map();
  const n = data.boothOf.length;
  for (let i = 0; i < n; i += 1) {
    const k = data.boothOf[i];
    if (k < 0 || !view.passesFilters[i]) continue;
    if (!byBooth.has(k)) byBooth.set(k, []);
    byBooth.get(k).push(i);
  }
  const t = data.t;
  const groupMap = new Map();
  for (const [k, games] of byBooth) {
    const booth = data.booths[k];
    const key = tierKeyOf(booth);
    const exc = games.map((i) => t.excitement[i]).filter((v) => v != null);
    const spreads = games.map((i) => (t.home_spread[i] == null ? null : Math.abs(t.home_spread[i])));
    const ranked = games.filter((i) => t.away_rank[i] != null && t.home_rank[i] != null).length;
    const rated = games.filter((i) => data.rated[i]).length;
    const row = {
      booth: k,
      tier: key,
      chip: chipText(booth, key, data),
      pbp: personName(data, booth.pbp),
      analyst: personName(data, booth.analyst),
      games: games.length,
      medianExcitement: median(exc),
      excitementN: exc.length,
      medianSpread: median(spreads),
      rankedShare: ranked / games.length,
      ratedShare: rated / games.length,
      lowN: lowN > 0 && games.length < lowN,
    };
    const gk = `${booth.family}|${booth.season}`;
    if (!groupMap.has(gk)) {
      groupMap.set(gk, {
        family: booth.family,
        season: booth.season,
        heading: `${BOOTH_FAMILY_NAMES[booth.family] ?? booth.family}, ${booth.season}`,
        rows: [],
      });
    }
    groupMap.get(gk).rows.push(row);
  }
  const famRank = (f) => {
    const r = FAMILY_ORDER.indexOf(f);
    return r < 0 ? FAMILY_ORDER.length : r;
  };
  const groups = [...groupMap.values()].sort((a, b) => b.season - a.season || famRank(a.family) - famRank(b.family));
  for (const g of groups) {
    g.rows.sort(
      (a, b) =>
        TIER_KEYS.indexOf(a.tier) - TIER_KEYS.indexOf(b.tier) ||
        b.games - a.games ||
        String(a.pbp ?? '').localeCompare(String(b.pbp ?? '')),
    );
  }
  return { state: groups.length ? 'rows' : 'no-match', groups, lowN };
}

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
}

const fixed = (v) => (v == null ? '—' : v.toFixed(1));
const pct = (v) => `${Math.round(v * 100)}%`;

function numCell(text) {
  return el('td', 'num', text);
}

function buildTable(group) {
  const wrap = el('div', 'nfl-booth-table-wrap crews-table-wrap table-scroll');
  const table = el('table', 'games-table nfl-booth-table crews-table');
  table.append(el('caption', 'visually-hidden', `Booths for ${group.heading}`));
  const tr = el('tr');
  ['Booth', 'Games', 'Median excitement', 'Median spread (points)', 'Ranked vs. ranked', 'Rated'].forEach((h, idx) => {
    // Games and Rated hold short figures, so their set widths are narrower (style.css).
    const cls = idx === 0 ? 'booth-col' : idx === 1 || idx === 5 ? 'num crews-narrow' : 'num';
    const th = el('th', cls, h);
    th.scope = 'col';
    tr.append(th);
  });
  const thead = el('thead');
  thead.append(tr);
  const tbody = el('tbody');
  for (const r of group.rows) {
    const row = el('tr');
    if (r.lowN) row.dataset.lowN = 'true';
    const th = el('th', 'booth-col');
    th.scope = 'row';
    const names = el('span', 'booth-names');
    names.append(nameWithRoles(el('span', 'booth-name crews-pbp', r.pbp ?? 'Unknown'), makeRolePill('pbp')));
    if (r.analyst != null) {
      names.append(
        el('span', 'booth-sep', ' / '),
        nameWithRoles(el('span', 'booth-name', r.analyst), makeRolePill('analyst')),
      );
    }
    if (r.chip) names.append(el('span', 'crews-chip', r.chip));
    if (r.lowN) {
      const tag = el('span', 'low-n-tag', 'low n');
      tag.title = 'Few games, so treat with care.';
      names.append(tag);
    }
    th.append(names);
    row.append(
      th,
      numCell(String(r.games)),
      numCell(fixed(r.medianExcitement)),
      numCell(fixed(r.medianSpread)),
      numCell(pct(r.rankedShare)),
      numCell(pct(r.ratedShare)),
    );
    tbody.append(row);
  }
  table.append(thead, tbody);
  wrap.append(table);
  detachCues.push(attachScrollCue(wrap, null));
  return wrap;
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

/**
 * Renders the Crews panel into `container`.
 * @param {HTMLElement} container
 * @param {ReturnType<typeof buildCrewsModel>} model
 */
export function renderCrewsPanel(container, model) {
  // Every render rebuilds the tables, so release the old ones' scroll-cue observers first.
  detachCues.splice(0).forEach((detach) => detach());
  container.replaceChildren();
  if (model.state !== 'rows') {
    const copy = model.state === 'no-order' ? NO_ORDER : NO_MATCH;
    const note = el('div', 'season-empty-note crews-empty');
    note.setAttribute('role', 'status');
    note.append(el('p', 'season-empty-title', copy.title), el('p', 'season-empty-hint', copy.body));
    container.append(note);
    return;
  }
  for (const group of model.groups) {
    const section = el('section', 'crews-group');
    section.append(el('h3', 'crews-heading', group.heading), buildTable(group));
    container.append(section);
  }
  if (model.lowN > 0) {
    container.append(
      el('p', 'caption crews-legend', `low n: fewer than ${model.lowN} games, so medians move easily.`),
    );
  }
  container.append(el('p', 'caption crews-rated-note', RATED_NOTE));
  const credits = el('div', 'crews-credits');
  credits.append(
    creditLine('Data provided by CollegeFootballData.com', 'https://collegefootballdata.com'),
    creditLine("Viewership figures: Ratings Reference and the second sources credited in each game's detail panel."),
    creditLine('Booth order from network press releases, cited per season in data/reference/cfb_booth_ranks.csv.'),
  );
  container.append(credits);
}
