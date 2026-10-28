/**
 * This weekend layout model (Phase 18, plan 05): the pure, DOM-free core both sports' views
 * render from. Row classification, day tabs, the time axis, greedy sub-row packing, cell
 * states, cell colours and the weekend pick state all live here so they can be tested without
 * a DOM. Nothing in this file reads the clock: callers pass the current time in (see
 * `etParts`, `etWallMinutes`), always converted to America/New_York (D-09), never the viewer's
 * zone.
 *
 * DOM safety (T-18-15): the model returns plain strings and numbers only; it never builds
 * markup. The T-04.4-09 rule (createElement/textContent, never innerHTML) applies to the render
 * modules that consume this model.
 */

import { sortNetworks } from './network.js';
import {
  FAMILY_COLORS, INK, PAGE_BG, contrastRatio, familyKey, mixHex,
} from './palette.js';

/**
 * One game as the render adapter (plan 08) hands it to the model.
 * @typedef {object} WeekendGame
 * @property {string} key
 * @property {'cfb'|'nfl'} sport
 * @property {'t'|'scheduled'|'upcoming'} block
 * @property {number} index
 * @property {string|null} date - ET ISO date (YYYY-MM-DD).
 * @property {number|null} kickoffMin - minutes after ET midnight of `date`.
 * @property {string|null} networkId
 * @property {string|null} networkName
 * @property {string} family - a familyKey result ('other' when unknown).
 * @property {string} away
 * @property {string} home
 * @property {number|null} awayRank
 * @property {number|null} homeRank
 * @property {boolean} neutral
 * @property {string|null} pbp
 * @property {string|null} analyst
 * @property {number|null} boothRank - 1 = A booth.
 * @property {boolean} lead - called by the network's A booth (the lead star).
 * @property {boolean} crewKnown
 * @property {boolean} past - the game is in a past week.
 */

/** CFB grid rows (D-03, D-10), repo network ids. Everything else is streaming or compact. */
export const WEEKEND_GRID_ROWS = Object.freeze([
  'abc', 'cbs', 'fox', 'nbc', 'espn', 'espn2', 'espnews', 'espnu', 'sec-network',
  'acc-network', 'big-ten-network', 'fs1', 'cbs-sports-network', 'tnt', 'usa-network', 'cw',
]);

/**
 * Network ids that share the one CFB Streaming row (D-10): every `streaming` tier id in
 * data/reference/networks.csv except the ESPN+ family (espn-plus, espn_plus, espn3,
 * espn-unlimited, espn_unltd, which go to the compact list), plus the streaming services the
 * repo ids name outside that csv (Peacock local, Apple TV, Prime Video, Netflix, YouTube, Yahoo).
 */
export const WEEKEND_STREAMING_IDS = Object.freeze([
  'peacock', 'peacock_local', 'apple', 'paramount-plus', 'max', 'disney-plus', 'prime',
  'netflix', 'youtube', 'yahoo', 'acc-network-extra', 'sec-network-plus', 'cbs-sports-facebook',
  'conference-usa-digital', 'stadium', 'flosports', 'barstool-sports', 'campus-insiders',
  'cyclones-tv', 'soonersports-tv', 'uconn-huskies-tv', 'uconn-plus', 'wvusports-com',
]);

/** Drawn width of a cell in minutes, per sport (UI-SPEC "Time scale"). */
export const BLOCK_MINUTES = Object.freeze({ cfb: 210, nfl: 195 });

/** Opacity of a cell that fails an active pick (D-21; one constant for every consumer). */
export const WEEKEND_FADED_OPACITY = 0.3;

