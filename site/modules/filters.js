/**
 * Filter toolbar: an Announcers popover plus seven filter popovers (Seasons,
 * Networks, Kickoff, Role, Conference, School, Bowls/Playoffs) above the
 * chart, plus "Clear all filters" and a full-height phone bottom sheet that
 * stacks every section, Announcers first (SITE-20, SITE-21, SITE-22,
 * SITE-24, SITE-27; D-02, D-03, D-10, D-11, D-18, D-21, D-27).
 *
 * D-21: the Announcers popover holds the moved person-search combobox
 * (`site/modules/topbar.js` still owns its search/add-person behavior; this
 * module only places its `#filter-announcers` section and reports its
 * trigger label/active state). D-27: "Clear all filters" also clears
 * `state.people`/`compare`/`together`, and the phone `Filters(N)` badge
 * counts selected people too.
 *
 * `initFilters(ctx)` builds the dynamic parts of the toolbar (the network
 * checklist, the conference/school checklists, the role helper line) once
 * and binds every DOM event listener, including the native `popover`
 * open/close mechanics and the desktop/mobile section placement;
 * `renderFilters(ctx)` is a pure DOM update called every render cycle from
 * app.js -- the same init-once/render-every-time split topbar.js uses. DOM
 * is built only with createElement/textContent/replaceChildren -- never any
 * markup-injecting DOM API (T-04-31). Typed conference/school search text is
 * only ever used as a search key, never rendered as markup; conference/team
 * names always land in the DOM via textContent.
 */

import { normalizeName } from './data.js';
import { FAMILY_LABELS } from './palette.js';
import { SLOT_SHORT_LABELS, ROLE_LABELS } from './format.js';

const ROLE_HELPER_TEXT = 'Limits matches to main-broadcast play-by-play or analyst roles.';

/** Section element id -> the popover id it lives in on desktop, in toolbar order (D-02, D-21). */
const SECTION_POPOVERS = [
  ['filter-announcers', 'pop-announcers'],
  ['filter-seasons', 'pop-seasons'],
  ['filter-networks', 'pop-networks'],
  ['filter-slots', 'pop-kickoff'],
  ['filter-role', 'pop-role'],
  ['filter-conference', 'pop-conference'],
  ['filter-school', 'pop-school'],
  ['filter-postseason', 'pop-postseason'],
];

/** Toolbar trigger names, in toolbar order -- also `#trigger-{name}`'s id suffix. */
const TRIGGER_NAMES = ['announcers', 'seasons', 'networks', 'kickoff', 'role', 'conference', 'school', 'postseason'];

/** Bowls/Playoffs radio values, in the DOM order they appear in `#postseason-options`. */
const POSTSEASON_ORDER = ['all', 'exclude', 'only'];

/** DOM element references, populated once by `initFilters`. */
let els = null;

/** network id -> its checkbox element, populated once by `buildNetworkChecklist`. */
let networkCheckboxes = new Map();

/** family key -> its checkbox element, populated once by `buildNetworkChecklist`. */
let familyCheckboxes = new Map();

/** conference name -> its checkbox element, populated once by `buildConferenceList`. */
let conferenceCheckboxes = new Map();

/** team slug -> its checkbox element, populated once by `buildSchoolList`. */
let schoolCheckboxes = new Map();

/** team slug -> its search keys (from `data.teamKeys`), populated once by `buildSchoolList`. */
let schoolKeysBySlug = new Map();

/** Network ids for every primary network in a given family. */
function familyNetworkIds(data, familyKeyVal) {
  return (data.networksByFamily.get(familyKeyVal) ?? []).map((idx) => data.lookups.networks[idx].id);
}

/** Network ids for every primary network across all families (the "unfiltered" set). */
function allPrimaryNetworkIds(data) {
  return data.primaryNetworks.map((idx) => data.lookups.networks[idx].id);
}

/** Orders a set of network ids the way `data.lookups.networks` lists them. */
function networksInLookupOrder(data, idSet) {
  return data.lookups.networks.map((net) => net.id).filter((id) => idSet.has(id));
}

