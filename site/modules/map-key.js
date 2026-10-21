// Map key (Phase 11 D-03, D-06a, D-09): a "Dot size" block of nested outline circles and a
// "Color strength" block of three swatches.
//
// buildMapKey is pure (numbers in, numbers and fixed copy out). renderMapKey builds DOM with
// createElement / createElementNS / textContent only, never HTML strings. Positioning and
// CSS belong to the page that mounts the key.

import { MAP_SPLAT, MUTED } from './palette.js';
import { venueDotSize } from './map-venues.js';

export const KEY_GAME_STEPS = Object.freeze([1, 2, 5, 10, 20, 50]);

const DESCRIPTION = 'Dot size blends the number of games with their audience.';
const SVG_NS = 'http://www.w3.org/2000/svg';
const LABEL_RESERVE = 96;
const LEADER_GAP = 8;
const LABEL_LINE = 20;
const STRENGTH_OPACITY = Object.freeze([0.15, 0.5, 0.88]);

/** Nearest key step in log distance; a tie goes to the smaller step. */
function nearestStep(target) {
  const t = Math.log(Math.max(target, 1e-9));
  let best = KEY_GAME_STEPS[0];
  let bestDist = Infinity;
  for (const s of KEY_GAME_STEPS) {
    const d = Math.abs(Math.log(s) - t);
    if (d < bestDist - 1e-12) {
      best = s;
      bestDist = d;
    }
  }
  return best;
}

/**
 * Key model for the filtered venue set.
 * @param {{venues: object[], maxScore: number, medianRatedViewers: number}} venueModel
 * @param {{phone: boolean, colorsOn: boolean}} opts
 * @returns {{visible: boolean, sizes: {games: number, label: string, diameter: number}[],
 *   showStrength: boolean, description: string}}
 */
export function buildMapKey(venueModel, opts) {
  const { phone = false, colorsOn = true } = opts || {};
  const out = { visible: false, sizes: [], showStrength: Boolean(colorsOn), description: DESCRIPTION };
  if (!venueModel || !venueModel.venues || !venueModel.venues.length || !(venueModel.maxScore > 0)) {
    return out;
  }
  const w = MAP_SPLAT.viewersWeight;
  const m = Math.max(venueModel.medianRatedViewers / 1e6, 0.01);
  const unit = m ** w;
  const nMax = venueModel.maxScore / unit;
  const seen = new Set();
  const games = [];
  for (const target of [nMax, nMax / 4, nMax / 16]) {
    const g = nearestStep(target);
    if (!seen.has(g)) {
      seen.add(g);
      games.push(g);
    }
  }
  games.sort((p, q) => q - p);
  out.sizes = games.map((g) => ({
    games: g,
    label: `${g} ${g === 1 ? 'game' : 'games'}`,
    diameter: venueDotSize(g * unit, venueModel.maxScore)[phone ? 'phone' : 'desktop'],
  }));
  out.visible = true;
  return out;
}

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
}

function svgEl(tag, attrs) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
  return node;
}

/**
 * Rebuilds the key inside a container.
 * @param {HTMLElement} root
 * @param {ReturnType<typeof buildMapKey>} key
 * @param {{theme: 'light'|'dark'}} env
 */
export function renderMapKey(root, key, env) {
  const muted = MUTED[(env && env.theme) || 'light'] || MUTED.light;
  root.replaceChildren();
  root.hidden = !key.visible;
  root.setAttribute('aria-description', key.description);
  if (!key.visible) return;

  if (key.sizes.length) {
    const block = el('div', 'map-key-block');
    block.appendChild(el('p', 'map-key-heading', 'Dot size'));
    // Labels stack at one line each: a label sits level with its circle's top when it can,
    // and is pushed down when the circles are too close together for the text.
    const circleW = Math.ceil(key.sizes[0].diameter);
    const centers = [];
    let prev = -Infinity;
    for (const s of key.sizes) {
      const want = circleW - s.diameter;
      prev = Math.max(want, prev + LABEL_LINE, LABEL_LINE / 2);
      centers.push(prev);
    }
    const height = Math.max(circleW, LABEL_LINE, Math.ceil(prev + LABEL_LINE / 2));
    const box = el('div', 'map-key-sizes');
    box.style.position = 'relative';
    box.style.width = `${circleW + LEADER_GAP + LABEL_RESERVE}px`;
    box.style.height = `${height}px`;
    const svg = svgEl('svg', {
      width: circleW + LEADER_GAP + 4,
      height,
      'aria-hidden': 'true',
      focusable: 'false',
    });
    svg.style.position = 'absolute';
    svg.style.left = '0px';
    svg.style.top = '0px';
    const cx = circleW / 2;
    const single = key.sizes.length === 1;
    key.sizes.forEach((s, i) => {
      const d = s.diameter;
      const top = height - d;
      svg.appendChild(
        svgEl('circle', { cx, cy: single ? height / 2 : height - d / 2, r: d / 2 - 0.5, fill: 'none', stroke: muted, 'stroke-width': 1 }),
      );
      // One circle needs no leader: its label is level with it.
      if (!single) {
        svg.appendChild(
          svgEl('polyline', {
            points: `${cx},${top} ${circleW / 2 + d / 2},${top} ${circleW + LEADER_GAP},${centers[i]}`,
            fill: 'none',
            stroke: muted,
            'stroke-width': 1,
            'stroke-dasharray': '1 2',
          }),
        );
      }
      const label = el('span', 'map-key-label', s.label);
      label.style.position = 'absolute';
      label.style.left = `${circleW + LEADER_GAP + 4}px`;
      label.style.top = `${(single ? height / 2 : centers[i]) - LABEL_LINE / 2}px`;
      box.appendChild(label);
    });
    box.insertBefore(svg, box.firstChild);
    block.appendChild(box);
    root.appendChild(block);
  }

  if (key.showStrength) {
    const block = el('div', 'map-key-block map-key-strength');
    block.appendChild(el('p', 'map-key-heading', 'Color strength'));
    block.appendChild(el('span', 'map-key-end', 'Few games or split networks'));
    for (const o of STRENGTH_OPACITY) {
      const sw = el('span', 'map-key-swatch');
      sw.style.opacity = String(o);
      sw.style.background = muted;
      sw.style.width = '16px';
      sw.style.height = '8px';
      block.appendChild(sw);
    }
    block.appendChild(el('span', 'map-key-end', 'Many games, one network'));
    root.appendChild(block);
  }
}
