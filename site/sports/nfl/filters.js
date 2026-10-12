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
 * `chipsHost` is accepted for the documented signature; the people chips are
 * rendered by index.js's selection bar, which already owns `#nfl-chips`.
 */
import { CATEGORY_OPTIONS, activeFilterCount, defaultNflState } from './state.js';

const TRIGGERS = [
  { key: 'announcers', label: 'Announcers' },
  { key: 'seasons', label: 'Seasons' },
  { key: 'category', label: 'Category' },
  { key: 'team', label: 'Team' },
];

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

let toolbarEl = null;
let layer = null;
let ui = null; // { clear, filtersButton, triggers: Map, sheet, popovers: Map }
let built = false; // sections need the loaded model
let updaters = [];
let mobileMql = null;

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
  input.setAttribute('aria-expanded', 'true');
  input.setAttribute('aria-autocomplete', 'list');
  input.setAttribute('aria-controls', `nfl-person-results-${sfx}`);
  input.placeholder = 'Search announcers — try "Joe Buck"';
  input.autocomplete = 'off';
  const list = el('ul', 'nfl-people-list');
  list.id = `nfl-person-results-${sfx}`;
  list.setAttribute('role', 'listbox');
  list.setAttribute('aria-multiselectable', 'true');
  list.setAttribute('aria-label', 'Announcers');
  const empty = el('p', 'helper', 'No announcers match.');
  empty.hidden = true;

  const people = [...model.people].sort((a, b) => a.name.localeCompare(b.name));
  const rows = new Map();
  const toggle = (id) => {
    const cur = ctx.getState().people;
    ctx.setState({ people: cur.includes(id) ? cur.filter((p) => p !== id) : [...cur, id] });
  };
  for (const p of people) {
    const li = el('li');
    li.setAttribute('role', 'option');
    li.tabIndex = 0;
    li.dataset.person = p.id;
    const box = el('span', 'option-check');
    box.setAttribute('aria-hidden', 'true');
    li.append(box, el('span', 'option-name', p.name));
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
  }
  input.addEventListener('input', filterRows);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') {
      const first = [...list.children].find((li) => !li.hidden);
      if (first) {
        e.preventDefault();
        first.focus();
      }
    }
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

// ---- init / render ----

function clearAll(ctx) {
  const d = defaultNflState(ctx.model);
  ctx.setState({ seasons: [...d.seasons], teams: [], people: [], cats: [] });
}