/** Builds the season-range `<select>` options once, from `data.seasons`. */
function buildSeasonSelects(data) {
  const optionsFor = () =>
    data.seasons.map((season) => {
      const opt = document.createElement('option');
      opt.value = String(season);
      opt.textContent = String(season);
      return opt;
    });
  els.seasonFrom.replaceChildren(...optionsFor());
  els.seasonTo.replaceChildren(...optionsFor());
}

/** Builds the family-nested network checklist once, from `data.families`/`networksByFamily` (D-06). */
function buildNetworkChecklist(data) {
  const heading = els.networksSection.querySelector('h3');
  networkCheckboxes = new Map();
  familyCheckboxes = new Map();

  const groups = data.families.map((familyKeyVal) => {
    const fieldset = document.createElement('fieldset');
    fieldset.className = 'family-group';

    const legend = document.createElement('legend');
    const familyLabel = document.createElement('label');
    const familyCheckbox = document.createElement('input');
    familyCheckbox.type = 'checkbox';
    familyCheckbox.dataset.familyCheckbox = familyKeyVal;
    familyLabel.appendChild(familyCheckbox);
    familyLabel.appendChild(document.createTextNode(` ${FAMILY_LABELS[familyKeyVal]}`));
    legend.appendChild(familyLabel);
    fieldset.appendChild(legend);
    familyCheckboxes.set(familyKeyVal, familyCheckbox);

    const list = document.createElement('ul');
    list.className = 'network-list';
    const netIdxs = data.networksByFamily.get(familyKeyVal) ?? [];
    for (const idx of netIdxs) {
      const net = data.lookups.networks[idx];
      const li = document.createElement('li');
      const label = document.createElement('label');
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.dataset.networkId = net.id;
      label.appendChild(checkbox);
      label.appendChild(document.createTextNode(` ${net.name}`));
      li.appendChild(label);
      list.appendChild(li);
      networkCheckboxes.set(net.id, checkbox);
    }
    fieldset.appendChild(list);
    return fieldset;
  });

  els.networksSection.replaceChildren(...(heading ? [heading] : []), ...groups);
}

/** Appends the role-filter helper line once, under the static role checkboxes (SITE-07). */
function buildRoleHelper() {
  const p = document.createElement('p');
  p.className = 'helper';
  p.textContent = ROLE_HELPER_TEXT;
  els.roleSection.appendChild(p);
}

/** Builds the Conference popover's checklist once, from `data.fbsConferences` (D-10). */
function buildConferenceList(data) {
  conferenceCheckboxes = new Map();
  const rows = data.fbsConferences.map((name) => {
    const label = document.createElement('label');
    label.className = 'check-row';
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.name = 'conference';
    checkbox.value = name;
    label.appendChild(checkbox);
    label.appendChild(document.createTextNode(` ${name}`));
    conferenceCheckboxes.set(name, checkbox);
    return label;
  });
  els.conferenceList.append(...rows);
}

/** Builds the School popover's checklist once, from every team, sorted by name (D-11). */
function buildSchoolList(data) {
  schoolCheckboxes = new Map();
  schoolKeysBySlug = new Map();
  const sortedTeams = data.teamKeys.slice().sort((a, b) => a.name.localeCompare(b.name));
  const rows = sortedTeams.map((team) => {
    const label = document.createElement('label');
    label.className = 'check-row';
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.name = 'school';
    checkbox.value = team.slug;
    label.appendChild(checkbox);
    label.appendChild(document.createTextNode(` ${team.name}`));
    schoolCheckboxes.set(team.slug, checkbox);
    schoolKeysBySlug.set(team.slug, team.keys);
    return label;
  });
  els.schoolList.append(...rows);
}

/** Hides checklist rows whose keys (via `keysFor`) don't contain the normalized query. */
function filterChecklist(listEl, query, keysFor) {
  const q = normalizeName(query);
  for (const row of listEl.querySelectorAll('label.check-row')) {
    const checkbox = row.querySelector('input[type="checkbox"]');
    if (q === '') {
      row.hidden = false;
      continue;
    }
    const keys = keysFor(checkbox);
    row.hidden = !keys.some((k) => k.includes(q));
  }
}

