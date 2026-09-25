# CollegeFootballData.com (CFBD): API semantics

booth-review calls exactly seven CFBD v2 endpoints — the only ones on the
allow-list a request can ever target: `/games`, `/games/media`, `/lines`,
`/metrics/wp/pregame`, `/rankings`, `/teams/fbs`, and the free `/info` budget
check. Every call except `/teams/fbs` passes `seasonType=both`; without it,
CFBD defaults to regular-season games only and silently drops postseason
(bowl and playoff) rows, which this project needs for the CFP games in its
sample. `/teams/fbs` isn't split by season type at all, so the parameter is
left off there. Every call also passes `year=<season>`, the only other
parameter this project sends.

CFBD's JSON comes back camelCase (`homeTeam`, `startDate`, `excitementIndex`);
booth-review's parsers translate every field to snake_case on the way in, so
nothing downstream has to remember which convention applies where.

## `startDate` is always UTC with an explicit `Z`

Every `startDate` value observed across 2014–2025 ends in a literal `Z`
(UTC, zero offset) — never a `+00:00`, another explicit offset, or a
timestamp with no offset at all. booth-review's parser treats an
offset-less timestamp as a hard error rather than assuming UTC, precisely
because CFBD's docs don't guarantee this format will never change. To show
a kickoff in Eastern time (which is what 506 Sports lists and what this
project displays), convert the UTC value with a real time-zone library —
never a fixed offset, since ET shifts between EST and EDT across the season.

## Week numbering

CFBD numbers weeks within each `seasonType` independently, and — this is the
part worth knowing before joining against another source — it does **not**
have a separate "week 0". The season-opening games some sites call "week 0"
(the ones playing a week before the rest of the country) are folded into
CFBD's `week=1` alongside the first full slate. A source that keeps its own
"week 0" as a distinct label (506 Sports does) needs an explicit mapping,
not a direct week-number match, when joining to CFBD.

`seasonType` values seen include `regular` and `postseason` for the main
slate, plus separate `spring_regular` / `spring_postseason` values for
spring games — another reason `seasonType=both` alone isn't enough context;
a join also has to decide whether spring games are in scope (this project's
are not).

## FBS classification

`homeClassification` / `awayClassification` carry values like `fbs`, `fcs`,
`ii`, and `iii`. This project's rule (JOIN-07) is: a game is in scope if
**at least one** side is `fbs` that season — kept even against an FCS
opponent, but two non-FBS teams playing each other is out of scope
regardless of anything else about the game.

## Media fill rate

`/games/media` doesn't have a row for every game — plenty of smaller games
have no media entry at all, and CFBD's counts overlap `mediaType` values
(`"tv"`, `"web"`, and others) rather than tell you the single carrying
network directly. In a recent season, roughly seven in ten FBS games had at
least one `"tv"`-typed media row; the rest either streamed only, had no
media entry recorded, or were the kind of small non-conference game with no
national broadcast at all. Don't assume a missing media row means an
untelevised game — cross-check against another source before drawing that
conclusion.

## Poll names

`/rankings` returns poll names verbatim, and they don't line up with the
short names people use casually. The polls this project has seen include the
AP media poll, a head-coaches poll, division-specific coaches polls for FCS
and Division II/III, and — starting partway through the season, once the
committee begins meeting — the College Football Playoff committee's own
weekly rankings. Filtering `/rankings` by a guessed poll name doesn't work
reliably; matching the exact string CFBD returns does.

## Line providers and spread direction

`/lines` returns one row per `(game, provider)`, since more than one
sportsbook can quote a line for the same game. `spread` is the closing
number; `spreadOpen` is the opening number from the same provider. Spread
sign follows the home team's perspective (negative means the home team is
favored). Not every provider quotes every game, and the set of active
providers has shifted over the years covered — a fixed priority order,
falling back from a designated "consensus" line to whichever provider has
the most coverage that season, is what this project uses to pick one
number per game when more than one is available (see the pre-game measure
section below).

## `excitementIndex`

`excitementIndex` is null for a substantial share of games in every season
observed — roughly two in five games in the earlier seasons, rising to well
over half from 2021 on. A null value stays null all the way through this
project's pipeline (never coerced to zero, which would misrepresent an
unmeasured game as a genuinely boring one). CFBD changed its excitement
model partway through 2025; this project flags that season for that reason
rather than treating all `excitementIndex` values as directly comparable
across the whole 2014–2025 span.

## Budget accounting

Every response carries an `X-CallLimit-Remaining` header, checked against
`/info`'s own `remainingCalls` field after every call; a persistent
disagreement between the two gets logged rather than silently trusted. In
this project's own testing, calling `/info` itself did **not** count
against the monthly quota — confirmed by an explicit two-call probe (call
`/info` twice back to back and check whether the remaining count actually
dropped) rather than assumed from the docs. Every CFBD call — data or
`/info` — is refused outright once the remaining count would drop below a
configured floor, so a bug can't run a key all the way to zero.

## Terms (updated August 12, 2026)

CFBD's terms allow using API data in a website, including derived outputs
like a chart, but prohibit providing the API data itself as a standalone
downloadable dataset, a bulk download, a mirror, or a substitute API — even
reformatted. This project's own downloadable exports may contain its own
analysis, never a bulk re-export of CFBD's fields. Attribution ("Data
provided by CollegeFootballData.com", linked) is appreciated by CFBD's terms
though not strictly required; this project displays it on the site anyway.

## Pre-game x-axis measure (SPIKE-04)

The site's x-axis toggle needs one pre-game measure of "how close a game was
expected to be" as an alternative to CFBD's post-game `excitementIndex`. Two
candidates were compared on their 2014–2025 coverage: the closing point
spread (from `/lines`) and the pregame home win probability (from
`/metrics/wp/pregame`).

**Chosen measure: closing spread.** Its worst-covered season still reaches
95.6% of that season's FBS-involving games, against pregame win
probability's worst season at 74.0% — a 21.6-point gap, comfortably past the
threshold for choosing on coverage alone. Where the two measures are both
well covered (2025), they agree closely: a rank correlation of 1.000 between
`|spread|` and `|winProbability − 0.5|` across that season's games with both
values present.

**Orientation:** `x = -abs(spread)`. A pick'em game (spread of 0) plots at
`x = 0`, the rightmost point on the axis; a bigger favorite in either
direction plots further left. This keeps "close game plots right" true
regardless of which team was favored.

**Coverage by season** (percentage of that season's FBS-involving games with
each measure available):

| Season | Closing spread | Pregame win probability |
|---|---|---|
| 2014 | 99.7% | 93.3% |
| 2015 | 95.6% | 91.4% |
| 2016 | 99.2% | 96.4% |
| 2017 | 99.9% | 98.7% |
| 2018 | 98.3% | 90.7% |
| 2019 | 99.2% | 99.2% |
| 2020 | 99.5% | 99.5% |
| 2021 | 100.0% | 99.3% |
| 2022 | 99.6% | 74.0% |
| 2023 | 99.7% | 93.3% |
| 2024 | 98.4% | 89.6% |
| 2025 | 100.0% | 99.6% |

The 2022 dip in pregame win-probability coverage is the season that decides
this: closing spread stays essentially complete throughout, while pregame WP
drops well below 80% that year — a gap too large to prefer WP's slightly
more familiar 0–1 scale over spread's much steadier availability.
