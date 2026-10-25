/**
 * MLB Apple crews view (SPORT-06): one row per Apple booth, 2026, on the shared Crews table
 * (D-11).
 *
 * Stakes first, Excitement second (D-07). Raw by default, Adjusted as a secondary switch.
 * While Retrosheet 2026 is not loaded the quality cells read "pending Retrosheet 2026"
 * (D-06). A Stakes or Excitement cell whose sample is under the threshold carries an
 * `n < K` tag (D-14); rows are never faded. The Booth position column shows each booth's
 * standing in Apple's own order (Lead, #2, #3), never a rank by a measure. No p-values and
 * no "wins": captions say "tendency, not proof".
 *
 * Everything is built with createElement and textContent only.
 */
import { APPLE_SORT_SPEC, buildAppleRows, sortAppleRows } from '../apple-rows.js';
import { boothLabelOf, gameRow as mlbGameRow, CAUSE_COPY } from '../data.js';
import { windowTag } from '../table.js';
import { announce, createTableState, el, renderCrewsTable } from '../../../modules/crews-table.js';
import { formatAudienceTable } from '../../../modules/format.js';
import { networkMark } from '../../../modules/network.js';
import { hideTooltip, showTextTooltip } from '../../../modules/tooltip.js';

const DASH = '—';
const MINUS = '−';
export const PENDING_TEXT = 'pending Retrosheet 2026';
export const TOO_FEW_TEXT = 'too few games to call a difference';

const METRICS = [
  { key: 'stakes', label: 'Stakes', raw: 'raw_stakes', adj: 'adj_stakes', se: 'adj_stakes_se', lead: 'lead_minus_others_stakes' },
  { key: 'excitement', label: 'Excitement', raw: 'raw_excitement', adj: 'adj_excitement', se: 'adj_excitement_se', lead: 'lead_minus_others_excitement' },
];

const COLUMNS = [
  ['position', 'Booth position', false],
  ['booth', 'Booth', false],
  ['network', 'Network', false],
  ['games', 'Games', true],
  ['listed', 'Crew listed', true],
  ['stakes', 'Stakes', true],
  ['excitement', 'Excitement', true],
  ['prior', '2025 win % of both clubs', true],
];

const refs = {
  ctx: null,
  coverage: null,
  values: null,
  lead: null,
  rrNote: null,
  tableHost: null,
  captions: null,
};

/** This view's own table state, so CFB and NFL paging and open rows are never shared. */
const ts = createTableState();
/** The header sort; UI-only (never in the URL). null is Booth position. */
let csort = null;
let adjusted = false;
let current = null;

/** The builder's rank labels ('Lead', '#2', ..., 'Other') are already short. */
export function shortRank(label) {
  return String(label);
}

function fixed(x, digits, signed) {
  if (x == null || !Number.isFinite(x)) return DASH;
  const s = Math.abs(x).toFixed(digits);
  if (!signed) return x < 0 ? `${MINUS}${s}` : s;
  if (Number(s) === 0) return s;
  return `${x < 0 ? MINUS : '+'}${s}`;
}

function winPct(x) {
  return x == null || !Number.isFinite(x) ? DASH : `${(x * 100).toFixed(1)}%`;
}

function setPressed(group, activeKey) {
  for (const b of group.querySelectorAll('button')) {
    b.setAttribute('aria-pressed', String(b.dataset.value === activeKey));
  }
}

function numCell(text) {
  return el('td', 'num', text);
}

function threshold(model) {
  return model.constants.low_n_threshold;
}

function allPending(model) {
  return model.appleBooths.length > 0 && model.appleBooths.every((b) => b.quality_status === 'pending');
}

/** The builder withholds every lead-minus-others figure while any booth is pending. */
function anyPending(model) {
  return model.freshness.quality_pending || model.appleBooths.some((b) => b.quality_status === 'pending');
}

/** One Stakes or Excitement cell: the value, `±` its 1.96 SE (Adjusted), and `n < K` when flagged. */
function qualityCell(model, row, m, cell) {
  if (cell.pending) {
    const td = el('td', 'num mlb-pending', PENDING_TEXT);
    td.dataset.pending = 'true';
    return td;
  }
  const td = numCell(fixed(cell.value, 2, adjusted));
  const se = model.appleBooths[Number(row.rowKey)][m.se];
  if (adjusted && cell.value != null && se != null) {
    td.append(el('span', 'rated-n', `±${(1.96 * se).toFixed(2)}`));
  }
  if (cell.flagged) {
    const k = threshold(model);
    td.classList.add('is-low-n');
    const tag = el('span', 'crews-tag', `n < ${k}`);
    tag.title = `Fewer than ${k} games have this figure`;
    td.append(' ', tag);
  }
  return td;
}

