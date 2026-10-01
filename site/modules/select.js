/**
 * Selection semantics (D-10..D-19, replacing Phase 4's D-05): the season
 * range is the only filter that removes a dot; every other filter (Networks,
 * Kickoff, Conference, School, Bowls/Playoffs) fades a dot that fails it
 * into an inert state instead. Role still limits only how a person matches,
 * never which dots pass. Also covers person/compare-mode matching, the
 * matched-games fill rule (person-or-school, D-12), and the match summary.
 * Also computes faceted option counts (D-08..D-12, `computeFacets`): each
 * facet counts rated telecasts passing every active constraint except its
 * own. Facets are pure counts and never change which dots are drawn or faded.
 * DOM-free; imports only from ./palette.js.
 */

import { COMPARE_SYMBOLS, SHARED_SYMBOL } from './palette.js';

/** Maximum number of people that can be selected in compare mode (D-07). */
export const MAX_COMPARE = 4;

/**
 * The default selection/filter state (D-12, D-13): all dots, nobody
 * selected, pre-game axis. `seasons`/`networks`/`slots` of `null` mean
 * "unfiltered"; `conferences`/`school` of `[]` mean "unfiltered" (D-10,
 * D-11); `postseason` of `'all'` means "unfiltered" (D-18). There is no
 * `team` field -- School (`state.school`) replaces the old team highlight
 * as a fade filter (D-11). `view` is the chart tab (`'scatter'`/`'bars'`/
 * `'butterfly'`), `bars` the bar style (`'simple'`/`'stacked'`), and `group`
 * the Group-by preference (`'teams'`, or null for the default Announcers)
 * (D-13).
 * @param {object} _data - a `prepareData` result (unused, kept for a
 *   uniform call signature with functions that do need it).
 * @returns {object}
 */
export function defaultState(_data) {
  return {
    people: [],
    compare: false,
    together: false,
    role: null,
    seasons: null,
    networks: null,
    slots: null,
    conferences: [],
    school: [],
    postseason: 'all',
    axis: 'pregame',
    view: 'scatter',
    bars: 'simple',
    group: null,
  };
}

/**
 * Determines whether a person matches a telecast's crew (D-08/D-18): a
 * main-feed entry matches when the role filter is unset or matches, an
 * alt-feed entry matches only when the dot is a combined-feed figure and no
 * role filter is set, and a spanish-feed entry never matches.
 * @param {object} data - a `prepareData` result.
 * @param {number} i - telecast index.
 * @param {number} personIndex
 * @param {"pbp"|"analyst"|null} role
 * @returns {"main"|"alt"|null}
 */
export function personOnGame(data, i, personIndex, role) {
  let mainMatch = false;
  let altMatch = false;
  for (const entry of data.t.crew[i]) {
    if (entry.person !== personIndex) continue;
    if (entry.feed === 'main') {
      if (role == null || entry.role === role) mainMatch = true;
    } else if (entry.feed === 'alt') {
      if (data.t.combined_feeds[i] !== null && role == null) altMatch = true;
    }
    // feed === 'spanish' never matches (D-08/D-18): the Spanish-feed
    // audience isn't the selected person's own figure in v1.
  }
  if (mainMatch) return 'main';
  if (altMatch) return 'alt';
  return null;
}

/** Computes visibility for every dot from the season range, the only filter that removes a dot (D-13). */
function computeVisible(data, state) {
  const { n } = data;
  const visible = new Uint8Array(n);
  for (let i = 0; i < n; i += 1) {
    if (state.seasons != null) {
      const season = data.t.season[i];
      if (season < state.seasons[0] || season > state.seasons[1]) continue;
    }
    visible[i] = 1;
  }
  return visible;
}

/** True when Networks excludes dot `i`. */
function failsNetworks(data, state, i) {
  if (state.networks == null) return false;
  const netId = data.lookups.networks[data.t.network[i]].id;
  return !state.networks.includes(netId);
}

/** True when Kickoff excludes dot `i` (a null slot fails any active Kickoff filter). */
function failsSlots(data, state, i) {
  if (state.slots == null) return false;
  const slot = data.t.time_slot[i];
  return slot == null || !state.slots.includes(slot);
}

/** True when Conference excludes dot `i` (neither team's conference selected). */
function failsConferences(data, state, i) {
  if (state.conferences.length === 0) return false;
  const t = data.t;
  const matches = [t.home_conference[i], t.away_conference[i]].some(
    (idx) => idx != null && state.conferences.includes(data.lookups.conferences[idx].name),
  );
  return !matches;
}

