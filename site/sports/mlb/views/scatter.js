/**
 * MLB view 3: Scatter (D-04..D-10). MLB-only: the NFL scatter helpers it needs are copied, not imported.
 *
 * One svg `scatter` dot per game; the Season type / Round control fades the games outside it. X is
 * Retrosheet excitement (linear), Y is viewers (log). A game with no public rating sits
 * in the bottom strip, a game with a rating but no excitement in the 72px left strip,
 * and a game with neither in the corner where the strips meet, so no game is dropped and
 * a missing value is never drawn at 0. Dots are coloured by network family; window-scope
 * figures draw as open dots. Game data never reaches Plotly as text: `customdata` holds
 * game indexes only, hover is off, and every label here is a fixed string set with
 * textContent.
 */
import { FAMILY_COLORS, MUTED, PAGE_BG, DIVIDER, INK } from '../../../modules/palette.js';
import { showTextTooltip, hideTooltip } from '../../../modules/tooltip.js';
import {
  showHoverRing, hideHoverRing, ringSpecFromPoint, hoverRingDiameter,
} from '../../../modules/hover-ring.js';
import { createOnlyDetector } from '../../../modules/legend.js';
import { formatAudienceShort } from '../../../modules/format.js';
import { frameConfig, frameLayout, referenceLine } from '../../../modules/chart-frame.js';
import { bandLayout, marginFor } from '../../../modules/chart.js';
import { initBandInfo, positionBandInfo, closeBandNote } from '../../../modules/band-info.js';
import { mountViewTools } from '../tools.js';
import { ROUND_LABELS, gameRow } from '../data.js';
import { dateShortText } from '../format.js';
import { MLB_SROUNDS } from '../state.js';
import { RETROSHEET_NOTICE, RETROSHEET_CONTACT } from '../panel.js';
import {
  buildScatterItems, colorSlotOf, statusText, stripJitter, MLB_FAMILY_ORDER, MLB_FAMILY_LABELS,
  SEASON_TYPE_HIGHLIGHTS,
} from '../scatter-items.js';

const CONFIG = frameConfig({ zoomable: true });

const VIEWER_TICKS = [
  [5e5, '500K'], [1e6, '1M'], [2e6, '2M'], [5e6, '5M'], [1e7, '10M'], [2e7, '20M'],
];
const BASE_SIZE = 6;
const STRIP_PX = 72; // the left strip's width
const STRIP_GAP_PX = 8; // between the strip's divider and excitement 0
const EDGE_PAD_PX = 8; // right padding so a dot at the maximum is not clipped
const PLOT_HEIGHT = { desktop: 480, phone: 360 };

// Fixed copy (RT-29..RT-34); no data string is ever written into it.
const ROUND_DISABLED_TITLE = 'Round applies to postseason games';
const NOTE_BOTTOM = 'No viewership figure for these games: Ratings Reference has none, the figure is not posted yet, or it is window-level only.';
const NOTE_LEFT = "Retrosheet's 2026 files are released late in 2026, and some older games have no play-by-play.";
const CAPTION_VIEWERS = "Viewership figures: Ratings Reference; each game's detail panel links its record and the figure's original source. Open dots are window-level: one figure covers the whole broadcast window, not this game alone.";
const CAPTION_NETWORKS = "Networks: 506 Sports and Wikipedia (CC BY-SA 4.0); each game's detail panel links its source.";
// The real MLB eras break at the same years as CFB's (2020, 2025, 2026), so the CFB era
// note (RT-21) is used as written (checked against the local build, 16-07).
const CAPTION_ERAS = 'Nielsen changed how it measures viewing in 2020, 2025, and 2026, so compare seasons with care; see ';

const FADED_OPACITY = 0.32; // unmatched dots under a selection (D-07)
const OUTLINE_PX = 1.5; // matched dots under a selection get an ink outline
const TAP_DEBOUNCE_MS = 500; // one physical tap can reach Plotly twice
const TAP_HINT = 'Tap again to open this game';
const hiddenFamilies = new Set(); // families toggled off by their legend chips

const STYPE_OPTIONS = [
  { key: 'all', label: 'All games' },
  { key: 'post', label: 'Postseason' },
  { key: 'reg', label: 'Reg. Season' },
];

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

const refs = {
  ctx: null,
  controls: null,
  chart: null,
  gd: null,
  note: null,
  status: null,
  drawn: false,
  bound: false,
  home: null,
  homeKey: null,
  lastWidth: 0,
  legend: null,
  chips: null,
  resetZoom: null,
};

