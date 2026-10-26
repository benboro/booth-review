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
import { networkMark } from './network.js';
import { FAMILY_COLORS, familyKey } from './palette.js';
import {
  boothLine, cellState, matchupText, stripCollapsedByDefault,
} from './weekend.js';

function item(game, ctx, { showTime = false } = {}) {
  const state = cellState(game, ctx.nowWall);
  const line = boothLine(game, state, ctx.collide);
  const btn = el('button', 'wk-item');
  btn.type = 'button';
  btn.dataset.wkId = `g:${game.key}`;
  btn.dataset.wkState = state;
  btn.setAttribute('aria-label', accessibleName(game, state, line));
  const edge = game.networkId == null
    ? 'var(--rule-strong)'
    : FAMILY_COLORS[ctx.theme][familyKey(game.family)];
  btn.style.borderLeftColor = edge;

  const mark = el('span', 'wk-item-mark');
  if (game.networkId != null) {
    mark.append(networkMark({ id: game.networkId, name: game.networkName ?? game.networkId,
      family: game.family }));
  } else {
    mark.append(el('span', 'wk-item-nonet', 'Network TBA'));
  }
  const text = el('span', 'wk-item-text');
  const when = game.kickoffMin == null ? 'Time TBA' : clock12(game.kickoffMin);
  const l1 = el('span', 'wk-item-l1', showTime ? `${when} ${matchupText(game)}` : matchupText(game));
  const l2 = el('span', 'wk-item-l2');
  if (line.star) {
    const star = el('span', 'wk-star', '★');
    star.setAttribute('aria-hidden', 'true');
    l2.append(star);
  }
  const booth = el('span', 'wk-booth', line.text);
  booth.style.fontWeight = String(line.weight);
  l2.append(booth);
  text.append(l1, l2);
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
  const byTime = new Map();
  for (const { g, row } of games) {
    if (!byTime.has(g.kickoffMin)) byTime.set(g.kickoffMin, []);
    byTime.get(g.kickoffMin).push({ g, k: rowIndex.get(row) });
  }
  const rank = (g) => (g.boothRank == null ? Infinity : g.boothRank);
  return [...byTime.keys()].sort((a, b) => a - b).map((min) => {
    const list = byTime.get(min).sort((a, b) => a.k - b.k || rank(a.g) - rank(b.g)
      || a.g.home.localeCompare(b.g.home));
    const section = el('section', 'wk-group');
    section.dataset.time = String(min);
    section.append(groupTitle(clock12(min)));
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
