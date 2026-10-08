/**
 * Announcer list, selected-people chips, the Compare people / Called
 * together toggles, the compare shape legend, Clear selection, and the
 * counts-only match summary line (SITE-02, SITE-08, SITE-10, D-07, D-08,
 * A1).
 *
 * D-21: the search combobox lives in the toolbar's Announcers popover
 * (`#pop-announcers`/`#filter-announcers`); the chips, toggles, and summary
 * live in `#selection-bar`'s `#selection-row` (hidden while no one is
 * selected) below the toolbar.
 *
 * D-28: `#person-results` is an Excel AutoFilter-style multi-select list --
 * every person is always rendered (one `<li role="option">` per person,
 * built once), filtered synchronously as the user types (no debounce), with
 * `aria-selected` meaning *checked* (in `state.people`), not the arrow-key
 * active row (that's the `is-active` class). Picking an unchecked row adds
 * that person, clears the search, and refocuses the input; picking a
 * checked row removes them and keeps the search text.
 *
 * D-08/D-09/D-11 (SITE-29): each row also carries a count (`view.facets.people`,
 * the person's telecasts under every other active filter and Role, ignoring
 * the person constraint itself, so selecting someone never changes the listed
 * set, in any match mode). A person with count 0 who is not checked is left
 * out of the list; a checked one stays, greyed, "(0)". The prebuilt rows are
 * never rebuilt: counts and `is-zero` are synced in place, and `renderList`
 * re-runs only when the set of facet-hidden ids changes, so the list keeps
 * its scroll position and active row across unrelated renders.
 *
 * `initTopbar(ctx)` binds every DOM event listener once; `renderTopbar(ctx)`
 * is a pure DOM update driven by the current state/view, called every render
 * cycle from app.js. DOM is built only with createElement/textContent/
 * replaceChildren -- never any markup-injecting DOM API (T-04.1-29,
 * T-04.1-38). Typed search text is only ever used as a search key and a
 * `dataset.query` value, never rendered as markup, and person/team names
 * always land in the DOM via textContent.
 */

import { searchPeople } from './data.js';
import { MAX_COMPARE } from './select.js';
import { summaryCopy } from './format.js';
import { makeRolePill } from './pill.js';
import { COMPARE_GLYPHS, COMPARE_SYMBOLS, SHARED_GLYPH } from './palette.js';
import { MAP_SHAPES_CAPTION } from './map-model.js';

const BASE_COMPARE_HELP = 'Compare up to 4 people — each gets its own shape.';
const OVER_LIMIT_SUFFIX = ' Remove people to use compare.';

/** DOM element references, populated once by `initTopbar`. */
let els = null;

/** The `prepareData` result, kept for `renderList`'s `searchPeople` calls. */
let dataRef = null;

/** Every option `<li>`, built once in `initTopbar`, keyed by person id. */
let optionsById = new Map();

/** Every option `<li>`, in alphabetical order (the empty-query list). */
let allRowsOrdered = [];

/** The rows currently rendered in `#person-results` (excludes the "no matching announcers" placeholder). */
let currentRows = [];

/** Index into `currentRows` the user has moved to with ArrowUp/ArrowDown, or -1. */
let activeIndex = -1;

/** Selection key the compare-note was last shown for, or null when hidden (D-07). */
let compareNoteStickyKey = null;

/** Person ids whose count is 0 and who are not checked: left out of the list (D-11). */
let facetHiddenIds = new Set();

/** Sorted, joined `facetHiddenIds`, so `renderTopbar` knows when the offered set changed. */
let facetSignature = null;

/** A key identifying the current people/compare selection, for the compare-note sticky logic. */
function personSelectionKey(state) {
  return `${state.people.join(',')}|${state.compare}`;
}

/** Builds every option `<li>` once, in alphabetical order (D-28). */
function buildOptionRows(data) {
  optionsById = new Map();
  const ordered = data.lookups.people
    .map((p, index) => ({ ...p, index }))
    .sort((a, b) => a.name.localeCompare(b.name) || a.id.localeCompare(b.id));

  allRowsOrdered = ordered.map((p) => {
    const li = document.createElement('li');
    li.id = `person-opt-${p.index}`;
    li.setAttribute('role', 'option');
    li.setAttribute('aria-selected', 'false');
    li.dataset.personId = p.id;

    const checkSpan = document.createElement('span');
    checkSpan.className = 'option-check';
    checkSpan.setAttribute('aria-hidden', 'true');
    li.appendChild(checkSpan);

    const nameSpan = document.createElement('span');
    nameSpan.className = 'option-name';
    nameSpan.textContent = p.name;
    li.appendChild(nameSpan);

    const variantSpan = document.createElement('span');
    variantSpan.className = 'option-variant';
    li.appendChild(variantSpan);

    const roleSpan = document.createElement('span');
    roleSpan.className = 'option-role';
    roleSpan.appendChild(makeRolePill(p.usual_role));
    li.appendChild(roleSpan);

    const countSpan = document.createElement('span');
    countSpan.className = 'option-count';
    countSpan.setAttribute('aria-hidden', 'true');
    li.appendChild(countSpan);

    const countSr = document.createElement('span');
    countSr.className = 'visually-hidden option-count-sr';
    li.appendChild(countSr);

    optionsById.set(p.id, li);
    return li;
  });
}

