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
  If that request fails, the week is recorded in `ledger/aa_feed_watch.json`
  (`crews_failed`), and the 22:30 backup and later Tuesday runs do not send it
  again; they say so in a reminder line.
  Conditional re-checks (ETag / Last-Modified) run Friday 18:00 and Saturday
  08:00 ET, since AA edits a post through Saturday. They only re-check a post
  that is already cached and has a stored ETag or Last-Modified (otherwise the
  run sends nothing and says so in a reminder line, so a re-check is never a plain
  request), and each slot sends at most one request: the slot is recorded in
  `ledger/aa_feed_watch.json` (`crews_rechecked`), so a backup or manual run in
  the same slot sends none. `--week N` re-checks an already-recorded week by hand.
- **Cap:** at most 2 AA requests per run (the feed and the post; the robots.txt
  check before them is not counted), at least 3 s apart, with the project user agent
  and robots.txt. A request that fails is never retried, and a redirect is never
  followed: a 3xx answer counts as the request and fails, so a run sends exactly
  the requests it counts and only to the recorded links. This applies to every
  awfulannouncing.com request, the 2021-2024 ratings pass included.
- **Gate:** an AA policy check from the last 30 days with confirmed terms. When
  it is stale, the run skips the fetch and says so in the reminder.
- **Cache:** `raw/aa/crews/2026/wk-NN.html` in the private vault. A 304 that
  omits a validator keeps the one stored before it, so the next re-check still
  sends it.
- **Parser:** one line per game, shaped like
  `Away at Home (time, Network): Name (play-by-play), Name (analyst), Name (reporter)`.
  Reporters are dropped, `TBD` is counted, and a line that does not parse is
  counted, never guessed. A `TBD` or `TBA` name is never a person: it is dropped
  from the booth, and a booth with no named play-by-play counts as TBD. A day
  header starts with a weekday ("Saturday, November 7", optionally with a year);
  January to May dates fall in the season's next year. A game line above every
  recognised day header, or under a weekday heading that does not parse, counts as
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

An AA fill (506 listed no crew) never moves the "crews through week N" stamp;
a 506 crew that AA's booth replaced still does, since 506 listed it. The coverage table
counts them in their own column (`matched_crew_aa`), never as 506 matches. Each
crew is credited to its exact post, and AA's crews come down if AA objects.

## Hand-saved posts (`booth-review import aa`)

`booth-review import aa [--from <folder>] [--force]` brings weekly
announcing-schedule posts saved by hand in a browser (default folder
`data/incoming/aa/`, any filename) into the vault. It sends no request.

- **Identification:** by content, never by file name. The canonical link must be
  an AA post under `/college-football/` or `/nfl/` whose slug or title says
  "announcing schedule" (fill-in news articles are ignored). The week number comes
  from the title, else the slug; the season from the year there, else the
  published date. Only 2026 is imported.
- **Checks:** the post must pass the crews parser above, and most of its dated
  game lines must fall in that week of the vault's schedule (CFBD for college
  football, nflverse for the NFL). A college football post the feed watch recorded
  under a different link that week is refused.
- **Paths:** college football posts go to `raw/aa/crews/2026/wk-NN.html` (the
  fetch's path) and NFL posts to `raw/nfl/aa/crews/2026/wk-NN.html`. The manifest
  line is marked `origin: manual` with the browser save time, which the build
  compares against 506 when the post carries no `article:modified_time`.
- **The job:** a hand-saved copy has no ETag or Last-Modified of its own. One that
  replaces a fetched copy (`--force`) keeps that copy's validators, so a re-check
  that gets a 304 means AA has not changed the post since that fetch. The Tuesday
  run fetches its own copy of a college football week over a hand import, and the
  Friday and Saturday re-checks then have validators to send. The job never fetches
  NFL posts.
- **Overwrites:** a vault copy that differs is left alone when it is at least as
  new as the save (reported as `vault_newer`, no complaint); otherwise it is kept
  unless `--force`. Two different saves of one week are both refused unless
  `--force`, which keeps the newest.

## NFL crews (2026)

The NFL build (`booth-review nfl build`, `nfl/crew_aa.py`) reads the imported NFL
posts and coalesces them with 506 by the same rules as college football, per
game:

1. A game 506 gave no booth (no listing, no resolved play-by-play voice, or a
   published-lineup fill) takes AA's booth; 506's later names that resolved stay.
   A published lineup fills only a game neither source names.
2. AA's people equal to, or all within, 506's crew (play-by-play, analyst and the
   later names, which can be a third booth member): 506 is kept (an agreement).
3. AA's people a strict superset of 506's crew: AA's whole booth wins.
4. Otherwise the newer page wins (AA's `article:modified_time`, else its save or
   fetch time, against the 506 page's save time); a tie keeps 506. Each
   superset or newer-page case writes a row to `interim/review_nfl_crew_aa.csv`
   (person ids only). When AA wins, its whole booth ships and none of 506's names
   stay.

Upcoming games follow the same rules, write their disagreements to the same file
(marked `upcoming`), and their booth rank follows the shipped play-by-play voice.
Two AA lines that match one game (an alt-cast or a corrected line) drop that game,
whether or not their names resolve. AA-sourced games vote in lead-booth inference and the modal
analyst like 506 games. Matching uses the team pair (through the `any` rows of
`nfl_team_crosswalk.csv`) and the game date. A booth is used only when every name
is in `people.csv`: the NFL build never adds people, so `booth-review nfl people`
lists AA's names with 506's and `--apply` registers them. The NFL site credits an
AA crew "Crew source: Awful Announcing" (upcoming: "Crew from Awful Announcing")
with a link to the post.

## Storage

The cached sitemaps and posts live only in the private vault, under `raw/aa/`
and `raw/nfl/aa/`.
They are never copied into this repository, its test fixtures, commit messages
or logs. Tests use synthetic pages.

## Takedown

If Awful Announcing objects, remove `raw/aa/` and `raw/nfl/aa/` from the vault,
commit and push the vault, and rebuild (`booth-review build` and
`booth-review nfl build`). It heads no telecast today, so the rated counts do not
change.
