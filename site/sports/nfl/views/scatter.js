/**
 * NFL view 4: Game scatter (D-16, D-17).
 *
 * One svg `scatter` dot per regular-season NFL game. Y is viewers (log) or
 * excitement (linear, GEI-style: the qualifier lives in the caption and hover only); X is date or absolute final margin, never the
 * spread. Games with no Y value sit in a strip under the plot (the unrated
 * band) and games with no final score sit in an N/A strip at the left of the
 * margin axis. A missing value is never plotted at 0. Dots are colored by
 * exclusive category, fade (or hide) under the Seasons, Team and Category
 * filters and highlight under Announcers.
 *
 * Date X reuses the CFB `buildDateAxis` for the block geometry: it keys blocks
 * by the season column and measures days from each season's first game, so a
 * September to January NFL season (January games carry the start-year season)
 * lays out as one contiguous block (RESEARCH A2 verified on the fixture). Its
 * lower tick row is Saturday-based and wired to the CFB chart, so the tick and
 * label rows are built here. Game strings only reach the DOM through
 * textContent/createElement; customdata holds game indexes only.
 */
import { gamePasses, personHighlight, EXCLUSIVE_CATEGORIES } from '../state.js';
import { gameRow } from '../data.js';
import { categoryColor } from '../palette.js';
import { CAUSE_COPY, slotLabel, flagLabels, viewersText, kickoffText, dateShortText } from '../game-format.js';
import { ACCENT, MUTED, PAGE_BG, DIVIDER, ZERO_LINE } from '../../../modules/palette.js';
import { frameConfig, frameLayout } from '../../../modules/chart-frame.js';
import { showTextTooltip, hideTooltip } from '../../../modules/tooltip.js';
import { showHoverRing, hideHoverRing, ringSpecFromPoint, hoverRingDiameter } from '../../../modules/hover-ring.js';
import { initBandInfo, positionBandInfo, closeBandNote } from '../../../modules/band-info.js';
import { placeEraLabels, setEraCaption } from '../era-labels.js';
import { bandLayout, MARGIN, TICK_FONT_PX, DOT_OPACITY } from '../../../modules/chart.js';
import { createOnlyDetector } from '../../../modules/legend.js';
import { buildDateAxis, seasonRange, shownBlocks, gapDividers } from '../../../modules/date-axis.js';
import { MONTHS, escapeHover } from '../../../modules/format.js';
import { mountViewTools } from '../tools.js';
import { DATA_TABLE_CLASS, findRowButton, rebuildKeepingFocus, rovingRows } from '../data-table.js';

const CONFIG = frameConfig({ zoomable: true });

const Y_TITLES = { viewers: 'Viewers', excitement: 'Excitement' };
const X_TITLE_MARGIN = 'Final margin (points)';
const VIEWER_TICKS = [
  [5e5, '500K'], [1e6, '1M'], [2e6, '2M'], [5e6, '5M'], [1e7, '10M'], [2e7, '20M'],
];
const BAND_FILL = { light: 'rgba(75, 85, 99, 0.06)', dark: 'rgba(156, 163, 175, 0.10)' };
// Marker sizes match the CFB scatter's base (6) and highlighted (10) dots.
const BASE_SIZE = 6;
const HIGHLIGHT_SIZE = 10;
const NA_X = -2.5; // the N/A strip's center on the margin axis
const NA_EDGE = -1; // the strip's right divider

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function link(text, href) {
  const a = el('a', null, text);
  a.href = href;
  a.rel = 'noopener noreferrer';
  return a;
}

const refs = {
  ctx: null,
  legend: null,
  controls: null,
  yGroup: null,
  xGroup: null,
  dotsGroup: null,
  chips: null,
  chart: null,
  gd: null,
  note: null,
  bandButton: null,
  bandText: null,
  bandNote: null,
  noteViewers: null,
  noteExcitement: null,
  captions: null,
  dataBody: null,
  drawn: false,
  bound: false,
};

const hiddenCats = new Set(); // exclusive-category keys toggled off by their legend chips
let current = null; // what the last render drew
let dateCache = { model: null, dateX: null, axis: null };
let lastToggle = { key: null, at: 0 };

function theme(env) {
  return env.dark ? 'dark' : 'light';
}

