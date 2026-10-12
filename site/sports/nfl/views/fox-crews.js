/**
 * NFL view contract module for 'fox'. This plan ships the shell and the
 * empty-state note; the view's plan fills in the chart.
 */
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

let note = null;
let noteTitle = null;

export function mount(container, _ctx) {
  const legend = el('div', 'nfl-legend-row');
  const controls = el('div', 'nfl-view-controls');
  const chart = el('div', 'nfl-chart');
  note = el('div', 'season-empty-note');
  note.setAttribute('role', 'status');
  noteTitle = el('p', 'season-empty-title');
  note.append(noteTitle, el('p', 'season-empty-hint', 'Pick another season with the stepper.'));
  chart.appendChild(note);
  const captions = el('div', 'nfl-captions');
  const dataTable = el('table', 'visually-hidden');
  dataTable.appendChild(el('caption', null, 'Fox crews'));
  container.append(legend, controls, chart, captions, dataTable);
}

export function render(ctx) {
  if (!noteTitle) return;
  const state = ctx.getState();
  noteTitle.textContent = `No Fox booth data for ${state.fseason}.`;
}

export function resize() {}

export function testModel() {
  return { view: 'fox', drawn: false };
}
