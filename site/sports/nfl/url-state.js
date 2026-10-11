/**
 * NFL URL state (D-05, D-06). DOM-free. Encodes `sport=nfl` first plus only
 * non-default params; decoding allowlists every value and never throws.
 */
import { canonicalNflState, defaultNflState, CATEGORY_OPTIONS, METRICS } from './state.js';

const VIEW_PARAM = ['fox', 'agotw', 'scatter'];

/**
 * @returns {string} '?sport=nfl' plus non-default params, in documented order
 */
export function encodeNflState(state, model) {
  const s = canonicalNflState(state, model);
  const d = defaultNflState(model);
  const parts = ['sport=nfl'];
  if (VIEW_PARAM.includes(s.view)) parts.push('view=' + s.view);
  if (s.seasons[0] !== d.seasons[0] || s.seasons[1] !== d.seasons[1]) {
    parts.push(`seasons=${s.seasons[0]}-${s.seasons[1]}`);
  }
  if (s.teams.length) parts.push('team=' + s.teams.map(encodeURIComponent).join(','));
  if (s.people.length) parts.push('people=' + s.people.map(encodeURIComponent).join(','));
  if (s.cats.length) parts.push('cat=' + s.cats.map(encodeURIComponent).join(','));
  if (s.fseason !== d.fseason && s.fseason != null) parts.push('fseason=' + s.fseason);
  if (s.adjusted) parts.push('adj=1');
  if (s.metric !== 'margin') parts.push('m=' + s.metric);
  if (s.agotwY === 'resid') parts.push('ay=resid');
  if (s.scatterX === 'margin') parts.push('x=margin');
  if (s.scatterY === 'excitement') parts.push('y=excitement');
  if (s.dots === 'hide') parts.push('dots=hide');
  return '?' + parts.join('&');
}

function safeDecode(piece) {
  try {
    return decodeURIComponent(piece);
  } catch {
    return null;
  }
}

function list(value) {
  const out = [];
  for (const piece of value.split(',')) {
    const v = safeDecode(piece);
    if (v !== null && v !== '') out.push(v);
  }
  return out;
}

/**
 * @param {string} search raw query string (with or without '?')
 * @returns {object} canonical state
 */
export function decodeNflState(search, model) {
  const state = defaultNflState(model);
  const q = typeof search === 'string' ? search.replace(/^\?/, '') : '';
  const seen = new Set();
  for (const pair of q.split('&')) {
    const eq = pair.indexOf('=');
    if (eq < 0) continue;
    const key = pair.slice(0, eq);
    const raw = pair.slice(eq + 1);
    if (seen.has(key)) continue;
    seen.add(key);
    switch (key) {
      case 'view': {
        const v = safeDecode(raw);
        if (VIEW_PARAM.includes(v)) state.view = v;
        break;
      }
      case 'seasons': {
        const m = /^(\d{4})-(\d{4})$/.exec(raw);
        if (m) state.seasons = [Number(m[1]), Number(m[2])];
        break;
      }
      case 'team': state.teams = list(raw); break;
      case 'people': state.people = list(raw); break;
      case 'cat': state.cats = list(raw).filter((k) => CATEGORY_OPTIONS.some((o) => o.key === k)); break;
      case 'fseason':
        if (/^\d{4}$/.test(raw)) state.fseason = Number(raw);
        break;
      case 'adj': state.adjusted = raw === '1'; break;
      case 'm': if (METRICS.includes(raw)) state.metric = raw; break;
      case 'ay': if (raw === 'resid') state.agotwY = 'resid'; break;
      case 'x': if (raw === 'margin') state.scatterX = 'margin'; break;
      case 'y': if (raw === 'excitement') state.scatterY = 'excitement'; break;
      case 'dots': if (raw === 'hide') state.dots = 'hide'; break;
      default: break;
    }
  }
  return canonicalNflState(state, model);
}
