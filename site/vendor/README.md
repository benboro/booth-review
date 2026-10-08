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

## us-states-albers.js

- **Source:** us-atlas 3.0.1 `states-albers-10m.json` (npm, ISC, Michael Bostock;
  data from US Census Bureau cartographic boundary files). Hosts, byte-identical:
  https://cdn.jsdelivr.net/npm/us-atlas@3.0.1/states-albers-10m.json,
  https://unpkg.com/us-atlas@3.0.1/states-albers-10m.json, and
  `package/states-albers-10m.json` in https://registry.npmjs.org/us-atlas/-/us-atlas-3.0.1.tgz
  (tarball sha512 equals the registry `dist.integrity`). Source: 82,031 bytes,
  SHA-256 `6e7bb086a3c791490361968a3094f377f7726c5d0c4900fec03cc42db2305a3d`.
- **Derivation:** `ops/vendor/us_states_albers.py` (stdlib only, network-free) keeps
  the 50 states (Alaska dropped, D-14), rounds coordinates to 0.1 map unit, and writes
  an ES module (`.js`, because `COPY_SUFFIXES` excludes `.json`) exporting
  `US_STATES`. Pre-projected to 975x610 with Hawaii in its inset.
- **Regenerate:** download the three files into fresh scratch directories (never the
  repo), `cmp` them, check the tarball with
  `openssl dgst -sha512 -binary us-atlas-3.0.1.tgz | base64 -w0` against
  `jq -r .dist.integrity` of https://registry.npmjs.org/us-atlas/3.0.1, extract, then
  `uv run python -I ops/vendor/us_states_albers.py <scratch>/package/states-albers-10m.json site/vendor/us-states-albers.js`.
- **Size:** 113,435 bytes
- **SHA-256:** `ff1e0a82d121f389782ef3ff466fc2910a08b7594af9e92598ac4032a9e2d3dc`
  (recorded in `us-states-albers.js.sha256`)
- **License:** ISC. Copyright 2013-2019 Michael Bostock. Permission to use, copy,
  modify, and/or distribute this software for any purpose with or without fee is hereby
  granted, provided that the above copyright notice and this permission notice appear
  in all copies. THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL
  WARRANTIES (full text in the module header).
- **Attribution:** Contains US Census Bureau cartographic boundary data via us-atlas, ISC.
- **SRI:** does not apply (imported as a module, not a `<script src>`); the build-time
  check `MAP_GEOMETRY_SHA256` in `site_assembly.py` refuses a mismatched file.

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
     (and, for the map geometry, `MAP_GEOMETRY` / `MAP_GEOMETRY_SHA256`, its
     `.sha256` sidecar, and `GEOMETRY_*` in `tests/test_site_vendor.py`)
   - `site/index.html`'s `src` and SRI `integrity`
   - `tests/test_cli_site.py`'s tainted-bundle filename
4. Delete the old `.js`/`.sha256` files so only the new pinned version remains.
5. Run `uv run pytest tests/test_site_vendor.py tests/test_cli_site.py -q` and the
   scatter e2e tests (`uv run pytest -m e2e tests/e2e/test_site_chart.py -q`).
