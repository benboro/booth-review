/**
 * This weekend render (Phase 18, plan 09): the desktop timeline for both sports, built from the
 * plain layout model in weekend.js. Sport-neutral: the CFB and NFL hosts hand it a model and a
 * few callbacks and never reach into the DOM it builds.
 *
 * DOM safety (T-18-28, the T-04.4-09 rule): every node is built with createElement,
 * textContent and setAttribute only; no markup-injecting API appears in this file. An `img src`
 * comes only from `logoFor()` through `networkMark`, and every link goes through `safeHref`.
 *
 * Contract for the hosts (plans 10 and 11):
 *   renderWeekend(host, model, opts) -> { destroy() }
 *   model = { sport, weekLabel, weekNumber, weeks: [{label, number}], isLatestWeek, games,
 *             day, past, missing, freshness, links }
 *   opts  = { width, now, passes(game), networksPicked(networkId), onDay(day), onWeek(delta),
 *             onOpen(game, openerEl) }
 */

import {
  WEEKEND_FADED_OPACITY, boothLine, buildDayModel, cellColors, cellState,
  collidingSurnames, dayLabel, dayTabs, defaultDay, etParts, etWallMinutes, matchupText,
  stripCollapsedByDefault,
} from './weekend.js';
import { makeCaretIcon } from './icons.js';
import { networkMark } from './network.js';
import { safeHref } from './panel-parts.js';
import { attachScrollCue } from './scroll-cue.js';
import { currentTheme, onThemeChange } from './theme.js';

const FALLBACK_WIDTH = 1440;
const RESIZE_DEBOUNCE_MS = 120;
const TICK_MS = 60000;
const ESPN_PRESS_ROOM = 'https://www.espnpressroom.com/';
const ROW_HEAD_WIDTH = 96;
const SUB_ROW_PITCH = 48;

/** Small element helper: tag, class, text. */
export function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
}

// ---- Formatting ----

/** `12:30` (no meridiem; the axis carries it). */
export function clockText(min) {
  const h = Math.floor(min / 60) % 24;
  const m = min % 60;
  return `${h % 12 === 0 ? 12 : h % 12}:${String(m).padStart(2, '0')}`;
}

/** `12:30 pm`. */
export function clock12(min) {
  const h = Math.floor(min / 60) % 24;
  return `${clockText(min)} ${h < 12 ? 'am' : 'pm'}`;
}

/** An ISO UTC stamp as ET text: `Thu. Oct. 29, 9:14 pm ET` (or the date alone). */
export function etStamp(iso, { withTime = true } = {}) {
  const parts = etParts(new Date(iso));
  const day = dayLabel(parts.date);
  return withTime ? `${day}, ${clock12(parts.minutes)} ET` : day;
}

// ---- Shared context ----

/**
 * Everything one render pass needs: theme, the ET clock, the day's model and the pick helpers.
 * @param {object} model
 * @param {object} opts
 * @param {{day: string|null, width: number}} state
 */
export function makeContext(model, opts, state) {
  const theme = currentTheme();
  const nowDate = typeof opts.now === 'function' ? opts.now() : (opts.now ?? new Date());
  const np = etParts(nowDate);
  const nowWall = etWallMinutes(np.date, np.minutes);
  const passes = opts.passes ?? (() => null);
  const networksPicked = opts.networksPicked ?? (() => null);
  const days = dayTabs(model.games);
  const day = state.day != null && days.includes(state.day) ? state.day : defaultDay(days, model.sport);
  const inDay = model.games.filter((g) => g.date === day || g.date == null);
  const dayModel = buildDayModel(model.games, { sport: model.sport, day, width: state.width });
  const anyPick = model.games.some((g) => passes(g) !== null);
  const collide = collidingSurnames(inDay);
  const open = opts.onOpen ?? (() => {});
  return {
    model, opts, state, theme, nowDate, nowParts: np, nowWall, passes, networksPicked, days, day,
    inDay, dayModel, anyPick, collide, open,
    countFor(d) {
      return model.games.filter((g) => (g.date === d || g.date == null) && passes(g) === true).length;
    },
    /** Whole-row fade from a Networks pick: every game in the row fails it. */
    rowFaded(games) {
      return games.length > 0 && games.every((g) => networksPicked(g.networkId) === false);
    },
  };
}

