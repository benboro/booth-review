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
3. "few figures were compiled for 2021–24": the game is from a season in that range, when Ratings Reference itself compiled far fewer figures (see Known gaps).
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

## Sources and credits

**Ratings Reference.** Viewership figures on this chart come from
[RatingsReference.com](https://ratingsreference.com), published under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). This project's use
of that data is modified: it has been filtered, joined against game and crew
data from other sources, and reshaped for this chart, rather than reproduced
as published. Every dot's detail panel links the specific Ratings Reference
record (or records, when more than one record was merged for the same
telecast) that its figure came from, along with that figure's own original
source — the article, wire report, or post the number was first published
in.

**506 Sports.** Crew listings — who called each telecast — come from
[506sports.com](https://506sports.com).

Crews come from 506 Sports, except a small set of telecasts 506 never lists,
including every College Football Playoff national championship. For those, the
booth was confirmed by hand from a public source, such as the network's press
release, and each such dot's detail view links that source in place of the 506
listing. If a public source shows that a crew 506 lists is wrong, that sourced
booth replaces 506's the same way, but the coverage table's hand-confirmed
count includes only telecasts 506 never gave a crew.

**CollegeFootballData.com.** Game data, rankings, closing spreads, and
excitement values come from CollegeFootballData.com. Every place this data
appears is credited with the phrase "Data provided by CollegeFootballData.com" linked to
[its homepage](https://collegefootballdata.com).

**Plotly.js.** The chart itself is rendered with
[Plotly.js](https://plotly.com/javascript/), used under its MIT license and
self-hosted alongside this site's other files.

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
