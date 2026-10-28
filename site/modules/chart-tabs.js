/**
 * Chart tabs: the Scatter | Bars | Butterfly | Map tablist, its hint (the chart module's subtitle), and the
 * grouping / Both-PBP-Analyst controls (SITE-33, D-10, D-12, D-13, D-14,
 * D-17, D-25, D-30; 04.6 D-21). One grouping control (`state.by`) shows only
 * the options that apply to the current subjects, and the role control is
 * concealed unless announcers are the rows or segments (D-30 refines D-25; a
 * concealed role still applies and stays editable in the toolbar). The role
 * control reads and writes the one `state.role` the Role filter popover uses,
 * so the two always agree.
 *
 * Init once (`initChartTabs`: delegated listeners), render every cycle
 * (`renderChartTabs`: syncs attributes to state). Every change goes through
 * `setState`, so the URL and Reset / Clear all behave as for any other control.
 *
 * DOM safety: createElement/textContent/attributes only, never markup-injecting
 * APIs (T-04.4-09). `data-*` values come from static markup and are still
 * allowlisted again by setState -> decodeState (T-04.4-10).
 */

import { byPatch, chartContext } from './bars.js';
import { MAP_HINT } from './map-model.js';
import { dayLabel } from './weekend.js';
import { selectedDay, selectedWeek, weekDays, weekDisplay } from './weekend-state.js';

export const TAB_HINTS = {
  bars: 'Pick a school, network, announcer, or game',
  butterfly: 'Pick exactly two schools or two announcers',
};

export const STALE_COPY = {
  bars: {
    title: 'Pick a school, network, announcer, or game',
    hint: 'Pick a school or a game, narrow Networks, or select an announcer to see counts.',
  },
  butterfly: {
    title: 'Pick exactly two schools or two announcers',
    hint: 'Select two schools or two announcers to compare them.',
  },
};

const VIEWS = ['scatter', 'bars', 'butterfly', 'map', 'crews', 'weekend'];

/** The Crews subtitle (14-UI-SPEC): the master Seasons range, "Seasons 2014–2026" or "Season 2026". */
function crewsSubtitle(state) {
  const years = currentData?.seasons ?? [];
  const lo = state.seasons ? state.seasons[0] : years[0];
  const hi = state.seasons ? state.seasons[1] : years[years.length - 1];
  if (lo == null || hi == null) return '';
  return lo === hi ? `Season ${lo}` : `Seasons ${lo}–${hi}`;
}

/** The This weekend subtitle (18-UI-SPEC): `Week 9, Sat. Oct. 31, all times ET`. */
function weekendSubtitle(state) {
  const week = currentData ? selectedWeek(currentData, state) : null;
  if (!week) return '';
  const day = selectedDay(weekDays(currentData, week).days, state.day);
  return [weekDisplay(week), day ? dayLabel(day) : null, 'all times ET'].filter(Boolean).join(', ');
}

/** The hint the module subtitle rests on: the Map's prompt until a subject (announcer, school or crew) is picked (04.18 D-02); the season range on Crews. */
function restingHint(state) {
  if (state.view === 'map' && state.people.length === 0 && state.school.length === 0 && state.crew == null) return MAP_HINT;
  if (state.view === 'crews') return crewsSubtitle(state);
  if (state.view === 'weekend') return weekendSubtitle(state);
  return '';
}

/** Hint on the Butterfly tab while Head-to-head blocks the two-school comparison (04.7 D-15). */
export const H2H_BUTTERFLY_HINT = 'Switch School to Either team to compare two schools';

function headToHeadBlocksButterfly(state) {
  return state.h2h === true && state.school.length === 2 && state.people.length !== 2;
}

/**
 * Title and hover/focus hint of a disabled tab.
 * @param {string} view
 * @param {object} state
 * @returns {string}
 */
export function tabHint(view, state) {
  if (view === 'butterfly' && headToHeadBlocksButterfly(state)) return H2H_BUTTERFLY_HINT;
  return TAB_HINTS[view] || '';
}

