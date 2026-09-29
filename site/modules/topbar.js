/**
 * Announcer search, selected-people chips, the Compare people / Called
 * together toggles, the compare shape legend, Clear selection, and the
 * counts-only match summary line (SITE-02, SITE-08, SITE-10, D-07, D-08, A1).
 *
 * D-21: the search combobox now lives in the toolbar's Announcers popover
 * (`#pop-announcers`/`#filter-announcers`); the chips, toggles, and summary
 * live in `#selection-bar`'s `#selection-row` (hidden while no one is
 * selected) below the toolbar.
 *
 * `initTopbar(ctx)` binds every DOM event listener once; `renderTopbar(ctx)`
 * is a pure DOM update driven by the current state/view, called every render
 * cycle from app.js. DOM is built only with createElement/textContent/
 * replaceChildren -- never any markup-injecting DOM API (T-04.1-29). Typed
 * search text is only ever used as a search key, never rendered as markup,
 * and person/team names always land in the DOM via textContent.
 */

import { searchPeople } from './data.js';
import { MAX_COMPARE } from './select.js';
import { summaryCopy, ROLE_LABELS } from './format.js';
import { COMPARE_GLYPHS, SHARED_GLYPH } from './palette.js';

const DEBOUNCE_MS = 120;

const BASE_COMPARE_HELP = 'Compare up to 4 people — each gets its own shape.';
const OVER_LIMIT_SUFFIX = ' Remove people to use compare.';

/** DOM element references, populated once by `initTopbar`. */
let els = null;

/** Debounce timer id for the search input. */
let debounceTimer = null;

/** The options currently rendered in `#person-results` (empty when closed or showing "no matches"). */
let currentOptions = [];

/** Index of the option the user has moved to with ArrowUp/ArrowDown, or -1. */
let activeIndex = -1;

/** Selection key the compare-note was last shown for, or null when hidden (D-07). */
let compareNoteStickyKey = null;

/** A key identifying the current people/compare selection, for the compare-note sticky logic. */
function personSelectionKey(state) {
  return `${state.people.join(',')}|${state.compare}`;
}

/** Closes and clears the search results listbox. */
function closeOptions() {
  els.results.hidden = true;
  els.results.replaceChildren();
  els.input.setAttribute('aria-expanded', 'false');
  els.input.removeAttribute('aria-activedescendant');
  currentOptions = [];
  activeIndex = -1;
}

/** Renders the search results listbox for a non-empty query. */
function renderOptions(data, results) {
  if (results.length === 0) {
    const li = document.createElement('li');
    li.setAttribute('role', 'option');
    li.setAttribute('aria-disabled', 'true');
    li.textContent = 'No matching announcers';
    els.results.replaceChildren(li);
  } else {
    const items = results.map((r, i) => {
      const li = document.createElement('li');
      li.id = `person-opt-${i}`;
      li.setAttribute('role', 'option');
      li.setAttribute('aria-selected', 'false');
      li.dataset.personId = r.id;

      const nameSpan = document.createElement('span');
      nameSpan.className = 'option-name';
      nameSpan.textContent = r.name;
      li.appendChild(nameSpan);

      if (r.matchedVariant) {
        const variantSpan = document.createElement('span');
        variantSpan.className = 'option-variant';
        variantSpan.textContent = ` (as “${r.matchedVariant}”)`;
        li.appendChild(variantSpan);
      }

      const person = data.lookups.people[r.index];
      const roleLabel = ROLE_LABELS[person.usual_role] ?? '';
      if (roleLabel) {
        const roleSpan = document.createElement('span');
        roleSpan.className = 'option-role';
        roleSpan.textContent = ` – ${roleLabel}`;
        li.appendChild(roleSpan);
      }

      return li;
    });
    els.results.replaceChildren(...items);
  }
  els.results.hidden = false;
  els.input.setAttribute('aria-expanded', 'true');
}

/** Re-runs the search for the input's current value and re-renders the listbox. */
function updateOptions(data, getState, rawValue) {
  const query = rawValue.trim();
  if (query === '') {
    closeOptions();
    return;
  }
  const state = getState();
  const results = searchPeople(data, query, 8).filter((r) => !state.people.includes(r.id));
  currentOptions = results;
  activeIndex = -1;
  renderOptions(data, results);
}

