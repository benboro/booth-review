# Methodology

This page explains what the chart on this site can and cannot say, in plain
language. It covers what is plotted, why the sample is not a random sample of
college football, how measurement changed over the years in scope, what
the x-axis options mean, and where the
figures on the chart come from.

## What this chart shows

Each dot is one rated national telecast of an FBS college football game, from
the 2014 season onward. The y-axis is viewers, on a log scale, and can show excitement, total points or winning margin instead (see [the y-axis section](#the-y-axis-viewers-excitement-points-or-margin)). The x-axis
defaults to the winner's closing point spread (see below) and can be toggled
to CFBD's post-game excitement measure or to the game's date instead. Dots are colored by network family —
for example, the Disney family groups ABC and the ESPN networks under one
color — but the specific network that carried a telecast is always named in
the hover, the detail panel, and the matched-games table. No dot is ever
colored by an individual announcer or crew.

A dot's tooltip is kept short: the matchup and final score, the date and
kickoff time, the named game (the bowl, rivalry, or playoff round, with its icon) on its own line,
the networks, the crew, and the viewer count. Click or tap the
dot to open its detail panel, which also has the measurement label, both
x-axis values, any flags, and, for a Saturday game, its time slot.

## Assignments, not quality

The single most important thing to understand before reading anything into
this chart: **a person's dots show what game they were assigned to call, not
how good they are at calling it, and not whether they personally drew
viewers.** Networks put their most experienced crews on the games they
already expect to draw the largest audience — the marquee matchup, the
rivalry game, the playoff game. A crew with dots skewed toward large audiences
is evidence the network trusted them with big assignments; it is not evidence
that audience showed up *because* of them.

Because of this, the chart deliberately shows no averages, no rankings, and
no leaderboards of any kind. There is no view on this site, now or planned
for this release, that orders announcers by viewership. Separating "who
gets the best games" (an assignment question, which this
chart answers directly) from "which announcers add audience beyond what the
matchup already predicts" (a causal question, which needs a model that
controls for matchup quality, network, time slot, and era) is the whole point
of this page's warning. The causal question is out of scope for this release
and is planned as a future model-driven milestone, not part of this chart.

The Bars and Butterfly views count assignments, not quality. Every bar is a number of games, never a viewer figure, and announcers are never ranked by audience. Bars are ordered by how many games an announcer, team, network family, or conference has in the current filters, which is a count of assignments, not a ranking of skill. In a stacked bar a game counts once for every announcer (or team) in it, so a bar can be longer than its number of games. Solid parts of a bar are rated games and outlined parts are games with no public rating. One announcer's (or team's) parts stay together in a stacked bar. In a network family bar, the networks named on the family's legend chip take the chip's color and then its shades, in the order the chip lists them (for example ABC, then ESPN), and any other channels follow, most games first.

## Which games are included

A game is in scope if at least one participating team was FBS that season —
a rated FBS-versus-FCS opener counts, but two non-FBS teams playing each
other does not. Only **rated** telecasts appear as dots: a telecast needs a
viewership figure this project could attach to it. Unrated games (mostly
smaller conference-network and streaming-only broadcasts) are not shown in
v1, even though their game and crew data still exists behind the scenes.

Each dot is one main-feed figure. When a game aired on more than one outlet
at once (a simulcast), it is still one dot, credited to the game's primary
rights-holder network; every outlet that carried it is listed in the hover
and detail panel. A combined figure — one viewership number that spans a
main broadcast plus one or more alternate-feed broadcasts, most often seen on
marquee postseason games with a companion "alt-cast" — is also one dot,
credited to the main booth. The people who called an alt-cast feed on a
combined figure are still linked to that dot and still match a person search
(labelled "alt-cast" in the table and detail panel), but they never match a
play-by-play or analyst role filter, since that filter is scoped to the
main-feed booth. A Spanish-language broadcast's own figure, and an
alt-cast-only feed's own figure when it is not part of a combined figure, are
kept in this project's data but are not plotted as their own dots in v1.

Kickoff time slots, used by the kickoff-time filter and shown in a Saturday
game's detail panel, are defined as: **noon** (before 2:00 PM ET),
**afternoon** (2:00 PM up to but not including 6:00 PM ET), **prime time**
(6:00 PM up to but not including 10:00 PM ET), and **after dark** (10:00 PM
ET or later, including kickoffs after midnight).

## How filters display

