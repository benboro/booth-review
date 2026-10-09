# NFL special games: field list and sources

This is the planned data model for the NFL special-games module. It comes from
the Phase 6 go/no-go spike (October 2026), which checked each source by hand. Nothing NFL is collected
yet; the build is a later phase. Each row names the field's source and how it
is reached, the earliest season the spike found, its terms status, and how it
changes during a season.

Terms status uses five values:

- **open-attribution:** CC BY or similar. Credit the source.
- **share-alike:** CC BY-SA.
- **analysis-only:** the terms are unclear. The field is used in analysis but
  never displayed, and only our own derived values reach the site.
- **blocked:** the terms ban reuse or automated access, so that source can't
  supply the field.
- **derived:** our own computed value.

## Fields

| field | definition | source | earliest season | terms status | updates in season | derivation |
|---|---|---|---|---|---|---|
| `season` | NFL season year; January games belong to the previous season | nflverse schedules (`season`), scripted download in the build | 2006 (the schedules file) | open-attribution (nflverse-data, CC BY 4.0) | fixed once the schedule is out | copied |
| `week` | Regular-season week 1 to 18 | nflverse schedules (`week` with `game_type`), scripted | 2006 | open-attribution (nflverse-data, CC BY 4.0) | fixed | copied |
| `game_date` | Date of the game in Eastern time | nflverse schedules (`gameday`), scripted | 2006 | open-attribution (nflverse-data, CC BY 4.0) | can change after a flex or a weather move; the schedules file refreshes every few minutes | copied |
| `kickoff_time_et` | Scheduled kickoff, 24-hour Eastern time for every venue | nflverse schedules (`gametime`), scripted | 2006 | open-attribution (nflverse-data, CC BY 4.0) | changes with flexes; refreshed every few minutes | copied |
| `home_team` | Home team, or the designated home team at a neutral site | nflverse schedules (`home_team`), scripted; names resolved through `data/reference/` crosswalks | 2006 | open-attribution (nflverse-data, CC BY 4.0) | fixed | copied, then crosswalked |
| `away_team` | Away team | nflverse schedules (`away_team`), scripted; crosswalked | 2006 | open-attribution (nflverse-data, CC BY 4.0) | fixed | copied, then crosswalked |
| `game_type` | Regular season or a playoff round | nflverse schedules (`game_type`: REG, WC, DIV, CON, SB), scripted | 2006 | open-attribution (nflverse-data, CC BY 4.0) | playoff games are added as rounds are set | copied |
| `network` | Main-feed network or streaming service | 506 Sports NFL week pages, hand-save (every game); Ratings Reference records for national games, scripted | 2025 evidenced on 506 (earlier seasons not yet checked); RR 2014 for national games | analysis-only (506 states no terms; RR's national-game networks are open-attribution) | 506 week pages change through the week; RR records follow sitemap lastmod | copied; RR's network on regional records is not trusted alone |
| `broadcast_team` | Main-feed crew: play-by-play first, then analyst, then sideline | 506 Sports NFL week pages, hand-save; Wikipedia season pairings as a weak backup | 2025 evidenced on 506 | analysis-only (506 states no terms; the Wikipedia backup is share-alike) | assignments change through the week; save pages after games finish | split on commas; people resolved through `data/reference/` |
| `alt_cast_broadcasts` | Child broadcast rows for alternate feeds of the same game, each with its own crew | none found: 506 NFL pages list no alt-casts; RR mentions them only in claim wording | none found | open-attribution (RR claim wording, the only trace) | n/a | one child row per alt-cast once a source is found |
| `is_standalone` | No other NFL game kicks off within 3 hours | derived from `game_date` and `kickoff_time_et` | 2006 | derived | recomputed when kickoffs change | absolute gap of 3:00 or less to any other kickoff fails |
| `slot_name` | Display label: Christmas, Thanksgiving, Black Friday, International, TNF, SNF, MNF, Saturday, Friday, Sunday early, Sunday late, Other | derived from date, kickoff and venue | 2006 | derived | recomputed when kickoffs change | first matching label in the order listed under Rules |
| `is_agotw` | Fox's late national game on a Fox doubleheader Sunday | derived from 506 (network and window) plus a text source to break ties (RR's late-window record, 506 page text) | 2025 evidenced | derived | settles once the late-window record exists | see Rules; `ambiguous` when no text source picks one game |
| `is_cbs_national` | CBS's late national game on a CBS doubleheader Sunday | derived the same way as `is_agotw` | 2025 evidenced | derived | as for `is_agotw` | see Rules |
| `is_international` | Venue outside the United States | derived from nflverse `location` and `stadium` plus 506's "(in City)" note | 2006 | derived | fixed | stadium mapped to a country |
| `flexed` | Moved after the schedule release into a standalone slot or the Fox or CBS late national game | derived from `original_slot` | 2014 (seasons checked) | derived | set when a move is announced | see Rules |
| `original_slot` | Slot as first released, kept for every move | Wikipedia season articles, scheduling-changes section, scripted read of public pages; league schedule releases as a lead | 2014 (2014, 2018, 2022 and 2025 checked) | share-alike (Wikipedia, CC BY-SA 4.0) | added as moves are announced | copied; sometimes missing for afternoon moves |
| `original_network` | Network as first released, kept for every move including CBS and Fox cross-flexes | Wikipedia season articles, as for `original_slot` | 2014 (seasons checked) | share-alike (Wikipedia, CC BY-SA 4.0) | added as moves are announced | copied; often omitted when the network did not change |
| `is_special` | Rollup: standalone, AGOTW or CBS late national | derived | 2006 | derived | recomputed | see Rules |
| `fox_doubleheader_weeks` | Count of Fox doubleheader Sundays per season | derived from 506 network and window (kickoffs from nflverse in the build) | 2025 evidenced | derived | grows weekly | see Rules |
| `cbs_doubleheader_weeks` | Count of CBS doubleheader Sundays per season | derived as for Fox | 2025 evidenced | derived | grows weekly | see Rules |
| `viewership` | Average audience in viewers, with Nielsen era tag | Ratings Reference JSON records, scripted through `booth-review collect` | 2014 (sparse from 2001) | open-attribution (RR compilation CC BY 4.0; figures credited to their publishers) | finals replace preliminary figures; sitemap lastmod drives re-checks | RR's current figure; Sunday-afternoon figures are window-level, labeled by the featured game |
| `coverage_share` | Share of US markets or households that received the game | none found for 2025; a third-party schedule site states per-game household shares for 2026 only, with no stated source | none found | analysis-only (third-party lead with unread terms; map images are never used) | the lead site changes weekly | not derived; Task 1 viewership is labeled window-level |
| `excitement_score` | Game excitement from in-game win probability | derived from nflverse play-by-play win probability | 1999 | derived | nightly after games | computed from `home_wp` per play |
| `pregame_spread` | Pre-game point spread, positive when home is favored | nflverse schedules (`spread_line`), scripted | 2006 | analysis-only (odds provenance unstated) | can move until kickoff | copied, used only for game-quality controls |
| `final_margin` | Home score minus away score | derived from nflverse schedules (`result`) | 2006 | derived | after the game | copied as computed |
| `wp_volatility` | How much win probability swung during the game | derived from nflverse play-by-play win probability | 1999 | derived | nightly after games | spread of per-play `home_wp` changes |

