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
 * touch device keeps tap-to-open-panel and never sees it. The hover ring
 * (notes-6) marks the hovered dot in both modes. `clearHover()` (tooltip +
 * ring) runs at the start of every `render()`, when the detail panel opens,
 * on page scroll/resize, on zoom/pan (`plotly_relayout`), and when the
 * pointer leaves the chart entirely.
 */

import { prepareData } from './modules/data.js';
import { defaultState, computeView, toggleFamilyNetworks, familyOnlyPatch, axisPatch, yPatch } from './modules/select.js';
import { encodeState, decodeState } from './modules/url-state.js';
import { buildFigure, renderChart, bindChartEvents, TOOLTIP_MODE } from './modules/chart.js';
import { initTopbar, renderTopbar, renderMapShapeLegend } from './modules/topbar.js';
import { initFilters, renderFilters } from './modules/filters.js';
import { initLegend, renderLegend } from './modules/legend.js';
import { renderPanel, openPanel, closePanel, initPanel } from './modules/panel.js';
import { renderTable } from './modules/table.js';
import { initChartTabs, renderChartTabs, staleCopy } from './modules/chart-tabs.js';
import { chartContext } from './modules/bars.js';
import { initBarsPanel, renderBarsPanel, lastBarsModel, resetBarsTap } from './modules/bars-panel.js';
import { buildMapModel } from './modules/map-model.js';
import { initMapPanel, renderMapPanel, resetMapTap, mapRenderCount } from './modules/map-panel.js';
import { initBandInfo, positionBandInfo, closeBandNote, setBandInfoMode } from './modules/band-info.js';
import { showTooltip, hideTooltip } from './modules/tooltip.js';
import { selectedPersonIndexes } from './modules/format.js';
import { SPORTS, enabledSports, resolveSport } from './sports/registry.js';
import {
  showHoverRing,
  hideHoverRing,
  ringSpecFromPoint,
  hoverRingDiameter,
} from './modules/hover-ring.js';

const versionMeta = document.querySelector('meta[name="site-data-version"]');
const version = versionMeta ? versionMeta.content : '';

const chartEl = document.getElementById('chart');
const loadErrorEl = document.getElementById('load-error');
const axisToggleEl = document.getElementById('axis-toggle');
const yToggleEl = document.getElementById('y-toggle');
const excitementCaptionEl = document.getElementById('excitement-caption');
const panelBodyEl = document.getElementById('panel-body');
const panelTitleEl = document.getElementById('panel-title');
const barsPanelEl = document.getElementById('bars-panel');
const mapPanelEl = document.getElementById('map-panel');
const mapChartEl = document.getElementById('map-chart');
const barsNoteEl = document.getElementById('bars-note');
const eraNoteEl = document.getElementById('era-note');
const shapeLegendEl = document.getElementById('shape-legend');
// Hidden when the selected bar tab no longer applies (D-12); the note shows instead.
const barsOnlyEls = ['bars-title', 'bars-footer', 'bars-captions', 'bars-data'].map((id) =>
  document.getElementById(id),
);

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
// chart's edge). `render()`/`openDetailPanel` call `clearHover()` directly,
// below.
/** Hides the hover tooltip and the hover ring together. */
function clearHover() {
  resetBarsTap();
  resetMapTap();
  hideTooltip();
  hideHoverRing();
}

window.addEventListener('scroll', () => clearHover(), { passive: true });
window.addEventListener('resize', () => clearHover(), { passive: true });
if (chartEl) {
  chartEl.addEventListener('mouseleave', () => clearHover());
}
if (mapChartEl) {
  // On touch the compatibility mouseleave fires right after a tap and would erase the
  // tap tooltip; there the outside-tap listener and the second tap close it instead.
  mapChartEl.addEventListener('mouseleave', () => {
    if (!window.matchMedia('(hover: none)').matches) clearHover();
  });
}

/**
 * The hovered dot's client-pixel position, shared by the tooltip and the ring.
 * The point-based math reaches into undocumented Plotly internals
 * (`_fullLayout`, `_size`, `.d2p`). If a vendored Plotly version reshapes or
 * drops any of them, fall through to the hover event's own client coordinates
 * rather than letting the exception silently swallow the hover (Plotly's
 * event dispatch does not surface a throwing listener to the user).
 */
