/**
 * Bars and Butterfly counting core (SITE-33..36, D-01..D-18). DOM-free;
 * imports only from ./select.js and ./palette.js. Every value is a count of games, rated and
 * unrated, with `rated` carried beside each count for the split (04.13 D-15): this module
 * never reads `viewers` and no model carries one.
 *
 * Games counted are exactly those passing every filter, narrowed to the
 * person-matched games when someone is selected (D-02). Crew matching goes
 * only through select.js's `personOnGame`. Rows sort by count descending,
 * ties by bare name (D-03); announcer rows share one list labeled
 * with the bare name; roles ride along as data (D-04, D-28). The butterfly (D-05..D-09)
 * mirrors the Bars rows for exactly two schools or two announcers.
 * Stacked announcer rows are one per network family (D-23, superseding D-15's
 * per-channel rows): segments are announcers, each carrying per-channel counts
 * and a stable `shade` index (`familyChannelOrder`); a `family` row's drill
 * target sets Networks to the family's offered channels (`offeredFamilyIds`).
 * `chartContext` decides which tabs apply and the Group-by (D-07, D-11) and
 * `drillPatch` builds the setState patch for a row/segment click (D-18).
 * Simple announcer rows carry `mainFamily` (D-31): the network family with the
 * most of the announcer's counted games, over both sides on the Butterfly.
 */

import { FAMILY_LABELS, FAMILY_ORDER, familyKey } from './palette.js';
import { MAX_COMPARE, offeredFamilyIds, personOnGame } from './select.js';

/** Rows shown before "show all" (D-03). */
export const TOP_N = 15;

/** Row key for games whose conference is unknown (D-15). */
export const NO_CONFERENCE_KEY = 'c:__none__';

/** Announcer roles in display order (04.6 D-18). */
export const ROLE_ORDER = ['pbp', 'analyst', 'unknown'];

/** Grouping options in their fixed display order (04.6 D-21). */
export const BY_ORDER = ['announcer', 'network', 'team', 'conference'];

/**
 * Splits a `by` value into the row group preference and bar style (04.6 D-27).
 * @param {string|null} by - null | 'announcer' | 'network' | 'team' | 'conference'.
 * @returns {{pref: 'announcers'|'teams', mode: 'simple'|'stacked'}}
 */
export function byParts(by) {
  if (by === 'network') return { pref: 'announcers', mode: 'stacked' };
  if (by === 'team') return { pref: 'teams', mode: 'simple' };
  if (by === 'conference') return { pref: 'teams', mode: 'stacked' };
  return { pref: 'announcers', mode: 'simple' };
}

/**
 * Joins a resolved group and mode back into a `by` value (04.6 D-26).
 * @param {'announcers'|'teams'} group
 * @param {'simple'|'stacked'} mode
 * @returns {'announcer'|'network'|'team'|'conference'}
 */
export function byFrom(group, mode) {
  if (group === 'announcers') return mode === 'stacked' ? 'network' : 'announcer';
  return mode === 'stacked' ? 'conference' : 'team';
}

/**
 * The setState patch for clicking a grouping option: the first applicable
 * option is the default and is stored as null (04.6 D-27).
 * @param {string} clicked
 * @param {string[]} options - applicable options in display order.
 * @returns {{by: string|null}}
 */
export function byPatch(clicked, options) {
  return { by: clicked === options[0] ? null : clicked };
}

/**
 * Which bar tabs apply, and the grouping choice (D-07, D-11, D-13; 04.6 D-21).
 * `state.by` keeps the raw preference; the resolved values are returned.
 * @param {object} _data - a `prepareData` result (unused).
 * @param {object} state
 * @returns {object}
 */
