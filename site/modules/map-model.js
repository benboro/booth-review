// Map model (04.18 D-01..D-16): everything the Map tab draws, as plain data.
//
// DOM-free and pure: imports only ./palette.js and ./select.js and never touches
// window, document or Plotly. Every exported table is frozen. It turns `data`
// (prepareData), `view` (computeView) and `state` into projected venue points,
// subjects, season paths, curved legs, per-venue-per-family dots, faded dots, edge
// markers, tooltip lines and the copy strings. The chart module (map-chart.js) only
// paints this model; no family color lives here.
//
// Geometry: the map lives in a fixed 975 x 610 pixel space that matches the vendored
// us-atlas states-albers-10m outlines, i.e. d3-geo's
// geoAlbersUsa().scale(1300).translate([487.5, 305]), reimplemented below (conic equal
// area, lower 48 plus Hawaii and Alaska sub-projections). Reference outputs from
// d3-geo 3.1.1 are pinned in tests/e2e/test_site_map_model.py.

import {
  COMPARE_GLYPHS,
  COMPARE_SYMBOLS,
  FAMILY_LABELS,
  FAMILY_ORDER,
  SHARED_SYMBOL,
} from './palette.js';
import { MAX_COMPARE } from './select.js';
import { buildVenueModel, venueDotSize } from './map-venues.js';
import {
  ALBERS_SCALE,
  ALBERS_TRANSLATE,
  EDGE_ANCHORS,
  FALLBACK_ANCHORS,
  HAWAII_INSET,
  MAP_HEIGHT,
  MAP_WIDTH,
  placeVenue,
  placeVenues,
  projectAlbersUsa,
} from './map-geo.js';
export {
  ALBERS_SCALE,
  ALBERS_TRANSLATE,
  EDGE_ANCHORS,
  FALLBACK_ANCHORS,
  HAWAII_INSET,
  MAP_HEIGHT,
  MAP_WIDTH,
  placeVenue,
  placeVenues,
  projectAlbersUsa,
} from './map-geo.js';

// ---------------------------------------------------------------- constants

/** Quadratic-arc bow, as a fraction of the leg length, to the left of travel (D-13). */
export const MAP_ARC_BOW = 0.15;
const ARC_STEP = 20;
const ARC_MIN_SEGMENTS = 6;
const ARC_MAX_SEGMENTS = 24;

export const MAP_HINT =
  'Pick an announcer or a school to trace a path. Color shows which network airs the most games nearby.';
export const MAP_SHAPES_CAPTION = Object.freeze({
  school: 'Shapes shown for the first 4 schools',
  person: 'Shapes shown for the first 4 announcers',
});
export const MAP_EMPTY = Object.freeze({
  title: 'No games match these filters.',
  hint: 'Widen the season range or reset Seasons.',
});
export const MAP_ERROR = Object.freeze({
  title: 'The map could not be drawn.',
  hint: 'Reload the page, or use the table below.',
});

/** Note under the map for games whose venue has no usable location (D-16). */
export function noLocationNote(n) {
  return n === 1 ? '1 game has no venue location' : `${n} games have no venue location`;
}

/** Accessible name of the map figure. */
export function mapAriaLabel(n) {
  return `Map of ${n} game venues`;
}


// ---------------------------------------------------------------- arcs

/**
 * Quadratic arc from a to b bowing to the left of travel (y-down screen space) by
 * MAP_ARC_BOW of the leg length (D-13). Endpoints are exact; a zero-length leg is [].
 */
export function arcPoints(a, b, bow = MAP_ARC_BOW) {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const len = Math.hypot(dx, dy);
  if (len < 1e-6) return [];
  const cx = (a.x + b.x) / 2 + dy * bow;
  const cy = (a.y + b.y) / 2 - dx * bow;
  const n = Math.max(ARC_MIN_SEGMENTS, Math.min(ARC_MAX_SEGMENTS, Math.round(len / ARC_STEP)));
  const pts = [{ x: a.x, y: a.y }];
  for (let s = 1; s < n; s += 1) {
    const u = s / n;
    const v = 1 - u;
    pts.push({
      x: v * v * a.x + 2 * v * u * cx + u * u * b.x,
      y: v * v * a.y + 2 * v * u * cy + u * u * b.y,
    });
  }
  pts.push({ x: b.x, y: b.y });
  return pts;
}

