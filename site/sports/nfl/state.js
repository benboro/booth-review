/**
 * NFL filter state, masks and aggregations (D-08, D-12 to D-15, D-24). DOM-free.
 *
 * State holds franchise ids and person ids (strings), not indexes, so the URL
 * round trip needs no translation. Selection and UI-only fields are never
 * encoded in the URL.
 */

import { lowNThreshold } from './mode.js';
import { computePicks } from './picks.js';

/**
 * The first tab is every regular-season game by team (`teams`); its "Special games only" toggle
 * (`state.special`) shows the eight special-game categories instead of the networks.
 */
export const NFL_VIEWS = Object.freeze(['teams', 'crews', 'viewership', 'scatter', 'weekend']);
export const CREW_METRICS = Object.freeze(['margin', 'excitement', 'viewers']);

/** Crews table sort keys and their natural directions (booth like CFB crew, margin like exc). */
export const NFL_CSORT_KEYS = Object.freeze(['booth', 'season', 'rank', 'network', 'games', 'margin', 'exc', 'viewers']);
export const NFL_NATURAL_DIR = Object.freeze({
  booth: 'asc', season: 'asc', rank: 'asc', network: 'asc',
  games: 'desc', margin: 'desc', exc: 'desc', viewers: 'desc',
});

/** Category filter options in UI order (labels exact per UI-SPEC). */
export const CATEGORY_OPTIONS = Object.freeze([
  { key: 'tnf', label: 'Thursday night', group: 'Solo slots', slot: 'TNF' },
  { key: 'snf', label: 'Sunday night', group: 'Solo slots', slot: 'SNF' },
  { key: 'mnf', label: 'Monday night', group: 'Solo slots', slot: 'MNF' },
  { key: 'thanksgiving', label: 'Thanksgiving', group: 'Solo slots', slot: 'Thanksgiving' },
  { key: 'christmas', label: 'Christmas', group: 'Solo slots', slot: 'Christmas' },
  { key: 'blackfriday', label: 'Black Friday', group: 'Solo slots', slot: 'Black Friday' },
  { key: 'saturday', label: 'Saturday', group: 'Solo slots', slot: 'Saturday' },
  { key: 'intl_slot', label: 'International (solo slot)', group: 'Solo slots', slot: 'International' },
  { key: 'other_standalone', label: 'Other solo slot', group: 'Solo slots', slot: null },
  { key: 'agotw', label: 'Fox AGOTW', group: 'Other special games', slot: null },
  { key: 'cbs', label: 'CBS late national', group: 'Other special games', slot: null },
  { key: 'intl', label: 'International (any window)', group: 'Other special games', slot: null },
  { key: 'flexed', label: 'Flexed', group: 'Other special games', slot: null },
].map((o) => Object.freeze(o)));

const CAT_KEYS = CATEGORY_OPTIONS.map((o) => o.key);
const STANDALONE_SLOT_BY_KEY = new Map(
  CATEGORY_OPTIONS.filter((o) => o.slot).map((o) => [o.key, o.slot]),
);
const NAMED_SLOTS = new Set(STANDALONE_SLOT_BY_KEY.values());

/** Exclusive categories (bars and scatter color), code order matches model.category. */
export const EXCLUSIVE_CATEGORIES = Object.freeze([
  { key: 'solo_thursday', code: 0, label: 'Thursday night' },
  { key: 'solo_sunday', code: 1, label: 'Sunday night' },
  { key: 'solo_monday', code: 2, label: 'Monday night' },
  { key: 'solo_holiday', code: 3, label: 'Holiday' },
  { key: 'solo_other', code: 4, label: 'Other solo slot' },
  { key: 'agotw', code: 5, label: 'Fox AGOTW' },
  { key: 'cbs_national', code: 6, label: 'CBS late national' },
  { key: 'international_other', code: 7, label: 'International' },
  { key: 'none', code: 8, label: 'Other games' },
].map((o) => Object.freeze(o)));

/** The eight stack segments (everything but 'none'). */
const SEGMENT_KEYS = Object.freeze(EXCLUSIVE_CATEGORIES.filter((c) => c.key !== 'none').map((c) => c.key));
const SEGMENT_SET = new Set(SEGMENT_KEYS);

