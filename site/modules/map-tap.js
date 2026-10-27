/**
 * Tap controller for one Plotly map container (PR #84 / #89 rules, factored out of
 * map-panel.js so each map binds its own document listeners to its own container).
 *
 * On a touch-only device the first tap on a dot shows its card, the second on the same
 * dot opens it, and a tap on no dot clears the card. Elsewhere a click opens at once.
 */

/** A touch that moves farther than this is a drag, not a tap. */
export const TAP_SLOP_PX = 10;
/** How long after the pointer lifts to wait for Plotly's click on a dot before calling it background. */
export const BACKGROUND_TAP_DELAY_MS = 120;

/**
 * @param {{container: Element, isTouchOnly: () => boolean,
 *   onShowCard: (key: string, ev: object) => void,
 *   onOpen: (key: string, ev: object) => void,
 *   onClear: () => void,
 *   isReady?: () => boolean,
 *   isInsideCard?: (target: EventTarget|null) => boolean}} opts - `isInsideCard`: a pointer-down
 *   on the map's own card (its Open game button) is neither a background tap nor an outside tap.
 */
export function createTapController({
  container, isTouchOnly, onShowCard, onOpen, onClear, isReady, isInsideCard,
}) {
  let pendingTapKey = null;
  /** Venue dot / marker clicks seen so far; a tap that leaves it unchanged hit the background. */
  let clickCount = 0;
  /** The touch in progress inside the map: where it began and how many venue clicks preceded it. */
  let down = null;
  /** Settles the last tap's background check now; null when none is waiting. */
  let settleBackground = null;
  let timer = null;

  /** Clears the pending first tap so the next tap on a dot shows its card again. */
  function reset() {
    pendingTapKey = null;
  }

  function onVenueClick(key, ev) {
    clickCount += 1;
    if (isReady && !isReady()) return;
    if (!isTouchOnly()) {
      onOpen(key, ev);
      return;
    }
    // The touch pointerdown is cancelled, so a tap reaches Plotly once, from its touch
    // events. A compatibility mouse click that still arrives says it came from touch;
    // dropping it by its source, not by time, means no queue order or delay lets it
    // count as a second tap, and a real mouse's clicks are never held back.
    const src = ev?.event;
    if (src?.type?.startsWith('mouse') && src.sourceCapabilities?.firesTouchEvents) return;
    if (key !== pendingTapKey) {
      pendingTapKey = key;
      onShowCard(key, ev);
      return;
    }
    onOpen(key, ev);
  }

  function onPointerDown(ev) {
    // Input arrives in order, so the last tap's Plotly click (if any) is in by now: settle
    // its background check before this tap, or a tap inside the wait would find the old
    // venue still armed and open it.
    settleBackground?.();
    if (isInsideCard?.(ev.target)) {
      down = null;
      return;
    }
    if (!container.contains(ev.target)) {
      down = null;
      if (pendingTapKey != null) {
        reset();
        onClear();
      }
      return;
    }
    // Cancelling a touch pointerdown stops the browser's compatibility mouse events (Pointer
    // Events), so Plotly sees each tap once. Scrolling and pinch follow touch-action instead.
    if (ev.pointerType === 'touch') ev.preventDefault();
    down = isTouchOnly() ? { x: ev.clientX, y: ev.clientY, clicks: clickCount } : null;
  }

  function onPointerCancel() {
    down = null;
  }

  function onPointerUp(ev) {
    const start = down;
    down = null;
    if (!start || Math.hypot(ev.clientX - start.x, ev.clientY - start.y) > TAP_SLOP_PX) return;
    // A tap on the map that lands on no dot or marker clears only the card. Plotly
    // reports a hit through plotly_click a moment after the pointer lifts, so look afterwards.
    const settle = () => {
      clearTimeout(t);
      if (settleBackground === settle) settleBackground = null;
      if (clickCount !== start.clicks) return;
      reset();
      onClear();
    };
    const t = setTimeout(settle, BACKGROUND_TAP_DELAY_MS);
    timer = t;
    settleBackground = settle;
  }

  document.addEventListener('pointerdown', onPointerDown);
  document.addEventListener('pointercancel', onPointerCancel);
  document.addEventListener('pointerup', onPointerUp);

  /** Removes both document listeners and any waiting background check. */
  function destroy() {
    document.removeEventListener('pointerdown', onPointerDown);
    document.removeEventListener('pointercancel', onPointerCancel);
    document.removeEventListener('pointerup', onPointerUp);
    clearTimeout(timer);
    settleBackground = null;
    down = null;
  }

  return {
    onVenueClick,
    reset,
    destroy,
    get clickCount() {
      return clickCount;
    },
  };
}
