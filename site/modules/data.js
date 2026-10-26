/**
 * Data preparation and search over a validated site-data.json payload.
 *
 * DOM-free: no reference to window/document/Plotly. `prepareData` is the
 * single place raw columnar JSON is turned into the indexes and derived
 * values every other module (select.js, url-state.js, the chart) relies on.
 */

import { FAMILY_ORDER, familyKey } from './palette.js';
import { CFP_GAME_DEFS, NEW_YEARS_SIX } from './format.js';
import { buildDateAxis } from './date-axis.js';
import { EXCITEMENT_CAP, Y_MEASURES } from './caps.js';
import { placeVenues } from './map-geo.js';

/**
 * Normalizes a name for matching: Unicode NFKD decomposition, combining
 * marks stripped, lowercased, whitespace collapsed and trimmed.
 * @param {string} s
 * @returns {string} e.g. "  José  Núñez " -> "jose nunez".
 */
export function normalizeName(s) {
  return s
    .normalize('NFKD')
    .replace(/\p{M}/gu, '')
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .trim();
}

/**
 * Slugifies a name: normalizeName, then non-[a-z0-9] runs collapse to a
 * single dash, with leading/trailing dashes trimmed.
 * @param {string} s
 * @returns {string} e.g. "Cedar Hollow" -> "cedar-hollow".
 */
