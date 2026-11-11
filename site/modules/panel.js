/**
 * Detail panel: full per-telecast facts, credits, and source links (SITE-05,
 * SITE-17, SITE-28, D-01..D-06, D-08, D-09, D-10, D-16, D-17). A native
 * `<dialog>` opened with `showModal()`: a centered modal on desktop/tablet and
 * a bottom sheet on phones (styled by `#detail-panel`/`.panel-inner` in
 * style.css). Opened by a chart dot click or clicking/pressing Enter on a
 * matched-games table row; closed by `#panel-close`, Escape (native), or a
 * backdrop click. It never changes the page layout or scroll position.
 *
 * DOM is built only with createElement/textContent/replaceChildren -- never
 * any markup-injecting DOM API (T-04-34). Every href passes through
 * `safeHref` first (T-04-35): a telecast's `source_url`/`s506_url`/`crew_source_url`/flag
 * `source_url` that isn't a plain http(s) URL never becomes a clickable
 * link.
 */


import {
  FEED_LABELS,
  SLOT_LABELS,
  conferenceLine,
  crewEntries,
  figureNotViaRrText,
  axisValueText,
  boothLabel,
  formatMatchup,
  formatViewersProse,
  matchupParts,
  gameTypeInfo,
  rivalryName,
  measurementLabel,
  noRatingLine,
  selectedPersonIndexes,
  showsTimeSlot,
} from './format.js';
import { conferenceMark } from './conf-logos.js';
import { makeGameTypeIcon } from './icons.js';
import { isTitleGame, titleGameMark } from './title-mark.js';
import { currentTheme } from './pill.js';
import {
  crewBox, externalLink, linksList, liveOpener, locationLine, markText, networksParagraph,
} from './panel-parts.js';
import { broadcastNetworks } from './network.js';
import { bothRanked, rankBadge } from './rank-badge.js';
import { joinerBreakNodes, syncBadgeWrap, watchBadgeWrap } from './matchup-wrap.js';
import { personOnGame } from './select.js';
import { scheduledFacade } from './weekend-data.js';
import { apKickoff } from './weekend.js';

/** The element focus returns to when the dialog closes, or null. */
let opener = null;

/** Counts `showModal()` calls; the `close` handler acts once per session. */
let openSession = 0;
let handledSession = 0;

/** Whether the latest pointerdown on the dialog landed on the backdrop itself. */
let pointerDownOnBackdrop = false;


export { safeHref } from './panel-parts.js';

/** Date and kickoff ET, then the time-slot after a semicolon. The time-slot label ("Prime time",
 * "Afternoon", "Noon") is gated on `showsTimeSlot` (D-19): only a
 * regular-season Saturday game shows it, so a Saturday bowl/CFP game never
 * gets a misleading scheduling-pattern label. */
function dateLine(data, i, unplayed = false, weekend = false) {
  const t = data.t;
  const noTime = unplayed ? 'Time TBA' : 'Kickoff time not recorded';
  // A panel opened from This weekend writes the kickoff as that view does (18-UI-REVIEW item 8).
  if (weekend) return apKickoff(t.date[i], t.kickoff[i], noTime);
  const line = apKickoff(t.date[i], t.kickoff[i], noTime.toLowerCase() === 'time tba' ? noTime : 'kickoff time not recorded', { year: true });
  return showsTimeSlot(data, i) ? `${line}; ${SLOT_LABELS[t.time_slot[i]]}` : line;
}

/** Networks paragraph for a CFB telecast: primary network first, then the other outlets in
 * network precedence (U7). Radio shows only when nothing else carries the game (user,
 * 2026-11-09; `broadcastNetworks`). Full names and any parenthetical notes are kept (SITE-26). */
function buildNetworksParagraph(data, i, theme) {
  const t = data.t;
  const { primary, others } = broadcastNetworks(
    data.lookups.networks[t.network[i]],
    t.outlets[i].filter((idx) => idx !== t.network[i]).map((idx) => data.lookups.networks[idx]),
  );
  return networksParagraph({
    primary,
    others,
    theme,
  });
}

/** Crew list for a CFB telecast: " (alt-cast)" etc. after a non-main feed (D-10). */
function buildCrewList(data, i, selected) {
  return crewBox(
    crewEntries(data, i, { selected }).map((entry) => ({
      name: entry.name,
      role: entry.role,
      selected: entry.selected,
      feedLabel: entry.feed !== 'main' ? FEED_LABELS[entry.feed] : null,
    })),
  );
}

