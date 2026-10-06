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
export const MONTHS = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
];

/** Time-slot filter labels, long form (D-11, SITE-11, D-20: four slots). */
export const SLOT_LABELS = {
  noon: 'Noon (before 2 PM ET)',
  afternoon: 'Afternoon (2–6 PM ET)',
  prime: 'Prime time (6–10 PM ET)',
  late: 'After dark (10 PM ET or later)',
};

/** Short time-slot labels for the tooltip/panel (D-19, D-20: four slots). */
export const SLOT_SHORT_LABELS = {
  noon: 'Noon',
  afternoon: 'Afternoon',
  prime: 'Prime time',
  late: 'After dark',
};

/** Detail-panel labels for a playoff telecast's round (D-17). */
export const CFP_ROUND_LABELS = {
  first_round: 'CFP first round',
  quarterfinal: 'CFP quarterfinal',
  semifinal: 'CFP semifinal',
  championship: 'CFP championship',
};

/**
 * CFP rounds played at a bowl (F3). The playoff's quarterfinals and
 * semifinals are always hosted by the New Year's Six bowls, so a game in one
 * of these rounds is both a playoff game and a bowl game. First-round games
 * are on campus sites and the championship is its own event, so neither
 * counts; a playoff game with no recorded round is never assumed to be at a
 * bowl. Page-only: this is derived from `playoff_round`, not a contract field.
 */
export const CFP_BOWL_ROUNDS = new Set(['quarterfinal', 'semifinal']);

/**
 * The four playoff entries of the Game picker, in fixed order (D-11). Picker
 * labels differ from the detail-panel `CFP_ROUND_LABELS` on purpose (UI-SPEC).
 */
export const CFP_GAME_DEFS = Object.freeze([
  Object.freeze({ slug: 'cfp-national-championship', label: 'CFP National Championship', round: 'championship', phrase: 'CFP national championships' }),
  Object.freeze({ slug: 'cfp-semifinal', label: 'CFP Semifinal', round: 'semifinal', phrase: 'CFP semifinals' }),
  Object.freeze({ slug: 'cfp-quarterfinal', label: 'CFP Quarterfinal', round: 'quarterfinal', phrase: 'CFP quarterfinals' }),
  Object.freeze({ slug: 'cfp-first-round', label: 'CFP First Round', round: 'first_round', phrase: 'CFP first round games' }),
]);

/** New Year's Six bowl franchise slugs, listed first among bowls (D-09). */
export const NEW_YEARS_SIX = Object.freeze([
  'rose-bowl',
  'sugar-bowl',
  'orange-bowl',
  'cotton-bowl',
  'fiesta-bowl',
  'peach-bowl',
]);

/**
 * Title phrase for a game (D-18): CFP entries use their plural phrase; a
 * rivalry takes its curated article ('the Iron Bowl', 'Bedlam', 'The Game';
 * WR-02); a bowl label starting with the case-sensitive 'The ' stays as is,
 * else 'the {label}'.
 * @param {{kind: string, label: string, phrase?: string, article?: string|null}} game
 * @returns {string}
 */
export function gameTitlePhrase(game) {
  if (game.kind === 'cfp') return game.phrase;
  if (game.kind === 'rivalry') return game.article === 'the' ? `the ${game.label}` : game.label;
  if (game.label.startsWith('The ')) return game.label;
  return `the ${game.label}`;
}

/**
 * Desktop hover title for a Game row (D-06, WR-03): a rivalry shows its two
 * teams, prefixed with its full name when the visible label is truncated; any
 * other row gets its full name only when truncated, else no title (null).
 * @param {{label: string, teams?: string[]}} game
 * @param {boolean} truncated - whether the row's label is cut off by an ellipsis.
 * @returns {string|null}
 */
export function gameRowTitle(game, truncated) {
  const teams = game.teams ? `${game.teams[0]} vs ${game.teams[1]}` : null;
  if (truncated) return teams ? `${game.label}: ${teams}` : game.label;
  return teams;
}

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
  spread: 'Spread',
  excitement: 'Excitement (CFBD)',
  date: 'Date',
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
 * True when an ET calendar date (`YYYY-MM-DD`) falls on a Saturday. This is
 * only the weekday half of the time-slot label's gate; callers never call
 * this alone to decide whether to show "Prime time"/"Afternoon"/"Noon" --
 * they gate on `game_type` through `showsTimeSlot` below (D-19), which also
 * excludes bowl/playoff games that happen to fall on a Saturday.
 * @param {string} ymd - e.g. "2019-09-07".
 * @returns {boolean}
 */
