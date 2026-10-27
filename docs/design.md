# Site design decisions

Design choices specific to this site. General style rules (typography, colour, chart
marks, tables, interaction) come from the owner's cross-project design brief; this file
records only where the site settles or applies them.

## Fonts

- The CSP forbids external font loading, so fonts are self-hosted from `site/fonts/`:
  Crimson Text 600 for headings, Roboto 400/600 for body and UI, and Roboto Condensed
  400 for plot-area text (picked 2026-10-21, Phase 12). Adding any other font file
  needs the owner's sign-off.

## Layout

- Desktop-first: about 1440px is the design target and the phone is a constraint. A
  desktop enhancement is never cut because it has no phone equivalent; the phone gets a
  working, uncluttered version of it (2026-10-21).
- Layout direction A (Phase 12): a top filter bar and view tabs, with each table at full
  width below its chart. Rejected: a left filter rail, and Savant-style stacked sections.
- Light mode is the default. Dark mode is reached by the theme toggle at the top right
  of the header, optically centred on the header links (Phase 17).
- The CFB, NFL and MLB pages share one visual system.
- This weekend is the sixth CFB tab and the fifth NFL tab (NFL behind its site flag): a
  control row (week stepper, day tabs), a one-line freshness stamp, the timeline grid, a
  collapsible Time TBA strip, the CFB ESPN+ and regional table, and a source line that
  credits only the sources the sport uses. Below 480px the grid becomes a list grouped by
  kickoff (Phase 18).
- The six view tabs stay on one row and scroll sideways inside their bar when the window is
  narrow, so the page never scrolls; the tab focus ring sits inside the tab so the bar does
  not clip it (Phase 18).

## Filters

- A filter control takes the accent only once it differs from its default. With
  Announcer and School both picked, both controls are accented; untouched controls stay
  neutral (Phase 12).

## Tables

- A network logo stands alone in its cell. The network-family dot is shown only when
  there is no logo (Phase 13).
- The NFL team "season by season" table is the one table with vertical rules: a 1px
  `--muted` rule on the left of Thursday night, Fox AGOTW, Special games and Flexed, with
  trimmed spanner rules over "Solo slots" and "Sunday windows" (Silver Bulletin is the
  reference). Every other table keeps booktabs rules (Phase 17.1).
- A header with a tooltip gets a dotted underline in `--muted` and no icon (Phase 17.1).

## Chart marks

- The NFL Special games bars have no value column at the right: the end markers carry
  each total (notes 15). The bars rank by their bright part: the categories the chips
  show and the Category filter keeps in focus, or the matched games under a pick.
- The NFL Special games hover lists one row per shown category with games, keyed by
  the legend chip's colour dot, the count right-aligned in tabular semibold figures.
  International (any window) and Flexed cut across the categories, so they show only
  while every chip is on.

- When a filter is active, lead stars take the same outline as the enlarged dots, at the
  same weight: dark in light mode, light in dark mode.
- A game with no rating is an empty, open star, so the band shows through it (Phase 17).
  It stays empty when highlighted or when a filter outlines it: the highlight and the dot
  outline are larger open stars around it, never a filled halo or a background-coloured fill.
- CFB map dots are sized by games at the venue only: area is exactly proportional to
  games, with no minimum floor, and relative to the busiest venue in the filtered set, so
  narrowing a filter or picking an announcer rescales the dots. That venue is 20px across
  on desktop and 10px on a phone, and dots are drawn largest first. A dot under 12px gets an
  invisible 12px hit target so it stays hoverable (Phase 17.1).
- Under an announcer or crew pick, picked dots of every shape (circle, square, diamond,
  star) keep this size with no minimum, so none exceeds the maximum; they stand out only by
  their outline and the fading of the other dots. Only the picked dots and the key use the
  busiest picked venue as the reference. The other venues' dots keep their size from the
  map without the pick, where its busiest venue is at the maximum, and are drawn faded; they
  are never capped at the picked scale (Phase 17.1).
- The map key is one inline row at every width: circle, count, circle, count, circle,
  "N games", largest first, with no leaders and no nesting. Its circle sizes come from
  `venueDotSize` (desktop and phone) with the same busiest-venue reference as the dots, so
  its values change with the filters. The key shows size only; venue colours are always on
  (Phase 17.1).

- The This weekend timeline is plain DOM, not a chart: rows follow network precedence in
  a 96px label column, the time scale runs 80-120 px/hour (80, not the spec's 88,
  so a 15-hour day fits at 1440), cells are 44px tall on a 48px
  row pitch, and a game's block is 3h30 long for CFB and 3h15 for NFL (Phase 18). A day
  narrower than the module (the 120 cap, or floor rounding) stretches its lane to the
  module edge and runs the hour ticks on to the lane's end or midnight, so the rules never
  stop mid-module; a longer day keeps its scroll width (v2.1 polish, 18-UI-REVIEW 9, 11).
