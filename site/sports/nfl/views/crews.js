/**
 * NFL Crews view (SPORT-08): one network, one season, booths ranked.
 *
 * Top to bottom: network picker and season stepper, a coverage line, the booth
 * table (the primary read), then a one-measure booth chart (Avg margin,
 * Excitement or Avg viewers; Raw by default, Adjusted as a secondary switch in
 * plain language). Seasons never pool. Styling reuses the CFB classes and chart
 * constants (D-18); the only NFL-only classes (.nfl-*) are layout hooks that
 * plan 11's stylesheet owns: the CFB stylesheet has no booth table or role-row.
 *
 * Names enter Plotly strings only through escapeHover; the tooltip, table,
 * captions and controls use createElement/textContent. The spread's value is
 * never shown; the word appears only in the Adjusted caption, Adjusted hover
 * lines and Adjusted axis titles (D-05).
 */
import { crewsNetworks, crewsSeasons, crewsRows, crewsCoverage, CREW_METRICS } from '../state.js';
import { crewStyle } from '../palette.js';
import { ACCENT, MUTED, PAGE_BG, DIVIDER, ZERO_LINE } from '../../../modules/palette.js';
import { frameConfig, frameLayout, referenceLine } from '../../../modules/chart-frame.js';
import { MARGIN, TICK_FONT_PX, DOT_OPACITY } from '../../../modules/chart.js';
import { makeRolePill, nameWithRoles, currentTheme } from '../../../modules/pill.js';
import { showTextTooltip, hideTooltip } from '../../../modules/tooltip.js';
import { escapeHover, MINUS, formatViewers } from '../../../modules/format.js';
import { mountViewTools } from '../tools.js';
import { attachScrollCue } from '../../../modules/scroll-cue.js';
import { DATA_TABLE_CLASS, rebuildKeepingFocus } from '../data-table.js';

const CONFIG = frameConfig({ zoomable: false });

const DASH = '—';
const SEGMENT_MAX = 6; // more networks than this use the popover picker
const BASE_SIZE = 9;
const PICKED_SIZE = 10;

const METRICS = {
  margin: {
    label: 'Avg margin',
    raw: 'raw_mean_abs_margin',
    resid: 'adj_margin_resid',
    se: 'adj_margin_se',
    rawTitle: 'Avg final margin (points)',
    adjTitle: 'Final margin vs. what the spread predicted (points)',
  },
  excitement: {
    label: 'Excitement',
    raw: 'raw_mean_excitement',
    resid: 'adj_excitement_resid',
    se: 'adj_excitement_se',
    rawTitle: 'Excitement',
    adjTitle: 'Excitement vs. what the spread predicted',
  },
  viewers: {
    label: 'Avg viewers',
    raw: 'raw_mean_viewers',
    resid: null,
    se: null,
    rawTitle: 'Avg viewers',
    adjTitle: null,
  },
};

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

const refs = {
  ctx: null,
  root: null,
  networkHost: null,
  networkKey: null,
  trigger: null,
  popover: null,
  listbox: null,
  prev: null,
  next: null,
  seasonValue: null,
  coverage: null,
  tableWrap: null,
  tableCaption: null,
  tableHead: null,
  tableBody: null,
  publishedNote: null,
  viewersNote: null,
  note: null,
  noteTitle: null,
  noteHint: null,
  chartControls: null,
  measure: null,
  values: null,
  chart: null,
  gd: null,
  captions: null,
  dataBody: null,
  dataMeasure: null,
  drawn: false,
  bound: false,
};

// What the last render drew (also what the event handlers read).
let current = null;

function theme() {
  return currentTheme();
}

function boothKey(model, group, r) {
  return `${group.id}:${model.people[r.pbp_person].id}`;
}

function personName(model, idx) {
  return idx == null ? null : model.people[idx].name;
}

/** 'Lead' for a known rank 1, '#n' otherwise; a games-ranked season never says Lead (D-23). */
function rankLabel(r) {
  return r.rank === 1 && r.rank_source !== 'games' ? 'Lead' : `#${r.rank}`;
}

function boothNames(model, r) {
  return [personName(model, r.pbp_person), personName(model, r.analyst_person)]
    .filter((n) => n != null)
    .join(' / ');
}

function fixed(x, digits) {
  if (x == null) return DASH;
  const s = Math.abs(x).toFixed(digits);
  return x < 0 && Number(s) !== 0 ? MINUS + s : s;
}

