# The TV Ratings Guide: 2021–2024 daily ratings posts

The TV Ratings Guide (`www.thetvratingsguide.com`) publishes daily ratings
posts: a cable post listing the night's top cable programs, and a broadcast
post listing the primetime shows on the broadcast networks. College football
games appear in both as table rows. Each post has its own page, so a figure is
credited with a link to the exact post it came from.

This project reads it only for the 2021–2024 games that Ratings Reference and
Sports Media Watch leave unrated (see [Known gaps](../known-gaps.md)).

## Access

- `booth-review collect tvrg --season <year>` is the only way it is fetched.
  Requests carry the standard user agent, honor robots.txt, go one at a time
  at least 3 seconds apart, and are cached in the private vault, so a cached
  page is never fetched again.
- Before any data pass, `booth-review collect tvrg --policy-check` re-reads
  robots.txt and the site's front page, then logs the result in the vault's
  policy ledger. `--confirm-terms` records that the user read the current
  terms and that they allow collection. A data pass runs only while the
  newest ledger line is at most 30 days old and both checks passed.
- If robots.txt or the terms now ban automated access, collection stops. A
  data pass also re-reads robots.txt, and a disallowed path or a Crawl-delay
  longer than 3 seconds stops the run before any page is fetched.
- Each run is capped (`--max-requests`, default 150). `--dry-run` prints the
  planned counts and sends no request.
- As re-checked on 2026-10-13, its robots.txt allows every path and sets no
  Crawl-delay, and it has no terms page; the footer carries a copyright
  notice. It is used without asking first, with credit on every figure, and
  its figures come off the site if it objects (see [Takedown](#takedown)).

## What is collected

Only dates that still have an unrated game on ABC, CBS, NBC, FOX, ESPN, ESPN2
or FS1 are collected. The collector reads the monthly archive pages for those
months, then the ratings posts dated within a day of such a date. The 2021
season was first collected for every unrated date; it filled no gap, because
the posts never list the conference-network, ESPNU, CBSSN or streaming games
that make up most of what is left. The other seasons were then limited to
those seven networks.

## What the parser keeps

Columns are found by their header text, so cable and broadcast posts parse
the same way. A row becomes a figure only when its show reads
`<label> Football: <away> v. <home>` and the label is not a pro, high-school
or fantasy league. Viewers are printed in millions with two decimals.

- A football row with no game (a studio show, a weather delay) is not a
  figure.
- Reruns and other shows are ignored.
- A cell with no number ("TBA", blank) has no figure.
- A number with any unknown trailing text goes to a review list instead of
  loading.
- Two networks in one cell (a simulcast total) are never a figure.

Team names are short forms, matched through `data/reference/team_crosswalk.csv`.
A short form that fits more than one school is a candidate set, narrowed by
the date and opponent. Matching, network holds and the loader's exclusions
are the same as for Sports Media Watch (see [smw.md](smw.md)).

## Agreement with Ratings Reference

The same 3% gate as Sports Media Watch applies, per season.

| Season | Shared games | Within 3% | Logged | Loaded | Result |
|---|---|---|---|---|---|
| 2021 | 58 | 58 | 0 | 139 | Passed |
| 2022 | 5 | 5 | 0 | 35 | Passed |
| 2023 | 5 | 5 | 0 | 18 | Passed |
| 2024 | 12 | 12 | 0 | 30 | Passed |

## On the site

The order is Ratings Reference, Sports Media Watch, The TV Ratings Guide, so a
figure from it is the headline only when neither ranks above it with a usable
figure. That is 16 telecasts: 3 in 2022 and 13 in 2023. The table's source
cell names The TV Ratings Guide, linked to the post. The detail panel adds
"View original source (The TV Ratings Guide) ↗" and says the figure was read
from its ratings post and is not listed on Ratings Reference. The panel shows
"Measurement not recorded", because the posts don't say how figures were
measured.

## Storage

The cached archive pages and posts live only in the private vault, under
`raw/tvrg/`. They are never copied into this repository, its test fixtures,
commit messages or logs. Tests use synthetic pages.

## Takedown

If The TV Ratings Guide objects, remove `raw/tvrg/` from the vault, commit and
push the vault, and rebuild. If the regression guard blocks the build, accept
the new baseline with `booth-review build --accept-baseline`. Its 16 headline
games go back to the "No public rating" strip.
