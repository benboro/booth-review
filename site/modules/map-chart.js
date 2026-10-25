// Map figure (04.18 D-04/D-05/D-07..D-10/D-13/D-15): paints the map model with Plotly.
//
// Constant-trace figure: outline, legs x 8 families, venue-faded, venue-dots, venue-selected,
// markers, always in that order and drawn bottom to top, so Plotly.react diffs cleanly whatever the
// selection; unused slots carry empty arrays. buildMapFigure is pure (model + geometry +
// env in, {traces, layout, config} out). window.Plotly is touched only inside renderMap
// and bindMapEvents. Data strings reach Plotly text only through escapeHover; hover labels
// are off (the page paints its own tooltip from the venue index), so no hovertemplate
// carries data. No color literal lives here: everything comes from palette.js.

import { escapeHover } from './format.js';
import { MAP_HEIGHT, MAP_WIDTH } from './map-model.js';
import { frameLayout, frameConfig, haloText } from './chart-frame.js';
import {
  ACCENT,
  DOT_OUTLINE,
  FAMILY_ORDER,
  MAP_FAMILY_COLORS,
  MAP_LAND,
  MAP_LINE_WIDTH,
  MAP_MARKER_LABEL,
  MAP_OPACITY,
  mapOpacity,
  MAP_OUTLINE,
  MAP_SIZE,
  MAP_VENUE_DOT,
  MUTED,
  PAGE_BG,
} from './palette.js';

const MARKER_FONT = { desktop: 12, mobile: 12 };
const MOBILE_HOVER_DISTANCE = 22;

/** The 14 trace names in draw order (Phase 11; `venue-hits` added at Phase 17.1 D-16). */
export const MAP_TRACE_NAMES = Object.freeze([
  'outline',
  ...FAMILY_ORDER.map((f) => `legs:${f}`),
  'venue-faded',
  'venue-dots',
  'venue-hits',
  'venue-selected',
  'markers',
]);

function outlineTrace(geometry, theme, splat) {
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
    fill: splat ? 'none' : 'toself',
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
    line: { color: MAP_FAMILY_COLORS[theme][family], width: MAP_LINE_WIDTH.leg },
    opacity: mapOpacity(theme).leg,
    hoverinfo: 'skip',
    hovertemplate: null,
    showlegend: false,
  };
}

function venueFadedTrace(faded, theme) {
  return {
    type: 'scatter',
    mode: 'markers',
    name: 'venue-faded',
    x: faded.map((d) => d.x),
    y: faded.map((d) => d.y),
    marker: {
      symbol: 'circle',
      size: MAP_VENUE_DOT.fadedSize,
      color: MUTED[theme],
      opacity: MAP_OPACITY.faded,
      line: { width: 0 },
    },
    hoverinfo: 'skip',
    hovertemplate: null,
    showlegend: false,
  };
}

/** Drawn diameter of one venue dot: the model size, raised to the subject shape size. */
function venueDotSize(dot, mobile) {
  const base = mobile ? dot.size.phone : dot.size.desktop;
  if (dot.tier !== 'subject') return base;
  return Math.max(base, MAP_SIZE.subject[dot.symbol] ?? MAP_SIZE.subject.circle);
}

function venueDotsTrace(dots, theme, mobile) {
  return {
    type: 'scatter',
    mode: 'markers',
    name: 'venue-dots',
    x: dots.map((d) => d.x),
    y: dots.map((d) => d.y),
    customdata: dots.map((d) => d.key),
    marker: {
      symbol: dots.map((d) => d.symbol),
      size: dots.map((d) => venueDotSize(d, mobile)),
      color: dots.map((d) => d.dotColor[theme]),
      opacity: dots.map((d) =>
        d.tier === 'subject'
          ? mapOpacity(theme).subject
          : d.tier === 'other'
            ? MAP_OPACITY.other
            : MAP_VENUE_DOT.opacity,
      ),
      line: {
        width: dots.map((d) =>
          d.tier === 'subject' ? MAP_LINE_WIDTH.subjectOutline : MAP_VENUE_DOT.ringWidth,
        ),
        color: dots.map((d) => (d.tier === 'subject' ? DOT_OUTLINE[theme] : PAGE_BG[theme])),
      },
    },
    // The invisible venue-hits trace carries hover and click, so these draw only.
    hoverinfo: 'skip',
    hovertemplate: null,
    showlegend: false,
  };
}

/**
 * The minimum hit target (Phase 17.1 D-16): a fully transparent twin of the venue dots, same
 * points in the same order, each at least `MAP_VENUE_DOT.hitDiameter` wide so a small dot is
 * still easy to hover, click and tap. It draws nothing; events are keyed by customdata.
 */
function venueHitsTrace(dots, mobile) {
  return {
    type: 'scatter',
    mode: 'markers',
    name: 'venue-hits',
    x: dots.map((d) => d.x),
    y: dots.map((d) => d.y),
    customdata: dots.map((d) => d.key),
    marker: {
      symbol: 'circle',
      size: dots.map((d) => Math.max(venueDotSize(d, mobile), MAP_VENUE_DOT.hitDiameter)),
      color: 'rgba(0,0,0,0)',
      opacity: 1,
      line: { width: 0 },
    },
    hoverinfo: 'none',
    hovertemplate: null,
    showlegend: false,
  };
}

