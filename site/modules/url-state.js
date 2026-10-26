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
 * `slot`, `axis` (`excitement`/`date`; Spread is the default and is omitted), `y`
 * (`excitement`/`points`/`margin`; Viewers is the default and is omitted; y wins over `axis=excitement`, 04.15 D-12), `view` (`bars`/`butterfly`/`map`/`crews`/`weekend`), `week` and `day` (This weekend, Phase 18), `by` (`network`/`team`/`conference`);
 * each of the last two is omitted at its default (D-13). `h2h` (`1`, only with
 * exactly two schools; omitted at Either team) and `dots` (`hide`; omitted at
 * the Fade default; 04.7 D-10, D-14). `game` (one named-game slug: a bowl franchise,
 * a rivalry, or a CFP round; allowlisted against `data.gameIndexBySlug`; omitted when
 * no game is picked; 04.9 D-20). `venue` (one venue or abroad-group slug, allowlisted against
 * `data.venueIndexesByKey`; omitted when none; Phase 11 D-05) (an old `colors` param is ignored; colours are always on, Phase 17.1 D-07). The Crews params (Phase 14 D-06..D-10), view-agnostic like `by` so a
 * stale `?view=scatter&crew=...` survives a setState round trip: `crew` (a pooled crew key, allowlisted
 * by `CREW_KEY_RE` and by existence in `crewIndex(data).crews`; dropped when `people` is present, A7),
 * `cmode` (`pbp`/`analyst`; Crew is the omitted default), `perseason` (`0` = pooled; Per season is the omitted default since Phase 14 Plan 10, and a
 * one-season range applies it as pooled without storing that) and `csort` (`<key>` or `<key>.asc|desc`; omitted at the default of the stored Per season preference, Season newest first or Games descending, so a chosen sort survives a one-season range; `rank`
 * only in Crew mode, `season` only with Per season on, A8). `booth` (`a`,`b`,`other`, canonical order; omitted when no
 * tier is picked; Phase 10 D-12). The old `bars` and
 * `group` params are ignored (04.6 D-27). There is no `team` param on encode -- `school` replaces
 * it (D-11, Pitfall 4). The legacy `team` param is still *decoded*: a valid
 * slug is unioned into `school` (legacy first) through the exact same path
 * a fresh `school` value takes, so an old shared link fades rather than
 * highlights, matching a School-filter selection made through the UI.
 */

import { MAX_COMPARE, defaultState } from './select.js';
import { CREW_KEY_RE, NATURAL_DIR, crewIndex, defaultSort } from './crew-groups.js';
import { DAY_TOKENS, decodeDay, decodeWeek } from './weekend-state.js';

/** Canonical time-slot order used both for encoding and decoding the `slot` param. */
// Y measures a link may name; Viewers is the default and is never encoded (04.17 D-19).
const Y_VALUES = ['excitement', 'points', 'margin'];
// Crews table sort keys a link may name (Phase 14). The default depends on the mode: Season newest
// first (then Games called) when rows are per season, else Games called descending; it encodes to nothing.
const CSORT_RE = /^(crew|season|rank|network|games|exc|viewers)(\.(asc|desc))?$/;
// Booth tiers in canonical order (Phase 10 D-12).
const BOOTH_ORDER = ['a', 'b', 'other'];
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
  if (state.h2h === true && state.school.length === 2) params.push(['h2h', '1']);

  if (state.postseason !== 'all') params.push(['postseason', state.postseason]);
  if (state.booth.length > 0) {
    const ordered = BOOTH_ORDER.filter((tier) => state.booth.includes(tier));
    if (ordered.length > 0) params.push(['booth', ordered.join(',')]);
  }
  if (state.game != null) params.push(['game', encodeURIComponent(state.game)]);
  if (state.venue != null) params.push(['venue', encodeURIComponent(state.venue)]);

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

  if (state.axis === 'excitement' || state.axis === 'date') params.push(['axis', state.axis]);
  if (Y_VALUES.includes(state.y)) params.push(['y', state.y]);
  if (state.view === 'bars' || state.view === 'butterfly' || state.view === 'map' || state.view === 'crews' || state.view === 'weekend') params.push(['view', state.view]);
  // This weekend (Phase 18): the stepper's week number and the day token, each omitted at its
  // default (the current weekend, the sport's default day) and validated again on decode.
  if (Number.isInteger(state.week)) params.push(['week', String(state.week)]);
  if (DAY_TOKENS.includes(state.day)) params.push(['day', state.day]);
  if (state.by) params.push(['by', state.by]);
  if (state.dots === 'hide') params.push(['dots', 'hide']);
  if (state.crew != null) params.push(['crew', state.crew]);
  if (state.cmode === 'pbp' || state.cmode === 'analyst') params.push(['cmode', state.cmode]);
  if (state.perseason === false) params.push(['perseason', '0']);
  if (state.csort != null && CSORT_RE.test(state.csort.key)) {
    const { key, dir } = state.csort;
    const natural = NATURAL_DIR[key];
    // The default follows the stored Per season preference, not the range, so a chosen
    // `csort=games` survives a one-season range and is still there when it widens.
    const def = defaultSort(state.perseason !== false);
    const isDefault = key === def.key && dir === def.dir;
    if (!isDefault) params.push(['csort', dir === natural ? key : `${key}.${dir}`]);
  }

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

