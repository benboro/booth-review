/**
 * College football data adapter for the This weekend tab (Phase 18, plan 08). Turns the three
 * game blocks (rated and unrated telecasts, merged by `prepareData`, and the scheduled block
 * that never joins them) into the `WeekendGame` list `weekend.js` lays out, and runs the
 * master-filter picks over those games with the same predicates every other tab uses.
 *
 * The scheduled block stays out of `data.t` on purpose (Pitfall 10): Scatter, Bars, Butterfly,
 * Map, Crews and Special count only played or listed telecasts. `scheduledFacade` gives
 * `select.js` and the detail panel a data-shaped object over the scheduled columns instead.
 *
 * DOM-free: no document, no markup. Nothing here reads the clock.
 */

import { BOOTH_TIER_CODE } from './data.js';
import { familyKey } from './palette.js';
import { defaultState, passesFadeFilters, personOnGame } from './select.js';
import { crewIndex } from './crew-groups.js';
import { kickoffMinutes, weekendPickState } from './weekend.js';

// Shared with the NFL host, so it lives with the clock rules in weekend.js.
export { isUnplayedGame } from './weekend.js';

/** The synthetic network a null network points at in the facade (client-side only). */
export const TBA_NETWORK = Object.freeze({ id: 'tba', name: 'Network TBA', family: 'other' });

/**
 * The label of the week whose Monday-to-Sunday window holds an ET date.
 * @param {{label: string, start: string, end: string}[]} weeks
 * @param {string} isoDate
 * @returns {string|null}
 */
export function weekOfDate(weeks, isoDate) {
  if (isoDate == null) return null;
  const hit = (weeks ?? []).find((w) => w.start <= isoDate && isoDate <= w.end);
  return hit ? hit.label : null;
}

const facadeCache = new WeakMap();

/** The main-feed person index in `role` of a shipped crew list, or null. */
function mainPerson(crew, role) {
  const hit = (crew ?? []).find((e) => e.feed === 'main' && e.role === role);
  return hit ? hit.person : null;
}

/**
 * The index in `lookups.booths` of the cited booth a scheduled row's ESPN Press Room crew is
 * (same family and season, same play-by-play and analyst), or null. The builder tiers only
 * shipped telecasts; a scheduled game with the network's A booth still earns its star and a
 * Booth pick this way (18-REVIEW IN-02).
 */
function scheduledBoothIndex(booths, networks, raw, j) {
  const netIdx = raw.network?.[j];
  const family = netIdx != null ? (networks[netIdx]?.family ?? null) : null;
  if (family == null) return null;
  const pbp = mainPerson(raw.crew?.[j], 'pbp');
  const analyst = mainPerson(raw.crew?.[j], 'analyst');
  if (pbp == null || analyst == null) return null;
  const season = raw.season[j];
  const b = booths.findIndex((bo) => bo.family === family && bo.season === season
    && bo.pbp === pbp && bo.analyst === analyst);
  return b >= 0 ? b : null;
}

/**
 * A `prepareData`-shaped object over the scheduled block, so `passesFadeFilters`, `personOnGame`
 * and `renderPanel` read it with the same column names. Scheduled games have no score, figure or
 * excitement; their only crew is an ESPN Press Room booth with its page credit (18-13 F7), else
 * none, and that crew takes the tier of the cited booth it matches (IN-02). A null network
 * points at a synthetic Network TBA entry. Cached per prepared data object.
 * @param {object} data - a `prepareData` result.
 * @returns {object}
 */
