/**
 * Display formatting and copywriting helpers (UI-SPEC Copywriting Contract,
 * Layout hover order, log/linear tick generation).
 *
 * DOM-free: no reference to window/document/Plotly. Dates and kickoff times
 * are parsed from their own string components rather than through `new
 * Date('YYYY-MM-DD')` or a browser-local Date conversion, since the data is
 * already in ET and must never shift by the viewer's local timezone.
 */

/** Short weekday names, Sunday-first, indexed by `Date#getUTCDay()`. */
const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

/** Short month names, indexed by `Date#getUTCMonth()`. */
const MONTHS = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
];

/** Time-slot filter labels, long form (D-11, SITE-11). */
export const SLOT_LABELS = {
  noon: 'Noon (before 2 PM ET)',
  afternoon: 'Afternoon (2–6 PM ET)',
  prime: 'Prime time (6 PM ET or later)',
};

/** Time-slot labels, short form, for chips/hover/table cells. */
export const SLOT_SHORT = {
  noon: 'Noon',
  afternoon: 'Afternoon',
  prime: 'Prime time',
};

/** Crew role filter labels (SITE-07). Sideline/other is role "unknown". */
export const ROLE_LABELS = {
  pbp: 'Play-by-play',
  analyst: 'Analyst',
  unknown: 'Sideline/other',
};

/** Crew feed labels. Main feed has no suffix; alt/spanish are labelled. */
export const FEED_LABELS = {
  main: '',
  alt: 'alt-cast',
  spanish: 'Spanish feed',
};

/** X-axis toggle labels (D-12). */
export const AXIS_LABELS = {
  pregame: 'Pre-game (spread)',
  excitement: 'Excitement (CFBD)',
};

/**
 * Formats an ET calendar date (`YYYY-MM-DD`) without any timezone
 * conversion: the three integers are read directly and turned into a UTC
 * instant purely to reuse `Date`'s weekday/month math (never `new
 * Date('YYYY-MM-DD')`, which some engines parse as local time).
 * @param {string} ymd - e.g. "2019-09-07".
 * @returns {string} e.g. "Sat, Sep 7, 2019".
 */
export function formatDate(ymd) {
  const [year, month, day] = ymd.split('-').map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  const weekday = WEEKDAYS[date.getUTCDay()];
  const monthName = MONTHS[date.getUTCMonth()];
  return `${weekday}, ${monthName} ${date.getUTCDate()}, ${year}`;
}

/**
 * Formats an ET kickoff ISO datetime as a 12-hour clock string, reading the
 * hour/minute directly from the string's own components (the value is
 * already ET; it is never converted to the browser's timezone).
 * @param {string|null} iso - e.g. "2019-11-16T15:30:00-05:00", or null.
 * @returns {string|null} e.g. "3:30 PM ET", or null when kickoff is unknown.
 */
export function formatKickoff(iso) {
  if (iso == null) return null;
  const match = /T(\d{2}):(\d{2})/.exec(iso);
  if (!match) return null;
  let hour = Number(match[1]);
  const minute = match[2];
  const ampm = hour >= 12 ? 'PM' : 'AM';
  hour = hour % 12;
  if (hour === 0) hour = 12;
  return `${hour}:${minute} ${ampm} ET`;
}

/**
 * Labels a measurement type for the detail panel and hover (D-02, verbatim
 * "Nielsen + Adobe (streaming)" wording).
 * @param {"nielsen"|"nielsen_adobe"|"unknown"} type
 * @returns {string}
 */
export function measurementLabel(type) {
  if (type === 'nielsen') return 'Nielsen';
  if (type === 'nielsen_adobe') return 'Nielsen + Adobe (streaming)';
  return 'Measurement not recorded';
}

/**
 * Formats a viewer count with thousands separators.
 * @param {number} n
 * @returns {string} e.g. "3,200,000".
 */
export function formatViewers(n) {
  return n.toLocaleString('en-US');
}

/**
 * Formats a matchup line: away vs./at home, with optional rank prefixes and
 * scores.
 * @param {object} data - a `prepareData` result.
 * @param {number} i - telecast index.
 * @param {{withScore?: boolean}} [options]
 * @returns {string} e.g. "#5 Northfield 20 at #3 Lakeview 27".
 */
export function formatMatchup(data, i, options = {}) {
  const withScore = options.withScore ?? false;
  const t = data.t;
  const awayTeam = data.lookups.teams[t.away_team[i]].name;
  const homeTeam = data.lookups.teams[t.home_team[i]].name;
  const awayRank = t.away_rank[i];
  const homeRank = t.home_rank[i];
  const awayPrefix = awayRank != null ? `#${awayRank} ` : '';
  const homePrefix = homeRank != null ? `#${homeRank} ` : '';
  const separator = t.neutral[i] ? 'vs.' : 'at';
  const showScore = withScore && t.away_points[i] != null && t.home_points[i] != null;
  const awayScore = showScore ? ` ${t.away_points[i]}` : '';
  const homeScore = showScore ? ` ${t.home_points[i]}` : '';
  return `${awayPrefix}${awayTeam}${awayScore} ${separator} ${homePrefix}${homeTeam}${homeScore}`;
}

/**
 * Groups a telecast's main-feed crew by role. Alt/spanish entries are
 * listed separately by the panel, not here.
 * @param {object} data - a `prepareData` result.
 * @param {number} i - telecast index.
 * @returns {{pbp: string[], analyst: string[], other: string[]}}
 */