/** Renders `#person-results` for the given raw query (D-28): an empty,
 * trimmed query shows every row alphabetically; otherwise only the rows
 * `searchPeople` matches, in ranked order, with their variant note filled
 * in. Reorders/reuses the prebuilt rows -- never rebuilds them. */
function renderList(rawValue) {
  const query = rawValue.trim();
  activeIndex = -1;
  els.input.removeAttribute('aria-activedescendant');

  let rows;
  const variantById = new Map();
  if (query === '') {
    rows = allRowsOrdered.filter((li) => !facetHiddenIds.has(li.dataset.personId));
  } else {
    const results = searchPeople(dataRef, query, Infinity).filter(
      (r) => !facetHiddenIds.has(r.id),
    );
    rows = results.map((r) => optionsById.get(r.id));
    for (const r of results) variantById.set(r.id, r.matchedVariant);
  }

  for (const li of allRowsOrdered) {
    const variantSpan = li.querySelector('.option-variant');
    const matched = variantById.get(li.dataset.personId);
    variantSpan.textContent = matched ? ` (as “${matched}”)` : '';
  }

  if (rows.length === 0) {
    const li = document.createElement('li');
    li.setAttribute('role', 'option');
    li.setAttribute('aria-disabled', 'true');
    li.textContent = query === '' ? 'No announcers match these filters' : 'No matching announcers';
    els.results.replaceChildren(li);
    currentRows = [];
  } else {
    els.results.replaceChildren(...rows);
    currentRows = rows;
  }
  els.results.dataset.query = query;
}

/** Syncs the arrow-key `is-active` row and `aria-activedescendant` to `activeIndex`, and scrolls it into view. */
function updateActiveDescendant() {
  currentRows.forEach((li, i) => {
    li.classList.toggle('is-active', i === activeIndex);
  });
  const activeLi = currentRows[activeIndex];
  if (activeLi) {
    els.input.setAttribute('aria-activedescendant', activeLi.id);
    activeLi.scrollIntoView({ block: 'nearest' });
  } else {
    els.input.removeAttribute('aria-activedescendant');
  }
}

/** Shows the "Compare mode holds up to 4 people." note, sticky until the selection changes. */
function showCompareNote(state) {
  compareNoteStickyKey = personSelectionKey(state);
  els.compareNote.hidden = false;
}

/** Adds a person by id, respecting the MAX_COMPARE cap (D-07), then clears
 * and refocuses the search field and resets the list to the full alphabetical
 * order (D-28). */
function addPerson(getState, setState, id) {
  const state = getState();
  if (state.compare && state.people.length >= MAX_COMPARE) {
    showCompareNote(state);
    return;
  }
  setState({ people: [...state.people, id] });
  els.input.value = '';
  renderList('');
  els.input.focus();
}

/** Toggles one person's selection from an option `<li>` (D-28): adds them
 * via `addPerson` if unchecked, else removes them and keeps the search text
 * and input focus. */
function togglePerson(getState, setState, li) {
  const id = li.dataset.personId;
  const state = getState();
  if (state.people.includes(id)) {
    setState({ people: state.people.filter((personId) => personId !== id) });
    // Clicking a non-focusable `<li>` shifts the browser's own focus away
    // from the input (there's nothing else to hold it); keep it there, per
    // D-28 ("focus stays in the input" -- the search text is untouched).
    els.input.focus();
  } else {
    addPerson(getState, setState, id);
  }
}

