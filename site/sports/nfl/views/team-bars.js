/**
 * NFL view 1: Special games by team (D-12, D-13, D-24).
 *
 * A stacked horizontal Plotly bar per franchise over the selected seasons, eight
 * exclusive segments (Thursday night ... International), each game
 * counted once. The legend is CFB's chip row with double-click "only this one"
 * (D-15) and an info note with one definition per segment (D-13). Hover text, the
 * season breakdown and the hidden data table are all built with
 * createElement/textContent; names enter Plotly strings only through
 * escapeHover, and customdata carries row indexes, never names.
 */
import { teamBars, teamSeasonRows, specialMatchedCounts, EXCLUSIVE_CATEGORIES } from '../state.js';
import { computePicks } from '../picks.js';
import { createOnlyDetector, makeLegendChip } from '../../../modules/legend.js';
import { initBandInfo } from '../../../modules/band-info.js';
import { MARGIN, TICK_FONT_PX, DOT_OPACITY } from '../../../modules/chart.js';
import { categoryColor } from '../palette.js';
import { ACCENT, INK, MUTED, PAGE_BG, DIVIDER, SPECIAL, mixHex } from '../../../modules/palette.js';
import { FRAME_FONT, frameConfig, frameLayout } from '../../../modules/chart-frame.js';
import {
  endMarkerAnnotations,
  endMarkerShapes,
  markerWidth,
  textWidth,
  valueColumn,
} from '../../../modules/bar-chart.js';
import { ensureTooltipEl, showTextTooltip, hideTooltip } from '../../../modules/tooltip.js';
import { escapeHover } from '../../../modules/format.js';
import { DATA_TABLE_CLASS, rebuildKeepingFocus } from '../data-table.js';

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
const VALUE_COL_PX = 12;
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
  dataBody: null,
  bound: false,
};

// What the last render drew (also what the event handlers read).
let drawn = null; // { rows, env, theme, state, model }

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

/** Every game of the franchise in the season range that is special or international. */
function teamGames(model, state, fIdx) {
  const c = model.cols;
  const [lo, hi] = state.seasons;
  return (model.franchiseGames.get(fIdx) || []).filter(
    (i) =>
      c.season[i] >= lo
      && c.season[i] <= hi
      && (c.standalone[i] || c.agotw[i] || c.cbs_national[i] || c.international[i]),
  );
}

function slotText(slots) {
  const ordered = [...slots].sort((a, b) => SLOT_ORDER.indexOf(a.label) - SLOT_ORDER.indexOf(b.label));
  return ordered.map((s) => `${s.label === 'Other' ? 'other' : s.label} ${s.count}`).join(', ');
}

/** The hover lines (UI-SPEC order) for a bar entry, without the click hint. */
function hoverLines(state, label, bar) {
  const [lo, hi] = state.seasons;
  const title = lo === hi ? `${label}, ${lo}` : `${label}, ${lo}–${hi}`;
  // Under an Announcers or Booths pick the second line is the matched share (UI-SPEC Q7).
  const matchedTotal = bar.matched ? SEGMENTS.reduce((a, seg) => a + bar.matched[seg.key], 0) : 0;
  const lines = [
    { text: title, kind: 'title' },
    { text: bar.matched ? `${matchedTotal} of ${bar.total} games` : `${bar.total} special games`, kind: 'body' },
  ];
  for (const seg of SEGMENTS) {
    const n = bar.counts[seg.key];
    if (n > 0) lines.push({ text: `${seg.label}: ${n}`, kind: 'body' });
  }
  if (bar.slots.length) lines.push({ text: `Solo slots: ${slotText(bar.slots)}`, kind: 'body' });
  lines.push(
    { text: `International, any window: ${bar.international}`, kind: 'body' },
    { text: `Flexed: ${bar.flexed}`, kind: 'body' },
  );
  return lines;
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
  ctx.selectGames({
    kind: 'team',
    key: id,
    label: row.label,
    games: teamGames(model, state, row.bar.franchise),
  });
}