/** Applies the fade or ring of an active pick to a node; `rowFaded` overrides the cell's own. */
export function applyPick(node, game, ctx, rowFaded = false) {
  const p = ctx.passes(game);
  if (rowFaded || p === false) {
    node.classList.add('is-faded');
    node.style.opacity = String(WEEKEND_FADED_OPACITY);
  } else if (p === true) {
    node.classList.add('is-match');
  }
}

// ---- Cell text ----

function crewSentence(game, state, line) {
  if (state === 'known') return `${line.text.replace(/ · /g, ' and ')}.`;
  return state === 'tba' ? 'Crew to be announced.' : 'Crew not listed.';
}

export function accessibleName(game, state, line) {
  const time = game.kickoffMin == null ? 'Time to be announced' : clock12(game.kickoffMin);
  const match = matchupText(game).replace(' @ ', ' at ');
  const net = game.networkName ?? 'Network to be announced';
  const parts = [`${time}, ${match}, ${net}.`];
  if (line.star) parts.push('Lead booth.');
  parts.push(crewSentence(game, state, line));
  return parts.join(' ');
}

/**
 * One two-line game cell: line 1 the kickoff and matchup, line 2 the booth (D-04, D-05, D-06).
 * Shared by the grid and the Time TBA strip.
 * @param {object} game
 * @param {object} ctx
 * @param {{service?: boolean, tail?: string|null}} [opts] - `service`: network name right of
 *   line 1 (the Streaming row); `tail`: text right of line 1 (the strip).
 */
export function buildCell(game, ctx, { tail = null } = {}) {
  const state = cellState(game, ctx.nowWall);
  const line = boothLine(game, state, ctx.collide);
  const matchup = matchupText(game);
  const btn = el('button', 'wk-cell');
  btn.type = 'button';
  btn.dataset.wkId = `g:${game.key}`;
  btn.dataset.wkState = state;
  btn.setAttribute('aria-label', accessibleName(game, state, line));
  const when = game.kickoffMin == null ? 'Time TBA' : clock12(game.kickoffMin);
  btn.title = `${when}, ${matchup}, ${line.text}`;

  const l1 = el('span', 'wk-line wk-line1');
  l1.append(
    el('span', 'wk-time', game.kickoffMin == null ? 'Time TBA' : clockText(game.kickoffMin)),
    el('span', 'wk-match', matchup),
  );
  if (tail) l1.append(el('span', 'wk-tail', tail));
  const l2 = el('span', 'wk-line wk-line2');
  if (line.star) {
    const star = el('span', 'wk-star', '★');
    star.setAttribute('aria-hidden', 'true');
    l2.append(star);
  }
  const booth = el('span', 'wk-booth', line.text);
  booth.style.fontWeight = String(line.weight);
  l2.append(booth);
  btn.append(l1, l2);

  if (game.networkId == null) {
    btn.classList.add('wk-cell--neutral');
  } else {
    const colors = cellColors(game.family, ctx.theme, state);
    btn.style.backgroundColor = colors.bg;
    btn.style.color = colors.fg;
    if (colors.edge) {
      btn.classList.add('wk-cell--tint');
      btn.style.setProperty('--wk-edge', colors.edge);
    }
  }
  btn.addEventListener('click', () => ctx.open(game, btn));
  return btn;
}

// ---- Control row: day tabs and week stepper ----

function stepButton(dir, label, disabled, title, onClick, id) {
  const b = el('button', `wk-step wk-step--${dir}`);
  b.type = 'button';
  b.setAttribute('aria-label', label);
  b.dataset.wkId = id;
  if (disabled) {
    b.setAttribute('aria-disabled', 'true');
    if (title) b.title = title;
  }
  b.append(makeCaretIcon());
  b.addEventListener('click', () => {
    if (!disabled) onClick();
  });
  return b;
}