export function crewByRole(data, i) {
  const result = { pbp: [], analyst: [], other: [] };
  for (const entry of data.t.crew[i]) {
    if (entry.feed !== 'main') continue;
    const name = data.lookups.people[entry.person].name;
    if (entry.role === 'pbp') result.pbp.push(name);
    else if (entry.role === 'analyst') result.analyst.push(name);
    else result.other.push(name);
  }
  return result;
}

/** Short axis value labels, distinct from the longer AXIS_LABELS toggle copy. */
const AXIS_VALUE_LABELS = { pregame: 'Spread', excitement: 'Excitement' };

/**
 * Formats a single axis value for hover/panel display. Pre-game values are
 * shown as a positive spread magnitude; null is never coerced to a number.
 * @param {"pregame"|"excitement"} axis
 * @param {number|null} value
 * @returns {string} e.g. "Spread: 3.5", "Excitement: 8.4", or "...: not available".
 */
export function formatAxisValue(axis, value) {
  if (value == null) return `${AXIS_LABELS[axis]}: not available`;
  const label = AXIS_VALUE_LABELS[axis];
  const num = axis === 'pregame' ? Math.abs(value) : value;
  return `${label}: ${num.toFixed(1)}`;
}

/** The full 1-2-5 tick sequence from 10,000 to 100,000,000. */
function logTickCandidates() {
  const candidates = [];
  for (let magnitude = 10000; magnitude <= 100000000; magnitude *= 10) {
    for (const multiplier of [1, 2, 5]) {
      const value = magnitude * multiplier;
      if (value <= 100000000) candidates.push(value);
    }
  }
  return candidates;
}

/** Labels a single log-axis tick value, "K" below 100,000 and "M" at/above. */
function logTickLabel(value) {
  if (value < 100000) return `${value / 1000}K`;
  return `${value / 1000000}M`;
}

/**
 * Builds log-axis tick values and labels for the viewers y-axis, filtered
 * to a padded window around the data's own min/max so the axis never shows
 * far more ticks than the data spans.
 * @param {number} minViewers
 * @param {number} maxViewers
 * @returns {{tickvals: number[], ticktext: string[]}}
 */
export function logTicks(minViewers, maxViewers) {
  const lo = minViewers / 1.5;
  const hi = maxViewers * 1.5;
  const tickvals = logTickCandidates().filter((v) => v >= lo && v <= hi);
  const ticktext = tickvals.map(logTickLabel);
  return { tickvals, ticktext };
}

/**
 * Builds "nice" ascending linear tick values on a 1/2/5 x 10^k step, all
 * within [min, max] inclusive, so no tick ever lands in the n/a strip band
 * to the left of the numeric axis.
 * @param {number} min
 * @param {number} max
 * @param {number} [target] - approximate desired tick count.
 * @returns {number[]}
 */
export function niceLinearTicks(min, max, target = 6) {
  if (max <= min) return [min];
  const range = max - min;
  const roughStep = range / Math.max(target - 1, 1);
  const magnitude = 10 ** Math.floor(Math.log10(roughStep));
  const normalized = roughStep / magnitude;
  let niceNormalized;
  if (normalized <= 1) niceNormalized = 1;
  else if (normalized <= 2) niceNormalized = 2;
  else if (normalized <= 5) niceNormalized = 5;
  else niceNormalized = 10;
  const step = niceNormalized * magnitude;
  const ticks = [];
  const start = Math.ceil(min / step) * step;
  for (let value = start; value <= max + step * 1e-9; value += step) {
    if (value < min) continue;
    ticks.push(Math.round(value * 1e6) / 1e6);
  }
  return ticks;
}

/**
 * Escapes `&`, `<`, and `>` for safe use in Plotly's pseudo-HTML hover text
 * (T-04-06). `&` is escaped first so the entities produced for `<`/`>`
 * are never double-escaped.
 * @param {string} s
 * @returns {string}
 */
export function escapeHover(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

/**
 * Turns a `computeView` summary object into display copy (UI-SPEC
 * Copywriting Contract, match summary line variants). Counts only --
 * never a computed or printed viewer statistic of any kind (anti-feature A1).
 * @param {object} summary - `computeView(...).summary`.
 * @returns {{count: string, detail: string}}
 */
export function summaryCopy(summary) {
  if (summary.kind === 'matches') {
    const n = summary.count;
    const count = n === 1 ? '1 rated telecast' : `${n} rated telecasts`;
    let detail = `${summary.seasonMin}–${summary.seasonMax} · ${summary.networks.join(', ')}`;
    if (summary.altCount > 0) {
      const gameWord = summary.altCount === 1 ? 'game' : 'games';
      detail += ` · includes ${summary.altCount} alt-cast ${gameWord}`;
    }
    return { count, detail };
  }
  if (summary.kind === 'no-rated') {
    return {
      count: '',
      detail: `${summary.name}: no Nielsen-rated telecasts in this sample. Conference-network and streaming-only games usually aren't rated — see the methodology page.`,
    };
  }
  if (summary.kind === 'filtered-out') {
    return {
      count: '',
      detail: `No games match the current filters for ${summary.selectionLabel}. Try widening the season range, or clear a filter.`,
    };
  }
  return { count: '', detail: '' };
}
