/**
 * Bootstrap: fetch `site-data.json`, hold one state object, run the render
 * cycle, keep the URL in sync, wire the chart's DOM controls, and expose
 * `window.__testHooks` (SITE-01, SITE-03, SITE-04, SITE-12, SITE-18, SITE-19,
 * SITE-25, SITE-26, D-22).
 *
 * Wiring only -- every selection/format/chart computation lives in
 * ./modules/*.js. This file never assigns raw markup into the page (T-04-24):
 * every piece of dynamic text below is a DOM attribute/property assignment
 * against already-static HTML, never a markup-injecting API.
 *
 * D-22: `tooltipMode` (default `chart.js`'s `TOOLTIP_MODE`) drives the
 * custom HTML tooltip shown on `plotly_hover`/hidden on `plotly_unhover` --
 * only when the pointer has real hover capability (`hoverNoneMedia`); a
 * touch device keeps tap-to-open-panel and never sees it. `hideTooltip()` is
 * also called at the start of every `render()`, when the detail panel
 * opens, on page scroll, and when the pointer leaves the chart entirely.
 */

import { prepareData } from './modules/data.js';
import { defaultState, computeView, toggleFamilyNetworks } from './modules/select.js';
import { encodeState, decodeState } from './modules/url-state.js';
import { buildFigure, renderChart, bindChartEvents, TOOLTIP_MODE } from './modules/chart.js';
import { initTopbar, renderTopbar } from './modules/topbar.js';
import { initFilters, renderFilters } from './modules/filters.js';
import { initLegend, renderLegend } from './modules/legend.js';
import { renderPanel, openPanel, closePanel } from './modules/panel.js';
import { renderTable } from './modules/table.js';
import { showTooltip, hideTooltip } from './modules/tooltip.js';

const versionMeta = document.querySelector('meta[name="site-data-version"]');
const version = versionMeta ? versionMeta.content : '';

const chartEl = document.getElementById('chart');
const loadErrorEl = document.getElementById('load-error');
const axisToggleEl = document.getElementById('axis-toggle');
const excitementCaptionEl = document.getElementById('excitement-caption');
const panelBodyEl = document.getElementById('panel-body');
const panelTitleEl = document.getElementById('panel-title');
const panelCloseEl = document.getElementById('panel-close');

const darkMedia = window.matchMedia('(prefers-color-scheme: dark)');
const mobileMedia = window.matchMedia('(max-width: 640px)');
const reducedMotionMedia = window.matchMedia('(prefers-reduced-motion: reduce)');
/** True on a touch device with no real hover capability (D-22): these
 * devices keep tap-to-open-panel and never show the hover tooltip. */
const hoverNoneMedia = window.matchMedia('(hover: none)');

/** The custom HTML tooltip's current mode (D-22); `__testHooks.setTooltipMode`
 * is the only way a test flips it to `'plotly'` at runtime. */
let tooltipMode = TOOLTIP_MODE;

/** Number of times the chart has actually been resized for the detail
 * panel's own open/close (D-32: a direct `Plotly.relayout({autosize:
 * true})` call -- see `resizeChartForPanel` below) -- exposed on
 * `__testHooks` so a test can wait deterministically instead of guessing a
 * transition's timing. `relayout` returns a Promise (a `scattergl` redraw
 * is a WebGL draw call, scheduled for a later animation frame, not
 * synchronous), so the counter increments only once the resize itself has
 * actually completed -- incrementing synchronously on call would let a
 * test's wait resolve before the chart visually caught up to its new
 * container width. */
let panelResizes = 0;

/** #chart-area's own container width, last recorded by the ResizeObserver
 * below, or null before its first callback (D-24). */
let lastChartAreaWidth = null;

/** Trailing debounce timer for the ResizeObserver below (D-24). */
let chartAreaResizeTimer = null;

/** The container width `resizeChartForPanel` most recently actually
 * resized the chart to, or null before the first resize (D-32). Checked
 * fresh against `#chart-area`'s *current* width on every call -- whether
 * from the immediate rAF-scheduled path below or the ResizeObserver's own
 * debounced catch-all -- so a call that finds nothing has changed since
 * the last real resize is a cheap no-op (a width/compare read) instead of
 * a redundant `scattergl` redraw (Pitfall 1: this is exactly how the old
 * code's transitionend-triggered resize and its ResizeObserver-debounced
 * resize could both fire for the same width change). */
let lastResizedWidth = null;

const chartAreaEl = document.getElementById('chart-area');

