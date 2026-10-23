/**
 * Custom HTML chip legend (D-04, D-16, SITE-20, SITE-26): a horizontal row
 * of clickable outlined chips (family dot plus label) above the chart, replacing Plotly's
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
 *
 * The Fade | Hide switch (`#dots-toggle`) lives beside the list in
 * `#legend-row`, outside the rebuilt `<ul>`. Its rule: every filter, Networks
 * included, fades the games it excludes unless Hide is on (04.16 D-15). It is concealed off Scatter.
 */

import { familyToggledOff, familyIsSole } from './select.js';
import { FAMILY_COLORS, FAMILY_LABELS, MAP_FAMILY_COLORS } from './palette.js';
import { currentTheme } from './pill.js';

/** D-07: two single clicks (or taps) on one pill within this many ms, by input time,
 * count as a double-click. */
export const DOUBLE_TAP_MS = 300;
/** Upper bound on a `detail === 2` click's gap from the first, so a stale first
 * click (and its `networks` snapshot) never pairs with it (WR-02). */
export const DOUBLE_CLICK_MAX_MS = 1000;

/**
 * D-05..D-08: a second click on the same pill (event.detail === 2 within
 * DOUBLE_CLICK_MAX_MS, or a second click within DOUBLE_TAP_MS, which also
 * covers double-tap) shows only that family, like Networks > Only. Detection
 * runs on `click` plus `detail` because a native `dblclick` never fires on
 * pills rebuilt every render; gaps are measured with `event.timeStamp`. The
 * first click snapshots the filter before toggling, so the result comes from
 * the pre-click state. Keyboard clicks (detail 0) never count; detail >= 3 is
 * ignored; `reset()` drops the pending first click (a click between pills).
 * Shared with the NFL legends.
 * @param {{onToggle: (key: string) => void,
 *   onOnly: (key: string, before: *) => void,
 *   snapshot: () => *}} args
 */
export function createOnlyDetector({ onToggle, onOnly, snapshot }) {
  let last = null;
  return {
    click(ev, key) {
      if (ev.detail >= 3) return;
      // The event's own input time, not the handler's wall clock: the first
      // click's synchronous render can block the main thread for 100-300ms on a
      // slow phone, and the queued second tap must not be charged for it (WR-01).
      const t = ev.timeStamp;
      const gap = last === null ? Infinity : t - last.time;
      const second = last !== null && last.key === key && ev.detail !== 0
        && (ev.detail === 2 ? gap <= DOUBLE_CLICK_MAX_MS : gap <= DOUBLE_TAP_MS);
      if (second) {
        const before = last.before;
        last = null;
        onOnly(key, before);
        return;
      }
      if (ev.detail === 0) {
        last = null;
      } else {
        last = { key, time: t, before: snapshot() };
      }
      onToggle(key);
    },
    reset() {
      last = null;
    },
  };
}

/**
 * Binds one delegated click listener on `listEl` for every legend chip,
 * present now or rebuilt later by `renderLegend`. Native `<button>`
 * elements already give Enter/Space activation for free, so no separate
 * `keydown` handler is needed. Click rule: see `createOnlyDetector`.
 * @param {{listEl: HTMLElement, onToggle: (family: string) => void,
 *   onOnly: (family: string, before: string[]|null) => void,
 *   getNetworks: () => string[]|null,
 *   switchEl?: HTMLElement|null, onDots?: (value: string) => void,
 *   colorsEl?: HTMLElement|null, onColors?: (value: string) => void}} args
 */
export function initLegend({
  listEl,
  onToggle,
  onOnly,
  getNetworks,
  switchEl,
  onDots,
  colorsEl,
  onColors,
}) {
  const detector = createOnlyDetector({ onToggle, onOnly, snapshot: getNetworks });
  if (switchEl) {
    switchEl.addEventListener('click', (ev) => {
      const button = ev.target.closest('button[data-dots]');
      if (!button) return;
      const value = button.dataset.dots;
      if (value === 'fade' || value === 'hide') onDots(value);
    });
  }
  if (colorsEl) {
    colorsEl.addEventListener('click', (ev) => {
      const button = ev.target.closest('button[data-colors]');
      if (!button) return;
      const value = button.dataset.colors;
      if (value === 'on' || value === 'off') onColors(value);
    });
  }
  listEl.addEventListener('click', (ev) => {
    const button = ev.target.closest('button[data-family]');
    if (!button) {
      // A click in the gaps between pills ends any pending first click (WR-02).
      detector.reset();
      return;
    }
    detector.click(ev, button.dataset.family);
  });
}

/**
 * Rebuilds `#legend-chips`'s children from `data.families`, syncing each
 * chip's `aria-pressed` and fill/border styling to whether the Networks
 * filter currently excludes every one of that family's networks (D-16).
 *
 * D-16: a chip whose family has no offered channel under the current filters
 * (`view.facets.networks` sums to 0) is greyed via `data-offered="false"`,
 * not hidden, because the legend also explains the chart colors; it keeps
 * its `aria-pressed` and still toggles the family.
 * @param {{data: object, state: object, view?: object}} args
 */
export function renderLegend({ data, state, view }) {
  const listEl = document.getElementById('legend-chips');
  if (!listEl) return;
  const theme = currentTheme();
  const palette = state.view === 'map' ? MAP_FAMILY_COLORS : FAMILY_COLORS;
  const items = data.families.map((family) => {
    const li = document.createElement('li');
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'legend-chip';
    button.dataset.family = family;
    // Outlined chip (13-12): an 8px family-colour dot plus the family label; the chip itself
    // is never filled. No logos: a chip stands for several channels.
    const dot = document.createElement('span');
    dot.className = 'legend-dot';
    dot.setAttribute('aria-hidden', 'true');
    dot.style.backgroundColor = palette[theme][family];
    const label = document.createElement('span');
    label.className = 'legend-label';
    label.textContent = FAMILY_LABELS[family];
    button.append(dot, label);
    const pressed = !familyToggledOff(data, state, family);
    button.setAttribute('aria-pressed', String(pressed));
    const hint = familyIsSole(data, view, family, state.networks)
      ? 'Double-click to show all networks'
      : `Double-click to show only ${FAMILY_LABELS[family]}`;
    button.title = hint;
    button.setAttribute('aria-description', hint);
    const counts = view?.facets?.networks;
    const offered = !counts
      || (data.networksByFamily.get(family) ?? []).reduce((sum, idx) => sum + (counts[idx] ?? 0), 0) > 0;
    button.dataset.offered = String(offered);
    // Offered, pressed and dashed states are drawn by CSS from data-offered and aria-pressed.
    li.appendChild(button);
    return li;
  });
  listEl.replaceChildren(...items);
  const toggleEl = document.getElementById('dots-toggle');
  if (toggleEl) {
    const mode = state.dots === 'hide' ? 'hide' : 'fade';
    for (const button of toggleEl.querySelectorAll('button[data-dots]')) {
      button.setAttribute('aria-pressed', String(button.dataset.dots === mode));
    }
    toggleEl.classList.toggle('is-concealed', state.view !== 'scatter');
  }
  const colorsEl = document.getElementById('colors-toggle');
  if (colorsEl) {
    const mode = state.colors === 'off' ? 'off' : 'on';
    for (const button of colorsEl.querySelectorAll('button[data-colors]')) {
      button.setAttribute('aria-pressed', String(button.dataset.colors === mode));
    }
    colorsEl.classList.toggle('is-concealed', state.view !== 'map');
  }
}