function viewersShort(x) {
  return `${(x / 1e6).toFixed(1)}M`;
}

function ratedGamesText(n) {
  return `${n} rated ${n === 1 ? 'game' : 'games'}`;
}

const VIEWERS_SCOPE_NOTE =
  'Avg viewers counts rated games only; unrated games are left out. Some figures are window-level: '
  + 'AGOTW and CBS late national figures cover every game in that Sunday window.';

function selectedBoothKey(state) {
  const s = state.selection;
  return s && s.kind === 'booth' ? s.key : null;
}

// ---- selection ----

let lastToggle = { key: null, at: 0 };

function toggleBooth(item, fromChart = false) {
  const { ctx } = refs;
  // A touch tap reaches Plotly as touchend and again as the emulated mouseup.
  if (fromChart) {
    const now = Date.now();
    if (lastToggle.key === item.key && now - lastToggle.at < 500) return;
    lastToggle = { key: item.key, at: now };
  }
  if (selectedBoothKey(ctx.getState()) === item.key) {
    ctx.clearSelection();
    return;
  }
  ctx.selectGames({
    kind: 'booth',
    key: item.key,
    booth: item.key,
    label: `${item.rankLabel} · ${item.names}, ${current.season}`,
    games: item.row.gameList,
  });
}

// ---- network picker ----

function placePopover(pop, trigger) {
  const r = trigger.getBoundingClientRect();
  const margin = 8;
  const width = Math.min(pop.offsetWidth || 240, window.innerWidth - 2 * margin);
  const left = Math.max(margin, Math.min(r.left, window.innerWidth - width - margin));
  pop.style.left = `${left}px`;
  pop.style.top = `${r.bottom + 4}px`;
}

function pickNetwork(id) {
  refs.ctx.setState({ network: id, selection: null });
}

function optionButtons() {
  return [...refs.listbox.querySelectorAll('li[role=option]')];
}

function focusOption(li) {
  for (const o of optionButtons()) o.tabIndex = o === li ? 0 : -1;
  li.focus();
}

function buildPopover() {
  const pop = el('div', 'filter-popover nfl-crews-popover');
  pop.id = 'nfl-crews-network-pop';
  pop.setAttribute('popover', 'auto');
  pop.setAttribute('role', 'dialog');
  pop.setAttribute('aria-label', 'Network');
  const list = el('ul', 'nfl-crews-listbox');
  list.setAttribute('role', 'listbox');
  list.setAttribute('aria-label', 'Network');
  list.addEventListener('keydown', (e) => {
    const li = e.target.closest('li[role=option]');
    if (!li) return;
    const all = optionButtons();
    const at = all.indexOf(li);
    if (e.key === 'ArrowDown' && all[at + 1]) focusOption(all[at + 1]);
    else if (e.key === 'ArrowUp' && all[at - 1]) focusOption(all[at - 1]);
    else if (e.key === 'Home') focusOption(all[0]);
    else if (e.key === 'End') focusOption(all[all.length - 1]);
    else if (e.key === 'Enter' || e.key === ' ') pickFrom(li);
    else if (e.key === 'Escape') closePopover();
    else return;
    e.preventDefault();
  });
  list.addEventListener('click', (e) => {
    const li = e.target.closest('li[role=option]');
    if (li) pickFrom(li);
  });
  pop.appendChild(list);
  pop.addEventListener('beforetoggle', (e) => {
    if (e.newState === 'open') {
      placePopover(pop, refs.trigger);
      requestAnimationFrame(() => placePopover(pop, refs.trigger));
    }
  });
  pop.addEventListener('toggle', (e) => {
    refs.trigger.setAttribute('aria-expanded', e.newState === 'open' ? 'true' : 'false');
    if (e.newState === 'open') {
      const sel = optionButtons().find((o) => o.getAttribute('aria-selected') === 'true') ?? optionButtons()[0];
      if (sel) focusOption(sel);
    }
  });
  refs.popover = pop;
  refs.listbox = list;
}

function closePopover() {
  if (refs.popover.matches(':popover-open')) refs.popover.hidePopover();
  refs.trigger.focus();
}

function pickFrom(li) {
  const id = li.dataset.network;
  closePopover();
  pickNetwork(id);
}

