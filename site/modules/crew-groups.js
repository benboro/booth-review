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

/** The sort a Crews table opens on: Season newest first when rows are per season, else Games called descending. */
export function defaultSort(perSeason) {
  return perSeason ? { key: 'season', dir: 'desc' } : { key: 'games', dir: 'desc' };
}

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
      // A null booth analyst is a cited regular who is on no shipped crew row, so on none
      // of this game's seats: the client cannot name them, and (as in booths.py) any game
      // with an analyst is a fill-in. The lineup then falls back to the group's modal one.
      regular = booth.analyst != null ? people[booth.analyst] : null;
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

// ---------------------------------------------------------------------------------------
// Row model (Phase 14, plan 14-03): Crew, PBP and Analyst rows, pooled or per season.
// Pure and DOM-free; the Crews table (14-07) only renders what these return.
// ---------------------------------------------------------------------------------------

/**
 * Fewest figures a metric needs before its cell stops carrying the `n < 8` flag (D-11).
 * Mirrors the NFL table's 12-D-20 choice and reverses the 2026-10-18 `CREWS_LOW_N = 0`
 * decision for the old family-season table, which this table replaces.
 */
export const CREWS_LOW_N_MIN = 8;

/**
 * Fallback for the first season of the CFBD excitement model break (A4) when no game in
 * the data carries a `model_break` flag. The real boundary is derived from the data.
 */
const MODEL_BREAK_SEASON_FALLBACK = 2025;

const breakCache = new WeakMap();

/** First season whose rated games carry a `model_break` flag, else the fallback (A4). */
export function modelBreakSeason(data) {
  if (breakCache.has(data)) return breakCache.get(data);
  const kinds = data.lookups.flags.map((f) => f.kind);
  let min = null;
  for (let i = 0; i < data.n; i += 1) {
    if (!data.rated[i]) continue;
    for (const f of data.t.flags[i] ?? []) {
      if (kinds[f] === 'model_break' && (min === null || data.t.season[i] < min)) {
        min = data.t.season[i];
      }
    }
  }
  const season = min ?? MODEL_BREAK_SEASON_FALLBACK;
  breakCache.set(data, season);
  return season;
}

const bandCache = new WeakMap();

/**
 * Nielsen measurement band of each season, read from the shipped `era` flags (no dates
 * hard-coded). A season counts as one band, as the NFL views do ("bands align to whole
 * seasons"): the era carried by most of the season's rated games, ties to the era that
 * starts later. A Week 0-1 game dated before a switch (2025-09-01) never splits a season.
 * @returns {Map<number, number>} season -> era flag index
 */
export function seasonBands(data) {
  const hit = bandCache.get(data);
  if (hit) return hit;
  const { t } = data;
  const kinds = data.lookups.flags.map((f) => f.kind);
  const count = new Map(); // season -> Map(flag -> n)
  const first = new Map(); // flag -> earliest date
  for (let i = 0; i < data.n; i += 1) {
    if (!data.rated[i]) continue;
    for (const f of t.flags[i] ?? []) {
      if (kinds[f] !== 'era') continue;
      const s = t.season[i];
      if (!count.has(s)) count.set(s, new Map());
      count.get(s).set(f, (count.get(s).get(f) ?? 0) + 1);
      if (!first.has(f) || t.date[i] < first.get(f)) first.set(f, t.date[i]);
    }
  }
  const out = new Map();
  for (const [s, flags] of count) {
    let best = null;
    for (const [f, n] of flags) {
      if (best === null) best = f;
      else {
        const bn = flags.get(best);
        if (n > bn || (n === bn && first.get(f) > first.get(best))) best = f;
      }
    }
    out.set(s, best);
  }
  bandCache.set(data, out);
  return out;
}

const cmpStr = (a, b) => (a < b ? -1 : a > b ? 1 : 0);

function joinNames(names) {
  if (names.length <= 1) return names.join('');
  return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
}

/** Display name for a person slug. */
function nameOf(data, slug) {
  const idx = data.personIndexById.get(slug);
  return idx === undefined ? slug : data.lookups.people[idx].name;
}

/**
 * Rank run text (D-04): `Lead 2019–24, No. 2 2025`; per season rows print one token.
 * `labelOf` maps a rank number to its text, so a sport can name its ranks its own way.
 */
export function rankRunOf(bySeason, perSeason, labelOf = (r) => (r === 1 ? 'Lead' : `No. ${r}`)) {
  const seasons = Array.from(bySeason.keys()).sort((a, b) => a - b);
  if (!seasons.length) return '';
  const label = labelOf;
  if (perSeason) return label(bySeason.get(seasons[0]));
  const runs = [];
  for (const s of seasons) {
    const last = runs[runs.length - 1];
    const l = label(bySeason.get(s));
    if (last && last.label === l && last.end === s - 1) last.end = s;
    else runs.push({ label: l, start: s, end: s });
  }
  const span = (r) => {
    if (r.start === r.end) return `${r.start}`;
    const sameCentury = Math.floor(r.start / 100) === Math.floor(r.end / 100);
    return `${r.start}–${sameCentury ? String(r.end % 100).padStart(2, '0') : r.end}`;
  };
  return runs.map((r) => `${r.label} ${span(r)}`).join(', ');
}

