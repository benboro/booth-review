/**
 * Selection semantics (D-10..D-19, 04.7 D-05..D-07, D-14): filters (Seasons,
 * Kickoff, Conference, School, Bowls/Playoffs) fade a dot that fails them by
 * default and hide it in Hide mode (`state.dots === 'hide'`); Networks always
 * hides. Head-to-head narrows School to games between exactly two schools.
 * Role still limits only how a person matches, never which dots pass. Also covers person/compare-mode matching, the
 * matched-games fill rule (person-or-school, D-12), and the match summary.
 * Also computes faceted option counts (D-08..D-12, `computeFacets`): each
 * facet counts games (rated and unrated, 04.13 D-08) passing every active constraint except its
 * own. Facets and counts never depend on Fade vs Hide.
 * DOM-free; imports only from ./palette.js and ./format.js.
 */

import { COMPARE_SYMBOLS, SHARED_SYMBOL } from './palette.js';
import { gameTitlePhrase } from './format.js';

/** Maximum number of people that can be selected in compare mode (D-07). */
export const MAX_COMPARE = 4;

/**
 * The default selection/filter state (D-12, D-13): all dots, nobody
 * selected, Spread axis. `seasons`/`networks`/`slots` of `null` mean
 * "unfiltered"; `conferences`/`school` of `[]` mean "unfiltered" (D-10,
 * D-11); `postseason` of `'all'` means "unfiltered" (D-18). There is no
 * `team` field -- School (`state.school`) replaces the old team highlight
 * as a fade filter (D-11). `view` is the chart tab (`'scatter'`/`'bars'`/
 * `'butterfly'`) and `by` the bar grouping (null = by Announcer, else
 * `'network'` | `'team'` | `'conference'`; 04.6 D-27). `dots` is the Fade |
 * Hide view setting (`'fade'` | `'hide'`, 04.7 D-10); `h2h` is Head-to-head
 * for exactly two schools (04.7 D-14). `y` is the scatter's Y measure
 * (`'viewers'` | `'excitement'`, 04.15 D-09).
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
    game: null,
    axis: 'spread',
    y: 'viewers',
    view: 'scatter',
    by: null,
    dots: 'fade',
    h2h: false,
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

/**
 * The drawn mask (04.7 D-05..D-07): Networks always hides a dot; the other
 * filters hide it only in Hide mode (the exact string 'hide'), else it stays
 * drawn and merely fades.
 */
function computeVisible(data, state) {
  const { n } = data;
  const visible = new Uint8Array(n);
  const hide = state.dots === 'hide';
  for (let i = 0; i < n; i += 1) {
    if (failsNetworks(data, state, i)) continue;
    if (hide && failsFadeable(data, state, i)) continue;
    visible[i] = 1;
  }
  return visible;
}

