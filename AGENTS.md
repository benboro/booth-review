# booth-review

Analysis of which broadcasters get the best college football games, and who draws
viewers beyond what the matchup predicts. `docs/PLAN.md` covers scope, sources, data
model, and build phases; read the relevant section before starting a phase.

# Public Repo Rules

- This repo is public. Never commit secrets. The CFBD API key lives in `.env`
  (gitignored); `.env.example` is the template.
- Everything under `data/` is gitignored except `data/README.md` and `data/reference/`.
  Never loosen these rules to commit scraped pages or API responses. `.gitignore`
  already carries `!data/processed/` then `data/processed/*` after `data/*`, so a
  derived table is published, once every source it draws on allows it (see the source
  table in `data/README.md`), by adding one `!data/processed/<file>` line below them;
  `tests/test_gitignore.py` checks the chain.
- GSD planning files (`.planning/`) and Fable task briefs (`fable-*.md`) are local and
  gitignored. Never commit them, and never commit the sections GSD generates (wrapped in
  its HTML-comment markers) in `AGENTS.md`; `CLAUDE.md` is a symlink to it, so tools that write `CLAUDE.md` edit
  `AGENTS.md`.
- Before every commit, check `git status` for staged data, cache, or `.env` files.

# Collecting Data

- Identify every request with the user agent
  `booth-review/<version> (+https://github.com/benboro/booth-review)`, and check the
  site's robots.txt before fetching.
- Send one request at a time, with a pause between requests. 506 Sports is a small
  fan-run site; keep its rate especially low.
- Cache every page and API response under `data/vault/raw/`, a local clone of the
  private data repo. Never re-fetch a cached response from a completed season. The one
  exception is Ratings Reference: `booth-review refresh ratingsref [--league nfl]`
  (also run by the scheduled job) re-fetches a record in any season, frozen ones
  included, when its sitemap `<lastmod>` advanced or the sitemap newly lists it. Each
  league has its own cap per run: at most 100 such fetches for college football and 40
  for the NFL, with current-season new records not counted and the rest carried over.
  A re-fetch overwrites the cached file; the vault's git history keeps earlier
  versions. When re-checking current-season data, send conditional requests (ETag /
  Last-Modified) where the source supports them.
- All requests go through the `booth-review collect` / `booth-review budget`
  commands, which apply the user agent, robots.txt, pacing, caching, and the CFBD
  budget. Never fetch with ad-hoc scripts, curl, or notebooks.
- 506 Sports blocks automated clients (403 Forbidden to booth-review's
  correctly-identified requests, confirmed 2026-09-25). Never work around this
  (no User-Agent changes, retries, or alternate request shapes). Instead, save
  its week pages by hand in a browser (any filename) and bring them into the vault
  with `booth-review import 506 --season <year> [--league nfl] [--from <folder>]`
  (default folder `data/incoming/506/cfb/` for college football and
  `data/incoming/506/nfl/` for the NFL; through the 2026 season the college-football
  import also reads pages left directly in `data/incoming/506/` and warns about them).
  The importer uses each saved file's modified time as its save time, so save pages
  from the browser straight into the league's folder (or copy with `cp -p`), since a
  plain copy resets that time. It identifies each page by its canonical link and
  title, validates it, and writes it to the same cache path and manifest shape a live
  fetch would.
- The scheduled job never fetches 506. It lists 2026 college-football and NFL week
  pages that are missing or were saved before their games finished (NFL weeks are
  checked against the nflverse schedule, never against 506); the user hand-saves those
  pages and imports them with
  `booth-review import 506 --season 2026 [--league nfl] [--force]`.
- Once the scheduled job is live, run `git -C data/vault pull --rebase` before a local
  collection command. Every `booth-review` command that writes to the vault holds a
  vault lock and commits only the paths it touched, so a local run and the job never
  clobber each other's in-progress files.
- The vault is private. Never copy its files into the public repo, test fixtures,
  commit messages, or logs; tests use synthetic 506 and CFBD fixtures.
- Ratings Reference: read the per-telecast JSON records (`/api/telecast/<id>.json`)
  instead of scraping HTML. Keep each row's record URL and the figure's original
  `source_url`; Ratings Reference's reuse terms ask for both.
- nflverse: fetch schedules from `raw.githubusercontent.com` and play-by-play through
  the GitHub REST API's release-asset endpoint on `api.github.com`
  (`booth-review collect nflverse`), never through github.com release-download links:
  github.com's robots.txt disallows `/*/download`. The client honors robots.txt
  wildcards (`*` and `$`).
