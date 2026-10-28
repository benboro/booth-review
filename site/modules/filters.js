/**
 * Filter toolbar: an Announcers popover plus eight filter popovers (Seasons,
 * Networks, Kickoff, Role, Conference, School, Bowls/Playoffs, Game) above the
 * chart, plus "Clear all filters" and a full-height phone bottom sheet that
 * stacks every section, Announcers first (SITE-20, SITE-21, SITE-22,
 * SITE-24, SITE-27; D-02, D-03, D-10, D-11, D-18, D-21, D-27). The School popover
 * also holds the Either team / Head-to-head control, shown with exactly two
 * schools (04.7 D-11..D-14). The Game popover is a searchable, sectioned radio
 * list of named games (playoff rounds, bowls, rivalries) built from `data.games`
 * (04.9 D-01..D-06); one pick at a time, written only through setState.
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

import { gameKeyMatches, gameSearchKey, normalizeName } from './data.js';
import { makeCaretIcon, makeGameTypeIcon } from './icons.js';
import { FAMILY_LABELS } from './palette.js';
import { familyIsSole, familyOnlyPatch, offeredFamilyIds, sameSet } from './select.js';
import { NEW_YEARS_SIX, SLOT_SHORT_LABELS, ROLE_LABELS, crewPickNames, gameRowTitle } from './format.js';
import { PHONE_QUERY } from './breakpoints.js';

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
  ['filter-game', 'pop-game'],
  ['filter-booth', 'pop-booth'],
];

/** Toolbar trigger names, in toolbar order -- also `#trigger-{name}`'s id suffix. */
const TRIGGER_NAMES = ['announcers', 'seasons', 'networks', 'kickoff', 'role', 'conference', 'school', 'postseason', 'game', 'booth'];

/**
 * Per-group reset patches (A4), keyed by trigger name and applied through
 * `setState` like every other filter change. "Clear all filters" is built from
 * this same map, so the two can never drift.
 */
const GROUP_RESETS = {
  announcers: { people: [], compare: false, together: false },
  seasons: { seasons: null },
  networks: { networks: null },
  kickoff: { slots: null },
  role: { role: null },
  conference: { conferences: [] },
  school: { school: [], h2h: false },
  postseason: { postseason: 'all' },
  game: { game: null },
  booth: { booth: [] },
  venue: { venue: null },
  // Phase 14 D-07: Clear all filters also drops a Crews pick (it has no toolbar trigger).
  crew: { crew: null },
};

/** Booth tier values in canonical order, and their trigger labels (D-12). */
const BOOTH_ORDER = ['a', 'b', 'other'];
const BOOTH_LABELS = { a: 'Lead (A)', b: 'No. 2 (B)', other: 'Other' };

/** Bowls/Playoffs radio values, in the DOM order they appear in `#postseason-options`. */
const POSTSEASON_ORDER = ['all', 'exclude', 'only'];

/** The latest `view`, kept so the delegated Only handlers can read facet counts (D-24). */
let lastView = null;

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

/** game slug -> its radio row button, populated once by `buildGameList`. */
let gameRows = new Map();

/** game slug -> its `data.games` entry, populated once by `buildGameList`. */
let gameBySlug = new Map();

/** Section order, header text and header icon kind of the Game list (04.9 D-02, 04.10 D-03). */
const GAME_SECTIONS = [
  ['playoff', 'PLAYOFF', 'playoff'],
  ['bowls', 'BOWLS', 'bowl'],
  ['rivalries', 'RIVALRIES', 'rivalry'],
];

/**
 * Game sections the viewer collapsed (the pre-search baseline), and the ones
 * collapsed by a header click during a search. In memory only: neither is ever
 * stored or put in the URL, and every open of the popover or sheet starts with
 * both empty (04.10 D-04, D-05).
 */
let collapsedSections = new Set();
let searchCollapsed = new Set();

/**
 * Network families the viewer expanded. Empty means every family is collapsed, which
 * is how each open of the popover or sheet starts (04.16 D-10). In memory only:
 * never stored or put in the URL.
 */
const expandedFamilies = new Set();

/** The longest query echoed in the empty-search line (04.9 D-04). */
const GAME_QUERY_ECHO_MAX = 40;

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

/** Signature of the season options last written to the two selects (D-14), so re-renders skip identical writes. */
let seasonOptionsSignature = '';

/** The "(N)" count span plus its screen-reader twin, appended to every faceted row (D-12). */
function makeCountSpans() {
  const visible = document.createElement('span');
  visible.className = 'option-count';
  visible.setAttribute('aria-hidden', 'true');
  const sr = document.createElement('span');
  sr.className = 'visually-hidden option-count-sr';
  return [visible, sr];
}

/** Writes a count into a row's two count spans (textContent only) and toggles `is-zero` on `zeroEl`. */
function setCount(container, count, zeroEl = container) {
  const visible = container.querySelector('.option-count');
  const sr = container.querySelector('.option-count-sr');
  const text = `(${count})`;
  if (visible && visible.textContent !== text) visible.textContent = text;
  const srText = `, ${count} ${count === 1 ? 'game' : 'games'}`;
  if (sr && sr.textContent !== srText) sr.textContent = srText;
  zeroEl.classList.toggle('is-zero', count === 0);
}

/** Combines the two independent hide reasons of a `.check-item` row: text search and facets (Pitfall 7). */
function syncRowHidden(item) {
  item.hidden = item.dataset.searchHidden === 'true' || item.dataset.facetHidden === 'true';
}

/** Sets a row's facet-hidden flag and re-syncs its `hidden` attribute. */
function setFacetHidden(item, hidden) {
  item.dataset.facetHidden = hidden ? 'true' : 'false';
  syncRowHidden(item);
}

/**
 * Builds one checklist row: `div.check-item > label.check-row > (input, name, counts)`.
 * @param {HTMLInputElement} checkbox
 * @param {string} name
 */
function makeCheckItem(checkbox, name) {
  const item = document.createElement('div');
  item.className = 'check-item';
  const label = document.createElement('label');
  label.className = 'check-row';
  const nameSpan = document.createElement('span');
  nameSpan.className = 'option-name';
  nameSpan.textContent = name;
  label.append(checkbox, nameSpan, ...makeCountSpans());
  item.appendChild(label);
  return item;
}

/**
 * D-11 amendment ("all but a few"): a non-null Networks pick is "narrowed" (its
 * impossible checked options stay visible, greyed) only when the checked channels
 * are no more than the unchecked ones. A tie counts as narrowed; 3 of 4 is
 * default-like, so impossible rows hide instead of greying.
 */
function networksPickNarrowed(data, state) {
  return state.networks != null && 2 * state.networks.length <= allPrimaryNetworkIds(data).length;
}

/**
 * D-36: the one row-hiding rule shared by renderNetworks and the Networks trigger
 * count. A channel row is hidden when the other filters leave it no games, unless
 * it is a checked explicit pick in a narrowed list (then it stays, greyed).
 */
function networkRowHidden(count, checked, narrowed) {
  return count === 0 && !(narrowed && checked);
}

/**
 * D-36: how many Networks rows are shown, how many of those are checked, and the checked names.
 * Iterates `data.primaryNetworks` only; missing facets count every row as shown.
 */
function shownNetworkCounts(data, state, view) {
  const currentIds = state.networks ?? allPrimaryNetworkIds(data);
  const narrowed = networksPickNarrowed(data, state);
  let shown = 0;
  let checkedShown = 0;
  const names = [];
  for (const idx of data.primaryNetworks) {
    const net = data.lookups.networks[idx];
    const checked = currentIds.includes(net.id);
    const count = view?.facets?.networks?.[idx] ?? 1;
    if (networkRowHidden(count, checked, narrowed)) continue;
    shown += 1;
    if (checked) {
      checkedShown += 1;
      names.push(net.name);
    }
  }
  return { shown, checked: checkedShown, names };
}