function textOn(hex) {
  const lin = (v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  const n = parseInt(hex.slice(1), 16);
  const lum = 0.2126 * lin(n >> 16) + 0.7152 * lin((n >> 8) & 255) + 0.0722 * lin(n & 255);
  return 1.05 / (lum + 0.05) >= (lum + 0.05) / 0.05 ? '#FFFFFF' : '#111111';
}

function dateGeometry(model) {
  if (dateCache.model !== model) {
    const c = model.cols;
    const { dateX, axis } = buildDateAxis(c.season, c.date, c.kickoff);
    dateCache = { model, dateX, axis };
  }
  return dateCache;
}

/** Era index owning most of a season's rated games, or null. */
function seasonEras(model) {
  const c = model.cols;
  const tally = new Map();
  for (let i = 0; i < model.n; i++) {
    if (c.era[i] == null) continue;
    const m = tally.get(c.season[i]) || new Map();
    m.set(c.era[i], (m.get(c.era[i]) || 0) + 1);
    tally.set(c.season[i], m);
  }
  const out = new Map();
  for (const [season, m] of tally) {
    let best = null;
    for (const [era, n] of m) if (best == null || n > best[1]) best = [era, n];
    out.set(season, best[0]);
  }
  return out;
}

// ---- items ----

function buildItems(model, state) {
  const c = model.cols;
  const geo = state.scatterX === 'date' ? dateGeometry(model) : null;
  const items = [];
  const counts = { plotted: 0, band: 0, faded: 0, hidden: 0, highlighted: 0, naStrip: 0 };
  const bandCauses = { pending: 0, regional: 0, none: 0 };
  const yKey = state.scatterY;
  for (let i = 0; i < model.n; i++) {
    const cat = EXCLUSIVE_CATEGORIES[model.category[i]];
    if (hiddenCats.has(cat.key)) {
      counts.hidden += 1;
      continue;
    }
    const pass = gamePasses(model, state, i);
    if (!pass && state.dots === 'hide') {
      counts.hidden += 1;
      continue;
    }
    const y = yKey === 'viewers' ? c.viewers[i] : c.excitement[i];
    let x;
    let na = false;
    if (geo) x = geo.dateX[i];
    else if (c.final_margin[i] == null) {
      x = NA_X;
      na = true;
    } else x = Math.abs(c.final_margin[i]);
    const band = y == null;
    const highlight = pass && personHighlight(model, state, i);
    items.push({ i, x, y: band ? null : y, band, na, pass, highlight, cat });
    if (band) {
      counts.band += 1;
      if (c.viewers[i] == null) {
        const cause = c.cause[i];
        bandCauses[cause in bandCauses ? cause : 'none'] += 1;
      }
    } else counts.plotted += 1;
    if (na) counts.naStrip += 1;
    if (!pass) counts.faded += 1;
    if (highlight) counts.highlighted += 1;
  }
  return { items, counts, bandCauses };
}

/** Deterministic vertical spread inside the band so overlapping dots stay countable. */
function bandY(i) {
  return 0.12 + ((i * 0.6180339887) % 1) * 0.76;
}

// ---- selection and hover ----

/** `fromTable`: the pick came from the data table's Details button, which then gets focus back when the panel closes. */
function pickGame(i, fromTable = false) {
  const { ctx } = refs;
  // A touch tap reaches Plotly as touchend and again as the emulated mouseup.
  const now = Date.now();
  if (lastToggle.key === i && now - lastToggle.at < 500) return;
  lastToggle = { key: i, at: now };
  const sel = ctx.getState().selection;
  const prev = sel && sel.kind === 'games' && sel.key === 'scatter' && Array.isArray(sel.games) ? sel.games : [];
  const games = prev.includes(i) ? prev : [...prev, i];
  ctx.selectGames({ kind: 'games', key: 'scatter', label: 'Picked games', games });
  const opener = fromTable ? findRowButton(refs.dataBody, String(i)) : null;
  ctx.openGame(i, opener ?? refs.gd);
}

function hoverLines(model, i, state) {
  const row = gameRow(model, i);
  const lines = [{ text: `${row.away} at ${row.home}`, kind: 'title' }];
  const kick = kickoffText(row);
  lines.push({
    text: `${dateShortText(row)}${kick ? `, ${kick}` : ''} · Week ${row.week}`,
    kind: 'body',
  });
  lines.push({ text: [slotLabel(row.slot), ...flagLabels(row)].join(' · '), kind: 'body' });
  if (row.network) {
    lines.push({ kind: 'network', network: { id: row.networkId, name: row.network, family: row.networkFamily } });
  }
  const pbp = row.crew.find((m) => m.role === 'pbp');
  const analyst = row.crew.find((m) => m.role === 'analyst');
  const picked = new Set((state?.people ?? []).map((id) => model.personIndex.get(id)));
  const entries = [pbp, analyst].filter(Boolean).map((m) => ({
    name: m.name,
    role: m.role,
    selected: picked.has(m.person),
  }));
  if (entries.length > 0) lines.push({ kind: 'crew', entries });
  if (row.viewers != null) {
    lines.push({
      text: `Viewers: ${viewersText(row)}${row.scope === 'window' ? ' · window-level' : ''}`,
      kind: 'body',
    });
  } else {
    const cause = CAUSE_COPY[row.cause] ?? CAUSE_COPY.none;
    lines.push({ text: `Viewers: not available (${cause.hover})`, kind: 'body' });
  }
  lines.push({
    text: row.excitement != null
      ? `Excitement: ${row.excitement.toFixed(1)} (GEI-style, not CFBD's index)`
      : 'Excitement: not available',
    kind: 'body',
  });
  return lines;
}

function itemFor(ev) {
  const pt = ev.points && ev.points[0] ? ev.points[0] : null;
  const k = pt ? pt.customdata : null;
  if (!current || !Number.isInteger(k)) return null;
  return current.byGame.get(k) || null;
}

/**
 * The hovered dot's client-pixel position, for the hover ring (the CFB scatter
 * derives its ring the same way). The tooltip keeps the pointer position; only
 * the ring uses this, so it sits on the dot even when the pointer is a few px
 * off it. The point-based math reaches into undocumented Plotly internals
 * (`_fullLayout`, `_offset`, `.l2p`). If a vendored Plotly version reshapes or
 * drops any of them, fall through to the hover event's own client coordinates
 * rather than letting the exception silently swallow the hover (Plotly's event
 * dispatch does not surface a throwing listener to the user).
 */
function pointClientPosition(gd, ev) {
  const point = ev.points && ev.points[0];
  let clientX;
  let clientY;
  try {
    if (point && point.x != null && point.y != null && gd._fullLayout) {
      const layout = gd._fullLayout;
      const rect = gd.getBoundingClientRect();
      // Each event point carries its own axes, so band (y2) points anchor on y2.
      const xa = point.xaxis ?? layout.xaxis;
      const ya = point.yaxis ?? layout.yaxis;
      clientX = rect.left + xa._offset + xa.l2p(xa.d2l(point.x));
      clientY = rect.top + ya._offset + ya.l2p(ya.d2l(point.y));
    }
  } catch {
    clientX = undefined;
    clientY = undefined;
  }
  if (clientX == null || clientY == null) {
    clientX = ev.event?.clientX;
    clientY = ev.event?.clientY;
  }
  return { clientX, clientY };
}

function bindEvents(gd) {
  if (refs.bound) return;
  refs.bound = true;
  gd.on('plotly_relayout', syncResetZoom);
  gd.on('plotly_click', (ev) => {
    const it = itemFor(ev);
    if (it && it.pass) pickGame(it.i);
  });
  gd.on('plotly_hover', (ev) => {
    const it = itemFor(ev);
    if (!it || !it.pass) return;
    if (current.env.mobile || current.env.hoverNone) return;
    const e = ev.event || {};
    const pointerX = e.clientX ?? 0;
    const pointerY = e.clientY ?? 0;
    showTextTooltip(hoverLines(current.model, it.i, current.state), {
      theme: theme(current.env),
      borderColor: ACCENT[theme(current.env)],
      clientX: pointerX,
      clientY: pointerY,
    });
    const at = pointClientPosition(gd, ev);
    if (Number.isFinite(at.clientX) && Number.isFinite(at.clientY)) {
      const spec = ringSpecFromPoint(ev.points[0]);
      showHoverRing({
        i: it.i,
        clientX: at.clientX,
        clientY: at.clientY,
        diameter: hoverRingDiameter(spec.size, spec.symbol),
      });
    }
  });
  gd.on('plotly_unhover', () => {
    hideTooltip();
    hideHoverRing();
  });
  gd.on('plotly_afterplot', () => placeBandInfo());
}

// ---- controls, legend, captions, table ----

function segmented(label, options, onPick, dataAttr) {
  const group = el('div', 'segmented');
  group.setAttribute('role', 'group');
  group.setAttribute('aria-label', label);
  for (const o of options) {
    const b = el('button', null, o.long ? null : o.label);
    b.type = 'button';
    b.dataset.value = o.key;
    if (dataAttr) b.dataset[dataAttr] = o.key;
    if (o.long) {
      b.setAttribute('aria-label', o.ariaLabel || o.long);
      if (o.title) b.title = o.title;
      b.append(el('span', 'axis-long', o.long), el('span', 'axis-short', o.short));
    }
    b.addEventListener('click', () => onPick(o.key));
    group.appendChild(b);
  }
  return group;
}

function pressGroup(group, value) {
  for (const b of group.querySelectorAll('button')) {
    b.setAttribute('aria-pressed', String(b.dataset.value === value));
  }
}

function axisGroup(caption, group) {
  const wrap = el('div', 'axis-group');
  const cap = el('span', 'axis-caption', caption);
  cap.setAttribute('aria-hidden', 'true');
  wrap.append(cap, group);
  return wrap;
}

function buildControls() {
  const { ctx } = refs;
  // CFB markup and wording (D-16, D-18). The X set is NFL-only: Date and Final margin,
  // because the spread is never shown. Y keeps NFL's narrower set (no points or margin).
  refs.xGroup = segmented(
    'X-axis measure',
    [
      { key: 'date', label: 'Date', long: 'Date', short: 'Date' },
      { key: 'margin', label: 'Final margin', long: 'Final margin', short: 'Final margin' },
    ],
    (k) => ctx.setState({ scatterX: k }),
    'axis',
  );
  refs.yGroup = segmented(
    'Y-axis measure',
    [
      { key: 'viewers', label: 'Viewers' },
      { key: 'excitement', long: 'Excitement', short: 'Excite.', title: 'Excitement' },
    ],
    (k) => ctx.setState({ scatterY: k }),
    'y',
  );
  refs.dotsGroup = segmented(
    'Filtered-out dots',
    [{ key: 'fade', label: 'Fade' }, { key: 'hide', label: 'Hide' }],
    (k) => ctx.setState({ dots: k }),
    'dots',
  );
  const dotsHint = 'Filters fade the games they exclude unless Hide is on.';
  refs.dotsGroup.title = dotsHint;
  refs.dotsGroup.setAttribute('aria-description', dotsHint);
  refs.dotsToggle = el('div', 'dots-toggle');
  const dotsCap = el('span', 'dots-caption', 'Filtered-out dots');
  dotsCap.setAttribute('aria-hidden', 'true');
  refs.dotsToggle.append(dotsCap, refs.dotsGroup);
  const scatterControls = el('div', 'scatter-controls');
  scatterControls.append(axisGroup('X axis', refs.xGroup), axisGroup('Y axis', refs.yGroup));
  refs.controls.appendChild(scatterControls);
  // Page-style Reset zoom (13-13): aria-disabled at the home range, same as the CFB scatter.
  refs.resetZoom = el('button', 'reset-zoom', 'Reset zoom');
  refs.resetZoom.type = 'button';
  refs.resetZoom.setAttribute('aria-disabled', 'true');
  refs.resetZoom.addEventListener('click', resetToHome);
  refs.controls.appendChild(refs.resetZoom);
}

/** The axis ranges Plotly drew last, as plain arrays (null before the first draw). */
function liveRanges(gd) {
  const full = gd && gd._fullLayout;
  if (!full || !full.xaxis || !full.yaxis) return null;
  return { x: [...full.xaxis.range], y: [...full.yaxis.range] };
}

const sameRange = (a, b) => a.length === b.length && a.every((v, i) => v === b[i]);

/** Reset zoom is enabled only while the plot has left its home range. */
function syncResetZoom() {
  const now = liveRanges(refs.gd);
  const atHome = !refs.home || !now || (sameRange(now.x, refs.home.x) && sameRange(now.y, refs.home.y));
  refs.resetZoom.setAttribute('aria-disabled', String(atHome));
}

function resetToHome() {
  if (refs.resetZoom.getAttribute('aria-disabled') === 'true' || !refs.home) return;
  window.Plotly.relayout(refs.gd, {
    'xaxis.range': [...refs.home.x],
    'yaxis.range': [...refs.home.y],
  });
}

const ALL_CATS = EXCLUSIVE_CATEGORIES.map((c) => c.key);

/** One delegated chip listener (D-15); chips are rebuilt each render. */
function bindLegend() {
  const { ctx, chips } = refs;
  const detector = createOnlyDetector({
    onToggle: (key) => {
      if (hiddenCats.has(key)) hiddenCats.delete(key);
      else hiddenCats.add(key);
      ctx.setState({});
    },
    onOnly: (key, before) => {
      const prior = new Set(before || []);
      const wasOnly = ALL_CATS.every((k) => (k === key ? !prior.has(k) : prior.has(k)));
      hiddenCats.clear();
      if (!wasOnly) for (const k of ALL_CATS) if (k !== key) hiddenCats.add(k);
      ctx.setState({});
    },
    snapshot: () => [...hiddenCats],
  });
  chips.addEventListener('click', (ev) => {
    const button = ev.target.closest('button[data-category]');
    if (!button) {
      detector.reset();
      return;
    }
    detector.click(ev, button.dataset.category);
  });
}

function renderLegend(th, state) {
  const { chips } = refs;
  const shown = ALL_CATS.filter((k) => !hiddenCats.has(k));
  const items = EXCLUSIVE_CATEGORIES.map((cat) => {
    const color = categoryColor(cat.key, th);
    const b = el('button', 'legend-chip pill', cat.label);
    b.type = 'button';
    b.dataset.category = cat.key;
    const on = !hiddenCats.has(cat.key);
    b.setAttribute('aria-pressed', String(on));
    const hint = shown.length === 1 && shown[0] === cat.key
      ? 'Double-click to show all'
      : `Double-click to show only ${cat.label}`;
    b.title = hint;
    b.setAttribute('aria-description', hint);
    if (on) {
      b.style.backgroundColor = color;
      b.style.color = textOn(color);
      b.style.borderColor = '';
    } else {
      b.style.backgroundColor = '';
      b.style.color = '';
      b.style.borderColor = color;
    }
    const li = document.createElement('li');
    li.appendChild(b);
    return li;
  });
  pressGroup(refs.dotsGroup, state.dots);
  chips.replaceChildren(...items);
}

function renderCaptions() {
  const { ctx, captions } = refs;
  for (const old of captions.querySelectorAll('p.caption')) old.remove();
  const viewers = el('p', 'caption');
  viewers.append(
    document.createTextNode('Viewers are window-level where marked and unnormalized; see '),
    link('methodology', ctx.methodologyHref('nfl-window-level-viewership')),
    document.createTextNode('.'),
  );
  const excitement = el('p', 'caption');
  excitement.append(
    document.createTextNode('NFL excitement is GEI-style, built from win probability. It is not CFBD’s excitementIndex; see '),
    link('methodology', ctx.methodologyHref('nfl-gei-style-excitement')),
    document.createTextNode('.'),
  );
  captions.prepend(viewers, excitement);
}

function fillBandNote() {
  const { ctx } = refs;
  const v = refs.noteViewers;
  v.append(
    el('p', 'band-note-title', 'No public rating'),
    el(
      'p',
      null,
      'We found no published viewer count for these games. The reason is shown for each game. The most common ones:',
    ),
  );
  const ul = el('ul');
  for (const t of [
    'Ratings Reference compiles national windows, not every regional game.',
    'The figure is not posted yet. This is for the newest games of the current season.',
    'No figure was published.',
  ]) ul.appendChild(el('li', null, t));
  const vp = el('p');
  vp.appendChild(link('How we count games', ctx.methodologyHref('nfl-games-with-no-public-rating')));
  v.append(ul, vp);
  const x = refs.noteExcitement;
  const xp = el('p');
  xp.appendChild(link('How the Y axis works', ctx.methodologyHref('nfl-gei-style-excitement')));
  x.append(
    el('p', 'band-note-title', 'No excitement value'),
    el(
      'p',
      null,
      'No win-probability data exists for these games, so they have no height on this chart. They are drawn here instead of being left out. Their viewer figures are unchanged.',
    ),
    xp,
  );
}

function renderDataTable(items, model) {
  rebuildKeepingFocus(refs.dataBody, () => {
    const frag = document.createDocumentFragment();
    for (const it of items) {
      const row = gameRow(model, it.i);
      const tr = el('tr');
      const matchup = `${row.away} at ${row.home}`;
      const th = el('th', null, matchup);
      th.scope = 'row';
      // A keyboard path to the detail panel, as a click on a dot gives (JS-WR-04).
      // Faded dots are not clickable, so their rows get no button either.
      const action = el('td');
      if (it.pass) {
        const btn = el('button', null, 'Details');
        btn.type = 'button';
        btn.dataset.key = String(it.i);
        btn.setAttribute('aria-label', `Details: ${matchup}, ${dateShortText(row)}`);
        action.appendChild(btn);
      }
      tr.append(
        th,
        el('td', null, dateShortText(row)),
        el('td', null, it.cat.label),
        el('td', null, viewersText(row) ?? 'not available'),
        el('td', null, row.excitement != null ? row.excitement.toFixed(1) : 'not available'),
        el('td', null, row.awayPoints != null && row.homePoints != null ? String(Math.abs(row.awayPoints - row.homePoints)) : 'not available'),
        action,
      );
      frag.appendChild(tr);
    }
    refs.dataBody.replaceChildren(frag);
  });
  // One row per game: a single tab stop with arrow keys, not one per game.
  rovingRows(refs.dataBody);
}

function setEmpty(show) {
  refs.note.hidden = !show;
  refs.gd.hidden = show;
  if (show) {
    refs.bandButton.hidden = true;
    refs.bandNote.hidden = true;
  }
}

function placeBandInfo() {
  if (!refs.drawn || refs.bandButton.hidden) return;
  positionBandInfo(refs.gd, refs.bandButton, refs.bandNote);
}

// ---- figure ----

function niceStep(range, target) {
  const rough = range / Math.max(target - 1, 1);
  const mag = 10 ** Math.floor(Math.log10(rough));
  const norm = rough / mag;
  return (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10) * mag;
}

function yAxisFor(model, yKey) {
  const c = model.cols;
  let lo = Infinity;
  let hi = -Infinity;
  const col = yKey === 'viewers' ? c.viewers : c.excitement;
  for (let i = 0; i < model.n; i++) {
    const v = col[i];
    if (v == null) continue;
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  if (yKey === 'viewers') {
    if (!(hi > 0)) return { type: 'log', range: [Math.log10(5e5), Math.log10(2e7)], tickvals: VIEWER_TICKS.map((t) => t[0]), ticktext: VIEWER_TICKS.map((t) => t[1]) };
    let ticks = VIEWER_TICKS.filter(([v]) => v >= lo / 1.5 && v <= hi * 1.5);
    if (ticks.length < 2) ticks = VIEWER_TICKS;
    return {
      type: 'log',
      range: [Math.log10(lo / 1.4), Math.log10(hi * 1.4)],
      tickvals: ticks.map((t) => t[0]),
      ticktext: ticks.map((t) => t[1]),
    };
  }
  if (!(hi >= lo)) return { type: 'linear', range: [0, 1], tickvals: [0, 0.5, 1], ticktext: ['0', '0.5', '1'] };
  const pad = (hi - lo || 1) * 0.1;
  const range = [lo - pad, hi + pad];
  const step = niceStep(range[1] - range[0], 6);
  const tickvals = [];
  for (let v = Math.ceil(range[0] / step) * step; v <= range[1] + step * 1e-9; v += step) {
    tickvals.push(Math.round(v * 1e6) / 1e6);
  }
  return { type: 'linear', range, tickvals, ticktext: tickvals.map((v) => String(v)) };
}

function dateXAxis(model, state, env, th, plotPx) {
  const { axis } = dateGeometry(model);
  const blocks = shownBlocks(axis, state.seasons);
  const use = blocks.length ? blocks : axis.blocks;
  const range = blocks.length ? seasonRange(axis, state.seasons) : [0, 1];
  const [lo, hi] = range;
  const ppd = plotPx / Math.max(hi - lo, 1);
  const tickvals = [];
  const ticktext = [];
  if (ppd * 30 >= 30) {
    for (const b of use) {
      for (let day = b.minDay; day <= b.maxDay; day++) {
        const dt = new Date(day * 86400000);
        if (dt.getUTCDate() !== 1) continue;
        tickvals.push(b.start + axis.pad + (day - b.minDay));
        ticktext.push(MONTHS[dt.getUTCMonth()]);
      }
    }
  }
  const shapes = gapDividers(use).map((x) => ({
    type: 'line', xref: 'x', yref: 'paper', x0: x, x1: x, y0: 0, y1: 1, layer: 'below',
    line: { color: DIVIDER[th], width: 1 },
  }));
  const annotations = [];
  const wide = (plotPx / Math.max(use.length, 1)) >= 44;
  for (const b of use) {
    annotations.push({
      xref: 'x', yref: 'paper', x: (b.start + b.end) / 2, y: 0, yanchor: 'top', yshift: -36,
      showarrow: false, font: { size: 12, color: MUTED[th] },
      text: wide ? String(b.season) : `'${String(b.season).slice(-2)}`,
    });
  }
  // Nielsen-era bands over whole seasons (alternating fills, label top-left).
  const eras = seasonEras(model);
  const merged = [];
  use.forEach((b, k) => {
    const era = eras.get(b.season);
    if (era == null) return;
    const x0 = k === 0 ? b.start : (use[k - 1].end + b.start) / 2;
    const x1 = k === use.length - 1 ? b.end : (b.end + use[k + 1].start) / 2;
    const last = merged[merged.length - 1];
    if (last && last.era === era && last.lastIdx === k - 1) {
      last.x1 = x1;
      last.lastIdx = k;
    } else merged.push({ era, x0, x1, lastIdx: k });
  });
  const places = placeEraLabels(
    merged.map((band) => ({ text: model.eras[band.era].label, x0: band.x0 })),
    range, plotPx, 12,
  );
  merged.forEach((band, k) => {
    if (k % 2 === 0) {
      shapes.push({
        type: 'rect', xref: 'x', yref: 'paper', x0: band.x0, x1: band.x1, y0: 0, y1: 1,
        fillcolor: BAND_FILL[th], line: { width: 0 }, layer: 'below',
      });
    }
    const pos = places[k];
    if (!pos) return;
    annotations.push({
      xref: 'x', yref: 'paper', x: pos.x, y: 1, xanchor: pos.xanchor, yanchor: 'top',
      xshift: pos.xshift, yshift: -2, showarrow: false, align: pos.xanchor,
      text: escapeHover(pos.text),
      font: { size: 12, color: MUTED[th] },
    });
  });
  return {
    xaxis: {
      range, tickmode: 'array', tickvals, ticktext, ticks: 'outside', ticklen: 4,
      tickcolor: ZERO_LINE[th], tickangle: 0, tickfont: { size: 12, color: MUTED[th] },
      showgrid: false, zeroline: false, fixedrange: true, anchor: 'y2',
    },
    shapes,
    annotations,
    eraLabels: merged.map((band) => model.eras[band.era].label),
  };
}

function marginXAxis(model, th, env) {
  const c = model.cols;
  let hi = 0;
  for (let i = 0; i < model.n; i++) if (c.final_margin[i] != null) hi = Math.max(hi, Math.abs(c.final_margin[i]));
  const top = Math.max(hi + 1, 10);
  const step = niceStep(top, 6);
  const tickvals = [];
  for (let v = 0; v <= top; v += step) tickvals.push(v);
  return {
    xaxis: {
      title: { text: X_TITLE_MARGIN, standoff: 8 },
      range: [-4, top], tickmode: 'array', tickvals, ticktext: tickvals.map(String),
      tickfont: { color: MUTED[th] }, gridcolor: DIVIDER[th], zeroline: false, fixedrange: true, anchor: 'y2',
    },
    shapes: [{
      type: 'line', xref: 'x', yref: 'paper', x0: NA_EDGE, x1: NA_EDGE, y0: 0, y1: 1, layer: 'below',
      line: { color: DIVIDER[th], width: 1 },
    }],
    annotations: [{
      xref: 'x', yref: 'paper', x: NA_X, y: 1, xanchor: 'center', yanchor: 'top', yshift: -2,
      showarrow: false, text: 'N/A', font: { size: 12, color: MUTED[th] },
    }],
  };
}

function buildFigure(model, state, env, th, items) {
  const bg = PAGE_BG[th];
  const height = env.mobile ? 440 : 520;
  const margin = MARGIN;
  const fontPx = env.mobile ? TICK_FONT_PX.mobile : TICK_FONT_PX.desktop;
  const plotH = height - margin.t - margin.b;
  const bandGeo = bandLayout(plotH);
  const plotW = Math.max((refs.chart.clientWidth || (env.mobile ? 360 : 1100)) - margin.l - margin.r, 100);
  const isDate = state.scatterX === 'date';
  const yAxis = yAxisFor(model, state.scatterY);
  const xPart = isDate ? dateXAxis(model, state, env, th, plotW) : marginXAxis(model, th, env);

  const build = (subset, yFn, yaxis) => ({
    type: 'scatter',
    mode: 'markers',
    x: subset.map((it) => it.x),
    y: subset.map(yFn),
    yaxis,
    customdata: subset.map((it) => it.i),
    hoverinfo: 'none',
    showlegend: false,
    marker: {
      // Other games share the grey of Other solo slot (#8C8C8C / #999999), so they draw
      // hollow and never read as that segment (UI-SPEC Color).
      symbol: subset.map((it) => (it.cat.key === 'none' ? 'circle-open' : 'circle')),
      size: subset.map((it) => (it.highlight ? HIGHLIGHT_SIZE : BASE_SIZE)),
      color: subset.map((it) => categoryColor(it.cat.key, th)),
      opacity: subset.map((it) => (it.pass ? 1 : DOT_OPACITY.inertUnderPerson)),
      line: {
        width: subset.map((it) => (it.highlight ? 1.5 : it.cat.key === 'none' ? 1.5 : 0)),
        color: subset.map((it) => (it.highlight ? ACCENT[th] : categoryColor(it.cat.key, th))),
      },
    },
  });
  const main = items.filter((it) => !it.band);
  const band = items.filter((it) => it.band);
  const traces = [build(main, (it) => it.y, 'y'), build(band, (it) => bandY(it.i), 'y2')];

  const layout = {
    hovermode: 'closest',
    clickmode: 'event',
    dragmode: false,
    height,
    margin,
    annotations: xPart.annotations,
    shapes: xPart.shapes,
    xaxis: xPart.xaxis,
    yaxis: {
      domain: [bandGeo.logBottom, 1],
      type: yAxis.type,
      title: { text: Y_TITLES[state.scatterY], standoff: 8 },
      range: yAxis.range,
      tickmode: 'array',
      tickvals: yAxis.tickvals,
      ticktext: yAxis.ticktext,
      tickfont: { color: MUTED[th], size: fontPx },
      gridcolor: DIVIDER[th],
      zeroline: false,
      fixedrange: true,
    },
    yaxis2: {
      domain: [0, bandGeo.bandTop],
      range: bandGeo.y2range,
      anchor: 'x',
      fixedrange: true,
      showticklabels: false,
      showgrid: false,
      zeroline: false,
    },
  };
  return { traces, layout: frameLayout(layout, { theme: th }), yAxis, eraLabels: xPart.eraLabels || [] };
}

// ---- contract ----

export function mount(container, ctx) {
  refs.ctx = ctx;
  refs.legend = el('div', 'legend-row');
  refs.chips = el('ul', 'legend-chips');
  refs.chips.setAttribute('aria-label', 'Game categories: select to show or hide');
  refs.controls = el('div', 'chart-controls');
  buildControls();
  refs.legend.append(refs.chips, refs.dotsToggle);
  bindLegend();
  refs.chart = el('div', 'nfl-chart');
  refs.gd = el('div');
  refs.note = el('div', 'season-empty-note');
  refs.note.setAttribute('role', 'status');
  refs.note.hidden = true;
  refs.note.append(
    el('p', 'season-empty-title', 'No NFL games match.'),
    el('p', 'season-empty-hint', 'Widen the season range or reset the filters.'),
  );
  refs.bandButton = el('button', 'band-info');
  refs.bandButton.type = 'button';
  refs.bandButton.hidden = true;
  refs.bandButton.setAttribute('aria-expanded', 'false');
  refs.bandText = el('span', 'band-info-text', 'No public rating');
  const glyph = el('span', 'band-info-glyph', 'i');
  glyph.setAttribute('aria-hidden', 'true');
  refs.bandButton.append(refs.bandText, glyph);
  refs.bandNote = el('div', 'band-note');
  refs.bandNote.hidden = true;
  refs.noteViewers = el('div');
  refs.noteExcitement = el('div');
  refs.noteExcitement.hidden = true;
  refs.bandNote.append(refs.noteViewers, refs.noteExcitement);
  fillBandNote();
  refs.bandButton.setAttribute('aria-controls', 'nfl-scatter-band-note');
  refs.bandNote.id = 'nfl-scatter-band-note';
  initBandInfo({ button: refs.bandButton, note: refs.bandNote });
  refs.chart.append(refs.gd, refs.note, refs.bandButton, refs.bandNote);
  refs.captions = el('div');
  const dataWrap = el('div', DATA_TABLE_CLASS);
  const dataTable = el('table');
  dataTable.appendChild(el('caption', null, 'Game scatter'));
  const thead = el('thead');
  const hr = el('tr');
  for (const h of ['Matchup', 'Date', 'Category', 'Viewers', 'Excitement', 'Final margin', 'Details']) {
    const th = el('th', null, h);
    th.scope = 'col';
    hr.appendChild(th);
  }
  thead.appendChild(hr);
  refs.dataBody = el('tbody');
  refs.dataBody.addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-key]');
    if (btn) pickGame(Number(btn.dataset.key), true);
  });
  dataTable.append(thead, refs.dataBody);
  dataWrap.appendChild(dataTable);
  container.append(refs.legend, refs.chart, refs.captions, dataWrap);
  mountViewTools(ctx, 'scatter', [refs.controls], container);
}