// ---------------------------------------------------------------- subjects and paths

/** Date, then kickoff (null last), then merged index; never the array order (D-12). */
function compareGames(t) {
  return (a, b) => {
    if (t.date[a] !== t.date[b]) return t.date[a] < t.date[b] ? -1 : 1;
    const ka = t.kickoff[a];
    const kb = t.kickoff[b];
    if (ka !== kb) {
      if (ka == null) return 1;
      if (kb == null) return -1;
      return ka < kb ? -1 : 1;
    }
    return a - b;
  };
}

function symbolFor(k, count) {
  if (count < 2) return 'circle';
  return k < MAX_COMPARE ? COMPARE_SYMBOLS[k] : 'circle';
}

/**
 * D-01/D-02: the picked announcers in pick order, else the School filter's schools,
 * else none. Symbols follow D-05 (circle for a single subject, compare shapes for the
 * first MAX_COMPARE, circles after).
 */
export function mapSubjects(data, view, state) {
  const people = (state.people ?? [])
    .map((id) => data.personIndexById.get(id))
    .filter((idx) => idx != null);
  if (people.length > 0) {
    return people.map((personIndex, k) => ({
      kind: 'person',
      key: `person:${personIndex}`,
      label: data.lookups.people[personIndex].name,
      personIndex,
      symbol: symbolFor(k, people.length),
    }));
  }
  const slugs = state.school ?? [];
  return slugs.map((slug, k) => {
    const teamIdx = data.teamSlugs.indexOf(slug);
    return {
      kind: 'school',
      key: `school:${slug}`,
      label: teamIdx >= 0 ? data.lookups.teams[teamIdx].name : slug,
      slug,
      symbol: symbolFor(k, slugs.length),
    };
  });
}

/** Merged indexes of the games a subject appears in, among games passing the filters. */
export function subjectGames(data, view, subject) {
  const out = [];
  if (subject.kind === 'person') {
    for (const i of view.highlighted) {
      const on = view.peopleOnGame.get(i);
      if (on && on.includes(subject.personIndex)) out.push(i);
    }
    return out;
  }
  const teamIdx = data.teamSlugs.indexOf(subject.slug);
  if (teamIdx < 0) return out;
  const { home_team: home, away_team: away } = data.t;
  for (let i = 0; i < data.n; i += 1) {
    if (view.passesFilters[i] && (home[i] === teamIdx || away[i] === teamIdx)) out.push(i);
  }
  return out;
}

/**
 * D-03: located games in date order, broken by season. One array per season, ascending
 * season; games without a venue location are dropped and never cut a path (D-16).
 */
export function seasonPaths(data, indexes) {
  const t = data.t;
  const games = indexes.filter((i) => t.place[i] != null);
  games.sort(compareGames(t));
  const bySeason = new Map();
  for (const i of games) {
    const s = t.season[i];
    if (!bySeason.has(s)) bySeason.set(s, []);
    bySeason.get(s).push(i);
  }
  return [...bySeason.keys()].sort((a, b) => a - b).map((s) => bySeason.get(s));
}

// ---------------------------------------------------------------- the model

function pushTo(map, key, value) {
  const list = map.get(key);
  if (list) list.push(value);
  else map.set(key, [value]);
}

/**
 * Everything the Map draws. `view` is computeView's output, reused as is: its
 * passesFilters, visible, highlighted and peopleOnGame decide which games count
 * (the filter always wins, 04.7 D-14), so nothing here re-derives a filter.
 */