function renderNetworkPicker(networks, state) {
  const key = networks.map((n) => n.id).join(',');
  const picked = networks.find((n) => n.id === state.network);
  if (networks.length <= SEGMENT_MAX) {
    if (refs.networkKey !== `s:${key}`) {
      const group = el('div', 'segmented');
      group.setAttribute('role', 'group');
      group.setAttribute('aria-label', 'Network');
      for (const n of networks) {
        const b = el('button', null, n.name);
        b.type = 'button';
        b.dataset.network = n.id;
        b.addEventListener('click', () => pickNetwork(n.id));
        group.appendChild(b);
      }
      refs.networkHost.replaceChildren(group);
      refs.networkKey = `s:${key}`;
    }
    for (const b of refs.networkHost.querySelectorAll('button')) {
      b.setAttribute('aria-pressed', String(b.dataset.network === state.network));
    }
    return;
  }
  if (refs.networkKey !== `p:${key}`) {
    refs.networkHost.replaceChildren(refs.trigger);
    refs.listbox.replaceChildren(
      ...networks.map((n) => {
        const li = el('li', null, n.name);
        li.setAttribute('role', 'option');
        li.dataset.network = n.id;
        return li;
      }),
    );
    refs.networkKey = `p:${key}`;
  }
  refs.trigger.textContent = picked ? picked.name : 'Network';
  for (const li of optionButtons()) {
    const on = li.dataset.network === state.network;
    li.setAttribute('aria-selected', String(on));
    li.tabIndex = on ? 0 : -1;
  }
}

// ---- controls ----

function segmented(label, options, onPick) {
  const group = el('div', 'segmented');
  group.setAttribute('role', 'group');
  group.setAttribute('aria-label', label);
  for (const o of options) {
    const b = el('button');
    b.type = 'button';
    b.dataset.value = o.key;
    if (o.short) {
      b.setAttribute('aria-label', o.label);
      b.title = o.label;
      b.append(el('span', 'axis-long', o.label), el('span', 'axis-short', o.short));
    } else {
      b.textContent = o.label;
    }
    b.addEventListener('click', () => onPick(o.key));
    group.appendChild(b);
  }
  return group;
}

function setPressed(group, activeKey) {
  for (const b of group.querySelectorAll('button')) {
    b.setAttribute('aria-pressed', String(b.dataset.value === activeKey));
  }
}

function goSeason(season) {
  refs.ctx.setState({ cseason: season, selection: null });
}

function buildControls() {
  const { ctx } = refs;
  const row = el('div', 'chart-controls nfl-crews-controls');

  const netGroup = el('div', 'axis-group');
  const netCaption = el('span', 'axis-caption', 'Network');
  netCaption.setAttribute('aria-hidden', 'true');
  refs.networkHost = el('div', 'nfl-crews-network');
  refs.trigger = el('button', 'filter-trigger', 'Network');
  refs.trigger.type = 'button';
  refs.trigger.setAttribute('aria-haspopup', 'dialog');
  refs.trigger.setAttribute('aria-expanded', 'false');
  refs.trigger.setAttribute('popovertarget', 'nfl-crews-network-pop');
  buildPopover();
  netGroup.append(netCaption, refs.networkHost, refs.popover);

  const seasonGroup = el('div', 'axis-group');
  const seasonCaption = el('span', 'axis-caption', 'Season');
  seasonCaption.setAttribute('aria-hidden', 'true');
  const stepper = el('div', 'segmented season-stepper');
  refs.prev = el('button', null, '‹');
  refs.prev.type = 'button';
  refs.prev.setAttribute('aria-label', 'Previous season');
  refs.seasonValue = el('span', 'season-value');
  refs.next = el('button', null, '›');
  refs.next.type = 'button';
  refs.next.setAttribute('aria-label', 'Next season');
  stepper.append(refs.prev, refs.seasonValue, refs.next);
  const step = (dir) => {
    const state = ctx.getState();
    const group = crewsNetworks(ctx.model, state).find((n) => n.id === state.network);
    if (!group) return;
    const list = crewsSeasons(ctx.model, group.index);
    const at = list.indexOf(state.cseason);
    // The list is newest first, so "previous season" is the next index.
    const to = list[at + dir];
    if (at >= 0 && to != null) goSeason(to);
  };
  refs.prev.addEventListener('click', () => step(1));
  refs.next.addEventListener('click', () => step(-1));
  seasonGroup.append(seasonCaption, stepper);

  row.append(netGroup, seasonGroup);

  const chartRow = el('div', 'chart-controls nfl-crews-chart-controls');
  refs.measure = segmented(
    'Measure',
    [
      { key: 'margin', label: 'Avg margin' },
      { key: 'excitement', label: 'Excitement', short: 'Excite.' },
      { key: 'viewers', label: 'Avg viewers' },
    ],
    (k) => ctx.setState({ metric: k }),
  );
  refs.values = segmented(
    'Raw or adjusted',
    [{ key: 'raw', label: 'Raw' }, { key: 'adjusted', label: 'Adjusted' }],
    (k) => ctx.setState({ adjusted: k === 'adjusted' }),
  );
  chartRow.append(refs.measure, refs.values);
  refs.chartControls = chartRow;
  return [row, chartRow];
}

