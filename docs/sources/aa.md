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

## Crew posts (2026)

For the 2026 college football season only, `booth-review collect aa --crews`
fetches the weekly announcing-schedule posts and the build reads their crews.

- **URLs:** only the week links recorded in `ledger/aa_feed_watch.json`, on the
  AA host. The command never takes a URL argument.
- **When:** the Tuesday reminder run fetches a post the first time it finds it.
  Conditional re-checks (ETag / Last-Modified) run Friday 18:00 and Saturday
  08:00 ET, since AA edits a post through Saturday. They only re-check a post
  that is already cached (an uncached post is skipped, with a reminder line),
  and each slot sends at most one request: the slot is recorded in
  `ledger/aa_feed_watch.json` (`crews_rechecked`), so a backup or manual run in
  the same slot sends none. `--week N` re-checks an already-recorded week by hand.
- **Cap:** at most 2 AA requests per run (the feed and the post; the robots.txt
  check before them is not counted), at least 3 s apart, with the project user agent
  and robots.txt. A request that fails is never retried.
- **Gate:** an AA policy check from the last 30 days with confirmed terms. When
  it is stale, the run skips the fetch and says so in the reminder.
- **Cache:** `raw/aa/crews/2026/wk-NN.html` in the private vault.
- **Parser:** one line per game, shaped like
  `Away at Home (time, Network): Name (play-by-play), Name (analyst), Name (reporter)`.
  Reporters are dropped, `TBD` is counted, and a line that does not parse is
  counted, never guessed. A game line above every recognised day header counts as
  unparsed, and a post with no booth while it has unparsed game lines (or with no
  day header at all) fails validation, so it is never cached as a good page.

Coalescing with 506, in order, per game and network:

1. A `crew_overrides.csv` row wins, whatever its status (one equal to 506's crew
   included).
2. A lone source fills.
3. The same people from both, or an AA booth whose people are all in 506's crew
   (AA drops reporters 506 may list): 506's crew and attribution are kept
   (corroborated), with no review row.
4. AA lists every person 506 lists, plus more: AA's whole booth fills (D-04), with
   a review row `relation=superset`.
5. Any other difference goes to the newer page (D-02): 506's manifest `saved_at`
   (else `fetched_at`) against AA's `article:modified_time` (else the fetch time of
   the last HTTP 200 line). A tie keeps 506. Each such case writes a row to
   `interim/review_crew_aa_disagreements.csv`; the build never fails over it.
6. ESPN Press Room fills only what is still blank.

AA crews never move the "crews through week N" stamp, and the coverage table
counts them in their own column (`matched_crew_aa`), never as 506 matches. Each
crew is credited to its exact post, and AA's crews come down if AA objects.

## Storage

The cached sitemaps and posts live only in the private vault, under `raw/aa/`.
They are never copied into this repository, its test fixtures, commit messages
or logs. Tests use synthetic pages.

## Takedown

If Awful Announcing objects, remove `raw/aa/` from the vault, commit and push
the vault, and rebuild. It heads no telecast today, so the rated counts do not
change.
