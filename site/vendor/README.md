# site/vendor/

Self-hosted, pinned third-party JavaScript for the static site (D-14). No CDN is
loaded at runtime; the site never sends a request to any data source or third-party
host after page load.

## plotly-partial-4.1.1.min.js

- **Source:** built locally (2026-10-21, Phase 12 spike) from the plotly.js tag v4.1.1
  (commit `0aabc3c`) as a custom bundle with only the traces scatter, scattergl and bar,
  which is everything the site draws; the build steps are under "Re-vendoring procedure"
  below. No published package carries this trace set, so the digest can only be
  checked by rebuilding. Must stay **>=4.1.1**: the first release with the
  `scattergl` per-point marker color fix the chart depends on.
- **License:** MIT (plotly.js, github.com/plotly/plotly.js)
- **Size:** 1,457,503 bytes (replaced the 4,815,814-byte full bundle)
- **SHA-256:** `bdf808c7a31ad3510f4f0306cb2720f999b8386de2e97cd6400720f7401bd04d`
  (recorded in `plotly-partial-4.1.1.min.js.sha256`, sha256sum format)
- **SRI:** `sha256-vfgIx6Ma01EPTwMGyycg+Zm4OG3i6XzWQAcg90Ab0E0=`
- **Verify:** `sha256sum site/vendor/plotly-partial-4.1.1.min.js` and
  `openssl dgst -sha256 -binary site/vendor/plotly-partial-4.1.1.min.js | base64`.

Git is configured (`.gitattributes`: `site/vendor/*.js -text linguist-vendored`) to
never text-normalize this file, so its committed bytes always match the pinned
digest above.

### CSP exception

The sport page keeps `script-src 'self' 'unsafe-eval'`. The partial bundle logged
eight script-src violations without it in spike 005 and the cause was not
investigated; dropping `'unsafe-eval'` is deferred (CONTEXT D-12, deferred idea).
No external script source is allowed. `tests/test_site_vendor.py` asserts the
directive and this record.

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

1. Build the partial bundle in a new empty scratch directory outside the repo, with no
   install scripts run:
   ```
   git clone --depth 1 --branch v<version> https://github.com/plotly/plotly.js.git <scratch>/plotly.js
   git -C <scratch>/plotly.js rev-parse --short HEAD   # record the commit (v4.1.1: 0aabc3c)
   cd <scratch>/plotly.js
   npm ci --ignore-scripts
   npm run custom-bundle -- --traces scatter,scattergl,bar --out phase12
   ```
   (`--out phase12` is the name the pinned v4.1.1 build used; keep it when rebuilding
   that version.) Take the minified file the command reports writing under `dist/` and
   copy it out as `plotly-partial-<version>.min.js`. Use the Node.js LTS current at build
   time and record its version (`node --version`) in this README; the v4.1.1 build did
   not record one. Keep the trace list in step with every trace type the site draws.
2. Check the result before copying it into `site/vendor/`: a rebuild of the pinned
   version must reproduce the SHA-256 above byte for byte (`sha256sum`; if it does not,
   stop and find the difference, usually the Node or npm version). For a new version,
   record the new size, SHA-256 and SRI, and run the e2e tests in step 5 to confirm every
   trace draws.
3. Update all of these together in one commit:
   - This README (source URL, version, size, digest, SRI)
   - `site/vendor/plotly-partial-<version>.min.js.sha256` (sha256sum format)
   - `tests/test_site_vendor.py`'s `EXPECTED_SHA256`, `BUNDLE_PATH`, `DIGEST_PATH`
   - `src/booth_review/build/site_assembly.py`'s `PLOTLY_BUNDLE` / `PLOTLY_SHA256`
     (and, for the map geometry, `MAP_GEOMETRY` / `MAP_GEOMETRY_SHA256`, its
     `.sha256` sidecar, and `GEOMETRY_*` in `tests/test_site_vendor.py`)
   - `site/index.html`'s `src` and SRI `integrity`
   - `tests/test_cli_site.py`'s tainted-bundle filename
4. Delete the old `.js`/`.sha256` files so only the new pinned version remains.
5. Run `uv run pytest tests/test_site_vendor.py tests/test_cli_site.py -q` and the
   scatter e2e tests (`uv run pytest -m e2e tests/e2e/test_site_chart.py -q`).