let pendingTap = null; // touch: the game whose tooltip the first tap showed
let lastTapAt = -Infinity;
let lastClick = { i: null, at: -Infinity };

let current = null; // what the last render drew

function theme(env) {
  return env.dark ? 'dark' : 'light';
}

function familyColor(family, th) {
  return FAMILY_COLORS[th][colorSlotOf(family)];
}

// ---- axes ----

/** Viewers axis from the rated items: log range padded 25%, ticks that fall inside it. */
function yAxisFor(items) {
  let lo = Infinity;
  let hi = -Infinity;
  for (const it of items) {
    if (it.x == null) continue;
    if (it.x < lo) lo = it.x;
    if (it.x > hi) hi = it.x;
  }
  const all = { tickvals: VIEWER_TICKS.map((t) => t[0]), ticktext: VIEWER_TICKS.map((t) => t[1]) };
  if (!(hi > 0)) return { range: [Math.log10(5e5), Math.log10(2e7)], ...all };
  const rLo = lo / 1.25;
  const rHi = hi * 1.25;
  const ticks = VIEWER_TICKS.filter(([v]) => v >= rLo && v <= rHi);
  if (ticks.length >= 2) {
    return {
      range: [Math.log10(rLo), Math.log10(rHi)],
      tickvals: ticks.map((t) => t[0]),
      ticktext: ticks.map((t) => t[1]),
    };
  }
  return { range: [Math.log10(Math.min(rLo, 5e5)), Math.log10(Math.max(rHi, 2e7))], ...all };
}

function tickText(v) {
  return Number.isInteger(v) ? String(v) : v.toFixed(1);
}

/** X geometry: excitement 0..xHi on the main plot, the 72px strip at negative x. */
function xGeometry(items, plotW) {
  let top = 0;
  for (const it of items) if (it.y != null && it.y > top) top = it.y;
  const xHi = top > 0 ? Math.ceil(top * 2) / 2 : 1;
  const mainPx = Math.max(plotW - STRIP_PX - STRIP_GAP_PX - EDGE_PAD_PX, 120);
  const scale = xHi / mainPx;
  const step = xHi < 4 ? 0.5 : 1;
  const tickvals = [];
  for (let v = 0; v <= xHi + 1e-9; v += step) tickvals.push(Math.round(v * 1e6) / 1e6);
  return {
    xHi,
    scale,
    lo: -(STRIP_PX + STRIP_GAP_PX) * scale,
    edge: -STRIP_GAP_PX * scale,
    hi: xHi + EDGE_PAD_PX * scale,
    tickvals,
    ticktext: tickvals.map(tickText),
  };
}

/** Deterministic x inside the left strip (12..60px of its 72px) for a game with no excitement.
 * A corner game (neither figure) also takes its y from `stripJitter(i)`, so its x uses a second,
 * independent sequence; reusing `stripJitter(i)` for both drew the corner as one diagonal line. */
function stripX(geo, i, corner = false) {
  const j = corner ? (i * 0.7548776662) % 1 : (stripJitter(i) - 0.12) / 0.76;
  return geo.lo + geo.scale * (12 + j * 48);
}

// ---- figure ----