/** The control row: day tabs (a second tablist) on the left, the week stepper on the right. */
export function buildControls(ctx, api) {
  const { model, days, day } = ctx;
  const row = el('div', 'wk-controls');

  const tabs = el('div', 'wk-days');
  tabs.setAttribute('role', 'tablist');
  tabs.setAttribute('aria-label', 'Day');
  const buttons = [];
  for (const d of days) {
    const tab = el('button', 'chart-tab wk-day');
    tab.type = 'button';
    tab.setAttribute('role', 'tab');
    tab.dataset.wkId = `day:${d}`;
    tab.dataset.day = d;
    const selected = d === day;
    tab.setAttribute('aria-selected', String(selected));
    tab.tabIndex = selected ? 0 : -1;
    tab.append(document.createTextNode(dayLabel(d)));
    if (ctx.anyPick) tab.append(el('span', 'wk-count', ` (${ctx.countFor(d)})`));
    tab.addEventListener('click', () => api.setDay(d));
    buttons.push(tab);
    tabs.append(tab);
  }
  tabs.addEventListener('keydown', (ev) => {
    const at = buttons.indexOf(document.activeElement);
    if (at < 0) return;
    let to = null;
    if (ev.key === 'ArrowRight') to = (at + 1) % buttons.length;
    else if (ev.key === 'ArrowLeft') to = (at + buttons.length - 1) % buttons.length;
    else if (ev.key === 'Home') to = 0;
    else if (ev.key === 'End') to = buttons.length - 1;
    if (to == null) return;
    ev.preventDefault();
    api.setDay(buttons[to].dataset.day, buttons[to].dataset.wkId);
  });

  const weeks = model.weeks ?? [];
  const at = weeks.findIndex((w) => w.label === model.weekLabel);
  const prev = at > 0 ? weeks[at - 1] : null;
  const next = at >= 0 && at < weeks.length - 1 ? weeks[at + 1] : null;
  const stepper = el('div', 'wk-stepper');
  const latest = Boolean(model.isLatestWeek) || next == null;
  stepper.append(
    stepButton('prev', prev ? `Previous week, ${prev.label}` : 'Previous week', prev == null,
      prev == null ? 'First week' : null, () => ctx.opts.onWeek?.(-1), 'step:prev'),
    el('span', 'wk-week', model.weekLabel),
    stepButton('next', next ? `Next week, ${next.label}` : 'Next week', latest,
      latest ? 'Latest week' : null, () => ctx.opts.onWeek?.(1), 'step:next'),
  );
  row.append(days.length ? tabs : el('div', 'wk-days'), stepper);
  return row;
}

// ---- Stamp, Time TBA strip, ESPN+ table and source line ----

const EMPTY = () => document.createDocumentFragment();

/** The freshness line above the grid, or the zero-match line under an active pick (D-16). */
export function buildStampLine(ctx) {
  const { model } = ctx;
  const p = el('p', 'wk-stamp');
  p.setAttribute('aria-live', 'off');
  if (ctx.anyPick && ctx.inDay.length > 0 && !ctx.inDay.some((g) => ctx.passes(g) === true)) {
    p.classList.add('wk-stamp--picks');
    p.textContent = `No games match your picks on ${dayLabel(ctx.day)}. `
      + 'Try another day or clear a filter.';
    return p;
  }
  if (model.past) {
    // ESPN Press Room is a college-football crew backup only; the NFL has no such source.
    p.textContent = model.sport === 'nfl'
      ? 'Crews: 506 Sports, as saved.'
      : 'Crews: 506 Sports and ESPN Press Room, as saved.';
    return p;
  }
  const f = model.freshness ?? {};
  const schedule = f.schedule_updated_at ? `Schedule updated ${etStamp(f.schedule_updated_at)}` : null;
  const segments = [];
  if (f.crews_506_saved_at) segments.push(`506 Sports saved ${etStamp(f.crews_506_saved_at)}`);
  if (f.crews_espnpr_saved_at) {
    const week = f.espnpr_week != null ? ` week ${f.espnpr_week}` : '';
    segments.push(`ESPN Press Room${week} saved ${etStamp(f.crews_espnpr_saved_at, { withTime: false })}`);
  }
  if (segments.length) {
    p.textContent = `Crews: ${[...segments, ...(schedule ? [schedule] : [])].join(' · ')}`;
  } else {
    p.textContent = 'Crews for this week are not posted yet. Games show Crew TBA until they are.'
      + `${schedule ? ` ${schedule}` : ''}`;
  }
  return p;
}

