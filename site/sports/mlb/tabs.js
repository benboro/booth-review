/**
 * MLB chart tabs: a roving-tabindex tablist built from the view ids that have
 * a module (plan 09-19 registers the views; until then the list is empty and
 * the tablist stays hidden). Programmatic changes never steal focus.
 */

const LABELS = Object.freeze({
  apple: 'Apple crews',
  postseason: 'Postseason booths',
});

/**
 * @param {HTMLElement} host
 * @param {{views: string[], onSelect: (id: string) => void}} opts
 */
export function createMlbTabs(host, { views, onSelect }) {
  const list = document.createElement('div');
  list.id = 'mlb-chart-tabs';
  list.className = 'chart-tabs';
  list.setAttribute('role', 'tablist');
  list.setAttribute('aria-label', 'Chart view');
  list.hidden = views.length === 0;
  const buttons = views.map((id) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.id = `mlb-tab-${id}`;
    b.className = 'chart-tab';
    b.setAttribute('role', 'tab');
    b.dataset.view = id;
    b.setAttribute('aria-controls', `mlb-view-${id}`);
    b.setAttribute('aria-selected', 'false');
    b.tabIndex = -1;
    b.textContent = LABELS[id] ?? id;
    list.appendChild(b);
    return b;
  });
  host.appendChild(list);

  let disabled = false;

  function setActive(id) {
    for (const b of buttons) {
      const on = b.dataset.view === id;
      b.setAttribute('aria-selected', on ? 'true' : 'false');
      b.tabIndex = on ? 0 : -1;
    }
  }

  list.addEventListener('click', (ev) => {
    const tab = ev.target.closest('button[data-view]');
    if (tab && !disabled) onSelect(tab.dataset.view);
  });

  list.addEventListener('keydown', (ev) => {
    const current = ev.target.closest('button[data-view]');
    if (!current) return;
    const at = buttons.indexOf(current);
    let target = null;
    if (ev.key === 'ArrowRight') target = buttons[(at + 1) % buttons.length];
    else if (ev.key === 'ArrowLeft') target = buttons[(at - 1 + buttons.length) % buttons.length];
    else if (ev.key === 'Home') target = buttons[0];
    else if (ev.key === 'End') target = buttons[buttons.length - 1];
    if (target) {
      ev.preventDefault();
      for (const b of buttons) b.tabIndex = b === target ? 0 : -1;
      target.focus();
      return;
    }
    if (ev.key === 'Enter' || ev.key === ' ') {
      ev.preventDefault();
      if (!disabled) {
        onSelect(current.dataset.view);
        current.focus();
      }
    }
  });

  return {
    setActive,
    setDisabled(value) {
      disabled = value;
      for (const b of buttons) {
        if (value) b.setAttribute('aria-disabled', 'true');
        else b.removeAttribute('aria-disabled');
      }
    },
  };
}
