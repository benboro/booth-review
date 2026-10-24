/**
 * Raw reason bar (D-06): a status line that explains why a view fell back to Raw.
 * Built with createElement/textContent only; absent and spaceless when not shown.
 */

/** @param {string} id */
export function createReasonBar(id) {
  const bar = document.createElement('div');
  bar.className = 'nfl-reason-bar';
  bar.id = id;
  bar.setAttribute('role', 'status');
  bar.hidden = true;
  return bar;
}

/** @param {HTMLElement} bar @param {string} text */
export function setReason(bar, text) {
  bar.textContent = text || '';
  bar.hidden = !text;
}

/**
 * Mark a link button as disabled without removing it from the tab order; callers
 * ignore its clicks while disabled.
 * @param {HTMLElement} button @param {HTMLElement} bar @param {boolean} disabled
 */
export function linkDisabled(button, bar, disabled) {
  if (disabled) {
    button.setAttribute('aria-disabled', 'true');
    button.setAttribute('aria-describedby', bar.id);
  } else {
    button.removeAttribute('aria-disabled');
    button.removeAttribute('aria-describedby');
  }
}
