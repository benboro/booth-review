/**
 * NFL toolbar filters (D-02, D-08): Clear all filters, Announcers, Seasons,
 * Category and Team popovers, plus the mobile Filters button and its own
 * bottom sheet (`#nfl-filters-sheet`).
 *
 * Nothing here touches CFB nodes or the CFB filters module: each section is built
 * twice (desktop popover and mobile sheet), both copies bound to the same NFL
 * state through ctx.setState. Everything is built with createElement and
 * textContent only (no markup strings). Every write goes through ctx.setState, which
 * runs canonicalNflState before the URL is written.
 *
 * `chipsHost` is `#nfl-chips`, rendered by index.js; `clearHost` is the count line's right side
 * (`.sum-right`), where Clear all filters sits last (C1). On a phone this module moves the chips
 * and Clear selection into the sheet's people strip. The bar itself is fixed: Booths is always
 * visible (D-11), and its entries are grouped Broadcast, Matchup, Calendar like the CFB bar.
 */
import { makeRolePill } from '../../modules/pill.js';
import { CATEGORY_OPTIONS, boothGames, defaultNflState } from './state.js';
import { PHONE_QUERY } from '../../modules/breakpoints.js';

const TRIGGERS = [
  { key: 'announcers', label: 'Announcers' },
  { key: 'seasons', label: 'Seasons' },
  { key: 'category', label: 'Category' },
  { key: 'team', label: 'Team' },
  { key: 'booths', label: 'Booths' },
];

/** The bar's three ruled groups, left to right (UI-SPEC decision 8); the phone sheet uses the same. */
const GROUPS = [
  { key: 'broadcast', label: 'Broadcast', keys: ['announcers', 'booths'] },
  { key: 'matchup', label: 'Matchup', keys: ['team', 'category'] },
  { key: 'calendar', label: 'Calendar', keys: ['seasons'] },
];

const UNUSED_ON_WEEKEND = ['seasons', 'category'];
const NOT_USED = 'Not used on This weekend';

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

let toolbarEl = null;
let clearHost = null;
let layer = null;
let ui = null; // { clear, filtersButton, triggers: Map, sheet, popovers: Map }
let built = false; // sections need the loaded model
let updaters = [];
let mobileMql = null;
let chipsEl = null;

// ---- section builders (one copy per container) ----

function sectionHead(title, onReset) {
  const head = el('div', 'section-head');
  const reset = el('button', 'group-reset', 'Reset');
  reset.type = 'button';
  reset.setAttribute('aria-label', `Reset ${title}`);
  reset.addEventListener('click', () => {
    if (reset.getAttribute('aria-disabled') !== 'true') onReset();
  });
  head.append(el('h3', null, title), reset);
  return { head, reset };
}

function setDisabledLook(btn, disabled) {
  btn.setAttribute('aria-disabled', disabled ? 'true' : 'false');
}

function labelFor(input, text) {
  const label = el('label', 'visually-hidden', text);
  label.htmlFor = input.id;
  return label;
}