/**
 * Category filter key -> every segment that can hold one of its games (flexed fades nothing).
 * A solo Saturday, Friday, Sunday-afternoon or other game played abroad is International, and
 * an international game can also sit in a primetime or holiday segment or be AGOTW or CBS
 * national (contract 3.0.0).
 */
const CAT_SEGMENTS = Object.freeze({
  tnf: ['solo_thursday'],
  snf: ['solo_sunday'],
  mnf: ['solo_monday'],
  thanksgiving: ['solo_holiday'],
  christmas: ['solo_holiday'],
  blackfriday: ['solo_holiday'],
  saturday: ['solo_other', 'international_other'],
  intl_slot: ['international_other'],
  other_standalone: ['solo_other', 'international_other'],
  agotw: ['agotw'],
  cbs: ['cbs_national'],
  intl: [
    'solo_thursday', 'solo_sunday', 'solo_monday', 'solo_holiday',
    'agotw', 'cbs_national', 'international_other',
  ],
});

const SPECIAL_SLOT_COLUMNS = Object.freeze([
  ['christmas', 'Christmas'], ['thanksgiving', 'Thanksgiving'],
  ['black_friday', 'Black Friday'], ['international', 'International'],
  ['tnf', 'TNF'], ['snf', 'SNF'], ['mnf', 'MNF'], ['saturday', 'Saturday'],
  ['friday', 'Friday'], ['sunday_early', 'Sunday early'],
  ['sunday_late', 'Sunday late'], ['other', 'Other'],
]);

/** @returns {object} the default NFL state for this model */
export function defaultNflState(model) {
  return {
    view: 'teams',
    // The first tab's toggle: false counts every game by network, true only the special games.
    special: false,
    seasons: [model.seasons[0], model.seasons[1]],
    teams: [],
    people: [],
    cats: [],
    // The Networks pick: null is unfiltered, [] is none, else network ids in lookup order
    // ('tba' stands for a game with no network yet), as on the CFB page.
    networks: null,
    dots: 'fade',
    booths: [],
    perseason: true,
    csort: null,
    adjusted: false,
    metric: 'margin',
    viewY: 'mean',
    scatterX: 'date',
    scatterY: 'viewers',
    selection: null,
    showAllTeams: false,
    hiddenSegments: [],
    hiddenCategories: [],
    week: null,
    day: null,
    wview: null,
  };
}

function cleanIds(list, lookup) {
  if (!Array.isArray(list)) return [];
  const out = new Set();
  for (const v of list) if (typeof v === 'string' && lookup.has(v)) out.add(v);
  return [...out].sort();
}

function pick(value, allowed, fallback) {
  return allowed.includes(value) ? value : fallback;
}

/** A Networks pick in lookup order; every network picked (or no list) is null, the unfiltered state. */
function cleanNetworks(list, model) {
  if (!Array.isArray(list)) return null;
  const picked = new Set(list.filter((v) => typeof v === 'string'));
  const ids = model.net.ids.filter((id) => picked.has(id));
  return ids.length === model.net.ids.length ? null : ids;
}

/** The season the This weekend tab shows: the upcoming block's, else the freshness season. */
function weekendSeason(model) {
  return model.upcomingRaw?.season?.[0] ?? model.freshness?.season ?? model.seasons[1];
}

/** The current weekend week: the freshness stamp's, else the latest played week of the season. */
export function weekendCurrentWeek(model) {
  if (model.weekend?.week != null) return model.weekend.week;
  const season = weekendSeason(model);
  let latest = null;
  for (let i = 0; i < model.n; i += 1) {
    if (model.cols.season[i] === season && (latest == null || model.cols.week[i] > latest)) {
      latest = model.cols.week[i];
    }
  }
  return latest;
}

/** Weeks the stepper reaches: those of the weekend season with games, up to the current week. */
export function weekendWeeks(model) {
  const current = weekendCurrentWeek(model);
  if (current == null) return [];
  const season = weekendSeason(model);
  const set = new Set();
  const c = model.cols;
  for (let i = 0; i < model.n; i += 1) if (c.season[i] === season) set.add(c.week[i]);
  const u = model.upcomingRaw;
  for (let j = 0; u && j < u.season.length; j += 1) if (u.season[j] === season) set.add(u.week[j]);
  set.add(current);
  return [...set].filter((w) => Number.isInteger(w) && w <= current).sort((a, b) => a - b);
}

