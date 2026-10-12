/**
 * NFL filter state, masks and aggregations (D-08, D-12 to D-15, D-24). DOM-free.
 *
 * State holds franchise ids and person ids (strings), not indexes, so the URL
 * round trip needs no translation. Selection and UI-only fields are never
 * encoded in the URL.
 */

export const NFL_VIEWS = Object.freeze(['special', 'crews', 'viewership', 'scatter']);
export const CREW_METRICS = Object.freeze(['margin', 'excitement', 'viewers']);

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
  { key: 'international_other', code: 7, label: 'International, shared window' },
  { key: 'none', code: 8, label: 'Other games' },
].map((o) => Object.freeze(o)));

/** The eight stack segments (everything but 'none'). */
const SEGMENT_KEYS = Object.freeze(EXCLUSIVE_CATEGORIES.filter((c) => c.key !== 'none').map((c) => c.key));
const SEGMENT_SET = new Set(SEGMENT_KEYS);

/** Category filter key -> segments it keeps in focus (flexed fades nothing). */
const CAT_SEGMENTS = Object.freeze({
  tnf: ['solo_thursday'],
  snf: ['solo_sunday'],
  mnf: ['solo_monday'],
  thanksgiving: ['solo_holiday'],
  christmas: ['solo_holiday'],
  blackfriday: ['solo_holiday'],
  saturday: ['solo_other'],
  intl_slot: ['solo_other'],
  other_standalone: ['solo_other'],
  agotw: ['agotw'],
  cbs: ['cbs_national'],
  intl: ['solo_other', 'international_other'],
});

const SPECIAL_SLOT_COLUMNS = Object.freeze([
  ['christmas', 'Christmas'], ['thanksgiving', 'Thanksgiving'],
  ['black_friday', 'Black Friday'], ['international', 'International'],
  ['tnf', 'TNF'], ['snf', 'SNF'], ['mnf', 'MNF'], ['saturday', 'Saturday'],
  ['friday', 'Friday'], ['sunday_early', 'Sunday early'],
  ['sunday_late', 'Sunday late'], ['other', 'Other'],
]);

function defaultNetwork(model) {
  const ids = model.networkGroups.map((g) => g.id);
  return ids.includes('fox') ? 'fox' : ids[0] ?? null;
}

function crewsDefaultSeason(model) {
  return model.freshness.crews_default_season ?? model.crewSeasons[0] ?? null;
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
    network: defaultNetwork(model),
    cseason: crewsDefaultSeason(model),
    booths: [],
    adjusted: false,
    metric: 'margin',
    viewY: 'mean',
    scatterX: 'date',
    scatterY: 'viewers',
    selection: null,
    showAllTeams: false,
    hiddenSegments: [],
    hiddenCategories: [],
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
  const cs = Number(s.cseason);
  const catIds = new Set(model.viewCategories.map((c) => c.id));
  const asList = (v) => (Array.isArray(v) ? v.filter((x) => typeof x === 'string') : []);
  return {
    view: pick(s.view, NFL_VIEWS, d.view),
    seasons: [lo, hi],
    teams: cleanIds(s.teams, new Map(model.franchises.map((f) => [f.id, 1]))),
    people: cleanIds(s.people, new Map(model.people.map((p) => [p.id, 1]))),
    cats: CAT_KEYS.filter((k) => catSet.has(k)),
    dots: s.dots === 'hide' ? 'hide' : 'fade',
    network: model.networkGroups.some((g) => g.id === s.network) ? s.network : d.network,
    cseason: model.crewSeasons.includes(cs) ? cs : d.cseason,
    booths: [...new Set(asList(s.booths).filter((k) => model.boothIndex.has(k)))],
    adjusted: s.adjusted === true,
    metric: pick(s.metric, CREW_METRICS, 'margin'),
    viewY: s.viewY === 'resid' ? 'resid' : 'mean',
    scatterX: s.scatterX === 'margin' ? 'margin' : 'date',
    scatterY: s.scatterY === 'excitement' ? 'excitement' : 'viewers',
    selection: s.selection && typeof s.selection === 'object' ? s.selection : null,
    showAllTeams: s.showAllTeams === true,
    hiddenSegments: [...new Set(asList(s.hiddenSegments).filter((k) => EXCLUSIVE_CATEGORIES.some((c) => c.key === k)))],
    hiddenCategories: [...new Set(asList(s.hiddenCategories).filter((k) => catIds.has(k)))],
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

function finish(model, acc, fIdx, denom, faded, segFaded) {
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

function groupIndexOf(model, id) {
  return model.networkGroups.findIndex((g) => g.id === id);
}

/** Network groups with a game in the season range, in lookup order. */
export function crewsNetworks(model, state) {
  const [lo, hi] = state.seasons;
  const c = model.cols;
  const has = new Set();
  for (let i = 0; i < model.n; i++) {
    if (c.season[i] < lo || c.season[i] > hi || c.network[i] == null) continue;
    const g = model.groupOfNetwork.get(c.network[i]);
    if (g !== undefined) has.add(g);
  }
  return model.networkGroups
    .map((g, index) => ({ id: g.id, index, name: g.name, flagship: g.flagship }))
    .filter((g) => has.has(g.index));
}

/** Seasons (newest first) with booth rows for a network group index. */
export function crewsSeasons(model, groupIndex) {
  return model.crewSeasonsByGroup.get(groupIndex) ?? [];
}

/** Booth rows for the picked network and season, by rank. */
export function crewsRows(model, state) {
  const gi = groupIndexOf(model, state.network);
  return model.booths
    .filter((r) => r.network_group === gi && r.season === state.cseason)
    .sort((a, b) => (a.rank ?? 0) - (b.rank ?? 0));
}

/** {total, withCrew, fromLineup} over the picked network's games in the season. */
export function crewsCoverage(model, state) {
  const gi = groupIndexOf(model, state.network);
  const c = model.cols;
  const out = { total: 0, withCrew: 0, fromLineup: 0 };
  for (let i = 0; i < model.n; i++) {
    if (c.season[i] !== state.cseason || c.network[i] == null) continue;
    if (model.groupOfNetwork.get(c.network[i]) !== gi) continue;
    out.total++;
    if ((c.crew[i] || []).length) out.withCrew++;
    if (c.crew_source[i] === 'published_lineup') out.fromLineup++;
  }
  return out;
}

/** One series per view category with its points in the season range. */
export function viewershipSeries(model, state) {
  const [lo, hi] = state.seasons;
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
        lowN: !!r.low_n,
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

/** True when any game in the list was called by one of the picked booths. */
export function pointHasBooth(model, gameList, keys) {
  if (!keys || !keys.length) return false;
  const set = new Set(boothGames(model, keys));
  return (gameList || []).some((g) => set.has(g));
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
  else if (state.booths.length) base = boothGames(model, state.booths);
  else if (state.people.length) {
    const set = new Set();
    for (const id of state.people) {
      for (const g of model.personGames.get(model.personIndex.get(id)) || []) set.add(g);
    }
    base = [...set];
  } else if (state.teams.length) {
    // CFB parity (D-18, D-19): a Team alone fills the table with that team's games, as School does on CFB.
    base = model.cols.date.map((_, i) => i);
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
  if (state.booths.length) n++;
  return n;
}