- Wikipedia: read plain season articles (`/wiki/<title>`) with
  `booth-review collect wikipedia --league nfl`, never the `/w/` or `/api/` paths its
  robots.txt disallows. Its text is CC BY-SA 4.0; store only extracted facts with the
  article URL.
- Sports Media Watch: never collect with scripts; its robots.txt blocks them. Save
  its season ratings pages by hand in a browser ("Webpage, Complete", after scrolling
  so every chart loads) into `data/incoming/smw/<season>/`. Transcribe the chart
  images in Claude Code sessions, two independent passes per chart, with no OCR or
  image-parsing script; reconcile them with `booth-review review smw-diff` and
  `smw-merge`, then bring them into the vault with
  `booth-review import smw --season <year>`. Transcriptions are private vault files:
  never put them in the public repo, test fixtures, commit messages, or logs. Credit
  every figure to Sports Media Watch with its season-page link, and take its figures
  down if it objects.
- The TV Ratings Guide and Awful Announcing: collect only with
  `booth-review collect tvrg|aa --season <year>`, and only for 2021-2024 dates that
  still have an unrated game on ABC, CBS, NBC, FOX, ESPN, ESPN2 or FS1. A data pass
  needs a policy check from the last 30 days: `--policy-check` re-reads robots.txt
  and the site's terms into the vault's policy ledger, and `--confirm-terms` records
  that the user read the terms and they allow collection. If robots.txt or the terms
  now ban automated access, stop collecting from that site. Requests go at least 3 s
  apart (a longer robots Crawl-delay stops the run) and are capped per run with
  `--max-requests` (default 150); check the count with `--dry-run` first. Credit
  every figure with a link to the exact post it came from, and take a site's figures
  down if it objects.
- ESPN Press Room: never collect with scripts; Disney's Terms of Use ban automated
  access. Save its pages by hand in a browser (any filename) into
  `data/incoming/espnpr/`, or copy them there with `cp -p` to keep each file's save
  time, and bring them into the vault with `booth-review import espnpr` (`--force`
  replaces a page whose re-save changed). The importer identifies each page by its
  canonical link and body class and skips the category listing. The commentators
  schedule page shows only the current week, so the scheduled job lists that week
  when it is not saved yet; it never fetches the page. ESPN Press Room crews are a
  backup: a hand-confirmed override wins, then 506, then ESPN Press Room, and a backup
  crew never moves the "crews through week N" stamp. Its viewership figures rank last,
  behind Ratings Reference, Sports Media Watch, The TV Ratings Guide and Awful
  Announcing, and pass the same 3% Ratings Reference agreement gate. Credit every crew
  and figure with a link to the exact page it came from, and take ESPN Press Room's
  data down if ESPN objects.
- CFBD: the free tier allows 1,000 requests per calendar month. Count every call, and
  never call per-game endpoints such as `/metrics/wp` in bulk.

# Website

- The website serves only pre-built data files. All data is pulled ahead of time,
  server-side; viewing the page never sends a request to CFBD or any other data
  source, and the CFBD key never appears in site code or build output.
- CFBD's terms (updated Aug 12, 2026) bar providing API data as a standalone dataset
  or bulk download, so the site data file holds display fields only. CFBD confirmed
  (Sep 25, 2026) that its fields, including `excitementIndex`, may appear in the chart;
  any downloadable file may hold only our own analysis, never CFBD's fields in bulk,
  even reformatted. Credit "Data provided by CollegeFootballData.com" with a link.
- Second-source viewership figures (Sports Media Watch, The TV Ratings Guide, Awful
  Announcing and ESPN Press Room) are credited with the publisher's name linked to the
  page the figure came from, and the detail panel says the figure is not listed on
  Ratings Reference.

# Tooling

- Use uv for everything: `uv sync`, `uv run pytest`, `uv run ruff check .`,
  `uv run ruff format .`, `uv run mypy src`. Add dependencies with `uv add` or
  `uv add --dev`, not pip.
- Run the browser tests in parallel with `uv run pytest -m e2e -n 4` (pytest-xdist);
  drop `-n 4` or add `-p no:xdist` to debug a test serially.
- Do not prefix shell commands with `cd` to the repo root; the working directory is
  already the root.

# Conventions

- Use `pathlib` for all file and directory operations (enforced by ruff `PTH`).
- Use timezone-aware datetimes (enforced by ruff `DTZ`). 506 Sports lists kickoff
  times in ET.
- Team and announcer names differ across sources. Resolve them through the
  crosswalk tables in `data/reference/`, not with one-off string fixes in parsers.
