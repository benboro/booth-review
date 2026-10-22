/**
 * Custom HTML hover tooltip (D-22, SITE-25, SITE-26): the default
 * `TOOLTIP_MODE` in `chart.js` swaps Plotly's own pseudo-HTML hover label
 * (which can't draw a filled background) for a small `position: fixed`
 * tooltip built here, positioned next to the hovered dot, whose network
 * networks render as logos (or a name) through `network.js`.
 *
 * `tooltipModel` is the pure, DOM-free content decision shared by both
 * tooltip paths: this module's `renderTooltipContent` (html mode) and
 * `chart.js`'s `hoverText` (the plotly-hovertemplate fallback mode) build
 * their own output from the same model, so the two paths can never drift on
 * which lines/order/content they show.
 *
 * DOM is built only with createElement/textContent/replaceChildren -- never
 * any markup-injecting DOM API (T-04.1-25), matching panel.js/filters.js/
 * table.js's own convention. Module scope never touches `window` or
 * `document` -- only the functions below do -- so `tooltipModel` stays
 * importable from plain node for a quick check.
 */

import {
  crewEntries,
  axisValueText,
  boothLabel,
  formatDate,
  formatAudienceShort,
  formatKickoff,
  formatMatchup,
  formatViewers,
  namedGameInfo,
  noRatingLine,
  stripNetworkNote,
} from './format.js';
import { makeGameTypeIcon } from './icons.js';
import { networkMarks } from './network.js';
import { makeRolePill, nameWithRoles, roleKey, ROLE_PILL_TEXT } from './pill.js';
import {
  FAMILY_COLORS,
  MAP_DOT_NEUTRAL,
  MAP_FAMILY_COLORS,
  PAGE_BG,
  familyKey,
} from './palette.js';

/** The single `#chart-tooltip` element, created lazily on first use. */
let tooltipEl = null;

/** Tooltip score line per y mode (04.17 D-14/D-15): label and the `prepareData` array. */
const SCORE_LINES = new Map([
  ['points', { label: 'Total points', key: 'total' }],
  ['margin', { label: 'Margin', key: 'margin' }],
]);

/** Sits this many pixels right of and below the hovered point before any
 * viewport-edge flip (see `showTooltip`). */
const OFFSET = 12;

/** Minimum distance the tooltip is ever clamped to from a viewport edge. */
const EDGE_MARGIN = 8;

/**
 * Builds the shared, DOM-free content model for telecast `i`'s tooltip: the
 * UI-SPEC's minimal line order -- matchup+score, date+kickoff (a named
 * only; a named game's icons plus its name -- rivalry, bowl core name, or CFP
 * round, from `format.js#namedGameInfo`, 04.10 D-10 -- sit on their own line
 * under it, notes-2 #6; the time-slot label is panel-only), slash-delimited networks (primary first,
 * each already stripped of any nested methodology parenthetical), one
 * "Position: Name" line per main-feed crew member, viewers, the active axis
 * value. Conferences, the time
 * slot, the full outlet list, the measurement-type badge, era/event flags,
 * and any scoring-source note are panel-only (SITE-25) -- never repeated
 * here. `dateText` is the date and kickoff only; `gameType` the named-game
 * marker, which `renderTooltipContent` draws as decorative `icons` followed by
 * the visible `text` on its own line (`chart.js#hoverText`, the text-only
 * fallback that can't draw an SVG, puts `text` on its own line too).
 * @param {object} data - a `prepareData` result.
 * @param {number} i - telecast index.
 * @param {{axis: "spread"|"excitement", y?: "viewers"|"excitement"|"points"|"margin", selected?: Set<number>}} opts
 * @returns {{crew: {name: string, role: string, selected: boolean}[], title: string, dateText: string, gameType: {icons: ("bowl"|"playoff"|"rivalry")[], text: string}|null, networks: {id: string, name: string, family: string}[], crewLines: string[], viewersLine: string, axisLine: string, scoreLine: string|null}}
 */