function announcersSection(ctx, sfx) {
  const { model } = ctx;
  const root = el('section', 'nfl-filter-section');
  root.id = `nfl-filter-announcers-${sfx}`;
  const { head, reset } = sectionHead('Announcers', () => ctx.setState({ people: [] }));
  const field = el('div', 'search-field');
  const input = el('input');
  input.type = 'text';
  input.id = `nfl-person-search-${sfx}`;
  input.setAttribute('role', 'combobox');
  input.setAttribute('aria-autocomplete', 'list');
  input.setAttribute('aria-controls', `nfl-person-results-${sfx}`);
  input.placeholder = 'Type a name, or pick from the list';
  input.autocomplete = 'off';
  const list = el('ul', 'nfl-people-list');
  list.id = `nfl-person-results-${sfx}`;
  list.setAttribute('role', 'listbox');
  list.setAttribute('aria-multiselectable', 'true');
  list.setAttribute('aria-label', 'Announcers');
  const empty = el('p', 'helper', 'No announcers match.');
  empty.hidden = true;

  // CFB parity (D-18): each row carries the person's usual role pill and game count, as CFB's list does.
  const roleTally = new Map();
  for (const crew of model.cols.crew) {
    for (const m of crew || []) {
      const t = roleTally.get(m.person) ?? new Map();
      t.set(m.role, (t.get(m.role) ?? 0) + 1);
      roleTally.set(m.person, t);
    }
  }
  // Every NFL tab shares this list, so a person known only from an upcoming This weekend crew is
  // left out: picking them would zero every other tab (18-13 F9).
  const upcomingOnly = new Set();
  for (const crew of model.upcomingRaw?.crew ?? []) {
    for (const m of crew || []) {
      if (!roleTally.has(m.person) && !(model.personGames.get(m.person) || []).length) {
        upcomingOnly.add(m.person);
      }
    }
  }
  const people = model.people
    .filter((p) => !upcomingOnly.has(model.personIndex.get(p.id)))
    .sort((a, b) => a.name.localeCompare(b.name));
  const usualRole = (idx) => {
    const t = roleTally.get(idx);
    if (!t) return 'unknown';
    return [...t.entries()].sort((a, b) => b[1] - a[1])[0][0];
  };
  const rows = new Map();
  // Roving tabindex (JS-WR-05): the list is one tab stop, held by `stop`.
  // ArrowUp/ArrowDown, Home and End move between the visible options, and
  // ArrowUp on the first option goes back to the search box.
  let stop = null;
  const setStop = (li) => {
    if (stop && stop !== li) stop.tabIndex = -1;
    stop = li;
    if (li) li.tabIndex = 0;
  };
  const visibleRows = () => [...list.children].filter((li) => !li.hidden);
  const toggle = (id) => {
    const cur = ctx.getState().people;
    ctx.setState({ people: cur.includes(id) ? cur.filter((p) => p !== id) : [...cur, id] });
  };
  for (const p of people) {
    const li = el('li');
    li.setAttribute('role', 'option');
    li.tabIndex = -1;
    li.dataset.person = p.id;
    const box = el('span', 'option-check');
    box.setAttribute('aria-hidden', 'true');
    const idx = model.personIndex.get(p.id);
    const roleSpan = el('span', 'option-role');
    roleSpan.appendChild(makeRolePill(usualRole(idx)));
    const countSpan = el('span', 'option-count', `(${(model.personGames.get(idx) || []).length})`);
    countSpan.setAttribute('aria-hidden', 'true');
    li.append(box, el('span', 'option-name', p.name), roleSpan, countSpan);
    li.addEventListener('click', () => toggle(p.id));
    li.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        toggle(p.id);
      }
    });
    rows.set(p.id, { li, lower: p.name.toLowerCase() });
    list.appendChild(li);
  }

  function filterRows() {
    const q = input.value.trim().toLowerCase();
    let shown = 0;
    for (const { li, lower } of rows.values()) {
      const hit = !q || lower.includes(q);
      li.hidden = !hit;
      if (hit) shown += 1;
    }
    empty.hidden = shown > 0;
    input.setAttribute('aria-expanded', shown > 0 ? 'true' : 'false');
    if (!stop || stop.hidden) setStop(visibleRows()[0] ?? null);
  }
  input.addEventListener('input', filterRows);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') {
      const first = visibleRows()[0];
      if (first) {
        e.preventDefault();
        setStop(first);
        first.focus();
      }
    }
  });
  list.addEventListener('focusin', (e) => {
    const li = e.target.closest('li[role="option"]');
    if (li) setStop(li);
  });
  list.addEventListener('keydown', (e) => {
    const li = e.target.closest('li[role="option"]');
    if (!li) return;
    const shown = visibleRows();
    const at = shown.indexOf(li);
    let target = null;
    if (e.key === 'ArrowDown') target = shown[Math.min(at + 1, shown.length - 1)];
    else if (e.key === 'ArrowUp') target = at > 0 ? shown[at - 1] : input;
    else if (e.key === 'Home') target = shown[0];
    else if (e.key === 'End') target = shown[shown.length - 1];
    if (!target) return;
    e.preventDefault();
    if (target !== input) setStop(target);
    target.focus();
  });

  field.append(labelFor(input, 'Search announcers'), input, list, empty);
  root.append(head, field);
  filterRows();
  return {
    root,
    update(state) {
      const sel = new Set(state.people);
      for (const [id, { li }] of rows) li.setAttribute('aria-selected', sel.has(id) ? 'true' : 'false');
      setDisabledLook(reset, state.people.length === 0);
    },
  };
}

/** The Booths list is grouped by category on Viewership and by network family everywhere else (D-10). */
const boothGrouping = (view) => (view === 'viewership' ? 'viewership' : 'network');

function sameKeys(a, b) {
  return a.length === b.length && a.every((k) => b.includes(k));
}

/**
 * Booths: a searchable checklist grouped by network on Crews and by category on
 * Viewership, with Only/All shortcuts per group (D-10). Picks write `booths`.
 */
