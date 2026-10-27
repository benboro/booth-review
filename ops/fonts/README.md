# Latin Modern Demi subset

Builds `site/fonts/lm-roman-demi-latin-600-normal.woff2`, the site's serif face, from GUST's
own Latin Modern Roman Demi 10.

- Source: https://www.gust.org.pl/projects/e-foundry/latin-modern/download/lm2.004otf.zip
- Zip SHA-256: `5b0236051d3728be6616f1b274e3b910473875b5a3ef9382f0ef00384ddb161b`
- OTF (`lmromandemi10-regular.otf`) SHA-256:
  `63b6f9528e6117c5b0c0b1992517696ae09d05e7ca3711df0e0409d9db6df32c`. TeX Live's copy under
  `/usr/share/texmf/fonts/opentype/public/lm/` is byte-identical.
- Licence: GUST Font License 1.0, shipped as `site/fonts/GUST-FONT-LICENSE.txt`
  (SHA-256 `5eb61bb836bb1845ef668717cb15b382e997748ce2629e4388cc5e4c3fa4e433`).

Command (offline; needs the dev dependencies fonttools and brotli). Unzip the OTF into an
empty directory outside the repo first:

    uv run python -I ops/fonts/build_lm_demi.py <lmromandemi10-regular.otf> \
        site/fonts/lm-roman-demi-latin-600-normal.woff2 \
        src/booth_review/build/serif_glyph_set.py

The script exits 2 on any source whose SHA-256 differs from the pin.

Notes:

- Glyphs: ASCII, U+00A0-017F, en and em dashes, curly quotes, ellipsis, and U+02BB.
- Latin Modern has no okina (U+02BB, as in Hawaiʻi), so its cmap entry is aliased to the
  U+2018 glyph before subsetting.
- The subset is renamed "Latin Modern Demi Subset" because the GUST Font License asks that
  modified files be renamed. Copyright and licence name records stay verbatim.
- `serif_glyph_set.py` is generated from the subset's cmap and feeds the build-time glyph
  guard (`booth_review.build.serif_glyphs`).
- The build is deterministic (head.modified is set to head.created).
- Output: 23,560 bytes, SHA-256
  `667737468c8b2a50e4b0b2c07ed5a426f88e27655205fe17bc8e4cb3996da2c1`.