export function buildMapModel(data, view, state) {
  const t = data.t;
  const placements = placeVenues(data.lookups.venues);
  const cmp = compareGames(t);
  const subjects = mapSubjects(data, view, state);
  const hasSubject = subjects.length > 0;
  const shapesCapped = subjects.length > MAX_COMPARE;

  // Which subject (pick order) owns each game; the earliest pick wins for symbols.
  const subjectSets = subjects.map((s) => subjectGames(data, view, s));
  const gameSubjects = new Map();
  subjectSets.forEach((list, k) => {
    for (const i of list) pushTo(gameSubjects, i, k);
  });

  // Located games, split into passing / visible-but-failing, and the unlocated count.
  const passing = [];
  const failing = [];
  let noLocationCount = 0;
  for (let i = 0; i < data.n; i += 1) {
    if (t.place[i] == null) {
      if (view.visible[i] === 1) noLocationCount += 1;
    } else if (view.passesFilters[i]) {
      passing.push(i);
    } else if (view.visible[i] === 1) {
      failing.push(i);
    }
  }
  passing.sort(cmp);

  const venueGames = new Map();
  for (const i of passing) pushTo(venueGames, t.place[i], i);
  const subjectVenueGames = subjectSets.map((list) => {
    const m = new Map();
    for (const i of list.filter((g) => t.place[g] != null).sort(cmp)) pushTo(m, t.place[i], i);
    return m;
  });

  // Legs: consecutive located games of each subject within a season (D-03, D-04).
  const legs = [];
  subjects.forEach((_, k) => {
    for (const path of seasonPaths(data, subjectSets[k])) {
      for (let s = 1; s < path.length; s += 1) {
        const from = path[s - 1];
        const to = path[s];
        const points = arcPoints(placements[t.place[from]], placements[t.place[to]]);
        if (points.length === 0) continue;
        legs.push({ subject: k, season: t.season[from], from, to, family: data.familyOf[to], points });
      }
    }
  });

  // Phase 11 venue model: one dot per venue (D-01), subject shapes (D-04), the selected
  // venue flag (D-05; the venue filter never reaches `passing`, so no dot collapses).
  // D-03: with announcers picked, the venue model (dots, splat, key, card) is built from
  // the picked people's games among those passing, exactly computeView's `highlighted`
  // (role and called-together included), so it rescales with the pick. Venues that
  // host only other games stay on the map as background dots from the full cohort.
  const personPick = hasSubject && subjects[0].kind === 'person';
  const fullVenueModel = buildVenueModel(data, passing, placements);
  const venueModel = personPick
    ? buildVenueModel(
        data,
        view.highlighted.filter((i) => t.place[i] != null),
        placements,
      )
    : fullVenueModel;
  const selectedSet = new Set(
    state.venue != null ? (data.venueIndexesByKey?.get(state.venue) ?? []) : [],
  );
  let venueShared = false;
  const venueDots = venueModel.venues.map((v) => {
    let tier = 'base';
    let symbol = 'circle';
    if (hasSubject) {
      const games = venueGames.get(v.index) ?? [];
      const owners = new Set();
      let together = false;
      for (const i of games) {
        const mine = gameSubjects.get(i);
        if (!mine) continue;
        for (const k of mine) owners.add(k);
        if (mine.some((k) => subjects[k].kind === 'person') && (view.peopleOnGame.get(i) ?? []).length >= 2) {
          together = true;
        }
      }
      if (owners.size === 0) {
        tier = 'other';
      } else {
        tier = 'subject';
        if (owners.size >= 2 || together) {
          symbol = SHARED_SYMBOL;
          venueShared = true;
        } else {
          symbol = subjects[Math.min(...owners)].symbol;
        }
      }
    }
    return {
      venue: v.index,
      key: v.key,
      x: v.x,
      y: v.y,
      tier,
      symbol,
      leader: v.leader,
      score: v.score,
      size: v.size,
      dotColor: v.dotColor,
      selected: selectedSet.has(v.index),
    };
  });
  if (personPick) {
    // Background venues first, so the picked people's dots draw on top. Their size uses the
    // picked cohort's scale (capped like any dot), so the two kinds stay comparable.
    const inCohort = new Set(venueModel.venues.map((v) => v.index));
    const background = fullVenueModel.venues
      .filter((v) => !inCohort.has(v.index))
      .map((v) => ({
        venue: v.index,
        key: v.key,
        x: v.x,
        y: v.y,
        tier: 'other',
        symbol: 'circle',
        leader: v.leader,
        score: v.score,
        size: venueDotSize(v.score, venueModel.maxScore),
        dotColor: v.dotColor,
        selected: selectedSet.has(v.index),
      }));
    venueDots.unshift(...background);
  }

  const passingVenues = new Set(passing.map((i) => t.place[i]));
  const venueFadedMap = new Map();
  for (const i of failing) {
    const venue = t.place[i];
    const p = placements[venue];
    if (p.abroad || passingVenues.has(venue) || venueFadedMap.has(venue)) continue;
    venueFadedMap.set(venue, { venue, key: data.venueKeys[venue], x: p.x, y: p.y });
  }
  // UI-SPEC Empty map behavior: with no game passing the filters the map is plain land,
  // so Fade's faded dots and edge markers go too (Hide has none to begin with).
  let passingAny = 0;
  for (let i = 0; i < data.n; i += 1) if (view.passesFilters[i]) passingAny += 1;
  const emptyAll = passingAny === 0;
  const venueFaded = emptyAll ? [] : [...venueFadedMap.values()].sort((a, b) => a.venue - b.venue);

  // Markers for venues abroad, one per label (D-15, D-10).
  const groups = new Map();
  data.lookups.venues.forEach((_, venue) => {
    const p = placements[venue];
    if (!p.abroad || p.label == null) return;
    if (!groups.has(p.label)) groups.set(p.label, { p, venues: [] });
    groups.get(p.label).venues.push(venue);
  });
  const busiest = (counts) => {
    let best = null;
    for (const f of FAMILY_ORDER) {
      if ((counts.get(f) ?? 0) > (best ? counts.get(best) : 0)) best = f;
    }
    return best;
  };
  const markers = [];
  const markerVenues = new Set();
  for (const [label, { p, venues }] of groups) {
    const pass = new Map();
    const vis = new Map();
    for (const v of venues) {
      for (const i of venueGames.get(v) ?? []) pass.set(data.familyOf[i], (pass.get(data.familyOf[i]) ?? 0) + 1);
    }
    for (const i of failing) {
      if (venues.includes(t.place[i])) vis.set(data.familyOf[i], (vis.get(data.familyOf[i]) ?? 0) + 1);
    }
    const key = data.venueGroupKeys?.[venues[0]] ?? null;
    const selected = (key != null && state.venue === key) || venues.some((v) => selectedSet.has(v));
    const grp = key != null ? venueModel.byKey.get(key) : null;
    const top = busiest(pass);
    if (top) {
      markers.push({ x: p.x, y: p.y, label, side: p.side, family: grp?.leader ?? top, faded: false, key, selected });
      for (const v of venues) if (venueGames.has(v)) markerVenues.add(v);
    } else {
      const alt = busiest(vis);
      if (alt) {
        markers.push({ x: p.x, y: p.y, label, side: p.side, family: alt, faded: true, key, selected });
        for (const v of venues) if (failing.some((i) => t.place[i] === v)) markerVenues.add(v);
      }
    }
  }

  if (emptyAll) {
    markers.length = 0;
    markerVenues.clear();
  }
  const drawn = new Set([
    ...venueDots.map((d) => d.venue),
    ...venueFaded.map((d) => d.venue),
    ...markerVenues,
  ]);
  return {
    hasSubject,
    subjects,
    shapesCapped,
    hasShared: venueShared,
    hasVenueShared: venueShared,
    venueModel,
    fullVenueModel,
    venueDots,
    venueFaded,
    legs,
    markers,
    venueGames,
    subjectVenueGames,
    noLocationCount,
    drawnCount: drawn.size,
    emptyAll,
  };
}