export function isSaturday(ymd) {
  const [year, month, day] = ymd.split('-').map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCDay() === 6;
}

/**
 * Whether the time-slot label ("Prime time"/"Afternoon"/"Noon") should show
 * for telecast `i` (D-19): only a regular-season game, with a recorded
 * time slot, on a Saturday. This replaces the Saturday-only proxy that let
 * a Saturday bowl game through.
 * @param {object} data - a `prepareData` result.
 * @param {number} i - telecast index.
 * @returns {boolean}
 */
export function showsTimeSlot(data, i) {
  const t = data.t;
  return t.game_type[i] === 'regular' && t.time_slot[i] != null && isSaturday(t.date[i]);
}

/**
 * The single source for telecast `i`'s game type (D-17, notes-4 A1/A2a): null
 * for a regular-season game (nothing to show), otherwise the icon `kind` --
 * 'bowl' for a non-CFP postseason game, 'playoff' for a College Football
 * Playoff game -- and its visible `label`: "Bowl", or the specific CFP round
 * (falling back to "College Football Playoff" when the round itself isn't
 * recorded). `atBowl` is true for a CFP game also played at a bowl
 * (`CFP_BOWL_ROUNDS`), which shows the bowl icon before the trophy; it is false
 * for a plain bowl, whose `kind` is already 'bowl'. `gameTypeKind`,
 * `gameTypeLabel` and `namedGameInfo` are views of this, so they can never
 * disagree.
 * @param {object} data - a `prepareData` result.
 * @param {number} i - telecast index.
 * @returns {{kind: "bowl"|"playoff", label: string, atBowl: boolean}|null}
 */
export function gameTypeInfo(data, i) {
  const t = data.t;
  const type = t.game_type[i];
  if (type === 'regular') return null;
  if (type === 'bowl') return { kind: 'bowl', label: 'Bowl', atBowl: false };
  const round = t.playoff_round[i];
  const label = round != null ? (CFP_ROUND_LABELS[round] ?? 'College Football Playoff') : 'College Football Playoff';
  return { kind: 'playoff', label, atBowl: CFP_BOWL_ROUNDS.has(round) };
}

/**
 * Labels telecast `i`'s game type for the detail panel (D-17): null for a
 * regular-season game (no label shown), "Bowl" for a non-CFP postseason
 * game, and the specific CFP round for a playoff game.
 * @param {object} data - a `prepareData` result.
 * @param {number} i - telecast index.
 * @returns {string|null}
 */
export function gameTypeLabel(data, i) {
  return gameTypeInfo(data, i)?.label ?? null;
}

/**
 * The DOM-free kind behind telecast `i`'s game-type icon: null for a
 * regular-season game (no icon), 'bowl', or 'playoff'.
 * @param {object} data - a `prepareData` result.
 * @param {number} i - telecast index.
 * @returns {"bowl"|"playoff"|null}
 */
export function gameTypeKind(data, i) {
  return gameTypeInfo(data, i)?.kind ?? null;
}

/**
 * Telecast `i`'s rivalry name (04.10 D-11/D-12), read from
 * `lookups.rivalries`; null when the game is not a named rivalry.
 * @param {object} data - a `prepareData` result.
 * @param {number} i - telecast index.
 * @returns {string|null}
 */
export function rivalryName(data, i) {
  return data.lookups.rivalries?.[data.t.rivalry?.[i]]?.name ?? null;
}

/**
 * The one source for the name shown beside a named game's icons in the hover
 * tooltip, its plotly-fallback text, and (via `rivalryName`) the modal (04.10
 * D-10). A rivalry shows its name; a bowl its core name (never the sponsor);
 * a CFP game at a bowl "<core> · <round>"; a CFP game elsewhere its round
 * label; a regular non-rivalry game null. A rivalry game is always regular
 * season, so the rivalry branch never collides with a bowl or CFP branch.
 * @param {object} data - a `prepareData` result.
 * @param {number} i - telecast index.
 * @returns {{icons: ("bowl"|"playoff"|"rivalry")[], text: string}|null}
 */
export function namedGameInfo(data, i) {
  const rivalry = rivalryName(data, i);
  if (rivalry != null) return { icons: ['rivalry'], text: rivalry };
  const info = gameTypeInfo(data, i);
  if (info == null) return null;
  const core = data.lookups.bowls?.[data.t.bowl?.[i]]?.core ?? null;
  if (info.kind === 'bowl') return { icons: ['bowl'], text: core ?? 'Bowl' };
  if (info.atBowl) {
    return { icons: ['bowl', 'playoff'], text: core ? `${core} \u00b7 ${info.label}` : info.label };
  }
  return { icons: ['playoff'], text: info.label };
}