/** "Selected on this game: ..." line (D-07), or null when nobody selected is on this dot. */
function selectedOnGameText(data, view, i) {
  const onGame = view.peopleOnGame.get(i);
  if (!onGame || onGame.length === 0) return null;
  const names = onGame.map((personIndex) => data.lookups.people[personIndex].name);
  return `Selected on this game: ${names.join(', ')}`;
}

/** First flag of `kind` on telecast `i`, or null. */
function flagOfKind(data, i, kind) {
  for (const idx of data.t.flags[i]) {
    const flag = data.lookups.flags[idx];
    if (flag.kind === kind) return flag;
  }
  return null;
}

/** Viewers paragraph: figure + measurement label. For Nielsen+Adobe the D-02
 * badge is the only place the label appears (D-39), linked to the measurement
 * flag's source when that passes `safeHref`. */
function buildViewersParagraph(data, i) {
  const t = data.t;
  const p = document.createElement('p');
  if (!data.rated[i]) {
    p.appendChild(document.createTextNode(`${noRatingLine(data, i)}; `));
    const why = document.createElement('a');
    why.href = 'methodology.html#games-with-no-public-rating';
    why.textContent = 'Why no rating?';
    p.appendChild(why);
    return p;
  }
  if (t.measurement_type[i] === 'nielsen_adobe') {
    p.appendChild(document.createTextNode(`Viewers: ${formatViewersProse(t.viewers[i])}, `));
    const flag = flagOfKind(data, i, 'measurement');
    const badge =
      (flag && externalLink(flag.source_url, 'Nielsen + Adobe (streaming)')) ??
      document.createElement('span');
    badge.className = 'badge';
    if (badge.textContent === '') badge.textContent = 'Nielsen + Adobe (streaming)';
    p.appendChild(badge);
  } else {
    p.appendChild(
      document.createTextNode(
        `Viewers: ${formatViewersProse(t.viewers[i])}, ${measurementLabel(t.measurement_type[i])}`,
      ),
    );
  }
  return p;
}

/** Flags list: each label, linked to its own `source_url` when that passes
 * `safeHref` (D-04). Measurement flags for Nielsen+Adobe and combined flags
 * for a telecast with a feed count are shown elsewhere (D-39), so skipped. */
function buildFlagsList(data, i) {
  const t = data.t;
  if (!data.rated[i]) return null;
  const flags = t.flags[i]
    .map((idx) => data.lookups.flags[idx])
    .filter(
      (flag) =>
        !(flag.kind === 'measurement' && t.measurement_type[i] === 'nielsen_adobe') &&
        !(flag.kind === 'combined' && t.combined_feeds[i] != null),
    );
  if (flags.length === 0) return null;
  const ul = document.createElement('ul');
  ul.className = 'panel-flags';
  for (const flag of flags) {
    const li = document.createElement('li');
    const link = externalLink(flag.source_url, flag.label);
    li.appendChild(link ?? document.createTextNode(flag.label));
    ul.appendChild(li);
  }
  return ul;
}

/** Links section: every RR record, the original source (or its absence), then the crew's own source for a hand-confirmed crew (04.3 D-11) or else the 506 listing. */
function buildLinksList(data, i, weekend = false) {
  const t = data.t;
  const items = [];

  const rated = Boolean(data.rated[i]);
  const rrUrls = rated ? t.rr_urls[i] : [];
  rrUrls.forEach((url, idx) => {
    const label =
      rrUrls.length > 1
        ? `View record ${idx + 1} on Ratings Reference ↗`
        : 'View record on Ratings Reference ↗';
    items.push({ href: url, text: label, fallback: label });
  });

  if (rated) {
    const publisherName = t.publisher[i] != null ? data.lookups.publishers[t.publisher[i]] : null;
    items.push({
      href: t.source_url[i],
      text: `View original source (${publisherName ?? 'publisher unknown'}) ↗`,
      fallback: 'Original source not recorded',
    });
  }

  const crewSourceLabel = t.crew_source_label?.[i] ?? null;
  const crewSourceUrl = t.crew_source_url?.[i] ?? null;
  if (crewSourceLabel != null) {
    items.push({
      href: crewSourceUrl,
      text: `Crew source: ${crewSourceLabel} ↗`,
      fallback: `Crew source: ${crewSourceLabel}`,
    });
  } else {
    // From This weekend the credit reads as the NFL panel's does (18-UI-SPEC, item 8).
    items.push({
      href: t.s506_url[i],
      text: weekend ? 'Crew from 506 Sports ↗' : 'View 506 Sports listing ↗',
    });
  }

  return linksList(items);
}

