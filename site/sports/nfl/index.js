/**
 * NFL mount module (D-05, D-06, D-07, D-09, D-10, D-11).
 *
 * `mount({ footerEl, search })` builds the NFL regions once, fetches
 * nfl-data.json once (cache 'no-cache'), swaps the footer credits and wires
 * the games table, detail panel, tabs and the four views. `unmount()` hides
 * nothing itself (CSS hides the regions under body[data-sport]); it restores
 * the footer, closes the panel and detaches listeners. State stays in memory.
 *
 * Everything is built with createElement/textContent; no innerHTML.
 */
import { prepareNfl, gameRow } from './data.js';
import { upcomingRow } from './weekend-data.js';
import { currentTheme, onThemeChange } from '../../modules/theme.js';
import { canonicalNflState, tableGames, gamePasses } from './state.js';
import { encodeNflState, decodeNflState } from './url-state.js';
import { createGamesTable } from './table.js';
import { createDetailPanel } from './panel.js';
import { createNflTabs, TAB_LABELS } from './tabs.js';
import { initNflFilters, renderNflFilters, closeNflFilters } from './filters.js';
import * as teamBars from './views/team-bars.js';
import * as crews from './views/crews.js';
import * as viewership from './views/viewership.js';
import * as scatter from './views/scatter.js';
import * as weekend from './views/weekend.js';
import { PHONE_QUERY } from '../../modules/breakpoints.js';
import { waitForFonts, onLateFont } from '../../modules/chart-frame.js';
import { showToolsFor } from './tools.js';

const VIEW_MODULES = { special: teamBars, crews, viewership, scatter, weekend };
const VIEW_IDS = Object.keys(VIEW_MODULES);

const HINTS = {
  special: 'Pick a team bar to see its seasons and games.',
  scatter: '',
};

const METHODOLOGY = 'methodology.html';

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function link(text, href) {
  const a = document.createElement('a');
  a.href = href;
  a.rel = 'noopener noreferrer';
  a.textContent = text;
  return a;
}

// ---- module state (lives across unmount and remount) ----

let regions = null; // { toolbar, selection, chartArea, matched, ... }
let table = null;
let panel = null;
let tabs = null;
let model = null;
let state = null;
let views = null; // id -> { section, mod }
let loadPromise = null;
let loadFailed = false;
let mounted = false;
// Whether the current Booths pick came from a Crews row (memory only; a reload counts it as
// filter-bar made, UI-SPEC Q8).
let boothFromRow = false;
let renderCount = 0;
let lastRows = [];
let footerOriginals = null; // { freshness: Node[], credit: Node[] }
let footerRefs = null; // { freshness, credit }
const mqls = [];
let mqHandler = null;
let stopThemeWatch = null;

const hooks = {
  ready: false,
  failed: false,
  renderCount: 0,
  getState: () => (state ? JSON.parse(JSON.stringify(state)) : null),
  setState: (patch) => setState(patch),
  getTableIndexes: () => lastRows.map((r) => r.i),
  openGame: (i) => openGame(i, undefined),
  closePanel: () => panel && panel.close(),
  pickBoothRow: (key, label) => pickBoothRow(key, label),
  getBoothCatalog: () => (model ? model.boothCatalog.map((e) => ({ key: e.key, label: e.label })) : []),
  getViewModel: (id) => (views && views[id] ? views[id].mod.testModel() : null),
};

// ---- regions ----

