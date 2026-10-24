/**
 * Shared text-pill builder (SITE-26): a family-colored, WCAG-AA-contrast
 * text pill reused by the legend chips, the detail panel's network field,
 * and the matched-games table's network cell (plan 05).
 *
 * DOM-free except for `makePill`'s `document.createElement` call -- no other browser API is
 * touched, so this module stays importable from node for a quick check. DOM
 * is built only with createElement/textContent -- never any
 * markup-injecting DOM API (T-04-31/T-04-34), matching filters.js/panel.js/
 * table.js's own convention.
 */

import { FAMILY_COLORS, PILL_TEXT_COLOR, familyKey } from './palette.js';

/*
 * Role pills (D-14..D-16, T-04.1-25): PBP is a solid violet pill, Analyst a
 * violet outline pill, anything else a grey "Sideline" outline pill. Colors
 * come only from CSS tokens (they follow the theme); the role is allowlisted
 * before it reaches dataset/aria-label and text is set via textContent. Each
 * accessible name begins with the visible text (WCAG 2.5.3 Label in Name).
 */
export const ROLE_PILL_TEXT = Object.freeze({ pbp: 'PBP', analyst: 'Analyst', unknown: 'Sideline' });
export const ROLE_PILL_NAMES = Object.freeze({
  pbp: 'PBP, play-by-play',
  analyst: 'Analyst',
  unknown: 'Sideline',
});

/**
 * Folds any value to a known role key by allowlist (never an object-property
 * lookup on raw input, so "constructor" or "__proto__" cannot resolve).
 * @param {unknown} role
 * @returns {"pbp"|"analyst"|"unknown"}
 */
export function roleKey(role) {
  return role === 'pbp' || role === 'analyst' ? role : 'unknown';
}

/**
 * Builds a role pill (`span.role-pill`).
 * @param {string} role - "pbp", "analyst", or anything else (folded to "unknown").
 * @returns {HTMLSpanElement}
 */
export function makeRolePill(role) {
  const key = roleKey(role);
  const span = document.createElement('span');
  span.className = 'role-pill';
  span.dataset.role = key;
  span.setAttribute('role', 'img');
  span.setAttribute('aria-label', ROLE_PILL_NAMES[key]);
  span.textContent = ROLE_PILL_TEXT[key];
  return span;
}

/**
 * Wraps a name node and its role pills in one `span.name-with-roles` that
 * cannot break inside (SITE-38): a pill never wraps onto a line without its
 * announcer. The unit itself still wraps whole between people.
 * @param {Node[]} nodes - the name node(s) followed by the pill(s).
 * @returns {HTMLSpanElement}
 */
export function nameWithRoles(...nodes) {
  const span = document.createElement('span');
  span.className = 'name-with-roles';
  span.append(...nodes);
  return span;
}

/**
 * A crew cell's people as one wrapping list (15-12 r6). Each person after the first carries
 * its own " · " separator, drawn in the gap before it; the list clips that gap (style.css
 * `.crew-list`), so a person who starts a line shows no separator and one who follows
 * another on the same line does -- on every resize, with no measuring. The separator stays
 * real text (aria-hidden) so a plain-text copy still reads "A PBP · B Analyst".
 * @param {Node[]} people - one node per person (a `nameWithRoles` span or plain text)
 * @param {Node[]} [notes] - trailing notes (a provenance tag) that take no separator
 * @returns {HTMLSpanElement}
 */
export function crewList(people, notes = []) {
  const outer = document.createElement('span');
  outer.className = 'crew-list';
  const inner = document.createElement('span');
  inner.className = 'crew-list-inner';
  people.forEach((node, idx) => {
    const item = document.createElement('span');
    item.className = 'crew-item';
    if (idx > 0) {
      const sep = document.createElement('span');
      sep.className = 'crew-sep';
      sep.setAttribute('aria-hidden', 'true');
      sep.textContent = ' · ';
      item.append(sep);
    }
    item.append(node);
    inner.append(item);
  });
  for (const node of notes) {
    const item = document.createElement('span');
    item.className = 'crew-item crew-note';
    item.append(node);
    inner.append(item);
  }
  outer.append(inner);
  return outer;
}

// Re-exported so the existing importers keep working; the theme module owns it.
export { currentTheme } from './theme.js';

/**
 * Builds a filled text pill (`span.pill`) for a network or family name,
 * using `familyKey` to fold a raw network family string to one of
 * `FAMILY_ORDER`'s known keys before looking up its fill/text colors.
 * @param {string} text - the pill's visible text (a network name or family label).
 * @param {string} family - a raw or already-canonical family key.
 * @param {"light"|"dark"} theme
 * @returns {HTMLSpanElement}
 */
export function makePill(text, family, theme) {
  const key = familyKey(family);
  const span = document.createElement('span');
  span.className = 'pill';
  span.dataset.family = key;
  span.style.backgroundColor = FAMILY_COLORS[theme][key];
  span.style.color = PILL_TEXT_COLOR[key];
  span.textContent = text;
  return span;
}
