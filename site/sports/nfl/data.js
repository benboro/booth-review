/**
 * NFL data preparation (D-01, D-03, D-22, D-23, D-24). DOM-free.
 *
 * prepareNfl(raw) turns nfl-data.json into a model; gameRow(model, i) yields
 * the shared GameRow shape. Missing values stay null, never 0.
 */

/** Category codes in model.category (D-24 precedence). */
export const CATEGORY_CODES = Object.freeze({
  solo_thursday: 0,
  solo_sunday: 1,
  solo_monday: 2,
  solo_holiday: 3,
  solo_other: 4,
  agotw: 5,
  cbs_national: 6,
  international_other: 7,
  none: 8,
});

const HOLIDAY_SLOTS = new Set(['Thanksgiving', 'Christmas', 'Black Friday']);

function soloCode(slot) {
  if (slot === 'TNF') return CATEGORY_CODES.solo_thursday;
  if (slot === 'SNF') return CATEGORY_CODES.solo_sunday;
  if (slot === 'MNF') return CATEGORY_CODES.solo_monday;
  if (HOLIDAY_SLOTS.has(slot)) return CATEGORY_CODES.solo_holiday;
  return CATEGORY_CODES.solo_other;
}

const REQUIRED_BLOCKS = [
  'games', 'lookups', 'special', 'season_weeks', 'booths',
  'viewership', 'freshness', 'constants',
];
const REQUIRED_LOOKUPS = [
  'franchises', 'team_names', 'networks', 'people', 'eras', 'slots',
  'network_groups', 'view_categories',
];

/** Columnar block -> array of row objects keyed by column name. */
function rowsOf(block) {
  const keys = Object.keys(block);
  const n = keys.length ? block[keys[0]].length : 0;
  const rows = new Array(n);
  for (let r = 0; r < n; r++) {
    const row = {};
    for (const k of keys) row[k] = block[k][r];
    rows[r] = row;
  }
  return rows;
}

/**
 * @param {object} raw parsed nfl-data.json
 * @returns {object} model
 */
export function prepareNfl(raw) {
  if (!raw || typeof raw !== 'object') throw new Error('NFL data is not available');
  for (const b of REQUIRED_BLOCKS) {
    if (!raw[b] || typeof raw[b] !== 'object') throw new Error('NFL data is incomplete');
  }
  for (const l of REQUIRED_LOOKUPS) {
    if (!Array.isArray(raw.lookups[l])) throw new Error('NFL data is incomplete');
  }
  const cols = raw.games;
  const n = Array.isArray(cols.season) ? cols.season.length : 0;
  const {
    franchises, team_names: teamNames, networks, people, eras, slots,
    network_groups: networkGroups, view_categories: viewCategories,
  } = raw.lookups;

  let minSeason = Infinity;
  let maxSeason = -Infinity;
  const category = new Uint8Array(n);
  const personGames = new Map();
  const franchiseGames = new Map();
  for (let i = 0; i < n; i++) {
    const s = cols.season[i];
    if (s < minSeason) minSeason = s;
    if (s > maxSeason) maxSeason = s;
    if (cols.standalone[i]) category[i] = soloCode(slots[cols.slot[i]]);
    else if (cols.agotw[i]) category[i] = CATEGORY_CODES.agotw;
    else if (cols.cbs_national[i]) category[i] = CATEGORY_CODES.cbs_national;
    else if (cols.international[i]) category[i] = CATEGORY_CODES.international_other;
    else category[i] = CATEGORY_CODES.none;
    for (const f of [cols.home[i], cols.away[i]]) {
      if (!franchiseGames.has(f)) franchiseGames.set(f, []);
      franchiseGames.get(f).push(i);
    }
    const seen = new Set();
    for (const c of cols.crew[i] || []) {
      if (seen.has(c.person)) continue;
      seen.add(c.person);
      if (!personGames.has(c.person)) personGames.set(c.person, []);
      personGames.get(c.person).push(i);
    }
  }

  const seasonWeeks = new Map();
  for (const r of rowsOf(raw.season_weeks)) seasonWeeks.set(r.season, r);

  const booths = rowsOf(raw.booths)
    .map((r) => ({ ...r, gameList: r.game_list }))
    .sort((a, b) => a.season - b.season || a.network_group - b.network_group || a.rank - b.rank);
  const viewership = rowsOf(raw.viewership)
    .map((r) => ({ ...r, gameList: r.game_list }))
    .sort((a, b) => a.category - b.category || a.season - b.season);

  const groupOfNetwork = new Map();
  networkGroups.forEach((g, gi) => {
    for (const m of g.members || []) groupOfNetwork.set(m, gi);
  });
  // Booth catalog: one entry per (group, pbp person) with games, analyst from the latest season.
  const boothIndex = new Map();
  const latest = new Map();
  for (const r of booths) {
    if (!(r.games > 0) || r.pbp_person == null) continue;
    const key = `${networkGroups[r.network_group].id}:${people[r.pbp_person].id}`;
    let e = boothIndex.get(key);
    if (!e) {
      e = { key, group: r.network_group, person: r.pbp_person, analyst: null, label: '', categories: new Set() };
      boothIndex.set(key, e);
    }
    if (!latest.has(key) || r.season >= latest.get(key)) {
      latest.set(key, r.season);
      e.analyst = r.analyst_person ?? null;
    }
  }
  for (const e of boothIndex.values()) {
    const pbp = people[e.person].name;
    e.label = e.analyst == null ? pbp : `${pbp} / ${people[e.analyst].name}`;
  }
  for (const v of viewership) {
    for (const g of v.gameList || []) {
      const grp = groupOfNetwork.get(cols.network[g]);
      if (grp === undefined) continue;
      for (const c of cols.crew[g] || []) {
        if (c.role !== 'pbp') continue;
        const e = boothIndex.get(`${networkGroups[grp].id}:${people[c.person].id}`);
        if (e) e.categories.add(v.category);
      }
    }
  }
  const boothCatalog = [...boothIndex.values()].sort((a, b) =>
    a.group - b.group || (a.label < b.label ? -1 : a.label > b.label ? 1 : 0));

  const franchiseIndex = new Map(franchises.map((f, k) => [f.id, k]));
  const personIndex = new Map(people.map((p, k) => [p.id, k]));

  return {
    n,
    cols,
    franchises,
    teamNames,
    networks,
    people,
    eras,
    slots,
    freshness: raw.freshness,
    constants: raw.constants,
    seasons: n ? [minSeason, maxSeason] : [0, 0],
    special: rowsOf(raw.special),
    seasonWeeks,
    networkGroups,
    groupOfNetwork,
    viewCategories,
    booths,
    viewership,
    boothCatalog,
    boothIndex,
    personGames,
    franchiseGames,
    franchiseIndex,
    personIndex,
    category,
    // Phase 18: the This weekend tab's unplayed games. They never join `cols`, so every other NFL
    // view keeps its counts; `weekend-data.js` reads them. A file from before 2.1.0 reads as null.
    upcomingRaw: raw.upcoming ?? null,
    weekend: raw.freshness?.weekend ?? null,
  };
}

