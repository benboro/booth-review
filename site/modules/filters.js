/**
 * Left filter rail: season range with per-season counts, the family-nested
 * network checklist, time slot, role, and the team highlight combobox, plus
 * Clear all filters, desktop/tablet rail collapse, and the phone "Filters
 * (N)" bottom-sheet drawer (SITE-06, SITE-07, SITE-09, SITE-11, SITE-18;
 * D-05, D-06, D-08, D-09).
 *
 * `initFilters(ctx)` builds the dynamic parts of the rail (the network
 * checklist, the role helper line) once and binds every DOM event listener;
 * `renderFilters(ctx)` is a pure DOM update called every render cycle from
 * app.js -- the same init-once/render-every-time split topbar.js uses. DOM
 * is built only with createElement/textContent/replaceChildren -- never any
 * markup-injecting DOM API (T-04-31). Typed team-search text is only ever
 * used as a search key, never rendered as markup; network/team names always
 * land in the DOM via textContent.
 */

import { searchTeams } from './data.js';
import { FAMILY_LABELS } from './palette.js';

const DEBOUNCE_MS = 120;

const ROLE_HELPER_TEXT = 'Limits matches to main-broadcast play-by-play or analyst roles.';

/** DOM element references, populated once by `initFilters`. */
let els = null;

/** network id -> its checkbox element, populated once by `buildNetworkChecklist`. */
let networkCheckboxes = new Map();

/** family key -> its checkbox element, populated once by `buildNetworkChecklist`. */
let familyCheckboxes = new Map();

/** Debounce timer id for the team search input. */
let teamDebounceTimer = null;

/** The options currently rendered in `#team-results` (empty when closed or showing "no matches"). */
let teamOptions = [];

/** Index of the team option the user has moved to with ArrowUp/ArrowDown, or -1. */
let teamActiveIndex = -1;

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

