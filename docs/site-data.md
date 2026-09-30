# site-data.json: the Phase 4 contract

`site-data.json` is the one file the static site loads. It is built once,
server-side, from the joined Phase 3 tables, and the browser never talks to
CFBD, Ratings Reference, or 506 Sports — every request happens ahead of time,
during the build (see `AGENTS.md` § Website). This document, the pydantic
models in `src/booth_review/contract/models.py`, and the generated JSON
Schema at `docs/site-data.schema.json` are the same contract described three
ways; `tests/test_contract.py` proves the schema file and the models never
drift apart.

This contract is fixed before any join code exists (D-14), so Phase 4 can
start building the site against `tests/fixtures/contract/site-data.fixture.json`
immediately, in parallel with Phase 3's real joins.

## Layout: columnar, index-aligned, index-referenced

`site-data.json` is **one versioned columnar JSON file** (D-13), not an array
of per-telecast objects:

- `schema_version` — the contract version (currently `"1.3.0"`). See
  Versioning below.
- `generated_at` — ISO UTC timestamp of the build that produced the file.
- `freshness` — `{ season, crews_through_week, viewership_through_week }`,
  the two SITE-14 freshness stamps.
- `lookups` — small tables (`teams`, `networks`, `people`, `publishers`,
  `flags`, `conferences`) that `telecasts` columns reference **by integer
  index**, so a team, network, person, publisher, flag, or conference name
  is stored once, not once per telecast.
- `telecasts` — the `TelecastColumns` object: **one array per display
  field**, every array the same length `N`. Index `i` across every array
  describes one telecast — one plotted dot. `telecasts.season[3]`,
  `telecasts.away_team[3]`, and `telecasts.viewers[3]` all describe the same
  telecast.
- `coverage` — one row per `(season, network)` plus a season-total row
  (`network` null), the SITE-16 coverage table.

A consumer never needs to reassemble per-telecast objects to plot the chart:
Plotly.js reads `telecasts.viewers`, `telecasts.excitement`, and
`telecasts.network` (mapped to a color through `lookups.networks`) directly
as parallel arrays.

## Only main-feed rated telecasts with a headline figure are dots

Only telecasts that JOIN-04's headline rule resolved to a figure on the
main broadcast feed appear as rows in `telecasts` (D-10). An alt-cast-only
or Spanish-language feed's own figure is kept in the build's processed
tables but is never plotted in v1 — the fields exist so switching that on
later is a flag change, not a schema change.

## Field-by-field contract

Every field below is a `telecasts.<name>` array of length `N`. "Null rule"
describes when the value is `null` instead of coerced to a placeholder like
`0` or `""` — missing stays missing end to end (D-11, FLAG-04).