## Rules

- **Standalone:** a game is standalone when no other NFL game kicks off within
  three hours of it. A gap of exactly 3:00 or less fails. The rule uses the
  combined date and kickoff time only, with no hardcoded exceptions. Monday
  doubleheader games fail but keep the label MNF. A 9:30 ET Sunday
  international game passes. International games in the 1 pm and 4 pm windows
  fail and are flagged international only.
- **Slot name:** a display label only, never used to decide standalone. The
  first match wins, in this order:
  - Christmas (December 25)
  - Thanksgiving (the fourth Thursday of November)
  - Black Friday (the day after)
  - International: outside the US with a kickoff before noon ET, or a Friday
    game outside the US
  - TNF (Thursday, 7 pm or later)
  - SNF (Sunday, 7 pm or later)
  - MNF (Monday)
  - Saturday
  - Friday
  - Sunday early (before 3 pm)
  - Sunday late
  - Other
- **Doubleheader week:** a network has a doubleheader on a regular-season
  Sunday when it carries a game at the 4:25 ET late national kickoff
  (4:15-4:35) and at least one 1:00 ET game that day. Both networks can have
  one on the same Sunday. A Saturday doubleheader is not a Sunday doubleheader.
- **AGOTW:** on a Fox doubleheader Sunday, the Fox 4:25 game when it is the only
  one. When several share that kickoff, it is the one a text source names as
  the national game: RR's late-window record for that date, 506 page text, or
  Fox's announced list. It is never chosen by crew or by map image. Otherwise
  the week is ambiguous.