function pointClientPosition(ev) {
  const point = ev.points && ev.points[0];
  let clientX;
  let clientY;
  try {
    if (point && point.x != null && point.y != null && chartEl._fullLayout) {
      const layout = chartEl._fullLayout;
      const rect = chartEl.getBoundingClientRect();
      // Each event point carries its own axes, so y2 (band) points anchor on y2.
      const xa = point.xaxis ?? layout.xaxis;
      const ya = point.yaxis ?? layout.yaxis;
      clientX = rect.left + xa._offset + xa.l2p(xa.d2l(point.x));
      clientY = rect.top + ya._offset + ya.l2p(ya.d2l(point.y));
    }
  } catch {
    clientX = undefined;
    clientY = undefined;
  }
  if (clientX == null || clientY == null) {
    clientX = ev.event?.clientX;
    clientY = ev.event?.clientY;
  }
  return { clientX, clientY };
}

/** Renderers other plans (04-08..04-10) push into: called every render with {data, state, view, setState}. */
const renderers = [];

let data = null;
let state = null;
let lastView = null;
/** The chart width the scatter was last rendered at, and how many width-only re-renders ran (04.12 D-01). */
let lastScatterWidth = null;
let scatterResizeRenders = 0;
let revision = 0;

/** Whether the scatter's Plotly event handlers are bound (needs one rendered scatter first). */
let scatterBound = false;
/** Which panel the last render showed: 'scatter' | 'bars' | 'map'. */
let lastPanel = null;
/** The Map model of the last Map render, or null before one ran. */
let lastMapModel = null;

/** Telecast index the detail panel currently shows, or null when it's closed. */
let openPanelIndex = null;

/** The matched-games table's own sort state (kept out of the URL, D-11/SITE-13). */
let sort = { key: 'date', dir: 'asc' };

/** Opens the detail panel on telecast `i` and remembers it's open, for `render`'s own refresh (D-10). */
function openDetailPanel(i) {
  clearHover();
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
    chartWidth: chartEl ? chartEl.clientWidth : undefined,
    chartHeight: chartEl ? chartEl.clientHeight : undefined,
  };
}

/** The band's info button and note (04.13 D-12). */
function bandInfoEls() {
  return { button: document.getElementById('band-info'), note: document.getElementById('band-note') };
}

function showBandInfo() {
  const { button, note } = bandInfoEls();
  if (!button) return;
  button.hidden = false;
  positionBandInfo(chartEl, button, note);
}

function hideBandInfo() {
  const els = bandInfoEls();
  if (els.button) els.button.hidden = true;
  closeBandNote(els);
}

/**
 * True while CFB is the sport on screen. CFB's global media/resize listeners
 * and `render()` do nothing otherwise, so they never draw into the hidden CFB
 * regions or write CFB state over the NFL URL (JS-CR-01). `showSport('cfb')`
 * re-renders on the way back. Always true with the NFL flag off.
 */
function cfbActive() {
  return activeSport === 'cfb';
}

