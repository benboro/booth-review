/**
 * The Crews game list's marks cell (CFB only): what kind of game it was, as the icons the
 * tooltip and panel already use. In order: rivalry (crossed swords), bowl, playoff trophy, the
 * national championship emblem on the title game, and the ranked-matchup badge when both teams
 * were ranked. Every icon is decorative; one visually hidden line names them all, and each
 * icon's `title` names it on hover.
 */

import { gameTypeInfo, rivalryName } from './format.js';
import { makeGameTypeIcon } from './icons.js';
import { bothRanked, rankBadge } from './rank-badge.js';
import { isTitleGame, titleGameMark } from './title-mark.js';

/**
 * The marks for telecast `i`, as [kind, label] pairs in display order. DOM-free.
 * @param {object} data - a `prepareData` result
 * @param {number} i - telecast index
 * @returns {Array<['rivalry'|'bowl'|'playoff'|'title'|'ranked', string]>}
 */
export function gameMarks(data, i) {
  const marks = [];
  const rivalry = rivalryName(data, i);
  if (rivalry != null) marks.push(['rivalry', `Rivalry: ${rivalry}`]);
  const info = gameTypeInfo(data, i);
  if (info?.kind === 'bowl' || info?.atBowl) {
    const core = data.lookups.bowls?.[data.t.bowl?.[i]]?.core ?? null;
    marks.push(['bowl', core ?? 'Bowl']);
  }
  if (info?.kind === 'playoff') {
    marks.push(['playoff', info.label]);
    if (isTitleGame(data, i)) marks.push(['title', 'National championship']);
  }
  if (bothRanked(data.t.away_rank?.[i], data.t.home_rank?.[i])) marks.push(['ranked', 'Both teams ranked']);
  return marks;
}

function iconFor(kind) {
  if (kind === 'title') return titleGameMark();
  if (kind === 'ranked') return rankBadge({ hidden: true });
  return makeGameTypeIcon(kind);
}

/**
 * The `td.crews-game-marks` cell for telecast `i` (empty for a plain regular-season game).
 * @param {object} data
 * @param {number} i
 * @returns {HTMLTableCellElement}
 */
export function gameMarksCell(data, i) {
  const td = document.createElement('td');
  td.className = 'crews-game-marks';
  const marks = gameMarks(data, i);
  if (!marks.length) return td;
  const row = document.createElement('span');
  row.className = 'crews-marks';
  for (const [kind, label] of marks) {
    const icon = iconFor(kind);
    if (!icon) continue;
    const slot = document.createElement('span');
    slot.className = 'crews-mark';
    slot.dataset.mark = kind;
    slot.title = label;
    slot.append(icon);
    row.append(slot);
  }
  const text = document.createElement('span');
  text.className = 'visually-hidden';
  text.textContent = marks.map(([, label]) => label).join(', ');
  td.append(row, text);
  return td;
}
