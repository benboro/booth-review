// Map figure (04.18 D-04/D-05/D-07..D-10/D-13/D-15): paints the map model with Plotly.
//
// Constant-trace figure: outline, legs x 8 families, inert x 8, dots x 8, markers, always
// in that order and drawn bottom to top, so Plotly.react diffs cleanly whatever the
// selection; unused slots carry empty arrays. buildMapFigure is pure (model + geometry +
// env in, {traces, layout, config} out). window.Plotly is touched only inside renderMap
// and bindMapEvents. Data strings reach Plotly text only through escapeHover; hover labels
// are off (the page paints its own tooltip from the venue index), so no hovertemplate
// carries data. No color literal lives here: everything comes from palette.js.

import { escapeHover } from './format.js';
import { MAP_HEIGHT, MAP_WIDTH } from './map-model.js';
import {
  DOT_OUTLINE,
  FAMILY_COLORS,
  FAMILY_ORDER,
  MAP_LAND,
  MAP_LINE_WIDTH,
  MAP_MARKER_LABEL,
  MAP_OPACITY,
  MAP_OUTLINE,
  MAP_SIZE,
  PAGE_BG,
} from './palette.js';

const MARKER_FONT = { desktop: 12, mobile: 10 };
const MOBILE_HOVER_DISTANCE = 22;

/** The 26 trace names in draw order. */
export const MAP_TRACE_NAMES = Object.freeze([
  'outline',
  ...FAMILY_ORDER.map((f) => `legs:${f}`),
  ...FAMILY_ORDER.map((f) => `inert:${f}`),
  ...FAMILY_ORDER.map((f) => `dots:${f}`),
  'markers',
]);

function outlineTrace(geometry, theme) {
  const x = [];
  const y = [];
  for (const state of geometry) {
    for (const ring of state.rings) {
      if (x.length > 0) {
        x.push(null);
        y.push(null);
      }
      for (let i = 0; i < ring.length; i += 2) {
        x.push(ring[i]);
        y.push(ring[i + 1]);
      }
    }
  }
  return {
    type: 'scatter',
    mode: 'lines',
    name: 'outline',
    x,
    y,
    fill: 'toself',
    fillcolor: MAP_LAND[theme],
    connectgaps: false,
    line: { color: MAP_OUTLINE[theme], width: MAP_LINE_WIDTH.outline },
    hoverinfo: 'skip',
    hovertemplate: null,
    showlegend: false,
  };
}

function legsTrace(family, legs, theme) {
  const x = [];
  const y = [];
  for (const leg of legs) {
    if (leg.family !== family) continue;
    if (x.length > 0) {
      x.push(null);
      y.push(null);
    }
    for (const p of leg.points) {
      x.push(p.x);
      y.push(p.y);
    }
  }
  return {
    type: 'scatter',
    mode: 'lines',
    name: `legs:${family}`,
    x,
    y,
    connectgaps: false,
    line: { color: FAMILY_COLORS[theme][family], width: MAP_LINE_WIDTH.leg },
    opacity: MAP_OPACITY.leg,
    hoverinfo: 'skip',
    hovertemplate: null,
    showlegend: false,
  };
}

function inertTrace(family, faded, theme) {
  const mine = faded.filter((d) => d.family === family);
  return {
    type: 'scatter',
    mode: 'markers',
    name: `inert:${family}`,
    x: mine.map((d) => d.x),
    y: mine.map((d) => d.y),
    marker: {
      symbol: 'circle',
      size: MAP_SIZE.faded,
      color: FAMILY_COLORS[theme][family],
      opacity: MAP_OPACITY.faded,
      line: { width: 0 },
    },
    hoverinfo: 'skip',
    hovertemplate: null,
    showlegend: false,
  };
}

function dotSize(dot) {
  if (dot.tier !== 'subject') return MAP_SIZE[dot.tier];
  return MAP_SIZE.subject[dot.symbol] ?? MAP_SIZE.subject.circle;
}

function dotsTrace(family, dots, theme) {
  const mine = dots.filter((d) => d.family === family);
  return {
    type: 'scatter',
    mode: 'markers',
    name: `dots:${family}`,
    x: mine.map((d) => d.x),
    y: mine.map((d) => d.y),
    customdata: mine.map((d) => d.venue),
    marker: {
      symbol: mine.map((d) => d.symbol),
      size: mine.map(dotSize),
      color: FAMILY_COLORS[theme][family],
      opacity: mine.map((d) => MAP_OPACITY[d.tier]),
      line: {
        width: mine.map((d) => (d.tier === 'subject' ? MAP_LINE_WIDTH.subjectOutline : 0)),
        color: mine.map(() => DOT_OUTLINE),
      },
    },
    hoverinfo: 'none',
    hovertemplate: null,
    showlegend: false,
  };
}