function buildShell(ctx) {
  const clear = el('button', null, 'Clear all filters');
  clear.type = 'button';
  clear.id = 'nfl-clear-filters';
  clear.addEventListener('click', () => {
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
  const nodes = [clear, filtersButton];
  for (const t of TRIGGERS) {
    const btn = el('button', 'filter-trigger desktop-only', t.label);
    btn.type = 'button';
    btn.id = `nfl-trigger-${t.key}`;
    btn.setAttribute('popovertarget', `nfl-pop-${t.key}`);
    btn.setAttribute('aria-haspopup', 'dialog');
    btn.setAttribute('aria-expanded', 'false');
    triggers.set(t.key, btn);
    nodes.push(btn);

    const pop = el('div', 'filter-popover nfl-filter-popover');
    pop.id = `nfl-pop-${t.key}`;
    pop.setAttribute('popover', 'auto');
    pop.setAttribute('role', 'dialog');
    pop.setAttribute('aria-label', t.label);
    pop.addEventListener('beforetoggle', (e) => {
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
  // Spacer cells keep the grid's row count equal to the CFB toolbar's, so
  // switching sport never moves the chart (SITE-20). Hidden from every user.
  for (let k = 0; k < 6; k++) {
    const spacer = el('span', 'nfl-toolbar-spacer');
    spacer.setAttribute('aria-hidden', 'true');
    nodes.push(spacer);
  }
  toolbarEl.append(...nodes);

  const sheet = el('div', 'filters-sheet nfl-filters-sheet');
  sheet.id = 'nfl-filters-sheet';
  sheet.setAttribute('popover', 'auto');
  sheet.setAttribute('role', 'dialog');
  sheet.setAttribute('aria-labelledby', 'nfl-filters-sheet-title');
  const header = el('div', 'sheet-header');
  const title = el('h2', null, 'Filters');
  title.id = 'nfl-filters-sheet-title';
  const clearSlot = el('div', 'sheet-clear-slot');
  const sheetClear = el('button', 'nfl-sheet-clear', 'Clear');
  sheetClear.type = 'button';
  sheetClear.addEventListener('click', () => {
    if (ctx.model) clearAll(ctx);
  });
  clearSlot.appendChild(sheetClear);
  header.append(title, clearSlot);
  const body = el('div', 'sheet-body');
  const footer = el('div', 'sheet-footer');
  const show = el('button', null, 'Show results');
  show.type = 'button';
  show.id = 'nfl-filters-show-results';
  show.addEventListener('click', () => {
    if (sheet.matches(':popover-open')) sheet.hidePopover();
  });
  footer.appendChild(show);
  sheet.append(header, body, footer);
  sheet.addEventListener('toggle', (e) => {
    filtersButton.setAttribute('aria-expanded', e.newState === 'open' ? 'true' : 'false');
  });
  layer.appendChild(sheet);

  ui = { clear, filtersButton, triggers, popovers, sheet, sheetBody: body };
  for (const btn of [filtersButton, ...triggers.values()]) {
    btn.disabled = true;
  }
}

function buildSections(ctx) {
  for (const t of TRIGGERS) {
    const popSection = BUILDERS[t.key](ctx, 'pop');
    ui.popovers.get(t.key).appendChild(popSection.root);
    const sheetSection = BUILDERS[t.key](ctx, 'sheet');
    ui.sheetBody.appendChild(sheetSection.root);
    updaters.push(popSection.update, sheetSection.update);
  }
  for (const btn of [ui.filtersButton, ...ui.triggers.values()]) btn.disabled = false;
  built = true;
}

/**
 * Build the toolbar controls once. The sections wait for the loaded model;
 * until then the triggers are disabled (also the load-error state).
 */
export function initNflFilters({ toolbar, sheetHost, ctx }) {
  if (ui) return;
  toolbarEl = toolbar;
  layer = sheetHost;
  buildShell(ctx);
  mobileMql = window.matchMedia('(max-width: 640px)');
  mobileMql.addEventListener('change', () => closeNflFilters());
  watchCellMin();
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
  const d = defaultNflState(ctx.model);
  const active = {
    announcers: state.people.length > 0,
    seasons: state.seasons[0] !== d.seasons[0] || state.seasons[1] !== d.seasons[1],
    category: state.cats.length > 0,
    team: state.teams.length > 0,
  };
  for (const [key, btn] of ui.triggers) btn.dataset.active = active[key] ? 'true' : 'false';
  const n = activeFilterCount(ctx.model, state);
  ui.filtersButton.textContent = n ? `Filters (${n})` : 'Filters';
}

// ---- toolbar cell width ----

/**
 * Sets --toolbar-cell-min on #nfl-toolbar: the wider of this toolbar's own
 * widest resting label and the CFB toolbar's value, so both grids wrap to the
 * same number of rows. The CFB value is written by toolbar-fit.js; this
 * follows it.
 */
function measureOwn() {
  const labels = [ui.clear, ...ui.triggers.values()];
  const box = el('div', 'toolbar-measure');
  box.setAttribute('aria-hidden', 'true');
  const probes = labels.map((btn) => {
    const cs = getComputedStyle(btn);
    const probe = el('span', null, btn.textContent + (btn === ui.clear ? '' : ' ▾'));
    for (const prop of ['fontFamily', 'fontSize', 'fontWeight', 'fontStyle', 'letterSpacing', 'paddingLeft', 'paddingRight']) {
      probe.style[prop] = cs[prop];
    }
    box.appendChild(probe);
    return probe;
  });
  document.body.appendChild(box);
  let widest = 0;
  for (const p of probes) widest = Math.max(widest, p.getBoundingClientRect().width);
  box.remove();
  return Math.ceil(widest);
}

function applyCellMin() {
  if (!toolbarEl) return;
  const cfb = document.getElementById('toolbar');
  const raw = cfb ? parseFloat(cfb.style.getPropertyValue('--toolbar-cell-min')) : NaN;
  const own = measureOwn();
  const px = Math.max(own, Number.isFinite(raw) ? raw : 0);
  if (px > 0) toolbarEl.style.setProperty('--toolbar-cell-min', `${px}px`);
}

function watchCellMin() {
  applyCellMin();
  const cfb = document.getElementById('toolbar');
  if (cfb) new MutationObserver(applyCellMin).observe(cfb, { attributes: true, attributeFilter: ['style'] });
  if (document.fonts) document.fonts.ready.then(applyCellMin);
  window.addEventListener('resize', applyCellMin, { passive: true });
}