export function chartContext(data, state) {
  // A named Game pick counts like a School for the announcers grouping (04.9 D-18); it adds
  // no Butterfly trigger. Unknown slugs never reach state (url-state allowlist), but check anyway.
  const gamePicked = state.game != null && data.gameIndexBySlug.has(state.game);
  const announcersApply = state.school.length > 0 || gamePicked;
  const teamsApply = state.networks !== null || state.people.length > 0;
  const { pref, mode } = byParts(state.by);
  const preferTeams = pref === 'teams';
  // Head-to-head makes the two schools one matchup subject: the Bars group by
  // announcer or network only (04.7 D-15), even with a person or Networks set,
  // since "by Team" would always draw the same two schools.
  const matchup = state.h2h === true && state.school.length === 2;
  const groupChoice = announcersApply && teamsApply && !matchup;
  let group = 'teams';
  if (groupChoice) group = preferTeams ? 'teams' : 'announcers';
  else if (announcersApply) group = 'announcers';

  // Head-to-head makes the two schools one matchup subject, so only two
  // announcers can trigger the Butterfly (04.7 D-15).
  const twoSchools = state.school.length === 2 && state.h2h !== true;
  const twoPeople = state.people.length === 2;
  const butterflyGroupChoice = twoSchools && twoPeople;
  let butterflyGroup = 'teams';
  if (butterflyGroupChoice) butterflyGroup = preferTeams ? 'teams' : 'announcers';
  else if (twoSchools) butterflyGroup = 'announcers';

  const optionsFor = (choice, g) => {
    if (choice) return [...BY_ORDER];
    return g === 'announcers' ? ['announcer', 'network'] : ['team', 'conference'];
  };

  return {
    barsEnabled: announcersApply || teamsApply,
    groupChoice,
    group,
    mode,
    byOptions: optionsFor(groupChoice, group),
    by: byFrom(group, mode),
    butterflyEnabled: twoSchools || twoPeople,
    butterflyGroupChoice,
    butterflyGroup,
    butterflyByOptions: optionsFor(butterflyGroupChoice, butterflyGroup),
    butterflyBy: byFrom(butterflyGroup, mode),
  };
}

/**
 * Indexes of games passing every filter.
 * @param {object} view - a `computeView` result.
 * @returns {number[]}
 */
export function passingIndices(view) {
  const out = [];
  for (let i = 0; i < view.passesFilters.length; i += 1) {
    if (view.passesFilters[i]) out.push(i);
  }
  return out;
}

/**
 * The games the Bars tab counts (D-02): the person-matched games when a
 * person is selected, else every passing game.
 * @param {object} view - a `computeView` result.
 * @returns {number[]}
 */
export function gamesForBars(view) {
  return view.hasPersonSelection ? view.highlighted : passingIndices(view);
}

/**
 * Roles in display order (D-18); unknown values are dropped.
 * @param {string[]} roles - roles present, any order.
 * @returns {string[]}
 */
export function orderedRoles(roles) {
  return ROLE_ORDER.filter((r) => roles.includes(r));
}

/** Sort comparator: count descending, ties by bare name, then key. */
function byCount(countOf) {
  return (a, b) => {
    const diff = countOf(b) - countOf(a);
    if (diff !== 0) return diff;
    const byName = a.name.localeCompare(b.name, 'en');
    return byName !== 0 ? byName : a.key.localeCompare(b.key, 'en');
  };
}

const channelOrderCache = new WeakMap();

/**
 * A family's primary network indexes ordered by data-wide telecast count
 * (highest first, ties by lookup order), so a channel keeps one shade in every
 * row and filter state (D-23).
 * @param {object} data - a `prepareData` result.
 * @param {string} family - a `familyKey` value.
 * @returns {number[]}
 */
export function familyChannelOrder(data, family) {
  let cache = channelOrderCache.get(data);
  if (!cache) {
    const counts = new Map();
    for (let i = 0; i < data.t.network.length; i += 1) {
      const net = data.t.network[i];
      counts.set(net, (counts.get(net) ?? 0) + 1);
    }
    cache = { counts, orders: new Map() };
    channelOrderCache.set(data, cache);
  }
  let order = cache.orders.get(family);
  if (!order) {
    const base = data.networksByFamily.get(family) ?? [];
    order = base
      .map((idx, pos) => ({ idx, pos, n: cache.counts.get(idx) ?? 0 }))
      .sort((a, b) => b.n - a.n || a.pos - b.pos)
      .map((e) => e.idx);
    cache.orders.set(family, order);
  }
  return order;
}

/**
 * The family key with the highest count, ties broken by FAMILY_ORDER (D-31).
 * @param {Map<string, number>} counts - family key to counted games.
 * @returns {string|null}
 */
export function mainFamilyOf(counts) {
  let best = null;
  let bestN = 0;
  for (const [key, n] of counts) {
    const better =
      n > bestN || (n === bestN && best != null && FAMILY_ORDER.indexOf(key) < FAMILY_ORDER.indexOf(best));
    if (better) {
      best = key;
      bestN = n;
    }
  }
  return best;
}

/**
 * Counts announcers over `games` (the computeFacets per-person `seen` rule).
 * Returns segments; with `withChannels` each also carries per-channel counts,
 * with `withMainFamily` the main network family (D-31).
 */
