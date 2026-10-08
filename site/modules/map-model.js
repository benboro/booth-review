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

// ---------------------------------------------------------------- constants

export const MAP_WIDTH = 975;
export const MAP_HEIGHT = 610;
export const ALBERS_SCALE = 1300;
export const ALBERS_TRANSLATE = Object.freeze([487.5, 305]);
/** Quadratic-arc bow, as a fraction of the leg length, to the left of travel (D-13). */
export const MAP_ARC_BOW = 0.15;
const ARC_STEP = 20;
const ARC_MIN_SEGMENTS = 6;
const ARC_MAX_SEGMENTS = 24;

/** The us-atlas Hawaii inset bounding box in map pixels. */
export const HAWAII_INSET = Object.freeze({ x0: 216, x1: 332, y0: 528, y1: 603 });

/** D-15: labeled anchors for venues abroad that fall outside every sub-projection. */
export const EDGE_ANCHORS = Object.freeze({
  IE: Object.freeze({ x: 955, y: 30, label: 'Dublin', side: 'left' }),
  GB: Object.freeze({ x: 955, y: 52, label: 'London', side: 'left' }),
  AU: Object.freeze({ x: 120, y: 575, label: 'Sydney', side: 'right' }),
});

/** D-15: corner anchors for any other country, chosen by bearing from the map center. */
export const FALLBACK_ANCHORS = Object.freeze({
  ne: Object.freeze({ x: 955, y: 74, side: 'left' }),
  se: Object.freeze({ x: 955, y: 588, side: 'left' }),
  sw: Object.freeze({ x: 40, y: 588, side: 'right' }),
  nw: Object.freeze({ x: 20, y: 30, side: 'right' }),
});

export const MAP_HINT = 'Pick an announcer or a school to trace a path';
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

// ---------------------------------------------------------------- projection

const RAD = Math.PI / 180;

/**
 * d3-geo's conic equal-area sub-projection with rotate/center/scale/translate,
 * returned as a function (lon, lat in degrees) -> [x, y] in screen space.
 */
function conicEqualArea(parallels, rotate, center, k, translate) {
  const s0 = Math.sin(parallels[0] * RAD);
  const s1 = Math.sin(parallels[1] * RAD);
  const n = (s0 + s1) / 2;
  const c = 1 + s0 * (2 * n - s0);
  const r0 = Math.sqrt(c) / n;
  const raw = (lambda, phi) => {
    const r = Math.sqrt(c - 2 * n * Math.sin(phi)) / n;
    return [r * Math.sin(n * lambda), r0 - r * Math.cos(n * lambda)];
  };
  // The center is given in rotated coordinates (not rotated again).
  const [cx, cy] = raw(center[0] * RAD, center[1] * RAD);
  return (lon, lat) => {
    const [rx, ry] = raw((lon + rotate) * RAD, lat * RAD);
    return [translate[0] + k * (rx - cx), translate[1] - k * (ry - cy)];
  };
}

const [TX, TY] = ALBERS_TRANSLATE;
const K = ALBERS_SCALE;
const LOWER48 = conicEqualArea([29.5, 45.5], 96, [-0.6, 38.7], K, [TX, TY]);
const HAWAII = conicEqualArea([8, 18], 157, [-3, 19.9], K, [TX - 0.205 * K, TY + 0.212 * K]);
// Alaska is left off the drawn map (D-14) but kept so a future Alaska venue still places.
const ALASKA = conicEqualArea([55, 65], 154, [-2, 58.5], 0.35 * K, [TX - 0.307 * K, TY + 0.201 * K]);
const CLIP = Object.freeze({
  x0: TX - 0.455 * K,
  x1: TX + 0.455 * K,
  y0: TY - 0.238 * K,
  y1: TY + 0.238 * K,
});

/** Project lon/lat to map pixels, or null when outside the (state-selected) projection. */
export function projectAlbersUsa(lon, lat, state) {
  if (state === 'HI') {
    const [x, y] = HAWAII(lon, lat);
    return Number.isFinite(x) && Number.isFinite(y) ? { x, y } : null;
  }
  if (state === 'AK') {
    const [x, y] = ALASKA(lon, lat);
    return Number.isFinite(x) && Number.isFinite(y) ? { x, y } : null;
  }
  const [x, y] = LOWER48(lon, lat);
  if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
  if (x < CLIP.x0 || x > CLIP.x1 || y < CLIP.y0 || y > CLIP.y1) return null;
  return { x, y };
}

function fallbackAnchor(venue) {
  const dLon = ((((venue.lon + 98 + 540) % 360) + 360) % 360) - 180;
  const dLat = venue.lat - 39;
  const corner = (dLat >= 0 ? 'n' : 's') + (dLon >= 0 ? 'e' : 'w');
  const a = FALLBACK_ANCHORS[corner];
  return { x: a.x, y: a.y, edge: true, label: venue.city ?? venue.name, side: a.side };
}

/** Where a venue sits on the map (D-14, D-15): projected, or a labeled edge anchor. */
export function placeVenue(venue) {
  const abroad = venue.country != null && venue.country !== 'US';
  const pt = projectAlbersUsa(venue.lon, venue.lat, venue.state);
  if (pt) {
    return {
      x: pt.x,
      y: pt.y,
      abroad,
      edge: false,
      label: abroad ? (venue.city ?? venue.name) : null,
      side: abroad ? 'left' : null,
    };
  }
  const known = abroad ? EDGE_ANCHORS[venue.country] : undefined;
  if (known) {
    return { x: known.x, y: known.y, abroad, edge: true, label: known.label, side: known.side };
  }
  return { ...fallbackAnchor(venue), abroad };
}

