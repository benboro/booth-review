/**
 * MLB Scatter item model (D-05, D-07, D-08, D-09). DOM-free; MLB-only; no NFL imports.
 *
 * One item per game that passes the Season type / Round control. Every item has
 * exactly one placement, so no game is dropped and a missing value is never
 * drawn at 0: 'plot' (both values), 'bottom' (no viewers), 'left' (no
 * excitement) or 'corner' (neither).
 */
import { MLB_SROUNDS, tableGames } from './state.js';

export const MLB_FAMILY_ORDER = Object.freeze(['apple', 'fox', 'tbs', 'disney', 'nbc', 'cbs', 'other']);

export const MLB_FAMILY_LABELS = Object.freeze({
  apple: 'Apple TV',
  fox: 'FOX/FS1',
  tbs: 'TBS',
  disney: 'ESPN/ABC',
  nbc: 'NBC/Peacock',
  cbs: 'CBS',
  other: 'Other',
});

// Chart colour slots: Apple borrows the conference slot and TBS the wbd slot, so the
// shared palette is never edited.
const COLOR_SLOTS = Object.freeze({
  apple: 'conference', tbs: 'wbd', disney: 'disney', fox: 'fox', cbs: 'cbs', nbc: 'nbc',
});

/** Network family of game i; 'other' for no network or a family outside the order. */
export function familyOf(model, i) {
  const idx = model.cols.network[i];
  if (idx == null) return 'other';
  const net = model.networks[idx];
  const family = net && net.family;
  return MLB_FAMILY_ORDER.includes(family) ? family : 'other';
}

/** Palette slot for a family. */
export function colorSlotOf(family) {
  return Object.prototype.hasOwnProperty.call(COLOR_SLOTS, family) ? COLOR_SLOTS[family] : 'other';
}

/** The Season type / Round control (D-09): narrows the items only. */
export function passesControl(model, i, state) {
  const round = model.cols.round[i];
  if (state.stype === 'reg') return round === 'regular';
  if (state.stype === 'post') {
    if (!MLB_SROUNDS.includes(round)) return false;
    return state.sround ? round === state.sround : true;
  }
  return true;
}

/** Deterministic spread along a strip so overlapping marks stay countable. */
export function stripJitter(i) {
  return 0.12 + ((i * 0.6180339887) % 1) * 0.76;
}

export function buildScatterItems(model, state, { hiddenFamilies } = {}) {
  const c = model.cols;
  const hiddenSet = hiddenFamilies || new Set();
  const selecting = state.booth != null || state.cell != null || state.selection != null;
  const matchedSet = selecting ? new Set(tableGames(model, state)) : null;
  const items = [];
  const present = new Set();
  const counts = { total: 0, plotted: 0, noRating: 0, noExcitement: 0, neither: 0, matched: 0, faded: 0 };
  for (let i = 0; i < model.n; i += 1) {
    if (!passesControl(model, i, state)) continue;
    const x = c.viewers[i] == null ? null : c.viewers[i];
    const y = c.wp_excitement[i] == null ? null : c.wp_excitement[i];
    let place;
    if (x != null && y != null) {
      place = 'plot';
      counts.plotted += 1;
    } else if (y != null) {
      place = 'bottom';
      counts.noRating += 1;
    } else if (x != null) {
      place = 'left';
      counts.noExcitement += 1;
    } else {
      place = 'corner';
      counts.neither += 1;
    }
    const family = familyOf(model, i);
    present.add(family);
    const matched = selecting && matchedSet.has(i);
    const faded = selecting && !matched;
    if (matched) counts.matched += 1;
    if (faded) counts.faded += 1;
    counts.total += 1;
    items.push({
      i, x, y, family, place,
      window: x != null && c.scope[i] === 'window',
      matched, faded,
      hidden: hiddenSet.has(family),
    });
  }
  return { items, counts, families: MLB_FAMILY_ORDER.filter((f) => present.has(f)) };
}

/** Status line under the chart (D-08): what is plotted and what sits in a strip. */
export function statusText(counts) {
  if (!counts || !counts.total) return '';
  const rest = [];
  if (counts.noRating) rest.push(`${counts.noRating} with no rating`);
  if (counts.noExcitement) rest.push(`${counts.noExcitement} with no excitement`);
  if (counts.neither) rest.push(`${counts.neither} with neither`);
  const plotted = counts.plotted
    ? `${counts.plotted} ${counts.plotted === 1 ? 'game' : 'games'} plotted.`
    : '';
  const tail = rest.length ? `${rest.join(', ')}.` : '';
  return [plotted, tail].filter(Boolean).join(' ');
}
