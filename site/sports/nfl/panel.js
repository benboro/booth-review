/**
 * NFL detail panel (999.5-08, D-09, D-22, D-23). A native <dialog> the
 * component creates inside `host`. Fields follow the UI-SPEC order. It never
 * shows a point spread or any spread-named field.
 *
 * DOM is built only with createElement/textContent; every href passes through
 * `safeHref` and gets target=_blank with rel="noopener noreferrer".
 */

import { safeHref } from '../../modules/panel.js';
import { makeRolePill, nameWithRoles } from '../../modules/pill.js';
import {
  causeCopy,
  dateLongText,
  flagLabels,
  kickoffText,
  scoreText,
  slotLabel,
  viewersText,
} from './game-format.js';

const WINDOW_TITLE = 'This figure covers the whole Sunday-afternoon window, not just this game.';
const NOT_RECORDED = 'Not recorded';

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function link(url, text) {
  const href = safeHref(url);
  if (!href) return null;
  const a = el('a', null, text);
  a.href = href;
  a.target = '_blank';
  a.rel = 'noopener noreferrer';
  return a;
}

/** A label/value field row: `<div class="panel-field"><h3>label</h3><div>...</div></div>`. */
function field(label, ...valueNodes) {
  const wrap = el('div', 'panel-field');
  wrap.appendChild(el('h3', null, label));
  const value = el('div', 'panel-field-value');
  value.append(...valueNodes);
  wrap.appendChild(value);
  return wrap;
}

function text(s) {
  return document.createTextNode(s);
}

function flexedNodes(row) {
  const parts = [];
  if (row.originalSlot != null) parts.push(row.originalSlot);
  const origin = parts.length ? parts[0] : null;
  let line = 'Flexed from';
  if (origin) line += ` ${origin}`;
  if (row.originalNetwork) line += origin ? ` (${row.originalNetwork})` : ` ${row.originalNetwork}`;
  const nodes = [el('p', null, line)];
  const a = link(row.changeUrl, 'Scheduling change on Wikipedia ↗');
  if (a) {
    const p = el('p');
    p.appendChild(a);
    nodes.push(p);
  }
  nodes.push(el('p', 'nfl-muted', 'Scheduling facts: Wikipedia, CC BY-SA 4.0.'));
  return nodes;
}

function crewNodes(row) {
  if (row.crew.length === 0) return [text(NOT_RECORDED)];
  const box = el('div', 'crew-box');
  const ul = el('ul', 'panel-crew');
  for (const c of row.crew) {
    const li = el('li');
    li.appendChild(nameWithRoles(el('span', 'crew-name', c.name), makeRolePill(c.role)));
    ul.appendChild(li);
  }
  box.appendChild(ul);
  return [box];
}

function viewersNodes(row) {
  const v = viewersText(row);
  if (v == null) return [text(`Not available (${causeCopy(row).panel})`)];
  const nodes = [text(v)];
  if (row.scope === 'window') {
    const tag = el('span', 'nfl-muted', 'window-level');
    tag.title = WINDOW_TITLE;
    nodes.push(text(' '), tag);
  }
  return nodes;
}

function linksNodes(row) {
  const ul = el('ul', 'panel-links');
  const rr = link(row.rrUrl, 'View record on Ratings Reference ↗');
  if (rr) {
    const li = el('li');
    li.appendChild(rr);
    ul.appendChild(li);
  }
  const li = el('li');
  const src = link(row.sourceUrl, 'View original source ↗');
  if (src) li.appendChild(src);
  else li.textContent = 'Original source not recorded';
  ul.appendChild(li);
  return [ul];
}

/**
 * @param {HTMLElement} host
 * @param {{methodologyHref?: string}} opts
 */
// methodologyHref is accepted for the shell's wiring; the panel itself shows no methodology link.
export function createDetailPanel(host, { methodologyHref: _methodologyHref } = {}) {
  const dialog = el('dialog', 'detail-panel nfl-detail-panel');
  dialog.id = 'nfl-detail-panel';
  dialog.setAttribute('aria-labelledby', 'nfl-panel-title');
  const inner = el('div', 'panel-inner');
  const closeBtn = el('button', 'panel-close', '×');
  closeBtn.type = 'button';
  closeBtn.setAttribute('aria-label', 'Close details');
  const title = el('h2');
  title.id = 'nfl-panel-title';
  const body = el('div', 'panel-body');
  inner.append(closeBtn, title, body);
  dialog.appendChild(inner);
  host.appendChild(dialog);

  let opener = null;
  let pointerDownOnBackdrop = false;

  closeBtn.addEventListener('click', () => dialog.close());
  dialog.addEventListener('pointerdown', (ev) => {
    pointerDownOnBackdrop = ev.target === dialog;
  });
  dialog.addEventListener('click', (ev) => {
    if (ev.target === dialog && pointerDownOnBackdrop) dialog.close();
    pointerDownOnBackdrop = false;
  });
  dialog.addEventListener('close', () => {
    const target = opener;
    opener = null;
    if (target && target.isConnected) target.focus({ preventScroll: true });
  });

  function renderRow(row) {
    title.textContent = `${row.away} at ${row.home}`;
    const fields = [
      field('Final score', text(scoreText(row))),
      field('Date', text(dateLongText(row))),
      field('Kickoff', text(kickoffText(row) ?? NOT_RECORDED)),
      field('Week', text(`Week ${row.week}, ${row.season} regular season`)),
      field('Slot', text(slotLabel(row.slot))),
    ];
    const flags = flagLabels(row);
    fields.push(
      field(
        'Flags',
        ...(flags.length
          ? flags.map((f) => el('span', 'pill nfl-pill', f))
          : [text('None')]),
      ),
    );
    if (row.flexed) fields.push(field('Flexed from', ...flexedNodes(row)));
    fields.push(field('Network', text(row.network ?? NOT_RECORDED)));
    fields.push(field('Crew', ...crewNodes(row)));
    fields.push(field('Viewers', ...viewersNodes(row)));
    if (row.viewers != null && row.era != null) fields.push(field('Measured under', text(row.era)));
    if (row.viewers != null && row.scope === 'window') {
      fields.push(
        field(
          'Viewership scope',
          el('span', 'nfl-muted', 'Unnormalized. No coverage-share data was available.'),
        ),
      );
    }
    const exVal = row.excitement == null ? 'Not available' : row.excitement.toFixed(1);
    fields.push(
      field(
        'GEI-style excitement',
        text(exVal),
        text(' '),
        el('span', 'nfl-muted', "Not CFBD's excitement index."),
      ),
    );
    fields.push(field('Links', ...linksNodes(row)));
    body.replaceChildren(...fields);
  }

  return {
    open(row, openerEl) {
      renderRow(row);
      if (dialog.open) return;
      opener = openerEl ?? (document.activeElement !== document.body ? document.activeElement : null);
      dialog.showModal();
    },
    close() {
      if (dialog.open) dialog.close();
    },
    isOpen() {
      return dialog.open;
    },
  };
}
