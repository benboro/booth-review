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

const ESPN_PLUS = { file: 'logos/espn-plus.svg', width: 70, height: 14, box: 'wordmark', darkFile: 'logos/dark/espn-plus.svg' };

/**
 * @type {Map<string, {file: string, width: number, height: number, box: 'wordmark'|'badge', darkFile: string}>}
 */
// One mark for both ids: college football says nfl-network, the NFL and MLB files say nfln.
const NFL_NETWORK = { file: 'logos/nfl-network.svg', width: 51, height: 20, box: 'badge', darkFile: 'logos/dark/nfl-network.svg' };

// SEC Network+ changed marks in 2024 (user, 2026-11-16): a game shows the mark its season used,
// like the conference logos (conf-logos.js). SEC Network keeps its 2014 mark for every season:
// the 2024 Commons file is CC BY 4.0 with no author on record (user, 2026-11-16).
const SEC_NETWORK_PLUS_2014 = { file: 'logos/sec-network-plus.svg', width: 48, height: 20, box: 'badge', darkFile: 'logos/dark/sec-network-plus.svg' };
const SEC_NETWORK_PLUS_2024 = { file: 'logos/sec-network-plus-2024.svg', width: 48, height: 20, box: 'badge', darkFile: 'logos/dark/sec-network-plus-2024.svg' };

const LOGOS = new Map([
  ['abc', { file: 'logos/abc.svg', width: 20, height: 20, box: 'badge', darkFile: 'logos/dark/abc.svg' }],
  ['cbs', { file: 'logos/cbs.svg', width: 49, height: 14, box: 'wordmark', darkFile: 'logos/dark/cbs.svg' }],
  ['cbs-sports-network', { file: 'logos/cbs-sports-network.svg', width: 78, height: 20, box: 'badge', darkFile: 'logos/dark/cbs-sports-network.svg' }],
  ['cw', { file: 'logos/cw.svg', width: 32, height: 14, box: 'wordmark', darkFile: 'logos/dark/cw.svg' }],
  ['espn', { file: 'logos/espn.svg', width: 57, height: 14, box: 'wordmark', darkFile: 'logos/dark/espn.svg' }],
  ['espn-plus', ESPN_PLUS],
  ['espn_plus', ESPN_PLUS],
  ['espn2', { file: 'logos/espn2.svg', width: 74, height: 14, box: 'wordmark', darkFile: 'logos/dark/espn2.svg' }],
  ['espn3', { file: 'logos/espn3.svg', width: 75, height: 14, box: 'wordmark', darkFile: 'logos/dark/espn3.svg' }],
  ['espnews', { file: 'logos/espnews.svg', width: 100, height: 14, box: 'wordmark', darkFile: 'logos/dark/espnews.svg' }],
  ['espnu', { file: 'logos/espnu.svg', width: 20, height: 20, box: 'badge', darkFile: 'logos/dark/espnu.svg' }],
  ['acc-network', { file: 'logos/acc-network.svg', width: 48, height: 14, box: 'wordmark', darkFile: 'logos/dark/acc-network.svg' }],
  ['sec-network', { file: 'logos/sec-network.svg', width: 39, height: 20, box: 'badge', darkFile: 'logos/dark/sec-network.svg' }],
  ['sec-network-plus', SEC_NETWORK_PLUS_2024],
  ['fox', { file: 'logos/fox.svg', width: 33, height: 14, box: 'wordmark', darkFile: 'logos/dark/fox.svg' }],
  ['fs1', { file: 'logos/fs1.svg', width: 26, height: 14, box: 'wordmark', darkFile: 'logos/dark/fs1.svg' }],
  ['fs2', { file: 'logos/fs2.svg', width: 28, height: 14, box: 'wordmark', darkFile: 'logos/dark/fs2.svg' }],
  ['nbc', { file: 'logos/nbc.svg', width: 57, height: 14, box: 'wordmark', darkFile: 'logos/dark/nbc.svg' }],
  ['usa-network', { file: 'logos/usa-network.svg', width: 32, height: 14, box: 'wordmark', darkFile: 'logos/dark/usa-network.svg' }],
  ['tbs', { file: 'logos/tbs.svg', width: 26, height: 14, box: 'wordmark', darkFile: 'logos/dark/tbs.svg' }],
  ['tnt', { file: 'logos/tnt.svg', width: 20, height: 20, box: 'badge', darkFile: 'logos/dark/tnt.svg' }],
  ['big-ten-network', { file: 'logos/big-ten-network.svg', width: 33, height: 20, box: 'badge', darkFile: 'logos/dark/big-ten-network.svg' }],
  ['peacock', { file: 'logos/peacock.svg', width: 56, height: 14, box: 'wordmark', darkFile: 'logos/dark/peacock.svg' }],
  ['prime', { file: 'logos/prime.svg', width: 34, height: 20, box: 'badge', darkFile: 'logos/dark/prime.svg' }],
  ['netflix', { file: 'logos/netflix.svg', width: 52, height: 14, box: 'wordmark', darkFile: 'logos/dark/netflix.svg' }],
  ['apple', { file: 'logos/apple.svg', width: 37, height: 14, box: 'wordmark', darkFile: 'logos/dark/apple.svg' }],
  ['paramount-plus', { file: 'logos/paramount-plus.svg', width: 61, height: 14, box: 'wordmark', darkFile: 'logos/dark/paramount-plus.svg' }],
  ['mountain-west-network', { file: 'logos/mountain-west-network.png', width: 31, height: 24, box: 'badge', darkFile: 'logos/dark/mountain-west-network.png' }],
  ['youtube', { file: 'logos/youtube.svg', width: 65, height: 14, box: 'wordmark', darkFile: 'logos/dark/youtube.svg' }],
  ['youtube-tv', { file: 'logos/youtube-tv.svg', width: 79, height: 14, box: 'wordmark', darkFile: 'logos/dark/youtube-tv.svg' }],
  ['nfl-network', NFL_NETWORK],
  ['nfln', NFL_NETWORK],
  ['nbcsn', { file: 'logos/nbcsn.svg', width: 68, height: 14, box: 'wordmark', darkFile: 'logos/dark/nbcsn.svg' }],
]);

/**
 * Network id -> [[first season, entry], ...], oldest era first, for a network whose mark
 * changed. LOGOS holds each one's newest entry, used when no season is given.
 * @type {Map<string, Array<[number, {file: string, width: number, height: number, box: 'wordmark'|'badge', darkFile: string}]>>}
 */
const ERAS = new Map([
  ['sec-network-plus', [[2014, SEC_NETWORK_PLUS_2014], [2024, SEC_NETWORK_PLUS_2024]]],
]);

/**
 * Returns the logo entry for a network id, or null when it has none. A network with eras
 * gives the mark of `season`'s era; a missing season gives the newest mark, and a season
 * before the first era gives the first.
 * @param {unknown} id - a `lookups.networks[].id` value.
 * @param {number|null|undefined} [season] - the game's season
 * @returns {{file: string, width: number, height: number, box: 'wordmark'|'badge', darkFile: string}|null}
 */
export function logoFor(id, season) {
  const key = String(id);
  if (!LOGOS.has(key)) return null;
  if (!ERAS.has(key) || season === null || season === undefined || season === ''
    || !Number.isFinite(Number(season))) {
    return LOGOS.get(key);
  }
  const year = Number(season);
  const eras = ERAS.get(key);
  let entry = eras[0][1];
  for (const [from, era] of eras) {
    if (from <= year) entry = era;
  }
  return entry;
}
