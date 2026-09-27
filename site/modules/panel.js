/**
 * Detail panel: full per-telecast facts, credits, and source links (SITE-05,
 * SITE-17, D-02, D-04, D-07, D-08, D-10, D-16). A right-side drawer on
 * desktop and a bottom sheet on phones (both styled by `.drawer` in
 * style.css); opened by a chart dot click or a matched-games table row's
 * Details button, closed by `#panel-close` or Escape.
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
  formatAxisValue,
  formatDate,
  formatKickoff,
  formatMatchup,
  formatViewers,
  measurementLabel,
} from './format.js';

/** The element focus should return to once the panel closes, or null. */
let previouslyFocused = null;

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

/** date · kickoff ET · time-slot line, matching the hover's own ordering. */
function dateLine(data, i) {
  const t = data.t;
  const parts = [formatDate(t.date[i]), formatKickoff(t.kickoff[i]) ?? 'Kickoff time not recorded'];
  if (t.time_slot[i] != null) parts.push(SLOT_LABELS[t.time_slot[i]]);
  return parts.join(' · ');
}

/** Primary network, then "Also on: ..." for any other outlets. */
function networkLine(data, i) {
  const t = data.t;
  const primary = data.lookups.networks[t.network[i]].name;
  const others = t.outlets[i]
    .filter((idx) => idx !== t.network[i])
    .map((idx) => data.lookups.networks[idx].name);
  return others.length > 0 ? `${primary} · Also on: ${others.join(', ')}` : primary;
}

/** Crew list: one `<li>` per crew entry -- name, role label, and a feed label when not main (D-08). */
function buildCrewList(data, i) {
  const ul = document.createElement('ul');
  ul.className = 'panel-crew';
  for (const entry of data.t.crew[i]) {
    const li = document.createElement('li');
    const name = data.lookups.people[entry.person].name;
    const roleLabel = ROLE_LABELS[entry.role] ?? '';
    const feedLabel = entry.feed !== 'main' ? FEED_LABELS[entry.feed] : '';
    li.textContent = [name, roleLabel, feedLabel].filter((part) => part !== '').join(' — ');
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

  if (t.neutral[i]) {
    const neutralP = document.createElement('p');
    neutralP.textContent = 'Neutral site';
    children.push(neutralP);
  }

  const networkP = document.createElement('p');
  networkP.textContent = networkLine(data, i);
  children.push(networkP);

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
  panelEl.hidden = false;
  document.body.classList.add('panel-open');
  document.getElementById('panel-close').focus();
}

/**
 * Closes the panel: removes `body.panel-open` immediately (driving the CSS
 * slide-out), hides `#detail-panel` after the 150ms transition (immediately
 * under `prefers-reduced-motion`), and restores focus to whatever was
 * focused before the panel opened.
 */
export function closePanel() {
  document.body.classList.remove('panel-open');

  const panelEl = document.getElementById('detail-panel');
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const hide = () => {
    panelEl.hidden = true;
  };
  if (reducedMotion) hide();
  else window.setTimeout(hide, 150);

  if (previouslyFocused && typeof previouslyFocused.focus === 'function') {
    previouslyFocused.focus();
  }
  previouslyFocused = null;
}
