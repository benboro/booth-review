// Weekend map model (Phase 24): the window shape of each game, and (below) the dots, nudge
// rows, edge markers, not-on-map list and splat input built from one day's WeekendGame list.
// pure: model + geometry + env in, no DOM, no clock, no window.Plotly. No colour literal lives
// here; colours come from palette.js through weekend-map-chart.js.

import { MAP_HEIGHT, MAP_WIDTH, placeVenue } from './map-geo.js';
import { pxPerUnit } from './map-chart.js';
import { venueTitle } from './map-model.js';
import { sortNetworks } from './network.js';
import { FAMILY_ORDER, WEEKEND_MAP_DOT, familyKey } from './palette.js';
import { boothLine, cellState, clock12, matchupText } from './weekend.js';

// ---------------------------------------------------------------- window shape (D-03)

/**
 * The one table of window -> Plotly marker symbol. The figure and the key both read it, so the
 * shapes cannot diverge. CFB windows are by ET kickoff; NFL windows by slot name.
 */
export const WINDOW_SYMBOL = Object.freeze({
  cfb: Object.freeze({ noon: 'circle', afternoon: 'square', prime: 'diamond', late: 'triangle-up' }),
  nfl: Object.freeze({ early: 'circle', late: 'square', night: 'diamond' }),
  tba: 'circle-open',
});

/** Key labels per sport, in key order (UI-SPEC "Copywriting Contract"). */
export const WINDOW_LABELS = Object.freeze({
  cfb: Object.freeze({
    noon: 'Noon',
    afternoon: 'Afternoon',
    prime: 'Prime',
    late: 'Late',
    tba: 'Time TBA',
  }),
  nfl: Object.freeze({
    early: 'Early',
    late: 'Late',
    night: 'Night and standalone',
    tba: 'Time TBA',
  }),
});

/** Key range captions per sport (UI-SPEC "Copywriting Contract"). */
export const WINDOW_CAPTION = Object.freeze({
  cfb: 'Noon is before 2:30 pm. Afternoon is 2:30 to 6:59 pm. Prime is 7:00 to 9:59 pm. '
    + 'Late is 10:00 pm and after.',
  nfl: 'Early is the 1:00 pm window. Late is the 4:05 and 4:25 pm windows. '
    + 'Night and standalone covers every other slot.',
});

/** CFB window boundaries in minutes after ET midnight: 2:30 pm, 7:00 pm, 10:00 pm. */
const CFB_AFTERNOON_MIN = 14 * 60 + 30;
const CFB_PRIME_MIN = 19 * 60;
const CFB_LATE_MIN = 22 * 60;

/**
 * The CFB broadcast window of an ET kickoff.
 * @param {number|null} kickoffMin - minutes after ET midnight.
 * @returns {'noon'|'afternoon'|'prime'|'late'|'tba'}
 */
export function cfbWindow(kickoffMin) {
  if (kickoffMin == null) return 'tba';
  if (kickoffMin >= CFB_LATE_MIN) return 'late';
  if (kickoffMin >= CFB_PRIME_MIN) return 'prime';
  if (kickoffMin >= CFB_AFTERNOON_MIN) return 'afternoon';
  return 'noon';
}

/**
 * The NFL broadcast window from the Python slot name. Only the two Sunday daytime slots are not
 * night; TNF, SNF, MNF and every standalone slot read as night (RESEARCH Pitfall 6: the slot
 * name decides, `classifyGame` only decides grid, compact or tba).
 * @param {string|null} slotName
 * @returns {'early'|'late'|'night'|'tba'}
 */
export function nflWindow(slotName) {
  if (slotName == null) return 'tba';
  if (slotName === 'Sunday early') return 'early';
  if (slotName === 'Sunday late') return 'late';
  return 'night';
}

/**
 * The window of a WeekendGame. A game with no kickoff time is `tba` in either sport.
 * @param {object} game
 * @returns {string}
 */
export function windowOf(game) {
  if (game.sport === 'nfl') return nflWindow(game.slotName ?? null);
  return cfbWindow(game.kickoffMin ?? null);
}

/**
 * The Plotly marker symbol of a WeekendGame.
 * @param {object} game
 * @returns {string}
 */
export function symbolOf(game) {
  const win = windowOf(game);
  if (win === 'tba') return WINDOW_SYMBOL.tba;
  return WINDOW_SYMBOL[game.sport === 'nfl' ? 'nfl' : 'cfb'][win];
}

// ---------------------------------------------------------------- nudge rows (D-01)