/**
 * Formats telecast `i`'s conference line for the detail panel (D-09):
 * away vs. home, matching `formatMatchup`'s "Away at Home" order. A side
 * with no recorded conference reads "Not recorded"; when neither side has
 * one, returns null (no row shown).
 * @param {object} data - a `prepareData` result.
 * @param {number} i - telecast index.
 * @returns {string|null}
 */
export function conferenceLine(data, i) {
  const t = data.t;
  const homeIdx = t.home_conference[i];
  const awayIdx = t.away_conference[i];
  if (homeIdx == null && awayIdx == null) return null;
  const away = awayIdx != null ? data.lookups.conferences[awayIdx].name : 'Not recorded';
  const home = homeIdx != null ? data.lookups.conferences[homeIdx].name : 'Not recorded';
  return `${away} vs ${home}`;
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
  if (n == null) return NO_RATING_LABEL;
  return n.toLocaleString('en-US');
}

/** Label for a game with no public rating (04.13). */
export const NO_RATING_LABEL = 'No public rating';

/**
 * Why a game has no public rating, in UI-SPEC wording (04.13 D-10).
 * @param {object} data - a `prepareData` result.
 * @param {number} i - telecast index.
 * @returns {string|null} null for a rated game.
 */
export function causeText(data, i) {
  const cause = data.t.cause[i];
  if (cause == null) return null;
  if (cause === 'rarely_rated') {
    return `${data.lookups.networks[data.t.network[i]].name} games are rarely rated`;
  }
  if (cause === 'pending') return 'viewership not posted yet';
  if (cause === 'rr_dip') return 'few figures were compiled for 2021–24';
  return 'no figure was published';
}