/** True when School excludes dot `i` (neither team selected). */
function failsSchool(data, state, i) {
  if (state.school.length === 0) return false;
  const t = data.t;
  const awaySlug = data.teamSlugs[t.away_team[i]];
  const homeSlug = data.teamSlugs[t.home_team[i]];
  return !state.school.includes(awaySlug) && !state.school.includes(homeSlug);
}

/** True when Bowls/Playoffs excludes dot `i`. */
function failsPostseason(data, state, i) {
  const gameType = data.t.game_type[i];
  if (state.postseason === 'exclude') return gameType !== 'regular';
  if (state.postseason === 'only') return gameType === 'regular';
  return false;
}

/**
 * Whether dot `i` passes every fade filter (D-13): Networks, Kickoff,
 * Conference, School, and Bowls/Playoffs. A dot that fails this stays
 * `visible` -- it renders as the inert filtered-out state (D-14), never
 * removed. Role is deliberately absent: it never fades a dot (D-13).
 * @param {object} data - a `prepareData` result.
 * @param {object} state - shaped like `defaultState(data)`.
 * @param {number} i - telecast index.
 * @returns {boolean}
 */
export function passesFadeFilters(data, state, i) {
  return !(
    failsNetworks(data, state, i) ||
    failsSlots(data, state, i) ||
    failsConferences(data, state, i) ||
    failsSchool(data, state, i) ||
    failsPostseason(data, state, i)
  );
}

/**
 * The one copy of the person-match rule (D-10): true when nobody is
 * selected, else the union (`some`) of per-person matches, or the
 * intersection (`every`) in called-together mode. Compare mode is a union.
 * @param {object} data - a `prepareData` result.
 * @param {object} state - shaped like `defaultState(data)`.
 * @param {number[]} personIndexes - lookup indexes of `state.people`.
 * @param {number} i - telecast index.
 * @param {"pbp"|"analyst"|null} role
 * @returns {boolean}
 */
function personMatches(data, state, personIndexes, i, role) {
  if (personIndexes.length === 0) return true;
  const test = (pIdx) => personOnGame(data, i, pIdx, role) != null;
  return state.together ? personIndexes.every(test) : personIndexes.some(test);
}

const BIT_SEASON = 1;
const BIT_NET = 2;
const BIT_SLOT = 4;
const BIT_CONF = 8;
const BIT_SCHOOL = 16;
const BIT_POST = 32;
const BIT_PERSON = 64;

/**
 * Faceted option counts (D-08..D-12): for every filter option, the number
 * of rated telecasts passing every active constraint except that facet's
 * own. One pass over the dots builds a per-dot fail bitmask; a dot counts
 * toward a facet iff its mask has no bit outside that facet's own. Role is
 * not a dot constraint; it only feeds the person match and the Role facet.
 * @param {object} data - a `prepareData` result.
 * @param {object} state - shaped like `defaultState(data)`.
 * @returns {object} `{ total, seasons, networks, slots, conferences,
 *   schools, postseason, role, people }`.
 */