// ---- table ----

function numCell(text) {
  const td = el('td', 'num', text);
  return td;
}

function renderBoothTable(items, group, state, season, anyPublished) {
  const hasFlagship = !!group.flagship;
  refs.tableCaption.textContent = `Booths for ${group.name}, ${season}`;
  const heads = ['Booth', 'Games'];
  if (hasFlagship) heads.push(group.flagship);
  heads.push('Avg viewers', 'Avg margin', 'Excitement');
  refs.tableHead.replaceChildren(
    ...heads.map((h, k) => {
      const th = el('th', k === 0 ? 'booth-col' : null, h);
      th.scope = 'col';
      if (h === 'Avg viewers') {
        const mark = el('span', 'footnote-mark', '*');
        mark.title = VIEWERS_SCOPE_NOTE;
        th.append(mark);
      }
      return th;
    }),
  );
  const picked = new Set(state.booths);
  const sel = selectedBoothKey(state);
  rebuildKeepingFocus(refs.tableBody, () => {
    refs.tableBody.replaceChildren();
    for (const it of items) {
      const r = it.row;
      const tr = el('tr');
      if (r.low_n) tr.dataset.lowN = 'true';
      if (picked.has(it.key)) tr.dataset.picked = 'true';
      const th = el('th', 'booth-col');
      th.scope = 'row';
      const btn = el('button', 'booth-row-btn');
      btn.type = 'button';
      btn.dataset.booth = it.key;
      btn.dataset.key = it.key;
      btn.setAttribute('aria-pressed', String(sel === it.key));
      btn.append(el('span', 'booth-rank', it.rankLabel));
      // The names sit in one `.booth-names` group: inline on desktop, stacked (pbp, analyst,
      // then the low-n tag) in the narrow phone column; see the 480px rules in style.css.
      const names = el('span', 'booth-names');
      names.append(nameWithRoles(el('span', 'booth-name', personName(current.model, r.pbp_person)), makeRolePill('pbp')));
      if (r.analyst_person != null) {
        names.append(
          el('span', 'booth-sep', ' / '),
          nameWithRoles(el('span', 'booth-name', personName(current.model, r.analyst_person)), makeRolePill('analyst')),
        );
      }
      if (r.low_n) {
        const tag = el('span', 'low-n-tag', 'low n');
        tag.title = 'Few games, so treat with care.';
        names.append(tag);
      }
      btn.append(' ', names);
      btn.addEventListener('click', () => toggleBooth(it));
      th.appendChild(btn);
      tr.append(th, numCell(String(r.games)));
      if (hasFlagship) tr.append(numCell(String(r.flagship_games)));
      const viewersTd = numCell(r.raw_mean_viewers == null ? DASH : formatViewers(Math.round(r.raw_mean_viewers)));
      if (r.games > 0) viewersTd.append(el('span', 'rated-n', ratedGamesText(r.raw_n_viewers)));
      tr.append(
        viewersTd,
        numCell(fixed(r.raw_mean_abs_margin, 1)),
        numCell(fixed(r.raw_mean_excitement, 1)),
      );
      refs.tableBody.appendChild(tr);
    }
  });
  refs.publishedNote.hidden = !anyPublished;
}

// ---- captions ----

function link(text, href) {
  const a = el('a', null, text);
  a.href = href;
  a.rel = 'noopener noreferrer';
  return a;
}

