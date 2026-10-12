/**
 * NFL Crews view: contract skeleton (plan 08-06).
 *
 * Mounts the section skeleton and lists the rows it has as plain text. The
 * full Crews table, chart and controls replaces this body. DOM only via createElement/textContent.
 */
import { crewsRows } from '../state.js';

const refs = { ctx: null, list: null, note: null, noteTitle: null, noteBody: null };
let current = { rows: [] };

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

export function mount(container, ctx) {
  refs.ctx = ctx;
  const controls = el('div', 'chart-controls');
  const chart = el('div', 'nfl-chart');
  refs.note = el('div', 'season-empty-note');
  refs.note.setAttribute('role', 'status');
  refs.noteTitle = el('p', 'season-empty-title');
  refs.noteBody = el('p', 'season-empty-hint');
  refs.note.append(refs.noteTitle, refs.noteBody);
  refs.list = el('div', 'nfl-rows');
  chart.append(refs.note, refs.list);
  const captions = el('div', 'caption');
  const dataHost = el('div', 'visually-hidden nfl-data-table');
  container.append(controls, chart, captions, dataHost);
}

export function render(ctx) {
  const rows = crewsRows(ctx.model, ctx.getState());
  current = { rows };
  refs.list.replaceChildren();
  if (!rows.length) {
    refs.noteTitle.textContent = 'No crews listed.';
    refs.noteBody.textContent = '506 does not list a crew for these games. Try another network or season.';
    refs.note.hidden = false;
    return;
  }
  refs.note.hidden = true;
  for (const line of rows.map((r) => `#${r.rank ?? '-'} · ${r.games} games`)) refs.list.appendChild(el('p', null, line));
}

export function resize() {}

export function testModel() {
  return { view: 'crews', rows: current.rows };
}
