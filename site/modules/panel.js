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
 * `safeHref` first (T-04-35): a telecast's `source_url`/`s506_url`/flag
 * `source_url` that isn't a plain http(s) URL never becomes a clickable
 * link.
 */


import {
  FEED_LABELS,
  ROLE_LABELS,
  SLOT_LABELS,
  conferenceLine,
  formatAxisValue,
  formatDate,
  formatKickoff,
  formatMatchup,
  formatViewers,
  gameTypeInfo,
  measurementLabel,
  showsTimeSlot,
} from './format.js';
import { makeGameTypeIcon } from './icons.js';
import { currentTheme, makePill } from './pill.js';

/** The element focus returns to when the dialog closes, or null. */
let opener = null;

/** Whether the latest pointerdown on the dialog landed on the backdrop itself. */
let pointerDownOnBackdrop = false;


/**
 * Returns `url` unchanged when it parses as an `http:`/`https:` URL, else
 * `null` (T-04-35). A malformed or non-http(s) scheme (e.g. `javascript:`)
 * never becomes a link href.
 * @param {string|null} url
 * @returns {string|null}
 */
export function safeHref(url) {
  if (url == null) return null;
  try {
    const parsed = new URL(url);
    return parsed.protocol === 'https:' || parsed.protocol === 'http:' ? url : null;
  } catch {
    return null;
  }
}

/**
 * Builds an external `<a>` with the D-16/T-04-36 target/rel pair, or
 * returns `null` when `href` fails `safeHref`.
 */
function externalLink(href, text) {
  const safe = safeHref(href);
  if (safe == null) return null;
  const a = document.createElement('a');
  a.href = safe;
  a.target = '_blank';
  a.rel = 'noopener noreferrer';
  a.textContent = text;
  return a;
}

/** date · kickoff ET · time-slot line. The time-slot label ("Prime time",
 * "Afternoon", "Noon") is gated on `showsTimeSlot` (D-19): only a
 * regular-season Saturday game shows it, so a Saturday bowl/CFP game never
 * gets a misleading scheduling-pattern label. */
function dateLine(data, i) {
  const t = data.t;
  const parts = [formatDate(t.date[i]), formatKickoff(t.kickoff[i]) ?? 'Kickoff time not recorded'];
  if (showsTimeSlot(data, i)) parts.push(SLOT_LABELS[t.time_slot[i]]);
  return parts.join(' · ');
}

/** Networks paragraph: "Network: " + a pill per network, primary first, then
 * "Also on: " + a pill per other outlet (SITE-26). Full names and any
 * parenthetical notes are kept -- the panel is where they belong. */
function buildNetworksParagraph(data, i, theme) {
  const t = data.t;
  const p = document.createElement('p');
  p.className = 'panel-networks';
  p.appendChild(document.createTextNode('Network: '));
  const primaryNet = data.lookups.networks[t.network[i]];
  p.appendChild(makePill(primaryNet.name, primaryNet.family, theme));
  const others = t.outlets[i].filter((idx) => idx !== t.network[i]);
  if (others.length > 0) {
    p.appendChild(document.createTextNode(' · Also on: '));
    others.forEach((idx, pos) => {
      if (pos > 0) p.appendChild(document.createTextNode(' '));
      const net = data.lookups.networks[idx];
      p.appendChild(makePill(net.name, net.family, theme));
    });
  }
  return p;
}

/** Crew list: one `<li>` per crew entry, "[Position]: [Name]" (product
 * notes 2026-09-27), with a parenthetical feed label appended when not main
 * (D-08), e.g. "Analyst: Taylor Vance (alt-cast)". */