/**
 * Seasons menus are (re)populated by `renderSeasons` (D-14); the init pass only
 * resets the signature so the first render writes them.
 */
function buildSeasonSelects() {
  seasonOptionsSignature = '';
}

/** Builds the family-nested network checklist once, from `data.families`/`networksByFamily` (D-06). */
function buildNetworkChecklist(data) {
  // A4: keep the `.section-head` (title + Reset) as the preserved first child, not a bare h3.
  const heading =
    els.networksSection.querySelector('.section-head') ?? els.networksSection.querySelector('h3');
  networkCheckboxes = new Map();
  familyCheckboxes = new Map();

  const groups = data.families.map((familyKeyVal) => {
    const fieldset = document.createElement('fieldset');
    fieldset.className = 'family-group';

    const legend = document.createElement('legend');
    const familyCheckbox = document.createElement('input');
    familyCheckbox.type = 'checkbox';
    familyCheckbox.dataset.familyCheckbox = familyKeyVal;
    const familyItem = makeCheckItem(familyCheckbox, FAMILY_LABELS[familyKeyVal]);
    familyItem.classList.add('family-item');
    const netIdxs = data.networksByFamily.get(familyKeyVal) ?? [];
    // D-13: caret vs spacer follows the total channel count, so the layout never shifts with facets.
    if (netIdxs.length > 1) {
      const caret = document.createElement('button');
      caret.type = 'button';
      caret.className = 'family-caret';
      caret.dataset.family = familyKeyVal;
      caret.setAttribute('aria-expanded', 'false');
      caret.setAttribute('aria-controls', `family-rows-${familyKeyVal}`);
      caret.setAttribute('aria-label', `${FAMILY_LABELS[familyKeyVal]} channels`);
      caret.title = 'Show channels';
      caret.appendChild(makeCaretIcon());
      familyItem.prepend(caret);
    } else {
      const spacer = document.createElement('span');
      spacer.className = 'family-caret-spacer';
      spacer.setAttribute('aria-hidden', 'true');
      familyItem.prepend(spacer);
    }
    // The hint sits between the name and the count, aria-hidden like the count (04.16 D-12).
    const hint = document.createElement('span');
    hint.className = 'family-on-hint';
    hint.setAttribute('aria-hidden', 'true');
    hint.hidden = true;
    // aria-describedby may reference an aria-hidden or hidden node, so the "N of M on"
    // text reaches assistive tech as the checkbox's description without renaming it (WR-01).
    hint.id = `family-on-${familyKeyVal}`;
    familyCheckbox.setAttribute('aria-describedby', hint.id);
    familyItem.querySelector('.option-name').after(hint);
    legend.appendChild(familyItem);
    fieldset.appendChild(legend);
    familyCheckboxes.set(familyKeyVal, familyCheckbox);

    const list = document.createElement('ul');
    list.className = 'network-list';
    list.id = `family-rows-${familyKeyVal}`;
    list.hidden = true;
    for (const idx of netIdxs) {
      const net = data.lookups.networks[idx];
      const li = document.createElement('li');
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.dataset.networkId = net.id;
      li.appendChild(makeCheckItem(checkbox, net.name));
      list.appendChild(li);
      networkCheckboxes.set(net.id, checkbox);
    }
    fieldset.appendChild(list);
    return fieldset;
  });

  els.networksSection.replaceChildren(
    ...(heading ? [heading] : []),
    ...groups,
  );
}

/** Applies `expandedFamilies` to every caret, its channel list and its "N of M on" hint (04.16 D-10..D-13). */
function syncFamilyRows() {
  for (const caret of els.networksSection.querySelectorAll('.family-caret')) {
    const family = caret.dataset.family;
    const expanded = expandedFamilies.has(family);
    caret.setAttribute('aria-expanded', String(expanded));
    caret.title = expanded ? 'Hide channels' : 'Show channels';
    const list = document.getElementById(`family-rows-${family}`);
    if (list) list.hidden = !expanded;
  }
  for (const [family, checkbox] of familyCheckboxes) {
    const hint = checkbox.closest('.check-item').querySelector('.family-on-hint');
    if (hint) hint.hidden = expandedFamilies.has(family) || !checkbox.indeterminate;
  }
}

/** Expands or collapses one family. Never touches `state.networks` (D-11). */
function toggleFamily(family) {
  if (expandedFamilies.has(family)) expandedFamilies.delete(family);
  else expandedFamilies.add(family);
  syncFamilyRows();
}

/** Collapses every family; called from `beforetoggle` so the first painted frame is collapsed (D-10). */
function resetNetworkCollapse() {
  expandedFamilies.clear();
  syncFamilyRows();
}

/** One "Only" button, a sibling of the row's label (never nested in it), built with textContent only. */
function makeOnlyButton(group, key, value) {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'only-btn';
  btn.textContent = 'Only';
  btn.dataset.onlyGroup = group;
  btn.dataset[key] = value;
  return btn;
}

/** Appends an Only button to every Networks channel, family, Conference and Kickoff row (D-23). */
function buildOnlyButtons() {
  for (const [id, cb] of networkCheckboxes) {
    cb.closest('.check-item').appendChild(makeOnlyButton('networks', 'onlyNetwork', id));
  }
  for (const [family, cb] of familyCheckboxes) {
    cb.closest('.check-item').appendChild(makeOnlyButton('networks', 'onlyFamily', family));
  }
  for (const [name, cb] of conferenceCheckboxes) {
    cb.closest('.check-item').appendChild(makeOnlyButton('conference', 'onlyConference', name));
  }
  for (const cb of els.slotsSection.querySelectorAll('input[name="slot"]')) {
    cb.closest('.check-item').appendChild(makeOnlyButton('kickoff', 'onlySlot', cb.value));
  }
}

/** True when the button's option is already the sole selection, so it reads "All" (D-25). */
function onlyIsSole(btn, data, state, view) {
  const d = btn.dataset;
  if (d.onlyNetwork) return state.networks != null && sameSet(state.networks, [d.onlyNetwork]);
  if (d.onlyFamily) {
    return familyIsSole(data, view, d.onlyFamily, state.networks);
  }
  if (d.onlySlot) return state.slots != null && sameSet(state.slots, [d.onlySlot]);
  if (d.onlyConference) return sameSet(state.conferences, [d.onlyConference]);
  return false;
}

/** Delegated click handler for one section's Only/All buttons (D-24, D-25, D-27). */
function handleOnlyClick(data, getState, setState, ev) {
  const btn = ev.target.closest('.only-btn');
  if (!btn) return;
  ev.preventDefault();
  ev.stopPropagation();
  const d = btn.dataset;
  const resetKey = d.onlyGroup;
  if (d.onlyFamily) {
    // Only and All share one rule with the legend pill double-click (04.15 D-06).
    setState(familyOnlyPatch(data, lastView, d.onlyFamily, getState().networks));
    return;
  }
  if (onlyIsSole(btn, data, getState(), lastView)) {
    setState(structuredClone(GROUP_RESETS[resetKey]));
  } else if (d.onlyNetwork) {
    setState({ networks: [d.onlyNetwork] });
  } else if (d.onlySlot) {
    setState({ slots: [d.onlySlot] });
  } else if (d.onlyConference) {
    setState({ conferences: [d.onlyConference] });
  }
}