function metric(mean, n, blank) {
  const shown = blank ? null : mean;
  return { mean: shown, n, flagged: !blank && n > 0 && n < CREWS_LOW_N_MIN, blank: blank ?? null };
}

/** exc / viewers metric objects for a row's games. */
function metricsOf(data, games) {
  const { t } = data;
  const boundary = modelBreakSeason(data);
  const bands = seasonBands(data);
  let excSum = 0;
  let excN = 0;
  let before = false;
  let after = false;
  let vSum = 0;
  let vN = 0;
  const eras = new Set();
  for (const i of games) {
    const e = t.excitement[i];
    if (e != null) {
      excSum += e;
      excN += 1;
      if (t.season[i] < boundary) before = true;
      else after = true;
    }
    if (data.rated[i] && t.viewers[i] != null) {
      vSum += t.viewers[i];
      vN += 1;
      const band = bands.get(t.season[i]);
      if (band !== undefined) eras.add(band);
    }
  }
  const excBlank = excN === 0 ? 'none' : before && after ? 'break' : null;
  const vBlank = vN === 0 ? 'none' : eras.size > 1 ? 'era' : null;
  return {
    exc: metric(excN ? excSum / excN : null, excN, excBlank),
    viewers: metric(vN ? vSum / vN : null, vN, vBlank),
  };
}

/** Primary network (most games, ties to the lower id) and the full list. */
function networkOf(data, games) {
  const counts = new Map();
  for (const i of games) {
    const id = data.lookups.networks[data.t.network[i]].id;
    counts.set(id, (counts.get(id) ?? 0) + 1);
  }
  const all = Array.from(counts.keys()).sort((a, b) => counts.get(b) - counts.get(a) || cmpStr(a, b));
  const primaryId = all[0] ?? null;
  const net = data.lookups.networks.find((n) => n.id === primaryId);
  return { primaryId, name: net ? net.name : '', count: all.length, all };
}

/** Newest first by date, then by index. */
function newestFirst(data, games) {
  return games.slice().sort((a, b) => {
    const da = data.t.date[a];
    const db = data.t.date[b];
    return da < db ? 1 : da > db ? -1 : b - a;
  });
}

/** Main-feed slugs of one role on game `i`, in crew order. */
function mainSlugs(data, i, role) {
  const out = [];
  for (const e of data.t.crew[i]) {
    if (e.feed === 'main' && e.role === role) out.push(data.lookups.people[e.person].id);
  }
  return out;
}

const defaultTie = (a, b) => b.gamesCount - a.gamesCount || cmpStr(a.names, b.names);

/** Per season rows open newest season first, then Games called descending; pooled rows by Games called. */
const seasonDefault = (a, b) => b.season - a.season || defaultTie(a, b);
const defaultOf = (rows) => (rows.length && rows[0].season != null ? seasonDefault : defaultTie);

/**
 * Build the Crews rows from the games that pass the master filters.
 * @param {object} data - a `prepareData` result.
 * @param {{passesFilters: Uint8Array}} view - a `computeView` result.
 * @param {{mode?: 'crew'|'pbp'|'analyst', perSeason?: boolean}} [opts]
 * @returns {{mode: string, perSeason: boolean, rows: Array<object>, leftOut: number,
 *   totalRows: number}}
 */
