// NFL Crews row model (Phase 15, D-01, D-03, D-22, NFL-03, NFL-04). DOM-free.
//
// A pooled row is one play-by-play voice + analyst pair per network group; shipped booth
// season rows pool across the Seasons range (exactly, from each season's n, mean and SE).
// A pick that cuts inside a booth season (Team, Category, an Announcers pick that matches
// another seat) recounts each row from its matched games and forces Raw.
import { classifyAnnouncers, computePicks, boothKeyOf, crewsScopeRows } from './picks.js';
import { crewsMode } from './mode.js';
import { NFL_NATURAL_DIR } from './state.js';
import { CREWS_LOW_N_MIN, defaultSort, rankRunOf, sortCrewRows } from '../../modules/crew-groups.js';

export const NFL_SORT_SPEC = Object.freeze({ naturalDir: NFL_NATURAL_DIR, defaultSort });

/**
 * Pool per-season residuals exactly (12-DECISIONS "Pooling check"). Parts are
 * `{ n, m, se }`; a null `m` is dropped with its n, and a null `se` counts as 0.
 * @returns {{ n: number, mean: number|null, se: number|null }}
 */
export function poolResidual(parts) {
  const used = parts.filter((p) => p.m != null && p.n > 0);
  const N = used.reduce((a, p) => a + p.n, 0);
  if (N === 0) return { n: 0, mean: null, se: null };
  const M = used.reduce((a, p) => a + p.n * p.m, 0) / N;
  if (N < 2) return { n: N, mean: M, se: null };
  let ss = 0;
  for (const p of used) {
    const se = p.se == null ? 0 : p.se;
    ss += (p.n - 1) * p.n * se * se + p.n * (p.m - M) * (p.m - M);
  }
  return { n: N, mean: M, se: Math.sqrt(ss / (N - 1) / N) };
}

/** n-weighted mean of `{ n, mean }` parts; a null mean leaves the pool. */
export function poolRaw(parts) {
  let n = 0;
  let sum = 0;
  for (const p of parts) {
    if (p.mean == null || !(p.n > 0)) continue;
    n += p.n;
    sum += p.n * p.mean;
  }
  return { n, mean: n ? sum / n : null };
}

/** Raw margin, excitement and viewers parts computed from game indexes. */
export function rawFromGames(model, games) {
  const c = model.cols;
  const acc = { margin: [0, 0], exc: [0, 0], viewers: [0, 0] };
  for (const g of games) {
    if (c.final_margin[g] != null) { acc.margin[0] += Math.abs(c.final_margin[g]); acc.margin[1] += 1; }
    if (c.excitement[g] != null) { acc.exc[0] += c.excitement[g]; acc.exc[1] += 1; }
    if (c.viewers[g] != null) { acc.viewers[0] += c.viewers[g]; acc.viewers[1] += 1; }
  }
  const out = {};
  for (const k of Object.keys(acc)) out[k] = { n: acc[k][1], mean: acc[k][1] ? acc[k][0] / acc[k][1] : null };
  return out;
}

const flag = (n) => n > 0 && n < CREWS_LOW_N_MIN;

function rawCell(p) {
  const blank = p.n === 0 || p.mean == null ? 'none' : null;
  return { mean: blank ? null : p.mean, n: p.n, flagged: !blank && flag(p.n), blank };
}

function adjCell(parts) {
  const r = poolResidual(parts);
  return { resid: r.mean, se: r.se, n: r.n, flagged: r.mean != null && flag(r.n) };
}

function modalEra(model, games) {
  const counts = new Map();
  for (const g of games) {
    if (model.cols.viewers[g] == null) continue;
    const e = model.cols.era[g];
    counts.set(e, (counts.get(e) ?? 0) + 1);
  }
  let best = null;
  for (const [e, k] of counts) {
    if (best === null || k > counts.get(best) || (k === counts.get(best) && e < best)) best = e;
  }
  return best;
}

function newestFirst(model, games) {
  const d = model.cols.date;
  return games.slice().sort((a, b) => (d[a] < d[b] ? 1 : d[a] > d[b] ? -1 : b - a));
}

/**
 * Build the NFL Crews rows for the current state.
 * @returns {{ perSeason: boolean, mode: 'raw'|'adjusted', reason: string|null,
 *   rows: object[], totalRows: number }}
 */