function boothsSection(ctx, sfx) {
  const { model } = ctx;
  const root = el('section', 'nfl-filter-section');
  root.id = `nfl-filter-booths-${sfx}`;
  const { head, reset } = sectionHead('Booths', () => ctx.setState({ booths: [] }));
  const field = el('div', 'search-field');
  const input = el('input');
  input.type = 'text';
  input.id = `nfl-booth-search-${sfx}`;
  input.setAttribute('role', 'combobox');
  input.setAttribute('aria-autocomplete', 'list');
  input.setAttribute('aria-controls', `nfl-booth-results-${sfx}`);
  input.placeholder = 'Search booths';
  input.autocomplete = 'off';
  const list = el('ul', 'nfl-people-list nfl-booth-list');
  list.id = `nfl-booth-results-${sfx}`;
  list.setAttribute('role', 'listbox');
  list.setAttribute('aria-multiselectable', 'true');
  list.setAttribute('aria-label', 'Booths');
  const empty = el('p', 'helper', 'No booths match.');
  empty.hidden = true;

  const counts = new Map(model.boothCatalog.map((e) => [e.key, boothGames(model, [e.key]).length]));
  let builtFor = null; // the grouping the list was built for
  let groups = []; // [{ id, head, only, keys, options: [{ li, key, lower }] }]
  let stop = null;
  const setStop = (li) => {
    if (stop && stop !== li) stop.tabIndex = -1;
    stop = li;
    if (li) li.tabIndex = 0;
  };
  const optionRows = () => [...list.querySelectorAll('li[role="option"]')].filter((li) => !li.hidden);
  const toggle = (key) => {
    const cur = ctx.getState().booths;
    ctx.setState({ booths: cur.includes(key) ? cur.filter((k) => k !== key) : [...cur, key] });
  };

  function groupings(grouping) {
    if (grouping === 'viewership') {
      return model.viewCategories
        .map((vc, ci) => ({
          id: vc.id,
          name: vc.label,
          entries: model.boothCatalog.filter((e) => e.categories.has(ci)),
        }))
        .filter((g) => g.entries.length);
    }
    return model.networkGroups
      .map((g, gi) => ({ id: g.id, name: g.name, entries: model.boothCatalog.filter((e) => e.group === gi) }))
      .filter((g) => g.entries.length);
  }

  function rebuild(grouping) {
    builtFor = grouping;
    groups = [];
    stop = null;
    list.replaceChildren();
    for (const g of groupings(grouping)) {
      const headLi = el('li', 'group-head');
      headLi.setAttribute('role', 'presentation');
      const only = el('button', 'only-btn', 'Only');
      only.type = 'button';
      only.dataset.onlyGroup = g.id;
      const keys = g.entries.map((e) => e.key);
      only.addEventListener('click', (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        const sole = sameKeys(ctx.getState().booths, keys);
        ctx.setState({ booths: sole ? [] : keys });
      });
      headLi.append(el('span', 'group-name', g.name), only);
      list.appendChild(headLi);
      const options = [];
      for (const e of g.entries) {
        const li = el('li');
        li.setAttribute('role', 'option');
        li.tabIndex = -1;
        li.dataset.booth = e.key;
        const box = el('span', 'option-check');
        box.setAttribute('aria-hidden', 'true');
        // Announcers parity: one line per person with its role pill, then the game
        // count (the games picking this booth selects).
        const people = el('span', 'option-people');
        const line = (idx, role) => {
          const roleSpan = el('span', 'option-role');
          roleSpan.appendChild(makeRolePill(role));
          const row = el('span', 'option-line');
          row.append(el('span', 'option-name', model.people[idx].name), roleSpan);
          people.appendChild(row);
        };
        line(e.person, 'pbp');
        if (e.analyst != null) line(e.analyst, 'analyst');
        const countSpan = el('span', 'option-count', `(${counts.get(e.key)})`);
        countSpan.setAttribute('aria-hidden', 'true');
        li.append(box, people, countSpan);
        li.addEventListener('click', () => toggle(e.key));
        li.addEventListener('keydown', (ev) => {
          if (ev.key === 'Enter' || ev.key === ' ') {
            ev.preventDefault();
            toggle(e.key);
          }
        });
        list.appendChild(li);
        options.push({ li, key: e.key, lower: e.label.toLowerCase() });
      }
      groups.push({ id: g.id, name: g.name, head: headLi, only, keys, options });
    }
    filterRows();
  }

  function filterRows() {
    const q = input.value.trim().toLowerCase();
    let shown = 0;
    for (const g of groups) {
      let any = false;
      for (const o of g.options) {
        const hit = !q || o.lower.includes(q);
        o.li.hidden = !hit;
        if (hit) {
          any = true;
          shown += 1;
        }
      }
      g.head.hidden = !any;
    }
    empty.hidden = shown > 0;
    input.setAttribute('aria-expanded', shown > 0 ? 'true' : 'false');
    if (!stop || stop.hidden || !list.contains(stop)) setStop(optionRows()[0] ?? null);
  }
  input.addEventListener('input', filterRows);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') {
      const first = optionRows()[0];
      if (first) {
        e.preventDefault();
        setStop(first);
        first.focus();
      }
    }
  });
  list.addEventListener('focusin', (e) => {
    const li = e.target.closest('li[role="option"]');
    if (li) setStop(li);
  });
  list.addEventListener('keydown', (e) => {
    const li = e.target.closest('li[role="option"]');
    if (!li) return;
    const shown = optionRows();
    const at = shown.indexOf(li);
    let target = null;
    if (e.key === 'ArrowDown') target = shown[Math.min(at + 1, shown.length - 1)];
    else if (e.key === 'ArrowUp') target = at > 0 ? shown[at - 1] : input;
    else if (e.key === 'Home') target = shown[0];
    else if (e.key === 'End') target = shown[shown.length - 1];
    if (!target) return;
    e.preventDefault();
    if (target !== input) setStop(target);
    target.focus();
  });

  field.append(labelFor(input, 'Search booths'), input, list, empty);
  root.append(head, field);
  return {
    root,
    update(state) {
      const grouping = boothGrouping(state.view);
      if (builtFor !== grouping) rebuild(grouping);
      const sel = new Set(state.booths);
      for (const g of groups) {
        for (const o of g.options) o.li.setAttribute('aria-selected', sel.has(o.key) ? 'true' : 'false');
        const sole = sameKeys(state.booths, g.keys);
        g.only.textContent = sole ? 'All' : 'Only';
        g.only.setAttribute('aria-label', sole ? 'Show all booths' : `Show only ${g.name}`);
      }
      setDisabledLook(reset, state.booths.length === 0);
    },
  };
}

