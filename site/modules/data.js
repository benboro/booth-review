/**
 * Data preparation and search over a validated site-data.json payload.
 *
 * DOM-free: no reference to window/document/Plotly. `prepareData` is the
 * single place raw columnar JSON is turned into the indexes and derived
 * values every other module (select.js, url-state.js, the chart) relies on.
 */

import { FAMILY_ORDER, familyKey } from './palette.js';

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
 * Prepares a validated site-data.json payload for selection, search, and
 * charting: builds every index and derived value the rest of the app needs
 * so it never has to re-scan the raw columns.
 * @param {object} raw - the parsed site-data.json payload.
 * @returns {object} the prepared data object (see module docs for shape).
 */
export function prepareData(raw) {
  const lookups = raw.lookups;
  const t = raw.telecasts;
  const n = t.season.length;

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

  const xRange = {
    pregame: nonNullRange(t.pregame),
    excitement: nonNullRange(t.excitement),
  };

  const peopleKeys = lookups.people.map((p, index) => ({
    index,
    name: p.name,
    keys: [normalizeName(p.name), ...p.variants.map(normalizeName)],
  }));

  const teamKeys = lookups.teams.map((team, index) => ({
    index,
    slug: teamSlugs[index],
    name: team.name,
    keys: [normalizeName(team.name)],
  }));

  return {
    raw,
    n,
    t,
    lookups,
    familyOf,
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
    peopleKeys,
    teamKeys,
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

/**
 * Searches teams by name, accent- and case-insensitively, with the same
 * ranking as `searchPeople`.
 * @param {object} data - a `prepareData` result.
 * @param {string} query
 * @param {number} [limit]
 * @returns {{index: number, slug: string, name: string}[]}
 */
export function searchTeams(data, query, limit = 8) {
  const normalizedQuery = normalizeName(query);
  if (normalizedQuery === '') return [];
  const matches = [];
  for (const team of data.lookups.teams) {
    const index = data.teamIndexBySlug.get(slugify(team.name));
    const rank = candidateRank(normalizeName(team.name), normalizedQuery);
    if (rank === -1) continue;
    matches.push({ index, slug: data.teamSlugs[index], name: team.name, _rank: rank });
  }
  matches.sort(
    (a, b) => a._rank - b._rank || a.name.localeCompare(b.name) || a.slug.localeCompare(b.slug),
  );
  return matches.slice(0, limit).map(({ _rank, ...rest }) => rest);
}
