/**
 * Pure NFL display helpers shared by the games table, the detail panel and the
 * views' hovers (999.5-08). DOM-free. Works on the shared GameRow shape; no
 * field here is, or is derived from, a point spread.
 */

import { MONTHS, formatKickoff, formatMillions, formatMillionsProse } from '../../modules/format.js';

const WEEKDAYS_LONG = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];

const SLOT_NAMES = Object.freeze({
  TNF: 'Thursday Night Football (TNF)',
  SNF: 'Sunday Night Football (SNF)',
  MNF: 'Monday Night Football (MNF)',
});

/** Why a game has no figure, as hover and panel copy (D-22). */
export const CAUSE_COPY = Object.freeze({
  pending: Object.freeze({ hover: 'not posted yet', panel: 'not posted yet' }),
  regional: Object.freeze({
    hover: 'not compiled for regional games',
    panel: 'Ratings Reference does not compile regional games',
  }),
  none: Object.freeze({ hover: 'no figure published', panel: 'no figure published' }),
});

/** Score line, winner first: 'Lanterns 27, Gulls 24'; tie '... (tie)'; missing 'Not available'. */
export function scoreText(row) {
  const { awayPoints: a, homePoints: h } = row;
  if (a == null || h == null) return 'Not available';
  if (h === a) return `${row.homeShort} ${h}, ${row.awayShort} ${a} (tie)`;
  return h > a ? `${row.homeShort} ${h}, ${row.awayShort} ${a}` : `${row.awayShort} ${a}, ${row.homeShort} ${h}`;
}

/** Long slot name for the three prime-time codes; other codes unchanged. */
export function slotLabel(code) {
  return SLOT_NAMES[code] ?? code;
}

/** Ordered subset of the flag labels set on the row. */
export function flagLabels(row) {
  const out = [];
  if (row.standalone) out.push('Solo slot');
  if (row.agotw) out.push('Fox AGOTW');
  if (row.cbsNational) out.push('CBS late national');
  if (row.international) out.push('International');
  if (row.flexed) out.push('Flexed');
  return out;
}

/** Crew provenance note, or null when the crew came from 506. */
export function crewSourceText(row) {
  return row.crewSource === 'published_lineup' ? 'from published lineup' : null;
}

/** '12.3MM' or null when unrated: the table form, one even decimal in millions. */
export function viewersText(row) {
  if (row.viewers == null) return null;
  return formatMillions(row.viewers);
}

/** '220K', '1.1MM' or null when unrated: the tooltip and panel form, no trailing zero. */
export function viewersProseText(row) {
  if (row.viewers == null) return null;
  return formatMillionsProse(row.viewers);
}

/** '1:00 PM ET' or null. */
export function kickoffText(row) {
  return formatKickoff(row.kickoff);
}

/** Splits 'YYYY-MM-DD' into a UTC date plus its parts (no timezone shift). */
function parts(ymd) {
  const [y, m, d] = ymd.split('-').map(Number);
  return { y, m, d, dow: new Date(Date.UTC(y, m - 1, d)).getUTCDay() };
}

/** 'Sep 7, 2025'. */
export function dateShortText(row) {
  const { y, m, d } = parts(row.date);
  return `${MONTHS[m - 1]} ${d}, ${y}`;
}

/** 'Sunday, Sep 7, 2025'. */
export function dateLongText(row) {
  const { dow } = parts(row.date);
  return `${WEEKDAYS_LONG[dow]}, ${dateShortText(row)}`;
}

/** Cause copy for an unrated row, falling back to the generic wording. */
export function causeCopy(row) {
  return CAUSE_COPY[row.cause] ?? CAUSE_COPY.none;
}