/** Full line: "No public rating · {cause}" (plain text; callers use textContent). */
export function noRatingLine(data, i) {
  return `${NO_RATING_LABEL} · ${causeText(data, i)}`;
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

const CREW_ROLE_ORDER = { pbp: 0, analyst: 1 };

/**
 * Structured crew lines for telecast `i`. With `mainOnly`, keeps only
 * main-feed entries ordered pbp, analyst, then the rest (stable); otherwise
 * every entry in data order.
 * @param {object} data - a `prepareData` result.
 * @param {number} i - telecast index.
 * @param {{mainOnly?: boolean, selected?: Set<number>}} [opts]
 * @returns {{person: number, name: string, role: string, feed: string, selected: boolean}[]}
 */
export function crewEntries(data, i, { mainOnly = false, selected = new Set() } = {}) {
  let entries = data.t.crew[i].map((entry) => ({
    person: entry.person,
    name: data.lookups.people[entry.person].name,
    role: entry.role,
    feed: entry.feed,
    selected: selected.has(entry.person),
  }));
  if (mainOnly) {
    entries = entries.filter((entry) => entry.feed === 'main');
    const rank = (entry) => CREW_ROLE_ORDER[entry.role] ?? 2;
    entries = entries
      .map((entry, idx) => ({ entry, idx }))
      .sort((a, b) => rank(a.entry) - rank(b.entry) || a.idx - b.idx)
      .map(({ entry }) => entry);
  }
  return entries;
}

/**
 * Data indexes of the people in `state.people` (ids not in the data skipped).
 * @param {object} data - a `prepareData` result.
 * @param {{people: string[]}} state
 * @returns {Set<number>}
 */
export function selectedPersonIndexes(data, state) {
  const result = new Set();
  for (const id of state.people ?? []) {
    const idx = data.personIndexById.get(id);
    if (idx !== undefined) result.add(idx);
  }
  return result;
}

/** Typographic minus used in all spread copy. */
export const MINUS = '\u2212';

/**
 * Spread line copy (04.8 D-04, D-05): a decided game names the winner and the
 * winner-signed line; a game with no decided result names the favorite and why.
 * @param {object} data - a `prepareData` result.
 * @param {number} i - telecast index.
 * @returns {string} e.g. "Spread: Northfield \u22123.5", "Spread: Pick'em",
 *   "Spread: Boulder Pass \u22122.0 (no final score yet)".
 */
export function spreadLabel(data, i) {
  const t = data.t;
  const s = t.home_spread[i];
  if (s == null) return 'Spread: not available';
  const home = data.lookups.teams[t.home_team[i]].name;
  const away = data.lookups.teams[t.away_team[i]].name;
  const x = t.spread[i];
  if (x != null) {
    if (s === 0) return "Spread: Pick'em";
    const winner = t.home_points[i] > t.away_points[i] ? home : away;
    return `Spread: ${winner} ${x < 0 ? MINUS : '+'}${Math.abs(x).toFixed(1)}`;
  }
  const reason = t.home_points[i] == null || t.away_points[i] == null ? 'no final score yet' : 'game tied';
  if (s === 0) return `Spread: Pick'em (${reason})`;
  return `Spread: ${s < 0 ? home : away} ${MINUS}${Math.abs(s).toFixed(1)} (${reason})`;
}

/**
 * Axis line text for the tooltip and modal.
 * @param {object} data - a `prepareData` result.
 * @param {number} i - telecast index.
 * @param {"spread"|"excitement"|"date"} axis - "date" shows both halves,
 *   spread first, joined by " \u00b7 ".
 * @returns {string}
 */
export function axisValueText(data, i, axis) {
  if (axis === 'date') {
    return `${spreadLabel(data, i)} \u00b7 ${formatAxisValue('excitement', data.t.excitement[i])}`;
  }
  if (axis === 'excitement') return formatAxisValue('excitement', data.t.excitement[i]);
  return spreadLabel(data, i);
}

/** Short axis value labels, distinct from the longer AXIS_LABELS toggle copy. */
const AXIS_VALUE_LABELS = { spread: 'Spread', excitement: 'Excitement' };

/**
 * Formats a single axis value for hover/panel display; null is never coerced
 * to a number.
 * @param {"spread"|"excitement"} axis
 * @param {number|null} value
 * @returns {string} e.g. "Excitement: 8.4" or "...: not available".
 */
export function formatAxisValue(axis, value) {
  if (value == null) return `${AXIS_LABELS[axis]}: not available`;
  const label = AXIS_VALUE_LABELS[axis];
  return `${label}: ${value.toFixed(1)}`;
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

/** Labels a single log-axis tick value, "K" below 1,000,000 and "M" at/above
 * (e.g. "500K", "200K", "100K", then "1M", "2M", ...) -- values in the
 * hundreds-of-thousands read clearer as whole thousands than as a fraction
 * of a million. */
function logTickLabel(value) {
  if (value < 1000000) return `${value / 1000}K`;
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
 * Strips a trailing/nested parenthetical note from a network's display name,
 * for the chart tooltip only (SITE-04): the canonical name in
 * `data/reference/networks.csv` sometimes carries a methodology aside (e.g.
 * "ESPN Plus (regional insert package, pre-2018)"), which belongs in the
 * detail panel/table's fuller name, not the tooltip's minimal one.
 * @param {string} name
 * @returns {string}
 */
export function stripNetworkNote(name) {
  return name.replace(/\s*\([^)]*\)/g, '').trim();
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
 * How many networks the summary detail names before "+N more". A broad filter
 * can pass games on 20 networks; listing them all wraps the line past the
 * selection band's reserved height and moves the chart (SITE-20, D-33). Three
 * names plus the count keep the line inside that reserve at 800px.
 */
export const SUMMARY_NETWORK_LIMIT = 3;

/**
 * The summary detail's network list, most telecasts first (A6): every name when
 * there are at most `SUMMARY_NETWORK_LIMIT`, else the first ones and "+N more".
 * @param {string[]} networks
 * @returns {string}
 */
function summaryNetworks(networks) {
  if (networks.length <= SUMMARY_NETWORK_LIMIT) return networks.join(', ');
  const more = networks.length - SUMMARY_NETWORK_LIMIT;
  return `${networks.slice(0, SUMMARY_NETWORK_LIMIT).join(', ')} +${more} more`;
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
    const count =
      summary.of != null
        ? `${n.toLocaleString('en-US')} of ${summary.of.toLocaleString('en-US')} rated telecasts`
        : n === 1
          ? '1 rated telecast'
          : `${n} rated telecasts`;
    let detail = `${summary.seasonMin}–${summary.seasonMax} · ${summaryNetworks(summary.networks)}`;
    if (summary.altCount > 0) {
      const gameWord = summary.altCount === 1 ? 'game' : 'games';
      detail += ` · includes ${summary.altCount} alt-cast ${gameWord}`;
    }
    return { count, detail };
  }
  if (summary.kind === 'no-filter-match') {
    return {
      count: '',
      detail:
        'No rated telecasts match these filters. Widen the seasons or clear a filter to see games.',
    };
  }
  if (summary.kind === 'no-game-match') {
    return {
      count: '',
      detail: `No telecasts of ${summary.phrase} match these filters. Widen the seasons or clear a filter to see games.`,
    };
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