/** Recomputes the view, re-renders the chart, syncs the axis UI and the URL, and runs every registered renderer. */
function render() {
  if (!cfbActive()) return;
  revision += 1;
  clearHover();
  const view = computeView(data, state);
  lastView = view;

  const ctx = chartContext(data, state);
  if (state.view === 'scatter') {
    chartEl.hidden = false;
    if (barsPanelEl) barsPanelEl.hidden = true;
    if (mapPanelEl) mapPanelEl.hidden = true;
    renderChart(chartEl, buildFigure(data, view, state, currentEnv()));
    setBandInfoMode(bandInfoEls(), state.y);
    showBandInfo();
    lastScatterWidth = chartEl.clientWidth;
    // The div had no width while hidden (research A4); re-measure once on return.
    if (lastPanel !== null && lastPanel !== 'scatter') window.Plotly.Plots.resize(chartEl);
    if (!scatterBound) {
      bindScatterEvents();
      scatterBound = true;
    }
    lastPanel = 'scatter';
  } else if (state.view === 'map') {
    chartEl.hidden = true;
    if (barsPanelEl) barsPanelEl.hidden = true;
    if (mapPanelEl) mapPanelEl.hidden = false;
    hideBandInfo();
    resetMapTap();
    lastMapModel = buildMapModel(data, view, state);
    renderMapPanel({ data, model: lastMapModel, env: currentEnv(), resize: lastPanel !== 'map' });
    lastPanel = 'map';
  } else {
    chartEl.hidden = true;
    hideBandInfo();
    if (barsPanelEl) barsPanelEl.hidden = false;
    if (mapPanelEl) mapPanelEl.hidden = true;
    const applies = state.view === 'bars' ? ctx.barsEnabled : ctx.butterflyEnabled;
    renderBarsShell(applies);
    if (applies) {
      renderBarsPanel({
        data,
        state,
        view,
        env: { ...currentEnv(), width: document.getElementById('bars-chart').clientWidth },
      });
    }
    lastPanel = 'bars';
  }

  if (axisToggleEl) {
    for (const button of axisToggleEl.querySelectorAll('button[data-axis]')) {
      button.setAttribute('aria-pressed', String(button.dataset.axis === state.axis));
    }
  }
  if (yToggleEl) {
    for (const button of yToggleEl.querySelectorAll('button[data-y]')) {
      button.setAttribute('aria-pressed', String(button.dataset.y === state.y));
    }
  }
  if (excitementCaptionEl) {
    excitementCaptionEl.hidden =
      (state.axis !== 'excitement' && state.y !== 'excitement') || state.view !== 'scatter';
  }
  if (eraNoteEl) eraNoteEl.hidden = state.view !== 'scatter';

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
  const leadKeyEl = document.getElementById('lead-key');
  if (leadKeyEl) leadKeyEl.hidden = state.view !== 'scatter';
  if (state.view === 'map') renderMapShapeLegend(shapeLegendEl, lastMapModel);
  else if (state.view !== 'scatter' && shapeLegendEl) shapeLegendEl.hidden = true;
}

/**
 * Bars/Butterfly panel shell: when the selected tab no longer applies (D-12) the
 * note shows the stale-tab copy in place at the same 520px height; otherwise the
 * note hides and the panel's own elements show. Plan 05 renders the bars here.
 */
function renderBarsShell(applies) {
  const chartBox = document.getElementById('bars-chart');
  if (applies) {
    if (barsNoteEl) barsNoteEl.hidden = true;
    for (const el of barsOnlyEls) if (el) el.hidden = false;
    if (chartBox) chartBox.classList.remove('is-concealed');
    return;
  }
  const copy = staleCopy(state);
  if (barsNoteEl) {
    barsNoteEl.querySelector('.season-empty-title').textContent = copy.title;
    barsNoteEl.querySelector('.season-empty-hint').textContent = copy.hint;
    barsNoteEl.hidden = false;
  }
  for (const el of barsOnlyEls) if (el) el.hidden = true;
  if (chartBox) chartBox.classList.add('is-concealed');
}