/** Syncs `aria-selected`/`aria-activedescendant` to the current `activeIndex`. */
function updateActiveDescendant() {
  const options = els.results.querySelectorAll('li[role="option"]:not([aria-disabled])');
  options.forEach((li, i) => {
    li.setAttribute('aria-selected', String(i === activeIndex));
  });
  const activeLi = options[activeIndex];
  if (activeLi) {
    els.input.setAttribute('aria-activedescendant', activeLi.id);
  } else {
    els.input.removeAttribute('aria-activedescendant');
  }
}

/** Shows the "Compare mode holds up to 4 people." note, sticky until the selection changes. */
function showCompareNote(state) {
  compareNoteStickyKey = personSelectionKey(state);
  els.compareNote.hidden = false;
}

/** Adds a person by id, respecting the MAX_COMPARE cap (D-07), then resets the search field. */
function addPerson(getState, setState, id) {
  const state = getState();
  if (state.compare && state.people.length >= MAX_COMPARE) {
    showCompareNote(state);
    return;
  }
  setState({ people: [...state.people, id] });
  els.input.value = '';
  closeOptions();
  els.input.focus();
}

/** Binds every top-bar DOM event listener once. `getState` always returns the latest state. */
export function initTopbar({ data, getState, setState }) {
  els = {
    input: document.getElementById('person-search'),
    results: document.getElementById('person-results'),
    selectionRow: document.getElementById('selection-row'),
    chips: document.getElementById('chips'),
    compareToggle: document.getElementById('compare-toggle'),
    compareHelp: document.getElementById('compare-help'),
    togetherToggle: document.getElementById('together-toggle'),
    togetherHelp: document.getElementById('together-help'),
    clearSelection: document.getElementById('clear-selection'),
    compareNote: document.getElementById('compare-note'),
    summaryCount: document.getElementById('summary-count'),
    summaryDetail: document.getElementById('summary-detail'),
    shapeLegend: document.getElementById('shape-legend'),
  };

  els.input.addEventListener('input', () => {
    const value = els.input.value;
    window.clearTimeout(debounceTimer);
    debounceTimer = window.setTimeout(() => updateOptions(data, getState, value), DEBOUNCE_MS);
  });

  els.input.addEventListener('keydown', (ev) => {
    if (ev.key === 'ArrowDown') {
      if (els.results.hidden || currentOptions.length === 0) return;
      ev.preventDefault();
      activeIndex = Math.min(activeIndex + 1, currentOptions.length - 1);
      updateActiveDescendant();
    } else if (ev.key === 'ArrowUp') {
      if (els.results.hidden || currentOptions.length === 0) return;
      ev.preventDefault();
      activeIndex = Math.max(activeIndex - 1, 0);
      updateActiveDescendant();
    } else if (ev.key === 'Enter') {
      if (activeIndex >= 0 && currentOptions[activeIndex]) {
        ev.preventDefault();
        addPerson(getState, setState, currentOptions[activeIndex].id);
      }
    } else if (ev.key === 'Escape') {
      closeOptions();
    }
  });

  els.results.addEventListener('click', (ev) => {
    const li = ev.target.closest('li[role="option"]');
    if (!li || !li.dataset.personId) return;
    addPerson(getState, setState, li.dataset.personId);
  });

  document.addEventListener('click', (ev) => {
    if (els.results.hidden) return;
    if (els.results.contains(ev.target) || ev.target === els.input) return;
    closeOptions();
  });

  els.chips.addEventListener('click', (ev) => {
    const btn = ev.target.closest('.chip-remove');
    if (!btn) return;
    const id = btn.dataset.personId;
    const state = getState();
    setState({ people: state.people.filter((personId) => personId !== id) });
  });

  els.compareToggle.addEventListener('click', () => {
    const state = getState();
    setState({ compare: !state.compare });
  });

  els.togetherToggle.addEventListener('click', () => {
    const state = getState();
    setState({ together: !state.together });
  });

  els.clearSelection.addEventListener('click', () => {
    setState({ people: [], compare: false, together: false });
  });
}