export function computeFacets(data, state) {
  const { n, t } = data;
  const personIndexes = state.people.map((id) => data.personIndexById.get(id));
  const hasPeople = personIndexes.length > 0;

  const seasons = new Map(data.seasons.map((s) => [s, 0]));
  const networks = new Int32Array(data.lookups.networks.length);
  const slots = { noon: 0, afternoon: 0, prime: 0, late: 0 };
  const conferences = new Map();
  const schools = new Int32Array(data.lookups.teams.length);
  const postseason = { all: 0, exclude: 0, only: 0 };
  const role = { pbp: 0, analyst: 0 };
  const people = new Int32Array(data.lookups.people.length);
  let total = 0;

  for (let i = 0; i < n; i += 1) {
    let mask = 0;
    if (state.seasons != null) {
      const season = t.season[i];
      if (season < state.seasons[0] || season > state.seasons[1]) mask |= BIT_SEASON;
    }
    if (failsNetworks(data, state, i)) mask |= BIT_NET;
    if (failsSlots(data, state, i)) mask |= BIT_SLOT;
    if (failsConferences(data, state, i)) mask |= BIT_CONF;
    if (failsSchool(data, state, i)) mask |= BIT_SCHOOL;
    if (failsPostseason(data, state, i)) mask |= BIT_POST;
    if (hasPeople && !personMatches(data, state, personIndexes, i, state.role)) mask |= BIT_PERSON;

    if (mask === 0) total += 1;
    if ((mask & ~BIT_SEASON) === 0) seasons.set(t.season[i], (seasons.get(t.season[i]) ?? 0) + 1);
    if ((mask & ~BIT_NET) === 0) networks[t.network[i]] += 1;
    if ((mask & ~BIT_SLOT) === 0 && t.time_slot[i] != null) slots[t.time_slot[i]] += 1;
    if ((mask & ~BIT_CONF) === 0) {
      const names = new Set();
      for (const idx of [t.home_conference[i], t.away_conference[i]]) {
        if (idx != null) names.add(data.lookups.conferences[idx].name);
      }
      for (const name of names) conferences.set(name, (conferences.get(name) ?? 0) + 1);
    }
    if ((mask & ~BIT_SCHOOL) === 0) {
      schools[t.home_team[i]] += 1;
      if (t.away_team[i] !== t.home_team[i]) schools[t.away_team[i]] += 1;
    }
    if ((mask & ~BIT_POST) === 0) {
      postseason.all += 1;
      if (t.game_type[i] === 'regular') postseason.exclude += 1;
      else postseason.only += 1;
    }
    if ((mask & ~BIT_PERSON) === 0) {
      for (const r of ['pbp', 'analyst']) {
        if (hasPeople) {
          if (personMatches(data, state, personIndexes, i, r)) role[r] += 1;
        } else if (t.crew[i].some((e) => e.feed === 'main' && e.role === r)) {
          role[r] += 1;
        }
      }
      const seen = new Set();
      for (const entry of t.crew[i]) {
        if (seen.has(entry.person)) continue;
        seen.add(entry.person);
        if (personOnGame(data, i, entry.person, state.role) != null) people[entry.person] += 1;
      }
    }
  }

  return { total, seasons, networks, slots, conferences, schools, postseason, role, people };
}

/**
 * Whether the network filter excludes every one of `family`'s networks
 * (its legend chip reads as off).
 * @param {object} data - a `prepareData` result.
 * @param {object} state - shaped like `defaultState(data)`.
 * @param {string} family - a key in `FAMILY_ORDER`.
 * @returns {boolean}
 */
export function familyToggledOff(data, state, family) {
  if (state.networks == null) return false;
  const famIds = (data.networksByFamily.get(family) ?? []).map((idx) => data.lookups.networks[idx].id);
  return !famIds.some((id) => state.networks.includes(id));
}

/**
 * Computes the next `networks` value from toggling a legend chip's family
 * (D-16): reproduces the app's own legend-click handling exactly, so the
 * legend chip and the Networks filter checklist always agree. Starting
 * from "every network selected" (`state.networks == null`), toggling a
 * family off removes just that family's ids; toggling any family back on
 * when some (not all) families are off adds that family's ids back in.
 * @param {object} data - a `prepareData` result.
 * @param {object} state - shaped like `defaultState(data)`.
 * @param {string} family - a key in `FAMILY_ORDER`.
 * @returns {string[]} the next `state.networks` value.
 */
export function toggleFamilyNetworks(data, state, family) {
  const current = state.networks ?? data.primaryNetworks.map((idx) => data.lookups.networks[idx].id);
  const famIds = (data.networksByFamily.get(family) ?? []).map((idx) => data.lookups.networks[idx].id);
  const everyFamIdIncluded = famIds.every((id) => current.includes(id));
  return everyFamIdIncluded
    ? current.filter((id) => !famIds.includes(id))
    : Array.from(new Set([...current, ...famIds]));
}

/** Builds the match summary for the current selection and matched/highlighted set. */
function buildSummary(data, state, matched, altGames, personIndexes, hasSelection) {
  if (!hasSelection) return { kind: 'none' };

  if (matched.length > 0) {
    const seasonsOfMatched = matched.map((i) => data.t.season[i]);
    // A6: networks ordered by matched-telecast count (most first), ties alphabetical.
    const networkCounts = new Map();
    for (const i of matched) {
      const name = data.lookups.networks[data.t.network[i]].name;
      networkCounts.set(name, (networkCounts.get(name) ?? 0) + 1);
    }
    return {
      kind: 'matches',
      count: matched.length,
      seasonMin: Math.min(...seasonsOfMatched),
      seasonMax: Math.max(...seasonsOfMatched),
      networks: Array.from(networkCounts.keys()).sort(
        (a, b) => networkCounts.get(b) - networkCounts.get(a) || a.localeCompare(b),
      ),
      altCount: altGames.size,
    };
  }

  if (state.people.length === 1) {
    const games = data.gamesByPerson.get(personIndexes[0]) ?? [];
    if (games.length === 0) {
      return { kind: 'no-rated', name: data.lookups.people[personIndexes[0]].name };
    }
  }

  const names = state.people.map((id) => data.lookups.people[data.personIndexById.get(id)].name);
  const schoolNames = state.school.map(
    (slug) => data.lookups.teams[data.teamIndexBySlug.get(slug)].name,
  );
  const selectionLabel = [...names, ...schoolNames].join(' + ');
  return { kind: 'filtered-out', selectionLabel };
}