/** `#chart-area`'s current content-box width, matching what the
 * ResizeObserver's own `contentRect.width` reports (border-box
 * `getBoundingClientRect().width` minus horizontal padding) -- or null
 * when `#chart-area` isn't in the DOM. */
function chartAreaContentWidth() {
  if (!chartAreaEl) return null;
  const style = window.getComputedStyle(chartAreaEl);
  const paddingX = parseFloat(style.paddingLeft || '0') + parseFloat(style.paddingRight || '0');
  return Math.round(chartAreaEl.getBoundingClientRect().width - paddingX);
}

/**
 * Resizes the chart for `#chart-area`'s current width (D-32): a direct
 * `Plotly.relayout({autosize: true})` call. The vendored bundle's own
 * `Plotly.Plots` resize helper wraps this exact same relayout call in a
 * further 100ms `setTimeout`, which was the largest single contributor to
 * the measured panel-to-chart lag (04.1-15-SUMMARY.md) -- so that helper is
 * bypassed entirely. `relayout({autosize: true})` only recomputes size when
 * the graph div's `layout.width`/`layout.height` are *not* already set --
 * Plotly bakes in numeric values after every draw (confirmed by reading the
 * vendored resize helper's own source, which deletes them for the same
 * reason before its own relayout call) -- so those are deleted first.
 *
 * A no-op when `#chart-area`'s width hasn't actually changed since the
 * last real resize, so a call from the debounced ResizeObserver catch-all
 * below that finds the immediate rAF path already handled this exact width
 * costs only a width read, not a redundant redraw.
 */
function resizeChartForPanel() {
  const width = chartAreaContentWidth();
  if (width !== null) {
    lastChartAreaWidth = width;
    if (width === lastResizedWidth) return;
    lastResizedWidth = width;
  }
  if (chartEl?.layout) {
    delete chartEl.layout.width;
    delete chartEl.layout.height;
  }
  const result = window.Plotly?.relayout?.(chartEl, { autosize: true });
  if (result && typeof result.then === 'function') {
    result.then(
      () => { panelResizes += 1; },
      () => { panelResizes += 1; },
    );
  } else {
    panelResizes += 1;
  }
}

/** Schedules `resizeChartForPanel` for the next animation frame -- called
 * right after the panel's own `body.panel-open` class toggle (D-32), once
 * that frame's layout (the now-instant grid column snap) is committed.
 * Called from both `openDetailPanel` and `hideDetailPanel` on every
 * viewport: it's cheap and harmless on phones, where `#chart-area`'s width
 * never changes. */
function scheduleChartResize() {
  window.requestAnimationFrame(resizeChartForPanel);
}

if (chartAreaEl && typeof ResizeObserver === 'function') {
  // D-24 belt-and-suspenders: the immediate rAF path above covers every
  // panel open/close, but a path that doesn't fit that (e.g. a user
  // dragging the window edge) still leaves the chart stale. Observing the
  // chart's own container directly catches every width change however it
  // happened, with one mechanism.
  //
  // Pitfall (RESEARCH Pitfall 1): never call Plotly's resize on every
  // ResizeObserver frame -- during a continuous width change (e.g. a user
  // dragging the window edge) that fires once per animation frame, and a
  // scattergl redraw on every frame is the exact mid-drag jank Pitfall 1
  // describes. The first callback only records the container's initial
  // width (ResizeObserver always fires once immediately on `observe()`);
  // every later callback compares against the last recorded width and
  // returns early when unchanged, otherwise records the new width and
  // debounces the actual resize call by 100ms so it runs exactly once
  // after the width settles -- and even then, `resizeChartForPanel`'s own
  // `lastResizedWidth` check (above) makes that debounced call a no-op
  // when the immediate rAF path already resized to this exact width, so a
  // panel open/close never schedules a redundant second redraw.
  const chartAreaObserver = new ResizeObserver((entries) => {
    const entry = entries[0];
    if (!entry) return;
    const width = Math.round(entry.contentRect.width);
    if (lastChartAreaWidth === null) {
      lastChartAreaWidth = width;
      return;
    }
    if (width === lastChartAreaWidth) return;
    lastChartAreaWidth = width;
    window.clearTimeout(chartAreaResizeTimer);
    chartAreaResizeTimer = window.setTimeout(resizeChartForPanel, 100);
  });
  chartAreaObserver.observe(chartAreaEl);
}