/** Binds the scatter's Plotly events; runs once, after the first scatter render. */
function bindScatterEvents() {
  // WR-03: Plotly.react is async, so place the band button once the layout is
  // drawn (first render, width changes, axis switches). Writes no Plotly layout.
  chartEl.on('plotly_afterplot', () => {
    const { button, note } = bandInfoEls();
    if (state.view !== 'scatter' || !button || button.hidden) return;
    positionBandInfo(chartEl, button, note);
  });
  bindChartEvents(chartEl, {
    onPointClick(i) {
      openDetailPanel(i);
    },
    onPointHover(i, ev) {
      if (hoverNoneMedia.matches) return;
      const { clientX, clientY } = pointClientPosition(ev);
      if (Number.isFinite(clientX) && Number.isFinite(clientY)) {
        const { size, symbol } = ringSpecFromPoint(ev.points && ev.points[0]);
        showHoverRing({ i, clientX, clientY, diameter: hoverRingDiameter(size, symbol) });
      }
      if (tooltipMode !== 'html') return;
      showTooltip(data, i, {
        axis: state.axis,
        y: state.y,
        theme: currentEnv().theme,
        clientX,
        clientY,
        selected: selectedPersonIndexes(data, state),
      });
    },
    onPointUnhover() {
      clearHover();
    },
    onRelayout() {
      clearHover();
    },
  });
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

async function startCfb(search = location.search) {
  cfbStarted = true;
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
    state = decodeState(search, data);

    initTopbar({ data, getState: () => state, setState });
    renderers.push(renderTopbar);

    initFilters({ data, getState: () => state, setState });
    renderers.push(renderFilters);

    initLegend({
      listEl: document.getElementById('legend-chips'),
      onToggle: (family) => setState({ networks: toggleFamilyNetworks(data, state, family) }),
      onOnly: (family, before) => setState(familyOnlyPatch(data, lastView, family, before)),
      getNetworks: () => structuredClone(state.networks),
      switchEl: document.getElementById('dots-toggle'),
      onDots: (dots) => setState({ dots }),
    });
    renderers.push(renderLegend);

    initBandInfo(bandInfoEls());

    initChartTabs({ data, getState: () => state, setState });
    renderers.push(renderChartTabs);

    initMapPanel();

    initBarsPanel({ data, getState: () => state, setState, rerender: render });

    let resizeTimer = null;
    window.addEventListener('resize', () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        if (!cfbActive()) return;
        if (state.view === 'butterfly' && !mobileMedia.matches) render();
        // 04.12 D-01: the gutter is converted from screen px using the plot
        // width, so a width change must rebuild the range. Height-only
        // changes (phone URL bar) leave clientWidth alone and do nothing.
        if (state.view === 'scatter' && chartEl.clientWidth !== lastScatterWidth) {
          lastScatterWidth = chartEl.clientWidth;
          scatterResizeRenders += 1;
          renderChart(chartEl, buildFigure(data, lastView, state, currentEnv()));
          showBandInfo();
        }
      }, 150);
    });

    renderers.push(tableRenderer);

    if (axisToggleEl) {
      axisToggleEl.addEventListener('click', (ev) => {
        const button = ev.target.closest('button[data-axis]');
        if (!button) return;
        setState(axisPatch(button.dataset.axis, state));
      });
    }

    if (yToggleEl) {
      yToggleEl.addEventListener('click', (ev) => {
        const button = ev.target.closest('button[data-y]');
        if (!button) return;
        setState(yPatch(button.dataset.y, state));
      });
    }

    darkMedia.addEventListener('change', () => {
      if (cfbActive()) render();
    });
    mobileMedia.addEventListener('change', () => {
      if (cfbActive()) render();
    });

    // The graph div only gains its `.on()` event-emitter API once Plotly has
    // rendered into it at least once, so the first render must come first.
    render();

    window.__testHooks = {
      get scatterResizeRenders() {
        return scatterResizeRenders;
      },
      ready: true,
      data,
      nRated: data.nRated,
      nGames: data.n,
      getState: () => structuredClone(state),
      getBarsModel: () => structuredClone(lastBarsModel()),
      setState,
      getView: () => ({
        visibleCount: lastView.visibleCount,
        passingCount: lastView.passingCount,
        passesFilters: Array.from(lastView.passesFilters).reduce((acc, v, i) => {
          if (v) acc.push(i);
          return acc;
        }, []),
        hasSelection: lastView.hasSelection,
        filterActive: lastView.filterActive,
        enlargeDots: lastView.enlargeDots,
        drawnFaded: lastView.drawnFaded,
        hasPersonSelection: lastView.hasPersonSelection,
        hasGameSelection: lastView.hasGameSelection,
        highlighted: lastView.highlighted,
        matched: lastView.matched,
        symbols: Object.fromEntries(lastView.symbols),
        altGames: [...lastView.altGames],
        seasonCounts: lastView.seasonCounts,
        facets: {
          total: lastView.facets.total,
          seasons: Object.fromEntries(lastView.facets.seasons),
          networks: Array.from(lastView.facets.networks),
          slots: { ...lastView.facets.slots },
          conferences: Object.fromEntries(lastView.facets.conferences),
          schools: Array.from(lastView.facets.schools),
          postseason: { ...lastView.facets.postseason },
          games: Array.from(lastView.facets.games),
          role: { ...lastView.facets.role },
          people: Array.from(lastView.facets.people),
        },
        summary: lastView.summary,
      }),
      renderers,
      get mapRenders() {
        return mapRenderCount();
      },
      getMapModel: () => {
        const m = lastMapModel;
        if (!m) return null;
        return {
          hasSubject: m.hasSubject,
          subjects: m.subjects.map(({ kind, key, label, symbol }) => ({ kind, key, label, symbol })),
          shapesCapped: m.shapesCapped,
          hasShared: m.hasShared,
          dots: structuredClone(m.dots),
          faded: structuredClone(m.faded),
          legs: m.legs.map((leg) => ({
            subject: leg.subject,
            season: leg.season,
            from: leg.from,
            to: leg.to,
            family: leg.family,
            pointCount: leg.points.length,
            first: leg.points[0],
            last: leg.points[leg.points.length - 1],
          })),
          markers: structuredClone(m.markers),
          noLocationCount: m.noLocationCount,
          drawnCount: m.drawnCount,
          emptyAll: m.emptyAll,
          venueGames: Object.fromEntries(m.venueGames),
        };
      },
      get lastPanel() {
        return lastPanel;
      },
      openPanel: (i) => openDetailPanel(i),
      closePanel: () => hideDetailPanel(),
      // D-22: the only way a test flips the tooltip's mode at runtime,
      // proving the fallback path (`hoverText`/Plotly's own hovertemplate,
      // in chart.js) still works end to end.
      setTooltipMode(mode) {
        if (mode !== 'html' && mode !== 'plotly') return;
        tooltipMode = mode;
        clearHover();
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

let cfbStarted = false;
/** Loaded non-CFB sport modules by registry id. */
const sportModules = new Map();
let activeSport = null;
/**
 * Per sport, the query it decodes its first state from: the page's own query
 * when it opened on that sport, else '' so a CFB link's shared params
 * (`seasons`, `people`, `y`, `dots`) never leak into its state (JS-CR-02).
 */
const sportInitialSearch = new Map();
/** Bumped by every sport change, so an NFL switch whose module import resolves late can tell it was superseded. */
let switchSeq = 0;

/** The query with only the sport param removed, other params kept in order. */
function searchWithoutSport(search) {
  const params = new URLSearchParams(search);
  params.delete('sport');
  const rest = params.toString();
  return rest ? `?${rest}` : '';
}

function sportMeta(id) {
  return SPORTS.find((s) => s.id === id);
}

const SPORT_ERROR_ID = 'sport-load-error';

/**
 * The URL a reload should open: the page's own query when it opened on that
 * sport (a shared link keeps its state), else the sport at its defaults.
 */
function sportReloadUrl(id) {
  return location.pathname + (sportInitialSearch.get(id) || `?sport=${id}`);
}

/**
 * Shown in NFL's place when the NFL modules failed to load (JS-WR-02, iter-2
 * WR-03). The browser keeps a failed module fetch for the document's lifetime,
 * for every module the NFL entry imports, so no in-page retry can recover;
 * a fresh document can. The page stays on NFL with the NFL URL (never CFB's,
 * IN-02), so a reload or a shared link opens NFL, and the button reloads it.
 */
function showSportLoadError(id) {
  const url = sportReloadUrl(id);
  if (location.pathname + location.search !== url) history.replaceState(null, '', url);
  // A banner for another sport (its text and reload target) must not outlive a new failure.
  const existing = document.getElementById(SPORT_ERROR_ID);
  if (existing?.dataset.sport === id) return;
  existing?.remove();
  const banner = document.createElement('section');
  banner.id = SPORT_ERROR_ID;
  banner.dataset.sport = id;
  banner.className = 'error-banner';
  banner.setAttribute('role', 'alert');
  const title = document.createElement('p');
  title.textContent = `Couldn't load the ${sportMeta(id).label} view.`;
  const hint = document.createElement('p');
  hint.textContent = 'Check your connection, then reload the page. CFB is still one click away on the switch above.';
  const reload = document.createElement('button');
  reload.type = 'button';
  reload.className = 'toggle';
  reload.textContent = 'Reload page';
  reload.addEventListener('click', () => {
    location.assign(sportReloadUrl(id));
  });
  banner.append(title, hint, reload);
  document.getElementById('chart-area')?.before(banner);
}

function clearSportLoadError() {
  document.getElementById(SPORT_ERROR_ID)?.remove();
}

async function showSport(id) {
  if (id === activeSport) return;
  activeSport = id;
  switchSeq += 1;
  const seq = switchSeq;
  for (const btn of document.querySelectorAll('#sport-switch button[data-sport]')) {
    btn.setAttribute('aria-pressed', btn.dataset.sport === id ? 'true' : 'false');
  }
  const status = document.getElementById('sport-status');
  if (status) status.textContent = `Showing ${sportMeta(id).label} games.`;
  for (const pop of document.querySelectorAll(':popover-open')) pop.hidePopover();
  if (openPanelIndex !== null) hideDetailPanel();
  window.scrollTo(0, 0);

  if (id !== 'cfb') {
    const entry = sportMeta(id);
    // Only one non-CFB view is mounted at a time.
    for (const [otherId, mod] of sportModules) if (otherId !== id) mod.unmount();
    document.body.dataset.sport = id;
    document.title = entry.title;
    try {
      if (!sportModules.has(id)) sportModules.set(id, await import(`./sports/${entry.module.replace(/^\.\//, '')}`));
    } catch (err) {
      // A network blip, a deploy swapping the module files, or a module that
      // throws on load: say so with a reload button instead of an empty page
      // (JS-WR-02, iter-2 WR-03). Nothing to say when a later switch took
      // over or the view loaded meanwhile (IN-01); the switch stays free for CFB.
      console.error(`booth-review: the ${entry.label} view failed to load`, err);
      if (seq !== switchSeq || activeSport !== id || sportModules.has(id)) return;
      showSportLoadError(id);
      return;
    }
    clearSportLoadError();
    // The user switched sport while the module loaded: mounting now would put
    // its footer, listeners and URL behind the other view (JS-WR-01).
    if (seq !== switchSeq) return;
    const mod = sportModules.get(id);
    await mod.mount({ footerEl: document.getElementById('site-footer'), search: sportInitialSearch.get(id) ?? '' });
    if (activeSport !== id) mod.unmount();
    return;
  }
  for (const mod of sportModules.values()) mod.unmount();
  clearSportLoadError();
  document.body.dataset.sport = 'cfb';
  document.title = sportMeta('cfb').title;
  if (!cfbStarted) {
    // The page opened on an NFL URL: its params belong to the NFL side (the
    // shared `seasons` would otherwise leak into CFB state), so CFB starts at
    // its defaults.
    await startCfb('');
  } else if (data) {
    render();
    history.replaceState(null, '', location.pathname + encodeState(state, data));
  }
}

function main() {
  const initialSearch = location.search;
  const enabled = enabledSports(document.querySelector('meta[name="booth-review-sports"]'));
  const sport = resolveSport(initialSearch, enabled);
  if (sport !== 'cfb') sportInitialSearch.set(sport, initialSearch);
  if (sport === 'cfb' && new URLSearchParams(initialSearch).has('sport')) {
    history.replaceState(null, '', location.pathname + searchWithoutSport(initialSearch));
  }
  const switchEl = document.getElementById('sport-switch');
  if (switchEl) {
    for (const btn of switchEl.querySelectorAll('button[data-sport]')) {
      btn.addEventListener('click', () => {
        showSport(btn.dataset.sport);
      });
    }
    const topbar = document.getElementById('topbar');
    const status = document.createElement('p');
    status.id = 'sport-status';
    status.className = 'visually-hidden';
    status.setAttribute('role', 'status');
    topbar.appendChild(status);
  }
  if (sport !== 'cfb') {
    showSport(sport);
  } else {
    activeSport = 'cfb';
    startCfb();
  }
}

main();
