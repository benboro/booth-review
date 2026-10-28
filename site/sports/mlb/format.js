/**
 * Pure MLB date helpers for the games table and detail panel. DOM-free.
 *
 * These repeat the NFL date helpers on purpose: a build with MLB on and NFL
 * off ships no sports/nfl/ files, so an import from there would 404.
 */
import { MONTHS } from '../../modules/format.js';
import { dayLabel } from '../../modules/weekend.js';

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

/** AP style with the year, as CFB and NFL write it: 'Fri. April 3, 2026'. MLB has no kickoff time. */
export function dateApText(row) {
  return `${dayLabel(row.date)}, ${row.date.slice(0, 4)}`;
}