/** Weight of the family colour in a Crew TBA / not-listed tint (D-05). */
const TINT_WEIGHT = 0.18;
/** White-on-fill contrast a known-crew cell is deepened to (user sign-off 2026-10-26). */
const KNOWN_TEXT_CONTRAST = 7;
const STREAMING_ROW = 'streaming';
const SUB_ROW_PITCH = 48;
const CELL_HEIGHT = 44;
/** The sticky network column (UI-SPEC "Row header column: 96px wide"). */
const ROW_HEAD_WIDTH = 96;
/** Minutes after ET midnight at the next midnight: the last tick a stretched lane can show. */
const MIDNIGHT = 24 * 60;
/** The Time TBA strip starts collapsed at this many games or more (D-13). */
const STRIP_COLLAPSE_AT = 7;

const GRID_SET = new Set(WEEKEND_GRID_ROWS);
const STREAMING_SET = new Set(WEEKEND_STREAMING_IDS);

// ---- Eastern-time helpers (no clock access: the caller passes the instant in) ----

const ET_FORMAT = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/New_York',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
});

/**
 * The ET calendar date and minute of day for an instant.
 * @param {Date} instant
 * @returns {{date: string, minutes: number}}
 */
export function etParts(instant) {
  const p = {};
  for (const part of ET_FORMAT.formatToParts(instant)) p[part.type] = part.value;
  return {
    date: `${p.year}-${p.month}-${p.day}`,
    minutes: Number(p.hour) * 60 + Number(p.minute),
  };
}

function dayNumber(isoDate) {
  const [y, m, d] = isoDate.split('-').map(Number);
  return Math.floor(Date.UTC(y, m - 1, d) / 86400000);
}

/**
 * ET wall-clock minutes on one scale for any ET date and minute of day, so a kickoff and "now"
 * compare directly (the scale is ET minutes since 1970-01-01 00:00; it is not an epoch).
 * @param {string} isoDate
 * @param {number} minutes
 * @returns {number}
 */
export function etWallMinutes(isoDate, minutes) {
  return dayNumber(isoDate) * 1440 + minutes;
}

const WEEKDAYS = ['Sun.', 'Mon.', 'Tue.', 'Wed.', 'Thu.', 'Fri.', 'Sat.'];
const MONTHS = [
  'Jan.', 'Feb.', 'March', 'April', 'May', 'June', 'July', 'Aug.', 'Sept.', 'Oct.', 'Nov.', 'Dec.',
];

function weekdayOf(isoDate) {
  return (dayNumber(isoDate) + 4) % 7; // 1970-01-01 was a Thursday
}

/** The `day` URL tokens both sports use, by weekday number (Sunday first). */
export const DAY_TOKENS = Object.freeze(['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat']);

/** The weekday token of an ET ISO date. */
export function dayToken(isoDate) {
  return DAY_TOKENS[weekdayOf(isoDate)];
}

/**
 * AP-style day tab label, `Sat. Oct. 31`.
 * @param {string} isoDate
 * @returns {string}
 */
export function dayLabel(isoDate) {
  const [, m, d] = isoDate.split('-').map(Number);
  return `${WEEKDAYS[weekdayOf(isoDate)]} ${MONTHS[m - 1]} ${d}`;
}

/** `12:30 pm`. */
export function clock12(min) {
  const h = Math.floor(min / 60) % 24;
  const m = min % 60;
  return `${h % 12 === 0 ? 12 : h % 12}:${String(m).padStart(2, '0')} ${h < 12 ? 'am' : 'pm'}`;
}

/** Minutes after ET midnight read from an ET ISO datetime, or null (no time yet). */
export function kickoffMinutes(iso) {
  if (iso == null) return null;
  const m = /T(\d{2}):(\d{2})/.exec(iso);
  return m ? Number(m[1]) * 60 + Number(m[2]) : null;
}

/**
 * The kickoff line of a panel opened from This weekend, written as the view writes times
 * (18-UI-SPEC, 18-UI-REVIEW item 8): `Sat. Oct. 31, 12:00 pm ET`, or `Sat. Oct. 31, Time TBA`.
 * @param {string} isoDate - ET date `YYYY-MM-DD`.
 * @param {string|null} kickoffIso - ET ISO datetime, or null.
 * @param {string} [noTime] - the text when there is no time.
 * @param {{year?: boolean}} [options] - `year` adds the year after the day: `Sat. Nov. 21, 2020, 12:00 pm ET`.
 * @returns {string}
 */