/** Syncs every Only button's text and accessible name ("All" when sole), hiding empty family buttons. */
function renderOnlyButtons(data, state, view) {
  const allLabels = {
    networks: 'Show all networks',
    conference: 'Show all conferences',
    kickoff: 'Show all kickoff times',
  };
  const netNames = new Map(data.lookups.networks.map((n) => [n.id, n.name]));
  for (const btn of document.querySelectorAll('.only-btn')) {
    const d = btn.dataset;
    if (d.onlyFamily) btn.hidden = offeredFamilyIds(data, d.onlyFamily, view).length === 0;
    const sole = onlyIsSole(btn, data, state, view);
    const name = d.onlyNetwork
      ? netNames.get(d.onlyNetwork)
      : d.onlyFamily
        ? FAMILY_LABELS[d.onlyFamily]
        : d.onlySlot
          ? SLOT_SHORT_LABELS[d.onlySlot]
          : d.onlyConference;
    const text = sole ? 'All' : 'Only';
    const label = sole ? allLabels[d.onlyGroup] : `Show only ${name}`;
    if (btn.textContent !== text) btn.textContent = text;
    if (btn.getAttribute('aria-label') !== label) btn.setAttribute('aria-label', label);
  }
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
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.name = 'conference';
    checkbox.value = name;
    conferenceCheckboxes.set(name, checkbox);
    return makeCheckItem(checkbox, name);
  });
  els.conferenceList.append(...rows);
}

/** Builds the School popover's checklist once, from every team, sorted by name (D-11). */
function buildSchoolList(data) {
  schoolCheckboxes = new Map();
  schoolKeysBySlug = new Map();
  const sortedTeams = data.teamKeys.slice().sort((a, b) => a.name.localeCompare(b.name));
  const rows = sortedTeams.map((team) => {
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.name = 'school';
    checkbox.value = team.slug;
    schoolCheckboxes.set(team.slug, checkbox);
    schoolKeysBySlug.set(team.slug, team.keys);
    return makeCheckItem(checkbox, team.name);
  });
  els.schoolList.append(...rows);
}

/** Builds the Game popover's sectioned radio list once, from `data.games` (04.9 D-02). */
function buildGameList(data) {
  gameRows = new Map();
  gameBySlug = new Map(data.games.map((g) => [g.slug, g]));
  const groups = [];
  for (const [section, header, iconKind] of GAME_SECTIONS) {
    const games = data.games.filter((g) => g.section === section);
    if (games.length === 0) continue;
    const group = document.createElement('div');
    group.setAttribute('role', 'group');
    group.dataset.gameSection = section;
    const head = document.createElement('button');
    head.type = 'button';
    head.className = 'game-section-head';
    head.id = `game-head-${section}`;
    head.dataset.section = section;
    head.setAttribute('aria-expanded', 'true');
    head.setAttribute('aria-controls', `game-rows-${section}`);
    const name = document.createElement('span');
    name.className = 'game-section-name';
    name.textContent = header;
    const hint = document.createElement('span');
    hint.className = 'game-picked-hint';
    hint.setAttribute('aria-hidden', 'true');
    hint.hidden = true;
    hint.textContent = '1 picked';
    const icon = makeGameTypeIcon(iconKind);
    head.append(makeCaretIcon(), ...(icon ? [icon] : []), name, hint);
    group.setAttribute('aria-labelledby', head.id);
    const rowsEl = document.createElement('div');
    rowsEl.className = 'game-rows';
    rowsEl.id = `game-rows-${section}`;
    group.append(head, rowsEl);
    // D-07/D-08: the New Year's Six rows sit in one gold band at the top of BOWLS,
    // built only when at least one NY6 franchise is in the data.
    let band = null;
    if (section === 'bowls' && games.some((g) => NEW_YEARS_SIX.includes(g.slug))) {
      band = document.createElement('div');
      band.className = 'game-ny6';
      band.setAttribute('role', 'group');
      band.setAttribute('aria-label', "New Year's Six");
      const bandLabel = document.createElement('div');
      bandLabel.className = 'game-ny6-label';
      bandLabel.setAttribute('aria-hidden', 'true');
      bandLabel.textContent = "New Year's Six";
      band.appendChild(bandLabel);
      rowsEl.appendChild(band);
    }
    for (const game of games) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.setAttribute('role', 'radio');
      btn.setAttribute('aria-checked', 'false');
      btn.tabIndex = -1;
      btn.dataset.game = game.slug;
      btn.dataset.searchHidden = 'false';
      btn.dataset.facetHidden = 'false';
      const label = document.createElement('span');
      label.className = 'game-label';
      label.textContent = game.label;
      btn.append(label, ...makeCountSpans());
      (band != null && NEW_YEARS_SIX.includes(game.slug) ? band : rowsEl).appendChild(btn);
      gameRows.set(game.slug, btn);
    }
    groups.push(group);
  }
  els.gameOptions.replaceChildren(...groups);
}

/** Whether the search box holds a query (the same test `filterGameRows` uses). */
function isSearching(query) {
  return gameSearchKey(query) !== '';
}

/**
 * Whether a section's rows are collapsed: the per-search state while a query is
 * active, the viewer's own baseline otherwise (04.10 D-05).
 */
function sectionCollapsed(section, searching) {
  return searching ? searchCollapsed.has(section) : collapsedSections.has(section);
}

/** Every Game row currently reachable by keyboard, in DOM order (collapse-aware). */
function visibleGameRows() {
  return Array.from(els.gameOptions.querySelectorAll('[data-game]:not([hidden])')).filter(
    (r) => !r.closest('.game-rows').hidden,
  );
}

/** Toggles one section's header: collapses or expands it visibly, and records it as the baseline. */
function toggleGameSection(section) {
  const searching = isSearching(els.gameSearch.value);
  const next = !sectionCollapsed(section, searching);
  if (searching) {
    if (next) searchCollapsed.add(section);
    else searchCollapsed.delete(section);
  }
  if (next) collapsedSections.add(section);
  else collapsedSections.delete(section);
  syncGameChrome(els.gameSearch.value);
}

/** Empties the Game search box and restores the full list and the pre-search collapse state (IN-07). */
function clearGameSearch(data) {
  els.gameSearch.value = '';
  filterGameRows(data, '');
}

/**
 * Opens every section again (04.10 D-04): called from `beforetoggle` whenever the
 * popover or sheet is about to open. The container is still hidden then, so the
 * tooltip measurement is left to the `toggle` handler (IN-06).
 */
function resetGameCollapse() {
  collapsedSections.clear();
  searchCollapsed.clear();
  syncGameChrome(els.gameSearch.value, { measure: false });
}

/**
 * The empty-list line (04.9 D-04, WR-04), or null while any row shows. A row
 * hides for two reasons, search and a zero count, so the line says which: no
 * game matches the query at all, games match but the other filters leave them
 * at zero, or (no query) the other filters leave every game at zero.
 * @param {string} query - the raw search box text.
 * @param {number} visible - rows currently shown.
 * @param {boolean} anySearchMatch - whether any row matches the query.
 * @returns {string|null}
 */
function gameEmptyLine(query, visible, anySearchMatch) {
  if (visible > 0) return null;
  const q = query.trim();
  if (q === '') return 'No games match these filters.';
  const shown = q.length > GAME_QUERY_ECHO_MAX ? `${q.slice(0, GAME_QUERY_ECHO_MAX)}...` : q;
  return anySearchMatch ? `No games match "${shown}" with these filters.` : `No games match "${shown}".`;
}

/**
 * Hides empty section groups, shows the empty-list line, and recomputes the roving
 * tab stop: the checked visible row, else the first visible row (04.9 D-03, D-04).
 * @param {string} query - the raw search box text.
 * @param {{measure?: boolean}} [opts] - `measure: false` skips the tooltip pass,
 *   for callers that run while the list is hidden and measure after it shows.
 */
