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
import { offeredFamilyIds } from './select.js';
import { NEW_YEARS_SIX, SLOT_SHORT_LABELS, ROLE_LABELS, gameRowTitle } from './format.js';

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
];

/** Toolbar trigger names, in toolbar order -- also `#trigger-{name}`'s id suffix. */
const TRIGGER_NAMES = ['announcers', 'seasons', 'networks', 'kickoff', 'role', 'conference', 'school', 'postseason', 'game'];

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
};

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
 * D-36: how many Networks rows are shown, and how many of those are checked.
 * Iterates `data.primaryNetworks` only; missing facets count every row as shown.
 */
function shownNetworkCounts(data, state, view) {
  const currentIds = state.networks ?? allPrimaryNetworkIds(data);
  const narrowed = networksPickNarrowed(data, state);
  let shown = 0;
  let checkedShown = 0;
  for (const idx of data.primaryNetworks) {
    const net = data.lookups.networks[idx];
    const checked = currentIds.includes(net.id);
    const count = view?.facets?.networks?.[idx] ?? 1;
    if (networkRowHidden(count, checked, narrowed)) continue;
    shown += 1;
    if (checked) checkedShown += 1;
  }
  return { shown, checked: checkedShown };
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
  const helper = els.networksSection.querySelector('.helper');
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
    legend.appendChild(familyItem);
    fieldset.appendChild(legend);
    familyCheckboxes.set(familyKeyVal, familyCheckbox);

    const list = document.createElement('ul');
    list.className = 'network-list';
    const netIdxs = data.networksByFamily.get(familyKeyVal) ?? [];
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
    ...(helper ? [helper] : []),
    ...groups,
  );
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

const SAME_SET = (a, b) => a.length === b.length && a.every((x) => b.includes(x));

/** True when the button's option is already the sole selection, so it reads "All" (D-25). */
function onlyIsSole(btn, data, state, view) {
  const d = btn.dataset;
  if (d.onlyNetwork) return state.networks != null && SAME_SET(state.networks, [d.onlyNetwork]);
  if (d.onlyFamily) {
    const offered = offeredFamilyIds(data, d.onlyFamily, view);
    return state.networks != null && offered.length > 0 && SAME_SET(state.networks, offered);
  }
  if (d.onlySlot) return state.slots != null && SAME_SET(state.slots, [d.onlySlot]);
  if (d.onlyConference) return SAME_SET(state.conferences, [d.onlyConference]);
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
  if (onlyIsSole(btn, data, getState(), lastView)) {
    setState(structuredClone(GROUP_RESETS[resetKey]));
  } else if (d.onlyNetwork) {
    setState({ networks: [d.onlyNetwork] });
  } else if (d.onlyFamily) {
    setState({ networks: offeredFamilyIds(data, d.onlyFamily, lastView) });
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
    'input, button:not(.group-reset):not(.only-btn):not([data-match]), [tabindex]:not([tabindex="-1"]):not(.group-reset):not(.only-btn)',
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
  els.networksSection.addEventListener('click', onOnlyClick);
  els.slotsSection.addEventListener('click', onOnlyClick);
  els.conferenceList.addEventListener('click', onOnlyClick);

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

  els.postseasonOptions.addEventListener('click', (ev) => {
    const btn = ev.target.closest('[data-postseason]');
    if (!btn) return;
    setState({ postseason: btn.dataset.postseason });
  });
  bindPostseasonKeyboard(setState);

  els.gameSearch.addEventListener('input', () => {
    filterGameRows(data, els.gameSearch.value);
    // Typing alone can make the Game Reset live (04.10 IN-03); no render runs here.
    if (lastView) renderGroupResets(data, getState(), lastView);
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
  window.addEventListener('scroll', repositionOpenPopovers, { passive: true });
  window.addEventListener('resize', () => {
    repositionOpenPopovers();
    syncGameTooltips();
  });

  const mobileMedia = window.matchMedia('(max-width: 640px)');
  placeSections(mobileMedia.matches);
  mobileMedia.addEventListener('change', (ev) => placeSections(ev.matches));
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
  }
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

/** A toolbar trigger's label and active state, from `state` (D-02 copywriting).
 * D-36: the Networks count is the checked rows among the rows shown in the list. */
function triggerInfo(name, data, state, view) {
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
    const { shown, checked } = shownNetworkCounts(data, state, view);
    if (checked === shown) return { label: 'Networks', active: false };
    return { label: `Networks · ${checked}`, active: true };
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
    if (state.h2h === true && state.school.length === 2) {
      const [a, b] = state.school.map((slug) => data.lookups.teams[data.teamIndexBySlug.get(slug)].name);
      return { label: `School: ${a} vs ${b}`, active: true };
    }
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
  if (name === 'game') {
    const idx = state.game != null ? data.gameIndexBySlug.get(state.game) : undefined;
    if (idx === undefined) return { label: 'Game', active: false };
    return { label: `Game: ${data.games[idx].label}`, active: true };
  }
  return { label: name, active: false };
}

/** Renders every toolbar trigger's label and `data-active` state (D-02). */
function renderTriggers(data, state, view) {
  for (const name of TRIGGER_NAMES) {
    const btn = els.triggers[name];
    const { label, active } = triggerInfo(name, data, state, view);
    btn.textContent = label;
    btn.dataset.active = active ? 'true' : 'false';
    // The full label is always available; long ones truncate in their grid cell (04.9 D-21).
    btn.setAttribute('title', label);
    btn.setAttribute('aria-label', label);
  }
}

/** Counts the active filters, for the mobile Filters(N) button (extends SITE-18's rail-era count).
 * D-27: also counts every selected announcer, since the phone Announcers
 * picker lives inside this same Filters sheet and "Clear all filters"
 * clears people too. Networks counts exactly when its trigger shows a count
 * (D-36), so the badge and the Networks button never disagree (review WR-02). */
function activeFilterCount(data, state, view) {
  let n = 0;
  if (state.seasons != null) n += 1;
  if (triggerInfo('networks', data, state, view).active) n += 1;
  if (state.slots != null) n += 1;
  if (state.role != null) n += 1;
  if (state.conferences.length > 0) n += 1;
  if (state.school.length > 0) n += 1;
  if (state.postseason !== 'all') n += 1;
  if (triggerInfo('game', data, state, view).active) n += 1;
  n += state.people.length;
  return n;
}

/** Renders the `#filters-button` label (SITE-18, D-03). */
function renderFiltersButton(data, state, view) {
  const n = activeFilterCount(data, state, view);
  els.filtersButton.textContent = n > 0 ? `Filters (${n})` : 'Filters';
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
  renderGame(data, state, view);
  renderOnlyButtons(data, state, view);
  renderTriggers(data, state, view);
  renderGroupResets(data, state, view);
  renderFiltersButton(data, state, view);
  // Last, once every trigger label (and so the toolbar's wrap) and the School
  // popover's own content are final: an open popover stays under its trigger.
  repositionOpenPopovers();
}