function venueSelectedTrace(model, theme, mobile) {
  const sel = model.venueDots.find((d) => d.selected);
  const ring = MAP_VENUE_DOT.selectedRingGap + MAP_VENUE_DOT.selectedRingWidth;
  return {
    type: 'scatter',
    mode: 'markers',
    name: 'venue-selected',
    x: sel ? [sel.x] : [],
    y: sel ? [sel.y] : [],
    marker: {
      symbol: 'circle-open',
      size: sel ? [venueDotSize(sel, mobile) + 2 * ring] : [],
      color: ACCENT[theme],
      line: { width: MAP_VENUE_DOT.selectedRingWidth, color: ACCENT[theme] },
    },
    hoverinfo: 'skip',
    hovertemplate: null,
    showlegend: false,
  };
}

function markersTrace(markers, theme, mobile) {
  const colors = markers.map((m) =>
    m.selected ? ACCENT[theme] : MAP_FAMILY_COLORS[theme][m.family],
  );
  return {
    type: 'scatter',
    mode: 'markers+text',
    name: 'markers',
    x: markers.map((m) => m.x),
    y: markers.map((m) => m.y),
    customdata: markers.map((m) => (m.faded ? null : (m.key ?? null))),
    text: markers.map((m) => escapeHover(m.label)),
    textposition: markers.map((m) => (m.side === 'left' ? 'middle left' : 'middle right')),
    textfont: {
      size: mobile ? MARKER_FONT.mobile : MARKER_FONT.desktop,
      color: MAP_MARKER_LABEL[theme],
      ...haloText(theme),
    },
    marker: {
      symbol: 'circle-open',
      size: MAP_SIZE.marker,
      color: colors,
      opacity: markers.map((m) => (m.faded ? MAP_OPACITY.faded : MAP_OPACITY.marker)),
      line: {
        width: markers.map((m) =>
          m.selected ? MAP_VENUE_DOT.selectedRingWidth : MAP_LINE_WIDTH.marker,
        ),
        color: colors,
      },
    },
    hoverinfo: 'none',
    hovertemplate: null,
    showlegend: false,
  };
}

/**
 * The y anchor of the splat image on the reversed y-axis, measured by the Phase 11
 * layout.images probe (11-01-SUMMARY.md: 'top' lands on the matching coordinates, 'bottom' fails).
 */
export const IMAGE_YANCHOR = 'top';

/**
 * The layout.images entry that places a splat raster under the traces (Phase 11 D-06).
 * @param {string} url - the raster's data URL.
 */
export function splatImageSpec(url) {
  return {
    source: url,
    xref: 'x',
    yref: 'y',
    x: 0,
    y: 0,
    sizex: MAP_WIDTH,
    sizey: MAP_HEIGHT,
    xanchor: 'left',
    yanchor: IMAGE_YANCHOR,
    sizing: 'stretch',
    layer: 'below',
    opacity: 1,
  };
}

/**
 * Builds the whole Map figure.
 * @param {object} model - buildMapModel output (venueDots, venueFaded, legs, markers used).
 * @param {ReadonlyArray<{id: string, rings: number[][]}>} geometry - US_STATES.
 * @param {{theme: 'light'|'dark', mobile: boolean, splat?: boolean, images?: object[]}} env
 * @returns {{traces: object[], layout: object, config: object}}
 */
export function buildMapFigure(model, geometry, env) {
  const { theme, mobile } = env;
  const traces = [
    outlineTrace(geometry, theme, env.splat),
    ...FAMILY_ORDER.map((f) => legsTrace(f, model.legs, theme)),
    venueFadedTrace(model.venueFaded, theme),
    venueDotsTrace(model.venueDots, theme, mobile),
    venueHitsTrace(model.venueDots, mobile),
    venueSelectedTrace(model, theme, mobile),
    markersTrace(model.markers, theme, mobile),
  ];
  const layout = frameLayout({
    xaxis: {
      visible: false,
      showgrid: false,
      range: [0, MAP_WIDTH],
      constrain: 'domain',
      fixedrange: mobile,
    },
    yaxis: {
      visible: false,
      showgrid: false,
      range: [MAP_HEIGHT, 0],
      scaleanchor: 'x',
      scaleratio: 1,
      constrain: 'domain',
      fixedrange: mobile,
    },
    // No modebar any more (Reset zoom is a page-level button), so no band is held above the plot.
    margin: { l: 0, r: 0, t: 0, b: 0 },
    hovermode: 'closest',
    dragmode: mobile ? false : 'zoom',
    uirevision: 'map',
    images: env.images ?? [],
  }, env);
  if (mobile) layout.hoverdistance = MOBILE_HOVER_DISTANCE;
  const config = frameConfig({ zoomable: true });
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
  if (name !== 'venue-hits' && name !== 'markers') return null;
  return { key: p.customdata };
}

/**
 * Binds Plotly events once, after the first `renderMap`. Only venue dots and keyed
 * (non-faded) markers count; callbacks receive (key, ev).
 * @param {HTMLElement} gd
 * @param {{onVenueClick?: Function, onVenueHover?: Function, onVenueUnhover?: Function}} handlers
 */
export function bindMapEvents(gd, handlers = {}) {
  const { onVenueClick, onVenueHover, onVenueUnhover } = handlers;
  gd.on('plotly_click', (ev) => {
    const hit = venueOf(ev);
    if (hit) onVenueClick?.(hit.key, ev);
  });
  gd.on('plotly_hover', (ev) => {
    const hit = venueOf(ev);
    if (hit) onVenueHover?.(hit.key, ev);
  });
  gd.on('plotly_unhover', () => onVenueUnhover?.());
}