/**
 * "[icon] label" game-type line. A decorative icon that can't be built is
 * skipped so the label always shows.
 * @param {string} kind
 * @param {string} label
 * @returns {HTMLParagraphElement}
 */
function buildLabelLine(kind, label, extra = null) {
  const p = document.createElement('p');
  p.className = 'panel-game-type';
  const icon = makeGameTypeIcon(kind);
  p.replaceChildren(...(icon ? [icon] : []), ...(extra ? [extra] : []), document.createTextNode(label));
  return p;
}

/**
 * Bowl line (D-20, D-21): bowl icon, then the official name with the core
 * name bold in --ink and the sponsor text around it in --muted. textContent
 * only, so a hostile name renders as literal text.
 * @param {{name: string, core: string}} bowl
 * @returns {HTMLParagraphElement}
 */
function buildBowlLine(bowl) {
  const p = document.createElement('p');
  p.className = 'panel-game-type panel-bowl';
  const parts = [];
  const icon = makeGameTypeIcon('bowl');
  if (icon) parts.push(icon);
  const at = bowl.name.indexOf(bowl.core);
  const span = (cls, text) => {
    const el = document.createElement(cls === 'bowl-core' ? 'strong' : 'span');
    el.className = cls;
    el.textContent = text;
    return el;
  };
  if (at < 0) {
    const plain = document.createElement('span');
    plain.style.fontWeight = '400';
    plain.style.color = 'var(--ink)';
    plain.textContent = bowl.name;
    parts.push(plain);
  } else {
    if (at > 0) parts.push(span('bowl-sponsor', bowl.name.slice(0, at)));
    parts.push(span('bowl-core', bowl.core));
    const rest = bowl.name.slice(at + bowl.core.length);
    if (rest) parts.push(span('bowl-sponsor', rest));
  }
  p.replaceChildren(...parts);
  return p;
}

/**
 * Rivalry line (04.10 D-11): crossed-swords icon, then the rivalry name bold
 * in --ink. textContent only, so a hostile name renders as literal text.
 * @param {string} name
 * @returns {HTMLParagraphElement}
 */
function buildRivalryLine(name) {
  const p = document.createElement('p');
  p.className = 'panel-game-type panel-rivalry';
  const parts = [];
  const icon = makeGameTypeIcon('rivalry');
  if (icon) parts.push(icon);
  const strong = document.createElement('strong');
  strong.className = 'rivalry-name';
  strong.textContent = name;
  parts.push(strong);
  p.replaceChildren(...parts);
  return p;
}

/**
 * Writes the modal title with each rank as a superscript and no "#" (notes 2026-11-02): the
 * title's large serif makes a full-size "#7" read as part of the name. Text nodes only, never
 * markup, so a team name is always plain text. The aria-label keeps the spoken "#7" form,
 * since a bare superscript would read as "7Michigan State".
 * @param {HTMLElement} titleEl
 * @param {object} data - a `prepareData` result.
 * @param {number} i - telecast index.
 */