/**
 * Stale-panel copy for the active view, aware of Head-to-head.
 * @param {object} state
 * @returns {{title: string, hint: string}}
 */
export function staleCopy(state) {
  if (state.view === 'butterfly' && headToHeadBlocksButterfly(state)) {
    return {
      title: H2H_BUTTERFLY_HINT,
      hint: 'Head-to-head keeps only the games between the two schools. Select two announcers to compare them in these games.',
    };
  }
  return STALE_COPY[state.view];
}

function tabsEl() {
  return document.getElementById('chart-tabs');
}

function allTabs() {
  return Array.from(tabsEl().querySelectorAll('button[role="tab"]')).filter((tab) => !tab.hidden);
}

/** The tab hint lives in the chart module's subtitle slot (C6); the title carries the full text. */
function setHint(text) {
  const hint = document.getElementById('chart-subtitle');
  if (!hint) return;
  hint.textContent = text;
  if (text) hint.title = text;
  else hint.removeAttribute('title');
}

let currentState = null;
let currentData = null;

function showHintFor(tab) {
  if (tab && tab.getAttribute('aria-disabled') === 'true') {
    setHint(tab.getAttribute('title') || '');
  }
}

/**
 * Wires the delegated listeners once.
 * @param {{data: object, getState: () => object, setState: (patch: object) => void}} deps
 */
export function initChartTabs({ data, getState, setState }) {
  const tabs = tabsEl();
  if (!tabs) return;

  function activate(tab) {
    if (!tab) return;
    if (tab.getAttribute('aria-disabled') === 'true') {
      tab.focus();
      showHintFor(tab);
      return;
    }
    setState({ view: tab.dataset.view });
    tab.focus();
  }

  tabs.addEventListener('click', (ev) => {
    const tab = ev.target.closest('button[data-view]');
    if (tab) activate(tab);
  });

  tabs.addEventListener('keydown', (ev) => {
    const list = allTabs();
    const current = ev.target.closest('button[data-view]');
    if (!current) return;
    const at = list.indexOf(current);
    let target = null;
    if (ev.key === 'ArrowRight') target = list[(at + 1) % list.length];
    else if (ev.key === 'ArrowLeft') target = list[(at - 1 + list.length) % list.length];
    else if (ev.key === 'Home') target = list[0];
    else if (ev.key === 'End') target = list[list.length - 1];
    if (target) {
      ev.preventDefault();
      for (const tab of list) tab.setAttribute('tabindex', tab === target ? '0' : '-1');
      target.focus();
      return;
    }
    if (ev.key === 'Enter' || ev.key === ' ') {
      ev.preventDefault();
      activate(current);
    } else if (ev.key === 'Escape') {
      setHint(currentState ? restingHint(currentState) : '');
    }
  });

  // mouseenter/mouseleave and focusin/focusout bubble-safe via capture on the container.
  for (const type of ['mouseover', 'focusin']) {
    tabs.addEventListener(type, (ev) => {
      showHintFor(ev.target.closest('button[data-view]'));
    });
  }
  for (const type of ['mouseout', 'focusout']) {
    tabs.addEventListener(type, (ev) => {
      const tab = ev.target.closest('button[data-view]');
      if (tab && tab.getAttribute('aria-disabled') === 'true') {
        setHint(currentState ? restingHint(currentState) : '');
      }
    });
  }
  document.addEventListener('pointerdown', (ev) => {
    if (!ev.target.closest('#chart-tabs')) setHint(currentState ? restingHint(currentState) : '');
  });

  const roleToggle = document.getElementById('bar-role-toggle');
  if (roleToggle) {
    roleToggle.addEventListener('click', (ev) => {
      const button = ev.target.closest('button[data-role]');
      if (button) setState({ role: button.dataset.role || null });
    });
  }
  const groupToggle = document.getElementById('group-by-toggle');
  if (groupToggle) {
    groupToggle.addEventListener('click', (ev) => {
      const button = ev.target.closest('button[data-by]');
      if (!button) return;
      const state = getState();
      const ctx = chartContext(data, state);
      const options = state.view === 'butterfly' ? ctx.butterflyByOptions : ctx.byOptions;
      setState(byPatch(button.dataset.by, options));
    });
  }
}

