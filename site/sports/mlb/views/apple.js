/**
 * MLB Apple crews view (SPORT-06): one row per Apple booth, 2026.
 *
 * Stakes first, Excitement second (D-07). Raw by default, Adjusted as a secondary
 * switch. While Retrosheet 2026 is not loaded the quality cells read "pending
 * Retrosheet 2026" (D-06). A low-n booth is faded and never ranked against others;
 * the table shows each booth's standing in Apple's own order (Lead, #2, #3), never
 * a rank by a measure. No p-values and no "wins": captions say "tendency, not proof".
 *
 * Everything is built with createElement and textContent only.
 */
import { boothLabelOf, personName } from '../data.js';
import { makeRolePill, nameWithRoles } from '../../../modules/pill.js';
import { attachScrollCue } from '../../../modules/scroll-cue.js';

const DASH = '—';
const MINUS = '−';
export const PENDING_TEXT = 'pending Retrosheet 2026';
export const TOO_FEW_TEXT = 'too few games to call a difference';

const METRICS = [
  { key: 'stakes', label: 'Stakes', raw: 'raw_stakes', adj: 'adj_stakes', se: 'adj_stakes_se', lead: 'lead_minus_others_stakes' },
  { key: 'excitement', label: 'Excitement', raw: 'raw_excitement', adj: 'adj_excitement', se: 'adj_excitement_se', lead: 'lead_minus_others_excitement' },
];

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

const refs = {
  ctx: null,
  coverage: null,
  values: null,
  lead: null,
  rrNote: null,
  info: null,
  tableBody: null,
  captions: null,
};

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

function isLowN(model, r) {
  return !!r.low_n || r.games < model.constants.low_n_threshold;
}

function allPending(model) {
  return model.appleBooths.length > 0 && model.appleBooths.every((b) => b.quality_status === 'pending');
}

/** The builder withholds every lead-minus-others figure while any booth is pending. */
function anyPending(model) {
  return model.freshness.quality_pending || model.appleBooths.some((b) => b.quality_status === 'pending');
}

function qualityCell(model, r, m) {
  if (r.quality_status === 'pending') {
    const td = el('td', 'num mlb-pending', PENDING_TEXT);
    td.dataset.pending = 'true';
    return td;
  }
  const value = adjusted ? r[m.adj] : r[m.raw];
  const td = numCell(fixed(value, 2, adjusted));
  if (adjusted && value != null && r[m.se] != null) {
    td.append(el('span', 'rated-n', `±${(1.96 * r[m.se]).toFixed(2)}`));
  }
  return td;
}

function boothCell(model, r, k, picked) {
  const th = el('th', 'booth-col');
  th.scope = 'row';
  const btn = el('button', 'booth-row-btn');
  btn.type = 'button';
  btn.dataset.booth = String(k);
  btn.setAttribute('aria-pressed', String(picked));
  btn.append(el('span', 'booth-rank', shortRank(r.rank_label)));
  const names = el('span', 'booth-names');
  names.append(nameWithRoles(el('span', 'booth-name', personName(model, r.pbp)), makeRolePill('pbp')));
  if (r.analyst != null) {
    names.append(
      el('span', 'booth-sep', ' / '),
      nameWithRoles(el('span', 'booth-name', personName(model, r.analyst)), makeRolePill('analyst')),
    );
  }
  if (isLowN(model, r)) {
    const tag = el('span', 'low-n-tag', 'low n');
    tag.title = 'Few games, so treat with care.';
    names.append(tag);
  }
  btn.append(' ', names);
  btn.addEventListener('click', () => {
    const state = refs.ctx.getState();
    if (state.booth === String(k)) refs.ctx.clearSelection();
    else refs.ctx.setState({ booth: String(k) });
  });
  th.appendChild(btn);
  return th;
}

function renderTable(model, state) {
  const body = refs.tableBody;
  body.replaceChildren();
  model.appleBooths.forEach((r, k) => {
    const tr = el('tr');
    tr.dataset.booth = String(k);
    const low = isLowN(model, r);
    if (low) tr.dataset.lowN = 'true';
    const picked = state.booth === String(k);
    if (picked) tr.dataset.picked = 'true';
    tr.append(boothCell(model, r, k, picked), numCell(String(r.games)));
    const listed = numCell(String(r.crew_listed));
    if (r.relay_crews > 0) listed.append(el('span', 'rated-n', `${r.relay_crews} from relay`));
    tr.append(listed);
    for (const m of METRICS) tr.append(qualityCell(model, r, m));
    tr.append(numCell(winPct(r.strength_prior)));
    body.appendChild(tr);
  });
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
  kids.push(el('p', 'caption', 'Faded rows are booths with few games.'));
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

  refs.coverage = el('p', 'caption nfl-coverage');
  refs.coverage.setAttribute('role', 'status');

  const wrap = el('div', 'nfl-booth-table-wrap table-scroll');
  const table = el('table', 'games-table nfl-booth-table mlb-apple-table');
  table.appendChild(el('caption', 'visually-hidden', 'Apple booths, 2026'));
  const head = el('tr');
  for (const h of ['Booth', 'Games', 'Crew listed', 'Stakes', 'Excitement', '2025 win % of both clubs']) {
    const th = el('th', h === 'Booth' ? 'booth-col' : 'num', h);
    th.scope = 'col';
    head.appendChild(th);
  }
  const thead = el('thead');
  thead.appendChild(head);
  refs.tableBody = el('tbody');
  table.append(thead, refs.tableBody);
  wrap.appendChild(table);
  attachScrollCue(wrap, null);

  refs.lead = el('div', 'mlb-lead-lines');
  refs.lead.setAttribute('role', 'status');
  refs.rrNote = el('p', 'caption mlb-rr-note');
  refs.captions = el('div', 'nfl-captions');

  container.append(controls, refs.coverage, wrap, refs.lead, refs.rrNote, refs.captions);
}

export function render(ctx) {
  const { model } = ctx;
  const state = ctx.getState();
  setPressed(refs.values, adjusted ? 'adjusted' : 'raw');
  // With every booth pending there is no value to switch between.
  refs.values.parentNode.hidden = allPending(model);
  refs.coverage.textContent = coverageText(model);
  renderTable(model, state);

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
  current = { model, state, lines };
}

export function resize() {}

export function testModel() {
  if (!current) return { view: 'apple', rows: [], lead: [] };
  const { model, state, lines } = current;
  return {
    view: 'apple',
    adjusted,
    coverage: refs.coverage.textContent,
    rrNote: refs.rrNote.textContent,
    lead: lines,
    rows: model.appleBooths.map((r, k) => ({
      key: String(k),
      rankLabel: shortRank(r.rank_label),
      label: boothLabelOf(model, r.pbp, r.analyst),
      games: r.games,
      lowN: isLowN(model, r),
      pending: r.quality_status === 'pending',
      picked: state.booth === String(k),
    })),
  };
}