/** Games closer than this many rendered px after projection share one row. */
export const NUDGE_GROUP_PX = 6;
/** Games per nudge row before wrapping to the next. */
export const NUDGE_ROW_MAX = 4;
/** Vertical px between wrapped nudge rows. */
export const NUDGE_ROW_GAP_PX = 16;
/** Px added to the largest member size to get the centre-to-centre pitch. */
export const NUDGE_PITCH_PAD_PX = 2;

const nullsLast = (n) => (n == null ? Infinity : n);

function byKickoff(a, b) {
  return (
    nullsLast(a.kickoffMin) - nullsLast(b.kickoffMin)
    || String(a.key ?? '').localeCompare(String(b.key ?? ''))
    || a.i - b.i
  );
}

/**
 * Lays same-place points in short horizontal rows centred on their venue. Points whose venue
 * points lie within `NUDGE_GROUP_PX` rendered px of each other (single linkage) form a group;
 * a group is ordered by kickoff (earliest left, no time last), spaced at the largest member
 * size plus 2 px, wrapped after 4 into rows 16 px lower, each row centred on the group's centre.
 * The offset is computed in px and converted to map units with `ppu`, so it holds at every
 * width. A lone point is not moved.
 * @param {{x: number, y: number, size: number, kickoffMin?: (number|null), key?: string}[]} points
 * @param {number} ppu - rendered pixels per map unit.
 * @returns {object[]} copies of `points`, index-aligned, with `x`/`y` nudged and the group's
 *   centre kept as `venueX`/`venueY`.
 */
export function nudgeRows(points, ppu) {
  const out = points.map((p) => ({ ...p, venueX: p.x, venueY: p.y }));
  if (!(ppu > 0) || out.length < 2) return out;
  const parent = out.map((_, i) => i);
  const find = (i) => {
    let r = i;
    while (parent[r] !== r) r = parent[r];
    return r;
  };
  for (let i = 0; i < out.length; i += 1) {
    for (let j = i + 1; j < out.length; j += 1) {
      const d = Math.hypot((out[i].x - out[j].x) * ppu, (out[i].y - out[j].y) * ppu);
      if (d <= NUDGE_GROUP_PX) parent[find(j)] = find(i);
    }
  }
  const groups = new Map();
  out.forEach((p, i) => {
    const r = find(i);
    if (!groups.has(r)) groups.set(r, []);
    groups.get(r).push({ p, i, kickoffMin: p.kickoffMin, key: p.key });
  });
  for (const members of groups.values()) {
    if (members.length < 2) continue;
    const cx = members.reduce((sum, m) => sum + m.p.venueX, 0) / members.length;
    const cy = members.reduce((sum, m) => sum + m.p.venueY, 0) / members.length;
    const pitch = Math.max(...members.map((m) => m.p.size)) + NUDGE_PITCH_PAD_PX;
    members.sort(byKickoff);
    members.forEach((m, k) => {
      const row = Math.floor(k / NUDGE_ROW_MAX);
      const inRow = Math.min(NUDGE_ROW_MAX, members.length - row * NUDGE_ROW_MAX);
      const col = k - row * NUDGE_ROW_MAX;
      m.p.x = cx + ((col - (inRow - 1) / 2) * pitch) / ppu;
      m.p.y = cy + (row * NUDGE_ROW_GAP_PX) / ppu;
      m.p.venueX = cx;
      m.p.venueY = cy;
    });
  }
  return out;
}

// ---------------------------------------------------------------- model

/** Plot box assumed when the caller has not measured one yet (px). */
const DEFAULT_PLOT_W = { desktop: 960, mobile: 390 };

function plotFor(env) {
  if (env.plot && env.plot.w > 0 && env.plot.h > 0) return env.plot;
  const w = env.mobile ? DEFAULT_PLOT_W.mobile : DEFAULT_PLOT_W.desktop;
  return { w, h: (w * MAP_HEIGHT) / MAP_WIDTH };
}

function hasPoint(venue) {
  return venue != null && Number.isFinite(venue.lat) && Number.isFinite(venue.lon);
}

/** The hover lines of a game (raw text; the figure escapes it). */
function hoverLines(game, nowWall, venueLine) {
  const state = cellState(game, nowWall);
  const booth = boothLine(game, state);
  const time = game.kickoffMin == null ? 'Time TBA' : `${clock12(game.kickoffMin)} ET`;
  const lines = {
    matchup: matchupText(game),
    booth: { star: booth.star, text: booth.text, weight: booth.weight },
    kickoff: `${time} \u00b7 ${game.networkName ?? 'Network TBA'}`,
    venue: venueLine,
  };
  return { ...lines, text: [lines.matchup, `${booth.star ? '\u2605 ' : ''}${booth.text}`, lines.kickoff, venueLine].join('\n') };
}

