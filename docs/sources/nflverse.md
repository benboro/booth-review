# nflverse: schedules and play-by-play

nflverse is an open-source project that publishes NFL schedules and
play-by-play data, with win probability. It is the planned source for the
NFL schedule, kickoff times, scores, spreads and in-game win probability.
The Phase 6 spike (October 2026) read only nflverse's documentation,
licenses and data dictionaries; it downloaded no nflverse data, and
collection is a later build phase. The planned fields are listed in
[nfl-field-list.md](nfl-field-list.md).

## License and terms

- **The data is CC BY 4.0, the code is separate:** the data repository that
  publishes the release files (nflverse-data) is labeled
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The R and Python
  packages that load it carry their own code licenses.
- **Attribution:** CC BY 4.0 asks for credit, a link to the license, and a
  note of any changes. This project would credit nflverse wherever a derived
  value from it appears.
- **Third-party carve-out:** CC BY 4.0 grants only rights the licensor holds.
  The schedules are compiled by a maintainer and the play-by-play is built
  from the league's game feed, so not every value is nflverse's own.
- **Terms status by field group** (under this project's rule for unclear
  terms):
  - **Schedules (dates, kickoff times, teams, scores):** open-attribution.
    These are facts, compiled under CC BY.
  - **Odds columns:** analysis-only. Their provenance is not stated.
  - **Play-by-play, including win probability:** analysis-only. Only derived
    values, such as an excitement score, reach the site.

## Schedules

One row per game:

- `game_id`, plus the league's own game IDs
- `season`: January games carry the previous season's year
- `game_type`: `REG`, `WC`, `DIV`, `CON` or `SB`
- `week`: weeks 18 and later need `game_type` to tell regular season from
  playoffs
- `gameday`, `weekday`
- `gametime`: kickoff in 24-hour Eastern time for every venue, international
  games included
- `away_team`, `home_team`: at a neutral site, `home_team` is the designated
  home team
- `away_score`, `home_score`, `result` (home minus away), `total`, `overtime`
- `location`: `Home` or `Neutral`
- `stadium`, `stadium_id`, `roof`, `surface`
- rest days, starting quarterbacks, coaches, and the referee

The schedules carry **no network or broadcaster field**. The network comes
from 506 Sports (hand-saved week pages) and, for national games, from Ratings
Reference.

## Spread and odds

- **`spread_line`:** the point spread, positive when the home team is
  favored. It lines up with `result`.
- **Related columns:** `total_line`, the two moneylines, and the odds on each
  side of the spread and the total.
- **Provenance not stated:** the current dictionaries name no sportsbook and
  no capture time.
  - An older changelog of the play-by-play package called its copy of the
    spread the closing line, sourced from Pro-Football-Reference.
  - One third-party note suggests the newest season may come from a
    different feed.
- **Status:** analysis-only, used only as a game-quality control.

## Original schedule and flexes

nflverse keeps no record of the schedule as first released. No field marks a
flexed game, an original slot, or an original network, and a moved game simply
shows its new date and time. The compiled games file's git history might hold
earlier versions, but GitHub's robots rules disallow its commit-list pages,
and a clone would be a data download, so that lead was not used. Original
slots and networks come from Wikipedia's per-season scheduling-changes lists
instead.

## Play-by-play and win probability

Play-by-play has one row per play. Its game-level fields repeat
`game_date`, `start_time` (Eastern), `stadium` and `location`. Win-probability
fields:

- `wp` and `def_wp`: the possession and defensive team's win probability at
  the start of the play
- `home_wp`, `away_wp`, and the end-of-play `home_wp_post` and `away_wp_post`
- `vegas_wp` and `vegas_home_wp`: the same, adjusted with the pre-game line
- `wpa`, `vegas_wpa`, `vegas_home_wpa`: win probability added on the play,
  plus air and yards-after-catch splits

The planned `excitement_score` and `wp_volatility` would both be computed from
`home_wp` across a game's plays. Only those derived values would be shown.

## Earliest seasons

| field group | earliest season |
|---|---|
| Schedules (games, kickoff, teams, scores) | 2006 |
| Spread and odds | 2006 (the start of the games file; per-season odds coverage not stated) |
| Play-by-play | 1999 |
| Win probability | 1999 |

The NFL module targets 2014 to 2026, which every group covers.

## Updates in season

- **Schedules:** refresh every few minutes during the season, so flexes and
  time changes appear quickly.
- **Play-by-play:** builds nightly after game days, with extra runs on game
  days (usually within about 15 minutes of a game ending). Stat corrections
  are picked up midweek.
- **2026:** the current season, re-checked and not frozen, like the CFB
  sources.

## Access route (999.4, D-21)

- **Schedules:** `https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv`,
  one file for all seasons, refreshed with conditional requests.
- **Play-by-play:** through the GitHub REST API, never a release-download link.
  `GET /repos/nflverse/nflverse-data/releases/tags/pbp` gives the release id;
  `GET /releases/{id}/assets?per_page=100&page=N` lists its files (at most 10
  pages); `GET /releases/assets/{asset_id}` with `Accept: application/octet-stream`
  returns a redirect to a signed asset host, which the client follows. Both API
  calls send `Accept: application/vnd.github+json` and
  `X-GitHub-Api-Version: 2022-11-28`.
- **Why not github.com:** `github.com/robots.txt` disallows `/*/download`, and the
  client now enforces wildcard rules, so release-download URLs are refused.
- **Token:** an optional `GITHUB_TOKEN` is sent to api.github.com only, never to
  raw.githubusercontent.com, and is dropped on the redirect.
- **Downloaded bytes** must match the listing size and start and end with the
  parquet magic bytes `PAR1`; otherwise nothing is ledgered and the next run
  downloads again.

## Change detection

The listing's `updated_at` and `size` for each `play_by_play_<season>.parquet`
are compared with the latest line for that file in the vault ledger
`ledger/nfl_nflverse_assets.jsonl` (name, asset_id, size, updated_at, sha256,
recorded_at). A season is downloaded only when the cached file is missing or
either value changed. Asset ids may change on a re-upload, so the name is the
key. Frozen seasons are never re-downloaded.

## Volume

About 19 MB of parquet per season, about 245 MB for 2014-2026. The 2026 season
is downloaded again only when its listing changed, and only on the Wednesday and
Thursday job runs.

## Excitement (GEI-style, D-22)

`excitement_score = (3600 / t) x sum of the absolute per-play changes in home win
probability`, where `t` is the game's seconds, overtime included. It is labeled
GEI-style: comparable in kind to CFBD's unpublished `excitementIndex`, not
identical to it. `wp_volatility` is the sample standard deviation of the same
per-play changes and is a separate field.

## Credit

nflverse-data is CC BY 4.0; credit nflverse wherever a derived value appears.
`spread_line` and play-by-play provenance are analysis-only, per the
[field list](nfl-field-list.md).
