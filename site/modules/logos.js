/**
 * Network logo map (SHELL-05): which network ids have a vendored mark under
 * site/logos/ and how large to draw it. Wordmarks render 14px high and badges
 * 20px high; each width is that height scaled by the file's viewBox, with no
 * width cap (13-LOGO-LINKS render boxes). Ids without an entry fall back to a
 * family dot plus the name (see network.js).
 *
 * Lookup goes through a Map with a has() check, never a bracket lookup on row
 * text, so "__proto__" or "constructor" can never resolve (T-13-08).
 */

const ESPN_PLUS = { file: 'logos/espn-plus.svg', width: 70, height: 14, box: 'wordmark' };

/**
 * @type {Map<string, {file: string, width: number, height: number, box: 'wordmark'|'badge'}>}
 */
const LOGOS = new Map([
  ['abc', { file: 'logos/abc.svg', width: 20, height: 20, box: 'badge' }],
  ['cbs', { file: 'logos/cbs.svg', width: 49, height: 14, box: 'wordmark' }],
  ['cbs-sports-network', { file: 'logos/cbs-sports-network.svg', width: 78, height: 20, box: 'badge' }],
  ['cw', { file: 'logos/cw.svg', width: 32, height: 14, box: 'wordmark' }],
  ['espn', { file: 'logos/espn.svg', width: 57, height: 14, box: 'wordmark' }],
  ['espn-plus', ESPN_PLUS],
  ['espn_plus', ESPN_PLUS],
  ['espn2', { file: 'logos/espn2.svg', width: 74, height: 14, box: 'wordmark' }],
  ['espn3', { file: 'logos/espn3.svg', width: 75, height: 14, box: 'wordmark' }],
  ['espnews', { file: 'logos/espnews.svg', width: 100, height: 14, box: 'wordmark' }],
  ['espnu', { file: 'logos/espnu.svg', width: 20, height: 20, box: 'badge' }],
  ['acc-network', { file: 'logos/acc-network.svg', width: 48, height: 14, box: 'wordmark' }],
  ['sec-network', { file: 'logos/sec-network.svg', width: 39, height: 20, box: 'badge' }],
  ['fox', { file: 'logos/fox.svg', width: 33, height: 14, box: 'wordmark' }],
  ['fs1', { file: 'logos/fs1.svg', width: 26, height: 14, box: 'wordmark' }],
  ['fs2', { file: 'logos/fs2.svg', width: 28, height: 14, box: 'wordmark' }],
  ['nbc', { file: 'logos/nbc.svg', width: 57, height: 14, box: 'wordmark' }],
  ['usa-network', { file: 'logos/usa-network.svg', width: 32, height: 14, box: 'wordmark' }],
  ['tbs', { file: 'logos/tbs.svg', width: 26, height: 14, box: 'wordmark' }],
  ['tnt', { file: 'logos/tnt.svg', width: 20, height: 20, box: 'badge' }],
  ['big-ten-network', { file: 'logos/big-ten-network.svg', width: 33, height: 20, box: 'badge' }],
  ['peacock', { file: 'logos/peacock.svg', width: 56, height: 14, box: 'wordmark' }],
  ['prime', { file: 'logos/prime.svg', width: 45, height: 14, box: 'wordmark' }],
  ['apple', { file: 'logos/apple.svg', width: 37, height: 14, box: 'wordmark' }],
  ['nbcsn', { file: 'logos/nbcsn.svg', width: 68, height: 14, box: 'wordmark' }],
]);

/**
 * Returns the logo entry for a network id, or null when it has none.
 * @param {unknown} id - a `lookups.networks[].id` value.
 * @returns {{file: string, width: number, height: number, box: 'wordmark'|'badge'}|null}
 */
export function logoFor(id) {
  const key = String(id);
  return LOGOS.has(key) ? LOGOS.get(key) : null;
}
