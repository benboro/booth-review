/**
 * URL query-string state encoding/decoding (SITE-12, UI-SPEC URL scheme).
 * DOM-free; imports only from ./select.js. `decodeState` never throws --
 * it allowlists every param against `data`'s own lookups and fixed enums,
 * dropping anything unrecognized (T-04-05).
 *
 * Encoding and decoding are symmetric: `encodeState` percent-encodes each
 * list piece on its own and joins them with a literal `,`; `decodeState`
 * reads the *raw* (still-encoded) query, splits a list on the literal `,`
 * first, then percent-decodes each piece exactly once. So an id holding a
 * comma (`%2C`) is never split in two, and a malformed escape (e.g. a lone
 * `%`) just drops that one value instead of throwing `URIError`.
 *
 * Params (SITE-12, D-09..D-19): `people`, `mode`, `role`, `conferences`
 * (comma-separated names, ordered/filtered by `data.fbsConferences`),
 * `school` (comma-separated team slugs, ordered by team index), `postseason`
 * (`exclude`/`only`; omitted at the default `all`), `seasons`, `networks`,
 * `slot`, `axis`, `view` (`bars`/`butterfly`), `by` (`network`/`team`/`conference`);
 * each of the last two is omitted at its default (D-13). The old `bars` and
 * `group` params are ignored (04.6 D-27). There is no `team` param on encode -- `school` replaces
 * it (D-11, Pitfall 4). The legacy `team` param is still *decoded*: a valid
 * slug is unioned into `school` (legacy first) through the exact same path
 * a fresh `school` value takes, so an old shared link fades rather than
 * highlights, matching a School-filter selection made through the UI.
 */

import { MAX_COMPARE, defaultState } from './select.js';

/** Canonical time-slot order used both for encoding and decoding the `slot` param. */
const SLOT_ORDER = ['noon', 'afternoon', 'prime', 'late'];

/** Whether a network id array equals the full set of primary network ids, order-independent. */
function isAllPrimaryNetworks(networkIds, allPrimaryIds) {
  return (
    networkIds.length === allPrimaryIds.length &&
    allPrimaryIds.every((id) => networkIds.includes(id))
  );
}

/**
 * Encodes selection/filter state into a query string. Every param is
 * omitted at its default value, so the default state encodes to `''`
 * (D-12).
 * @param {object} state - shaped like `defaultState(data)`.
 * @param {object} data - a `prepareData` result.
 * @returns {string} e.g. "" or "?people=dale-harlow&axis=excitement".
 */
export function encodeState(state, data) {
  const params = [];

  if (state.people.length > 0) {
    params.push(['people', state.people.map(encodeURIComponent).join(',')]);
  }

  const modeParts = [];
  if (state.compare) modeParts.push('compare');
  if (state.together) modeParts.push('together');
  if (modeParts.length > 0) params.push(['mode', modeParts.join(',')]);

  if (state.role != null) params.push(['role', state.role]);

  if (state.conferences.length > 0) {
    const ordered = data.fbsConferences.filter((name) => state.conferences.includes(name));
    params.push(['conferences', ordered.map(encodeURIComponent).join(',')]);
  }

  if (state.school.length > 0) {
    const ordered = data.teamSlugs.filter((slug) => state.school.includes(slug));
    params.push(['school', ordered.map(encodeURIComponent).join(',')]);
  }

  if (state.postseason !== 'all') params.push(['postseason', state.postseason]);

  if (
    state.seasons != null &&
    !(state.seasons[0] === data.seasonMin && state.seasons[1] === data.seasonMax)
  ) {
    params.push(['seasons', `${state.seasons[0]}-${state.seasons[1]}`]);
  }

  if (state.networks !== null) {
    if (state.networks.length === 0) {
      params.push(['networks', 'none']);
    } else {
      const allPrimaryIds = data.primaryNetworks.map((idx) => data.lookups.networks[idx].id);
      if (!isAllPrimaryNetworks(state.networks, allPrimaryIds)) {
        params.push(['networks', state.networks.map(encodeURIComponent).join(',')]);
      }
    }
  }

  if (state.slots != null) {
    const ordered = SLOT_ORDER.filter((slot) => state.slots.includes(slot));
    params.push(['slot', ordered.join(',')]);
  }

  if (state.axis === 'result' || state.axis === 'excitement') params.push(['axis', state.axis]);
  if (state.view === 'bars' || state.view === 'butterfly') params.push(['view', state.view]);
  if (state.by) params.push(['by', state.by]);

  if (params.length === 0) return '';
  return `?${params.map(([key, value]) => `${key}=${value}`).join('&')}`;
}