| Field | Type | Null rule | Serves |
|---|---|---|---|
| `season` | int | never null | SITE-06 |
| `date` | str, ET calendar date, `YYYY-MM-DD` | never null | SITE-04, SITE-06 |
| `kickoff` | str \| null, ET ISO datetime with UTC offset | null when kickoff time is unknown | SITE-04 |
| `time_slot` | `"noon"` \| `"afternoon"` \| `"prime"` \| `"late"` \| null | null exactly when `kickoff` is null | SITE-11 |
| `away_team` | int, index into `lookups.teams` | never null | SITE-01, SITE-09 |
| `home_team` | int, index into `lookups.teams` | never null | SITE-01, SITE-09 |
| `neutral` | bool | never null | SITE-04 |
| `away_points` | int \| null | null before/if a final score isn't known | SITE-04 |
| `home_points` | int \| null | null before/if a final score isn't known | SITE-04 |
| `away_rank` | int \| null | null when that team is unranked | SITE-04 |
| `home_rank` | int \| null | null when that team is unranked | SITE-04 |
| `network` | int, index into `lookups.networks` | never null; the primary network (rights holder, JOIN-06) | SITE-01, SITE-04 |
| `outlets` | list[int], indexes into `lookups.networks` | never null; the full outlet list (JOIN-06), including `network` | SITE-04 |
| `viewers` | int, must be `> 0` | never null; a telecast with no headline figure isn't a row at all | SITE-01 |
| `measurement_type` | `"nielsen"` \| `"nielsen_adobe"` \| `"unknown"` | never null | FLAG-02, SITE-04 |
| `publisher` | int \| null, index into `lookups.publishers` | null when the figure's first publisher isn't known | SITE-17 |
| `source_url` | str \| null | null when the figure's original source URL isn't known | SITE-05, SITE-17 |
| `rr_urls` | list[str], never empty | every merged Ratings Reference record URL for this telecast (JOIN-05); a duplicate-record merge keeps both | SITE-05 |
| `s506_url` | str \| null | null when no 506 page is linked | SITE-05 |
| `excitement` | float \| null | null when CFBD's `excitementIndex` is missing — **never coerced to 0** (FLAG-04) | SITE-03, SITE-04 |
| `pregame` | float \| null, `-\|closing spread\|` (SPIKE-04) | null when the closing spread isn't known | SITE-03 |
| `flags` | list[int], indexes into `lookups.flags` | empty list when no flag applies | SITE-04, FLAG-01, FLAG-02, FLAG-03, FLAG-04 |
| `combined_feeds` | int \| null, `>= 2` when set | null unless this figure combines viewers across feeds (D-08) | SITE-04 |
| `crew` | list of `{person, role, feed}` | empty list when no crew is known; each entry's `person` is an index into `lookups.people` | SITE-04, SITE-07, SITE-10 |
| `game_type` | `"regular"` \| `"bowl"` \| `"playoff"` | never null | SITE-21, SITE-24, SITE-25 |
| `playoff_round` | `"first_round"` \| `"quarterfinal"` \| `"semifinal"` \| `"championship"` \| null | null unless `game_type` is `"playoff"`, in which case it holds the CFP round when CFBD's own `playoff.round` value is one of these four; an unrecognized round string is also null | SITE-24, SITE-25 |
| `home_conference` | int \| null, index into `lookups.conferences` | null when CFBD reports no conference for the home side (e.g. some FCS opponents) | SITE-21, SITE-25 |
| `away_conference` | int \| null, index into `lookups.conferences` | null when CFBD reports no conference for the away side | SITE-21, SITE-25 |
| `bowl` | int \| null, index into `lookups.bowls` | non-null only for a game played at a named bowl; never set on a regular-season game; display name only, the raw CFBD note never ships | SITE-30 |

### `time_slot` boundaries

`time_slot` is derived from `kickoff`'s ET local time (D-20/D-26):

- **`noon`** — kickoff from **05:00** up to (but not including) **14:00** ET.
- **`afternoon`** — kickoff from **14:00** up to (but not including) **18:00** ET.
- **`prime`** — kickoff from **18:00** up to (but not including) **22:00** ET.
- **`late`** ("After dark") — kickoff at **22:00** ET or later, plus
  **00:00–04:59** ET for a game that kicks off after midnight (e.g. a Hawaii
  home game) — that game is an after-dark game, not "noon".
- **`null`** — kickoff time is unknown (`kickoff` is also null in this case).

### Crew role and feed

Each `crew` entry is `{ person: int, role, feed }`:

- **`role`** is `"pbp"`, `"analyst"`, or `"unknown"`. Sideline reporters are
  role `"unknown"` (out of scope as a filterable role, D-04) rather than a
  fourth role value; they're still linked to the telecast and searchable by
  name.
- **`feed`** is `"main"`, `"alt"`, or `"spanish"`. An alt-cast person on a
  combined figure (`combined_feeds` set) keeps feed `"alt"` so the person
  and role filters can include or exclude them (D-08) even though the dot
  itself is credited to the main-feed booth.

### Lookup tables (`lookups`)

- **`teams`**: `{ name }`.
- **`networks`**: `{ id, name, family }` — `family` groups a network's
  color (for example `"disney"`, `"fox"`, `"cbs"`, `"nbc"`, `"conference"`,
  `"other"`) for the at-most-8-color, colorblind-safe palette (SITE-01).
- **`people`**: `{ id, name, variants, usual_role }` — `id` is the D-01
  `person_id` slug, `variants` lists every name string seen for that person
  (canonical included), and `usual_role` is the D-03 inferred default.
- **`publishers`**: a flat list of publisher display names (SITE-17).
- **`flags`**: `{ id, kind, label, source_url }` — `kind` is `"era"`,
  `"event"`, `"measurement"`, `"model_break"`, or `"combined"`; `source_url`
  is null when a flag has no single citable source.
