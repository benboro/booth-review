/**
 * NFL This weekend view (Phase 18, D-01, D-12): the shared timeline (desktop) or list (phone) over
 * one week of NFL games, laid out by `modules/weekend-view.js` and `modules/weekend-list.js`.
 * The NFL master filter contributes Team, Announcers and Booths picks only (Seasons and Category
 * are not used here, D-20, D-21). Credits: nflverse and 506 Sports, plus Wikipedia (CC BY-SA
 * 4.0) only when a slot-basis network shows; the NFL page never credits a CFB data source.
 *
 * One page per week (user 2026-11-09): no day tabs; the timeline stacks each day's rows in date
 * order (Thursday above Sunday above Monday) on one time axis, and the map shows every game of
 * the week.
 *
 * Everything is built with createElement/textContent. State: `week` lives in the NFL state
 * (null means the current week) and round-trips through the URL.
 */
import { renderWeekend } from '../../../modules/weekend-view.js';
import { renderWeekendList } from '../../../modules/weekend-list.js';
import { renderWeekendMap } from '../../../modules/weekend-map-view.js';
import { dayTabs, etParts, etWallMinutes, isUnplayedGame } from '../../../modules/weekend.js';
import { PHONE_QUERY } from '../../../modules/breakpoints.js';
import { nflWeekendGames, nflWeekendPasses } from '../weekend-data.js';
import { weekendCurrentWeek, weekendWeeks } from '../state.js';

const refs = { ctx: null, host: null, instance: null, kind: null };
let current = null;

function el(tag, className) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  return node;
}

function hasPick(state) {
  return state.teams.length > 0 || state.people.length > 0 || state.booths.length > 0;
}

/** The weekend week to show; every day of it shows. */
function resolve(model, state) {
  const weeks = weekendWeeks(model);
  const currentWeek = weekendCurrentWeek(model);
  const week = state.week ?? currentWeek;
  const games = week == null ? [] : nflWeekendGames(model, week);
  return { weeks, currentWeek, week, games, days: dayTabs(games) };
}

function buildModel(ctx, r) {
  const { model } = ctx;
  const season = model.upcomingRaw?.season?.[0] ?? model.freshness?.season ?? model.seasons[1];
  // Wikipedia is credited only when a slot-basis network shows in the shown week (RT-03). The
  // article is rebuilt from the season; tests/test_nfl_slot_credit.py pins this pattern to every
  // source_url in data/reference/nfl_slot_networks.csv, since the contract ships no slot URL
  // (18-REVIEW IN-04).
  const slotShown = r.games.some((g) => g.networkBasis === 'slot');
  const links = slotShown ? { wikipedia: `https://en.wikipedia.org/wiki/${season}_NFL_season` } : {};
  return {
    sport: 'nfl',
    weekLabel: r.week == null ? 'No week' : `Week ${r.week}`,
    weekNumber: r.week,
    weeks: r.weeks.map((n) => ({ label: `Week ${n}`, number: n })),
    isLatestWeek: r.week === r.currentWeek,
    games: r.games,
    day: null,
    allDays: true,
    // Without a weekend stamp the tab shows the latest played week: a past week (18-13 F17).
    past: r.week != null
      && (model.weekend == null || (r.currentWeek != null && r.week < r.currentWeek)),
    missing: false,
    freshness: model.weekend ?? {},
    links,
  };
}

function setSubtitle(ctx, r) {
  const week = r.week == null ? 'No week' : `Week ${r.week}`;
  ctx.setSubtitle([document.createTextNode(`${week}, all times ET`)]);
}

export function mount(container, ctx) {
  refs.ctx = ctx;
  refs.host = el('div', 'nfl-weekend-host');
  container.append(refs.host);
}

/** Stops the clock timer and drops the grid while another tab is showing. */
export function deactivate() {
  refs.instance?.destroy();
  refs.instance = null;
  refs.kind = null;
}

export function render(ctx) {
  const { model } = ctx;
  const state = ctx.getState();
  const r = resolve(model, state);
  const wk = buildModel(ctx, r);
  setSubtitle(ctx, r);
  // A fixed clock for tests: set before load with an init script, or on the test hooks.
  const fixedNow = window.__nflWeekendNow ?? (window.__nflTestHooks && window.__nflTestHooks.weekendNow);
  const opts = {
    wview: state.wview,
    onView: (v) => ctx.setState({ wview: v === 'map' ? 'map' : null }),
    passes: (g) => (hasPick(state) ? nflWeekendPasses(model, state, g) : null),
    onWeek: (delta) => {
      const at = r.weeks.indexOf(r.week);
      const to = r.weeks[at + delta];
      if (to != null) ctx.setState({ week: to, day: null });
    },
    onOpen: (game, opener) => {
      if (game.block !== 'upcoming') {
        ctx.openGame(game.index, opener, { weekend: true });
        return;
      }
      // The kickoff rule that turns the cell to "Crew not listed" also ends "Not played yet."
      // (18-13 F3, WR-01): an upcoming row stays one until the next build after the game.
      const now = etParts(opts.now ?? new Date());
      const unplayed = isUnplayedGame(game, etWallMinutes(now.date, now.minutes));
      ctx.openUpcoming(game.index, opener, { unplayed, weekend: true });
    },
  };
  if (fixedNow) opts.now = new Date(fixedNow);
  const phone = window.matchMedia(PHONE_QUERY).matches;
  const kind = state.wview === 'map' ? 'map' : 'timeline';
  // Leaving the map purges its Plotly node; map to map re-renders in place (no destroy between).
  if (refs.kind === 'map' && kind !== 'map') deactivate();
  refs.instance = kind === 'map'
    ? renderWeekendMap(refs.host, wk, opts)
    : (phone ? renderWeekendList : renderWeekend)(refs.host, wk, opts);
  refs.kind = kind;
  // The selection bar's summary counts the week's games (18-UI-REVIEW item 6, now the whole week).
  const matching = hasPick(state) ? r.games.filter((g) => opts.passes(g) === true).length : r.games.length;
  current = {
    week: r.week, day: null, days: r.days, games: r.games.length,
    slotCredit: Boolean(wk.links.wikipedia), counts: { matching, total: r.games.length },
  };
}

export function resize() {}

export function testModel() {
  return { view: 'weekend', ...(current ?? { week: null, day: null, days: [], games: 0, slotCredit: false }) };
}

/** The shown week's `{ matching, total }` for the host's summary line, or null before a render. */
export function summaryCounts() {
  return current ? current.counts : null;
}
