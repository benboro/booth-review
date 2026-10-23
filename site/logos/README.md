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
- The manifest and this notice are not copied into the built site.