/** True when the season range excludes dot `i`. */
function failsSeasons(data, state, i) {
  if (state.seasons == null) return false;
  const season = data.t.season[i];
  return season < state.seasons[0] || season > state.seasons[1];
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

/**
 * True when School excludes dot `i`: neither team selected (Either team), or,
 * under Head-to-head with exactly two schools, not both teams selected (D-14).
 */
function failsSchool(data, state, i) {
  if (state.school.length === 0) return false;
  const t = data.t;
  const awayIn = state.school.includes(data.teamSlugs[t.away_team[i]]);
  const homeIn = state.school.includes(data.teamSlugs[t.home_team[i]]);
  if (state.h2h === true && state.school.length === 2) return !(awayIn && homeIn);
  return !(awayIn || homeIn);
}

/** True when Bowls/Playoffs excludes dot `i`. */
function failsPostseason(data, state, i) {
  const gameType = data.t.game_type[i];
  if (state.postseason === 'exclude') return gameType !== 'regular';
  if (state.postseason === 'only') return gameType === 'regular';
  return false;
}

/**
 * True when the Game pick excludes dot `i` (04.9 D-03, D-11): no pick, or an
 * unknown slug (T-04.9-16), never excludes; else the dot must belong to the game.
 */
function failsGame(data, state, i) {
  if (state.game == null) return false;
  const gi = data.gameIndexBySlug.get(state.game);
  if (gi === undefined) return false;
  return !data.dotGames[i].includes(gi);
}

/** True when any filter that fades (Seasons, Kickoff, Conference, School, Bowls/Playoffs, Game; not Networks or Role) excludes dot `i`. */
function failsFadeable(data, state, i) {
  return (
    failsSeasons(data, state, i) ||
    failsSlots(data, state, i) ||
    failsConferences(data, state, i) ||
    failsSchool(data, state, i) ||
    failsPostseason(data, state, i) ||
    failsGame(data, state, i)
  );
}

/**
 * Whether dot `i` passes every filter: Seasons, Networks, Kickoff,
 * Conference, School, Bowls/Playoffs, and Game (04.7 D-06, 04.9 D-14). Independent of the
 * Fade/Hide mode. Role is deliberately absent: it never fades a dot.
 * @param {object} data - a `prepareData` result.
 * @param {object} state - shaped like `defaultState(data)`.
 * @param {number} i - telecast index.
 * @returns {boolean}
 */
export function passesFadeFilters(data, state, i) {
  return !failsNetworks(data, state, i) && !failsFadeable(data, state, i);
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
const BIT_GAME = 128;

/**
 * Faceted option counts (D-08..D-12): for every filter option, the number
 * of games (rated and unrated, 04.13 D-08) passing every active constraint except that facet's
 * own. One pass over the dots builds a per-dot fail bitmask; a dot counts
 * toward a facet iff its mask has no bit outside that facet's own. Role is
 * not a dot constraint; it only feeds the person match and the Role facet.
 * @param {object} data - a `prepareData` result.
 * @param {object} state - shaped like `defaultState(data)`.
 * @returns {object} `{ total, seasons, networks, slots, conferences,
 *   schools, postseason, games, role, people }` (`games`: one count per
 *   `data.games` entry, a dot counting toward every game it belongs to).
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
  const games = new Int32Array(data.games.length);
  const role = { pbp: 0, analyst: 0 };
  const people = new Int32Array(data.lookups.people.length);
  let total = 0;

  for (let i = 0; i < n; i += 1) {
    let mask = 0;
    if (failsSeasons(data, state, i)) mask |= BIT_SEASON;
    if (failsNetworks(data, state, i)) mask |= BIT_NET;
    if (failsSlots(data, state, i)) mask |= BIT_SLOT;
    if (failsConferences(data, state, i)) mask |= BIT_CONF;
    if (failsSchool(data, state, i)) mask |= BIT_SCHOOL;
    if (failsPostseason(data, state, i)) mask |= BIT_POST;
    if (failsGame(data, state, i)) mask |= BIT_GAME;
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
    if ((mask & ~BIT_GAME) === 0) {
      for (const g of data.dotGames[i]) games[g] += 1;
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

  return { total, seasons, networks, slots, conferences, schools, postseason, games, role, people };
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

/**
 * Builds the match summary for the current selection and the summary set
 * (D-09, 04.7; 04.13 D-07). `summarySet` is the matched games when something
 * is selected, else every filter-passing game (all games when nothing is
 * filtered). `count` is games, `rated` the rated subset. Counts only -- never
 * a viewer statistic (A1).
 */
function buildSummary(data, state, summarySet, altGames, personIndexes, hasSelection, filterActive) {
  const matched = summarySet;
  const ratedOf = (set) => set.reduce((sum, i) => sum + data.rated[i], 0);
  if (!hasSelection && !filterActive) {
    return { kind: 'all', count: matched.length, rated: ratedOf(matched) };
  }

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
      rated: ratedOf(matched),
      seasonMin: Math.min(...seasonsOfMatched),
      seasonMax: Math.max(...seasonsOfMatched),
      networks: Array.from(networkCounts.keys()).sort(
        (a, b) => networkCounts.get(b) - networkCounts.get(a) || a.localeCompare(b),
      ),
      altCount: altGames.size,
    };
  }

  if (!hasSelection) return { kind: 'no-filter-match' };

  if (state.people.length === 1) {
    const games = data.gamesByPerson.get(personIndexes[0]) ?? [];
    if (games.length === 0) {
      return { kind: 'no-rated', name: data.lookups.people[personIndexes[0]].name };
    }
  }

  const game =
    state.game != null ? data.games[data.gameIndexBySlug.get(state.game)] : undefined;
  if (game && state.people.length === 0 && state.school.length === 0) {
    return { kind: 'no-game-match', phrase: gameTitlePhrase(game) };
  }

  const names = state.people.map((id) => data.lookups.people[data.personIndexById.get(id)].name);
  const schoolNames = state.school.map(
    (slug) => data.lookups.teams[data.teamIndexBySlug.get(slug)].name,
  );
  const schoolParts =
    state.h2h === true && schoolNames.length === 2 ? [schoolNames.join(' vs ')] : schoolNames;
  const selectionLabel = [...names, ...schoolParts, ...(game ? [game.label] : [])].join(' + ');
  return { kind: 'filtered-out', selectionLabel };
}

