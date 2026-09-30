# Methodology

This page explains what the chart on this site can and cannot say, in plain
language. It covers what is plotted, why the sample is not a random sample of
college football, how measurement changed over the years in scope, why the
x-axis has two different meanings depending on the toggle, and where the
figures on the chart come from.

## What this chart shows

Each dot is one rated national telecast of an FBS college football game, from
the 2014 season onward. The y-axis is viewers, on a log scale. The x-axis
defaults to the pre-game closing spread and can be toggled to CFBD's
post-game excitement measure instead. Dots are colored by network family —
for example, the Disney family groups ABC and the ESPN networks under one
color — but the specific network that carried a telecast is always named in
the hover, the detail panel, and the matched-games table. No dot is ever
colored by an individual announcer or crew.

A dot's tooltip is kept short: the matchup and final score, the date and
kickoff time (with a bowl or trophy icon for postseason games), the
networks, the crew, and the viewer count. Click or tap the
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
to excitement mode, a caption appears under the x-axis noting the break.
Affected dots look identical to any other dot — the flag is informational
only and never changes a dot's size, color, or shape.

## The x-axis: pre-game spread and excitement

The chart's x-axis can show one of two different measures of "how close this
game was expected to be," and the choice between them matters for what a dot
placement can and cannot explain.

**Pre-game (the default):** x is the negative absolute value of the game's
closing point spread, so a game expected to be closer sits further to the
right and a bigger expected blowout (in either team's favor) sits further to
the left. This measure is known before kickoff, which makes it the
appropriate control for a viewer's decision to tune in — nobody decides to
watch a game based on how exciting it turned out to be, because that
information does not exist yet at kickoff.

**Excitement (CFBD, the toggle):** this measure is calculated from what
actually happened during the game, after the fact. It can help explain
whether an audience stayed tuned in as the game unfolded, but it cannot
explain the initial decision to watch, since it is not available until the
outcome is already known. This is why pre-game spread, not excitement, is
the chart's default measure.

A telecast missing either value — its closing spread was not recorded, or
CFBD did not compute an excitement value for it — is shown in a narrow "N/A"
strip at the left edge of the chart, still plotted at its real viewers value.
An N/A-strip dot is never plotted at zero and never dropped from the chart;
it behaves identically to any other dot under every filter, highlight, and
hover.

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
listing.

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