By default a filter fades the games it excludes instead of removing them: the
faded dots keep their network color, so the rest of the field stays visible as
context. The Hide switch at the end of the network legend row removes them
instead. The Networks filter, set from the legend chips or the Networks menu,
works the same way: games on networks that are switched off fade, or disappear with Hide on. With an announcer selected, their games are drawn at full
strength, other games that pass the filters are partly transparent, and games
that fail a filter are fainter still. The summary line and the Bars and
Butterfly charts count only the games that pass every filter, whether the
excluded games are faded or hidden. The per-season counts in the Seasons filter
apply every filter except the season range itself, so seasons outside the range
keep their counts. The matched-games table fills once an announcer, a school, or a named game is selected,
and lists the games that pass every filter. Double-clicking (or double-tapping) a network pill shows only that network family, the same as Networks > Only; doing it again on the only family showing brings all networks back. With exactly two schools selected, Head-to-head keeps only the games between them.

**Named games.** The Game filter picks one named game and shows every rated telecast of it. Bowls are grouped by franchise and shown under their latest name, so a renamed bowl is one entry and searching an old name finds it. The CFP entries are the four playoff rounds, and a semifinal or quarterfinal played at a bowl appears under both its round and that bowl. Rivalries come from a curated list of well-known named FBS rivalries and count only the first regular-season meeting of the two teams each season, never a conference championship game. CFBD marks conference title games from 2022 on, so from then a title game is left out even when it comes before the rivalry game or replaces it. For earlier seasons the first-meeting rule alone applies, so a later conference-championship rematch is left out. Postseason meetings never count. The matched-games table lists the games that pass every filter, and the filter combines with the others like any other.

**Dot size.** Games that pass the filters are drawn larger, with a thin black outline, only when faded games are also on the chart, so they stand out against them. In Hide mode, or when a filter leaves nothing faded (for example every kickoff slot checked), every dot keeps its normal size. Zooming or panning never changes sizes. With Networks as the only filter, the number of network families also matters: picking 1 to 3 network families draws the shown games larger against the faded rest, and 4 or more keep them at normal size even though the other networks' games are faded. On the Date axis a season range alone does not enlarge dots.

None of this changes the axes or uses viewership as an input.

## Games with no public rating

Besides the rated games the chart plots, the site lists the games that have no public viewer figure, so a network's thin coverage is visible instead of silent.

**What ships.** Every main-feed game that has a matched game and a resolved network, rated or not. A game with no resolved network is left out; it is only counted in the build summary. A game shows up once: if it has a rated telecast, only that one is shown, and otherwise only its first unrated main-feed telecast is. The build counts the rest, and the site's data file is rejected if it repeats a game.

**What "rated" means.** A public viewer figure exists for the game's main broadcast.

**Why a game has no rating.** Each unrated game gets one cause, the first that matches:

1. "{Network} games are rarely rated": the network is on a hand-kept list (below).
2. "viewership not posted yet": the game is in the current season, in the newest week that has any posted figure or later (the postseason counts as after every regular week). When the season has no posted figure yet, every current-season game qualifies. A week's figures arrive over several days, so a strictly-later rule would flag nothing.
3. "no figure found in our 2021–24 sources": the game is from a season in that range, Ratings Reference compiled few figures for those seasons, and the second sources listed under Sources and credits did not cover the game (see Known gaps).
4. "no figure was published": anything else. This also covers the rare game whose only figure is for an alternate feed.

On the site each game reads "No public rating · {cause}".

**Counts.** "N rated of M games" counts the games that pass the current filters or selection: N is how many have a figure, M is all of them, rated or not. Filter counts count every game.

**The rarely-rated list.** It is set by hand, one value per network, in `data/reference/network_rarity.csv`, and never computed from a threshold. Every network in `networks.csv` has a row, so a newly mapped network forces a review. The build reports only how many networks have an actual rated share that contradicts their flag, so the list stays auditable.

**Where they appear.** With the y-axis on Viewers, these games sit in the "No public rating" strip under the plot as hollow rings when no filter is active, and for games that fail the filters. With the y-axis on Excitement, they are filled dots at their excitement value like every other game. On Points and Margin every game is a filled dot at its value, and the strip holds only games with no final score. When passing games are drawn larger (see Dot size above), the unrated games that pass are drawn like rated dots, and a selected announcer's games use the same shapes as their rated games; otherwise they stay hollow rings on Viewers. In Bars, each bar's outlined part counts them.

## Measurement eras