export function apKickoff(isoDate, kickoffIso, noTime = 'Time TBA', { year = false } = {}) {
  const min = kickoffMinutes(kickoffIso);
  const day = year ? `${dayLabel(isoDate)}, ${isoDate.slice(0, 4)}` : dayLabel(isoDate);
  return `${day}, ${min == null ? noTime : `${clock12(min)} ET`}`;
}

// ---- Classification, days, axis ----

/**
 * Where a game goes (D-10, D-13). A game with no network or no kickoff time goes to the Time
 * TBA strip; nothing is dropped. CFB: the listed linear networks are grid rows, streaming
 * services share one row, and everything else (ESPN+, regional) goes to the compact list.
 * NFL: every network is a grid row.
 * @param {WeekendGame} game
 * @returns {{section: 'grid', row: string}|{section: 'compact'}|{section: 'tba'}}
 */
export function classifyGame(game) {
  if (game.networkId == null || game.kickoffMin == null) return { section: 'tba' };
  if (game.sport === 'nfl') return { section: 'grid', row: game.networkId };
  if (GRID_SET.has(game.networkId)) return { section: 'grid', row: game.networkId };
  if (STREAMING_SET.has(game.networkId)) return { section: 'grid', row: STREAMING_ROW };
  return { section: 'compact' };
}

/**
 * The days with games, in ET date order. A game whose date is known counts even when it sits in
 * the Time TBA strip; undated games add no tab (D-07).
 * @param {WeekendGame[]} games
 * @returns {string[]} ISO dates.
 */
export function dayTabs(games) {
  return [...new Set(games.map((g) => g.date).filter((d) => d != null))].sort();
}

/**
 * Default day (D-07): Saturday for CFB, Sunday for NFL, else the first day with games.
 * @param {string[]} days
 * @param {'cfb'|'nfl'} sport
 * @returns {string|null}
 */
export function defaultDay(days, sport) {
  const want = sport === 'nfl' ? 0 : 6;
  return days.find((d) => weekdayOf(d) === want) ?? days[0] ?? null;
}

/**
 * Axis start and end in minutes after ET midnight: earliest kickoff floored to the hour, latest
 * kickoff plus the block length ceiled to the hour. Null with no kickoffs.
 * @param {number[]} kickoffs
 * @param {number} blockMinutes
 * @returns {{start: number, end: number}|null}
 */
export function axisRange(kickoffs, blockMinutes) {
  if (kickoffs.length === 0) return null;
  return {
    start: Math.floor(Math.min(...kickoffs) / 60) * 60,
    end: Math.ceil((Math.max(...kickoffs) + blockMinutes) / 60) * 60,
  };
}

/**
 * Pixels per hour: clamp(80, floor((width - 96) / hours), 120); 96 is the row header column.
 * The 80 floor lets a 15-hour day fit at 1440 (user sign-off 2026-10-26; the spec had 88).
 * @param {number} width - container width in px.
 * @param {number} hours - hours the axis spans.
 * @returns {number}
 */
export function pxPerHour(width, hours) {
  return Math.min(120, Math.max(80, Math.floor((width - ROW_HEAD_WIDTH) / hours)));
}

function tickLabel(min) {
  const h = Math.floor(min / 60) % 24;
  const hour12 = h % 12 === 0 ? 12 : h % 12;
  return `${hour12} ${h < 12 ? 'am' : 'pm'}`;
}

/** Row height in px: sub-rows x 48 - 4, minimum 44 (UI-SPEC "Sub-row stacking"). */
export function rowHeight(subRows) {
  return Math.max(CELL_HEIGHT, subRows * SUB_ROW_PITCH - 4);
}

// ---- Packing ----

function cmpNum(a, b) {
  if (a === b) return 0;
  return a < b ? -1 : 1;
}