/** Decodes the `booth` param (D-12): exact tokens a, b, other only, deduped, canonical order. */
function decodeBooth(raw) {
  if (!raw) return [];
  const pieces = raw.split(',');
  return BOOTH_ORDER.filter((tier) => pieces.includes(tier));
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

  // Head-to-head only means something with exactly two (already allowlisted)
  // schools; checked after the legacy `team` union so the count is final. A
  // stale h2h snaps back through setState and is not restored (04.7 D-12).
  state.h2h = scalarParam(params, 'h2h') === '1' && state.school.length === 2;

  const rawPostseason = scalarParam(params, 'postseason');
  state.postseason = rawPostseason === 'exclude' || rawPostseason === 'only' ? rawPostseason : 'all';
  state.booth = decodeBooth(scalarParam(params, 'booth'));
  const rawGame = scalarParam(params, 'game');
  state.game = rawGame != null && data.gameIndexBySlug.has(rawGame) ? rawGame : null;
  const rawVenue = scalarParam(params, 'venue');
  state.venue = rawVenue != null && data.venueIndexesByKey?.has(rawVenue) ? rawVenue : null;

  state.seasons = decodeSeasons(scalarParam(params, 'seasons'), data);
  state.networks = decodeNetworks(params.get('networks') ?? null, data);
  state.slots = decodeSlots(scalarParam(params, 'slot'));
  const rawAxis = scalarParam(params, 'axis');
  state.axis = ['excitement', 'date'].includes(rawAxis) ? rawAxis : 'spread';
  const rawY = scalarParam(params, 'y');
  state.y = Y_VALUES.includes(rawY) ? rawY : 'viewers';
  // D-12: a non-default y in a link was picked on purpose, so it wins and x falls back to Spread.
  if (state.y === 'excitement' && state.axis === 'excitement') state.axis = 'spread';
  // view/by are enum-allowlisted but never checked for applicability
  // (D-12): a stale `?view=bars` must survive a setState round trip.
  const rawView = scalarParam(params, 'view');
  state.view = rawView === 'bars' || rawView === 'butterfly' || rawView === 'map' || rawView === 'crews' ? rawView : 'scatter';
  // The This weekend tab exists only when the build ships weeks (no weeks, no tab).
  if (rawView === 'weekend' && (data.weeks ?? []).length > 0) state.view = 'weekend';
  // This weekend (Phase 18, D-07, D-23): week and day are allowlisted against the shipped weeks
  // and that week's games; anything else, and a value equal to the default, drops (T-18-31).
  state.week = decodeWeek(scalarParam(params, 'week'), data);
  state.day = decodeDay(scalarParam(params, 'day'), data, state.week);
  const rawBy = scalarParam(params, 'by');
  state.by = ['network', 'team', 'conference'].includes(rawBy) ? rawBy : null;
  // Fade is the default; only the literal 'hide' selects Hide (04.7 D-10).
  state.dots = scalarParam(params, 'dots') === 'hide' ? 'hide' : 'fade';

  // Crews params (Phase 14). The crew index is built only when `crew` is present, so a crew-free
  // URL does no grouping work. A pick of people wins over a crew in the same link (A7, D-08).
  const rawCrew = scalarParam(params, 'crew');
  state.crew =
    rawCrew != null &&
    state.people.length === 0 &&
    CREW_KEY_RE.test(rawCrew) &&
    crewIndex(data).crews.has(rawCrew)
      ? rawCrew
      : null;
  const rawCmode = scalarParam(params, 'cmode');
  state.cmode = rawCmode === 'pbp' || rawCmode === 'analyst' ? rawCmode : 'crew';
  // Per season needs two or more seasons in the range to change anything (D-10).
  const lo = state.seasons ? state.seasons[0] : data.seasonMin;
  const hi = state.seasons ? state.seasons[1] : data.seasonMax;
  const seasonsInRange = data.seasons.filter((season) => season >= lo && season <= hi).length;
  // Per season is the default (14-10 checkpoint, 2026-10-23); only an explicit `0` pools. The state keeps
  // the preference even on a one-season range, where pooled and per-season rows are the same; the
  // consumers apply the two-season rule (`perSeasonApplies`).
  state.perseason = scalarParam(params, 'perseason') !== '0';
  const csortMatch = CSORT_RE.exec(scalarParam(params, 'csort') ?? '');
  state.csort = null;
  if (csortMatch) {
    const key = csortMatch[1];
    const dir = csortMatch[3] ?? NATURAL_DIR[key];
    const modeOk = key !== 'rank' || state.cmode === 'crew';
    const seasonOk = key !== 'season' || (state.perseason && seasonsInRange >= 2);
    const def = defaultSort(state.perseason);
    const isDefault = key === def.key && dir === def.dir;
    if (modeOk && seasonOk && !isDefault && NATURAL_DIR[key] !== undefined) state.csort = { key, dir };
  }

  return state;
}
