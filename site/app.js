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
import { defaultState, computeView } from './modules/select.js';
import { encodeState, decodeState } from './modules/url-state.js';
import { buildFigure, renderChart, bindChartEvents } from './modules/chart.js';
import { initTopbar, renderTopbar } from './modules/topbar.js';
import { initFilters, renderFilters } from './modules/filters.js';
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

const darkMedia = window.matchMedia('(prefers-color-scheme: dark)');
const mobileMedia = window.matchMedia('(max-width: 640px)');

// Registered here, at module-evaluation time, so this listener runs before
// filters.js's own Escape handler (registered later, inside `initFilters`
// during `bootstrap`): when the phone filters drawer is open, Escape closes
// only the drawer, never the detail panel too.
document.addEventListener('keydown', (ev) => {
  if (ev.key !== 'Escape') return;
  if (document.body.classList.contains('filters-open')) return;
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

/** Opens the detail panel on telecast `i` and remembers it's open, for `render`'s own refresh (D-10). */
function openDetailPanel(i) {
  openPanelIndex = i;
  openPanel(i, { data, state, view: lastView });
}

/** Closes the detail panel and forgets it's open. */
function hideDetailPanel() {
  openPanelIndex = null;
  closePanel();
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

/** Network ids for every primary network in a given family. */
function familyNetworkIds(key) {
  return (data.networksByFamily.get(key) ?? []).map((idx) => data.lookups.networks[idx].id);
}

/** Network ids for every primary network across all families (the "unfiltered" set). */
function allPrimaryNetworkIds() {
  return data.primaryNetworks.map((idx) => data.lookups.networks[idx].id);
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
      onLegendClick(key) {
        const current = state.networks ?? allPrimaryNetworkIds();
        const famIds = familyNetworkIds(key);
        const everyFamIdIncluded = famIds.every((id) => current.includes(id));
        const next = everyFamIdIncluded
          ? current.filter((id) => !famIds.includes(id))
          : Array.from(new Set([...current, ...famIds]));
        setState({ networks: next });
      },
      onLegendDoubleClick(key) {
        const current = state.networks ?? allPrimaryNetworkIds();
        const famIds = familyNetworkIds(key);
        const isExactlyFamily = current.length === famIds.length && famIds.every((id) => current.includes(id));
        setState({ networks: isExactlyFamily ? null : famIds });
      },
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
    };
  } catch (err) {
    console.error('booth-review: the chart failed to start', err);
    showLoadError();
  }
}

bootstrap();