// ---------------------------------------------------------------- tooltip

const MAX_TOOLTIP_GAMES = 3;

function countryName(code) {
  try {
    return new Intl.DisplayNames(['en'], { type: 'region' }).of(code) ?? code;
  } catch {
    return code;
  }
}

function venueTitle(venue) {
  const abroad = venue.country != null && venue.country !== 'US';
  if (!venue.city) return venue.name;
  const where = abroad ? countryName(venue.country) : venue.state;
  return where ? `${venue.name} · ${venue.city}, ${where}` : `${venue.name} · ${venue.city}`;
}

/**
 * Name and tooltip for the venue filter chip and status (Phase 11 D-05): a single venue
 * gives its name and "name, city, ST"; an abroad marker group gives its label. Unknown
 * keys give null.
 */
export function venueFilterInfo(data, key) {
  const indexes = key != null ? data.venueIndexesByKey?.get(key) : undefined;
  if (!indexes || indexes.length === 0) return null;
  const single = data.venueKeys?.indexOf(key) ?? -1;
  if (single >= 0) {
    const v = data.lookups.venues[single];
    const abroad = v.country != null && v.country !== 'US';
    const where = abroad ? countryName(v.country) : v.state;
    const title = [v.name, v.city, where].filter(Boolean).join(', ');
    return { name: v.name, title };
  }
  const label = placeVenues(data.lookups.venues)[indexes[0]]?.label ?? key;
  return { name: label, title: label };
}

