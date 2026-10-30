# Site design decisions

Design choices specific to this site. General style rules (typography, colour, chart
marks, tables, interaction) come from the owner's cross-project design brief; this file
records only where the site settles or applies them.

## Fonts

- The CSP forbids external font loading, so fonts are self-hosted from `site/fonts/`:
  Latin Modern Roman Demi 10 at weight 600 for every heading, Roboto 400/600 for body and
  UI, and Roboto Condensed 400 for plot-area text. Roboto and Roboto Condensed were picked
  2026-10-21 (Phase 12). Adding any other font file needs the owner's sign-off.
- The serif is Latin Modern Roman Demi 10, picked by the owner on 2026-10-27 (Phase 26
  sketch round 1b; CMU Serif Bold Non-extended was the runner-up). It replaces the earlier
  serif in every heading slot. Headings are 22px, the display title is 27px, and the phone
  site title is 20px, the sanctioned fifth size beside 12, 14, 22 and 27 (the earlier
  headings sat one step lower).
- Source: GUST's own `lm2.004otf.zip`
  (https://www.gust.org.pl/projects/e-foundry/latin-modern/download/lm2.004otf.zip),
  SHA-256 `5b0236051d3728be6616f1b274e3b910473875b5a3ef9382f0ef00384ddb161b`; the OTF
  inside (`lmromandemi10-regular.otf`) is
  `63b6f9528e6117c5b0c0b1992517696ae09d05e7ca3711df0e0409d9db6df32c`.
- Licence: GUST Font License 1.0, shipped beside the font as
  `site/fonts/GUST-FONT-LICENSE.txt` (SHA-256
  `5eb61bb836bb1845ef668717cb15b382e997748ce2629e4388cc5e4c3fa4e433`, stored with its
  published CRLF line endings). The footer credits Latin Modern under it.
- The shipped file is a subset: ASCII, U+00A0-017F, the en and em dashes, curly quotes,
  the ellipsis and U+02BB (323 codepoints, 23,560 bytes, SHA-256
  `667737468c8b2a50e4b0b2c07ed5a426f88e27655205fe17bc8e4cb3996da2c1`). Because the GUST
  licence asks that modified files be renamed, the family is "Latin Modern Demi Subset"
  inside the file; CSS calls it "Latin Modern Demi".
- Latin Modern has no okina (U+02BB, as in Hawaiʻi), so the subset aliases U+02BB to the
  U+2018 glyph. Four other codepoints (U+0138, U+0149, U+0166, U+0167) have no glyph in
  the source either; no team or person name uses them.
- `font-synthesis: none` is set, so a missing weight is never faked. The recipe that builds
  the subset is committed at `ops/fonts/` (offline; dev-only fonttools and brotli), and the
  data build checks every serif-slot name against the subset's glyphs and fails when one
  would fall back to another face.

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
- Ground (Phase 26, owner's pick 2026-10-27, option c, green-gray): light page `#F5F7F6`,
  surface `#EBEFED`, rules `#DAE0DD` and `#C0C9C5`, land `#E8EDEA`, ink `#1E2321`, muted
  `#5A6460`, disabled `#8E9894`. The teal accent `#1B4F5C` stays. Dark is derived from the
  same hue: page `#191D1C`, surface `#212625`, ink `#E5EAE8`, muted `#9EA8A4`, rules `#333A38`
  and `#434B48`, accent `#68BACB`. The "no games" legend label has its own token,
  `--legend-none` (`#687270` light, 4.6:1; `#87918D` dark, 5.2:1). A dark page prints with the
  light tokens.
- Chrome is "Frame + recede" (the T3 sketch, picked 2026-10-27): an ink rule only under the
  title row, over the footer and on the top of panels, drawn at 2px (the owner's call: a
  1.5px border draws as 1px in Chromium); module borders, chips and segmented controls use
  the lightest 1px rule; a selected segment is a light fill with a 2px ink underline;
  panels and tooltips sit on the page colour with a 4px radius. Modules pad 20/24px (16px
  at 480px and under) with 32px between modules.
- Spacing and size exceptions the owner confirmed in the sketches: an 18px column gap in the
  legend, 10px legend marks, a 5px filter caret, and 2px lines.
- The header is one row at every width. From 481 to 767px it drops the Methodology and
  Coverage links (the footer nav carries them, as on a phone), and below 600px the title
  takes the 22px heading size and the sport-switch buttons half their side padding, so the
  27px title never wraps beside CFB, NFL and MLB (Phase 26 critique).
- Methodology tables sit in a `.table-scroll` box and long code strings wrap, so a static
  page never scrolls sideways on a phone (Phase 26 critique).
- The six view tabs stay on one row and scroll sideways inside their bar when the window is
  narrow, so the page never scrolls; the tab focus ring sits inside the tab so the bar does
  not clip it (Phase 18).

## Filters

- The CFB filter bar is a ledger (Phase 26, owner's pick 2026-10-27: the ledger line combined
  with grouped boxes). Entries are boxless: a small label over the value, in three groups
  with small sentence-case labels and a 1px column rule between them: Broadcast (Announcers,
  Networks, Booth, Role), Matchup (Conference, School, Game) and Calendar (Seasons, Kickoff,
  Bowls/Playoffs). Group widths are fixed at 40/30/30%, so the bar is one 82px row from
  1280px, two rows from 768px, three rows from 481px, and gone at 480px and under (the
  phone panel replaces it). A long pick truncates inside its entry and never moves a rule.
- Entry states: neutral (default word in ink), changed (the pick in the accent at 600 with a
  2px accent line), open (2px ink line), and greyed (`--disabled`, not-allowed). On This
  weekend the Calendar group and Game grey out. The value line reads a default word ("All",
  "Any"), the pick itself, the first pick plus a count ("Big Ten +1"), or "N people" in
  compare mode; the Seasons entry shows a range. The Networks entry lists the checked
  network names, not a count. The old reserved fit-measuring script (`toolbar-fit.js`) is
  retired because no bar is measured any more.
- The count line replaces the Phase 12 selection row, which is gone. It is one fixed-height
  band (32px from 1104px, two 32px rows below, one 24px line on a phone) with the count and
  its detail on the left and the actions on the right; "Clear all filters" is always last and
  anchored right, so nothing shifts. Person chips (shape key, name and ×) appear on the count
  line only in compare mode. With four or more people the toggles switch to short labels:
  Compare, Together and "Clear people"; the long accessible names are unchanged. The long
  labels show only from 1280px with three people or fewer.
- Legend chips are a colour mark plus a label with no outline: on is filled, off is an empty
  ring, no games is a dotted ring. The off and no-games labels reach 4.5:1.
- Phone: one "Filters (N changed)" button, a fixed one-line summary, and a Filters panel
  grouped Broadcast, Matchup and Calendar like the bar, so picks never push the page down.
  The people strip (chips, then Compare people, Called together and Clear selection) sits
  under the Announcers heading, and the changed-filter chips live in the panel as a fixed
  strip. A chip reads "Announcers: A, B" when it fits and "Announcers (2)", the filter name
  plus the count, when it would truncate or wrap; it never carries a middle dot.
- The sketch rounds were picked on 2026-10-27: round 3 chose the ledger line with grouping,
  and round 3b confirmed the 40/30/30 widths, the no-game label colours and the phone panel.
- A filter control takes the accent only once it differs from its default. With
  Announcer and School both picked, both controls are accented; untouched controls stay
  neutral (Phase 12).

- The NFL bar is the same ledger: Broadcast (Announcers 250px, Booths), Matchup (Team, Category)
  and Calendar (Seasons), 148px entries, one row from 1024px, and the same count line and phone
  panel. NFL has no compare mode, so its count line never shows person or booth chips on desktop
  (the pick already shows its name); the phone Filters sheet keeps them in its people strip; MLB has no bar and takes the count line's chip shape, and its Matched games sits in the same module frame as CFB's (Phase 26).

## Copy

- No middle-dot meta strings (Phase 26, owner's call 2026-10-27). Lists join with commas,
  and a second clause follows a semicolon in lowercase (`Schedule: nflverse; crews: 506
  Sports; networks: Wikipedia (CC BY-SA 4.0)`). The footer links are spaced, the freshness
  line uses a semicolon, each credit sits on its own line, and page titles separate with a
  colon or hyphen.
- The one kept dot is the crew pair in a booth ("Fowler · Herbstreit"). Exactly three code
  spots use it (the crew separator, the booth line and the read-aloud replace), and a test
  fails on any other middle dot in site code or built pages.
- Dates in tooltips and panels follow AP style (`Sept.`, lowercase `pm`, no dot between
  parts). View code builds the page with `createElement` and `textContent`; a test fails on
  any `innerHTML`.

## Tables

- A network logo stands alone in its cell. The network-family dot is shown only when
  there is no logo (Phase 13).
- The NFL team "season by season" table is the one table with vertical rules: a 1px
  `--muted` rule on the left of Thursday night, Fox AGOTW, Special games and Flexed, with
  trimmed spanner rules over "Solo slots" and "Sunday windows" (Silver Bulletin is the
  reference). Every other table keeps booktabs rules (Phase 17.1).
- A header with a tooltip gets a dotted underline in `--muted` and no icon (Phase 17.1).

## Chart marks

- Viewer counts in tooltips, panels and other prose carry at most one decimal and no trailing
  zero ("220K", "1.1MM", "1MM"); tables keep their even one-decimal form ("220.0K"). The
  CFB prose form is `formatViewersProse` (`formatAudienceShort`); NFL and MLB use
  `formatMillionsProse`, which rounds exactly as their tables do and then drops the zero
  (26-10 sign-off).

- The CFB Bars and the NFL Special games bars have no value column at the right: the end
  markers carry each total, and the hover repeats it (notes 15; CFB Bars at the 26-10 sign-off). The bars rank by their bright part: the categories the chips
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

- This weekend (user 2026-10-30): booth lines show full names (a last-word surname showed
  "III" and "Jr."), CFB rows put FOX, ABC, ESPN, NBC and CBS first and the rest in network
  precedence, and the four CFB lead booths get a 3px inset gold frame (`--lead-frame`, both
  themes; the ink hairline was hard to see in light mode, and 3px holds on CBS's gold-brown). The frame is inset because an outside
  outline hides under the sticky axis and row heads; a pick's heavier ring replaces it. Module
  subtitles sit on the title's baseline.
- The This weekend timeline is plain DOM, not a chart: rows follow network precedence in
  a 96px label column, the time scale runs 80-120 px/hour (80, not the spec's 88,
  so a 15-hour day fits at 1440), cells are 44px tall on a 48px
  row pitch, and a game's block is 3h30 long for CFB and 3h15 for NFL (Phase 18). A day
  narrower than the module (the 120 cap, or floor rounding) stretches its lane to the
  module edge and runs the hour ticks on to the lane's end or midnight, so the rules never
  stop mid-module; a longer day keeps its scroll width (v2.1 polish, 18-UI-REVIEW 9, 11).
- A day tab always shows a count: the day's games with no pick, its matches under a pick
  (Phase 24 sign-off). The count box keeps a min-width of one ch per character of the day's
  full count, so a pick's count never widens the tab or moves the next one. The legend chip row
  and the Matched games section hide under This weekend, as on Crews and the NFL page, and
  on the phone the empty chart-tools row goes too (v2.1 polish, 18-UI-REVIEW 4, 5, 7, 10).
- On a phone the Map also drops the chart-tools row (its concealed scatter controls and
  dead Reset zoom made a blank band above the map), the map box follows the map's own
  975:610 aspect ratio instead of the desktop's 520px, and the dot-size key sits in flow
  under the map. So the 04.18 D-09 "nothing moves between Scatter and Map" rule holds in
  full on desktop only; on a phone the panel top moves up by that row and the filter row
  still never moves (v2.1 todo 2026-10-25-phone-map-blank-bands).
- A panel opened from a This weekend cell writes its kickoff in AP style (`Sat. Oct. 31,
  12:00 pm ET`) and credits the crew as `Crew from 506 Sports ↗` in both sports. Since Phase
  26 the Matched games table panel and the tooltip use the same AP form with the year
  (`Sun. Sept. 7, 2025, 1:00 pm ET`, no dot), which supersedes the long date form of the
  18-UI-REVIEW 8 note.
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
  palette, deepened toward black where a family falls under 3:1 on the land. The deepening
  lives in the shared `MAP_FAMILY_COLORS`, so the CFB Map's light-theme family colours (dots,
  splat, tooltip, legend) shifted slightly on purpose for that 3:1 rule (fox #009E73 to
  #009B71, cbs #B77F00 to #B57E00, nbc #C972A2 to #C16D9C, cw #1D96DB to #1C90D2, other
  #8B8B8B to #888888); dark is unchanged. Phase 26 then re-derived the light set against the
  green-gray land by the same deepen rule: fox #009970, cbs #B37C00, nbc #BF6C9A, cw #1C8FD0,
  other #878787 (disney, wbd and conference are unchanged). The chart's own light FOX and CBS
  (`FAMILY_COLORS.light`) took the same #009970 and #B37C00 in the Phase 26 panel, so they hold
  3:1 on the unrated strip's SURFACE (3.13 and 3.12) and the page ground; NBC and Other on that
  strip were already under 3:1 on the old ground and rely on the 2px ring rule. The kickoff
  window is the shape: CFB circle (noon), square (afternoon), diamond (prime), triangle
  (late, Plotly `arrow-up` lifted half its size by `standoff`, so the map draws the key's
  even triangle centred on the venue, not Plotly's flatter `triangle-up`; user 2026-10-30); NFL circle (early), square (late), diamond (night and standalone); a Time TBA
  game is an open ring in its family colour, still listed in the Time TBA strip. Games at
  one venue sit in a centred row, wrapping at four, never stacked. A game abroad is an edge
  marker in the same shape, labelled by city once per site. A game with no venue is listed
  under "Not on the map (n)", and a CFB ESPN+ game with a venue is dotted and also stays in
  the compact table.
- The weekend map's shading is the light game-count splat: one game weighs 1 and viewers
  count for nothing, so the dots stay the data. Final values (`MAP_SPLAT_WEEKEND` in
  palette.js; the CFB Map is 0.88), kept after the 24-11 real-data renders: max opacity 0.4,
  spread 25, solid percentile 80. Dot sizes (`WEEKEND_MAP_DOT`) and the open Time TBA ring
  (no `x` fallback needed: it reads as a thin family-colour ring, never as the dark ink pick
  ring) were also kept.
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
