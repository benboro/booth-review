/**
 * Chart building and rendering (SITE-01, SITE-03, SITE-04, SITE-12, SITE-18,
 * D-01..D-04, D-12): one `scattergl` trace per network family plus a
 * highlight overlay drawn last, the D-03 n/a strip, log-axis ticks, hover
 * text, and the phone/desktop layout.
 *
 * `window.Plotly` is referenced only inside `renderChart`/`bindChartEvents`
 * (never at module scope), so `buildFigure`/`naBand`/`hoverText` stay
 * importable from node for quick checks.
 */

import { ACCENT, DIVIDER, FAMILY_COLORS, FAMILY_LABELS, PAGE_BG, SURFACE } from './palette.js';
import {
  crewByRole,
  escapeHover,
  formatAxisValue,
  formatDate,
  formatKickoff,
  formatMatchup,
  formatViewers,
  logTicks,
  measurementLabel,
  niceLinearTicks,
  SLOT_SHORT,
} from './format.js';

/** X-axis chart titles (distinct from format.js's shorter AXIS_LABELS toggle copy). */
const XAXIS_TITLES = {
  pregame: 'Closing spread (points) — closer games to the right',
  excitement: 'Excitement index (CFBD)',
};

/**
 * Computes the reserved n/a-strip band for one axis (D-03): a sentinel x for
 * missing values, the numeric-axis divider, the plotted range, and tick
 * values/labels that never fall inside the band.
 * @param {object} data - a `prepareData` result.
 * @param {"pregame"|"excitement"} axis
 * @returns {{sentinel: number, divider: number, range: [number, number], tickvals: number[], ticktext: string[]}}
 */
export function naBand(data, axis) {
  const [lo, hi] = data.xRange[axis];
  const span = Math.max(hi - lo, 1);
  const w = 0.06 * span;
  const sentinel = lo - 1.5 * w;
  const divider = lo - 0.75 * w;
  const range = [lo - 2.25 * w, hi + 0.03 * span];
  const tickvals = niceLinearTicks(lo, hi, 6);
  const ticktext = tickvals.map((v) => (axis === 'pregame' ? String(Math.abs(v)) : String(v)));
  return { sentinel, divider, range, tickvals, ticktext };
}

/**
 * Builds the escaped, `<br>`-joined hover text for one telecast, in the
 * UI-SPEC's hover order (SITE-04, D-02, D-04).
 * @param {object} data - a `prepareData` result.
 * @param {number} i - telecast index.
 * @param {"pregame"|"excitement"} axis - the currently active axis.
 * @param {string[]} selectedNames - names of currently selected people on this game.
 * @returns {string}
 */
export function hoverText(data, i, axis, selectedNames) {
  const t = data.t;
  const lines = [];

  lines.push(formatMatchup(data, i, { withScore: true }));

  const dateParts = [formatDate(t.date[i]), formatKickoff(t.kickoff[i]) ?? 'Kickoff time not recorded'];
  if (t.time_slot[i] != null) dateParts.push(SLOT_SHORT[t.time_slot[i]]);
  lines.push(dateParts.join(' · '));

  const primaryNetwork = data.lookups.networks[t.network[i]];
  const otherOutletNames = t.outlets[i]
    .filter((idx) => idx !== t.network[i])
    .map((idx) => data.lookups.networks[idx].name);
  let networkLine = primaryNetwork.name;
  if (otherOutletNames.length > 0) networkLine += ` (also ${otherOutletNames.join(', ')})`;
  lines.push(networkLine);

  const crew = crewByRole(data, i);
  const crewParts = [];
  if (crew.pbp.length > 0) crewParts.push(`PBP: ${crew.pbp.join(', ')}`);
  if (crew.analyst.length > 0) crewParts.push(`Analyst: ${crew.analyst.join(', ')}`);
  lines.push(crewParts.length > 0 ? crewParts.join(' · ') : 'Crew not recorded');

  lines.push(`Viewers: ${formatViewers(t.viewers[i])} · ${measurementLabel(t.measurement_type[i])}`);

  const otherAxis = axis === 'pregame' ? 'excitement' : 'pregame';
  lines.push(`${formatAxisValue(axis, t[axis][i])} · ${formatAxisValue(otherAxis, t[otherAxis][i])}`);

  const flagLabels = t.flags[i].map((idx) => data.lookups.flags[idx].label);
  const combined = t.combined_feeds[i];
  if (flagLabels.length > 0 || combined != null) {
    const flagParts = [...flagLabels];
    if (combined != null) flagParts.push(`Combined across ${combined} feeds`);
    lines.push(flagParts.join(' · '));
  }

  if (selectedNames.length > 0) lines.push(`Selected: ${selectedNames.join(', ')}`);

  return escapeHover(lines.join('<br>'));
}

