/**
 * Date x-axis geometry (04.11, SITE-48).
 *
 * DOM-free: no reference to window/document/Plotly. Every season that has
 * telecasts gets one block, trimmed to its own earliest..latest telecast plus
 * a small pad, at one data unit per calendar day; blocks sit left to right
 * separated by a fixed gap. A dot's x is its block start + pad + days since
 * the season's first telecast + the ET kickoff fraction of the day.
 *
 * Dates are ET calendar days straight from the shipped `date` column; kickoff
 * fractions read the HH:MM of the already-ET ISO string. No timezone
 * conversion and no `new Date('YYYY-MM-DD')` (which parses as UTC) happens here.
 */

import { MONTHS } from './format.js';

/** Day-units of empty space inside each block edge. */
export const DATE_PAD = 1;

/** Day-units between neighbouring blocks. */
export const DATE_GAP = 7;

const MS_PER_DAY = 86400000;

/**
 * Integer days since 1970-01-01 for an ET calendar date.
 * @param {string} ymd - "YYYY-MM-DD".
 * @returns {number}
 */
export function epochDay(ymd) {
  const [y, m, d] = ymd.split('-').map(Number);
  return Date.UTC(y, m - 1, d) / MS_PER_DAY;
}

/**
 * Fraction of the ET day at kickoff; a missing kickoff sits at midday.
 * @param {string|null} iso - ET ISO string such as "2021-10-02T22:30:00-04:00".
 * @returns {number} in [0, 1).
 */
export function kickoffFraction(iso) {
  if (iso == null) return 0.5;
  const h = Number(iso.slice(11, 13));
  const m = Number(iso.slice(14, 16));
  return (h * 60 + m) / 1440;
}

/**
 * @typedef {object} Block
 * @property {number} season
 * @property {number} minDay - epoch day of the season's first telecast.
 * @property {number} maxDay - epoch day of the season's last telecast.
 * @property {number} start - data x of the block's left edge.
 * @property {number} end - data x of the block's right edge.
 */

/**
 * Builds the season blocks and per-telecast date x from ALL telecasts.
 * @param {number[]} season - telecast season column.
 * @param {string[]} date - ET "YYYY-MM-DD" column.
 * @param {(string|null)[]} kickoff - ET ISO kickoff column.
 * @returns {{dateX: number[], axis: {pad: number, gap: number, blocks: Block[]}}}
 */
export function buildDateAxis(season, date, kickoff) {
  const n = season.length;
  const days = new Array(n);
  const span = new Map();
  for (let i = 0; i < n; i += 1) {
    const day = epochDay(date[i]);
    days[i] = day;
    const s = span.get(season[i]);
    if (s === undefined) span.set(season[i], { minDay: day, maxDay: day });
    else {
      if (day < s.minDay) s.minDay = day;
      if (day > s.maxDay) s.maxDay = day;
    }
  }
  const blocks = [];
  let cursor = 0;
  for (const s of Array.from(span.keys()).sort((a, b) => a - b)) {
    const { minDay, maxDay } = span.get(s);
    const width = maxDay - minDay + 1 + 2 * DATE_PAD;
    blocks.push({ season: s, minDay, maxDay, start: cursor, end: cursor + width });
    cursor += width + DATE_GAP;
  }
  const byseason = new Map(blocks.map((b) => [b.season, b]));
  const dateX = new Array(n);
  for (let i = 0; i < n; i += 1) {
    const b = byseason.get(season[i]);
    dateX[i] = b.start + DATE_PAD + (days[i] - b.minDay) + kickoffFraction(kickoff[i]);
  }
  return { dateX, axis: { pad: DATE_PAD, gap: DATE_GAP, blocks } };
}

/**
 * Blocks inside a season filter.
 * @param {{blocks: Block[]}} axis
 * @param {[number, number]|null} seasons - null for all, else inclusive [from, to].
 * @returns {Block[]}
 */
export function shownBlocks(axis, seasons) {
  if (seasons == null) return axis.blocks;
  return axis.blocks.filter((b) => b.season >= seasons[0] && b.season <= seasons[1]);
}

/**
 * Visible x range for a season filter: exactly the first shown block's start
 * to the last shown block's end. No shown block falls back to the full range.
 * @param {{blocks: Block[]}} axis
 * @param {[number, number]|null} seasons
 * @returns {[number, number]}
 */
export function seasonRange(axis, seasons) {
  const shown = shownBlocks(axis, seasons);
  const use = shown.length ? shown : axis.blocks;
  return [use[0].start, use[use.length - 1].end];
}

/**
 * Divider x positions at the center of each gap between consecutive blocks.
 * @param {Block[]} blocks
 * @returns {number[]}
 */
export function gapDividers(blocks) {
  const out = [];
  for (let i = 1; i < blocks.length; i += 1) out.push((blocks[i - 1].end + blocks[i].start) / 2);
  return out;
}

// MONTHS is used by the label rule (dateAxisLabels).
void MONTHS;
