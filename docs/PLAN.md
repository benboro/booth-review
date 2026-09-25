# Who Calls the Best Games? College Football Feasibility Study and Project Plan

Prepared September 24, 2026. No code has been written yet; this document covers scope, sources, risks, and the build plan. Sections 3, 4, 6, 9, 11, 13, and 14 were updated the same day after checking each source's terms, robots.txt, and API limits, and after decisions on hosting, the viewership basis, and in-season updates.

---

## 1. Goal

Build an interactive scatter plot of college football telecasts in which:

- each dot is one game telecast,
- dot color is the network,
- hovering shows the broadcast crew (play-by-play, analyst) and game details,
- a live filter by broadcaster name highlights every game that person called, across networks and seasons,
- the axes combine an audience measure (viewership) and a game-quality measure (excitement index or pre-game expectation).

Longer term: add a toggle for NFL and MLB if their data proves workable.

---

## 2. Conversation Summary

**Starting question.** Is there a single database of every baseball or football game with its broadcasters? No. Coverage exists in pieces that have to be stitched together, and each piece is dense for some eras and thin for others.

**Requirement added.** Announcer names are required, and the analysis needs an audience measure (viewership) and a quality measure (excitement) per game.

**Core design problem identified.** Networks assign their top crews to the biggest games, so average viewership by crew mostly reproduces each network's depth chart. The analogy: ranking restaurant critics by the quality of the restaurants they review measures the editor's assignments, not the critic.

This splits the project into two questions:

| Question | Type | Difficulty |
|---|---|---|
| Who gets the best games? | Descriptive | Easy; the scatter plot answers it directly |
| Which announcers add audience after accounting for the game? | Causal | Hard; needs controls and natural experiments |

**Excitement cannot measure announcer quality.** Announcers do not change win-probability swings, so excitement is useful as a control variable or to describe assignments, not as evidence of skill.

**Visualization decisions made so far:**

- The y-axis should offer a viewership residual (actual minus expected), with raw log viewers as a toggle, because raw viewership mostly separates games by time slot.
- Filtering must work on individual people, not crew strings, so one person's games highlight across networks.
- Unmatched dots fade to low opacity but keep their network color; matched dots get larger with an outline.
- Plan one primary-network rule for simulcasts and streaming, with the full outlet list in the hover.

**Decision.** Start with college football (FBS).

---

## 3. Feasibility Verdict: College Football

**Feasible, and a better starting point than the NFL.** All three required data components have public, game-level sources that overlap from 2013 onward:

| Component | Best source | Coverage | Format | Verdict |
|---|---|---|---|---|
| Announcer names | 506 Sports weekly CFB pages | 2013 to present on the main site; 2009 to 2020 on an older blog | Consistent HTML, one page per week | Strong |
| Viewership | Ratings Reference (aggregates Sports Media Watch and others) | About 3,800 telecasts, Aug 2013 to present | JSON record per telecast; CC BY 4.0 | Good, but only for rated games |
| Game data, lines, excitement | CollegeFootballData.com (CFBD) API | Games 1869+, in-game win probability 2014+, betting lines 2013+ | JSON API, free key | Strong |

**Why college football beats the NFL for this project:**

1. **Per-game viewership.** CFB ratings are published per telecast. NFL Sunday afternoon games are reported as regional windows ("featuring Team A in 44% of markets"), which can't be attributed to one crew.
2. **More crews.** ESPN, FOX, CBS, NBC, and others each run many crews, versus one primetime crew per NFL package.
3. **Natural experiments.** Rights deals moved whole conferences between networks and crews, giving before-and-after comparisons with the same teams (see Section 7).

**Main limitation.** Viewership exists only for games that are Nielsen-rated and publicly reported. Conference networks are not rated at all: ESPN uses ComScore rather than Nielsen for SEC Network, ACC Network, and Longhorn Network, and CBS Sports Network is also not measured. The analyzable sample is therefore mostly games on ABC, ESPN, ESPN2, FOX, FS1, CBS, NBC, and BTN (some BTN and FS1 figures come via Programming Insider).

---

## 4. Source Details

### 4.1 Announcers: 506 Sports