function buildRegions(footerEl) {
  const toolbar = el('nav', 'nfl-region');
  toolbar.id = 'nfl-toolbar';
  toolbar.setAttribute('aria-label', 'Filters');

  const selection = el('section', 'nfl-region');
  selection.id = 'nfl-selection-bar';
  selection.setAttribute('aria-label', 'Selection');
  const chips = el('ul', 'nfl-chips');
  chips.id = 'nfl-chips';
  const clearBtn = el('button', 'toggle', 'Clear selection');
  clearBtn.type = 'button';
  clearBtn.id = 'nfl-clear-selection';
  clearBtn.hidden = true;
  const summary = el('p', 'nfl-summary');
  summary.id = 'nfl-summary';
  // The headline is the chart module's title (13-11); it keeps its id.
  const headline = el('h2', 'nfl-headline module-title');
  headline.id = 'nfl-headline';
  // Always-rendered 32px row: chips, Clear selection, then Clear all filters at
  // the right end (filters.js places it; C1).
  const selectionRow = el('div', 'selection-row nfl-selection-row');
  selectionRow.id = 'nfl-selection-row';
  selectionRow.append(chips, clearBtn);
  selection.append(selectionRow, summary);

  const chartArea = el('section', 'nfl-region');
  chartArea.id = 'nfl-chart-area';
  chartArea.setAttribute('aria-label', 'Chart');
  const tabHost = el('div', 'nfl-tabs-host');
  // Module frame (SHELL-06): title (the headline), subtitle (the tab hint, C6) and tools.
  const chartModule = el('div', 'module nfl-chart-module');
  const moduleHead = el('div', 'module-head');
  const hint = el('p', 'module-subtitle');
  hint.id = 'nfl-chart-subtitle';
  hint.setAttribute('role', 'status');
  const tools = el('div', 'module-tools');
  tools.id = 'nfl-chart-tools';
  moduleHead.append(headline, hint, tools);
  const viewHost = el('div', 'nfl-views');
  const status = el('div', 'nfl-status');
  chartModule.append(moduleHead, viewHost, status);
  chartArea.append(tabHost, chartModule);

  const matched = el('section', 'nfl-region');
  matched.id = 'nfl-matched-games';

  const filterLayer = el('div', 'nfl-filter-layer');
  filterLayer.id = 'nfl-filter-layer';

  footerEl.before(toolbar, filterLayer, selection, chartArea, matched);
  return { toolbar, filterLayer, selection, selectionRow, chips, clearBtn, summary, chartArea, tabHost, hint, tools, viewHost, status, matched, headline };
}

function showStatus(kind) {
  const { status } = regions;
  status.replaceChildren();
  if (kind === 'loading') {
    const note = el('div', 'season-empty-note');
    note.setAttribute('role', 'status');
    note.appendChild(el('p', 'season-empty-title', 'Loading NFL data…'));
    status.appendChild(note);
  } else if (kind === 'error') {
    const banner = el('div', 'error-banner');
    banner.setAttribute('role', 'alert');
    banner.append(
      el('p', 'error-title', "Couldn't load the NFL data."),
      el('p', null, 'Check your connection and reload the page. You can still use the CFB view.'),
    );
    status.appendChild(banner);
  }
  status.hidden = kind === 'none';
}

// ---- footer swap (D-10, D-23) ----

function freshnessText() {
  const f = model && model.freshness ? model.freshness : {};
  const sched = f.through_week
    ? `Schedules and scores through Week ${f.through_week}`
    : 'Schedules and scores: not yet available this season';
  const view = f.viewership_through_week
    ? `Viewership through Week ${f.viewership_through_week}`
    : 'Viewership: not yet available this season';
  return `${sched} · ${view}`;
}

function creditNodes() {
  const t = (s) => document.createTextNode(s);
  const BY = 'https://creativecommons.org/licenses/by/4.0/';
  return [
    t('Viewership: '),
    link('RatingsReference.com', 'https://ratingsreference.com'),
    t(' ('),
    link('CC BY 4.0', BY),
    t('), modified: filtered and joined with crew and game data · Schedules and win-probability measures: '),
    link('nflverse', 'https://nflverse.com'),
    t(' ('),
    link('CC BY 4.0', BY),
    t('), modified: derived and joined with crew and viewership data · Scheduling changes: '),
    link('Wikipedia', 'https://www.wikipedia.org'),
    t(' ('),
    link('CC BY-SA 4.0', 'https://creativecommons.org/licenses/by-sa/4.0/'),
    t(') · Crews and networks: '),
    link('506 Sports', 'https://506sports.com'),
  ];
}

function swapFooter(footerEl) {
  const freshness = footerEl.querySelector('.freshness');
  const credit = footerEl.querySelector('.credit-line');
  if (!freshness || !credit) return;
  if (!footerOriginals) {
    footerOriginals = {
      freshness: Array.from(freshness.childNodes),
      credit: Array.from(credit.childNodes),
    };
    footerRefs = { freshness, credit };
    credit.replaceChildren(...creditNodes());
  }
  freshness.replaceChildren(document.createTextNode(freshnessText()));
}

function restoreFooter() {
  if (!footerOriginals) return;
  footerRefs.freshness.replaceChildren(...footerOriginals.freshness);
  footerRefs.credit.replaceChildren(...footerOriginals.credit);
  footerOriginals = null;
  footerRefs = null;
}