function syncGameChrome(query, { measure = true } = {}) {
  for (const group of els.gameOptions.querySelectorAll('[data-game-section]')) {
    group.hidden = group.querySelector('[data-game]:not([hidden])') == null;
  }
  // D-09: the NY6 band hides whole when search or facets leave it no visible row.
  for (const band of els.gameOptions.querySelectorAll('.game-ny6')) {
    band.hidden = band.querySelector('[data-game]:not([hidden])') == null;
  }
  // Collapse is a separate hide dimension: it never empties a group or the list.
  const shown = els.gameOptions.querySelectorAll('[data-game]:not([hidden])').length;
  const searching = isSearching(query);
  if (!searching) searchCollapsed.clear();
  for (const head of els.gameOptions.querySelectorAll('.game-section-head')) {
    const collapsed = sectionCollapsed(head.dataset.section, searching);
    document.getElementById(head.getAttribute('aria-controls')).hidden = collapsed;
    head.setAttribute('aria-expanded', String(!collapsed));
    // D-05: a collapsed section holding the pick says so (decorative; the pick is
    // announced on the toolbar trigger).
    const rowsEl = document.getElementById(head.getAttribute('aria-controls'));
    const holdsPick = rowsEl.querySelector('[data-game][aria-checked="true"]') != null;
    head.querySelector('.game-picked-hint').hidden = !(collapsed && holdsPick);
  }
  const rows = visibleGameRows();
  const anySearchMatch = Array.from(gameRows.values()).some(
    (r) => r.dataset.searchHidden !== 'true',
  );
  const line = gameEmptyLine(query, shown, anySearchMatch);
  if (line != null) {
    els.gameEmpty.textContent = line;
    els.gameEmpty.hidden = false;
  } else {
    els.gameEmpty.hidden = true;
  }
  const stop = rows.find((r) => r.getAttribute('aria-checked') === 'true') ?? rows[0];
  for (const btn of gameRows.values()) btn.tabIndex = btn === stop ? 0 : -1;
  if (measure) syncGameTooltips();
}

/**
 * Desktop-only hover titles on Game rows (D-06, WR-03): rivalry rows name their
 * teams, and a row whose label is cut off by the ellipsis also gets its full
 * name. Truncation is measured, so this reruns whenever rows can change size or
 * visibility: on every render and search, when the popover or sheet opens, and
 * on resize. Without hover (phones), no row has a title.
 */
function syncGameTooltips() {
  const hoverCapable = window.matchMedia('(hover: hover) and (pointer: fine)').matches;
  // Measure every row before writing any title, so layout is read once.
  const tips = Array.from(gameRows, ([slug, row]) => {
    if (!hoverCapable) return [row, null];
    const label = row.querySelector('.game-label');
    return [row, gameRowTitle(gameBySlug.get(slug), label.scrollWidth > label.clientWidth)];
  });
  for (const [row, tip] of tips) {
    if (tip) row.setAttribute('title', tip);
    else row.removeAttribute('title');
  }
}

/** Hides Game rows whose search keys do not contain the folded query (04.9 D-04). */
function filterGameRows(data, query) {
  const q = gameSearchKey(query);
  for (const game of data.games) {
    const row = gameRows.get(game.slug);
    row.dataset.searchHidden =
      q !== '' && !game.keys.some((k) => gameKeyMatches(k, q)) ? 'true' : 'false';
    syncRowHidden(row);
  }
  syncGameChrome(query);
}

/**
 * Radiogroup keyboard for the Game list (04.9 D-03): arrows move focus and
 * selection together across visible rows without wrapping; Home/End jump to the
 * ends; ArrowUp from the first row returns to the search box; ArrowDown in the
 * search box focuses the first visible row.
 */
function bindGameKeyboard(setState) {
  els.gameSearch.addEventListener('keydown', (ev) => {
    if (ev.key !== 'ArrowDown') return;
    const rows = visibleGameRows();
    if (rows.length === 0) return;
    ev.preventDefault();
    rows[0].focus();
  });
  els.gameOptions.addEventListener('keydown', (ev) => {
    const key = ev.key;
    if (!['ArrowLeft', 'ArrowUp', 'ArrowRight', 'ArrowDown', 'Home', 'End'].includes(key)) return;
    const target = ev.target;
    if (!(target instanceof HTMLElement) || !target.dataset.game) return;
    const rows = visibleGameRows();
    const idx = rows.indexOf(target);
    if (idx === -1) return;
    ev.preventDefault();
    let next;
    if (key === 'Home') next = 0;
    else if (key === 'End') next = rows.length - 1;
    else if (key === 'ArrowDown' || key === 'ArrowRight') next = Math.min(idx + 1, rows.length - 1);
    else if (idx === 0) {
      els.gameSearch.focus();
      return;
    } else next = idx - 1;
    const slug = rows[next].dataset.game;
    setState({ game: slug });
    // setState -> render() runs synchronously, so the roving tabindex is current.
    gameRows.get(slug)?.focus();
  });
}

/** Hides checklist rows whose keys (via `keysFor`) don't contain the normalized query. */
function filterChecklist(listEl, query, keysFor) {
  const q = normalizeName(query);
  for (const item of listEl.querySelectorAll('.check-item')) {
    const checkbox = item.querySelector('input[type="checkbox"]');
    if (q === '') {
      item.dataset.searchHidden = 'false';
    } else {
      item.dataset.searchHidden = keysFor(checkbox).some((k) => k.includes(q)) ? 'false' : 'true';
    }
    syncRowHidden(item);
  }
}

/** Every checkbox in `listEl` whose row is currently visible, in DOM order. */
function visibleCheckboxes(listEl) {
  return Array.from(listEl.querySelectorAll('.check-item:not([hidden])')).map((item) =>
    item.querySelector('input[type="checkbox"]'),
  );
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

/**
 * The first focusable element inside a popover: its search input, else its first
 * input/button. The per-group Reset button (A4) is skipped on purpose: it is a
 * secondary action, so the first focus belongs to the group's own control; the School
 * Head-to-head buttons are skipped too (hidden with <2 schools, and the search comes first). It
 * stays in the normal Tab order (Shift+Tab from that first control reaches it).
 */
function firstFocusable(container) {
  return container.querySelector(
    'input, button:not(.group-reset):not(.only-btn):not(.family-caret):not([data-match]), [tabindex]:not([tabindex="-1"]):not(.group-reset):not(.only-btn):not(.family-caret)',
  );
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
    els.sheetBody.replaceChildren();
    for (const group of SHEET_GROUPS) {
      const label = document.createElement('div');
      label.className = 'sheet-group-label';
      label.textContent = group.label;
      els.sheetBody.appendChild(label);
      for (const sectionId of group.sections) els.sheetBody.appendChild(document.getElementById(sectionId));
    }
    // The people strip sits under the Announcers heading: chips (row A), then the three buttons (row B).
    const strip = document.createElement('div');
    strip.className = 'people-strip';
    strip.id = 'people-strip';
    strip.append(els.chips, els.toggleGroup);
    const announcers = document.getElementById('filter-announcers');
    announcers.querySelector('.section-head').after(strip);
  } else {
    document.getElementById('people-strip')?.remove();
    els.sheetBody.replaceChildren();
    els.sumRight.append(els.chips, els.toggleGroup, els.clearFilters);
    for (const [sectionId, popoverId] of SECTION_POPOVERS) {
      document.getElementById(popoverId).appendChild(document.getElementById(sectionId));
    }
  }
}

/** The phone Filters panel's groups, in the order the desktop bar shows them (Round 3b). */
const SHEET_GROUPS = [
  { label: 'Broadcast', sections: ['filter-announcers', 'filter-networks', 'filter-booth', 'filter-role'] },
  { label: 'Matchup', sections: ['filter-conference', 'filter-school', 'filter-game'] },
  { label: 'Calendar', sections: ['filter-seasons', 'filter-slots', 'filter-postseason'] },
];

/** Each trigger's panel section id, for the pick shown beside a changed section's heading. */
const TRIGGER_SECTIONS = {
  announcers: 'filter-announcers',
  seasons: 'filter-seasons',
  networks: 'filter-networks',
  kickoff: 'filter-slots',
  role: 'filter-role',
  conference: 'filter-conference',
  school: 'filter-school',
  postseason: 'filter-postseason',
  game: 'filter-game',
  booth: 'filter-booth',
};