function countAnnouncers(
  data,
  games,
  role,
  { withChannels = false, family = null, withMainFamily = false } = {},
) {
  const acc = new Map();
  for (const i of games) {
    const seen = new Set();
    for (const entry of data.t.crew[i]) {
      if (seen.has(entry.person)) continue;
      seen.add(entry.person);
      if (personOnGame(data, i, entry.person, role) == null) continue;
      let rec = acc.get(entry.person);
      if (!rec) {
        rec = { count: 0, rated: 0, main: new Set(), alt: new Set(), nets: new Map(), fams: new Map() };
        acc.set(entry.person, rec);
      }
      rec.count += 1;
      const isRated = data.rated[i] === 1 ? 1 : 0;
      rec.rated += isRated;
      if (withMainFamily) {
        const fam = familyKey(data.lookups.networks[data.t.network[i]].family);
        rec.fams.set(fam, (rec.fams.get(fam) ?? 0) + 1);
      }
      if (withChannels) {
        const net = data.t.network[i];
        const cur = rec.nets.get(net) ?? { count: 0, rated: 0 };
        rec.nets.set(net, { count: cur.count + 1, rated: cur.rated + isRated });
      }
      for (const e of data.t.crew[i]) {
        if (e.person !== entry.person) continue;
        if (e.feed === 'main') rec.main.add(e.role);
        else if (e.feed === 'alt') rec.alt.add(e.role);
      }
    }
  }
  const segments = [];
  for (const [person, rec] of acc) {
    const { id, name } = data.lookups.people[person];
    const roles = Array.from(rec.main.size > 0 ? rec.main : rec.alt);
    const seg = {
      key: `p:${id}`,
      name,
      label: name,
      roles: orderedRoles(roles),
      count: rec.count,
      rated: rec.rated,
      target: { kind: 'person', id },
    };
    if (withMainFamily) seg.mainFamily = mainFamilyOf(rec.fams);
    if (withChannels) {
      const order = familyChannelOrder(data, family);
      seg.channels = Array.from(rec.nets, ([net, { count, rated }]) => ({
        id: data.lookups.networks[net].id,
        name: data.lookups.networks[net].name,
        count,
        rated,
        shade: order.indexOf(net),
      })).sort((a, b) => a.shade - b.shade);
    }
    segments.push(seg);
  }
  return segments.sort(byCount((s) => s.count));
}

/** Counts schools over `games` (each side once; a team playing itself counts once). */
function countTeams(data, games) {
  const acc = new Map();
  const bump = (idx, isRated) => {
    const cur = acc.get(idx) ?? { count: 0, rated: 0 };
    acc.set(idx, { count: cur.count + 1, rated: cur.rated + isRated });
  };
  for (const i of games) {
    const isRated = data.rated[i] === 1 ? 1 : 0;
    bump(data.t.home_team[i], isRated);
    if (data.t.away_team[i] !== data.t.home_team[i]) bump(data.t.away_team[i], isRated);
  }
  const segments = [];
  for (const [idx, { count, rated }] of acc) {
    const name = data.lookups.teams[idx].name;
    segments.push({
      key: `t:${data.teamSlugs[idx]}`,
      name,
      label: name,
      count,
      rated,
      target: { kind: 'team', slug: data.teamSlugs[idx] },
    });
  }
  return segments.sort(byCount((s) => s.count));
}

/** Simple announcer rows: one row per announcer. */
function announcerRows(data, games, role) {
  return countAnnouncers(data, games, role, { withMainFamily: true }).map((s) => ({
    key: s.key,
    name: s.name,
    label: s.label,
    roles: s.roles,
    family: null,
    mainFamily: s.mainFamily,
    total: s.count,
    rated: s.rated,
    target: s.target,
    segments: [],
  }));
}

/** Simple team rows: one row per school. */
function teamRows(data, games) {
  return countTeams(data, games).map((s) => ({
    key: s.key,
    name: s.name,
    label: s.label,
    roles: [],
    family: null,
    mainFamily: null,
    total: s.count,
    rated: s.rated,
    target: s.target,
    segments: [],
  }));
}

/** Stacked announcer rows: network families, each stacked by announcer with per-channel counts (D-23). */
function familyRows(data, games, role, view) {
  const byFamily = new Map();
  for (const i of games) {
    const family = familyKey(data.lookups.networks[data.t.network[i]].family);
    if (!byFamily.has(family)) byFamily.set(family, []);
    byFamily.get(family).push(i);
  }
  const rows = [];
  for (const [family, list] of byFamily) {
    const segments = countAnnouncers(data, list, role, { withChannels: true, family });
    const total = segments.reduce((sum, s) => sum + s.count, 0);
    const rated = segments.reduce((sum, s) => sum + s.rated, 0);
    if (total === 0) continue;
    const label = FAMILY_LABELS[family];
    rows.push({
      key: `f:${family}`,
      name: label,
      label,
      roles: [],
      family,
      mainFamily: null,
      total,
      rated,
      shadeCount: familyChannelOrder(data, family).length,
      target: { kind: 'family', family, ids: offeredFamilyIds(data, family, view) },
      segments,
    });
  }
  return rows.sort(byCount((r) => r.total));
}

