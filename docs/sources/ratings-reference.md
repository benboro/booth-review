# Ratings Reference: record format

Ratings Reference publishes about 3,800 college football telecast records at
`https://ratingsreference.com/telecast/<id>.json` (there's also an HTML page at
the same path without `.json`, meant for people, not for booth-review; we only
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
