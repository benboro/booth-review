/**
 * This weekend map view (Phase 24, plan 07): the map body mounted inside the shared weekend
 * shell. Sport-neutral, like weekend-view.js: a host hands it a model and callbacks.
 *
 *   renderWeekendMap(host, model, opts) -> { destroy() }
 *   model, opts = weekend-view.js's (opts also takes `wview` and `onView`, which the shell reads).
 *
 * mountWeekend rebuilds its DOM on every render (RESEARCH Pitfall 2), so the Plotly node, the tap
 * controller and the splat layer live in a per-host closure and are re-attached, never recreated.
 * Calling renderWeekendMap again on the same host keeps that closure (the figure then updates in
 * place through Plotly.react); `destroy()` purges the node and revokes the splat URL.
 *
 * DOM safety (T-24-19): createElement, createElementNS, textContent and setAttribute only; no
 * markup-injecting API and no colour literal appears in this file. Plotly is touched only through
 * renderMap, bindMapEvents and Plotly.purge. No request is made by hover, click, tap or switch
 * (the geometry is the same-origin import the CFB Map already uses).
 */

import { PHONE_QUERY } from './breakpoints.js';
import { splatImageSpec, renderMap, bindMapEvents } from './map-chart.js';
import { paintSplat } from './map-splat.js';
import { createSplatLayer } from './map-splat-layer.js';
import { createTapController } from './map-tap.js';
import {
  FAMILY_LABELS,
  FAMILY_ORDER,
  MAP_FAMILY_COLORS,
  MAP_LAND,
  MAP_SPLAT,
  MAP_SPLAT_WEEKEND,
  MUTED,
  WEEKEND_MAP_DOT,
} from './palette.js';
import { hideTooltip, isInTooltip, showGameTooltip } from './tooltip.js';
import { dayLabel, stripCollapsedByDefault } from './weekend.js';
import { WINDOW_CAPTION, WINDOW_LABELS, WINDOW_SYMBOL, buildWeekendMapModel, windowOf } from './weekend-map.js';
import { WEEKEND_MAP_TRACE_NAMES, buildWeekendMapFigure } from './weekend-map-chart.js';
import { makeCaretIcon } from './icons.js';
import {
  applyPick,
  buildCell,
  buildCompactTable,
  buildSourceLine,
  buildStampLine,
  buildTbaStrip,
  el,
  mountWeekend,
} from './weekend-view.js';

const SVG_NS = 'http://www.w3.org/2000/svg';
const SPLAT_CAPTION = 'Shading shows which network has the most games nearby.';
const NONE_PLACED = "None of this day's games has a venue yet. They are listed below.";
const DRAW_FAILED = "The map could not be drawn. Switch to Timeline to see this day's games.";
const NOT_ON_MAP_NOTE = 'No venue is listed for these games yet.';

/** One closure per host, so the graph node survives the shell's rebuilds. */
const MOUNTS = new WeakMap();
let renderCount = 0;
let geometryPromise = null;

/** How many times a weekend map figure has been drawn with Plotly.react (test hook). */
export function weekendMapRenderCount() {
  return renderCount;
}

const hoverNone = () => window.matchMedia('(hover: none)').matches;
const isPhone = () => window.matchMedia(PHONE_QUERY).matches;

function loadGeometry() {
  if (!geometryPromise) {
    geometryPromise = import('../vendor/us-states-albers.js').then((m) => m.US_STATES).catch((err) => {
      // A failed import must not pin the failure: the next draw retries.
      geometryPromise = null;
      throw err;
    });
  }
  return geometryPromise;
}

/** Client coordinates of a Plotly event's source event (mouse, or the touch that landed). */
function pointOf(ev) {
  const src = ev?.event;
  const at = src?.changedTouches?.[0] ?? src?.touches?.[0] ?? src;
  return { x: at?.clientX ?? 0, y: at?.clientY ?? 0 };
}

// ---- The key ----

function svgEl(tag, attrs) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
  return node;
}

/** One window shape, drawn from the same symbol table the figure reads. */
function shapeSvg(symbol, size, color) {
  const d = Math.ceil(size) + 2;
  const c = d / 2;
  const r = size / 2;
  const svg = svgEl('svg', { width: d, height: d, viewBox: `0 0 ${d} ${d}`, 'aria-hidden': 'true', focusable: 'false' });
  if (symbol === 'circle') {
    svg.append(svgEl('circle', { cx: c, cy: c, r, fill: color }));
  } else if (symbol === 'square') {
    svg.append(svgEl('rect', { x: c - r, y: c - r, width: size, height: size, fill: color }));
  } else if (symbol === 'diamond') {
    svg.append(svgEl('polygon', { points: `${c},${c - r} ${c + r},${c} ${c},${c + r} ${c - r},${c}`, fill: color }));
  } else if (symbol === 'triangle-up') {
    svg.append(svgEl('polygon', { points: `${c},${c - r} ${c + r},${c + r} ${c - r},${c + r}`, fill: color }));
  } else {
    svg.append(svgEl('circle', {
      cx: c, cy: c, r: r - WEEKEND_MAP_DOT.tbaStroke / 2, fill: 'none', stroke: color,
      'stroke-width': WEEKEND_MAP_DOT.tbaStroke,
    }));
  }
  return svg;
}

