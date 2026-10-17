/**
 * MLB module state (D-01, D-03, D-22). DOM-free.
 *
 * `booth` is an Apple booth index (string), `cell` a postseason cell key
 * (season-round-league), `game` a game index whose panel is open. Indexes are
 * in-memory only; the URL carries stable ids (see url-state.js). A selection
 * made by a view ({games, label}) is UI-only and never reaches the URL.
 */
import { boothLabelOf, cellLabel } from './data.js';

export const MLB_VIEWS = Object.freeze(['apple', 'postseason']);

export function defaultMlbState() {
  return { view: 'apple', booth: null, cell: null, game: null, selection: null };
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
  return {
    view: MLB_VIEWS.includes(s.view) ? s.view : d.view,
    booth,
    cell: booth == null ? cell : null,
    game,
    selection: s.selection && typeof s.selection === 'object' && Array.isArray(s.selection.games) ? s.selection : null,
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