/** Appends the D-08 role-filter helper line once, under the static role checkboxes. */
function buildRoleHelper() {
  const p = document.createElement('p');
  p.className = 'helper';
  p.textContent = ROLE_HELPER_TEXT;
  els.roleSection.appendChild(p);
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

/** Closes and clears the team-search results listbox. */
function closeTeamOptions() {
  els.teamResults.hidden = true;
  els.teamResults.replaceChildren();
  els.teamSearch.setAttribute('aria-expanded', 'false');
  els.teamSearch.removeAttribute('aria-activedescendant');
  teamOptions = [];
  teamActiveIndex = -1;
}

/** Renders the team-search results listbox for a non-empty query. */
function renderTeamOptions(results) {
  if (results.length === 0) {
    const li = document.createElement('li');
    li.setAttribute('role', 'option');
    li.setAttribute('aria-disabled', 'true');
    li.textContent = 'No matching teams';
    els.teamResults.replaceChildren(li);
  } else {
    const items = results.map((r, i) => {
      const li = document.createElement('li');
      li.id = `team-opt-${i}`;
      li.setAttribute('role', 'option');
      li.setAttribute('aria-selected', 'false');
      li.dataset.teamSlug = r.slug;
      li.textContent = r.name;
      return li;
    });
    els.teamResults.replaceChildren(...items);
  }
  els.teamResults.hidden = false;
  els.teamSearch.setAttribute('aria-expanded', 'true');
}

/** Re-runs the team search for the input's current value and re-renders the listbox. */
function updateTeamOptions(data, rawValue) {
  const query = rawValue.trim();
  if (query === '') {
    closeTeamOptions();
    return;
  }
  const results = searchTeams(data, query, 8);
  teamOptions = results;
  teamActiveIndex = -1;
  renderTeamOptions(results);
}

/** Syncs `aria-selected`/`aria-activedescendant` to the current `teamActiveIndex`. */
function updateTeamActiveDescendant() {
  const options = els.teamResults.querySelectorAll('li[role="option"]:not([aria-disabled])');
  options.forEach((li, i) => {
    li.setAttribute('aria-selected', String(i === teamActiveIndex));
  });
  const activeLi = options[teamActiveIndex];
  if (activeLi) {
    els.teamSearch.setAttribute('aria-activedescendant', activeLi.id);
  } else {
    els.teamSearch.removeAttribute('aria-activedescendant');
  }
}

/** Sets the team highlight, then resets the search field (SITE-09). */
function chooseTeam(setState, slug) {
  setState({ team: slug });
  els.teamSearch.value = '';
  closeTeamOptions();
}

/** Closes the phone filters drawer and returns focus to the button that opened it (SITE-18). */
function closeDrawer() {
  document.body.classList.remove('filters-open');
  els.filtersButton.focus();
}

/** Binds every rail DOM event listener once. `getState` always returns the latest state. */
export function initFilters({ data, getState, setState }) {
  els = {
    seasonFrom: document.getElementById('season-from'),
    seasonTo: document.getElementById('season-to'),
    seasonCounts: document.getElementById('season-counts'),
    networksSection: document.getElementById('filter-networks'),
    slotsSection: document.getElementById('filter-slots'),
    roleSection: document.getElementById('filter-role'),
    teamSearch: document.getElementById('team-search'),
    teamResults: document.getElementById('team-results'),
    teamChip: document.getElementById('team-chip'),
    clearFilters: document.getElementById('clear-filters'),
    railToggle: document.getElementById('rail-toggle'),
    railClose: document.getElementById('rail-close'),
    filtersButton: document.getElementById('filters-button'),
  };

  buildSeasonSelects(data);
  buildNetworkChecklist(data);
  buildRoleHelper();

  const onSeasonChange = () => {
    const from = Number(els.seasonFrom.value);
    const to = Number(els.seasonTo.value);
    setState({ seasons: [from, to] });
  };
  els.seasonFrom.addEventListener('change', onSeasonChange);
  els.seasonTo.addEventListener('change', onSeasonChange);

  els.networksSection.addEventListener('change', (ev) => handleNetworksChange(data, getState, setState, ev));

  els.slotsSection.addEventListener('change', () => handleSlotsChange(setState));

  els.roleSection.addEventListener('change', (ev) => handleRoleChange(setState, ev));

  els.teamSearch.addEventListener('input', () => {
    const value = els.teamSearch.value;
    window.clearTimeout(teamDebounceTimer);
    teamDebounceTimer = window.setTimeout(() => updateTeamOptions(data, value), DEBOUNCE_MS);
  });

  els.teamSearch.addEventListener('keydown', (ev) => {
    if (ev.key === 'ArrowDown') {
      if (els.teamResults.hidden || teamOptions.length === 0) return;
      ev.preventDefault();
      teamActiveIndex = Math.min(teamActiveIndex + 1, teamOptions.length - 1);
      updateTeamActiveDescendant();
    } else if (ev.key === 'ArrowUp') {
      if (els.teamResults.hidden || teamOptions.length === 0) return;
      ev.preventDefault();
      teamActiveIndex = Math.max(teamActiveIndex - 1, 0);
      updateTeamActiveDescendant();
    } else if (ev.key === 'Enter') {
      if (teamActiveIndex >= 0 && teamOptions[teamActiveIndex]) {
        ev.preventDefault();
        chooseTeam(setState, teamOptions[teamActiveIndex].slug);
      }
    } else if (ev.key === 'Escape') {
      closeTeamOptions();
    }
  });

  els.teamResults.addEventListener('click', (ev) => {
    const li = ev.target.closest('li[role="option"]');
    if (!li || !li.dataset.teamSlug) return;
    chooseTeam(setState, li.dataset.teamSlug);
  });

  document.addEventListener('click', (ev) => {
    if (els.teamResults.hidden) return;
    if (els.teamResults.contains(ev.target) || ev.target === els.teamSearch) return;
    closeTeamOptions();
  });

  els.teamChip.addEventListener('click', (ev) => {
    const btn = ev.target.closest('.chip-remove');
    if (!btn) return;
    setState({ team: null });
  });

  els.clearFilters.addEventListener('click', () => {
    setState({ seasons: null, networks: null, slots: null, role: null });
  });

  els.railToggle.addEventListener('click', () => {
    const collapsed = document.body.classList.toggle('rail-collapsed');
    els.railToggle.setAttribute('aria-expanded', String(!collapsed));
    els.railToggle.textContent = collapsed ? '▸' : '▾';
  });

  const tabletMedia = window.matchMedia('(min-width: 641px) and (max-width: 1024px)');
  if (tabletMedia.matches) {
    document.body.classList.add('rail-collapsed');
    els.railToggle.setAttribute('aria-expanded', 'false');
    els.railToggle.textContent = '▸';
  }

  els.filtersButton.addEventListener('click', () => {
    document.body.classList.add('filters-open');
    els.railClose.focus();
  });

  els.railClose.addEventListener('click', () => closeDrawer());

  document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape' && document.body.classList.contains('filters-open')) {
      closeDrawer();
    }
  });
}

/** Renders the season range selects and the D-05 per-season counts list. */
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

/** Renders the `#team-chip` for the current team highlight, or clears it (SITE-09). */
function renderTeamChip(data, state) {
  if (state.team == null) {
    els.teamChip.className = '';
    els.teamChip.replaceChildren();
    return;
  }
  const idx = data.teamIndexBySlug.get(state.team);
  const team = data.lookups.teams[idx];
  els.teamChip.className = 'chip';

  const nameSpan = document.createElement('span');
  nameSpan.textContent = team.name;

  const removeBtn = document.createElement('button');
  removeBtn.type = 'button';
  removeBtn.className = 'chip-remove';
  removeBtn.textContent = '×';
  removeBtn.setAttribute('aria-label', `Remove ${team.name}`);

  els.teamChip.replaceChildren(nameSpan, removeBtn);
}

/** Counts the active hide-filters plus the team highlight, for the mobile Filters(N) button. */
function activeFilterCount(state) {
  let n = 0;
  if (state.seasons != null) n += 1;
  if (state.networks != null) n += 1;
  if (state.slots != null) n += 1;
  if (state.role != null) n += 1;
  if (state.team != null) n += 1;
  return n;
}

/** Renders the `#filters-button` label (SITE-18). */
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
  renderTeamChip(data, state);
  renderFiltersButton(state);
}
