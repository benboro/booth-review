/**
 * URL and view state helpers for the CFB This weekend tab (Phase 18, plan 10). DOM-free.
 *
 * `state.week` is a week number (null = the current weekend) and `state.day` a weekday token
 * (`thu`..`wed`, null = the sport's default day). Both are allowlisted against the shipped
 * `lookups.weeks` and that week's games when decoded (T-04.4-10, T-18-31): anything else is
 * dropped. The stepper only reaches back to the first shipped week and forward to the current
 * weekend (D-23).
 */

import { cfbWeekendGames } from './weekend-data.js';
import { dayTabs, defaultDay } from './weekend.js';

export const DAY_TOKENS = Object.freeze(['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat']);

/** The weekday token of an ET ISO date. */
export function dayToken(isoDate) {
  const [y, m, d] = isoDate.split('-').map(Number);
  const dayNumber = Math.floor(Date.UTC(y, m - 1, d) / 86400000);
  return DAY_TOKENS[(dayNumber + 4) % 7]; // 1970-01-01 was a Thursday
}

/** The label the stepper and subtitle show: `Week 9` for a numeric label, else the label. */
export function weekDisplay(week) {
  return /^\d+$/.test(String(week.label)) ? `Week ${week.label}` : String(week.label);
}

/** The current weekend's week entry: the freshness block's label, else the last shipped week. */
export function currentWeek(data) {
  const weeks = data.weeks ?? [];
  if (weeks.length === 0) return null;
  const wanted = data.weekend?.label;
  return weeks.find((w) => w.label === wanted) ?? weeks[weeks.length - 1];
}

/** The weeks the stepper can reach: the first shipped week up to the current weekend. */
export function reachableWeeks(data) {
  const weeks = data.weeks ?? [];
  const current = currentWeek(data);
  if (!current) return [];
  return weeks.filter((w) => w.number <= current.number);
}

/** The week entry a state shows (its stored number when reachable, else the current weekend). */
export function selectedWeek(data, state) {
  const reach = reachableWeeks(data);
  const hit = state.week != null ? reach.find((w) => w.number === state.week) : null;
  return hit ?? currentWeek(data);
}

/** The week's games and its day tabs (ISO dates). */
export function weekDays(data, week) {
  const games = cfbWeekendGames(data, week.label);
  return { games, days: dayTabs(games) };
}

/** The ISO date a state shows within a week's days: its token when present, else the default. */
export function selectedDay(days, token) {
  const hit = token != null ? days.find((d) => dayToken(d) === token) : null;
  return hit ?? defaultDay(days, 'cfb');
}

/**
 * The state's `week` for a numeric URL value: a reachable non-current week number, else null.
 * @param {string|null} raw
 * @param {object} data
 * @returns {number|null}
 */
export function decodeWeek(raw, data) {
  if (raw == null || !/^\d+$/.test(raw)) return null;
  const n = Number(raw);
  const current = currentWeek(data);
  if (!current || n === current.number) return null;
  return reachableWeeks(data).some((w) => w.number === n) ? n : null;
}

/**
 * The state's `day` for a URL token: a token present in the shown week and not its default
 * day, else null.
 * @param {string|null} raw
 * @param {object} data
 * @param {number|null} week - the already decoded week number.
 * @returns {string|null}
 */
export function decodeDay(raw, data, week) {
  if (raw == null || !DAY_TOKENS.includes(raw)) return null;
  const shown = selectedWeek(data, { week });
  if (!shown) return null;
  const { days } = weekDays(data, shown);
  const hit = days.find((d) => dayToken(d) === raw);
  if (!hit || hit === defaultDay(days, 'cfb')) return null;
  return raw;
}
