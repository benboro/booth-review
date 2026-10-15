/**
 * MLB mount module (D-01, D-02, D-03, D-22).
 *
 * `mount({ footerEl, search })` builds the MLB regions once, fetches
 * mlb-data.json once (cache 'no-cache'), swaps the footer credits and wires
 * the games table, detail panel and tabs. `unmount()` hides nothing itself
 * (CSS hides the regions under body[data-sport]); it restores the footer,
 * closes the panel and detaches listeners. State stays in memory.
 *
 * Everything is built with createElement and textContent only.
 */
import { prepareMlb, gameRow, boothLabelOf } from './data.js';
import { canonicalMlbState, tableGames, selectionLabel } from './state.js';
import { encodeMlbState, decodeMlbState } from './url-state.js';
import { createGamesTable } from './table.js';
import { createDetailPanel, RETROSHEET_NOTICE, RETROSHEET_CONTACT } from './panel.js';
import { createMlbTabs } from './tabs.js';
import * as appleView from './views/apple.js';

// View id -> module (mount, render, resize, testModel); the tab bar renders from this map.
const VIEW_MODULES = { apple: appleView };
const VIEW_IDS = Object.keys(VIEW_MODULES);

const HINTS = {
  apple: 'Pick a booth to list its games.',
  postseason: 'Pick a postseason cell to list its games.',
};

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

let regions = null;
let table = null;
let panel = null;
let tabs = null;
let model = null;
let state = null;
let views = null; // id -> { section, mod }
let loadPromise = null;
let loadFailed = false;
let mounted = false;
let renderCount = 0;
let lastRows = [];
let pendingOpener = null;
let footerOriginals = null; // { freshness: Node[], credit: Node[] }
let footerRefs = null; // { freshness, credit }
const mqls = [];
let mqHandler = null;

const hooks = {
  ready: false,
  failed: false,
  renderCount: 0,
  getState: () => (state ? JSON.parse(JSON.stringify(state)) : null),
  setState: (patch) => setState(patch),
  getTableIndexes: () => lastRows.map((r) => r.i),
  openGame: (i) => openGame(i, undefined),
  closePanel: () => panel && panel.close(),
  getBoothCatalog: () => (model
    ? model.appleBooths.map((b, k) => ({ key: String(k), label: boothLabelOf(model, b.pbp, b.analyst) }))
    : []),
  getViewModel: (id) => (views && views[id] ? views[id].mod.testModel() : null),
};

// ---- regions ----

function buildRegions(footerEl) {
  const toolbar = el('nav', 'nfl-region');
  toolbar.id = 'mlb-toolbar';
  toolbar.setAttribute('aria-label', 'Filters');

  const selection = el('section', 'nfl-region');
  selection.id = 'mlb-selection-bar';
  selection.setAttribute('aria-label', 'Selection');
  const chips = el('ul', 'nfl-chips');
  chips.id = 'mlb-chips';
  const clearBtn = el('button', 'toggle', 'Clear selection');
  clearBtn.type = 'button';
  clearBtn.id = 'mlb-clear-selection';
  clearBtn.hidden = true;
  const summary = el('p', 'nfl-summary');
  summary.id = 'mlb-summary';
  const headline = el('h2', 'nfl-headline');
  headline.id = 'mlb-headline';
  selection.append(chips, clearBtn, summary, headline);

  const chartArea = el('section', 'nfl-region');
  chartArea.id = 'mlb-chart-area';
  chartArea.setAttribute('aria-label', 'Chart');
  const tabHost = el('div', 'nfl-tabs-host');
  const hint = el('p', 'tab-hint');
  hint.id = 'mlb-tab-hint';
  hint.setAttribute('role', 'status');
  const viewHost = el('div', 'nfl-views');
  const status = el('div', 'nfl-status');
  chartArea.append(tabHost, hint, viewHost, status);

  const matched = el('section', 'nfl-region');
  matched.id = 'mlb-matched-games';

  footerEl.before(toolbar, selection, chartArea, matched);
  return { toolbar, selection, chips, clearBtn, summary, chartArea, tabHost, hint, viewHost, status, matched, headline };
}

