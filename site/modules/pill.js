/**
 * Shared text-pill builder (SITE-26): a family-colored, WCAG-AA-contrast
 * text pill reused by the legend chips, the detail panel's network field,
 * and the matched-games table's network cell (plan 05).
 *
 * DOM-free except for `currentTheme`'s own `window.matchMedia` read and
 * `makePill`'s `document.createElement` call -- no other browser API is
 * touched, so this module stays importable from node for a quick check. DOM
 * is built only with createElement/textContent -- never any
 * markup-injecting DOM API (T-04-31/T-04-34), matching filters.js/panel.js/
 * table.js's own convention.
 */

import { FAMILY_COLORS, PILL_TEXT_COLOR, familyKey } from './palette.js';

/**
 * The current color-scheme theme, read live from the browser (not cached),
 * matching `app.js`'s own `darkMedia` check.
 * @returns {"light"|"dark"}
 */
export function currentTheme() {
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

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