/**
 * Greedy sub-row packing for one network row. Games sort by kickoff, then booth rank (A first,
 * unranked last), then network id, then home team; each goes in the first sub-row whose last
 * cell ends at or before its kickoff. The A booth therefore sits on the top sub-row of every
 * kickoff window (D-03, D-11).
 * @param {WeekendGame[]} games - all with a numeric kickoffMin.
 * @param {number} blockMinutes
 * @returns {{placed: {game: WeekendGame, subRow: number}[], subRows: number}}
 */
export function packSubRows(games, blockMinutes) {
  const rank = (g) => (g.boothRank == null ? Infinity : g.boothRank);
  const ordered = [...games].sort(
    (a, b) => cmpNum(a.kickoffMin, b.kickoffMin)
      || cmpNum(rank(a), rank(b))
      || cmpNum(a.networkId ?? '', b.networkId ?? '')
      || a.home.localeCompare(b.home),
  );
  const ends = [];
  const placed = [];
  for (const game of ordered) {
    let r = ends.findIndex((end) => end <= game.kickoffMin);
    if (r === -1) {
      ends.push(0);
      r = ends.length - 1;
    }
    ends[r] = game.kickoffMin + blockMinutes;
    placed.push({ game, subRow: r });
  }
  return { placed, subRows: ends.length };
}

function precedenceIndex(ids) {
  const order = new Map(sortNetworks(ids.map((id) => ({ id }))).map((n, k) => [n.id, k]));
  return (id) => (order.has(id) ? order.get(id) : Infinity);
}

/**
 * Everything the render needs for one day of one sport.
 * Undated games (no ET date) appear in every day's strip, so nothing is dropped.
 * @param {WeekendGame[]} games - the whole week.
 * @param {{sport: 'cfb'|'nfl', day: string, width: number}} opts
 * @returns {{
 *   axis: {start: number, end: number, ticks: {min: number, label: string}[]}|null,
 *   pxh: number,
 *   laneWidth: number,
 *   rows: {id: string, label: string, subRows: number, height: number,
 *          cells: {game: WeekendGame, subRow: number, left: number, width: number}[]}[],
 *   tba: WeekendGame[],
 *   compact: WeekendGame[]
 * }}
 */
export function buildDayModel(games, { sport, day, width }) {
  const block = BLOCK_MINUTES[sport];
  const inDay = games.filter((g) => g.date === day || g.date == null);
  const byRow = new Map();
  const tba = [];
  const compact = [];
  for (const g of inDay) {
    const c = classifyGame(g);
    if (c.section === 'tba') tba.push(g);
    else if (c.section === 'compact') compact.push(g);
    else {
      if (!byRow.has(c.row)) byRow.set(c.row, []);
      byRow.get(c.row).push(g);
    }
  }
  const kickoffs = [...byRow.values()].flat().map((g) => g.kickoffMin);
  const range = axisRange(kickoffs, block);
  const pxh = range ? pxPerHour(width, (range.end - range.start) / 60) : 80;
  // The lane is the axis span at pxh, or the room beside the row header when that is wider: a
  // short day (the 120 cap) or floor rounding must not leave the rules ending mid-module
  // (18-UI-REVIEW items 9 and 11). A long day keeps its scroll width.
  const laneWidth = range
    ? Math.max(Math.round(((range.end - range.start) * pxh) / 60), width - ROW_HEAD_WIDTH)
    : 0;
  let axis = null;
  if (range) {
    // Hour ticks run to the axis end, and on across a stretched lane up to midnight, so the
    // axis never stops mid-module (18-UI-REVIEW item 9).
    const lastTick = Math.min(
      MIDNIGHT, range.start + Math.floor((laneWidth * 60) / pxh / 60) * 60,
    );
    const ticks = [];
    for (let m = range.start; m <= Math.max(range.end, lastTick); m += 60) {
      ticks.push({ min: m, label: tickLabel(m) });
    }
    axis = { ...range, ticks };
  }

  const prec = precedenceIndex([...byRow.keys()].filter((id) => id !== STREAMING_ROW));
  const ids = [...byRow.keys()].filter((id) => id !== STREAMING_ROW)
    .sort((a, b) => cmpNum(prec(a), prec(b)) || a.localeCompare(b));
  if (byRow.has(STREAMING_ROW)) ids.push(STREAMING_ROW);

  const rows = ids.map((id) => {
    const rowGames = byRow.get(id);
    const { placed, subRows } = packSubRows(rowGames, block);
    return {
      id,
      label: id === STREAMING_ROW ? 'Streaming' : (rowGames[0].networkName ?? id),
      subRows,
      height: rowHeight(subRows),
      cells: placed.map(({ game, subRow }) => ({
        game,
        subRow,
        left: Math.round(((game.kickoffMin - range.start) * pxh) / 60),
        width: Math.round((block * pxh) / 60) - 2,
      })),
    };
  });

  const rankOf = precedenceIndex([...new Set(inDay.map((g) => g.networkId).filter(Boolean))]);
  const idRank = (g) => (g.networkId == null ? Infinity : rankOf(g.networkId));
  tba.sort(
    (a, b) => cmpNum(a.date ?? '9999', b.date ?? '9999')
      || cmpNum(idRank(a), idRank(b)) || a.home.localeCompare(b.home),
  );
  compact.sort((a, b) => cmpNum(a.kickoffMin, b.kickoffMin) || cmpNum(idRank(a), idRank(b)));
  return { axis, pxh, laneWidth, rows, tba, compact };
}

