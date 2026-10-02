# site/vendor/

Self-hosted, pinned third-party JavaScript for the static site (D-14). No CDN is
loaded at runtime; the site never sends a request to any data source or third-party
host after page load.

## plotly-4.1.1.min.js

- **Source:** https://cdn.plot.ly/plotly-4.1.1.min.js (mirror, byte-identical:
  https://cdn.jsdelivr.net/npm/plotly.js-dist-min@4.1.1/plotly.min.js)
- **Version:** 4.1.1 full dist bundle, kept for both `scattergl` (scatter) and `bar`
  (Bars and Butterfly tabs, Phase 04.4). Must stay **>=4.1.1**: this is the first
  release with the `scattergl` per-point marker color fix the chart depends on.
  It replaced the `gl2d` partial bundle, which has no `bar` trace.
- **License:** MIT (plotly.js, github.com/plotly/plotly.js)
- **Size:** 4,815,814 bytes (about 1.47 MB gzipped)
- **SHA-256:** `3b6e15d45dbb7fca5bd2094291e961ddc5472cd887009e6009a56dab668d721f`
  (recorded in `plotly-4.1.1.min.js.sha256`, sha256sum format)
- **SRI:** `sha256-O24V1F27f8pb0glCkelh3cVHLNiHAJ5gCaVtq2aNch8=`

Git is configured (`.gitattributes`: `site/vendor/*.js -text linguist-vendored`) to
never text-normalize this file, so its committed bytes always match the pinned
digest above.

## Re-vendoring procedure

Any new vendored file stops at a user-approval checkpoint first.

1. Download to a scratch directory outside the repo:
   `curl -fsSL --proto '=https' -o <scratch>/plotly-<version>.min.js https://cdn.plot.ly/plotly-<version>.min.js`
2. Verify the digest against an independent second host (jsDelivr
   `plotly.js-dist-min@<version>`, compare with `cmp`) before copying into
   `site/vendor/`.
3. Update all of these together in one commit:
   - This README (source URL, version, size, digest, SRI)
   - `site/vendor/plotly-<version>.min.js.sha256` (sha256sum format)
   - `tests/test_site_vendor.py`'s `EXPECTED_SHA256`, `BUNDLE_PATH`, `DIGEST_PATH`
   - `src/booth_review/build/site_assembly.py`'s `PLOTLY_BUNDLE` / `PLOTLY_SHA256`
   - `site/index.html`'s `src` and SRI `integrity`
   - `tests/test_cli_site.py`'s tainted-bundle filename
4. Delete the old `.js`/`.sha256` files so only the new pinned version remains.
5. Run `uv run pytest tests/test_site_vendor.py tests/test_cli_site.py -q` and the
   scatter e2e tests (`uv run pytest -m e2e tests/e2e/test_site_chart.py -q`).
