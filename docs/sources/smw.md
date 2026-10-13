# Sports Media Watch: 2021–2024 ratings charts

Sports Media Watch publishes one college football ratings page per season, at
`https://www.sportsmediawatch.com/college-football-tv-ratings/<year>-season/`.
Each page carries the season's per-game viewer figures as chart images: one
chart per week, plus postseason and season-top summary charts. The charts have
no page of their own, so the season page is the most specific link for a
figure.

From 2014 to 2020, Sports Media Watch was the main upstream source of Ratings
Reference's per-game college football figures. Ratings Reference compiled far
fewer figures for 2021–2024, but Sports Media Watch kept publishing its charts,
so this project reads them to fill those four seasons (see
[Known gaps](../known-gaps.md)).

## Access

- Its robots.txt blocks scripts, so nothing in this project fetches from it.
  The host is not in the collector allow-list, and a test checks that it is
  never fetched (`tests/test_config_hosts.py`).
- Its season pages are saved by hand in a browser, as "Webpage, Complete" after
  scrolling so every chart loads, into `data/incoming/smw/<season>/`.
- It has no terms page, and its footer carries a copyright notice. It is used
  without asking first, with credit on every figure, and its figures come off
  the site if it objects (see [Takedown](#takedown)).

## Transcription

The charts are images. They are read in Claude Code sessions, never by an OCR
or image-parsing script.

- Every chart is transcribed twice, in two independent passes that never see
  each other's output. The two passes run on different models.
- A tall chart can first be cropped into overlapping strips with
  `uv run python -m booth_review.sources.smw.tiles`. This only crops pixels.
- `booth-review review smw-diff --season <year>` lists every cell where the two
  passes differ. Each one gets a third look at the image, and the answer is
  recorded as a resolution.
- `booth-review review smw-merge --season <year>` writes the merged rows.
- Every printed row is transcribed as printed, including games and networks
  this project does not carry. The loader, not the transcriber, decides which
  rows count.

## Import

`booth-review import smw --season <year> [--from <folder>] [--force]` copies
the season page, the chart images and the transcription into the vault's
`raw/smw/<season>/`. Before it writes anything it checks that:

- the saved page's canonical link and title name the season;
- every chart image is a real PNG and has transcribed rows;
- the diff and the merged rows are exactly what the two passes and the recorded
  resolutions produce, so every figure traces back to both passes.

Like every vault write, it holds the vault lock and commits only its own paths.

## Chart layouts

- **2021 weekly charts:** date, kickoff, one game cell with both teams as short
  abbreviations, network, rating and viewers, then comparison columns against
  earlier seasons, which are not transcribed. Some abbreviations fit more than
  one school; they are resolved by the date and opponent.
- **2022 and 2023 weekly charts:** a window column (weekday, date and kickoff),
  then away team, home team, network, rating and viewers. The 2023 charts put
  the network last.
- **2024 weekly charts:** window, away, home, viewers and network, with no
  rating column. The header notes which networks are not Nielsen-rated.
- **Postseason charts:** window, the bowl or game name, both teams, network,
  rating and viewers. 2021's postseason charts print the bowl name in the same
  cell as the first team.
- **Season-top charts:** the season's most-watched games. They are used only for
  a game that appears on no weekly or postseason chart.

## What the loader keeps

A row is loaded only when it prints a per-game figure for a telecast this
project already carries. It never creates a telecast. These rows are left out:

- a simulcast total, where one figure covers two networks (joined by "&", a
  comma or a spaced "+");
- an ESPN MegaCast total, which combines several feeds;
- a regional-window total, such as a Big Ten Network window that lists several
  games;
- a row that is not a game, such as a studio show;
- a row marked as not Nielsen-rated;
- a row with no figure ("n/a", blank, or "not disclosed");
- a game with no FBS team;
- a row the user excluded on review.

A number with an unknown suffix goes to a review list instead of loading.

Rows are matched by season, both teams through `data/reference/team_crosswalk.csv`,
and the date within a day. Home and away may be flipped for neutral sites. A
row that fits more than one game goes to the review list and is never guessed.
When the chart names a different network from ours, the figure is held until
the user either corrects our network (`primary_network_overrides.csv`) or keeps
ours for that row (`second_source_network_accepts.csv`). When a game appears on
two charts with different figures, the later chart wins; every such conflict is
reported.

## Agreement with Ratings Reference

A season loads only after its figures agree with Ratings Reference's on the
games both sources cover.

- Every shared game must agree within 3%.
- On a miss, the chart is read again. A misread is fixed. If the chart really
  prints that figure, the game is logged as a known disagreement, and Ratings
  Reference's figure stays the headline there.
- A season passes with at most 2 logged disagreements. More than 2 needs a
  recorded user decision (`second_source_gate_overrides.csv`).

| Season | Shared games | Within 3% | Logged | Result |
|---|---|---|---|---|
| 2021 | 152 | 151 | 1 | Passed |
| 2022 | 111 | 111 | 0 | Passed |
| 2023 | 132 | 132 | 0 | Passed |
| 2024 | 155 | 152 | 3 | Passed by user decision |

## On the site

Ratings Reference ranks first: a Sports Media Watch figure is the headline only
when Ratings Reference has no usable figure for the telecast. The table's source
cell names Sports Media Watch, linked to the season page. The detail panel adds
"View original source (Sports Media Watch) ↗" and says the figure was read from
that season's chart and is not listed on Ratings Reference. Sports Media Watch
does not say how its figures were measured, so the panel shows "Measurement not
recorded". Only the figure is shown; the site offers no download of the
transcriptions.

## Storage

The saved pages, chart images and transcriptions live only in the private
vault, under `raw/smw/<season>/`. They are never copied into this repository,
its test fixtures, commit messages or logs. Tests use synthetic chart rows.

## Takedown

If Sports Media Watch objects, remove `raw/smw/<season>/` from the vault for
each season, commit and push the vault, and rebuild. The rated counts drop, so
if the regression guard blocks the build, accept the new baseline with
`booth-review build --accept-baseline`. The affected games go back to the
"No public rating" strip.
