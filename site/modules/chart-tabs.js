/**
 * Chart tabs: the Scatter | Bars | Butterfly tablist, its hint row, and the
 * Bar style / Both-PBP-Analyst / Group-by controls (SITE-33, D-10, D-12, D-13,
 * D-14, D-17, D-25). The role control reads and writes the one `state.role` the
 * Role filter popover uses, so the two always agree.
 *
 * Init once (`initChartTabs`: delegated listeners), render every cycle
 * (`renderChartTabs`: syncs attributes to state). Every change goes through
 * `setState`, so the URL and Reset / Clear all behave as for any other control.
 *
 * DOM safety: createElement/textContent/attributes only, never markup-injecting
 * APIs (T-04.4-09). `data-*` values come from static markup and are still
 * allowlisted again by setState -> decodeState (T-04.4-10).
 */

import { chartContext } from './bars.js';

export const TAB_HINTS = {
  bars: 'Pick a school, network, or announcer',
  butterfly: 'Pick exactly two schools or two announcers',
};

export const STALE_COPY = {
  bars: {
    title: 'Pick a school, network, or announcer',
    hint: 'Pick a school, narrow Networks, or select an announcer to see counts.',
  },
  butterfly: {
    title: 'Pick exactly two schools or two announcers',
    hint: 'Select two schools or two announcers to compare them.',
  },
};

const VIEWS = ['scatter', 'bars', 'butterfly'];

function tabsEl() {
  return document.getElementById('chart-tabs');
}

function allTabs() {
  return Array.from(tabsEl().querySelectorAll('button[role="tab"]'));
}

function setHint(text) {
  const hint = document.getElementById('tab-hint');
  if (hint) hint.textContent = text;
}

function showHintFor(tab) {
  if (tab && tab.getAttribute('aria-disabled') === 'true') {
    setHint(TAB_HINTS[tab.dataset.view] || '');
  }
}

/**
 * Wires the delegated listeners once.
 * @param {{data: object, getState: () => object, setState: (patch: object) => void}} deps
 */
export function initChartTabs({ setState }) {
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
      setHint('');
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
      if (tab && tab.getAttribute('aria-disabled') === 'true') setHint('');
    });
  }
  document.addEventListener('pointerdown', (ev) => {
    if (!ev.target.closest('#chart-tabs')) setHint('');
  });

  const styleToggle = document.getElementById('bar-style-toggle');
  if (styleToggle) {
    styleToggle.addEventListener('click', (ev) => {
      const button = ev.target.closest('button[data-bars]');
      if (button) setState({ bars: button.dataset.bars });
    });
  }
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
      const button = ev.target.closest('button[data-group]');
      if (button) setState({ group: button.dataset.group === 'teams' ? 'teams' : null });
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
  const enabled = { scatter: true, bars: ctx.barsEnabled, butterfly: ctx.butterflyEnabled };
  const focused = document.activeElement;

  for (const tab of allTabs()) {
    const view = tab.dataset.view;
    if (!VIEWS.includes(view)) continue;
    const selected = view === state.view;
    tab.setAttribute('aria-selected', String(selected));
    tab.setAttribute('tabindex', selected || tab === focused ? '0' : '-1');
    if (enabled[view]) {
      tab.removeAttribute('aria-disabled');
      tab.removeAttribute('title');
      tab.removeAttribute('aria-describedby');
    } else {
      tab.setAttribute('aria-disabled', 'true');
      tab.setAttribute('title', TAB_HINTS[view]);
      tab.setAttribute('aria-describedby', 'tab-hint');
    }
    if (selected) {
      const panel = document.getElementById('chart-panel');
      if (panel) panel.setAttribute('aria-labelledby', tab.id);
    }
  }
  setHint('');

  const scatter = state.view === 'scatter';
  const axisToggle = document.getElementById('axis-toggle');
  const barControls = document.getElementById('bar-controls');
  if (axisToggle) axisToggle.classList.toggle('is-concealed', !scatter);
  if (barControls) barControls.classList.toggle('is-concealed', scatter);

  for (const button of document.querySelectorAll('#bar-style-toggle button[data-bars]')) {
    button.setAttribute('aria-pressed', String(button.dataset.bars === state.bars));
  }

  for (const button of document.querySelectorAll('#bar-role-toggle button[data-role]')) {
    button.setAttribute('aria-pressed', String((button.dataset.role || null) === state.role));
  }

  const butterfly = state.view === 'butterfly';
  const choice = butterfly ? ctx.butterflyGroupChoice : ctx.groupChoice;
  const group = butterfly ? ctx.butterflyGroup : ctx.group;
  const groupBy = document.getElementById('group-by');
  if (groupBy) groupBy.classList.toggle('is-concealed', !choice);
  for (const button of document.querySelectorAll('#group-by-toggle button[data-group]')) {
    button.setAttribute('aria-pressed', String(button.dataset.group === group));
  }
}
