// Pure geometry for the CFB Map: the fixed 975 x 610 Albers USA space, venue placement
// and edge anchors. Imports nothing and never touches the DOM, so data.js can use it
// without a cycle. Moved verbatim from map-model.js (04.18 D-14/D-15); map-model.js
// re-exports every name.

// ---------------------------------------------------------------- constants

export const MAP_WIDTH = 975;
export const MAP_HEIGHT = 610;
export const ALBERS_SCALE = 1300;
export const ALBERS_TRANSLATE = Object.freeze([487.5, 305]);

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
