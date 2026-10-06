# Known Gaps (AUDIT-02)

This page describes, in our own words and with counts only, where this
project's coverage of 2014–2025 college football telecasts is thin or
uneven. It exists so a reader of the chart understands what "every rated
telecast" actually means before comparing two seasons, two networks, or two
announcers. No specific game, crew, or figure is named here — see
`docs/sources/506.md`, `docs/sources/ratings-reference.md`, and
`docs/sources/cfbd.md` for source-level detail, and `docs/site-data.md` for
how these tables reach the chart.

## Scope

The chart covers games from the 2014 season onward where at least one team
was FBS that season (JOIN-07) — a rated FBS-vs-FCS opener counts, two
non-FBS teams playing each other does not. Only **rated** telecasts (a
figure this project could attach a Ratings Reference viewership claim to)
appear as dots; unrated games are not shown in v1, though the data behind
that gap is being kept for a possible future assignment view. 2013 is out of
scope: it needs its own excitement computation this project doesn't attempt
in v1 (CFBD's win-probability data used for excitement starts in 2014).

## Ratings Reference coverage: a real dip in 2021–2024

Ratings Reference's own record count per season is not flat. 2021–2024 sit
noticeably lower than the seasons around them:

| Season | RR records |
|---|---|
| 2021 | 154 |
| 2022 | 113 |
| 2023 | 148 |
| 2024 | 171 |

By comparison, every other season in this project's range falls between
roughly 322 and 412 records. This project did not cause the dip — it
reflects how much Ratings Reference itself compiled for those four seasons
— but it matters for reading the chart: a season-over-season comparison of
"how many telecasts got a national audience figure" is not apples-to-apples
across this boundary, since a thinner season here has fewer candidate
telecasts to plot at all, not necessarily less television coverage. Treat
any 2021–2024 vs. neighboring-season count comparison with that caveat.
These games now appear in the 'No public rating' strip, and the counts read 'N rated of M games'.

## 506 Sports: hand-saved pages and a small number of empty weeks

506sports.com blocks this project's automated, correctly-identified,
robots-respecting client, so every 506 page in this project's vault —
2014–2024 backfill and the 2025 season alike — was saved by hand in a
browser and imported, never fetched live (`docs/sources/506.md`,
`AGENTS.md`). Ten season-level cells, spanning 2014–2023, were waived at the
2014–2025 freeze because the season's own saved pages show the site had no
games to list that week (a structurally empty page, not a bad save) — the
freeze recorded exactly which ten and why, and no other 506 gap was waived.
Separately, a small share of 506 listings carry no announcing crew at all
(mostly smaller-audience and streaming-only games); those telecasts, when
otherwise rated, are counted as coverage gaps rather than silently dropped
— see the crew-match rate below. During the season, crews for the newest
week appear once its 506 pages are saved by hand and imported; a second,
automated crew source was evaluated and none was adopted. Until then those
dots read "Crew not listed", and the "crews through week N" stamp shows how
far crews reach.

## Matching: game and game-plus-crew rates

Two match rates matter for "does this telecast make it into the chart with
the right crew." This project's research baseline (2014–2025, before the
crosswalk, pointer overrides, and this phase's joins existed) measured 97.9%
for a Ratings Reference record matched to a CFBD game alone, and 91.1% once
a matched 506 crew was also required. Those research-baseline numbers are
kept here only as a historical reference point, not as this project's
current state.

After building the real crosswalk, pointer-only overrides, and the joins in
this phase, the project's own full rebuild (2014–2026) measures **100.0%**
RR-to-game and **99.7%** RR-to-game-plus-crew (3,451 of 3,460 in-scope
rated records), comfortably above the 95% target for both. Every season in
range individually clears 95% game-plus-crew match as well; the lowest is
2014 at 98.0%. The remaining 9 of 3,460 in-scope records (0.3%) without a
crew are telecasts for which no listed crew exists and no public source named
the booth, not a game this project failed to find. As of the last build, 34
plotted telecasts take their crew from a hand-confirmed public source instead
of a 506 listing, including every College Football Playoff national
championship, which 506 never lists. They count toward the game-plus-crew
rate above; counting 506 crews alone, the rate is 98.8% (3,417 of 3,460).
9 plotted telecasts still have no listed crew. This phase also draws a stratified, hand-checked sample of
50 telecasts across seasons and networks for a user to confirm; the user
confirmed all 50 rows against their Ratings Reference record and 506 page,
for a JOIN-08 sample precision of 50/50 (100%). This project's
own match and crew rates, season by season and network by network, are in
the coverage table each build produces (`AUDIT-01`, `processed/coverage.csv`
in the vault).

A handful of other counts from the same rebuild, each affecting a small
share of telecasts and none blocking a telecast from the chart: 4 duplicate
Ratings Reference records were merged onto an existing telecast rather than
plotted as their own dot (JOIN-05); 5 telecasts had a headline-figure pick
that disagreed with Ratings Reference's own current-figure marker; 15
telecasts disagreed with this project's own era assignment (see below)
versus Ratings Reference's own era tag; and 14 telecasts were flagged
combined across simulcast feeds (see the next section).

Separately, this phase's coverage-audit pass compared Ratings Reference's
own listed network against 506 Sports' own listed network for every rated,
crew-matched telecast, since the two sources are compiled independently and
occasionally disagree about which channel actually carried a game. 28 of
3,416 crew-matched telecasts (0.8%) showed a disagreement between the two
sources' raw network text. Most of these are plausible same-family channel
swaps (e.g. ESPN vs. ESPN2) that this project's own review could not
independently confirm one way or the other without a source neither party
already has access to, some are simulcasts where both sources in fact list
overlapping channels and no real disagreement exists, and a small number are
clear-cut, corrected through a pointer-only network override once verified
(see `data/reference/primary_network_overrides.csv`). Uncorrected
disagreements do not block a telecast from the chart; the dot uses this
project's own rights-holder rule and is not otherwise flagged to the reader.
By category (counts only, no game-level detail): 4 benign channel overlaps
where both sources in fact list overlapping outlets, 2 ambiguous
streaming-companion pairings, 4 telecasts (2 same-night game pairs) where
the two sources' channels for that night appear swapped between the pair,
15 same-family disagreements (e.g. a channel vs. its sister feed), and 3
cross-family disagreements. None of the 28 were corrected by an override
after this review; they remain documented disagreements.

## Combined figures are identified by review, not by a source flag

Ratings Reference's schema has fields (`composite_of`, `carrier_network`)
meant to mark a figure that combines viewership across simulcast feeds (a
MegaCast or a title game with alt-casts) — but across every claim in this
project's 2014–2025 range, neither field was ever populated. A combined
figure is real (a title game's audience genuinely spans a main network and
one or more alt-casts), it just isn't self-declared in the source data. This
project instead flags a likely combined figure for review (a CFP, New
Year's Six, or MegaCast game with 506-listed alt-casts, or a figure well
above that network's typical audience) and confirms it by hand in a
pointer-only override table (`data/reference/`, D-06) rather than trusting
an empty source field to mean "not combined." Every CFP national
championship game in this project's range is treated as combined on that
basis; since neither source lists every alt-cast feed a championship
MegaCast actually ran, the feed count recorded for those games is a
documented minimum of 2, not an exact tally.

## Measurement: eras, blends, and figures with no current-figure marker

Ratings Reference tags each claim with one of three `era_id` values across
this project's range, coarser than the five dated measurement eras this
project tracks (Nielsen panel-only, panel-plus-out-of-home, the February
2025 out-of-home expansion, Nielsen's Big Data + Panel switch, and the
planned 2026 co-viewing addition) — two of this project's five eras share
one `era_id` value because Ratings Reference doesn't distinguish them, and a
handful of claims carry an `era_id` that looks like it reflects when the
figure was reported or revised rather than when the game aired. Because of
that lag risk, this project assigns a telecast's era from its own air date
and treats Ratings Reference's `era_id` as a cross-check, not the source of
truth. Claims Ratings Reference itself marks as a Nielsen-plus-streaming-
analytics blend are flagged in this project as a separate Nielsen+Adobe
measurement type rather than folded in with plain Nielsen figures. Finally,
Ratings Reference does not mark every record with a current-figure pick:
roughly 18% of records in this project's range carry no such marker at all
(no "peers" block to compare claims against), so this project's own
headline-figure-vs-Ratings-Reference-current-pick agreement check is not
comparable for that share of records — it is skipped, not counted as either
agreement or disagreement.

## CFBD: excitement, the 2025 model change, media rows, and rankings

CFBD's `excitementIndex` is null far more often on CFBD's own all-division
games table (44–64% depending on season) than on the FBS-involving games
this project actually charts, where the null rate stays under 2% in every
season 2014–2025 (`docs/sources/cfbd.md`). CFBD changed its excitement/
win-probability model partway through the 2025 season without backfilling
earlier seasons, so this project flags every 2025-and-later telecast rather
than treating excitement as directly comparable across the whole 2014–2025
span (`FLAG-04`). CFBD's own media rows don't cover every game a network
actually carried — 506 Sports, not CFBD, is this project's source for which
network aired a game. Postseason games take their rank from the last
regular-season poll available, not a postseason "final" poll CFBD only
publishes after the bowls are already played (so it was never the ranking
in force at kickoff). Looking ahead, Nielsen's planned Aug 31, 2026
enhanced co-viewing addition is tracked as a dated era boundary the moment
it takes effect, by air date, the same way every other measurement break in
this project is handled.

## Conference networks show very few dots

Conference networks such as the Pac-12 Network are rarely Nielsen-rated, and
when they are, the figure is rarely reported publicly. They therefore appear
on the chart with very few dots even though many games aired there. For the
Pac-12 Network, 506 Sports lists 318 telecasts across 2014–2026, but only 1 has
a published Ratings Reference viewer figure, so the chart shows 1 dot.
These games now appear in the 'No public rating' strip, and the counts read 'N rated of M games'.

## Games with no public rating

Games with no public viewer figure are shown, not dropped: they sit in a "No public rating" strip, each with its cause. See [Games with no public rating](methodology.md#games-with-no-public-rating) for the causes and how the counts work.
