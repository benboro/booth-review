/**
 * Selection semantics (D-10..D-19, replacing Phase 4's D-05): the season
 * range is the only filter that removes a dot; every other filter (Networks,
 * Kickoff, Conference, School, Bowls/Playoffs) fades a dot that fails it
 * into an inert state instead. Role still limits only how a person matches,
 * never which dots pass. Also covers person/compare-mode matching, the
 * matched-games fill rule (person-or-school, D-12), and the match summary.
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
 * as a fade filter (D-11).
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
  const t = data.t;
  if (state.networks != null) {
    const netId = data.lookups.networks[t.network[i]].id;
    if (!state.networks.includes(netId)) return false;
  }
  if (state.slots != null) {
    const slot = t.time_slot[i];
    if (slot == null || !state.slots.includes(slot)) return false;
  }
  if (state.conferences.length > 0) {
    const homeConf = t.home_conference[i];
    const awayConf = t.away_conference[i];
    const matches = [homeConf, awayConf].some(
      (idx) => idx != null && state.conferences.includes(data.lookups.conferences[idx].name),
    );
    if (!matches) return false;
  }
  if (state.school.length > 0) {
    const awaySlug = data.teamSlugs[t.away_team[i]];
    const homeSlug = data.teamSlugs[t.home_team[i]];
    if (!state.school.includes(awaySlug) && !state.school.includes(homeSlug)) return false;
  }
  if (state.postseason === 'exclude' && t.game_type[i] !== 'regular') return false;
  if (state.postseason === 'only' && t.game_type[i] === 'regular') return false;
  return true;
}

/** Per-season counts under every fade filter, season range ignored (D-13). */
function computeSeasonCounts(data, state) {
  return data.seasons.map((season) => {
    let count = 0;
    for (let i = 0; i < data.n; i += 1) {
      if (data.t.season[i] !== season) continue;
      if (passesFadeFilters(data, state, i)) count += 1;
    }
    return [season, count];
  });
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
    const networkNames = new Set(
      matched.map((i) => data.lookups.networks[data.t.network[i]].name),
    );
    return {
      kind: 'matches',
      count: matched.length,
      seasonMin: Math.min(...seasonsOfMatched),
      seasonMax: Math.max(...seasonsOfMatched),
      networks: Array.from(networkNames).sort((a, b) => a.localeCompare(b)),
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

  const seasonCounts = computeSeasonCounts(data, state);

  const personIndexes = state.people.map((id) => data.personIndexById.get(id));
  const hasPersonSelection = state.people.length > 0;
  const hasSelection = hasPersonSelection || state.school.length > 0;

  const peopleOnGame = new Map();
  const altGames = new Set();
  const highlighted = [];

  for (let i = 0; i < n; i += 1) {
    const results = personIndexes.map((pIdx) => personOnGame(data, i, pIdx, state.role));

    let personMatch = true;
    if (hasPersonSelection) {
      personMatch = state.together
        ? results.every((r) => r != null)
        : results.some((r) => r != null);
    }

    // D-14: a person-matched dot that fails a fade filter is filtered out,
    // not highlighted -- the filter always wins.
    if (hasPersonSelection && passesFilters[i] && personMatch) {
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
    summary,
  };
}
