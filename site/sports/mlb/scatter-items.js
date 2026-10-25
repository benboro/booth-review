/**
 * MLB Scatter item model (D-05, D-07, D-08, D-09). DOM-free; MLB-only; no NFL imports.
 *
 * One item per game; the Season type / Round control fades the games outside it. Every item has
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

/**
 * Whether the Season type control fades (true) or narrows (false) the chart. The user asked for
 * the Round control to highlight instead of filter (U5); the Season type control was moved to
 * the same behaviour by the coordinator so the two buttons in one group act alike. Set this to
 * false to make Season type narrow the chart again (Round then highlights within it); the home
 * zoom range then follows Season type too (see scatter.js).
 */
export const SEASON_TYPE_HIGHLIGHTS = true;

/** The Season type half of the control: regular season or postseason games. */
export function passesSeasonType(model, i, state) {
  const round = model.cols.round[i];
  if (state.stype === 'reg') return round === 'regular';
  if (state.stype === 'post') return MLB_SROUNDS.includes(round);
  return true;
}

/** The Season type / Round control (D-09, U5): which games the control highlights. */
export function passesControl(model, i, state) {
  if (!passesSeasonType(model, i, state)) return false;
  if (state.stype === 'post' && state.sround) return model.cols.round[i] === state.sround;
  return true;
}

/** Deterministic spread along a strip so overlapping marks stay countable. */
export function stripJitter(i) {
  return 0.12 + ((i * 0.6180339887) % 1) * 0.76;
}

export function buildScatterItems(model, state, { hiddenFamilies } = {}) {
  const c = model.cols;
  const hiddenSet = hiddenFamilies || new Set();
  const picked = state.booth != null || state.cell != null || state.selection != null;
  // An open game counts as a selection for the fade only when nothing else is picked (D-07).
  const gameOnly = !picked && Number.isInteger(state.game);
  const selecting = picked || gameOnly;
  const matchedSet = !selecting ? null : gameOnly ? new Set([state.game]) : new Set(tableGames(model, state));
  // The control highlights (U5): every game stays plotted, and games outside it fade.
  const controlling = state.stype != null;
  const highlighting = selecting || controlling;
  const items = [];
  const present = new Set();
  const counts = {
    total: 0, plotted: 0, noRating: 0, noExcitement: 0, neither: 0, matched: 0, faded: 0,
    highlighted: highlighting ? 0 : null,
  };
  // Games whose family chip is off: still in the counts, not drawn.
  let hidden = 0;
  for (let i = 0; i < model.n; i += 1) {
    if (!SEASON_TYPE_HIGHLIGHTS && !passesSeasonType(model, i, state)) continue;
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
    // Full strength only when the game matches both the control and any pick.
    const inControl = passesControl(model, i, state);
    const inPick = !selecting || matchedSet.has(i);
    const matched = selecting && inPick && inControl;
    const faded = highlighting && !(inPick && inControl);
    if (matched) counts.matched += 1;
    if (faded) counts.faded += 1;
    else if (highlighting) counts.highlighted += 1;
    counts.total += 1;
    if (hiddenSet.has(family)) hidden += 1;
    items.push({
      i, x, y, family, place,
      window: x != null && c.scope[i] === 'window',
      matched, faded,
      hidden: hiddenSet.has(family),
    });
  }
  return { items, counts, hidden, families: MLB_FAMILY_ORDER.filter((f) => present.has(f)) };
}

/**
 * Status line under the chart (D-08): what is plotted and what sits in a strip. The counts cover
 * every game; when the control or a pick fades some, `highlighted` names how many stay at full
 * strength, and `hidden` games (legend chips off) are named so the line still adds up to what is
 * drawn.
 */
export function statusText(counts, hidden = 0) {
  if (!counts || !counts.total) return '';
  const rest = [];
  if (counts.noRating) rest.push(`${counts.noRating} with no rating`);
  if (counts.noExcitement) rest.push(`${counts.noExcitement} with no excitement`);
  if (counts.neither) rest.push(`${counts.neither} with neither`);
  const plotted = counts.plotted
    ? `${counts.plotted} ${counts.plotted === 1 ? 'game' : 'games'} plotted.`
    : '';
  const tail = rest.length ? `${rest.join(', ')}.` : '';
  const lit = counts.highlighted != null ? `${counts.highlighted} highlighted.` : '';
  const off = hidden > 0 ? `${hidden} hidden by the legend.` : '';
  return [plotted, tail, lit, off].filter(Boolean).join(' ');
}