function seasonsSection(ctx, sfx) {
  const { model } = ctx;
  const d = defaultNflState(model);
  const root = el('section', 'nfl-filter-section');
  root.id = `nfl-filter-seasons-${sfx}`;
  const { head, reset } = sectionHead('Seasons', () => ctx.setState({ seasons: [...d.seasons] }));
  const from = el('select');
  from.id = `nfl-season-from-${sfx}`;
  const to = el('select');
  to.id = `nfl-season-to-${sfx}`;
  for (let y = model.seasons[0]; y <= model.seasons[1]; y++) {
    from.appendChild(new Option(String(y), String(y)));
    to.appendChild(new Option(String(y), String(y)));
  }
  const fromLabel = el('label', null, 'From');
  fromLabel.htmlFor = from.id;
  const toLabel = el('label', null, 'To');
  toLabel.htmlFor = to.id;
  from.addEventListener('change', () => {
    const lo = Number(from.value);
    const hi = Math.max(lo, Number(to.value));
    ctx.setState({ seasons: [lo, hi] });
  });
  to.addEventListener('change', () => {
    const hi = Number(to.value);
    const lo = Math.min(hi, Number(from.value));
    ctx.setState({ seasons: [lo, hi] });
  });
  root.append(head, fromLabel, from, toLabel, to);
  return {
    root,
    update(state) {
      from.value = String(state.seasons[0]);
      to.value = String(state.seasons[1]);
      setDisabledLook(reset, state.seasons[0] === d.seasons[0] && state.seasons[1] === d.seasons[1]);
    },
  };
}

function categorySection(ctx, sfx) {
  const root = el('section', 'nfl-filter-section');
  root.id = `nfl-filter-category-${sfx}`;
  const { head, reset } = sectionHead('Category', () => ctx.setState({ cats: [] }));
  root.appendChild(head);
  const boxes = new Map();
  const groups = [...new Set(CATEGORY_OPTIONS.map((o) => o.group))];
  for (const group of groups) {
    const fs = el('fieldset', 'nfl-cat-group');
    fs.appendChild(el('legend', null, group));
    for (const opt of CATEGORY_OPTIONS.filter((o) => o.group === group)) {
      const item = el('div', 'check-item');
      const label = el('label', 'check-row');
      const box = el('input');
      box.type = 'checkbox';
      box.name = 'nfl-cat';
      box.value = opt.key;
      box.addEventListener('change', () => {
        const cur = new Set(ctx.getState().cats);
        if (box.checked) cur.add(opt.key);
        else cur.delete(opt.key);
        ctx.setState({ cats: [...cur] });
      });
      label.append(box, document.createTextNode(' '), el('span', 'option-name', opt.label));
      item.appendChild(label);
      fs.appendChild(item);
      boxes.set(opt.key, box);
    }
    root.appendChild(fs);
  }
  root.appendChild(el('p', 'helper', 'Games in any checked category match.'));
  return {
    root,
    update(state) {
      const sel = new Set(state.cats);
      for (const [key, box] of boxes) box.checked = sel.has(key);
      setDisabledLook(reset, state.cats.length === 0);
    },
  };
}