/** Stacked team rows: per-game era-correct conferences, each stacked by team (D-15). */
function conferenceRows(data, games) {
  const byConf = new Map();
  const add = (confIdx, teamIdx, isRated) => {
    const name = confIdx == null ? null : data.lookups.conferences[confIdx].name;
    const key = name == null ? NO_CONFERENCE_KEY : `c:${name}`;
    let rec = byConf.get(key);
    if (!rec) {
      rec = { name, teams: new Map() };
      byConf.set(key, rec);
    }
    const cur = rec.teams.get(teamIdx) ?? { count: 0, rated: 0 };
    rec.teams.set(teamIdx, { count: cur.count + 1, rated: cur.rated + isRated });
  };
  for (const i of games) {
    const isRated = data.rated[i] === 1 ? 1 : 0;
    add(data.t.home_conference[i], data.t.home_team[i], isRated);
    if (data.t.away_team[i] !== data.t.home_team[i]) add(data.t.away_conference[i], data.t.away_team[i], isRated);
  }
  const rows = [];
  for (const [key, rec] of byConf) {
    const segments = [];
    for (const [idx, { count, rated }] of rec.teams) {
      const name = data.lookups.teams[idx].name;
      segments.push({
        key: `t:${data.teamSlugs[idx]}`,
        name,
        label: name,
        count,
        rated,
        target: { kind: 'team', slug: data.teamSlugs[idx] },
      });
    }
    segments.sort(byCount((s) => s.count));
    const label = rec.name ?? 'No conference';
    const target =
      rec.name != null && data.fbsConferences.includes(rec.name)
        ? { kind: 'conference', name: rec.name }
        : null;
    rows.push({
      key,
      name: label,
      label,
      roles: [],
      family: null,
      mainFamily: null,
      total: segments.reduce((sum, s) => sum + s.count, 0),
      rated: segments.reduce((sum, s) => sum + s.rated, 0),
      target,
      segments,
    });
  }
  return rows.sort(byCount((r) => r.total));
}

/** Shape of the rows for a group/mode: `{ rowKind, segmentKind, build(games) }`. */
function rowSpec(data, group, mode, role, view) {
  if (group === 'announcers') {
    return mode === 'stacked'
      ? { rowKind: 'family', segmentKind: 'person', build: (g) => familyRows(data, g, role, view) }
      : { rowKind: 'person', segmentKind: null, build: (g) => announcerRows(data, g, role) };
  }
  return mode === 'stacked'
    ? { rowKind: 'conference', segmentKind: 'team', build: (g) => conferenceRows(data, g) }
    : { rowKind: 'team', segmentKind: null, build: (g) => teamRows(data, g) };
}

/**
 * The Bars tab model (D-01..D-04, D-15), or null when the tab does not apply.
 * @param {object} data - a `prepareData` result.
 * @param {object} view - a `computeView` result.
 * @param {object} state
 * @returns {object|null}
 */
export function barsModel(data, view, state) {
  const ctx = chartContext(data, state);
  if (!ctx.barsEnabled) return null;
  const spec = rowSpec(data, ctx.group, ctx.mode, state.role, view);
  return {
    kind: 'bars',
    group: ctx.group,
    mode: ctx.mode,
    rowKind: spec.rowKind,
    segmentKind: spec.segmentKind,
    rows: spec.build(gamesForBars(view)),
  };
}

/**
 * The Butterfly model (D-05..D-09), or null unless exactly two schools or
 * two announcers are selected. Per-side sets ignore `together`: each side is
 * the passing games that subject appears in; `shared` counts games in both.
 * @param {object} data - a `prepareData` result.
 * @param {object} view - a `computeView` result.
 * @param {object} state
 * @returns {object|null}
 */
