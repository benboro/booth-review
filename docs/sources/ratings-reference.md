# Ratings Reference: record format

Ratings Reference publishes about 3,800 college football telecast records at
`https://ratingsreference.com/api/telecast/<id>.json` (there's also an HTML page
at `/telecast/<id>`, meant for people, not for booth-review; we only
read the JSON). Every ID starts with a league prefix (`cfb-` for the ones this
project reads) and ends with the game's date, for example
`cfb-example-state-example-tech-2026-10-03`.

## Finding records

The full list lives in one sitemap, `sitemap-telecasts.xml`. Each `<url>` entry
gives the record's page URL and a `<lastmod>` date — the last time that
record's figures changed, not when it was created. booth-review derives the
JSON URL from the page URL and keeps the fetched `<lastmod>` next to the
record, so a later run can tell whether a record needs re-checking (its terms
allow revisions, so an old figure can be corrected months after a game).
Non-CFB entries (other leagues Ratings Reference also covers) and any entry
without a trailing date are skipped.

## Record shape

Each JSON body has a `telecast` block (id, date, title, the announcing
networks, the participating teams, and a tier/kind classification — tier is
a small integer, not a label) and a `claims` array. A telecast can carry more
than one claim: Ratings Reference records viewership as it's reported, and a
single game is often covered by more than one outlet at different times.

## Claim vocabulary

Across the 2025 season's records, every observed claim carries:

- **`status`**: almost every claim is `"final"`; a `"preliminary"` claim
  (posted before Nielsen's final numbers) is rare but does happen, and gets
  superseded later. Fewer than 1 in 400 claims in the 2025 season were still
  preliminary as of collection.
- **`metric_type`**: every claim observed in 2025 was `"avg_audience"` (an
  average-audience figure for the telecast); the schema also has room for a
  `"peak_audience"` figure, which simply didn't appear in this season's
  sample.
- **`cut`**: always `"full_telecast"` in this sample — no split-window or
  per-quarter figures showed up for 2025 games.
- **`unit`**: always `"viewers"`, ranging from a few thousand for a small
  cable window up to tens of millions for a marquee CFP game.
- **`measured_by`** / **`measurement_method`**: `"nielsen"` for every claim
  observed, with `measurement_method` recorded as `"unspecified"` — Ratings
  Reference doesn't distinguish panel-only from Big Data + Panel at the claim
  level; that distinction lives in `era_id` instead (see below).
- **`era_id`**: tags which Nielsen measurement regime was in effect —
  `nielsen-bd-plus-panel` for most of the season, `nielsen-panel-plus-ooh`
  for the handful of claims that predate the Big Data + Panel switch. This is
  the field this project's era flags key off.
- **`publisher`**: who first reported the figure — a wire service, a
  Wikipedia editor citing a source, or a dedicated ratings blog. A handful of
  named publishers account for nearly all of a season's claims.
- **`source_url`**: present on every claim in the 2025 sample — the original
  article or post the figure came from, separate from the Ratings Reference
  record URL itself.

A record's `model_extra` (fields the schema doesn't pin down as required)
regularly carries a few more useful facts: a `figure_type` tag (Ratings
Reference calls a viewer count a `"currency"` figure), a `figure_scope` and
`platform_scope` (whether the number covers linear only or is left
unstated), a `geo_scope` (`"us"` for everything seen so far), a
`provider_attribution_confidence` tag, and provenance fields (`recorded_at`,
`source_fetched_at`, a content hash, and a short `source_excerpt` quoting the
original figure). None of these are required by the schema, so a future
record could omit any of them.

## Why "most recent" is the wrong rule