- **`bowls`**: `{ name, core }` — `name` is the official bowl name for that season with sponsor, `core` is the core bowl name and is always a substring of `name` (D-17/D-19). Never a raw CFBD note.
- **`conferences`**: `{ name, is_fbs }` — one entry per distinct conference
  name that appears as a plotted telecast's `home_conference` or
  `away_conference` (D-09). `name` is CFBD's own per-game conference string
  for that team in that season, so a team that changes conference (USC:
  Pac-12 through 2023, Big Ten from 2024) gets a different index in
  different seasons — no season-aware membership table is maintained here.
  `is_fbs` is `true` when any appearance of that conference name in the
  payload was on an FBS-classified side; the client's Conference filter
  lists only the `is_fbs` entries plus "FBS Independents" (D-10), while the
  detail panel may still display any conference, FBS or not.

### `freshness`

`{ season, crews_through_week, viewership_through_week }` — the two SITE-14
stamps ("crews through Week N" and "viewership through Week N") for the
current in-season build. `crews_through_week` and `viewership_through_week`
are null before either has a value.

### `coverage`

One `CoverageRow` per `(season, network)`, plus one season-total row per
season with `network` null: `season`, `network`, `rated_telecasts`,
`matched_game`, `matched_crew`, `match_rate` (null when there's nothing to
divide), `headline_present`, `excitement_present`, `pregame_present`,
`duplicate_merges`, `combined_figures`, and `publisher_counts` (a
publisher-name-to-count map). This is AUDIT-01's table, exposed to the site
for SITE-16.

## Display fields only — no bulk CFBD data (SITE-19)

Every model in `contract/models.py` sets `extra="forbid"`: a payload with
any field not listed above — a CFBD classification, venue,
`homeWinProbability`, or any other bulk field the chart doesn't show — fails
validation instead of shipping. `SITE_DATA_FIELDS` (in `models.py`) is the
literal allowlist of `telecasts` column names the real build (Plan 11) is
allowed to write. There is no bulk download of this file's contents beyond
what the chart displays, and the CFBD key never appears anywhere in this
file or in the build output that produces it.

Per-game conference names are the one CFBD field this contract now displays
(`home_conference`/`away_conference` via `lookups.conferences`): the detail
panel shows them (e.g. "Pac-12 vs Big Ten") and they drive the Conference
filter (D-09, SITE-21), under CFBD's 2026-09-25 approval to use its fields
in the interactive chart. `home_classification`/`away_classification`, the
raw CFBD `playoff` object, `venue`, and win probability still never ship —
only their derived, display-safe outputs (`game_type`, `playoff_round`, the
`is_fbs` flag) do.

## Versioning

`schema_version` follows a simple two-tier rule:

- **Adding a field, or adding a new value to an existing enum/Literal**,
  bumps the **minor** version — for example, `1.0.0` → `1.1.0` added
  `game_type`, `playoff_round`, `home_conference`, `away_conference`, and
  `lookups.conferences` (D-09/D-17); `1.1.0` → `1.2.0` added the `late`
  time_slot value (D-20); `1.2.0` -> `1.3.0` added `lookups.bowls` and
  `telecasts.bowl` (D-19).
- **Removing a field, renaming a field, or changing a field's type**
  (including narrowing an enum) bumps the **major** version (`1.0.0` →
  `2.0.0`).

Every change to `contract/models.py` regenerates `docs/site-data.schema.json`
by running:

```
uv run python -m booth_review.contract.schema
```

`tests/test_contract.py::test_schema_file_matches_models` fails the build if
the committed schema file and the current models ever disagree.

## Fixture

`tests/fixtures/contract/site-data.fixture.json` is a hand-written, fully
synthetic `SiteData` payload (invented teams, people, networks, and
publishers; `example.com` source URLs) that validates against these models.
Phase 4 can build the chart against this fixture immediately; Plan 11 later
validates the real build's output against the same models.

As of v1.1.0 the fixture also encodes: a USC-shaped conference change (the
team at index 0 plays in `home_conference`/`away_conference` index 4,
"Pac-12", in 2019 and index 0, "Big Ten", in 2025/2026); a bowl game at
telecast index 7 (a Saturday game with a prime-time kickoff, `game_type`
`"bowl"`); and a CFP semifinal at telecast index 5 (`game_type` `"playoff"`,
`playoff_round` `"semifinal"`).

As of v1.2.0 telecast index 2 has a 22:30 ET Saturday kickoff (`late`).

As of v1.3.0 telecast 7 (bowl) points at a sponsor-prefixed bowl and telecast 5 (CFP semifinal) at a sponsor-suffixed bowl; the CFP-not-at-a-bowl and unnamed-bowl cases are covered by route-mutated payloads in the e2e suite.