export function buildNflCrewRows(model, state) {
  const perSeason = state.perseason !== false && state.seasons[1] > state.seasons[0];
  const scope = crewsScopeRows(model, state);
  const announcers = classifyAnnouncers(model, state, scope);
  const picks = computePicks(model, state);
  const subset = (state.teams || []).length > 0 || (state.cats || []).length > 0
    || announcers === 'subset';
  let kept = scope;
  if (announcers === 'rowfilter') {
    kept = scope.filter((r) => r.pbp_person != null && picks.peopleIdx.has(r.pbp_person));
  }
  const m = crewsMode(state, { announcers });
  const adjustedMode = m.effective === 'adjusted' && !subset;

  const slug = (i) => (i == null ? 'null' : model.people[i].id);
  const groups = new Map();
  for (const r of kept) {
    const gid = model.networkGroups[r.network_group].id;
    const base = `${gid}:${slug(r.pbp_person)}.${slug(r.analyst_person)}`;
    const key = perSeason ? `${base}:${r.season}` : base;
    if (!groups.has(key)) groups.set(key, { rowKey: key, parts: [] });
    groups.get(key).parts.push(r);
  }

  const rows = [];
  for (const g of groups.values()) {
    const first = g.parts[0];
    const group = model.networkGroups[first.network_group];
    const pbp = first.pbp_person == null ? null : model.people[first.pbp_person];
    const analyst = first.analyst_person == null ? null : model.people[first.analyst_person];
    const seasons = g.parts.map((p) => p.season).sort((a, b) => a - b);

    // Games and the era band of each part season.
    const matchedOf = (p) => (subset ? (p.gameList || []).filter((i) => picks.matched[i]) : (p.gameList || []));
    const games = g.parts.flatMap(matchedOf);
    if (subset && games.length === 0) continue;
    const bands = new Set();
    for (const p of g.parts) {
      const e = modalEra(model, matchedOf(p));
      if (e !== null) bands.add(e);
    }

    let margin;
    let exc;
    let viewers;
    if (subset) {
      const raw = rawFromGames(model, games);
      margin = rawCell(raw.margin);
      exc = rawCell(raw.exc);
      viewers = rawCell(raw.viewers);
    } else {
      margin = rawCell(poolRaw(g.parts.map((p) => ({ n: p.raw_n_margin, mean: p.raw_mean_abs_margin }))));
      exc = rawCell(poolRaw(g.parts.map((p) => ({ n: p.raw_n_excitement, mean: p.raw_mean_excitement }))));
      viewers = rawCell(poolRaw(g.parts.map((p) => ({ n: p.raw_n_viewers, mean: p.raw_mean_viewers }))));
    }
    if (!perSeason && viewers.blank === null && bands.size > 1) {
      viewers = { mean: null, n: viewers.n, flagged: false, blank: 'era' };
    }

    const adjusted = subset
      ? { margin: { resid: null, se: null, n: 0, flagged: false }, exc: { resid: null, se: null, n: 0, flagged: false } }
      : {
        margin: adjCell(g.parts.map((p) => ({ n: p.adj_n_margin, m: p.adj_margin_resid, se: p.adj_margin_se }))),
        exc: adjCell(g.parts.map((p) => ({ n: p.adj_n_excitement, m: p.adj_excitement_resid, se: p.adj_excitement_se }))),
      };

    const bySeason = new Map();
    for (const p of g.parts) {
      if (p.rank == null) continue;
      bySeason.set(p.season, p.rank === 1 && p.rank_source !== 'games' ? 0 : p.rank);
    }
    const ranks = g.parts.filter((p) => p.rank != null).map((p) => p.rank);
    const analystIdx = first.analyst_person;
    const fillIn = new Set();
    if (analystIdx != null) {
      for (const i of games) {
        const a = (model.cols.crew[i] || []).find((c) => c.role === 'analyst');
        if (a && a.person !== analystIdx) fillIn.add(i);
      }
    }
    rows.push({
      rowKey: g.rowKey,
      boothKey: boothKeyOf(model, first),
      groupId: group.id,
      network: { id: group.id, name: group.name },
      pbp: pbp && { id: pbp.id, name: pbp.name },
      analyst: analyst && { id: analyst.id, name: analyst.name },
      names: analyst ? `${pbp ? pbp.name : ''} and ${analyst.name}` : (pbp ? pbp.name : ''),
      season: perSeason ? first.season : null,
      seasons,
      games,
      gamesCount: games.length,
      gamesList: newestFirst(model, games),
      fillIn,
      windowGames: new Set(games.filter((i) => model.cols.scope[i] === 'window')),
      margin,
      exc,
      viewers,
      adjusted,
      rankRun: rankRunOf(bySeason, perSeason, (v) => (v === 0 ? 'Lead' : `No. ${v}`)),
      rankKey: ranks.length ? Math.min(...ranks) : null,
      published: g.parts.some((p) => p.rank_source === 'published'),
    });
  }
  return {
    perSeason,
    mode: adjustedMode ? 'adjusted' : 'raw',
    reason: m.reason,
    rows,
    totalRows: rows.length,
  };
}

/**
 * Sort Crews rows with the shared buckets (D-03). In Adjusted mode the Margin and
 * Excitement sorts read the residual cells. A Season sort on pooled rows is the default.
 */
export function sortNflCrewRows(rows, csort, perSeason, mode = 'raw') {
  let sort = csort ?? defaultSort(perSeason);
  if (!perSeason && sort.key === 'season') sort = defaultSort(false);
  if (mode === 'adjusted' && (sort.key === 'margin' || sort.key === 'exc')) {
    const proxied = rows.map((r) => ({
      ...r,
      [sort.key]: { mean: r.adjusted[sort.key].resid, n: r.adjusted[sort.key].n, flagged: r.adjusted[sort.key].flagged },
    }));
    const sorted = sortCrewRows(proxied, sort, NFL_NATURAL_DIR);
    const byKey = new Map(rows.map((r) => [r.rowKey, r]));
    return sorted.map((r) => byKey.get(r.rowKey));
  }
  return sortCrewRows(rows, sort, NFL_NATURAL_DIR);
}