function renderCaptions(state, adjusted) {
  const { ctx, captions } = refs;
  const kids = [];
  kids.push(
    el(
      'p',
      'caption',
      "Average for each booth's games this season. Each row in the table is one booth.",
    ),
  );
  if (adjusted) {
    kids.push(
      el(
        'p',
        'caption',
        "Adjusted: how far each booth's games ran from what the spread predicted, for example 1.4 pts closer. "
          + 'Whiskers show plus or minus 1.96 standard errors.',
      ),
    );
  }
  if (state.metric === 'excitement') {
    const p = el('p', 'caption');
    p.append(
      document.createTextNode("NFL excitement is GEI-style, built from win probability. It is not CFBD's excitementIndex; see "),
      link('methodology', ctx.methodologyHref('nfl-gei-style-excitement')),
      document.createTextNode('.'),
    );
    kids.push(p);
  }
  if (state.metric === 'viewers') {
    kids.push(el('p', 'caption nfl-viewers-note', VIEWERS_SCOPE_NOTE));
  }
  kids.push(el('p', 'caption', 'Hollow marks are booths with few games.'));
  captions.replaceChildren(...kids);
}

// ---- hover ----

function hoverLines(item) {
  const { metric, adjusted } = current;
  const r = item.row;
  const lines = [
    { text: item.names, kind: 'title' },
    { text: String(current.season), kind: 'body' },
    { text: `${r.games} ${r.games === 1 ? 'game' : 'games'}`, kind: 'body' },
  ];
  const x = item.x;
  if (!adjusted) {
    let text;
    if (x == null) text = `${METRICS[metric].label}: not available`;
    else if (metric === 'margin') text = `Avg margin: ${fixed(x, 1)} pts`;
    else if (metric === 'excitement') text = `Excitement: ${fixed(x, 1)} (GEI-style, not CFBD's index)`;
    else text = `Avg viewers: ${viewersShort(x)}`;
    lines.push({ text, kind: 'body' });
    if (metric === 'viewers') lines.push({ text: ratedGamesText(r.raw_n_viewers), kind: 'body' });
  } else {
    let text;
    if (x == null) {
      text = `${METRICS[metric].label}: not available`;
    } else {
      const abs = Math.abs(x).toFixed(1);
      if (Number(abs) === 0) {
        text = metric === 'margin' ? 'Final margin: as the spread predicted' : 'Excitement: as the spread predicted';
      } else if (metric === 'margin') {
        text = `${abs} pts ${x < 0 ? 'closer' : 'wider'} than the spread predicted`;
      } else {
        text = `${abs} ${x < 0 ? 'less' : 'more'} excitement than the spread predicted`;
      }
    }
    lines.push({ text, kind: 'body' });
    if (item.err == null || x == null) {
      lines.push({ text: '±1.96 standard errors: not available', kind: 'body' });
    } else {
      lines.push({
        text: `±1.96 standard errors: ${fixed(x - item.err, 1)} to ${fixed(x + item.err, 1)}`,
        kind: 'body',
      });
    }
  }
  if (r.low_n) lines.push({ text: 'low n: Few games, so treat with care.', kind: 'body' });
  lines.push({ text: 'Click to list games.', kind: 'hint' });
  return lines;
}

function bindEvents(gd) {
  if (refs.bound) return;
  refs.bound = true;
  gd.on('plotly_click', (ev) => {
    const k = ev.points && ev.points[0] ? ev.points[0].customdata : null;
    if (current && Number.isInteger(k) && current.items[k]) toggleBooth(current.items[k], true);
  });
  gd.on('plotly_hover', (ev) => {
    const k = ev.points && ev.points[0] ? ev.points[0].customdata : null;
    if (!current || !Number.isInteger(k) || !current.items[k]) return;
    if (current.env.mobile || current.env.hoverNone) return;
    const e = ev.event || {};
    showTextTooltip(hoverLines(current.items[k]), {
      theme: theme(),
      borderColor: ACCENT[theme()],
      clientX: e.clientX ?? 0,
      clientY: e.clientY ?? 0,
    });
  });
  gd.on('plotly_unhover', () => hideTooltip());
}

// ---- figure ----

