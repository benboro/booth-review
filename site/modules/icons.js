/**
 * Shared game-type icons (notes-4 A1/A2a): a monochrome inline SVG for a bowl
 * game and one for a College Football Playoff game, drawn in `currentColor` so
 * they follow the theme and render the same on every OS. Used by the chart's
 * HTML tooltip (`tooltip.js`) and the detail panel (`panel.js`); the path data
 * lives here only.
 *
 * Colors come from CSS (`.game-type-icon[data-kind]` in style.css), never from
 * here: the icons only draw in `currentColor`.
 *
 * Always decorative (`aria-hidden="true"`): the meaning lives in the visible
 * text beside the icon -- the detail panel's label or the tooltip's game name
 * (04.10 D-10; there is no `role="img"` wrapper). Three kinds: bowl, playoff
 * and rivalry (crossed swords). Built with
 * `createElementNS` + `setAttribute` from the constant path data below --
 * never any markup-injecting DOM API (T-04.1-25) -- and never from a data
 * string, so a malicious value can't become an element or attribute.
 * Module scope never touches `document`, so this stays node-importable.
 */

const SVG_NS = 'http://www.w3.org/2000/svg';

/**
 * Path data per icon kind on a 16x16 grid. `stroke: true` draws an open
 * outline (round caps, no fill) instead of a filled shape.
 */
const ICON_PATHS = {
  // A bowl (cup) on a short foot.
  bowl: [
    { d: 'M1.5 5.5h13c0 3.7-2.9 6.6-6.5 6.6S1.5 9.2 1.5 5.5z' },
    { d: 'M5 13.2h6v1.3H5z' },
  ],
  // A trophy: cup, two handles, stem and base.
  playoff: [
    { d: 'M4.5 1.5h7V6a3.5 3.5 0 0 1-7 0z' },
    { d: 'M7.25 9.4h1.5V12h2.25v1.5H5V12h2.25z' },
    { d: 'M4.5 3H2.5v1.5a2 2 0 0 0 2 2', stroke: true },
    { d: 'M11.5 3h2v1.5a2 2 0 0 1-2 2', stroke: true },
  ],
  // Crossed swords (04.10 D-01): two stroked blades crossing near (8,8), a
  // crossguard and grip per sword, and a small filled pommel at each grip end.
  rivalry: [
    { d: 'M2.5 2.5L11 11', stroke: true },
    { d: 'M9.5 12.5L12.5 9.5', stroke: true },
    { d: 'M11 11L13 13', stroke: true },
    { d: 'M13.5 2.5L5 11', stroke: true },
    { d: 'M6.5 12.5L3.5 9.5', stroke: true },
    { d: 'M5 11L3 13', stroke: true },
    { d: 'M13.6 12.7a.9.9 0 1 0 0 1.8.9.9 0 0 0 0-1.8z' },
    { d: 'M2.4 12.7a.9.9 0 1 0 0 1.8.9.9 0 0 0 0-1.8z' },
  ],
};

/**
 * Builds the decorative icon for a game-type kind.
 * @param {"bowl"|"playoff"|"rivalry"} kind - one of `format.js#namedGameInfo().icons`.
 * @returns {SVGSVGElement|null} null for an unknown kind.
 */
export function makeGameTypeIcon(kind) {
  const paths = ICON_PATHS[kind];
  if (!paths) return null;

  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('viewBox', '0 0 16 16');
  svg.setAttribute('width', '1em');
  svg.setAttribute('height', '1em');
  svg.setAttribute('fill', 'currentColor');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  svg.setAttribute('class', 'game-type-icon');
  svg.setAttribute('data-kind', kind);

  for (const spec of paths) {
    const path = document.createElementNS(SVG_NS, 'path');
    path.setAttribute('d', spec.d);
    if (spec.stroke) {
      path.setAttribute('fill', 'none');
      path.setAttribute('stroke', 'currentColor');
      path.setAttribute('stroke-width', '1.2');
      path.setAttribute('stroke-linecap', 'round');
      path.setAttribute('stroke-linejoin', 'round');
    }
    svg.appendChild(path);
  }
  return svg;
}

/**
 * Builds the decorative disclosure caret for a Game section header (04.10
 * D-03): a chevron pointing down; CSS rotates it for the collapsed state.
 * Constant path data via `createElementNS`, never a data string.
 * @returns {SVGSVGElement}
 */
export function makeCaretIcon() {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('viewBox', '0 0 12 12');
  svg.setAttribute('width', '12');
  svg.setAttribute('height', '12');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '1.5');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  svg.setAttribute('class', 'game-caret');
  const path = document.createElementNS(SVG_NS, 'path');
  path.setAttribute('d', 'M3 4.5l3 3 3-3');
  svg.appendChild(path);
  return svg;
}
