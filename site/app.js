/**
 * Bootstrap: fetch `site-data.json`, hold one state object, run the render
 * cycle, keep the URL in sync, wire the chart's DOM controls, and expose
 * `window.__testHooks` (SITE-01, SITE-03, SITE-04, SITE-12, SITE-18, SITE-19).
 *
 * Wiring only -- every selection/format/chart computation lives in
 * ./modules/*.js. This file never assigns raw markup into the page (T-04-24):
 * every piece of dynamic text below is a DOM attribute/property assignment
 * against already-static HTML, never a markup-injecting API.
 */

import { prepareData } from './modules/data.js';
import { defaultState, computeView, toggleFamilyNetworks } from './modules/select.js';
import { encodeState, decodeState } from './modules/url-state.js';
import { buildFigure, renderChart, bindChartEvents } from './modules/chart.js';
import { initTopbar, renderTopbar } from './modules/topbar.js';
import { initFilters, renderFilters } from './modules/filters.js';
import { initLegend, renderLegend } from './modules/legend.js';
import { renderPanel, openPanel, closePanel } from './modules/panel.js';
import { renderTable } from './modules/table.js';

const versionMeta = document.querySelector('meta[name="site-data-version"]');
const version = versionMeta ? versionMeta.content : '';

const chartEl = document.getElementById('chart');
const loadErrorEl = document.getElementById('load-error');
const axisToggleEl = document.getElementById('axis-toggle');
const excitementCaptionEl = document.getElementById('excitement-caption');
const panelBodyEl = document.getElementById('panel-body');
const panelTitleEl = document.getElementById('panel-title');
const panelCloseEl = document.getElementById('panel-close');
const panelEl = document.getElementById('detail-panel');

const darkMedia = window.matchMedia('(prefers-color-scheme: dark)');
const mobileMedia = window.matchMedia('(max-width: 640px)');
const reducedMotionMedia = window.matchMedia('(prefers-reduced-motion: reduce)');

/** Number of times `Plotly.Plots.resize` has *finished* for the detail
 * panel's own open/close (belt-and-suspenders alongside
 * `config.responsive: true`'s internal ResizeObserver, Pattern 1) --
 * exposed on `__testHooks` so a test can wait deterministically instead of
 * guessing a transition's timing. `Plotly.Plots.resize` returns a Promise
 * (a `scattergl` redraw is a WebGL draw call, scheduled for a later
 * animation frame, not synchronous), so the counter increments only once
 * the resize itself has actually completed -- incrementing synchronously
 * on call would let a test's wait resolve before the chart visually
 * caught up to its new container width. */
let panelResizes = 0;

/** Resizes the chart for the panel's own width change, and counts it once the resize itself settles. */
function resizeChartForPanel() {
  const result = window.Plotly?.Plots?.resize?.(chartEl);
  if (result && typeof result.then === 'function') {
    result.then(
      () => { panelResizes += 1; },
      () => { panelResizes += 1; },
    );
  } else {
    panelResizes += 1;
  }
}

if (panelEl) {
  // The deterministic desktop/tablet path: once the panel column's own
  // `width` transition finishes, resize the chart for its new container
  // width (Pattern 1). Guarded to this element/property so a transition on
  // some other panel-inner property (or a future added property) doesn't
  // double-fire it.
  panelEl.addEventListener('transitionend', (ev) => {
    if (ev.target !== panelEl || ev.propertyName !== 'width') return;
    resizeChartForPanel();
  });
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

/** No `transitionend` fires when the panel's width change is instant
 * (reduced motion) or the panel is a phone bottom sheet with no width
 * transition of its own -- these paths need their own resize call, since
 * the `transitionend` listener above never runs for them (Pattern 1). */
function resizeChartForPanelIfNoTransition() {
  if (!reducedMotionMedia.matches && !mobileMedia.matches) return;
  window.requestAnimationFrame(resizeChartForPanel);
}

/** Opens the detail panel on telecast `i` and remembers it's open, for `render`'s own refresh (D-10). */
function openDetailPanel(i) {
  openPanelIndex = i;
  openPanel(i, { data, state, view: lastView });
  resizeChartForPanelIfNoTransition();
}

/** Closes the detail panel and forgets it's open. */
function hideDetailPanel() {
  openPanelIndex = null;
  closePanel();
  resizeChartForPanelIfNoTransition();
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
    },
  });
}

/** The env object `buildFigure` needs, refreshed on every render. */
function currentEnv() {
  return {
    theme: darkMedia.matches ? 'dark' : 'light',
    mobile: mobileMedia.matches,
    revision,
  };
}

/** Recomputes the view, re-renders the chart, syncs the axis UI and the URL, and runs every registered renderer. */
function render() {
  revision += 1;
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
    };
  } catch (err) {
    console.error('booth-review: the chart failed to start', err);
    showLoadError();
  }
}

bootstrap();
