// MLB Apple crews row model (Phase 16, D-11, D-14, N6). DOM-free, MLB-only, no NFL imports.
//
// One row per Apple booth. Analysts are tallied from the booth's games (N6); Stakes and
// Excitement carry their own sample size and flag (never per row); the sort spec keeps
// pending and blank values last in both directions.

/** Booth standing order: Lead 0, '#n' n-1, anything else last. */
export function RANK_ORDER(label) {
  if (label === 'Lead') return 0;
  const m = /^#(\d+)$/.exec(String(label));
  return m ? Number(m[1]) - 1 : 999;
}

/** Game indexes newest first: date descending, then index descending. */
function newestFirst(model, list) {
  const d = model.cols.date;
  return [...list].sort((a, b) => {
    if (d[a] !== d[b]) return d[a] < d[b] ? 1 : -1;
    return b - a;
  });
}

/**
 * Analysts across a booth's games, most games first, ties by name ascending. A one-game
 * fill-in counts like any other analyst; pbp members and unknown roles are ignored.
 * @returns {{ person: number, name: string, n: number }[]}
 */
export function analystTally(model, gameList) {
  const counts = new Map();
  for (const g of gameList) {
    const crew = model.cols.crew[g];
    if (!Array.isArray(crew)) continue;
    for (const m of crew) {
      if (!m || m.role !== 'analyst') continue;
      counts.set(m.person, (counts.get(m.person) ?? 0) + 1);
    }
  }
  const out = [];
  for (const [person, n] of counts) {
    const p = model.people[person];
    out.push({ person, name: p ? p.name : '', n });
  }
  return out.sort((a, b) => b.n - a.n || a.name.localeCompare(b.name));
}

function modalNetwork(model, games) {
  const counts = new Map();
  for (const g of games) {
    const idx = model.cols.network[g];
    if (idx == null) continue;
    counts.set(idx, (counts.get(idx) ?? 0) + 1);
  }
  let best = null;
  for (const [idx, k] of counts) {
    if (best === null || k > counts.get(best) || (k === counts.get(best) && idx < best)) best = idx;
  }
  return best == null ? null : model.networks[best];
}

function cell(model, pending, value, n) {
  if (pending) return { value: null, n, flagged: false, pending: true };
  const flagged = n > 0 && n < model.constants.low_n_threshold;
  return { value: value ?? null, n, flagged, pending: false };
}

/**
 * Build the Apple rows for the given mode. Excitement's n is the booth's games with a
 * non-null excitement figure (raw) or with both excitement and stakes (adjusted).
 */
export function buildAppleRows(model, { adjusted }) {
  const c = model.cols;
  return model.appleBooths.map((b, k) => {
    const list = b.game_list || [];
    const pending = b.quality_status === 'pending';
    let excN = 0;
    let adjExcN = 0;
    for (const g of list) {
      if (c.wp_excitement[g] == null) continue;
      excN += 1;
      if (c.stakes[g] != null) adjExcN += 1;
    }
    const analysts = analystTally(model, list);
    const pbpName = model.people[b.pbp] ? model.people[b.pbp].name : '';
    return {
      rowKey: String(k),
      rank: b.rank_label,
      rankOrder: RANK_ORDER(b.rank_label),
      pbpName,
      analysts,
      names: [pbpName, ...analysts.map((a) => a.name)],
      games: newestFirst(model, list),
      network: modalNetwork(model, list),
      gamesCount: b.games,
      listed: b.crew_listed,
      relay: b.relay_crews,
      prior: b.strength_prior,
      stakes: cell(model, pending, adjusted ? b.adj_stakes : b.raw_stakes, b.raw_stakes_n),
      excitement: cell(
        model,
        pending,
        adjusted ? b.adj_excitement : b.raw_excitement,
        adjusted ? adjExcN : excN,
      ),
    };
  });
}

export const APPLE_SORT_SPEC = Object.freeze({
  naturalDir: Object.freeze({
    position: 'asc',
    booth: 'asc',
    network: 'asc',
    games: 'desc',
    listed: 'desc',
    stakes: 'desc',
    excitement: 'desc',
    prior: 'desc',
  }),
  defaultSort: () => ({ key: 'position', dir: 'asc' }),
});

const QUALITY_KEYS = new Set(['stakes', 'excitement', 'prior']);

/** [bucket, value]: 0 full-n value, 1 flagged value, 2 pending or blank. */
function qualityOf(row, key) {
  if (key === 'prior') {
    return row.prior == null || !Number.isFinite(row.prior) ? [2, null] : [0, row.prior];
  }
  const c = row[key];
  if (!c || c.pending || c.value == null || !Number.isFinite(c.value)) return [2, null];
  return [c.flagged ? 1 : 0, c.value];
}

/** Rows sorted by `sort` ({ key, dir }); null uses the default. Returns a new array. */
export function sortAppleRows(rows, sort) {
  const { key, dir } = sort || APPLE_SORT_SPEC.defaultSort();
  const sign = dir === 'desc' ? -1 : 1;
  const tie = (a, b) => b.gamesCount - a.gamesCount || a.rankOrder - b.rankOrder;
  const cmp = (a, b) => {
    if (QUALITY_KEYS.has(key)) {
      const [ba, va] = qualityOf(a, key);
      const [bb, vb] = qualityOf(b, key);
      if (ba !== bb) return ba - bb;
      if (va !== vb && va != null) return sign * (va - vb) || tie(a, b);
      return tie(a, b);
    }
    let r = 0;
    if (key === 'position') r = a.rankOrder - b.rankOrder;
    else if (key === 'booth') r = a.names.join(' ').localeCompare(b.names.join(' '));
    else if (key === 'network') r = String(a.network?.name ?? '').localeCompare(String(b.network?.name ?? ''));
    else if (key === 'games') r = a.gamesCount - b.gamesCount;
    else if (key === 'listed') r = a.listed - b.listed;
    return sign * r || tie(a, b);
  };
  return [...rows].sort(cmp);
}
