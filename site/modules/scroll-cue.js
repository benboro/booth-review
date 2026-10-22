/**
 * Phone table scroll cue (13-UI-SPEC "Phone" item 1). While the phone query matches,
 * a table scroller gets `has-more-left` / `has-more-right` classes (CSS turns them
 * into 24px fades) driven by an IntersectionObserver on two 1px sentinels, and its
 * module header gets a 12px muted "Swipe for more ›" label in a reserved slot. The
 * label goes `visibility: hidden` (never removed) for the rest of the session after
 * the first scroll of any table. Desktop output is untouched: the sentinels are
 * invisible and every class is only styled inside the 480px block.
 * Everything is built with createElement and textContent only.
 */
import { PHONE_QUERY } from './breakpoints.js';

const SEEN_KEY = 'swipe-cue-seen';
const CUE_TEXT = 'Swipe for more ›';

const attached = new WeakSet();
/** Per header: the cue element and the scrollers feeding it. */
const heads = new WeakMap();

function seen() {
  try {
    return sessionStorage.getItem(SEEN_KEY) === '1';
  } catch {
    return false;
  }
}

function markSeen() {
  try {
    sessionStorage.setItem(SEEN_KEY, '1');
  } catch {
    // Storage unavailable: the cue simply stays for this page view.
  }
  document.querySelectorAll('.swipe-cue').forEach((cue) => cue.classList.add('is-idle'));
}

function sentinel(className) {
  const s = document.createElement('span');
  s.className = `scroll-sentinel ${className}`;
  s.setAttribute('aria-hidden', 'true');
  return s;
}

function resolveHead(headEl, scroller) {
  if (typeof headEl === 'function') return headEl();
  return headEl ?? scroller.closest('.module')?.querySelector(':scope > .module-head') ?? null;
}

function cueFor(head) {
  let entry = heads.get(head);
  if (!entry) {
    const cue = document.createElement('span');
    cue.className = 'swipe-cue';
    cue.textContent = CUE_TEXT;
    head.append(cue);
    entry = { cue, scrollers: new Set() };
    heads.set(head, entry);
  }
  return entry;
}

/**
 * @param {HTMLElement} scroller the `.table-scroll` wrapper
 * @param {HTMLElement|(() => HTMLElement|null)|null} headEl the module header to carry the label
 */
export function attachScrollCue(scroller, headEl) {
  if (attached.has(scroller)) return;
  attached.add(scroller);
  scroller.classList.add('table-scroll');

  const mq = window.matchMedia(PHONE_QUERY);
  const startS = sentinel('scroll-sentinel-start');
  const endS = sentinel('scroll-sentinel-end');
  scroller.append(startS, endS);

  let head = null;

  function refresh() {
    const phone = mq.matches;
    const shown = phone && scroller.offsetWidth > 0;
    const overflow = shown && scroller.scrollWidth > scroller.clientWidth + 1;
    if (phone) {
      const pin = scroller.querySelector('th, td');
      scroller.style.setProperty('--pin-w', `${pin ? pin.offsetWidth : 0}px`);
      endS.style.left = `${Math.max(0, scroller.scrollWidth - 1)}px`;
    } else {
      scroller.classList.remove('has-more-left', 'has-more-right');
    }
    head = head ?? resolveHead(headEl, scroller);
    if (!head) return;
    const entry = cueFor(head);
    entry.scrollers.add(scroller);
    scroller.__cueOverflow = overflow;
    const live = [...entry.scrollers].filter((s) => s.isConnected && s.offsetWidth > 0);
    entry.cue.classList.toggle('is-slot', live.length > 0);
    entry.cue.classList.toggle('is-idle', seen() || !live.some((s) => s.__cueOverflow));
  }

  const io = new IntersectionObserver(
    (entries) => {
      if (!mq.matches) return;
      for (const e of entries) {
        if (e.target === startS) scroller.classList.toggle('has-more-left', !e.isIntersecting);
        else scroller.classList.toggle('has-more-right', !e.isIntersecting);
      }
      refresh();
    },
    { root: scroller, threshold: 0 },
  );
  io.observe(startS);
  io.observe(endS);

  const ro = new ResizeObserver(refresh);
  ro.observe(scroller);
  const table = scroller.querySelector('table');
  if (table) ro.observe(table);
  mq.addEventListener('change', refresh);

  let scrolled = false;
  scroller.addEventListener(
    'scroll',
    () => {
      if (scrolled || !mq.matches) return;
      scrolled = true;
      markSeen();
    },
    { passive: true },
  );
}
