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
import { renderPanel, openPanel, closePanel, initPanel } from './modules/panel.js';
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

const darkMedia = window.matchMedia('(prefers-color-scheme: dark)');
const mobileMedia = window.matchMedia('(max-width: 640px)');
/** True on a touch device with no real hover capability (D-22): these
 * devices keep tap-to-open-panel and never show the hover tooltip. */
const hoverNoneMedia = window.matchMedia('(hover: none)');

/** The custom HTML tooltip's current mode (D-22); `__testHooks.setTooltipMode`
 * is the only way a test flips it to `'plotly'` at runtime. */
let tooltipMode = TOOLTIP_MODE;


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
}

/** Closes the detail panel and forgets it's open. */
function hideDetailPanel() {
  closePanel();
}

// The dialog's close event (x, Escape, backdrop) is the one place the open index clears.
initPanel({
  onClosed: () => {
    openPanelIndex = null;
  },
});

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
        // The point-based position math below reaches into undocumented
        // Plotly internals (`_fullLayout`, `_size`, `.d2p`). If a vendored
        // Plotly version reshapes or drops any of them, fall through to the
        // hover event's own client coordinates rather than letting the
        // exception silently swallow the tooltip (Plotly's event dispatch
        // does not surface a throwing listener to the user).
        try {
          if (point && point.x != null && point.y != null && chartEl._fullLayout) {
            const layout = chartEl._fullLayout;
            const rect = chartEl.getBoundingClientRect();
            clientX = rect.left + layout._size.l + layout.xaxis.d2p(point.x);
            clientY = rect.top + layout._size.t + layout.yaxis.d2p(point.y);
          }
        } catch {
          clientX = undefined;
          clientY = undefined;
        }
        if (clientX == null || clientY == null) {
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
      closePanel: () => hideDetailPanel(),
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
