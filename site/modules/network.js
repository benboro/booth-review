/**
 * Network mark builder (SHELL-05): one place that turns a network into either
 * its vendored logo (an `<img>`, so SVG script can never run) or, for ids with
 * no logo, an 8px family dot plus the name. Call sites switch to this builder
 * instead of building network text or pills themselves.
 *
 * DOM is built only with createElement/textContent/setAttribute, and `src`
 * comes only from the logo map, never from row text (T-13-08).
 */

import { FAMILY_COLORS, familyKey } from './palette.js';
import { currentTheme, onThemeChange } from './theme.js';
import { logoFor } from './logos.js';

let themeWatch = null;

/**
 * Repaints every family dot on the page when data-theme changes, so dots in tables,
 * chips and open panels follow the theme hook, not only the active chart (SHELL-02).
 * Armed once, on the first dot built.
 */
function watchTheme() {
  if (themeWatch) return;
  themeWatch = onThemeChange((theme) => {
    for (const dot of document.querySelectorAll('.net-dot[data-family]')) {
      dot.style.background = FAMILY_COLORS[theme][dot.dataset.family];
    }
  });
}

/**
 * Builds one network mark (`span.net-mark`).
 * @param {{id: string, name: string, family: string}} network
 * @param {{dot?: boolean}} [opts] - dot: draw the family dot first (default true).
 * @returns {HTMLSpanElement}
 */
export function networkMark({ id, name, family }, { dot = true } = {}) {
  const mark = document.createElement('span');
  mark.className = 'net-mark';
  if (dot) {
    const dotEl = document.createElement('span');
    dotEl.className = 'net-dot';
    const key = familyKey(family);
    dotEl.dataset.family = key;
    dotEl.style.background = FAMILY_COLORS[currentTheme()][key];
    watchTheme();
    mark.appendChild(dotEl);
  }
  const entry = logoFor(id);
  if (entry) {
    const img = document.createElement('img');
    img.className = entry.box === 'badge' ? 'net-logo net-logo--badge' : 'net-logo';
    img.src = entry.file;
    img.alt = name;
    img.title = name;
    img.setAttribute('width', String(entry.width));
    img.setAttribute('height', String(entry.height));
    img.decoding = 'async';
    mark.appendChild(img);
  } else {
    const label = document.createElement('span');
    label.className = 'net-name';
    label.textContent = name;
    mark.appendChild(label);
  }
  return mark;
}

/**
 * Builds a `span.net-marks` holding one mark per network, in the given order
 * (primary first), for multi-network cells.
 * @param {Array<{id: string, name: string, family: string}>} list
 * @param {{dot?: boolean}} [opts]
 * @returns {HTMLSpanElement}
 */
export function networkMarks(list, opts) {
  const wrap = document.createElement('span');
  wrap.className = 'net-marks';
  for (const network of list) wrap.appendChild(networkMark(network, opts));
  return wrap;
}