/**
 * The key: Kickoff shapes and ranges, the static network colour row, and the shading caption
 * (hidden until a splat is scheduled). Only windows and families that occur that day show.
 */
function buildKey(ctx, placed) {
  const sport = ctx.model.sport === 'nfl' ? 'nfl' : 'cfb';
  const phone = isPhone();
  const sizes = phone ? WEEKEND_MAP_DOT.phone : WEEKEND_MAP_DOT.desktop;
  const muted = MUTED[ctx.theme] ?? MUTED.light;
  const key = el('div', 'wk-map-key');
  const present = new Set(placed.map((d) => windowOf(d.game)));
  const families = new Set(placed.map((d) => d.family));

  if (present.size) {
    const part = el('div', 'wk-map-key-part wk-map-key-kickoff');
    part.append(el('p', 'wk-map-key-heading', 'Kickoff'));
    const row = el('ul', 'wk-map-key-row');
    for (const win of Object.keys(WINDOW_LABELS[sport])) {
      if (!present.has(win)) continue;
      const symbol = win === 'tba' ? WINDOW_SYMBOL.tba : WINDOW_SYMBOL[sport][win];
      const item = el('li', 'wk-map-key-item');
      item.dataset.window = win;
      item.dataset.symbol = symbol;
      item.append(shapeSvg(symbol, sizes[symbol], muted), el('span', null, WINDOW_LABELS[sport][win]));
      row.append(item);
    }
    part.append(row, el('p', 'wk-map-key-caption', WINDOW_CAPTION[sport]));
    key.append(part);
  }
  if (families.size) {
    const part = el('div', 'wk-map-key-part wk-map-key-networks');
    const row = el('ul', 'wk-map-key-row wk-map-key-row--nets');
    for (const family of FAMILY_ORDER) {
      if (!families.has(family)) continue;
      const item = el('li', 'wk-map-key-item');
      item.dataset.family = family;
      const dot = el('span', 'wk-map-key-dot');
      dot.setAttribute('aria-hidden', 'true');
      dot.style.backgroundColor = MAP_FAMILY_COLORS[ctx.theme][family];
      item.append(dot, el('span', null, FAMILY_LABELS[family] ?? family));
      row.append(item);
    }
    part.append(row);
    key.append(part);
  }
  const shading = el('p', 'wk-map-key-caption wk-map-key-shading', SPLAT_CAPTION);
  shading.hidden = true;
  key.append(shading);
  return { key, shading };
}

// ---- Not on the map ----

function notOnMapCell(game, ctx) {
  const cell = buildCell(game, ctx, { tail: game.networkName ?? 'Network TBA' });
  applyPick(cell, game, ctx, ctx.rowFaded([game]));
  return cell;
}

/** The "Not on the map (n)" list: the Time TBA strip's shell and cells, one rule for open. */
function buildNotOnMap(ctx, api, games) {
  if (!games.length) return document.createDocumentFragment();
  const open = ctx.state.notMapOpen ?? !stripCollapsedByDefault(games.length);
  const section = el('section', 'wk-tba wk-notmap');
  const head = el('button', 'wk-tba-head');
  head.type = 'button';
  head.dataset.wkId = 'notmap';
  head.setAttribute('aria-expanded', String(open));
  head.setAttribute('aria-controls', 'wk-notmap-body');
  head.append(makeCaretIcon(), el('span', 'wk-tba-title', `Not on the map (${games.length})`));
  head.addEventListener('click', () => {
    ctx.state.notMapOpen = !open;
    api.rerender();
  });
  const body = el('div', 'wk-tba-body');
  body.id = 'wk-notmap-body';
  body.hidden = !open;
  for (const g of games) body.append(notOnMapCell(g, ctx));
  section.append(head, el('p', 'wk-notmap-note', NOT_ON_MAP_NOTE), body);
  return section;
}

// ---- Per-host mount (graph node, tap controller, splat layer) ----

