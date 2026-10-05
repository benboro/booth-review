/**
 * Display strings for the Bars and Butterfly tabs (SITE-34, SITE-35). Pure and
 * DOM-free; imports only TOP_N from ./bars.js. Every string follows the 04.4
 * UI-SPEC Copywriting Contract exactly. D-01: every number printed here is a
 * count of rated telecasts (or games); no function reads or prints a
 * per-telecast audience figure.
 */

import { TOP_N } from './bars.js';
import { gameTitlePhrase } from './format.js';
import { ROLE_PILL_TEXT } from './pill.js';

/** Shown when the filters leave no rows (UI-SPEC empty state). */
export const EMPTY_COPY = {
  title: 'No rated telecasts for this selection',
  hint: 'Widen the season range or reset a filter.',
};

/** Grouping control labels by `by` value (04.6 D-21). */
export const BY_LABELS = Object.freeze({
  announcer: 'by Announcer',
  network: 'by Network',
  team: 'by Team',
  conference: 'by Conference',
});

const NOUNS = {
  person: ['announcer', 'announcers'],
  team: ['team', 'teams'],
  network: ['network', 'networks'],
  family: ['network family', 'network families'],
  conference: ['conference', 'conferences'],
};

/**
 * `1 rated telecast` / `N rated telecasts`.
 * @param {number} n
 * @returns {string}
 */
export function telecastCount(n) {
  return n === 1 ? '1 rated telecast' : `${n} rated telecasts`;
}

/**
 * Row noun for a row kind, singular for 1.
 * @param {string} rowKind
 * @param {number} n
 * @returns {string}
 */
export function rowNoun(rowKind, n) {
  const [one, many] = NOUNS[rowKind];
  return n === 1 ? one : many;
}

function teamName(data, slug) {
  return data.lookups.teams[data.teamIndexBySlug.get(slug)].name;
}

function personName(data, id) {
  return data.lookups.people[data.personIndexById.get(id)].name;
}

function isMatchup(state) {
  return state.h2h === true && state.school.length === 2;
}

/**
 * The " in A vs B games" phrase for a Head-to-head matchup (04.7 D-16).
 * @param {object} data
 * @param {object} state
 * @returns {string} '' unless Head-to-head is on with exactly two schools.
 */
export function matchupPhrase(data, state) {
  if (!isMatchup(state)) return '';
  const [a, b] = state.school;
  return `in ${teamName(data, a)} vs ${teamName(data, b)} games`;
}

/**
 * The names after "with" in a title (D-21): announcers (joined by "and" when
 * called together, else "or"), then schools (joined by "or"; Either team keeps
 * this join, 04.4 D-21). Under Head-to-head the schools are named by
 * `matchupPhrase` instead and are skipped here. When both groups
 * show, a group of 2+ names is parenthesised and the groups join with "and".
 * @param {object} data
 * @param {object} state
 * @param {{omit?: 'people'|'schools'|null}} [opts] - A group the chart's sides already name.
 * @returns {string} '' when nothing is left to name.
 */
export function subjectPhrase(data, state, { omit = null } = {}) {
  const groups = [];
  if (omit !== 'people' && state.people.length > 0) {
    const names = state.people.map((id) => personName(data, id));
    groups.push({ names, joiner: state.together ? ' and ' : ' or ' });
  }
  if (omit !== 'schools' && !isMatchup(state) && state.school.length > 0) {
    groups.push({ names: state.school.map((slug) => teamName(data, slug)), joiner: ' or ' });
  }
  const wrap = groups.length > 1;
  return groups
    .map(({ names, joiner }) => {
      const text = names.join(joiner);
      return wrap && names.length > 1 ? `(${text})` : text;
    })
    .join(' and ');
}

/**
 * The " on <networks>" tail of a title, or '' when the Networks filter is not narrowed.
 * @param {object} data
 * @param {object} state
 * @returns {string}
 */
export function networkPhrase(data, state) {
  if (state.networks === null) return '';
  const n = state.networks.length;
  if (n === 0) return ' on no networks';
  if (n > 3) return ` on ${n} networks`;
  const names = state.networks.map((id) => {
    const found = data.lookups.networks.find((net) => net.id === id);
    return found ? found.name : id;
  });
  return ` on ${names.join(' or ')}`;
}

/**
 * The " of the Harbor Bowl" / " in the Harbor Bowl" game phrase of a title (04.9 D-18).
 * @param {object} data
 * @param {object} state
 * @param {string} [preposition]
 * @returns {string} '' when no (known) game is picked.
 */
export function gamePhrase(data, state, preposition = 'of') {
  if (state.game == null) return '';
  const index = data.gameIndexBySlug.get(state.game);
  if (index === undefined) return '';
  return `${preposition} ${gameTitlePhrase(data.games[index])}`;
}

