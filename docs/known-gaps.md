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
— see the crew-match rate below.

## Matching: game and game-plus-crew rates

Two match rates matter for "does this telecast make it into the chart with
the right crew." Matching a Ratings Reference record to a CFBD game alone
measured 97.9% in this project's research baseline (2014–2025) — comfortably
above the 95% target. Requiring a matched 506 crew as well brought that down
to 91.1% in the same baseline measurement, concentrated in cases where 506
never listed the game at all rather than listing it without a crew. This
project's own current match and crew rates, season by season and network by
network, are in the coverage table each build produces (`AUDIT-01`,
`processed/coverage.csv` in the vault); Plan 12 of this phase updates the
final numbers reported here once every override and review pass is done.

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
an empty source field to mean "not combined."

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