function positionCell(row) {
  const td = el('td', 'crews-col-position');
  const key = row.rank === 'Lead' ? 'lead' : row.rank === '#2' ? '2' : null;
  if (key) {
    const pill = el('span', 'rank-pill', row.rank);
    pill.dataset.rank = key;
    td.append(pill);
  } else {
    td.textContent = row.rank;
  }
  return td;
}

const countText = (a) => `${a.name} (${a.n})`;

/** The `+N` control: a tooltip on hover or focus (desktop), a popover on tap (phone). It never picks the row. */
function moreNames(rest) {
  const btn = el('button', 'more-names', `+${rest.length}`);
  btn.type = 'button';
  const noun = rest.length === 1 ? 'analyst' : 'analysts';
  btn.setAttribute('aria-label', `${rest.length} more ${noun}: ${rest.map(countText).join(', ')}`);
  const hoverCapable = () => !window.matchMedia('(hover: none)').matches;
  const showTip = (x, y) => {
    const border = getComputedStyle(document.documentElement).getPropertyValue('--rule-strong').trim();
    showTextTooltip(rest.map((a) => ({ kind: 'body', text: countText(a) })), {
      borderColor: border, clientX: x, clientY: y,
    });
  };
  btn.addEventListener('mouseenter', (ev) => {
    if (hoverCapable()) showTip(ev.clientX, ev.clientY);
  });
  btn.addEventListener('focus', () => {
    if (!hoverCapable()) return;
    const r = btn.getBoundingClientRect();
    showTip(r.left, r.bottom);
  });
  btn.addEventListener('mouseleave', hideTooltip);
  btn.addEventListener('blur', hideTooltip);

  let pop = null;
  const close = (refocus) => {
    if (!pop) return;
    pop.remove();
    pop = null;
    document.removeEventListener('pointerdown', onOutside, true);
    document.removeEventListener('keydown', onKey, true);
    if (refocus) btn.focus();
  };
  function onOutside(ev) {
    if (pop && !pop.contains(ev.target) && ev.target !== btn) close(false);
  }
  function onKey(ev) {
    if (ev.key === 'Escape') close(true);
  }
  btn.addEventListener('click', (ev) => {
    ev.stopPropagation();
    if (hoverCapable()) return;
    if (pop) {
      close(false);
      return;
    }
    pop = el('div', 'more-names-pop');
    pop.setAttribute('role', 'dialog');
    pop.setAttribute('aria-label', 'More analysts');
    for (const a of rest) pop.append(el('p', null, countText(a)));
    btn.after(pop);
    document.addEventListener('pointerdown', onOutside, true);
    document.addEventListener('keydown', onKey, true);
  });
  return btn;
}

function nameCell(row) {
  const td = el('td', 'crews-name');
  td.append(el('span', 'crews-person-name', row.pbpName));
  const shown = row.analysts.slice(0, 2);
  if (shown.length > 0) {
    td.append(el('span', 'crews-with', ' with '));
    shown.forEach((a, k) => {
      if (k > 0) td.append(', ');
      td.append(el('span', 'crews-person-name', a.name));
    });
  }
  const rest = row.analysts.slice(2);
  if (rest.length > 0) td.append(moreNames(rest));
  return td;
}

/** The expanded row's head: every analyst with the games worked (the full list `+N` abbreviates). */
function subHead(row) {
  const p = el('p', 'mlb-analysts');
  p.append(el('strong', null, 'Analysts'));
  if (row.analysts.length === 0) {
    p.append(' ', el('span', 'mlb-analyst-n', 'none listed'));
    return [p];
  }
  row.analysts.forEach((a, k) => {
    p.append(k === 0 ? ' ' : ', ', a.name, ' ', el('span', 'mlb-analyst-n', `(${a.n})`));
  });
  return [p];
}

function networkCell(row) {
  const td = el('td', 'crews-network');
  if (row.network) {
    td.append(networkMark({ id: row.network.id, name: row.network.name, family: row.network.family }));
    td.title = row.network.name;
  }
  return td;
}

function buildCells(model, row) {
  const listed = numCell(String(row.listed));
  if (row.relay > 0) listed.append(el('span', 'rated-n', `${row.relay} from relay`));
  return [
    positionCell(row),
    nameCell(row),
    networkCell(row),
    numCell(String(row.gamesCount)),
    listed,
    qualityCell(model, row, METRICS[0], row.stakes),
    qualityCell(model, row, METRICS[1], row.excitement),
    numCell(winPct(row.prior)),
  ];
}