function buildFigure(items, metric, adjusted, env, th, sel, picked) {
  const bg = PAGE_BG[th];
  const f = METRICS[metric];
  const size = env.mobile ? BASE_SIZE + 3 : BASE_SIZE;
  const ids = items.map((it) => `r${it.row.rank}`);
  const anyPicked = picked.size > 0;
  const err = items.map((it) => (adjusted && it.err != null ? it.err : 0));
  const isPicked = items.map((it) => picked.has(it.key));
  const styles = items.map((it, k) => crewStyle(k, th));

  const main = {
    type: 'scatter',
    mode: 'markers',
    name: 'Booths',
    x: items.map((it) => it.x),
    y: ids,
    customdata: items.map((_, k) => k),
    hoverinfo: 'none',
    marker: {
      symbol: items.map((it, k) => (it.row.low_n ? `${styles[k].symbol}-open` : styles[k].symbol)),
      size: items.map((_, k) => (isPicked[k] ? PICKED_SIZE : size)),
      color: styles.map((s) => s.color),
      opacity: items.map((it, k) => {
        if (anyPicked && !isPicked[k]) return DOT_OPACITY.inertUnderPerson;
        return it.row.low_n ? DOT_OPACITY.activeUnderPerson : DOT_OPACITY.active;
      }),
      line: { color: styles.map((s) => s.color), width: items.map((it) => (it.row.low_n ? 2 : 0)) },
    },
  };
  if (adjusted) {
    main.error_x = { type: 'data', array: err, visible: true, color: MUTED[th], thickness: 1.5, width: 6 };
  }
  const ring = items.map((it, k) => it.key === sel || isPicked[k]);
  const underlay = {
    type: 'scatter',
    mode: 'markers',
    name: 'Picked',
    x: items.map((it, k) => (ring[k] ? it.x : null)),
    y: ids,
    hoverinfo: 'skip',
    marker: { symbol: 'circle-open', size: size + 9, color: ACCENT[th], line: { color: ACCENT[th], width: 2 } },
  };

  let lo = Infinity;
  let hi = -Infinity;
  items.forEach((it, k) => {
    if (it.x == null) return;
    lo = Math.min(lo, it.x - err[k]);
    hi = Math.max(hi, it.x + err[k]);
  });
  if (!Number.isFinite(lo)) {
    lo = 0;
    hi = 1;
  }
  lo = Math.min(lo, 0);
  if (adjusted) hi = Math.max(hi, 0);
  const pad = (hi - lo || 1) * 0.08;
  const range = [lo === 0 && !adjusted ? 0 : lo - pad, hi + pad];

  const tick = env.mobile ? TICK_FONT_PX.mobile : TICK_FONT_PX.desktop;
  const titleText = adjusted ? f.adjTitle : f.rawTitle;
  const font = { size: tick, color: ACCENT[th] };
  const pitch = env.mobile ? 48 : 40;
  const layout = {
    font,
    hovermode: 'closest',
    clickmode: 'event',
    dragmode: false,
    height: items.length * pitch + MARGIN.t + MARGIN.b + 20,
    margin: { ...MARGIN, l: env.mobile ? 56 : MARGIN.l },
    shapes: adjusted
      ? [referenceLine({ xref: 'x', yref: 'paper', x0: 0, x1: 0, y0: 0, y1: 1 }, th)]
      : [],
    xaxis: {
      title: { text: escapeHover(titleText), standoff: 4, font: { size: tick } },
      range,
      gridcolor: DIVIDER[th],
      tickfont: { color: MUTED[th], size: tick },
      zeroline: false,
      fixedrange: true,
    },
    yaxis: {
      type: 'category',
      categoryorder: 'array',
      categoryarray: ids,
      tickmode: 'array',
      tickvals: ids,
      ticktext: items.map((it) => escapeHover(it.rankLabel)),
      tickfont: { color: MUTED[th], size: tick },
      autorange: 'reversed',
      showgrid: false,
      zeroline: false,
      fixedrange: true,
    },
  };
  return { traces: [underlay, main], layout: frameLayout(layout, { theme: th }) };
}

function renderDataTable(items, metric, adjusted) {
  refs.dataMeasure.textContent = adjusted ? `${METRICS[metric].label} (adjusted)` : METRICS[metric].label;
  rebuildKeepingFocus(refs.dataBody, () => {
    refs.dataBody.replaceChildren();
    for (const it of items) {
      const tr = el('tr');
      const th = el('th');
      th.scope = 'row';
      const b = el('button', null, `${it.rankLabel} · ${it.names}`);
      b.type = 'button';
      b.dataset.key = `d:${it.key}`;
      b.setAttribute('aria-label', `Select ${it.rankLabel} · ${it.names}`);
      b.addEventListener('click', () => toggleBooth(it));
      th.appendChild(b);
      tr.append(th, el('td', null, it.x == null ? 'n/a' : String(Math.round(it.x * 100) / 100)));
      refs.dataBody.appendChild(tr);
    }
  });
}

