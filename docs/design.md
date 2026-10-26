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

- When a filter is active, lead stars take the same outline as the enlarged dots, at the
  same weight: dark in light mode, light in dark mode.
- A game with no rating is an empty, open star, so the band shows through it (Phase 17).
  It stays empty when highlighted or when a filter outlines it: the highlight and the dot
  outline are larger open stars around it, never a filled halo or a background-coloured fill.
- CFB map dots are sized by games at the venue only: area is exactly proportional to
  games, with no minimum floor, and relative to the busiest venue in the filtered set, so
  narrowing a filter or picking an announcer rescales the dots. That venue is 20px across
  on desktop and 10px on a phone, and dots are drawn largest first. A dot under 12px gets an
  invisible 12px hit target so it stays hoverable. Under an announcer or crew pick, picked
  dots of every shape (circle, square, diamond, star) keep this size with no minimum, so none
  exceeds the maximum; they stand out only by their outline and the fading of the other
  dots. The key is one inline row at every width (circle, count, circle, count, circle, "N games", largest first, no leaders, no nesting). Circle sizes come from `venueDotSize` (desktop and phone) with the same busiest-venue reference as the dots, so its values
  change with the filters, showing size only, and venue colours are always on
  (Phase 17.1).