function createMount(host) {
  const gd = el('div', 'wk-map-box');
  gd.setAttribute('role', 'img');
  const wrap = el('div', 'wk-map-wrap');
  const overlay = el('p', 'map-overlay');
  overlay.hidden = true;
  wrap.append(gd, overlay);

  const z = {
    host, gd, wrap, overlay,
    model: null, opts: {}, ctx: null, shading: null,
    byKey: new Map(),
    drawToken: 0, figEpoch: 0, ready: false, bound: false, dead: false,
    sig: null, hoverKey: null, cardOwned: false, splatBroken: false, geometry: null,
  };

  const opener = () => z.host.querySelector('[data-wk-id="wview:map"]');
  const openGame = (game) => {
    hideCard();
    z.tap.reset();
    z.opts.onOpen?.(game, opener());
  };

  function setOverlay(text, failed) {
    overlay.hidden = text == null;
    overlay.textContent = text ?? '';
    overlay.classList.toggle('wk-map-fail', Boolean(failed));
  }
  z.setOverlay = setOverlay;

  function hideCard() {
    if (!z.cardOwned) return;
    z.cardOwned = false;
    hideTooltip();
    if (z.hoverKey != null) setRing(null);
  }

  function cardFor(key) {
    const d = z.byKey.get(key);
    return d ? { d, lines: d.hoverLines } : null;
  }

  function showCard(key, ev, phone) {
    const hit = cardFor(key);
    if (!hit || !z.ctx) return;
    const at = pointOf(ev);
    z.cardOwned = true;
    showGameTooltip(
      {
        matchup: hit.lines.matchup,
        booth: hit.lines.booth,
        kickoff: hit.lines.kickoff,
        venue: hit.lines.venue,
        family: hit.d.family,
      },
      {
        theme: z.ctx.theme,
        clientX: at.x,
        clientY: at.y,
        phone,
        onOpen: () => openGame(hit.d.game),
        within: phone ? gd.getBoundingClientRect() : null,
      },
    );
  }

  /**
   * The 1px ring on one mark (the tap ring and the desktop hover ring): a restyle of the
   * wk-hover trace alone, so the land fill, the splat image and the hover state of the other
   * traces are never re-rendered (a full react on every hover would flicker the unhover).
   */
  function setRing(key) {
    z.hoverKey = key;
    if (!gd.data || !window.Plotly) return;
    const d = key == null ? null : z.byKey.get(key);
    const update = d
      ? { x: [[d.x]], y: [[d.y]], 'marker.size': [[d.size + WEEKEND_MAP_DOT.hoverRing.offset]] }
      : { x: [[]], y: [[]], 'marker.size': [[]] };
    Promise.resolve(window.Plotly.restyle(gd, update, [WEEKEND_MAP_TRACE_NAMES.indexOf('wk-hover')]))
      .catch(() => {});
  }

  z.tap = createTapController({
    container: gd,
    isTouchOnly: hoverNone,
    isReady: () => z.ready,
    isInsideCard: isInTooltip,
    onShowCard: (key, ev) => {
      showCard(key, ev, true);
      setRing(key);
    },
    onOpen: (key) => {
      const hit = cardFor(key);
      if (hit) openGame(hit.d.game);
    },
    // Only the card this map showed; another map's or panel's tooltip is not ours to hide.
    onClear: hideCard,
  });

  z.layer = createSplatLayer(gd, {
    imageSpec: splatImageSpec,
    landFill: (theme) => MAP_LAND[theme],
    onFail: (err) => {
      z.splatBroken = true;
      if (z.shading) z.shading.hidden = true;
      console.warn('booth-review: weekend map colors could not be drawn', err);
    },
  });

  z.bindEvents = () => {
    if (z.bound) return;
    bindMapEvents(gd, {
      onVenueClick: (key, ev) => z.tap.onVenueClick(key, ev),
      onVenueHover: (key, ev) => {
        if (hoverNone()) return;
        showCard(key, ev, false);
        setRing(key);
      },
      // On touch the tap card must outlive Plotly's synthetic unhover.
      onVenueUnhover: () => {
        if (!hoverNone()) hideCard();
      },
    });
    z.bound = true;
  };

  z.destroy = () => {
    if (z.dead) return;
    z.dead = true;
    z.drawToken += 1;
    z.ready = false;
    z.tap.destroy();
    hideCard();
    z.layer.destroy();
    try {
      window.Plotly?.purge(gd);
    } catch {
      // Nothing left to purge.
    }
    wrap.remove();
    if (MOUNTS.get(host) === z) MOUNTS.delete(host);
  };
  return z;
}

function dayModelFor(ctx, z, plot) {
  return buildWeekendMapModel({
    games: ctx.inDay,
    day: ctx.day,
    passes: ctx.passes,
    networksPicked: ctx.networksPicked,
    theme: ctx.theme,
    mobile: isPhone(),
    plot,
    nowWall: ctx.nowWall,
  });
}

