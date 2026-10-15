/**
 * MLB URL state (D-01). DOM-free. Encodes `sport=mlb` first plus only
 * non-default params; decoding allowlists every value and never throws.
 */
import { canonicalMlbState, defaultMlbState, MLB_VIEWS } from './state.js';

export function encodeMlbState(state, model) {
  const s = canonicalMlbState(state, model);
  const d = defaultMlbState();
  const parts = ['sport=mlb'];
  if (s.view !== d.view) parts.push('view=' + s.view);
  if (s.booth != null) parts.push('booth=' + s.booth);
  if (s.cell != null) parts.push('cell=' + encodeURIComponent(s.cell));
  if (s.game != null) parts.push('game=' + s.game);
  return '?' + parts.join('&');
}

function safeDecode(piece) {
  try {
    return decodeURIComponent(piece);
  } catch {
    return null;
  }
}

/**
 * @param {string} search raw query string (with or without '?')
 * @returns {object} canonical state
 */
export function decodeMlbState(search, model) {
  const state = defaultMlbState();
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
      case 'view': if (MLB_VIEWS.includes(raw)) state.view = raw; break;
      case 'booth': state.booth = raw; break;
      case 'cell': state.cell = safeDecode(raw); break;
      case 'game': state.game = raw === '' ? null : Number(raw); break;
      default: break;
    }
  }
  return canonicalMlbState(state, model);
}