/**
 * Percent-decodes one raw query component exactly once (`+` reads as a
 * space, as in form encoding), returning null instead of throwing on a
 * malformed escape such as a lone `%` (CR-01).
 * @param {string} s
 * @returns {string|null}
 */
function safeDecode(s) {
  try {
    return decodeURIComponent(s.replace(/\+/g, ' '));
  } catch {
    return null;
  }
}

/**
 * Splits a query string into its *raw* (still percent-encoded) values by
 * decoded key, keeping the first occurrence of each key the way
 * `URLSearchParams#get` does. Values stay encoded so list params can be
 * split on their literal `,` separator before any decoding.
 * @param {string|null|undefined} search - with or without a leading `?`.
 * @returns {Map<string, string>}
 */
function rawParams(search) {
  const params = new Map();
  const query = String(search ?? '').replace(/^\?/, '');
  for (const part of query.split('&')) {
    if (part === '') continue;
    const eq = part.indexOf('=');
    const key = safeDecode(eq === -1 ? part : part.slice(0, eq));
    if (key == null || params.has(key)) continue;
    params.set(key, eq === -1 ? '' : part.slice(eq + 1));
  }
  return params;
}

/** Decodes a raw scalar param once; a missing param stays null, a malformed one reads as ''. */
function scalarParam(params, key) {
  const raw = params.get(key);
  if (raw == null) return null;
  return safeDecode(raw) ?? '';
}

/** Decodes the `people` param: unknown ids dropped, duplicates dropped, first-seen order kept. */
function decodePeople(raw, data) {
  if (!raw) return [];
  const seen = new Set();
  const ids = [];
  for (const piece of raw.split(',')) {
    const id = safeDecode(piece);
    if (id == null || !data.personIndexById.has(id) || seen.has(id)) continue;
    seen.add(id);
    ids.push(id);
  }
  return ids;
}

/** Decodes the `mode` param into {compare, together}, ignoring unknown tokens. */
function decodeMode(raw) {
  let compare = false;
  let together = false;
  if (raw) {
    for (const part of raw.split(',')) {
      if (part === 'compare') compare = true;
      else if (part === 'together') together = true;
    }
  }
  return { compare, together };
}

/**
 * Decodes the `seasons` param onto seasons that actually exist in the data
 * (the only values the season `<select>`s offer): the start snaps up and the
 * end snaps down to the nearest data season. A range that holds no data
 * season at all (e.g. entirely past the last season, or inside a gap) falls
 * back to unfiltered rather than an inverted range or a value neither select
 * can show (WR-13).
 */
function decodeSeasons(raw, data) {
  if (!raw) return null;
  const match = /^(-?\d+)-(-?\d+)$/.exec(raw);
  if (!match) return null;
  let a = Number(match[1]);
  let b = Number(match[2]);
  if (a > b) [a, b] = [b, a];
  const from = data.seasons.find((season) => season >= a);
  const to = data.seasons.findLast((season) => season <= b);
  if (from === undefined || to === undefined || from > to) return null;
  if (from === data.seasonMin && to === data.seasonMax) return null;
  return [from, to];
}

/** Decodes the `networks` param: 'none' -> [], unknown ids dropped, all/none -> null. */
function decodeNetworks(raw, data) {
  if (raw == null) return null;
  if (raw === 'none') return [];
  const ids = [];
  for (const piece of raw.split(',')) {
    const id = safeDecode(piece);
    if (id != null && data.networkIndexById.has(id) && !ids.includes(id)) ids.push(id);
  }
  const canonical = data.lookups.networks.map((net) => net.id).filter((id) => ids.includes(id));
  if (canonical.length === 0) return null;
  const allPrimaryIds = data.primaryNetworks.map((idx) => data.lookups.networks[idx].id);
  if (isAllPrimaryNetworks(canonical, allPrimaryIds)) return null;
  return canonical;
}

