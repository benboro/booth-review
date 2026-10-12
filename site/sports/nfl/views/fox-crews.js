/**
 * NFL view 2: Fox crews (D-14).
 *
 * One season's booths as a dot chart: Lead, Fox #2, Fox #3, ... and Others
 * (pooled). Raw shows means with no whiskers; Adjusted shows the residual
 * against what the matchup predicts with +/-1.96 standard error whiskers and a
 * zero line. Seasons are never pooled: only the rows of state.fseason are
 * read. Names enter Plotly strings only through escapeHover; the tooltip,
 * captions and hidden table use createElement/textContent.
 */
import { foxRows } from '../state.js';
import { ACCENT, MUTED, PAGE_BG, DIVIDER, ZERO_LINE } from '../../../modules/palette.js';
import { showTextTooltip, hideTooltip } from '../../../modules/tooltip.js';
import { escapeHover, MINUS } from '../../../modules/format.js';

const CONFIG = {
  responsive: true,
  displayModeBar: false,
  displaylogo: false,
  scrollZoom: false,
  showLink: false,
  showSendToCloud: false,
  showEditInChartStudio: false,
};

const METRICS = [
  { key: 'margin', label: 'Final margin' },
  { key: 'excitement', label: 'GEI-style excitement' },
  { key: 'volatility', label: 'WP volatility' },
];

const METRIC_FIELDS = {
  margin: { raw: 'raw_mean_abs_margin', resid: 'adj_margin_resid', se: 'adj_margin_se' },
  excitement: { raw: 'raw_mean_excitement', resid: 'adj_excitement_resid', se: 'adj_excitement_se' },
  volatility: { raw: 'raw_mean_volatility', resid: 'adj_volatility_resid', se: 'adj_volatility_se' },
};

const AXIS_TITLES = {
  raw: {
    margin: 'Mean final margin (points)',
    excitement: 'Mean GEI-style excitement',
    volatility: 'Mean WP volatility',
  },
  adjusted: {
    margin: 'Final margin vs. expected for the matchup (points)',
    excitement: 'GEI-style excitement vs. expected for the matchup',
    volatility: 'WP volatility vs. expected for the matchup',
  },
};

const END_CAPTIONS = {
  margin: ['Closer than expected', 'Wider than expected'],
  excitement: ['Less exciting than expected', 'More exciting than expected'],
  volatility: ['Less volatile than expected', 'More volatile than expected'],
};