// ---- Cell state, text, colour ----

/**
 * A cell's state (D-04, D-05, D-16): `known` (a crew exists), `tba` (no crew, kickoff still
 * ahead in ET), `not-listed` (no crew, kickoff passed or a past week).
 * @param {WeekendGame} game
 * @param {number} nowWall - ET wall minutes (see `etWallMinutes`).
 * @returns {'known'|'tba'|'not-listed'}
 */
export function cellState(game, nowWall) {
  if (game.crewKnown) return 'known';
  if (game.past) return 'not-listed';
  if (game.date != null && game.kickoffMin != null
      && etWallMinutes(game.date, game.kickoffMin) <= nowWall) {
    return 'not-listed';
  }
  return 'tba';
}

/**
 * Whether a weekend game has not been played at `nowWall`: not in a past week, no score or
 * figure, and its kickoff (when known) still ahead in ET. The same kickoff rule flips its cell
 * from "Crew TBA" to "Crew not listed", so the panel's "Not played yet." (D-22) never outlives
 * the cell's (18-13 F3). The network's rating cause plays no part (18-13 F4).
 * @param {object} game - from `cfbWeekendGames` or `nflWeekendGames`.
 * @param {number} nowWall - ET wall minutes (see `etWallMinutes`).
 * @returns {boolean}
 */
export function isUnplayedGame(game, nowWall) {
  if (game.past || game.scored) return false;
  if (game.date != null && game.kickoffMin != null) {
    return etWallMinutes(game.date, game.kickoffMin) > nowWall;
  }
  return true;
}

function surname(name) {
  const parts = name.trim().split(/\s+/);
  return parts[parts.length - 1];
}

/**
 * Surnames (lower case) shared by two or more different people among the games' cells, so the
 * booth line can add a first initial (`T. Smith`).
 * @param {WeekendGame[]} games
 * @returns {Set<string>}
 */
export function collidingSurnames(games) {
  const seen = new Map();
  for (const g of games) {
    for (const n of [g.pbp, g.analyst]) {
      if (!n) continue;
      const key = surname(n).toLowerCase();
      if (!seen.has(key)) seen.set(key, new Set());
      seen.get(key).add(n);
    }
  }
  return new Set([...seen].filter(([, names]) => names.size > 1).map(([k]) => k));
}