export function slugify(s) {
  return normalizeName(s)
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

/** Orders venues that share a name and city by their own data, never by array position. */
function compareVenueIdentity(venues, i, j) {
  const a = venues[i];
  const b = venues[j];
  // Code-unit order, so the result never depends on the browser's locale.
  const text = (x, y) => ((x ?? '') < (y ?? '') ? -1 : (x ?? '') > (y ?? '') ? 1 : 0);
  return (
    text(a.state, b.state) ||
    text(a.country, b.country) ||
    (a.lat ?? 0) - (b.lat ?? 0) ||
    (a.lon ?? 0) - (b.lon ?? 0) ||
    i - j
  );
}

/**
 * Stable venue keys (Phase 11 D-05): the slug of name + city. Venues that repeat a name
 * and city get -2/-3 suffixes in the order of their own state, country, latitude and
 * longitude, so a saved link keeps its venue when other venues are added or removed or
 * the lookup is reordered (only an exact duplicate of all of those falls back to lookup
 * position). A venue with a unique name and city keeps the bare slug. Also a group key
 * for each abroad marker label (Dublin) that resolves to every venue in the group.
 * Indexes are never put in a URL.
 * @param {Array<object>} venues lookups.venues
 */
function buildVenueKeys(venues) {
  const bases = venues.map((v) => slugify(`${v.name} ${v.city ?? ''}`) || 'venue');
  // Every natural base is reserved first, so a suffix (foo-2) never lands on another
  // venue's own key ("Foo 2"); keys without a collision stay exactly the base.
  const reserved = new Set(bases);
  const taken = new Set();
  const members = new Map();
  bases.forEach((base, i) => members.set(base, [...(members.get(base) ?? []), i]));
  const venueKeys = new Array(venues.length);
  for (const [base, indexes] of members) {
    indexes.sort((i, j) => compareVenueIdentity(venues, i, j));
    indexes.forEach((i, rank) => {
      let key = base;
      if (rank > 0) {
        let n = 2;
        while (reserved.has(`${base}-${n}`) || taken.has(`${base}-${n}`)) n += 1;
        key = `${base}-${n}`;
      }
      taken.add(key);
      venueKeys[i] = key;
    });
  }
  const placements = placeVenues(venues);
  // One key per abroad label; it can match neither a venue key nor another label's key.
  const groupByLabel = new Map();
  const groupKeyOf = (label) => {
    if (groupByLabel.has(label)) return groupByLabel.get(label);
    const slug = slugify(label) || 'venue';
    let key = taken.has(slug) ? `abroad-${slug}` : slug;
    for (let n = 2; taken.has(key); n += 1) key = `${taken.has(slug) ? 'abroad-' : ''}${slug}-${n}`;
    taken.add(key);
    groupByLabel.set(label, key);
    return key;
  };
  const venueGroupKeys = placements.map((pl) =>
    !pl.abroad || pl.label == null ? null : groupKeyOf(pl.label),
  );
  const venueIndexesByKey = new Map();
  venueKeys.forEach((key, i) => venueIndexesByKey.set(key, [i]));
  venueGroupKeys.forEach((key, i) => {
    if (key == null) return;
    const hit = venueIndexesByKey.get(key);
    if (hit) hit.push(i);
    else venueIndexesByKey.set(key, [i]);
  });
  return { venueKeys, venueGroupKeys, venueIndexesByKey };
}

/**
 * Search-key normalizer for named games: normalizeName, then U+02BB and
 * apostrophes (U+0027, U+2018, U+2019) removed, and every other run of
 * characters that is not a letter or digit (hyphens, dashes, commas,
 * parentheses, "&") read as one space (04.9 WR-01).
 * @param {string} s
 * @returns {string} e.g. "Hawaiʻi Bowl" -> "hawaii bowl", "Pop-Tarts Bowl" -> "pop tarts bowl".
 */
export function gameSearchKey(s) {
  return normalizeName(s)
    .replace(/[\u02BB'\u2018\u2019]/g, '')
    .replace(/[^\p{L}\p{N}]+/gu, ' ')
    .trim();
}

/**
 * Library sort key for a named game's label: a leading "The " is dropped
 * (case-insensitive) so "The Game" sorts under G while still displaying as
 * "The Game" (04.10 D-06).
 * @param {string} label
 * @returns {string}
 */
export function gameSortKey(label) {
  return label.replace(/^the\s+/i, '');
}

/**
 * Whether a folded query (from gameSearchKey) is found in a folded key: as a
 * substring, or with spaces ignored on both sides, so "army navy", "armynavy"
 * and "army-navy" all find "Army-Navy Game" (04.9 D-04, WR-01).
 * @param {string} key
 * @param {string} query - already folded; '' matches everything.
 * @returns {boolean}
 */
export function gameKeyMatches(key, query) {
  if (key.includes(query)) return true;
  return key.replaceAll(' ', '').includes(query.replaceAll(' ', ''));
}

/** Tier code per booth tier name; 0 means untiered (Phase 10). */
export const BOOTH_TIER_CODE = { a: 1, b: 2, other: 3 };

/** Computes [min, max] over the non-null values of an array, or [null, null] if none. */
function nonNullRange(values) {
  let min = Infinity;
  let max = -Infinity;
  for (const v of values) {
    if (v == null) continue;
    if (v < min) min = v;
    if (v > max) max = v;
  }
  if (min === Infinity) return [null, null];
  return [min, max];
}

/**
 * Winner-signed closing line for the Spread axis (04.6 D-02, 04.8 D-10):
 * favorite won -> negative, underdog won -> positive, pick'em -> 0, never -0.
 * @param {number|null} spread - HOME-side closing line (negative = home favored).
 * @param {number|null} hp - home points.
 * @param {number|null} ap - away points.
 * @returns {number|null} null when there is no line, no score, or a tie.
 */
function spreadX(spread, hp, ap) {
  if (spread == null || hp == null || ap == null || hp === ap) return null;
  const x = hp > ap ? spread : -spread;
  return x === 0 ? 0 : x;
}

/**
 * Prepares a validated site-data.json payload for selection, search, and
 * charting: builds every index and derived value the rest of the app needs
 * so it never has to re-scan the raw columns. Beside `t`: `total` and `margin` (derived per
 * game, null without both scores), `maxOf` (raw whole-dataset maxima for excitement, points
 * and margin) and `pinned` (maxOf above the fixed cap), 04.17 D-09..D-15.
 * @param {object} raw - the parsed site-data.json payload.
 * @returns {object} the prepared data object (see module docs for shape).
 */
export function prepareData(raw) {
  const lookups = raw.lookups;
  // home_spread is required since contract v2.0.0 (04.8 D-03).
  if (!Array.isArray(raw.telecasts.home_spread)) {
    throw new Error('site-data.json: telecasts.home_spread is missing (contract v2.0.0)');
  }
  if (
    !Array.isArray(raw.telecasts.rivalry) ||
    !Array.isArray(lookups.bowl_franchises) ||
    !Array.isArray(lookups.rivalries)
  ) {
    throw new Error('site-data.json: named-game fields are missing (contract v2.1.0)');
  }
  if (!raw.telecasts_unrated || !Array.isArray(raw.telecasts_unrated.cause)) {
    throw new Error('site-data.json: telecasts_unrated is missing (contract v2.2.0)');
  }
  if (
    !Array.isArray(lookups.venues) ||
    !Array.isArray(raw.telecasts.place) ||
    !Array.isArray(raw.telecasts_unrated.place)
  ) {
    throw new Error('site-data.json: venue fields are missing (contract v2.3.0)');
  }
  if (
    !Array.isArray(lookups.booths) ||
    !Array.isArray(raw.telecasts.booth) ||
    !Array.isArray(raw.telecasts_unrated.booth)
  ) {
    throw new Error('site-data.json: booth fields are missing (booth tiers need contract 2.6.0)');
  }
  const nRated = raw.telecasts.season.length;
  const nUnrated = raw.telecasts_unrated.season.length;
  const n = nRated + nUnrated;
  // One indexed model (04.13): rated games first (indices 0..nRated-1, the log
  // axis), then games with no public rating. Built on copies; raw is never mutated.
  // figure_source (since contract 2.4.0) gets the null tail for unrated games; a file
  // without it reads as 'rr'.
  const merged = {};
  for (const key of Object.keys(raw.telecasts)) {
    let tail;
    if (key in raw.telecasts_unrated) {
      tail = raw.telecasts_unrated[key];
    } else if (key === 'rr_urls' || key === 'flags') {
      tail = Array.from({ length: nUnrated }, () => []);
    } else {
      tail = new Array(nUnrated).fill(null);
    }
    merged[key] = raw.telecasts[key].concat(tail);
  }
  merged.cause = new Array(nRated).fill(null).concat(raw.telecasts_unrated.cause);
  const rated = new Uint8Array(n);
  rated.fill(1, 0, nRated);
  // v2.1 (user rule, 2026-10-26): a current-season game with no figure, no score and a
  // pending cause has not been played yet. Scatter, Bars, Butterfly, Map, Crews, the facets
  // and the counts leave it out until it is played or rated; This weekend reads the blocks
  // directly and still shows it with its crew.
  const unplayed = new Uint8Array(n);
  for (let i = nRated; i < n; i += 1) {
    if (
      merged.cause[i] === 'pending'
      && merged.home_points[i] == null
      && merged.away_points[i] == null
    ) {
      unplayed[i] = 1;
    }
  }
  // 04.13 D-05: band jitter is fixed per data file, implies no order, and ships
  // nothing; hashed by the unrated-block index so new rated games never move
  // band markers.
  const jitter = new Array(n).fill(null);
  for (let i = nRated; i < n; i += 1) {
    jitter[i] = (Math.imul(i - nRated + 1, 2654435761) >>> 0) / 4294967296;
  }
  // 04.15 D-16: band y for Excitement mode, where rated games with no excitement value also
  // sit in the band. Unrated values equal `jitter`, so Viewers-mode markers never move.
  const bandJitter = new Array(n);
  for (let i = 0; i < n; i += 1) {
    bandJitter[i] = jitter[i] ?? (Math.imul(i + 1, 2246822519) >>> 0) / 4294967296;
  }
  // 04.17 D-14/D-15: total points and margin of victory, derived in the browser from the
  // display fields already shipped (no new shipped field). Null when either score is null.
  // A future tie would plot at 0 margin; the shipped data has none.
  const total = new Array(n);
  const margin = new Array(n);
  for (let i = 0; i < n; i += 1) {
    const h = merged.home_points[i];
    const a = merged.away_points[i];
    const both = h != null && a != null;
    total[i] = both ? h + a : null;
    margin[i] = both ? Math.abs(h - a) : null;
  }
  const homeSpread = merged.home_spread;
  const spread = new Array(n);
  for (let i = 0; i < n; i += 1) {
    spread[i] = spreadX(homeSpread[i], merged.home_points[i], merged.away_points[i]);
  }
  // Derived column lives on a copy so raw.telecasts is never mutated. D-06:
  // season blocks come from every shipped game; so do the postseason days that
  // place the bands (04.17 D-06), whatever the view filters are.
  const { dateX, axis: dateAxis } = buildDateAxis(merged.season, merged.date, merged.kickoff, merged.game_type);
  const t = { ...merged, spread, dateX };

  // Phase 10: per-game booth index and tier from the merged booth column (rated rows first,
  // then unrated), so unrated lead games keep their tier. 0 none, 1 a, 2 b, 3 other.
  const boothOf = new Int32Array(n).fill(-1);
  const boothTier = new Uint8Array(n);
  const boothIsConfLead = new Uint8Array(n);
  for (let i = 0; i < n; i += 1) {
    const b = merged.booth[i];
    if (b == null || lookups.booths[b] == null) continue;
    boothOf[i] = b;
    boothTier[i] = BOOTH_TIER_CODE[lookups.booths[b].tier] ?? 0;
    boothIsConfLead[i] = lookups.booths[b].lead_network != null ? 1 : 0;
  }

  const familyOf = new Array(n);
  for (let i = 0; i < n; i += 1) {
    familyOf[i] = familyKey(lookups.networks[t.network[i]].family);
  }
  const familiesPresent = new Set(familyOf);
  const families = FAMILY_ORDER.filter((f) => familiesPresent.has(f));

  const personIndexById = new Map();
  lookups.people.forEach((p, idx) => personIndexById.set(p.id, idx));

  const networkIndexById = new Map();
  lookups.networks.forEach((net, idx) => networkIndexById.set(net.id, idx));

  const teamSlugs = lookups.teams.map((team) => slugify(team.name));
  const teamIndexBySlug = new Map();
  teamSlugs.forEach((slug, idx) => teamIndexBySlug.set(slug, idx));

  const seasons = Array.from(new Set(t.season)).sort((a, b) => a - b);
  const seasonMin = seasons[0];
  const seasonMax = seasons[seasons.length - 1];

  const primaryNetworkSet = new Set(t.network);
  const primaryNetworks = lookups.networks
    .map((_, idx) => idx)
    .filter((idx) => primaryNetworkSet.has(idx));

  const networksByFamily = new Map();
  for (const idx of primaryNetworks) {
    const fam = familyKey(lookups.networks[idx].family);
    if (!networksByFamily.has(fam)) networksByFamily.set(fam, []);
    networksByFamily.get(fam).push(idx);
  }

  const gamesByPerson = new Map();
  for (let i = 0; i < n; i += 1) {
    for (const entry of t.crew[i]) {
      if (!gamesByPerson.has(entry.person)) gamesByPerson.set(entry.person, []);
      gamesByPerson.get(entry.person).push(i);
    }
  }

  const [viewersMin, viewersMax] = nonNullRange(t.viewers);

  // xRange covers every shipped game: the band sits at the same x.
  // 04.17 D-09/D-10: the Excitement range stops at the fixed cap, on X and Y alike; a game
  // above it is pinned at plot time only, data.t.excitement keeps the true value.
  const [exLo, exHi] = nonNullRange(t.excitement);
  const xRange = {
    spread: nonNullRange(spread),
    excitement: exLo != null && exHi != null ? [exLo, Math.min(exHi, EXCITEMENT_CAP)] : [exLo, exHi],
  };
  // Whole-dataset maxima and the any-above-cap flags (04.17 D-12, D-14, D-15).
  const maxOfList = (list) => nonNullRange(list)[1];
  const maxOf = { excitement: exHi, points: maxOfList(total), margin: maxOfList(margin) };
  const pinned = {};
  for (const key of Object.keys(Y_MEASURES)) {
    pinned[key] = maxOf[key] != null && maxOf[key] > Y_MEASURES[key].cap;
  }

  const peopleKeys = lookups.people.map((p, index) => ({
    index,
    name: p.name,
    keys: [normalizeName(p.name), ...p.variants.map(normalizeName)],
  }));

  // The School and Conference lists every tab shares offer only teams and conferences of a
  // played or listed game: one known only from a scheduled This weekend row would zero every
  // other tab (18-13 F9). URL values still resolve through teamSlugs and the full lookups.
  const listedTeams = new Set([...t.home_team, ...t.away_team]);
  const listedConferences = new Set(
    [...t.home_conference, ...t.away_conference].filter((c) => c != null),
  );
  const teamKeys = lookups.teams
    .map((team, index) => ({
      index,
      slug: teamSlugs[index],
      name: team.name,
      keys: [normalizeName(team.name)],
    }))
    .filter((team) => listedTeams.has(team.index));

  // FBS conference names, alphabetical (D-10): the Conference filter's list
  // scope. FCS conferences (is_fbs false) are left out entirely -- School
  // reuses teamSlugs/teamIndexBySlug/teamKeys unchanged (D-11), so nothing
  // else needs a name->index map here.
  const fbsConferences = lookups.conferences
    .filter((c, index) => c.is_fbs && listedConferences.has(index))
    .map((c) => c.name)
    .sort((a, b) => a.localeCompare(b));

  // Named games (04.9): playoff rounds, bowl franchises, curated rivalries.
  const cfpGames = CFP_GAME_DEFS.map((d) => ({
    slug: d.slug,
    label: d.label,
    kind: 'cfp',
    section: 'playoff',
    round: d.round,
    phrase: d.phrase,
    keys: [gameSearchKey(d.label)],
  }));
  const bowlGames = lookups.bowl_franchises.map((f, franchise) => ({
    slug: f.slug,
    label: f.name,
    kind: 'bowl',
    section: 'bowls',
    franchise,
    keys: [f.name, ...f.former].map(gameSearchKey),
  }));
  const nysRank = (slug) => {
    const k = NEW_YEARS_SIX.indexOf(slug);
    return k === -1 ? NEW_YEARS_SIX.length : k;
  };
  bowlGames.sort(
    (a, b) =>
      nysRank(a.slug) - nysRank(b.slug) ||
      gameSortKey(a.label).localeCompare(gameSortKey(b.label)) ||
      a.label.localeCompare(b.label),
  );
  const rivalryGames = lookups.rivalries.map((r, rivalry) => ({
    slug: r.slug,
    label: r.name,
    kind: 'rivalry',
    section: 'rivalries',
    rivalry,
    // Curated in rivalries.csv (WR-02): 'the' for "the Iron Bowl", null for
    // a name that stands alone ("Bedlam", "The Game").
    article: r.article === 'the' ? 'the' : null,
    teams: r.teams.map((ti) => lookups.teams[ti].name),
    keys: [r.name, ...r.teams.map((ti) => lookups.teams[ti].name)].map(gameSearchKey),
  }));
  rivalryGames.sort(
    (a, b) =>
      gameSortKey(a.label).localeCompare(gameSortKey(b.label)) ||
      a.label.localeCompare(b.label),
  );
  const games = [...cfpGames, ...bowlGames, ...rivalryGames];
  games.forEach((g, index) => {
    g.index = index;
  });
  const gameIndexBySlug = new Map(games.map((g) => [g.slug, g.index]));
  const { venueKeys, venueGroupKeys, venueIndexesByKey } = buildVenueKeys(lookups.venues);
  const gameByRound = new Map();
  const gameByFranchise = new Map();
  const gameByRivalry = new Map();
  for (const g of games) {
    if (g.kind === 'cfp') gameByRound.set(g.round, g.index);
    else if (g.kind === 'bowl') gameByFranchise.set(g.franchise, g.index);
    else gameByRivalry.set(g.rivalry, g.index);
  }
  const dotGames = new Array(n);
  for (let i = 0; i < n; i += 1) {
    const memberships = [];
    const round = t.playoff_round[i];
    if (round != null && gameByRound.has(round)) memberships.push(gameByRound.get(round));
    const bowl = t.bowl[i];
    if (bowl != null) {
      const gi = gameByFranchise.get(lookups.bowls[bowl].franchise);
      if (gi !== undefined) memberships.push(gi);
    }
    const riv = t.rivalry[i];
    if (riv != null) memberships.push(gameByRivalry.get(riv));
    dotGames[i] = memberships;
  }

  return {
    raw,
    n,
    nRated,
    rated,
    unplayed,
    jitter,
    bandJitter,
    t,
    lookups,
    familyOf,
    booths: lookups.booths,
    boothOf,
    boothTier,
    boothIsConfLead,
    families,
    personIndexById,
    networkIndexById,
    teamSlugs,
    teamIndexBySlug,
    seasons,
    seasonMin,
    seasonMax,
    primaryNetworks,
    networksByFamily,
    gamesByPerson,
    viewersMin,
    viewersMax,
    xRange,
    total,
    margin,
    maxOf,
    pinned,
    dateAxis,
    peopleKeys,
    teamKeys,
    fbsConferences,
    games,
    gameIndexBySlug,
    venueKeys,
    venueGroupKeys,
    venueIndexesByKey,
    dotGames,
    // Phase 18: the This weekend tab's blocks. They never join `t`, so every other tab keeps its
    // counts; `weekend-data.js` reads them. A file from before contract 2.7.0 reads as empty.
    scheduledRaw: raw.telecasts_scheduled ?? null,
    weeks: lookups.weeks ?? [],
    weekend: raw.freshness?.weekend ?? null,
  };
}

/** Match rank for a single normalized candidate string against a normalized query. */
function candidateRank(normalizedCandidate, normalizedQuery) {
  if (normalizedCandidate.startsWith(normalizedQuery)) return 0;
  if (normalizedCandidate.split(' ').some((word) => word.startsWith(normalizedQuery))) return 1;
  if (normalizedCandidate.includes(normalizedQuery)) return 2;
  return -1;
}

/**
 * Finds the best-ranked match among a canonical name and its variants.
 * @returns {{rank: number, isCanonical: boolean, text: string}|null}
 */
function bestNameMatch(name, variants, normalizedQuery) {
  const candidates = [{ text: name, isCanonical: true }];
  for (const variant of variants) {
    candidates.push({ text: variant, isCanonical: variant === name });
  }
  let best = null;
  for (const candidate of candidates) {
    const rank = candidateRank(normalizeName(candidate.text), normalizedQuery);
    if (rank === -1) continue;
    if (
      best === null ||
      rank < best.rank ||
      (rank === best.rank && candidate.isCanonical && !best.isCanonical)
    ) {
      best = { rank, isCanonical: candidate.isCanonical, text: candidate.text };
    }
  }
  return best;
}

/**
 * Searches people by canonical name or any variant, accent- and
 * case-insensitively. Ranks name-prefix matches first, then word-prefix
 * matches, then substrings; ties break by name then id.
 * @param {object} data - a `prepareData` result.
 * @param {string} query
 * @param {number} [limit]
 * @returns {{index: number, id: string, name: string, matchedVariant: string|null}[]}
 */
export function searchPeople(data, query, limit = 8) {
  const normalizedQuery = normalizeName(query);
  if (normalizedQuery === '') return [];
  const matches = [];
  for (const p of data.lookups.people) {
    const best = bestNameMatch(p.name, p.variants, normalizedQuery);
    if (best === null) continue;
    matches.push({
      index: data.personIndexById.get(p.id),
      id: p.id,
      name: p.name,
      matchedVariant: best.isCanonical ? null : best.text,
      _rank: best.rank,
    });
  }
  matches.sort(
    (a, b) => a._rank - b._rank || a.name.localeCompare(b.name) || a.id.localeCompare(b.id),
  );
  return matches.slice(0, limit).map(({ _rank, ...rest }) => rest);
}
