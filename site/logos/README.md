# Network logos

These SVG files are trademarks owned by their networks. They are shown only to
identify each network in the site's tables, panels and tooltips, and they are not
covered by this repository's MIT license.

- `manifest.csv` records, for each file, its source page, retrieval date, licence
  (PD-textlogo, or the English Wikipedia equivalent for Big Ten Network), the mark
  type, the render box (wordmark 14 px high, badge 20 px high) and a SHA-256 digest.
- Each file was saved by hand from a Wikimedia Commons or English Wikipedia file
  page and approved by the user on 2026-10-22. Nothing here was fetched by a script.
- The only edits are an added `viewBox` on four files (ABC, ESPN wordmark, FS2,
  SEC Network), equal to the file's existing width and height, and the removal of
  the unused SVG 1.1 `DOCTYPE` line from the CBS file so it passes the lint. Line
  endings are normalised to LF.
- Logos are rendered only through `<img>`, so no script inside a file can run.
- Dark-theme variants are generated at build time by
  `src/booth_review/build/logos_dark.py` into `logos/dark/<name>.svg` (same viewBox,
  width and height; light marks recoloured, nothing else changed). The sources here are
  never edited, the manifest's `dark_sha256` column records each generated file's hash,
  and the trademark notice is unchanged.
- The manifest and this notice are not copied into the built site.

# Conference logos

The conference marks are trademarks owned by their conferences. They are shown only to
identify each conference in the game panel, the filter list and the hover card, and they
are not covered by this repository's MIT license.

- The files live in `conf/` with their own `conf/manifest.csv`. It has the network
  manifest's columns plus `conference`, `seasons_from`, `seasons_to` (empty for the
  current logo) and `edit`.
- Each file was saved by hand by the user and approved by the user on 2026-11-03.
  Nothing here was fetched by a script.
- Edits, all recorded in the `edit` column: Big 12 gained a `viewBox` (its source has
  none); the Pac-12 2026 mark's `viewBox` was tightened to its content; the Pac-12 shield
  used before 2026 was derived from the Pac-12 Network 2012 file by removing its NETWORK
  lettering and tightening the box. That file has no source page, so its `source_url`
  says so. The MAC file was cropped at the user's request: its lettering below the
  shield was removed and the box tightened to the shield.
- Dark-theme variants are built into `logos/dark/conf/<name>.svg` the same way as the
  network variants, and `dark_sha256` records each one's hash.
- A game shows the logo its conference used in that game's season: SEC changes logo in
  2024, Conference USA in 2023 and the Pac-12 in 2026. Every other conference uses one
  logo for all games. `site/modules/conf-logos.js` holds the season ranges.
- Before any other conference gets a second logo, ask the user for a ruling: one logo for
  all games, or a season range per logo (D-10).
- FBS Independents, FCS Independents and every FCS conference are shown as text. No FCS
  logos are collected (D-11).
- A conference's logo comes down if the conference objects.