// ---- contract ----

export function mount(container, ctx) {
  refs.ctx = ctx;
  refs.root = container;
  const [controls, chartControls] = buildControls();

  refs.coverage = el('p', 'caption nfl-coverage');
  refs.coverage.setAttribute('role', 'status');

  refs.tableWrap = el('div', 'nfl-booth-table-wrap table-scroll');
  const table = el('table', 'games-table nfl-booth-table');
  refs.tableCaption = el('caption', 'visually-hidden');
  refs.tableHead = el('tr');
  const thead = el('thead');
  thead.appendChild(refs.tableHead);
  refs.tableBody = el('tbody');
  table.append(refs.tableCaption, thead, refs.tableBody);
  refs.viewersNote = el('p', 'caption nfl-viewers-footnote', `* ${VIEWERS_SCOPE_NOTE}`);
  refs.tableWrap.append(table, refs.viewersNote);
  attachScrollCue(refs.tableWrap, null);
  refs.publishedNote = el('p', 'caption nfl-published-note', 'Booth order from a published lineup.');
  refs.publishedNote.hidden = true;

  refs.note = el('div', 'season-empty-note');
  refs.note.setAttribute('role', 'status');
  refs.noteTitle = el('p', 'season-empty-title');
  refs.noteHint = el('p', 'season-empty-hint');
  refs.note.append(refs.noteTitle, refs.noteHint);

  refs.chart = el('div', 'nfl-chart');
  refs.gd = el('div');
  refs.chart.appendChild(refs.gd);
  refs.captions = el('div', 'nfl-captions');

  const dataWrap = el('div', DATA_TABLE_CLASS);
  const dataTable = el('table');
  dataTable.appendChild(el('caption', null, 'Crews'));
  const thead2 = el('thead');
  const hr = el('tr');
  refs.dataMeasure = el('th');
  refs.dataMeasure.scope = 'col';
  const boothTh = el('th', null, 'Booth');
  boothTh.scope = 'col';
  hr.append(boothTh, refs.dataMeasure);
  thead2.appendChild(hr);
  refs.dataBody = el('tbody');
  dataTable.append(thead2, refs.dataBody);
  dataWrap.appendChild(dataTable);

  container.append(
    controls,
    refs.coverage,
    refs.tableWrap,
    refs.publishedNote,
    refs.note,
    refs.chart,
    refs.captions,
    dataWrap,
  );
  // The mode control (measure, raw or adjusted) lives in the module header tools.
  mountViewTools(ctx, 'crews', [chartControls], container);
}

function nearest(list, season) {
  return list.reduce((a, b) => (Math.abs(b - season) < Math.abs(a - season) ? b : a));
}

