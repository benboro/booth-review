/**
 * Network mark builder (SHELL-05): one place that turns a network into either
 * its vendored logo (an `<img>`, so SVG script can never run) or, for ids with
 * no logo, an 8px family dot plus the name. Call sites switch to this builder
 * instead of building network text or pills themselves.
 *
 * DOM is built only with createElement/textContent/setAttribute, and `src`
 * comes only from the logo map, never from row text (T-13-08).
 */

import { FAMILY_COLORS, familyKey } from './palette.js';
import { currentTheme, onThemeChange } from './theme.js';
import { logoFor } from './logos.js';

let themeWatch = null;

/**
 * Repaints every family dot on the page when data-theme changes, so dots in tables,
 * chips and open panels follow the theme hook, not only the active chart (SHELL-02).
 * Armed once, on the first dot built.
 */
function watchTheme() {
  if (themeWatch) return;
  themeWatch = onThemeChange((theme) => {
    for (const dot of document.querySelectorAll('.net-dot[data-family]')) {
      dot.style.background = FAMILY_COLORS[theme][dot.dataset.family];
    }
  });
}

/**
 * Network precedence (U7): the order networks take whenever several are shown together (an MLB
 * Postseason cell's outlets, a CFB panel's "Also on" list and tooltip row after the primary).
 * Within each family the broadcast network comes first, then cable from the most prominent
 * down, then streaming:
 *   FOX > FS1 > FS2 > Big Ten Network > Fox regional nets;
 *   ABC > ESPN > ESPN2 > ESPNEWS > ESPNU > the conference nets > ESPN3 / ESPN+ / Disney+;
 *   NBC > USA Network > NBCSN > NBC regional > Peacock;
 *   CBS > CBS Sports Network > Paramount+;
 *   TBS > TNT > truTV > Max;
 *   then The CW, Apple TV, MLB Network, NFL Network and Prime Video.
 * The family blocks are in the same order as the chart families. A network not listed keeps its
 * given order after every listed one (the sort is stable). The user's pinned orderings: FOX
 * before FS1, ABC before ESPN before ESPN2 / ESPNEWS / ESPNU, NBC before Peacock.
 */
export const NETWORK_PRECEDENCE = Object.freeze([
  'fox', 'fs1', 'fs2', 'big-ten-network', 'fsn-regional', 'sun-sports', 'sportsouth',
  'abc', 'espn', 'espn2', 'espnews', 'espnu', 'sec-network', 'acc-network', 'longhorn-network',
  'sec-network-plus', 'acc-network-extra', 'espn3', 'espn-plus', 'espn_plus', 'espn-unlimited',
  'disney-plus', 'espn-gameplan', 'espn-regional-insert',
  'nbc', 'usa-network', 'nbcsn', 'nbc-sports-bay-area', 'peacock',
  'cbs', 'cbs-sports-network', 'paramount-plus', 'cbs-sports-facebook',
  'tbs', 'tnt', 'trutv', 'max',
  'cw', 'apple', 'mlb-network', 'nfl-network', 'prime',
]);

const PRECEDENCE_RANK = new Map(NETWORK_PRECEDENCE.map((id, k) => [id, k]));

/**
 * A copy of `list` in network precedence (see NETWORK_PRECEDENCE); unlisted ids keep their
 * order after the listed ones.
 * @template {{id?: string}} T
 * @param {T[]} list
 * @returns {T[]}
 */
export function sortNetworks(list) {
  const rank = (net) => {
    const key = net && net.id != null ? String(net.id) : '';
    return PRECEDENCE_RANK.has(key) ? PRECEDENCE_RANK.get(key) : Infinity;
  };
  return list
    .map((net, k) => ({ net, k, r: rank(net) }))
    .sort((a, b) => (a.r === b.r ? a.k - b.k : a.r < b.r ? -1 : 1))
    .map((x) => x.net);
}

/**
 * Builds one network mark (`span.net-mark`).
 * @param {{id: string, name: string, family: string}} network
 * @param {{dot?: boolean}} [opts] - dot: draw the family dot before a fallback name
 *   (default true). A logo always stands alone: the dot is only the fallback's
 *   colour key, never drawn beside a logo (brief §5).
 * @returns {HTMLSpanElement}
 */
export function networkMark({ id, name, family }, { dot = true } = {}) {
  const mark = document.createElement('span');
  mark.className = 'net-mark';
  const entry = logoFor(id);
  if (dot && !entry) {
    const dotEl = document.createElement('span');
    dotEl.className = 'net-dot';
    const key = familyKey(family);
    dotEl.dataset.family = key;
    dotEl.style.background = FAMILY_COLORS[currentTheme()][key];
    watchTheme();
    mark.appendChild(dotEl);
  }
  if (entry) {
    const img = document.createElement('img');
    img.className = entry.box === 'badge' ? 'net-logo net-logo--badge' : 'net-logo';
    img.src = entry.file;
    img.alt = name;
    img.title = name;
    img.setAttribute('width', String(entry.width));
    img.setAttribute('height', String(entry.height));
    img.decoding = 'async';
    mark.appendChild(img);
  } else {
    const label = document.createElement('span');
    label.className = 'net-name';
    label.textContent = name;
    mark.appendChild(label);
  }
  return mark;
}

/**
 * Builds a `span.net-marks` holding one mark per network, in the given order
 * (primary first), for multi-network cells.
 * @param {Array<{id: string, name: string, family: string}>} list
 * @param {{dot?: boolean}} [opts]
 * @returns {HTMLSpanElement}
 */
export function networkMarks(list, opts) {
  const wrap = document.createElement('span');
  wrap.className = 'net-marks';
  for (const network of list) wrap.appendChild(networkMark(network, opts));
  return wrap;
}