/** Every checkbox in `listEl` whose row is currently visible, in DOM order. */
function visibleCheckboxes(listEl) {
  return Array.from(listEl.querySelectorAll('label.check-row'))
    .filter((row) => !row.hidden)
    .map((row) => row.querySelector('input[type="checkbox"]'));
}

/** Wires ArrowUp/ArrowDown keyboard navigation between a search input and its checklist. */
function bindChecklistKeyboard(searchInput, listEl) {
  searchInput.addEventListener('keydown', (ev) => {
    if (ev.key !== 'ArrowDown') return;
    const boxes = visibleCheckboxes(listEl);
    if (boxes.length === 0) return;
    ev.preventDefault();
    boxes[0].focus();
  });

  listEl.addEventListener('keydown', (ev) => {
    if (ev.key !== 'ArrowDown' && ev.key !== 'ArrowUp') return;
    const target = ev.target;
    if (!(target instanceof HTMLInputElement) || target.type !== 'checkbox') return;
    const boxes = visibleCheckboxes(listEl);
    const idx = boxes.indexOf(target);
    if (idx === -1) return;
    ev.preventDefault();
    if (ev.key === 'ArrowDown') {
      if (idx < boxes.length - 1) boxes[idx + 1].focus();
    } else if (idx > 0) {
      boxes[idx - 1].focus();
    } else {
      searchInput.focus();
    }
  });
}

/**
 * Wires the WAI-ARIA APG radiogroup keyboard pattern to the Bowls/Playoffs
 * `role="radio"` buttons (roving tabindex; ArrowLeft/ArrowUp and
 * ArrowRight/ArrowDown move focus and selection together; Home/End jump to
 * the first/last option) -- required because `role="radiogroup"`/`role="radio"`
 * promise this behavior to assistive tech (WR-05).
 */
function bindPostseasonKeyboard(setState) {
  els.postseasonOptions.addEventListener('keydown', (ev) => {
    const key = ev.key;
    if (!['ArrowLeft', 'ArrowUp', 'ArrowRight', 'ArrowDown', 'Home', 'End'].includes(key)) return;
    const target = ev.target;
    if (!(target instanceof HTMLElement) || !target.dataset.postseason) return;
    const idx = POSTSEASON_ORDER.indexOf(target.dataset.postseason);
    if (idx === -1) return;
    ev.preventDefault();

    let nextIdx;
    if (key === 'Home') {
      nextIdx = 0;
    } else if (key === 'End') {
      nextIdx = POSTSEASON_ORDER.length - 1;
    } else if (key === 'ArrowRight' || key === 'ArrowDown') {
      nextIdx = (idx + 1) % POSTSEASON_ORDER.length;
    } else {
      nextIdx = (idx - 1 + POSTSEASON_ORDER.length) % POSTSEASON_ORDER.length;
    }

    const nextValue = POSTSEASON_ORDER[nextIdx];
    setState({ postseason: nextValue });
    // setState -> render() runs synchronously, so renderPostseason has
    // already synced tabindex/aria-checked by the time this runs.
    els.postseasonOptions.querySelector(`[data-postseason="${nextValue}"]`)?.focus();
  });
}

/** Applies a family/network checkbox change to state, in lookup order (D-06). */
function handleNetworksChange(data, getState, setState, ev) {
  const target = ev.target;
  const current = new Set(getState().networks ?? allPrimaryNetworkIds(data));
  if (target.dataset.familyCheckbox) {
    const ids = familyNetworkIds(data, target.dataset.familyCheckbox);
    if (target.checked) ids.forEach((id) => current.add(id));
    else ids.forEach((id) => current.delete(id));
  } else if (target.dataset.networkId) {
    if (target.checked) current.add(target.dataset.networkId);
    else current.delete(target.dataset.networkId);
  } else {
    return;
  }
  setState({ networks: networksInLookupOrder(data, current) });
}

/** Reads the checked `#filter-slots` checkboxes into a state patch (SITE-11). */
function handleSlotsChange(setState) {
  const checked = Array.from(els.slotsSection.querySelectorAll('input[name="slot"]:checked')).map(
    (cb) => cb.value,
  );
  setState({ slots: checked.length > 0 ? checked : null });
}