**Never pick a telecast's headline figure by taking whichever claim was
`recorded_at` most recently.** A `"preliminary"` figure posted the Monday
after a game can be recorded before a `"final"` figure that corrects it a
week later — recency and correctness aren't the same axis. The rule this
project uses is status first (prefer `"final"` over `"preliminary"`), then a
tie-break within the same status. A record with two or more `avg_audience`
claims is uncommon (well under 5% of a season's records) but real, so the
selection rule has to handle it rather than assume one claim per telecast.

## Composite and MegaCast hazards

`composite_of` and `carrier_network` exist in the schema for exactly the case
this project has to watch for: a title-game or MegaCast figure that combines
viewers across simulcast feeds (a main network plus one or more alt-casts).
Neither field showed up populated in the 2025 sample, but that doesn't mean
every big-game figure is single-network — some combined figures arrive with
both fields left null, inferred only from context (which network the record
lists versus how the figure compares to that network's typical audience).
Treat a suspiciously large figure on a single-network CFP or rivalry game as
worth a second look before crediting it to one crew.

## License and attribution

Ratings Reference publishes under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/): the compilation
and its JSON records can be reused and adapted, including commercially, as
long as attribution is given. This project's attribution, wherever a Ratings
Reference figure appears on the site, is: credit RatingsReference.com by
name, link the specific record the figure came from, cite that figure's own
`source_url` alongside it, and note that the published data has been
modified (joined against other sources, filtered, and re-shaped for the
chart) rather than reproduced as-is.

## NFL records

Ratings Reference also covers the NFL. The Phase 6 spike (October 2026) read
its NFL records by hand to judge whether an NFL module is workable. The
collector still reads CFB only: the sitemap filter keeps paths starting
`/telecast/cfb-`, and NFL entries are skipped until a later build phase adds
an opt-in NFL option.

- **IDs:** `nfl-<team>-<team>-<yyyy-mm-dd>`. The two team words are nicknames
  in alphabetical order, not away then home; the record's title gives the
  away and home teams. A few IDs carry an event word, such as a Christmas
  marker, and a few are non-game specials with no team words at all
  (`nfl-kickoff-<yyyy-mm-dd>`, a Hall of Fame game); those are included in
  the depth counts below. Some Tuesday or Wednesday-dated entries repeat a
  game played a day or two earlier.
- **Depth:** about 95 to 120 NFL telecasts a season from 2014 onward,
  counting playoffs. That covers national windows, primetime and the
  postseason, not every game. Before 2014 there are 2 to 13 entries a
  season, back to 2001. Counted from a locally cached sitemap.
- **How the spike read them:** 14 JSON records, one at a time, 3 seconds
  apart. Each figure was kept with its record URL and its `source_url`
  privately. No figure appears in this repository.
- **No venue, kickoff time or playoff round:** NFL records carry none of these.
  Kickoff, venue and round come from nflverse (see `nflverse.md`). Use a
  record's `networks` with care on regional Sunday games: one record checked
  listed an implausible network.

### Sunday-afternoon figures are window figures

A Sunday-afternoon figure covers a window, not one game.

- **National windows:** claims carry `figure_scope: split_window`, a
  qualitative `market_coverage` text such as "in most markets", and source
  wording along the lines of "<network>'s national window, featuring <game>,
  averaged ...".
- **Regional early-window figures:** worded as regional action featuring a
  game.
- **Inconsistent labels:** some records for the same kind of window say only
  "<game> averaged ..." with `single_window`. The source wording, not the
  scope label alone, is the reliable signal.
- **Standalone games:** primetime, holidays, international mornings and
  playoffs are one game per window, so their figures are per game.
- **No market shares:** no NFL claim read states a percent or count of
  markets.

### Composite and streaming hazards

These extend the CFB MegaCast hazard above.

- **Monday games with an alternate feed:** the final figure is worded as
  covering ABC, ESPN and ESPN2, the channel that carries the ManningCast
  alternate broadcast. Nothing marks it as combined: `composite_of` is
  null, and the separate per-network claims sum to less than the total.
- **Monday doubleheaders:** the final figure is "combined across ABC and
  ESPN", next to a preliminary per-network ESPN claim (`cut: per_network`,
  `carrier_network`).
- **Amazon Thursday games:** Nielsen-measured (`self_reported: false`), with
  `platform_scope` unstated. Nothing says whether local broadcast simulcasts
  in the teams' markets are included.
- **Netflix Christmas games:** tagged Nielsen, but the source wording credits
  the streamer (`press_attributed`). Simulcast inclusion is again unstated.

Other NFL claim fields seen:

- `cut`: `full_telecast`, `window`, `per_network`
- `era_id`: for example a pre-out-of-home panel era for 2015
- `supersedes_id`: for example a network-confirmed figure replacing a press
  figure
- `corroboration`

Preliminary fast-national time-slot lines often sit next to the final figure.
Every NFL figure is used under the same license and attribution rules as
above: credit RatingsReference.com, link the record, cite its `source_url`,
and note the data was modified.