function gameRow(ctx, model, row, i) {
  const g = mlbGameRow(model, i);
  const matchup = `${g.away} at ${g.home}`;
  const tr = el('tr', 'crews-game');
  tr.dataset.game = String(i);
  tr.tabIndex = 0;
  tr.setAttribute('role', 'button');
  tr.setAttribute('aria-label', `Details for ${matchup}`);
  const crewTd = el('td', 'crews-game-crew');
  const analysts = g.crew.filter((m) => m.role === 'analyst').map((m) => m.name);
  crewTd.append(analysts.join(', '));
  const here = (model.cols.crew[i] || []).filter((m) => m.role === 'analyst').map((m) => m.person);
  const regular = row.analysts[0];
  if (here.length > 0 && regular && !here.includes(regular.person)) {
    const tag = el('span', 'crews-tag is-dashed', 'fill-in');
    tag.title = 'The regular analyst was absent';
    crewTd.append(tag);
  }
  const viewers = el('td', 'num crews-game-viewers');
  if (g.viewers != null) {
    viewers.append(el('span', 'crews-figure', formatAudienceTable(g.viewers)));
    // A window-level figure covers the whole broadcast window: tag it as Matched games does.
    if (g.scope === 'window') viewers.append(' ', windowTag());
  } else viewers.append(el('span', 'caption', CAUSE_COPY[g.cause] ?? 'no Ratings Reference figure'));
  tr.append(
    el('td', 'date crews-game-date', g.date),
    el('td', 'matchup crews-game-matchup', matchup),
    crewTd,
    viewers,
  );
  tr.addEventListener('click', () => ctx.openGame?.(i, gameOpener(i)));
  return tr;
}

/**
 * Focus target for the game panel: the table is rebuilt when the panel opens, so the row that
 * opened it is detached by the time the panel closes. This stands in for "the same game's row".
 */
function gameOpener(i) {
  const find = () => refs.tableHost.querySelector(`tr.crews-game[data-game="${i}"]`);
  return {
    get isConnected() {
      return find() != null;
    },
    focus(opts) {
      find()?.focus(opts);
    },
  };
}

function renderTable(ctx, model, state) {
  const rows = sortAppleRows(buildAppleRows(model, { adjusted }), csort).map((r) => ({
    ...r,
    names: r.names.join(' and '),
  }));
  const picked = (r) => state.booth === r.rowKey;
  renderCrewsTable(refs.tableHost, {
    ts,
    state: { csort, perseason: false },
    perSeason: false,
    sortSpec: APPLE_SORT_SPEC,
    rows,
    signature: JSON.stringify([csort, adjusted, state.booth]),
    columns: COLUMNS,
    label: 'Apple booths',
    modeKey: adjusted ? 'adjusted' : 'raw',
    colCount: COLUMNS.length + 1,
    tableClasses: ['is-mlb', 'mlb-apple-table'],
    gameHeads: ['Date', 'Matchup', 'Crew', 'Viewers'],
    buildTools: () => document.createDocumentFragment(),
    isPicked: picked,
    crewKeyOf: (r) => r.rowKey,
    buildCells: (r) => buildCells(model, r),
    subHead,
    gameRow: (r, i) => gameRow(ctx, model, r, i),
    onPick: (r) => {
      if (picked(r)) {
        ctx.clearSelection();
        announce(refs.tableHost, 'Booth pick cleared.');
      } else {
        ctx.setState({ booth: r.rowKey });
        const who = [r.pbpName, ...r.analysts.slice(0, 1).map((a) => a.name)].filter(Boolean).join(' and ');
        announce(refs.tableHost, `Booth pick set to ${who}.`);
      }
    },
    onSort: (next) => {
      csort = next;
      render(ctx);
    },
    openGame: (i) => ctx.openGame(i, gameOpener(i)),
    rerender: () => render(ctx),
  });
  return rows;
}

/** One line per measure, or the pending text; stakes first. */
function leadLines(model) {
  const s = model.appleSummary;
  const lines = [];
  const side = `${s.n_lead} ${s.n_lead === 1 ? 'game' : 'games'} for the lead booth, ${s.n_others} for the others`;
  for (const m of METRICS) {
    const diff = s[m.lead];
    const se = s[`${m.lead}_se`];
    let text;
    if (anyPending(model)) {
      text = PENDING_TEXT;
    } else if (diff == null || se == null || Math.abs(diff) <= 1.96 * se) {
      text = TOO_FEW_TEXT;
    } else {
      text = `${fixed(diff, 2, true)} ±${(1.96 * se).toFixed(2)} (${side})`;
    }
    lines.push({ key: m.key, label: m.label, text });
  }
  return lines;
}