function showStatus(kind) {
  const { status } = regions;
  status.replaceChildren();
  if (kind === 'loading') {
    const note = el('div', 'season-empty-note');
    note.setAttribute('role', 'status');
    note.appendChild(el('p', 'season-empty-title', 'Loading MLB data…'));
    status.appendChild(note);
  } else if (kind === 'error') {
    const banner = el('div', 'error-banner');
    banner.setAttribute('role', 'alert');
    banner.append(
      el('p', 'error-title', "Couldn't load the MLB data."),
      el('p', null, 'Check your connection and reload the page. You can still use the CFB view.'),
    );
    status.appendChild(banner);
  }
  status.hidden = kind === 'none';
}

// ---- footer swap (D-03) ----

function freshnessText() {
  const f = model && model.freshness ? model.freshness : {};
  const through = f.retrosheet_through_season
    ? `Retrosheet through ${f.retrosheet_through_season}`
    : 'Retrosheet: not yet loaded';
  return f.in_progress && f.season ? `${through} · ${f.season} season in progress` : through;
}

function creditNodes() {
  const t = (s) => document.createTextNode(s);
  return [
    t(`${RETROSHEET_NOTICE} ${RETROSHEET_CONTACT}`),
    link('www.retrosheet.org', 'https://www.retrosheet.org'),
    t(' · Viewership: '),
    link('RatingsReference.com', 'https://ratingsreference.com'),
    t(' ('),
    link('CC BY 4.0', 'https://creativecommons.org/licenses/by/4.0/'),
    t('), modified: filtered and joined with crew and game data · Postseason outlets and some crews: '),
    link('Wikipedia', 'https://www.wikipedia.org'),
    t(' ('),
    link('CC BY-SA 4.0', 'https://creativecommons.org/licenses/by-sa/4.0/'),
    t(') · Crews and networks: '),
    link('506 Sports', 'https://506sports.com'),
    t(' · Some 2026 crews: relayed from a fan schedule blog, each linked in the game panel with the press page it cites'),
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
  if (model) freshness.replaceChildren(document.createTextNode(freshnessText()));
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
    dark: window.matchMedia('(prefers-color-scheme: dark)').matches,
    mobile: window.matchMedia('(max-width: 640px)').matches,
    hoverNone: window.matchMedia('(hover: none)').matches,
  };
}

function syncUrl() {
  if (!model) return;
  history.replaceState(null, '', location.pathname + encodeMlbState(state, model));
}

function renderSelectionBar() {
  const { chips, clearBtn, summary, headline } = regions;
  const label = selectionLabel(model, state);
  if (label) {
    const li = el('li', 'chip');
    const rm = el('button', 'chip-remove', '×');
    rm.type = 'button';
    rm.setAttribute('aria-label', `Remove ${label}`);
    rm.addEventListener('click', () => clearSelection());
    li.append(el('span', 'chip-label', label), rm);
    chips.replaceChildren(li);
  } else {
    chips.replaceChildren();
  }
  clearBtn.hidden = !label;
  const n = lastRows.length;
  summary.textContent = n ? `${n} ${n === 1 ? 'game matches' : 'games match'}` : '';
  const seasons = model.cols.season;
  const lo = model.n ? Math.min(...seasons) : null;
  const hi = model.n ? Math.max(...seasons) : null;
  const span = lo == null ? '' : ` · ${lo === hi ? lo : `${lo}–${hi}`}`;
  headline.textContent = `${model.n.toLocaleString('en-US')} ${model.n === 1 ? 'game' : 'games'}${span}`;
}

function renderTable() {
  lastRows = tableGames(model, state).map((i) => gameRow(model, i));
  const label = selectionLabel(model, state);
  table.render(lastRows, { emptyKind: label ? 'filtered' : 'nothing', selectionLabel: label });
}

function renderTabHint() {
  regions.hint.textContent = selectionLabel(model, state) ? '' : HINTS[state.view] ?? '';
}

function showActiveView({ resize }) {
  for (const id of VIEW_IDS) views[id].section.hidden = id !== state.view;
  tabs.setActive(state.view);
  if (resize && views[state.view]) views[state.view].mod.resize();
}

/** Open or close the panel to match state.game. */
function syncPanel() {
  if (state.game == null) {
    panel.close();
    return;
  }
  if (panel.currentGame() === state.game) return;
  // The table re-rendered before this point, so an opener button from the old render is detached:
  // focus returns to the same game's new button instead.
  const opener = pendingOpener
    ? regions.matched.querySelector(`.nfl-matchup-btn[data-game="${state.game}"]`) ?? pendingOpener
    : undefined;
  panel.open(gameRow(model, state.game), opener);
  pendingOpener = null;
}