/** The ET dates (YYYY-MM-DD, sorted) that have a game in one weekend week. */
export function weekendDays(model, week) {
  const season = weekendSeason(model);
  const set = new Set();
  const c = model.cols;
  for (let i = 0; i < model.n; i += 1) {
    if (c.season[i] === season && c.week[i] === week && c.date[i]) set.add(c.date[i]);
  }
  const u = model.upcomingRaw;
  for (let j = 0; u && j < u.season.length; j += 1) {
    if (u.season[j] === season && u.week[j] === week && u.date[j]) set.add(u.date[j]);
  }
  return [...set].sort();
}

/**
 * Allowlist a week: the current week collapses to null. The day is always null: This weekend
 * shows the whole week on one page (user 2026-11-09), so an old link's `day=` is dropped.
 */
function cleanWeekend(model, week) {
  const weeks = weekendWeeks(model);
  const current = weekendCurrentWeek(model);
  const w = Number.isInteger(week) && weeks.includes(week) && week !== current ? week : null;
  return { week: w, day: null };
}

/**
 * Clamp and allowlist a state so every later reader can trust it.
 * Never throws.
 */
export function canonicalNflState(state, model) {
  const d = defaultNflState(model);
  const s = state && typeof state === 'object' ? state : {};
  let lo = Number(Array.isArray(s.seasons) ? s.seasons[0] : NaN);
  let hi = Number(Array.isArray(s.seasons) ? s.seasons[1] : NaN);
  if (!Number.isFinite(lo)) lo = d.seasons[0];
  if (!Number.isFinite(hi)) hi = d.seasons[1];
  if (lo > hi) [lo, hi] = [hi, lo];
  lo = Math.min(Math.max(Math.trunc(lo), d.seasons[0]), d.seasons[1]);
  hi = Math.min(Math.max(Math.trunc(hi), d.seasons[0]), d.seasons[1]);
  const catSet = new Set(Array.isArray(s.cats) ? s.cats : []);
  const catIds = new Set(model.viewCategories.map((c) => c.id));
  const cso = s.csort;
  const csort = cso && typeof cso === 'object'
    && NFL_CSORT_KEYS.includes(cso.key) && (cso.dir === 'asc' || cso.dir === 'desc')
    ? { key: cso.key, dir: cso.dir } : null;
  const wk = cleanWeekend(model, Number(s.week));
  const asList = (v) => (Array.isArray(v) ? v.filter((x) => typeof x === 'string') : []);
  return {
    view: pick(s.view, NFL_VIEWS, d.view),
    special: s.special === true,
    seasons: [lo, hi],
    teams: cleanIds(s.teams, new Map(model.franchises.map((f) => [f.id, 1]))),
    people: cleanIds(s.people, new Map(model.people.map((p) => [p.id, 1]))),
    cats: CAT_KEYS.filter((k) => catSet.has(k)),
    networks: cleanNetworks(s.networks, model),
    dots: s.dots === 'hide' ? 'hide' : 'fade',
    booths: [...new Set(asList(s.booths).filter((k) => model.boothIndex.has(k)))],
    perseason: s.perseason !== false,
    csort,
    adjusted: s.adjusted === true,
    metric: pick(s.metric, CREW_METRICS, 'margin'),
    viewY: s.viewY === 'resid' ? 'resid' : 'mean',
    scatterX: s.scatterX === 'margin' ? 'margin' : 'date',
    scatterY: s.scatterY === 'excitement' ? 'excitement' : 'viewers',
    selection: s.selection && typeof s.selection === 'object' ? s.selection : null,
    showAllTeams: s.showAllTeams === true,
    hiddenSegments: [...new Set(asList(s.hiddenSegments).filter((k) => EXCLUSIVE_CATEGORIES.some((c) => c.key === k)))],
    hiddenCategories: [...new Set(asList(s.hiddenCategories).filter((k) => catIds.has(k)))],
    week: wk.week,
    day: wk.day,
    wview: s.view === 'weekend' && s.wview === 'map' ? 'map' : null,
  };
}