function buildCrewList(data, i) {
  const ul = document.createElement('ul');
  ul.className = 'panel-crew';
  for (const entry of data.t.crew[i]) {
    const li = document.createElement('li');
    const name = data.lookups.people[entry.person].name;
    const roleLabel = ROLE_LABELS[entry.role] ?? ROLE_LABELS.unknown;
    const feedLabel = entry.feed !== 'main' ? FEED_LABELS[entry.feed] : '';
    li.textContent = feedLabel !== '' ? `${roleLabel}: ${name} (${feedLabel})` : `${roleLabel}: ${name}`;
    ul.appendChild(li);
  }
  return ul;
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
  if (t.measurement_type[i] === 'nielsen_adobe') {
    p.appendChild(document.createTextNode(`Viewers: ${formatViewers(t.viewers[i])} · `));
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
        `Viewers: ${formatViewers(t.viewers[i])} · ${measurementLabel(t.measurement_type[i])}`,
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

/** Links section: every RR record, the original source (or its absence), and the 506 listing. */
function buildLinksList(data, i) {
  const t = data.t;
  const ul = document.createElement('ul');
  ul.className = 'panel-links';

  const rrUrls = t.rr_urls[i];
  rrUrls.forEach((url, idx) => {
    const label =
      rrUrls.length > 1
        ? `View record ${idx + 1} on Ratings Reference ↗`
        : 'View record on Ratings Reference ↗';
    const li = document.createElement('li');
    li.appendChild(externalLink(url, label) ?? document.createTextNode(label));
    ul.appendChild(li);
  });

  const sourceLi = document.createElement('li');
  const publisherName = t.publisher[i] != null ? data.lookups.publishers[t.publisher[i]] : null;
  const sourceLink = externalLink(t.source_url[i], `View original source (${publisherName ?? 'publisher unknown'}) ↗`);
  sourceLi.appendChild(sourceLink ?? document.createTextNode('Original source not recorded'));
  ul.appendChild(sourceLi);

  const s506Link = externalLink(t.s506_url[i], 'View 506 Sports listing ↗');
  if (s506Link) {
    const li = document.createElement('li');
    li.appendChild(s506Link);
    ul.appendChild(li);
  }

  return ul;
}

/**
 * "[icon] label" game-type line. A decorative icon that can't be built is
 * skipped so the label always shows.
 * @param {string} kind
 * @param {string} label
 * @returns {HTMLParagraphElement}
 */
function buildLabelLine(kind, label) {
  const p = document.createElement('p');
  p.className = 'panel-game-type';
  const icon = makeGameTypeIcon(kind);
  p.replaceChildren(...(icon ? [icon] : []), document.createTextNode(label));
  return p;
}

/**
 * Bowl line (D-20, D-21): bowl icon, then the official name with the core
 * name bold in --text and the sponsor text around it in --muted. textContent
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
    plain.style.color = 'var(--text)';
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
 * Renders the full detail-panel body for telecast `i` into `bodyEl`, and
 * its title into `titleEl` (SITE-05, D-02, D-04, D-07, D-08, D-16). Pure DOM
 * update -- safe to call again for a different `i` while the panel is
 * already open (D-10 swap), or to refresh the currently open panel after a
 * selection changes elsewhere in the app.
 * Game type (D-20, D-21): a bowl game (or CFP quarterfinal/semifinal) shows
 * its named bowl line first, then a "[trophy] CFP round" line; a named bowl
 * replaces "Neutral site".
 * D-39: an empty crew reads "Crew not listed" (the missing crews themselves are
 * a data-join issue, out of scope: see the championship-crews todo); the
 * Nielsen+Adobe label shows once (the badge) and combined feeds show as one line.
 * @param {HTMLElement} bodyEl
 * @param {HTMLElement} titleEl
 * @param {{data: object, i: number, state: object, view: object}} ctx
 */
export function renderPanel(bodyEl, titleEl, { data, i, state, view }) {
  const t = data.t;
  titleEl.textContent = formatMatchup(data, i, { withScore: true });

  const children = [];

  const dateP = document.createElement('p');
  dateP.textContent = dateLine(data, i);
  children.push(dateP);

  const gameType = gameTypeInfo(data, i);
  const bowlIdx = t.bowl?.[i] ?? null;
  const bowl = bowlIdx != null ? (data.lookups.bowls?.[bowlIdx] ?? null) : null;
  let namedBowlLine = false;
  if (gameType != null && (gameType.kind === 'bowl' || gameType.atBowl)) {
    if (bowl) {
      children.push(buildBowlLine(bowl));
      namedBowlLine = true;
    } else {
      children.push(buildLabelLine('bowl', 'Bowl'));
    }
  } else if (bowl) {
    children.push(buildBowlLine(bowl));
    namedBowlLine = true;
  }
  if (gameType != null && gameType.kind === 'playoff') {
    children.push(buildLabelLine('playoff', gameType.label));
  }

  if (t.neutral[i] && !namedBowlLine) {
    const neutralP = document.createElement('p');
    neutralP.textContent = 'Neutral site';
    children.push(neutralP);
  }

  const conferences = conferenceLine(data, i);
  if (conferences != null) {
    const conferencesP = document.createElement('p');
    conferencesP.className = 'panel-conferences';
    conferencesP.textContent = `Conference: ${conferences}`;
    children.push(conferencesP);
  }

  children.push(buildNetworksParagraph(data, i, currentTheme()));

  const crewHeading = document.createElement('h3');
  crewHeading.textContent = 'Crew';
  if (t.crew[i].length === 0) {
    const emptyP = document.createElement('p');
    emptyP.className = 'panel-crew-empty';
    emptyP.textContent = 'Crew not listed';
    children.push(crewHeading, emptyP);
  } else {
    children.push(crewHeading, buildCrewList(data, i));
  }

  const selectedText = selectedOnGameText(data, view, i);
  if (selectedText) {
    const selectedP = document.createElement('p');
    selectedP.textContent = selectedText;
    children.push(selectedP);
  }

  children.push(buildViewersParagraph(data, i));

  if (t.publisher[i] != null) {
    const publishedP = document.createElement('p');
    publishedP.textContent = `Figure first published by ${data.lookups.publishers[t.publisher[i]]}`;
    children.push(publishedP);
  }

  const otherAxis = state.axis === 'pregame' ? 'excitement' : 'pregame';
  const axisP = document.createElement('p');
  axisP.textContent = `${formatAxisValue(state.axis, t[state.axis][i])} · ${formatAxisValue(otherAxis, t[otherAxis][i])}`;
  children.push(axisP);

  const flagsList = buildFlagsList(data, i);
  if (flagsList) children.push(flagsList);

  if (t.combined_feeds[i] != null) {
    const combinedP = document.createElement('p');
    const combinedText = `Combined across ${t.combined_feeds[i]} feeds`;
    const combinedFlag = flagOfKind(data, i, 'combined');
    const combinedLink = combinedFlag && externalLink(combinedFlag.source_url, combinedText);
    if (combinedLink) combinedP.appendChild(combinedLink);
    else combinedP.textContent = combinedText;
    children.push(combinedP);
  }

  const linksHeading = document.createElement('h3');
  linksHeading.textContent = 'Links';
  children.push(linksHeading, buildLinksList(data, i));

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
    onClosed();
    const target = opener && opener.isConnected ? opener : document.getElementById('chart');
    opener = null;
    if (target) target.focus({ preventScroll: true });
  });
}

/**
 * Opens the modal on telecast `i`, or swaps its contents when it is already
 * open (D-10). Closes any open popover first; the opener is the focused
 * element, or `#chart` when focus sat on the body (a dot click).
 * @param {number} i
 * @param {{data: object, state: object, view: object}} ctx
 */
export function openPanel(i, ctx) {
  const dialog = document.getElementById('detail-panel');
  const titleEl = document.getElementById('panel-title');
  const bodyEl = document.getElementById('panel-body');
  renderPanel(bodyEl, titleEl, { data: ctx.data, i, state: ctx.state, view: ctx.view });
  if (dialog.open) return;
  for (const el of document.querySelectorAll(':popover-open')) el.hidePopover();
  const active = document.activeElement;
  opener = active && active !== document.body ? active : document.getElementById('chart');
  dialog.showModal();
}

/** Closes the modal if open; the `close` event handler restores focus. */
export function closePanel() {
  const dialog = document.getElementById('detail-panel');
  if (dialog.open) dialog.close();
}
