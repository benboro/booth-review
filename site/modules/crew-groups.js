/**
 * Crew grouping core (Phase 14, route two): the client mirror of
 * `src/booth_review/build/booths.py`, so the Crews table can list every crew 2014-2026
 * without a Python change. Pure and DOM-free; no import of any DOM module.
 *
 * Rules mirrored from booths.py (`_modal`, `_lowest_position`, `assign_cfb_booths`):
 *  1. Only `feed === 'main'` crew entries count. The shipped crew is ordered by (feed,
 *     crew_position), so the first main `pbp` entry is the lowest-position PBP and the
 *     first main `analyst` is the game analyst.
 *  2. Modal: most common value, ties to the lowest id (compared with `<`, never
 *     `localeCompare`).
 *  3. Fill-in: the game has at least one main-feed analyst and the regular analyst is on
 *     none of its main-feed analyst seats.
 *  4. No main-feed PBP: the game is not tiered (the D-05 population).
 *  5. Family comes from the telecast network; only disney/fox/cbs/nbc are booth families.
 *
 * Assumptions applied:
 *  A1  Regular analyst is hybrid. Tiered games (`booth != null`) read pbp, regular analyst,
 *      rank and tier from `lookups.booths[booth]` (the cited analyst when booths.py matched
 *      a cited row); untiered games use the modal analyst over the group's games.
 *  A6  Crew key `<groupId>:<pbpSlug>[.<analystSlug>...]`, analysts sorted ascending by slug;
 *      a no-PBP key is `<groupId>:~<slug>.<slug>...` over every main-feed person. The
 *      groupId is the family id for the big four and the network id for every other network.
 *      Season is not part of the key, so keys pool across seasons (D-09).
 *  A11 The displayed lineup of a (group, season, pbp) booth is the modal sorted tuple of
 *      each game's main-feed analyst slugs (ties to the lowest tuple, element-wise); if it
 *      does not contain the regular analyst, the modal tuple among games that seat the
 *      regular analyst; if none do, `[regular]`. The fill-in test uses the regular analyst,
 *      never the lineup.
 */

// Mirrors CFB_BOOTH_FAMILIES in src/booth_review/build/booth_ranks.py.
const BOOTH_FAMILIES = new Set(['disney', 'fox', 'cbs', 'nbc']);

/** Strict crew key allowlist (T-14-03). */
export const CREW_KEY_RE = /^[a-z0-9-]+:~?[a-z0-9-]+(\.[a-z0-9-]+)*$/;

/** Crews sort keys and their natural directions (14-UI-SPEC "Sorting"). */
export const NATURAL_DIR = Object.freeze({
  crew: 'asc',
  season: 'asc',
  network: 'asc',
  rank: 'asc',
  games: 'desc',
  exc: 'desc',
  viewers: 'desc',
});

/**
 * Most common slug; ties go to the lower slug. null when empty.
 * @param {string[]} slugs
 * @returns {string|null}
 */
export function modalSlug(slugs) {
  if (!slugs.length) return null;
  const counts = new Map();
  for (const s of slugs) counts.set(s, (counts.get(s) ?? 0) + 1);
  let best = null;
  let bestN = 0;
  for (const [s, n] of counts) {
    if (n > bestN || (n === bestN && s < best)) {
      best = s;
      bestN = n;
    }
  }
  return best;
}

/** Element-wise `<` over two slug arrays: negative, zero or positive. */
function cmpTuple(a, b) {
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i += 1) {
    if (a[i] < b[i]) return -1;
    if (a[i] > b[i]) return 1;
  }
  return a.length - b.length;
}

/** Modal tuple (arrays of slugs); ties to the lowest tuple. null when empty. */
function modalTuple(tuples) {
  if (!tuples.length) return null;
  const counts = new Map();
  for (const t of tuples) {
    const k = t.join('.');
    const e = counts.get(k);
    if (e) e.n += 1;
    else counts.set(k, { t, n: 1 });
  }
  let best = null;
  for (const e of counts.values()) {
    if (best === null || e.n > best.n || (e.n === best.n && cmpTuple(e.t, best.t) < 0)) best = e;
  }
  return best.t;
}

const sortedUnique = (slugs) => {
  const out = Array.from(new Set(slugs));
  out.sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
  return out;
};

/**
 * Group every game into a crew, per booths.py rules.
 * @param {{people: string[], networks: {id: string, family: string|null}[],
 *   booths: {family: string, season: number, pbp: number|null, analyst: number|null,
 *   rank: number|null, tier: string}[],
 *   games: {season: number, network: number, booth: number|null,
 *   crew: {person: number, role: string, feed: string}[]}[]}} input
 * @returns {Array<object>} one entry per game.
 */