function gamePreposition(model) {
  return model.rowKind === 'family' || model.rowKind === 'conference' ? 'in' : 'of';
}

function subject(model) {
  if (model.rowKind === 'person') return 'Announcers by rated telecasts';
  if (model.rowKind === 'family') return 'Network families by announcer';
  if (model.rowKind === 'team') return 'Teams by rated telecasts';
  return 'Conferences by team';
}

function butterflySubject(model) {
  if (model.rowKind === 'person') return 'Announcers';
  if (model.rowKind === 'family') return 'Network families by announcer';
  if (model.rowKind === 'team') return 'Teams';
  return 'Conferences by team';
}

/**
 * Chart title for a Bars or Butterfly model: subject, game (04.9 D-18), matchup
 * (Head-to-head only), people, networks. Either team keeps the "or" join (04.4 D-21).
 * @param {object} model
 * @param {object} data
 * @param {object} state
 * @returns {string}
 */
export function chartTitle(model, data, state) {
  const nets = networkPhrase(data, state);
  const matchup = matchupPhrase(data, state);
  const matchupTail = matchup ? ` ${matchup}` : '';
  const game = gamePhrase(data, state, gamePreposition(model));
  const gameTail = game ? ` ${game}` : '';
  if (model.kind === 'butterfly') {
    const omit = model.group === 'announcers' ? 'schools' : 'people';
    const phrase = subjectPhrase(data, state, { omit });
    const head = `${butterflySubject(model)}: ${model.sides[0].name} and ${model.sides[1].name}`;
    return `${head}${gameTail}${matchupTail}${phrase ? ` with ${phrase}` : ''}${nets}`;
  }
  const phrase = subjectPhrase(data, state);
  return `${subject(model)}${gameTail}${matchupTail}${phrase ? ` with ${phrase}` : ''}${nets}`;
}

/**
 * Row-count caption under the title.
 * @param {object} model
 * @param {boolean} expanded
 * @returns {string}
 */
export function rowCountCaption(model, expanded) {
  const n = model.rows.length;
  const noun = rowNoun(model.rowKind, n);
  if (n > TOP_N && !expanded) return `Showing top ${TOP_N} of ${n} ${noun}`;
  if (n === 1) return `Showing 1 ${noun}`;
  return `Showing all ${n} ${noun}`;
}

/**
 * Label of the show-all toggle, or null when there is nothing to expand.
 * @param {number} total
 * @param {boolean} expanded
 * @returns {string|null}
 */
export function showAllLabel(total, expanded) {
  if (total <= TOP_N) return null;
  return expanded ? `Show top ${TOP_N}` : `Show all ${total}`;
}

function sharedCaption(shared) {
  return shared === 1 ? '1 game includes both.' : `${shared} games include both.`;
}

/**
 * Explanatory caption lines, in UI-SPEC order.
 * @param {object} model
 * @param {object[]} shownRows
 * @returns {string[]}
 */
export function captionLines(model, shownRows) {
  const lines = [];
  if (model.segmentKind === 'person') {
    lines.push(
      'Each telecast counts once for every announcer in it, so a bar can be longer than its number of telecasts.',
    );
  }
  if (model.rowKind === 'team' || model.segmentKind === 'team') {
    lines.push(
      'Each game counts once for every team in it, so team totals can add up to more than the number of games.',
    );
  }
  if (model.rowKind === 'family') {
    lines.push(
      "Shades within a network family's bar mark its channels. Hover or tap a segment for each channel's count.",
    );
  }
  if (model.kind === 'butterfly') lines.push(sharedCaption(model.shared));
  if (shownRows.some((row) => row.target == null)) {
    lines.push("Non-FBS and unlisted conferences can't be used as a filter.");
  }
  return lines;
}

/**
 * In-segment text.
 * @param {{label: string, count: number}} seg
 * @returns {string}
 */
export function segmentText(seg) {
  return `${seg.label} ${seg.count}`;
}

/**
 * Plain-text role suffix for screen-reader strings, e.g. ' (PBP, Analyst)' (D-15).
 * @param {string[]} [roles]
 * @returns {string}
 */
export function roleSuffix(roles = []) {
  if (roles.length === 0) return '';
  return ` (${roles.map((r) => ROLE_PILL_TEXT[r] ?? ROLE_PILL_TEXT.unknown).join(', ')})`;
}

/**
 * In-tooltip text of one channel line of a family segment.
 * @param {{name: string, count: number}} ch
 * @returns {string}
 */
export function channelLineText(ch) {
  return `${ch.name} ${ch.count}`;
}