export function buildCrewRows(data, view, { mode = 'crew', perSeason = false } = {}) {
  const { t } = data;
  const index = crewIndex(data);
  const buckets = new Map();
  let leftOut = 0;
  const add = (rowKey, meta, i) => {
    let b = buckets.get(rowKey);
    if (!b) {
      b = { rowKey, meta, games: [] };
      buckets.set(rowKey, b);
    }
    b.games.push(i);
  };
  const suffix = (i) => (perSeason ? `|${t.season[i]}` : '');

  for (let i = 0; i < data.n; i += 1) {
    if (!view.passesFilters[i]) continue;
    const pg = index.perGame[i];
    if (mode === 'crew') {
      if (pg.noCrew) {
        leftOut += 1;
        continue;
      }
      add(pg.key + suffix(i), { crewKey: pg.key }, i);
    } else if (mode === 'pbp') {
      if (pg.pbp === null) {
        leftOut += 1;
        continue;
      }
      add(`pbp:${pg.pbp}${suffix(i)}`, { slug: pg.pbp }, i);
    } else {
      const analysts = mainSlugs(data, i, 'analyst');
      if (!analysts.length) {
        leftOut += 1;
        continue;
      }
      for (const slug of new Set(analysts)) add(`analyst:${slug}${suffix(i)}`, { slug }, i);
    }
  }

  const rows = [];
  for (const b of buckets.values()) {
    const games = newestFirst(data, b.games);
    const season = perSeason ? t.season[games[0]] : null;
    const base = {
      rowKey: b.rowKey,
      season,
      games,
      gamesCount: games.length,
      network: networkOf(data, games),
      ...metricsOf(data, games),
    };
    if (mode === 'crew') {
      const crew = index.crews.get(b.meta.crewKey);
      const unknownCount = new Map();
      if (crew.noPbp) {
        for (const i of games) {
          for (const s of index.perGame[i].unknownPeople) {
            unknownCount.set(s, (unknownCount.get(s) ?? 0) + 1);
          }
        }
      }
      const people = crew.people.map((slug) => {
        const k = unknownCount.get(slug) ?? 0;
        const unknownTag = k === 0 ? null : k === games.length ? 'all' : { k, n: games.length };
        return { slug, name: nameOf(data, slug), unknownTag };
      });
      const rankBySeason = new Map();
      for (const i of games) {
        const r = index.perGame[i].rank;
        if (r == null) continue;
        const s = t.season[i];
        rankBySeason.set(s, Math.min(rankBySeason.get(s) ?? r, r));
      }
      const ranks = Array.from(rankBySeason.values());
      rows.push({
        ...base,
        crewKey: b.meta.crewKey,
        groupId: crew.groupId,
        family: BOOTH_FAMILIES.has(crew.groupId) ? crew.groupId : null,
        people,
        names: joinNames(people.map((p) => p.name)),
        rankRun: rankRunOf(rankBySeason, perSeason),
        rankKey: ranks.length ? Math.min(...ranks) : null,
        fillInGames: new Set(games.filter((i) => index.perGame[i].fillIn)),
      });
    } else {
      const partnerCount = new Map();
      for (const i of games) {
        const others = mode === 'pbp' ? mainSlugs(data, i, 'analyst') : [index.perGame[i].pbp];
        for (const s of new Set(others)) {
          if (s != null && s !== b.meta.slug) partnerCount.set(s, (partnerCount.get(s) ?? 0) + 1);
        }
      }
      const partners = Array.from(partnerCount, ([slug, n]) => ({
        slug,
        name: nameOf(data, slug),
        games: n,
      })).sort((a, c) => c.games - a.games || cmpStr(a.name, c.name));
      const name = nameOf(data, b.meta.slug);
      rows.push({
        ...base,
        personSlug: b.meta.slug,
        crewKey: null,
        groupId: null,
        family: null,
        people: [{ slug: b.meta.slug, name, unknownTag: null }],
        names: name,
        partners,
        partnersShown: partners.slice(0, 3),
        partnersMore: Math.max(0, partners.length - 3),
        rankRun: '',
        rankKey: null,
        fillInGames: new Set(),
      });
    }
  }
  rows.sort(perSeason ? seasonDefault : defaultTie);
  return { mode, perSeason, rows, leftOut, totalRows: rows.length };
}

/**
 * Sort rows without touching the input. Metric keys bucket full-n values, then flagged
 * values, then blanks (D-12), and only reverse inside the first two buckets; `rank` puts
 * unranked rows last in both directions. Ties fall back to games desc, then name asc.
 * `booth` sorts like `crew` (by names) and `margin` like `exc`/`viewers` (NFL keys).
 * @param {Array<object>} rows
 * @param {{key: string, dir?: 'asc'|'desc'}|null} sort - null is the default sort.
 * @param {Readonly<Record<string, 'asc'|'desc'>>} [naturalDir] - the sport's natural directions.
 */
export function sortCrewRows(rows, sort, naturalDir = NATURAL_DIR) {
  if (!sort) return rows.slice().sort(defaultOf(rows));
  const dir = (sort.dir ?? naturalDir[sort.key]) === 'desc' ? -1 : 1;
  const bucket = (m) => (m.mean == null ? 2 : m.flagged ? 1 : 0);
  const cmp = (a, b) => {
    switch (sort.key) {
      case 'crew':
      case 'booth':
        return dir * cmpStr(a.names, b.names);
      case 'season': {
        if (a.season == null || b.season == null) return (a.season == null) - (b.season == null);
        return dir * (a.season - b.season);
      }
      case 'network':
        return dir * cmpStr(a.network.name, b.network.name);
      case 'games':
        return dir * (a.gamesCount - b.gamesCount);
      case 'rank': {
        if (a.rankKey == null || b.rankKey == null) return (a.rankKey == null) - (b.rankKey == null);
        return dir * (a.rankKey - b.rankKey);
      }
      case 'exc':
      case 'margin':
      case 'viewers': {
        const ma = a[sort.key];
        const mb = b[sort.key];
        const ba = bucket(ma);
        const bb = bucket(mb);
        if (ba !== bb) return ba - bb;
        return ba === 2 ? 0 : dir * (ma.mean - mb.mean);
      }
      default:
        return 0;
    }
  };
  return rows.slice().sort((a, b) => cmp(a, b) || defaultTie(a, b));
}
