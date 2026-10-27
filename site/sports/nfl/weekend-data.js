/**
 * NFL data adapter for the This weekend tab (Phase 18, plan 08). Turns the played `games` block
 * and the `upcoming` block into the `WeekendGame` list `modules/weekend.js` lays out, and runs
 * the NFL master-filter picks (Team, Announcers, Booths) over them with the same predicate
 * (`gamePasses`) every other NFL view uses. Seasons and Category are ignored on this view
 * (D-20, D-21).
 *
 * `upcoming` rows never enter `model.cols`, so no other NFL view changes its counts. DOM-free.
 */

import { familyKey } from '../../modules/palette.js';
import { weekendPickState } from '../../modules/weekend.js';
import { boothGames, defaultNflState, gamePasses } from './state.js';

function kickoffMinutes(iso) {
  if (iso == null) return null;
  const m = /T(\d{2}):(\d{2})/.exec(iso);
  return m ? Number(m[1]) * 60 + Number(m[2]) : null;
}

/**
 * The panel row (the shape `gameRow` returns) for upcoming row `j`: no score, figure or
 * excitement, plus `networkBasis` ('506' or 'slot'), `upcoming: true` and `unplayed`. The host
 * passes `unplayed: false` once the kickoff has passed in ET (the cell's own rule), and the row
 * then reads as a played game whose figure is not posted yet (18-13 F3, WR-01).
 * @param {object} model - a `prepareNfl` result.
 * @param {number} j - index into the upcoming block.
 * @param {{unplayed?: boolean}} [opts]
 * @returns {object}
 */
export function upcomingRow(model, j, { unplayed = true } = {}) {
  const u = model.upcomingRaw;
  const net = u.network[j] == null ? null : model.networks[u.network[j]];
  const slot = u.slot[j] == null ? null : model.slots[u.slot[j]];
  const away = model.teamNames[u.away_name[j]];
  const home = model.teamNames[u.home_name[j]];
  return {
    i: j,
    upcoming: true,
    unplayed,
    season: u.season[j],
    week: u.week[j],
    date: u.date[j],
    kickoff: u.kickoff[j] ?? null,
    away: away.name,
    home: home.name,
    awayShort: away.short,
    homeShort: home.short,
    awayPoints: null,
    homePoints: null,
    slot,
    standalone: false,
    agotw: false,
    cbsNational: false,
    international: Boolean(u.international[j]),
    flexed: false,
    originalSlot: null,
    originalNetwork: null,
    changeUrl: null,
    network: net ? net.name : null,
    networkFamily: net ? (net.family ?? null) : null,
    networkId: net ? (net.id ?? null) : null,
    networkGroup: null,
    networkBasis: u.network_basis?.[j] ?? null,
    crewSource: u.crew_source?.[j] ?? null,
    crewSourceUrl: u.crew_source_url?.[j] ?? null,
    crew: (u.crew[j] || []).map((m) => ({
      name: model.people[m.person].name,
      role: m.role,
      person: m.person,
    })),
    viewers: null,
    scope: null,
    cause: unplayed ? null : 'pending',
    era: null,
    excitement: null,
    rrUrl: null,
    sourceUrl: null,
  };
}

/** A Seasons range no game falls outside. */
const ALL_SEASONS = Object.freeze([-Infinity, Infinity]);

const upcomingFacades = new WeakMap();

/** A `gamePasses`-shaped model over the upcoming columns (Team is the only filter that reads it). */
function upcomingFacade(model) {
  const hit = upcomingFacades.get(model);
  if (hit) return hit;
  const u = model.upcomingRaw ?? { season: [], home: [], away: [], slot: [] };
  const n = u.season.length;
  const no = () => new Array(n).fill(false);
  const facade = {
    n,
    franchises: model.franchises,
    slots: model.slots,
    cols: {
      season: u.season,
      home: u.home,
      away: u.away,
      slot: u.slot.map((s) => s ?? 0),
      standalone: no(),
      agotw: no(),
      cbs_national: no(),
      international: u.international ?? no(),
      flexed: no(),
    },
  };
  upcomingFacades.set(model, facade);
  return facade;
}

const rankCaches = new WeakMap();

/** Booth rank per played game index, from the booth rows' game lists. */
function playedBoothRanks(model) {
  const hit = rankCaches.get(model);
  if (hit) return hit;
  const ranks = new Map();
  for (const row of model.booths) {
    for (const g of row.gameList || []) {
      if (!ranks.has(g) || row.rank < ranks.get(g)) ranks.set(g, row.rank);
    }
  }
  rankCaches.set(model, ranks);
  return ranks;
}

function crewNames(model, crew) {
  let pbp = null;
  let analyst = null;
  for (const m of crew || []) {
    const name = model.people[m.person].name;
    if (m.role === 'pbp' && pbp == null) pbp = name;
    else if (m.role === 'analyst' && analyst == null) analyst = name;
  }
  return { pbp, analyst };
}

function netFields(model, networkIdx) {
  const net = networkIdx == null ? null : model.networks[networkIdx];
  return {
    networkId: net ? (net.id ?? null) : null,
    networkName: net ? net.name : null,
    family: net ? familyKey(net.family) : 'other',
  };
}

/**
 * Every game of one week as `WeekendGame` objects, once each: the played games of the current
 * season in that week (block `'t'`, index into `model.cols`), then the upcoming rows of that
 * week (block `'upcoming'`, index into the upcoming block). The booth rank of a played game is
 * its booth row's rank; of an upcoming row, its `booth_rank`. `lead` is rank 1.
 * @param {object} model - a `prepareNfl` result.
 * @param {number} week
 * @returns {object[]}
 */