export function tooltipModel(data, i, { axis, y = 'viewers', selected = new Set() }) {
  const t = data.t;

  const title = formatMatchup(data, i, { withScore: true });

  const dateText = [formatDate(t.date[i]), formatKickoff(t.kickoff[i]) ?? 'Kickoff time not recorded'].join(' · ');
  const gameType = namedGameInfo(data, i);

  const primaryNetwork = data.lookups.networks[t.network[i]];
  const otherOutlets = t.outlets[i]
    .filter((idx) => idx !== t.network[i])
    .map((idx) => data.lookups.networks[idx]);
  const networks = [primaryNetwork, ...otherOutlets].map((net) => ({
    id: net.id,
    name: stripNetworkNote(net.name),
    family: net.family,
  }));

  const crew = crewEntries(data, i, { mainOnly: true, selected });
  const crewLines = crew.map((entry) => `${entry.name} (${ROLE_PILL_TEXT[roleKey(entry.role)]})`);
  if (crewLines.length === 0) crewLines.push('Crew not recorded');

  const viewersLine = data.rated[i] ? `Viewers: ${formatViewers(t.viewers[i])}` : noRatingLine(data, i);
  // D-17: on Spread x with Excitement y the line shows both plotted measures,
  // the same form as the Date line. Excitement x cannot pair with Excitement y
  // (the D-11 swap), and Viewers y is unchanged.
  const lineAxis = y === 'excitement' && axis === 'spread' ? 'date' : axis;
  const axisLine = axisValueText(data, i, lineAxis);
  // 04.17 D-11: Points and Margin plot a pinned value, so the true one is stated here.
  // A constant label plus a number or the literal 'not available' (T-04.17-12).
  // A Map, not an object literal, so an unexpected `y` such as "constructor" finds nothing.
  const score = SCORE_LINES.get(y);
  const scoreLine = score ? `${score.label}: ${data[score.key][i] ?? 'not available'}` : null;
  const boothLine = boothLabel(data, i);

  return { boothLine, title, dateText, gameType, networks, crew, crewLines, viewersLine, axisLine, scoreLine };
}

/**
 * Rebuilds `el`'s children from `model` (`replaceChildren`, never an
 * incremental append) -- a title, a row of network marks (no family dot: the border carries it)
 * (SITE-26, D-29 -- the `.tooltip-networks` flex row's own gap is the only
 * visible separator between pills, no separator element or text), one line
 * per date/crew/viewers/axis fact. Every string is
 * assigned via `textContent`/`networkMark` (which itself only uses
 * `textContent`), so a malicious team/crew/network name can never become a
 * real element (T-04.1-25). Also sets `el`'s own border color to the
 * primary network's (`model.networks[0]`, always first per `tooltipModel`)
 * family color (D-29, T-04.1-43): resolved only through `FAMILY_COLORS` /
 * `familyKey`, never a raw data string, matching `pill.js`'s own pattern.
 * @param {HTMLElement} el
 * @param {ReturnType<typeof tooltipModel>} model
 * @param {"light"|"dark"} theme
 */
export function renderTooltipContent(el, model, theme) {
  const children = [];

  const title = document.createElement('strong');
  title.className = 'tooltip-title';
  title.textContent = model.title;
  children.push(title);

  const dateLine = document.createElement('div');
  dateLine.textContent = model.dateText;
  children.push(dateLine);
  if (model.gameType) {
    // The icons are decorative (aria-hidden) and the visible name carries the
    // meaning (04.10 D-10, reversing 04.2 D-22's icon-only rule). If any icon
    // can't be built, draw none (never a partial marker); the text still shows.
    const icons = model.gameType.icons.map((kind) => makeGameTypeIcon(kind));
    const type = document.createElement('div');
    type.className = 'tooltip-game-type';
    if (icons.every((icon) => icon != null)) type.replaceChildren(...icons);
    type.appendChild(document.createTextNode(model.gameType.text));
    children.push(type);
  }

  const networksRow = document.createElement('div');
  networksRow.className = 'tooltip-networks';
  networksRow.appendChild(networkMarks(model.networks, { dot: false }));
  children.push(networksRow);

  const primaryFamily = familyKey(model.networks[0].family);
  el.style.borderColor = FAMILY_COLORS[theme][primaryFamily];
  el.dataset.family = primaryFamily;

  if ((model.crew ?? []).length === 0) {
    const missing = document.createElement('div');
    missing.className = 'crew-missing';
    missing.textContent = 'Crew not recorded';
    children.push(missing);
  } else {
    const box = document.createElement('div');
    box.className = model.crew.some((e) => e.selected) ? 'crew-box is-matched' : 'crew-box';
    for (const entry of model.crew) {
      const line = document.createElement('div');
      line.className = 'crew-line';
      const name = document.createElement('span');
      name.className = entry.selected ? 'crew-name is-selected' : 'crew-name';
      name.textContent = entry.name;
      line.append(nameWithRoles(name, makeRolePill(entry.role)));
      box.appendChild(line);
    }
    children.push(box);
  }

  if (model.boothLine != null) {
    const booth = document.createElement('div');
    booth.className = 'tooltip-booth';
    booth.textContent = model.boothLine;
    children.push(booth);
  }

  const viewersLine = document.createElement('div');
  viewersLine.textContent = model.viewersLine;
  children.push(viewersLine);

  const axisLine = document.createElement('div');
  axisLine.textContent = model.axisLine;
  children.push(axisLine);
  if (model.scoreLine != null) {
    const scoreLine = document.createElement('div');
    scoreLine.textContent = model.scoreLine;
    children.push(scoreLine);
  }

  el.replaceChildren(...children);
}