/**
 * Tooltip lines for a point reference.
 * @param {object} model
 * @param {object[]} shownRows
 * @param {{r: number, s: number, side: number|null}} ref
 * @param {{touch?: boolean}} [opts]
 * @returns {{text: string, kind: 'title'|'body'|'hint', shade?: number}[]}
 */
export function tooltipLines(model, shownRows, ref, { touch = false } = {}) {
  const row = shownRows[ref.r];
  const butterfly = model.kind === 'butterfly';
  const side = butterfly && ref.side != null ? row.sides[ref.side] : null;
  const sideName = butterfly && ref.side != null ? model.sides[ref.side].name : null;
  const lines = [];
  let target;
  if (ref.s >= 0) {
    const seg = (side ? side.segments : row.segments)[ref.s];
    const count = telecastCount(seg.count);
    lines.push({ text: seg.name ?? seg.label, kind: 'title', roles: seg.roles ?? [] });
    for (const ch of seg.channels ?? []) {
      lines.push({ text: `${ch.name}: ${ch.count}`, kind: 'body', shade: ch.shade });
    }
    lines.push({
      text: sideName ? `${sideName}: ${count} on ${row.name}` : `${count} on ${row.name}`,
      kind: 'body',
    });
    target = seg.target;
  } else {
    const count = telecastCount(side ? side.total : row.total);
    lines.push({ text: row.label, kind: 'title', roles: row.roles ?? [] });
    lines.push({ text: sideName ? `${sideName}: ${count}` : count, kind: 'body' });
    target = row.target;
  }
  if (target != null) {
    lines.push({ text: touch ? 'Tap again to filter →' : 'Click to filter →', kind: 'hint' });
  }
  return lines;
}

function drillPhrase(target, name) {
  if (target == null) return name;
  if (target.kind === 'person') return `Add ${name} as a filter`;
  if (target.kind === 'team') return `Add ${name} to the School filter`;
  if (target.kind === 'network' || target.kind === 'family') return `Show only ${name}`;
  return `Add ${name} to the Conference filter`;
}

/**
 * Accessible name of a counts-list button.
 * @param {object|null} target
 * @param {string} name
 * @param {number} n
 * @returns {string}
 */
export function countsListName(target, name, n) {
  return `${drillPhrase(target, name)}, ${telecastCount(n)}`;
}

function sideCounts(row, model) {
  return `${model.sides[0].name} ${row.sides[0].total}, ${model.sides[1].name} ${row.sides[1].total}`;
}

/**
 * Counts-list row text for a butterfly row.
 * @param {object} row
 * @param {object} model
 * @returns {string}
 */
export function butterflyRowText(row, model) {
  return `${row.label}${roleSuffix(row.roles)}${butterflySideText(row, model)}`;
}

/**
 * The part of a butterfly counts-list row after the name and pills.
 * @param {object} row
 * @param {object} model
 * @returns {string}
 */
export function butterflySideText(row, model) {
  return `: ${sideCounts(row, model)} rated telecasts`;
}

/**
 * Accessible name of a butterfly counts-list button.
 * @param {object} row
 * @param {object} model
 * @returns {string}
 */
export function butterflyCountsName(row, model) {
  return `${drillPhrase(row.target, row.name)}, ${sideCounts(row, model)} rated telecasts`;
}

/**
 * Screen-reader summary of the chart.
 * @param {object} model
 * @param {object} data
 * @param {object} state
 * @param {number} shownCount
 * @returns {string}
 */
export function ariaSummary(model, data, state, shownCount) {
  const [lo, hi] = state.seasons ?? [data.seasonMin, data.seasonMax];
  const range = lo === hi ? `${lo}` : `${lo}–${hi}`;
  const total = model.rows.length;
  const lower = (s) => s.charAt(0).toLowerCase() + s.slice(1);
  const title = lower(chartTitle(model, data, state));
  const head = `${model.kind === 'butterfly' ? 'Butterfly' : 'Bar'} chart: ${title}, ${range}.`;
  let out = `${head} Showing ${shownCount} of ${total}.`;
  if (model.kind === 'butterfly') out += ` ${sharedCaption(model.shared)}`;
  if (shownCount > 0) {
    const top = model.rows.slice(0, Math.min(model.kind === 'butterfly' ? 2 : 3, shownCount));
    const parts = top.map((row) =>
      model.kind === 'butterfly'
        ? `${row.label}${roleSuffix(row.roles)} ${row.sides[0].total} and ${row.sides[1].total}`
        : `${row.label}${roleSuffix(row.roles)} ${row.total}`,
    );
    out += ` Top: ${parts.join(', ')}.`;
  }
  return out;
}