function rrNoteText(model) {
  const s = model.appleSummary;
  if (s.rr_rated === 0) return `Ratings Reference has no figure for any of Apple's ${s.apple_games} games.`;
  return `Ratings Reference has a figure for ${s.rr_rated} of Apple's ${s.apple_games} games.`;
}

function coverageText(model) {
  let listed = 0;
  let relay = 0;
  for (const b of model.appleBooths) {
    listed += b.crew_listed;
    relay += b.relay_crews;
  }
  return `Crew listed for ${listed} of ${model.appleSummary.apple_games} Apple games. ${relay} from the relay.`;
}

function renderCaptions(model) {
  const kids = [
    el('p', 'caption', 'Average for each booth\'s games this season. Each row is one booth, in Apple\'s own order; the order is not a ranking by a measure.'),
  ];
  if (adjusted) {
    kids.push(el(
      'p',
      'caption',
      'Adjusted: how far each booth\'s games ran from what the matchup predicted, for example +0.2 more than expected. '
        + 'The ± shows 1.96 standard errors. A tendency, not proof.',
    ));
  }
  const k = threshold(model);
  kids.push(el('p', 'caption', `Cells marked n < ${k} rest on fewer than ${k} games.`));
  if (allPending(model)) {
    kids.push(el(
      'p',
      'caption mlb-pending-note',
      'Stakes and excitement for 2026 games need Retrosheet\'s 2026 files, which are released late in 2026. '
        + 'Until then the quality columns stay pending.',
    ));
  }
  refs.captions.replaceChildren(...kids);
}

export function mount(container, ctx) {
  refs.ctx = ctx;
  const controls = el('div', 'chart-controls nfl-crews-controls');
  const group = el('div', 'segmented');
  group.setAttribute('role', 'group');
  group.setAttribute('aria-label', 'Raw or adjusted');
  for (const o of [{ key: 'raw', label: 'Raw' }, { key: 'adjusted', label: 'Adjusted' }]) {
    const b = el('button', null, o.label);
    b.type = 'button';
    b.dataset.value = o.key;
    b.addEventListener('click', () => {
      adjusted = o.key === 'adjusted';
      render(ctx);
    });
    group.appendChild(b);
  }
  refs.values = group;
  controls.appendChild(group);

  refs.tableHost = el('div', 'mlb-apple-host');

  refs.coverage = el('p', 'caption nfl-coverage');
  refs.coverage.setAttribute('role', 'status');
  refs.lead = el('div', 'mlb-lead-lines');
  refs.lead.setAttribute('role', 'status');
  refs.rrNote = el('p', 'caption mlb-rr-note');
  refs.captions = el('div', 'nfl-captions');

  container.append(controls, refs.tableHost, refs.coverage, refs.lead, refs.rrNote, refs.captions);
}

export function render(ctx) {
  const { model } = ctx;
  const state = ctx.getState();
  setPressed(refs.values, adjusted ? 'adjusted' : 'raw');
  // With every booth pending there is no value to switch between.
  refs.values.parentNode.hidden = allPending(model);
  refs.coverage.textContent = coverageText(model);
  const rows = renderTable(ctx, model, state);

  const lines = leadLines(model);
  const nodes = [el('p', 'mlb-lead-title', 'Lead booth minus the others')];
  for (const l of lines) {
    const p = el('p', 'mlb-lead-line');
    p.dataset.measure = l.key;
    if (l.text === PENDING_TEXT) p.dataset.pending = 'true';
    p.append(el('span', 'mlb-lead-measure', l.label), ' ', el('span', null, l.text));
    nodes.push(p);
  }
  refs.lead.replaceChildren(...nodes);
  refs.rrNote.textContent = rrNoteText(model);
  renderCaptions(model);
  current = { model, state, lines, rows };
}

export function resize() {}

export function testModel() {
  if (!current) return { view: 'apple', rows: [], lead: [] };
  const { model, state, lines, rows } = current;
  const cellOf = (c) => ({ value: c.value, n: c.n, flagged: c.flagged, pending: c.pending });
  return {
    view: 'apple',
    adjusted,
    coverage: refs.coverage.textContent,
    rrNote: refs.rrNote.textContent,
    lead: lines,
    sort: csort ?? APPLE_SORT_SPEC.defaultSort(),
    rows: rows.map((r) => {
      const b = model.appleBooths[Number(r.rowKey)];
      return {
        key: r.rowKey,
        rankLabel: shortRank(r.rank),
        label: boothLabelOf(model, b.pbp, b.analyst),
        games: r.gamesCount,
        pending: r.stakes.pending,
        picked: state.booth === r.rowKey,
        analysts: r.analysts.map((a) => ({ name: a.name, n: a.n })),
        stakes: cellOf(r.stakes),
        excitement: cellOf(r.excitement),
      };
    }),
  };
}
