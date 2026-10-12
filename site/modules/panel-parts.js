/**
 * Data-independent detail-panel builders shared by the CFB and NFL panels
 * (08 D-14). Every function takes plain arguments, builds DOM only with
 * createElement/textContent (never a markup-injecting API), and sends every
 * href through `safeHref` with the target/rel pair (T-04-35, T-04-36).
 */

import { makePill, makeRolePill, nameWithRoles } from './pill.js';

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
export function externalLink(href, text) {
  const safe = safeHref(href);
  if (safe == null) return null;
  const a = document.createElement('a');
  a.href = safe;
  a.target = '_blank';
  a.rel = 'noopener noreferrer';
  a.textContent = text;
  return a;
}

/** Networks paragraph: "Network: " + a pill for `primary`, then "Also on: " + a
 * pill per entry of `others` (SITE-26). `primary` and `others` items are
 * `{ name, family }`.
 * @param {{primary: {name: string, family: string},
 *   others?: {name: string, family: string}[], theme: string}} args */
export function networksParagraph({ primary, others = [], theme }) {
  const p = document.createElement('p');
  p.className = 'panel-networks';
  p.appendChild(document.createTextNode('Network: '));
  p.appendChild(makePill(primary.name, primary.family, theme));
  if (others.length > 0) {
    p.appendChild(document.createTextNode(' · Also on: '));
    others.forEach((net, pos) => {
      if (pos > 0) p.appendChild(document.createTextNode(' '));
      p.appendChild(makePill(net.name, net.family, theme));
    });
  }
  return p;
}

/** Crew list in one violet `.crew-box`: one `<li>` per entry, "Name [pill]",
 * with " (feedLabel)" after the pill when `feedLabel` is non-null (D-10).
 * Selected entries are bold (D-11).
 * @param {{name: string, role: string, selected?: boolean, feedLabel?: string|null}[]} entries */
export function crewBox(entries) {
  const box = document.createElement('div');
  box.className = 'crew-box';
  const ul = document.createElement('ul');
  ul.className = 'panel-crew';
  for (const entry of entries) {
    const li = document.createElement('li');
    const name = document.createElement('span');
    name.className = entry.selected ? 'crew-name is-selected' : 'crew-name';
    name.textContent = entry.name;
    li.append(nameWithRoles(name, makeRolePill(entry.role)));
    if (entry.feedLabel != null) {
      const feed = document.createElement('span');
      feed.className = 'crew-feed';
      feed.textContent = ` (${entry.feedLabel})`;
      li.appendChild(feed);
    }
    ul.appendChild(li);
  }
  box.appendChild(ul);
  return box;
}

/** Links list: one `<li>` per item with `externalLink(href, text)`, or a text
 * node of `fallback` when the href is invalid and `fallback` is a string, or no
 * `<li>` when invalid and `fallback` is undefined.
 * @param {{href: string|null, text: string, fallback?: string}[]} items */
export function linksList(items) {
  const ul = document.createElement('ul');
  ul.className = 'panel-links';
  for (const item of items) {
    const link = externalLink(item.href, item.text);
    if (link == null && typeof item.fallback !== 'string') continue;
    const li = document.createElement('li');
    li.appendChild(link ?? document.createTextNode(item.fallback));
    ul.appendChild(li);
  }
  return ul;
}