function markersTrace(markers, theme, mobile) {
  const colors = markers.map((m) => FAMILY_COLORS[theme][m.family]);
  return {
    type: 'scatter',
    mode: 'markers+text',
    name: 'markers',
    x: markers.map((m) => m.x),
    y: markers.map((m) => m.y),
    text: markers.map((m) => escapeHover(m.label)),
    textposition: markers.map((m) => (m.side === 'left' ? 'middle left' : 'middle right')),
    textfont: {
      size: mobile ? MARKER_FONT.mobile : MARKER_FONT.desktop,
      color: MAP_MARKER_LABEL[theme],
    },
    marker: {
      symbol: 'circle-open',
      size: MAP_SIZE.marker,
      color: colors,
      opacity: markers.map((m) => (m.faded ? MAP_OPACITY.faded : MAP_OPACITY.marker)),
      line: { width: MAP_LINE_WIDTH.marker, color: colors },
    },
    hoverinfo: 'skip',
    hovertemplate: null,
    showlegend: false,
  };
}

/**
 * Builds the whole Map figure.
 * @param {object} model - buildMapModel output (dots, faded, legs, markers used).
 * @param {ReadonlyArray<{id: string, rings: number[][]}>} geometry - US_STATES.
 * @param {{theme: 'light'|'dark', mobile: boolean}} env
 * @returns {{traces: object[], layout: object, config: object}}
 */
export function buildMapFigure(model, geometry, env) {
  const { theme, mobile } = env;
  const traces = [
    outlineTrace(geometry, theme),
    ...FAMILY_ORDER.map((f) => legsTrace(f, model.legs, theme)),
    ...FAMILY_ORDER.map((f) => inertTrace(f, model.faded, theme)),
    ...FAMILY_ORDER.map((f) => dotsTrace(f, model.dots, theme)),
    markersTrace(model.markers, theme, mobile),
  ];
  const layout = {
    xaxis: {
      visible: false,
      range: [0, MAP_WIDTH],
      constrain: 'domain',
      fixedrange: mobile,
    },
    yaxis: {
      visible: false,
      range: [MAP_HEIGHT, 0],
      scaleanchor: 'x',
      scaleratio: 1,
      constrain: 'domain',
      fixedrange: mobile,
    },
    margin: { l: 0, r: 0, t: 0, b: 0 },
    paper_bgcolor: PAGE_BG[theme],
    plot_bgcolor: PAGE_BG[theme],
    showlegend: false,
    hovermode: 'closest',
    dragmode: mobile ? false : 'zoom',
    uirevision: 'map',
  };
  if (mobile) layout.hoverdistance = MOBILE_HOVER_DISTANCE;
  const config = {
    responsive: true,
    scrollZoom: false,
    displayModeBar: !mobile,
    displaylogo: false,
    modeBarButtonsToRemove: ['lasso2d', 'select2d'],
  };
  return { traces, layout, config };
}

/**
 * Draws the figure (Plotly.react, so the constant traces diff in place).
 * @param {HTMLElement} gd
 * @param {{traces: object[], layout: object, config: object}} figure
 * @returns {*} the Plotly promise.
 */
export function renderMap(gd, figure) {
  return window.Plotly.react(gd, figure.traces, figure.layout, figure.config);
}

function venueOf(ev) {
  const p = ev.points && ev.points[0];
  if (!p || p.customdata == null) return null;
  const name = p.data && p.data.name;
  if (typeof name !== 'string' || !name.startsWith('dots:')) return null;
  return { venue: p.customdata, family: name.slice('dots:'.length) };
}

/**
 * Binds Plotly events once, after the first `renderMap`. Only active dots count;
 * callbacks receive (venueIndex, family, ev).
 * @param {HTMLElement} gd
 * @param {{onVenueClick?: Function, onVenueHover?: Function, onVenueUnhover?: Function}} handlers
 */
export function bindMapEvents(gd, handlers = {}) {
  const { onVenueClick, onVenueHover, onVenueUnhover } = handlers;
  gd.on('plotly_click', (ev) => {
    const hit = venueOf(ev);
    if (hit) onVenueClick?.(hit.venue, hit.family, ev);
  });
  gd.on('plotly_hover', (ev) => {
    const hit = venueOf(ev);
    if (hit) onVenueHover?.(hit.venue, hit.family, ev);
  });
  gd.on('plotly_unhover', () => onVenueUnhover?.());
}
