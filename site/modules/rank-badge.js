/**
 * The ranked-matchup badge (Phase 28, D-01, D-02, D-04, D-06, D-07): a classic five-point star
 * with an "R" cut out of it, shown only when both teams of a college-football game are ranked.
 *
 * The R is a pre-rendered path (not live text) so it never depends on a font loading inside the
 * SVG. It is a hole in a mask (white star, black R) applied to a `currentColor` rect, so the
 * background shows through the letter and the badge takes the text colour of whatever holds it.
 * Not the lead-booth star colour. Built only with createElementNS and setAttribute from
 * constants; no row data enters the svg.
 */

const SVG_NS = 'http://www.w3.org/2000/svg';
const LABEL = 'Both teams ranked';

// Roboto 600 "R" (site/fonts/roboto-latin-600-normal.woff2), font size 42, bbox centred at
// (50, 55) in the 100-unit box.
const R_PATH =
  'M38.55 40.07H49.4Q52.8 40.07 55.24 41.1Q57.68 42.12 58.99 44.13Q60.31 46.14 60.31 49.07' +
  'Q60.31 51.39 59.48 53.09Q58.66 54.79 57.18 55.94Q55.69 57.09 53.68 57.75L51.92 58.65H42.34' +
  'L42.3 54.2H49.46Q51.2 54.2 52.35 53.58Q53.5 52.97 54.08 51.88Q54.67 50.8 54.67 49.4' +
  'Q54.67 47.9 54.09 46.81Q53.52 45.71 52.35 45.12Q51.18 44.52 49.4 44.52H44.19V69.93H38.55Z' +
  'M55.4 69.93 48.49 56.56 54.46 56.54 61.45 69.64V69.93Z';

/** Ten alternating outer (52) and inner (20.8) points around (50, 54), first point straight up. */
const STAR_POINTS = Array.from({ length: 10 }, (_, k) => {
  const r = k % 2 === 0 ? 52 : 20.8;
  const a = (-90 + k * 36) * Math.PI / 180;
  return `${(50 + r * Math.cos(a)).toFixed(2)},${(54 + r * Math.sin(a)).toFixed(2)}`;
}).join(' ');

let maskCount = 0;

/** True when both ranks are set; rank 0 is a value, so compare with != null. */
export function bothRanked(away, home) {
  return away != null && home != null;
}

/** True for a CFB game whose two teams are both ranked (NFL and MLB never). */
export function isRankedMatchup(game) {
  return game?.sport === 'cfb' && bothRanked(game.awayRank, game.homeRank);
}

function svgEl(name, attrs) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
  return node;
}

/**
 * The badge. `hidden` marks the span and its svg aria-hidden for surfaces whose enclosing
 * accessible name already says "Both teams ranked.", so the span's title is not surfaced as a
 * description either; the tooltip still shows on hover either way.
 * @param {{hidden?: boolean}} [opts]
 * @returns {HTMLSpanElement}
 */
export function rankBadge({ hidden = false } = {}) {
  maskCount += 1;
  const id = `rkm-${maskCount}`;
  const span = document.createElement('span');
  span.className = 'rk-badge';
  span.title = LABEL;
  const svg = svgEl('svg', { viewBox: '0 0 100 100' });
  if (hidden) {
    span.setAttribute('aria-hidden', 'true');
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('focusable', 'false');
  } else {
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', LABEL);
    const title = svgEl('title', {});
    title.textContent = LABEL;
    svg.append(title);
  }
  const defs = svgEl('defs', {});
  const mask = svgEl('mask', {
    id, maskUnits: 'userSpaceOnUse', x: -10, y: -10, width: 120, height: 120,
  });
  mask.append(
    svgEl('rect', { x: -10, y: -10, width: 120, height: 120, fill: 'black' }),
    svgEl('polygon', { points: STAR_POINTS, fill: 'white' }),
    svgEl('path', { d: R_PATH, fill: 'black' }),
  );
  defs.append(mask);
  svg.append(defs, svgEl('rect', {
    x: -10, y: -10, width: 120, height: 120, fill: 'currentColor', mask: `url(#${id})`,
  }));
  span.append(svg);
  return span;
}