/** Renders the chips list in selection order. */
function renderChips(data, state) {
  const items = state.people.map((id, position) => {
    const idx = data.personIndexById.get(id);
    const person = data.lookups.people[idx];

    const li = document.createElement('li');
    li.className = 'chip';

    if (state.compare) {
      const glyph = document.createElement('span');
      glyph.className = 'chip-glyph';
      glyph.setAttribute('aria-hidden', 'true');
      glyph.textContent = COMPARE_GLYPHS[position] ?? '';
      li.appendChild(glyph);
    }

    const nameSpan = document.createElement('span');
    nameSpan.textContent = person.name;
    li.appendChild(nameSpan);

    const removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.className = 'chip-remove';
    removeBtn.textContent = '×';
    removeBtn.setAttribute('aria-label', `Remove ${person.name}`);
    removeBtn.dataset.personId = id;
    li.appendChild(removeBtn);

    return li;
  });
  els.chips.replaceChildren(...items);
}

/** Renders the compare/together toggle states and helper text. */
function renderToggles(state) {
  els.compareToggle.setAttribute('aria-pressed', String(state.compare));
  const overLimit = state.people.length > MAX_COMPARE;
  els.compareToggle.disabled = overLimit;
  els.compareHelp.textContent = overLimit ? `${BASE_COMPARE_HELP}${OVER_LIMIT_SUFFIX}` : BASE_COMPARE_HELP;
  // The helper text moved from a visible paragraph to an aria-describedby
  // span (D-21, to keep the chip row compact); a `title` tooltip keeps the
  // same copy available on hover/long-press.
  els.compareToggle.title = els.compareHelp.textContent;

  els.togetherToggle.setAttribute('aria-pressed', String(state.together));
  els.togetherToggle.disabled = state.people.length < 2;
  els.togetherToggle.title = els.togetherHelp.textContent;
}

/** Renders the compare-mode shape legend (D-07), visible only in compare mode with people selected. */
function renderShapeLegend(data, state, view) {
  const shouldShow = state.compare && state.people.length > 0;
  if (!shouldShow) {
    els.shapeLegend.hidden = true;
    els.shapeLegend.replaceChildren();
    return;
  }

  const items = state.people.map((id, position) => {
    const idx = data.personIndexById.get(id);
    const person = data.lookups.people[idx];
    const li = document.createElement('li');
    const glyph = document.createElement('span');
    glyph.setAttribute('aria-hidden', 'true');
    glyph.textContent = COMPARE_GLYPHS[position] ?? '';
    li.appendChild(glyph);
    li.appendChild(document.createTextNode(` ${person.name}`));
    return li;
  });

  const hasStar = Array.from(view.symbols.values()).includes('star');
  if (hasStar) {
    const li = document.createElement('li');
    const glyph = document.createElement('span');
    glyph.setAttribute('aria-hidden', 'true');
    glyph.textContent = SHARED_GLYPH;
    li.appendChild(glyph);
    li.appendChild(document.createTextNode(' Shared booth'));
    items.push(li);
  }

  els.shapeLegend.replaceChildren(...items);
  els.shapeLegend.hidden = false;
}

/** Renders the counts-only match summary line (A1). */
function renderSummary(view) {
  const { count, detail } = summaryCopy(view.summary);
  els.summaryCount.textContent = count;
  els.summaryDetail.textContent = detail;
}

/** Pure DOM update from the current state/view, called every render cycle. */
export function renderTopbar({ data, state, view }) {
  els.selectionRow.hidden = state.people.length === 0;
  renderChips(data, state);
  renderToggles(state);
  els.clearSelection.hidden = state.people.length === 0;
  renderShapeLegend(data, state, view);
  renderSummary(view);

  const currentKey = personSelectionKey(state);
  if (compareNoteStickyKey !== null && currentKey !== compareNoteStickyKey) {
    compareNoteStickyKey = null;
  }
  els.compareNote.hidden = compareNoteStickyKey === null;
}
