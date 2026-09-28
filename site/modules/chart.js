/**
 * Chart building and rendering (SITE-01, SITE-03, SITE-04, SITE-12, SITE-18,
 * SITE-23, SITE-25, SITE-26, D-01..D-04, D-08, D-12, D-14, D-15): two
 * `scattergl` traces per network family -- an "active" trace (dots that
 * pass every fade filter) and an "inert" trace (dots that fail one, D-14) --
 * plus a highlight overlay drawn last, the D-03 n/a strip, log-axis ticks,
 * the UI-SPEC's minimal 7-line hover text, and the phone/desktop layout.
 * Plotly's own legend is off everywhere (`showlegend: false`); the HTML
 * chip row in `legend.js` replaces it (D-04).
 *
 * The inert trace's `hoverinfo: 'skip'` is paired with `hovertemplate: null`
 * on the same trace update -- both are required to actually suppress hover
 * in this vendored Plotly build (the project's own 04-11 finding, STATE.md)
 * -- so an inert dot never takes a hover or a click (D-15).
 *
 * `window.Plotly` is referenced only inside `renderChart`/`bindChartEvents`
 * (never at module scope), so `buildFigure`/`naBand`/`hoverText` stay
 * importable from node for quick checks.
 */

import { ACCENT, DIVIDER, FAMILY_COLORS, PAGE_BG, SURFACE, familyKey } from './palette.js';
import {
  crewByRole,
  escapeHover,
  formatAxisValue,
  formatDate,
  formatKickoff,
  formatMatchup,
  formatViewers,
  logTicks,
  niceLinearTicks,
  ROLE_LABELS,
  showsTimeSlot,
  SLOT_SHORT_LABELS,
  stripNetworkNote,
} from './format.js';

/** X-axis chart titles (distinct from format.js's shorter AXIS_LABELS toggle copy). */
const XAXIS_TITLES = {
  pregame: 'Closing spread (points) — closer games to the right',
  excitement: 'Excitement index (CFBD)',
};

