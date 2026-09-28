# site/vendor/

Self-hosted, pinned third-party JavaScript for the static site (D-14). No CDN is
loaded at runtime; the site never sends a request to any data source or third-party
host after page load.

## plotly-gl2d-4.1.1.min.js

- **Source:** https://cdn.plot.ly/plotly-gl2d-4.1.1.min.js
- **Version:** 4.1.1 (`gl2d` partial bundle — WebGL 2D chart types only, including
  `scattergl`). Must stay **≥4.1.1**: this is the first release with the
  `scattergl` per-point marker color fix the chart depends on.
- **License:** MIT (plotly.js, github.com/plotly/plotly.js)
- **Size:** 1,486,338 bytes
- **SHA-256:** `3db1f8ca5c906266bd6ab2eeeef9e3c1e3f45c5844529657c3525ec2ad7c77e4`
  (recorded in `plotly-gl2d-4.1.1.min.js.sha256`, sha256sum format)

Git is configured (`.gitattributes`: `site/vendor/*.js -text linguist-vendored`) to
never text-normalize this file, so its committed bytes always match the pinned
digest above.

## Re-vendoring procedure

To pick up a new Plotly.js `gl2d` release:

1. Download the new bundle:
   `curl -fsSL --proto '=https' -o site/vendor/plotly-gl2d-<version>.min.js https://cdn.plot.ly/plotly-gl2d-<version>.min.js`
2. Compute its digest (`sha256sum site/vendor/plotly-gl2d-<version>.min.js`) and
   confirm it against the upstream release before trusting it.
3. Update all four places that reference the old filename/digest together in one
   commit:
   - This README (source URL, version, size, digest)
   - `site/vendor/plotly-gl2d-<version>.min.js.sha256` (new file, sha256sum format)
   - `tests/test_site_vendor.py`'s `EXPECTED_SHA256` and `BUNDLE_PATH`/`DIGEST_PATH`
     filenames
   - `src/booth_review/build/site_assembly.py`'s digest constant (once that module
     exists) and `index.html`'s SRI attribute for the `<script>` tag
4. Delete the old `.js`/`.sha256` files so only the new pinned version remains.
5. Run `uv run pytest tests/test_site_vendor.py -q` to confirm the new digest checks
   out before committing.
