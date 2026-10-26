/**
 * NFL This weekend view (Phase 18, D-01, D-12): the shared timeline (desktop) or list (phone) over
 * one week of NFL games, laid out by `modules/weekend-view.js` and `modules/weekend-list.js`.
 * The NFL master filter contributes Team, Announcers and Booths picks only (Seasons and Category
 * are not used here, D-20, D-21). Credits: nflverse and 506 Sports, plus Wikipedia (CC BY-SA
 * 4.0) only when a slot-basis network shows; the NFL page never credits a CFB data source.
 *
 * Everything is built with createElement/textContent. State: `week` and `day` live in the NFL
 * state (null means the current week and the default day) and round-trip through the URL.
 */
import { renderWeekend } from '../../../modules/weekend-view.js';
import { renderWeekendList } from '../../../modules/weekend-list.js';
import { dayLabel, dayTabs, defaultDay } from '../../../modules/weekend.js';
import { PHONE_QUERY } from '../../../modules/breakpoints.js';
import { nflWeekendGames, nflWeekendPasses } from '../weekend-data.js';
import { weekendCurrentWeek, weekendWeeks } from '../state.js';

const refs = { ctx: null, host: null, instance: null };
let current = null;

function el(tag, className) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  return node;
}

function hasPick(state) {
  return state.teams.length > 0 || state.people.length > 0 || state.booths.length > 0;
}

/** The weekend week to show and the effective day. */
function resolve(model, state) {
  const weeks = weekendWeeks(model);
  const currentWeek = weekendCurrentWeek(model);
  const week = state.week ?? currentWeek;
  const games = week == null ? [] : nflWeekendGames(model, week);
  const days = dayTabs(games);
  const day = state.day != null && days.includes(state.day) ? state.day : defaultDay(days, 'nfl');
  return { weeks, currentWeek, week, games, days, day };
}

function buildModel(ctx, r) {
  const { model } = ctx;
  const season = model.upcomingRaw?.season?.[0] ?? model.freshness?.season ?? model.seasons[1];
  // Wikipedia is credited only when a slot-basis network shows on the shown day (RT-03).
  const slotShown = r.games.some((g) => g.networkBasis === 'slot' && (g.date === r.day || g.date == null));
  const links = slotShown ? { wikipedia: `https://en.wikipedia.org/wiki/${season}_NFL_season` } : {};
  return {
    sport: 'nfl',
    weekLabel: r.week == null ? 'No week' : `Week ${r.week}`,
    weekNumber: r.week,
    weeks: r.weeks.map((n) => ({ label: `Week ${n}`, number: n })),
    isLatestWeek: r.week === r.currentWeek,
    games: r.games,
    day: r.day,
    past: r.currentWeek != null && r.week != null && r.week < r.currentWeek,
    missing: false,
    freshness: model.weekend ?? {},
    links,
  };
}

function setSubtitle(ctx, r) {
  const parts = [r.week == null ? 'No week' : `Week ${r.week}`];
  if (r.day) parts.push(dayLabel(r.day));
  parts.push('All times ET');
  ctx.setSubtitle([document.createTextNode(parts.join(' · '))]);
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
    passes: (g) => (hasPick(state) ? nflWeekendPasses(model, state, g) : null),
    onDay: (day) => ctx.setState({ day }),
    onWeek: (delta) => {
      const at = r.weeks.indexOf(r.week);
      const to = r.weeks[at + delta];
      if (to != null) ctx.setState({ week: to, day: null });
    },
    onOpen: (game, opener) => {
      if (game.block === 'upcoming') ctx.openUpcoming(game.index, opener);
      else ctx.openGame(game.index, opener);
    },
  };
  if (fixedNow) opts.now = new Date(fixedNow);
  const phone = window.matchMedia(PHONE_QUERY).matches;
  refs.instance = (phone ? renderWeekendList : renderWeekend)(refs.host, wk, opts);
  current = { week: r.week, day: r.day, days: r.days, games: r.games.length, slotCredit: Boolean(wk.links.wikipedia) };
}

export function resize() {}

export function testModel() {
  return { view: 'weekend', ...(current ?? { week: null, day: null, days: [], games: 0, slotCredit: false }) };
}