/**
 * Creates `#chart-tooltip` on first call and appends it to `document.body`
 * once; every later call returns the same element. Created in JS (not
 * `index.html`) so this plan touches no static markup.
 * @returns {HTMLElement}
 */
export function ensureTooltipEl() {
  if (tooltipEl) return tooltipEl;
  tooltipEl = document.createElement('div');
  tooltipEl.id = 'chart-tooltip';
  tooltipEl.className = 'chart-tooltip';
  tooltipEl.setAttribute('role', 'tooltip');
  tooltipEl.hidden = true;
  document.body.appendChild(tooltipEl);
  return tooltipEl;
}

/**
 * Positions `el` (already unhidden) beside `(clientX, clientY)`: OFFSET px
 * right of and below, flipping left/above near the right/bottom edge, always
 * clamped EDGE_MARGIN px inside the viewport.
 */
function placeTooltip(el, clientX, clientY) {
  const width = el.offsetWidth;
  const height = el.offsetHeight;

  let left = clientX + OFFSET;
  if (left + width > window.innerWidth - EDGE_MARGIN) left = clientX - OFFSET - width;
  left = Math.max(EDGE_MARGIN, Math.min(left, window.innerWidth - EDGE_MARGIN - width));

  let top = clientY + OFFSET;
  if (top + height > window.innerHeight - EDGE_MARGIN) top = clientY - OFFSET - height;
  top = Math.max(EDGE_MARGIN, Math.min(top, window.innerHeight - EDGE_MARGIN - height));

  el.style.left = `${left}px`;
  el.style.top = `${top}px`;
}

/**
 * Shows plain text lines in the shared tooltip (Bars/Butterfly, D-16).
 * @param {{text: string, kind: 'title'|'body'|'hint', swatch?: string, roles?: string[]}[]} lines
 * @param {{theme: string, borderColor: string, clientX: number, clientY: number}} opts
 */
export function showTextTooltip(lines, { borderColor, clientX, clientY }) {
  const el = ensureTooltipEl();
  const children = lines.map(({ text, kind, swatch, roles }) => {
    const node = document.createElement(kind === 'title' ? 'strong' : 'div');
    if (kind === 'title') node.className = 'tooltip-title';
    if (kind === 'hint') node.className = 'tooltip-hint';
    if (swatch) {
      const chip = document.createElement('span');
      chip.className = 'tooltip-swatch';
      chip.setAttribute('aria-hidden', 'true');
      chip.style.backgroundColor = swatch;
      node.appendChild(chip);
      node.appendChild(document.createTextNode(text));
    } else {
      node.textContent = text;
    }
    if (roles && roles.length > 0) {
      // Keep the last text and the pills in one unbreakable unit (SITE-38).
      const last = node.lastChild;
      const unit = nameWithRoles(...(last ? [last] : []), ...roles.map(makeRolePill));
      node.appendChild(unit);
    }
    return node;
  });
  el.replaceChildren(...children);
  el.style.borderColor = borderColor;
  delete el.dataset.family;
  delete el.dataset.kind;
  el.hidden = false;
  placeTooltip(el, clientX, clientY);
}

/**
 * Renders telecast `i`'s tooltip content and positions it beside the
 * hovered point at `(clientX, clientY)`: `OFFSET`px right of and below the
 * point by default, flipping to the left/above when it would cross within
 * `EDGE_MARGIN`px of the right/bottom edge, and always clamped to at least
 * `EDGE_MARGIN`px from every edge. Size is measured (`offsetWidth`/
 * `offsetHeight`) only after the element is unhidden, since a `hidden`
 * element reports zero size.
 * @param {object} data - a `prepareData` result.
 * @param {number} i - telecast index.
 * @param {{axis: "spread"|"excitement", y?: "viewers"|"excitement", theme: "light"|"dark", clientX: number, clientY: number}} opts
 */
export function showTooltip(data, i, { axis, y, theme, clientX, clientY, selected }) {
  const el = ensureTooltipEl();
  renderTooltipContent(el, tooltipModel(data, i, { axis, y, selected }), theme);
  delete el.dataset.kind;
  el.hidden = false;

  placeTooltip(el, clientX, clientY);
}

/** Hides the tooltip (a no-op before the first `showTooltip` call). */
export function hideTooltip() {
  if (tooltipEl) tooltipEl.hidden = true;
}

const SVG_NS = 'http://www.w3.org/2000/svg';

/** Credit note for aggregate viewer sums (CLAUDE.md Website rule): the games table credits each source. */
export const VENUE_CREDIT_NOTE =
  "Viewers add up published figures from Ratings Reference and other outlets; the games table (click the dot) credits each game's source.";

