/**
 * NFL filter state, masks and aggregations (D-08, D-12 to D-15, D-24). DOM-free.
 *
 * State holds franchise ids and person ids (strings), not indexes, so the URL
 * round trip needs no translation. Selection and UI-only fields are never
 * encoded in the URL.
 */

export const NFL_VIEWS = Object.freeze(['special', 'fox', 'agotw', 'scatter']);
export const METRICS = Object.freeze(['margin', 'excitement', 'volatility']);

/** Category filter options in UI order (labels exact per UI-SPEC). */
export const CATEGORY_OPTIONS = Object.freeze([
  { key: 'tnf', label: 'Thursday Night Football (TNF)', group: 'Standalone slots', slot: 'TNF' },
  { key: 'snf', label: 'Sunday Night Football (SNF)', group: 'Standalone slots', slot: 'SNF' },
  { key: 'mnf', label: 'Monday Night Football (MNF)', group: 'Standalone slots', slot: 'MNF' },
  { key: 'thanksgiving', label: 'Thanksgiving', group: 'Standalone slots', slot: 'Thanksgiving' },
  { key: 'christmas', label: 'Christmas', group: 'Standalone slots', slot: 'Christmas' },
  { key: 'blackfriday', label: 'Black Friday', group: 'Standalone slots', slot: 'Black Friday' },
  { key: 'saturday', label: 'Saturday', group: 'Standalone slots', slot: 'Saturday' },
  { key: 'intl_slot', label: 'International (standalone slot)', group: 'Standalone slots', slot: 'International' },
  { key: 'other_standalone', label: 'Other standalone slots', group: 'Standalone slots', slot: null },
  { key: 'agotw', label: 'AGOTW', group: 'Other special games', slot: null },
  { key: 'cbs', label: 'CBS national', group: 'Other special games', slot: null },
  { key: 'intl', label: 'International (any slot)', group: 'Other special games', slot: null },
  { key: 'flexed', label: 'Flexed', group: 'Other special games', slot: null },
].map((o) => Object.freeze(o)));

const CAT_KEYS = CATEGORY_OPTIONS.map((o) => o.key);
const STANDALONE_SLOT_BY_KEY = new Map(
  CATEGORY_OPTIONS.filter((o) => o.slot).map((o) => [o.key, o.slot]),
);
const NAMED_SLOTS = new Set(STANDALONE_SLOT_BY_KEY.values());
const STANDALONE_KEYS = new Set(['other_standalone', ...STANDALONE_SLOT_BY_KEY.keys()]);

/** Exclusive categories (bars and scatter color), code order matches model.category. */
export const EXCLUSIVE_CATEGORIES = Object.freeze([
  { key: 'standalone', code: 0, label: 'Standalone slot' },
  { key: 'agotw', code: 1, label: 'AGOTW' },
  { key: 'cbs_national', code: 2, label: 'CBS national' },
  { key: 'international_other', code: 3, label: 'International (not standalone)' },
  { key: 'none', code: 4, label: 'Other games' },
].map((o) => Object.freeze(o)));

const SPECIAL_SLOT_COLUMNS = Object.freeze([
  ['christmas', 'Christmas'], ['thanksgiving', 'Thanksgiving'],
  ['black_friday', 'Black Friday'], ['international', 'International'],
  ['tnf', 'TNF'], ['snf', 'SNF'], ['mnf', 'MNF'], ['saturday', 'Saturday'],
  ['friday', 'Friday'], ['sunday_early', 'Sunday early'],
  ['sunday_late', 'Sunday late'], ['other', 'Other'],
]);

function foxDefault(model) {
  return model.freshness.fox_default_season ?? model.foxSeasons[0] ?? null;
}

