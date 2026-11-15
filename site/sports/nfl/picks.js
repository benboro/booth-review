// NFL pick layer (Phase 15): one DOM-free answer to "which games does this pick match",
// so every NFL view reads the same mask. Seasons, Networks, Team and Category decide whether a
// game passes; Announcers and Booths decide whether a passing game is matched (their
// intersection when both are set, U-05).
import { gamePasses, boothGames, networkIdOf } from './state.js';

const MEMO_SIZE = 4;
let memo = [];

/** The Booths-pick key of a booth row: "<group id>:<pbp person id>", null without a pbp. */
export function boothKeyOf(model, row) {
  if (row.pbp_person == null) return null;
  return `${model.networkGroups[row.network_group].id}:${model.people[row.pbp_person].id}`;
}

/**
 * Per-game masks for the current pick. `passes` is Seasons AND Networks AND Team AND Category;
 * `matched` further requires the Announcers pick (any seat) and the Booths pick.
 * Memoized on the pick signature and the model identity.
 */
export function computePicks(model, state) {
  const signature = JSON.stringify([
    state.seasons, state.teams, state.cats, state.people, state.booths, state.networks ?? null,
  ]);
  const hit = memo.find((m) => m.model === model && m.result.signature === signature);
  if (hit) return hit.result;

  const n = model.n;
  const crew = model.cols.crew;
  const peopleIdx = new Set();
  for (const id of state.people || []) {
    const k = model.personIndex.get(id);
    if (k !== undefined) peopleIdx.add(k);
  }
  const hasPeople = (state.people || []).length > 0;
  const hasBooths = (state.booths || []).length > 0;
  const boothSet = hasBooths ? new Set(boothGames(model, state.booths)) : null;

  const passes = new Uint8Array(n);
  const matched = new Uint8Array(n);
  let matchedCount = 0;
  for (let i = 0; i < n; i++) {
    if (!gamePasses(model, state, i)) continue;
    passes[i] = 1;
    if (hasPeople && !(crew[i] || []).some((m) => peopleIdx.has(m.person))) continue;
    if (hasBooths && !boothSet.has(i)) continue;
    matched[i] = 1;
    matchedCount++;
  }
  const result = {
    signature, passes, matched, hasPeople, hasBooths,
    hasPick: hasPeople || hasBooths, peopleIdx, boothSet, matchedCount,
  };
  // A render asks for the pick with and without Team (the all-games bars) and without Networks
  // (the Networks list's counts), so the last few answers are kept, newest first.
  memo.unshift({ model, result });
  memo.length = Math.min(memo.length, MEMO_SIZE);
  return result;
}

/**
 * How a Networks pick meets one booth row: 'in' (no pick, or every game of the row is on a
 * picked network), 'out' (none is) or 'cut' (some are, so the pick cuts inside the booth season).
 * A lineup-only row (no games yet) is 'in' when any network of its group is picked.
 */
export function networksRowState(model, state, row) {
  const picked = state.networks;
  if (picked == null) return 'in';
  const games = row.gameList || [];
  if (!games.length) {
    const members = model.networkGroups[row.network_group].members || [];
    return members.some((m) => picked.includes(model.networks[m].id)) ? 'in' : 'out';
  }
  let on = 0;
  for (const g of games) if (picked.includes(networkIdOf(model, g))) on += 1;
  if (on === 0) return 'out';
  return on === games.length ? 'in' : 'cut';
}

/**
 * The booth rows in scope on Crews: Seasons range, the Booths row filter, then the Networks
 * pick, which drops a row with no game on a picked network.
 */
export function crewsScopeRows(model, state) {
  const booths = state.booths || [];
  return model.booths.filter((r) => {
    if (r.season < state.seasons[0] || r.season > state.seasons[1]) return false;
    if (networksRowState(model, state, r) === 'out') return false;
    if (!booths.length) return true;
    const k = boothKeyOf(model, r);
    return k !== null && booths.includes(k);
  });
}

/** Whether the Networks pick cuts inside any in-scope booth row (some of its games, not all). */
export function networksCutRows(model, state, scopeRows) {
  return state.networks != null && scopeRows.some((r) => networksRowState(model, state, r) === 'cut');
}

/**
 * How an Announcers pick acts on Crews (12-DECISIONS NFL matrix, RESEARCH A1):
 * 'none' without a pick; 'subset' when a picked person appears on any game of any
 * in-scope row in a crew entry other than as that row's play-by-play voice (the pick
 * then cuts inside the booth season); otherwise 'rowfilter'.
 */
export function classifyAnnouncers(model, state, scopeRows) {
  const ids = state.people || [];
  if (!ids.length) return 'none';
  const picked = new Set();
  for (const id of ids) {
    const k = model.personIndex.get(id);
    if (k !== undefined) picked.add(k);
  }
  const crew = model.cols.crew;
  for (const r of scopeRows) {
    for (const g of r.gameList || []) {
      for (const m of crew[g] || []) {
        if (picked.has(m.person) && m.person !== r.pbp_person) return 'subset';
      }
    }
  }
  return 'rowfilter';
}
