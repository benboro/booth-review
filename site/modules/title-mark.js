/**
 * The College Football Playoff national championship emblem: the CFP football mark (two gold
 * arcs around four laces) from the title game's logo, its NATIONAL CHAMPIONSHIP lettering
 * removed (see site/logos/README.md), shown beside the trophy icon on the
 * title game only, in the Crews game list, the hover tooltip and the game panel.
 *
 * Always decorative: the text beside it (or the cell's hidden label) says "CFP championship".
 * The `<img>` cannot see page CSS, so a theme flip swaps it to the generated dark file, as the
 * network and conference logos do.
 */

import { gameTypeInfo } from './format.js';
import { currentTheme, onThemeChange } from './theme.js';

const FILE = 'logos/marks/cfp-national-championship.svg';
const DARK_FILE = 'logos/dark/marks/cfp-national-championship.svg';
// The emblem's viewBox is 99.2 x 132.4; drawn 16px high it is 12px wide.
const WIDTH = 12;
const HEIGHT = 16;

/** True when telecast `i` is the CFP national championship game. */
export function isTitleGame(data, i) {
  return gameTypeInfo(data, i)?.kind === 'playoff' && data.t.playoff_round?.[i] === 'championship';
}

let themeWatch = null;

function watchTheme() {
  if (themeWatch) return;
  themeWatch = onThemeChange((theme) => {
    for (const img of document.querySelectorAll('img.title-mark')) img.src = theme === 'dark' ? DARK_FILE : FILE;
  });
}

/**
 * The emblem as a decorative `<img class="title-mark">`. A file that fails to load is removed,
 * never left as a broken image; the trophy icon beside it still marks the game.
 * @returns {HTMLImageElement}
 */
export function titleGameMark() {
  const img = document.createElement('img');
  img.className = 'title-mark';
  img.addEventListener('error', () => img.remove(), { once: true });
  img.src = currentTheme() === 'dark' ? DARK_FILE : FILE;
  watchTheme();
  img.alt = '';
  img.setAttribute('aria-hidden', 'true');
  img.title = 'CFP national championship';
  img.setAttribute('width', String(WIDTH));
  img.setAttribute('height', String(HEIGHT));
  img.decoding = 'async';
  return img;
}