function notOnMapOrder(games) {
  const rank = new Map(
    sortNetworks([...new Set(games.map((g) => g.networkId).filter(Boolean))].map((id) => ({ id })))
      .map((n, k) => [n.id, k]),
  );
  const net = (g) => (g.networkId == null ? Infinity : (rank.get(g.networkId) ?? Infinity));
  const known = (g) => (g.kickoffMin == null ? 1 : 0);
  return [...games].sort(
    (a, b) => known(a) - known(b)
      || nullsLast(a.kickoffMin) - nullsLast(b.kickoffMin)
      || net(a) - net(b)
      || String(a.home).localeCompare(String(b.home)),
  );
}

function layer(d) {
  if (d.faded) return 0;
  return d.ringed ? 2 : 1;
}

/**
 * The weekend map model of one day (D-01, D-06, D-07, D-09, D-11).
 * @param {object} env
 * @param {object[]} env.games - the day's WeekendGames (the caller filters by day).
 * @param {string} [env.day] - the day's ISO date, carried through.
 * @param {Function} [env.passes] - `ctx.passes(game)`: true, false or null.
 * @param {Function} [env.networksPicked] - `ctx.networksPicked(networkId)`.
 * @param {'light'|'dark'} [env.theme]
 * @param {boolean} [env.mobile]
 * @param {{w: number, h: number}} [env.plot] - the plot box in CSS px.
 * @param {number} [env.nowWall] - ET wall minutes, for the booth line.
 * @returns {{dots: object[], markers: object[], notOnMap: object[], splatModel: object,
 *   counts: object, day: (string|undefined)}}
 */
export function buildWeekendMapModel(env) {
  const { games, day, mobile = false } = env;
  const passes = env.passes ?? (() => null);
  const networksPicked = env.networksPicked ?? (() => null);
  const ppu = pxPerUnit(plotFor(env));
  const sizes = mobile ? WEEKEND_MAP_DOT.phone : WEEKEND_MAP_DOT.desktop;
  const base = (game, symbol) => {
    const faded = passes(game) === false || networksPicked(game.networkId) === false;
    return {
      key: game.key,
      game,
      kickoffMin: game.kickoffMin ?? null,
      symbol,
      size: sizes[symbol],
      family: familyKey(game.family),
      faded,
      ringed: !faded && passes(game) === true,
    };
  };

  const onMap = [];
  const edge = [];
  const lost = [];
  for (const game of games) {
    const venue = game.venue ?? null;
    if (!hasPoint(venue)) {
      lost.push(game);
      continue;
    }
    const at = placeVenue(venue);
    const symbol = symbolOf(game);
    if (at.abroad || at.edge) {
      const label = at.label ?? venue.city ?? venue.name ?? null;
      if (label == null) {
        lost.push(game);
        continue;
      }
      edge.push({
        ...base(game, symbol),
        x: at.x,
        y: at.y,
        side: at.side ?? 'left',
        label,
        hoverLines: hoverLines(game, env.nowWall, label),
      });
    } else {
      onMap.push({
        ...base(game, symbol),
        x: at.x,
        y: at.y,
        hoverLines: hoverLines(game, env.nowWall, venueTitle(venue)),
      });
    }
  }

  // On-map dots: shared-venue rows.
  const nudged = nudgeRows(onMap, ppu);
  const dots = nudged.sort(
    (a, b) => layer(a) - layer(b) || byKickoff({ ...a, i: 0 }, { ...b, i: 0 }),
  );

  // Edge markers: one site per anchor and label; sites spread by pixel gap, games of a site
  // laid in a row that grows away from the edge so the single label stays beside the row.
  const markers = layoutMarkers(edge, ppu, mobile);

  const notOnMap = notOnMapOrder(lost);
  const splatModel = splatVenueModel(dots);
  const counts = {
    dots: dots.length,
    markers: markers.length,
    notOnMap: notOnMap.length,
    total: games.length,
    faded: [...dots, ...markers].filter((d) => d.faded).length,
    ringed: [...dots, ...markers].filter((d) => d.ringed).length,
  };
  return { dots, markers, notOnMap, splatModel, counts, day };
}

/** Roboto Condensed 12 px label height used to space edge sites (matches map-chart). */
const MARKER_LABEL_PX = 12;
/** Blank px kept between two stacked edge-marker labels (map-chart's MARKER_GAP_PX). */
const MARKER_SITE_GAP_PX = 6;

