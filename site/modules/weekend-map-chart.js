// Weekend map figure (Phase 24, UI-SPEC "Marks"): paints the weekend map model with Plotly.
//
// Constant-trace figure (10 traces): outline, faded dots, normal dots, matched dots, ring
// keyline, ring ink, hover ring, venue-hits, markers, marker labels, always in that order and
// drawn bottom to top, so Plotly.react diffs cleanly whatever the pick; unused slots carry empty arrays.
// buildWeekendMapFigure is pure (model + geometry + env in, {traces, layout, config} out).
// Data strings reach Plotly text only through escapeHover; hover labels are off (the page paints
// its own tooltip from the key), so no hovertemplate carries data. The 'venue-hits' and
// 'markers' trace names and the game key in customdata are what map-chart.js's bindMapEvents and
// touchedKey resolve, unchanged. No colour literal lives here: everything comes from palette.js.

import { escapeHover } from './format.js';
import { FRAME_FONT, frameConfig, frameLayout, haloText } from './chart-frame.js';
import { MAP_HEIGHT, MAP_WIDTH } from './map-geo.js';
import { outlineTrace } from './map-chart.js';
import {
  INK,
  MAP_FAMILY_COLORS,
  MAP_LINE_WIDTH,
  MAP_MARKER_LABEL,
  MAP_OPACITY,
  PAGE_BG,
  WEEKEND_MAP_DOT,
} from './palette.js';

/** The ten trace names in draw order. */
export const WEEKEND_MAP_TRACE_NAMES = Object.freeze([
  'outline',
  'dots-faded',
  'dots',
  'dots-matched',
  'ring-keyline',
  'ring-ink',
  'wk-hover',
  'venue-hits',
  'markers',
  'marker-labels',
]);

/** Map-local edge-marker label font: Roboto Condensed 400, 12 px (not bar-chart's weight 600). */
const LABEL_FONT = Object.freeze({ family: FRAME_FONT, size: 12, weight: 400 });
const MOBILE_HOVER_DISTANCE = 22;
/** A fully transparent fill for the hit twin (it draws nothing). */
const HIT_COLOR = 'rgba(0,0,0,0)';

function colorOf(point, theme) {
  return MAP_FAMILY_COLORS[theme][point.family] ?? MAP_FAMILY_COLORS[theme].other;
}

function isOpen(point) {
  return point.symbol === 'circle-open';
}

/** Keyline per point: filled marks wear the page-background keyline; the open TBA ring is its own stroke. */
function markerLine(points, theme) {
  return {
    width: points.map((p) => (isOpen(p) ? WEEKEND_MAP_DOT.tbaStroke : MAP_LINE_WIDTH.dotKeyline)),
    color: points.map((p) => (isOpen(p) ? colorOf(p, theme) : PAGE_BG[theme])),
  };
}

function layer(name, points, theme) {
  return {
    type: 'scatter',
    mode: 'markers',
    name,
    x: points.map((p) => p.x),
    // A mark draws at `markY` when the model set one (the arrow-up triangle, lifted to centre
    // on its point); rings, hit targets and labels use `y`.
    y: points.map((p) => p.markY ?? p.y),
    customdata: points.map((p) => p.key),
    marker: {
      symbol: points.map((p) => p.symbol),
      size: points.map((p) => p.size),
      color: points.map((p) => colorOf(p, theme)),
      opacity: points.map((p) => (p.faded ? MAP_OPACITY.faded : 1)),
      line: markerLine(points, theme),
    },
    // The venue-hits trace carries hover and click, so the layers only draw.
    hoverinfo: 'skip',
    hovertemplate: null,
    showlegend: false,
  };
}

function ringTrace(name, points, spec, color) {
  return {
    type: 'scatter',
    mode: 'markers',
    name,
    x: points.map((p) => p.x),
    y: points.map((p) => p.y),
    marker: {
      symbol: 'circle-open',
      size: points.map((p) => p.size + spec.offset),
      color,
      line: { width: spec.width, color },
    },
    hoverinfo: 'skip',
    hovertemplate: null,
    showlegend: false,
  };
}

/**
 * The minimum hit target: a fully transparent twin of every dot and edge marker, same points,
 * each at least `WEEKEND_MAP_DOT.hitDiameter` wide, so a small mark is still easy to hover,
 * click and tap. It draws nothing; events are keyed by customdata.
 */