/** Makes the two role checkboxes mutually exclusive and updates state (SITE-07, D-08). */
function handleRoleChange(setState, ev) {
  const target = ev.target;
  if (target.name !== 'role') return;
  if (target.checked) {
    for (const cb of els.roleSection.querySelectorAll('input[name="role"]')) {
      if (cb !== target) cb.checked = false;
    }
    setState({ role: target.value });
  } else {
    setState({ role: null });
  }
}

/** Reads the checked Conference checkboxes into a state patch, in `data.fbsConferences` order (D-10). */
function handleConferenceChange(data, setState) {
  const checked = new Set();
  for (const [name, cb] of conferenceCheckboxes) if (cb.checked) checked.add(name);
  setState({ conferences: data.fbsConferences.filter((name) => checked.has(name)) });
}

/** Reads the checked School checkboxes into a state patch (D-11). */
function handleSchoolChange(setState) {
  const checked = [];
  for (const [slug, cb] of schoolCheckboxes) if (cb.checked) checked.push(slug);
  setState({ school: checked });
}

/** Positions a filter popover under its trigger button, clamped to stay on-screen (Pitfall 2). */
function positionPopover(popover, trigger) {
  const rect = trigger.getBoundingClientRect();
  popover.style.top = `${rect.bottom + 4}px`;
  const maxLeft = Math.max(8, window.innerWidth - popover.offsetWidth - 8);
  popover.style.left = `${Math.max(8, Math.min(rect.left, maxLeft))}px`;
}

/** The first focusable element inside a popover: its search input, else its first input/button. */
function firstFocusable(container) {
  return container.querySelector('input, button, [tabindex]:not([tabindex="-1"])');
}

/** Wires open/close focus management and (for filter popovers) `beforetoggle` positioning for one popover. */
function bindPopoverMechanics(popover) {
  const isFilterPopover = popover.classList.contains('filter-popover');
  if (isFilterPopover) {
    // A5: position BEFORE the popover is shown. `toggle` is queued after the popover is
    // shown, so the first frame painted at the static (0,0) position or at a stale
    // top/left from the previous open. Sync call: top is exact, but left is unclamped
    // because offsetWidth is 0 while the popover is still display:none. The rAF refine
    // runs in the first rendering update after show, before paint, so the clamp is exact.
    popover.addEventListener('beforetoggle', (ev) => {
      if (ev.newState !== 'open') return;
      const trigger = document.querySelector(`[popovertarget="${popover.id}"]`);
      if (!trigger) return;
      positionPopover(popover, trigger);
      requestAnimationFrame(() => {
        if (popover.matches(':popover-open')) positionPopover(popover, trigger);
      });
    });
  }
  popover.addEventListener('toggle', (ev) => {
    const trigger = document.querySelector(`[popovertarget="${popover.id}"]`);
    if (ev.newState === 'open') {
      if (trigger) trigger.setAttribute('aria-expanded', 'true');
      const focusable = firstFocusable(popover);
      if (focusable) focusable.focus();
    } else {
      if (trigger) trigger.setAttribute('aria-expanded', 'false');
      const active = document.activeElement;
      if (trigger && (popover.contains(active) || active === document.body)) {
        trigger.focus();
      }
    }
  });
}

/** Repositions every currently-open filter popover (window scroll/resize, Pitfall 2). */
function repositionOpenPopovers() {
  for (const popover of document.querySelectorAll('.filter-popover:popover-open')) {
    const trigger = document.querySelector(`[popovertarget="${popover.id}"]`);
    if (trigger) positionPopover(popover, trigger);
  }
}

/**
 * Moves "Clear all filters" and every filter section between the desktop
 * popovers and the phone bottom sheet, closing any open popover first.
 * @param {boolean} isMobile
 */
function placeSections(isMobile) {
  for (const popover of document.querySelectorAll('.filter-popover:popover-open, .filters-sheet:popover-open')) {
    popover.hidePopover();
  }
  if (isMobile) {
    els.sheetClearSlot.appendChild(els.clearFilters);
    for (const [sectionId] of SECTION_POPOVERS) {
      els.sheetBody.appendChild(document.getElementById(sectionId));
    }
  } else {
    els.toolbar.insertBefore(els.clearFilters, els.toolbar.firstChild);
    for (const [sectionId, popoverId] of SECTION_POPOVERS) {
      document.getElementById(popoverId).appendChild(document.getElementById(sectionId));
    }
  }
}