const VALUE_LINES = {
  raw: {
    margin: (x) => `Mean final margin: ${x} points`,
    excitement: (x) => `Mean GEI-style excitement: ${x}`,
    volatility: (x) => `Mean WP volatility: ${x}`,
  },
  adjusted: {
    margin: (x) => `Final margin vs. expected: ${x} points`,
    excitement: (x) => `GEI-style excitement vs. expected: ${x}`,
    volatility: (x) => `WP volatility vs. expected: ${x}`,
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
  controls: null,
  prev: null,
  next: null,
  select: null,
  values: null,
  metrics: null,
  chart: null,
  gd: null,
  note: null,
  noteTitle: null,
  captions: null,
  dataBody: null,
  drawn: false,
  bound: false,
};

// What the last render drew (also what the event handlers read).
let current = null; // { rows, env, theme, state, model, ... }

function theme(env) {
  return env.dark ? 'dark' : 'light';
}

function plural(n, one, many) {
  return `${n} ${n === 1 ? one : many}`;
}

function fmt(metric, x, signed) {
  const s = Math.abs(x).toFixed(metric === 'margin' ? 1 : 2);
  if (x < 0 && Number(s) !== 0) return MINUS + s;
  return signed && x > 0 && Number(s) !== 0 ? '+' + s : s;
}

function personName(model, idx) {
  return idx == null ? null : model.people[idx].name;
}

function boothNames(model, r) {
  if (r.group === 'others_pooled') return 'Others (pooled)';
  const pbp = personName(model, r.pbp_person);
  const analyst = personName(model, r.analyst_person);
  return [pbp, analyst].filter((n) => n != null).join(' / ');
}

function rowRole(r) {
  if (r.group === 'lead') return 'Lead';
  if (r.group === 'others_pooled') return null;
  return `Fox #${r.rank}`;
}

/** Plain label (no markup): 'Lead · pbp / analyst', 'Others (pooled)'. */
function rowLabel(model, r) {
  const role = rowRole(r);
  const base = role ? `${role} · ${boothNames(model, r)}` : 'Others (pooled)';
  return r.low_n ? `${base} (low n)` : base;
}

function rowKey(r) {
  return `${r.season}:${r.group}:${r.rank ?? ''}`;
}

function annotationText(r) {
  return `${plural(r.games, 'game', 'games')} · ${r.fill_in_games} fill-in`;
}

function selectedBoothKey(state) {
  const s = state.selection;
  return s && s.kind === 'booth' ? s.key : null;
}

function hasSelectedPerson(state, r) {
  if (!state.people.length) return false;
  const ids = new Set(state.people);
  const model = refs.ctx.model;
  return [r.pbp_person, r.analyst_person].some(
    (p) => p != null && model.people[p] && ids.has(model.people[p].id),
  );
}

/** Seasons the stepper may reach: Fox seasons inside the Seasons filter. */
function allowedSeasons(model, state) {
  const [lo, hi] = state.seasons;
  return model.foxSeasons.filter((s) => s >= lo && s <= hi);
}

let lastToggle = { key: null, at: 0 };

function toggleBooth(item) {
  const { ctx } = refs;
  // A touch tap reaches Plotly as touchend and again as the emulated mouseup.
  const now = Date.now();
  if (lastToggle.key === item.key && now - lastToggle.at < 500) return;
  lastToggle = { key: item.key, at: now };
  if (selectedBoothKey(ctx.getState()) === item.key) {
    ctx.clearSelection();
    return;
  }
  ctx.selectGames({
    kind: 'booth',
    key: item.key,
    label: item.label,
    games: item.row.gameList,
  });
}

function hoverLines(item) {
  const { state, model } = current;
  const r = item.row;
  const adjusted = state.adjusted;
  const lines = [
    { text: boothNames(model, r), kind: 'title' },
    { text: String(r.season), kind: 'body' },
  ];
  const fmtLine = VALUE_LINES[adjusted ? 'adjusted' : 'raw'][state.metric];
  lines.push({ text: item.x == null ? fmtLine('not available') : fmtLine(fmt(state.metric, item.x, adjusted)), kind: 'body' });
  if (adjusted) {
    if (item.se == null || item.x == null) {
      lines.push({ text: '±1.96 standard errors: not available', kind: 'body' });
    } else {
      const half = 1.96 * item.se;
      lines.push({
        text: `±1.96 standard errors: ${fmt(state.metric, item.x - half, false)} to ${fmt(state.metric, item.x + half, false)}`,
        kind: 'body',
      });
    }
  }
  lines.push({ text: annotationText(r), kind: 'body' });
  if (r.low_n) {
    lines.push({
      text: `Fewer than ${model.constants.low_n_threshold} games. Read with care.`,
      kind: 'body',
    });
  }
  lines.push({ text: 'Click to list games.', kind: 'hint' });
  return lines;
}

function bindEvents(gd) {
  if (refs.bound) return;
  refs.bound = true;
  gd.on('plotly_click', (ev) => {
    const k = ev.points && ev.points[0] ? ev.points[0].customdata : null;
    if (current && Number.isInteger(k) && current.items[k]) toggleBooth(current.items[k]);
  });
  gd.on('plotly_hover', (ev) => {
    const k = ev.points && ev.points[0] ? ev.points[0].customdata : null;
    if (!current || !Number.isInteger(k) || !current.items[k]) return;
    if (current.env.mobile || current.env.hoverNone) return;
    const e = ev.event || {};
    showTextTooltip(hoverLines(current.items[k]), {
      theme: theme(current.env),
      borderColor: ACCENT[theme(current.env)],
      clientX: e.clientX ?? 0,
      clientY: e.clientY ?? 0,
    });
  });
  gd.on('plotly_unhover', () => hideTooltip());
}

// ---- controls ----

function segmented(label, options, onPick) {
  const group = el('div', 'segmented');
  group.setAttribute('role', 'group');
  group.setAttribute('aria-label', label);
  const buttons = options.map((o) => {
    const b = el('button', null, o.label);
    b.type = 'button';
    b.dataset.value = o.key;
    b.addEventListener('click', () => onPick(o.key));
    return b;
  });
  group.append(...buttons);
  return group;
}

function setPressed(group, activeKey) {
  for (const b of group.querySelectorAll('button')) {
    b.setAttribute('aria-pressed', String(b.dataset.value === activeKey));
  }
}

function goSeason(season) {
  const { ctx } = refs;
  const patch = { fseason: season };
  if (selectedBoothKey(ctx.getState())) patch.selection = null;
  ctx.setState(patch);
}

function buildControls() {
  const { ctx } = refs;
  refs.controls.id = 'nfl-fox-controls';
  const stepper = el('div', 'nfl-stepper');
  refs.prev = el('button', null, '←');
  refs.prev.type = 'button';
  refs.prev.setAttribute('aria-label', 'Previous season');
  refs.select = el('select');
  refs.select.setAttribute('aria-label', 'Season');
  refs.next = el('button', null, '→');
  refs.next.type = 'button';
  refs.next.setAttribute('aria-label', 'Next season');
  stepper.append(refs.prev, refs.select, refs.next);
  const step = (dir) => {
    const list = allowedSeasons(ctx.model, ctx.getState());
    const at = list.indexOf(ctx.getState().fseason);
    // The list is newest first, so "previous season" is the next index.
    const to = list[at + dir];
    if (at >= 0 && to != null) goSeason(to);
  };
  refs.prev.addEventListener('click', () => step(1));
  refs.next.addEventListener('click', () => step(-1));
  refs.select.addEventListener('change', () => goSeason(Number(refs.select.value)));
  refs.values = segmented(
    'Values',
    [{ key: 'raw', label: 'Raw' }, { key: 'adjusted', label: 'Adjusted' }],
    (k) => ctx.setState({ adjusted: k === 'adjusted' }),
  );
  refs.metrics = segmented('Metric', METRICS, (k) => ctx.setState({ metric: k }));
  refs.metrics.classList.add('nfl-fox-metrics');
  refs.controls.append(stepper, refs.values, refs.metrics);
}

function renderControls(model, state, allowed) {
  const seasons = allowed.length ? allowed : [state.fseason];
  const want = seasons.map(String).join(',');
  if (refs.select.dataset.options !== want) {
    refs.select.replaceChildren(
      ...seasons.map((s) => {
        const o = el('option', null, String(s));
        o.value = String(s);
        return o;
      }),
    );
    refs.select.dataset.options = want;
  }
  refs.select.value = String(state.fseason);
  const at = allowed.indexOf(state.fseason);
  refs.prev.disabled = at < 0 || at >= allowed.length - 1;
  refs.next.disabled = at <= 0;
  setPressed(refs.values, state.adjusted ? 'adjusted' : 'raw');
  setPressed(refs.metrics, state.metric);
}

// ---- captions, table, note ----

function link(text, href) {
  const a = el('a', null, text);
  a.href = href;
  a.rel = 'noopener noreferrer';
  return a;
}

function renderCaptions(model, state) {
  const { ctx, captions } = refs;
  const n = model.constants.low_n_threshold;
  const first = el('p');
  first.textContent = 'One season at a time. Seasons are not pooled.'
    + (state.adjusted ? ' Whiskers show ±1.96 standard errors.' : '');
  const second = el('p', null, state.adjusted
    ? ''
    : 'Raw means. No error bars. Use Adjusted to compare booths.');
  const lowN = el('p');
  lowN.append(
    document.createTextNode(`Hollow dots have fewer than ${n} games. `),
    link('About small samples', ctx.methodologyHref('nfl-low-n')),
    document.createTextNode('.'),
  );
  const links = el('p');
  links.append(
    link('How the booths are chosen', ctx.methodologyHref('nfl-fox-crews-and-the-lead-booth')),
    document.createTextNode(' · '),
    link('How the adjustment works', ctx.methodologyHref('nfl-the-spread-adjustment')),
  );
  const kids = [first];
  if (!state.adjusted) kids.push(second);
  kids.push(lowN, links);
  captions.replaceChildren(...kids);
}

function valueText(metric, x, adjusted) {
  return x == null ? 'n/a' : fmt(metric, x, adjusted);
}

function renderDataTable(items, state) {
  const { dataBody } = refs;
  dataBody.replaceChildren();
  for (const it of items) {
    const tr = el('tr');
    const th = el('th');
    th.scope = 'row';
    const btn = el('button', null, it.label);
    btn.type = 'button';
    btn.setAttribute('aria-label', `Select ${it.label}`);
    btn.addEventListener('click', () => toggleBooth(it));
    th.appendChild(btn);
    tr.append(
      th,
      el('td', null, String(it.row.games)),
      el('td', null, String(it.row.fill_in_games)),
      el('td', null, valueText(state.metric, it.x, state.adjusted)),
      el('td', null, it.row.low_n ? 'yes' : 'no'),
    );
    dataBody.appendChild(tr);
  }
}

function setNote(title) {
  const { note, noteTitle, gd } = refs;
  if (title == null) {
    note.hidden = true;
    gd.hidden = false;
    return;
  }
  noteTitle.textContent = title;
  note.hidden = false;
  gd.hidden = true;
}

// ---- figure ----

function buildItems(model, state, rows) {
  const f = METRIC_FIELDS[state.metric];
  return rows.map((r) => {
    const x = state.adjusted ? r[f.resid] : r[f.raw];
    return {
      row: r,
      id: `${r.group}:${r.rank ?? ''}`,
      key: rowKey(r),
      label: rowLabel(model, r),
      x: x == null ? null : x,
      se: state.adjusted ? (r[f.se] == null ? null : r[f.se]) : null,
      lowN: !!r.low_n,
    };
  });
}

function buildFigure(items, state, env, th, selectedKey) {
  const bg = PAGE_BG[th];
  const adjusted = state.adjusted;
  const ring = items.map((it) => it.key === selectedKey || hasSelectedPerson(state, it.row));
  const ids = items.map((it) => it.id);
  const size = env.mobile ? 14 : 11;
  const err = items.map((it) => (adjusted && it.se != null ? 1.96 * it.se : 0));

  const main = {
    type: 'scatter',
    mode: 'markers',
    name: 'Booths',
    x: items.map((it) => it.x),
    y: ids,
    customdata: items.map((_, k) => k),
    hoverinfo: 'none',
    opacity: 1,
    marker: {
      symbol: 'circle',
      size,
      color: items.map((it) => (it.lowN ? 'rgba(0,0,0,0)' : ACCENT[th])),
      opacity: items.map((it) => (it.lowN ? 0.5 : 1)),
      line: {
        color: ACCENT[th],
        width: items.map((it) => (it.lowN ? 2 : 0)),
      },
    },
  };
  if (adjusted) {
    main.error_x = {
      type: 'data',
      array: err,
      visible: true,
      color: MUTED[th],
      thickness: 1.5,
      width: 6,
    };
  }
  const underlay = {
    type: 'scatter',
    mode: 'markers',
    name: 'Selected',
    x: items.map((it, k) => (ring[k] ? it.x : null)),
    y: ids,
    hoverinfo: 'skip',
    marker: {
      symbol: 'circle-open',
      size: size + 9,
      color: ACCENT[th],
      line: { color: ACCENT[th], width: 1.5 },
    },
  };

  // x range: include zero (Adjusted) and the whiskers.
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
  if (adjusted) {
    lo = Math.min(lo, 0);
    hi = Math.max(hi, 0);
  } else {
    lo = Math.min(lo, 0);
  }
  const pad = (hi - lo || 1) * 0.08;
  const range = [lo === 0 && !adjusted ? 0 : lo - pad, hi + pad];

  const annotations = [];
  const titleText = AXIS_TITLES[adjusted ? 'adjusted' : 'raw'][state.metric];
  if (adjusted) {
    const [left, right] = END_CAPTIONS[state.metric];
    const cap = { xref: 'paper', yref: 'paper', y: 0, yshift: env.mobile ? -66 : -58, yanchor: 'top', showarrow: false, font: { size: env.mobile ? 12 : 14, color: MUTED[th] } };
    annotations.push({ ...cap, x: 0, xanchor: 'left', text: left });
    annotations.push({ ...cap, x: 1, xanchor: 'right', yshift: env.mobile ? -84 : -58, text: right });
  }
  if (!env.mobile) {
    items.forEach((it) => {
      annotations.push({
        xref: 'paper', x: 1, xanchor: 'left', xshift: 12, yref: 'y', y: it.id,
        showarrow: false, text: annotationText(it.row), font: { size: 14, color: MUTED[th] },
      });
    });
  }
  const ticktext = items.map((it) => {
    const role = rowRole(it.row);
    const suffix = it.lowN ? ' (low n)' : '';
    if (!env.mobile) return escapeHover(it.label);
    const names = boothNames(current.model, it.row);
    const first = role ? `${role}` : 'Others (pooled)';
    const second = role ? escapeHover(names).replace(' / ', '<br>') + suffix : '';
    return [escapeHover(first) + (role ? '' : suffix), second, annotationText(it.row)]
      .filter((s) => s !== '')
      .join('<br>');
  });

  const font = { family: getComputedStyle(document.body).fontFamily, size: 14, color: ACCENT[th] };
  const pitch = env.mobile ? 88 : 44;
  const layout = {
    paper_bgcolor: bg,
    plot_bgcolor: bg,
    font,
    showlegend: false,
    hovermode: 'closest',
    clickmode: 'event',
    dragmode: false,
    height: items.length * pitch + (adjusted ? 130 : 96) + (env.mobile ? 40 : 0),
    margin: { l: env.mobile ? 150 : 280, r: env.mobile ? 16 : 120, t: 8, b: (adjusted ? 100 : 56) + (env.mobile ? 40 : 0) },
    annotations,
    shapes: adjusted
      ? [{ type: 'line', xref: 'x', yref: 'paper', x0: 0, x1: 0, y0: 0, y1: 1, line: { color: ZERO_LINE[th], width: 1.5 } }]
      : [],
    xaxis: {
      title: { text: env.mobile ? titleText.replace(' vs. ', '<br>vs. ') : titleText, standoff: 4, font: { size: env.mobile ? 12 : 14 } },
      range,
      gridcolor: DIVIDER[th],
      tickfont: { color: MUTED[th] },
      zeroline: false,
      fixedrange: true,
    },
    yaxis: {
      type: 'category',
      categoryorder: 'array',
      categoryarray: ids,
      tickmode: 'array',
      tickvals: ids,
      ticktext,
      autorange: 'reversed',
      showgrid: false,
      zeroline: false,
      fixedrange: true,
    },
  };
  return { traces: [underlay, main], layout, ring };
}

// ---- contract ----

export function mount(container, ctx) {
  refs.ctx = ctx;
  const legend = el('div', 'nfl-legend-row');
  refs.controls = el('div', 'nfl-view-controls');
  buildControls();
  refs.chart = el('div', 'nfl-chart');
  refs.gd = el('div');
  refs.note = el('div', 'season-empty-note');
  refs.note.setAttribute('role', 'status');
  refs.noteTitle = el('p', 'season-empty-title');
  refs.note.append(refs.noteTitle, el('p', 'season-empty-hint', 'Pick another season with the stepper.'));
  refs.chart.append(refs.gd, refs.note);
  refs.captions = el('div', 'nfl-captions');
  const dataWrap = el('div', 'visually-hidden');
  const dataTable = el('table');
  dataTable.appendChild(el('caption', null, 'Fox crews'));
  const thead = el('thead');
  const hr = el('tr');
  for (const h of ['Booth', 'Games', 'Fill-ins', 'Value', 'Low n']) {
    const th = el('th', null, h);
    th.scope = 'col';
    hr.appendChild(th);
  }
  thead.appendChild(hr);
  refs.dataBody = el('tbody');
  dataTable.append(thead, refs.dataBody);
  dataWrap.appendChild(dataTable);
  container.append(legend, refs.controls, refs.chart, refs.captions, dataWrap);
}

export function render(ctx) {
  const model = ctx.model;
  const state = ctx.getState();
  const env = ctx.env();
  const th = theme(env);
  hideTooltip();

  // Seasons narrows the stepper: move a season that fell outside the range.
  const allowed = allowedSeasons(model, state);
  if (allowed.length && !allowed.includes(state.fseason)) {
    const near = allowed.reduce((a, b) => (Math.abs(b - state.fseason) < Math.abs(a - state.fseason) ? b : a));
    goSeason(near);
    return;
  }

  renderControls(model, state, allowed);
  renderCaptions(model, state);
  const rows = allowed.length ? foxRows(model, state) : [];
  const items = buildItems(model, state, rows);
  current = { items, rows, env, theme: th, state, model };
  renderDataTable(items, state);

  // A selected booth belongs to one season: drop it when it no longer matches.
  const sel = selectedBoothKey(state);
  if (sel && !items.some((it) => it.key === sel)) {
    ctx.clearSelection();
    return;
  }

  if (!items.length) {
    setNote(`No Fox booth data for ${state.fseason}.`);
    refs.drawn = false;
    current.fig = null;
    return;
  }
  setNote(null);
  const fig = buildFigure(items, state, env, th, sel);
  current.ring = fig.ring;
  refs.drawn = true;
  window.Plotly.react(refs.gd, fig.traces, fig.layout, CONFIG);
  bindEvents(refs.gd);
}

export function resize() {
  if (refs.drawn && refs.gd && window.Plotly && refs.gd.data) window.Plotly.Plots.resize(refs.gd);
}

export function testModel() {
  if (!current || !refs.drawn) {
    const s = refs.ctx ? refs.ctx.getState() : null;
    return {
      view: 'fox',
      drawn: false,
      season: s ? s.fseason : null,
      adjusted: s ? s.adjusted : false,
      metric: s ? s.metric : 'margin',
      rows: [],
      axisTitle: null,
      hasWhiskers: false,
    };
  }
  const { state, items } = current;
  return {
    view: 'fox',
    drawn: true,
    season: state.fseason,
    adjusted: state.adjusted,
    metric: state.metric,
    rows: items.map((it, k) => ({
      key: it.key,
      label: it.label,
      x: it.x,
      err: state.adjusted && it.se != null ? 1.96 * it.se : 0,
      lowN: it.lowN,
      ring: current.ring[k],
      games: it.row.games,
      fillIn: it.row.fill_in_games,
    })),
    axisTitle: AXIS_TITLES[state.adjusted ? 'adjusted' : 'raw'][state.metric],
    hasWhiskers: state.adjusted,
  };
}