/** A string that changes whenever the figure would: day, theme, size and every game's pick state. */
function signatureOf(ctx, model, plot, wantSplat) {
  const marks = [...model.dots, ...model.markers]
    .map((d) => `${d.key}:${d.x.toFixed(2)}:${d.y.toFixed(2)}:${d.faded ? 'f' : d.ringed ? 'r' : 'n'}`)
    .join(',');
  return [ctx.day, ctx.theme, plot.w, plot.h, wantSplat, marks].join('|');
}

async function draw(z, ctx) {
  const mine = (z.drawToken += 1);
  const live = () => !z.dead && mine === z.drawToken;
  const { gd } = z;
  let geometry;
  try {
    geometry = z.geometry ?? (await loadGeometry());
  } catch (err) {
    console.warn('booth-review: weekend map geometry could not be loaded', err);
    if (live()) z.setOverlay(DRAW_FAILED, true);
    return;
  }
  z.geometry = geometry;
  if (!live() || !gd.isConnected) return;
  const plot = { w: gd.clientWidth, h: gd.clientHeight };
  if (!(plot.w > 0) || !(plot.h > 0)) return;

  const model = dayModelFor(ctx, z, plot);
  z.byKey = new Map([...model.dots, ...model.markers].map((d) => [d.key, d]));
  const placed = model.dots.length + model.markers.length;
  const when = ctx.day != null ? `on ${dayLabel(ctx.day)}` : 'with no listed date';
  gd.setAttribute('aria-label', `Map of ${placed} ${placed === 1 ? 'game' : 'games'} ${when}, `
    + 'colored by network. Switch to Timeline to read every game with the keyboard.');
  z.setOverlay(placed === 0 && ctx.inDay.length > 0 ? NONE_PLACED : null, false);

  const wantSplat = !z.splatBroken && model.splatModel.venues.length > 0;
  const sig = signatureOf(ctx, model, plot, wantSplat);
  if (z.shading) z.shading.hidden = !wantSplat;
  if (sig === z.sig && gd.data) {
    z.ready = true;
    return;
  }
  const mobile = isPhone();
  // The splat belongs to the figure it was painted for; a skipped (unchanged) draw keeps it.
  const epoch = (z.figEpoch += 1);
  const current = () => !z.dead && epoch === z.figEpoch;
  try {
    const env = {
      theme: ctx.theme,
      mobile,
      plot,
      splat: wantSplat && z.layer.currentSpec != null,
    };
    const figure = buildWeekendMapFigure(model, geometry, {
      ...env,
      hoverKey: null,
      images: wantSplat && z.layer.currentSpec ? [z.layer.currentSpec] : [],
    });
    z.hoverKey = null;
    await renderMap(gd, figure);
    if (!live()) return;
    z.bindEvents();
    z.sig = sig;
    z.ready = true;
    renderCount += 1;
    if (wantSplat) {
      z.layer.schedule(
        async () => {
          const { blob } = await paintSplat({
            venueModel: model.splatModel,
            states: geometry,
            theme: ctx.theme,
            cell: mobile ? MAP_SPLAT.cell.phone : MAP_SPLAT.cell.desktop,
            params: { ...MAP_SPLAT, ...MAP_SPLAT_WEEKEND },
          });
          return blob;
        },
        current,
        ctx.theme,
      );
    } else {
      await z.layer.clear();
    }
  } catch (err) {
    // Plotly can reject (a zero-width container, say): say so and keep the switch usable.
    console.warn('booth-review: weekend map could not be drawn', err);
    if (live()) z.setOverlay(DRAW_FAILED, true);
  }
}

function buildMapBody(z) {
  return (ctx, api) => {
    z.ctx = ctx;
    z.opts = ctx.opts;
    const model = dayModelFor(ctx, z, null);
    const placed = [...model.dots, ...model.markers];
    const { key, shading } = buildKey(ctx, placed);
    z.shading = shading;
    const nodes = [
      buildStampLine(ctx),
      z.wrap,
      key,
      buildTbaStrip(ctx, api),
      buildCompactTable(ctx),
      buildNotOnMap(ctx, api, model.notOnMap),
      buildSourceLine(ctx),
    ];
    // The node is attached once the shell has swapped its children in; draw after that.
    Promise.resolve().then(() => draw(z, ctx));
    return nodes;
  };
}

/**
 * Mounts the weekend map in `host`. A second call on the same host keeps the graph node and
 * updates it in place; `destroy()` purges it.
 * @returns {{destroy: () => void}}
 */
export function renderWeekendMap(host, model, opts = {}) {
  let z = MOUNTS.get(host);
  if (!z || z.dead) {
    z = createMount(host);
    MOUNTS.set(host, z);
  }
  z.model = model;
  z.opts = opts;
  const instance = mountWeekend(host, model, { ...opts, wview: 'map' }, buildMapBody(z), 'map');
  const mount = z;
  return {
    destroy() {
      instance.destroy();
      mount.destroy();
    },
  };
}