/**
 * Computes the full view for the current data and selection/filter state
 * (D-10..D-19): which dots are visible (season range only), which pass
 * every fade filter, which are person-matched, which rows fill the
 * matched-games table, their compare-mode symbols, per-season counts, and
 * the match summary.
 * @param {object} data - a `prepareData` result.
 * @param {object} state - shaped like `defaultState(data)`.
 * @returns {object}
 */
export function computeView(data, state) {
  const { n } = data;
  const visible = computeVisible(data, state);
  let visibleCount = 0;

  const passesFilters = new Uint8Array(n);
  let passingCount = 0;
  for (let i = 0; i < n; i += 1) {
    if (visible[i]) visibleCount += 1;
    if (visible[i] && passesFadeFilters(data, state, i)) {
      passesFilters[i] = 1;
      passingCount += 1;
    }
  }

  const facets = computeFacets(data, state);
  const seasonCounts = data.seasons.map((season) => [season, facets.seasons.get(season)]);

  const personIndexes = state.people.map((id) => data.personIndexById.get(id));
  const hasPersonSelection = state.people.length > 0;
  const hasSelection = hasPersonSelection || state.school.length > 0;

  const peopleOnGame = new Map();
  const altGames = new Set();
  const highlighted = [];

  for (let i = 0; i < n; i += 1) {
    // D-14: a person-matched dot that fails a fade filter is filtered out,
    // not highlighted -- the filter always wins.
    if (
      hasPersonSelection &&
      passesFilters[i] &&
      personMatches(data, state, personIndexes, i, state.role)
    ) {
      const results = personIndexes.map((pIdx) => personOnGame(data, i, pIdx, state.role));
      highlighted.push(i);
      const onGame = [];
      let hasAlt = false;
      personIndexes.forEach((pIdx, idx) => {
        const result = results[idx];
        if (result != null) {
          onGame.push(pIdx);
          if (result === 'alt') hasAlt = true;
        }
      });
      if (onGame.length > 0) peopleOnGame.set(i, onGame);
      if (hasAlt) altGames.add(i);
    }
  }

  // D-12: the matched-games table fills when a person is selected (its rows
  // are exactly `highlighted`) or, absent a person, when School is set (its
  // rows are every dot that passes the fade filters). Every other filter
  // alone never fills it (no-bulk rule).
  let matched;
  if (hasPersonSelection) {
    matched = highlighted;
  } else if (state.school.length > 0) {
    matched = [];
    for (let i = 0; i < n; i += 1) if (passesFilters[i]) matched.push(i);
  } else {
    matched = [];
  }

  const symbols = new Map();
  for (const i of highlighted) {
    if (!state.compare) {
      symbols.set(i, 'circle');
      continue;
    }
    const onGame = peopleOnGame.get(i);
    if (!onGame || onGame.length === 0) {
      symbols.set(i, 'circle');
    } else if (onGame.length >= 2) {
      symbols.set(i, SHARED_SYMBOL);
    } else {
      const position = state.people.findIndex(
        (id) => data.personIndexById.get(id) === onGame[0],
      );
      symbols.set(i, COMPARE_SYMBOLS[position] ?? 'circle');
    }
  }

  const summary = buildSummary(data, state, matched, altGames, personIndexes, hasSelection);

  return {
    visible,
    passesFilters,
    visibleCount,
    passingCount,
    hasPersonSelection,
    hasSelection,
    highlighted,
    matched,
    peopleOnGame,
    altGames,
    symbols,
    seasonCounts,
    facets,
    summary,
  };
}

/**
 * Channel ids of a family that have games under the other filters (count > 0),
 * in lookup order (04.2 D-24); the family drill-in reuses it (04.4 D-23).
 * @param {object} data - a `prepareData` result.
 * @param {string} familyKeyVal - a `familyKey` value.
 * @param {object} [view] - a `computeView` result; all channels when missing.
 * @returns {string[]}
 */
export function offeredFamilyIds(data, familyKeyVal, view) {
  const counts = view?.facets?.networks;
  return (data.networksByFamily.get(familyKeyVal) ?? [])
    .filter((idx) => (counts ? counts[idx] > 0 : true))
    .map((idx) => data.lookups.networks[idx].id);
}
