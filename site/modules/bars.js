/**
 * Bars and Butterfly counting core (SITE-33..36, D-01..D-18). DOM-free;
 * imports only from ./select.js. Every value is a count of rated telecasts
 * (D-01): this module never reads `viewers` and no model carries one.
 *
 * Games counted are exactly those passing every filter, narrowed to the
 * person-matched games when someone is selected (D-02). Crew matching goes
 * only through select.js's `personOnGame`. Rows sort by count descending,
 * ties by bare name (D-03); announcer rows share one list labeled
 * `Name · PBP`/`Analyst`/`PBP/Analyst` (D-04). The butterfly (D-05..D-09)
 * mirrors the Bars rows for exactly two schools or two announcers.
 * `chartContext` decides which tabs apply and the Group-by (D-07, D-11) and
 * `drillPatch` builds the setState patch for a row/segment click (D-18).
 */

import { MAX_COMPARE, personOnGame } from './select.js';

/** Rows shown before "show all" (D-03). */
export const TOP_N = 15;

/** Row key for games whose conference is unknown (D-15). */
export const NO_CONFERENCE_KEY = 'c:__none__';

/** Role tags appended to announcer labels (D-04). */
export const ROLE_TAGS = { pbp: 'PBP', analyst: 'Analyst', unknown: 'Other' };

const ROLE_ORDER = ['pbp', 'analyst', 'unknown'];

/**
 * Which bar tabs apply, and the Group-by choice (D-07, D-11, D-13).
 * `state.group` keeps the raw preference; the resolved value is returned.
 * @param {object} _data - a `prepareData` result (unused).
 * @param {object} state
 * @returns {object}
 */
export function chartContext(_data, state) {
  const announcersApply = state.school.length > 0;
  const teamsApply = state.networks !== null || state.people.length > 0;
  const preferTeams = state.group === 'teams';
  const groupChoice = announcersApply && teamsApply;
  let group = 'teams';
  if (groupChoice) group = preferTeams ? 'teams' : 'announcers';
  else if (announcersApply) group = 'announcers';

  const twoSchools = state.school.length === 2;
  const twoPeople = state.people.length === 2;
  const butterflyGroupChoice = twoSchools && twoPeople;
  let butterflyGroup = 'teams';
  if (butterflyGroupChoice) butterflyGroup = preferTeams ? 'teams' : 'announcers';
  else if (twoSchools) butterflyGroup = 'announcers';

  return {
    barsEnabled: announcersApply || teamsApply,
    groupChoice,
    group,
    butterflyEnabled: twoSchools || twoPeople,
    butterflyGroupChoice,
    butterflyGroup,
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
 * Announcer row label (D-04): `Name · PBP`, `Name · PBP/Analyst`, ...
 * @param {string} name
 * @param {string[]} roles - roles present, any order.
 * @returns {string}
 */
export function announcerLabel(name, roles) {
  const tags = ROLE_ORDER.filter((r) => roles.includes(r)).map((r) => ROLE_TAGS[r]);
  return tags.length > 0 ? `${name} · ${tags.join('/')}` : name;
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

/** Counts announcers over `games` (the computeFacets per-person `seen` rule). Returns segments. */
function countAnnouncers(data, games, role) {
  const acc = new Map();
  for (const i of games) {
    const seen = new Set();
    for (const entry of data.t.crew[i]) {
      if (seen.has(entry.person)) continue;
      seen.add(entry.person);
      if (personOnGame(data, i, entry.person, role) == null) continue;
      let rec = acc.get(entry.person);
      if (!rec) {
        rec = { count: 0, main: new Set(), alt: new Set() };
        acc.set(entry.person, rec);
      }
      rec.count += 1;
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
    segments.push({
      key: `p:${id}`,
      name,
      label: announcerLabel(name, roles),
      count: rec.count,
      target: { kind: 'person', id },
    });
  }
  return segments.sort(byCount((s) => s.count));
}

/** Counts schools over `games` (each side once; a team playing itself counts once). */
function countTeams(data, games) {
  const acc = new Map();
  const bump = (idx) => acc.set(idx, (acc.get(idx) ?? 0) + 1);
  for (const i of games) {
    bump(data.t.home_team[i]);
    if (data.t.away_team[i] !== data.t.home_team[i]) bump(data.t.away_team[i]);
  }
  const segments = [];
  for (const [idx, count] of acc) {
    const name = data.lookups.teams[idx].name;
    segments.push({
      key: `t:${data.teamSlugs[idx]}`,
      name,
      label: name,
      count,
      target: { kind: 'team', slug: data.teamSlugs[idx] },
    });
  }
  return segments.sort(byCount((s) => s.count));
}

/** Simple announcer rows: one row per announcer. */
function announcerRows(data, games, role) {
  return countAnnouncers(data, games, role).map((s) => ({
    key: s.key,
    name: s.name,
    label: s.label,
    family: null,
    total: s.count,
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
    family: null,
    total: s.count,
    target: s.target,
    segments: [],
  }));
}

/** Stacked announcer rows: networks, each stacked by announcer (D-15). */
function networkRows(data, games, role) {
  const byNetwork = new Map();
  for (const i of games) {
    const net = data.t.network[i];
    if (!byNetwork.has(net)) byNetwork.set(net, []);
    byNetwork.get(net).push(i);
  }
  const rows = [];
  for (const [net, list] of byNetwork) {
    const segments = countAnnouncers(data, list, role);
    const total = segments.reduce((sum, s) => sum + s.count, 0);
    if (total === 0) continue;
    const { id, name, family } = data.lookups.networks[net];
    rows.push({
      key: `n:${id}`,
      name,
      label: name,
      family,
      total,
      target: { kind: 'network', id },
      segments,
    });
  }
  return rows.sort(byCount((r) => r.total));
}

/** Stacked team rows: per-game era-correct conferences, each stacked by team (D-15). */
function conferenceRows(data, games) {
  const byConf = new Map();
  const add = (confIdx, teamIdx) => {
    const name = confIdx == null ? null : data.lookups.conferences[confIdx].name;
    const key = name == null ? NO_CONFERENCE_KEY : `c:${name}`;
    let rec = byConf.get(key);
    if (!rec) {
      rec = { name, teams: new Map() };
      byConf.set(key, rec);
    }
    rec.teams.set(teamIdx, (rec.teams.get(teamIdx) ?? 0) + 1);
  };
  for (const i of games) {
    add(data.t.home_conference[i], data.t.home_team[i]);
    if (data.t.away_team[i] !== data.t.home_team[i]) add(data.t.away_conference[i], data.t.away_team[i]);
  }
  const rows = [];
  for (const [key, rec] of byConf) {
    const segments = [];
    for (const [idx, count] of rec.teams) {
      const name = data.lookups.teams[idx].name;
      segments.push({
        key: `t:${data.teamSlugs[idx]}`,
        name,
        label: name,
        count,
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
      family: null,
      total: segments.reduce((sum, s) => sum + s.count, 0),
      target,
      segments,
    });
  }
  return rows.sort(byCount((r) => r.total));
}

/** Shape of the rows for a group/mode: `{ rowKind, segmentKind, build(games) }`. */
function rowSpec(data, group, mode, role) {
  if (group === 'announcers') {
    return mode === 'stacked'
      ? { rowKind: 'network', segmentKind: 'person', build: (g) => networkRows(data, g, role) }
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
  const spec = rowSpec(data, ctx.group, state.bars, state.role);
  return {
    kind: 'bars',
    group: ctx.group,
    mode: state.bars,
    rowKind: spec.rowKind,
    segmentKind: spec.segmentKind,
    rows: spec.build(gamesForBars(view)),
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