/** Binds every toolbar/popover/sheet DOM event listener once. `getState` always returns the latest state. */
export function initFilters({ data, getState, setState }) {
  els = {
    toolbar: document.getElementById('toolbar'),
    sumRight: document.querySelector('#summary .sum-right'),
    chips: document.getElementById('chips'),
    toggleGroup: document.querySelector('#summary .toggle-group'),
    filterChips: document.getElementById('filter-chips'),
    seasonFrom: document.getElementById('season-from'),
    seasonTo: document.getElementById('season-to'),
    seasonCounts: document.getElementById('season-counts'),
    seasonEmptyNote: document.getElementById('season-empty-note'),
    seasonEmptyTitle: document.querySelector('#season-empty-note .season-empty-title'),
    networksSection: document.getElementById('filter-networks'),
    slotsSection: document.getElementById('filter-slots'),
    roleSection: document.getElementById('filter-role'),
    conferenceSearch: document.getElementById('conference-search'),
    conferenceList: document.getElementById('conference-list'),
    schoolSearch: document.getElementById('school-search'),
    schoolChips: document.getElementById('school-chips'),
    schoolMatch: document.getElementById('school-match'),
    schoolList: document.getElementById('school-list'),
    postseasonOptions: document.getElementById('postseason-options'),
    boothList: document.getElementById('booth-list'),
    gameSearch: document.getElementById('game-search'),
    gameOptions: document.getElementById('game-options'),
    gameEmpty: document.getElementById('game-empty'),
    clearFilters: document.getElementById('clear-filters'),
    filtersButton: document.getElementById('filters-button'),
    filtersShowResults: document.getElementById('filters-show-results'),
    sheetClearSlot: document.querySelector('.sheet-clear-slot'),
    sheetBody: document.querySelector('.sheet-body'),
    triggers: Object.fromEntries(
      TRIGGER_NAMES.map((name) => [name, document.getElementById(`trigger-${name}`)]),
    ),
  };

  for (const name of TRIGGER_NAMES) restingLabels.set(name, els.triggers[name].textContent.trim());

  buildSeasonSelects();
  buildNetworkChecklist(data);
  buildRoleHelper();
  buildConferenceList(data);
  buildSchoolList(data);
  buildGameList(data);
  buildOnlyButtons();

  const onSeasonChange = (ev) => {
    let from = Number(els.seasonFrom.value);
    let to = Number(els.seasonTo.value);
    // A blank select reads as Number('') === 0; never turn that into a range (WR-13).
    if (!Number.isInteger(from) || !Number.isInteger(to) || from <= 0 || to <= 0) return;
    // With no season filter set, the menus show the facet-clamped range (D-14),
    // but the untouched end still means "no limit": commit the data's own bound
    // for it, so a one-sided edit never removes dots the visitor didn't exclude
    // or puts a range they didn't pick into the URL (D-15, review WR-01).
    if (getState().seasons == null) {
      if (ev.target === els.seasonTo) from = data.seasonMin;
      else to = data.seasonMax;
    }
    setState({ seasons: from === data.seasonMin && to === data.seasonMax ? null : [from, to] });
  };
  els.seasonFrom.addEventListener('change', onSeasonChange);
  els.seasonTo.addEventListener('change', onSeasonChange);

  els.networksSection.addEventListener('change', (ev) => handleNetworksChange(data, getState, setState, ev));
  const onOnlyClick = (ev) => handleOnlyClick(data, getState, setState, ev);
  els.networksSection.addEventListener('click', (ev) => {
    const caret = ev.target.closest('.family-caret');
    if (caret) {
      toggleFamily(caret.dataset.family);
      return;
    }
    onOnlyClick(ev);
  });
  els.slotsSection.addEventListener('click', onOnlyClick);
  els.conferenceList.addEventListener('click', onOnlyClick);

  els.slotsSection.addEventListener('change', () => handleSlotsChange(setState));

  els.roleSection.addEventListener('change', (ev) => handleRoleChange(setState, ev));

  els.boothList.addEventListener('change', () => {
    const picked = new Set([...els.boothList.querySelectorAll('input[name="booth"]:checked')].map((cb) => cb.value));
    setState({ booth: BOOTH_ORDER.filter((tier) => picked.has(tier)) });
  });

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

  els.schoolMatch.addEventListener('click', (ev) => {
    const btn = ev.target.closest('button[data-match]');
    if (!btn) return;
    setState({ h2h: btn.dataset.match === 'both' });
  });

  els.schoolChips.addEventListener('click', (ev) => {
    const btn = ev.target.closest('.chip-remove');
    if (!btn || !btn.dataset.slug) return;
    setState({ school: getState().school.filter((slug) => slug !== btn.dataset.slug) });
  });

  // Phase 11 D-05: the chip lives in the table heading row; removal clears only the venue.
  document.getElementById('venue-chips')?.addEventListener('click', (ev) => {
    const btn = ev.target.closest('.chip-remove');
    if (!btn || !btn.dataset.venue) return;
    setState({ venue: null });
  });

  els.postseasonOptions.addEventListener('click', (ev) => {
    const btn = ev.target.closest('[data-postseason]');
    if (!btn) return;
    setState({ postseason: btn.dataset.postseason });
  });
  bindPostseasonKeyboard(setState);

  els.gameSearch.addEventListener('input', () => {
    filterGameRows(data, els.gameSearch.value);
    // Typing alone can make the Game Reset and Clear all live (04.10 IN-03); no render runs here.
    if (lastView) {
      renderGroupResets(data, getState(), lastView);
      renderFiltersButton(data, getState(), lastView);
    }
  });
  els.gameOptions.addEventListener('click', (ev) => {
    const head = ev.target.closest('.game-section-head');
    if (head) {
      toggleGameSection(head.dataset.section);
      return;
    }
    const btn = ev.target.closest('[data-game]');
    if (!btn) return;
    setState({ game: btn.dataset.game });
  });
  bindGameKeyboard(setState);

  els.clearFilters.addEventListener('click', () => {
    // Announced as disabled while nothing is changed (renderFiltersButton): a no-op then,
    // like the per-group Reset below.
    if (els.clearFilters.getAttribute('aria-disabled') === 'true') return;
    // D-27 (overrides the earlier "people are not cleared" proposal): Clear all
    // filters also removes every selected announcer, compare mode, and
    // called-together (the `announcers` reset). "Clear selection" in the chip
    // row still clears only the people.
    // Empty the search first: setState renders synchronously, so the Game Reset
    // is then dimmed against the cleared box (04.10 IN-03).
    clearGameSearch(data);
    setState(structuredClone(Object.assign({}, ...Object.values(GROUP_RESETS))));
  });

  // A4: one delegated listener for every per-group Reset (desktop popovers and
  // phone-sheet sections). `aria-disabled` (not `disabled`) keeps the button
  // focusable, so clicking it at default is a no-op and focus stays put.
  document.addEventListener('click', (ev) => {
    const btn = ev.target.closest('.group-reset');
    if (!btn || btn.getAttribute('aria-disabled') === 'true') return;
    const name = btn.dataset.reset;
    if (!Object.hasOwn(GROUP_RESETS, name)) return;
    if (name === 'game') clearGameSearch(data);
    setState(structuredClone(GROUP_RESETS[name]));
  });

  els.filtersShowResults.addEventListener('click', () => {
    document.getElementById('filters-sheet').hidePopover();
  });

  for (const popover of document.querySelectorAll('.filter-popover, .filters-sheet')) {
    bindPopoverMechanics(popover);
  }
  // D-04: reopen with every section open. `beforetoggle` runs synchronously before
  // the show, so the first painted frame is already all-open; `toggle` is queued
  // after the show and would paint one stale collapsed frame (04.10 WR-01, same
  // reason as the A5 positioning). Row labels only have a measurable width once
  // the container is shown, so the tooltip pass stays in `toggle` (WR-03).
  for (const id of ['pop-game', 'filters-sheet']) {
    const pop = document.getElementById(id);
    pop.addEventListener('beforetoggle', (ev) => {
      if (ev.newState === 'open') resetGameCollapse();
    });
    pop.addEventListener('toggle', (ev) => {
      if (ev.newState === 'open') syncGameTooltips();
    });
  }
  // 04.16 D-10: families reopen collapsed; same beforetoggle timing as the Game reset above.
  for (const id of ['pop-networks', 'filters-sheet']) {
    document.getElementById(id).addEventListener('beforetoggle', (ev) => {
      if (ev.newState === 'open') resetNetworkCollapse();
    });
  }
  window.addEventListener('scroll', repositionOpenPopovers, { passive: true });
  window.addEventListener('resize', () => {
    repositionOpenPopovers();
    syncGameTooltips();
  });

  const mobileMedia = window.matchMedia(PHONE_QUERY);
  placeSections(mobileMedia.matches);
  mobileMedia.addEventListener('change', (ev) => placeSections(ev.matches));

  // The changed-filter chips re-decide their wording whenever their strip's width changes: opening
  // the panel, a rotation, or a resize (a closed panel measures 0 and is skipped).
  new ResizeObserver(() => fitFilterChips()).observe(els.filterChips);
}