/** Binds every top-bar DOM event listener once. `getState` always returns the latest state. */
export function initTopbar({ data, getState, setState }) {
  dataRef = data;
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

  buildOptionRows(data);
  renderList('');

  els.input.addEventListener('input', () => {
    renderList(els.input.value);
  });

  els.input.addEventListener('keydown', (ev) => {
    if (ev.key === 'ArrowDown') {
      if (currentRows.length === 0) return;
      ev.preventDefault();
      activeIndex = Math.min(activeIndex + 1, currentRows.length - 1);
      updateActiveDescendant();
    } else if (ev.key === 'ArrowUp') {
      if (currentRows.length === 0) return;
      ev.preventDefault();
      activeIndex = Math.max(activeIndex - 1, 0);
      updateActiveDescendant();
    } else if (ev.key === 'Enter') {
      let li = null;
      if (activeIndex >= 0 && currentRows[activeIndex]) {
        li = currentRows[activeIndex];
      } else {
        const query = els.input.value.trim();
        if (query === '') return;
        li = currentRows.find((row) => row.getAttribute('aria-selected') === 'false') ?? null;
      }
      if (!li) return;
      ev.preventDefault();
      togglePerson(getState, setState, li);
    }
  });

  els.results.addEventListener('click', (ev) => {
    const li = ev.target.closest('li[role="option"]:not([aria-disabled])');
    if (!li || !li.dataset.personId) return;
    togglePerson(getState, setState, li);
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

    // D-30: this slot is always present (never conditional on
    // `state.compare`) so toggling Compare only changes its text, never
    // whether the chip has one -- the fixed-width `.chip-glyph` CSS rule
    // then means toggling Compare shifts no chip or toggle button.
    const glyph = document.createElement('span');
    glyph.className = 'chip-glyph';
    glyph.setAttribute('aria-hidden', 'true');
    glyph.textContent = state.compare ? (COMPARE_GLYPHS[position] ?? '') : '';
    li.appendChild(glyph);

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

/** One shape-legend item: an aria-hidden glyph, then the name. Shared by the scatter and Map legends. */
function legendItem(glyphText, name) {
  const li = document.createElement('li');
  const glyph = document.createElement('span');
  glyph.setAttribute('aria-hidden', 'true');
  glyph.textContent = glyphText;
  li.appendChild(glyph);
  li.appendChild(document.createTextNode(` ${name}`));
  return li;
}

/**
 * The Map's shape legend (04.18 D-05): glyph and name per subject for the first four,
 * a Shared booth item when a shared game is drawn, and the cap caption past four.
 * Hidden and emptied with fewer than two subjects.
 * @param {HTMLElement} el
 * @param {object} model - a buildMapModel result.
 */
export function renderMapShapeLegend(el, model) {
  if (!el) return;
  if (!model || model.subjects.length < 2) {
    el.hidden = true;
    el.replaceChildren();
    return;
  }
  const items = model.subjects.slice(0, MAX_COMPARE).map((subject) => {
    const at = COMPARE_SYMBOLS.indexOf(subject.symbol);
    return legendItem(COMPARE_GLYPHS[at] ?? '', subject.label);
  });
  if (model.hasShared) items.push(legendItem(SHARED_GLYPH, 'Shared booth'));
  if (model.shapesCapped) {
    const caption = document.createElement('li');
    caption.className = 'shape-legend-caption';
    caption.textContent = MAP_SHAPES_CAPTION[model.subjects[0].kind];
    items.push(caption);
  }
  el.replaceChildren(...items);
  el.hidden = false;
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
    return legendItem(COMPARE_GLYPHS[position] ?? '', person.name);
  });

  const hasStar = Array.from(view.symbols.values()).includes('star');
  if (hasStar) {
    items.push(legendItem(SHARED_GLYPH, 'Shared booth'));
  }

  els.shapeLegend.replaceChildren(...items);
  els.shapeLegend.hidden = false;
}

/** Renders the counts-only match summary line (A1). */
function renderSummary(view) {
  const { count, detail } = summaryCopy(view.summary);
  els.summaryCount.textContent = count;
  els.summaryDetail.textContent = detail;
  // The line ends in an ellipsis when it does not fit; the title keeps the full text.
  els.summaryDetail.title = detail;
}

/** Syncs every option row's `aria-selected` (checked state) from
 * `state.people` (D-28). Never rebuilds rows, so scroll position survives a
 * check/uncheck; covers URL-loaded, Clear selection, and Clear all filters
 * (D-27) states alike. */
function renderPersonList(state) {
  for (const [id, li] of optionsById) {
    li.setAttribute('aria-selected', String(state.people.includes(id)));
  }
}

/** Syncs every row's count and `is-zero` from `view.facets.people` (D-09/D-11),
 * and re-renders the list only when the facet-hidden set changed. */
function renderPersonFacets(state, view) {
  const counts = view.facets?.people;
  if (!counts) return;
  const hidden = new Set();
  for (const [id, li] of optionsById) {
    const count = counts[dataRef.personIndexById.get(id)] ?? 0;
    const selected = state.people.includes(id);
    const text = `(${count})`;
    const visible = li.querySelector('.option-count');
    if (visible.textContent !== text) visible.textContent = text;
    const srText = `, ${count} ${count === 1 ? 'game' : 'games'}`;
    const sr = li.querySelector('.option-count-sr');
    if (sr.textContent !== srText) sr.textContent = srText;
    li.classList.toggle('is-zero', count === 0 && selected);
    if (count === 0 && !selected) hidden.add(id);
  }
  const signature = [...hidden].sort().join(',');
  if (signature !== facetSignature) {
    facetSignature = signature;
    facetHiddenIds = hidden;
    renderList(els.input.value);
  }
}

/** Pure DOM update from the current state/view, called every render cycle. */
export function renderTopbar({ data, state, view }) {
  els.selectionRow.hidden = state.people.length === 0;
  renderChips(data, state);
  renderToggles(state);
  els.clearSelection.hidden = state.people.length === 0;
  renderShapeLegend(data, state, view);
  renderSummary(view);
  renderPersonList(state);
  renderPersonFacets(state, view);

  const currentKey = personSelectionKey(state);
  if (compareNoteStickyKey !== null && currentKey !== compareNoteStickyKey) {
    compareNoteStickyKey = null;
  }
  els.compareNote.hidden = compareNoteStickyKey === null;
}