function teamSection(ctx, sfx) {
  const { model } = ctx;
  const root = el('section', 'nfl-filter-section');
  root.id = `nfl-filter-team-${sfx}`;
  const { head, reset } = sectionHead('Team', () => ctx.setState({ teams: [] }));
  const input = el('input');
  input.type = 'search';
  input.id = `nfl-team-search-${sfx}`;
  input.placeholder = 'Search teams';
  input.autocomplete = 'off';
  input.className = 'nfl-team-search';
  const fs = el('fieldset', 'nfl-team-list');
  fs.appendChild(el('legend', 'visually-hidden', 'Team, multi-select'));
  const empty = el('p', 'helper', 'No teams match.');
  empty.hidden = true;
  const rows = new Map();
  const franchises = [...model.franchises].sort((a, b) => a.name.localeCompare(b.name));
  for (const f of franchises) {
    const item = el('div', 'check-item');
    const label = el('label', 'check-row');
    const box = el('input');
    box.type = 'checkbox';
    box.name = 'nfl-team';
    box.value = f.id;
    box.addEventListener('change', () => {
      const cur = new Set(ctx.getState().teams);
      if (box.checked) cur.add(f.id);
      else cur.delete(f.id);
      ctx.setState({ teams: [...cur] });
    });
    label.append(box, document.createTextNode(' '), el('span', 'option-name', f.name));
    item.appendChild(label);
    fs.appendChild(item);
    rows.set(f.id, { item, box, lower: f.name.toLowerCase() });
  }
  input.addEventListener('input', () => {
    const q = input.value.trim().toLowerCase();
    let shown = 0;
    for (const { item, lower } of rows.values()) {
      const hit = !q || lower.includes(q);
      item.hidden = !hit;
      if (hit) shown += 1;
    }
    empty.hidden = shown > 0;
  });
  root.append(head, labelFor(input, 'Search teams'), input, fs, empty);
  return {
    root,
    update(state) {
      const sel = new Set(state.teams);
      for (const [id, { box }] of rows) box.checked = sel.has(id);
      setDisabledLook(reset, state.teams.length === 0);
    },
  };
}

const BUILDERS = {
  announcers: announcersSection,
  booths: boothsSection,
  seasons: seasonsSection,
  category: categorySection,
  team: teamSection,
};

// ---- popover placement ----

function placePopover(pop, trigger) {
  const r = trigger.getBoundingClientRect();
  const margin = 8;
  const width = Math.min(pop.offsetWidth || 240, window.innerWidth - 2 * margin);
  let left = Math.min(Math.max(r.left, margin), window.innerWidth - width - margin);
  if (left < margin) left = margin;
  pop.style.left = `${left}px`;
  pop.style.top = `${r.bottom + 4}px`;
}

// ---- control text and the changed predicate ----

/** One trigger's text: the resting label, then the value (empty at default), in two inline spans. */
function triggerText(label, value) {
  const text = el('span', 'filter-text');
  text.append(el('span', 'filter-label', label), el('span', 'filter-value', value));
  return text;
}

/**
 * Per control: whether it differs from a clean load (defaultNflState), the entry's value line
 * (a default word or the pick itself), the full text for the title and the chips, and the pick
 * names. One predicate for the desktop accent, the phone "Filters (N changed)" label and the chips.
 */
