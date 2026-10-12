/**
 * Keyboard access to the NFL views' data tables (JS-WR-04).
 *
 * Each view mirrors its chart in a table inside a `DATA_TABLE_CLASS` wrapper:
 * visually hidden at rest, shown in place by style.css while keyboard focus is
 * inside it, so a sighted keyboard user sees which row button is focused. Row
 * buttons carry a `data-key`; a rebuild after a pick puts focus back on the
 * button with the same key instead of dropping it to the page.
 */

/** The wrapper's classes: hidden like `.visually-hidden`, shown on focus-within. */
export const DATA_TABLE_CLASS = 'visually-hidden nfl-data-table';

/** The row button in `tbody` whose `data-key` is `key`, or null. */
export function findRowButton(tbody, key) {
  for (const b of tbody.querySelectorAll('button[data-key]')) {
    if (b.dataset.key === key) return b;
  }
  return null;
}

/**
 * Runs `build()` (which replaces `tbody`'s rows) and, when a row button had
 * focus before, focuses the rebuilt button with the same `data-key`.
 */
export function rebuildKeepingFocus(tbody, build) {
  const active = document.activeElement;
  const key = active instanceof HTMLElement && tbody.contains(active) ? active.dataset.key : undefined;
  build();
  if (key === undefined) return;
  const next = findRowButton(tbody, key);
  if (next) next.focus();
}

/**
 * One tab stop across `tbody`'s row buttons (a roving tabindex), for tables
 * with a row per game. Call after every rebuild; ArrowUp/ArrowDown, Home and
 * End move focus between the buttons. The key listener is bound once.
 */
export function rovingRows(tbody) {
  const buttons = [...tbody.querySelectorAll('button[data-key]')];
  const keep = buttons.find((b) => b === document.activeElement) ?? buttons[0];
  for (const b of buttons) b.tabIndex = b === keep ? 0 : -1;
  if (tbody.dataset.roving === 'true') return;
  tbody.dataset.roving = 'true';
  tbody.addEventListener('keydown', (e) => {
    const btn = e.target.closest('button[data-key]');
    if (!btn) return;
    const all = [...tbody.querySelectorAll('button[data-key]')];
    const at = all.indexOf(btn);
    let target = null;
    if (e.key === 'ArrowDown') target = all[at + 1];
    else if (e.key === 'ArrowUp') target = all[at - 1];
    else if (e.key === 'Home') target = all[0];
    else if (e.key === 'End') target = all[all.length - 1];
    if (!target) return;
    e.preventDefault();
    btn.tabIndex = -1;
    target.tabIndex = 0;
    target.focus();
  });
}
