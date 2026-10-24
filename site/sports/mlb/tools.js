/**
 * MLB view tools in the chart module header (SHELL-06, 13-13; a copy of the NFL helper, never an import). Each view mounts its tools
 * into the shared header slot (`ctx.chartTools`) inside its own wrapper; `showActiveView`
 * in index.js shows only the active view's wrapper, so the header never carries another
 * view's controls. With no slot (a bare test host) the tools stay in the view's container.
 */

/**
 * Wraps `nodes` in a per-view tools container and seats it in the header slot.
 * @param {{chartTools?: HTMLElement|null}} ctx
 * @param {string} viewId
 * @param {HTMLElement[]} nodes
 * @param {HTMLElement} container - the view's own section, used when there is no slot.
 * @returns {HTMLElement} the wrapper.
 */
export function mountViewTools(ctx, viewId, nodes, container) {
  const wrap = document.createElement('div');
  wrap.className = 'module-tools-view';
  wrap.dataset.toolsFor = viewId;
  wrap.append(...nodes);
  const slot = ctx.chartTools ?? null;
  (slot ?? container).appendChild(wrap);
  return wrap;
}

/**
 * Shows the active view's tools wrapper and hides the others.
 * @param {HTMLElement|null} slot
 * @param {string} activeView
 */
export function showToolsFor(slot, activeView) {
  if (!slot) return;
  for (const wrap of slot.querySelectorAll('[data-tools-for]')) {
    wrap.hidden = wrap.dataset.toolsFor !== activeView;
  }
}
