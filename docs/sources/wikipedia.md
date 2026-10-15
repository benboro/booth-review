# Wikipedia: NFL season scheduling changes

Wikipedia's NFL season articles list in-season scheduling changes (flexes,
cross-flexes, network moves). They are the only scripted source for a game's
original slot and network, 2014 to 2026. Planned fields are in
[nfl-field-list.md](nfl-field-list.md).

## Access

- Only the plain article page `https://en.wikipedia.org/wiki/<year>_NFL_season`
  is requested, through `booth-review collect wikipedia`. One request per
  season.
- The `/w/` and `/api/` paths are disallowed by robots.txt and are never used.
- Every request goes through the shared transport: the project user agent
  (which satisfies the Wikimedia user-agent policy), robots.txt checks
  including wildcard rules, a minimum interval of 2 seconds, and the raw cache.

## What is read

Only the scheduling-changes lists under "Regular season". The parser keeps the
week, the two team names as written, the original day, time (ET) and network,
and the new network or slot wording. Venue relocations are counted and
dropped. A bullet the parser cannot read cleanly goes to an unparsed list,
which is written to a private vault review file, never guessed at.

## Cadence

- 2014 to 2025: collected once, checked, then frozen like the CFB seasons
  (freeze key `nfl_wikipedia`).
- 2026: re-read by the scheduled job with conditional requests (ETag and
  Last-Modified).

## Storage

The cached article HTML lives in the private vault only. Downstream tables
hold extracted facts only (week, team pair, original slot and network), each
row carrying the article URL.

## Credit and license

Article text is licensed
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), which is
share-alike; the field list records how that affects published rows. The
NFL site shows `original_slot`, `original_network` and the change article link in the detail panel, with a CC BY-SA 4.0 notice in the footer, the panel and `docs/nfl-data.md` (999.5 D-23).

## MLB pages (Phase 9)

`booth-review collect wikipedia --league mlb` reads plain `/wiki/<title>` pages
only: the "<year> Major League Baseball postseason" articles from 2014 (13 season
articles) and the named broadcaster list pages. It extracts rounds, series
leagues, outlets and lead-booth markers; nothing else is kept. Text is CC BY-SA
4.0, so published rows carry the article URL and the share-alike notice, and the
cached HTML stays in the private vault.

