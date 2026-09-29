/**
 * Detail panel: full per-telecast facts, credits, and source links (SITE-05,
 * SITE-17, D-01, D-02, D-04, D-07, D-08, D-09, D-10, D-16, D-17). A push
 * grid column on desktop/tablet and a bottom sheet on phones (styled by
 * `#detail-panel`/`.panel-inner` in style.css); opened by a chart dot click
 * or clicking/pressing Enter on a matched-games table row, closed by
 * `#panel-close` or Escape.
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
  gameTypeLabel,
  measurementLabel,
  showsTimeSlot,
} from './format.js';
import { currentTheme, makePill } from './pill.js';

/** The element focus should return to once the panel closes, or null. */
let previouslyFocused = null;

/** `closePanel`'s pending fallback hide timer, or null (WR-03, D-24). */
let hideTimer = null;

/** The one-shot `transitionend`/`transitioncancel` listener `closePanel`
 * registered on `#detail-panel`, or null (WR-03, D-24). Tracked so
 * `cancelPendingHide` can remove it before a reopen fires it late. */
let hideListenerTarget = null;
let hideListener = null;

/** Cancels a pending post-close hide -- both the fallback timer and the
 * transition-event listener -- so neither can fire after a reopen (WR-03). */
function cancelPendingHide() {
  if (hideTimer !== null) {
    window.clearTimeout(hideTimer);
    hideTimer = null;
  }
  if (hideListenerTarget !== null && hideListener !== null) {
    hideListenerTarget.removeEventListener('transitionend', hideListener);
    hideListenerTarget.removeEventListener('transitioncancel', hideListener);
    hideListenerTarget = null;
    hideListener = null;
  }
}

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

/** Viewers paragraph: figure + measurement label, with the D-02 badge appended for Nielsen+Adobe. */
function buildViewersParagraph(data, i) {
  const t = data.t;
  const p = document.createElement('p');
  p.appendChild(
    document.createTextNode(
      `Viewers: ${formatViewers(t.viewers[i])} · ${measurementLabel(t.measurement_type[i])}`,
    ),
  );
  if (t.measurement_type[i] === 'nielsen_adobe') {
    p.appendChild(document.createTextNode(' '));
    const badge = document.createElement('span');
    badge.className = 'badge';
    badge.textContent = 'Nielsen + Adobe (streaming)';
    p.appendChild(badge);
  }
  return p;
}

