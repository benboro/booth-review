# Retrosheet: game info and play-by-play

The Phase 7 spike (October 2026) read only Retrosheet's notice, robots file and
download documentation. It downloaded no data file. The field list is in
[mlb-field-list.md](mlb-field-list.md).

## Notice and attribution

The notice allows any use, commercial included, and asks that any transfer or
product built on the data carry a prominent credit. The exact line is quoted
because the notice asks for it: "The information used here was obtained free of
charge from and is copyrighted by Retrosheet." It is followed by "Interested
parties may contact Retrosheet at www.retrosheet.org". The notice places no other
restriction on redistribution or derived works and does not guarantee accuracy.
The terms status is open-attribution.

## Robots

One group for all agents, with no Claude or Anthropic group and no crawl delay.
It disallows `/gamelogs/` and `/boxesetc/`, each also with a leading double-slash
variant. The build must never request those paths.

## Files

Seven master CSV files: all players, game info, team stats, batting, pitching,
fielding and plays, plus packaged sets.

- **Game info** holds the game id, date, doubleheader number, start time, day or
  night, site, both teams, game type, the completion date of a suspended game and
  forfeit data.
- **Plays** holds inning, half, outs, base runners, runs and the running score,
  which is the full game state.
- No file or column carries television, broadcast, network or announcer data,
  and none carries win probability, win expectancy, leverage or win probability
  added.

## Release timing

Releases are twice a year. A season arrives in the release after it ends: 2025
arrived on November 27, 2025, and the August 2026 release still ends at 2025. The
2026 season is pending until a late-2026 release, so 2026 results and
play-by-play have no allowed scripted source until then.

## Win probability

Retrosheet has no win-probability field. The chosen route is our own: derive a
win-expectancy table from Retrosheet's plays game states, then compute
`wp_excitement` (the sum of absolute changes in home win probability across a
game) from it. Published tables are method references only, not field sources.
Pre-game stakes (records and games behind) are derived from game info results.

## Earliest seasons

| item | earliest season |
|---|---|
| Game info (schedule, results) | 1897 |
| Plays (complete play-by-play) | 1908 |
| Measured for game quality | 2017 to 2025 |
| 2026 | pending the late-2026 release |

## Collector route (Phase 9)

`booth-review collect retrosheet` first reads the downloads index (recon,
`--index-only` / `--list-assets`), then fetches only an allow-list: the game info
file, the per-season plays files and the `allplayers` file (added by D-17) under
`/downloads/`. Guards refuse `/gamelogs/` and `/boxesetc/`. A completed season
freezes once collected and checked; later drift in a frozen season is reported,
not silently overwritten (`--refresh` is explicit). 2026 is collected only after
the late-2026 release; an MLB season freezes on March 1 of the next year, so that
release can still be collected for 2026.

Credit line for every page that shows Retrosheet-derived data: "The information used here was obtained free of charge from and is copyrighted by Retrosheet. Interested parties may contact Retrosheet at www.retrosheet.org".

## Columns (recorded from the cached files)

To be filled by plan 09-16 after the first live collection.