/** One strip cell: the shared two-line cell with the network (or Network TBA) at the right. */
function stripCell(game, ctx) {
  const cell = buildCell(game, ctx, { tail: game.networkName ?? 'Network TBA' });
  applyPick(cell, game, ctx, ctx.rowFaded([game]));
  return cell;
}

/** The collapsible Time or network to be announced strip (D-13); nothing is dropped. */
export function buildTbaStrip(ctx, api) {
  const games = ctx.dayModel.tba;
  if (!games.length) return EMPTY();
  const open = ctx.state.stripOpen ?? !stripCollapsedByDefault(games.length);
  const section = el('section', 'wk-tba');
  const head = el('button', 'wk-tba-head');
  head.type = 'button';
  head.dataset.wkId = 'strip';
  head.setAttribute('aria-expanded', String(open));
  head.setAttribute('aria-controls', 'wk-tba-body');
  head.append(makeCaretIcon(),
    el('span', 'wk-tba-title', `Time or network to be announced (${games.length})`));
  head.addEventListener('click', () => {
    ctx.state.stripOpen = !open;
    api.rerender();
  });
  const body = el('div', 'wk-tba-body');
  body.id = 'wk-tba-body';
  body.hidden = !open;
  for (const g of games) body.append(stripCell(g, ctx));
  section.append(head, body);
  return section;
}

function activateOnKey(node, fn) {
  node.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter' || ev.key === ' ') {
      ev.preventDefault();
      fn();
    }
  });
}

/** The CFB ESPN+ and regional booktabs table (D-10); absent when empty and for the NFL. */
export function buildCompactTable(ctx) {
  const games = ctx.dayModel.compact;
  if (ctx.model.sport !== 'cfb' || !games.length) return EMPTY();
  const section = el('section', 'wk-compact');
  section.append(el('h3', 'wk-compact-title', 'ESPN+ and regional'));
  const table = el('table', 'games-table wk-compact-table');
  const headRow = el('tr');
  for (const label of ['Time', 'Game', 'Network', 'Booth']) {
    const th = el('th', null, label);
    th.scope = 'col';
    headRow.append(th);
  }
  const thead = el('thead');
  thead.append(headRow);
  const tbody = el('tbody');
  for (const g of games) {
    const state = cellState(g, ctx.nowWall);
    const line = boothLine(g, state, ctx.collide);
    const tr = el('tr', 'wk-crow');
    tr.setAttribute('role', 'button');
    tr.tabIndex = 0;
    tr.dataset.wkId = `g:${g.key}`;
    tr.setAttribute('aria-label', accessibleName(g, state, line));
    const net = el('td', 'wk-c-net');
    if (g.networkId != null) {
      net.append(networkMark({ id: g.networkId, name: g.networkName ?? g.networkId, family: g.family }));
    }
    const booth = el('td', 'wk-c-booth', line.text);
    booth.style.fontWeight = String(line.weight);
    tr.append(
      el('td', 'wk-c-time', g.kickoffMin == null ? 'Time TBA' : clock12(g.kickoffMin)),
      el('td', 'wk-c-game', matchupText(g)),
      net,
      booth,
    );
    applyPick(tr, g, ctx, ctx.rowFaded([g]));
    if (tr.classList.contains('is-match')) booth.style.fontWeight = '600';
    tr.addEventListener('click', () => ctx.open(g, tr));
    activateOnKey(tr, () => ctx.open(g, tr));
    tbody.append(tr);
  }
  table.append(thead, tbody);
  section.append(table);
  return section;
}

