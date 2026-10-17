/**
 * MLB detail panel (D-02, D-03, D-04). A native <dialog> the component
 * creates inside `host`: header, crew with its credit, viewership with the
 * Ratings Reference record and the figure's publisher link, excitement, and
 * both teams' lineups.
 *
 * DOM is built only with createElement/textContent; every href passes through
 * `externalLink` -> `safeHref` and gets target=_blank, rel="noopener noreferrer".
 */

import { externalLink, crewBox, linksList, networksParagraph } from '../../modules/panel-parts.js';
import { currentTheme } from '../../modules/pill.js';
import { dateLongText } from './format.js';
import { CAUSE_COPY, viewersText } from './data.js';

export const RETROSHEET_NOTICE =
  'The information used here was obtained free of charge from and is copyrighted by Retrosheet.';
export const RETROSHEET_CONTACT = 'Interested parties may contact Retrosheet at ';

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function titleText(row) {
  return `${row.away} at ${row.home}`;
}

/** 'League championship · AL, game 2' or '' for the regular season. */
function roundLine(row) {
  if (!row.roundLabel) return '';
  const bits = [row.roundLabel];
  if (row.seriesLeague) bits.push(row.seriesLeague);
  if (row.seriesGame != null) bits.push(`game ${row.seriesGame}`);
  return bits.length > 1 ? `${bits[0]} · ${bits.slice(1).join(', ')}` : bits[0];
}

function creditLine(row) {
  const p = el('p', 'crew-source-note mlb-credit');
  const t = (s) => document.createTextNode(s);
  const add = (...nodes) => p.append(...nodes.filter(Boolean));
  switch (row.crewSource) {
    case 'relay':
      add(
        t('Relayed from '),
        externalLink(row.crewSourceUrl, 'a fan schedule blog post') ?? t('a fan schedule blog post'),
        row.pressName ? t(', citing ') : null,
        row.pressName ? externalLink(row.pressUrl, row.pressName) ?? t(row.pressName) : null,
        t('.'),
      );
      break;
    case 'wikipedia':
      add(t('Wikipedia list (CC BY-SA 4.0) '), externalLink(row.crewSourceUrl, 'View article ↗') ?? t('(link not recorded)'));
      break;
    case '506':
      add(t('Crew from '), externalLink(row.crewSourceUrl, '506 Sports ↗') ?? t('506 Sports'));
      break;
    case 'override':
      add(t('Hand-confirmed crew.'));
      break;
    default:
      return null;
  }
  return p;
}

/** The outlet's source: Wikipedia (CC BY-SA 4.0) with its article, or a hand-confirmed outlet. */
function outletCredit(row) {
  if (row.network == null) return [];
  const p = el('p', 'crew-source-note mlb-credit');
  p.dataset.outletSource = row.networkSource ?? '';
  const t = (s) => document.createTextNode(s);
  if (row.networkSource === 'wikipedia') {
    p.append(t('Outlet from Wikipedia (CC BY-SA 4.0) '), externalLink(row.networkSourceUrl, 'View outlet article ↗') ?? t('(link not recorded)'));
  } else if (row.networkSource === 'override') {
    p.append(t('Hand-confirmed outlet.'));
    const link = externalLink(row.networkSourceUrl, 'Source ↗');
    if (link) p.append(t(' '), link);
  } else {
    return [];
  }
  return [p];
}

function crewSection(row) {
  const heading = el('h3', null, 'Crew');
  if (row.crew.length === 0) return [heading, el('p', 'panel-crew-empty crew-missing', 'Crew not listed.')];
  const nodes = [heading, crewBox(row.crew.map((c) => ({ name: c.name, role: c.role })))];
  const credit = creditLine(row);
  if (credit) nodes.push(credit);
  return nodes;
}

function viewershipSection(row) {
  const nodes = [el('h3', null, 'Viewership')];
  const v = viewersText(row.viewers);
  if (v == null) {
    nodes.push(el('p', null, `Viewers: not available (${CAUSE_COPY[row.cause] ?? CAUSE_COPY.none})`));
  } else {
    const windowNote = row.scope === 'window' ? ' (whole broadcast window, not this game alone)' : '';
    nodes.push(el('p', null, `${row.viewersLabel || 'Viewers'}: ${v}${windowNote}`));
    if (row.era != null) nodes.push(el('p', null, `Measured under ${row.era}.`));
  }
  const links = [{ href: row.rrUrl, text: 'View record on Ratings Reference ↗' }];
  if (row.viewers != null) {
    links.push({
      href: row.sourceUrl,
      text: 'View original source ↗',
      fallback: 'Original source not recorded',
    });
  }
  const list = linksList(links);
  if (list.children.length) nodes.push(list);
  return nodes;
}