export function scheduledFacade(data) {
  const hit = facadeCache.get(data);
  if (hit) return hit;
  const raw = data.scheduledRaw ?? { season: [] };
  const n = raw.season.length;
  const tbaIdx = data.lookups.networks.length;
  const lookups = { ...data.lookups, networks: [...data.lookups.networks, TBA_NETWORK] };
  const nulls = () => new Array(n).fill(null);
  const booths = lookups.booths ?? [];
  const booth = Array.from({ length: n }, (_, j) => scheduledBoothIndex(booths, data.lookups.networks, raw, j));
  const boothOf = new Int32Array(n).fill(-1);
  const boothTier = new Uint8Array(n);
  const boothIsConfLead = new Uint8Array(n);
  for (let j = 0; j < n; j += 1) {
    const b = booth[j];
    if (b == null) continue;
    boothOf[j] = b;
    boothTier[j] = BOOTH_TIER_CODE[booths[b].tier] ?? 0;
    boothIsConfLead[j] = booths[b].lead_network != null ? 1 : 0;
  }
  const t = {
    ...raw,
    network: (raw.network ?? nulls()).map((v) => v ?? tbaIdx),
    outlets: raw.outlets ?? Array.from({ length: n }, () => []),
    place: raw.place ?? nulls(),
    away_points: nulls(),
    home_points: nulls(),
    excitement: nulls(),
    viewers: nulls(),
    home_spread: nulls(),
    spread: nulls(),
    measurement_type: nulls(),
    combined_feeds: nulls(),
    figure_source: nulls(),
    publisher: nulls(),
    crew_source_url: raw.crew_source_url ?? nulls(),
    crew_source_label: raw.crew_source_label ?? nulls(),
    s506_url: nulls(),
    playoff_round: nulls(),
    bowl: nulls(),
    rivalry: nulls(),
    // A scheduled game is a current-season game with no figure yet, so a panel opened after
    // kickoff reads "viewership not posted yet" (18-13 F3).
    cause: new Array(n).fill('pending'),
    booth,
    game_type: new Array(n).fill('regular'),
    crew: raw.crew ?? Array.from({ length: n }, () => []),
    flags: Array.from({ length: n }, () => []),
    rr_urls: Array.from({ length: n }, () => []),
  };
  const facade = {
    scheduled: true,
    n,
    nRated: 0,
    rated: new Uint8Array(n),
    t,
    lookups,
    booths: lookups.booths,
    boothOf,
    boothTier,
    boothIsConfLead,
    teamSlugs: data.teamSlugs,
    teamIndexBySlug: data.teamIndexBySlug,
    personIndexById: data.personIndexById,
    gameIndexBySlug: data.gameIndexBySlug,
    dotGames: Array.from({ length: n }, () => []),
  };
  facadeCache.set(data, facade);
  return facade;
}

/** First main-feed person name in `role` on game `i` of a data-shaped object, or null. */
function mainName(obj, i, role) {
  for (const e of obj.t.crew[i]) {
    if (e.feed === 'main' && e.role === role) return obj.lookups.people[e.person].name;
  }
  return null;
}

function weekendGame(data, obj, block, i, week, weekend) {
  const t = obj.t;
  const netIdx = t.network[i];
  const net = netIdx != null ? obj.lookups.networks[netIdx] : null;
  const isTba = net == null || net.id === TBA_NETWORK.id;
  const pbp = mainName(obj, i, 'pbp');
  const analyst = mainName(obj, i, 'analyst');
  const tier = obj.boothTier[i];
  const past = weekend != null && week.number < weekend.number;
  const scored = Boolean(obj.rated[i]) || t.home_points[i] != null || t.away_points[i] != null;
  const placeIdx = t.place?.[i] ?? null;
  return {
    key: `cfb:${block}:${i}`,
    sport: 'cfb',
    block,
    index: i,
    date: t.date[i],
    kickoffMin: kickoffMinutes(t.kickoff[i]),
    networkId: isTba ? null : net.id,
    networkName: isTba ? null : net.name,
    family: isTba ? 'other' : familyKey(net.family),
    away: obj.lookups.teams[t.away_team[i]].name,
    home: obj.lookups.teams[t.home_team[i]].name,
    awayRank: t.away_rank[i],
    homeRank: t.home_rank[i],
    neutral: Boolean(t.neutral[i]),
    pbp,
    analyst,
    boothRank: tier === 1 ? 1 : tier === 2 ? 2 : null,
    lead: tier === 1,
    crewKnown: pbp != null || analyst != null,
    past,
    scored,
    placeIdx,
    venue: placeIdx == null ? null : (obj.lookups.venues?.[placeIdx] ?? null),
  };
}