/**
 * The 48px venue pie (Phase 11 D-02): slices clockwise from 12 o'clock in the given order,
 * 1px page-background separators, a plain circle for a single family. Built with
 * createElementNS only.
 * @param {{family: string, games: number}[]} slices
 * @param {"light"|"dark"} theme
 * @returns {SVGSVGElement}
 */
export function venuePieSvg(slices, theme) {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('width', '48');
  svg.setAttribute('height', '48');
  svg.setAttribute('viewBox', '0 0 48 48');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('class', 'tooltip-pie');
  const total = slices.reduce((sum, s) => sum + s.games, 0);
  const r3 = (v) => String(Math.round(v * 1000) / 1000);
  if (slices.length === 1) {
    const circle = document.createElementNS(SVG_NS, 'circle');
    circle.setAttribute('cx', '24');
    circle.setAttribute('cy', '24');
    circle.setAttribute('r', '22');
    circle.setAttribute('fill', MAP_FAMILY_COLORS[theme][slices[0].family]);
    svg.appendChild(circle);
    return svg;
  }
  let a0 = -Math.PI / 2;
  for (const slice of slices) {
    const share = slice.games / total;
    const a1 = a0 + 2 * Math.PI * share;
    const large = share > 0.5 ? 1 : 0;
    const path = document.createElementNS(SVG_NS, 'path');
    path.setAttribute(
      'd',
      `M24 24 L${r3(24 + 22 * Math.cos(a0))} ${r3(24 + 22 * Math.sin(a0))} ` +
        `A22 22 0 ${large} 1 ${r3(24 + 22 * Math.cos(a1))} ${r3(24 + 22 * Math.sin(a1))} Z`,
    );
    path.setAttribute('fill', MAP_FAMILY_COLORS[theme][slice.family]);
    path.setAttribute('stroke', PAGE_BG[theme]);
    path.setAttribute('stroke-width', '1');
    svg.appendChild(path);
    a0 = a1;
  }
  return svg;
}

/**
 * Shows the venue hover card (Phase 11 D-02, D-01a) from a plain card object.
 * @param {{title: string, leader: string, slices: object[], rows: object[],
 *   hasMissingViewers: boolean, hasPartialViewers?: boolean, hasViewers: boolean,
 *   subjectLines: {text: string, kind: string}[]}} card
 * @param {{theme: "light"|"dark", clientX: number, clientY: number, hint: string}} opts
 */
export function showVenueTooltip(card, { theme, clientX, clientY, hint }) {
  const el = ensureTooltipEl();
  const text = (tag, className, content) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    node.textContent = content;
    return node;
  };

  const title = text('strong', 'tooltip-title', card.title);

  const table = document.createElement('table');
  table.className = 'tooltip-venue-table';
  const headRow = document.createElement('tr');
  headRow.append(text('th', '', ''), text('th', '', 'Games'), text('th', '', 'Viewers'));
  const thead = document.createElement('thead');
  thead.appendChild(headRow);
  const tbody = document.createElement('tbody');
  for (const row of card.rows) {
    const tr = document.createElement('tr');
    const label = document.createElement('td');
    const swatch = document.createElement('span');
    swatch.className = 'tooltip-swatch';
    swatch.setAttribute('aria-hidden', 'true');
    swatch.style.backgroundColor =
      row.family == null ? MAP_DOT_NEUTRAL[theme] : MAP_FAMILY_COLORS[theme][row.family];
    label.append(swatch, document.createTextNode(row.label));
    const viewers =
      row.viewers == null ? '-' : formatAudienceShort(row.viewers) + (row.partial ? '*' : '');
    tr.append(label, text('td', 'num', String(row.games)), text('td', 'num', viewers));
    tbody.appendChild(tr);
  }
  table.append(thead, tbody);

  const body = document.createElement('div');
  body.className = 'tooltip-venue-body';
  body.append(venuePieSvg(card.slices, theme), table);

  const children = [title, body];
  if (card.hasMissingViewers) {
    children.push(text('p', 'tooltip-footnote', '- no viewer figure listed'));
  }
  if (card.hasPartialViewers) {
    children.push(text('p', 'tooltip-footnote', '* Viewers cover rated games only'));
  }
  if (card.hasViewers) {
    children.push(text('p', 'tooltip-footnote tooltip-credit', VENUE_CREDIT_NOTE));
  }
  for (const line of card.subjectLines) {
    children.push(text('div', line.kind === 'hint' ? 'tooltip-hint' : '', line.text));
  }
  children.push(text('p', 'tooltip-hint', hint));

  el.replaceChildren(...children);
  el.style.borderColor = MAP_FAMILY_COLORS[theme][card.leader];
  delete el.dataset.family;
  el.dataset.kind = 'venue';
  el.hidden = false;
  placeTooltip(el, clientX, clientY);
}
