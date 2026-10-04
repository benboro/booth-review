# data/reference/

This folder is public: `.gitignore` allows it explicitly, and every table
here is committed with the rest of the repo, unlike everything else under
`data/` (which lives in the private vault instead — see the top-level
`AGENTS.md`). Names, network mappings, and dated era boundaries are public
facts; who called which specific game is not, so no table here ever holds a
game-level row (D-05), with one documented exception: the hand-confirmed
crews in `crew_overrides.csv`, each cited to a public source that already
publishes it (04.3 D-01). Override tables hold pointers and reason codes only,
never a crew, a figure, or matchup text (D-06). Every table is read through
`reference.read_reference_csv`, which rejects a header that doesn't match
exactly, a row with extra columns, or a cell that could be read as a
spreadsheet formula, and every table listed below is checked by
`tests/test_reference_tables.py` (known files only, exact header, loads
through its own loader, no game-level column, and never accidentally
gitignored).

| File | Purpose | Columns | Edited by | Loader |
|---|---|---|---|---|
| `measurement_eras.csv` | The five dated Nielsen measurement eras this project tracks (FLAG-01), cross-checked against Ratings Reference's own `era_id` | `era_id, label, start_date, end_date, rr_era_ids, source_url, note` | Hand, during research/checkpoints | `flags.era.load_eras` |
| `event_flags.csv` | One-off dated events (a carriage dispute, a blackout window) and the CFBD win-probability model-break flag (FLAG-03/FLAG-04) | `flag_id, kind, label, start_date, end_date, season_from, networks, source_url, note` | Hand, during research/checkpoints | `flags.events.load_event_flags` |
| `team_crosswalk.csv` | Season-ranged team-name variants (506/Ratings Reference/CFBD spellings) mapped to one CFBD team id (JOIN-01) | `source, variant, canonical, cfbd_team_id, season_from, season_to, note` | Hand, from `resolve/diagnose.py`'s unresolved-name review | `resolve.teams.load_team_crosswalk` |
| `game_overrides.csv` | Hand-confirmed game-match decisions (a date-shift, an exclusion) for a specific 506 listing or Ratings Reference record pointer (JOIN-02) | `source, season, pointer, action, cfbd_game_id, reason` | Hand, from the unmatched-row review | `resolve.overrides.load_game_overrides` |
| `people.csv` | The person registry: one row per real person, a stable `person_id` (never renamed, D-01), every name variant, and their usual booth role | `person_id, canonical_name, variants, usual_role, role_override` | The people-grouping review tool (`people/registry.py`), hand-edited for `role_override` | `people.registry.load_people` |
| `people_reviewed.csv` | Name pairs a human confirmed are the same person or different people (D-02), so a re-run of grouping never re-asks | `name_a, name_b, reason, decision` | The people-grouping review checkpoint | `people.registry.load_reviewed` |
| `person_overrides.csv` | Hand-confirmed role/identity pointers for one crew slot (season, 506 pointer, position) that automatic grouping got wrong | `season, pointer, position, person_id, reason` | Hand, from the people review | `people.registry.load_person_overrides` |
| `networks.csv` | Outlet-string-to-network mapping and each network's rights-holder precedence tier (JOIN-06) | `variant, network_id, display_name, family, tier, feed_type, season_from, season_to, priority` | Hand, from the network-diagnose review | `resolve.networks.load_networks` |
| `primary_network_overrides.csv` | A per-game override of the rights-holder rule's own primary-network pick, for a neutral-site or bowl-game exception | `cfbd_game_id, network_id, reason` | Hand, from the primary-network review | `resolve.networks.load_primary_overrides` |
| `combined_figures.csv` | Hand-confirmed pointers marking a Ratings Reference figure as combined across simulcast feeds (D-09), since `composite_of`/`carrier_network` are never populated in this project's range | `rr_telecast_id, decision, feeds, reason` | Hand, from the combined-figure candidate review (`interim/review_combined.csv` in the vault); `alt_listed` candidates are pre-filled `combined` by `python -m booth_review.build.combined`, outlier-only candidates are left blank for the user | `build.combined.load_combined_figures` |
| `bowls.csv` | Display names for bowl games, keyed by CFBD game id: the official name for that season (sponsor included) and the core bowl name, plus whether the game was played at a bowl (D-17), and a `franchise` slug: a stable lowercase kebab id that groups a bowl across sponsor changes and renames (the site labels a franchise with its latest core name; slugs are never renamed once shipped, like `person_id`; empty exactly when `core_name` is empty) | `cfbd_game_id, official_name, core_name, at_bowl, franchise` | Hand, from the private vault review file `interim/review_bowls.csv` | `build.bowls.load_bowls` |
| `rivalries.csv` | Curated well-known named FBS rivalries: a stable kebab `rivalry_id`, the current name, the two teams by CFBD canonical name, and optional season limits. Only the first regular-season meeting of the pair in a season counts, so a conference-championship or postseason rematch is not the rivalry game (D-13) | `rivalry_id, name, team_a, team_b, season_from, season_to` | Hand, edited at the 04.9 review. Naming rule: when a rivalry name is shared with another rivalry, the lesser-known game's name carries its team abbreviations in parentheses joined by an en dash, e.g. `Governor's Cup (UK–LOU)` | `build.rivalries.load_rivalries` |
| `crew_overrides.csv` | Hand-confirmed main-feed booth crews for plotted telecasts 506 Sports does not list (every CFP national championship and other gaps), one row per crew member, each citing the public source that names the booth (04.3 D-01/D-02) | `cfbd_game_id, network_id, crew_position, person_id, role, reason, source_kind, source_name, source_url` | Hand, after the user accepts each proposal from the private vault draft (`interim/crew_overrides_draft.csv`), using the build's gap list `interim/review_crew_overrides.csv` | `build.crew_overrides.load_crew_overrides` |

## Rules every table here follows

- **Names-only, never game-level (D-05; sole exception `crew_overrides.csv`, below):** `people.csv`, `people_reviewed.csv`,
  `team_crosswalk.csv`, and `networks.csv` describe people, teams, and
  networks in the abstract — never which crew called which game, a viewer
  figure, or a headline value.
- **Override tables are pointers, not data (D-06; sole exception `crew_overrides.csv`, below):** `game_overrides.csv`,
  `person_overrides.csv`, `primary_network_overrides.csv`, and
  `combined_figures.csv` identify *which* record a hand decision applies to
  (a CFBD game id, a 506 season/week/row pointer, a Ratings Reference record
  URL or slug) plus a short reason code — never the crew names, matchup
  text, or figures behind that decision. `bowls.csv` is keyed by CFBD game id
  and holds only public bowl names reviewed by hand, never CFBD notes text;
  empty names with `at_bowl=true` mean the name is unknown.
- **One documented exception (04.3 D-01):** `crew_overrides.csv` records a
  telecast's main-feed booth only when a public source (network press
  release, school game notes, or a reputable outlet; never 506 Sports) names
  it; every row carries that `source_url`, roles come from the source, and
  `tests/test_reference_tables.py` allow-lists exactly this one table.
  Vocabularies: `reason` is `no-506-listing | no-506-crew | correction`,
  `source_kind` is `press-release | school | outlet`, `role` is
  `pbp | analyst`, with exactly one `pbp` row per telecast. The override
  always wins, but when 506 lists a different booth and the row's reason is
  not `correction`, `booth-review build` prints a warning citing the row's
  line (without blocking): mark it `correction` if the source is right, or
  fix the row if 506 is.
- **`person_id` values are never renamed (D-01):** a later name change is
  recorded as a new variant on the same `person_id`, never a rewrite of the
  id itself, since ids appear in shareable site URLs.
- **No formula-like cells:** every reader rejects a cell beginning with `=`,
  `+`, `-`, `@`, a tab, or a carriage return — the same protection a
  spreadsheet needs against formula injection.
- **Every table is guarded by a test:** `tests/test_reference_tables.py`
  fails the build if an unrecognized `data/reference/*.csv` file appears, if
  a known file's header drifts from its column constant, if its loader
  can't read it, or if a header re-introduces a game-level column name.

## A note on `combined_figures.csv`'s 12 CFP national championship rows

All 12 CFP national championship game rows in `combined_figures.csv` (`reason`
`title-game`) carry `feeds,2` as a documented *lower bound*, not a precise
feed count. Neither Ratings Reference nor 506 Sports lists every alt-cast
feed a MegaCast championship actually ran; ESPN reports its championship
audience as a single multi-feed total, and Ratings Reference has back-filled
an explicit `cut: combined` claim for only 2 of these 12 records. Rather than
guess a precise number or single out the 2 records with an explicit claim
for different treatment than the other 10, this project treats all 12 alike:
flagged combined (one dot, correctly excluded from a single-feed
network-season comparison), with `feeds,2` standing in for "at least 2, true
count unknown" (User checkpoint decision, Phase 3 Plan 9 Task 3). See
`docs/known-gaps.md` for the same caveat in the public-facing gaps page.

## A note on `event_flags.csv`'s `yttv-disney-blackout-2025` row

That row's `source_url` cites the ESPN carriage-deal report
(<https://www.espn.com/espn/story/_/id/46969585/disney-reaches-new-deal-youtube-tv-ending-blackout>).
The user archived a copy of that page on 2026-09-26:
<https://web.archive.org/web/20260926202646/https://www.espn.com/espn/story/_/id/46969585/disney-reaches-new-deal-youtube-tv-ending-blackout>.
