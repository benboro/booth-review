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

const versionMeta = document.querySelector('meta[name="site-data-version"]');
const version = versionMeta ? versionMeta.content : '';

const chartEl = document.getElementById('chart');
const loadErrorEl = document.getElementById('load-error');
const axisToggleEl = document.getElementById('axis-toggle');
const excitementCaptionEl = document.getElementById('excitement-caption');

const darkMedia = window.matchMedia('(prefers-color-scheme: dark)');
const mobileMedia = window.matchMedia('(max-width: 640px)');

/** Renderers other plans (04-08..04-10) push into: called every render with {data, state, view, setState}. */
const renderers = [];

let data = null;
let state = null;
let lastView = null;
let revision = 0;

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

  data = prepareData(raw);
  state = decodeState(location.search, data);

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
  });

  window.__testHooks = {
    ready: true,
    data,
    getState: () => structuredClone(state),
    setState,
    getView: () => ({
      visibleCount: lastView.visibleCount,
      highlighted: lastView.highlighted,
      symbols: Object.fromEntries(lastView.symbols),
      altGames: [...lastView.altGames],
      seasonCounts: lastView.seasonCounts,
      summary: lastView.summary,
    }),
    renderers,
  };
}

bootstrap();