/** Selected-people names on telecast `i`, from `view.peopleOnGame` (empty when nobody's selected). */
function selectedNamesFor(data, view, i) {
  const onGame = view.peopleOnGame.get(i);
  if (!onGame) return [];
  return onGame.map((personIndex) => data.lookups.people[personIndex].name);
}

/**
 * Builds the full Plotly figure (traces, layout, config) for the current
 * data/view/state/env (SITE-01, SITE-03, SITE-04, SITE-18).
 * @param {object} data - a `prepareData` result.
 * @param {object} view - a `computeView` result.
 * @param {object} state - shaped like `defaultState(data)`.
 * @param {{theme: "light"|"dark", mobile: boolean, revision: number}} env
 * @returns {{traces: object[], layout: object, config: object}}
 */
export function buildFigure(data, view, state, env) {
  const axis = state.axis;
  const band = naBand(data, axis);
  const theme = env.theme;

  const traces = [];
  for (const family of data.families) {
    const x = [];
    const y = [];
    const customdata = [];
    const text = [];
    for (let i = 0; i < data.n; i += 1) {
      if (!view.visible[i] || data.familyOf[i] !== family) continue;
      const rawX = data.t[axis][i];
      x.push(rawX == null ? band.sentinel : rawX);
      y.push(data.t.viewers[i]);
      customdata.push(i);
      text.push(hoverText(data, i, axis, selectedNamesFor(data, view, i)));
    }
    traces.push({
      type: 'scattergl',
      mode: 'markers',
      name: FAMILY_LABELS[family],
      meta: `family:${family}`,
      legendgroup: family,
      x,
      y,
      customdata,
      text,
      hovertemplate: '%{text}<extra></extra>',
      marker: {
        color: FAMILY_COLORS[theme][family],
        size: 6,
        opacity: view.hasSelection ? 0.15 : 1,
        line: { width: 0 },
      },
      visible: x.length > 0 ? true : 'legendonly',
    });
  }

  const hx = [];
  const hy = [];
  const hcustomdata = [];
  const htext = [];
  const hcolor = [];
  const hsize = [];
  const hsymbol = [];
  for (const i of view.highlighted) {
    const rawX = data.t[axis][i];
    hx.push(rawX == null ? band.sentinel : rawX);
    hy.push(data.t.viewers[i]);
    hcustomdata.push(i);
    htext.push(hoverText(data, i, axis, selectedNamesFor(data, view, i)));
    hcolor.push(FAMILY_COLORS[theme][data.familyOf[i]]);
    const symbol = view.symbols.get(i) ?? 'circle';
    hsymbol.push(symbol);
    hsize.push(symbol === 'star' ? 13 : 10);
  }
  traces.push({
    type: 'scattergl',
    mode: 'markers',
    meta: 'highlight',
    showlegend: false,
    x: hx,
    y: hy,
    customdata: hcustomdata,
    text: htext,
    hovertemplate: '%{text}<extra></extra>',
    marker: {
      color: hcolor,
      size: hsize,
      symbol: hsymbol,
      opacity: 1,
      line: { width: 1.5, color: ACCENT[theme] },
    },
  });

  const yTicks = logTicks(data.viewersMin, data.viewersMax);

  const layout = {
    datarevision: env.revision,
    uirevision: state.axis,
    paper_bgcolor: PAGE_BG[theme],
    plot_bgcolor: PAGE_BG[theme],
    font: {
      family:
        'system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji"',
      size: 14,
      color: ACCENT[theme],
    },
    hovermode: 'closest',
    hoverdistance: 20,
    hoverlabel: {
      bgcolor: SURFACE[theme],
      bordercolor: DIVIDER[theme],
      font: { color: ACCENT[theme] },
    },
    xaxis: {
      title: XAXIS_TITLES[axis],
      range: band.range,
      tickmode: 'array',
      tickvals: band.tickvals,
      ticktext: band.ticktext,
      zeroline: false,
      gridcolor: DIVIDER[theme],
      fixedrange: env.mobile,
    },
    yaxis: {
      type: 'log',
      title: 'Viewers (log scale)',
      tickmode: 'array',
      tickvals: yTicks.tickvals,
      ticktext: yTicks.ticktext,
      range: [Math.log10(data.viewersMin / 1.4), Math.log10(data.viewersMax * 1.4)],
      gridcolor: DIVIDER[theme],
      fixedrange: env.mobile,
    },
    shapes: [
      {
        type: 'line',
        xref: 'x',
        yref: 'paper',
        x0: band.divider,
        x1: band.divider,
        y0: 0,
        y1: 1,
        line: { width: 1, color: DIVIDER[theme] },
      },
    ],
    annotations: [
      {
        text: 'N/A',
        x: band.sentinel,
        xref: 'x',
        y: 0,
        yref: 'paper',
        yanchor: 'top',
        yshift: -6,
        showarrow: false,
        font: { size: 14 },
      },
    ],
    legend: env.mobile ? { orientation: 'h', x: 0, y: -0.25 } : { orientation: 'v', x: 1.02, y: 1 },
    dragmode: env.mobile ? false : 'zoom',
    margin: { l: 70, r: env.mobile ? 24 : 170, t: 24, b: 60 },
  };

  const config = {
    responsive: true,
    displaylogo: false,
    scrollZoom: false,
    showSendToCloud: false,
    showEditInChartStudio: false,
    showLink: false,
    displayModeBar: !env.mobile,
    modeBarButtonsToRemove: ['lasso2d', 'select2d'],
  };

  return { traces, layout, config };
}

