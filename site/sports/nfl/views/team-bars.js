/**
 * NFL view contract module for 'special'. This plan ships the shell and the
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
  note.append(noteTitle, el('p', 'season-empty-hint', 'Widen the season range or reset Seasons.'));
  chart.appendChild(note);
  const captions = el('div', 'nfl-captions');
  const dataTable = el('table', 'visually-hidden');
  dataTable.appendChild(el('caption', null, 'Special games by team'));
  container.append(legend, controls, chart, captions, dataTable);
}

export function render(ctx) {
  if (!noteTitle) return;
  noteTitle.textContent = 'No NFL games in these seasons.';
}

export function resize() {}

export function testModel() {
  return { view: 'special', drawn: false };
}
