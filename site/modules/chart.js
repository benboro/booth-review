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
  formatDate,
  formatKickoff,
  formatMatchup,
  formatViewers,
  logTicks,
  niceLinearTicks,
  stripNetworkNote,
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
 * Builds the `<br>`-joined hover text for one telecast: kept deliberately
 * minimal (matchup+score, date+kickoff, networks, crew, viewers, and a
 * closing hint to open the detail panel) -- every other fact (time slot,
 * measurement/scoring source, axis values, flags, combined-feed notes) is
 * dropped from the tooltip and lives only in the detail panel (SITE-04,
 * SITE-05, D-02, D-04; product notes 2026-09-27). Each line is built from
 * untrusted data (team/crew/network names) and escaped *individually*
 * before being joined with the literal `<br>` separators Plotly's
 * pseudo-HTML hover renderer expects (T-04-06): escaping the fully-joined
 * string instead would also escape those `<br>` tags themselves, so Plotly
 * would render the whole tooltip as one unbroken line of visible
 * `&lt;br&gt;` markup rather than as actual line breaks.
 * @param {object} data - a `prepareData` result.
 * @param {number} i - telecast index.
 * @param {string[]} selectedNames - names of currently selected people on this game.
 * @returns {string}
 */
export function hoverText(data, i, selectedNames) {
  const t = data.t;
  const lines = [];

  lines.push(`<b>${escapeHover(formatMatchup(data, i, { withScore: true }))}</b>`);

  const dateParts = [formatDate(t.date[i]), formatKickoff(t.kickoff[i]) ?? 'Kickoff time not recorded'];
  lines.push(escapeHover(dateParts.join(' · ')));

  const primaryNetwork = data.lookups.networks[t.network[i]];
  const otherOutletNames = t.outlets[i]
    .filter((idx) => idx !== t.network[i])
    .map((idx) => data.lookups.networks[idx].name);
  // Slash-delimited, primary first (e.g. "ABC / ESPN2"), with any nested
  // methodology parenthetical (e.g. "(regional insert package)") stripped --
  // tooltip-only; the fuller name still shows in the panel/table.
  const networkNames = [primaryNetwork.name, ...otherOutletNames].map(stripNetworkNote);
  lines.push(escapeHover(networkNames.join(' / ')));

  const crew = crewByRole(data, i);
  const crewParts = [];
  if (crew.pbp.length > 0) crewParts.push(`PBP: ${crew.pbp.join(', ')}`);
  if (crew.analyst.length > 0) crewParts.push(`Analyst: ${crew.analyst.join(', ')}`);
  lines.push(escapeHover(crewParts.length > 0 ? crewParts.join(' · ') : 'Crew not recorded'));

  lines.push(escapeHover(`Viewers: ${formatViewers(t.viewers[i])}`));

  if (selectedNames.length > 0) lines.push(escapeHover(`Selected: ${selectedNames.join(', ')}`));

  lines.push(escapeHover('Click or tap for details'));

  return lines.join('<br>');
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

  // `view.highlighted` matches trivially against every visible dot when
  // nothing is selected (select.js's own semantics); only draw the overlay
  // once a person/team selection actually exists.
  const highlighted = view.hasSelection ? view.highlighted : [];
  // Once a selection exists, a highlighted dot is dropped from its own
  // family (base) trace, since the highlight overlay below already draws it,
  // and the faded base traces stop taking hover and clicks entirely
  // (`hoverinfo: 'skip'`), so a hover near a highlighted dot always snaps to
  // it instead of a nearer faded one. Plotly only honours `hoverinfo` when
  // `hovertemplate` is unset, so a skipped trace sets it to null.
  const highlightSet = new Set(highlighted);
  const highlightedFamilies = new Set(highlighted.map((i) => data.familyOf[i]));

  const traces = [];
  for (const family of data.families) {
    const x = [];
    const y = [];
    const customdata = [];
    const text = [];
    for (let i = 0; i < data.n; i += 1) {
      if (!view.visible[i] || data.familyOf[i] !== family) continue;
      if (highlightSet.has(i)) continue;
      const rawX = data.t[axis][i];
      x.push(rawX == null ? band.sentinel : rawX);
      y.push(data.t.viewers[i]);
      customdata.push(i);
      text.push(hoverText(data, i, selectedNamesFor(data, view, i)));
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
      hoverinfo: view.hasSelection ? 'skip' : 'all',
      hovertemplate: view.hasSelection ? null : '%{text}<extra></extra>',
      marker: {
        color: FAMILY_COLORS[theme][family],
        size: 6,
        opacity: view.hasSelection ? 0.15 : 1,
        line: { width: 0 },
      },
      // A family whose only dots are all currently highlighted has x.length
      // 0 here (they moved to the overlay trace below), but its dots are
      // still fully visible on the chart -- so its legend entry must not
      // read as hidden/off the way an actually-filtered-out family does.
      visible: x.length > 0 || highlightedFamilies.has(family) ? true : 'legendonly',
    });
  }

  const hx = [];
  const hy = [];
  const hcustomdata = [];
  const htext = [];
  const hcolor = [];
  const hsize = [];
  const hsymbol = [];
  for (const i of highlighted) {
    const rawX = data.t[axis][i];
    hx.push(rawX == null ? band.sentinel : rawX);
    hy.push(data.t.viewers[i]);
    hcustomdata.push(i);
    htext.push(hoverText(data, i, selectedNamesFor(data, view, i)));
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
    hoverinfo: 'all',
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
    // Wider once a selection exists, so it's easier to snap to a highlighted
    // dot's tooltip even when the cursor lands a few pixels off it (T3/D-02).
    hoverdistance: view.hasSelection ? 40 : 20,
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
