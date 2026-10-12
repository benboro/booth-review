/**
 * NFL Viewership view: contract skeleton (plan 08-06).
 *
 * Mounts the section skeleton and lists the rows it has as plain text. The
 * full Viewership chart, legend and controls replaces this body. DOM only via createElement/textContent.
 */
import { viewershipSeries } from '../state.js';

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
  const state = ctx.getState();
  const rows = viewershipSeries(ctx.model, state).filter(
    (s) => s.points.length && !state.hiddenCategories.includes(s.id),
  );
  current = { rows };
  refs.list.replaceChildren();
  if (!rows.length) {
    refs.noteTitle.textContent = 'No categories shown.';
    refs.noteBody.textContent = 'Turn on a category above.';
    refs.note.hidden = false;
    return;
  }
  refs.note.hidden = true;
  for (const line of rows.map((s) => `${s.label}: ${s.points.length} seasons`)) refs.list.appendChild(el('p', null, line));
}

export function resize() {}

export function testModel() {
  return { view: 'viewership', rows: current.rows };
}