export function renderMatchupTitle(titleEl, data, i) {
  const parts = matchupParts(data, i, { withScore: true });
  const side = (nodes, { rank, team, score }) => {
    if (rank != null) {
      const sup = document.createElement('sup');
      sup.className = 'title-rank';
      sup.textContent = String(rank);
      nodes.push(sup);
    }
    nodes.push(document.createTextNode(score != null ? `${team} ${score}` : team));
    return nodes;
  };
  const away = side([], parts.away);
  // A wrapping title breaks before its joiner (2026-11-03): the joiner, the home side and the
  // badge share one inline-block after the away side (matchup-wrap.js).
  const nodes = side([document.createTextNode(`${parts.separator} `)], parts.home);
  // Phase 28 (D-01, D-04): a both-ranked game ends the title with the ranked badge; the
  // title's aria-label carries the sentence, so the badge itself is aria-hidden. Only the CFB
  // modal reaches here (NFL and MLB have their own panels), and data without rank columns
  // never shows it.
  const ranked = bothRanked(data.t.away_rank?.[i], data.t.home_rank?.[i]);
  if (ranked) {
    // The title's last word and the badge share a no-wrap span, so a narrow modal never leaves
    // the badge alone on a line of its own.
    const last = nodes.pop();
    const text = last.textContent;
    const cut = text.lastIndexOf(' ') + 1;
    if (cut > 0) nodes.push(document.createTextNode(text.slice(0, cut)));
    const glue = document.createElement('span');
    glue.className = 'rk-glue';
    glue.append(document.createTextNode(text.slice(cut)), rankBadge({ hidden: true }));
    nodes.push(glue);
  }
  titleEl.replaceChildren(...joinerBreakNodes(away, nodes));
  // A wrapped title moves its badge to the right, centred on the lines (matchup-wrap.js).
  watchBadgeWrap(titleEl);
  const label = formatMatchup(data, i, { withScore: true });
  // A matchup usually ends without a full stop, so the sentence gets one first: screen readers
  // pause only at punctuation, and "34 Both" would otherwise run into the score.
  const stop = /[.!?]$/.test(label) ? '' : '.';
  titleEl.setAttribute('aria-label', ranked ? `${label}${stop} Both teams ranked.` : label);
}

/**
 * The modal's Conference line (D-12, D-13): "Conference: [logo] vs. [logo]", each logo for the
 * game's season (D-09), a side without a logo as its name in text (D-11), a side with no
 * conference as "Not recorded" (conferenceLine's wording), and one mark when both teams share
 * a conference. Names enter the DOM only through conferenceMark (a Text node, or an img whose
 * alt and title are set as properties) and text nodes, never as markup (T-28-14).
 * @param {object} data - a `prepareData` result.
 * @param {number} i - telecast index.
 * @returns {HTMLParagraphElement}
 */
function buildConferencesParagraph(data, i) {
  const t = data.t;
  const season = t.season?.[i] ?? null;
  const nameOf = (idx) => (idx != null ? (data.lookups.conferences[idx]?.name ?? null) : null);
  const mark = (name) => (name != null ? conferenceMark(name, season) : document.createTextNode('Not recorded'));
  const away = nameOf(t.away_conference[i]);
  const home = nameOf(t.home_conference[i]);
  const line = document.createElement('span');
  line.className = 'cf-line';
  if (away != null && away === home) {
    line.append(mark(away));
  } else {
    const sep = document.createElement('span');
    sep.className = 'cf-sep';
    sep.textContent = 'vs.';
    line.append(mark(away), sep, mark(home));
  }
  const p = document.createElement('p');
  p.className = 'panel-conferences';
  p.append(markText('Conference: '), line);
  return p;
}

/**
 * Renders the full detail-panel body for telecast `i` into `bodyEl`, and
 * its title into `titleEl` (SITE-05, D-02, D-04, D-07, D-08, D-16). Pure DOM
 * update -- safe to call again for a different `i` while the panel is
 * already open (D-10 swap), or to refresh the currently open panel after a
 * selection changes elsewhere in the app.
 * Game type (D-20, D-21): a bowl game (or CFP quarterfinal/semifinal) shows
 * its named bowl line first, then a "[trophy] CFP round" line. The location line
 * ("AT&T Stadium, Arlington, TX") sits right under the date for any game with a venue; a
 * neutral-site game adds " (neutral site)" unless a named bowl line shows. A named rivalry
 * (04.10 D-11) shows its own line and never suppresses the neutral-site note.
 * D-39: an empty crew reads "Crew not recorded" (the missing crews themselves are
 * a data-join issue, out of scope: see the championship-crews todo); the
 * Nielsen+Adobe label shows once (the badge) and combined feeds show as one line.
 * An `unplayed` game (D-22, Phase 18) shows "Not played yet." in place of the viewers, figure,
 * spread and excitement lines, and "Crew TBA" for an empty crew; nothing else changes.
 * @param {HTMLElement} bodyEl
 * @param {HTMLElement} titleEl
 * @param {{data: object, i: number, state: object, view: object, unplayed?: boolean}} ctx
 */
