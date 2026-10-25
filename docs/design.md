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

## Chart marks

- When a filter is active, lead stars take the same outline as the enlarged dots, at the
  same weight: dark in light mode, light in dark mode.
- A game with no rating is an empty, open star, so the band shows through it (Phase 17).
  It stays empty when highlighted or when a filter outlines it: the highlight and the dot
  outline are larger open stars around it, never a filled halo or a background-coloured fill.