function controlInfo(model, state) {
  const d = defaultNflState(model);
  const personName = (id) => {
    const idx = model.personIndex.get(id);
    return idx == null ? id : model.people[idx].name;
  };
  const teamName = (id) => model.franchises.find((f) => f.id === id)?.name ?? id;
  const boothName = (key) => model.boothIndex.get(key)?.label ?? key;
  const catName = (key) => CATEGORY_OPTIONS.find((o) => o.key === key)?.label ?? key;
  const picks = (label, noneWord, names) => ({
    active: names.length > 0,
    items: names,
    value: names.length === 0 ? noneWord : names.length === 1 ? names[0] : `${names[0]} +${names.length - 1}`,
    full: names.length === 0 ? label : `${label}: ${names.join(', ')}`,
  });
  const seasonsChanged = state.seasons[0] !== d.seasons[0] || state.seasons[1] !== d.seasons[1];
  const range = `${state.seasons[0]}–${state.seasons[1]}`;
  return {
    announcers: picks('Announcers', 'Any', state.people.map(personName)),
    seasons: {
      active: seasonsChanged,
      items: [range],
      value: range,
      full: seasonsChanged ? `Seasons: ${range}` : 'Seasons',
    },
    category: picks('Category', 'All', state.cats.map(catName)),
    team: picks('Team', 'Any', state.teams.map(teamName)),
    booths: picks('Booths', 'Any', state.booths.map(boothName)),
  };
}

/** The control keys that differ from a clean load, in bar order. */
export function changedControls(model, state) {
  const info = controlInfo(model, state);
  return TRIGGERS.map((t) => t.key).filter((key) => info[key].active);
}

// ---- init / render ----

function clearAll(ctx) {
  const d = defaultNflState(ctx.model);
  ctx.setState({ seasons: [...d.seasons], teams: [], people: [], cats: [], booths: [] });
}

function buildShell(ctx) {
  const clear = el('button', 'clear-all', 'Clear all filters');
  clear.type = 'button';
  clear.id = 'nfl-clear-filters';
  clear.addEventListener('click', () => {
    // aria-disabled while nothing is changed (renderNflFilters): a no-op then.
    if (clear.getAttribute('aria-disabled') === 'true') return;
    if (ctx.model) clearAll(ctx);
  });

  const filtersButton = el('button', 'mobile-only', 'Filters');
  filtersButton.type = 'button';
  filtersButton.id = 'nfl-filters-button';
  filtersButton.setAttribute('popovertarget', 'nfl-filters-sheet');
  filtersButton.setAttribute('aria-haspopup', 'dialog');
  filtersButton.setAttribute('aria-expanded', 'false');

  const triggers = new Map();
  const popovers = new Map();
  const filterChips = el('ul', 'filter-chips');
  filterChips.id = 'nfl-filter-chips';
  filterChips.setAttribute('aria-label', 'Changed filters');
  const nodes = [filtersButton];
  const rows = new Map();
  for (const g of GROUPS) {
    const group = el('div', 'fgroup');
    group.dataset.g = g.key;
    group.setAttribute('role', 'group');
    const groupLabel = el('span', 'fgroup-label', g.label);
    groupLabel.id = `nfl-fgroup-${g.key}`;
    group.setAttribute('aria-labelledby', groupLabel.id);
    const row = el('div', 'fgroup-row');
    group.append(groupLabel, row);
    rows.set(g.key, row);
    nodes.push(group);
  }
  const rowOf = (key) => rows.get(GROUPS.find((g) => g.keys.includes(key)).key);
  // Triggers are created in bar order (the groups', left to right), so Tab follows what is drawn.
  const inBarOrder = GROUPS.flatMap((g) => g.keys.map((key) => TRIGGERS.find((t) => t.key === key)));
  for (const t of inBarOrder) {
    const btn = el('button', 'filter-trigger desktop-only');
    btn.append(triggerText(t.label, ''));
    btn.type = 'button';
    btn.id = `nfl-trigger-${t.key}`;
    btn.setAttribute('popovertarget', `nfl-pop-${t.key}`);
    btn.setAttribute('aria-haspopup', 'dialog');
    btn.setAttribute('aria-expanded', 'false');
    triggers.set(t.key, btn);
    rowOf(t.key).append(btn);

    const pop = el('div', 'filter-popover nfl-filter-popover');
    pop.id = `nfl-pop-${t.key}`;
    pop.setAttribute('popover', 'auto');
    pop.setAttribute('role', 'dialog');
    pop.setAttribute('aria-label', t.label);
    pop.addEventListener('beforetoggle', (e) => {
      // A control This weekend does not use stays shut (D-21).
      if (e.newState === 'open' && btn.getAttribute('aria-disabled') === 'true') {
        e.preventDefault();
        return;
      }
      if (e.newState === 'open') {
        placePopover(pop, btn);
        requestAnimationFrame(() => placePopover(pop, btn));
      }
    });
    pop.addEventListener('toggle', (e) => {
      btn.setAttribute('aria-expanded', e.newState === 'open' ? 'true' : 'false');
    });
    popovers.set(t.key, pop);
    layer.appendChild(pop);
  }
  toolbarEl.append(...nodes);
  if (clearHost) clearHost.append(clear);

  const sheet = el('div', 'filters-sheet nfl-filters-sheet');
  sheet.id = 'nfl-filters-sheet';
  sheet.setAttribute('popover', 'auto');
  sheet.setAttribute('role', 'dialog');
  sheet.setAttribute('aria-labelledby', 'nfl-filters-sheet-title');
  const header = el('div', 'sheet-header');
  const title = el('h2', null, 'Filters');
  title.id = 'nfl-filters-sheet-title';
  const clearSlot = el('div', 'sheet-clear-slot');
  const sheetClear = el('button', 'nfl-sheet-clear', 'Clear all filters');
  sheetClear.type = 'button';
  sheetClear.addEventListener('click', () => {
    // aria-disabled while nothing is changed (renderNflFilters): a no-op then.
    if (sheetClear.getAttribute('aria-disabled') === 'true') return;
    if (ctx.model) clearAll(ctx);
  });
  clearSlot.appendChild(sheetClear);
  header.append(title, clearSlot);
  const body = el('div', 'sheet-body');
  const footer = el('div', 'sheet-footer');
  const show = el('button', null, 'Show games');
  show.type = 'button';
  show.id = 'nfl-filters-show-results';
  show.addEventListener('click', () => {
    if (sheet.matches(':popover-open')) sheet.hidePopover();
  });
  footer.appendChild(show);
  sheet.append(header, filterChips, body, footer);
  sheet.addEventListener('toggle', (e) => {
    filtersButton.setAttribute('aria-expanded', e.newState === 'open' ? 'true' : 'false');
  });
  layer.appendChild(sheet);

  ui = { clear, sheetClear, filtersButton, filterChips, triggers, popovers, sheet, sheetBody: body };
  for (const btn of [filtersButton, ...triggers.values()]) {
    btn.disabled = true;
  }
}