export function renderPanel(bodyEl, titleEl, { data, i, state, view, unplayed = false, weekend = false }) {
  const t = data.t;
  renderMatchupTitle(titleEl, data, i);

  const children = [];

  const dateP = document.createElement('p');
  dateP.textContent = dateLine(data, i, unplayed, weekend);
  children.push(dateP);

  const gameType = gameTypeInfo(data, i);
  const bowlIdx = t.bowl?.[i] ?? null;
  const bowl = bowlIdx != null ? (data.lookups.bowls?.[bowlIdx] ?? null) : null;
  const typeLines = [];
  let namedBowlLine = false;
  if (gameType != null && (gameType.kind === 'bowl' || gameType.atBowl)) {
    if (bowl) {
      typeLines.push(buildBowlLine(bowl));
      namedBowlLine = true;
    } else {
      typeLines.push(buildLabelLine('bowl', 'Bowl'));
    }
  } else if (bowl) {
    typeLines.push(buildBowlLine(bowl));
    namedBowlLine = true;
  }
  if (gameType != null && gameType.kind === 'playoff') {
    // The title game keeps the trophy and adds the national championship emblem after it.
    typeLines.push(buildLabelLine('playoff', gameType.label, isTitleGame(data, i) ? titleGameMark() : null));
  }

  // The venue sits right under the date; a named bowl line already says the game is neutral.
  const venue = t.place?.[i] != null ? (data.lookups.venues?.[t.place[i]] ?? null) : null;
  const locationP = locationLine(venue, Boolean(t.neutral[i]) && !namedBowlLine);
  if (locationP) children.push(locationP);
  children.push(...typeLines);

  const rivalry = rivalryName(data, i);
  if (rivalry != null) children.push(buildRivalryLine(rivalry));

  // conferenceLine stays the gate: a game with neither conference recorded has no line.
  if (conferenceLine(data, i) != null) children.push(buildConferencesParagraph(data, i));

  children.push(buildNetworksParagraph(data, i, currentTheme()));

  const crewHeading = document.createElement('h3');
  crewHeading.textContent = 'Crew';
  if (t.crew[i].length === 0) {
    const emptyP = document.createElement('p');
    emptyP.className = 'panel-crew-empty crew-missing';
    emptyP.textContent = unplayed ? 'Crew TBA' : 'Crew not recorded';
    children.push(crewHeading, emptyP);
  } else {
    children.push(crewHeading, buildCrewList(data, i, selectedPersonIndexes(data, state)));
  }
  const boothText = boothLabel(data, i);
  if (boothText != null) {
    const boothP = document.createElement('p');
    boothP.className = 'panel-booth';
    boothP.textContent = boothText;
    children.push(boothP);
  }

  const selectedText = selectedOnGameText(data, view, i);
  if (selectedText) {
    const selectedP = document.createElement('p');
    selectedP.textContent = selectedText;
    children.push(selectedP);
  }

  if (unplayed) {
    const unplayedP = document.createElement('p');
    unplayedP.className = 'panel-unplayed';
    unplayedP.textContent = 'Not played yet.';
    children.push(unplayedP);
  } else {
    children.push(buildViewersParagraph(data, i));

    if (data.rated[i] && t.publisher[i] != null) {
      const publishedP = document.createElement('p');
      publishedP.textContent = `Figure first published by ${data.lookups.publishers[t.publisher[i]]}`;
      children.push(publishedP);
    }

    const notViaRr = data.rated[i] ? figureNotViaRrText(data, i) : null;
    if (notViaRr) {
      const notViaRrP = document.createElement('p');
      notViaRrP.textContent = notViaRr;
      children.push(notViaRrP);
    }

    const spreadText = axisValueText(data, i, 'spread');
    const excitementText = axisValueText(data, i, 'excitement');
    const axisP = document.createElement('p');
    axisP.textContent = state.axis === 'excitement'
      ? `${excitementText}; ${spreadText}`
      : `${spreadText}; ${excitementText}`;
    children.push(axisP);

    const flagsList = buildFlagsList(data, i);
    if (flagsList) children.push(flagsList);

    if (data.rated[i] && t.combined_feeds[i] != null) {
      const combinedP = document.createElement('p');
      const combinedText = `Combined across ${t.combined_feeds[i]} feeds`;
      const combinedFlag = flagOfKind(data, i, 'combined');
      const combinedLink = combinedFlag && externalLink(combinedFlag.source_url, combinedText);
      if (combinedLink) combinedP.appendChild(combinedLink);
      else combinedP.textContent = combinedText;
      children.push(combinedP);
    }
  }

  const linksHeading = document.createElement('h3');
  linksHeading.textContent = 'Links';
  const linksEl = buildLinksList(data, i, weekend);
  // An unplayed game with no crew source has no link to show; skip the empty section.
  if (!unplayed || linksEl.children.length > 0) children.push(linksHeading, linksEl);

  bodyEl.replaceChildren(...children);
}

