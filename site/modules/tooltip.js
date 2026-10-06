/**
 * Custom HTML hover tooltip (D-22, SITE-25, SITE-26): the default
 * `TOOLTIP_MODE` in `chart.js` swaps Plotly's own pseudo-HTML hover label
 * (which can't draw a filled background) for a small `position: fixed`
 * tooltip built here, positioned next to the hovered dot, whose network
 * names render as real `pill.js` pills instead of colored text.
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
  formatDate,
  formatKickoff,
  formatMatchup,
  formatViewers,
  namedGameInfo,
  noRatingLine,
  stripNetworkNote,
} from './format.js';
import { makeGameTypeIcon } from './icons.js';
import { makePill, makeRolePill, nameWithRoles, roleKey, ROLE_PILL_TEXT } from './pill.js';
import { FAMILY_COLORS, familyKey } from './palette.js';

/** The single `#chart-tooltip` element, created lazily on first use. */
let tooltipEl = null;

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
 * value, and a closing "Click for details →" hint. Conferences, the time
 * slot, the full outlet list, the measurement-type badge, era/event flags,
 * and any scoring-source note are panel-only (SITE-25) -- never repeated
 * here. `dateText` is the date and kickoff only; `gameType` the named-game
 * marker, which `renderTooltipContent` draws as decorative `icons` followed by
 * the visible `text` on its own line (`chart.js#hoverText`, the text-only
 * fallback that can't draw an SVG, puts `text` on its own line too).
 * @param {object} data - a `prepareData` result.
 * @param {number} i - telecast index.
 * @param {{axis: "spread"|"excitement", selected?: Set<number>}} opts
 * @returns {{crew: {name: string, role: string, selected: boolean}[], title: string, dateText: string, gameType: {icons: ("bowl"|"playoff"|"rivalry")[], text: string}|null, networks: {name: string, family: string}[], crewLines: string[], viewersLine: string, axisLine: string, hint: string}}
 */
export function tooltipModel(data, i, { axis, selected = new Set() }) {
  const t = data.t;

  const title = formatMatchup(data, i, { withScore: true });

  const dateText = [formatDate(t.date[i]), formatKickoff(t.kickoff[i]) ?? 'Kickoff time not recorded'].join(' · ');
  const gameType = namedGameInfo(data, i);

  const primaryNetwork = data.lookups.networks[t.network[i]];
  const otherOutlets = t.outlets[i]
    .filter((idx) => idx !== t.network[i])
    .map((idx) => data.lookups.networks[idx]);
  const networks = [primaryNetwork, ...otherOutlets].map((net) => ({
    name: stripNetworkNote(net.name),
    family: net.family,
  }));

  const crew = crewEntries(data, i, { mainOnly: true, selected });
  const crewLines = crew.map((entry) => `${entry.name} (${ROLE_PILL_TEXT[roleKey(entry.role)]})`);
  if (crewLines.length === 0) crewLines.push('Crew not recorded');

  const viewersLine = data.rated[i] ? `Viewers: ${formatViewers(t.viewers[i])}` : noRatingLine(data, i);
  const axisLine = axisValueText(data, i, axis);
  const hint = 'Click for details →';

  return { title, dateText, gameType, networks, crew, crewLines, viewersLine, axisLine, hint };
}

/**
 * Rebuilds `el`'s children from `model` (`replaceChildren`, never an
 * incremental append) -- a title, a space-separated row of `pill.js` pills
 * (SITE-26, D-29 -- the `.tooltip-networks` flex row's own gap is the only
 * visible separator between pills, no separator element or text), one line
 * per date/crew/viewers/axis fact, and a closing hint. Every string is
 * assigned via `textContent`/`makePill` (which itself only uses
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
  model.networks.forEach((net) => {
    networksRow.appendChild(makePill(net.name, net.family, theme));
  });
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
    box.className = 'crew-box';
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

  const viewersLine = document.createElement('div');
  viewersLine.textContent = model.viewersLine;
  children.push(viewersLine);

  const axisLine = document.createElement('div');
  axisLine.textContent = model.axisLine;
  children.push(axisLine);

  const hint = document.createElement('div');
  hint.className = 'tooltip-hint';
  hint.textContent = model.hint;
  children.push(hint);

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
 * @param {{axis: "spread"|"excitement", theme: "light"|"dark", clientX: number, clientY: number}} opts
 */
export function showTooltip(data, i, { axis, theme, clientX, clientY, selected }) {
  const el = ensureTooltipEl();
  renderTooltipContent(el, tooltipModel(data, i, { axis, selected }), theme);
  el.hidden = false;

  placeTooltip(el, clientX, clientY);
}

/** Hides the tooltip (a no-op before the first `showTooltip` call). */
export function hideTooltip() {
  if (tooltipEl) tooltipEl.hidden = true;
}
