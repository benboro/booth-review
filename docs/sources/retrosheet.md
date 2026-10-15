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

Recorded 2026-10-14 from the twelve cached season bundles (2014-2025, one `<year>csvs.zip` per season). The index offers no separate gameinfo, allplayers or plays assets, so each bundle is the only unit collected. Header lines were read locally; the header is identical across all twelve seasons for every file.

Members of each bundle (`<year>` prefix): `allplayers.csv`, `batting.csv`, `fielding.csv`, `gameinfo.csv`, `pitching.csv`, `plays.csv`, `teamstats.csv`.

- `gameinfo.csv`: gid, visteam, hometeam, site, date, number, starttime, daynight, innings, tiebreaker, usedh, htbf, timeofgame, attendance, fieldcond, precip, sky, temp, winddir, windspeed, oscorer, forfeit, suspend, umphome, ump1b, ump2b, ump3b, umplf, umprf, wp, lp, save, gametype, vruns, hruns, wteam, lteam, line, batteries, lineups, box, pbp, season.
- `allplayers.csv`: id, last, first, bat, throw, team, g, g_p, g_sp, g_rp, g_c, g_1b, g_2b, g_3b, g_ss, g_lf, g_cf, g_rf, g_of, g_dh, g_ph, g_pr, first_g, last_g.
- `batting.csv`: gid, id, team, b_lp, b_seq, stattype, b_pa, b_ab, b_r, b_h, b_d, b_t, b_hr, b_rbi, b_sh, b_sf, b_hbp, b_w, b_iw, b_k, b_sb, b_cs, b_gdp, b_xi, b_roe, dh, ph, pr, date, number, site, vishome, opp, win, loss, tie, gametype, box, pbp.
- `fielding.csv`: gid, id, team, d_seq, d_pos, stattype, d_ifouts, d_po, d_a, d_e, d_dp, d_tp, d_pb, d_wp, d_sb, d_cs, d_gs, date, number, site, vishome, opp, win, loss, tie, gametype, box, pbp.
- `pitching.csv`: gid, id, team, p_seq, stattype, p_ipouts, p_noout, p_bfp, p_h, p_d, p_t, p_hr, p_r, p_er, p_w, p_iw, p_k, p_hbp, p_wp, p_bk, p_sh, p_sf, p_sb, p_cs, p_pb, wp, lp, save, p_gs, p_gf, p_cg, date, number, site, vishome, opp, win, loss, tie, gametype, box, pbp.
- `teamstats.csv`: gid, team, inn1 to inn28, lob, mgr, stattype, the b_, p_ and d_ team totals, start_l1 to start_l9 (starting batting order), start_f1 to start_f10 (starting fielders), date, number, site, vishome, opp, win, loss, tie, gametype, box, pbp.
- `plays.csv` (one row per play): gid, event, inning, top_bot, vis_home, site, batteam, pitteam, score_v, score_h, batter, pitcher, lp, bat_f, bathand, pithand, balls, strikes, count, pitches, nump, pa, ab, the outcome flags (single, double, triple, hr, sh, sf, hbp, walk, k, and so on), outs_pre, outs_post, br1_pre to br3_post (base runners before and after), run and rbi columns, l1 to l9 (batting order ids), lf1 to lf9 (batting order fielding positions), f2 to f9 (fielders by position), po0 to po9, a1 to a9, fseq, loc, hittype, pn, umphome to umprf, date, gametype, pbp.

`gametype` values across 2014-2025 `gameinfo.csv`: `regular`, `allstar`, `wildcard`, `divisionseries`, `lcs`, `worldseries`, `playoff` (`playoff` is rare, two games across all twelve seasons; not a modeled round unless a later plan decides otherwise). Values are words, not numeric codes.

Score columns are pre-play: in a count-only check of the first play of 3,001 sampled games (mostly 2014 plus the first game of later sampled seasons), none had a nonzero `score_v` or `score_h`. Running scores after a play are the next row's scores or `score + runs`.

Lineup slot, fielding position and pinch flags exist: `batting.csv` has `b_lp` (lineup position) and `b_seq` (sequence within the slot), plus `ph` and `pr` flags and `dh`; `fielding.csv` has `d_pos` (position) and `d_seq`; `plays.csv` has `lp` and `bat_f` for the batter and `l1`-`l9`/`lf1`-`lf9` for the lineup state.