const placementCache = new WeakMap();

/** placeVenue for every venue, cached per venues array. */
export function placeVenues(venues) {
  let hit = placementCache.get(venues);
  if (!hit) {
    hit = venues.map(placeVenue);
    placementCache.set(venues, hit);
  }
  return hit;
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

const TIER_RANK = { base: 0, other: 0, subject: 1 };

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

  // Dots: one per (venue, family, tier, symbol) for passing games (D-10, D-05).
  let hasShared = false;
  const dotMap = new Map();
  for (const i of passing) {
    const venue = t.place[i];
    const family = data.familyOf[i];
    let tier = 'base';
    let symbol = 'circle';
    if (hasSubject) {
      const owners = gameSubjects.get(i);
      if (owners) {
        tier = 'subject';
        const first = owners[0];
        if (subjects[first].kind === 'person' && (view.peopleOnGame.get(i) ?? []).length >= 2) {
          symbol = SHARED_SYMBOL;
          hasShared = true;
        } else {
          symbol = subjects[first].symbol;
        }
      } else {
        tier = 'other';
      }
    }
    const key = `${venue}|${family}|${tier}|${symbol}`;
    if (!dotMap.has(key)) {
      const p = placements[venue];
      dotMap.set(key, { venue, family, x: p.x, y: p.y, symbol, tier });
    }
  }
  const symbolRank = (s) => (s === SHARED_SYMBOL ? COMPARE_SYMBOLS.length : COMPARE_SYMBOLS.indexOf(s));
  const dots = [...dotMap.values()].sort(
    (a, b) =>
      FAMILY_ORDER.indexOf(a.family) - FAMILY_ORDER.indexOf(b.family) ||
      a.venue - b.venue ||
      TIER_RANK[a.tier] - TIER_RANK[b.tier] ||
      symbolRank(a.symbol) - symbolRank(b.symbol),
  );

  // Faded dots: visible failing games where no passing game shares (venue, family) (D-12).
  const passingKeys = new Set(passing.map((i) => `${t.place[i]}|${data.familyOf[i]}`));
  const fadedMap = new Map();
  for (const i of failing) {
    const venue = t.place[i];
    const family = data.familyOf[i];
    const key = `${venue}|${family}`;
    if (passingKeys.has(key) || fadedMap.has(key)) continue;
    const p = placements[venue];
    fadedMap.set(key, { venue, family, x: p.x, y: p.y });
  }
  const faded = [...fadedMap.values()].sort(
    (a, b) => FAMILY_ORDER.indexOf(a.family) - FAMILY_ORDER.indexOf(b.family) || a.venue - b.venue,
  );

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

  // Markers for venues abroad, one per label (D-15).
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
  for (const [label, { p, venues }] of groups) {
    const pass = new Map();
    const vis = new Map();
    for (const v of venues) {
      for (const i of venueGames.get(v) ?? []) pass.set(data.familyOf[i], (pass.get(data.familyOf[i]) ?? 0) + 1);
    }
    for (const i of failing) {
      if (venues.includes(t.place[i])) vis.set(data.familyOf[i], (vis.get(data.familyOf[i]) ?? 0) + 1);
    }
    const top = busiest(pass);
    if (top) {
      markers.push({ x: p.x, y: p.y, label, side: p.side, family: top, faded: false });
    } else {
      const alt = busiest(vis);
      if (alt) markers.push({ x: p.x, y: p.y, label, side: p.side, family: alt, faded: true });
    }
  }

  const drawn = new Set([...dots, ...faded].map((d) => d.venue));
  return {
    hasSubject,
    subjects,
    shapesCapped,
    hasShared,
    dots,
    faded,
    legs,
    markers,
    venueGames,
    subjectVenueGames,
    noLocationCount,
    drawnCount: drawn.size,
    emptyAll: view.visibleCount === 0,
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

function gameLine(data, i) {
  const t = data.t;
  const teams = data.lookups.teams;
  const home = teams[t.home_team[i]].name;
  const away = teams[t.away_team[i]].name;
  const matchup = t.neutral[i] ? `${away} vs ${home}` : `${away} @ ${home}`;
  return `${t.date[i]}  ${matchup}  ${data.lookups.networks[t.network[i]].name}`;
}

/**
 * D-11: plain {text, kind} lines for one venue (index into lookups.venues): title,
 * family counts for passing games, then each subject's games there (up to three, then
 * "+N more"). The caller writes them with textContent only.
 */
export function venueTooltipLines(data, model, venue) {
  const lines = [{ text: venueTitle(data.lookups.venues[venue]), kind: 'title' }];
  const games = model.venueGames.get(venue) ?? [];
  const counts = new Map();
  for (const i of games) counts.set(data.familyOf[i], (counts.get(data.familyOf[i]) ?? 0) + 1);
  const parts = FAMILY_ORDER.filter((f) => counts.get(f)).map((f) => `${FAMILY_LABELS[f]} ${counts.get(f)}`);
  if (parts.length > 0) lines.push({ text: parts.join(' · '), kind: 'body' });
  const several = model.subjects.length >= 2;
  model.subjects.forEach((subject, k) => {
    const mine = model.subjectVenueGames[k].get(venue) ?? [];
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
