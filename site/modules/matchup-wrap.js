/**
 * A matchup that wraps before its joiner (user decisions 2026-11-03): when the line has to
 * wrap, the next line starts with "at", "@" or "vs." and holds the home side (and an inline
 * ranked badge, where the surface sets one inline), so the away team never ends a line with a
 * dangling joiner and the home side never splits while it fits on its own line.
 *
 * The away side stays plain inline text, so it wraps like any text (a phone row's line clamp
 * still counts its lines); the joiner, the home side and the badge form one inline-block
 * (`.mu-part`), so the space before the joiner is the only break between the sides. A home
 * part longer than a whole line still wraps inside itself. A rank and the word after it
 * ("#20 Florida") share a no-wrap run (`.mu-glue`), so a rank never ends a line apart from its
 * team. Text nodes only: a team name is never markup, and the element's textContent is
 * exactly the one-string matchup ("#20 Florida @ #5 Georgia").
 */

/**
 * Text as nodes, each "#N word" pair in one no-wrap run.
 * @param {string} text
 * @returns {Node[]}
 */
export function gluedText(text) {
  const nodes = [];
  const re = /#\d+ \S+/g;
  let at = 0;
  for (let m = re.exec(text); m; m = re.exec(text)) {
    if (m.index > at) nodes.push(document.createTextNode(text.slice(at, m.index)));
    const glue = document.createElement('span');
    glue.className = 'mu-glue';
    glue.textContent = m[0];
    nodes.push(glue);
    at = m.index + m[0].length;
  }
  if (at < text.length) nodes.push(document.createTextNode(text.slice(at)));
  return nodes;
}

/**
 * The away nodes, a space, then one inline-block holding the home nodes (which start with the
 * joiner).
 * @param {Node[]} awayNodes
 * @param {Node[]} homeNodes
 * @returns {Node[]}
 */
export function joinerBreakNodes(awayNodes, homeNodes) {
  const homePart = document.createElement('span');
  homePart.className = 'mu-part';
  homePart.append(...homeNodes);
  return [...awayNodes, document.createTextNode(' '), homePart];
}

/**
 * Fills `target` with "away joiner home", breaking before the joiner.
 * @param {HTMLElement} target
 * @param {{away: string, joiner: string, home: string}} sides - `away` may carry a prefix (a
 *   kickoff time) and `home` a suffix (a score, a neutral site's city); each stays with its side.
 * @param {HTMLElement|null} [badge] - an inline badge, ending the home part.
 */
export function fillWrappingMatchup(target, { away, joiner, home }, badge = null) {
  const homeNodes = gluedText(`${joiner} ${home}`);
  if (badge) homeNodes.push(badge);
  target.replaceChildren(...joinerBreakNodes(gluedText(away), homeNodes));
}

/**
 * Whether the element's text runs over more than one line. Measures the plain text runs only
 * (not the badge's own title, and not the raised superscript ranks of the modal title), so a
 * line is a change in the text's bottom edge of more than half a line.
 * @param {HTMLElement} el
 * @returns {boolean}
 */
export function textWraps(el) {
  const bottoms = [];
  let tall = 0;
  const walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  for (let n = walk.nextNode(); n; n = walk.nextNode()) {
    if (n.parentElement.closest('.rk-badge, sup') || !n.data.trim()) continue;
    const range = document.createRange();
    range.selectNodeContents(n);
    for (const r of range.getClientRects()) {
      if (r.height === 0) continue;
      bottoms.push(r.bottom);
      tall = Math.max(tall, r.height);
    }
  }
  if (bottoms.length === 0) return false;
  return Math.max(...bottoms) - Math.min(...bottoms) > tall / 2;
}

/**
 * The right edge of the element's longest text line, from its left padding edge (the origin of
 * an absolutely positioned child). Text runs only, the badge's own title skipped, so the badge
 * never counts toward the line it sits beside.
 * @param {HTMLElement} el
 * @returns {number|null} null when the element has no laid-out text
 */