// ---- state, URL, rendering ----

function env() {
  return {
    dark: currentTheme() === 'dark',
    mobile: window.matchMedia(PHONE_QUERY).matches,
    hoverNone: window.matchMedia('(hover: none)').matches,
  };
}

function syncUrl() {
  if (!model) return;
  history.replaceState(null, '', location.pathname + encodeNflState(state, model));
}

function personName(id) {
  const idx = model.personIndex.get(id);
  return idx == null ? id : model.people[idx].name;
}

function boothLabel(key) {
  const e = model.boothIndex.get(key);
  return e ? e.label : key;
}

/** `3 of 12 games match`, singular on a one-game day. */
function matchSummary(matching, total) {
  return `${matching} of ${total} ${total === 1 ? 'game matches' : 'games match'}`;
}

function renderSelectionBar() {
  const { chips, clearBtn, summary } = regions;
  const chip = (name, onRemove) => {
    const li = el('li', 'chip');
    li.title = name;
    li.setAttribute('aria-label', name);
    const label = el('span', 'chip-label', name);
    const rm = el('button', 'chip-remove', '×');
    rm.type = 'button';
    rm.setAttribute('aria-label', `Remove ${name}`);
    rm.addEventListener('click', onRemove);
    li.append(label, rm);
    return li;
  };
  chips.replaceChildren(
    ...state.people.map((id) =>
      chip(personName(id), () => setState({ people: state.people.filter((p) => p !== id) }))),
    ...state.booths.map((key) =>
      chip(boothLabel(key), () => setState({ booths: state.booths.filter((k) => k !== key) }))),
  );
  clearBtn.hidden = !state.selection;
  if (state.view === 'weekend') {
    // The weekend view counts the shown day's games (grid and strip), like the CFB summary.
    const c = weekend.summaryCounts();
    summary.textContent = c ? matchSummary(c.matching, c.total) : '';
    return;
  }
  const n = lastRows.length;
  // Same sources tableGames fills the table from; a source that matches nothing still reads
  // "0 games match" rather than falling back to the at-rest line.
  const tableActive = !!state.selection || state.booths.length > 0 || state.people.length > 0
    || state.teams.length > 0;
  if (tableActive) {
    summary.textContent = `${n} ${n === 1 ? 'game matches' : 'games match'}`;
  } else {
    // No selection: the same "N rated of M games" line CFB shows, over the games the filters pass.
    const total = model.cols.season.length;
    let all = 0;
    let rated = 0;
    for (let i = 0; i < total; i += 1) {
      if (!gamePasses(model, state, i)) continue;
      all += 1;
      if (model.cols.viewers[i] != null) rated += 1;
    }
    summary.textContent = all
      ? `${rated.toLocaleString('en-US')} rated of ${all.toLocaleString('en-US')} ${all === 1 ? 'game' : 'games'}`
      : '';
  }
}

/** '{N} games · {first}–{last}' for the active Seasons range and filters. */
function renderHeadline() {
  const n = model.cols.season.length;
  let count = 0;
  for (let i = 0; i < n; i += 1) if (gamePasses(model, state, i)) count += 1;
  const [lo, hi] = state.seasons;
  const span = lo === hi ? String(lo) : `${lo}–${hi}`;
  if (state.view === 'crews' || state.view === 'viewership' || state.view === 'weekend') {
    regions.headline.textContent = TAB_LABELS[state.view];
    return;
  }
  regions.headline.textContent = `${count.toLocaleString('en-US')} ${count === 1 ? 'game' : 'games'} · ${span}`;
}

function renderTable() {
  lastRows = tableGames(model, state).map((i) => gameRow(model, i));
  const filtered = !!state.selection || state.booths.length > 0 || state.people.length > 0;
  let selectionLabel = '';
  if (state.selection && state.selection.label) selectionLabel = String(state.selection.label);
  else {
    const names = [...state.booths.map(boothLabel), ...state.people.map(personName)];
    if (names.length) selectionLabel = names.join(', ');
  }
  table.render(lastRows, { emptyKind: filtered ? 'filtered' : 'nothing', selectionLabel });
}

