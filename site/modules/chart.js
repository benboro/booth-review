/**
 * Chart building and rendering (SITE-01, SITE-03, SITE-04, SITE-12, SITE-18,
 * SITE-23, SITE-25, SITE-26, D-01..D-04, D-08, D-12, D-14, D-15, D-22): two
 * `scattergl` traces per network family -- an "active" trace (dots that
 * pass every filter) and an "inert" trace (dots that fail one, drawn in the
 * family color at the fail tier, D-01/D-02, never hoverable, D-03; Hide mode
 * and Networks leave them undrawn upstream in select.js) --
 * plus a highlight overlay drawn last, the D-03 n/a strip, log-axis ticks,
 * the UI-SPEC's minimal hover content, and the phone/desktop layout.
 * Plotly's own legend is off everywhere (`showlegend: false`); the HTML
 * chip row in `legend.js` replaces it (D-04).
 *
 * `TOOLTIP_MODE` (D-22) picks which of two hover paths `buildFigure` wires
 * up, both fed by the same `tooltip.js` `tooltipModel`:
 *   - 'html' (default): active/highlight traces carry no `text` array and
 *     set `hoverinfo: 'none'`/`hovertemplate: null` (or `'skip'`/`null` for
 *     a person-faded active trace, D-15) -- `hoverinfo: 'none'` still fires
 *     `plotly_hover`/`plotly_click` with no Plotly-drawn label, so
 *     `app.js` can show `tooltip.js`'s custom HTML tooltip instead.
 *   - 'plotly': the exact pre-D-22 trace config -- `text` arrays built by
 *     `hoverText` below and `hovertemplate: '%{text}<extra></extra>'` --
 *     restoring Plotly's own pseudo-HTML hover label.
 * Reverting to 'plotly' is a one-line edit of the constant below; both
 * paths are covered by `tests/e2e/test_site_chart.py`.
 *
 * The inert trace's `hoverinfo: 'skip'` is paired with `hovertemplate: null`
 * on the same trace update -- both are required to actually suppress hover
 * in this vendored Plotly build (the project's own 04-11 finding, STATE.md)
 * -- so an inert dot never takes a hover or a click (D-15). This trace's
 * config is unaffected by `TOOLTIP_MODE`.
 *
 * The "date" axis (04.11, SITE-48) plots each dot at `data.t.dateX` over
 * season blocks: no x title, no N/A strip, no zero line or captions; gap
 * dividers sit between blocks and two label rows (lower ticks, one season
 * annotation per block) are kept right by `fitDateAxis` after every draw.
 * A season filter limits the x range to the shown blocks and drops
 * out-of-range dots from every trace (trace count unchanged).
 *
 * `window.Plotly` is referenced only inside `renderChart`/`bindChartEvents`
 * (never at module scope), so `buildFigure`/`naBand`/`hoverText` stay
 * importable from node for quick checks.
 */

import { ACCENT, DIVIDER, DOT_OUTLINE, FAMILY_COLORS, MUTED, PAGE_BG, SURFACE, ZERO_LINE, familyKey } from './palette.js';
import { MINUS, escapeHover, logTicks, niceLinearTicks } from './format.js';
import { tooltipModel } from './tooltip.js';
import { dateAxisLabels, gapDividers, seasonRange, shownBlocks } from './date-axis.js';
import { gutterPads } from './gutter.js';

/**
 * One-line fallback switch (D-22): set to 'plotly' to restore Plotly's own
 * hovertemplate label; both paths are covered by
 * tests/e2e/test_site_chart.py.
 */
export const TOOLTIP_MODE = 'html';

/**
 * Dot opacity tiers (04.7 UI-SPEC tuning of D-02's 100/45/25/15 targets).
 * Order must stay active > activeUnderPerson > inert > inertUnderPerson;
 * retune here in one line.
 */
export const DOT_OPACITY = Object.freeze({
  active: 1,
  activeUnderPerson: 0.5,
  inert: 0.3,
  inertUnderPerson: 0.15,
});

/** X-axis chart titles (distinct from format.js's shorter AXIS_LABELS toggle copy). */
const XAXIS_TITLES = {
  spread: "Winner's closing spread (points)",
  excitement: 'Excitement index (CFBD)',
};

