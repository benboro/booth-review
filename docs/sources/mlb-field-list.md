# MLB: field list and sources

This is the planned data model for a Major League Baseball module. It comes from
the Phase 7 go/no-go spike (October 2026), which checked each source by hand.
Nothing MLB is collected yet; the build is a later phase. Each row names the
field's source and how it is reached, the earliest season the spike found, its
terms status, and how it changes during a season. No real rows, clubs, games or
people appear here; examples use placeholders.

Terms status uses six values:

- **open-attribution:** CC BY or a stated free-use notice with credit. Credit the source.
- **share-alike:** CC BY-SA.
- **analysis-only:** the terms are unclear. The field is used in analysis but not
  displayed; only our own derived values from it reach the site (see Display rule).
- **blocked:** the terms ban reuse, bulk use or automated collection, or require
  prior written authorization, so that source can't supply the field until
  permission exists in writing.
- **derived:** our own computed value.
- **none-found:** no source found.

## Tasks

The spike judged five tasks, each go or no-go on its own, and the overall call is
go when any task is go.

- **task_scatter:** for national telecasts of own or unknown production (regular
  season and postseason), plot the game-quality measure against the crew, so
  that the crew's pull can be read beyond what the matchup predicts.
- **task_exposure:** count, per team and season, the regular-season national
  games, by default only those that are exclusive (no local telecast), with
  all national games reported alongside.
- **task_topcrew:** for one network at a time, compare its lead (A) booth with
  its other booths over the same season. A network passes only when it has two
  or more booths and enough games for each.
- **task_postseason:** the same crew view for the postseason, using a round,
  league and outlet map stored per season as data.
- **task_local:** name the local television crew of each game for all 30 clubs.

A game is national when a national outlet carries it: a broadcast or cable
network, a streaming service reaching viewers across the country, or the league's
own network. A local regional network, a team network, a local over-the-air
station, MLB.TV and other out-of-market packages are not national.

## Fields