export function groupTelecasts(input) {
  const { people, networks, booths, games } = input;
  const pass1 = games.map((g) => {
    const net = networks[g.network];
    const family = net ? net.family : null;
    const groupId = BOOTH_FAMILIES.has(family) ? family : (net ? net.id : 'unknown');
    let pbp = null;
    const analysts = [];
    const main = [];
    const unknown = [];
    for (const e of g.crew) {
      if (e.feed !== 'main') continue;
      const slug = people[e.person];
      main.push(slug);
      if (e.role === 'pbp' && pbp === null) pbp = slug;
      else if (e.role === 'analyst') analysts.push(slug);
      else if (e.role === 'unknown') unknown.push(slug);
    }
    return { groupId, pbp, analysts, main, unknown, season: g.season, booth: g.booth };
  });

  // Per (group, season, pbp): first analysts for the modal, and tuples for the lineup.
  const groups = new Map();
  pass1.forEach((p, i) => {
    if (p.pbp === null) return;
    const gk = `${p.groupId}|${p.season}|${p.pbp}`;
    if (!groups.has(gk)) groups.set(gk, { first: [], tuples: [], idx: [] });
    const grp = groups.get(gk);
    grp.idx.push(i);
    if (p.analysts.length) {
      grp.first.push(p.analysts[0]);
      grp.tuples.push(sortedUnique(p.analysts));
    }
  });
  for (const grp of groups.values()) grp.modal = modalSlug(grp.first);

  const regularOf = new Array(games.length).fill(null);
  const out = pass1.map((p, i) => {
    const base = {
      groupId: p.groupId,
      pbp: p.pbp,
      regular: null,
      lineup: [],
      fillIn: false,
      rank: null,
      tier: null,
      noPbp: false,
      noCrew: p.main.length === 0,
      people: sortedUnique(p.main),
      unknownPeople: sortedUnique(p.unknown),
      key: null,
    };
    if (base.noCrew) return base;
    if (p.pbp === null) {
      base.noPbp = true;
      base.key = `${p.groupId}:~${base.people.join('.')}`;
      return base;
    }
    const grp = groups.get(`${p.groupId}|${p.season}|${p.pbp}`);
    let regular = grp.modal;
    const booth = p.booth != null ? booths[p.booth] : null;
    if (booth) {
      if (booth.analyst != null) regular = people[booth.analyst];
      base.rank = booth.rank;
      base.tier = booth.tier;
    }
    regularOf[i] = regular;
    base.regular = regular;
    base.fillIn = p.analysts.length > 0 && !p.analysts.includes(regular);
    return base;
  });

  // Lineup once per group, from the group's regular analyst (A11).
  const lineups = new Map();
  groups.forEach((grp, gk) => {
    const regular = regularOf[grp.idx[0]];
    // Every game of a group shares the regular analyst unless a booth cites one; use the
    // first game's, as the booth is per (group, season, pbp, regular).
    let lineup = modalTuple(grp.tuples);
    if (regular != null && (lineup === null || !lineup.includes(regular))) {
      const seating = grp.tuples.filter((t) => t.includes(regular));
      lineup = modalTuple(seating) ?? [regular];
    }
    lineups.set(gk, lineup ?? []);
  });

  pass1.forEach((p, i) => {
    const o = out[i];
    if (o.noCrew || o.noPbp) return;
    const lineup = lineups.get(`${p.groupId}|${p.season}|${p.pbp}`);
    o.lineup = lineup;
    const rest = lineup.filter((s) => s !== p.pbp);
    o.key = `${p.groupId}:${[p.pbp, ...rest].join('.')}`;
  });
  return out;
}

/**
 * Parse a crew key from a URL; null when it fails the strict allowlist. Callers must also
 * require the key to exist in `crewIndex(data).crews`.
 * @param {string} str
 * @returns {{groupId: string, noPbp: boolean, slugs: string[]}|null}
 */
export function parseCrewKey(str) {
  if (typeof str !== 'string' || !CREW_KEY_RE.test(str)) return null;
  const at = str.indexOf(':');
  const groupId = str.slice(0, at);
  let rest = str.slice(at + 1);
  const noPbp = rest.startsWith('~');
  if (noPbp) rest = rest.slice(1);
  return { groupId, noPbp, slugs: rest.split('.') };
}

const indexCache = new WeakMap();

/**
 * Per-data crew index, memoized on the prepared data object. Call it lazily, never from the
 * map or scatter render path.
 * @param {object} data - a `prepareData` result.
 */
export function crewIndex(data) {
  const hit = indexCache.get(data);
  if (hit) return hit;
  const { lookups, t } = data;
  const input = {
    people: lookups.people.map((p) => p.id),
    networks: lookups.networks.map((n) => ({ id: n.id, family: n.family })),
    booths: lookups.booths,
    games: [],
  };
  for (let i = 0; i < data.n; i += 1) {
    input.games.push({
      season: t.season[i],
      network: t.network[i],
      booth: data.boothOf[i] >= 0 ? data.boothOf[i] : null,
      crew: t.crew[i],
    });
  }
  const perGame = groupTelecasts(input);
  const keys = perGame.map((g) => g.key);
  const crews = new Map();
  perGame.forEach((g, i) => {
    if (g.key === null) return;
    if (!crews.has(g.key)) {
      crews.set(g.key, {
        groupId: g.groupId,
        pbp: g.pbp,
        lineup: g.lineup,
        noPbp: g.noPbp,
        people: g.noPbp ? g.people : [g.pbp, ...g.lineup.filter((s) => s !== g.pbp)],
        games: [],
      });
    }
    crews.get(g.key).games.push(i);
  });
  const result = { perGame, keys, crews };
  indexCache.set(data, result);
  return result;
}
