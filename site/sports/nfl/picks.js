// NFL pick layer (Phase 15): one DOM-free answer to "which games does this pick match",
// so every NFL view reads the same mask. Seasons, Team and Category decide whether a game
// passes; Announcers and Booths decide whether a passing game is matched (their
// intersection when both are set, U-05).
import { gamePasses, boothGames } from './state.js';

let memo = null;

/** The Booths-pick key of a booth row: "<group id>:<pbp person id>", null without a pbp. */
export function boothKeyOf(model, row) {
  if (row.pbp_person == null) return null;
  return `${model.networkGroups[row.network_group].id}:${model.people[row.pbp_person].id}`;
}

/**
 * Per-game masks for the current pick. `passes` is Seasons AND Team AND Category;
 * `matched` further requires the Announcers pick (any seat) and the Booths pick.
 * Memoized on the pick signature and the model identity.
 */
export function computePicks(model, state) {
  const signature = JSON.stringify([state.seasons, state.teams, state.cats, state.people, state.booths]);
  if (memo && memo.model === model && memo.result.signature === signature) return memo.result;

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
  memo = { model, result };
  return result;
}

/** The booth rows in scope on Crews: Seasons range, then the Booths row filter. */
export function crewsScopeRows(model, state) {
  const booths = state.booths || [];
  return model.booths.filter((r) => {
    if (r.season < state.seasons[0] || r.season > state.seasons[1]) return false;
    if (!booths.length) return true;
    const k = boothKeyOf(model, r);
    return k !== null && booths.includes(k);
  });
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
