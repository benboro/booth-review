/**
 * Selection semantics (D-05..D-08): hide filters, person/team highlighting,
 * OR/AND across selected people, compare-mode shapes, and the match
 * summary. DOM-free; imports only from ./palette.js.
 */

import { COMPARE_SYMBOLS, SHARED_SYMBOL } from './palette.js';

/** Maximum number of people that can be selected in compare mode (D-07). */
export const MAX_COMPARE = 4;

/**
 * The default selection/filter state (D-12): all dots, nobody selected,
 * pre-game axis. `seasons`/`networks`/`slots` of `null` mean "unfiltered".
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
    team: null,
    seasons: null,
    networks: null,
    slots: null,
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

/** Computes visibility for every dot from the season/network/slot hide filters (D-05). */
function computeVisible(data, state) {
  const { n } = data;
  const visible = new Uint8Array(n);
  for (let i = 0; i < n; i += 1) {
    visible[i] = dotPassesHideFilters(data, state, i) ? 1 : 0;
  }
  return visible;
}

/** Whether dot `i` passes the season/network/slot hide filters (D-05). */
function dotPassesHideFilters(data, state, i) {
  const { t } = data;
  if (state.seasons != null) {
    const season = t.season[i];
    if (season < state.seasons[0] || season > state.seasons[1]) return false;
  }
  if (state.networks != null) {
    const netId = data.lookups.networks[t.network[i]].id;
    if (!state.networks.includes(netId)) return false;
  }
  if (state.slots != null) {
    const slot = t.time_slot[i];
    if (slot == null || !state.slots.includes(slot)) return false;
  }
  return true;
}

/** Whether dot `i` passes the network/slot filters only, for per-season counts. */
function dotPassesCountFilters(data, state, i) {
  const { t } = data;
  if (state.networks != null) {
    const netId = data.lookups.networks[t.network[i]].id;
    if (!state.networks.includes(netId)) return false;
  }
  if (state.slots != null) {
    const slot = t.time_slot[i];
    if (slot == null || !state.slots.includes(slot)) return false;
  }
  return true;
}

/** Per-season counts under the network/slot filters only (season filter excluded, D-05). */
function computeSeasonCounts(data, state) {
  return data.seasons.map((season) => {
    let count = 0;
    for (let i = 0; i < data.n; i += 1) {
      if (data.t.season[i] !== season) continue;
      if (dotPassesCountFilters(data, state, i)) count += 1;
    }
    return [season, count];
  });
}

/** Builds the match summary for the current selection and highlighted set. */
function buildSummary(data, state, highlighted, altGames, personIndexes, teamIdx) {
  const hasSelection = state.people.length > 0 || state.team !== null;
  if (!hasSelection) return { kind: 'none' };

  if (highlighted.length > 0) {
    const seasonsOfHighlighted = highlighted.map((i) => data.t.season[i]);
    const networkNames = new Set(
      highlighted.map((i) => data.lookups.networks[data.t.network[i]].name),
    );
    return {
      kind: 'matches',
      count: highlighted.length,
      seasonMin: Math.min(...seasonsOfHighlighted),
      seasonMax: Math.max(...seasonsOfHighlighted),
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
  let selectionLabel = names.join(' + ');
  if (teamIdx !== null) {
    const teamName = data.lookups.teams[teamIdx].name;
    selectionLabel = selectionLabel ? `${selectionLabel} + ${teamName}` : teamName;
  }
  return { kind: 'filtered-out', selectionLabel };
}

/**
 * Computes the full view for the current data and selection/filter state:
 * which dots are visible, which are highlighted, their compare-mode
 * symbols, per-season counts, and the match summary (D-05..D-08).
 * @param {object} data - a `prepareData` result.
 * @param {object} state - shaped like `defaultState(data)`.
 * @returns {object}
 */
export function computeView(data, state) {
  const { n } = data;
  const visible = computeVisible(data, state);
  let visibleCount = 0;
  for (let i = 0; i < n; i += 1) if (visible[i]) visibleCount += 1;

  const seasonCounts = computeSeasonCounts(data, state);

  const personIndexes = state.people.map((id) => data.personIndexById.get(id));
  const teamIdx = state.team !== null ? data.teamIndexBySlug.get(state.team) : null;

  const peopleOnGame = new Map();
  const altGames = new Set();
  const highlighted = [];
  let matchedUnfiltered = 0;

  for (let i = 0; i < n; i += 1) {
    const results = personIndexes.map((pIdx) => personOnGame(data, i, pIdx, state.role));

    let personMatch = true;
    if (state.people.length > 0) {
      personMatch = state.together
        ? results.every((r) => r != null)
        : results.some((r) => r != null);
    }

    let teamMatch = true;
    if (teamIdx !== null) {
      teamMatch = data.t.away_team[i] === teamIdx || data.t.home_team[i] === teamIdx;
    }

    const match = personMatch && teamMatch;
    if (match) matchedUnfiltered += 1;

    if (visible[i] && match) {
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

  const summary = buildSummary(data, state, highlighted, altGames, personIndexes, teamIdx);

  return {
    visible,
    visibleCount,
    hasSelection: state.people.length > 0 || state.team !== null,
    highlighted,
    peopleOnGame,
    altGames,
    symbols,
    seasonCounts,
    matchedUnfiltered,
    summary,
  };
}