/** Flags list: each label, linked to its own `source_url` when that passes `safeHref` (D-04). */
function buildFlagsList(data, i) {
  const flagIdxs = data.t.flags[i];
  if (flagIdxs.length === 0) return null;
  const ul = document.createElement('ul');
  ul.className = 'panel-flags';
  for (const flagIdx of flagIdxs) {
    const flag = data.lookups.flags[flagIdx];
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
 * Renders the full detail-panel body for telecast `i` into `bodyEl`, and
 * its title into `titleEl` (SITE-05, D-02, D-04, D-07, D-08, D-16). Pure DOM
 * update -- safe to call again for a different `i` while the panel is
 * already open (D-10 swap), or to refresh the currently open panel after a
 * selection changes elsewhere in the app.
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

  const gameType = gameTypeLabel(data, i);
  if (gameType != null) {
    const gameTypeP = document.createElement('p');
    gameTypeP.className = 'panel-game-type';
    gameTypeP.textContent = gameType;
    children.push(gameTypeP);
  }

  if (t.neutral[i]) {
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
  children.push(crewHeading, buildCrewList(data, i));

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
    combinedP.textContent = `Combined across ${t.combined_feeds[i]} feeds`;
    children.push(combinedP);
  }

  const linksHeading = document.createElement('h3');
  linksHeading.textContent = 'Links';
  children.push(linksHeading, buildLinksList(data, i));

  bodyEl.replaceChildren(...children);
}

/**
 * Opens the panel on telecast `i` (or swaps its contents when it's already
 * open, D-10): renders, unhides `#detail-panel`, adds `body.panel-open`,
 * remembers the pre-open focus target the first time, and focuses the
 * close button.
 * @param {number} i
 * @param {{data: object, state: object, view: object}} ctx
 */
export function openPanel(i, ctx) {
  const panelEl = document.getElementById('detail-panel');
  const titleEl = document.getElementById('panel-title');
  const bodyEl = document.getElementById('panel-body');
  renderPanel(bodyEl, titleEl, { data: ctx.data, i, state: ctx.state, view: ctx.view });

  if (!document.body.classList.contains('panel-open')) {
    previouslyFocused = document.activeElement;
  }
  // A reopen inside closePanel's 150ms slide-out window would otherwise be
  // re-hidden when that stale timer fires (WR-03).
  cancelPendingHide();
  const wasHidden = panelEl.hidden;
  panelEl.hidden = false;
  // Unhiding and adding `body.panel-open` in the same frame would start the
  // width transition from `display: none`'s implicit 0 with no paint in
  // between, so the browser can coalesce it away entirely -- force a reflow
  // first so the 0-width state is committed before the class (and the
  // transition to 360px/320px) is applied (Pattern 1).
  if (wasHidden) void panelEl.offsetWidth;
  document.body.classList.add('panel-open');
  document.getElementById('panel-close').focus();
}

/**
 * Closes the panel: removes `body.panel-open` immediately (driving the CSS
 * slide-out), hides `#detail-panel` and restores focus to whatever was
 * focused before the panel opened.
 *
 * D-24 (original bug, desktop/tablet): a bare 150ms hide timer raced the
 * CSS `width` transition -- setting `hidden` (display:none) at the same
 * ~150ms mark as the transition's own natural end frequently interrupted it
 * first, so the browser fired `transitioncancel` instead of `transitionend`
 * for the tracked property, and app.js's `transitionend`-only resize
 * listener never ran (confirmed empirically: a diagnostic listener logged
 * `transitioncancel` for `width` at the transition's expected end time on
 * every close).
 *
 * D-32 (desktop/tablet mechanism): `#detail-panel`'s own `width` no longer
 * transitions at all (style.css's "Detail panel" section) -- the grid
 * column snaps to 0 in the same frame `body.panel-open` is removed, so
 * there is no transition left to wait for. The panel hides immediately,
 * the same way the old reduced-motion path always did, so the chart's own
 * resize (app.js, scheduled on the very next animation frame) sees the
 * final collapsed width at once instead of ~150ms later. This keeps D-24:
 * with nothing left to race, the panel can never end up stuck mid-close.
 *
 * Phones keep the original mechanism unchanged: hiding is driven by the
 * bottom sheet's own `transform` transition's one-shot event
 * (`transitionend` on a full close, `transitioncancel` on an interrupted
 * one -- e.g. a close fired mid-transition), with a longer fallback timer
 * only for the case where no transition event ever fires at all (e.g. the
 * panel was already off-screen), and hides immediately under
 * `prefers-reduced-motion`.
 */
export function closePanel() {
  document.body.classList.remove('panel-open');

  const panelEl = document.getElementById('detail-panel');
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const isPhone = window.matchMedia('(max-width: 640px)').matches;

  cancelPendingHide();

  const hide = () => {
    cancelPendingHide();
    panelEl.hidden = true;
  };

  if (!isPhone || reducedMotion) {
    // Desktop/tablet: no transition left to wait for (D-32). Phones under
    // reduced motion: same immediate-hide behavior as before.
    hide();
  } else {
    // Phones only, motion allowed: wait for the bottom sheet's own
    // `transform` transition to actually finish.
    const onTransitionEvent = (ev) => {
      if (ev.target !== panelEl || ev.propertyName !== 'transform') return;
      hide();
    };
    hideListenerTarget = panelEl;
    hideListener = onTransitionEvent;
    panelEl.addEventListener('transitionend', onTransitionEvent);
    panelEl.addEventListener('transitioncancel', onTransitionEvent);
    // Fallback: guarantees the panel still hides even if neither transition
    // event ever fires (belt-and-suspenders, not the primary mechanism).
    hideTimer = window.setTimeout(hide, 300);
  }

  if (previouslyFocused && typeof previouslyFocused.focus === 'function') {
    previouslyFocused.focus();
  }
  previouslyFocused = null;
}
