// Weekend map model (Phase 24): the window shape of each game, and (below) the dots, nudge
// rows, edge markers, not-on-map list and splat input built from one day's WeekendGame list.
// pure: model + geometry + env in, no DOM, no clock, no window.Plotly. No colour literal lives
// here; colours come from palette.js through weekend-map-chart.js.

// ---------------------------------------------------------------- window shape (D-03)

/**
 * The one table of window -> Plotly marker symbol. The figure and the key both read it, so the
 * shapes cannot diverge. CFB windows are by ET kickoff; NFL windows by slot name.
 */
export const WINDOW_SYMBOL = Object.freeze({
  cfb: Object.freeze({ noon: 'circle', afternoon: 'square', prime: 'diamond', late: 'triangle-up' }),
  nfl: Object.freeze({ early: 'circle', late: 'square', night: 'diamond' }),
  tba: 'circle-open',
});

/** Key labels per sport, in key order (UI-SPEC "Copywriting Contract"). */
export const WINDOW_LABELS = Object.freeze({
  cfb: Object.freeze({
    noon: 'Noon',
    afternoon: 'Afternoon',
    prime: 'Prime',
    late: 'Late',
    tba: 'Time TBA',
  }),
  nfl: Object.freeze({
    early: 'Early',
    late: 'Late',
    night: 'Night and standalone',
    tba: 'Time TBA',
  }),
});

/** Key range captions per sport (UI-SPEC "Copywriting Contract"). */
export const WINDOW_CAPTION = Object.freeze({
  cfb: 'Noon is before 2:30 pm. Afternoon is 2:30 to 6:59 pm. Prime is 7:00 to 9:59 pm. '
    + 'Late is 10:00 pm and after.',
  nfl: 'Early is the 1:00 pm window. Late is the 4:05 and 4:25 pm windows. '
    + 'Night and standalone covers every other slot.',
});

/** CFB window boundaries in minutes after ET midnight: 2:30 pm, 7:00 pm, 10:00 pm. */
const CFB_AFTERNOON_MIN = 14 * 60 + 30;
const CFB_PRIME_MIN = 19 * 60;
const CFB_LATE_MIN = 22 * 60;

/**
 * The CFB broadcast window of an ET kickoff.
 * @param {number|null} kickoffMin - minutes after ET midnight.
 * @returns {'noon'|'afternoon'|'prime'|'late'|'tba'}
 */
export function cfbWindow(kickoffMin) {
  if (kickoffMin == null) return 'tba';
  if (kickoffMin >= CFB_LATE_MIN) return 'late';
  if (kickoffMin >= CFB_PRIME_MIN) return 'prime';
  if (kickoffMin >= CFB_AFTERNOON_MIN) return 'afternoon';
  return 'noon';
}

/**
 * The NFL broadcast window from the Python slot name. Only the two Sunday daytime slots are not
 * night; TNF, SNF, MNF and every standalone slot read as night (RESEARCH Pitfall 6: the slot
 * name decides, `classifyGame` only decides grid, compact or tba).
 * @param {string|null} slotName
 * @returns {'early'|'late'|'night'|'tba'}
 */
export function nflWindow(slotName) {
  if (slotName == null) return 'tba';
  if (slotName === 'Sunday early') return 'early';
  if (slotName === 'Sunday late') return 'late';
  return 'night';
}

/**
 * The window of a WeekendGame. A game with no kickoff time is `tba` in either sport.
 * @param {object} game
 * @returns {string}
 */
export function windowOf(game) {
  if (game.sport === 'nfl') return nflWindow(game.slotName ?? null);
  return cfbWindow(game.kickoffMin ?? null);
}

/**
 * The Plotly marker symbol of a WeekendGame.
 * @param {object} game
 * @returns {string}
 */
export function symbolOf(game) {
  const win = windowOf(game);
  if (win === 'tba') return WINDOW_SYMBOL.tba;
  return WINDOW_SYMBOL[game.sport === 'nfl' ? 'nfl' : 'cfb'][win];
}