/**
 * Computes the reserved n/a-strip band for one axis (D-03): a sentinel x for
 * missing values, the numeric-axis divider, the plotted range, and tick
 * values/labels that never fall inside the band.
 * @param {object} data - a `prepareData` result.
 * @param {"spread"|"excitement"|"date"} axis
 * @param {number} [plotPx] - plot width in screen pixels; when given, the range
 *   carries a 10px gutter (04.12 D-02) measured from the n/a sentinel and the max,
 *   never smaller than the legacy pads. Omitted keeps the legacy range.
 * @returns {{sentinel: number, divider: number, range: [number, number], tickvals: number[], ticktext: string[]}}
 */
export function naBand(data, axis, plotPx) {
  let [lo, hi] = data.xRange[axis] || [null, null];
  if (lo == null || hi == null) [lo, hi] = [-1, 1];
  if (axis === 'spread') {
    lo = Math.min(lo, 0);
    hi = Math.max(hi, 0);
  }
  const span = Math.max(hi - lo, 1);
  const w = 0.06 * span;
  const sentinel = lo - 1.5 * w;
  const divider = lo - 0.75 * w;
  let range = [lo - 2.25 * w, hi + 0.03 * span];
  if (plotPx !== undefined) {
    const [padLo, padHi] = gutterPads(hi - sentinel, plotPx, { minLo: 0.75 * w, minHi: 0.03 * span });
    range = [sentinel - padLo, hi + padHi];
  }
  const tickvals = niceLinearTicks(lo, hi, 6);
  const ticktext = tickvals.map((v) => {
    if (axis === 'spread') return v > 0 ? `+${v}` : v < 0 ? `${MINUS}${Math.abs(v)}` : '0';
    return String(v);
  });
  return { sentinel, divider, range, tickvals, ticktext };
}

/**
 * Builds the `<br>`-joined hover text for one telecast (D-22 'plotly'
 * fallback mode only -- the default 'html' mode never calls this and never
 * builds a `text` array at all). Built from the same `tooltip.js`
 * `tooltipModel` the default HTML tooltip renders, so the two modes can
 * never drift on content/order: matchup+score, date+kickoff (a named game
 * appends `namedGameInfo().text` -- the rivalry name, the bowl core name, or
 * "core · round" -- as plain text, since this mode can't draw the HTML
 * tooltip's icons -- and emoji glyphs vary by OS; the time-slot label is
 * panel-only, notes-4 A1),
 * slash-delimited networks (primary first, each colored by its own family --
 * the stand-in for a filled pill in this text-only mode, since Plotly's
 * hover renderer can't draw one, SITE-26), one "Position: Name" line per
 * main-feed crew member, viewers, the active axis value, and a closing
 * "Click for details →" hint. Conferences, the time slot, the full outlet list,
 * the measurement-type badge, era/event flags, and any scoring-source/
 * methodology note are panel-only (SITE-25) -- never repeated here. Each
 * line is built from untrusted data (team/crew/network names) and escaped
 * individually before being joined with the literal `<br>` separators
 * Plotly's pseudo-HTML hover renderer expects (T-04-06): escaping the
 * fully-joined string instead would also escape those `<br>` tags
 * themselves, so Plotly would render the whole tooltip as one unbroken line
 * of visible `&lt;br&gt;` markup rather than as actual line breaks.
 * @param {object} data - a `prepareData` result.
 * @param {number} i - telecast index.
 * @param {{axis: "spread"|"excitement"|"date", theme: "light"|"dark"}} opts
 * @returns {string}
 */
export function hoverText(data, i, { axis, theme }) {
  const model = tooltipModel(data, i, { axis });
  const lines = [];

  lines.push(`<b>${escapeHover(model.title)}</b>`);
  lines.push(escapeHover(model.dateLine));

  // Slash-delimited, primary first, no spaces around '/' (D-25); each name
  // is colored by its own family, standing in for a filled pill (SITE-26).
  // The color comes only from the FAMILY_COLORS constant, never from data.
  const networkSpans = model.networks.map((net) => {
    const name = escapeHover(net.name);
    const color = FAMILY_COLORS[theme][familyKey(net.family)];
    return `<span style="color:${color}">${name}</span>`;
  });
  lines.push(networkSpans.join('/'));

  for (const line of model.crewLines) lines.push(escapeHover(line));

  lines.push(escapeHover(model.viewersLine));
  lines.push(escapeHover(model.axisLine));
  lines.push(escapeHover(model.hint));

  return lines.join('<br>');
}