| field | definition | source | earliest season | terms status | updates in season | derivation |
|---|---|---|---|---|---|---|
| `season` | Season year | Retrosheet game info, scripted download in the build; 2026 from the hand-saved 506 weekly pages until Retrosheet's late-2026 release | 1897 (game info); measured 2017 on | open-attribution (Retrosheet, credit line required; 2026 rows read from 506 are analysis-only) | fixed once the schedule is out | copied from the date |
| `game_date` | Date of the game | Retrosheet game info, scripted; 2026 from the 506 weekly pages | 1897 (game info) | open-attribution (Retrosheet; 2026 506 rows analysis-only) | can change after a postponement; 506 pages change through the week | copied |
| `game_number` | Game 1 or 2 of a same-day doubleheader, 0 otherwise | Retrosheet game info (`number`); 506 page notes for 2026 | 1897 (game info) | open-attribution (Retrosheet; 2026 506 rows analysis-only) | fixed | copied; a game is keyed by date, both teams and game number |
| `home_team` | Home club, or the listed home club at a neutral or foreign site | Retrosheet game info, scripted; 506 listing for 2026; names resolved through `data/reference/` crosswalks | 1897 (game info) | open-attribution (Retrosheet; 2026 506 rows analysis-only) | fixed | copied, then crosswalked |
| `away_team` | Away club | Retrosheet game info, scripted; 506 listing for 2026; crosswalked | 1897 (game info) | open-attribution (Retrosheet; 2026 506 rows analysis-only) | fixed | copied, then crosswalked |
| `venue_country` | Country of the site, descriptive only | Retrosheet game info site code plus 506's "in City" site note | 1897 (game info) | derived | fixed | site mapped to a country; never changes the listed home club |
| `is_postseason` | Game belongs to the postseason | Retrosheet game info (`gametype`); 506 round pages | 1897 (game info) | derived | postseason games are added as rounds are set | true when the game type is a postseason type |
| `round` | Wild card, division, league championship, World Series, or tiebreak | Wikipedia postseason articles and the wild card broadcasters list, hand-read; 506 round pages | 2012 (the wild card list); 506 round pages saved for 2025 and 2026 only | share-alike (Wikipedia, CC BY-SA 4.0) | added as rounds are set | copied; stored per season as data |
| `series_league` | League of a division or league-championship series | Wikipedia postseason articles, hand-read | 2012 (the wild card list); maps built for 2025 and 2026 | share-alike (Wikipedia, CC BY-SA 4.0) | added as series are set | copied; the league-to-network split changes between seasons, so it is data |
| `resumed_date` | Completion date of a suspended game | Retrosheet game info (`suspend`), scripted | 1897 (game info) | open-attribution (Retrosheet) | 2026 resumptions have no allowed source until the late-2026 release | copied; the game keeps its original date |
| `is_national` | A national outlet carries the game | derived from `network` under the national-game rule | 2026 regular season and 2025 postseason measured; 506 offers pages back to 2014 but only those seasons were read | derived | 506 weekly pages change through the week | true when the outlet is on the national list |
| `network` | Main-feed national outlet or streaming service | 506 MLB pages, hand-save (2026 weekly pages list every national game with outlet; 2025 postseason round pages); Ratings Reference only for rated games | 2026 regular season and 2025 postseason read; 506 offers 2014 on, kinds unverified | analysis-only (506 states no terms) | 506 pages change through the week; save after games finish | normalized: trailing star removed, sister outlets and regional tails dropped |
| `window` | Fox Saturday regional window marker | 506 map-marker note in the outlet cell | 2026 (2025 pages are coverage maps without an outlet cell) | analysis-only (506 states no terms) | changes through the week | copied from the marker note |
| `is_exclusive` | No local telecast of the game exists (the national outlet is exclusive; local carriage is blacked out) | 506 star mark (a starred listing means the national telecast is blacked out in the teams' areas, where the local network airs the game, so it is not exclusive); package wording from Wikipedia and network releases | 2026 regular season, 2025 postseason (package wording) | analysis-only (506 states no terms; Wikipedia wording is share-alike) | 506 pages change through the week | false when starred or a regional network is named; true only on stated package exclusivity; null otherwise, never guessed |
| `production` | Own, simulcast of a local feed, or unknown | 506 star and crew cell, with Wikipedia and league page wording | 2026 regular season, 2025 postseason | analysis-only (506 states no terms) | as for `network` | starred listings with no crew read as simulcast; a named crew reads as own; no wording reads as unknown |
| `play_by_play` | Main-feed play-by-play voice | 506 MLB pages, hand-save; for listings with no crew, the fan schedule blog under Secondary crew source; Wikipedia season lists only as pairings, never game assignments | 2026 regular season, 2025 postseason | analysis-only (506 states no terms) | assignments change through the week; save pages after games finish | first name in the crew cell; people resolved through `data/reference/` |
| `analyst_1` | First analyst | 506 MLB pages, hand-save | 2026 regular season, 2025 postseason | analysis-only (506 states no terms) | as for `play_by_play` | second name in the crew cell |
| `analyst_2` | Second analyst, stored and not required | 506 MLB pages, hand-save | 2026 regular season, 2025 postseason | analysis-only (506 states no terms) | as for `play_by_play` | third name in the crew cell, or n/a |
| `crew_scope` | How the crew is tied to the game | derived from the source kind | 2026 regular season, 2025 postseason | derived | recomputed with the crew | per-game, single-booth-package, season-pairing or none |
| `booth_key` | A booth: play-by-play voice plus network plus season | derived | 2026 regular season, 2025 postseason | derived | recomputed with the crew | analyst changes do not split a booth; a one-off fill-in voice joins the booth its source places it in |
| `is_a_booth` | The network's lead booth | Wikipedia current-season national list (lead marker), hand-read; network releases where read | 2026 (current list); 2025 for some networks | derived (from share-alike Wikipedia markers) | changes when a network revises its lead | lead marker, else first-listed pairing, else the booth on the highest postseason round; unidentified blocks task_topcrew for that network |
| `alt_cast_broadcasts` | Child rows for alternate feeds, each with its own crew | none found: 506 MLB pages list no alternate feeds; the alternate-game listing for blacked-out areas is a different game, not a feed | none found | none-found | n/a | one child row per alternate feed once a source is found |
| `local_crew` | Local television crew of the game | none found: no source names a per-game local crew for any club | none found | none-found | n/a | n/a |
| `viewership` | Average audience in viewers, with Nielsen era tag | Ratings Reference JSON records, scripted through `booth-review collect` once a league option exists | 2002 for postseason records; 2017 for regular-season records | open-attribution (RR compilation CC BY 4.0; figures credited to their publishers) | finals replace preliminary figures; sitemap lastmod drives re-checks | RR's current figure, era-tagged per docs/PLAN.md section 6 |
| `viewership_label` | Whether a figure is per-game, window-level, composite or unnormalized | derived from the record's claim wording | same as `viewership` | derived | recomputed with the figure | per-game when the record names that game; window-level for regionalized windows; composite when feeds are summed |
| `wp_excitement` | Sum of absolute changes in home win probability across a game | derived by us from Retrosheet play-by-play with our own win-expectancy table | 1908 (complete play-by-play); measured 2017 to 2025; 2026 pending | derived | 2026 pending until Retrosheet's late-2026 release | table built from Retrosheet game states, then summed per game |
| `pregame_stakes` | Each team's record, games behind in its division and games behind the last wild-card spot | derived by us from game results through the previous day | 1897 (game info); measured 2017 to 2025; 2026 pending | derived | 2026 pending (no allowed scripted 2026 results source) | cumulative results from Retrosheet game info |
| `moneyline` | Pre-game betting line | none found: only unverified leads | none found | none-found | n/a | unavailable |
| `national_games_per_team` | National games per team and season, exclusive by default | derived from `is_national` and `is_exclusive` | 2026 | derived | grows weekly | count; the null-exclusivity count is reported beside it |
| `local_viewership` | Per-game local audience | none found: only team-season household ratings | none found | none-found | n/a | n/a |

## Rules

- **National game:** a national outlet carries it. A game carried by two outlets
  of one family (for example a network with its cable or streaming sister) is
  one telecast under its main outlet. A regionalized window gives one telecast
  per game, each with its own booth. A national outlet's simulcast of a local
  feed stays a row, with production marked simulcast.
- **Production:** own (the outlet's own booth), simulcast (the outlet carries a
  club's local feed and crew) or unknown. With no wording it is unknown, never
  assumed from the outlet.
- **Exclusive:** true when a source states the telecast or its package is
  exclusive; false when a source shows local carriage of the same game (a starred
  506 listing, or a listing naming a regional network); null otherwise. The
  exposure count uses true only and reports the null count.
- **Crew named:** a telecast counts when its source names a play-by-play voice and
  at least one analyst. TBA, an empty crew or a single name is a miss.
- **Crew scope:** per-game when the source ties the people to that game, its
  date or its series; single-booth-package when one booth is stated to call every
  game of a package; season-pairing otherwise. Coverage counts the first two.
  The per-game-only and loose (adds season pairings) counts are shown, and only
  the user can accept a looser count.
- **Booth and A booth:** a booth is a play-by-play voice plus network plus season.
  The A booth is the network's own lead marker, else the first-listed pairing,
  else the booth on its highest postseason round.
- **Slate complete:** every game of a package is listed in a slate source and the
  found count equals any stated count. A short count or a package with no list
  makes the slate incomplete.
- **Game quality:** passes when win-probability excitement or pre-game stakes is
  available for 2017 to 2025 from sources whose terms allow analysis.
- **Task bars:** coverage of at least 95.0% with a complete slate for the crew
  checks; at least 90.0% of sampled games for the local sample; at least 10
  telecasts for each of a network's A booth and one other booth.
- **Viewership label:** per-game, window-level, composite, unnormalized or none,
  taken from the record's wording; it never decides a verdict.

## Edge cases

- **Local-feed simulcast:** "Club A at Club B" on the league's network, starred,
  with no crew. Production simulcast, exclusive false, outside every crew
  denominator, counted in the all-national exposure count.
- **Showcase game:** a starred league-network listing that names a crew is the
  network's own production.
- **Regional network on a national game:** a starred cable listing naming a crew
  stays in the scatter subset as own production; exclusive is false.
- **Doubleheader:** "Club A at Club B" twice on one date at different times. The
  later listing is game 2. Ratings Reference slugs carry no game number, so two
  entries on such a date stay ambiguous until a text source ties them.
- **Suspended game:** the game keeps its original date with the resumption date
  stored; 506 has no such field, so a 2026 resumption needs another source.
- **New-outlet wild card round:** the round comes from the page, the outlet from
  the listing with its sister outlet dropped, production own.
- **Spanish feed of the final series:** not on the saved page; it would be a
  child row with its own crew, outside every denominator.
- **Game abroad:** "Club A vs Club B (in a foreign city)". The listed order is
  kept; the site note is stored as venue, descriptive only. Domestic neutral
  sites work the same way.
- **Streaming exclusive:** a streaming service's own production with a named booth
  stays exclusive-null at game scope unless a source states exclusivity.

## Alt-casts and streaming

- **One row per game and national outlet.** Alternate casts are child rows with
  their own crew, described by outlet and kind, and sit outside every denominator.
- **Streaming exclusives:** streaming services are simply `network` values.
  Starred streaming-package listings are local-feed simulcasts, on 506's own
  week-1 labels and the league network's description.
- **Combined figures:** Ratings Reference figures that may combine feeds get the
  same check as the college-football MegaCast hazard. Every composite finding
  (`rr_composite:` in the spike) came back unclear: platform scope was unstated,
  and in one case two final claims disagreed. Streaming figures are measured by
  Nielsen but do not say whether local simulcasts are included.

## Postseason

Postseason games are included by default in the scatter and top-crew views, each
flagged with its round. The round, league and outlet map is stored per season as
data, never as a fixed rule, because the league-to-network split flips between
seasons.

- **2025:** the wild card round on one sports network and its broadcast sister,
  the American League division and league series on one broadcast network's
  family, the National League ones on a cable network's family, and the World
  Series on the broadcast network. 47 games (11, 18, 11 and 7 by round).
- **2026 (in progress when read):** the wild card on a new broadcast network with
  a streaming service, the American League series on the cable network's family,
  the National League series on the broadcast network's family, and the World
  Series on the broadcast network.

## Season range and the current season

- **task_scatter, task_exposure, task_topcrew:** the planned range is 2017 to
  2026, but the per-game crew and outlet source, the 506 full-schedule weekly
  pages, starts in 2026, so the supported range is 2026 only.
- **task_postseason:** 2014 to 2026. 506 offers 2014 on and the wild card list
  names booths back to 2012; only 2025 and 2026 round maps were built.
- **task_local:** n/a.
- **Sources:** Retrosheet game info from 1897 and play-by-play from 1908 (2026
  pending the late-2026 release); Ratings Reference regular-season records from
  2017 and postseason records from 2002; Wikipedia crew lists from 1990.

2026 is the current season: it is re-checked, not frozen. Under a bar-season
amendment of 2026-10-10, chosen by the user after seeing the evidence, the
national crew bars are measured on the 2026 regular season plus the 2025
postseason (the original bar season was 2025, where 506 holds only Fox Saturday
coverage maps for the regular season). task_postseason stays on 2025.

A 2025 back-check, shown for context and never deciding, found that outside the
postseason and a few Fox Saturday games, 2025 regular-season crews exist only as
season pairings. A 2025 back-fill of per-game crews therefore has no source, and
2017 to 2024 crews have none either.

## Secondary crew source

Where a 506 listing names no crew, the spike filled it from a fan-run schedule
blog that keeps per-game national crew lists for each network
(<https://tamirmoore.blogspot.com/>, for example its "2026 MLB on Apple TV
schedule" post). It is a secondary source: each list credits the network press
page it was copied from (Apple Newsroom, ESPN Press Room, Fox Sports Press Pass,
Warner Bros. Discovery). The blog states no terms of its own, but its lists relay
press pages that are blocked (Apple's site terms bar copying and public display)
or failed the policy screen (Fox Sports Press Pass, Warner Bros. Discovery); only
the ESPN list relays an analysis-only host. The spike used these crews once,
hand-read, for analysis only; they are not displayed. Any reuse needs its own
robots and terms check, a HOST_POLICIES entry and a new owner decision. In the
spike it agreed with 506 on every game where both name a crew that was checked.
Cite the blog together with the press page it credits.

## Display rule

Analysis-only fields are used in analysis but not displayed, and only our own
derived values from them reach the site. Open-attribution and share-alike fields
may be displayed. Blocked fields are not used until permission exists in
writing. Each displayed source gets its credit: Retrosheet's credit line ("The
information used here was obtained free of charge from and is copyrighted by
Retrosheet."), Ratings Reference with record links and original publishers, and
Wikipedia under CC BY-SA.

The analysis-only fields are `network`, `window`, `is_exclusive`, `production`,
`play_by_play`, `analyst_1` and `analyst_2` (506 states no terms). The blocked
group is the Stats API (see mlb-statsapi.md): analysis use only, never displayed,
and MLB has not granted written permission. No field row depends on it yet.

**Open question for the build:** the college-football site already displays 506
crews (hover details), even though 506 states no terms and its publishing row in
`data/README.md` still reads "ask the site owners". MLB crew views need crew
names, and most of these crews come from 506. Before MLB views are built, decide
whether MLB crews follow that college-football precedent or the strict rule above.
Asking 506's owners would settle both. Apple TV+, the only network that passes top
crew, takes 30 of its 50 crews from the relay under Secondary crew source, which
the 506 precedent does not cover. Display of the relayed crews and of Stats API
fields is an open question for the build; until it is settled they stay
analysis-only.
