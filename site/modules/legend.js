/**
 * Custom HTML chip legend (D-04, D-16, SITE-20, SITE-26): a horizontal row
 * of clickable family-colored pills above the chart, replacing Plotly's
 * built-in legend now that `chart.js` sets `showlegend: false` on every
 * trace. Clicking (or Enter/Space on) a chip toggles that family in the
 * Networks filter through the same `toggleFamilyNetworks` helper the
 * Networks popover checklist will use (plan 04), so the chip row and the
 * filter always agree.
 *
 * `initLegend` binds one delegated click listener, once; `renderLegend` is a
 * pure DOM sync, rebuilding the chip list every render cycle -- the same
 * init-once/render-every-time split `filters.js`/`topbar.js` already use.
 * DOM is built only with createElement/textContent/replaceChildren -- never
 * any markup-injecting DOM API (T-04-31/T-04-34).
 */

import { familyToggledOff } from './select.js';
import { FAMILY_COLORS, FAMILY_LABELS, PILL_TEXT_COLOR } from './palette.js';
import { currentTheme } from './pill.js';

/**
 * Binds one delegated click listener on `listEl` for every legend chip,
 * present now or rebuilt later by `renderLegend`. Native `<button>`
 * elements already give Enter/Space activation for free, so no separate
 * `keydown` handler is needed.
 * @param {{listEl: HTMLElement, onToggle: (family: string) => void}} args
 */
export function initLegend({ listEl, onToggle }) {
  listEl.addEventListener('click', (ev) => {
    const button = ev.target.closest('button[data-family]');
    if (!button) return;
    onToggle(button.dataset.family);
  });
}

/**
 * Rebuilds `#legend-chips`'s children from `data.families`, syncing each
 * chip's `aria-pressed` and fill/border styling to whether the Networks
 * filter currently excludes every one of that family's networks (D-16).
 * @param {{data: object, state: object}} args
 */
export function renderLegend({ data, state }) {
  const listEl = document.getElementById('legend-chips');
  if (!listEl) return;
  const theme = currentTheme();
  const items = data.families.map((family) => {
    const li = document.createElement('li');
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'legend-chip pill';
    button.dataset.family = family;
    button.textContent = FAMILY_LABELS[family];
    const pressed = !familyToggledOff(data, state, family);
    button.setAttribute('aria-pressed', String(pressed));
    if (pressed) {
      button.style.backgroundColor = FAMILY_COLORS[theme][family];
      button.style.color = PILL_TEXT_COLOR[family];
      button.style.borderColor = '';
    } else {
      // Toggled off: clear the inline fill so CSS's own
      // `.legend-chip[aria-pressed="false"]` rule (transparent background,
      // `--text` color) applies; only the border keeps the family color.
      button.style.backgroundColor = '';
      button.style.color = '';
      button.style.borderColor = FAMILY_COLORS[theme][family];
    }
    li.appendChild(button);
    return li;
  });
  listEl.replaceChildren(...items);
}
