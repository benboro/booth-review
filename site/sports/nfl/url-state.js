/**
 * NFL URL state (D-05, D-06). DOM-free. Encodes `sport=nfl` first plus only
 * non-default params; decoding allowlists every value and never throws.
 */
import {
  canonicalNflState, defaultNflState, CATEGORY_OPTIONS, CREW_METRICS, NFL_NATURAL_DIR,
} from './state.js';
import { defaultSort } from '../../modules/crew-groups.js';

const CSORT_RE = /^(booth|season|rank|network|games|margin|exc|viewers)(\.(asc|desc))?$/;

const VIEW_PARAM = ['crews', 'viewership', 'scatter'];
const VIEW_ALIASES = Object.freeze({ fox: 'crews', agotw: 'viewership' });

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
  if (s.booths.length) parts.push('booths=' + s.booths.map(encodeURIComponent).join(','));
  if (s.perseason === false) parts.push('perseason=0');
  // decode keeps csort=season only when the table has a Season column (Per season on and a
  // multi-season range), so encode drops it under the same rule: URL and reload then agree.
  const seasonColumn = s.perseason !== false && s.seasons[1] > s.seasons[0];
  if (s.csort && (s.csort.key !== 'season' || seasonColumn)) {
    const def = defaultSort(s.perseason !== false);
    if (s.csort.key !== def.key || s.csort.dir !== def.dir) {
      parts.push('csort=' + (s.csort.dir === NFL_NATURAL_DIR[s.csort.key] ? s.csort.key : `${s.csort.key}.${s.csort.dir}`));
    }
  }
  if (s.adjusted) parts.push('adj=1');
  if (s.metric !== 'margin') parts.push('m=' + s.metric);
  if (s.viewY === 'resid') parts.push('ay=resid');
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
  let legacySeason = null;
  let csort = null;
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
        else if (Object.prototype.hasOwnProperty.call(VIEW_ALIASES, v)) state.view = VIEW_ALIASES[v];
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
      case 'net': break; // legacy one-network param: read and ignored
      case 'booths': state.booths = list(raw); break;
      case 'cseason':
      case 'fseason':
        // The first of cseason and fseason seen wins (fseason is the old name).
        if (legacySeason == null && /^\d{4}$/.test(raw)) legacySeason = Number(raw);
        break;
      case 'perseason': state.perseason = raw !== '0'; break;
      case 'csort': {
        const m = CSORT_RE.exec(raw);
        if (m) csort = { key: m[1], dir: m[3] || NFL_NATURAL_DIR[m[1]] };
        break;
      }
      case 'adj': state.adjusted = raw === '1'; break;
      case 'm': if (CREW_METRICS.includes(raw)) state.metric = raw; break;
      case 'ay': if (raw === 'resid') state.viewY = 'resid'; break;
      case 'x': if (raw === 'margin') state.scatterX = 'margin'; break;
      case 'y': if (raw === 'excitement') state.scatterY = 'excitement'; break;
      case 'dots': if (raw === 'hide') state.dots = 'hide'; break;
      default: break;
    }
  }
  if (legacySeason != null && !seen.has('seasons')
    && legacySeason >= model.seasons[0] && legacySeason <= model.seasons[1]) {
    state.seasons = [legacySeason, legacySeason];
  }
  const out = canonicalNflState(state, model);
  if (csort) {
    const def = defaultSort(out.perseason);
    const seasonOk = out.perseason && out.seasons[1] > out.seasons[0];
    if ((csort.key !== 'season' || seasonOk) && !(csort.key === def.key && csort.dir === def.dir)) {
      out.csort = csort;
    }
  }
  return out;
}
