/**
 * Sport registry (D-19). Adding MLB is one entry here plus an mlb-data.json
 * and a sports/mlb/index.js module; the build's sports meta decides which
 * entries are enabled on a given page.
 */
export const SPORTS = [
  {
    id: 'cfb',
    label: 'CFB',
    title: 'The Broadcast Ledger: college football broadcast crews and viewership',
  },
  {
    id: 'nfl',
    label: 'NFL',
    title: 'The Broadcast Ledger: NFL broadcast crews and special games',
    module: './nfl/index.js',
    data: 'nfl-data.json',
  },
  {
    id: 'mlb',
    label: 'MLB',
    title: 'The Broadcast Ledger: MLB national telecasts',
    module: './mlb/index.js',
    data: 'mlb-data.json',
  },
];

/**
 * Ids named by the meta's comma list that exist in SPORTS; CFB is always on.
 * @param {Element | null} metaEl
 * @returns {string[]}
 */
export function enabledSports(metaEl) {
  const known = new Set(SPORTS.map((s) => s.id));
  const listed = (metaEl?.getAttribute('content') ?? '')
    .split(',')
    .map((s) => s.trim())
    .filter((s) => known.has(s));
  return ['cfb', ...listed.filter((s) => s !== 'cfb')];
}

/**
 * The raw `sport` param when it is enabled, else 'cfb' (T-999.5-38).
 * @param {string} search
 * @param {string[]} enabled
 * @returns {string}
 */
export function resolveSport(search, enabled) {
  const raw = new URLSearchParams(search).get('sport');
  return raw !== null && enabled.includes(raw) ? raw : 'cfb';
}
