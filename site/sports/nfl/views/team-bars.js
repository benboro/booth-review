/**
 * NFL view 1: games by team (D-12, D-13, D-24), one horizontal Plotly bar per franchise over
 * the selected seasons, each game counted once per team.
 *
 * With "Special games only" off (the default) a bar holds every game the filters pass, grouped
 * by network family, the special games solid and the other games light (views/network-bars.js).
 * The legend chips are the network families and act on the Networks filter, as on the CFB page.
 *
 * With it on, a bar holds the special games in eight exclusive segments (Thursday night ...
 * International), the legend chips show and hide a segment, and the info note has one
 * definition per segment (D-13). This is the old Special games tab, unchanged.
 *
 * Both legends are CFB's chip row with double-click "only this one" (D-15). Hover text, the
 * season breakdown and the hidden data table are all built with createElement/textContent;
 * names enter Plotly strings only through escapeHover, and customdata carries row indexes,
 * never names.
 */
import {
  teamBars,
  teamSeasonRows,
  specialMatchedCounts,
  rankTeamBars,
  shownTotal,
  pendingNetworkSeasons,
  networkBars,
  networkSeasonRows,
  networkFacets,
  networkIdOf,
  countedMask,
  SLOT_SEGMENT,
  EXCLUSIVE_CATEGORIES,
} from '../state.js';
import { computePicks } from '../picks.js';
import { createOnlyDetector, makeLegendChip } from '../../../modules/legend.js';
import {
  familyIsSole,
  familyOnlyPatch,
  familyToggledOff,
  toggleFamilyNetworks,
} from '../../../modules/select.js';
import { MARGIN, TICK_FONT_PX, DOT_OPACITY } from '../../../modules/chart.js';
import { categoryColor, familyColor, familyLabel } from '../palette.js';
import { ACCENT, INK, MUTED, PAGE_BG, DIVIDER, SPECIAL, mixHex } from '../../../modules/palette.js';
import { FRAME_FONT, frameConfig, frameLayout } from '../../../modules/chart-frame.js';
import {
  endMarkerAnnotations,
  endMarkerShapes,
  markerWidth,
  overlayAxis,
  textWidth,
} from '../../../modules/bar-chart.js';
import { ensureTooltipEl, showTextTooltip, hideTooltip } from '../../../modules/tooltip.js';
import { attachScrollCue } from '../../../modules/scroll-cue.js';
import { escapeHover } from '../../../modules/format.js';
import { DATA_TABLE_CLASS, rebuildKeepingFocus } from '../data-table.js';
import { mountViewTools } from '../tools.js';
import { networkTraces, networkHoverModel } from './network-bars.js';

const SEGMENTS = EXCLUSIVE_CATEGORIES.filter((c) => c.key !== 'none');
const TOP_N = 15;
const FADE = 0.4;
const EMPTY_TITLE = 'No games match these filters';
const EMPTY_HINT = 'Clear all filters, or widen the Seasons range.';
const SLOT_ORDER = [
  'TNF', 'SNF', 'MNF', 'Thanksgiving', 'Christmas', 'Black Friday', 'Saturday',
  'International', 'Friday', 'Sunday early', 'Sunday late', 'Other',
];
const CONFIG = frameConfig();
const HERO_INK_WEIGHT = 0.8;
// Gap Plotly leaves between a y tick label and the plot when automargin sizes the left edge.
const LABEL_PAD_PX = 4;

