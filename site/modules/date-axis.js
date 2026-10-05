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

const round4 = (v) => Math.round(v * 10000) / 10000;
const round2 = (v) => Math.round(v * 100) / 100;

/**
 * Lower-row tier from pixels per day: 1 weekly dates, 2 biweekly dates,
 * 3 month names, 4 unlabeled month ticks, 5 nothing.
 * @param {number} ppd
 * @returns {1|2|3|4|5}
 */
function tierFor(ppd) {
  if (7 * ppd >= 56) return 1;
  if (14 * ppd >= 56) return 2;
  if (30 * ppd >= 40) return 3;
  if (30 * ppd >= 6) return 4;
  return 5;
}

/**
 * Lower-row ticks for one tier, walking each block's calendar days.
 * @returns {{tickvals: number[], ticktext: string[]}}
 */
function lowerRow(blocks, lo, hi, tier) {
  const tickvals = [];
  const ticktext = [];
  if (tier === 5) return { tickvals, ticktext };
  for (const b of blocks) {
    let saturdayIndex = 0;
    for (let day = b.minDay; day <= b.maxDay; day += 1) {
      const dt = new Date(day * MS_PER_DAY);
      const base = b.start + DATE_PAD + (day - b.minDay);
      if (tier <= 2) {
        if (dt.getUTCDay() !== 6) continue;
        const keep = tier === 1 || saturdayIndex % 2 === 0;
        saturdayIndex += 1;
        if (!keep) continue;
        const x = round4(base + 0.5);
        if (x < lo || x > hi) continue;
        tickvals.push(x);
        ticktext.push(`${MONTHS[dt.getUTCMonth()]} ${dt.getUTCDate()}`);
      } else {
        if (dt.getUTCDate() !== 1) continue;
        const x = round4(base);
        if (x < lo || x > hi) continue;
        tickvals.push(x);
        ticktext.push(tier === 3 ? MONTHS[dt.getUTCMonth()] : '');
      }
    }
  }
  return { tickvals, ticktext };
}

/**
 * Places labels left to right, then pulls them back inside the right limit,
 * and reports which cannot sit validly (outside the limits or off their block).
 * @param {{c: number, a: number, b: number, w: number}[]} items - desired px
 *   center, own visible px span [a, b], and box width, in order.
 * @returns {{centers: number[], invalid: boolean[]}}
 */
function placeRow(items, gapPx, leftLimit, rightLimit) {
  const centers = items.map((it) => it.c);
  let prevRight = -Infinity;
  items.forEach((it, i) => {
    centers[i] = Math.max(centers[i], prevRight + gapPx + it.w / 2);
    prevRight = centers[i] + it.w / 2;
  });
  let nextLeft = Infinity;
  for (let i = items.length - 1; i >= 0; i -= 1) {
    const w = items[i].w;
    const maxCenter = Math.min(rightLimit - w / 2, nextLeft - gapPx - w / 2);
    centers[i] = Math.min(centers[i], maxCenter);
    nextLeft = centers[i] - w / 2;
  }
  const invalid = items.map((it, i) => {
    const left = centers[i] - it.w / 2;
    const right = centers[i] + it.w / 2;
    if (left < leftLimit || right > rightLimit) return true;
    return !(left < it.b && right > it.a);
  });
  return { centers, invalid };
}

/**
 * Adaptive two-row label rule (D-11): a lower-row tier from px-per-day and a
 * collision-free season row. All season labels switch to two-digit years
 * together; a label that still cannot be placed is hidden as a last resort.
 * @param {Block[]} blocks - the shown blocks, ascending.
 * @param {[number, number]} range - visible data x range [lo, hi].
 * @param {number} plotPx - plot width in px.
 * @param {{mobile?: boolean, marginLeft?: number, marginRight?: number}} [opts]
 * @returns {{tier: number, tickvals: number[], ticktext: string[], twoDigit: boolean,
 *   seasons: {season: number, x: number, xshift: number, label: string, visible: boolean}[]}}
 */
export function dateAxisLabels(blocks, range, plotPx, { mobile = false, marginLeft = 70, marginRight = 24 } = {}) {
  const [lo, hi] = range;
  const pxPerUnit = plotPx / (hi - lo);
  const tier = tierFor(pxPerUnit);
  const { tickvals, ticktext } = lowerRow(blocks, lo, hi, tier);

  const fontSize = mobile ? 10 : 14;
  const charPx = 0.62 * fontSize;
  const leftLimit = -marginLeft + 2;
  const rightLimit = plotPx + marginRight - 2;
  const toPx = (x) => (x - lo) * pxPerUnit;

  const entries = blocks.map((b) => {
    const a = Math.max(b.start, lo);
    const e = Math.min(b.end, hi);
    const overlaps = e > a && b.end > lo && b.start < hi;
    const x = round4(overlaps ? (a + e) / 2 : Math.min(Math.max((b.start + b.end) / 2, lo), hi));
    return { block: b, x, overlaps, a: toPx(a), b: toPx(e), c: toPx(x) };
  });
  const full = (s) => String(s);
  const short = (s) => `'${String(s).slice(-2)}`;
  const result = entries.map((en) => ({
    season: en.block.season,
    x: en.x,
    xshift: 0,
    label: full(en.block.season),
    visible: en.overlaps,
  }));
  if (blocks.length === 1) return { tier, tickvals, ticktext, twoDigit: false, seasons: result };

  const run = (twoDigit) => {
    const fmt = twoDigit ? short : full;
    const gap = twoDigit ? 1 : 2;
    let active = entries.map((en, i) => (en.overlaps ? i : -1)).filter((i) => i >= 0);
    const placed = new Map();
    const hidden = new Set();
    // Two-digit form may drop unplaceable labels and re-run once; full years never hide.
    for (let pass = 0; pass < 2; pass += 1) {
      const items = active.map((i) => ({
        c: entries[i].c,
        a: entries[i].a,
        b: entries[i].b,
        w: charPx * fmt(entries[i].block.season).length,
      }));
      const { centers, invalid } = placeRow(items, gap, leftLimit, rightLimit);
      placed.clear();
      active.forEach((i, k) => placed.set(i, centers[k]));
      if (!invalid.some(Boolean)) return { ok: true, placed, hidden };
      if (!twoDigit) return { ok: false };
      for (const i of active.filter((_, k) => invalid[k])) hidden.add(i);
      active = active.filter((i) => !hidden.has(i));
    }
    // Leftovers from the final re-run are hidden too (last resort, never truncated).
    for (const i of Array.from(placed.keys())) if (hidden.has(i)) placed.delete(i);
    return { ok: true, placed, hidden };
  };

  let twoDigit = false;
  let outcome = run(false);
  if (!outcome.ok) {
    twoDigit = true;
    outcome = run(true);
  }
  const fmt = twoDigit ? short : full;
  const seasons = result.map((r, i) => {
    const center = outcome.placed.get(i);
    const hide = outcome.hidden.has(i) || center === undefined;
    return {
      ...r,
      label: fmt(r.season),
      visible: r.visible && !hide,
      xshift: hide ? 0 : round2(center - entries[i].c),
    };
  });
  return { tier, tickvals, ticktext, twoDigit, seasons };
}