export function longestLineRight(el) {
  let right = null;
  const walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  for (let n = walk.nextNode(); n; n = walk.nextNode()) {
    if (n.parentElement.closest('.rk-badge') || !n.data.trim()) continue;
    const range = document.createRange();
    range.selectNodeContents(n);
    for (const r of range.getClientRects()) {
      if (r.width === 0 || r.height === 0) continue;
      right = right === null ? r.right : Math.max(right, r.right);
    }
  }
  if (right === null) return null;
  const box = el.getBoundingClientRect();
  // Client rects carry any transform on an ancestor; the offset is wanted in CSS px.
  const scale = el.offsetWidth > 0 ? box.width / el.offsetWidth : 1;
  return (right - box.left) / scale - el.clientLeft;
}

/**
 * The ranked badge on a wrapped matchup (user feedback 2026-11-03, the map card as reference):
 * on one line it ends the line inline; once the text wraps, `rk-wrapped` moves it to the right
 * and centres it on the lines (the CFB modal title, the ESPN+ and regional table, Matched
 * games). The wrap is measured with the class off, so the answer is always the one-line
 * (inline badge) layout's: a surface whose wrapped placement takes room (the tables' end
 * padding) can never hold itself wrapped once the inline layout fits on one line again.
 *
 * With the class on (so the line breaks are final), `--rk-line-end` holds the right edge of the
 * longest line: the badge starts its one-line gap after it (6px in the tables, 10px in the
 * modal title) rather than at the right edge (user feedback 2026-11-03). The badge is out of
 * flow, so placing it never moves a line break.
 * @param {HTMLElement} el
 */
export function syncBadgeWrap(el) {
  const ranked = el.querySelector('.rk-badge') !== null;
  el.classList.remove('rk-wrapped');
  const wrapped = ranked && textWraps(el);
  el.classList.toggle('rk-wrapped', wrapped);
  const end = wrapped ? longestLineRight(el) : null;
  if (end === null) el.style.removeProperty('--rk-line-end');
  else el.style.setProperty('--rk-line-end', `${end}px`);
}

/** @type {ResizeObserver|null} */
let wrapObserver = null;

/**
 * Keeps `syncBadgeWrap` current: now if the element is laid out, and again whenever it changes
 * size (a dialog opening, a table column narrowing, the viewport resizing), and once more when
 * the page's web fonts finish loading. One observer serves every element; an element that leaves the page is dropped on its last (zero-size) report.
 * @param {HTMLElement} el
 */
export function watchBadgeWrap(el) {
  if (el.isConnected) syncBadgeWrap(el);
  // A web font that lands later changes the text's widths, not always the element's size.
  if (document.fonts && document.fonts.status !== 'loaded') {
    document.fonts.ready.then(() => {
      if (el.isConnected) syncBadgeWrap(el);
    });
  }
  if (typeof ResizeObserver !== 'function') return;
  wrapObserver ??= new ResizeObserver((entries) => {
    for (const { target } of entries) {
      if (target.isConnected) syncBadgeWrap(/** @type {HTMLElement} */ (target));
      else wrapObserver.unobserve(target);
    }
  });
  wrapObserver.observe(el);
}

/**
 * A table's matchup cell: `fillWrappingMatchup` inside one block (`span.mu-lines`) that is
 * exactly as tall as the matchup's lines, so a wrapped cell's badge centres on those lines
 * whatever the row's other cells do (user decision 2026-11-03), 6px after its longest line
 * (`--rk-line-end`). A one-line cell keeps the badge inline after the last word and renders as
 * before.
 * @param {HTMLElement} target
 * @param {{away: string, joiner: string, home: string}} sides
 * @param {HTMLElement|null} [badge]
 */
export function fillTableMatchup(target, sides, badge = null) {
  const lines = document.createElement('span');
  lines.className = 'mu-lines';
  fillWrappingMatchup(lines, sides, badge);
  target.replaceChildren(lines);
  if (badge) watchBadgeWrap(lines);
}