/**
 * Builds the full Plotly figure (traces, layout, config) for the current
 * data/view/state/env (SITE-01, SITE-03, SITE-04, SITE-18, SITE-23, D-14,
 * D-22). Each family contributes two traces -- pushed inert-first, then
 * active-first, so the trace count stays constant across a re-render for a
 * clean `Plotly.react` diff -- followed by the highlight overlay, always
 * last. `env.tooltipMode` (falling back to the module's own `TOOLTIP_MODE`)
 * picks the active/highlight traces' hover config; see the header comment.
 * @param {object} data - a `prepareData` result.
 * @param {object} view - a `computeView` result.
 * @param {object} state - shaped like `defaultState(data)`.
 * @param {{theme: "light"|"dark", mobile: boolean, revision: number, tooltipMode?: "html"|"plotly", plotWidth?: number}} env
 * @returns {{traces: object[], layout: object, config: object, dateAxis: object|null}}
 */
export function buildFigure(data, view, state, env) {
  const axis = state.axis;
  const isDate = axis === 'date';
  const plotPx = env.plotWidth ?? (env.mobile ? 266 : 1138);
  // Pitfall 9: naBand never sees 'date'; a harmless band keeps every path off a sentinel.
  const band = isDate
    ? { sentinel: 0, divider: 0, range: [0, 1], tickvals: [], ticktext: [] }
    : naBand(data, axis, plotPx);
  // Date x: the numeric dateX column (never the string `t.date`); a dot outside
  // the season filter is not drawn on this axis (D-12).
  const outOfSeasons = (i) =>
    isDate && state.seasons != null && (data.t.season[i] < state.seasons[0] || data.t.season[i] > state.seasons[1]);
  const xOf = (i) => {
    const rawX = isDate ? data.t.dateX[i] : data.t[axis][i];
    return rawX == null ? band.sentinel : rawX;
  };
  const theme = env.theme;
  const hoverOpts = { axis, theme };
  const tooltipMode = env.tooltipMode ?? TOOLTIP_MODE;

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

  // D-22: html mode never needs a per-dot hover string at all (the custom
  // tooltip renders straight from `tooltipModel` on `plotly_hover`, in
  // app.js) -- only the plotly-fallback mode calls `hoverText` and carries a
  // `text` array on the active/highlight traces.
  const usePlotlyText = tooltipMode === 'plotly';
  const activeHoverInfo = usePlotlyText
    ? (view.hasPersonSelection ? 'skip' : 'all')
    : (view.hasPersonSelection ? 'skip' : 'none');
  const activeHoverTemplate = usePlotlyText && !view.hasPersonSelection ? '%{text}<extra></extra>' : null;

  const inertTraces = [];
  const activeTraces = [];
  for (const family of data.families) {
    const active = { x: [], y: [], customdata: [], text: [] };
    const inert = { x: [], y: [] };
    for (let i = 0; i < data.n; i += 1) {
      if (!view.visible[i] || data.familyOf[i] !== family) continue;
      if (highlightSet.has(i)) continue;
      if (outOfSeasons(i)) continue;
      const x = xOf(i);
      const y = data.t.viewers[i];
      if (view.passesFilters[i]) {
        active.x.push(x);
        active.y.push(y);
        active.customdata.push(i);
        if (usePlotlyText) active.text.push(hoverText(data, i, hoverOpts));
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
        color: FAMILY_COLORS[theme][family],
        size: 6,
        opacity: view.hasPersonSelection ? DOT_OPACITY.inertUnderPerson : DOT_OPACITY.inert,
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
      ...(usePlotlyText ? { text: active.text } : {}),
      hoverinfo: activeHoverInfo,
      hovertemplate: activeHoverTemplate,
      hoverlabel: { bordercolor: FAMILY_COLORS[theme][family] },
      marker: {
        color: FAMILY_COLORS[theme][family],
        // D-13/D-14 (04.10): with a filter active, passing dots take the announcer-selected
        // size; filtered-out (inert) dots stay 6; under a person this trace holds the
        // passing-not-theirs dots, which stay inert at activeUnderPerson opacity.
        // Enlarged dots also get a 1px black outline (theme-independent) to separate
        // overlapping 10px dots; unfiltered 6px dots stay borderless.
        // 04.12 D-05: sizing reads view.sizeFilterActive, which ignores a seasons-only filter
        // on the Date axis (seasons there only choose what the axis shows); filterActive
        // still drives the summary.
        size: view.sizeFilterActive ? 10 : 6,
        opacity: view.hasPersonSelection ? DOT_OPACITY.activeUnderPerson : DOT_OPACITY.active,
        line: { width: view.sizeFilterActive ? 1 : 0, color: DOT_OUTLINE },
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
  const hlineWidth = [];
  // D-33 halo: a separate scattergl trace holding just the non-circle
  // highlight points (same x/y/symbol), pushed immediately before the
  // highlight trace below.
  const haloX = [];
  const haloY = [];
  const haloSymbol = [];
  const haloSize = [];
  // D-31/D-33: a scattergl non-circle symbol (square/diamond/triangle-up/
  // star) is drawn from an SDF glyph atlas (regl-scatter2d), and a
  // `marker.line` border on one of those glyphs antialiases into a
  // speckled fringe just outside the shape's edge -- confirmed empirically
  // (04.1-13-SUMMARY.md: 1 ring-speckle pixel per diamond marker with a
  // 1.5px `marker.line` border, 0 with it removed). Circles are drawn
  // analytically and never show the artifact, so they keep the accent
  // `marker.line` border directly. Every other symbol instead gets a
  // solid ACCENT-filled "halo" trace underneath it (meta 'highlight-halo',
  // built just below): the same point, ~3px larger, `line.width` 0,
  // `hoverinfo: 'skip'` and `hovertemplate: null` so it never takes a
  // hover or a click. That restores the same accent border the circles
  // have without ever setting `marker.line` on an SDF glyph.
  for (const i of highlighted) {
    if (outOfSeasons(i)) continue;
    const x = xOf(i);
    const y = data.t.viewers[i];
    hx.push(x);
    hy.push(y);
    hcustomdata.push(i);
    if (usePlotlyText) htext.push(hoverText(data, i, hoverOpts));
    hcolor.push(FAMILY_COLORS[theme][data.familyOf[i]]);
    const symbol = view.symbols.get(i) ?? 'circle';
    hsymbol.push(symbol);
    const size = symbol === 'circle' ? 10 : symbol === 'star' ? 15 : 12;
    hsize.push(size);
    hlineWidth.push(symbol === 'circle' ? 1.5 : 0);
    if (symbol !== 'circle') {
      haloX.push(x);
      haloY.push(y);
      haloSymbol.push(symbol);
      haloSize.push(size + 3);
    }
  }
  if (haloX.length > 0) {
    traces.push({
      type: 'scattergl',
      mode: 'markers',
      meta: 'highlight-halo',
      showlegend: false,
      x: haloX,
      y: haloY,
      hoverinfo: 'skip',
      hovertemplate: null,
      marker: {
        symbol: haloSymbol,
        size: haloSize,
        color: ACCENT[theme],
        opacity: 1,
        line: { width: 0 },
      },
    });
  }
  traces.push({
    type: 'scattergl',
    mode: 'markers',
    meta: 'highlight',
    showlegend: false,
    x: hx,
    y: hy,
    customdata: hcustomdata,
    ...(usePlotlyText ? { text: htext } : {}),
    hoverinfo: usePlotlyText ? 'all' : 'none',
    hovertemplate: usePlotlyText ? '%{text}<extra></extra>' : null,
    hoverlabel: { bordercolor: hcolor },
    marker: {
      color: hcolor,
      size: hsize,
      symbol: hsymbol,
      opacity: 1,
      line: { width: hlineWidth, color: ACCENT[theme] },
    },
  });

  const yTicks = logTicks(data.viewersMin, data.viewersMax);

  let dateAxis = null;
  if (isDate) {
    const blocks = shownBlocks(data.dateAxis, state.seasons);
    const base = seasonRange(data.dateAxis, state.seasons);
    // 04.12 D-01/D-03: DATE_PAD stays block geometry; the outer gutter is measured
    // from the block edge. Inter-season gaps are not plot edges and get no gutter,
    // and a zoom-box edge is not padded. This padded range also feeds the pan
    // limits (minallowed/maxallowed) and the Autoscale put-back.
    const [padLo, padHi] = gutterPads(base[1] - base[0], plotPx);
    const range = [base[0] - padLo, base[1] + padHi];
    const labels = dateAxisLabels(blocks, range, plotPx, { mobile: env.mobile });
    dateAxis = { blocks, range, mobile: env.mobile, labels };
  }

  const layout = {
    datarevision: env.revision,
    // D-13: on Date a season change resets the zoom, other filters keep it.
    uirevision: isDate ? 'date:' + (state.seasons ? state.seasons.join('-') : 'all') : state.axis,
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
      ...(isDate ? {} : { title: { text: XAXIS_TITLES[axis] } }),
      range: isDate ? dateAxis.range.slice() : band.range,
      ...(isDate ? { minallowed: dateAxis.range[0], maxallowed: dateAxis.range[1] } : {}),
      tickmode: 'array',
      tickvals: isDate ? dateAxis.labels.tickvals : band.tickvals,
      ticktext: isDate ? dateAxis.labels.ticktext : band.ticktext,
      ...(isDate
        ? {
            ticks: 'outside',
            ticklen: 4,
            tickcolor: ZERO_LINE[theme],
            tickangle: 0,
            tickfont: { size: env.mobile ? 10 : 14, color: MUTED[theme] },
            showgrid: false,
          }
        : { gridcolor: DIVIDER[theme] }),
      zeroline: false,
      fixedrange: env.mobile,
    },
    yaxis: {
      type: 'log',
      title: { text: 'Viewers (log scale)' },
      tickmode: 'array',
      tickvals: yTicks.tickvals,
      ticktext: yTicks.ticktext,
      // 04.12 D-04 check: the x1.4 log pad is log10(1.4) = 0.146 decade per side; at the
      // 420px minimum plot height (#chart min-height 520 minus margins 100) a 3-decade
      // viewer spread still leaves about 18.7px, over twice the 9px star+halo
      // half-extent, so y needs no gutter (e2e test_site_gutter.py checks >= 10px).
      range: [Math.log10(data.viewersMin / 1.4), Math.log10(data.viewersMax * 1.4)],
      gridcolor: DIVIDER[theme],
      fixedrange: env.mobile,
    },
    shapes: isDate
      ? gapDividers(dateAxis.blocks).map((x) => ({
          type: 'line',
          xref: 'x',
          x0: x,
          x1: x,
          yref: 'paper',
          y0: 0,
          y1: 1,
          layer: 'below',
          line: { width: 1, color: ZERO_LINE[theme] },
        }))
      : [
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
    annotations: isDate
      ? dateAxis.labels.seasons.map((s) => ({
          name: `season-${s.season}`,
          text: `<b>${s.label}</b>`,
          x: s.x,
          xshift: s.xshift,
          visible: s.visible,
          xref: 'x',
          y: 0,
          yref: 'paper',
          yanchor: 'top',
          yshift: env.mobile ? -24 : -28,
          showarrow: false,
          captureevents: false,
          font: { size: env.mobile ? 10 : 14, color: ACCENT[theme] },
        }))
      : [
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
    margin: { l: 70, r: 24, t: 40, b: 60 },
  };

  // D-02: Spread axis only -- appended so shapes[0]/annotations[0] stay the
  // N/A divider and label.
  if (axis === 'spread') {
    layout.shapes.push({
      type: 'line',
      xref: 'x',
      x0: 0,
      x1: 0,
      yref: 'paper',
      y0: 0,
      y1: 1,
      layer: 'below',
      line: { width: 1.5, color: ZERO_LINE[theme], dash: 'solid' },
    });
    const caption = { xref: 'x', x: 0, yref: 'paper', y: 1, yanchor: 'bottom', showarrow: false, captureevents: false, font: { size: env.mobile ? 10 : 14, color: MUTED[theme] } };
    layout.annotations.push(
      { ...caption, text: '← favorite won', xanchor: 'right', xshift: -6 },
      { ...caption, text: 'underdog won →', xanchor: 'left', xshift: 6 },
    );
  }

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

  return { traces, layout, config, dateAxis: isDate ? { blocks: dateAxis.blocks, range: dateAxis.range, mobile: env.mobile } : null };
}

/**
 * Renders `figure` into `gd` via `Plotly.react` -- never the one-shot plot
 * call Pattern 2/Pitfall 4 warn against reusing on updates. `figure.traces`/
 * `layout` must already hold fresh array identities for any changed
 * attribute.
 *
 * The home range is re-saved as the target of double-click and the modebar's
 * "Reset axes" (CR-01) on a `uirevision` change (axis switch, Date season
 * change) and when the home x range moves under the same `uirevision` (a width
 * change moves the pixel gutter, 04.12 D-03). A range the user zoomed or
 * panned away from home is kept through such a re-render, and through every
 * later render under the same `uirevision`.
 * @param {HTMLElement} gd
 * @param {{traces: object[], layout: object, config: object, dateAxis?: object|null}} figure
 */
export function renderChart(gd, figure) {
  gd.boothDateAxis = figure.dateAxis ?? null;
  const home = figure.layout.xaxis.range;
  const prevRev = gd.layout?.uirevision;
  const prevHome = gd.boothHomeX;
  const sameRev = prevRev !== undefined && prevRev === figure.layout.uirevision;
  const homeMoved = sameRev && Array.isArray(prevHome) && !sameRange(prevHome, home);
  const live = gd._fullLayout?.xaxis?.range;
  // Every same-revision render while the user is off home re-asserts the live
  // range, not only one where the home moved: once a width change has passed
  // the live range as input, Plotly's _preGUI no longer records it as a user
  // edit, so a later home input would snap the zoom back (04.11 D-13).
  const awayFromHome = sameRev && Array.isArray(prevHome) && Array.isArray(live) && !sameRange(live, prevHome);
  const layout = awayFromHome
    ? { ...figure.layout, xaxis: { ...figure.layout.xaxis, range: live.slice() } }
    : figure.layout;
  window.Plotly.react(gd, figure.traces, layout, figure.config);
  if ((prevRev !== undefined && !sameRev) || homeMoved) resetHomeRanges(gd, figure.layout);
  if (homeMoved && !awayFromHome) {
    const now = gd._fullLayout?.xaxis?.range;
    if (!Array.isArray(now) || !sameRange(now, home)) {
      window.Plotly.relayout(gd, { 'xaxis.range': home.slice() });
    }
  }
  gd.boothHomeX = Array.isArray(home) ? home.slice() : undefined;
}

/** True when two [lo, hi] ranges agree to within float noise. */
function sameRange(a, b) {
  if (!Array.isArray(a) || !Array.isArray(b) || a.length !== 2 || b.length !== 2) return false;
  const tol = 1e-9 * Math.max(1, Math.abs(b[1] - b[0]));
  return Math.abs(a[0] - b[0]) <= tol && Math.abs(a[1] - b[1]) <= tol;
}

/**
 * Plotly 4.1.1 records each axis's reset target (`_rangeInitial0/1`, read by
 * double-click and "Reset axes") only on the graph's first draw and carries it
 * across every later `Plotly.react`, even when `uirevision` changes. Without
 * this, after Spread -> Date a reset lands on Spread's numbers (a sliver of
 * the first season), and after a season change on Date it lands on the old
 * filter. No public option re-saves it: `doubleClick: 'autosize'` plus
 * dropping the Reset button would also autoscale Spread/Excitement and the
 * y axis to the data. So write the private fields, and only when they exist
 * in the shape Plotly 4.1.1 uses; if a future Plotly renames them this is a
 * no-op and the CR-01 e2e tests fail on the upgrade.
 * @param {HTMLElement} gd
 * @param {object} layout - the layout just passed to `Plotly.react`.
 */
function resetHomeRanges(gd, layout) {
  for (const name of ['xaxis', 'yaxis']) {
    const ax = gd._fullLayout?.[name];
    const range = layout[name]?.range;
    if (!ax || !Array.isArray(range) || range.length !== 2) continue;
    if (!('_rangeInitial0' in ax) || !('_rangeInitial1' in ax)) continue;
    ax._rangeInitial0 = range[0];
    ax._rangeInitial1 = range[1];
    ax._autorangeInitial = false;
  }
}

/** D-02 caption gap from the zero line, in px; `fitZeroCaptions` only ever
 * shrinks it (toward or past the line) when the caption would leave the SVG. */
const ZERO_CAPTION_GAP = 6;
/** Breathing room kept between a nudged caption and the SVG edge, in px. */
const ZERO_CAPTION_EDGE_PAD = 2;

/**
 * Keeps the Spread-axis zero-line captions inside the chart. They hang off
 * x = 0 by `ZERO_CAPTION_GAP`, so when zero sits near an edge (a narrow
 * phone, a zoom, a lopsided range) a caption can run past the SVG and clip.
 * Measures each caption where it was actually drawn (so the real font
 * decides), works out where it would sit at the normal gap, and slides it
 * back in by exactly the overflow -- or back out to the normal gap once
 * there is room again. Idempotent: it only relayouts when the wanted shift
 * differs from the current one, so binding it to `plotly_afterplot` cannot
 * loop.
 * @param {HTMLElement} gd
 */
export function fitZeroCaptions(gd) {
  const anns = gd.layout?.annotations;
  const svg = gd.querySelector('svg.main-svg');
  if (!Array.isArray(anns) || !svg) return;
  const box = svg.getBoundingClientRect();
  const update = {};
  // Zero off the plotted range (a zoom, a pan): Plotly hides or clamps the
  // caption, so its measured box does not follow xshift and chasing it would
  // relayout forever. Park the shift at the normal gap and measure nothing.
  const range = gd._fullLayout?.xaxis?.range;
  const zeroInView = !range || (Math.min(...range) <= 0 && Math.max(...range) >= 0);
  anns.forEach((ann, k) => {
    const side = ann.text === '← favorite won' ? -1 : ann.text === 'underdog won →' ? 1 : 0;
    if (side === 0) return;
    const base = side * ZERO_CAPTION_GAP;
    if (!zeroInView) {
      if (ann.xshift != null && Math.abs(ann.xshift - base) > 0.5) {
        update[`annotations[${k}].xshift`] = base;
      }
      return;
    }
    const el = gd.querySelector(`.annotation[data-index="${k}"]`);
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const shift = ann.xshift ?? base;
    // Overflow past the near SVG edge if the caption sat at the normal gap.
    const overflow =
      side > 0
        ? rect.right + (base - shift) - (box.right - ZERO_CAPTION_EDGE_PAD)
        : box.left + ZERO_CAPTION_EDGE_PAD - (rect.left + (base - shift));
    const want = overflow > 0 ? base - side * overflow : base;
    if (Math.abs(want - shift) > 0.5) update[`annotations[${k}].xshift`] = want;
  });
  if (Object.keys(update).length > 0) window.Plotly.relayout(gd, update);
}

/**
 * Returns a function giving a season label's rendered text width in px, or
 * undefined when no season label is drawn yet (the first draw, where
 * `dateAxisLabels` falls back to its estimate). Clones a drawn season label's
 * `<text>` (keeping Plotly's bold tspan and inline font), swaps in each asked
 * string, measures it in place and removes it at once. Touches no layout, so
 * calling it from `fitDateAxis` cannot trigger another draw; the widths depend
 * only on the font, so every pass measures the same and the hook still settles.
 * @param {HTMLElement} gd
 * @returns {((text: string) => number) | undefined}
 */
export function seasonLabelMeasurer(gd) {
  const anns = gd.layout?.annotations ?? [];
  let template = null;
  for (let k = 0; k < anns.length && !template; k += 1) {
    if (!String(anns[k].name ?? '').startsWith('season-')) continue;
    template = gd.querySelector(`.annotation[data-index="${k}"] text`);
  }
  if (!template || !template.parentNode) return undefined;
  const cache = new Map();
  return (text) => {
    if (cache.has(text)) return cache.get(text);
    const probe = template.cloneNode(true);
    (probe.querySelector('tspan') ?? probe).textContent = text;
    probe.setAttribute('visibility', 'hidden');
    template.parentNode.appendChild(probe);
    const width = probe.getBBox().width;
    probe.remove();
    cache.set(text, width);
    return width;
  };
}

/**
 * Keeps the Date-axis label rows and home range right after every draw,
 * zoom, pan, and resize (D-11, D-12, D-13). Reads the shown blocks from
 * `gd.boothDateAxis` (null off the Date axis, where this is a no-op). Writes
 * the x range only when Plotly autoscaled it (Autoscale, or a double-click
 * that autosizes), putting back the filtered seasons; pans and zooms never
 * leave them because `buildFigure` sets `xaxis.minallowed`/`maxallowed`,
 * which Plotly applies before drawing, so there is nothing to clamp here.
 * Otherwise relayouts only the tick and season-label values that differ from
 * the pure `dateAxisLabels` rule. Compare-before-relayout means the
 * `plotly_afterplot` this triggers finds nothing to change: it never loops.
 * @param {HTMLElement} gd
 */
export function fitDateAxis(gd) {
  const meta = gd.boothDateAxis;
  const xa = gd._fullLayout?.xaxis;
  if (!meta || !xa || !xa.range) return;
  if (gd.layout?.xaxis?.autorange === true) {
    window.Plotly.relayout(gd, { 'xaxis.range': meta.range.slice(), 'xaxis.autorange': false });
    return;
  }
  const want = dateAxisLabels(meta.blocks, xa.range, xa._length, {
    mobile: meta.mobile,
    measure: seasonLabelMeasurer(gd),
  });
  const update = {};
  const round4 = (a) => (a ?? []).map((v) => Math.round(v * 1e4) / 1e4);
  const have = gd.layout.xaxis;
  const sameTicks =
    JSON.stringify(round4(have.tickvals)) === JSON.stringify(round4(want.tickvals)) &&
    JSON.stringify(have.ticktext ?? []) === JSON.stringify(want.ticktext);
  if (!sameTicks) {
    update['xaxis.tickvals'] = want.tickvals;
    update['xaxis.ticktext'] = want.ticktext;
  }
  const anns = gd.layout.annotations ?? [];
  want.seasons.forEach((s, k) => {
    const idx = anns.findIndex((a) => a.name === `season-${s.season}`);
    if (idx < 0) return;
    const a = anns[idx];
    if (Math.abs((a.x ?? 0) - s.x) > 0.01) update[`annotations[${idx}].x`] = s.x;
    if (Math.abs((a.xshift ?? 0) - s.xshift) > 0.5) update[`annotations[${idx}].xshift`] = s.xshift;
    if (a.text !== `<b>${s.label}</b>`) update[`annotations[${idx}].text`] = `<b>${s.label}</b>`;
    if ((a.visible ?? true) !== s.visible) update[`annotations[${idx}].visible`] = s.visible;
  });
  if (Object.keys(update).length > 0) window.Plotly.relayout(gd, update);
}

/**
 * Binds the chart's Plotly event handlers once: point click (detail panel
 * hook) and hover/unhover (D-22: `app.js` uses these to drive the custom
 * HTML tooltip in the default mode; `hoverinfo: 'none'` on the html-mode
 * active/highlight traces still fires `plotly_hover`/`plotly_unhover` with
 * no Plotly-drawn label -- only `hoverinfo: 'skip'` on an inert/faded trace
 * suppresses the event entirely, D-15). Plotly's own legend-click/
 * double-click events have no handler here -- the HTML chip legend
 * (`legend.js`) is a plain DOM click listener wired in `app.js`, entirely
 * outside Plotly's own event system, since every trace now sets
 * `showlegend: false` (D-04). `plotly_relayout` (zoom/pan/resize) calls
 * `onRelayout` so app.js can clear the hover ring.
 * @param {HTMLElement} gd
 * @param {{onPointClick?: (customdata: number) => void, onPointHover?: (customdata: number, ev: object) => void, onPointUnhover?: () => void, onRelayout?: () => void}} handlers
 */
export function bindChartEvents(gd, handlers = {}) {
  const { onPointClick, onPointHover, onPointUnhover, onRelayout } = handlers;

  gd.on('plotly_click', (ev) => {
    const point = ev.points && ev.points[0];
    if (point) onPointClick?.(point.customdata);
  });

  gd.on('plotly_hover', (ev) => {
    const point = ev.points && ev.points[0];
    if (point && point.customdata != null) onPointHover?.(point.customdata, ev);
  });

  gd.on('plotly_unhover', () => onPointUnhover?.());

  // Zoom, pan and autosize all move dots out from under the hover ring.
  gd.on('plotly_relayout', () => onRelayout?.());

  // D-02: every draw (react, resize, zoom) re-fits the zero-line captions.
  gd.on('plotly_afterplot', () => {
    fitZeroCaptions(gd);
    fitDateAxis(gd);
  });
  // Bound after the first render (`.on` only exists then), so that draw's
  // afterplot may already have fired.
  fitZeroCaptions(gd);
  fitDateAxis(gd);
}