/** Binds every toolbar/popover/sheet DOM event listener once. `getState` always returns the latest state. */
export function initFilters({ data, getState, setState }) {
  els = {
    toolbar: document.getElementById('toolbar'),
    seasonFrom: document.getElementById('season-from'),
    seasonTo: document.getElementById('season-to'),
    seasonCounts: document.getElementById('season-counts'),
    networksSection: document.getElementById('filter-networks'),
    slotsSection: document.getElementById('filter-slots'),
    roleSection: document.getElementById('filter-role'),
    conferenceSearch: document.getElementById('conference-search'),
    conferenceList: document.getElementById('conference-list'),
    schoolSearch: document.getElementById('school-search'),
    schoolChips: document.getElementById('school-chips'),
    schoolList: document.getElementById('school-list'),
    postseasonOptions: document.getElementById('postseason-options'),
    clearFilters: document.getElementById('clear-filters'),
    filtersButton: document.getElementById('filters-button'),
    filtersShowResults: document.getElementById('filters-show-results'),
    sheetClearSlot: document.querySelector('.sheet-clear-slot'),
    sheetBody: document.querySelector('.sheet-body'),
    triggers: Object.fromEntries(
      TRIGGER_NAMES.map((name) => [name, document.getElementById(`trigger-${name}`)]),
    ),
  };

  buildSeasonSelects(data);
  buildNetworkChecklist(data);
  buildRoleHelper();
  buildConferenceList(data);
  buildSchoolList(data);

  const onSeasonChange = () => {
    const from = Number(els.seasonFrom.value);
    const to = Number(els.seasonTo.value);
    // A blank select reads as Number('') === 0; never turn that into a range (WR-13).
    if (!Number.isInteger(from) || !Number.isInteger(to) || from <= 0 || to <= 0) return;
    setState({ seasons: [from, to] });
  };
  els.seasonFrom.addEventListener('change', onSeasonChange);
  els.seasonTo.addEventListener('change', onSeasonChange);

  els.networksSection.addEventListener('change', (ev) => handleNetworksChange(data, getState, setState, ev));

  els.slotsSection.addEventListener('change', () => handleSlotsChange(setState));

  els.roleSection.addEventListener('change', (ev) => handleRoleChange(setState, ev));

  els.conferenceList.addEventListener('change', () => handleConferenceChange(data, setState));
  els.conferenceSearch.addEventListener('input', () => {
    filterChecklist(els.conferenceList, els.conferenceSearch.value, (cb) => [normalizeName(cb.value)]);
  });
  bindChecklistKeyboard(els.conferenceSearch, els.conferenceList);

  els.schoolList.addEventListener('change', () => handleSchoolChange(setState));
  els.schoolSearch.addEventListener('input', () => {
    filterChecklist(els.schoolList, els.schoolSearch.value, (cb) => schoolKeysBySlug.get(cb.value) ?? []);
  });
  bindChecklistKeyboard(els.schoolSearch, els.schoolList);

  els.schoolChips.addEventListener('click', (ev) => {
    const btn = ev.target.closest('.chip-remove');
    if (!btn || !btn.dataset.slug) return;
    setState({ school: getState().school.filter((slug) => slug !== btn.dataset.slug) });
  });

  els.postseasonOptions.addEventListener('click', (ev) => {
    const btn = ev.target.closest('[data-postseason]');
    if (!btn) return;
    setState({ postseason: btn.dataset.postseason });
  });
  bindPostseasonKeyboard(setState);

  els.clearFilters.addEventListener('click', () => {
    setState({
      seasons: null,
      networks: null,
      slots: null,
      role: null,
      conferences: [],
      school: [],
      postseason: 'all',
      // D-27 (overrides the earlier "people are not cleared" proposal):
      // Clear all filters also removes every selected announcer, compare
      // mode, and called-together. "Clear selection" in the chip row still
      // clears only the people.
      people: [],
      compare: false,
      together: false,
    });
  });

  els.filtersShowResults.addEventListener('click', () => {
    document.getElementById('filters-sheet').hidePopover();
  });

  for (const popover of document.querySelectorAll('.filter-popover, .filters-sheet')) {
    bindPopoverMechanics(popover);
  }
  window.addEventListener('scroll', repositionOpenPopovers, { passive: true });
  window.addEventListener('resize', repositionOpenPopovers);

  const mobileMedia = window.matchMedia('(max-width: 640px)');
  placeSections(mobileMedia.matches);
  mobileMedia.addEventListener('change', (ev) => placeSections(ev.matches));
}