function buildFigure(items, env, th) {
  const height = env.mobile ? PLOT_HEIGHT.phone : PLOT_HEIGHT.desktop;
  const margin = marginFor(env.mobile);
  const plotH = height - margin.t - margin.b;
  const bandGeo = bandLayout(plotH);
  const plotW = Math.max((refs.chart.clientWidth || (env.mobile ? 360 : 1100)) - margin.l - margin.r, 200);
  const yAxis = yAxisFor(items);
  const geo = xGeometry(items, plotW);
  const bg = PAGE_BG[th];

  const traces = [];
  const present = MLB_FAMILY_ORDER.filter((f) => items.some((it) => it.family === f));
  const coords = (it) => {
    const left = it.place === 'left' || it.place === 'corner';
    const strip = it.place === 'bottom' || it.place === 'corner';
    return {
      x: left ? stripX(geo, it.i, it.place === 'corner') : it.y,
      y: strip ? stripJitter(it.i) : it.x,
    };
  };
  const build = (family, rawSubset, yaxis) => {
    const color = familyColor(family, th);
    // Faded dots draw first, matched dots last, so highlighted games sit on top.
    const rank = (it) => (it.faded ? 0 : it.matched ? 2 : 1);
    const subset = [0, 1, 2].flatMap((r) => rawSubset.filter((it) => rank(it) === r));
    const pts = subset.map(coords);
    return {
      type: 'scatter',
      mode: 'markers',
      meta: family,
      x: pts.map((p) => p.x),
      y: pts.map((p) => p.y),
      yaxis,
      customdata: subset.map((it) => it.i),
      hoverinfo: 'none',
      showlegend: false,
      marker: {
        symbol: 'circle',
        size: subset.map(() => BASE_SIZE),
        // Window-scope figures cover a whole broadcast window: open dots, page-colour fill.
        color: subset.map((it) => (it.window ? bg : color)),
        opacity: subset.map((it) => (it.faded ? FADED_OPACITY : 1)),
        line: {
          width: subset.map((it) => (it.matched || it.window ? OUTLINE_PX : 0)),
          color: subset.map((it) => (it.matched ? INK[th] : color)),
        },
      },
    };
  };
  for (const family of present) {
    const mine = items.filter((it) => it.family === family && !it.hidden);
    const main = mine.filter((it) => it.place === 'plot' || it.place === 'left');
    const strip = mine.filter((it) => it.place === 'bottom' || it.place === 'corner');
    if (main.length) traces.push(build(family, main, 'y'));
    if (strip.length) traces.push(build(family, strip, 'y2'));
  }

  const zoomable = !env.mobile;
  const layout = {
    hovermode: 'closest',
    clickmode: 'event',
    dragmode: zoomable ? 'zoom' : false,
    height,
    margin,
    annotations: [],
    shapes: [referenceLine({ xref: 'x', yref: 'paper', x0: geo.edge, x1: geo.edge, y0: 0, y1: 1 }, th)],
    xaxis: {
      title: { text: 'Excitement', standoff: 8 },
      range: [geo.lo, geo.hi],
      tickmode: 'array',
      tickvals: geo.tickvals,
      ticktext: geo.ticktext,
      ticks: 'outside',
      ticklen: 4,
      tickfont: { color: MUTED[th] },
      showgrid: false,
      zeroline: false,
      anchor: 'y2',
      // Zoom is vertical only (viewers): the excitement axis shares the left strip, so zooming
      // it would scroll the strip out of view. Spike result, 16-07 (RESEARCH A3).
      fixedrange: true,
    },
    yaxis: {
      domain: [bandGeo.logBottom, 1],
      type: 'log',
      title: { text: 'Viewers', standoff: 8 },
      range: yAxis.range,
      tickmode: 'array',
      tickvals: yAxis.tickvals,
      ticktext: yAxis.ticktext,
      tickfont: { color: MUTED[th] },
      gridcolor: DIVIDER[th],
      zeroline: false,
      fixedrange: !zoomable,
      ...(zoomable ? { minallowed: yAxis.range[0], maxallowed: yAxis.range[1] } : {}),
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
  return { traces, layout: frameLayout(layout, { theme: th }), geo, yAxis, families: present };
}

function liveRanges(gd) {
  const full = gd && gd._fullLayout;
  if (!full || !full.xaxis || !full.yaxis) return null;
  return { x: [...full.xaxis.range], y: [...full.yaxis.range] };
}

function setEmpty(show) {
  refs.note.hidden = !show;
  refs.gd.hidden = show;
  if (show) {
    for (const info of [refs.bottomInfo, refs.leftInfo]) {
      info.button.hidden = true;
      closeBandNote(info);
    }
  }
}

/** A strip label that doubles as a 44px info button (the CFB band pattern). */
function stripInfo(className, label, ariaLabel, noteText) {
  const button = el('button', `band-info ${className}`);
  button.type = 'button';
  button.hidden = true;
  button.setAttribute('aria-label', ariaLabel);
  button.setAttribute('aria-expanded', 'false');
  const glyph = el('span', 'band-info-glyph', 'i');
  glyph.setAttribute('aria-hidden', 'true');
  button.append(el('span', 'band-info-text', label), glyph);
  const note = el('div', `band-note ${className.replace('info', 'note')}`);
  note.hidden = true;
  note.id = `${className}-note`;
  note.appendChild(el('p', null, noteText));
  button.setAttribute('aria-controls', note.id);
  initBandInfo({ button, note });
  return { button, note };
}

/** Bottom label in the gap row above the bottom strip; left label at the top of the left strip. */
function placeStripInfo() {
  if (!refs.drawn) return;
  const gd = refs.gd;
  const full = gd._fullLayout;
  if (!full || !full._size || !full.xaxis) return;
  if (!refs.bottomInfo.button.hidden) positionBandInfo(gd, refs.bottomInfo.button, refs.bottomInfo.note);
  const left = refs.leftInfo.button;
  if (!left.hidden) {
    const x = Math.round(full._size.l + 2);
    const y = Math.round(full._size.t + 2);
    left.style.left = `${x}px`;
    left.style.top = `${y}px`;
    const note = refs.leftInfo.note;
    const noteW = note.offsetWidth || 280;
    note.style.left = `${Math.round(Math.min(x, Math.max(0, gd.clientWidth - noteW - 4)))}px`;
    note.style.top = `${y + left.offsetHeight}px`;
  }
}

// ---- controls and captions ----

function segmented(label, options, onPick) {
  const group = el('div', 'segmented');
  group.setAttribute('role', 'group');
  group.setAttribute('aria-label', label);
  for (const o of options) {
    const b = el('button', null, o.label);
    b.type = 'button';
    b.dataset.value = o.key;
    b.addEventListener('click', () => onPick(o.key, b));
    group.appendChild(b);
  }
  return group;
}

function axisGroup(caption, group) {
  const wrap = el('div', 'axis-group');
  const cap = el('span', 'axis-caption', caption);
  cap.setAttribute('aria-hidden', 'true');
  wrap.append(cap, group);
  return wrap;
}

function presentRounds(model) {
  const seen = new Set(model.cols.round);
  return MLB_SROUNDS.filter((r) => seen.has(r));
}

function buildControls(ctx) {
  refs.stypeGroup = segmented('Season type', STYPE_OPTIONS, (k) => {
    ctx.setState(k === 'all' ? { stype: null, sround: null } : { stype: k });
  });
  const rounds = [{ key: 'all', label: 'All rounds' }, ...presentRounds(ctx.model).map((r) => ({ key: r, label: ROUND_LABELS[r] }))];
  refs.roundGroup = segmented('Round', rounds, (k, b) => {
    if (b.getAttribute('aria-disabled') === 'true') return;
    ctx.setState({ sround: k === 'all' ? null : k });
  });
  const wrap = el('div', 'scatter-controls');
  wrap.append(axisGroup('Season type', refs.stypeGroup), axisGroup('Round', refs.roundGroup));
  refs.controls.appendChild(wrap);
}

function press(group, value) {
  for (const b of group.querySelectorAll('button')) {
    b.setAttribute('aria-pressed', String(b.dataset.value === value));
  }
}

/** Pressed state, and the Round group's disabled look (no reflow: the buttons stay). */
function syncControls(state) {
  press(refs.stypeGroup, state.stype ?? 'all');
  const post = state.stype === 'post';
  press(refs.roundGroup, post ? state.sround ?? 'all' : 'all');
  for (const b of refs.roundGroup.querySelectorAll('button')) {
    if (post) {
      b.removeAttribute('aria-disabled');
      b.removeAttribute('title');
    } else {
      b.setAttribute('aria-disabled', 'true');
      b.title = ROUND_DISABLED_TITLE;
    }
  }
}

function link(text, href) {
  const a = el('a', null, text);
  a.href = href;
  a.rel = 'noopener noreferrer';
  return a;
}

/** Captions 1-3 always (Retrosheet, Ratings Reference, networks); caption 4 with more than one era. */
function buildCaptions(ctx) {
  const retro = el('p', 'caption');
  retro.append(
    document.createTextNode(`${RETROSHEET_NOTICE} ${RETROSHEET_CONTACT}`),
    link('www.retrosheet.org', 'https://www.retrosheet.org'),
  );
  const lines = [retro, el('p', 'caption', CAPTION_VIEWERS), el('p', 'caption', CAPTION_NETWORKS)];
  if (ctx.model.lookups.eras.length > 1) {
    const eras = el('p', 'caption');
    eras.append(
      document.createTextNode(CAPTION_ERAS),
      link('methodology', ctx.methodologyHref('measurement-eras')),
      document.createTextNode('.'),
    );
    lines.push(eras);
  }
  return lines;
}

function itemFor(ev) {
  const pt = ev.points && ev.points[0] ? ev.points[0] : null;
  const k = pt ? pt.customdata : null;
  if (!current || !Number.isInteger(k)) return null;
  return current.byGame.get(k) || null;
}

/**
 * The dot's client-pixel position, for the hover ring (copied from the NFL scatter). The
 * point math reaches into undocumented Plotly internals, so it falls back to the event's
 * own coordinates if a vendored version drops any of them.
 */
function pointClientPosition(gd, ev) {
  const point = ev.points && ev.points[0];
  let clientX;
  let clientY;
  try {
    if (point && point.x != null && point.y != null && gd._fullLayout) {
      const layout = gd._fullLayout;
      const rect = gd.getBoundingClientRect();
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

function excitementText(row) {
  if (row.excitement != null) return `Excitement ${row.excitement.toFixed(1)}`;
  // Pending follows Retrosheet's freshness, as the Postseason grid does; the year is the game's.
  return row.retrosheetPending ? `Excitement pending Retrosheet ${row.season}` : 'Excitement not available';
}

/** Tooltip lines (D-05): logo, matchup and date, then the viewers and excitement line. */
function hoverLines(model, i, hint) {
  const row = gameRow(model, i);
  const lines = [];
  if (row.network) {
    lines.push({ kind: 'network', network: { id: row.networkId, name: row.network, family: row.networkFamily } });
  }
  lines.push({ text: `${row.away} at ${row.home} · ${dateShortText(row)}`, kind: 'title' });
  let viewers = 'No public rating';
  if (row.viewers != null) {
    viewers = `${formatAudienceShort(row.viewers)} viewers${row.scope === 'window' ? ', whole window' : ''}`;
  }
  lines.push({ text: `${viewers} · ${excitementText(row)}`, kind: 'body' });
  if (hint) lines.push({ text: hint, kind: 'hint' });
  return lines;
}

function showTip(ev, it, hint) {
  const th = theme(current.env);
  const at = pointClientPosition(refs.gd, ev);
  const e = ev.event || {};
  showTextTooltip(hoverLines(current.model, it.i, hint), {
    theme: th,
    borderColor: familyColor(it.family, th),
    clientX: hint ? at.clientX ?? e.clientX ?? 0 : e.clientX ?? at.clientX ?? 0,
    clientY: hint ? at.clientY ?? e.clientY ?? 0 : e.clientY ?? at.clientY ?? 0,
  });
  if (Number.isFinite(at.clientX) && Number.isFinite(at.clientY)) {
    const spec = ringSpecFromPoint(ev.points[0]);
    showHoverRing({
      i: it.i, clientX: at.clientX, clientY: at.clientY, diameter: hoverRingDiameter(spec.size, spec.symbol),
    });
  }
}

function clearHover() {
  pendingTap = null;
  hideTooltip();
  hideHoverRing();
}

function openFrom(it) {
  clearHover();
  // The chart never sets a selection (Pitfall 9); it only opens the panel.
  refs.ctx.openGame(it.i, refs.gd);
}

function onClick(ev) {
  const it = itemFor(ev);
  if (!it) return;
  const now = performance.now();
  if (current.env.hoverNone || current.env.mobile) {
    // One tap reaches Plotly twice (touch, then the compatibility click): ignore the echo.
    if (now - lastTapAt < TAP_DEBOUNCE_MS) return;
    lastTapAt = now;
    if (pendingTap !== it.i) {
      pendingTap = it.i;
      showTip(ev, it, TAP_HINT);
      return;
    }
    openFrom(it);
    return;
  }
  if (lastClick.i === it.i && now - lastClick.at < TAP_DEBOUNCE_MS) return;
  lastClick = { i: it.i, at: now };
  openFrom(it);
}

/** Reset zoom is enabled only while the viewers axis has left its home range. */
function syncResetZoom() {
  const now = liveRanges(refs.gd);
  const home = refs.home;
  const atHome = !home || !now || (now.y[0] === home.y[0] && now.y[1] === home.y[1]);
  refs.resetZoom.setAttribute('aria-disabled', String(atHome));
}

function resetToHome() {
  if (refs.resetZoom.getAttribute('aria-disabled') === 'true' || !refs.home) return;
  window.Plotly.relayout(refs.gd, { 'yaxis.range': [...refs.home.y] });
}

function bindEvents(gd) {
  if (refs.bound) return;
  refs.bound = true;
  gd.on('plotly_afterplot', () => placeStripInfo());
  gd.on('plotly_relayout', () => {
    syncResetZoom();
    hideHoverRing();
  });
  gd.on('plotly_click', onClick);
  gd.on('plotly_hover', (ev) => {
    const it = itemFor(ev);
    if (!it || current.env.mobile || current.env.hoverNone) return;
    showTip(ev, it, null);
  });
  gd.on('plotly_unhover', () => {
    if (current && (current.env.mobile || current.env.hoverNone)) return;
    hideTooltip();
    hideHoverRing();
  });
}

// ---- legend chips (D-05; no Fade | Hide toggle on MLB, U-10) ----

function textOn(hex) {
  const lin = (v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  const n = parseInt(hex.slice(1), 16);
  const lum = 0.2126 * lin(n >> 16) + 0.7152 * lin((n >> 8) & 255) + 0.0722 * lin(n & 255);
  return 1.05 / (lum + 0.05) >= (lum + 0.05) / 0.05 ? '#FFFFFF' : '#111111';
}

/** One delegated chip listener; chips are rebuilt each render. */
function bindLegend() {
  const present = () => (current ? current.families : []);
  const detector = createOnlyDetector({
    onToggle: (key) => {
      if (hiddenFamilies.has(key)) hiddenFamilies.delete(key);
      else hiddenFamilies.add(key);
      refs.ctx.setState({});
    },
    onOnly: (key, before) => {
      const prior = new Set(before || []);
      const all = present();
      const wasOnly = all.every((k) => (k === key ? !prior.has(k) : prior.has(k)));
      hiddenFamilies.clear();
      if (!wasOnly) for (const k of all) if (k !== key) hiddenFamilies.add(k);
      refs.ctx.setState({});
    },
    snapshot: () => [...hiddenFamilies],
  });
  refs.chips.addEventListener('click', (ev) => {
    const button = ev.target.closest('button[data-family]');
    if (!button) {
      detector.reset();
      return;
    }
    detector.click(ev, button.dataset.family);
  });
}

function renderLegend(families, th) {
  const shown = families.filter((f) => !hiddenFamilies.has(f));
  const items = families.map((family) => {
    const label = MLB_FAMILY_LABELS[family];
    const color = familyColor(family, th);
    const b = el('button', 'legend-chip pill', label);
    b.type = 'button';
    b.dataset.family = family;
    const on = !hiddenFamilies.has(family);
    b.setAttribute('aria-pressed', String(on));
    const hint = shown.length === 1 && shown[0] === family
      ? 'Double-click to show all'
      : `Double-click to show only ${label}`;
    b.title = hint;
    b.setAttribute('aria-description', hint);
    if (on) {
      b.style.backgroundColor = color;
      b.style.color = textOn(color);
    } else {
      b.style.borderColor = color;
    }
    const li = document.createElement('li');
    li.appendChild(b);
    return li;
  });
  // A chip toggle re-renders the legend: keep keyboard focus on the same family's new chip.
  const active = document.activeElement;
  const focused = active && refs.chips.contains(active) ? active.dataset.family : null;
  refs.chips.replaceChildren(...items);
  if (focused) refs.chips.querySelector(`button[data-family="${CSS.escape(focused)}"]`)?.focus();
}

// ---- contract ----

export function mount(container, ctx) {
  refs.ctx = ctx;
  container.classList.add('mlb-scatter');
  refs.controls = el('div', 'chart-controls mlb-scatter-controls');
  refs.chart = el('div', 'nfl-chart mlb-scatter-plot');
  refs.gd = el('div');
  refs.gd.tabIndex = -1; // the panel's Escape returns focus here
  refs.note = el('div', 'season-empty-note');
  refs.note.setAttribute('role', 'status');
  refs.note.hidden = true;
  refs.note.append(
    el('p', 'season-empty-title', 'No games in this view'),
    el('p', 'season-empty-hint', 'Choose All games or another round.'),
  );
  refs.bottomInfo = stripInfo(
    'mlb-bottom-info', 'No public rating', 'Why do some games have no public rating?', NOTE_BOTTOM,
  );
  refs.leftInfo = stripInfo(
    'mlb-left-info', 'No excitement', 'Why do some games have no excitement figure?', NOTE_LEFT,
  );
  refs.chart.append(
    refs.gd, refs.note,
    refs.bottomInfo.button, refs.bottomInfo.note, refs.leftInfo.button, refs.leftInfo.note,
  );
  refs.status = el('p', 'mlb-scatter-status');
  refs.status.setAttribute('role', 'status');
  buildControls(ctx);
  refs.resetZoom = el('button', 'reset-zoom', 'Reset zoom');
  refs.resetZoom.type = 'button';
  refs.resetZoom.setAttribute('aria-disabled', 'true');
  refs.resetZoom.addEventListener('click', resetToHome);
  refs.controls.appendChild(refs.resetZoom);
  refs.legend = el('div', 'legend-row');
  refs.chips = el('ul', 'legend-chips');
  refs.chips.setAttribute('aria-label', 'Network families: select to show or hide');
  refs.legend.appendChild(refs.chips);
  bindLegend();
  document.addEventListener('pointerdown', (ev) => {
    if (pendingTap != null && !ev.target.closest('.mlb-scatter-plot')) clearHover();
  });
  container.append(refs.legend, refs.chart, refs.status, ...buildCaptions(ctx));
  mountViewTools(ctx, 'scatter', [refs.controls], container);
  // The strip is a fixed 72px, so a width change re-lays the figure out.
  if (typeof ResizeObserver !== 'undefined') {
    let frame = 0;
    new ResizeObserver(() => {
      const w = refs.chart.clientWidth;
      if (!refs.drawn || !w || Math.abs(w - refs.lastWidth) < 2) return;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => render(refs.ctx));
    }).observe(refs.chart);
  }
}

export function render(ctx) {
  const model = ctx.model;
  const state = ctx.getState();
  const env = ctx.env();
  const th = theme(env);
  clearHover();

  const built = buildScatterItems(model, state, { hiddenFamilies });
  const { items, counts, hidden, families } = built;
  current = { items, counts, families, env, model, state, byGame: new Map(items.map((it) => [it.i, it])) };
  renderLegend(families, th);
  refs.status.textContent = statusText(counts, hidden);
  syncControls(state);

  // The axes come from every game (the control only fades, U5), so the home range changes only
  // with phone vs desktop or the theme. Any other re-render (a control change, a dot click, the
  // panel closing, a legend chip, a width change) keeps a viewers-axis zoom, and the kept zoom
  // never becomes the new home. If Season type narrows again, it moves the home range too.
  const homeKey = JSON.stringify([SEASON_TYPE_HIGHLIGHTS ? null : state.stype ?? null, !!env.mobile, th]);
  const live = refs.drawn && refs.home && refs.homeKey === homeKey ? liveRanges(refs.gd) : null;
  const zoomed = !!live && (live.y[0] !== refs.home.y[0] || live.y[1] !== refs.home.y[1]);

  if (!items.length) {
    refs.drawn = false;
    refs.home = null;
    refs.homeKey = null;
    refs.resetZoom.setAttribute('aria-disabled', 'true');
    setEmpty(true);
    return;
  }
  setEmpty(false);
  const fig = buildFigure(items, env, th);
  if (zoomed) fig.layout.yaxis.range = [...live.y];
  current.fig = fig;
  refs.drawn = true;
  refs.lastWidth = refs.chart.clientWidth;
  refs.bottomInfo.button.hidden = counts.noRating + counts.neither === 0;
  if (refs.bottomInfo.button.hidden) closeBandNote(refs.bottomInfo);
  refs.leftInfo.button.hidden = counts.noExcitement + counts.neither === 0;
  if (refs.leftInfo.button.hidden) closeBandNote(refs.leftInfo);
  const done = window.Plotly.react(refs.gd, fig.traces, fig.layout, CONFIG);
  bindEvents(refs.gd);
  if (done && typeof done.then === 'function') {
    done.then(() => {
      placeStripInfo();
      if (!zoomed) refs.home = liveRanges(refs.gd);
      refs.homeKey = homeKey;
      syncResetZoom();
    });
  }
}

export function resize() {
  if (refs.drawn && refs.gd && window.Plotly && refs.gd.data) {
    render(refs.ctx);
    placeStripInfo();
  }
}

export function testModel() {
  if (!current || !refs.drawn) {
    return { view: 'scatter', drawn: false, counts: { total: 0, plotted: 0, noRating: 0, noExcitement: 0, neither: 0 }, families: [], status: refs.status ? refs.status.textContent : '' };
  }
  const { counts, families, fig } = current;
  return {
    view: 'scatter',
    drawn: true,
    counts: { ...counts },
    families: [...families],
    status: refs.status.textContent,
    yType: 'log',
    xRange: [...fig.layout.xaxis.range],
  };
}