// Registered here, at module-evaluation time. This listener runs during
// Escape's dispatch, before the browser's own native `popover` close
// (triggered by the same keypress): when a filter popover or the phone
// filters sheet is open, Escape closes only that popover -- the detail
// panel stays open, and the popover's own 'toggle' listener (filters.js)
// still returns focus to its trigger.
document.addEventListener('keydown', (ev) => {
  if (ev.key !== 'Escape') return;
  if (document.querySelector(':popover-open')) return;
  if (!document.body.classList.contains('panel-open')) return;
  hideDetailPanel();
});

if (panelCloseEl) {
  panelCloseEl.addEventListener('click', () => hideDetailPanel());
}

// D-22 close triggers: the custom HTML tooltip hides on scroll (the anchored
// dot's own screen position moves under it) and when the pointer leaves the
// chart entirely (a `plotly_unhover` for the exact hovered dot already
// covers moving off *that* dot, but not e.g. a fast flick straight off the
// chart's edge). `render()`/`openDetailPanel` call `hideTooltip()` directly,
// below.
window.addEventListener('scroll', () => hideTooltip(), { passive: true });
if (chartEl) {
  chartEl.addEventListener('mouseleave', () => hideTooltip());
}

/** Renderers other plans (04-08..04-10) push into: called every render with {data, state, view, setState}. */
const renderers = [];

let data = null;
let state = null;
let lastView = null;
let revision = 0;

/** Telecast index the detail panel currently shows, or null when it's closed. */
let openPanelIndex = null;

/** The matched-games table's own sort state (kept out of the URL, D-11/SITE-13). */
let sort = { key: 'date', dir: 'asc' };

/** Opens the detail panel on telecast `i` and remembers it's open, for `render`'s own refresh (D-10). */
function openDetailPanel(i) {
  hideTooltip();
  openPanelIndex = i;
  openPanel(i, { data, state, view: lastView });
  scheduleChartResize();
}

/** Closes the detail panel and forgets it's open. */
function hideDetailPanel() {
  openPanelIndex = null;
  closePanel();
  scheduleChartResize();
}

/** Pushed into `renderers`: renders the matched-games table and wires its sort headers and Details buttons. */
function tableRenderer({ data, state, view }) {
  renderTable({
    data,
    view,
    state,
    sort,
    onSort(key) {
      sort =
        sort.key === key
          ? { key, dir: sort.dir === 'asc' ? 'desc' : 'asc' }
          : { key, dir: key === 'date' ? 'asc' : 'desc' };
      render();
    },
    onDetails(i) {
      openDetailPanel(i);
      // D-23: a table row can be far below the fold; bring the chart and
      // the panel beside it into view. Chart dot clicks don't need this --
      // the chart is already visible when a dot is clicked. Phones keep
      // the bottom sheet, which needs no scroll of its own.
      if (!mobileMedia.matches) {
        document.getElementById('chart-area').scrollIntoView({
          block: 'start',
          behavior: reducedMotionMedia.matches ? 'auto' : 'smooth',
        });
      }
    },
  });
}

/** The env object `buildFigure` needs, refreshed on every render. */
function currentEnv() {
  return {
    theme: darkMedia.matches ? 'dark' : 'light',
    mobile: mobileMedia.matches,
    revision,
    tooltipMode,
  };
}

/** Recomputes the view, re-renders the chart, syncs the axis UI and the URL, and runs every registered renderer. */
function render() {
  revision += 1;
  hideTooltip();
  const view = computeView(data, state);
  lastView = view;

  renderChart(chartEl, buildFigure(data, view, state, currentEnv()));

  if (axisToggleEl) {
    for (const button of axisToggleEl.querySelectorAll('button[data-axis]')) {
      button.setAttribute('aria-pressed', String(button.dataset.axis === state.axis));
    }
  }
  if (excitementCaptionEl) {
    excitementCaptionEl.hidden = state.axis !== 'excitement';
  }

  history.replaceState(null, '', location.pathname + encodeState(state, data));

  // Keeps "Selected on this game" (and any other view-derived text) current
  // in an already-open panel when a filter/selection change elsewhere
  // triggers this render, without re-running openPanel's own focus/reveal
  // side effects.
  if (openPanelIndex !== null) {
    renderPanel(panelBodyEl, panelTitleEl, { data, i: openPanelIndex, state, view });
  }

  for (const renderer of renderers) {
    renderer({ data, state, view, setState });
  }
}

/**
 * Applies a partial state patch through one canonicalization path
 * (encodeState -> decodeState), then re-renders.
 * @param {object} patch
 */