function buildSections(ctx) {
  const sheetRoots = new Map();
  for (const t of TRIGGERS) {
    const popSection = BUILDERS[t.key](ctx, 'pop');
    ui.popovers.get(t.key).appendChild(popSection.root);
    const sheetSection = BUILDERS[t.key](ctx, 'sheet');
    sheetRoots.set(t.key, sheetSection.root);
    updaters.push(popSection.update, sheetSection.update);
  }
  // The phone sheet follows the bar: Broadcast, Matchup, Calendar, each under a ruled label.
  for (const g of GROUPS) {
    ui.sheetBody.appendChild(el('div', 'sheet-group-label', g.label));
    for (const key of g.keys) ui.sheetBody.appendChild(sheetRoots.get(key));
  }
  for (const btn of [ui.filtersButton, ...ui.triggers.values()]) btn.disabled = false;
  built = true;
  placeSelection(mobileMql.matches);
}

/**
 * Moves the selection chips and Clear selection between the count line (desktop) and the people
 * strip under the phone sheet's Announcers heading, and keeps Clear all filters last on the count line.
 */
function placeSelection(isMobile) {
  const chips = chipsEl;
  const clearSel = clearHost?.querySelector('#nfl-clear-selection') ?? document.getElementById('nfl-clear-selection');
  if (!chips || !clearSel) return;
  if (isMobile) {
    const head = document.querySelector('#nfl-filter-announcers-sheet > .section-head');
    if (!head) return;
    const strip = el('div', 'people-strip');
    strip.id = 'nfl-people-strip';
    strip.append(chips, clearSel);
    head.after(strip);
  } else {
    document.getElementById('nfl-people-strip')?.remove();
    if (clearHost) clearHost.append(chips, clearSel, ui.clear);
  }
}

/**
 * Build the toolbar controls once. The sections wait for the loaded model;
 * until then the triggers are disabled (also the load-error state).
 */
export function initNflFilters({ toolbar, sheetHost, clearHost: clearRow, chipsHost, ctx }) {
  if (ui) return;
  toolbarEl = toolbar;
  clearHost = clearRow ?? null;
  chipsEl = chipsHost ?? null;
  layer = sheetHost;
  buildShell(ctx);
  mobileMql = window.matchMedia(PHONE_QUERY);
  mobileMql.addEventListener('change', (ev) => {
    closeNflFilters();
    if (built) placeSelection(ev.matches);
  });
  // The changed-filter chips re-decide their wording whenever their strip's width changes: opening
  // the sheet, a rotation, or a resize (a closed sheet measures 0 and is skipped).
  new ResizeObserver(() => fitFilterChips()).observe(ui.filterChips);
}

export function closeNflFilters() {
  if (!ui) return;
  for (const p of [...ui.popovers.values(), ui.sheet]) {
    if (p.matches(':popover-open')) p.hidePopover();
  }
}