function hitsTrace(points) {
  return {
    type: 'scatter',
    mode: 'markers',
    name: 'venue-hits',
    x: points.map((p) => p.x),
    y: points.map((p) => p.y),
    customdata: points.map((p) => p.key),
    hovertext: points.map((p) => escapeHover(p.hoverLines?.text ?? '')),
    marker: {
      symbol: 'circle',
      size: points.map((p) => Math.max(p.size, WEEKEND_MAP_DOT.hitDiameter)),
      color: HIT_COLOR,
      opacity: 1,
      line: { width: 0 },
    },
    hoverinfo: 'none',
    hovertemplate: null,
    showlegend: false,
  };
}

/** Edge markers in their window shape; their city labels are the 'marker-labels' trace. */
function markersTrace(markers, theme) {
  return {
    ...layer('markers', markers, theme),
    hovertext: markers.map((m) => escapeHover(m.hoverLines?.text ?? '')),
    hoverinfo: 'none',
  };
}

/**
 * One city label per edge site, haloed in the page colour. Its own trace so the label stays on
 * the site's row when the labelled mark is a lifted triangle: invisible markers of the same size
 * on each point keep Plotly's marker-size text offset, so labels sit where they always did.
 */
function markerLabelsTrace(markers, theme) {
  return {
    type: 'scatter',
    mode: 'markers+text',
    name: 'marker-labels',
    x: markers.map((m) => m.x),
    y: markers.map((m) => m.y),
    text: markers.map((m) => escapeHover(m.text ?? '')),
    textposition: markers.map((m) => (m.side === 'left' ? 'middle left' : 'middle right')),
    textfont: { ...LABEL_FONT, color: MAP_MARKER_LABEL[theme], ...haloText(theme) },
    marker: { size: markers.map((m) => m.size), opacity: 0, line: { width: 0 } },
    hoverinfo: 'skip',
    hovertemplate: null,
    showlegend: false,
  };
}

/**
 * Builds the whole weekend map figure.
 * @param {object} model - `buildWeekendMapModel` output (dots and markers used).
 * @param {ReadonlyArray<{id: string, rings: number[][]}>} geometry - US_STATES.
 * @param {{theme: 'light'|'dark', mobile: boolean, splat?: boolean, images?: object[],
 *   hoverKey?: (string|null)}} env
 * @returns {{traces: object[], layout: object, config: object}}
 */
export function buildWeekendMapFigure(model, geometry, env) {
  const { theme, mobile } = env;
  const dots = model.dots ?? [];
  const markers = model.markers ?? [];
  const all = [...dots, ...markers];
  const ringed = all.filter((p) => !p.faded && p.ringed);
  const hovered = env.hoverKey == null ? [] : all.filter((p) => p.key === env.hoverKey);
  const traces = [
    outlineTrace(geometry, theme, env.splat),
    layer('dots-faded', dots.filter((d) => d.faded), theme),
    layer('dots', dots.filter((d) => !d.faded && !d.ringed), theme),
    layer('dots-matched', dots.filter((d) => !d.faded && d.ringed), theme),
    ringTrace('ring-keyline', ringed, WEEKEND_MAP_DOT.keylineRing, PAGE_BG[theme]),
    ringTrace('ring-ink', ringed, WEEKEND_MAP_DOT.inkRing, INK[theme]),
    ringTrace('wk-hover', hovered, WEEKEND_MAP_DOT.hoverRing, INK[theme]),
    hitsTrace(all),
    markersTrace(markers, theme),
    markerLabelsTrace(markers, theme),
  ];
  const layout = frameLayout(
    {
      xaxis: {
        visible: false,
        showgrid: false,
        range: [0, MAP_WIDTH],
        constrain: 'domain',
        fixedrange: true,
      },
      yaxis: {
        visible: false,
        showgrid: false,
        range: [MAP_HEIGHT, 0],
        scaleanchor: 'x',
        scaleratio: 1,
        constrain: 'domain',
        fixedrange: true,
      },
      margin: { l: 0, r: 0, t: 0, b: 0 },
      hovermode: 'closest',
      dragmode: false,
      uirevision: 'weekend-map',
      images: env.images ?? [],
    },
    env,
  );
  if (mobile) layout.hoverdistance = MOBILE_HOVER_DISTANCE;
  return { traces, layout, config: frameConfig({ zoomable: false }) };
}