export function render(ctx) {
  const model = ctx.model;
  const state = ctx.getState();
  const env = ctx.env();
  const th = theme(env);
  hideTooltip();
  hideHoverRing();

  pressGroup(refs.yGroup, state.scatterY);
  pressGroup(refs.xGroup, state.scatterX);
  renderLegend(th, state);
  renderCaptions();

  const { items, counts, bandCauses } = buildItems(model, state);
  const byGame = new Map(items.map((it) => [it.i, it]));
  const excitement = state.scatterY === 'excitement';
  // Band label and note follow the Y mode; close the note when the mode changes.
  const mode = excitement ? 'excitement' : 'viewers';
  if (refs.bandButton.dataset.yMode && refs.bandButton.dataset.yMode !== mode) {
    closeBandNote({ button: refs.bandButton, note: refs.bandNote });
  }
  refs.bandButton.dataset.yMode = mode;
  refs.bandText.textContent = excitement ? 'No excitement value' : 'No public rating';
  refs.bandButton.setAttribute(
    'aria-label',
    excitement ? 'Why do some games have no excitement value?' : 'Why do some games have no public rating?',
  );
  refs.noteViewers.hidden = excitement;
  refs.noteExcitement.hidden = !excitement;

  current = { items, byGame, counts, bandCauses, env, model, state, axisTitles: null };
  renderDataTable(items, model);

  if (!items.length) {
    refs.drawn = false;
    setEmpty(true);
    return;
  }
  setEmpty(false);
  const fig = buildFigure(model, state, env, th, items);
  current.axisTitles = {
    x: state.scatterX === 'margin' ? X_TITLE_MARGIN : null,
    y: Y_TITLES[state.scatterY],
  };
  current.fig = { yType: fig.yAxis.type };
  refs.bandButton.hidden = counts.band === 0;
  if (counts.band === 0) closeBandNote({ button: refs.bandButton, note: refs.bandNote });
  refs.drawn = true;
  setEraCaption(refs.captions, fig.eraLabels, env.mobile);
  const done = window.Plotly.react(refs.gd, fig.traces, fig.layout, CONFIG);
  bindEvents(refs.gd);
  if (done && typeof done.then === 'function') {
    done.then(() => {
      placeBandInfo();
      refs.home = liveRanges(refs.gd);
      syncResetZoom();
    });
  }
}

