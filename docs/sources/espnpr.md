# ESPN Press Room: hand-saved crews and ratings releases

ESPN Press Room (`espnpressroom.com`) publishes ESPN's college football
announcer schedules and its ratings releases. This project uses it for two
things: a backup crew source for ESPN-family games that have no 506 Sports
crew, and the last-ranked viewership source for 2021–2024 (see
[Known gaps](../known-gaps.md)).

## Access

- The Disney Terms of Use ban automated access, so nothing in this project
  fetches from it. The host is not in the collector allow-list, the importer
  has no network client, and tests check both (`tests/test_config_hosts.py`,
  `tests/test_import_espnpr.py`).
- Its pages are saved by hand in a browser (any filename) into
  `data/incoming/espnpr/`, or copied there with `cp -p`, which keeps each
  file's modified time as its save time.
- It is used without asking first, with credit on every crew and figure, and
  its data comes off the site if ESPN objects (see [Takedown](#takedown)).

## Page kinds

- **Commentators schedule:** one page per season, at
  `https://espnpressroom.com/<yyyy>-<yy>-espn-college-football-commentators-schedule/`.
  It is replaced every Monday and shows only the current week, so a week that
  is not saved that week cannot be recovered from it.
- **Weekly release:** a press release at `/press-release/<slug>/` with the
  week's game-by-game table. Slugs are free text, so a release is found by
  searching the site, not by URL.
- **Ratings release:** a press release with a viewers table, bullet figures
  or figures in its prose.
- **Category listing:** a list of releases, not a data page. The importer
  skips it with a note to open a release from it and save that.

## Import

`booth-review import espnpr [--from <folder>] [--force]` reads every saved
page and writes it into the vault's `raw/espnpr/<season>/`, under
`commentators/wk-<N>.html`, `releases/<slug>.html` or `ratings/<slug>.html`.
It identifies each page by its canonical link and its body class, never by
file name or title, and checks that:

- the file is an HTML page with exactly one canonical link on
  `espnpressroom.com`, and is not an error or challenge page;
- the body class matches the page kind;
- a commentators page names its week, and a release has a published date
  (its season is that year, or the year before for a January to June date);
- no two different files claim the same page, and the season is not frozen.

A re-save with identical bytes is skipped. A re-save that changed needs
`--force`. Like every vault write, the import holds the vault lock and
commits only its own paths. It sends no request.

## Crews

Booths come only from the schedule table on a commentators page or weekly
release. The matchup is the text before the first line break and each later
line is a crew. A `TV:` line wins, `Radio:` lines are dropped, and a row
whose only network is ESPN Radio never becomes a TV booth. Names keep their
printed order: the first is play-by-play, and each later name takes its role
from `data/reference/people.csv`, defaulting to analyst. Trailing names with
no booth role (sideline reporters) are dropped, down to two names.

A booth fills a telecast only when:

- it matches the game by season, both teams through
  `data/reference/team_crosswalk.csv`, and the date within a day;
- its network is the telecast's own network, in the ESPN family;
- the telecast has no hand-confirmed override and no 506 crew.

The order is a hand-confirmed override, then 506 Sports, then ESPN Press Room,
and the whole booth comes from one source. A later 506 crew replaces a backup
crew. When 506 and ESPN Press Room name different people, 506 stays and the
difference goes to a review list. A backup crew never moves the "crews
through week N" stamp, and the coverage table counts backup crews in their
own column.

Past crew gaps on ESPN-family networks are listed by ESPN week in the vault
(`interim/espnpr_backfill_gaps.csv`), so the matching weekly releases can be
looked up and saved by hand. A gap whose release can't be found stays a gap.

## Weekly reminder

The scheduled job never fetches the commentators page. When the vault has no
saved copy of the week the page carries at run time, the job's attention list
names the page and the import command, so the user can save it before the
next Monday's replacement.

## Viewership

Only ratings releases are read for viewership; schedule pages never are.

- A viewers-table row takes its network from the heading above the table.
- A bullet figure needs a lead-in that names one network with no wider scope.
- A figure in the prose loads only when its sentence ties it to exactly one
  named game, as for Awful Announcing (see [aa.md](aa.md)).
- Simulcast and MegaCast totals, window and franchise averages, and
  whole-million figures (too coarse for the 3% check) are left out.
- A number with an unknown suffix, or a row with no clear network, goes to a
  review list instead of loading.

Matching, network holds and the loader's other exclusions are the same as for
Sports Media Watch (see [smw.md](smw.md)).

## Agreement with Ratings Reference

The same 3% gate as Sports Media Watch applies, per season.

| Season | Shared games | Within 3% | Logged | Loaded | Result |
|---|---|---|---|---|---|
| 2024 | 7 | 6 | 1 | 7 | Passed |

No ratings release from 2021, 2022 or 2023 has been saved.

## On the site

ESPN Press Room ranks last, after Ratings Reference, Sports Media Watch, The
TV Ratings Guide and Awful Announcing, so its figure is the headline only when
none of those has a usable figure. No telecast's headline comes from it yet.
When one does, the table's source cell names ESPN Press Room, linked to the
release, and the detail panel says the figure is not listed on Ratings
Reference. A backup crew's detail panel reads "Crew source: ESPN Press Room ↗",
linked to the page the booth came from.

## Storage

The saved pages live only in the private vault, under `raw/espnpr/<season>/`.
They are never copied into this repository, its test fixtures, commit
messages or logs. Tests use synthetic pages.

## Takedown

If ESPN objects, remove `raw/espnpr/<season>/` from the vault for each
season, commit and push the vault, and rebuild. Backup crews go back to "Crew
not listed", and its figures come off the site; it heads no telecast today, so
the rated counts do not change. Crew overrides in
`data/reference/crew_overrides.csv` that cite an ESPN Press Room release are
hand-confirmed rows, not imported pages; they would need another public source
or removal.