function gameLine(data, i) {
  const t = data.t;
  const teams = data.lookups.teams;
  const home = teams[t.home_team[i]].name;
  const away = teams[t.away_team[i]].name;
  const matchup = t.neutral[i] ? `${away} vs ${home}` : `${away} @ ${home}`;
  return `${t.date[i]}  ${matchup}  ${data.lookups.networks[t.network[i]].name}`;
}

/** Subject blocks ("── Pat here ──", up to three games, "+N more") for venue indexes. */
function subjectLinesFor(data, model, indexes) {
  const lines = [];
  const several = model.subjects.length >= 2;
  model.subjects.forEach((subject, k) => {
    const mine = indexes.flatMap((v) => model.subjectVenueGames[k].get(v) ?? []);
    if (mine.length === 0) return;
    const glyph = several ? `${k < MAX_COMPARE ? COMPARE_GLYPHS[k] : '●'} ` : '';
    lines.push({ text: `── ${glyph}${subject.label} here ──`, kind: 'body' });
    for (const i of mine.slice(0, MAX_TOOLTIP_GAMES)) lines.push({ text: gameLine(data, i), kind: 'body' });
    if (mine.length > MAX_TOOLTIP_GAMES) {
      lines.push({ text: `+${mine.length - MAX_TOOLTIP_GAMES} more`, kind: 'hint' });
    }
  });
  return lines;
}

const CARD_MAX_ROWS = 6;

/**
 * Hover-card data for one venue key or abroad group key (Phase 11 D-02, D-01a): the
 * title, pie slices, at most six family rows plus Other, real viewers (the unrated
 * floor never enters; a row with unrated games is `partial`), and the subject lines. Unknown keys give null.
 */
export function venueCard(data, model, key) {
  const entry = model.venueModel?.byKey.get(key) ?? model.fullVenueModel?.byKey.get(key);
  if (!entry) return null;
  const isGroup = Array.isArray(entry.indexes);
  const indexes = isGroup ? entry.indexes : [entry.index];
  const title = isGroup ? entry.label : venueTitle(data.lookups.venues[entry.index]);
  const slices = FAMILY_ORDER.map((family, f) => ({
    family,
    games: entry.counts[f],
    rated: entry.ratedCounts[f],
    viewers: entry.ratedCounts[f] > 0 ? entry.viewers[f] : null,
  }))
    .filter((s) => s.games > 0)
    .sort((a, b) => b.games - a.games || FAMILY_ORDER.indexOf(a.family) - FAMILY_ORDER.indexOf(b.family));
  const rows = slices.slice(0, CARD_MAX_ROWS).map((s) => ({
    family: s.family,
    label: FAMILY_LABELS[s.family],
    games: s.games,
    viewers: s.viewers,
    partial: s.viewers != null && s.rated < s.games,
  }));
  const rest = slices.slice(CARD_MAX_ROWS);
  if (rest.length > 0) {
    const rated = rest.filter((s) => s.viewers != null);
    const games = rest.reduce((n, s) => n + s.games, 0);
    rows.push({
      family: null,
      label: 'Other',
      games,
      viewers: rated.length > 0 ? rated.reduce((n, s) => n + s.viewers, 0) : null,
      partial: rated.length > 0 && rest.reduce((n, s) => n + s.rated, 0) < games,
    });
  }
  return {
    title,
    leader: entry.leader,
    slices,
    rows,
    hasMissingViewers: rows.some((r) => r.viewers == null),
    // A row's Viewers figure adds up its rated games only when some of its games are unrated.
    hasPartialViewers: rows.some((r) => r.partial),
    hasViewers: rows.some((r) => r.viewers != null),
    subjectLines: subjectLinesFor(data, model, indexes),
  };
}