function renderAll({ resize = false } = {}) {
  if (!model || !views) return;
  showActiveView({ resize });
  if (views[state.view]) views[state.view].mod.render(ctx);
  renderTable();
  renderSelectionBar();
  renderTabHint();
  renderCount += 1;
  hooks.renderCount = renderCount;
  syncPanel();
}

function setState(patch) {
  if (!model) return;
  const prevView = state.view;
  const p = { ...(patch || {}) };
  // A booth and a postseason cell exclude each other; picking one clears the
  // other and any view selection unless the same patch says otherwise.
  if (p.booth != null && !('cell' in p)) p.cell = null;
  if (p.cell != null && !('booth' in p)) p.booth = null;
  if (('booth' in p || 'cell' in p) && !('selection' in p)) p.selection = null;
  state = canonicalMlbState({ ...state, ...p }, model);
  // A selection belongs to the view that made it, so a tab change drops it
  // unless the same patch sets a new one.
  if (state.view !== prevView && !('booth' in p || 'cell' in p || 'selection' in p)) {
    state = canonicalMlbState({ ...state, booth: null, cell: null, selection: null }, model);
  }
  syncUrl();
  renderAll({ resize: state.view !== prevView });
}

function clearSelection() {
  setState({ booth: null, cell: null, selection: null });
}

function openGame(i, opener) {
  if (!model || !panel || !Number.isInteger(i) || i < 0 || i >= model.n) return;
  pendingOpener = opener ?? null;
  setState({ game: i });
}

const ctx = {
  get model() {
    return model;
  },
  getState: () => state,
  setState: (patch) => setState(patch),
  env,
  selectGames: (sel) => setState({ booth: null, cell: null, selection: sel }),
  clearSelection: () => clearSelection(),
  openGame: (i, opener) => openGame(i, opener),
  setTabHint: (text) => {
    if (regions) regions.hint.textContent = text || '';
  },
};

// ---- load ----

function buildViews() {
  views = {};
  for (const id of VIEW_IDS) {
    const section = el('section', 'nfl-view');
    section.id = `mlb-view-${id}`;
    section.setAttribute('role', 'tabpanel');
    section.setAttribute('aria-labelledby', `mlb-tab-${id}`);
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
      const resp = await fetch('mlb-data.json', { cache: 'no-cache' });
      if (!resp.ok) throw new Error(`mlb-data.json: HTTP ${resp.status}`);
      const raw = await resp.json();
      model = prepareMlb(raw);
      state = decodeMlbState(search, model);
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
  panel = createDetailPanel(document.body, {
    getConstants: () => (model ? model.constants : null),
    // Escape, the close button and the backdrop all end here: the game leaves the state and URL.
    onClose: () => {
      if (state && state.game != null) {
        state = canonicalMlbState({ ...state, game: null }, model);
        if (mounted) syncUrl();
      }
    },
  });
  tabs = createMlbTabs(regions.tabHost, {
    views: VIEW_IDS,
    onSelect: (id) => setState({ view: id }),
  });
  regions.clearBtn.addEventListener('click', () => clearSelection());
  table.render([], { emptyKind: 'nothing' });
}

function attachMedia() {
  detachMedia();
  mqHandler = () => {
    if (mounted && model && views && views[state.view]) views[state.view].mod.render(ctx);
  };
  for (const q of ['(prefers-color-scheme: dark)', '(max-width: 640px)', '(hover: none)']) {
    const mql = window.matchMedia(q);
    mql.addEventListener('change', mqHandler);
    mqls.push(mql);
  }
}

function detachMedia() {
  for (const mql of mqls) mql.removeEventListener('change', mqHandler);
  mqls.length = 0;
}

/**
 * @param {{footerEl: HTMLElement, search?: string}} opts
 */
export async function mount({ footerEl, search = '' } = {}) {
  window.__mlbTestHooks = hooks;
  hooks.ready = false;
  mounted = true;
  ensureShell(footerEl);
  swapFooter(footerEl);
  attachMedia();
  await ensureLoaded(search);
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
  }
  hooks.ready = true;
}

export function unmount() {
  mounted = false;
  if (panel) panel.close();
  detachMedia();
  restoreFooter();
}