/** Round tick step (1, 2, 5, 10, 20, 25, 50, ...) giving 4-8 ticks over max. */
export function niceStep(max) {
  const steps = [];
  for (let m = 1; m <= 1e6; m *= 10) steps.push(m, 2 * m, 5 * m, ...(m >= 10 ? [2.5 * m] : []));
  steps.sort((a, b) => a - b);
  for (const st of steps) if (max / st <= 8) return st;
  return steps[steps.length - 1];
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

const refs = {
  ctx: null,
  legend: null,
  chart: null,
  gd: null,
  note: null,
  noteTitle: null,
  noteHint: null,
  showAll: null,
  breakdown: null,
  captions: null,
  pending: null,
  dataBody: null,
  dataHead: null,
  dataCaption: null,
  specialBox: null,
  shadeKey: null,
  infoButton: null,
  bound: false,
};

// What the last render drew (also what the event handlers read).
let drawn = null; // { all, rows, env, theme, state, model, pending }

function theme(env) {
  return env.dark ? 'dark' : 'light';
}

/** The franchise's display name: its latest, or that season's when one is picked. */
function teamLabel(model, state, fIdx) {
  const [lo, hi] = state.seasons;
  if (lo === hi) {
    const c = model.cols;
    for (const i of model.franchiseGames.get(fIdx) || []) {
      if (c.season[i] !== lo) continue;
      return model.teamNames[c.home[i] === fIdx ? c.home_name[i] : c.away_name[i]].name;
    }
  }
  return model.franchises[fIdx].name;
}

/**
 * Special games only: the franchise's games in the season range, on a picked network, that sit
 * in a stack segment the legend leaves visible, so a bar click lists the games the bar shows.
 * With every chip on that is every special or international game of the team.
 */
function teamGames(model, state, fIdx) {
  const c = model.cols;
  const [lo, hi] = state.seasons;
  const hidden = new Set(state.hiddenSegments);
  return (model.franchiseGames.get(fIdx) || []).filter((i) => {
    if (c.season[i] < lo || c.season[i] > hi) return false;
    // A Networks pick narrows the bar (state.js specialRows), so it narrows the bar's games too.
    if (state.networks != null && !state.networks.includes(networkIdOf(model, i))) return false;
    const cat = EXCLUSIVE_CATEGORIES[model.category[i]];
    return !!cat && cat.key !== 'none' && !hidden.has(cat.key);
  });
}

/** "2025", "2025 and 2026", "2024, 2025 and 2026". */
function seasonList(seasons) {
  const s = seasons.map(String);
  return s.length < 2 ? s.join('') : `${s.slice(0, -1).join(', ')} and ${s[s.length - 1]}`;
}

/** Which of the two Sunday-window segments a pending season leaves unsettled, as shown. */
function pendingNames(hidden) {
  const names = [];
  if (!hidden.has('agotw')) names.push('Fox AGOTW');
  if (!hidden.has('cbs_national')) names.push('CBS late national');
  return names.join(' and ');
}

/**
 * The pending-networks note (notes 15), or null when no season in range is pending or both
 * Sunday-window segments are hidden. `short` is the tooltip's one-liner.
 */
export function pendingText(pending, hiddenSegments, short = false) {
  const names = pendingNames(new Set(hiddenSegments));
  if (!pending.seasons.length || !names) return null;
  const yrs = seasonList(pending.seasons);
  if (short) return `${yrs} ${names} ${names.includes(' and ') ? 'are' : 'is'} pending.`;
  const n = pending.games;
  return `${yrs} ${names} counts are pending: ${n} Sunday-afternoon ${n === 1 ? 'game has' : 'games have'} no network listed yet, so ${n === 1 ? 'it is' : 'they are'} not counted.`;
}

/** Sub-slot text under a row that combines several slots (Holiday, Other solo slot). */
function subSlots(bar, segKey) {
  if (segKey !== 'solo_holiday' && segKey !== 'solo_other') return null;
  const parts = [...bar.slots]
    .filter((sl) => SLOT_SEGMENT[sl.key] === segKey)
    .sort((a, b) => SLOT_ORDER.indexOf(a.label) - SLOT_ORDER.indexOf(b.label))
    .map((sl) => `${sl.label === 'Other' ? 'other' : sl.label} ${sl.count}`);
  return parts.length ? parts.join(', ') : null;
}

/**
 * The hover content for a bar entry, without the click hint (notes 15): the title, the shown
 * total, one colour-keyed row per shown category with games, then context lines.
 * A chip-hidden category leaves the rows and the total. International (any window) and Flexed
 * cut across the categories, so they show only while every category is shown.
 */
function hoverModel(state, label, bar, th, pending) {
  const [lo, hi] = state.seasons;
  const hidden = new Set(state.hiddenSegments);
  const shownSegs = SEGMENTS.filter((seg) => !hidden.has(seg.key));
  const title = lo === hi ? `${label}, ${lo}` : `${label}, ${lo}–${hi}`;
  const total = shownTotal(bar, state.hiddenSegments);
  // Under an Announcers or Booths pick the second line is the matched share (UI-SPEC Q7).
  const matchedTotal = bar.matched ? shownSegs.reduce((a, seg) => a + bar.matched[seg.key], 0) : 0;
  const summary = bar.matched ? `${matchedTotal} of ${total} games` : `${total} special games`;
  const rows = shownSegs
    .filter((seg) => bar.counts[seg.key] > 0)
    .map((seg) => ({
      key: seg.key,
      label: seg.label,
      color: categoryColor(seg.key, th),
      value: bar.matched ? `${bar.matched[seg.key]} of ${bar.counts[seg.key]}` : String(bar.counts[seg.key]),
      // Sub-slot counts are all games, so they are left out beside a matched "n of m".
      sub: bar.matched ? null : subSlots(bar, seg.key),
    }));
  const asides = hidden.size === 0
    ? [`International, any window: ${bar.international}`, `Flexed: ${bar.flexed}`]
    : [];
  return { title, summary, rows, asides, footnote: pendingText(pending, state.hiddenSegments, true) };
}

/** The hover model as tooltip lines. */
function tooltipLines(m) {
  const lines = [
    { text: m.title, kind: 'title' },
    { text: m.summary, kind: 'body' },
  ];
  if (m.rows.length) lines.push({ kind: 'counts', rows: m.rows });
  for (const text of m.asides) lines.push({ text, kind: 'aside' });
  if (m.footnote) lines.push({ text: m.footnote, kind: 'footnote' });
  return lines;
}

/** The hover model as plain text lines (the phone breakdown and the tests). */
export function hoverTextLines(m) {
  return [
    m.title,
    m.summary,
    ...m.rows.map((r) => `${r.label}: ${r.value}${r.sub ? ` (${r.sub})` : ''}`),
    ...m.asides,
    ...(m.footnote ? [m.footnote] : []),
  ];
}

function selectedKey(state) {
  const s = state.selection;
  return s && s.kind === 'team' ? s.key : null;
}

let lastToggle = { id: null, at: 0 };

function toggleTeam(row) {
  const { ctx } = refs;
  // A touch tap reaches Plotly as touchend and again as the emulated mouseup.
  const now = Date.now();
  if (lastToggle.id === row.id && now - lastToggle.at < 500) return;
  lastToggle = { id: row.id, at: now };
  const { model, state } = drawn;
  const id = model.franchises[row.bar.franchise].id;
  if (selectedKey(ctx.getState()) === id) {
    ctx.clearSelection();
    return;
  }
  ctx.selectGames(teamSelection(model, state, row.bar, id, row.label));
}

/**
 * The selection a team bar makes. An all-games bar lists exactly the games it counts (`exact`:
 * the Matched games table does not filter them again); a Special games bar lists its shown
 * segments' games.
 */
function teamSelection(model, state, bar, id, label) {
  if (!state.special) return { kind: 'team', key: id, label, games: bar.games, exact: true };
  return { kind: 'team', key: id, label, games: teamGames(model, state, bar.franchise) };
}

/** The drawn row a Plotly point belongs to: customdata is the row index, or `{ r }` on the shared stacked bars. */
function pointRow(ev) {
  const cd = ev.points && ev.points[0] ? ev.points[0].customdata : null;
  const k = Number.isInteger(cd) ? cd : cd && Number.isInteger(cd.r) ? cd.r : null;
  return drawn && k != null && drawn.rows[k] ? drawn.rows[k] : null;
}

/** The hover model of a drawn row, for the mode it was drawn in. */
function rowHover(d, row) {
  return d.all
    ? networkHoverModel(d.model, d.state, row.label, row.bar, d.theme)
    : hoverModel(d.state, row.label, row.bar, d.theme, d.pending);
}

function bindEvents(gd) {
  if (refs.bound) return;
  refs.bound = true;
  gd.on('plotly_click', (ev) => {
    const row = pointRow(ev);
    if (row) toggleTeam(row);
  });
  gd.on('plotly_hover', (ev) => {
    const row = pointRow(ev);
    if (!row) return;
    if (drawn.env.mobile || drawn.env.hoverNone) return;
    const lines = tooltipLines(rowHover(drawn, row));
    lines.push({ text: 'Click to see seasons and games.', kind: 'hint' });
    const e = ev.event || {};
    showTextTooltip(lines, {
      theme: theme(drawn.env),
      borderColor: ACCENT[theme(drawn.env)],
      clientX: e.clientX ?? 0,
      clientY: e.clientY ?? 0,
    });
  });
  gd.on('plotly_unhover', () => hideTooltip());
}

// ---- pieces ----

const SEGMENT_NOTES = Object.freeze([
  'Solo slot = no other NFL game kicks off within 3 hours.',
  'Thursday night: solo-slot games on Thursday.',
  'Sunday night: solo-slot Sunday night games.',
  'Monday night: solo-slot Monday games. Monday doubleheader games share a window, so they are not counted here.',
  'Holiday: Thanksgiving, Christmas and Black Friday games in a solo slot.',
  'Other solo slot: any other game with no NFL game within 3 hours, such as a Saturday, Friday or lone Sunday-afternoon game.',
  "Fox AGOTW: Fox's top game on a Sunday afternoon doubleheader.",
  "CBS late national: CBS's national game in the late Sunday window.",
  'International: a game played abroad, alone in its window or not. A night, holiday, Fox AGOTW or CBS late national game abroad keeps that category.',
]);

const ALL_KEYS = SEGMENTS.map((s) => s.key);

/** Sets hiddenSegments to the keys in `hide`, in segment order. */
function setHidden(ctx, hide) {
  const set = new Set(hide);
  ctx.setState({ hiddenSegments: ALL_KEYS.filter((k) => set.has(k)) });
}

/** "A", "A and B", "A, B and C". */
function joinAnd(names) {
  return names.length < 2 ? names.join('') : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
}

/** The network names of a family, in the family's network order. */
function familyNetworkNames(model, family) {
  const { net } = model;
  return (net.networksByFamily.get(family) ?? []).map((idx) => net.lookups.networks[idx].name);
}

/** The info note with "Special games only" off: what a bar, its groups and its two fills mean. */
function networkNotes(model) {
  const { net } = model;
  const lines = [
    "Each bar counts a team's regular-season games in the Seasons range, once each, grouped by the network that carried them.",
    "Solid: the network's special games. A special game is alone in its window (Thursday, Sunday or Monday night, a holiday, or another solo slot), is Fox AGOTW or CBS late national, or was played abroad.",
    "Light: the network's other games, mostly regional Sunday afternoons.",
  ];
  const shared = net.families.filter((f) => f !== 'tba' && f !== 'other' && familyNetworkNames(model, f).length > 1);
  if (shared.length) {
    lines.push(`A group can hold several networks: ${shared.map((f) => joinAnd(familyNetworkNames(model, f))).join('; ')}. The hover counts each one.`);
  }
  if (net.families.includes('other')) lines.push(`Other: ${joinAnd(familyNetworkNames(model, 'other'))}.`);
  if (net.families.includes('tba')) {
    lines.push(`${familyLabel('tba')}: a game whose network is not in the data, or is not assigned yet.`);
  }
  lines.push('A chip turns a network on or off in the Networks filter. Turn on Special games only to split the special games by category.');
  return lines;
}

/** Binds the one delegated chip listener (D-15); the chips themselves are rebuilt each render. */
function bindLegend() {
  const { ctx, legend } = refs;
  // Network chips are the Networks filter, with the CFB legend's rules (modules/select.js).
  const families = createOnlyDetector({
    onToggle: (family) => ctx.setState({ networks: toggleFamilyNetworks(ctx.model.net, ctx.getState(), family) }),
    onOnly: (family, before) => {
      const view = { facets: { networks: networkFacets(ctx.model, ctx.getState()) } };
      ctx.setState(familyOnlyPatch(ctx.model.net, view, family, before));
    },
    snapshot: () => ctx.getState().networks,
  });
  const detector = createOnlyDetector({
    onToggle: (key) => {
      const cur = new Set(ctx.getState().hiddenSegments);
      if (cur.has(key)) cur.delete(key);
      else cur.add(key);
      setHidden(ctx, cur);
    },
    onOnly: (key, before) => {
      const prior = new Set(before || []);
      const wasOnly = ALL_KEYS.every((k) => (k === key ? !prior.has(k) : prior.has(k)));
      setHidden(ctx, wasOnly ? [] : ALL_KEYS.filter((k) => k !== key));
    },
    snapshot: () => [...ctx.getState().hiddenSegments],
  });
  legend.addEventListener('click', (ev) => {
    const button = ev.target.closest('button[data-segment], button[data-family]');
    if (!button) {
      // A click in the gaps between chips ends any pending first click.
      detector.reset();
      families.reset();
      return;
    }
    if (button.dataset.family) families.click(ev, button.dataset.family);
    else detector.click(ev, button.dataset.segment);
  });
}

/**
 * The network chips: one per family, on unless the Networks filter excludes every network of
 * the family, and dotted (`data-offered="false"`) when the other filters leave it no games.
 */
function renderNetworkLegend(model, state, th) {
  const { net } = model;
  const counts = networkFacets(model, state);
  const view = { facets: { networks: counts } };
  const items = net.families.map((family) => {
    const label = familyLabel(family);
    const hint = familyIsSole(net, view, family, state.networks)
      ? 'Double-click to show all networks'
      : `Double-click to show only ${label}`;
    const b = makeLegendChip({
      label,
      color: familyColor(family, th),
      pressed: !familyToggledOff(net, state, family),
      hint,
      data: { family },
    });
    const games = (net.networksByFamily.get(family) ?? []).reduce((sum, idx) => sum + counts[idx], 0);
    b.dataset.offered = String(games > 0);
    const li = document.createElement('li');
    li.appendChild(b);
    return li;
  });
  refs.legend.replaceChildren(...items);
}

function renderLegend(state, th) {
  const { legend } = refs;
  const hidden = new Set(state.hiddenSegments);
  const shown = ALL_KEYS.filter((k) => !hidden.has(k));
  const items = SEGMENTS.map((seg) => {
    const hint = shown.length === 1 && shown[0] === seg.key
      ? 'Double-click to show all'
      : `Double-click to show only ${seg.label}`;
    // The shared outlined chip with a colour dot (U6), as on CFB and MLB.
    const b = makeLegendChip({
      label: seg.label,
      color: categoryColor(seg.key, th),
      pressed: !hidden.has(seg.key),
      hint,
      data: { segment: seg.key },
    });
    const li = document.createElement('li');
    li.appendChild(b);
    return li;
  });
  legend.replaceChildren(...items);
}

function buildInfo(ctx) {
  const button = el('button', 'band-info');
  button.type = 'button';
  button.setAttribute('aria-label', 'About this chart');
  button.setAttribute('aria-expanded', 'false');
  button.append(el('span', 'band-info-glyph', 'i'));
  button.firstChild.setAttribute('aria-hidden', 'true');
  button.setAttribute('aria-haspopup', 'dialog');
  // The legend row has no plot geometry to hang the button on as CFB does, so it sits in the row's flow.
  button.classList.add('nfl-legend-info');
  // Nine definitions are too much for a note beside the chart: they open in a modal, built like the
  // game panel (same frame, close button, backdrop, Escape), so the page under it never moves.
  const dialog = el('dialog', 'detail-panel info-modal');
  dialog.setAttribute('aria-labelledby', 'nfl-special-info-title');
  const inner = el('div', 'panel-inner');
  const close = el('button', 'panel-close', '×');
  close.type = 'button';
  close.setAttribute('aria-label', 'Close');
  const title = el('h2');
  title.id = 'nfl-special-info-title';
  const body = el('div', 'panel-body');
  // The note follows the toggle: the networks and the two fills, or the eight categories.
  const fill = () => {
    const all = !ctx.getState().special;
    title.textContent = all ? 'Games by network' : 'Special game categories';
    const foot = el('p');
    foot.append(document.createTextNode(all ? 'Each game counts once per team. See ' : 'Each game counts once. See '));
    const a = el('a', null, 'methodology');
    a.href = ctx.methodologyHref(all ? 'nfl-games-by-network' : 'nfl-special-games');
    a.rel = 'noopener noreferrer';
    foot.append(a, document.createTextNode(' for the full rules.'));
    const lines = all ? networkNotes(ctx.model) : SEGMENT_NOTES;
    body.replaceChildren(...lines.map((line) => el('p', null, line)), foot);
  };
  inner.append(close, title, body);
  dialog.appendChild(inner);

  let downOnBackdrop = false;
  button.addEventListener('click', () => {
    if (dialog.open) return;
    fill();
    dialog.showModal();
    button.setAttribute('aria-expanded', 'true');
  });
  close.addEventListener('click', () => dialog.close());
  dialog.addEventListener('pointerdown', (ev) => {
    downOnBackdrop = ev.target === dialog;
  });
  dialog.addEventListener('click', (ev) => {
    if (ev.target === dialog && downOnBackdrop) dialog.close();
    downOnBackdrop = false;
  });
  dialog.addEventListener('close', () => button.setAttribute('aria-expanded', 'false'));
  return { button, dialog };
}

function setNote(title, hint) {
  const { note, noteTitle, noteHint, gd } = refs;
  if (title == null) {
    note.hidden = true;
    gd.hidden = false;
    return;
  }
  noteTitle.textContent = title;
  noteHint.textContent = hint;
  note.hidden = false;
  gd.hidden = true;
}

function cell(tag, text, className) {
  return el(tag, className || null, text);
}

const RULE_KEYS = new Set(['solo_thursday', 'agotw']);
const SPECIAL_TIP_LEAD = 'Solo slots, Sunday-window and international games:';
const SPECIAL_TIP_FORMULA = 'Thu + Sun + Mon + Holiday + Other solo + AGOTW + CBS + Intl.';
const SPECIAL_TIP = `${SPECIAL_TIP_LEAD} ${SPECIAL_TIP_FORMULA}`;

/** A header tip's lines: the Special games formula gets its own unbreakable line (v2.1). */
function tipLines(text) {
  if (text !== SPECIAL_TIP) return [{ kind: 'body', text }];
  return [{ kind: 'body', text: `${SPECIAL_TIP_LEAD} ` }, { kind: 'formula', text: SPECIAL_TIP_FORMULA }];
}
const SEGMENT_TIPS = Object.freeze({
  solo_other: 'A game alone in its window that is not a Thursday, Sunday or Monday night game, a holiday or an international game, such as a Saturday, Friday or lone Sunday-afternoon game.',
  agotw: "Fox's America's Game of the Week, its top Sunday-afternoon game.",
  cbs_national: "CBS's late Sunday-afternoon national game.",
});

/** How long a header tip waits after the pointer leaves, so the pointer can reach the tip. */
const TIP_LEAVE_MS = 200;

// The one open header tooltip: { button, off } where off removes its listeners. Touch mode
// (`openTip`, a tap toggle) and hover mode (`hoverTip`, hover and focus) never mix on one page.
let openTip = null;
let hoverTip = null;
let tipWatch = null;

function closeTip() {
  if (!openTip) return;
  const { button, off } = openTip;
  openTip = null;
  off();
  button.setAttribute('aria-expanded', 'false');
  hideTooltip();
}

function closeHoverTip() {
  if (!hoverTip) return;
  const { off } = hoverTip;
  hoverTip = null;
  off();
  // Another view may have taken the shared tooltip over meanwhile; only a header tip is hidden.
  if ('hoverable' in ensureTooltipEl().dataset) hideTooltip();
}

/**
 * The shared tooltip is also hidden by other code (a window resize or scroll, another view's
 * hover). Once it is hidden, whichever header tip was open counts as closed, so its listeners
 * go, `aria-expanded` is reset, and the next tap on the same header opens it again.
 */
function watchTooltip() {
  if (tipWatch) return;
  const tip = ensureTooltipEl();
  tipWatch = new MutationObserver(() => {
    if (!tip.hidden) return;
    closeTip();
    closeHoverTip();
  });
  tipWatch.observe(tip, { attributes: true, attributeFilter: ['hidden'] });
}

/** Hover and focus mode (WCAG 1.4.13): Escape closes it from anywhere, and the pointer can rest on it. */
function openHoverTip(button, show) {
  const tip = ensureTooltipEl();
  if (hoverTip && hoverTip.button === button && !tip.hidden) {
    hoverTip.cancel();
    return;
  }
  closeHoverTip();
  let timer = null;
  const cancel = () => {
    clearTimeout(timer);
    timer = null;
  };
  // Leaving closes after a short wait, unless the header still has keyboard focus.
  const later = () => {
    cancel();
    timer = setTimeout(() => {
      if (document.activeElement !== button) closeHoverTip();
    }, TIP_LEAVE_MS);
  };
  const onKey = (ev) => {
    if (ev.key === 'Escape') closeHoverTip();
  };
  const onTipLeave = (ev) => {
    if (!button.contains(ev.relatedTarget)) later();
  };
  document.addEventListener('keydown', onKey, true);
  tip.addEventListener('mouseenter', cancel);
  tip.addEventListener('mouseleave', onTipLeave);
  hoverTip = {
    button,
    cancel,
    later,
    off: () => {
      cancel();
      document.removeEventListener('keydown', onKey, true);
      tip.removeEventListener('mouseenter', cancel);
      tip.removeEventListener('mouseleave', onTipLeave);
    },
  };
  show(true);
}

/** Fills a head th with a dotted-underline button that shows `text` in the site tooltip. */
function tipHead(th, label, text, env) {
  const button = el('button', 'nfl-tip', label);
  button.type = 'button';
  button.setAttribute('aria-description', text);
  watchTooltip();
  const show = (hoverable = false) => {
    const rect = button.getBoundingClientRect();
    const e = drawn ? drawn.env : env;
    // Above the header, so the tip never covers the data cells under it (v2.1).
    showTextTooltip(tipLines(text), {
      theme: theme(e),
      borderColor: DIVIDER[theme(e)],
      clientX: rect.left,
      clientY: rect.top,
      placement: 'above',
      hoverable,
    });
  };
  if (!env.hoverNone) {
    const mine = () => hoverTip && hoverTip.button === button;
    button.addEventListener('mouseenter', () => openHoverTip(button, show));
    button.addEventListener('focus', () => openHoverTip(button, show));
    button.addEventListener('mouseleave', (ev) => {
      const tip = ensureTooltipEl();
      if (mine() && !tip.contains(ev.relatedTarget)) hoverTip.later();
    });
    button.addEventListener('blur', () => {
      // A blur while the pointer still rests on the header or its tip keeps the tip.
      if (mine() && !button.matches(':hover') && !ensureTooltipEl().matches(':hover')) {
        closeHoverTip();
      }
    });
  } else {
    button.setAttribute('aria-expanded', 'false');
    button.addEventListener('click', () => {
      if (openTip && openTip.button === button && !ensureTooltipEl().hidden) {
        closeTip();
        return;
      }
      closeTip();
      const onDown = (ev) => {
        if (ev.target !== button && !button.contains(ev.target)) closeTip();
      };
      const onKey = (ev) => {
        if (ev.key === 'Escape') closeTip();
      };
      const onScroll = () => closeTip();
      document.addEventListener('pointerdown', onDown, true);
      document.addEventListener('keydown', onKey, true);
      window.addEventListener('scroll', onScroll, true);
      openTip = {
        button,
        off: () => {
          document.removeEventListener('pointerdown', onDown, true);
          document.removeEventListener('keydown', onKey, true);
          window.removeEventListener('scroll', onScroll, true);
        },
      };
      button.setAttribute('aria-expanded', 'true');
      show();
    });
  }
  th.appendChild(button);
}

function renderBreakdown(model, state, env, rows) {
  const { breakdown } = refs;
  closeTip();
  closeHoverTip();
  breakdown.replaceChildren();
  const key = selectedKey(state);
  if (key == null || !model.franchiseIndex.has(key)) {
    breakdown.hidden = true;
    return;
  }
  const fIdx = model.franchiseIndex.get(key);
  const label = teamLabel(model, state, fIdx);
  breakdown.hidden = false;
  breakdown.appendChild(el('h3', null, `${label}: season by season`));
  if (!state.special) {
    renderNetworkBreakdown(model, state, env, rows, fIdx, label);
    return;
  }

  const bar = (rows.find((r) => r.bar.franchise === fIdx) || {}).bar
    || teamBars(model, state).find((b) => b.franchise === fIdx);
  const pending = pendingNetworkSeasons(model, state);
  let lines = null;
  if ((env.mobile || env.hoverNone) && bar) {
    // The hover content on a phone, with the same colour dots as the tooltip. It is appended
    // after the table (v2.1, todo 2026-10-25-nfl-phone-season-table-reach), so the table sits
    // right under its heading instead of below ten stacked lines.
    lines = phoneLines(hoverModel(state, label, bar, theme(env), pending));
  }
  const pendingSeasons = new Set(pending.seasons);
  const PENDING_KEYS = new Set(['agotw', 'cbs_national']);

  const table = el('table', 'games-table');
  const VR = ' nfl-vrule';
  const spanner = (label, span) => {
    const th = el('th', 'nfl-spanner' + VR);
    th.colSpan = span;
    th.scope = 'colgroup';
    th.appendChild(el('span', 'nfl-spanner-label', label));
    return th;
  };
  const tall = (label, cls) => {
    const th = cell('th', label, cls);
    th.rowSpan = 2;
    th.scope = 'col';
    return th;
  };
  const row1 = el('tr');
  const seasonHead = tall('Season', null);
  const specialHead = tall(null, 'num' + VR);
  tipHead(specialHead, 'Special games', SPECIAL_TIP, env);
  row1.append(seasonHead, spanner('Solo slots', 5), spanner('Sunday windows', 3), specialHead, tall('Flexed', 'num' + VR));
  const row2 = el('tr');
  for (const seg of SEGMENTS) {
    const th = el('th', 'num' + (RULE_KEYS.has(seg.key) ? VR : ''));
    th.scope = 'col';
    if (SEGMENT_TIPS[seg.key]) tipHead(th, seg.label, SEGMENT_TIPS[seg.key], env);
    else th.textContent = seg.label;
    row2.appendChild(th);
  }
  const thead = el('thead');
  thead.append(row1, row2);
  const tbody = el('tbody');
  // A chip-hidden category is not shown: its cells read as a dash and Special games sums the
  // shown columns only, so the table matches the bar. While a chip is off, a season with no
  // games in the shown columns is left out; with every chip on, every season is listed.
  const hidden = new Set(state.hiddenSegments);
  for (const r of teamSeasonRows(model, state, fIdx)) {
    if (hidden.size && shownTotal(r, state.hiddenSegments) === 0) continue;
    const tr = el('tr');
    tr.dataset.season = String(r.season);
    const season = cell('th', String(r.season));
    season.scope = 'row';
    tr.append(
      season,
      ...SEGMENTS.map((seg) => {
        const cls = 'num' + (RULE_KEYS.has(seg.key) ? VR : '');
        if (hidden.has(seg.key)) {
          const td = cell('td', '–', cls);
          td.dataset.hidden = 'true';
          td.setAttribute('aria-label', 'Hidden');
          return td;
        }
        const mark = pendingSeasons.has(r.season) && PENDING_KEYS.has(seg.key);
        const td = cell('td', String(r.counts[seg.key]), cls);
        if (mark) {
          td.classList.add('nfl-pending');
          td.appendChild(el('span', 'nfl-pending-mark', '*'));
        }
        return td;
      }),
      cell('td', String(shownTotal(r, state.hiddenSegments)), 'num nfl-vrule nfl-total'),
      cell('td', String(r.flexed), 'num nfl-vrule'),
    );
    tbody.appendChild(tr);
  }
  // Column groups matching the spanners, so scope="colgroup" ties each spanner to its columns.
  const groups = [1, 5, 3, 1, 1].map((span) => {
    const g = el('colgroup');
    g.span = span;
    return g;
  });
  table.append(...groups, thead, tbody);
  // Eleven columns do not fit a phone; the table scrolls inside its own wrapper, with the
  // site's edge-fade scroll cue (v2.1). The breakdown lines follow the table.
  appendBreakdownTable(table, lines);

  if (!tbody.children.length) {
    breakdown.appendChild(el('p', 'nfl-muted', 'No games in the shown categories.'));
  }
  breakdown.appendChild(el(
    'p',
    'nfl-muted',
    hidden.size
      ? 'Special games is the sum of the shown columns before it; a dash marks a category hidden in the legend. Flexed games are counted separately.'
      : 'Special games is the sum of the eight columns before it. Flexed games are counted separately.',
  ));
  const shownPending = pending.seasons.filter((s) => tbody.querySelector(`tr[data-season="${s}"]`));
  if (shownPending.length && ![...PENDING_KEYS].every((k) => hidden.has(k))) {
    breakdown.appendChild(el(
      'p',
      'nfl-muted nfl-pending-note',
      `* Pending: not every ${seasonList(shownPending)} Sunday-afternoon game has a network listed yet, so Fox AGOTW and CBS late national are not final.`,
    ));
  }
}

/** Appends the season table in its scroll wrapper (the site's edge-fade cue) and, on a phone, the hover lines. */
function appendBreakdownTable(table, lines) {
  const { breakdown } = refs;
  const scroll = el('div', 'table-scroll');
  scroll.appendChild(table);
  breakdown.appendChild(scroll);
  refs.cueOff?.();
  refs.cueOff = attachScrollCue(scroll, null);
  if (lines) breakdown.appendChild(lines);
}

/** The hover model as the phone's lines under the season table, with the tooltip's colour dots. */
function phoneLines(m) {
  const lines = el('div', 'nfl-breakdown-lines');
  hoverTextLines(m).slice(1).forEach((text, k) => {
    const p = el('p');
    const row = m.rows[k - 1];
    if (row) {
      const dot = el('span', 'tooltip-counts-dot');
      dot.setAttribute('aria-hidden', 'true');
      dot.style.backgroundColor = row.color;
      p.appendChild(dot);
    }
    p.appendChild(document.createTextNode(text));
    lines.appendChild(p);
  });
  return lines;
}

const NETWORK_SPECIAL_TIP = 'The games among them in a special category: a solo slot, Fox AGOTW, CBS late national or a game played abroad.';

/**
 * The season table with "Special games only" off: one column per network family, then the
 * season's games (their sum) and how many of them are special. A family the Networks filter
 * turns off reads as a dash, as a chip-hidden category does on the Special games table.
 */
function renderNetworkBreakdown(model, state, env, rows, fIdx, label) {
  const { breakdown } = refs;
  const { net } = model;
  const bar = (rows.find((r) => r.bar.franchise === fIdx) || {}).bar;
  const lines = (env.mobile || env.hoverNone) && bar
    ? phoneLines(networkHoverModel(model, state, label, bar, theme(env)))
    : null;
  const off = new Set(net.families.filter((f) => familyToggledOff(net, state, f)));
  // A family with only some of its networks on (ESPN without ABC) still has a column.
  const partial = state.networks != null && net.families.some((f) => {
    const ids = (net.networksByFamily.get(f) ?? []).map((idx) => net.lookups.networks[idx].id);
    const on = ids.filter((id) => state.networks.includes(id)).length;
    return on > 0 && on < ids.length;
  });
  const VR = ' nfl-vrule';
  // Short network heads: the table is as wide as its content, not the module.
  const table = el('table', 'games-table nfl-network-table');
  const tall = (text, cls) => {
    const th = cell('th', text, cls);
    th.rowSpan = 2;
    th.scope = 'col';
    return th;
  };
  const spanner = el('th', 'nfl-spanner' + VR);
  spanner.colSpan = net.families.length;
  spanner.scope = 'colgroup';
  spanner.appendChild(el('span', 'nfl-spanner-label', 'Games by network'));
  const specialHead = tall(null, 'num' + VR);
  tipHead(specialHead, 'Special games', NETWORK_SPECIAL_TIP, env);
  const row1 = el('tr');
  row1.append(tall('Season', null), spanner, tall('Games', 'num' + VR), specialHead);
  const row2 = el('tr');
  net.families.forEach((family, k) => {
    const th = el('th', 'num' + (k === 0 ? VR : ''));
    th.scope = 'col';
    th.dataset.family = family;
    const names = familyNetworkNames(model, family);
    if (family === 'other') tipHead(th, familyLabel(family), `${joinAnd(names)}.`, env);
    else if (family === 'tba') tipHead(th, familyLabel(family), 'Games whose network is not in the data, or is not assigned yet.', env);
    else th.textContent = familyLabel(family);
    row2.appendChild(th);
  });
  const thead = el('thead');
  thead.append(row1, row2);
  const tbody = el('tbody');
  for (const r of networkSeasonRows(model, state, fIdx)) {
    const tr = el('tr');
    tr.dataset.season = String(r.season);
    const season = cell('th', String(r.season));
    season.scope = 'row';
    const counts = new Map(r.segments.map((seg) => [seg.family, seg.count]));
    tr.append(
      season,
      ...net.families.map((family, k) => {
        const cls = 'num' + (k === 0 ? VR : '');
        if (off.has(family)) {
          const td = cell('td', '–', cls);
          td.dataset.hidden = 'true';
          td.setAttribute('aria-label', 'Hidden');
          return td;
        }
        return cell('td', String(counts.get(family) ?? 0), cls);
      }),
      cell('td', String(r.total), 'num nfl-vrule nfl-total'),
      cell('td', String(r.special), 'num nfl-vrule'),
    );
    tbody.appendChild(tr);
  }
  const groups = [1, net.families.length, 1, 1].map((span) => {
    const g = el('colgroup');
    g.span = span;
    return g;
  });
  table.append(...groups, thead, tbody);
  appendBreakdownTable(table, lines);
  if (!tbody.children.length) breakdown.appendChild(el('p', 'nfl-muted', 'No games match these filters.'));
  const notes = [
    off.size
      ? 'Games is the sum of the network columns before it; a dash marks a network turned off in the legend or the Networks filter.'
      : 'Games is the sum of the network columns before it.',
    ...(partial ? ['A column with some of its networks turned off counts only the ones left on.'] : []),
    'Special games counts the special games among them.',
  ];
  breakdown.appendChild(el('p', 'nfl-muted', notes.join(' ')));
}

function renderDataTable(rows, all, model) {
  const { dataBody } = refs;
  const families = all ? model.net.families : [];
  const heads = all
    ? ['Team', ...families.map(familyLabel), 'Games', 'Special games']
    : ['Team', ...SEGMENTS.map((seg) => seg.label), 'Total'];
  refs.dataCaption.textContent = all ? 'Games by team and network' : 'Special games by team';
  const hr = el('tr');
  for (const h of heads) {
    const th = el('th', null, h);
    th.scope = 'col';
    hr.appendChild(th);
  }
  refs.dataHead.replaceChildren(hr);
  rebuildKeepingFocus(dataBody, () => {
    dataBody.replaceChildren();
    for (const r of rows) {
      const tr = el('tr');
      const th = el('th');
      th.scope = 'row';
      const btn = el('button', null, r.label);
      btn.type = 'button';
      btn.dataset.key = r.id;
      btn.setAttribute('aria-label', `Select ${r.label}`);
      btn.addEventListener('click', () => toggleTeam(r));
      th.appendChild(btn);
      if (all) {
        const counts = new Map(r.bar.segments.map((seg) => [seg.family, seg.count]));
        tr.append(
          th,
          ...families.map((family) => cell('td', String(counts.get(family) ?? 0))),
          cell('td', String(r.bar.total)),
          cell('td', String(r.bar.special)),
        );
      } else {
        tr.append(
          th,
          ...SEGMENTS.map((seg) => cell('td', String(r.bar.counts[seg.key]))),
          cell('td', String(r.bar.total)),
        );
      }
      dataBody.appendChild(tr);
    }
  });
}

function renderShowAll(total, state) {
  const { ctx, showAll } = refs;
  if (total <= TOP_N) {
    showAll.hidden = true;
    return;
  }
  showAll.hidden = false;
  showAll.textContent = state.showAllTeams ? `Show top ${TOP_N}` : `Show all ${total} teams`;
  showAll.setAttribute('aria-pressed', String(state.showAllTeams));
  showAll.onclick = () => ctx.setState({ showAllTeams: !ctx.getState().showAllTeams });
}

function buildFigure(rows, state, env, th) {
  const hidden = new Set(state.hiddenSegments);
  const selected = selectedKey(state);
  const bg = PAGE_BG[th];
  const ids = rows.map((r) => r.id);
  const picked = rows.some((r) => r.bar.matched);
  // Under a pick every segment gets an explicit start so the matched overlay lines up exactly.
  const starts = new Map(SEGMENTS.map((seg) => [seg.key, []]));
  for (const r of rows) {
    let at = 0;
    for (const seg of SEGMENTS) {
      starts.get(seg.key).push(at);
      if (!hidden.has(seg.key)) at += r.bar.counts[seg.key];
    }
  }
  const rowFade = (r, seg) => (r.faded || r.bar.segmentFaded[seg.key] || (selected && r.id !== selected) ? FADE : 1);
  const trace = (seg, full) => ({
    type: 'bar',
    orientation: 'h',
    name: seg.label,
    ...(full ? {} : { meta: `matched:${seg.key}`, showlegend: false }),
    visible: hidden.has(seg.key) ? false : true,
    // A segment with no matched games draws no overlay (null, not a zero-length outlined bar).
    x: rows.map((r) => (full ? r.bar.counts[seg.key] : r.bar.matched[seg.key] || null)),
    ...(picked ? { base: starts.get(seg.key) } : {}),
    y: ids,
    customdata: rows.map((_, k) => k),
    hoverinfo: 'none',
    marker: {
      color: categoryColor(seg.key, th),
      opacity: rows.map((r) => {
        const f = rowFade(r, seg);
        return picked && full ? Math.min(f, DOT_OPACITY.inert) : f;
      }),
      line: {
        color: rows.map((r) => (r.id === selected ? ACCENT[th] : bg)),
        width: rows.map((r) => (r.id === selected ? 1.5 : 1)),
      },
    },
  });
  const traces = SEGMENTS.map((seg) => trace(seg, true));
  if (picked) for (const seg of SEGMENTS) traces.push(trace(seg, false));
  // End markers: the visible total per row.
  const totals = rows.map((r) => shownTotal(r.bar, state.hiddenSegments));
  const layout = barLayout(rows, totals, state, env, th, {
    title: 'Special games',
    barmode: picked ? 'overlay' : 'stack',
  });
  return { traces, layout: frameLayout(layout, { theme: th }) };
}

/** The figure with "Special games only" off: the shared stacked bars, one group per network family. */
function buildNetworkFigure(rows, state, env, th) {
  const selected = selectedKey(state);
  const faded = rows.map((r) => r.faded || (selected != null && r.id !== selected));
  const traces = networkTraces(rows, env, th, faded);
  const layout = barLayout(rows, rows.map((r) => r.bar.total), state, env, th, { title: 'Games', barmode: 'stack' });
  // The stacked builder puts its separators and hover targets on an overlay axis.
  layout.xaxis3 = overlayAxis('x', layout.xaxis.range);
  return { traces, layout: frameLayout(layout, { theme: th }) };
}

/**
 * The layout both modes share: one row per team with its name on the y axis, a count axis with
 * round ticks, and an end marker with each row's total in the hero colour (--ink at 80%, the
 * accent on the picked team).
 */
function barLayout(rows, totals, state, env, th, { title, barmode }) {
  const selected = selectedKey(state);
  const bg = PAGE_BG[th];
  const ids = rows.map((r) => r.id);
  const max = Math.max(0, ...totals);
  const pitch = env.mobile ? 44 : 32;
  const thickness = env.mobile ? 28 : 20;
  const fontPx = env.mobile ? TICK_FONT_PX.mobile : TICK_FONT_PX.desktop;
  const heroInk = mixHex(INK[th], bg, HERO_INK_WEIGHT);
  const fills = rows.map((r) => (r.id === selected ? SPECIAL[th] : heroInk));
  const markerRows = totals.map((total) => ({ total }));
  const markerHalf = Math.ceil(markerWidth(String(Math.max(max, 1))) / 2) + 2;
  // The y axis automargins to the team names, so the plot is narrower than the 8px left
  // margin says by the widest label (plus Plotly's tick pad); size the marker headroom to that.
  const labelPx = Math.ceil(Math.max(0, ...rows.map((r) => textWidth(r.label, { size: fontPx, family: FRAME_FONT }))));
  const plotPx = Math.max(1, (refs.chart.clientWidth || env.width || 600) - 8 - labelPx - LABEL_PAD_PX - 16);
  const top = Math.max(1, max) * Math.max(1.05, plotPx / Math.max(1, plotPx - markerHalf));
  const layout = {
    barmode,
    bargap: 1 - thickness / pitch,
    hovermode: 'closest',
    clickmode: 'event',
    dragmode: false,
    height: rows.length * pitch + 70,
    // NFL-only: horizontal bars need no top margin and a tiny left one, because
    // automargin sizes the left edge to the team names.
    // No value column at the right (notes 15): the end markers carry each total.
    margin: { l: 8, r: 16, t: 8, b: MARGIN.b },
    xaxis: {
      title: { text: title, standoff: 4 },
      range: [0, top],
      tickmode: 'linear',
      tick0: 0,
      dtick: niceStep(max),
      tickformat: ',d',
      gridcolor: DIVIDER[th],
      tickfont: { color: MUTED[th], size: fontPx },
      zeroline: false,
      fixedrange: true,
    },
    yaxis: {
      type: 'category',
      categoryorder: 'array',
      categoryarray: ids,
      tickmode: 'array',
      tickvals: ids,
      ticktext: rows.map((r) => escapeHover(r.label)),
      tickfont: { size: fontPx, color: INK[th] },
      autorange: 'reversed',
      automargin: true,
      showgrid: false,
      zeroline: false,
      fixedrange: true,
    },
  };
  layout.shapes = endMarkerShapes(markerRows, (r) => r.total, fills, th, 'x');
  layout.annotations = endMarkerAnnotations(markerRows, (r) => r.total, fills, th, 'x');
  return layout;
}

export function mount(container, ctx) {
  refs.ctx = ctx;
  const legendRow = el('div', 'legend-row');
  refs.legend = el('ul', 'legend-chips');
  // The key to the two fills of a network's group (all games only); it is not a control.
  refs.shadeKey = el('p', 'nfl-shade-key');
  for (const [cls, text] of [['is-solid', 'Special games'], ['is-light', 'Not special']]) {
    const item = el('span', 'nfl-shade-key-item');
    const mark = el('span', `nfl-shade-key-mark ${cls}`);
    mark.setAttribute('aria-hidden', 'true');
    item.append(mark, document.createTextNode(text));
    refs.shadeKey.appendChild(item);
  }
  const info = buildInfo(ctx);
  refs.infoDialog = info.dialog;
  refs.infoButton = info.button;
  legendRow.append(refs.legend, refs.shadeKey, info.button, info.dialog);
  bindLegend();
  // "Special games only" sits in the module header tools, a checkbox like Crews' Per season.
  const specialLabel = el('label', 'crews-perseason-label nfl-special-only-label');
  refs.specialBox = el('input', 'crews-perseason nfl-special-only');
  refs.specialBox.type = 'checkbox';
  refs.specialBox.addEventListener('change', () => ctx.setState({ special: refs.specialBox.checked }));
  specialLabel.append(refs.specialBox, ' Special games only');
  const tools = el('div', 'chart-controls nfl-teams-controls');
  tools.appendChild(specialLabel);
  refs.chart = el('div', 'nfl-chart');
  refs.gd = el('div');
  refs.note = el('div', 'season-empty-note');
  refs.note.setAttribute('role', 'status');
  refs.noteTitle = el('p', 'season-empty-title');
  refs.noteHint = el('p', 'season-empty-hint');
  refs.note.append(refs.noteTitle, refs.noteHint);
  refs.chart.append(refs.gd, refs.note);
  // Notes 15: a season whose Sunday-afternoon networks are missing says so under the chart.
  refs.pending = el('p', 'nfl-captions nfl-pending-caption');
  refs.pending.hidden = true;
  refs.showAll = el('button', 'toggle nfl-show-all');
  refs.showAll.type = 'button';
  refs.showAll.hidden = true;
  refs.breakdown = el('div', 'nfl-breakdown');
  refs.breakdown.hidden = true;
  refs.captions = el('div', 'nfl-captions');
  const dataWrap = el('div', DATA_TABLE_CLASS);
  const dataTable = el('table');
  dataWrap.appendChild(dataTable);
  // The caption and the head follow the toggle (renderDataTable).
  refs.dataCaption = el('caption');
  refs.dataHead = el('thead');
  refs.dataBody = el('tbody');
  dataTable.append(refs.dataCaption, refs.dataHead, refs.dataBody);
  container.append(legendRow, refs.chart, refs.pending, refs.showAll, refs.breakdown, refs.captions, dataWrap);
  mountViewTools(ctx, 'teams', [tools], container);
}

/** The games with no network among the games the all-games bars count: their seasons and how many. */
function tbaGames(model, state) {
  const mask = countedMask(model, state);
  const c = model.cols;
  const seasons = new Set();
  let games = 0;
  for (let i = 0; i < model.n; i++) {
    if (!mask[i] || c.network[i] != null) continue;
    seasons.add(c.season[i]);
    games += 1;
  }
  return { seasons: [...seasons].sort((a, b) => a - b), games };
}

/** The caption under the all-games chart when it counts a game with no network yet, else null. */
export function tbaText(tba) {
  if (!tba.games) return null;
  const n = tba.games;
  return `${n} ${n === 1 ? 'game' : 'games'} (${seasonList(tba.seasons)}) ${n === 1 ? 'has' : 'have'} no network listed.`;
}

/** Renders the tab with "Special games only" off: every counted game by team and network. */
function renderNetworks(ctx, model, state, env, th) {
  const bars = networkBars(model, state);
  // Keep a selected team's games in step with the filters; an all-games selection is exact.
  const key = selectedKey(state);
  if (key != null && model.franchiseIndex.has(key)) {
    const bar = bars.find((b) => b.franchise === model.franchiseIndex.get(key));
    const fresh = bar ? bar.games : [];
    const cur = state.selection.games || [];
    if (state.selection.exact !== true || fresh.length !== cur.length || fresh.some((g, k) => g !== cur[k])) {
      ctx.selectGames({ kind: 'team', key, label: state.selection.label, games: fresh, exact: true });
      return;
    }
  }

  renderNetworkLegend(model, state, th);
  const rowsAll = bars.map((bar) => ({
    bar,
    id: model.franchises[bar.franchise].id,
    label: teamLabel(model, state, bar.franchise),
    faded: bar.teamFaded,
  }));
  const rows = state.showAllTeams ? rowsAll : rowsAll.slice(0, TOP_N);
  const tba = tbaGames(model, state);
  drawn = { all: true, rows, totalTeams: rowsAll.length, env, theme: th, state, model, pending: tba };
  renderShowAll(rowsAll.length, state);
  renderDataTable(rows, true, model);
  renderBreakdown(model, state, env, rowsAll);

  const anyShown = rows.length > 0;
  if (anyShown) setNote(null);
  else setNote(EMPTY_TITLE, EMPTY_HINT);
  refs.drawn = anyShown;
  const caption = anyShown ? tbaText(tba) : null;
  refs.pending.hidden = caption == null;
  refs.pending.textContent = caption ?? '';
  if (!anyShown) {
    refs.showAll.hidden = true;
    return;
  }
  const fig = buildNetworkFigure(rows, state, env, th);
  refs.chart.style.minHeight = `${fig.layout.height}px`;
  window.Plotly.react(refs.gd, fig.traces, fig.layout, CONFIG);
  bindEvents(refs.gd);
}

export function render(ctx) {
  const model = ctx.model;
  const state = ctx.getState();
  const env = ctx.env();
  const th = theme(env);
  hideTooltip();

  const all = !state.special;
  refs.specialBox.checked = state.special;
  refs.shadeKey.hidden = !all;
  refs.legend.setAttribute(
    'aria-label',
    all ? 'Networks: select to show or hide' : 'Special game categories: select to show or hide',
  );
  refs.infoButton.setAttribute('aria-label', all ? 'About this chart' : 'About these categories');
  if (all) {
    renderNetworks(ctx, model, state, env, th);
    return;
  }

  // Keep a selected team's games in step with the season range, the Networks pick and the legend
  // chips. A selection made with the toggle off was exact; here the table filters it again.
  const key = selectedKey(state);
  if (key != null && model.franchiseIndex.has(key)) {
    const fresh = teamGames(model, state, model.franchiseIndex.get(key));
    const cur = state.selection.games || [];
    if (state.selection.exact === true || fresh.length !== cur.length || fresh.some((g, k) => g !== cur[k])) {
      ctx.selectGames({ kind: 'team', key, label: state.selection.label, games: fresh });
      return;
    }
  }

  renderLegend(state, th);
  const bars = teamBars(model, state);
  const picks = computePicks(model, state);
  let pickedGames = 0;
  if (picks.hasPick) {
    const counts = specialMatchedCounts(model, state, picks.matched);
    for (const bar of bars) {
      bar.matched = {};
      for (const seg of SEGMENTS) bar.matched[seg.key] = counts.get(bar.franchise)?.[seg.key] ?? 0;
      pickedGames += SEGMENTS.reduce((a, seg) => a + bar.matched[seg.key], 0);
    }
  }
  const hasGames = bars.some((b) => b.total > 0);
  const pending = pendingNetworkSeasons(model, state);
  const rowsAll = rankTeamBars(model, bars, state.hiddenSegments).map((bar) => ({
    bar,
    id: model.franchises[bar.franchise].id,
    label: teamLabel(model, state, bar.franchise),
    faded: bar.teamFaded,
  }));
  const rows = state.showAllTeams ? rowsAll : rowsAll.slice(0, TOP_N);
  drawn = { all: false, rows, totalTeams: rowsAll.length, env, theme: th, state, model, pending };
  renderShowAll(rowsAll.length, state);
  renderDataTable(rows, false, model);
  renderBreakdown(model, state, env, rowsAll);

  let anyShown = false;
  if (!model.n || !model.special.some((r) => r.season >= state.seasons[0] && r.season <= state.seasons[1])) {
    setNote(EMPTY_TITLE, EMPTY_HINT);
  } else if (!hasGames || (picks.hasPick && pickedGames === 0)) {
    setNote(EMPTY_TITLE, EMPTY_HINT);
  } else {
    anyShown = true;
    setNote(null);
  }
  refs.drawn = anyShown;
  // The caption names both segments whatever the chips show, so a chip click never moves it.
  const caption = anyShown ? pendingText(pending, []) : null;
  refs.pending.hidden = caption == null;
  refs.pending.textContent = caption ?? '';
  if (!anyShown) {
    refs.showAll.hidden = true;
    return;
  }
  const fig = buildFigure(rows, state, env, th);
  // The container follows the figure height (rows x pitch + margins), not the 520px CSS minimum,
  // so a short chart leaves no blank band below the plot.
  refs.chart.style.minHeight = `${fig.layout.height}px`;
  window.Plotly.react(refs.gd, fig.traces, fig.layout, CONFIG);
  bindEvents(refs.gd);
}

export function resize() {
  if (refs.drawn && refs.gd && window.Plotly && refs.gd.data) window.Plotly.Plots.resize(refs.gd);
}

export function testModel() {
  if (!drawn || !refs.drawn) {
    const s = refs.ctx ? refs.ctx.getState() : null;
    return {
      view: 'teams',
      mode: s && !s.special ? 'all' : 'special',
      drawn: false,
      rows: [],
      hiddenSegments: s ? [...s.hiddenSegments] : [],
      selected: s ? selectedKey(s) : null,
    };
  }
  const s = refs.ctx.getState();
  if (drawn.all) {
    const { net } = drawn.model;
    const counts = networkFacets(drawn.model, s);
    return {
      view: 'teams',
      mode: 'all',
      drawn: true,
      rows: drawn.rows.map((r) => ({
        franchise: r.id,
        label: r.label,
        total: r.bar.total,
        special: r.bar.special,
        faded: r.faded,
        games: [...r.bar.games],
        segments: r.bar.segments.map((seg) => ({
          family: seg.family,
          count: seg.count,
          special: seg.special,
          channels: seg.channels.map((ch) => ({ id: ch.id, count: ch.count, special: ch.special })),
        })),
      })),
      families: net.families.map((family) => ({
        family,
        label: familyLabel(family),
        on: !familyToggledOff(net, s, family),
        games: (net.networksByFamily.get(family) ?? []).reduce((sum, idx) => sum + counts[idx], 0),
      })),
      networks: s.networks,
      selected: selectedKey(s),
      totalTeams: drawn.totalTeams,
      tba: { ...drawn.pending },
      hover: drawn.rows.map((r) => hoverTextLines(rowHover(drawn, r))),
    };
  }
  return {
    view: 'teams',
    mode: 'special',
    drawn: true,
    rows: drawn.rows.map((r) => ({
      franchise: r.id,
      label: r.label,
      counts: { ...r.bar.counts },
      total: r.bar.total,
      faded: r.faded,
      matched: r.bar.matched ? { ...r.bar.matched } : null,
      segmentFaded: { ...r.bar.segmentFaded },
    })),
    overlay: drawn.rows.flatMap((r) => (r.bar.matched
      ? SEGMENTS.filter((seg) => r.bar.matched[seg.key] > 0)
        .map((seg) => ({ id: r.id, segment: seg.key, matched: r.bar.matched[seg.key], total: r.bar.counts[seg.key] }))
      : [])),
    hiddenSegments: [...s.hiddenSegments],
    selected: selectedKey(s),
    totalTeams: teamBars(drawn.model, s).length,
    pending: { ...drawn.pending },
    hover: drawn.rows.map((r) => hoverTextLines(rowHover(drawn, r))),
  };
}

/** Closes the info modal (the shell calls this when it leaves the NFL page). */
export function closeInfo() {
  if (refs.infoDialog?.open) refs.infoDialog.close();
}