/** Sum of `facets.seasons` over the inclusive range [from, to]. */
function seasonRangeTotal(facetSeasons, from, to) {
  let sum = 0;
  for (const [season, count] of facetSeasons) if (season >= from && season <= to) sum += count;
  return sum;
}

/**
 * Renders the season range selects (D-14: only seasons with matching games plus
 * the selected ends), the per-season counts list, and the empty-state note.
 */
function renderSeasons(data, state, view) {
  const facetSeasons = view.facets.seasons;
  const matching = data.seasons.filter((s) => facetSeasons.get(s) > 0);
  const fallback = matching.length === 0;
  const offeredSet = new Set(fallback ? data.seasons : matching);
  for (const end of state.seasons ?? []) offeredSet.add(end);
  const offered = Array.from(offeredSet).sort((a, b) => a - b);
  const labels = offered.map((s) => (!fallback && facetSeasons.get(s) === 0 ? `${s} (0)` : String(s)));

  const signature = `${offered.join(',')}|${labels.join(',')}`;
  if (signature !== seasonOptionsSignature) {
    const optionsFor = () =>
      offered.map((season, i) => {
        const opt = document.createElement('option');
        opt.value = String(season);
        opt.textContent = labels[i];
        return opt;
      });
    els.seasonFrom.replaceChildren(...optionsFor());
    els.seasonTo.replaceChildren(...optionsFor());
    seasonOptionsSignature = signature;
  }

  // Display only: `state.seasons` stays null until the visitor changes a menu.
  const [minSeason, maxSeason] = state.seasons ?? [offered[0], offered[offered.length - 1]];
  els.seasonFrom.value = String(minSeason);
  els.seasonTo.value = String(maxSeason);

  const items = view.seasonCounts.map(([season, count]) => {
    const li = document.createElement('li');
    if (state.seasons != null && (season < state.seasons[0] || season > state.seasons[1])) {
      li.className = 'out-of-range';
    }
    const word = count === 1 ? 'game' : 'games';
    li.textContent = `${season}: ${count} ${word}`;
    return li;
  });
  els.seasonCounts.replaceChildren(...items);

  // D-14 empty state: the range holds nothing, though other seasons would.
  let showNote = false;
  if (state.seasons != null) {
    const [from, to] = state.seasons;
    const inRange = seasonRangeTotal(facetSeasons, from, to);
    const overall = seasonRangeTotal(facetSeasons, -Infinity, Infinity);
    showNote = inRange === 0 && overall > 0;
    if (showNote) {
      els.seasonEmptyTitle.textContent =
        from === to ? `No games in ${from} for this selection` : `No games in ${from}–${to} for this selection`;
    }
  }
  els.seasonEmptyNote.hidden = !showNote;
}

/**
 * Syncs the network checklist from `state.networks` and `view.facets.networks`
 * (D-08, D-11): counts on every row; an impossible channel hides unless it is an
 * explicit pick in a narrowed list, in which case it stays checked and greyed.
 */
function renderNetworks(data, state, view) {
  const currentIds = state.networks ?? allPrimaryNetworkIds(data);
  const narrowed = networksPickNarrowed(data, state);
  for (const familyKeyVal of data.families) {
    const netIdxs = data.networksByFamily.get(familyKeyVal) ?? [];
    let checkedCount = 0;
    let visibleCount = 0;
    let visibleChecked = 0;
    let familyTotal = 0;
    for (const idx of netIdxs) {
      const net = data.lookups.networks[idx];
      const checkbox = networkCheckboxes.get(net.id);
      const checked = currentIds.includes(net.id);
      checkbox.checked = checked;
      if (checked) checkedCount += 1;
      const count = view.facets.networks[idx];
      familyTotal += count;
      const hidden = networkRowHidden(count, checked, narrowed);
      const item = checkbox.closest('.check-item');
      setFacetHidden(item, hidden);
      setCount(item, count);
      if (!hidden) {
        visibleCount += 1;
        if (checked) visibleChecked += 1;
      }
    }
    const familyCheckbox = familyCheckboxes.get(familyKeyVal);
    const familyItem = familyCheckbox.closest('.check-item');
    const familyHidden = netIdxs.length > 0 && visibleCount === 0;
    setFacetHidden(familyItem, familyHidden);
    familyCheckbox.closest('fieldset').hidden = familyHidden;
    setCount(familyItem, familyTotal);
    const total = visibleCount > 0 ? visibleCount : netIdxs.length;
    const on = visibleCount > 0 ? visibleChecked : checkedCount;
    familyCheckbox.checked = netIdxs.length > 0 && on === total;
    familyCheckbox.indeterminate = on > 0 && on < total;
    familyItem.querySelector('.family-on-hint').textContent = `${on} of ${total} on`;
  }
  syncFamilyRows();
}

/** Syncs the time-slot checkboxes and their counts (SITE-11, D-13: never hidden, never disabled). */
function renderSlots(state, view) {
  for (const cb of els.slotsSection.querySelectorAll('input[name="slot"]')) {
    cb.checked = state.slots != null && state.slots.includes(cb.value);
    setCount(cb.closest('.check-item') ?? cb.closest('label'), view.facets.slots[cb.value] ?? 0);
  }
}

/** Syncs the role checkboxes and their counts (SITE-07, D-13). */
function renderRole(state, view) {
  for (const cb of els.roleSection.querySelectorAll('input[name="role"]')) {
    cb.checked = state.role === cb.value;
    setCount(cb.closest('label'), view.facets.role[cb.value] ?? 0);
  }
}

/** Syncs the Booth checkboxes and counts; all three rows always show (D-12). */
function renderBooth(state, view) {
  for (const cb of els.boothList.querySelectorAll('input[name="booth"]')) {
    cb.checked = state.booth.includes(cb.value);
    setCount(cb.closest('.check-item'), view.facets.booth[cb.value] ?? 0);
  }
}

/** Syncs the Conference checklist's checked state and counts (D-10, D-11). */
function renderConferences(state, view) {
  for (const [name, cb] of conferenceCheckboxes) {
    const checked = state.conferences.includes(name);
    cb.checked = checked;
    const count = view.facets.conferences.get(name) ?? 0;
    const item = cb.closest('.check-item');
    setFacetHidden(item, count === 0 && !checked);
    setCount(item, count);
  }
}