/**
 * The shared GameRow for game `i`.
 * @param {object} model
 * @param {number} i
 */
export function gameRow(model, i) {
  const c = model.cols;
  const name = (idx) => (idx == null ? null : model.networks[idx].name);
  const hasViewers = c.viewers[i] != null;
  const grp = c.network[i] == null ? null : model.groupOfNetwork.get(c.network[i]) ?? null;
  return {
    i,
    season: c.season[i],
    week: c.week[i],
    date: c.date[i],
    kickoff: c.kickoff[i] ?? null,
    away: model.teamNames[c.away_name[i]].name,
    home: model.teamNames[c.home_name[i]].name,
    awayShort: model.teamNames[c.away_name[i]].short,
    homeShort: model.teamNames[c.home_name[i]].short,
    awayPoints: c.away_points[i] ?? null,
    homePoints: c.home_points[i] ?? null,
    slot: model.slots[c.slot[i]],
    standalone: !!c.standalone[i],
    agotw: !!c.agotw[i],
    cbsNational: !!c.cbs_national[i],
    international: !!c.international[i],
    flexed: !!c.flexed[i],
    originalSlot: c.original_slot[i] == null ? null : model.slots[c.original_slot[i]],
    originalNetwork: name(c.original_network[i]),
    changeUrl: c.change_url[i] ?? null,
    network: name(c.network[i]),
    networkFamily: c.network[i] == null ? null : model.networks[c.network[i]].family ?? null,
    networkId: c.network[i] == null ? null : model.networks[c.network[i]].id ?? null,
    networkGroup: grp == null ? null : model.networkGroups[grp].name,
    crewSource: c.crew_source[i] ?? null,
    crewSourceUrl: c.crew_source_url[i] ?? null,
    crew: (c.crew[i] || []).map((m) => ({ name: model.people[m.person].name, role: m.role, person: m.person })),
    viewers: c.viewers[i] ?? null,
    scope: hasViewers ? c.scope[i] ?? null : null,
    cause: hasViewers ? null : c.cause[i] ?? null,
    era: hasViewers && c.era[i] != null ? model.eras[c.era[i]].label : null,
    excitement: c.excitement[i] ?? null,
    rrUrl: c.rr_url[i] ?? null,
    sourceUrl: c.source_url[i] ?? null,
  };
}