/**
 * Computes the full view for the current data and selection/filter state
 * (D-10..D-19, 04.7): which dots are drawn (filters fade by default and
 * hide in Hide mode; Networks always hides), which pass every filter, which are person-matched, which rows fill the
 * matched-games table, their compare-mode symbols, per-season counts, and
 * the match summary. The result's `filterActive` drives the summary. `enlargeDots`
 * is for dot sizing only (04.16 D-01..D-07): true when at least one faded dot is drawn
 * (`drawnFaded`, counted over the whole plot, never the zoom range, and ignoring
 * out-of-range seasons on the Date axis), or when Networks is the only filter and 1-3
 * families are on.
 * @param {object} data - a `prepareData` result.
 * @param {object} state - shaped like `defaultState(data)`.
 * @returns {object}
 */
export function computeView(data, state) {
  const { n } = data;
  const visible = computeVisible(data, state);
  let visibleCount = 0;
  let drawnFaded = 0;

  const passesFilters = new Uint8Array(n);
  let passingCount = 0;
  for (let i = 0; i < n; i += 1) {
    if (visible[i]) visibleCount += 1;
    if (passesFadeFilters(data, state, i)) {
      passesFilters[i] = 1;
      passingCount += 1;
    }
    // D-01/D-03: a faded dot is drawn but fails a fade filter; on Date, seasons outside
    // the range are not drawn, so they never count. No zoom input (D-02).
    if (
      visible[i] &&
      !passesFilters[i] &&
      !(state.axis === 'date' && failsSeasons(data, state, i))
    ) {
      drawnFaded += 1;
    }
  }

  const facets = computeFacets(data, state);
  const seasonCounts = data.seasons.map((season) => [season, facets.seasons.get(season)]);

  const personIndexes = state.people.map((id) => data.personIndexById.get(id));
  const hasPersonSelection = state.people.length > 0;
  const hasGameSelection =
    state.game != null && data.gameIndexBySlug.has(state.game);
  const hasSelection = hasPersonSelection || hasGameSelection || state.school.length > 0;

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
  // are exactly `highlighted`) or, absent a person, when School or a named game is set (its
  // rows are every dot that passes the fade filters). Every other filter
  // alone never fills it (no-bulk rule).
  let matched;
  if (hasPersonSelection) {
    matched = highlighted;
  } else if (state.school.length > 0 || hasGameSelection) {
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

  // Every filter except seasons and Networks. Role and people are deliberately not
  // filters (04.1 D-13). A new filter goes here once, so it drives every flag below.
  const nonNetworkFilter =
    state.slots != null ||
    state.conferences.length > 0 ||
    state.school.length > 0 ||
    hasGameSelection ||
    state.postseason !== 'all';
  const otherFilterActive = state.networks != null || nonNetworkFilter;
  const filterActive = state.seasons != null || otherFilterActive;
  // 04.16 D-04: the old rule-based size flag is gone. SITE-50 (D-03) keeps a
  // seasons-only filter on Date as "no filter": out-of-range seasons are off the axis.
  const seasonsSizeFilter = state.seasons != null && state.axis !== 'date';
  // D-05..D-07: with Networks the only filter, 1-3 families on enlarge even though
  // nothing is faded; any other filter makes the family count irrelevant (D-06).
  const networksOnly = state.networks != null && !nonNetworkFilter && !seasonsSizeFilter;
  const familiesOn = networksOnly
    ? data.families.filter((f) => !familyToggledOff(data, state, f)).length
    : 0;
  const enlargeDots = drawnFaded > 0 || (networksOnly && familiesOn >= 1 && familiesOn <= 3);
  let summarySet = matched;
  if (!hasSelection) {
    summarySet = [];
    for (let i = 0; i < n; i += 1) if (passesFilters[i]) summarySet.push(i);
  }
  const summary = buildSummary(
    data,
    state,
    summarySet,
    altGames,
    personIndexes,
    hasSelection,
    filterActive,
  );

  return {
    visible,
    passesFilters,
    visibleCount,
    passingCount,
    hasPersonSelection,
    hasGameSelection,
    hasSelection,
    filterActive,
    enlargeDots,
    drawnFaded,
    totalCount: n,
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

/**
 * Whether two id lists hold the same members, ignoring order.
 * @param {Array} a
 * @param {Array} b
 * @returns {boolean}
 */
export function sameSet(a, b) {
  return a.length === b.length && a.every((x) => b.includes(x));
}

/**
 * Whether `networks` is exactly a family's offered channels (so its Only
 * button reads "All"; 04.2 D-25).
 * @param {object} data - a `prepareData` result.
 * @param {object} view - a `computeView` result.
 * @param {string} family - a `familyKey` value.
 * @param {string[]|null} networks - `state.networks`.
 * @returns {boolean}
 */
export function familyIsSole(data, view, family, networks) {
  const offered = offeredFamilyIds(data, family, view);
  return networks != null && offered.length > 0 && sameSet(networks, offered);
}

/**
 * The state patch for a family's Only/All (04.15 D-06, 04.2 D-24/D-25): the
 * family's offered channels; `networks: null` (All) when they are already the
 * sole selection; no change when the family offers no channel. The Networks
 * popover's family button and the legend pill double-click both call this.
 * The pill double-click passes the `networks` snapshot from before its first
 * click, so the two single clicks do not make it read as already sole.
 * @param {object} data - a `prepareData` result.
 * @param {object} view - a `computeView` result.
 * @param {string} family - a `familyKey` value.
 * @param {string[]|null} networksBefore - the `networks` value to judge against.
 * @returns {{networks: string[]|null}}
 */
export function familyOnlyPatch(data, view, family, networksBefore) {
  const offered = offeredFamilyIds(data, family, view);
  if (offered.length === 0) return { networks: networksBefore };
  if (familyIsSole(data, view, family, networksBefore)) return { networks: null };
  return { networks: offered };
}

/**
 * Patch for picking an X axis (04.15 D-11): Excitement on both axes is not
 * allowed, so picking it on x while y is Excitement moves y to Viewers in the
 * same patch (two patches would flash an invalid state, and `decodeState`
 * would undo a bare axis change because y wins in a link, D-12).
 * @param {string} axis - the picked x axis.
 * @param {object} state - shaped like `defaultState(data)`.
 * @returns {object}
 */
export function axisPatch(axis, state) {
  return axis === 'excitement' && state.y === 'excitement' ? { axis, y: 'viewers' } : { axis };
}

/**
 * Patch for picking a Y measure (04.15 D-11): picking Excitement while x is
 * Excitement moves x to Spread in the same patch.
 * @param {string} y - the picked y measure.
 * @param {object} state - shaped like `defaultState(data)`.
 * @returns {object}
 */
export function yPatch(y, state) {
  return y === 'excitement' && state.axis === 'excitement' ? { y, axis: 'spread' } : { y };
}