/** Phone x-axis titles: the long pre-game title is wider than a phone screen, so it wraps (Plotly titles never wrap on their own). */
const XAXIS_TITLES_MOBILE = {
  pregame: 'Closing spread (points)<br>closer games to the right',
  excitement: XAXIS_TITLES.excitement,
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
 * Builds the `<br>`-joined hover text for one telecast: the UI-SPEC's
 * minimal 7-line order -- matchup+score, date+kickoff (with a time-slot
 * label only for a regular-season Saturday game, D-19), slash-delimited
 * networks (primary first, each colored by its own family -- the tooltip's
 * stand-in for a filled pill, since Plotly's hover renderer can't draw one,
 * SITE-26), one "Position: Name" line per main-feed crew member, viewers,
 * the active axis value, and a closing "Click for details →" hint.
 * Conferences, game type, the full outlet list, the measurement-type badge,
 * era/event flags, and any scoring-source/methodology note are panel-only
 * (SITE-25) -- never repeated here. Each line is built from untrusted data
 * (team/crew/network names) and escaped individually before being joined
 * with the literal `<br>` separators Plotly's pseudo-HTML hover renderer
 * expects (T-04-06): escaping the fully-joined string instead would also
 * escape those `<br>` tags themselves, so Plotly would render the whole
 * tooltip as one unbroken line of visible `&lt;br&gt;` markup rather than as
 * actual line breaks.
 * @param {object} data - a `prepareData` result.
 * @param {number} i - telecast index.
 * @param {{axis: "pregame"|"excitement", theme: "light"|"dark"}} opts
 * @returns {string}
 */
export function hoverText(data, i, { axis, theme }) {
  const t = data.t;
  const lines = [];

  lines.push(`<b>${escapeHover(formatMatchup(data, i, { withScore: true }))}</b>`);

  const dateParts = [formatDate(t.date[i]), formatKickoff(t.kickoff[i]) ?? 'Kickoff time not recorded'];
  if (showsTimeSlot(data, i)) dateParts.push(SLOT_SHORT_LABELS[t.time_slot[i]]);
  lines.push(escapeHover(dateParts.join(' · ')));

  const primaryNetwork = data.lookups.networks[t.network[i]];
  const otherOutlets = t.outlets[i]
    .filter((idx) => idx !== t.network[i])
    .map((idx) => data.lookups.networks[idx]);
  // Slash-delimited, primary first, no spaces around '/' (D-25); each name
  // is individually stripped of any nested methodology parenthetical (e.g.
  // "(regional insert package)" -- tooltip-only, the panel/table keep the
  // fuller name) and colored by its own family, standing in for a filled
  // pill (SITE-26). The color comes only from the FAMILY_COLORS constant,
  // never from data.
  const networkSpans = [primaryNetwork, ...otherOutlets].map((net) => {
    const name = escapeHover(stripNetworkNote(net.name));
    const color = FAMILY_COLORS[theme][familyKey(net.family)];
    return `<span style="color:${color}">${name}</span>`;
  });
  lines.push(networkSpans.join('/'));

  const crew = crewByRole(data, i);
  const crewLines = [
    ...crew.pbp.map((name) => `${ROLE_LABELS.pbp}: ${name}`),
    ...crew.analyst.map((name) => `${ROLE_LABELS.analyst}: ${name}`),
    ...crew.other.map((name) => `${ROLE_LABELS.unknown}: ${name}`),
  ];
  if (crewLines.length > 0) {
    for (const line of crewLines) lines.push(escapeHover(line));
  } else {
    lines.push(escapeHover('Crew not recorded'));
  }

  lines.push(escapeHover(`Viewers: ${formatViewers(t.viewers[i])}`));

  lines.push(escapeHover(formatAxisValue(axis, t[axis][i])));

  lines.push(escapeHover('Click for details →'));

  return lines.join('<br>');
}

/**
 * Builds the full Plotly figure (traces, layout, config) for the current
 * data/view/state/env (SITE-01, SITE-03, SITE-04, SITE-18, SITE-23, D-14).
 * Each family contributes two traces -- pushed inert-first, then
 * active-first, so the trace count stays constant across a re-render for a
 * clean `Plotly.react` diff -- followed by the highlight overlay, always
 * last.
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
  const hoverOpts = { axis, theme };

  // `view.highlighted` matches trivially against every visible dot when
  // nothing is selected (select.js's own semantics); only draw the overlay
  // once a person/school selection actually exists.
  const highlighted = view.hasSelection ? view.highlighted : [];
  // Once a selection exists, a highlighted dot is dropped from its own
  // family (active) trace, since the highlight overlay below already draws
  // it, and the faded active traces stop taking hover and clicks entirely
  // (`hoverinfo: 'skip'`), so a hover near a highlighted dot always snaps to
  // it instead of a nearer faded one. Plotly only honours `hoverinfo` when
  // `hovertemplate` is unset, so a skipped trace sets it to null.
  const highlightSet = new Set(highlighted);

  const inertTraces = [];
  const activeTraces = [];
  for (const family of data.families) {
    const active = { x: [], y: [], customdata: [], text: [] };
    const inert = { x: [], y: [] };
    for (let i = 0; i < data.n; i += 1) {
      if (!view.visible[i] || data.familyOf[i] !== family) continue;
      if (highlightSet.has(i)) continue;
      const rawX = data.t[axis][i];
      const x = rawX == null ? band.sentinel : rawX;
      const y = data.t.viewers[i];
      if (view.passesFilters[i]) {
        active.x.push(x);
        active.y.push(y);
        active.customdata.push(i);
        active.text.push(hoverText(data, i, hoverOpts));
      } else {
        // Filtered-out: no customdata/text needed -- this trace never
        // hovers or clicks (D-15).
        inert.x.push(x);
        inert.y.push(y);
      }
    }
    inertTraces.push({
      type: 'scattergl',
      mode: 'markers',
      meta: `inert:${family}`,
      showlegend: false,
      x: inert.x,
      y: inert.y,
      hoverinfo: 'skip',
      hovertemplate: null,
      marker: {
        color: DIVIDER[theme],
        size: 6,
        opacity: 0.08,
        line: { width: 0 },
      },
    });
    activeTraces.push({
      type: 'scattergl',
      mode: 'markers',
      meta: `family:${family}`,
      showlegend: false,
      x: active.x,
      y: active.y,
      customdata: active.customdata,
      text: active.text,
      hoverinfo: view.hasPersonSelection ? 'skip' : 'all',
      hovertemplate: view.hasPersonSelection ? null : '%{text}<extra></extra>',
      hoverlabel: { bordercolor: FAMILY_COLORS[theme][family] },
      marker: {
        color: FAMILY_COLORS[theme][family],
        size: 6,
        opacity: view.hasPersonSelection ? 0.15 : 1,
        line: { width: 0 },
      },
    });
  }

  const traces = [...inertTraces, ...activeTraces];

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
    htext.push(hoverText(data, i, hoverOpts));
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
    hoverlabel: { bordercolor: hcolor },
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
    showlegend: false,
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
      // Plotly >= 3 takes only the object form; a bare string title is
      // silently dropped (CR-02).
      title: { text: (env.mobile ? XAXIS_TITLES_MOBILE : XAXIS_TITLES)[axis] },
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
      title: { text: 'Viewers (log scale)' },
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
    dragmode: env.mobile ? false : 'zoom',
    // D-04: the 170px right margin only ever made room for Plotly's own
    // legend; the HTML chip row above the chart replaced it, so the margin
    // is the same narrow width at every screen size now.
    margin: { l: 70, r: 24, t: 24, b: 60 },
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
 * Binds the chart's Plotly event handlers once: point click (detail panel
 * hook). Plotly's own legend-click/double-click events have no handler here
 * -- the HTML chip legend (`legend.js`) is a plain DOM click listener wired
 * in `app.js`, entirely outside Plotly's own event system, since every
 * trace now sets `showlegend: false` (D-04).
 * @param {HTMLElement} gd
 * @param {{onPointClick?: (customdata: number) => void}} handlers
 */
export function bindChartEvents(gd, handlers = {}) {
  const { onPointClick } = handlers;

  gd.on('plotly_click', (ev) => {
    const point = ev.points && ev.points[0];
    if (point) onPointClick?.(point.customdata);
  });
}