/**
 * Syncs tab, hint, and control DOM to the current state.
 * @param {{data: object, state: object}} args
 */
export function renderChartTabs({ data, state }) {
  const tabs = tabsEl();
  if (!tabs) return;
  const ctx = chartContext(data, state);
  const enabled = { scatter: true, bars: ctx.barsEnabled, butterfly: ctx.butterflyEnabled, map: true, crews: true, weekend: (data.weeks ?? []).length > 0 };
  const focused = document.activeElement;
  // Roving tabindex (WR-04): one Tab stop. The focused tab keeps it while focus
  // is inside the tablist (a focused disabled tab included); otherwise the
  // selected tab holds it.
  const focusInside = tabs.contains(focused);

  for (const tab of allTabs()) {
    const view = tab.dataset.view;
    if (!VIEWS.includes(view)) continue;
    // No weeks in the build, no This weekend tab (the tab never shows empty).
    if (view === 'weekend') tab.hidden = !enabled.weekend;
    const selected = view === state.view;
    tab.setAttribute('aria-selected', String(selected));
    tab.setAttribute('tabindex', (focusInside ? tab === focused : selected) ? '0' : '-1');
    if (enabled[view]) {
      tab.removeAttribute('aria-disabled');
      tab.removeAttribute('title');
      tab.removeAttribute('aria-describedby');
    } else {
      tab.setAttribute('aria-disabled', 'true');
      tab.setAttribute('title', tabHint(view, state));
      tab.setAttribute('aria-describedby', 'chart-subtitle');
    }
    if (selected) {
      const panel = document.getElementById('chart-panel');
      if (panel) panel.setAttribute('aria-labelledby', tab.id);
      // On a phone the tab row scrolls sideways; keep the selected tab fully in view.
      if (tabs.scrollWidth > tabs.clientWidth) {
        const left = tab.offsetLeft - tabs.offsetLeft;
        if (left < tabs.scrollLeft) tabs.scrollLeft = left;
        else if (left + tab.offsetWidth > tabs.scrollLeft + tabs.clientWidth) {
          tabs.scrollLeft = left + tab.offsetWidth - tabs.clientWidth;
        }
      }
      // The module title is the active tab's label (recorded planner choice, 13-11).
      const title = document.getElementById('chart-title');
      if (title) title.textContent = tab.textContent;
    }
  }
  currentState = state;
  currentData = data;
  setHint(restingHint(state));

  const scatter = state.view === 'scatter';
  const scatterControls = document.getElementById('scatter-controls');
  const barControls = document.getElementById('bar-controls');
  if (scatterControls) scatterControls.classList.toggle('is-concealed', !scatter);
  if (barControls) barControls.classList.toggle('is-concealed', scatter || state.view === 'map' || state.view === 'crews' || state.view === 'weekend');
  // Reset zoom is wired by 13-12; it is shown on the zoomable Scatter and Map only, and
  // concealed (not removed) elsewhere so the header never reflows.
  const resetZoom = document.getElementById('reset-zoom');
  if (resetZoom) resetZoom.classList.toggle('is-concealed', !(scatter || state.view === 'map'));

  for (const button of document.querySelectorAll('#bar-role-toggle button[data-role]')) {
    button.setAttribute('aria-pressed', String((button.dataset.role || null) === state.role));
  }

  const butterfly = state.view === 'butterfly';
  const options = butterfly ? ctx.butterflyByOptions : ctx.byOptions;
  const selected = butterfly ? ctx.butterflyBy : ctx.by;
  const group = butterfly ? ctx.butterflyGroup : ctx.group;
  for (const button of document.querySelectorAll('#group-by-toggle button[data-by]')) {
    button.hidden = !options.includes(button.dataset.by);
    button.setAttribute('aria-pressed', String(button.dataset.by === selected));
  }
  const roleToggle = document.getElementById('bar-role-toggle');
  if (roleToggle) roleToggle.classList.toggle('is-concealed', group !== 'announcers');
}