- A day tab's count box keeps a min-width of one ch per character of the day's full count,
  so the count a pick adds never widens the tab or moves the next one. The legend chip row
  and the Matched games section hide under This weekend, as on Crews and the NFL page, and
  on the phone the empty chart-tools row goes too (v2.1 polish, 18-UI-REVIEW 4, 5, 7, 10).
- On a phone the Map also drops the chart-tools row (its concealed scatter controls and
  dead Reset zoom made a blank band above the map), the map box follows the map's own
  975:610 aspect ratio instead of the desktop's 520px, and the dot-size key sits in flow
  under the map. So the 04.18 D-09 "nothing moves between Scatter and Map" rule holds in
  full on desktop only; on a phone the panel top moves up by that row and the filter row
  still never moves (v2.1 todo 2026-10-25-phone-map-blank-bands).
- A panel opened from a This weekend cell writes its kickoff as the view does (`Sat. Oct.
  31, 12:00 pm ET`, AP style) and credits the crew as `Crew from 506 Sports ↗` in both
  sports; the same game opened from the Matched games table keeps the site's long date
  form (18-UI-REVIEW 8).
- Cell states: a known crew is a solid network-family fill, deepened toward black until
  white text on it reaches 7:1 (the mid-tone fills read poorly with black text; user
  sign-off 2026-10-26); Crew TBA and not-listed
  cells use a 0.18 family tint with a 4px family edge, and never `--muted` text on a
  tint (Phase 18).
- Under a pick, non-matching cells fade to 0.3 and matching cells get an inset 2px `--ink`
  ring with a `--bg` keyline. This is a user-approved deviation from the accent ring in
  the Phase 18 context (D-21), because the ring has to read over every family fill in both
  themes (Phase 18).
- The Now line (1px, `--accent`, labelled "Now") is the one use of the accent in this
  view that is not a focus or changed-filter state; lead stars follow the stars rule above
  (Phase 18).

- Weekend map (Phase 24): the This weekend tab has a Timeline | Map switch (default Timeline,
  URL `wview=map`), one segmented control left of the week stepper (32px visually, a 44px
  tap area on a phone). The map shows one dot per placed game in its network-family colour
  with a 1.5px keyline in the page colour; the colour comes from the CFB Map's family
  palette, deepened toward black where a family falls under 3:1 on the land. The kickoff
  window is the shape: CFB circle (noon), square (afternoon), diamond (prime), triangle
  (late); NFL circle (early), square (late), diamond (night and standalone); a Time TBA
  game is an open ring in its family colour, still listed in the Time TBA strip. Games at
  one venue sit in a centred row, wrapping at four, never stacked. A game abroad is an edge
  marker in the same shape, labelled by city once per site. A game with no venue is listed
  under "Not on the map (n)", and a CFB ESPN+ game with a venue is dotted and also stays in
  the compact table.
- The weekend map's shading is the light game-count splat: one game weighs 1 and viewers
  count for nothing, so the dots stay the data. Current values (`MAP_SPLAT_WEEKEND` in
  palette.js; the CFB Map is 0.88): max opacity 0.4, spread 25, solid percentile 80. 24-11
  tunes these in the critique renders; update this line then.
- Under a pick the map fades non-matching dots to 0.15 (a dot has no text to keep readable,
  so lower than the timeline's 0.3) and rings matches with a 2px `--ink` ring over a 3px
  page-colour keyline; the splat follows the matching games only. This is the same ring and
  fade rule as the timeline cells, in the dot's own terms.
- The colour and shape key sits in flow under the map (never overlaid), listing only the
  windows and families present that day; it is not a filter. On a phone the map is fixed
  (no zoom or pan) at the map's own 975:610 ratio, the dots shrink (8 to 12px) and keep a
  12px hit target, and a tap works as on the CFB Map: the first tap shows the game card with
  a 1px ring on the mark and a full-width 44px `Open game` button, the second tap or the
  button opens the panel, and a tap on the background clears only the card. A pointer that
  can hover (a mouse at phone width) opens on the first click, with no button.
- The map has no keyboard path of its own: the Timeline is the keyboard-accessible twin, and
  the map's label says so. A panel opened from the map returns focus to the Map segment.
- NFL map mode adds a stadium-location credit to the source line (Wikipedia, CC BY-SA 4.0).
  The "stadium locations" link points at data/reference/nfl_stadium_locations.csv, whose
  source_url column cites each stadium's Wikipedia article.