/** Renders the season range selects and the per-season counts list (D-13 counts). */
function renderSeasons(data, state, view) {
  const [minSeason, maxSeason] = state.seasons ?? [data.seasonMin, data.seasonMax];
  els.seasonFrom.value = String(minSeason);
  els.seasonTo.value = String(maxSeason);

  const items = view.seasonCounts.map(([season, count]) => {
    const li = document.createElement('li');
    if (season < minSeason || season > maxSeason) li.className = 'out-of-range';
    const word = count === 1 ? 'rated telecast' : 'rated telecasts';
    li.textContent = `${season}: ${count} ${word}`;
    return li;
  });
  els.seasonCounts.replaceChildren(...items);
}

/** Syncs the network checklist's checked/indeterminate state from `state.networks` (D-06). */
function renderNetworks(data, state) {
  const currentIds = state.networks ?? allPrimaryNetworkIds(data);
  for (const familyKeyVal of data.families) {
    const netIdxs = data.networksByFamily.get(familyKeyVal) ?? [];
    let checkedCount = 0;
    for (const idx of netIdxs) {
      const net = data.lookups.networks[idx];
      const checkbox = networkCheckboxes.get(net.id);
      const checked = currentIds.includes(net.id);
      checkbox.checked = checked;
      if (checked) checkedCount += 1;
    }
    const familyCheckbox = familyCheckboxes.get(familyKeyVal);
    familyCheckbox.checked = netIdxs.length > 0 && checkedCount === netIdxs.length;
    familyCheckbox.indeterminate = checkedCount > 0 && checkedCount < netIdxs.length;
  }
}

/** Syncs the time-slot checkboxes from `state.slots` (SITE-11). */
function renderSlots(state) {
  for (const cb of els.slotsSection.querySelectorAll('input[name="slot"]')) {
    cb.checked = state.slots != null && state.slots.includes(cb.value);
  }
}

/** Syncs the role checkboxes from `state.role` (SITE-07). */
function renderRole(state) {
  for (const cb of els.roleSection.querySelectorAll('input[name="role"]')) {
    cb.checked = state.role === cb.value;
  }
}

/** Syncs the Conference checklist's checked state from `state.conferences` (D-10). */
function renderConferences(state) {
  for (const [name, cb] of conferenceCheckboxes) {
    cb.checked = state.conferences.includes(name);
  }
}

/** Syncs the School checklist's checked state and `#school-chips` from `state.school` (D-11). */
function renderSchool(data, state) {
  for (const [slug, cb] of schoolCheckboxes) {
    cb.checked = state.school.includes(slug);
  }
  const items = state.school.map((slug) => {
    const idx = data.teamIndexBySlug.get(slug);
    const team = data.lookups.teams[idx];
    const li = document.createElement('li');
    li.className = 'chip';
    const nameSpan = document.createElement('span');
    nameSpan.textContent = team.name;
    const removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.className = 'chip-remove';
    removeBtn.textContent = '×';
    removeBtn.setAttribute('aria-label', `Remove ${team.name}`);
    removeBtn.dataset.slug = slug;
    li.appendChild(nameSpan);
    li.appendChild(removeBtn);
    return li;
  });
  els.schoolChips.replaceChildren(...items);
}

/**
 * Syncs the Bowls/Playoffs radio group's `aria-checked` from `state.postseason`
 * (D-18), and its roving `tabindex` (WR-05): only the selected radio is a tab
 * stop, per the WAI-ARIA APG radiogroup pattern `bindPostseasonKeyboard` wires
 * the arrow-key/Home/End half of.
 */
