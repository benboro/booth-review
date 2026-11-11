/**
 * Page-height hold for synchronous rebuilds (user rule 2026-11-10: nothing on This weekend may
 * jump the page). A rebuild that empties a host (a destroy, a replaceChildren, a map node moved
 * out) and then reads a size forces a layout while the document is briefly shorter; the browser
 * clamps the scroll there and the page jumps up. Holding the root element at its current scroll
 * height for the length of the rebuild means no layout inside it can be shorter than the page
 * was, so the scroll is never clamped. The hold is released before the paint, so a page that
 * really ends shorter settles at its new height as it always did.
 *
 * The hold covers synchronous work only: it lifts when `fn` returns, so a height that changes
 * later (an async draw, a late image) must be settled inside the build instead, as the weekend
 * map's shading caption is.
 *
 * Holds nest: only the outermost call pins and restores, so the app's render, a sport's render
 * and the weekend view's own rebuilds can each wrap themselves without knowing about the others.
 */
let depth = 0;
let saved = '';

/**
 * Runs `fn` with the document held at its current scroll height.
 * @template T
 * @param {() => T} fn
 * @returns {T}
 */
export function holdPage(fn) {
  const root = document.documentElement;
  if (depth === 0) {
    saved = root.style.minHeight;
    const h = root.scrollHeight;
    if (h > 0) root.style.minHeight = `${h}px`;
  }
  depth += 1;
  try {
    return fn();
  } finally {
    depth -= 1;
    if (depth === 0) root.style.minHeight = saved;
  }
}
