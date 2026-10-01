/**
 * Bars / Butterfly panel renderer (SITE-34, SITE-35, SITE-36; D-01, D-03, D-09,
 * D-14, D-15, D-18, D-19). Builds the title, chart, aria summary, Show all
 * toggle, captions, counts list, and empty state from the models in bars.js
 * and the strings in bar-copy.js, and turns clicks, taps, and keys into
 * filter patches through `drillPatch` -> `setState`.
 *
 * D-01: every number here is a count of rated telecasts; no viewer figure.
 * D-03: the Show all expansion lives only in this module's memory and resets
 * when the subject, group, or bar style changes; it never enters the URL.
 * DOM safety (T-04.4-17): createElement/textContent/setAttribute/
 * replaceChildren only, never a markup-injecting API. Drill targets are
 * resolved from the in-memory model by index (T-04.4-18), never from DOM text.
 */

import { barsModel, butterflyModel, visibleRows, drillPatch } from './bars.js';
import {
  EMPTY_COPY,
  chartTitle,
  rowCountCaption,
  showAllLabel,
  captionLines,
  tooltipLines,
  countsListName,
  butterflyRowText,
  butterflyCountsName,
  ariaSummary,
} from './bar-copy.js';
import { barTones, buildBarFigure, buildButterflyFigure, renderBars, bindBarEvents } from './bar-chart.js';
import { makePill, currentTheme } from './pill.js';
import { showTextTooltip, hideTooltip } from './tooltip.js';

let expanded = false;
let expandKey = '';
let barsBound = false;
let lastModel = null;
let lastShownRows = [];
let pendingFocusKey = null;
let pendingTapKey = null;
let pendingTapAt = 0;

/** Plotly reports one touch tap as two plotly_click events a few ms apart; a repeat this soon is the same tap. */
const TAP_DEBOUNCE_MS = 350;
let deps = null;

const hoverNone = () => window.matchMedia('(hover: none)').matches;

/** The current Bars/Butterfly model (for test hooks), or null. */
export function lastBarsModel() {
  return lastModel;
}

/** Forgets a pending first tap (called at every render and when hover clears). */
export function resetBarsTap() {
  pendingTapKey = null;
}

function el(id) {
  return document.getElementById(id);
}

/** Resolves the drill target for a `{r, s, side}` reference from the model. */
function targetFor(ref) {
  const row = lastShownRows[ref.r];
  if (!row) return null;
  if (ref.s < 0) return row.target;
  const list = ref.side != null && ref.side >= 0 && row.sides ? row.sides[ref.side].segments : row.segments;
  const seg = list[ref.s];
  return seg ? seg.target : null;
}

function drill(target) {
  const patch = drillPatch(deps.data, deps.getState(), target);
  if (patch) deps.setState(patch);
  else pendingFocusKey = null;
}

function refKey(ref) {
  return `${ref.r}/${ref.s}/${ref.side ?? ''}`;
}

function onPointClick(ref, ev) {
  const target = targetFor(ref);
  if (hoverNone()) {
    const tapKey = refKey(ref);
    const now = performance.now();
    if (tapKey === pendingTapKey && now - pendingTapAt < TAP_DEBOUNCE_MS) return;
    if (tapKey !== pendingTapKey) {
      pendingTapKey = tapKey;
      pendingTapAt = now;
      const lines = tooltipLines(lastModel, lastShownRows, ref, { touch: true });
      const tone = barTones(lastShownRows[ref.r], currentTheme());
      showTextTooltip(lines, {
        theme: currentTheme(),
        borderColor: tone.a,
        clientX: ev.event?.clientX ?? 0,
        clientY: ev.event?.clientY ?? 0,
      });
      return;
    }
    pendingTapKey = null;
    hideTooltip();
  }
  drill(target);
}

function onPointHover(ref, ev) {
  if (hoverNone()) return;
  const lines = tooltipLines(lastModel, lastShownRows, ref, { touch: false });
  const tone = barTones(lastShownRows[ref.r], currentTheme());
  showTextTooltip(lines, {
    theme: currentTheme(),
    borderColor: tone.a,
    clientX: ev.event.clientX,
    clientY: ev.event.clientY,
  });
}

/**
 * Wires the delegated listeners once.
 * @param {{data: object, getState: () => object, setState: (patch: object) => void, rerender: () => void}} args
 */
export function initBarsPanel(args) {
  deps = args;
  const showAll = el('bars-show-all');
  if (showAll) {
    showAll.addEventListener('click', () => {
      expanded = !expanded;
      deps.rerender();
    });
  }
  document.addEventListener('pointerdown', (ev) => {
    if (pendingTapKey != null && !ev.target.closest('#bars-chart')) {
      resetBarsTap();
      hideTooltip();
    }
  });
  const list = el('bars-counts');
  if (list) {
    list.addEventListener('click', (ev) => {
      const button = ev.target.closest('button[data-r]');
      if (!button) return;
      const ref = {
        r: Number(button.dataset.r),
        s: Number(button.dataset.s),
        side: button.dataset.side === '' || button.dataset.side == null ? null : Number(button.dataset.side),
      };
      pendingFocusKey = button.dataset.key;
      drill(targetFor(ref));
    });
  }
}

function countSpan(n) {
  const span = document.createElement('span');
  span.className = 'counts-n';
  span.textContent = String(n);
  return span;
}

function labelNode(row, theme) {
  if (row.family != null) return makePill(row.label, row.family, theme);
  const span = document.createElement('span');
  span.className = 'counts-label';
  span.textContent = row.label;
  return span;
}

