/**
 * 04.13 D-12: the "No public rating" label/info button in the band's gap row and
 * its small cause note. DOM-only: toggles hidden/aria attributes and px positions;
 * never writes data strings.
 */
import { BAND } from './chart.js';

/**
 * Wires the toggle, Escape and outside-press handling. Safe to call once.
 * @param {{button: HTMLElement|null, note: HTMLElement|null}} els
 */
export function initBandInfo({ button, note }) {
  if (!button || !note) return;
  const setOpen = (open, refocus) => {
    note.hidden = !open;
    button.setAttribute('aria-expanded', String(open));
    if (!open && refocus) button.focus();
  };
  button.addEventListener('click', () => setOpen(note.hidden, false));
  document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape' && !note.hidden) setOpen(false, true);
  });
  document.addEventListener('pointerdown', (ev) => {
    if (note.hidden) return;
    if (button.contains(ev.target) || note.contains(ev.target)) return;
    setOpen(false, false);
  });
}

/** Closes the note without moving focus (used when the button is hidden). */
export function closeBandNote({ button, note }) {
  if (!button || !note) return;
  note.hidden = true;
  button.setAttribute('aria-expanded', 'false');
}

/**
 * Centers the button vertically in the gap row and left-aligns it to plot left + 4px;
 * places the note just under it, clamped inside the chart's width.
 * @param {HTMLElement} chartEl
 * @param {HTMLElement} button
 * @param {HTMLElement} note
 */
export function positionBandInfo(chartEl, button, note) {
  const fl = chartEl && chartEl._fullLayout;
  if (!fl || !fl.yaxis2 || !fl._size || !button) return;
  const top = fl.yaxis2._offset - BAND.gapPx / 2 - button.offsetHeight / 2;
  const left = fl._size.l + 4;
  button.style.top = `${Math.round(top)}px`;
  button.style.left = `${Math.round(left)}px`;
  if (note) {
    const noteW = note.offsetWidth || 280;
    const maxLeft = Math.max(0, chartEl.clientWidth - noteW - 4);
    note.style.top = `${Math.round(top + button.offsetHeight)}px`;
    note.style.left = `${Math.round(Math.min(left, maxLeft))}px`;
  }
}