- **CBS late national:** the same rule for CBS on a CBS doubleheader Sunday.
- **Is special:** standalone, AGOTW or CBS late national. International and
  flexed are descriptive and never make a game special on their own.
  Regular season only unless the playoffs toggle includes them.
- **Flexed:** true when a game moved after the schedule release into SNF, MNF or
  TNF, or into the AGOTW or CBS late national game. The original slot and
  network are kept for every move, including 1:00 to 4:25 moves and CBS-Fox
  cross-flexes, even when flexed is false.

## Edge cases

- **Monday doubleheader:** Team A at Team B at 7:15 pm ET and Team C at Team D
  at 8:15 pm ET, on two networks. Both are 60 minutes apart, so neither is
  standalone. Both keep slot name MNF. A 7:00 and 10:00 pair is exactly three
  hours apart and also fails.
- **Thanksgiving:** three games at 1:00, 4:30 and 8:00 pm ET on three networks.
  Each gap is 3:30, so all three are standalone with slot name Thanksgiving.
- **Saturday tripleheader:** late-December Saturday games at 1:00, 4:30 and
  8:00 pm ET. The gaps are 3:30, so all three pass. The 2025 season had
  Saturday doubleheaders only (about 4:30 or 5:00 then 8:00 or 8:20), and those
  pass too.
- **Christmas on a streamer:** a Thursday Christmas with two streaming-exclusive
  games at 1:00 and 4:30 pm ET and a streaming night game. All are standalone
  with slot name Christmas, and the streaming service is the network value.
- **9:30 ET international:** Team A vs. Team B in Europe on Sunday at 9:30 am ET
  on a cable network. The next kickoff is 1:00 pm, a gap of 3:30, so it is
  standalone with slot name International and the international flag set.
- **Friday in Brazil:** an opening-week Friday night game in Sao Paulo on a
  streaming service. It is standalone, and its slot name is International.
- **Cross-flex:** a 1:00 pm game moved from CBS to Fox. It is not standalone and
  not flexed. The original slot (Sunday early) and original network (CBS) are
  kept.
- **Flex into SNF:** a 1:00 pm CBS game moved to Sunday night. It is standalone
  and flexed, with original slot Sunday early and original network CBS. The
  displaced night game moves to the afternoon, and its original slot is kept
  where the source states it.

## Alt-casts and streaming

- **One row per game.** `network` and `broadcast_team` describe the main feed.
- **Alt-casts:** an alternate feed with its own crew, such as an ESPN2
  alternate broadcast of a Monday game, is a child broadcast row with its own
  crew. The 2025 506 NFL pages list no alt-casts, so this needs another source.
- **Streaming exclusives:** Prime Video, Netflix, YouTube, Peacock and ESPN+
  are simply `network` values.
- **Combined figures:** Ratings Reference figures that combine feeds get the
  same check as the college-football MegaCast hazard. The 2025 Monday figures
  checked combine ABC, ESPN and the ESPN2 alternate feed, and
  `composite_of` doesn't mark it. Whether streaming figures include local
  broadcast simulcasts in the teams' markets is not recorded.

## Playoffs

Regular season only by default. Playoff games, identified by nflverse
`game_type`, are included only when the playoffs config toggle is on, for
special-game counts and for the AGOTW comparison alike.

## Season range and the current season

Both tasks target the 2014 to 2026 seasons. Earliest seasons found per source:

- nflverse schedules: 2006.
- nflverse play-by-play and win probability: 1999.
- Ratings Reference NFL records: about 95 to 120 a season from 2014, sparse
  before.
- Wikipedia scheduling changes: 2014 at least.
- 506 NFL week pages: 2025 evidenced. Earlier seasons sit behind 506's archive,
  which still has to be checked by hand.

2026 is the current season. It is re-checked, not frozen. Sources that update
during a season:

- nflverse schedules: every few minutes.
- nflverse play-by-play: nightly after game days.
- 506 week pages: through each week; save them after games finish.
- Ratings Reference: preliminary figures are replaced by finals, and sitemap
  lastmod drives re-checks.
- Wikipedia: scheduling changes as moves are announced.

## Display rule

Analysis-only fields are used in analysis and never displayed. Only our own
derived values reach the site, and each displayed source gets its credit:
nflverse, Ratings Reference with record links and original publishers, and
Wikipedia under CC BY-SA.

The analysis-only fields are:

- `network` and `broadcast_team` (506 states no terms; the same status as its
  college-football pages until the site owners are asked)
- `coverage_share` (only a lead with unread terms)
- `pregame_spread` (odds provenance unstated)