function catMatches(model, key, i) {
  const c = model.cols;
  switch (key) {
    case 'agotw': return !!c.agotw[i];
    case 'cbs': return !!c.cbs_national[i];
    case 'intl': return !!c.international[i];
    case 'flexed': return !!c.flexed[i];
    case 'other_standalone':
      return !!c.standalone[i] && !NAMED_SLOTS.has(model.slots[c.slot[i]]);
    default: {
      const slot = STANDALONE_SLOT_BY_KEY.get(key);
      return slot !== undefined && !!c.standalone[i] && model.slots[c.slot[i]] === slot;
    }
  }
}

/** The Networks-filter id of game `i`: its network's id, or 'tba' when it has none yet. */
export function networkIdOf(model, i) {
  const n = model.cols.network[i];
  return n == null ? 'tba' : model.networks[n].id;
}

/** Seasons AND Networks AND Team AND Category (match any); an empty filter passes all. */
export function gamePasses(model, state, i) {
  const c = model.cols;
  if (c.season[i] < state.seasons[0] || c.season[i] > state.seasons[1]) return false;
  if (state.networks != null && !state.networks.includes(networkIdOf(model, i))) return false;
  if (state.teams.length) {
    const home = model.franchises[c.home[i]].id;
    const away = model.franchises[c.away[i]].id;
    if (!state.teams.includes(home) && !state.teams.includes(away)) return false;
  }
  if (state.cats.length && !state.cats.some((k) => catMatches(model, k, i))) return false;
  return true;
}

function emptyCounts() {
  const c = {};
  for (const k of SEGMENT_KEYS) c[k] = 0;
  return c;
}

function addRow(acc, r) {
  for (const k of SEGMENT_KEYS) acc.counts[k] += r[k] ?? 0;
  acc.international += r.international;
  acc.flexed += r.flexed;
  acc.games += r.games;
  for (const [col] of SPECIAL_SLOT_COLUMNS) acc.slotCounts[col] += r['standalone_' + col];
}

function newAcc() {
  const slotCounts = {};
  for (const [col] of SPECIAL_SLOT_COLUMNS) slotCounts[col] = 0;
  return { counts: emptyCounts(), international: 0, flexed: 0, games: 0, slotCounts };
}

function segmentFading(state) {
  const keep = new Set();
  let any = false;
  for (const k of state.cats) {
    const segs = CAT_SEGMENTS[k];
    if (!segs) continue;
    any = true;
    for (const g of segs) keep.add(g);
  }
  const out = {};
  for (const k of SEGMENT_KEYS) out[k] = any && !keep.has(k);
  return out;
}

function finish(model, acc, fIdx, faded, segFaded) {
  const slots = SPECIAL_SLOT_COLUMNS
    .filter(([col]) => acc.slotCounts[col] > 0)
    .map(([col, label]) => ({ key: col, label, count: acc.slotCounts[col] }));
  const c = acc.counts;
  return {
    franchise: fIdx,
    name: model.franchises[fIdx].name,
    counts: c,
    total: SEGMENT_KEYS.reduce((n, k) => n + c[k], 0),
    international: acc.international,
    flexed: acc.flexed,
    games: acc.games,
    slots,
    teamFaded: faded,
    segmentFaded: segFaded,
  };
}

const SLOT_COLUMN_BY_NAME = new Map(SPECIAL_SLOT_COLUMNS.map(([col, label]) => [label, col]));

/**
 * The `special` block's rows recounted from the games `keep` passes: one row per franchise and
 * season with the eight segments, `international`, `flexed`, `games` and the twelve
 * `standalone_<slot>` counts. With every game kept it equals the shipped block on those columns.
 */