export function butterflyModel(data, view, state) {
  const ctx = chartContext(data, state);
  if (!ctx.butterflyEnabled) return null;
  const group = ctx.butterflyGroup;
  const spec = rowSpec(data, group, ctx.mode, state.role, view);
  let sides;
  let sets;
  if (group === 'announcers') {
    const base = gamesForBars(view);
    sides = state.school.map((slug) => ({
      key: `t:${slug}`,
      name: data.lookups.teams[data.teamIndexBySlug.get(slug)].name,
      kind: 'school',
    }));
    sets = state.school.map((slug) => {
      const idx = data.teamIndexBySlug.get(slug);
      return base.filter((i) => data.t.home_team[i] === idx || data.t.away_team[i] === idx);
    });
  } else {
    const base = passingIndices(view);
    sides = state.people.map((id) => ({
      key: `p:${id}`,
      name: data.lookups.people[data.personIndexById.get(id)].name,
      kind: 'person',
    }));
    sets = state.people.map((id) => {
      const idx = data.personIndexById.get(id);
      return base.filter((i) => personOnGame(data, i, idx, state.role) != null);
    });
  }
  const inRight = new Set(sets[1]);
  const shared = sets[0].filter((i) => inRight.has(i)).length;

  // D-31: a person row's main family and union roles cover both sides'
  // games, each game once.
  const unionByKey = new Map();
  if (spec.rowKind === 'person') {
    const union = Array.from(new Set([...sets[0], ...sets[1]])).sort((a, b) => a - b);
    for (const row of spec.build(union)) unionByKey.set(row.key, row);
  }
  const left = spec.build(sets[0]);
  const right = spec.build(sets[1]);
  const rows = new Map();
  const empty = { total: 0, rated: 0, segments: [] };
  for (const [side, list] of [[0, left], [1, right]]) {
    for (const row of list) {
      let merged = rows.get(row.key);
      if (!merged) {
        merged = {
          key: row.key,
          name: row.name,
          label: row.label,
          roles: unionByKey.get(row.key)?.roles ?? row.roles ?? [],
          family: row.family,
          mainFamily: spec.rowKind === 'person' ? (unionByKey.get(row.key)?.mainFamily ?? null) : null,
          total: 0,
          rated: 0,
          target: row.target,
          sides: [{ ...empty }, { ...empty }],
        };
        if (row.shadeCount != null) merged.shadeCount = row.shadeCount;
        rows.set(row.key, merged);
      }
      merged.sides[side] = { total: row.total, rated: row.rated, segments: row.segments };
      merged.total += row.total;
      merged.rated += row.rated;
    }
  }
  return {
    kind: 'butterfly',
    group,
    mode: ctx.mode,
    rowKind: spec.rowKind,
    segmentKind: spec.segmentKind,
    sides,
    shared,
    rows: Array.from(rows.values()).sort(byCount((r) => r.total)),
  };
}

/**
 * The rows to draw: the top `TOP_N` until expanded (D-03).
 * @param {object[]} rows
 * @param {boolean} expanded
 * @returns {object[]}
 */
export function visibleRows(rows, expanded) {
  return expanded ? rows : rows.slice(0, TOP_N);
}

/**
 * The setState patch for clicking a row or segment (D-18), or null when the
 * click would do nothing (already applied, over the compare cap, or not a
 * filterable target). Keeps the shown grouping (`by`, 04.6 D-26) so a click
 * never flips the chart's grouping.
 * @param {object} data - a `prepareData` result.
 * @param {object} state
 * @param {object|null} target
 * @returns {object|null}
 */
export function drillPatch(data, state, target) {
  if (target == null) return null;
  let patch = null;
  if (target.kind === 'person') {
    if (state.people.includes(target.id)) return null;
    if (state.compare && state.people.length >= MAX_COMPARE) return null;
    patch = { people: [...state.people, target.id] };
  } else if (target.kind === 'team') {
    if (state.school.includes(target.slug)) return null;
    patch = { school: [...state.school, target.slug] };
  } else if (target.kind === 'network') {
    if (state.networks && state.networks.length === 1 && state.networks[0] === target.id) {
      return null;
    }
    patch = { networks: [target.id] };
  } else if (target.kind === 'family') {
    const ids = target.ids ?? [];
    if (ids.length === 0) return null;
    const cur = state.networks;
    if (cur && cur.length === ids.length && ids.every((id) => cur.includes(id))) return null;
    patch = { networks: [...ids] };
  } else if (target.kind === 'conference') {
    if (!data.fbsConferences.includes(target.name)) return null;
    if (state.conferences.includes(target.name)) return null;
    patch = { conferences: [...state.conferences, target.name] };
  } else {
    return null;
  }
  const butterfly = state.view === 'butterfly';
  const before = chartContext(data, state);
  const after = chartContext(data, { ...state, ...patch });
  const choice = butterfly ? after.butterflyGroupChoice : after.groupChoice;
  if (choice) {
    const was = butterfly ? before.butterflyGroup : before.group;
    const wasBy = byFrom(was, byParts(state.by).mode);
    const keep = wasBy === 'announcer' ? null : wasBy;
    if (keep !== (state.by ?? null)) patch.by = keep;
  }
  return patch;
}