function makeButton(ref, key, aria) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'counts-btn';
  button.dataset.r = String(ref.r);
  button.dataset.s = String(ref.s);
  button.dataset.side = ref.side == null ? '' : String(ref.side);
  button.dataset.key = key;
  button.setAttribute('aria-label', aria);
  return button;
}

function segmentList(segments, r, side, rowKey, prefix) {
  const ol = document.createElement('ol');
  ol.className = 'counts-sublist';
  if (prefix) {
    const head = document.createElement('li');
    head.className = 'counts-side';
    head.textContent = prefix;
    ol.appendChild(head);
  }
  segments.forEach((seg, s) => {
    const li = document.createElement('li');
    const text = `${seg.label} ${seg.count}`;
    if (seg.target != null) {
      const b = makeButton({ r, s, side }, `${rowKey}/${seg.key}/${side ?? ''}`, countsListName(seg.target, seg.name, seg.count));
      b.textContent = text;
      li.appendChild(b);
    } else {
      li.textContent = text;
    }
    ol.appendChild(li);
  });
  return ol;
}

function buildCountsList(model, rows, theme) {
  const items = rows.map((row, r) => {
    const li = document.createElement('li');
    const fly = model.kind === 'butterfly';
    const content = [];
    if (fly) {
      const text = document.createElement('span');
      text.className = 'counts-label';
      text.textContent = butterflyRowText(row, model);
      content.push(text);
    } else {
      content.push(labelNode(row, theme), countSpan(row.total));
    }
    if (row.target != null) {
      const aria = fly ? butterflyCountsName(row, model) : countsListName(row.target, row.name, row.total);
      const b = makeButton({ r, s: -1, side: null }, row.key, aria);
      b.replaceChildren(...content);
      li.appendChild(b);
    } else {
      const span = document.createElement('span');
      span.className = 'counts-plain';
      span.replaceChildren(...content);
      li.appendChild(span);
    }
    if (model.segmentKind != null) {
      if (fly) {
        [0, 1].forEach((side) => {
          if (row.sides[side].segments.length > 0) {
            li.appendChild(segmentList(row.sides[side].segments, r, side, row.key, model.sides[side].name));
          }
        });
      } else {
        li.appendChild(segmentList(row.segments, r, null, row.key, null));
      }
    }
    return li;
  });
  el('bars-counts').replaceChildren(...items);
}

function setHidden(ids, hidden) {
  for (const id of ids) {
    const node = el(id);
    if (node) node.hidden = hidden;
  }
}

/**
 * Renders the active bar tab. Called by app.js only when the tab applies.
 * @param {{data: object, state: object, view: object, env: {theme: string, mobile: boolean, revision: number, width: number}}} args
 */
export function renderBarsPanel({ data, state, view, env }) {
  resetBarsTap();
  const model = state.view === 'bars' ? barsModel(data, view, state) : butterflyModel(data, view, state);
  if (!model) return;
  const key = [
    state.view,
    model.group,
    state.bars,
    state.school.join(','),
    state.people.join(','),
    JSON.stringify(state.networks),
  ].join('|');
  if (key !== expandKey) {
    expanded = false;
    expandKey = key;
  }
  const shown = visibleRows(model.rows, expanded);
  lastModel = model;
  lastShownRows = shown;

  const chart = el('bars-chart');
  const note = el('bars-note');
  el('bars-title').textContent = chartTitle(model, data, state);
  chart.setAttribute('aria-label', ariaSummary(model, data, state, shown.length));

  if (model.rows.length === 0) {
    note.querySelector('.season-empty-title').textContent = EMPTY_COPY.title;
    note.querySelector('.season-empty-hint').textContent = EMPTY_COPY.hint;
    note.hidden = false;
    chart.classList.add('is-concealed');
    setHidden(['bars-footer', 'bars-captions', 'bars-data'], true);
    return;
  }

  note.hidden = true;
  chart.classList.remove('is-concealed');
  setHidden(['bars-footer', 'bars-captions', 'bars-data'], false);

  const figEnv = { ...env, width: chart.clientWidth || env.width };
  const figure =
    model.kind === 'butterfly' ? buildButterflyFigure(model, shown, figEnv) : buildBarFigure(model, shown, figEnv);
  renderBars(chart, figure);
  if (!barsBound) {
    bindBarEvents(chart, {
      onPointClick,
      onPointHover,
      // On touch the tap tooltip must outlive Plotly's synthetic unhover; it clears on render, scroll, or a tap elsewhere.
      onPointUnhover: () => {
        if (!hoverNone()) hideTooltip();
      },
      onLabelClick: (rowIndex) => {
        const row = lastShownRows[rowIndex];
        if (row) drill(row.target);
      },
    });
    barsBound = true;
  }

  const label = showAllLabel(model.rows.length, expanded);
  const toggle = el('bars-show-all');
  if (label == null) {
    toggle.hidden = true;
  } else {
    toggle.textContent = label;
    toggle.hidden = false;
  }
  toggle.setAttribute('aria-expanded', String(expanded));
  el('bars-rowcount').textContent = rowCountCaption(model, expanded);

  el('bars-captions').replaceChildren(
    ...captionLines(model, shown).map((text) => {
      const p = document.createElement('p');
      p.className = 'caption';
      p.textContent = text;
      return p;
    }),
  );

  buildCountsList(model, shown, currentTheme());
  if (pendingFocusKey != null) {
    const next = Array.from(el('bars-counts').querySelectorAll('button[data-key]')).find(
      (b) => b.dataset.key === pendingFocusKey,
    );
    (next || el('bars-data').querySelector('summary')).focus();
    pendingFocusKey = null;
  }
}
