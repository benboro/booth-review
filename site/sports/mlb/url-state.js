/**
 * MLB URL state (D-01). DOM-free. Encodes `sport=mlb` first plus only
 * non-default params; decoding allowlists every value and never throws.
 *
 * `booth` is the booth's play-by-play person id and `game` a date~away~home~number id,
 * both stable across rebuilds. An old positional link (`booth=1`, `game=3`) matches no
 * id and falls back to the default view.
 */
import { canonicalMlbState, defaultMlbState, MLB_VIEWS } from './state.js';

export function encodeMlbState(state, model) {
  const s = canonicalMlbState(state, model);
  const d = defaultMlbState();
  const parts = ['sport=mlb'];
  if (s.view !== d.view) parts.push('view=' + s.view);
  const boothId = s.booth == null ? null : model.boothIds[Number(s.booth)];
  if (boothId != null && model.boothIndexById.get(boothId) === Number(s.booth)) {
    parts.push('booth=' + encodeURIComponent(boothId));
  }
  if (s.cell != null) parts.push('cell=' + encodeURIComponent(s.cell));
  if (s.stype != null) parts.push('stype=' + s.stype);
  if (s.sround != null) parts.push('sround=' + s.sround);
  const gameId = s.game == null ? null : model.gameIds[s.game];
  if (gameId != null && model.gameIndexById.get(gameId) === s.game) {
    parts.push('game=' + encodeURIComponent(gameId));
  }
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
      case 'booth': {
        const at = model.boothIndexById.get(safeDecode(raw));
        state.booth = at == null ? null : String(at);
        break;
      }
      case 'cell': state.cell = safeDecode(raw); break;
      case 'stype': state.stype = safeDecode(raw); break;
      case 'sround': state.sround = safeDecode(raw); break;
      case 'game': {
        const at = model.gameIndexById.get(safeDecode(raw));
        state.game = at == null ? null : at;
        break;
      }
      default: break;
    }
  }
  return canonicalMlbState(state, model);
}
