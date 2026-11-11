/**
 * This weekend phone list (Phase 18, plan 09, D-08): the 480px-and-under layout. Games group by
 * kickoff time, each item a button with a network mark, two text lines and a 4px family edge;
 * the Time or network to be announced group and the ESPN+ and regional group come last. No time
 * axis and no Now line. It shares the model, options, control row, stamp line, source line and
 * mount lifecycle with weekend-view.js, so no copy string is duplicated.
 *
 * DOM safety (T-18-28): createElement, textContent and setAttribute only; no markup-injecting API.
 */

import {
  accessibleName, applyPick, buildSourceLine, buildStampLine, clock12, el,
  mountWeekend,
} from './weekend-view.js';
import { makeCaretIcon } from './icons.js';
import { isRankedMatchup, rankBadge } from './rank-badge.js';
import { fillWrappingMatchup } from './matchup-wrap.js';
import { networkMark } from './network.js';
import { FAMILY_COLORS, familyKey } from './palette.js';
import {
  boothLine, cellState, dayLabel, matchupSides, stripCollapsedByDefault, weekdayLabel,
} from './weekend.js';

function item(game, ctx, { showTime = false } = {}) {
  const state = cellState(game, ctx.nowWall);
  const line = boothLine(game, state);
  const btn = el('button', 'wk-item');
  btn.type = 'button';
  btn.dataset.wkId = `g:${game.key}`;
  btn.dataset.wkState = state;
  if (line.star && game.sport === 'cfb') btn.classList.add('wk-item--lead');
  btn.setAttribute('aria-label', accessibleName(game, state, line));
  const edge = game.networkId == null
    ? 'var(--rule-strong)'
    : FAMILY_COLORS[ctx.theme][familyKey(game.family)];
  btn.style.borderLeftColor = edge;

  const mark = el('span', 'wk-item-mark');
  if (game.networkId != null) {
    // No family dot: the 4px edge already carries the family, and the name needs all 56px.
    mark.append(networkMark({ id: game.networkId, name: game.networkName ?? game.networkId,
      family: game.family }, { dot: false }));
  } else {
    mark.append(el('span', 'wk-item-nonet', 'Network TBA'));
  }
  const text = el('span', 'wk-item-text');
  let when = game.kickoffMin == null ? 'Time TBA' : clock12(game.kickoffMin);
  // A whole-week page names the day outside its day-and-kickoff groups (the strip).
  if (ctx.allDays && game.date != null) when = `${weekdayLabel(game.date)} ${when}`;
  const l1 = el('span', 'wk-item-l1');
  const sides = matchupSides(game);
  fillWrappingMatchup(l1, showTime ? { ...sides, away: `${when} ${sides.away}` } : sides);
  const l2 = el('span', 'wk-item-l2');
  if (line.star) {
    const star = el('span', 'wk-star', '★');
    star.setAttribute('aria-hidden', 'true');
    l2.append(star);
  }
  const booth = el('span', 'wk-booth', line.text);
  booth.style.fontWeight = String(line.weight);
  l2.append(booth);
  // The matchup's own wrapper is as tall as its visible lines, so the ranked badge inside it
  // centres on line 1, or lines 1-2 when the matchup wraps (user feedback 2026-11-03). Every
  // row gets it, ranked or not, so the layout is the same either way.
  const mu = el('span', 'wk-item-mu');
  mu.append(l1);
  if (isRankedMatchup(game)) {
    btn.classList.add('rk-has');
    mu.append(rankBadge({ hidden: true }));
  }
  text.append(mu, l2);
  btn.append(mark, text);
  btn.addEventListener('click', () => ctx.open(game, btn));
  applyPick(btn, game, ctx, ctx.rowFaded([game]));
  return btn;
}

function groupTitle(text) {
  return el('h3', 'wk-group-title', text);
}

function kickoffGroups(ctx) {
  const rowIndex = new Map(ctx.dayModel.rows.map((r, k) => [r.id, k]));
  const games = [];
  for (const row of ctx.dayModel.rows) for (const c of row.cells) games.push({ g: c.game, row: row.id });
  // A whole-week page (the NFL) groups by date and kickoff, so Thursday's and Monday's night
  // games never share a group, and names the day in each title.
  const keyOf = (g) => (ctx.allDays ? `${g.date ?? '9999'}|${String(g.kickoffMin).padStart(4, '0')}` : g.kickoffMin);
  const byTime = new Map();
  for (const { g, row } of games) {
    const key = keyOf(g);
    if (!byTime.has(key)) byTime.set(key, { date: g.date, min: g.kickoffMin, list: [] });
    byTime.get(key).list.push({ g, k: rowIndex.get(row) });
  }
  const rank = (g) => (g.boothRank == null ? Infinity : g.boothRank);
  const order = (a, b) => (ctx.allDays ? (a < b ? -1 : Number(a > b)) : a - b);
  return [...byTime.keys()].sort(order).map((key) => {
    const { date, min, list: entries } = byTime.get(key);
    const list = entries.sort((a, b) => a.k - b.k || rank(a.g) - rank(b.g)
      || a.g.home.localeCompare(b.g.home));
    const section = el('section', 'wk-group');
    section.dataset.time = String(min);
    if (ctx.allDays && date != null) section.dataset.date = date;
    const title = ctx.allDays && date != null ? `${dayLabel(date)}, ${clock12(min)}` : clock12(min);
    section.append(groupTitle(title));
    for (const { g } of list) section.append(item(g, ctx));
    return section;
  });
}

function tbaGroup(ctx, api) {
  const games = ctx.dayModel.tba;
  if (!games.length) return null;
  const open = ctx.state.stripOpen ?? !stripCollapsedByDefault(games.length);
  const section = el('section', 'wk-group wk-tba');
  const head = el('button', 'wk-tba-head');
  head.type = 'button';
  head.dataset.wkId = 'strip';
  head.setAttribute('aria-expanded', String(open));
  head.setAttribute('aria-controls', 'wk-tba-body');
  head.append(makeCaretIcon(), el('span', 'wk-tba-title', `Time or network to be announced (${games.length})`));
  head.addEventListener('click', () => {
    ctx.state.stripOpen = !open;
    api.rerender();
  });
  const body = el('div', 'wk-tba-body');
  body.id = 'wk-tba-body';
  body.hidden = !open;
  for (const g of games) body.append(item(g, ctx, { showTime: true }));
  section.append(head, body);
  return section;
}

function compactGroup(ctx) {
  const games = ctx.dayModel.compact;
  if (ctx.model.sport !== 'cfb' || !games.length) return null;
  const section = el('section', 'wk-group wk-compact');
  section.append(groupTitle('ESPN+ and regional'));
  for (const g of games) section.append(item(g, ctx, { showTime: true }));
  return section;
}

function buildListBody(ctx, api) {
  const nodes = [buildStampLine(ctx), ...kickoffGroups(ctx)];
  for (const g of [tbaGroup(ctx, api), compactGroup(ctx)]) if (g) nodes.push(g);
  nodes.push(buildSourceLine(ctx));
  return nodes;
}

/**
 * Phone list view (480px and under); same model and options as renderWeekend.
 * @returns {{destroy: () => void}}
 */
export function renderWeekendList(host, model, opts = {}) {
  return mountWeekend(host, model, opts, buildListBody, 'list');
}