function renderTabHint() {
  // Viewership and This weekend write their own subtitle through ctx.setSubtitle.
  if (state.view === 'viewership' || state.view === 'weekend') return;
  if (state.view === 'crews') {
    const [lo, hi] = state.seasons;
    regions.hint.textContent = lo === hi ? `Season ${lo}` : `Seasons ${lo}–${hi}`;
    return;
  }
  regions.hint.textContent = state.selection ? '' : HINTS[state.view] ?? '';
}

function showActiveView({ resize }) {
  for (const id of VIEW_IDS) {
    views[id].section.hidden = id !== state.view;
    if (id !== state.view && views[id].mod.deactivate) views[id].mod.deactivate();
  }
  // The matched games table lists played games; This weekend has its own cells and panel.
  regions.matched.hidden = state.view === 'weekend';
  showToolsFor(regions.tools, state.view);
  tabs.setActive(state.view);
  const chartModule = regions.chartArea.querySelector('.nfl-chart-module');
  if (chartModule) chartModule.dataset.view = state.view;
  if (resize) views[state.view].mod.resize();
}

function renderAll({ resize = false } = {}) {
  if (!model || !views) return;
  showActiveView({ resize });
  views[state.view].mod.render(ctx);
  renderTable();
  renderSelectionBar();
  renderHeadline();
  renderTabHint();
  renderNflFilters(ctx);
  renderCount += 1;
  hooks.renderCount = renderCount;
}

function joinNamesAnd(names) {
  if (names.length <= 1) return names.join('');
  return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
}

function announce(text) {
  const seat = document.getElementById('pick-status');
  if (seat) seat.textContent = text;
}

function setState(patch) {
  if (!model) return;
  const prevView = state.view;
  let message = '';
  if (patch) {
    const hasBooths = 'booths' in patch;
    if (Array.isArray(patch.people) && patch.people.length > 0 && boothFromRow && !hasBooths) {
      // D-04: an Announcers pick clears a Booths pick that a row made.
      patch = { ...patch, booths: [] };
      boothFromRow = false;
      message = `Announcers pick set to ${joinNamesAnd(patch.people.map(personName))}. Booths pick cleared.`;
    } else if (hasBooths) {
      boothFromRow = false;
    }
  }
  // Leaving This weekend forgets its week and day, so the tab reopens on the current weekend
  // (18-UI-SPEC; 18-13 F16).
  if (patch && 'view' in patch && patch.view !== 'weekend') patch = { ...patch, week: null, day: null };
  state = canonicalNflState({ ...state, ...(patch || {}) }, model);
  // A selection (team bar, booth, AGOTW season, scatter picks) belongs to the
  // view that made it and only that view keeps it current, so a tab change
  // drops it unless the same patch sets a new one (JS-WR-03, D-09).
  if (state.view !== prevView && !(patch && 'selection' in patch)) state.selection = null;
  syncUrl();
  renderAll({ resize: state.view !== prevView });
  if (message) announce(message);
}

/** D-05: a Crews booth-row pick replaces Booths with that catalog key; the same key clears it. */
function pickBoothRow(key, label) {
  if (!model || !model.boothIndex.has(key)) return;
  const prev = state;
  if (prev.booths.length === 1 && prev.booths[0] === key) {
    setState({ booths: [] });
    announce('Booths pick cleared.');
    return;
  }
  setState({ booths: [key], people: [] });
  boothFromRow = state.booths.length === 1 && state.booths[0] === key;
  let text = `Booths pick set to ${label || boothLabel(key)}.`;
  if (prev.people.length > 0) text += ' Announcers pick cleared.';
  announce(text);
}

function openGame(i, opener) {
  if (!model || !panel || !Number.isInteger(i) || i < 0 || i >= model.n) return;
  panel.open(gameRow(model, i), opener);
}

function openUpcoming(j, opener, { unplayed = true } = {}) {
  const u = model && model.upcomingRaw;
  if (!u || !panel || !Number.isInteger(j) || j < 0 || j >= u.season.length) return;
  panel.open(upcomingRow(model, j, { unplayed }), opener);
}

const ctx = {
  get model() {
    return model;
  },
  getState: () => state,
  setState: (patch) => setState(patch),
  env,
  selectGames: (sel) => setState({ selection: sel }),
  clearSelection: () => setState({ selection: null }),
  openGame: (i, opener) => openGame(i, opener),
  openUpcoming: (j, opener, opts) => openUpcoming(j, opener, opts),
  methodologyHref: (anchor) => (anchor ? `${METHODOLOGY}#${anchor}` : METHODOLOGY),
  pickBoothRow: (key, label) => pickBoothRow(key, label),
  /** Viewership writes its own subtitle row from nodes it built (never HTML strings). */
  setSubtitle: (nodes) => {
    if (regions) regions.hint.replaceChildren(...nodes);
  },
  setTabHint: (text) => {
    if (regions) regions.hint.textContent = text || '';
  },
  /** The chart module header's tools slot (view tools move in here in 13-13). */
  get chartTools() {
    return regions ? regions.tools : null;
  },
};