- **URL pattern:** `https://506sports.com/ncaaf.php?yr=YYYY&wk=N`, weeks 0 to 16 plus a bowls and CFP page (`wk=B`).
- **Seasons on the main site:** 2013 to present. The 506 Archive wiki notes a separate blog with listings from 2009 to 2020, including FCS and untelevised games.
- **Fields per game (verified on Week 5, 2025):** matchup with AP rank prefixes, kickoff time (ET), network, and announcers.
- **Format quirks to handle:**
  - Rank numbers are embedded in team names (for example, "8 Florida State @ Virginia"). Strip them, but keep the numbers as a feature, since ranked matchups affect viewership.
  - Most listings name only the booth (two or three people). Sideline reporters are usually not listed.
  - Many ESPN+ and regional games have no announcers listed. That doesn't matter much, because those games also lack viewership data.
  - Neutral-site games use "vs" and home games use "@".
- **Access caveat:** The 506 Archive wiki (older seasons) sits behind a Cloudflare bot check, which blocked automated fetching during this research. The main site loaded normally. For 2009 to 2012, expect manual work or a request to the site owners.
- **Etiquette:** 506 is a small, fan-run site funded partly through Patreon. Scrape slowly, cache pages locally so each is fetched once, and consider contacting them or becoming a patron before bulk collection.
- **Terms (checked September 24, 2026):** the site has no robots.txt (404), and its schedule pages carry no terms or copyright notice. Republishing derived crew data is therefore unresolved; ask the owners.

### 4.2 Viewership: Ratings Reference, Sports Media Watch, and others

**Ratings Reference (ratingsreference.com/league/cfb)** is the primary candidate:

- 3,815 CFB telecasts with published figures, from 2013-08-29 through 2026-09-19.
- Each figure is attributed to its source: about 3,195 via Sports Media Watch, about 380 via On3, about 248 via Wikipedia, plus network PR.
- Telecasts per year are uneven:

| Year | Telecasts | Year | Telecasts |
|---|---|---|---|
| 2013 | 340 | 2020 | 281 |
| 2014 | 342 | 2021 | 157 |
| 2015 | 357 | 2022 | 115 |
| 2016 | 362 | 2023 | 146 |
| 2017 | 350 | 2024 | 167 |
| 2018 | 322 | 2025 | 412 |
| 2019 | 343 | 2026 (partial) | 121 |

  Note that the years are calendar years, so bowl games fall into the following year. The 2021 to 2024 dip is a coverage gap in the aggregator, not a drop in games played; investigate before modeling.
- **Access (checked September 24, 2026):**
  - robots.txt allows all crawlers. The `/bot` page describes the site's own crawler (one request per source at a time with pauses; honors robots.txt and ETag/Last-Modified), which is a good model for ours.
  - Every telecast has a JSON record at `/api/telecast/<id>.json` (for example, `cfb-ohio-state-texas-2026-09-12`). Each figure in it records the value, the Nielsen measurement era (`era_id`, for example `nielsen-bd-plus-panel`), the measurement method, the publisher, the original `source_url`, and a status (`final`, with `supersedes_id` when a figure replaces an earlier one). Use these records instead of scraping the HTML tables.
  - There's no league-wide JSON file. List telecasts from the paginated league pages (`?page=N`) or `sitemap.xml`, then fetch each record once: about 3,800 requests, one time. An RSS feed at `/feed/cfb.xml` may help pick up new records in season (not yet inspected).
- **License:** the compilation and its JSON records are CC BY 4.0. Reuse requires crediting RatingsReference.com and linking each record used, and each figure's original source should be cited alongside. The figures themselves are facts; the license covers the compilation. This means a viewership table derived from Ratings Reference can be published.
- **Still to verify:** spot-check accuracy against Sports Media Watch.

**Sports Media Watch (SMW)** is the upstream source:

- Season pages back to 2012 at `sportsmediawatch.com/college-football-tv-ratings/`.
- **Problem:** weekly figures are published as chart images (PNG), not tables. Using SMW directly means OCR or manual entry, which is why Ratings Reference is the better starting point.
- SMW's written recaps are useful for context flags, such as competing events (a World Series Game 7) and carriage disputes.
- **robots.txt:** allows general crawlers but explicitly blocks scripting tools (`Python-urllib`, `scrapy`, `curl`) and AI crawlers. Don't collect SMW with scripts.
- **Role in this project:** manual only. Spot-check a sample of Ratings Reference figures, note context flags from the recaps, and, if the Phase 3 coverage audit shows the 2021 to 2024 gap matters, consider filling it by hand.