/**
 * Renders `figure` into `gd` via `Plotly.react` -- never the one-shot plot
 * call Pattern 2/Pitfall 4 warn against reusing on updates. `figure.traces`/
 * `layout` must already hold fresh array identities for any changed
 * attribute.
 * @param {HTMLElement} gd
 * @param {{traces: object[], layout: object, config: object}} figure
 */
export function renderChart(gd, figure) {
  window.Plotly.react(gd, figure.traces, figure.layout, figure.config);
}

/**
 * Binds the chart's Plotly event handlers once: legend click/double-click
 * (family toggle, D-01/D-05) and point click (detail panel hook, wired in
 * plan 04-10).
 * @param {HTMLElement} gd
 * @param {{onLegendClick?: (key: string) => void, onLegendDoubleClick?: (key: string) => void, onPointClick?: (customdata: number) => void}} handlers
 */
export function bindChartEvents(gd, handlers = {}) {
  const { onLegendClick, onLegendDoubleClick, onPointClick } = handlers;

  gd.on('plotly_legendclick', (ev) => {
    const meta = gd.data[ev.curveNumber]?.meta;
    if (typeof meta === 'string' && meta.startsWith('family:')) {
      onLegendClick?.(meta.slice('family:'.length));
    }
    return false;
  });

  gd.on('plotly_legenddoubleclick', (ev) => {
    const meta = gd.data[ev.curveNumber]?.meta;
    if (typeof meta === 'string' && meta.startsWith('family:')) {
      onLegendDoubleClick?.(meta.slice('family:'.length));
    }
    return false;
  });

  gd.on('plotly_click', (ev) => {
    const point = ev.points && ev.points[0];
    if (point) onPointClick?.(point.customdata);
  });
}