function shortName(name, collide) {
  const last = surname(name);
  if (collide && collide.has(last.toLowerCase()) && name.trim().includes(' ')) {
    return `${name.trim()[0]}. ${last}`;
  }
  return last;
}

/**
 * The booth line of a cell.
 * @param {WeekendGame} game
 * @param {'known'|'tba'|'not-listed'} state
 * @param {Set<string>} [collide] - from `collidingSurnames`.
 * @returns {{star: boolean, text: string, weight: 600|400}}
 */
export function boothLine(game, state, collide) {
  if (state === 'known' && (game.pbp || game.analyst)) {
    const pbp = game.pbp ? shortName(game.pbp, collide) : 'Play-by-play TBA';
    const analyst = game.analyst ? shortName(game.analyst, collide) : 'Analyst TBA';
    return { star: Boolean(game.lead), text: `${pbp} · ${analyst}`, weight: 600 };
  }
  return {
    star: false,
    text: state === 'not-listed' ? 'Crew not listed' : 'Crew TBA',
    weight: 400,
  };
}

/**
 * The matchup, `#20 Florida @ #5 Georgia`; `vs` for neutral sites; NFL carries no ranks.
 * @param {WeekendGame} game
 * @returns {string}
 */
export function matchupText(game) {
  const side = (name, rank) => (rank != null && game.sport !== 'nfl' ? `#${rank} ${name}` : name);
  return `${side(game.away, game.awayRank)} ${game.neutral ? 'vs' : '@'} `
    + `${side(game.home, game.homeRank)}`;
}

/**
 * The family colour mixed toward black, in 1% steps, until white text on it reaches
 * `KNOWN_TEXT_CONTRAST`. Disney and light conference already pass and come back unchanged.
 * @param {string} hex
 * @returns {string}
 */
function deepenForWhite(hex) {
  for (let w = 100; w >= 0; w -= 1) {
    const out = mixHex(hex, '#000000', w / 100);
    if (contrastRatio(out, '#FFFFFF') >= KNOWN_TEXT_CONTRAST) return out;
  }
  return '#000000';
}

/**
 * Cell colours (D-05). Known: the family fill deepened for white text at 7:1, no edge (the
 * mid-tone fills read poorly with black text; user sign-off 2026-10-26). Crew TBA or not
 * listed: a tint of the family over the page background with `--ink` text and a solid family
 * left edge. An unknown family folds to `other`.
 * @param {string} family
 * @param {'light'|'dark'} theme
 * @param {'known'|'tba'|'not-listed'} state
 * @returns {{bg: string, fg: string, edge: string|null}}
 */
export function cellColors(family, theme, state) {
  const key = familyKey(family);
  const solid = FAMILY_COLORS[theme][key];
  if (state === 'known') return { bg: deepenForWhite(solid), fg: '#FFFFFF', edge: null };
  return { bg: mixHex(solid, PAGE_BG[theme], TINT_WEIGHT), fg: INK[theme], edge: solid };
}

// ---- Picks and strip ----

/** Controls this view does not use: reset to defaults so a hidden pick cannot filter (D-20). */
const UNUSED_KEYS = Object.freeze(['seasons', 'slots', 'postseason', 'game', 'cats', 'category']);

/**
 * The filter state the weekend view reads: Seasons, Kickoff slots, Bowls/Playoffs, Game and
 * Category reset to defaults; every other pick is kept (D-20, D-21). Works for the CFB state
 * (`slots`, `postseason`, `game`) and the NFL state (`cats`, `seasons`).
 * @param {object} state
 * @param {object} defaults
 * @returns {object}
 */
export function weekendPickState(state, defaults) {
  const out = { ...state };
  for (const key of UNUSED_KEYS) {
    if (key in defaults) out[key] = defaults[key];
  }
  return out;
}

/** Whether the Time TBA strip starts collapsed (D-13): 7 or more games. */
export function stripCollapsedByDefault(count) {
  return count >= STRIP_COLLAPSE_AT;
}
