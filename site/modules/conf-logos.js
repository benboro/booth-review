/**
 * Conference logo map and mark builder (Phase 28).
 *
 * - Each FBS conference with an approved file under site/logos/conf/ maps to its logo
 *   by the game's season (D-09): SEC changes logo in 2024, Conference USA in 2023 and
 *   the Pac-12 in 2026; every other conference has one logo for all games.
 * - Only those three conferences have more than one era (D-10).
 * - FBS Independents, FCS Independents and every FCS conference have no entry, so
 *   conferenceMark returns their name as a text node (D-11).
 * - Logos are `<img class="cf-logo">` with alt and title set to the conference name
 *   (D-13), and swap to the generated file under logos/dark/conf/ when the theme
 *   changes (D-14).
 * - Each entry's width and height attributes give a 20px-high box, its width scaled by the
 *   file's viewBox.
 * - `scale` sizes each logo by area: the surface's nominal height (20px modal, 16px card and
 *   filter list) times `scale` is its drawn height, so wordmarks shrink and shields grow until
 *   each covers about the same opaque area. scale = sqrt(k_ref / k), clamped to 0.55..1.25 and
 *   rounded to 0.01, where k is the file's opaque fraction (measured offline at 400px high)
 *   times its aspect ratio and k_ref is the geometric mean of k over every file. CSS keeps the
 *   margin box at the nominal height, so no row, cell, card or title changes height (D-05).
 *
 * Lookup goes through a Map with a has() check, never a bracket lookup on a name, so
 * "__proto__" or "constructor" can never resolve, and `src` comes only from this map.
 * DOM is built with createElement/createTextNode/setAttribute only.
 */

import { currentTheme, onThemeChange } from './theme.js';

const AAC = { file: 'logos/conf/american-athletic-conference.svg', width: 19, height: 20, scale: 1.24, darkFile: 'logos/dark/conf/american-athletic-conference.svg' };
const ACC = { file: 'logos/conf/atlantic-coast-conference.svg', width: 68, height: 20, scale: 0.82, darkFile: 'logos/dark/conf/atlantic-coast-conference.svg' };
const BIG_12 = { file: 'logos/conf/big-12-conference.svg', width: 33, height: 20, scale: 0.95, darkFile: 'logos/dark/conf/big-12-conference.svg' };
const BIG_TEN = { file: 'logos/conf/big-ten-conference.svg', width: 53, height: 20, scale: 0.69, darkFile: 'logos/dark/conf/big-ten-conference.svg' };
const CUSA_2013 = { file: 'logos/conf/conference-usa-2013-2023.svg', width: 102, height: 20, scale: 0.55, darkFile: 'logos/dark/conf/conference-usa-2013-2023.svg' };
const CUSA_2023 = { file: 'logos/conf/conference-usa-2023-present.svg', width: 90, height: 20, scale: 0.58, darkFile: 'logos/dark/conf/conference-usa-2023-present.svg' };
const MAC = { file: 'logos/conf/mid-american-conference.svg', width: 22, height: 20, scale: 1.14, darkFile: 'logos/dark/conf/mid-american-conference.svg' };
const MW = { file: 'logos/conf/mountain-west-conference.svg', width: 19, height: 20, scale: 1.18, darkFile: 'logos/dark/conf/mountain-west-conference.svg' };
const PAC_12_SHIELD = { file: 'logos/conf/pac-12-conference-before-2026.svg', width: 16, height: 20, scale: 1.25, darkFile: 'logos/dark/conf/pac-12-conference-before-2026.svg' };
const PAC_12_2026 = { file: 'logos/conf/pac-12-conference-2026-present-official-site.svg', width: 16, height: 20, scale: 1.25, darkFile: 'logos/dark/conf/pac-12-conference-2026-present-official-site.svg' };
const SEC_BEFORE_2024 = { file: 'logos/conf/southeastern-conference-before-2024.svg', width: 20, height: 20, scale: 1.13, darkFile: 'logos/dark/conf/southeastern-conference-before-2024.svg' };
const SEC_2024 = { file: 'logos/conf/southeastern-conference-2024-present.svg', width: 20, height: 20, scale: 1.11, darkFile: 'logos/dark/conf/southeastern-conference-2024-present.svg' };
const SUN_BELT = { file: 'logos/conf/sun-belt-conference.svg', width: 31, height: 20, scale: 1.25, darkFile: 'logos/dark/conf/sun-belt-conference.svg' };