/** A link through safeHref; an unsafe or missing href leaves plain text. */
function sourceLink(text, href) {
  const safe = safeHref(href);
  if (safe == null) return document.createTextNode(text);
  const a = el('a', null, text);
  a.href = safe;
  a.target = '_blank';
  a.rel = 'noopener noreferrer';
  return a;
}

/** The credit line at the bottom: only the sources this sport actually uses (RT-01, RT-03). */
export function buildSourceLine(ctx) {
  const { model } = ctx;
  const links = model.links ?? {};
  const press = links.espnPressRoom ?? ESPN_PRESS_ROOM;
  const p = el('p', 'wk-source');
  const text = (t) => document.createTextNode(t);
  if (model.sport === 'nfl') {
    p.append(text('Schedule: '), sourceLink('nflverse', 'https://www.nflverse.com/'),
      text(' · Crews: '), sourceLink('506 Sports', 'https://506sports.com'));
    if (links.wikipedia) {
      p.append(text(' · Networks: '), sourceLink('Wikipedia', links.wikipedia),
        text(' (CC BY-SA 4.0)'));
    }
  } else {
    const cfbd = 'https://collegefootballdata.com';
    p.append(text('Schedule: '), sourceLink('CollegeFootballData.com', cfbd),
      text(' · Crews: '), sourceLink('506 Sports', 'https://506sports.com'), text(' and '),
      sourceLink('ESPN Press Room', press), text(' · Networks: '),
      sourceLink('CollegeFootballData.com', cfbd), text(' and '),
      sourceLink('506 Sports', 'https://506sports.com'));
  }
  return p;
}

// ---- The grid ----

function buildAxis(ctx, laneWidth) {
  const { axis, pxh } = ctx.dayModel;
  const bar = el('div', 'wk-axis');
  bar.append(el('div', 'wk-corner', 'All times ET'));
  const ticks = el('div', 'wk-ticks');
  ticks.style.width = `${laneWidth}px`;
  for (const t of axis.ticks) {
    if (t.min >= axis.end) continue;
    const tick = el('span', 'wk-tick', t.label);
    tick.style.left = `${Math.round(((t.min - axis.start) * pxh) / 60)}px`;
    ticks.append(tick);
  }
  bar.append(ticks);
  return bar;
}

function buildRow(row, ctx, lanes) {
  const first = row.cells[0].game;
  const games = row.cells.map((c) => c.game);
  const faded = ctx.rowFaded(games);
  const wrap = el('div', 'wk-row');
  wrap.dataset.row = row.id;
  const head = el('div', 'wk-rowhead');
  if (row.id === 'streaming') {
    head.append(el('span', 'wk-rowname', row.label));
  } else {
    head.append(networkMark({ id: first.networkId, name: first.networkName ?? row.label,
      family: first.family }));
  }
  if (faded) {
    head.classList.add('is-faded');
    head.style.opacity = String(WEEKEND_FADED_OPACITY);
  }
  const lane = el('div', 'wk-lane');
  lane.style.height = `${row.height}px`;
  lane.style.width = `${Math.round(((ctx.dayModel.axis.end - ctx.dayModel.axis.start) * ctx.dayModel.pxh) / 60)}px`;
  const bySub = [];
  for (const c of row.cells) {
    const cell = buildCell(c.game, ctx, { tail: row.id === 'streaming' ? c.game.networkName : null });
    cell.style.left = `${c.left}px`;
    cell.style.top = `${c.subRow * SUB_ROW_PITCH}px`;
    cell.style.width = `${c.width}px`;
    cell.dataset.left = String(c.left);
    applyPick(cell, c.game, ctx, faded);
    lane.append(cell);
    (bySub[c.subRow] ??= []).push(cell);
  }
  for (const sub of bySub) {
    sub.sort((a, b) => Number(a.dataset.left) - Number(b.dataset.left));
    lanes.push(sub);
  }
  wrap.append(head, lane);
  return wrap;
}