function layoutMarkers(edge, ppu, mobile) {
  if (edge.length === 0) return [];
  const sites = new Map();
  edge.forEach((m) => {
    const id = `${m.x}|${m.y}|${m.label}`;
    if (!sites.has(id)) sites.set(id, { x: m.x, y: m.y, side: m.side, members: [] });
    sites.get(id).members.push(m);
  });
  const list = [...sites.values()];
  const spread = spreadSites(list, ppu);
  const out = [];
  list.forEach((site, k) => {
    const members = site.members
      .map((m, i) => ({ ...m, i }))
      .sort(byKickoff);
    const pitch = Math.max(...members.map((m) => m.size)) + NUDGE_PITCH_PAD_PX;
    const step = ppu > 0 ? pitch / ppu : 0;
    const n = members.length;
    members.forEach((m, j) => {
      // side 'left': the label sits left of the leftmost marker, the row grows leftward from the
      // edge anchor; side 'right': the label sits right of the rightmost marker, the row grows
      // rightward. The labelled marker is the one nearest the label.
      const fromAnchor = site.side === 'left' ? n - 1 - j : j;
      const labelled = site.side === 'left' ? j === 0 : j === n - 1;
      const rest = { ...m };
      delete rest.i;
      out.push({
        ...rest,
        x: site.side === 'left' ? spread[k].x - fromAnchor * step : spread[k].x + fromAnchor * step,
        y: spread[k].y,
        venueX: site.x,
        venueY: site.y,
        text: labelled ? m.label : '',
      });
    });
  });
  return out;
}

function spreadSites(sites, ppu) {
  // Spread one entry per site vertically by the CFB Map's pixel rule, then read the result back.
  const gap = ppu > 0 ? (MARKER_LABEL_PX + MARKER_SITE_GAP_PX) / ppu : 0;
  const out = sites.map((s) => ({ x: s.x, y: s.y, side: s.side }));
  if (!(gap > 0)) return out;
  for (const side of ['left', 'right']) {
    const col = out.map((p, i) => ({ p, i })).filter((e) => e.p.side === side).sort((a, b) => a.p.y - b.p.y);
    let start = 0;
    for (let k = 1; k <= col.length; k += 1) {
      if (k < col.length && col[k].p.y - col[k - 1].p.y < gap && Math.abs(col[k].p.x - col[k - 1].p.x) < 200) {
        continue;
      }
      const run = col.slice(start, k);
      start = k;
      if (run.length < 2) continue;
      const mid = run.reduce((sum, e) => sum + e.p.y, 0) / run.length;
      let top = mid - ((run.length - 1) * gap) / 2;
      const half = (MARKER_LABEL_PX / 2 + 2) / ppu;
      top = Math.min(Math.max(top, half), MAP_HEIGHT - half - (run.length - 1) * gap);
      run.forEach((e, r) => {
        e.p.y = top + r * gap;
      });
    }
  }
  return out;
}

// ---------------------------------------------------------------- splat input (D-02, D-11)

function venueKeyOf(game) {
  const v = game.venue;
  return game.placeIdx != null ? `p${game.placeIdx}` : `${v?.name}|${v?.lat}|${v?.lon}`;
}

/**
 * The painter's input from unfaded on-map dots: one venue entry per place, `games` and `score`
 * the game count (weight 1 per game, no viewers), `counts` per `FAMILY_ORDER` index, region 2
 * for the Hawaii inset. Edge markers never feed the splat (Phase 11 D-10). With no unfaded dot
 * the model has no venues and the land fill returns.
 * @param {object[]} dots - `buildWeekendMapModel` dots.
 * @param {Map<string, object>} [venuesByKey] - optional venue override per place key.
 * @returns {{venues: object[], medianScore: number}}
 */
export function splatVenueModel(dots, venuesByKey) {
  const acc = new Map();
  for (const d of dots) {
    if (d.faded) continue;
    const key = venueKeyOf(d.game);
    let v = acc.get(key);
    if (!v) {
      const venue = venuesByKey?.get(key) ?? d.game.venue;
      v = {
        key,
        x: d.venueX ?? d.x,
        y: d.venueY ?? d.y,
        region: venue?.state === 'HI' ? 2 : 1,
        counts: new Array(FAMILY_ORDER.length).fill(0),
        games: 0,
        score: 0,
      };
      acc.set(key, v);
    }
    const f = FAMILY_ORDER.indexOf(d.family);
    if (f >= 0) v.counts[f] += 1;
    v.games += 1;
    v.score += 1;
  }
  const venues = [...acc.values()];
  const positive = venues.map((v) => v.score).filter((n) => n > 0).sort((a, b) => a - b);
  const medianScore = positive.length ? positive[Math.floor(positive.length / 2)] : 1;
  return { venues, medianScore };
}