/** @returns {object} the default NFL state for this model */
export function defaultNflState(model) {
  return {
    view: 'special',
    seasons: [model.seasons[0], model.seasons[1]],
    teams: [],
    people: [],
    cats: [],
    dots: 'fade',
    fseason: foxDefault(model),
    adjusted: false,
    metric: 'margin',
    agotwY: 'mean',
    scatterX: 'date',
    scatterY: 'viewers',
    selection: null,
    showAllTeams: false,
    hiddenSegments: [],
    hiddenCrews: [],
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
  const fs = Number(s.fseason);
  return {
    view: pick(s.view, NFL_VIEWS, d.view),
    seasons: [lo, hi],
    teams: cleanIds(s.teams, new Map(model.franchises.map((f) => [f.id, 1]))),
    people: cleanIds(s.people, new Map(model.people.map((p) => [p.id, 1]))),
    cats: CAT_KEYS.filter((k) => catSet.has(k)),
    dots: s.dots === 'hide' ? 'hide' : 'fade',
    fseason: model.foxSeasons.includes(fs) ? fs : d.fseason,
    adjusted: s.adjusted === true,
    metric: pick(s.metric, METRICS, 'margin'),
    agotwY: s.agotwY === 'resid' ? 'resid' : 'mean',
    scatterX: s.scatterX === 'margin' ? 'margin' : 'date',
    scatterY: s.scatterY === 'excitement' ? 'excitement' : 'viewers',
    selection: s.selection && typeof s.selection === 'object' ? s.selection : null,
    showAllTeams: s.showAllTeams === true,
    hiddenSegments: Array.isArray(s.hiddenSegments) ? [...s.hiddenSegments] : [],
    hiddenCrews: Array.isArray(s.hiddenCrews) ? [...s.hiddenCrews] : [],
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

/** Seasons AND Team AND Category (match any); an empty filter passes all. */
export function gamePasses(model, state, i) {
  const c = model.cols;
  if (c.season[i] < state.seasons[0] || c.season[i] > state.seasons[1]) return false;
  if (state.teams.length) {
    const home = model.franchises[c.home[i]].id;
    const away = model.franchises[c.away[i]].id;
    if (!state.teams.includes(home) && !state.teams.includes(away)) return false;
  }
  if (state.cats.length && !state.cats.some((k) => catMatches(model, k, i))) return false;
  return true;
}

/** True when any selected person called game i. */
export function personHighlight(model, state, i) {
  if (!state.people.length) return false;
  const idx = new Set(state.people.map((id) => model.personIndex.get(id)));
  return (model.cols.crew[i] || []).some((m) => idx.has(m.person));
}

function emptyCounts() {
  return { standalone: 0, agotw: 0, cbs_national: 0, international_other: 0 };
}

function addRow(acc, r) {
  acc.counts.standalone += r.standalone_total;
  acc.counts.agotw += r.agotw;
  acc.counts.cbs_national += r.cbs_national;
  acc.counts.international_other += r.international_other;
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

function denominators(model, lo, hi) {
  let fox = 0;
  let cbs = 0;
  for (const [season, w] of model.seasonWeeks) {
    if (season < lo || season > hi) continue;
    fox += w.fox_doubleheader_weeks - w.fox_ambiguous_weeks;
    cbs += w.cbs_doubleheader_weeks - w.cbs_ambiguous_weeks;
  }
  return { fox, cbs };
}

function segmentFading(state) {
  const relevant = state.cats.filter((k) => STANDALONE_KEYS.has(k) || k === 'agotw' || k === 'cbs');
  if (!relevant.length) {
    return { standalone: false, agotw: false, cbs_national: false, international_other: false };
  }
  return {
    standalone: !relevant.some((k) => STANDALONE_KEYS.has(k)),
    agotw: !relevant.includes('agotw'),
    cbs_national: !relevant.includes('cbs'),
    international_other: true,
  };
}

function finish(model, acc, fIdx, denom, faded, segFaded) {
  const slots = SPECIAL_SLOT_COLUMNS
    .filter(([col]) => acc.slotCounts[col] > 0)
    .map(([col, label]) => ({ key: col, label, count: acc.slotCounts[col] }));
  const c = acc.counts;
  return {
    franchise: fIdx,
    name: model.franchises[fIdx].name,
    counts: c,
    total: c.standalone + c.agotw + c.cbs_national + c.international_other,
    international: acc.international,
    flexed: acc.flexed,
    games: acc.games,
    slots,
    agotwRate: { count: c.agotw, denom: denom.fox },
    cbsRate: { count: c.cbs_national, denom: denom.cbs },
    teamFaded: faded,
    segmentFaded: segFaded,
  };
}

/** One entry per franchise, summed over the selected season range. */
export function teamBars(model, state) {
  const [lo, hi] = state.seasons;
  const accs = model.franchises.map(() => newAcc());
  for (const r of model.special) {
    if (r.season < lo || r.season > hi) continue;
    addRow(accs[r.franchise], r);
  }
  const denom = denominators(model, lo, hi);
  const segFaded = segmentFading(state);
  const out = accs.map((acc, f) =>
    finish(
      model, acc, f, denom,
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
  const rows = model.special
    .filter((r) => r.franchise === franchiseIdx && r.season >= lo && r.season <= hi)
    .sort((a, b) => b.season - a.season);
  return rows.map((r) => {
    const acc = newAcc();
    addRow(acc, r);
    const d = denominators(model, r.season, r.season);
    return { season: r.season, ...finish(model, acc, franchiseIdx, d, false, segFaded) };
  });
}

/** '4 of 8 weeks (50%)' or 'n/a' when no denominator. */
export function rateText(count, denom) {
  if (!(denom > 0)) return 'n/a';
  return `${count} of ${denom} weeks (${Math.round((count / denom) * 100)}%)`;
}

/** Fox rows for one season, never pooled: lead, others by rank, pooled. */
export function foxRows(model, state) {
  return model.foxBooths
    .filter((r) => r.season === state.fseason)
    .sort((a, b) =>
      (GROUP_RANK[a.group] ?? 9) - (GROUP_RANK[b.group] ?? 9) || (a.rank ?? 0) - (b.rank ?? 0));
}
const GROUP_RANK = { lead: 0, other: 1, others_pooled: 2 };

/** AGOTW points per season in range, split into segments where the crew changes. */
export function agotwSeries(model, state) {
  const [lo, hi] = state.seasons;
  const points = model.agotw
    .filter((r) => r.season >= lo && r.season <= hi)
    .map((r) => ({
      season: r.season,
      crewKey: `${r.pbp_person ?? ''}|${r.analyst_person ?? ''}`,
      pbp: r.pbp_person,
      analyst: r.analyst_person,
      era: r.era,
      values: { mean: r.mean_viewers, resid: r.viewership_resid, se: r.viewership_se },
      games: r.games,
      fillIn: r.fill_in_games,
      lowN: !!r.low_n,
      gameList: r.gameList,
    }));
  const order = new Map();
  const segments = [];
  for (const p of points) {
    if (!order.has(p.crewKey)) order.set(p.crewKey, order.size);
    const last = segments[segments.length - 1];
    if (last && last.crewKey === p.crewKey) last.points.push(p);
    else segments.push({ crewKey: p.crewKey, order: order.get(p.crewKey), points: [p] });
  }
  return { points, segments };
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
  if (state.selection && Array.isArray(state.selection.games)) base = state.selection.games;
  else if (state.people.length) {
    const set = new Set();
    for (const id of state.people) {
      for (const g of model.personGames.get(model.personIndex.get(id)) || []) set.add(g);
    }
    base = [...set];
  }
  if (!base) return [];
  return newestFirst(model, base.filter((i) => gamePasses(model, state, i)));
}

/** Count of non-default Seasons, Team, Category and Announcers filters (0-4). */
export function activeFilterCount(model, state) {
  const d = defaultNflState(model);
  let n = 0;
  if (state.seasons[0] !== d.seasons[0] || state.seasons[1] !== d.seasons[1]) n++;
  if (state.teams.length) n++;
  if (state.cats.length) n++;
  if (state.people.length) n++;
  return n;
}