function excitementLine(row, constants) {
  if (row.excitement != null) {
    const method = constants && constants.excitement_method ? ` (${constants.excitement_method})` : '';
    return `Excitement: ${row.excitement.toFixed(1)}${method}`;
  }
  return row.lineupStatus === 'pending' || row.season >= 2026
    ? 'Excitement: pending Retrosheet 2026'
    : 'Excitement: not available';
}

function lineupList(side) {
  const ol = el('ol', 'mlb-lineup-list');
  for (const b of side.batters) {
    const li = el('li');
    li.append(el('span', 'mlb-slot', String(b.slot)), el('span', 'mlb-player', b.name), el('span', 'mlb-pos', b.position));
    ol.appendChild(li);
  }
  if (side.pitcher) {
    const li = el('li', 'mlb-sp');
    li.append(el('span', 'mlb-slot', 'SP'), el('span', 'mlb-player', side.pitcher.name), el('span', 'mlb-pos', side.pitcher.position));
    ol.appendChild(li);
  }
  return ol;
}

function lineupsSection(row) {
  const nodes = [el('h3', null, 'Lineups')];
  if (row.lineupStatus === 'pending') {
    nodes.push(el('p', 'mlb-lineup-note', 'Lineups: pending Retrosheet 2026'));
    return nodes;
  }
  if (row.lineupStatus !== 'present') {
    nodes.push(el('p', 'mlb-lineup-note', 'Lineup not in Retrosheet'));
    return nodes;
  }
  const grid = el('div', 'mlb-lineups');
  for (const [key, club] of [['away', row.away], ['home', row.home]]) {
    const col = el('div', 'mlb-lineup');
    col.dataset.side = key;
    col.append(el('h4', null, club), lineupList(row.lineups[key]));
    grid.appendChild(col);
  }
  nodes.push(grid);
  const credit = el('p', 'mlb-credit');
  const a = externalLink('https://www.retrosheet.org', 'www.retrosheet.org');
  credit.append(document.createTextNode(`${RETROSHEET_NOTICE} ${RETROSHEET_CONTACT}`), a ?? document.createTextNode('www.retrosheet.org'));
  nodes.push(credit);
  return nodes;
}

/**
 * @param {HTMLElement} host
 * @param {{onClose?: () => void, getConstants?: () => object}} opts
 */
export function createDetailPanel(host, { onClose, getConstants } = {}) {
  const dialog = el('dialog', 'detail-panel nfl-detail-panel mlb-detail-panel');
  dialog.id = 'mlb-detail-panel';
  dialog.setAttribute('aria-labelledby', 'mlb-panel-title');
  const inner = el('div', 'panel-inner');
  const closeBtn = el('button', 'panel-close', '×');
  closeBtn.type = 'button';
  closeBtn.setAttribute('aria-label', 'Close details');
  const title = el('h2');
  title.id = 'mlb-panel-title';
  const body = el('div', 'panel-body');
  inner.append(closeBtn, title, body);
  dialog.appendChild(inner);
  host.appendChild(dialog);

  let opener = null;
  let current = null;
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
    current = null;
    if (target && target.isConnected) target.focus({ preventScroll: true });
    onClose?.();
  });

  function renderRow(row) {
    title.textContent = titleText(row);
    const when = [dateLongText(row)];
    const round = roundLine(row);
    if (round) when.push(round);
    const dateP = el('p', null, when.join(' · '));
    const network = row.network == null
      ? el('p', null, 'Outlet not recorded.')
      : networksParagraph({ primary: { name: row.network, family: row.networkFamily }, others: [], theme: currentTheme() });
    if (row.network != null) network.firstChild.textContent = 'Outlet: ';
    body.replaceChildren(
      dateP,
      network,
      ...outletCredit(row),
      ...crewSection(row),
      ...viewershipSection(row),
      el('h3', null, 'Excitement'),
      el('p', null, excitementLine(row, getConstants?.())),
      ...lineupsSection(row),
    );
  }

  return {
    open(row, openerEl) {
      renderRow(row);
      current = row.i;
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
    currentGame() {
      return dialog.open ? current : null;
    },
  };
}