/**
 * Binds the dialog's close mechanics once: the x button, backdrop click (only
 * when the press also began on the backdrop, so a text drag-select ending
 * there does not close it), and the native `close` event, which reports
 * `onClosed` and returns focus to the opener (or `#chart`).
 * @param {{onClosed: () => void}} opts
 */
export function initPanel({ onClosed }) {
  const dialog = document.getElementById('detail-panel');
  document.getElementById('panel-close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('pointerdown', (ev) => {
    pointerDownOnBackdrop = ev.target === dialog;
  });
  dialog.addEventListener('click', (ev) => {
    if (ev.target === dialog && pointerDownOnBackdrop) dialog.close();
    pointerDownOnBackdrop = false;
  });
  dialog.addEventListener('close', () => {
    // `close` is queued as a task, so a close and reopen in the same task
    // delivers it while the dialog is open again; that event is stale, and
    // acting on it would forget the open panel and its opener (review WR-03).
    // Under load an earlier session's event can also land after the next
    // session has closed, so two events see a closed dialog: handle each
    // session once, or the second would find no opener and focus #chart.
    if (dialog.open || handledSession === openSession) return;
    handledSession = openSession;
    onClosed();
    const target = liveOpener(opener) ?? document.getElementById('chart');
    opener = null;
    if (target) target.focus({ preventScroll: true });
  });
}

/**
 * Opens the modal on telecast `i`, or swaps its contents when it is already
 * open (D-10). Closes any open popover first; the opener is the focused
 * element, or `#chart` when focus sat on the body (a dot click).
 * @param {number} i
 * @param {{data: object, state: object, view: object, unplayed?: boolean, weekend?: boolean}} ctx -
 *   `weekend` marks a panel opened from This weekend (AP kickoff line, `Crew from 506 Sports`).
 */
export function openPanel(i, ctx) {
  showPanel({
    data: ctx.data, i, state: ctx.state, view: ctx.view,
    unplayed: ctx.unplayed === true, weekend: ctx.weekend === true,
  });
}

/**
 * Opens the same modal on scheduled game `j` (Phase 18, D-22): the panel renders over the
 * scheduled facade, so it shows teams, kickoff (or Time TBA), network (or Network TBA), its
 * ESPN Press Room crew or "Crew TBA", and "Not played yet." with no score, figure or excitement.
 * @param {number} j - index into the scheduled block.
 * @param {{data: object, state: object, unplayed?: boolean}} ctx - `data` is the prepared data;
 *   `unplayed` (default true) is false once the game has kicked off (18-13 F3).
 */
export function openScheduledPanel(j, ctx) {
  const facade = scheduledFacade(ctx.data);
  showPanel({
    data: facade,
    i: j,
    state: ctx.state,
    view: scheduledView(facade, j, ctx.state),
    unplayed: ctx.unplayed ?? true,
    weekend: true,
  });
}

/**
 * The panel view of scheduled game `j`: the picked people on its own crew. The played-game
 * view is keyed by `data.t` index, so it never applies to a scheduled row (18-13 F5).
 */
function scheduledView(facade, j, state) {
  const onGame = (state.people ?? [])
    .map((id) => facade.personIndexById.get(id))
    .filter((p) => p != null && personOnGame(facade, j, p, state.role) != null);
  return { peopleOnGame: onGame.length > 0 ? new Map([[j, onGame]]) : new Map() };
}

/** Renders `args` into the dialog and opens it (or swaps its contents when already open). */
function showPanel(args) {
  const dialog = document.getElementById('detail-panel');
  const titleEl = document.getElementById('panel-title');
  const bodyEl = document.getElementById('panel-body');
  renderPanel(bodyEl, titleEl, args);
  if (dialog.open) return;
  for (const el of document.querySelectorAll(':popover-open')) el.hidePopover();
  const active = document.activeElement;
  opener = active && active !== document.body ? active : document.getElementById('chart');
  openSession += 1;
  dialog.showModal();
  // The title had no layout while the dialog was closed; place the badge before first paint.
  syncBadgeWrap(titleEl);
}

/** Closes the modal if open; the `close` event handler restores focus. */
export function closePanel() {
  const dialog = document.getElementById('detail-panel');
  if (dialog.open) dialog.close();
}