/**
 * CFBD conference name -> [[first season, entry], ...], oldest era first.
 * Any conference that gains a second logo needs the user's ruling (one logo for all games, or a season range per logo) before it is added here. D-10.
 * @type {Map<string, Array<[number, {file: string, width: number, height: number, scale: number, darkFile: string}]>>}
 */
const ERAS = new Map([
  ['American Athletic', [[2014, AAC]]],
  ['ACC', [[2014, ACC]]],
  ['Big 12', [[2014, BIG_12]]],
  ['Big Ten', [[2014, BIG_TEN]]],
  ['Conference USA', [[2014, CUSA_2013], [2023, CUSA_2023]]],
  ['Mid-American', [[2014, MAC]]],
  ['Mountain West', [[2014, MW]]],
  ['Pac-12', [[2014, PAC_12_SHIELD], [2026, PAC_12_2026]]],
  ['SEC', [[2014, SEC_BEFORE_2024], [2024, SEC_2024]]],
  ['Sun Belt', [[2014, SUN_BELT]]],
]);

/**
 * The logo a conference used in a game's season, or null when it has none (D-09, D-11).
 * A missing season gives the newest logo; a season before the first era gives the first.
 * @param {unknown} name - the CFBD conference name
 * @param {number|null|undefined} season
 * @returns {{file: string, width: number, height: number, scale: number, darkFile: string}|null}
 */
export function conferenceLogoFor(name, season) {
  const key = String(name);
  if (!ERAS.has(key)) return null;
  const eras = ERAS.get(key);
  if (season === null || season === undefined || !Number.isFinite(Number(season))) {
    return eras[eras.length - 1][1];
  }
  const year = Number(season);
  let entry = eras[0][1];
  for (const [from, era] of eras) {
    if (from <= year) entry = era;
  }
  return entry;
}

let themeWatch = null;

/**
 * Swaps every conference logo on the page to the file for the new theme (D-14). Armed once,
 * on the first logo built. The name and season come from data attributes this module set,
 * and go back through the Map lookup, so page data never picks a file directly.
 */
function watchTheme() {
  if (themeWatch) return;
  themeWatch = onThemeChange((theme) => {
    for (const img of document.querySelectorAll('img.cf-logo[data-cf]')) {
      const season = img.dataset.season ? Number(img.dataset.season) : null;
      const logo = conferenceLogoFor(img.dataset.cf, season);
      if (logo) img.src = theme === 'dark' ? logo.darkFile : logo.file;
    }
  });
}

/**
 * The conference's logo as an `<img class="cf-logo">`, or its name as a text node when it
 * has no logo (D-11, D-13).
 * - `decorative` is for a place whose own text already says the name (the filter list's
 *   label): the logo gets `alt=""` and aria-hidden, so the name is not read twice, and keeps
 *   its `title` for the hover tooltip.
 * - A logo that fails to load is replaced by the name as a text node (or, when decorative,
 *   removed), never left as a broken image.
 * @param {unknown} name - the CFBD conference name
 * @param {number|null|undefined} season - the game's season
 * @param {{decorative?: boolean}} [options]
 * @returns {HTMLImageElement|Text}
 */
export function conferenceMark(name, season, { decorative = false } = {}) {
  const entry = conferenceLogoFor(name, season);
  if (!entry) return document.createTextNode(String(name));
  const label = String(name);
  const img = document.createElement('img');
  img.className = 'cf-logo';
  img.dataset.cf = label;
  img.dataset.season = String(season ?? '');
  // A logo that fails to load (404, blocked, bad decode) falls back to the name as text, so
  // no broken-image box shows (UI-SPEC error state). A decorative logo sits beside its own
  // name, so it just leaves its slot empty, as a conference without a logo does.
  img.addEventListener(
    'error',
    () => img.replaceWith(...(decorative ? [] : [document.createTextNode(label)])),
    { once: true },
  );
  img.src = currentTheme() === 'dark' ? entry.darkFile : entry.file;
  watchTheme();
  img.alt = decorative ? '' : label;
  if (decorative) img.setAttribute('aria-hidden', 'true');
  img.title = label;
  img.setAttribute('width', String(entry.width));
  img.setAttribute('height', String(entry.height));
  img.style.setProperty('--cf-scale', String(entry.scale));
  img.decoding = 'async';
  return img;
}