**Supplementary sources:** Wikipedia bowl game pages list the network, full announcer crew (including sidelines), and Nielsen viewers in a structured infobox. They're a good cross-check for postseason games.

### 4.3 Game data and excitement: CollegeFootballData.com (CFBD)

| Dataset | Seasons | Use in this project |
|---|---|---|
| Games (scores, venue, Elo, `excitementIndex`) | 1869 to present | Backbone game table; excitement |
| In-game win probability | 2014 to present | Compute our own excitement index |
| Pregame win probability | 2013 to present | Pre-game expected closeness (x-axis option) |
| Betting lines | 2013 to present | Spread and total as controls |
| Game media (TV outlet) | 2003 to present | Network cross-check against 506 |
| Rankings (AP, CFP) | 1936 / 2014 to present | Ranked-matchup controls |
| Team talent, recruiting | 2015 / 2000 to present | Drawing-power proxies |

- **Access:** a free API key (bearer token). The free tier allows 1,000 requests per calendar month, and creating extra keys to get around the limit is prohibited (from the key's terms). CFBD recommends making all requests server-side, never from a web frontend; this project goes further, and the website never calls the API at all (Section 9).
- **Request budget** (endpoint parameters from the API's OpenAPI spec):

| Data | Endpoint | Calls, 2013 to 2025 |
|---|---|---|
| Games, media, pregame win probability, rankings, talent, betting lines | `/games`, `/games/media`, `/metrics/wp/pregame`, `/rankings`, `/talent`, `/lines` | About one per season each, so roughly 100 (a regular/postseason split may add some) |
| Play-by-play | `/plays` (requires year and week) | About 17 per season, so roughly 220 |
| In-game win probability | `/metrics/wp` (requires a game ID) | One per game: 10,000+, far over budget |

- **Excitement index caveat:** CFBD notes that stored in-game win-probability values from 2025 onward use the current model, and earlier values were not backfilled. That's a model break at 2025. Options:
  1. Use CFBD's `excitementIndex` as-is and add a season fixed effect.
  2. Recompute excitement from play-by-play with one consistent win-probability model (for example, cfbfastR's model), for a uniform definition across seasons. This is preferred if time allows. Under the free tier, this has to start from `/plays` or from play-by-play data the cfbfastR project publishes (check availability), not from the per-game `/metrics/wp` endpoint.
- **Media endpoint caveat:** media records are not available for every game, so treat 506 as the primary network source and CFBD as the cross-check.

---

## 5. Expected Sample and Its Bias

- FBS plays roughly 800+ games per season. Published viewership covers roughly 100 to 400 per season, concentrated on broadcast networks and major cable channels.
- **Implication:** the analysis describes rated national telecasts, not college football broadcasting as a whole. Many conference-network and streaming crews will have few or no rated games.
- **Selection bias to state explicitly:** whether a game gets rated depends on the network, which depends on how attractive the game was expected to be. The sample is not random. The results support within-sample comparisons (among rated games), not claims about all announcers.
- **Mitigation:** keep unrated games in the dataset with excitement and crew data. They can show up on an "assignments" view (excitement or pre-game expectation versus network tier) even without viewership.

---

## 6. Measurement Breaks and Confounders

Build these as explicit flags or era variables. Year-over-year viewership comparisons are skewed without them.

| When | Change | Effect |
|---|---|---|
| Aug 31, 2020 | Nielsen begins including out-of-home viewing | Level shift upward |
| Feb 2025 | Out-of-home measurement expanded to all markets | Further upward shift |
| Sep 2025 | Nielsen "Big Data + Panel" methodology | Generally boosts live sports |
| Aug 31, 2026 | Nielsen adds enhanced co-viewing (passive measurement through wearables) to its currency | Further upward shift, about +4% in February pilots; see the viewership basis option in Section 9 |
| Varies | Some NBC and Peacock figures combine Nielsen and Adobe Analytics | Not comparable to Nielsen-only; flag as a separate measurement type |
| Nov 2025 | Disney networks blacked out on YouTube TV for several weeks | Depressed ABC and ESPN numbers; flag the affected weeks |
| Any week | Competing events (World Series, NFL, other marquee games in the same window) | Include a same-window competition variable |

Ratings Reference tags each figure with a measurement era (`era_id`, for example `nielsen-bd-plus-panel`). In Phase 0, check how its eras line up with the rows above; they may supply most of these flags directly. It had not split out a co-viewing era as of September 2026 (the Sep 12 Ohio State–Texas figure is still tagged `nielsen-bd-plus-panel`), so flag the Aug 31, 2026 change ourselves, by air date.

---

## 7. Analytical Design

### 7.1 Question A (descriptive): who gets the best games?

Plot pre-game expectation (spread, rankings, combined team talent) or realized excitement against raw viewership, colored by network. This shows each network's assignment hierarchy directly and needs no model.

### 7.2 Question B (causal): which announcers add audience?

**Base model (conceptual):**

log(viewers) = crew effect + network effect + time slot + season/era + week
             + team drawing power (both teams) + rankings + pre-game spread
             + same-window competition + measurement-type flags + error

- Report crew effects with uncertainty intervals. Many crews will have too few rated games; set a minimum game count before ranking anyone.
- Model individuals (play-by-play and analyst separately) as well as fixed pairings, since the goal is filtering by person.

**Identification from natural experiments.** This is where college football is strongest. Look for cases where the same teams or conferences get a different crew:

- **Conference rights moves.** The SEC's top game moved from CBS (through the 2023 season) to ABC/ESPN (from 2024). The Big Ten's deal with FOX, CBS, and NBC began in 2023. Same teams, different network and crew, before versus after.
- **Crew moves between networks.** Announcers who switch networks provide person-level comparisons across different game portfolios.
- **Fill-ins and one-off assignments.** When a lead crew is unavailable, the same package slot gets a different crew.

An event study around each change, controlling for matchup quality, is more credible than a single cross-sectional ranking.

### 7.3 Role of excitement

- As a control, realized excitement can explain late-game audience retention, but it's measured after kickoff, so don't use it to explain the decision to tune in.
- Pre-game expectation (spread, rankings) is the correct control for initial tune-in.
- Keep both available as x-axis options in the plot.

---

## 8. Critiques and Responses

| # | Critique | Response |
|---|---|---|
| 1 | The top crews get the top games, so rankings reflect assignment. | Separate Question A from Question B; use natural experiments for B. |
| 2 | Only rated games have viewership, and rating depends on the network. | Report results as within-sample; keep unrated games for the assignment view. |
| 3 | Nielsen methodology changed repeatedly between 2020 and 2026. | Era fixed effects plus measurement-type flags; avoid raw cross-era comparisons. |
| 4 | CFBD's win-probability model changed in 2025 without backfill. | Recompute excitement with one model, or add a season effect and note it. |
| 5 | The 506 Archive is behind a bot check, and 506 is a small fan site. | Start at 2013 (main site); cache everything; contact the owners before bulk pulls. |
| 6 | Ratings Reference is an aggregator with uneven yearly coverage. | Validate a sample against SMW and network PR; investigate the 2021 to 2024 dip. |
| 7 | Team names differ across all three sources. | Build and maintain a team-name crosswalk as a first-class table. |
| 8 | Sideline reporters are rarely listed on 506. | Scope v1 to booth announcers; use Wikipedia infoboxes for postseason sidelines if needed. |
| 9 | Sample sizes per crew may be small. | Minimum-game thresholds, shrinkage (partial pooling) in the model, and intervals on every estimate. |

---

## 9. Visualization Spec (v1)

- **Dots:** one per rated telecast. Unrated games are hidden by default, with an option to show them hollow on the assignment view.
- **X-axis toggle:** realized excitement / pre-game expectation (spread or combined rank).
- **Y-axis toggle:** log viewers / viewership residual from the Section 7.2 model.
- **Viewership basis (back-end option, decided September 24, 2026):** `as_published` is the default and shows each figure as released. `coviewing` puts every game on Nielsen's co-viewing basis: figures for games aired from Aug 31, 2026 stay as published, and earlier figures are scaled up by an estimated co-viewing lift and marked as estimates in the hover. Nielsen publishes one figure per telecast, so no game has both versions (Ratings Reference shows a single figure for Ohio State–Texas, Sep 12, 2026). The lift starts at Nielsen's 4.19% pilot average, which came from marquee February events rather than college football; replace it if a better estimate appears. The basis follows air date, so any 2026 games before Aug 31 stay on the old basis.
- **Color:** primary network, with at most about 8 colorblind-safe colors. Group small outlets as "Other."
- **Hover:** matchup and date, final score, rankings, network and kickoff time, play-by-play and analyst, viewers (with source and measurement type), excitement, residual, and any flags (such as a carriage dispute or a competing event).
- **Filter:** search or multi-select by person. Matched dots are enlarged and outlined; unmatched dots drop to about 15% opacity but keep their color. In compare mode, each selected person gets their own marker shape.
- **Stack (decided September 24, 2026):** Python builds the data: collectors, joins, and the Section 7.2 model, with pathlib for file handling and a small class-based data layer. The front end is a static page using Plotly.js (`scattergl` for performance). Hover details come from Plotly's hover templates, and filters and axis toggles run in browser JavaScript, so no Dash server is needed and the page can live on GitHub Pages. Model outputs such as residuals are computed during the build, not in the browser.
- **Deployment (decided September 24, 2026):** the website serves pre-built data files only. All data is pulled ahead of time, server-side, so viewing the page never sends a request to CFBD or any other source, and the CFBD key never reaches the site.

---

## 10. Data Model

| Table | Grain | Key fields |
|---|---|---|
| `games` | One row per game (CFBD ID) | season, week, date, home, away, neutral site, scores, conferences, excitement, pregame win probability, spread |
| `telecasts` | One row per game per outlet | game_id, network, kickoff time, primary-network flag, source (506 or CFBD) |
| `people` | One row per announcer | person_id, canonical name, name variants |
| `telecast_people` | One row per person per telecast | telecast_id, person_id, role (PBP, analyst, sideline) |
| `viewership` | One row per published figure | telecast_id, viewers, rating, measurement type (Nielsen, Nielsen plus Adobe, etc.), publisher, source URL |
| `team_crosswalk` | One row per name variant | variant, canonical team, source |
| `flags` | One row per game or week event | type (carriage dispute, competing event), date range, affected networks |

The per-person table (`telecast_people`) is what makes filtering work across networks and crew changes.

---

## 11. Build Plan

| Phase | Work | Exit criterion |
|---|---|---|
| 0. Validation spike | One season (2025): pull 506 weeks, Ratings Reference 2025, CFBD games. Join by hand on 20 games. | Join rate measured; list of name-matching problems |
| 1. Ingest | Cached collectors for all three sources, 2013 to 2025 | Raw files stored locally; each page fetched once |
| 2. Clean and join | Team crosswalk, person table, telecast and viewership joins, flags | Over 95% of rated telecasts matched to a game and a crew |
| 3. Coverage audit | Table of season by network by field completeness | Known gaps documented before any modeling |
| 4. Descriptive view | Scatter plot for Question A | Working filter and hover |
| 5. Model | Section 7.2 model plus event studies around conference moves | Crew effects with intervals; residuals feeding the y-axis toggle |
| 6. Toggle prep | Repeat Phase 0 for NFL and MLB | Go or no-go per sport |
| 7. In-season updates | Scheduled job that fetches only the current season (506 week pages, new Ratings Reference records, CFBD data for the week), adds it to the earlier seasons, rebuilds the site data, and publishes it. Runs Sunday for crews, scores, and excitement, and Wednesday for viewership. Can start once Phase 4 works; it doesn't need Phase 5 | A weekend's games appear on the site by Sunday night and their viewership by Wednesday, with no re-fetch of earlier seasons and CFBD use well under the monthly limit |

**Phase 7 notes:**

- **Where it runs:** a scheduled GitHub Actions workflow, the same pattern as terminal-dashboard, pushing the built files to `benboro.github.io`. The CFBD key is an encrypted Actions secret, so requests stay server-side.
- **Earlier seasons:** Actions runners start empty, and GitHub drops cache entries unused for 7 days. The job therefore builds on the previously built data rather than on a raw-page cache; a single cache miss must never trigger a full re-fetch (about 3,800 Ratings Reference requests and 300 CFBD calls).
- **Offseason:** GitHub disables scheduled workflows in public repos after 60 days without a commit. Re-enable the workflow each August.
- **Timing:** 506 posts crews before kickoff; CFBD has scores by Saturday night or Sunday; viewership mostly arrives Tuesday to Wednesday (Ohio State–Texas, Sat Sep 12, 2026, was published Tue Sep 15), and some figures come later or are revised.
- **Prerequisite:** the site's data file publishes joined data, so open question 5 must be settled for CFBD and 506 before the site goes live, in this phase or in Phase 4.

---

## 12. Toggle Feasibility: NFL and MLB (from earlier research)

**NFL: medium.**

- Announcers: 506 Sports weekly listings (national and regional games) and the 506 Archive.
- Excitement: nflverse play-by-play from 1999 with win probability; a game excitement index is straightforward.
- Viewership: clean per-game figures only for primetime, the national late window, and playoffs. Regional afternoon windows can't be attributed to one crew.
- Best identification: crew moves (Romo replacing Simms at CBS in 2017; Buck and Aikman moving to ESPN in 2022; Tirico replacing Michaels on Sunday Night Football).
- To check: whether Ratings Reference covers the NFL at the same depth.

**MLB: weakest.**

- Network data: MLB Stats API (`hydrate=broadcasts`) gives outlets per game but not announcer names.
- Announcers: 506 for national games; local booths only at team-season level (Wikipedia broadcaster lists), with fill-ins lost.
- Viewership: only national telecasts are published. Local regional sports network ratings per game are essentially not public, and most games are local.
- Excitement: computable from Retrosheet event files or MLB win-expectancy data.
- Likely scope if added: national games only, which is a small sample.

**Recommendation:** finish CFB through Phase 5 before starting either toggle.

---

## 13. Open Questions

1. Seasons in scope: 2014 to 2025 (full in-game win probability) or 2013 to 2025 (adds one season but needs our own excitement computation)?
2. FBS only, or include FCS games when they're rated?
3. Primary-network rule for simulcasts (for example, ABC plus ESPN2 or Disney+): first-listed outlet, or rights holder?
4. Include Nielsen plus Adobe figures with a flag, or restrict to Nielsen-only?
5. Terms of use: resolved for Ratings Reference (CC BY 4.0; see Section 4.2). Still open for 506 Sports (no published terms; ask the owners) and for republishing CFBD data, especially its `excitementIndex` (ask CFBD).
6. ~~Front end: Dash, or a static page?~~ Decided: a static Plotly.js page on GitHub Pages (Section 9).
7. Co-viewing lift for the `coviewing` basis: keep Nielsen's 4.19% pilot average, or estimate one from college football data once 2026 figures accumulate? The 2026 era effect in the Section 7.2 model mixes co-viewing with every other change in 2026, so it isn't a clean estimate.

---

## 14. Source Links

- 506 Sports CFB schedule and announcers: https://506sports.com/ncaaf.php
- 506 Archive (older seasons): https://archive.506sports.com/wiki/College_Football
- Ratings Reference, CFB: https://ratingsreference.com/league/cfb
- Ratings Reference methodology and license: https://ratingsreference.com/methodology
- Ratings Reference bot policy: https://ratingsreference.com/bot
- Sports Media Watch CFB ratings: https://www.sportsmediawatch.com/college-football-tv-ratings/
- CFBD API docs: https://api.collegefootballdata.com/
- CFBD data availability: https://api.collegefootballdata.com/data-availability
- CFBD OpenAPI spec: https://api.collegefootballdata.com/api-docs.json
- Nielsen co-viewing enters currency Aug 31, 2026 (Front Office Sports): https://frontofficesports.com/article/nielsen-co-viewing-currency/
- Nielsen co-viewing pilot results: https://www.nielsen.com/insights/2026/nielsen-co-viewing-pilot-delivers-a-4-average-increase-in-total-viewers-for-februarys-live-televised-events/
- cfbfastR (win probability models): https://cfbfastr.sportsdataverse.org/
