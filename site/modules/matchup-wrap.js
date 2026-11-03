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
