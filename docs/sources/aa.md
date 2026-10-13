# Awful Announcing: 2021–2024 ratings posts

Awful Announcing (`awfulannouncing.com`) writes sports media news, including
posts on college football viewership. The posts are prose: figures appear in
sentences, next to peaks, streaming numbers and comparisons with other games
and seasons. Each post has its own page, so a figure is credited with a link to
the exact post it came from.

This project reads it only for the 2021–2024 games that Ratings Reference,
Sports Media Watch and The TV Ratings Guide leave unrated (see
[Known gaps](../known-gaps.md)).

## Access

- `booth-review collect aa --season <year>` is the only way it is fetched.
  Requests carry the standard user agent, honor robots.txt, go one at a time
  at least 3 seconds apart, and are cached in the private vault, so a cached
  page is never fetched again.
- Before any data pass, `booth-review collect aa --policy-check` re-reads
  robots.txt and the site's disclaimer, then logs the result in the vault's
  policy ledger. `--confirm-terms` records that the user read the current
  terms and that they allow collection. A data pass runs only while the
  newest ledger line is at most 30 days old and both checks passed.
- If robots.txt or the terms now ban automated access, collection stops. A
  data pass also re-reads robots.txt, and a disallowed path or a Crawl-delay
  longer than 3 seconds stops the run before any page is fetched.
- Each run is capped (`--max-requests`, default 150). `--dry-run` prints the
  planned counts and sends no request.
- As re-checked on 2026-10-13, its robots.txt disallows only a few old
  archive-index paths and sets no Crawl-delay, and its disclaimer has no
  clause on automated access. It is used without asking first, with credit on
  every figure, and its figures come off the site if it objects (see
  [Takedown](#takedown)).

## What is collected

Only regular-season dates that still have an unrated game on ABC, CBS, NBC,
FOX, ESPN, ESPN2 or FS1 are collected. The collector reads the sitemap index,
then only the post sitemaps that span those weeks, then the college football
ratings posts whose slug names a gap week or, with no week in the slug, whose
sitemap date falls within a week after a gap date. Posts about other leagues
are skipped.

## What the parser keeps

The parser loads a figure only when one sentence ties it to exactly one named
game, in a fixed form such as "<game> averaged <figure> viewers on
<network>". It never guesses.

- Peaks, streaming-only numbers and figures inside an embedded post are
  ignored.
- A sentence that refers to another season or to a multi-game total
  ("combined", "doubleheader", "window") is not a figure.
- Every other mention is counted on the gate line as unlinked prose and is not
  loaded. These mentions carry no figure for a single game.
- A sentence that names no network leaves the network blank, and the row goes
  to review.

The game is dated from the post's publish date in ET: a weekday named in the
sentence dates it to the latest such day before the post, and otherwise to the
latest Saturday before it. Team names are matched through
`data/reference/team_crosswalk.csv`. Matching, network holds and the loader's
exclusions are the same as for Sports Media Watch (see [smw.md](smw.md)).

## Agreement with Ratings Reference

The same 3% gate as Sports Media Watch applies, per season.

| Season | Shared games | Within 3% | Loaded | Unlinked prose | Result |
|---|---|---|---|---|---|
| 2023 | 1 | 1 | 1 | 26 | Passed |
| 2024 | 0 | 0 | 0 | 43 | No shared games |

For 2021 the collector read one post sitemap and found no post for the
season's one gap date; 2022 had no gap date on those networks. Neither season
has a gate line.

## On the site

The order is Ratings Reference, Sports Media Watch, The TV Ratings Guide,
Awful Announcing, so a figure from it is the headline only when none of those
has a usable figure. No telecast's headline comes from it yet. When one does,
the table's source cell names Awful Announcing, linked to the post, and the
detail panel adds "View original source (Awful Announcing) ↗" and says the
figure was read from its ratings post and is not listed on Ratings Reference.

## Storage

The cached sitemaps and posts live only in the private vault, under `raw/aa/`.
They are never copied into this repository, its test fixtures, commit messages
or logs. Tests use synthetic pages.

## Takedown

If Awful Announcing objects, remove `raw/aa/` from the vault, commit and push
the vault, and rebuild. It heads no telecast today, so the rated counts do not
change.