export function resize() {
  if (refs.drawn && refs.gd && window.Plotly && refs.gd.data) {
    window.Plotly.Plots.resize(refs.gd);
    placeBandInfo();
  }
}

export function testModel() {
  const s = refs.ctx ? refs.ctx.getState() : null;
  const x = s ? s.scatterX : 'date';
  const y = s ? s.scatterY : 'viewers';
  if (!current || !refs.drawn) {
    return {
      view: 'scatter', drawn: false, x, y,
      counts: { plotted: 0, band: 0, faded: 0, hidden: 0, highlighted: 0 },
      bandCauses: { pending: 0, regional: 0, none: 0 },
      axisTitles: null, dateAxis: 'reused', items: [],
    };
  }
  const { items, counts, bandCauses, axisTitles } = current;
  return {
    view: 'scatter',
    drawn: true,
    x,
    y,
    counts: { ...counts },
    bandCauses: { ...bandCauses },
    axisTitles,
    dateAxis: 'reused',
    yType: current.fig.yType,
    bandLabel: refs.bandText.textContent,
    hiddenCategories: [...hiddenCats],
    items: items.map((it) => ({
      i: it.i, band: it.band, na: it.na, faded: !it.pass, highlighted: it.highlight, category: it.cat.key,
    })),
  };
}