/** Decodes the `slot` param: unknown values dropped, canonicalized to noon/afternoon/prime/late order. */
function decodeSlots(raw) {
  if (!raw) return null;
  const pieces = raw.split(',');
  const ordered = SLOT_ORDER.filter((slot) => pieces.includes(slot));
  return ordered.length > 0 ? ordered : null;
}

/** Decodes the `conferences` param (D-10): unknown/FCS names dropped, deduped, canonicalized to `data.fbsConferences` order. */
function decodeConferences(raw, data) {
  if (!raw) return [];
  const names = [];
  for (const piece of raw.split(',')) {
    const name = safeDecode(piece);
    if (name != null && data.fbsConferences.includes(name) && !names.includes(name)) names.push(name);
  }
  return data.fbsConferences.filter((name) => names.includes(name));
}

/** Decodes the `school` param (D-11): unknown slugs dropped, deduped, canonicalized to team-index order. */
function decodeSchool(raw, data) {
  if (!raw) return [];
  const slugs = [];
  for (const piece of raw.split(',')) {
    const slug = safeDecode(piece);
    if (slug != null && data.teamIndexBySlug.has(slug) && !slugs.includes(slug)) slugs.push(slug);
  }
  return data.teamSlugs.filter((slug) => slugs.includes(slug));
}

/**
 * Decodes a query string into a selection/filter state, validated against
 * `data`'s own lookups. Never throws on malformed input; unrecognized
 * values fall back to their default (T-04-05).
 * @param {string} search - a query string, with or without a leading `?`.
 * @param {object} data - a `prepareData` result.
 * @returns {object} shaped like `defaultState(data)`.
 */
export function decodeState(search, data) {
  const params = rawParams(search);
  const state = defaultState(data);

  // `people`/`networks` stay raw here: they're split on the literal `,`
  // before each piece is decoded (see the module header).
  state.people = decodePeople(params.get('people') ?? null, data);

  const { compare, together } = decodeMode(scalarParam(params, 'mode'));
  state.compare = state.people.length > MAX_COMPARE ? false : compare;
  // "Called together" (AND) only means something with 2+ people; below that
  // the toggle is disabled, so a stale `together` would be stuck on and
  // silently switch the next added person to AND (WR-12). setState goes
  // through here too, so removing a person clears it.
  state.together = together && state.people.length >= 2;

  const rawRole = scalarParam(params, 'role');
  state.role = rawRole === 'pbp' || rawRole === 'analyst' ? rawRole : null;

  state.conferences = decodeConferences(params.get('conferences') ?? null, data);

  // Legacy Phase 4 `?team=<slug>` link (Pitfall 4): a valid slug is unioned
  // into `school` -- legacy first -- so it takes the exact same fade-filter
  // path a fresh School selection does. There is no separate "highlight"
  // code path for it; `state.team` no longer exists (D-11).
  state.school = decodeSchool(params.get('school') ?? null, data);
  const teamSlug = scalarParam(params, 'team');
  if (teamSlug != null && data.teamIndexBySlug.has(teamSlug) && !state.school.includes(teamSlug)) {
    state.school = [teamSlug, ...state.school];
  }

  const rawPostseason = scalarParam(params, 'postseason');
  state.postseason = rawPostseason === 'exclude' || rawPostseason === 'only' ? rawPostseason : 'all';

  state.seasons = decodeSeasons(scalarParam(params, 'seasons'), data);
  state.networks = decodeNetworks(params.get('networks') ?? null, data);
  state.slots = decodeSlots(scalarParam(params, 'slot'));
  const rawAxis = scalarParam(params, 'axis');
  state.axis = rawAxis === 'result' || rawAxis === 'excitement' ? rawAxis : 'pregame';
  // view/by are enum-allowlisted but never checked for applicability
  // (D-12): a stale `?view=bars` must survive a setState round trip.
  const rawView = scalarParam(params, 'view');
  state.view = rawView === 'bars' || rawView === 'butterfly' ? rawView : 'scatter';
  const rawBy = scalarParam(params, 'by');
  state.by = ['network', 'team', 'conference'].includes(rawBy) ? rawBy : null;

  return state;
}
