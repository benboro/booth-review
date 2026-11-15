/**
 * NFL view 1 with "Special games only" off: every game by team, grouped by network.
 *
 * The bars are the CFB Bars' stacked bars (`stackedTraces` in modules/bar-chart.js), so a network
 * looks the same on both pages: one group per network family in its family colour, with a solid
 * part and a light part in the same hue. On CFB the solid part is the rated games; here it is
 * the special games, and the light part is the family's other games. A game with no network yet
 * ("No network listed") has no network colour: it is one pale neutral piece, special or not.
 *
 * DOM-free: the trace builder, the hover model and the plain-text lines the phone and the tests
 * read. views/team-bars.js owns the chart node, the layout, the legend and the tables.
 */
import { stackedTraces } from '../../../modules/bar-chart.js';
import { PAGE_BG, mixHex } from '../../../modules/palette.js';
import { familyColor, familyLabel } from '../palette.js';

/** Separator stroke between network groups, as on the CFB bars (D-28). */
const SEGMENT_GAP = { desktop: 3, phone: 2 };

/**
 * How much of its colour a faded row keeps (the Special games bars fade to 0.4 opacity). The
 * tones are mixed toward the page instead of drawn translucent, so the borders of neighbouring
 * pieces never add up to a darker line.
 */
const FADE_WEIGHT = 0.4;

/**
 * The pieces of one family segment: one piece in the family's colour, whose `rated` length is
 * drawn solid (the special games, or every game with no network) and the rest light. A family is
 * one colour, not a shade per network: lightness already tells special from other.
 */
function partsFor(theme) {
  return (row, _i, seg) => {
    const base = familyColor(seg.family, theme);
    const tone = row.faded ? mixHex(base, PAGE_BG[theme], FADE_WEIGHT) : base;
    return [{ count: seg.count, rated: seg.family === 'tba' ? seg.count : seg.special, tone }];
  };
}

/**
 * The bar traces for the shown rows. `faded` holds one flag per row: a team the Team filter
 * leaves out of focus, or every row but the selected one.
 * @param {{id: string, bar: object}[]} rows - `bar` from `networkBars`.
 * @param {{mobile: boolean}} env
 * @param {'light'|'dark'} theme
 * @param {boolean[]} faded
 * @returns {object[]}
 */
export function networkTraces(rows, env, theme, faded) {
  const barRows = rows.map((r, k) => ({ key: r.id, segments: r.bar.segments, faded: faded[k] }));
  return stackedTraces(
    barRows,
    (r) => r.segments,
    partsFor(theme),
    null,
    theme,
    { piece: 'x', overlay: 'x3', text: 'x5' },
    env.mobile ? SEGMENT_GAP.phone : SEGMENT_GAP.desktop,
    false,
    { labels: false },
  );
}

/** "ABC 3, ESPN 14" for a family whose label names more than one network, else null. */
function channelText(model, seg) {
  if ((model.net.networksByFamily.get(seg.family) ?? []).length < 2) return null;
  return seg.channels.map((ch) => `${ch.name} ${ch.count}`).join(', ');
}

/**
 * The hover content for an all-games bar, without the click hint: the title, the counted games
 * and how many of them are special, then one colour-keyed row per network family with games.
 * A family of several networks names each with its count, and every row says how many of its
 * games are special.
 */
export function networkHoverModel(model, state, label, bar, theme) {
  const [lo, hi] = state.seasons;
  const title = lo === hi ? `${label}, ${lo}` : `${label}, ${lo}–${hi}`;
  const summary = `${bar.total} ${bar.total === 1 ? 'game' : 'games'}, ${bar.special} special`;
  const rows = bar.segments.map((seg) => {
    const sub = [channelText(model, seg), seg.special > 0 ? `${seg.special} special` : null]
      .filter((t) => t != null);
    return {
      key: seg.family,
      label: familyLabel(seg.family),
      color: familyColor(seg.family, theme),
      value: String(seg.count),
      sub: sub.length ? sub.join('; ') : null,
    };
  });
  return { title, summary, rows, asides: [], footnote: null };
}