function setState(patch) {
  const next = { ...state, ...patch };
  state = decodeState(encodeState(next, data), data);
  render();
}

/** Shows the static #load-error banner and hides the chart, per a failed fetch/parse. */
function showLoadError() {
  if (loadErrorEl) loadErrorEl.hidden = false;
  if (chartEl) chartEl.hidden = true;
  window.__testHooks = { ready: true, failed: true };
}

async function bootstrap() {
  let response;
  try {
    response = await fetch(`site-data.json?v=${encodeURIComponent(version)}`);
  } catch {
    showLoadError();
    return;
  }
  if (!response.ok) {
    showLoadError();
    return;
  }

  let raw;
  try {
    raw = await response.json();
  } catch {
    showLoadError();
    return;
  }

  // Anything past the parse can still throw -- a payload that doesn't fit
  // the shape prepareData expects, a render with Plotly missing (the bundle
  // failed to load or its SRI hash drifted), or a future bug -- and would
  // otherwise leave an empty chart with no explanation (WR-04).
  try {
    if (typeof window.Plotly?.react !== 'function') {
      throw new Error('Plotly bundle not loaded');
    }
    data = prepareData(raw);
    state = decodeState(location.search, data);

    initTopbar({ data, getState: () => state, setState });
    renderers.push(renderTopbar);

    initFilters({ data, getState: () => state, setState });
    renderers.push(renderFilters);

    initLegend({
      listEl: document.getElementById('legend-chips'),
      onToggle: (family) => setState({ networks: toggleFamilyNetworks(data, state, family) }),
    });
    renderers.push(renderLegend);

    renderers.push(tableRenderer);

    if (axisToggleEl) {
      axisToggleEl.addEventListener('click', (ev) => {
        const button = ev.target.closest('button[data-axis]');
        if (!button) return;
        setState({ axis: button.dataset.axis });
      });
    }

    darkMedia.addEventListener('change', () => render());
    mobileMedia.addEventListener('change', () => render());

    // The graph div only gains its `.on()` event-emitter API once Plotly has
    // rendered into it at least once, so the first render must come first.
    render();

    bindChartEvents(chartEl, {
      onPointClick(i) {
        openDetailPanel(i);
      },
      onPointHover(i, ev) {
        if (tooltipMode !== 'html' || hoverNoneMedia.matches) return;
        const point = ev.points && ev.points[0];
        let clientX;
        let clientY;
        if (point && point.x != null && point.y != null) {
          const layout = chartEl._fullLayout;
          const rect = chartEl.getBoundingClientRect();
          clientX = rect.left + layout._size.l + layout.xaxis.d2p(point.x);
          clientY = rect.top + layout._size.t + layout.yaxis.d2p(point.y);
        } else {
          clientX = ev.event?.clientX;
          clientY = ev.event?.clientY;
        }
        showTooltip(data, i, { axis: state.axis, theme: currentEnv().theme, clientX, clientY });
      },
      onPointUnhover() {
        hideTooltip();
      },
    });

    window.__testHooks = {
      ready: true,
      data,
      getState: () => structuredClone(state),
      setState,
      getView: () => ({
        visibleCount: lastView.visibleCount,
        passingCount: lastView.passingCount,
        passesFilters: Array.from(lastView.passesFilters).reduce((acc, v, i) => {
          if (v) acc.push(i);
          return acc;
        }, []),
        hasSelection: lastView.hasSelection,
        hasPersonSelection: lastView.hasPersonSelection,
        highlighted: lastView.highlighted,
        matched: lastView.matched,
        symbols: Object.fromEntries(lastView.symbols),
        altGames: [...lastView.altGames],
        seasonCounts: lastView.seasonCounts,
        summary: lastView.summary,
      }),
      renderers,
      openPanel: (i) => openDetailPanel(i),
      get panelResizes() {
        return panelResizes;
      },
      // D-22: the only way a test flips the tooltip's mode at runtime,
      // proving the fallback path (`hoverText`/Plotly's own hovertemplate,
      // in chart.js) still works end to end.
      setTooltipMode(mode) {
        if (mode !== 'html' && mode !== 'plotly') return;
        tooltipMode = mode;
        hideTooltip();
        render();
      },
      get tooltipMode() {
        return tooltipMode;
      },
    };
  } catch (err) {
    console.error('booth-review: the chart failed to start', err);
    showLoadError();
  }
}

bootstrap();
