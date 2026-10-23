/**
 * NFL detail panel (999.5-08, D-09, D-14, D-17, D-20, D-22, D-23). A native
 * <dialog> the component creates inside `host`. Its sections follow the CFB
 * panel's order and are built from the shared panel-parts. It never shows a
 * point spread or any spread-named field.
 *
 * DOM is built only with createElement/textContent; every href passes through
 * `externalLink` -> `safeHref` and gets target=_blank, rel="noopener noreferrer".
 */

import { externalLink, crewBox, linksList, networksParagraph } from '../../modules/panel-parts.js';
import { currentTheme } from '../../modules/pill.js';
import {
  causeCopy,
  dateLongText,
  flagLabels,
  kickoffText,
  scoreText,
  slotLabel,
  viewersText,
} from './game-format.js';

const WINDOW_NOTE = ' · Window-level figure (all Sunday afternoon games).';

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function titleText(row) {
  const away = row.awayPoints != null ? `${row.away} ${row.awayPoints}` : row.away;
  const home = row.homePoints != null ? `${row.home} ${row.homePoints}` : row.home;
  return `${away} at ${home}`;
}

function crewSection(row) {
  const heading = el('h3', null, 'Crew');
  if (row.crew.length === 0) return [heading, el('p', 'panel-crew-empty crew-missing', 'Crew not listed.')];
  const box = crewBox(row.crew.map((c) => ({ name: c.name, role: c.role })));
  if (row.crewSource === 'published_lineup') {
    box.appendChild(el('p', 'crew-source-note', 'From published lineup.'));
  }
  return [heading, box];
}

function viewersNodes(row) {
  const v = viewersText(row);
  if (v == null) return [el('p', null, `Viewers: not available (${causeCopy(row).panel})`)];
  const nodes = [el('p', null, `Viewers: ${v}${row.scope === 'window' ? WINDOW_NOTE : ''}`)];
  if (row.era != null) nodes.push(el('p', null, `Measured under ${row.era}.`));
  return nodes;
}

function factsParagraph(row) {
  const p = el('p', 'panel-facts');
  const bits = [`Slot: ${slotLabel(row.slot)}.`, row.standalone ? 'Solo slot.' : 'Shares its window.'];
  for (const f of flagLabels(row)) if (f !== 'Solo slot' && f !== 'Flexed') bits.push(`${f}.`);
  p.appendChild(document.createTextNode(bits.join(' ')));
  if (row.flexed) {
    let line = ' Flexed from';
    if (row.originalSlot != null) line += ` ${row.originalSlot}`;
    if (row.originalNetwork) line += row.originalSlot != null ? ` on ${row.originalNetwork}` : ` ${row.originalNetwork}`;
    p.appendChild(document.createTextNode(`${line}. `));
    const a = externalLink(row.changeUrl, 'Wikipedia (CC BY-SA 4.0)');
    if (a) p.appendChild(a);
    else p.appendChild(document.createTextNode('Source: Wikipedia (CC BY-SA 4.0).'));
  }
  p.appendChild(document.createTextNode(` Final score: ${scoreText(row)}.`));
  const ex = row.excitement == null
    ? 'Excitement: not available.'
    : `Excitement: ${row.excitement.toFixed(1)} (GEI-style, not CFBD's index).`;
  p.appendChild(document.createTextNode(` ${ex}`));
  return p;
}

function linkItems(row) {
  const items = [{ href: row.rrUrl, text: 'View record on Ratings Reference ↗' }];
  items.push({
    href: row.sourceUrl,
    text: 'View original source ↗',
    fallback: row.viewers != null ? 'Original source not recorded' : undefined,
  });
  if (row.crewSource === 'published_lineup') {
    items.push({
      href: row.crewSourceUrl,
      text: 'Crew source: published lineup ↗',
      fallback: 'Crew source: published lineup',
    });
  }
  return items;
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
    title.textContent = titleText(row);
    const dateP = el('p', null, `${dateLongText(row)} · ${kickoffText(row) ?? 'Kickoff time not recorded'}`);
    const network = row.network == null
      ? el('p', null, 'Network not recorded.')
      : networksParagraph({
          primary: { id: row.networkId, name: row.network, family: row.networkFamily },
          others: [],
          theme: currentTheme(),
        });
    const children = [dateP, network, ...crewSection(row), ...viewersNodes(row), factsParagraph(row)];
    // CFB parity: the Links heading appears only when there is something to link to.
    const links = linkItems(row).filter((it) => it.href || it.fallback);
    if (links.length) children.push(el('h3', null, 'Links'), linksList(links));
    body.replaceChildren(...children);
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