function wireRoving(grid, lanes) {
  const all = lanes.flat();
  if (!all.length) return;
  const setStop = (cell) => {
    for (const c of all) c.tabIndex = c === cell ? 0 : -1;
  };
  const stop = all.find((c) => c.classList.contains('is-match')) ?? all[0];
  setStop(stop);
  grid.addEventListener('focusin', (ev) => {
    const cell = ev.target.closest?.('.wk-cell');
    if (cell && all.includes(cell)) setStop(cell);
  });
  grid.addEventListener('keydown', (ev) => {
    const cell = ev.target.closest?.('.wk-cell');
    if (!cell) return;
    const laneAt = lanes.findIndex((l) => l.includes(cell));
    if (laneAt < 0) return;
    const lane = lanes[laneAt];
    const at = lane.indexOf(cell);
    let to = null;
    if (ev.key === 'ArrowRight') to = lane[Math.min(at + 1, lane.length - 1)];
    else if (ev.key === 'ArrowLeft') to = lane[Math.max(at - 1, 0)];
    else if (ev.key === 'Home') to = lane[0];
    else if (ev.key === 'End') to = lane[lane.length - 1];
    else if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
      const other = lanes[laneAt + (ev.key === 'ArrowDown' ? 1 : -1)];
      if (other) {
        const x = Number(cell.dataset.left);
        to = other.reduce((best, c) => (Math.abs(Number(c.dataset.left) - x)
          < Math.abs(Number(best.dataset.left) - x) ? c : best), other[0]);
      }
    }
    if (ev.key.startsWith('Arrow') || ev.key === 'Home' || ev.key === 'End') ev.preventDefault();
    if (to && to !== cell) {
      setStop(to);
      to.focus();
    }
  });
}

function buildNowLine(ctx, body, axisEl) {
  const { axis, pxh } = ctx.dayModel;
  const { date, minutes } = ctx.nowParts;
  if (date !== ctx.day || minutes < axis.start || minutes > axis.end) return;
  const x = ROW_HEAD_WIDTH + Math.round(((minutes - axis.start) * pxh) / 60);
  const line = el('div', 'wk-now');
  line.style.left = `${x}px`;
  body.append(line);
  const label = el('span', 'wk-now-label', 'Now');
  label.style.left = `${x - 4}px`;
  axisEl.append(label);
}

/** The timeline: sticky axis and network column, one row per network. */
export function buildGrid(ctx, api) {
  const { axis, pxh, rows } = ctx.dayModel;
  const laneWidth = Math.round(((axis.end - axis.start) * pxh) / 60);
  const scroller = el('div', 'wk-scroll');
  const grid = el('div', 'wk-grid');
  grid.setAttribute('role', 'group');
  grid.setAttribute('aria-label', 'Games by network and kickoff time, all times ET');
  grid.style.width = `${ROW_HEAD_WIDTH + laneWidth}px`;
  grid.style.setProperty('--wk-pxh', `${pxh}px`);
  const axisEl = buildAxis(ctx, laneWidth);
  const body = el('div', 'wk-body');
  const lanes = [];
  for (const row of rows) body.append(buildRow(row, ctx, lanes));
  buildNowLine(ctx, body, axisEl);
  grid.append(axisEl, body);
  scroller.append(grid);
  wireRoving(grid, lanes);
  api.onDispose(attachScrollCue(scroller, null));
  return scroller;
}

function buildDesktopBody(ctx, api) {
  const nodes = [buildStampLine(ctx)];
  const m = ctx.dayModel;
  if (m.axis && m.rows.length) nodes.push(buildGrid(ctx, api));
  nodes.push(buildTbaStrip(ctx, api), buildCompactTable(ctx), buildSourceLine(ctx));
  return nodes;
}

// ---- Mount lifecycle (shared with the phone list) ----

const MOUNTED = new WeakMap();

