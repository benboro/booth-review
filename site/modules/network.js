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
 * Armed once, on the first dot or logo built.
 */
function watchTheme() {
  if (themeWatch) return;
  themeWatch = onThemeChange((theme) => {
    for (const dot of document.querySelectorAll('.net-dot[data-family]')) {
      dot.style.background = FAMILY_COLORS[theme][dot.dataset.family];
    }
    // Logo <img> cannot see page CSS, so a theme flip swaps to the generated dark file (D-09).
    // The id is a map key set from logoFor(); the Map lookup keeps data rows out of it (T-13-08).
    for (const img of document.querySelectorAll('img.net-logo[data-logo]')) {
      const logo = logoFor(img.dataset.logo);
      if (logo) img.src = theme === 'dark' ? logo.darkFile : logo.file;
    }
  });
}

/**
 * Network precedence (U7): the order networks take whenever several are shown together (an MLB
 * Postseason cell's outlets, a CFB panel's "Also on" list and tooltip row after the primary).
 * Within each family the broadcast network comes first, then cable from the most prominent
 * down, then streaming:
 *   FOX > FS1 > FS2 > Big Ten Network > Fox regional nets;
 *   ABC > ESPN > ESPN2 > ESPNEWS > ESPNU > ESPN Deportes > the conference nets > ESPN3 / ESPN+ /
 *     ESPN Unlimited / Disney+;
 *   NBC > USA Network > NBCSN > CNBC > NBC regional > Peacock;
 *   CBS > CBS Sports Network > Paramount+;
 *   TBS > TNT > truTV > Max;
 *   then The CW and Apple TV, the conference family (Pac-12, Mountain West, CUSA Digital), the
 *   regional sports networks, and the other family: local broadcast affiliates, then cable (MLB
 *   Network, NFL Network and the rest), then streaming (Prime Video, Netflix, YouTube, Yahoo and
 *   the school and digital services), then pay-per-view and unclassified.
 * The family blocks are not ordered against each other by tier (that question is open, G2). It
 * holds every network_id in data/reference/*networks.csv (tests/test_site_network_precedence.py
 * checks it); both the CFB ids (espn-plus, espn-unlimited, nfl-network) and the MLB / NFL ids
 * (espn_plus, espn_unltd, mlbn, nfln) are listed. A network not listed keeps its given order
 * after every listed one (the sort is stable). The user's pinned orderings: FOX before FS1, ABC
 * before ESPN before ESPN2 / ESPNEWS / ESPNU, NBC before Peacock.
 */
export const NETWORK_PRECEDENCE = Object.freeze([
  'fox', 'fs1', 'fs2', 'big-ten-network', 'fsn-regional', 'sun-sports', 'sportsouth',
  'abc', 'espn', 'espn2', 'espnews', 'espnu', 'espn_deportes', 'sec-network', 'acc-network',
  'longhorn-network', 'sec-network-plus', 'acc-network-extra', 'espn3', 'espn-plus', 'espn_plus',
  'espn-unlimited', 'espn_unltd', 'disney-plus', 'espn-gameplan', 'espn-radio', 'espn-mobile',
  'nbc', 'usa-network', 'nbcsn', 'cnbc', 'nbc-sports-bay-area', 'peacock', 'peacock_local',
  'cbs', 'cbs-sports-network', 'paramount-plus', 'cbs-sports-facebook',
  'tbs', 'tnt', 'trutv', 'max',
  'cw', 'apple',
  'pac-12-network', 'mountain-west-network', 'conference-usa-digital',
  'nesn', 'sny', 'bally-sports-regional', 'spectrum-sports-regional', 'altitude-sports',
  'root-att-sportsnet-mountain', 'root-att-sportsnet-pittsburgh', 'csn-houston',
  'comcast-sportsnet-nm', 'time-warner-cable-sports', 'nevada-sports-net', 'silver-state-sports',
  'swx-spokane', 'buckeye-cable-sports',
  'local-broadcast-affiliate', 'unimas',
  'mlbn', 'mlbn_alt', 'nfl-network', 'nfln', 'bein-sports', 'byutv', 'eleven-sports',
  'acc-network-legacy', 'american-sports-network', 'fcs-regional-network', 'jayhawk-network',
  'k-state-hd', 'team-1-sports',
  'prime', 'netflix', 'youtube', 'yahoo', 'stadium', 'flosports', 'barstool-sports',
  'campus-insiders', 'cyclones-tv', 'soonersports-tv', 'uconn-huskies-tv', 'uconn-plus',
  'wvusports-com',
  'directv-college-sports', 'hawaii-ppv', 'oklahoma-ppv', 'other-unclassified',
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
    img.dataset.logo = String(id);
    img.src = currentTheme() === 'dark' ? entry.darkFile : entry.file;
    watchTheme();
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