export function specialRowsFromGames(model, keep) {
  const c = model.cols;
  const rows = new Map();
  const rowOf = (franchise, season) => {
    const key = `${franchise}:${season}`;
    let row = rows.get(key);
    if (!row) {
      row = { franchise, season, games: 0, international: 0, flexed: 0 };
      for (const k of SEGMENT_KEYS) row[k] = 0;
      for (const [col] of SPECIAL_SLOT_COLUMNS) row['standalone_' + col] = 0;
      rows.set(key, row);
    }
    return row;
  };
  for (let i = 0; i < model.n; i++) {
    if (!keep(i)) continue;
    const cat = EXCLUSIVE_CATEGORIES[model.category[i]];
    const slotCol = c.standalone[i] ? SLOT_COLUMN_BY_NAME.get(model.slots[c.slot[i]]) : undefined;
    for (const f of [c.home[i], c.away[i]]) {
      const row = rowOf(f, c.season[i]);
      row.games += 1;
      if (cat && cat.key !== 'none') row[cat.key] += 1;
      if (slotCol) row['standalone_' + slotCol] += 1;
      if (c.international[i]) row.international += 1;
      if (c.flexed[i]) row.flexed += 1;
    }
  }
  return [...rows.values()].sort((a, b) => a.franchise - b.franchise || a.season - b.season);
}

let specialMemo = null;

/**
 * The special rows the bars read: the shipped block, or under a Networks pick the rows recounted
 * from the games on the picked networks, so the pick narrows the Special games bars too.
 */
export function specialRows(model, state) {
  if (state.networks == null) return model.special;
  const signature = state.networks.join(',');
  if (specialMemo && specialMemo.model === model && specialMemo.signature === signature) return specialMemo.rows;
  const picked = new Set(state.networks);
  const rows = specialRowsFromGames(model, (i) => picked.has(networkIdOf(model, i)));
  specialMemo = { model, signature, rows };
  return rows;
}