/**
 * Mounts one weekend view in `host`, replacing any earlier mount there and keeping focus on the
 * same control or cell across the rebuild. The theme, the clock and the width rebuild it.
 * @param {HTMLElement} host
 * @param {object} model
 * @param {object} opts
 * @param {(ctx: object, api: object) => Node[]} buildBody
 * @param {string} kind - 'grid' or 'list' (a class hook).
 * @returns {{destroy: () => void}}
 */
export function mountWeekend(host, model, opts, buildBody, kind) {
  const previous = MOUNTED.get(host);
  const carriedFocus = previous ? previous.activeId() : null;
  previous?.destroy();

  const state = { day: model.day ?? null, width: opts.width ?? (host.clientWidth || FALLBACK_WIDTH),
    stripOpen: null };
  let disposers = [];
  let focusId = carriedFocus;
  let forceFocus = null;

  const api = {
    onDispose(fn) {
      disposers.push(fn);
    },
    setDay(day, focus = null) {
      state.day = day;
      forceFocus = focus;
      render();
      opts.onDay?.(day);
    },
    rerender: () => render(),
    state,
  };

  function activeId() {
    const a = document.activeElement;
    return a && host.contains(a) ? (a.dataset?.wkId ?? null) : null;
  }

  function render() {
    focusId = forceFocus ?? activeId() ?? focusId;
    forceFocus = null;
    for (const fn of disposers) fn();
    disposers = [];
    const ctx = makeContext(model, opts, state);
    const root = el('div', `wk-root wk-root--${kind}`);
    root.dataset.sport = model.sport;
    root.append(buildControls(ctx, api));
    if (model.missing) {
      const weeks = model.weeks ?? [];
      const at = weeks.findIndex((w) => w.label === model.weekLabel);
      const back = at > 0 ? weeks[at - 1].label : null;
      root.append(el('p', 'wk-error', `This build has no schedule for ${model.weekLabel}. `
        + `Reload the page${back ? ` or step back to ${back}` : ''}.`));
    } else if (model.games.length === 0) {
      const empty = el('div', 'wk-empty');
      empty.append(
        el('p', 'wk-empty-title', 'No games this weekend'),
        el('p', 'wk-empty-body', `The schedule has no games for ${model.weekLabel} yet. `
          + 'Step back to a past week to see final crews.'),
      );
      root.append(empty);
    } else {
      for (const node of buildBody(ctx, api)) root.append(node);
    }
    host.replaceChildren(root);
    if (focusId) {
      const target = [...host.querySelectorAll('[data-wk-id]')].find((n) => n.dataset.wkId === focusId);
      target?.focus({ preventScroll: true });
    }
    focusId = null;
  }

  // Resize rebuilds with the new pixels per hour; rows keep their heights.
  let resizeTimer = null;
  let seenWidth = host.clientWidth;
  const resizeObserver = new ResizeObserver(() => {
    const w = host.clientWidth;
    if (w === 0 || Math.abs(w - seenWidth) < 1) return;
    seenWidth = w;
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      state.width = w;
      render();
    }, RESIZE_DEBOUNCE_MS);
  });
  resizeObserver.observe(host);
  const stopTheme = onThemeChange(() => render());
  // A fixed Date is a test clock; otherwise the view re-reads the clock every minute.
  const clockTimer = opts.now instanceof Date ? null : setInterval(render, TICK_MS);

  const instance = {
    activeId,
    destroy() {
      clearTimeout(resizeTimer);
      if (clockTimer != null) clearInterval(clockTimer);
      resizeObserver.disconnect();
      stopTheme();
      for (const fn of disposers) fn();
      disposers = [];
      host.replaceChildren();
      if (MOUNTED.get(host) === instance) MOUNTED.delete(host);
    },
  };
  MOUNTED.set(host, instance);
  render();
  return { destroy: instance.destroy };
}

/**
 * Desktop timeline view (481px and up).
 * @returns {{destroy: () => void}}
 */
export function renderWeekend(host, model, opts = {}) {
  return mountWeekend(host, model, opts, buildDesktopBody, 'grid');
}