// ---- load ----

function buildViews() {
  views = {};
  for (const id of VIEW_IDS) {
    const section = el('section', 'nfl-view');
    section.id = `nfl-view-${id}`;
    section.setAttribute('role', 'tabpanel');
    section.setAttribute('aria-labelledby', `nfl-tab-${id}`);
    section.hidden = true;
    regions.viewHost.appendChild(section);
    VIEW_MODULES[id].mount(section, ctx);
    views[id] = { section, mod: VIEW_MODULES[id] };
  }
}

function ensureLoaded(search) {
  if (model || loadPromise) return loadPromise;
  showStatus('loading');
  loadPromise = (async () => {
    try {
      const resp = await fetch('nfl-data.json', { cache: 'no-cache' });
      if (!resp.ok) throw new Error(`nfl-data.json: HTTP ${resp.status}`);
      const raw = await resp.json();
      model = prepareNfl(raw);
      state = decodeNflState(search, model);
      buildViews();
      tabs.setDisabled(false);
      showStatus('none');
      loadFailed = false;
    } catch (_err) {
      model = null;
      loadFailed = true;
      showStatus('error');
      tabs.setDisabled(true);
      table.render([], { emptyKind: 'nothing' });
    } finally {
      loadPromise = null;
    }
  })();
  return loadPromise;
}

function ensureShell(footerEl) {
  if (regions) return;
  regions = buildRegions(footerEl);
  table = createGamesTable(regions.matched, {
    onOpen: (i, button) => openGame(i, button),
  });
  panel = createDetailPanel(document.body, { methodologyHref: METHODOLOGY });
  tabs = createNflTabs(regions.tabHost, {
    onSelect: (id) => setState({ view: id }),
  });
  regions.clearBtn.addEventListener('click', () => setState({ selection: null }));
  initNflFilters({
    toolbar: regions.toolbar,
    chipsHost: regions.chips,
    sheetHost: regions.filterLayer,
    clearHost: regions.selectionRow,
    ctx,
  });
  table.render([], { emptyKind: 'nothing' });
}

function attachMedia() {
  detachMedia();
  mqHandler = () => {
    if (mounted && model && views) views[state.view].mod.render(ctx);
  };
  for (const q of [PHONE_QUERY, '(hover: none)']) {
    const mql = window.matchMedia(q);
    mql.addEventListener('change', mqHandler);
    mqls.push(mql);
  }
  stopThemeWatch = onThemeChange(mqHandler);
}

function detachMedia() {
  for (const mql of mqls) mql.removeEventListener('change', mqHandler);
  mqls.length = 0;
  if (stopThemeWatch) stopThemeWatch();
  stopThemeWatch = null;
}

/**
 * @param {{footerEl: HTMLElement, search?: string}} opts
 */
export async function mount({ footerEl, search = '' } = {}) {
  window.__nflTestHooks = hooks;
  hooks.ready = false;
  mounted = true;
  ensureShell(footerEl);
  swapFooter(footerEl);
  attachMedia();
  // The first draw waits (at most 1500ms, alongside the data) for the faces, as CFB's does, so
  // tick labels and margins do not shift after font swap (13-UI-SPEC "Wait for fonts").
  const [, fontsLoaded] = await Promise.all([ensureLoaded(search), waitForFonts()]);
  if (loadFailed || !model) {
    hooks.failed = true;
    hooks.ready = true;
    return;
  }
  hooks.failed = false;
  if (mounted) {
    swapFooter(footerEl);
    syncUrl();
    renderAll({ resize: true });
    // A face that arrives later re-lays the charts out once.
    if (!fontsLoaded) {
      onLateFont(() => {
        if (mounted) renderAll({ resize: true });
      });
    }
  }
  hooks.ready = true;
}

export function unmount() {
  mounted = false;
  if (panel) panel.close();
  closeNflFilters();
  detachMedia();
  restoreFooter();
}