export function renderNflFilters(ctx) {
  if (!ui || !ctx.model) return;
  if (!built) buildSections(ctx);
  const state = ctx.getState();
  for (const update of updaters) update(state);
  const info = controlInfo(ctx.model, state);
  for (const [key, btn] of ui.triggers) {
    const { active, value, full } = info[key];
    const label = TRIGGERS.find((t) => t.key === key).label;
    btn.replaceChildren(triggerText(label, value));
    btn.dataset.active = active ? 'true' : 'false';
    btn.classList.toggle('is-changed', active);
    // The full summary is always available; a long pick truncates inside its entry.
    btn.setAttribute('title', full);
    btn.setAttribute('aria-label', full);
  }
  // This weekend uses only Team, Announcers and Booths: Seasons and Category are greyed (D-21).
  const weekendView = state.view === 'weekend';
  for (const key of UNUSED_ON_WEEKEND) {
    const btn = ui.triggers.get(key);
    btn.setAttribute('aria-disabled', weekendView ? 'true' : 'false');
    if (weekendView) {
      btn.title = NOT_USED;
      btn.setAttribute('aria-description', NOT_USED);
      if (btn.matches(':popover-open')) btn.popoverTargetElement?.hidePopover();
    } else {
      btn.removeAttribute('aria-description');
    }
    for (const root of document.querySelectorAll(`#nfl-filter-${key}-pop, #nfl-filter-${key}-sheet`)) {
      root.classList.toggle('is-unused', weekendView);
      root.setAttribute('aria-disabled', weekendView ? 'true' : 'false');
      let note = root.querySelector('.nfl-unused-note');
      if (weekendView && !note) {
        note = el('p', 'helper nfl-unused-note', NOT_USED);
        root.prepend(note);
      }
      if (note) note.hidden = !weekendView;
      for (const child of root.children) if (child !== note) child.inert = weekendView;
    }
  }
  const changed = changedControls(ctx.model, state);
  ui.filtersButton.textContent = changed.length ? `Filters (${changed.length} changed)` : 'Filters';
  ui.filtersButton.classList.toggle('is-changed', changed.length > 0);
  // Clear all filters looks and reads as disabled while nothing is changed (the shared predicate).
  for (const btn of [ui.clear, ui.sheetClear]) btn.setAttribute('aria-disabled', changed.length > 0 ? 'false' : 'true');
  const chips = changed.map((key) => {
    const label = TRIGGERS.find((t) => t.key === key).label;
    const { full, items } = info[key];
    const li = el('li');
    const chip = el('button', 'filter-chip');
    chip.type = 'button';
    chip.setAttribute('popovertarget', 'nfl-filters-sheet');
    chip.setAttribute('aria-haspopup', 'dialog');
    chip.setAttribute('aria-label', full);
    chip.title = full;
    const text = el('span', 'chip-text');
    text.dataset.name = label;
    text.dataset.value = full.slice(label.length);
    text.dataset.count = String(key === 'seasons' ? 1 : items.length);
    chip.append(text);
    li.append(chip);
    return li;
  });
  if (chips.length === 0) chips.push(el('li', 'chip-none', 'No filters changed'));
  ui.filterChips.replaceChildren(...chips);
  fitFilterChips();
  // A changed section shows its pick beside its heading in the sheet.
  for (const key of TRIGGERS.map((t) => t.key)) {
    const head = document.querySelector(`#nfl-filter-${key}-sheet > .section-head`);
    if (!head) continue;
    let pick = head.querySelector(':scope > .section-pick');
    if (!pick) {
      pick = el('span', 'section-pick');
      head.querySelector('h3').after(pick);
    }
    const on = changed.includes(key);
    pick.hidden = !on;
    pick.textContent = on ? info[key].value : '';
  }
}

/**
 * Chooses each changed-filter chip's wording by measuring: "Announcers: A, B" when it fits the chip,
 * otherwise "Announcers (2)" (the filter name and the pick count, no middle dot).
 */
function fitFilterChips() {
  if (!ui) return;
  for (const text of ui.filterChips.querySelectorAll('.chip-text')) {
    const { name, value, count } = text.dataset;
    text.replaceChildren(el('b', null, name), document.createTextNode(value));
    text.dataset.form = 'long';
    // A closed sheet has no width to measure; the next resize event decides.
    if (text.clientWidth > 0 && text.scrollWidth > text.clientWidth) {
      text.replaceChildren(el('b', null, name), document.createTextNode(` (${count})`));
      text.dataset.form = 'short';
    }
  }
}
