/**
 * MLB module state (D-01, D-03, D-22). DOM-free.
 *
 * `booth` is an Apple booth index (string), `cell` a postseason cell key
 * (season-round-league), `game` a game index whose panel is open. Indexes are
 * in-memory only; the URL carries stable ids (see url-state.js). A selection
 * made by a view ({games, label}) is UI-only and never reaches the URL.
 */
import { boothLabelOf, cellLabel } from './data.js';

export const MLB_VIEWS = Object.freeze(['apple', 'postseason', 'scatter']);
export const MLB_STYPES = Object.freeze(['post', 'reg']);
export const MLB_SROUNDS = Object.freeze(['wild_card', 'division', 'lcs', 'world_series', 'tiebreak']);

export function defaultMlbState() {
  return { view: 'apple', booth: null, cell: null, game: null, selection: null, stype: null, sround: null };
}

/** Clamp and allowlist a state so every later reader can trust it. Never throws. */
export function canonicalMlbState(state, model) {
  const d = defaultMlbState();
  const s = state && typeof state === 'object' ? state : {};
  const boothNum = typeof s.booth === 'number' || typeof s.booth === 'string' ? String(s.booth) : '';
  const booth = /^\d+$/.test(boothNum) && Number(boothNum) < model.appleBooths.length ? String(Number(boothNum)) : null;
  const cell = typeof s.cell === 'string' && model.cells.has(s.cell) ? s.cell : null;
  const gameNum = Number(s.game);
  const game = s.game != null && Number.isInteger(gameNum) && gameNum >= 0 && gameNum < model.n ? gameNum : null;
  const stype = MLB_STYPES.includes(s.stype) ? s.stype : null;
  const sround = stype === 'post' && MLB_SROUNDS.includes(s.sround) ? s.sround : null;
  return {
    view: MLB_VIEWS.includes(s.view) ? s.view : d.view,
    booth,
    cell: booth == null ? cell : null,
    game,
    selection: s.selection && typeof s.selection === 'object' && Array.isArray(s.selection.games) ? s.selection : null,
    stype,
    sround,
  };
}

function newestFirst(model, list) {
  const c = model.cols;
  return [...list].sort((a, b) => {
    if (c.date[a] !== c.date[b]) return c.date[a] < c.date[b] ? 1 : -1;
    return b - a;
  });
}

/** Game indexes for the Matched games table: a view's selection, else the picked booth or cell. */
export function tableGames(model, state) {
  let base = null;
  if (state.selection) base = state.selection.games;
  else if (state.booth != null) base = model.appleBooths[Number(state.booth)].game_list;
  else if (state.cell != null) base = model.cells.get(state.cell).games;
  if (!base) return [];
  return newestFirst(model, base.filter((i) => Number.isInteger(i) && i >= 0 && i < model.n));
}

/** Name of the active selection, or ''. */
export function selectionLabel(model, state) {
  if (state.selection) return String(state.selection.label || '');
  if (state.booth != null) {
    const b = model.appleBooths[Number(state.booth)];
    return `${boothLabelOf(model, b.pbp, b.analyst)} (${b.rank_label})`;
  }
  if (state.cell != null) return cellLabel(model.cells.get(state.cell));
  return '';
}

/**
 * What survives a tab change (D-07): booth and cell are kept or dropped per
 * transition; a selection made by a view never outlives its view, except into
 * the Scatter, which reads whatever is picked. Pure; view ids are plain strings.
 */
export function carryOnViewChange(prev, next, s) {
  if (prev === next) return s;
  if (next === 'scatter') return s;
  if (prev === 'scatter' && next === 'apple') return { ...s, cell: null, selection: null };
  if (prev === 'scatter' && next === 'postseason') return { ...s, booth: null, selection: null };
  return { ...s, booth: null, cell: null, selection: null };
}