export function nflWeekendGames(model, week) {
  const season = model.upcomingRaw?.season?.[0] ?? model.freshness?.season ?? model.seasons[1];
  const currentWeek = model.weekend?.week ?? null;
  // No weekend stamp (the season is over, or the build has no schedule): only played weeks
  // show, so every week is past (18-13 F17).
  const past = model.weekend == null || (currentWeek != null && week < currentWeek);
  const c = model.cols;
  const out = [];
  const ranks = playedBoothRanks(model);
  for (let i = 0; i < model.n; i += 1) {
    if (c.season[i] !== season || c.week[i] !== week) continue;
    const { pbp, analyst } = crewNames(model, c.crew[i]);
    const rank = ranks.get(i) ?? null;
    out.push({
      key: `nfl:t:${i}`,
      placeIdx: c.place?.[i] ?? null,
      venue: model.venues?.[c.place?.[i]] ?? null,
      slotName: model.slots?.[c.slot?.[i]] ?? null,
      sport: 'nfl',
      block: 't',
      index: i,
      date: c.date[i],
      kickoffMin: kickoffMinutes(c.kickoff[i]),
      ...netFields(model, c.network[i]),
      away: model.teamNames[c.away_name[i]].name,
      home: model.teamNames[c.home_name[i]].name,
      awayRank: null,
      homeRank: null,
      neutral: Boolean(c.international[i]),
      pbp,
      analyst,
      boothRank: rank,
      lead: rank === 1,
      crewKnown: pbp != null || analyst != null,
      past,
    });
  }
  const u = model.upcomingRaw;
  for (let j = 0; u && j < u.season.length; j += 1) {
    if (u.season[j] !== season || u.week[j] !== week) continue;
    const { pbp, analyst } = crewNames(model, u.crew[j]);
    const rank = u.booth_rank?.[j] ?? null;
    out.push({
      key: `nfl:upcoming:${j}`,
      placeIdx: u.place?.[j] ?? null,
      venue: model.venues?.[u.place?.[j]] ?? null,
      slotName: model.slots?.[u.slot?.[j]] ?? null,
      sport: 'nfl',
      block: 'upcoming',
      index: j,
      date: u.date[j],
      kickoffMin: kickoffMinutes(u.kickoff[j]),
      ...netFields(model, u.network[j]),
      networkBasis: u.network_basis?.[j] ?? null,
      away: model.teamNames[u.away_name[j]].name,
      home: model.teamNames[u.home_name[j]].name,
      awayRank: null,
      homeRank: null,
      // One rule for both blocks: played games ship only `international` (18-13 F19).
      neutral: Boolean(u.international?.[j]),
      pbp,
      analyst,
      boothRank: rank,
      lead: rank === 1,
      crewKnown: pbp != null || analyst != null,
      past,
    });
  }
  return out;
}

/** The Booths-pick key of an upcoming row ("<group id>:<pbp person id>"), or null. */
function upcomingBoothKey(model, j) {
  const u = model.upcomingRaw;
  const grp = u.network[j] == null ? undefined : model.groupOfNetwork.get(u.network[j]);
  const pbp = (u.crew[j] || []).find((m) => m.role === 'pbp');
  if (grp === undefined || !pbp) return null;
  return `${model.networkGroups[grp].id}:${model.people[pbp.person].id}`;
}

/**
 * Whether the pick narrows to a person or booth (the cells that match ring).
 * @param {object} state
 * @returns {boolean}
 */
export function nflHasCrewPick(state) {
  return (state.people ?? []).length > 0 || (state.booths ?? []).length > 0;
}

/**
 * Whether a weekend game passes the NFL master filter: Team through `gamePasses` (played rows on
 * the model, upcoming rows on the upcoming facade), then an Announcers pick (any seat) and a
 * Booths pick. Seasons and Category are ignored (D-20, D-21).
 * @param {object} model - a `prepareNfl` result.
 * @param {object} state - shaped like `defaultNflState(model)`.
 * @param {object} game - from `nflWeekendGames`.
 * @returns {boolean}
 */
export function nflWeekendPasses(model, state, game) {
  // Seasons is ignored outright: its default spans the played seasons only, so before an
  // opener it would drop every upcoming game (18-13 F8).
  const pick = { ...weekendPickState(state, defaultNflState(model)), seasons: ALL_SEASONS };
  const upcoming = game.block === 'upcoming';
  const i = game.index;
  if (!gamePasses(upcoming ? upcomingFacade(model) : model, pick, i)) return false;
  const crew = (upcoming ? model.upcomingRaw.crew[i] : model.cols.crew[i]) || [];
  if ((pick.people ?? []).length > 0) {
    const idx = new Set(pick.people.map((id) => model.personIndex.get(id)));
    if (!crew.some((m) => idx.has(m.person))) return false;
  }
  if ((pick.booths ?? []).length > 0) {
    if (upcoming) {
      const key = upcomingBoothKey(model, i);
      if (key == null || !pick.booths.includes(key)) return false;
    } else if (!boothGames(model, pick.booths).includes(i)) {
      return false;
    }
  }
  return true;
}

/**
 * Whether a weekend game passes AND matches an active Announcers or Booths pick (the ring
 * state); false when no such pick is active.
 * @param {object} model
 * @param {object} state
 * @param {object} game
 * @returns {boolean}
 */
export function nflWeekendMatches(model, state, game) {
  return nflHasCrewPick(state) && nflWeekendPasses(model, state, game);
}
