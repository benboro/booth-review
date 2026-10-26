// Venue model (Phase 11 D-01, D-01a, D-03, D-06a, D-07, D-11, D-12): one record per
// stadium for every Map surface (dots, hover card, pie, size key, splat painter).
//
// DOM-free and pure: imports only ./palette.js and never reads the page or the chart
// library. Inputs and outputs are plain numbers, strings and arrays (the one Map in the
// model is byKey). Keeping the rules apart from any painter is what keeps a second splat
// style cheap later (D-11).
//
// Rules: inside a venue the family with the most games leads and viewers only break exact
// ties (D-06a). Across venues one score, games^(1 - w) x max(viewersMM, 0.01)^w, sets splat
// strength. Dot size is games only (Phase 17.1 D-01): area exactly proportional to games, relative
// to the busiest venue in the filtered set (D-20). Unrated games count at the floor
// viewers (p10 of the rated passing set) in the score only, never in the shown viewers (D-07).

import {
  FAMILY_ORDER,
  MAP_DOT_NEUTRAL,
  MAP_FAMILY_COLORS,
  MAP_SPLAT,
  MAP_VENUE_DOT,
  mixOklab,
} from './palette.js';

const NF = FAMILY_ORDER.length;

/**
 * Index into an ascending list for a percentile.
 * @param {number} len
 * @param {number} pct - 0..100.
 * @returns {number}
 */
export function percentileIndex(len, pct) {
  return Math.floor(((len - 1) * pct) / 100);
}

/**
 * Cross-venue score: games^(1-w) x max(weightedViewers / 1e6, 0.01)^w; 0 with no games.
 * @param {number} games
 * @param {number} weightedViewers - total viewers, unrated games at the floor.
 * @returns {number}
 */
export function venueScore(games, weightedViewers) {
  if (!games) return 0;
  const w = MAP_SPLAT.viewersWeight;
  return games ** (1 - w) * Math.max(weightedViewers / 1e6, 0.01) ** w;
}

/**
 * Leader by games; an equal nonzero game count goes to the larger real (rated) viewers,
 * then the larger floor-weighted viewers, then the earlier FAMILY_ORDER family (D-06a:
 * viewers only break exact ties, and an unrated game's floor never beats a real figure).
 * @param {number[]} counts
 * @param {number[]} weighted - viewers with unrated games at the floor.
 * @param {number[]} [viewers] - real viewers only.
 * @returns {{leaderIndex: number, leaderGames: number, runnerUpGames: number}}
 */
export function venueLeader(counts, weighted, viewers = counts.map(() => 0)) {
  let a = 0;
  let b = 0;
  let ai = 0;
  for (let f = 0; f < counts.length; f += 1) {
    const w = counts[f];
    const tieWin =
      w === a &&
      w > 0 &&
      (viewers[f] > viewers[ai] || (viewers[f] === viewers[ai] && weighted[f] > weighted[ai]));
    if (w > a || tieWin) {
      b = a;
      a = w;
      ai = f;
    } else if (w > b) {
      b = w;
    }
  }
  return { leaderIndex: ai, leaderGames: a, runnerUpGames: b };
}

/**
 * Dot diameters in px for desktop and phone: games only, area exactly proportional to
 * games, where refGames (the busiest venue in the filtered set) draws the maximum (D-20).
 * Games are not clamped to refGames: each caller passes its own set's busiest venue (D-24).
 * @param {number} games
 * @param {number} refGames
 * @returns {{desktop: number, phone: number}}
 */
export function venueDotSize(games, refGames) {
  const ref = refGames > 0 ? refGames : 1;
  const n = Math.max(Number(games) || 0, 0);
  const r = Math.sqrt(n / ref);
  return {
    desktop: MAP_VENUE_DOT.maxDiameter * r,
    phone: MAP_VENUE_DOT.phoneMaxDiameter * r,
  };
}

function blank() {
  return {
    counts: new Float64Array(NF),
    viewers: new Float64Array(NF),
    ratedCounts: new Float64Array(NF),
    weighted: new Float64Array(NF),
  };
}

function median(sortedAsc, fallback) {
  return sortedAsc.length ? sortedAsc[Math.floor(sortedAsc.length / 2)] : fallback;
}

/**
 * Builds the venue model for the games that pass the filters.
 * @param {{t: {place: (number|null)[], viewers: (number|null)[]}, familyOf: string[],
 *   lookups: {venues: {state?: string}[]}, venueKeys: string[],
 *   venueGroupKeys: (string|null)[]}} data
 * @param {number[]} passing - game indexes that pass the filters and have a place.
 * @param {{x: number, y: number, abroad: boolean, label?: string}[]} placements
 * @returns {object} VenueModel (see the Phase 11 plan 02 contract).
 */