/**
 * Every game of one week as `WeekendGame` objects, once each: main-feed rated and unrated
 * telecasts of the week (block `'t'`, index into `data.t`), then the scheduled rows (block
 * `'scheduled'`, index into the scheduled block). A row belongs to the week its shipped `week`
 * label names, so a Labor Day Monday game stays in its CFBD week (18-13 F1); a row with a null
 * label (another season, a postseason game, a file without the column) falls back to the
 * week's Monday-to-Sunday dates. A scheduled row's only crew is an ESPN Press Room booth.
 * Empty for an unknown week label.
 * @param {object} data - a `prepareData` result.
 * @param {string} label - a `lookups.weeks` label.
 * @returns {object[]}
 */
export function cfbWeekendGames(data, label) {
  const week = (data.weeks ?? []).find((w) => w.label === label);
  if (!week) return [];
  const weekend = data.weekend ?? null;
  const out = [];
  const inWeek = (t, i) => {
    const own = t.week?.[i];
    if (own != null) return own === week.label;
    const d = t.date[i];
    return d != null && week.start <= d && d <= week.end;
  };
  for (let i = 0; i < data.n; i += 1) {
    if (inWeek(data.t, i)) out.push(weekendGame(data, data, 't', i, week, weekend));
  }
  const facade = scheduledFacade(data);
  for (let j = 0; j < facade.n; j += 1) {
    if (inWeek(facade.t, j)) out.push(weekendGame(data, facade, 'scheduled', j, week, weekend));
  }
  return out;
}

/** The person-match rule of `select.js` (union, or intersection when called together). */
function personMatch(obj, pick, personIndexes, i) {
  const test = (p) => personOnGame(obj, i, p, pick.role) != null;
  return pick.together ? personIndexes.every(test) : personIndexes.some(test);
}

/**
 * Whether the pick reduces the week to a person or crew selection (the cells that match ring).
 * @param {object} state
 * @returns {boolean}
 */
export function hasPersonPick(state) {
  return (state.people ?? []).length > 0 || state.crew != null;
}

/**
 * Whether a weekend game passes the master filter: the existing fade predicate (Networks,
 * Conference, School, Booth, Head-to-head) plus the Announcers, Role, Compare and Called
 * together person rule, on the scheduled facade for scheduled rows. Seasons, Kickoff slots,
 * Bowls/Playoffs and Game are ignored (D-20, D-21). A crew pick keeps only that crew's games.
 * @param {object} data - a `prepareData` result.
 * @param {object} state - shaped like `defaultState(data)`.
 * @param {object} game - from `cfbWeekendGames`.
 * @returns {boolean}
 */
export function cfbWeekendPasses(data, state, game) {
  const pick = weekendPickState(state, defaultState(data));
  const scheduled = game.block === 'scheduled';
  const obj = scheduled ? scheduledFacade(data) : data;
  const i = game.index;
  // This weekend shows unplayed games, so the fade predicate is asked with `unplayedOk`.
  if (!passesFadeFilters(obj, pick, i, { unplayedOk: true })) return false;
  const personIndexes = (pick.people ?? []).map((id) => data.personIndexById.get(id));
  if (personIndexes.length > 0 && !personMatch(obj, pick, personIndexes, i)) return false;
  if (pick.crew != null && (scheduled || crewIndex(data).keys[i] !== pick.crew)) return false;
  return true;
}

/**
 * Whether a weekend game passes AND matches an active person or crew pick (the ring state);
 * false when no such pick is active.
 * @param {object} data
 * @param {object} state
 * @param {object} game
 * @returns {boolean}
 */
export function cfbWeekendMatches(data, state, game) {
  return hasPersonPick(state) && cfbWeekendPasses(data, state, game);
}