export function render(ctx) {
  const { model } = ctx;
  const state = ctx.getState();
  const env = ctx.env();
  const th = theme();
  hideTooltip();

  const networks = crewsNetworks(model, state);
  if (!networks.length) {
    refs.coverage.textContent = '';
    refs.tableWrap.hidden = true;
    refs.chart.hidden = true;
    refs.chartControls.hidden = true;
    refs.noteTitle.textContent = 'No crews listed.';
    refs.noteHint.textContent = '506 does not list a crew for these games. Try another network or season.';
    refs.note.hidden = false;
    refs.drawn = false;
    current = { season: state.cseason, rows: [], items: [], networks, metric: state.metric, adjusted: false };
    return;
  }
  let group = networks.find((n) => n.id === state.network);
  if (!group) {
    ctx.setState({ network: networks[0].id, selection: null });
    return;
  }
  const seasons = crewsSeasons(model, group.index);
  if (seasons.length && !seasons.includes(state.cseason)) {
    ctx.setState({ cseason: nearest(seasons, state.cseason), selection: null });
    return;
  }
  group = networks.find((n) => n.id === state.network);

  renderNetworkPicker(networks, state);
  refs.seasonValue.textContent = String(state.cseason);
  const at = seasons.indexOf(state.cseason);
  const prevOff = at < 0 || at >= seasons.length - 1;
  const nextOff = at <= 0;
  refs.prev.disabled = prevOff;
  refs.prev.setAttribute('aria-disabled', String(prevOff));
  refs.next.disabled = nextOff;
  refs.next.setAttribute('aria-disabled', String(nextOff));

  const metric = CREW_METRICS.includes(state.metric) ? state.metric : 'margin';
  const adjusted = !!state.adjusted && metric !== 'viewers';
  setPressed(refs.measure, metric);
  setPressed(refs.values, adjusted ? 'adjusted' : 'raw');
  refs.values.classList.toggle('is-concealed', metric === 'viewers');

  const cov = crewsCoverage(model, state);
  refs.coverage.textContent = cov.total === 0
    ? `No ${group.name} games this season.`
    : `Crew listed for ${cov.withCrew} of ${cov.total} games.`
      + (cov.fromLineup > 0 ? ` ${cov.fromLineup} from published lineup.` : '');

  const rows = crewsRows(model, state);
  const f = METRICS[metric];
  const items = rows.map((r) => {
    const x = adjusted ? r[f.resid] : r[f.raw];
    const se = adjusted ? r[f.se] : null;
    return {
      row: r,
      key: boothKey(model, group, r),
      rankLabel: rankLabel(r),
      names: boothNames(model, r),
      x: x == null ? null : x,
      err: se == null ? null : 1.96 * se,
    };
  });
  current = {
    model, env, season: state.cseason, group, networks, seasons, cov, rows, items, metric, adjusted, state,
  };

  const sel = selectedBoothKey(state);
  if (sel && !items.some((it) => it.key === sel)) {
    ctx.clearSelection();
    return;
  }

  renderCaptions(state, adjusted);
  renderBoothTable(items, group, state, state.cseason, rows.some((r) => r.rank_source === 'published'));
  renderDataTable(items, metric, adjusted);

  if (!items.length) {
    refs.noteTitle.textContent = cov.total === 0 ? `No ${group.name} games this season.` : 'No crews listed.';
    refs.noteHint.textContent = cov.total === 0
      ? 'Pick another season.'
      : '506 does not list a crew for these games. Try another network or season.';
    refs.note.hidden = false;
    refs.tableWrap.hidden = true;
    refs.chart.hidden = true;
    refs.chartControls.hidden = true;
    refs.drawn = false;
    return;
  }
  refs.note.hidden = true;
  refs.tableWrap.hidden = false;
  refs.chart.hidden = false;
  refs.chartControls.hidden = false;

  const fig = buildFigure(items, metric, adjusted, env, th, sel, new Set(state.booths));
  refs.drawn = true;
  // The container follows the figure height (rows x pitch + margins), not the 520px CSS minimum,
  // so a short chart leaves no blank band below the plot.
  refs.chart.style.minHeight = `${fig.layout.height}px`;
  window.Plotly.react(refs.gd, fig.traces, fig.layout, CONFIG);
  bindEvents(refs.gd);
}

export function resize() {
  if (refs.drawn && refs.gd && window.Plotly && refs.gd.data) window.Plotly.Plots.resize(refs.gd);
}

export function testModel() {
  const s = refs.ctx ? refs.ctx.getState() : null;
  if (!current || !current.group) {
    return {
      view: 'crews',
      network: s ? s.network : null,
      season: s ? s.cseason : null,
      networks: [],
      seasons: [],
      flagshipHeader: null,
      coverage: { total: 0, withCrew: 0, fromLineup: 0 },
      rows: [],
      chart: { metric: s ? s.metric : 'margin', adjusted: false, points: [] },
      drawn: false,
    };
  }
  const picked = new Set(current.state.booths);
  return {
    view: 'crews',
    network: current.group.id,
    season: current.season,
    networks: current.networks.map((n) => ({ id: n.id, name: n.name })),
    seasons: current.seasons,
    flagshipHeader: current.group.flagship,
    coverage: current.cov,
    rows: current.items.map((it) => ({
      key: it.key,
      rankLabel: it.rankLabel,
      pbp: personName(current.model, it.row.pbp_person),
      analyst: personName(current.model, it.row.analyst_person),
      games: it.row.games,
      flagship: current.group.flagship ? it.row.flagship_games : null,
      viewers: it.row.raw_mean_viewers,
      ratedGames: it.row.raw_n_viewers,
      margin: it.row.raw_mean_abs_margin,
      excitement: it.row.raw_mean_excitement,
      lowN: !!it.row.low_n,
      rankSource: it.row.rank_source,
      picked: picked.has(it.key),
    })),
    chart: {
      metric: current.metric,
      adjusted: current.adjusted,
      points: current.items.map((it) => ({ key: it.key, x: it.x, err: current.adjusted && it.err != null ? it.err : 0 })),
    },
    drawn: refs.drawn,
  };
}