export function buildVenueModel(data, passing, placements) {
  const rated = [];
  for (const g of passing) {
    const v = data.t.viewers[g];
    if (v != null) rated.push(v);
  }
  rated.sort((p, q) => p - q);
  const fallback = MAP_SPLAT.unratedFallback;
  const floorViewers = rated.length
    ? rated[percentileIndex(rated.length, MAP_SPLAT.unratedPercentile)]
    : fallback;
  const medianRatedViewers = median(rated, fallback);

  const acc = new Map();
  for (const g of passing) {
    const idx = data.t.place[g];
    if (idx == null || !placements[idx]) continue;
    const f = FAMILY_ORDER.indexOf(data.familyOf[g]);
    if (f < 0) continue;
    let a = acc.get(idx);
    if (!a) {
      a = blank();
      acc.set(idx, a);
    }
    const v = data.t.viewers[g];
    a.counts[f] += 1;
    if (v != null) {
      a.viewers[f] += v;
      a.ratedCounts[f] += 1;
      a.weighted[f] += v;
    } else {
      a.weighted[f] += floorViewers;
    }
  }

  const venues = [];
  const groupMap = new Map();
  for (const [index, a] of acc) {
    const p = placements[index];
    const games = a.counts.reduce((s, c) => s + c, 0);
    if (!games) continue;
    if (p.abroad) {
      const gk = data.venueGroupKeys[index] ?? data.venueKeys[index];
      let grp = groupMap.get(gk);
      if (!grp) {
        grp = { key: gk, label: p.label ?? gk, indexes: [], ...blank(), games: 0, leader: FAMILY_ORDER[0] };
        groupMap.set(gk, grp);
      }
      grp.indexes.push(index);
      for (let f = 0; f < NF; f += 1) {
        grp.counts[f] += a.counts[f];
        grp.viewers[f] += a.viewers[f];
        grp.ratedCounts[f] += a.ratedCounts[f];
        grp.weighted[f] += a.weighted[f];
      }
      grp.games += games;
      continue;
    }
    const weightedSum = a.weighted.reduce((s, c) => s + c, 0);
    const { leaderIndex, leaderGames, runnerUpGames } = venueLeader(a.counts, a.weighted, a.viewers);
    const margin = (leaderGames - runnerUpGames) / games;
    const fade = margin ** MAP_SPLAT.dotMarginExp;
    const leader = FAMILY_ORDER[leaderIndex];
    venues.push({
      index,
      key: data.venueKeys[index],
      x: p.x,
      y: p.y,
      region: data.lookups.venues[index]?.state === 'HI' ? 2 : 1,
      counts: Array.from(a.counts),
      viewers: Array.from(a.viewers),
      ratedCounts: Array.from(a.ratedCounts),
      weighted: Array.from(a.weighted),
      games,
      score: venueScore(games, weightedSum),
      leader,
      runnerUpGames,
      margin,
      fade,
      size: { desktop: 0, phone: 0 },
      dotColor: {
        light: mixOklab(MAP_DOT_NEUTRAL.light, MAP_FAMILY_COLORS.light[leader], fade),
        dark: mixOklab(MAP_DOT_NEUTRAL.dark, MAP_FAMILY_COLORS.dark[leader], fade),
      },
    });
  }

  let maxScore = 0;
  for (const v of venues) if (v.score > maxScore) maxScore = v.score;
  const positive = venues.map((v) => v.score).filter((s) => s > 0).sort((p, q) => p - q);
  const medianScore = median(positive, 1);
  let refGames = 0;
  for (const v of venues) if (v.games > refGames) refGames = v.games;
  for (const v of venues) v.size = venueDotSize(v.games, refGames);
  venues.sort((p, q) => q.games - p.games || p.index - q.index);

  const groups = [];
  for (const grp of groupMap.values()) {
    grp.leader = FAMILY_ORDER[venueLeader(grp.counts, grp.weighted, grp.viewers).leaderIndex];
    grp.counts = Array.from(grp.counts);
    grp.viewers = Array.from(grp.viewers);
    grp.ratedCounts = Array.from(grp.ratedCounts);
    grp.weighted = Array.from(grp.weighted);
    groups.push(grp);
  }

  const byKey = new Map();
  for (const v of venues) byKey.set(v.key, v);
  for (const grp of groups) byKey.set(grp.key, grp);

  return { venues, byKey, groups, floorViewers, medianRatedViewers, medianScore, maxScore, refGames };
}
