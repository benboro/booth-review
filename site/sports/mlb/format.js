/**
 * Pure MLB date helpers for the games table and detail panel. DOM-free.
 *
 * These repeat the NFL date helpers on purpose: a build with MLB on and NFL
 * off ships no sports/nfl/ files, so an import from there would 404.
 */
import { MONTHS } from '../../modules/format.js';

const WEEKDAYS_LONG = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];

/** Splits 'YYYY-MM-DD' into a UTC date plus its parts (no timezone shift). */
function parts(ymd) {
  const [y, m, d] = ymd.split('-').map(Number);
  return { y, m, d, dow: new Date(Date.UTC(y, m - 1, d)).getUTCDay() };
}

/** 'Apr 3, 2026'. */
export function dateShortText(row) {
  const { y, m, d } = parts(row.date);
  return `${MONTHS[m - 1]} ${d}, ${y}`;
}

/** 'Friday, Apr 3, 2026'. */
export function dateLongText(row) {
  const { dow } = parts(row.date);
  return `${WEEKDAYS_LONG[dow]}, ${dateShortText(row)}`;
}