/** Syncs the School checklist (checked, counts, facet hiding) and `#school-chips` (D-11). */
function renderSchool(data, state, view) {
  els.schoolMatch.hidden = state.school.length !== 2;
  for (const btn of els.schoolMatch.querySelectorAll('button[data-match]')) {
    btn.setAttribute('aria-pressed', String((btn.dataset.match === 'both') === (state.h2h === true)));
  }
  for (const [slug, cb] of schoolCheckboxes) {
    const checked = state.school.includes(slug);
    cb.checked = checked;
    const count = view.facets.schools[data.teamIndexBySlug.get(slug)] ?? 0;
    const item = cb.closest('.check-item');
    setFacetHidden(item, count === 0 && !checked);
    setCount(item, count);
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
 * (D-18), its roving `tabindex` (WR-05: only the selected radio is a tab stop,
 * per the WAI-ARIA APG radiogroup pattern `bindPostseasonKeyboard` wires the
 * arrow-key/Home/End half of), and each option's count (D-13: never hidden).
 */
function renderPostseason(state, view) {
  for (const btn of els.postseasonOptions.querySelectorAll('[data-postseason]')) {
    const checked = btn.dataset.postseason === state.postseason;
    btn.setAttribute('aria-checked', String(checked));
    btn.tabIndex = checked ? 0 : -1;
    setCount(btn, view.facets.postseason[btn.dataset.postseason] ?? 0);
  }
}

/**
 * Syncs the Game radio list (04.9 D-03, D-05, D-06, D-19): aria-checked, counts,
 * zero-count rows hidden unless they are the pick, and (via syncGameChrome) the
 * desktop-only row tooltips. The pick stays checked and greyed at (0) when other
 * filters empty it.
 */
function renderGame(data, state, view) {
  for (const game of data.games) {
    const row = gameRows.get(game.slug);
    const checked = game.slug === state.game;
    row.setAttribute('aria-checked', String(checked));
    const count = view.facets.games[game.index] ?? 0;
    setCount(row, count);
    setFacetHidden(row, count === 0 && !checked);
  }
  syncGameChrome(els.gameSearch.value);
}

/** What an untouched entry reads in its value line (Round 3b): the default, in words. */
const ENTRY_DEFAULTS = {
  announcers: 'Any',
  networks: 'All',
  booth: 'Any',
  role: 'Both',
  conference: 'Any',
  school: 'Any',
  game: 'Any',
  kickoff: 'Any',
  postseason: 'All games',
};

/** Resting label per trigger name, captured from index.html before the first render replaces any of them. */
const restingLabels = new Map();

/**
 * A toolbar trigger's active state and its picks in full, from `state` (D-02 copywriting).
 * `items` lists each pick as the visitor reads it ([] at default); `label` is the full summary
 * ("Announcers: Kirk Herbstreit, Chris Fowler"), the title and accessible name. The short text an
 * entry shows is `entryValue`'s. D-36: the Networks picks are the checked rows among the rows shown.
 */
function triggerInfo(name, data, state, view) {
  const resting = restingLabels.get(name) ?? name;
  const info = (items) => ({
    label: items.length > 0 ? `${resting}: ${items.join(', ')}` : resting,
    active: items.length > 0,
    items,
  });
  if (name === 'crew') {
    // Not a toolbar trigger: only `changedControls` asks, so the phone count and chips list it.
    return { label: `Crew: ${crewPickNames(data, state).join(' / ')}`, active: state.crew != null, items: [] };
  }
  if (name === 'announcers') {
    return info(
      state.people.map((id) => {
        const idx = data.personIndexById.get(id);
        return idx === undefined ? id : data.lookups.people[idx].name;
      }),
    );
  }
  if (name === 'seasons') {
    if (state.seasons == null) return info([]);
    const [a, b] = state.seasons;
    return info([`${a}–${b}`]);
  }
  if (name === 'networks') {
    if (state.networks == null) return info([]);
    const { shown, checked, names } = shownNetworkCounts(data, state, view);
    if (checked === shown) return info([]);
    return info(names.length > 0 ? names : ['None']);
  }
  if (name === 'kickoff') {
    return info(state.slots == null ? [] : state.slots.map((slot) => SLOT_SHORT_LABELS[slot]));
  }
  if (name === 'role') {
    return info(state.role == null ? [] : [ROLE_LABELS[state.role]]);
  }
  if (name === 'conference') {
    return info([...state.conferences]);
  }
  if (name === 'school') {
    const names = state.school.map((slug) => data.lookups.teams[data.teamIndexBySlug.get(slug)].name);
    if (state.h2h === true && names.length === 2) return info([`${names[0]} vs ${names[1]}`]);
    return info(names);
  }
  if (name === 'postseason') {
    if (state.postseason === 'all') return info([]);
    return info([state.postseason === 'exclude' ? 'Exclude' : 'Only']);
  }
  if (name === 'booth') {
    return info(state.booth.map((tier) => BOOTH_LABELS[tier]));
  }
  if (name === 'game') {
    const idx = state.game != null ? data.gameIndexBySlug.get(state.game) : undefined;
    return info(idx === undefined ? [] : [data.games[idx].label]);
  }
  return { label: name, active: false, items: [] };
}

/**
 * The text an entry shows on its value line: the default word at rest, otherwise the pick itself
 * (one pick in full, several "{first} +{n-1}"; compare mode counts people because the count line
 * names them). Seasons shows its range, read from the data. Long text truncates in the entry.
 */
function entryValue(name, data, state, view) {
  const { items, active } = triggerInfo(name, data, state, view);
  if (!active) {
    if (name === 'seasons') return `${Math.min(...data.seasons)}–${Math.max(...data.seasons)}`;
    return ENTRY_DEFAULTS[name] ?? '';
  }
  if (name === 'announcers' && state.compare) {
    return items.length === 1 ? '1 person' : `${items.length} people`;
  }
  return items.length === 1 ? items[0] : `${items[0]} +${items.length - 1}`;
}

/** The trigger's changed value text ("" at default): the part of the summary after the resting label. */
function triggerValue(name, label, active) {
  if (!active) return '';
  const resting = restingLabels.get(name) ?? '';
  return label.startsWith(resting) ? label.slice(resting.length) : label;
}

/**
 * The control keys that differ from a clean load, in toolbar order (SHELL-03).
 * One predicate for the desktop accent, the phone "Filters (N changed)" label and
 * the phone chips. It reads the same per-control facts `triggerInfo` shows, not
 * `activeFilterCount`, which also counts each selected person (Pitfall 10).
 */
export function changedControls(data, state, view) {
  const changed = TRIGGER_NAMES.filter((name) => triggerInfo(name, data, state, view).active);
  // D-07: a Crews pick counts once, after the toolbar controls; it never touches Booth.
  if (state.crew != null) changed.push('crew');
  return changed;
}

/**
 * Whether Clear all filters has anything to reset: a changed toolbar control, a venue picked
 * on the map (GROUP_RESETS.venue has no toolbar trigger, so `changedControls` never lists it),
 * or any state a group Reset is live for without its trigger showing it (renderGroupResets):
 * compare or called-together with no one selected, a stored Networks pick, search text.
 */
export function clearAllActive(changed, state, searchText = '') {
  return (
    changed.length > 0 ||
    state.venue != null ||
    state.compare ||
    state.together ||
    state.networks != null ||
    searchText !== ''
  );
}

/** Renders every toolbar trigger's label, value and `data-active` / `.is-changed` state (D-02). */
function renderTriggers(data, state, view) {
  const changed = new Set(changedControls(data, state, view));
  for (const name of TRIGGER_NAMES) {
    const btn = els.triggers[name];
    const { label, active } = triggerInfo(name, data, state, view);
    const resting = restingLabels.get(name) ?? label;
    const labelSpan = document.createElement('span');
    labelSpan.className = 'filter-label';
    labelSpan.textContent = resting;
    const valueSpan = document.createElement('span');
    valueSpan.className = 'filter-value';
    valueSpan.textContent = entryValue(name, data, state, view);
    const text = document.createElement('span');
    text.className = 'filter-text';
    text.append(labelSpan, valueSpan);
    btn.replaceChildren(text);
    btn.dataset.active = active ? 'true' : 'false';
    btn.classList.toggle('is-changed', changed.has(name));
    // The full summary is always available; a long pick truncates inside its entry.
    btn.setAttribute('title', label);
    btn.setAttribute('aria-label', label);
  }
}

/** Renders the phone `#filters-button` label, the changed-control chips and each section's pick (SHELL-03 Phone). */
function renderFiltersButton(data, state, view) {
  const changed = changedControls(data, state, view);
  const n = changed.length;
  els.filtersButton.textContent = n > 0 ? `Filters (${n} changed)` : 'Filters';
  els.filtersButton.classList.toggle('is-changed', n > 0);
  // Clear all filters looks and reads as disabled while nothing it would reset is changed: a
  // changed toolbar control, the map's venue filter (its chip sits in the table heading row),
  // or state only a group Reset shows, such as compare with no one selected or search text.
  const live = clearAllActive(changed, state, els.gameSearch.value);
  els.clearFilters.setAttribute('aria-disabled', live ? 'false' : 'true');
  const chips = changed.map((name) => {
    const { label, items } = triggerInfo(name, data, state, view);
    const li = document.createElement('li');
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'filter-chip';
    chip.setAttribute('popovertarget', 'filters-sheet');
    chip.setAttribute('aria-haspopup', 'dialog');
    // The crew pick has no toolbar trigger, so no resting label: bold its "Crew:" prefix.
    const resting = name === 'crew' ? 'Crew' : (restingLabels.get(name) ?? label);
    const value = name === 'crew' ? label.slice('Crew'.length) : triggerValue(name, label, true);
    const count = name === 'crew' ? crewPickNames(data, state).length : items.length;
    const text = document.createElement('span');
    text.className = 'chip-text';
    text.dataset.name = resting;
    text.dataset.value = value;
    text.dataset.count = String(count);
    chip.append(text);
    chip.setAttribute('aria-label', label);
    chip.title = label;
    li.append(chip);
    return li;
  });
  if (chips.length === 0) {
    const none = document.createElement('li');
    none.className = 'chip-none';
    none.textContent = 'No filters changed';
    chips.push(none);
  }
  els.filterChips.replaceChildren(...chips);
  fitFilterChips();
  for (const name of TRIGGER_NAMES) {
    const section = document.getElementById(TRIGGER_SECTIONS[name]);
    const head = section?.querySelector(':scope > .section-head');
    if (!head) continue;
    let pick = head.querySelector(':scope > .section-pick');
    if (!pick) {
      pick = document.createElement('span');
      pick.className = 'section-pick';
      head.querySelector('h3').after(pick);
    }
    const on = changed.includes(name);
    pick.hidden = !on;
    pick.textContent = on ? entryValue(name, data, state, view) : '';
  }
}

/**
 * Chooses each changed-filter chip's wording by measuring: the long form "Announcers: A, B" when it
 * fits on the chip, otherwise "Announcers (2)" (the filter name and the pick count, no middle dot).
 * The long form is set first and kept unless it overflows the chip.
 */
function fitFilterChips() {
  if (!els?.filterChips) return;
  for (const text of els.filterChips.querySelectorAll('.chip-text')) {
    const { name, value, count } = text.dataset;
    text.replaceChildren();
    const strong = document.createElement('b');
    strong.textContent = name;
    text.append(strong, document.createTextNode(value));
    text.dataset.form = 'long';
    // A closed panel has no width to measure; the next resize event decides.
    if (text.clientWidth > 0 && text.scrollWidth > text.clientWidth) {
      const short = document.createElement('b');
      short.textContent = name;
      text.replaceChildren(short, document.createTextNode(` (${count})`));
      text.dataset.form = 'short';
    }
  }
}

/** Dims each group's Reset button (`aria-disabled`) while that group is at its default (A4). */
function renderGroupResets(data, state, view) {
  for (const btn of document.querySelectorAll('.group-reset')) {
    const name = btn.dataset.reset;
    // The Announcers Reset also clears compare / called-together, so it is
    // live for `?mode=compare` with no one selected (the toolbar trigger's
    // own active state is left alone). The Networks Reset stays live while any
    // pick is stored (D-15), even one D-36 shows without a count, since that
    // pick is still in the URL and Reset is how the visitor removes it. The
    // Game Reset is also live while the search box holds text, since Reset
    // clears that too (IN-07, 04.10 IN-03).
    const active =
      name === 'announcers'
        ? state.people.length > 0 || state.compare || state.together
        : name === 'networks'
          ? state.networks != null
          : name === 'game'
            ? triggerInfo(name, data, state, view).active || els.gameSearch.value !== ''
            : triggerInfo(name, data, state, view).active;
    btn.setAttribute('aria-disabled', active ? 'false' : 'true');
  }
}

/** Filter controls with no meaning on This weekend (D-20): trigger, sheet section, hint. */
const WEEKEND_UNUSED = [
  { trigger: 'seasons', section: 'filter-seasons', hint: 'This weekend shows one week; use the week stepper.' },
  { trigger: 'kickoff', section: 'filter-slots', hint: 'Not used on This weekend' },
  { trigger: 'postseason', section: 'filter-postseason', hint: 'Not used on This weekend' },
  { trigger: 'game', section: 'filter-game', hint: 'Not used on This weekend' },
];

/**
 * Greys the controls This weekend does not use (D-20, D-21): `aria-disabled` plus the hint as
 * title and description, the popover link removed so the control cannot open, and the same on
 * the phone sheet's sections and the Fade | Hide switch. Restored when another tab is shown.
 */
function renderWeekendUnused(state) {
  const on = state.view === 'weekend';
  for (const { trigger, section, hint } of WEEKEND_UNUSED) {
    const btn = els.triggers[trigger];
    if (btn) {
      if (on) {
        if (btn.hasAttribute('popovertarget')) {
          btn.dataset.popovertarget = btn.getAttribute('popovertarget');
          btn.removeAttribute('popovertarget');
        }
        btn.setAttribute('aria-disabled', 'true');
        btn.setAttribute('title', hint);
        btn.setAttribute('aria-description', hint);
      } else {
        if (btn.dataset.popovertarget) btn.setAttribute('popovertarget', btn.dataset.popovertarget);
        delete btn.dataset.popovertarget;
        btn.removeAttribute('aria-disabled');
        btn.removeAttribute('aria-description');
      }
    }
    const sec = document.getElementById(section);
    if (sec) {
      sec.toggleAttribute('inert', on);
      sec.classList.toggle('is-unused', on);
      let note = sec.querySelector(':scope > .unused-hint');
      if (on && !note) {
        note = document.createElement('p');
        note.className = 'helper unused-hint';
        sec.prepend(note);
      }
      if (note) {
        note.hidden = !on;
        note.textContent = hint;
      }
    }
  }
  const dots = document.getElementById('dots-toggle');
  if (dots) {
    const group = dots.querySelector('.segmented');
    dots.classList.toggle('is-unused', on);
    for (const button of dots.querySelectorAll('button[data-dots]')) {
      if (on) button.setAttribute('aria-disabled', 'true');
      else button.removeAttribute('aria-disabled');
    }
    if (group) {
      if (on) group.setAttribute('title', 'Not used on This weekend');
      else group.setAttribute('title', 'Filters fade the games they exclude unless Hide is on.');
    }
  }
}

/** Pure DOM update from the current data/state/view, called every render cycle. */
export function renderFilters({ data, state, view }) {
  lastView = view;
  renderSeasons(data, state, view);
  renderNetworks(data, state, view);
  renderSlots(state, view);
  renderRole(state, view);
  renderConferences(state, view);
  renderSchool(data, state, view);
  renderPostseason(state, view);
  renderBooth(state, view);
  renderGame(data, state, view);
  renderOnlyButtons(data, state, view);
  renderTriggers(data, state, view);
  renderGroupResets(data, state, view);
  renderFiltersButton(data, state, view);
  renderWeekendUnused(state);
  // Last, once every trigger label (and so the toolbar's wrap) and the School
  // popover's own content are final: an open popover stays under its trigger.
  repositionOpenPopovers();
}