Nielsen, the source of nearly every viewership figure on this chart, changed
how it measures television audiences several times across this project's
2014-onward range. Comparing a raw viewership number from one era against
another without accounting for this is misleading — a level shift from a
methodology change can look like a change in real audience interest. Every
dot's detail panel shows which era its figure falls under.

| Era | Start | End | Source |
|---|---|---|---|
| Nielsen panel-only measurement | (project start) | 2020-08-30 | [ratingsreference.com/methodology](https://ratingsreference.com/methodology) |
| Nielsen panel plus out-of-home | 2020-08-31 | 2025-01-31 | [ratingsreference.com/methodology](https://ratingsreference.com/methodology) |
| Nielsen out-of-home expanded to all markets | 2025-02-01 | 2025-08-31 | [ratingsreference.com/methodology](https://ratingsreference.com/methodology) |
| Nielsen Big Data plus Panel | 2025-09-01 | 2026-08-30 | [ratingsreference.com/methodology](https://ratingsreference.com/methodology) |
| Nielsen enhanced co-viewing | 2026-08-31 | (ongoing) | [frontofficesports.com](https://frontofficesports.com/article/nielsen-co-viewing-currency/) |

Because each of these changes tends to shift viewership levels upward (out-of-home
and co-viewing measurement both count audiences that panel-only Nielsen
measurement missed), a season-over-season or era-over-era comparison of raw
viewership numbers needs this context. This chart does not attempt to correct
older figures onto a later era's basis — every figure is shown as originally
published, tagged with its own era.

Separate from measurement eras, a small number of telecasts carry an event
flag for a one-off circumstance that affected their audience. One such flag
on this chart marks telecasts that aired while Disney's networks (including
ABC and the ESPN networks) were in a carriage dispute with YouTube TV, from
October 31, 2025 through November 14, 2025 — see
[the reporting on the resolved dispute](https://www.espn.com/espn/story/_/id/46969585/disney-reaches-new-deal-youtube-tv-ending-blackout)
for background. A telecast carrying this flag may show depressed viewership
on the affected platform for reasons unrelated to the matchup or the crew.

### Nielsen + Adobe (streaming) figures

Some viewership figures on this chart blend Nielsen's linear-television
measurement with streaming-analytics data from Adobe, rather than reporting
Nielsen alone. These dots look exactly like every other dot on the chart —
same size, same color, same behavior under every filter — but their detail
panel and matched-games table row label them "Nielsen + Adobe (streaming)."
Because this figure type mixes two different measurement approaches, it is not strictly
comparable to a Nielsen-only figure, even within the same era, and should be
read with that caveat in mind.

Figures from the second sources (see [Sources and credits](#sources-and-credits))
carry no measurement label, because those sources don't say how a figure was
measured. Their detail panel shows "Measurement not recorded"; the era still
comes from the air date.

## The 2025 excitement break

CFBD, the source of this chart's excitement measure, changed its underlying
win-probability model partway through the 2025 season without recalculating
excitement for earlier seasons under the new model. As a result, an
excitement value from the 2025 season or later is not directly comparable to
an excitement value from an earlier season, even though both are reported on
the same numeric scale. Every telecast from the 2025 season onward carries
this flag in its detail panel, and when the chart's x-axis is set
to excitement mode, a caption appears under the axis noting the break. The caption shows whenever excitement is on either axis.
Affected dots look identical to any other dot — the flag is informational
only and never changes a dot's size, color, or shape.

## The x-axis: spread, excitement, and date

The chart's x-axis can show one of three options. Two are different measures
of "how close this game was expected to be or turned out to be," and the
choice between them matters for what a dot placement can and cannot explain.
The third is the game's date.

**Spread (the default):** x is the winner's closing point spread: negative
when the favorite won, positive when the underdog won (an upset), and 0 for a
pick'em. A solid zero line is captioned "← favorite won" and "underdog won →".
The distance from the zero line is the line's size, known before kickoff, so
games expected to be close sit near the middle on both sides. The side shows
the result: left when the favorite won, right for an upset. Read the distance
for the tune-in question, and the side for how the game turned out. The
closing spread comes from CFBD's betting lines (consensus provider first).

**Excitement (CFBD, the toggle):** this measure is calculated from what
actually happened during the game, after the fact. It can help explain
whether an audience stayed tuned in as the game unfolded, but it cannot
explain the initial decision to watch, since it is not available until the
outcome is already known. Only the Spread's distance is known at kickoff,
which is why Spread is the chart's default measure. The axis stops at 12. A game
above that sits at the right edge, marked "12+", and its tooltip shows the real value.

**Date (the third option):** each dot sits at the day its game aired in
Eastern time, nudged within the day by its kickoff time (a game with no listed
kickoff sits at midday). Seasons sit side by side, each trimmed to its own
first and last telecast, so the offseason takes no space and the current
season's block widens as games are added. A faint line marks the gap between
seasons; that gap is compressed space, not real days. Under the axis, one row
names each season (two-digit years on narrow screens, such as '24, or 24 on
the narrowest phones) and a second row shows month ticks, month names, or
dates, depending on how much room there is. On the Date axis, a faint gold band covers each season's bowl games and playoff games, from the first one to the end of that season. Conference championship games are not included. The band is only a calendar marker: it does not change with your filters. On this
option only, picking a season range shows just those seasons on the axis,
while every other filter fades or hides dots as usual. The Date axis has no
N/A strip because every telecast has a date, and its tooltip and detail panel
show both the spread and excitement values.

A telecast missing the value for the selected measure (no closing line, no
final score yet, or a tied game for Spread; no CFBD excitement value for
Excitement) is shown in a narrow "N/A" strip at the left edge of the chart,
still plotted at its real viewers value. An N/A-strip dot is never plotted at
zero and never dropped from the chart; it behaves identically to any other dot
under every filter, highlight, and hover. A game whose score has not arrived
yet moves into place on the next data update.

## The y-axis: viewers, excitement, points, or margin

The y-axis has four choices. **Viewers** is the default, on a log scale. **Excitement** is CFBD's excitement index, on a straight scale. **Points** is the two teams' final scores added together. The axis starts at 0. **Margin** is how many points the winner won by. The axis starts at 0. Games have no ties in our data. The axis does not change when you filter, so a dot never moves because of a filter.

The Excitement axis stops at 12, and the Points and Margin axes stop at 120 and 70. A game above a cap is drawn at the top edge, marked "12+", "120+" or "70+". Hover or tap the dot to see its real number. Like the rest of the axis, the "+" mark comes from every game we have, not just the ones your filters show, so it can appear even when no game above the cap is in view.

In Excitement mode every game is a filled dot at its excitement value, rated or not. The strip under the plot then holds the games CFBD publishes no excitement index for, and is labeled "No excitement value". The tooltip still shows viewers (or "No public rating" and its reason), and the summary still counts rated games. Read the vertical position the way [the 2025 excitement break](#the-2025-excitement-break) allows.

A game with no final score is drawn in the bottom strip, labeled "No final score", instead of being left out.

Excitement cannot be on both axes. Picking it on one axis moves the other back: the x-axis to Spread, or the y-axis to Viewers. Points and Margin work with any x-axis.

## Booth announcers only

This chart's person search and role filters cover booth announcers: the
play-by-play announcer and the analyst (color commentator) on a telecast's
main feed. These are the only two roles a search or a role filter can match
directly. A sideline reporter, when one is linked to a telecast, is still
searchable by name and still shown in the detail panel and matched-games
table, but a sideline credit never matches a play-by-play or analyst role
filter.

Announcer names are resolved through this project's own name crosswalk
rather than matched as literal strings, so that, for example, a parent and
child who share the same name are kept as two separate, distinct people
rather than merged into one.

## The map

The map shows where games were played and who traveled to call them. It counts
assignments. It is not a measure of quality or audience, and it carries no
viewer figures.

A dot is one venue for one network family, counting only the games that pass
the filters. A venue with many games reads darker.

Where each dot sits comes from one list of venues from CollegeFootballData.com.
Each game uses its own venue, so a neutral-site or bowl game sits where it was
played, not at a team's home stadium.

The lines show travel. With announcers picked, each person's games are joined in
date order. With schools picked and no announcer, each school's games are joined
the same way. Each season is its own path, so a line never runs across an
offseason. Each leg is colored by the network of the game it leads to. Filters
skip games but never cut a path: a leg runs from the last game still shown to
the next one.

Hawaii is drawn in an inset at the lower left. Alaska is not drawn, because no
game in the data was played there. Games abroad appear as labeled markers at the
edge of the map nearest them (Dublin and London at the top right, Sydney at the
lower left), or at their real point when that point is on the map (Nassau). A
game with no known location is left off the map and counted in a note.

<!-- nfl:start -->

## NFL: Special games

The NFL view counts how often each franchise plays in a special game. These are assignments, not quality: a special game says where the league scheduled a team, not how good the team is. Only regular-season games are counted.

**Solo slot.** A game is in a solo slot when no other NFL game kicks off within three hours of it, judged by kickoff times alone. A gap of exactly three hours fails. Slot names (Thursday night, Sunday night, Monday night, Thanksgiving, Christmas, Black Friday, Saturday, International) are labels only and never decide whether a game is in a solo slot. A Monday doubleheader keeps its Monday night label but neither game is in a solo slot.

**Fox AGOTW.** On a Fox doubleheader Sunday, the game Fox shows at the late national kickoff is America's Game of the Week. When several Fox games share that kickoff, a text source (a Ratings Reference late-window record or 506 page text) must name the national game. Otherwise the week is ambiguous and is left out of the Fox AGOTW counts and rates.

**CBS late national.** The same rule applied to CBS on a CBS doubleheader Sunday.

**International and flexed.** International games are labeled but are special only when they are also in a solo slot, Fox AGOTW or CBS late national. A game is flexed when it moved after the schedule was released into a solo slot or into the Fox or CBS late national game; the original slot and network come from Wikipedia and are shown with the article link.

**The stacked bars.** Each game counts once. The eight segments, in stack order, are:

1. Thursday night
2. Sunday night
3. Monday night (solo-slot games only; Monday doubleheader games share a window and are not counted here)
4. Holiday (Thanksgiving, Christmas and Black Friday games in a solo slot)
5. Other solo slot (Saturday, international mornings and any other solo-slot game)
6. Fox AGOTW
7. CBS late national
8. International, shared window (a game played abroad that shares its window)

A solo international game counts under its solo segment. The detail panel lists every flag a game carries, including the total international count.

## NFL: Doubleheader weeks and rates

A network has a doubleheader on a Sunday when it carries a game at the late national kickoff and at least one early game that day. The Fox AGOTW rate is a team's Fox AGOTW games divided by the Fox doubleheader weeks that are not ambiguous; the CBS late national rate works the same way for CBS. When the range covers several seasons, the rate is the summed count divided by the summed denominator, never an average of season rates. When the denominator is zero the rate shows as n/a, never 0.

## NFL: Crews and the lead booth

A booth is a play-by-play voice within one season and one network, together with that booth's most frequent analyst. Fill-in analysts stay with their booth, and each row shows its fill-in game count. Networks are grouped by family: ESPN, ABC, ESPN2, ESPN+ and ESPN Deportes count as ESPN/ABC, Peacock counts with NBC, NFL Network stands alone, and Netflix, YouTube and similar one-offs stand on their own. Games with no network are left out. Every regular-season game a booth called for that network counts.

Each network's lead booth is its flagship booth. For Fox it is the booth with the most Fox AGOTW calls. For CBS it is the booth with the most CBS late national calls. For NBC it is the Sunday night booth, for ESPN/ABC the Monday night booth, and for Amazon the Thursday night booth. For other networks it is the booth with the most games. The other booths follow by games called.

Three sources set the order, strongest first. Where a cited published lineup ranks a network's booths for a season, that order sets Lead, #2 and #3. Otherwise a cited lead-booth override applies. Otherwise the inference above applies. The build reports where a published lead differs from the inferred one.

The view shows one season at a time and is never pooled across seasons, because the standard errors do not combine simply. Its season list covers seasons with games and seasons with a published lineup. The rows describe which games each booth was assigned and how those games turned out, not how well anyone called them.

## NFL: Published lineups

506 lists a crew for nearly all Fox and CBS games, but often gives national games (Sunday, Monday and Thursday night, and streaming) a network and no crew. For those games, the first booth on a network's cited lineup release for that season is assigned to that network's flagship-window games that have no 506 crew. These games say "from published lineup" in the table and panel, which link the release. A crew 506 names always wins.

This is the second documented exception to the 506-only crew rule, alongside the college-football crew overrides in `crew_overrides.csv`. The rows are typed by hand from the release and confirmed by the user; no network site is collected by script. The Crews view states how many of a network's games have a listed crew.

## NFL: The spread adjustment

The Adjusted setting compares each booth's average outcome with what the league-wide average predicts for games in the same band of absolute pregame spread. The Crews caption words it plainly, for example "1.4 pts closer than the spread predicted". Whiskers are plus or minus 1.96 standard errors. The spread's value is never drawn, listed or shown in a detail panel; only the adjusted result and the booth's average band are displayed. Win-probability volatility is no longer shown.

## NFL: Low n

A booth, or a category point in the viewership view, with fewer than 8 games for an adjusted outcome or a residual is marked low n. It is drawn faded or hollow and carries a "low n" label. No ranking is implied by the order of rows, and a faded row is not a verdict.

## NFL: GEI-style excitement

The NFL excitement score is computed from nflverse per-play win probability, in the style of the Game Excitement Index. It is not CollegeFootballData.com's excitementIndex and the two are not on the same scale. Buttons, axis titles and table headers say "Excitement". The GEI-style qualifier appears in the excitement caption, the hover, the detail panel and here. A game with no play-by-play stays missing and is never shown as 0.

## NFL: Viewership by category

Each rated regular-season game falls in one category. Fox AGOTW is checked first, then CBS late national, then the slot: Sunday night, Monday night, Thursday night, Thanksgiving, Christmas, Black Friday, International, Saturday, Friday, and Other. Regional Sunday early and late games are not a category.

The chart draws one line per category, with season on the x axis and mean viewers on the y axis. Ratings Reference reports Fox AGOTW and CBS late national figures for the whole Sunday window rather than for one game, so those lines are dashed and labeled window-level. No coverage-share source exists, so the comparison is unnormalized, and each figure is tagged with the measurement era it was taken under.

The residual setting fits viewers on game quality within each category and Nielsen era. A point shows how a season compared with other seasons of the same category and era, not how categories compare with each other. Categories with too few games for a fit show no residual. Points with fewer than 8 games are marked low n. A missing figure stays missing and is never shown as 0.

## NFL: Window-level viewership

Ratings Reference reports some Sunday-afternoon figures for the whole regional window rather than for one game, so those figures are labeled window-level. See [Viewership by category](#nfl-viewership-by-category) for how they are drawn.

## NFL: Games with no public rating

A game can have no public viewer figure for one of three reasons, checked in this order:

1. Ratings Reference compiles national windows, not every regional game.
2. The figure is not posted yet. This applies to games of the current season at or after the latest week that has any figure.
3. No figure was published.

On the site each such game reads "No public rating" with its cause.

## NFL: Measurement eras

Eras are read from `data/reference/measurement_eras.csv`. Through the 2019 season viewers were measured by the panel alone. From 2020 the panel was combined with out-of-home viewing. From 2025 Nielsen's Big Data plus Panel applies, and from 2026 enhanced co-viewing is added. The February 2025 out-of-home expansion falls in the offseason, so it owns no NFL season. Bands align to whole seasons. Compare across bands with care.

<!-- nfl:end -->

<!-- mlb:start -->

## MLB: Sources, games and crews

The MLB view covers the Apple TV Friday game and the postseason booths on national networks. Game results, lineups and the play-by-play behind the excitement and stakes scores come from [Retrosheet](https://www.retrosheet.org), schedules and outlets from [506 Sports](https://506sports.com) hand-saved pages, round and crew lists from [Wikipedia](https://www.wikipedia.org) (CC BY-SA 4.0), and viewership from [RatingsReference.com](https://ratingsreference.com) (CC BY 4.0, modified). A game is identified by its date, the two clubs and the game number of a doubleheader, so each source lands on the same game.

**Crew precedence.** A hand-confirmed override wins, then a crew listed by 506 Sports, then a crew relayed from a fan-run schedule blog (credited game by game with its post and the press release the post cites), then Wikipedia's per-series broadcaster lists. When two sources name different crews for one game the build keeps the higher one and records the disagreement. Names are resolved through one crosswalk so a variant spelling is one person; Chris Caray and Chip Caray are kept as two people.

**Apple lead booth.** The lead is the play-by-play voice that Wikipedia's current national broadcaster list ranks first for Apple. Apple booths are the play-by-play voice plus the analysts listed with them in a season.

## MLB: Stakes

Stakes is a leverage proxy, not a simulation. For each game it takes each club's record through the previous day and its games behind the division leader and the last wild-card spot, and asks how much one game can move those races: the games-behind change is treated as having a standard deviation of the square root of one eighth per square-root game left, and ties on a cutoff are shifted by half a game. Wild-card spots are two per league through 2021 and three from 2022. Stakes are not scored in the first 20 games of a season, and 2020 is left out of the baseline because the short season distorts it.

## MLB: Excitement

Excitement uses a win-expectancy table our own method builds from Retrosheet play-by-play for 2015-2025. It is in-sample: the same seasons the table is trained on are scored with it. A state is the inning (extra innings pooled at the tenth), the half, the outs, the base runners and the score difference (clipped at 10), with a separate extra-inning regime for the automatic runner (2020 on). Each state is smoothed toward a coarser table and forced to rise with the home lead. Excitement is the sum of the changes in the home team's win probability over a game's plays, ending with the result, so extra innings simply add terms. A game with fewer than 30 plays, a forfeit or an undecided game gets no score, never zero. This is our own analysis; it is not a Retrosheet figure and not another source's rating.

## MLB: The adjustment, low n and what is pending

Booths are compared after adjusting for the matchup. Stakes are compared with the average for games in the same calendar month; excitement with the average for games in the same stakes band (band edges at the 50th, 80th and 95th percentiles of a 2017-2025 baseline with 2020 excluded). A band with fewer than 200 games is pooled with its neighbor. The difference between the lead booth and the others is a Welch difference with its standard error. A booth with fewer than 10 games is marked low n and no difference is claimed from it.

**Pending Retrosheet 2026.** Retrosheet publishes the 2026 season late in 2026. Until then 2026 games have no play-by-play, so 2026 stakes, excitement and lineups read "pending Retrosheet 2026". Rebuilding after the release fills them in. We did not use the league's own statistics service as a stopgap.

## MLB: Viewership

Viewership is matched to games from Ratings Reference records, which are kept with their record URL and the figure's original source. A figure can be marked as covering a window rather than one game, as a doubleheader that cannot be told apart, or as one network of several carrying the game; those are shown with their cause and not counted as a single-game figure. Apple's viewership is not reported to Ratings Reference, so the Apple view shows no figures and says so.

## MLB: Postseason crews 2014-2026

Crews for the 2025 and 2026 postseason come from 506 Sports round pages first. 506 has no MLB round pages before 2025, so 2014-2024 crews come from Wikipedia's lists of broadcasters for the Wild Card, League Championship Series and World Series, which do not cover the Division Series. The round-to-network map for those seasons is read from each season's Wikipedia postseason article and settled by hand. Each season row says what share of its games has a crew listed.

<!-- mlb:end -->

## Sources and credits

**Ratings Reference.** Most viewership figures on this chart come from
[RatingsReference.com](https://ratingsreference.com), published under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). This project's use
of that data is modified: it has been filtered, joined against game and crew
data from other sources, and reshaped for this chart, rather than reproduced
as published. Every dot's detail panel links the specific Ratings Reference
record (or records, when more than one record was merged for the same
telecast) that its figure came from, along with that figure's own original
source — the article, wire report, or post the number was first published
in.

**Sports Media Watch and the other viewership sources.** Ratings Reference
compiled few figures for the 2021–2024 seasons, so for those seasons this
project also uses the per-game figures that
[Sports Media Watch](https://www.sportsmediawatch.com/college-football-tv-ratings/)
printed in its season ratings charts. The charts are images. Their pages are
saved by hand and each chart is transcribed twice, independently, with no
automated reading (see `docs/sources/smw.md`). For the games still unrated
on ABC, CBS, NBC, FOX, ESPN, ESPN2 or FS1, a collector reads
[The TV Ratings Guide](https://www.thetvratingsguide.com)'s daily ratings
posts, whose tables list college games by name, and takes each game row's
viewers (see `docs/sources/tvrg.md`). It also reads
[Awful Announcing](https://awfulannouncing.com)'s college football ratings
posts, which are prose, and takes a figure only from a sentence that ties it
to exactly one named game (see `docs/sources/aa.md`). Both are fetched only
for dates that still have unrated games, after a fresh check of each site's
robots.txt and terms. ESPN's ratings releases on
[ESPN Press Room](https://espnpressroom.com) are the last source. Disney's
terms ban automated access, so its pages are saved by hand and imported, never
fetched (see `docs/sources/espnpr.md`).

Each telecast's headline figure comes from one source, so a dot never mixes
two sources' numbers: the highest-ranked source with a usable figure, in the
order Ratings Reference, Sports Media Watch, The TV Ratings Guide, Awful
Announcing, ESPN Press Room. Lower-ranked figures for the same telecast are kept
in this project's data but are not shown.

A second source's season loads only after its figures agree with Ratings
Reference's within 3% on every game both cover. A miss is read again from the
source. If the source really prints a different figure, the game is logged as
a known disagreement and Ratings Reference's figure stays the headline. A
season with more than two such disagreements loads only by a recorded decision.
All four Sports Media Watch seasons passed; 2024 had three logged disagreements
and loads by that decision. The TV Ratings Guide passed in all four seasons
and Awful Announcing in 2023, with no disagreements; Awful Announcing's 2024
posts share no game with Ratings Reference. ESPN Press Room's 2024 ratings
release passed with one logged disagreement.

Only per-game figures are used. A simulcast total (one figure for two
networks), a regional-window total (such as a Big Ten Network window that
covers several games), a multi-feed MegaCast total, and an "n/a" entry are all
left out.

As a result, 2021–2024 figures come from a mix of sources. A second-source
figure counts the same as a Ratings Reference figure everywhere: in the rated
counts, the coverage audit, and any future model built on this data.

Each second-source figure is credited to its publisher by name, linked to the
page it came from. For Sports Media Watch that is the season's ratings page,
because its charts have no page of their own; for The TV Ratings Guide,
Awful Announcing and ESPN Press Room it is the exact post or release. The
detail panel also says the
figure is not listed on Ratings Reference. These sources are used without
asking first, and a source's figures come off the site if it objects.

**506 Sports.** Crew listings — who called each telecast — come from
[506sports.com](https://506sports.com).

Crews come from 506 Sports, except a small set of telecasts 506 never lists,
including every College Football Playoff national championship. For those, the
booth was confirmed by hand from a public source, such as the network's press
release, and each such dot's detail view links that source in place of the 506
listing. If a public source shows that a crew 506 lists is wrong, that sourced
booth replaces 506's the same way, but the coverage table's hand-confirmed
count includes only telecasts 506 never gave a crew.

ESPN Press Room is a backup crew source for ESPN-family games. Its announcer
schedules and weekly releases are saved by hand and imported, never fetched.
Crews follow a fixed order: a hand-confirmed booth, then 506 Sports, then ESPN
Press Room, and the whole booth comes from one source, never merged person by
person. A backup booth fills a telecast only when it is on the same network and
neither of the others names a crew, and a later 506 crew replaces it. Its
detail view reads "Crew source: ESPN Press Room ↗", linked to the page the
booth came from. The coverage table counts backup crews in their own column,
and the "crews through week N" stamp counts 506 crews only.

**CollegeFootballData.com.** Game data, venue names and locations, rankings, closing spreads, and
excitement values come from CollegeFootballData.com. Every place this data
appears is credited with the phrase "Data provided by CollegeFootballData.com" linked to
[its homepage](https://collegefootballdata.com).

**Plotly.js.** The chart itself is rendered with
[Plotly.js](https://plotly.com/javascript/), used under its MIT license and
self-hosted alongside this site's other files.

<!-- nfl:start -->

**NFL.** The NFL view draws on four sources. Schedules and the win-probability-derived measures come from [nflverse](https://nflverse.com), published under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); this use is modified, because the data is derived and joined with crew and viewership data. NFL viewership comes from [RatingsReference.com](https://ratingsreference.com), also CC BY 4.0 and modified; each detail panel links the Ratings Reference record and the figure's original source. Scheduling changes, meaning the original slot and network of flexed games, come from [Wikipedia](https://www.wikipedia.org), with the article linked, and are licensed [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Crews and networks come from [506 Sports](https://506sports.com), on the same terms as college football. The NFL view also offers no bulk download and loads nothing from any source when you view it.

<!-- nfl:end -->

<!-- mlb:start -->

**MLB.** Play-by-play, results and lineups: "The information used here was obtained free of charge from and is copyrighted by Retrosheet. Interested parties may contact Retrosheet at www.retrosheet.org." Viewership comes from [RatingsReference.com](https://ratingsreference.com) (CC BY 4.0; modified), each detail panel linking the record and the figure's original source. Lists of broadcasters and postseason articles come from [Wikipedia](https://www.wikipedia.org), linked per crew and licensed [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Schedules and 2025-2026 crews come from [506 Sports](https://506sports.com); 2026 crews relayed from a fan-run schedule blog are credited per game with the post and the press release it cites. Excitement and stakes are our own analysis. The MLB view offers no bulk download and loads nothing from any source when you view it.

<!-- mlb:end -->

This site offers no bulk download of any of the data above, and it loads no
data from Ratings Reference, 506 Sports, CollegeFootballData.com, or any
other outside source at the time you view it — every figure shown here was
gathered and assembled ahead of time, before the page was built.

## Known gaps

This project's coverage of 2014-onward college football telecasts has some
known thin spots and edge cases — where a source's own records are uneven,
where a match between two sources could not be made with full confidence, or
where a figure combines more than one broadcast feed. See
[Known gaps](known-gaps.md) for the details, in the project's own words and
with counts only.

<!-- include: known-gaps.md -->