function renderPostseason(state) {
  for (const btn of els.postseasonOptions.querySelectorAll('[data-postseason]')) {
    const checked = btn.dataset.postseason === state.postseason;
    btn.setAttribute('aria-checked', String(checked));
    btn.tabIndex = checked ? 0 : -1;
  }
}

/** A toolbar trigger's label and active state, from `state` (D-02 copywriting). */
function triggerInfo(name, data, state) {
  if (name === 'announcers') {
    if (state.people.length === 0) return { label: 'Announcers', active: false };
    return { label: `Announcers · ${state.people.length}`, active: true };
  }
  if (name === 'seasons') {
    if (state.seasons == null) return { label: 'Seasons', active: false };
    const [a, b] = state.seasons;
    return { label: `Seasons ${a}–${b}`, active: true };
  }
  if (name === 'networks') {
    if (state.networks == null) return { label: 'Networks', active: false };
    return { label: `Networks · ${state.networks.length}`, active: true };
  }
  if (name === 'kickoff') {
    if (state.slots == null) return { label: 'Kickoff', active: false };
    const label =
      state.slots.length === 1 ? `Kickoff: ${SLOT_SHORT_LABELS[state.slots[0]]}` : `Kickoff · ${state.slots.length}`;
    return { label, active: true };
  }
  if (name === 'role') {
    if (state.role == null) return { label: 'Role', active: false };
    return { label: `Role: ${ROLE_LABELS[state.role]}`, active: true };
  }
  if (name === 'conference') {
    if (state.conferences.length === 0) return { label: 'Conference', active: false };
    const label =
      state.conferences.length === 1 ? `Conference: ${state.conferences[0]}` : `Conference · ${state.conferences.length}`;
    return { label, active: true };
  }
  if (name === 'school') {
    if (state.school.length === 0) return { label: 'School', active: false };
    if (state.school.length === 1) {
      const idx = data.teamIndexBySlug.get(state.school[0]);
      return { label: `School: ${data.lookups.teams[idx].name}`, active: true };
    }
    return { label: `School · ${state.school.length}`, active: true };
  }
  if (name === 'postseason') {
    if (state.postseason === 'all') return { label: 'Bowls/Playoffs', active: false };
    const label = state.postseason === 'exclude' ? 'Bowls/Playoffs: Exclude' : 'Bowls/Playoffs: Only';
    return { label, active: true };
  }
  return { label: name, active: false };
}

/** Renders every toolbar trigger's label and `data-active` state (D-02). */
function renderTriggers(data, state) {
  for (const name of TRIGGER_NAMES) {
    const btn = els.triggers[name];
    const { label, active } = triggerInfo(name, data, state);
    btn.textContent = label;
    btn.dataset.active = active ? 'true' : 'false';
  }
}

/** Counts the active filters, for the mobile Filters(N) button (extends SITE-18's rail-era count).
 * D-27: also counts every selected announcer, since the phone Announcers
 * picker lives inside this same Filters sheet and "Clear all filters"
 * clears people too. */
function activeFilterCount(state) {
  let n = 0;
  if (state.seasons != null) n += 1;
  if (state.networks != null) n += 1;
  if (state.slots != null) n += 1;
  if (state.role != null) n += 1;
  if (state.conferences.length > 0) n += 1;
  if (state.school.length > 0) n += 1;
  if (state.postseason !== 'all') n += 1;
  n += state.people.length;
  return n;
}

/** Renders the `#filters-button` label (SITE-18, D-03). */
function renderFiltersButton(state) {
  const n = activeFilterCount(state);
  els.filtersButton.textContent = n > 0 ? `Filters (${n})` : 'Filters';
}

/** Pure DOM update from the current data/state/view, called every render cycle. */
export function renderFilters({ data, state, view }) {
  renderSeasons(data, state, view);
  renderNetworks(data, state);
  renderSlots(state);
  renderRole(state);
  renderConferences(state);
  renderSchool(data, state);
  renderPostseason(state);
  renderTriggers(data, state);
  renderFiltersButton(state);
}