/** One entry per franchise, summed over the selected season range. */
export function teamBars(model, state) {
  const [lo, hi] = state.seasons;
  const accs = model.franchises.map(() => newAcc());
  for (const r of specialRows(model, state)) {
    if (r.season < lo || r.season > hi) continue;
    addRow(accs[r.franchise], r);
  }
  const segFaded = segmentFading(state);
  const out = accs.map((acc, f) =>
    finish(
      model, acc, f,
      state.teams.length > 0 && !state.teams.includes(model.franchises[f].id),
      segFaded,
    ));
  out.sort((a, b) => b.total - a.total || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
  return out;
}

/** One row per season in range for a franchise, newest first. */
export function teamSeasonRows(model, state, franchiseIdx) {
  const [lo, hi] = state.seasons;
  const segFaded = segmentFading(state);
  const rows = specialRows(model, state)
    .filter((r) => r.franchise === franchiseIdx && r.season >= lo && r.season <= hi)
    .sort((a, b) => b.season - a.season);
  return rows.map((r) => {
    const acc = newAcc();
    addRow(acc, r);
    return { season: r.season, ...finish(model, acc, franchiseIdx, false, segFaded) };
  });
}

/**
 * The stack segment each `standalone_<slot>` column belongs to (docs/nfl-data.md). A solo
 * International-slot game is always International (contract 3.0.0); the other solo_other slots
 * map there too, though a game of theirs played abroad counts under International.
 */
export const SLOT_SEGMENT = Object.freeze({
  tnf: 'solo_thursday',
  snf: 'solo_sunday',
  mnf: 'solo_monday',
  thanksgiving: 'solo_holiday',
  christmas: 'solo_holiday',
  black_friday: 'solo_holiday',
  saturday: 'solo_other',
  international: 'international_other',
  friday: 'solo_other',
  sunday_early: 'solo_other',
  sunday_late: 'solo_other',
  other: 'solo_other',
});

/**
 * The count a team bar is ranked by: its segments that are shown (not hidden by a chip) and
 * in focus (not faded by the Category filter); under an Announcers or Booths pick, only the
 * matched games in them. That is the bright part of each bar.
 */
export function activeCount(bar, hiddenSegments) {
  const hidden = new Set(hiddenSegments);
  let n = 0;
  for (const k of SEGMENT_KEYS) {
    if (hidden.has(k) || bar.segmentFaded[k]) continue;
    n += bar.matched ? bar.matched[k] ?? 0 : bar.counts[k];
  }
  return n;
}

/** The shown total: every segment a chip leaves visible, faded or not. */
export function shownTotal(bar, hiddenSegments) {
  const hidden = new Set(hiddenSegments);
  return SEGMENT_KEYS.reduce((n, k) => n + (hidden.has(k) ? 0 : bar.counts[k]), 0);
}

/**
 * Team bars ranked for the chart (notes 15): the active count, descending; ties go to the
 * larger shown total, then the franchise name A to Z, then its id. Returns a new array.
 */
export function rankTeamBars(model, bars, hiddenSegments) {
  const keyed = bars.map((bar) => ({
    bar,
    active: activeCount(bar, hiddenSegments),
    shown: shownTotal(bar, hiddenSegments),
    id: model.franchises[bar.franchise].id,
  }));
  keyed.sort((a, b) =>
    b.active - a.active
    || b.shown - a.shown
    || (a.bar.name < b.bar.name ? -1 : a.bar.name > b.bar.name ? 1 : 0)
    || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  return keyed.map((k) => k.bar);
}

const SUNDAY_AFTERNOON = new Set(['Sunday early', 'Sunday late']);

/**
 * Seasons in the range whose Fox AGOTW and CBS late national counts are not final: they have
 * Sunday-afternoon games with no network yet, so the CBS and FOX doubleheaders could not be
 * found (notes 15). `games` counts those games over the range.
 * @returns {{seasons: number[], games: number}}
 */
export function pendingNetworkSeasons(model, state) {
  const [lo, hi] = state.seasons;
  const c = model.cols;
  const seasons = new Set();
  let games = 0;
  for (let i = 0; i < model.n; i++) {
    if (c.season[i] < lo || c.season[i] > hi || c.network[i] != null) continue;
    if (!SUNDAY_AFTERNOON.has(model.slots[c.slot[i]])) continue;
    seasons.add(c.season[i]);
    games += 1;
  }
  return { seasons: [...seasons].sort((a, b) => a - b), games };
}

/** One series per view category with its points in the season range. */
export function viewershipSeries(model, state) {
  const [lo, hi] = state.seasons;
  // Low n means the game count in both the pick and no-pick paths (user rule, 2026-10-26;
  // Phase 15 review F7): the shipped residual-based `low_n` flag is not read, so a no-fit
  // point with enough games is solid.
  const threshold = lowNThreshold(model);
  return model.viewCategories.map((vc, category) => ({
    category,
    id: vc.id,
    label: vc.label,
    windowLevel: !!vc.window_level,
    points: model.viewership
      .filter((r) => r.category === category && r.season >= lo && r.season <= hi)
      .map((r) => ({
        season: r.season,
        era: r.era,
        mean: r.mean_viewers,
        resid: r.viewership_resid,
        se: r.viewership_se,
        games: r.games,
        lowN: r.games < threshold,
        gameList: r.gameList,
      })),
  }));
}

/** Game indexes the picked booths called (pbp person on a network of the booth's group). */
export function boothGames(model, keys) {
  const set = new Set();
  const c = model.cols;
  for (const key of keys || []) {
    const e = model.boothIndex.get(key);
    if (!e) continue;
    for (const i of model.personGames.get(e.person) || []) {
      if (c.network[i] == null || model.groupOfNetwork.get(c.network[i]) !== e.group) continue;
      if ((c.crew[i] || []).some((m) => m.person === e.person && m.role === 'pbp')) set.add(i);
    }
  }
  return [...set].sort((a, b) => a - b);
}

function newestFirst(model, list) {
  const c = model.cols;
  return [...list].sort((a, b) => {
    if (c.date[a] !== c.date[b]) return c.date[a] < c.date[b] ? 1 : -1;
    return b - a;
  });
}

/** Game indexes for the Matched games table. */
export function tableGames(model, state) {
  let base = null;
  const picks = computePicks(model, state);
  if (state.selection && state.selection.exact === true && Array.isArray(state.selection.games)) {
    // An all-games team bar lists exactly the games it counts: every filter but Team, which only
    // puts the picked teams' bars in focus, so the table never drops a game the bar shows.
    return newestFirst(model, state.selection.games);
  }
  if (state.selection && Array.isArray(state.selection.games)) {
    // Under a pick a chart click may carry games the pick excludes (a Special games bar, a point's
    // full list) and a selection can go stale when the pick changes, so intersect with the matched
    // mask. A scatter hand-pick that a later pick change leaves unmatched drops out of the table.
    base = picks.hasPick ? state.selection.games.filter((i) => picks.matched[i]) : state.selection.games;
  } else {
    if (picks.hasPick) {
      // U-05: Announcers and Booths intersect; computePicks already applies Seasons, Team and Category.
      base = [];
      for (let i = 0; i < model.n; i++) if (picks.matched[i]) base.push(i);
    } else if (state.teams.length) {
      // CFB parity (D-18, D-19): a Team alone fills the table with that team's games, as School does on CFB.
      base = model.cols.date.map((_, i) => i);
    }
  }
  if (!base) return [];
  return newestFirst(model, base.filter((i) => gamePasses(model, state, i)));
}

/**
 * Per-franchise, per-segment counts of the games in `matched` (a 0/1 mask over games) inside the
 * Seasons range. A game counts for both franchises under its exclusive category (D-24, the same
 * precedence as special[]); the 'none' category belongs to no segment. With matched = passes and
 * no Team/Category filter this equals the shipped special[] counts.
 */
export function specialMatchedCounts(model, state, matched) {
  const [lo, hi] = state.seasons;
  const c = model.cols;
  const out = new Map();
  const bump = (f, key) => {
    let rec = out.get(f);
    if (!rec) { rec = emptyCounts(); out.set(f, rec); }
    rec[key]++;
  };
  for (let i = 0; i < model.n; i++) {
    if (!matched[i] || c.season[i] < lo || c.season[i] > hi) continue;
    const cat = EXCLUSIVE_CATEGORIES[model.category[i]];
    if (!cat || cat.key === 'none') continue;
    bump(c.home[i], cat.key);
    bump(c.away[i], cat.key);
  }
  return out;
}

/** Count of non-default Seasons, Team, Category, Networks, Announcers and Booths filters (0-6). */
export function activeFilterCount(model, state) {
  const d = defaultNflState(model);
  let n = 0;
  if (state.seasons[0] !== d.seasons[0] || state.seasons[1] !== d.seasons[1]) n++;
  if (state.teams.length) n++;
  if (state.cats.length) n++;
  if (state.networks != null) n++;
  if (state.people.length) n++;
  if (state.booths.length) n++;
  return n;
}

// ---- every game by team and network (the first tab with "Special games only" off) ----

/** Per-network counts of game `i` added to a franchise's tally (`byNet`: network index -> counts). */
function bumpNet(byNet, netIdx, special) {
  let rec = byNet.get(netIdx);
  if (!rec) {
    rec = { count: 0, special: 0 };
    byNet.set(netIdx, rec);
  }
  rec.count += 1;
  if (special) rec.special += 1;
}

/** A tally (`network index -> {count, special}`) as family segments in legend order, each with its networks. */
function familySegments(model, byNet) {
  const { net } = model;
  const out = [];
  for (const family of net.families) {
    const channels = [];
    for (const idx of net.networksByFamily.get(family) ?? []) {
      const rec = byNet.get(idx);
      if (!rec) continue;
      const { id, name } = net.lookups.networks[idx];
      channels.push({ id, name, count: rec.count, special: rec.special });
    }
    if (!channels.length) continue;
    out.push({
      family,
      count: channels.reduce((n, ch) => n + ch.count, 0),
      special: channels.reduce((n, ch) => n + ch.special, 0),
      channels,
    });
  }
  return out;
}

/** Whether game `i` is a special game: it sits in one of the eight stack segments. */
export function isSpecialGame(model, i) {
  const cat = EXCLUSIVE_CATEGORIES[model.category[i]];
  return !!cat && cat.key !== 'none';
}

/**
 * The games an all-games bar counts: every filter except Team (Seasons, Networks, Category) and
 * the Announcers and Booths picks. Team does not narrow a bar; it puts the picked teams' bars in
 * focus, as on the Special games bars.
 */
export function countedMask(model, state) {
  return computePicks(model, state.teams.length ? { ...state, teams: [] } : state).matched;
}

/** Whether a filter or pick narrows the all-games bars, so team totals differ and rank the bars. */
export function barsNarrowed(state) {
  return state.networks != null || state.cats.length > 0 || state.people.length > 0 || state.booths.length > 0;
}

/**
 * One entry per franchise with a counted game: its games by network family and network, each
 * split into special and other games. `games` lists the counted game indexes (the bar click).
 */
export function networkBars(model, state) {
  const mask = countedMask(model, state);
  const c = model.cols;
  const tallies = new Map();
  for (let i = 0; i < model.n; i++) {
    if (!mask[i]) continue;
    const netIdx = c.network[i] ?? model.net.tbaIndex;
    const special = isSpecialGame(model, i);
    for (const f of [c.home[i], c.away[i]]) {
      let t = tallies.get(f);
      if (!t) {
        t = { byNet: new Map(), games: [] };
        tallies.set(f, t);
      }
      bumpNet(t.byNet, netIdx, special);
      t.games.push(i);
    }
  }
  const out = [];
  for (const [f, t] of tallies) {
    const segments = familySegments(model, t.byNet);
    out.push({
      franchise: f,
      name: model.franchises[f].name,
      total: segments.reduce((n, s) => n + s.count, 0),
      special: segments.reduce((n, s) => n + s.special, 0),
      segments,
      games: t.games,
      teamFaded: state.teams.length > 0 && !state.teams.includes(model.franchises[f].id),
    });
  }
  return rankNetworkBars(model, out, barsNarrowed(state));
}

/**
 * All-games bars ranked for the chart. With no narrowing filter every team has about the same
 * total (a full schedule), so the bars rank by special games, the solid part, with ties by the
 * franchise name A to Z and then its id: the order the Special games bars have with every chip
 * on (`rankTeamBars`), so the rows keep their places when the toggle flips. Once a filter or
 * pick narrows them they rank by their total, ties by special games, then name and id.
 */
export function rankNetworkBars(model, bars, narrowed) {
  const id = (b) => model.franchises[b.franchise].id;
  const byName = (a, b) =>
    (a.name < b.name ? -1 : a.name > b.name ? 1 : 0) || (id(a) < id(b) ? -1 : id(a) > id(b) ? 1 : 0);
  return [...bars].sort((a, b) => (narrowed
    ? b.total - a.total || b.special - a.special || byName(a, b)
    : b.special - a.special || byName(a, b)));
}

/** One row per season with a counted game for a franchise, newest first, in the bars' shape. */
export function networkSeasonRows(model, state, franchiseIdx) {
  const mask = countedMask(model, state);
  const c = model.cols;
  const seasons = new Map();
  for (const i of model.franchiseGames.get(franchiseIdx) || []) {
    if (!mask[i]) continue;
    let byNet = seasons.get(c.season[i]);
    if (!byNet) {
      byNet = new Map();
      seasons.set(c.season[i], byNet);
    }
    bumpNet(byNet, c.network[i] ?? model.net.tbaIndex, isSpecialGame(model, i));
  }
  return [...seasons.entries()]
    .sort((a, b) => b[0] - a[0])
    .map(([season, byNet]) => {
      const segments = familySegments(model, byNet);
      return {
        season,
        segments,
        total: segments.reduce((n, s) => n + s.count, 0),
        special: segments.reduce((n, s) => n + s.special, 0),
      };
    });
}

/**
 * Games per network index passing every filter and pick except Networks itself (the counts beside
 * the Networks list's rows and the legend's "no games" state), in `model.net` index order. On the
 * team bars Team is left out too: it only puts bars in focus there, so every team's networks
 * still show. This weekend counts its own week's games (weekend-data.js nflWeekendNetworkFacets).
 */
export function networkFacets(model, state) {
  const open = { ...state, networks: null, ...(state.view === 'teams' ? { teams: [] } : {}) };
  const mask = computePicks(model, open).matched;
  const counts = new Int32Array(model.net.lookups.networks.length);
  const c = model.cols;
  for (let i = 0; i < model.n; i++) {
    if (mask[i]) counts[c.network[i] ?? model.net.tbaIndex] += 1;
  }
  return counts;
}