function bindEvents(gd) {
  if (refs.bound) return;
  refs.bound = true;
  gd.on('plotly_click', (ev) => {
    const k = ev.points && ev.points[0] ? ev.points[0].customdata : null;
    if (drawn && Number.isInteger(k) && drawn.rows[k]) toggleTeam(drawn.rows[k]);
  });
  gd.on('plotly_hover', (ev) => {
    const k = ev.points && ev.points[0] ? ev.points[0].customdata : null;
    if (!drawn || !Number.isInteger(k) || !drawn.rows[k]) return;
    if (drawn.env.mobile || drawn.env.hoverNone) return;
    const row = drawn.rows[k];
    const lines = hoverLines(drawn.state, row.label, row.bar);
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
  'Other solo slot: any other game with no NFL game within 3 hours, such as Saturday or an international morning game.',
  "Fox AGOTW: Fox's top game on a Sunday afternoon doubleheader.",
  "CBS late national: CBS's national game in the late Sunday window.",
  'International: a game played abroad that shares its window with other games.',
]);

const ALL_KEYS = SEGMENTS.map((s) => s.key);

/** Sets hiddenSegments to the keys in `hide`, in segment order. */
function setHidden(ctx, hide) {
  const set = new Set(hide);
  ctx.setState({ hiddenSegments: ALL_KEYS.filter((k) => set.has(k)) });
}

/** Binds the one delegated chip listener (D-15); the chips themselves are rebuilt each render. */
function bindLegend() {
  const { ctx, legend } = refs;
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
    const button = ev.target.closest('button[data-segment]');
    if (!button) {
      // A click in the gaps between chips ends any pending first click.
      detector.reset();
      return;
    }
    detector.click(ev, button.dataset.segment);
  });
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
  button.setAttribute('aria-label', 'About these categories');
  button.setAttribute('aria-expanded', 'false');
  button.append(el('span', 'band-info-glyph', 'i'));
  button.firstChild.setAttribute('aria-hidden', 'true');
  const note = el('div', 'band-note');
  note.hidden = true;
  for (const line of SEGMENT_NOTES) note.appendChild(el('p', null, line));
  const foot = el('p');
  foot.append(document.createTextNode('Each game counts once. See '));
  const a = el('a', null, 'methodology');
  a.href = ctx.methodologyHref('nfl-special-games');
  a.rel = 'noopener noreferrer';
  foot.append(a, document.createTextNode(' for the full rules.'));
  note.appendChild(foot);
  // CFB positions .band-info absolutely inside the chart; style.css puts both in the legend row's flow.
  button.classList.add('nfl-legend-info');
  note.classList.add('nfl-legend-info-note');
  return { button, note };
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
const SPECIAL_TIP = 'Solo slots plus Sunday-window games: Thu + Sun + Mon + Holiday + Other solo + AGOTW + CBS + Intl.';
const SEGMENT_TIPS = Object.freeze({
  solo_other: 'A game alone in its window that is not a Thursday, Sunday or Monday night game or a holiday, such as a Saturday, Friday or lone Sunday-afternoon game, or a solo international game.',
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
    showTextTooltip([{ kind: 'body', text }], {
      theme: theme(e),
      borderColor: DIVIDER[theme(e)],
      clientX: rect.left,
      clientY: rect.bottom,
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

  const bar = (rows.find((r) => r.bar.franchise === fIdx) || {}).bar
    || teamBars(model, state).find((b) => b.franchise === fIdx);
  if ((env.mobile || env.hoverNone) && bar) {
    const lines = el('div', 'nfl-breakdown-lines');
    for (const l of hoverLines(state, label, bar).slice(1)) lines.appendChild(el('p', null, l.text));
    breakdown.appendChild(lines);
  }

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
  for (const r of teamSeasonRows(model, state, fIdx)) {
    const tr = el('tr');
    tr.dataset.season = String(r.season);
    const season = cell('th', String(r.season));
    season.scope = 'row';
    tr.append(
      season,
      ...SEGMENTS.map((seg) => cell('td', String(r.counts[seg.key]), 'num' + (RULE_KEYS.has(seg.key) ? VR : ''))),
      cell('td', String(r.total), 'num nfl-vrule nfl-total'),
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
  // Eleven columns do not fit a phone; the table scrolls inside its own wrapper.
  const scroll = el('div', 'table-scroll');
  scroll.appendChild(table);
  breakdown.appendChild(scroll);

  breakdown.appendChild(el(
    'p',
    'nfl-muted',
    'Special games is the sum of the eight columns before it. Flexed games are counted separately.',
  ));
}

function renderDataTable(rows) {
  const { dataBody } = refs;
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
      tr.append(
        th,
        ...SEGMENTS.map((seg) => cell('td', String(r.bar.counts[seg.key]))),
        cell('td', String(r.bar.total)),
      );
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
  let max = 0;
  for (const r of rows) {
    const sum = SEGMENTS.reduce((a, seg) => a + (hidden.has(seg.key) ? 0 : r.bar.counts[seg.key]), 0);
    if (sum > max) max = sum;
  }
  const pitch = env.mobile ? 44 : 32;
  const thickness = env.mobile ? 28 : 20;
  const fontPx = env.mobile ? TICK_FONT_PX.mobile : TICK_FONT_PX.desktop;
  // End markers: the visible total per row, in the hero colour (--ink at 80%, accent on the picked team).
  const totals = rows.map((r) =>
    SEGMENTS.reduce((a, seg) => a + (hidden.has(seg.key) ? 0 : r.bar.counts[seg.key]), 0));
  const heroInk = mixHex(INK[th], bg, HERO_INK_WEIGHT);
  const fills = rows.map((r) => (r.id === selected ? SPECIAL[th] : heroInk));
  const markerRows = totals.map((total) => ({ total }));
  const columnPx = Math.ceil(textWidth(String(Math.max(max, 1)), { size: 14 })) + VALUE_COL_PX;
  const markerHalf = Math.ceil(markerWidth(String(Math.max(max, 1))) / 2) + 2;
  // The y axis automargins to the team names, so the plot is narrower than the 8px left
  // margin says by the widest label (plus Plotly's tick pad); size the marker headroom to that.
  const labelPx = Math.ceil(Math.max(0, ...rows.map((r) => textWidth(r.label, { size: fontPx, family: FRAME_FONT }))));
  const plotPx = Math.max(1, (refs.chart.clientWidth || env.width || 600) - 8 - labelPx - LABEL_PAD_PX - columnPx - 16);
  const top = Math.max(1, max) * Math.max(1.05, plotPx / Math.max(1, plotPx - markerHalf));
  const layout = {
    barmode: picked ? 'overlay' : 'stack',
    bargap: 1 - thickness / pitch,
    hovermode: 'closest',
    clickmode: 'event',
    dragmode: false,
    height: rows.length * pitch + 70,
    // NFL-only: horizontal bars need no top margin and a tiny left one, because
    // automargin sizes the left edge to the team names.
    margin: { l: 8, r: 16 + columnPx, t: 8, b: MARGIN.b },
    xaxis: {
      title: { text: 'Special games', standoff: 4 },
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
  layout.annotations = endMarkerAnnotations(markerRows, (r) => r.total, fills, th, 'x').concat(
    valueColumn(markerRows, (r) => r.total, layout.margin.r, th),
  );
  return { traces, layout: frameLayout(layout, { theme: th }) };
}

export function mount(container, ctx) {
  refs.ctx = ctx;
  const legendRow = el('div', 'legend-row');
  refs.legend = el('ul', 'legend-chips');
  refs.legend.setAttribute('aria-label', 'Special game categories: select to show or hide');
  const info = buildInfo(ctx);
  legendRow.append(refs.legend, info.button, info.note);
  initBandInfo(info);
  bindLegend();
  refs.chart = el('div', 'nfl-chart');
  refs.gd = el('div');
  refs.note = el('div', 'season-empty-note');
  refs.note.setAttribute('role', 'status');
  refs.noteTitle = el('p', 'season-empty-title');
  refs.noteHint = el('p', 'season-empty-hint');
  refs.note.append(refs.noteTitle, refs.noteHint);
  refs.chart.append(refs.gd, refs.note);
  refs.showAll = el('button', 'toggle nfl-show-all');
  refs.showAll.type = 'button';
  refs.showAll.hidden = true;
  refs.breakdown = el('div', 'nfl-breakdown');
  refs.breakdown.hidden = true;
  refs.captions = el('div', 'nfl-captions');
  const dataWrap = el('div', DATA_TABLE_CLASS);
  const dataTable = el('table');
  dataWrap.appendChild(dataTable);
  dataTable.appendChild(el('caption', null, 'Special games by team'));
  const thead = el('thead');
  const hr = el('tr');
  for (const h of ['Team', ...SEGMENTS.map((s) => s.label), 'Total']) {
    const th = el('th', null, h);
    th.scope = 'col';
    hr.appendChild(th);
  }
  thead.appendChild(hr);
  refs.dataBody = el('tbody');
  dataTable.append(thead, refs.dataBody);
  container.append(legendRow, refs.chart, refs.showAll, refs.breakdown, refs.captions, dataWrap);
}

export function render(ctx) {
  const model = ctx.model;
  const state = ctx.getState();
  const env = ctx.env();
  const th = theme(env);
  hideTooltip();

  // Keep a selected team's games in step with the season range.
  const key = selectedKey(state);
  if (key != null && model.franchiseIndex.has(key)) {
    const fresh = teamGames(model, state, model.franchiseIndex.get(key));
    const cur = state.selection.games || [];
    if (fresh.length !== cur.length || fresh.some((g, k) => g !== cur[k])) {
      ctx.selectGames({ ...state.selection, games: fresh });
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
  const rowsAll = bars.map((bar) => ({
    bar,
    id: model.franchises[bar.franchise].id,
    label: teamLabel(model, state, bar.franchise),
    faded: bar.teamFaded,
  }));
  const rows = state.showAllTeams ? rowsAll : rowsAll.slice(0, TOP_N);
  drawn = { rows, env, theme: th, state, model };
  renderShowAll(rowsAll.length, state);
  renderDataTable(rows);
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
      view: 'special',
      drawn: false,
      rows: [],
      hiddenSegments: s ? [...s.hiddenSegments] : [],
      selected: s ? selectedKey(s) : null,
    };
  }
  const s = refs.ctx.getState();
  return {
    view: 'special',
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
  };
}
