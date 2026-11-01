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
  exception is Ratings Reference: `booth-review refresh ratingsref [--league nfl|mlb]`
  (run by the scheduled job for college football and the NFL; MLB is hand-run only)
  re-fetches a record in any season, frozen ones included, when its sitemap `<lastmod>`
  advanced or the sitemap newly lists it. Each league has its own cap per run: at most
  100 such fetches for college football, 40 for the NFL and 40 for MLB, with
  current-season new records not counted and the rest carried over. For MLB, a record
  qualifies only if its game date falls inside the windows `booth-review mlb
  rr-backfill` stored (the 2014-2026 postseason and the 2026 regular season); nothing
  outside them is ever fetched, and without stored windows the MLB commands refuse to
  run.
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
  with `booth-review import 506 --season <year> [--league nfl|mlb] [--from <folder>]`
  (default folder `data/incoming/506/cfb/` for college football,
  `data/incoming/506/nfl/` for the NFL and `data/incoming/506/mlb/` for MLB; through
  the 2026 season the college-football import also reads pages left directly in
  `data/incoming/506/` and warns about them). For MLB, save the 2026 week pages and
  the 2025-2026 postseason round pages (WC, DS, CS, WS); 506 has no MLB round pages
  before 2025. `--inspect` reports each saved MLB file's layout and counts without
  importing.
  The importer uses each saved file's modified time as its save time, so save pages
  from the browser straight into the league's folder (or copy with `cp -p`), since a
  plain copy resets that time. It identifies each page by its canonical link and
  title, validates it, and writes it to the same cache path and manifest shape a live
  fetch would.
- The scheduled job never fetches 506. It lists 2026 college-football and NFL week
  pages that are missing or were saved before their games finished (NFL weeks are
  checked against the nflverse schedule, never against 506); the user hand-saves those
  pages and imports them with
  `booth-review import 506 --season 2026 [--league nfl] [--force]`. The job does
  nothing for MLB: after each 2026 MLB round ends, the user hand-saves its 506 page
  and imports it with `booth-review import 506 --season 2026 --league mlb [--force]`.
- Once the scheduled job is live, run `git -C data/vault pull --rebase` before a local
  collection command. Every `booth-review` command that writes to the vault holds a
  vault lock and commits only the paths it touched, so a local run and the job never
  clobber each other's in-progress files.
- The vault is private. Never copy its files into the public repo, test fixtures,
  commit messages, or logs; tests use synthetic 506 and CFBD fixtures.
- Ratings Reference: read the per-telecast JSON records (`/api/telecast/<id>.json`)
  instead of scraping HTML. Keep each row's record URL and the figure's original
  `source_url`; Ratings Reference's reuse terms ask for both. For MLB,
  `booth-review mlb rr-backfill` is a one-time backfill of only the 2014-2026
  postseason and the 2026 regular season; MLB records use calendar-year seasons, and
  an MLB season freezes on March 1 of the next year, so the late-2026 Retrosheet
  release can still be collected for 2026.
- nflverse: fetch schedules from `raw.githubusercontent.com` and play-by-play through
  the GitHub REST API's release-asset endpoint on `api.github.com`
  (`booth-review collect nflverse`), never through github.com release-download links:
  github.com's robots.txt disallows `/*/download`. The client honors robots.txt
  wildcards (`*` and `$`).
- Retrosheet: collect only with `booth-review collect retrosheet`, and only the
  downloads index page and the per-season CSV bundles (`/downloads/<year>/<year>csvs.zip`,
  one request per season from 2014) under `/downloads/` on www.retrosheet.org; never
  request `/gamelogs/` or `/boxesetc/`, the `plays.html` page, or any other path.
  Each bundle's CSV files are read locally from the zip. Completed seasons freeze once
  collected and checked; 2026 is collected only after Retrosheet's late-2026 release.
  Every page that shows Retrosheet-derived data carries: "The information used here was
  obtained free of charge from and is copyrighted by Retrosheet. Interested parties may
  contact Retrosheet at www.retrosheet.org".
- MLB relay crews (the user's exception to the collect-only rule, for the 2026 season
  only): a Claude Code session may read the fan schedule blog
  `tamirmoore.blogspot.com` with WebFetch to fill 2026 MLB crews that 506 does not
  list. Before the first request, the session identifies itself as the Phase 7 spike
  did: WebFetch sends its own identification and cannot send the project user agent,
  so the session writes the project name and repo URL, as the user agent string
  `booth-review/<version> (+https://github.com/benboro/booth-review)`, at the top of
  its session log and states there that the requests themselves did not carry it.
  Check its robots.txt first and stop if it disallows the posts; send one request at a
  time, at least 5 s apart, within the request count the user approves for that
  session. Transcribe only extracted facts (game, crew, post link, and the press page
  the post credits) into `data/incoming/mlb-relay/` and bring them into the vault with
  `booth-review import relay`; never save page copies, and never put the file in the
  public repo. The blog is never a `booth-review collect` source and never runs on a
  schedule. Credit every relayed crew with its blog post and the press page it cites.
- MLB Stats API (`statsapi.mlb.com`): never request it except through
  `booth-review collect statsapi`, which stays disabled until the user approves a
  single test request; it may serve 2026 lineups only, never in bulk and never for
  anything else. Any refusal (HTTP 406 or another 4xx) ends the route: no retries,
  user-agent or header changes, or other endpoints.
- Wikipedia: read plain articles (`/wiki/<title>`) with
  `booth-review collect wikipedia --league nfl|mlb`, never the `/w/` or `/api/` paths
  its robots.txt disallows. For the NFL that means the season articles and, with
  `--stadiums`, the stadium articles listed in `NFL_WIKIPEDIA_STADIUM_PAGES` (map
  coordinates only). For MLB that means the '<year> Major League Baseball
  postseason' articles from 2014 and the named broadcaster list pages only. Its text
  is CC BY-SA 4.0; store only extracted facts with the article URL.
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
- Awful Announcing feed watch (2026 college football season only): the Tuesday evening
  reminder run (21:30 ET and its 22:30 ET backup) may check AA's feed once per run for
  that week's college football announcing-schedule post, with the same feed check as
  `booth-review collect aa --feed` (project user agent, robots.txt, pacing, and
  conditional requests with ETag / Last-Modified). It reads only each entry's title,
  link, date and categories, keeps only the post link, and itself never parses or stores a
  post body or crew data; the response is never cached, and `ledger/aa_feed_watch.json`
  holds only the feed validators, the verified feed URL, each week's post link or a mark
  that its plain reminder went out (after which that week is not checked again, so it
  gets one comment), and the Friday and Saturday crews re-check slots already used. The
  feed is the `/schedules/feed/` category feed, or the site
  feed if a first `booth-review collect aa --feed --verify` request shows the category
  feed lacks the posts. It needs an AA policy check from the last 30 days with
  confirmed terms; when that is stale, or robots.txt now refuses the feed, the job
  skips the request, posts the plain reminder and asks for `--policy-check` and
  `--confirm-terms`. If robots.txt or the terms ban automated access, stop. It ends
  with the 2026 season.
- Awful Announcing crew posts (2026 college football season only): the scheduled job
  may fetch only the weekly college football announcing-schedule posts whose links the
  feed watch recorded in `ledger/aa_feed_watch.json`, and only through
  `booth-review collect aa --crews`.
  - **When:** it fetches a post on the Tuesday reminder run that finds it. It re-checks
    the post with conditional requests (ETag / Last-Modified) on the Friday 18:00 and
    Saturday 08:00 ET runs.
  - **How:** at most 2 AA requests per run (the feed and the post; the robots.txt check
    before them is not counted), at least 3 s apart, with the project user agent and
    robots.txt. A request that fails is never retried. Each response is cached under
    `raw/aa/crews/2026/`.
  - **Policy check:** it needs the same AA policy check as the feed watch: done within
    the last 30 days, with terms confirmed. When that check is stale, or robots.txt
    refuses the post, the run skips the fetch and says so in the reminder. If
    robots.txt or the terms ban automated access, stop.
  - **Data and credit:** the parsed crews are private vault data. The site credits each
    crew to its exact post, and AA's crews come down if AA objects.
  - It ends with the 2026 season.
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
- Network lineup pages (Phase 10 booth tiers): never collect with scripts; the FOX,
  CBS and NBC press sites ban scripts or block clients, and ESPN Press Room's terms ban
  automated access. Save each season's lineup announcement by hand in a browser into
  `data/incoming/lineups/<family>/` (disney, fox, cbs, nbc). A Claude session reads the
  saved pages and proposes rows for `data/reference/cfb_booth_ranks.csv`; the user
  confirms every row before it is added. Only the facts (family, season, rank,
  play-by-play, analyst, conference-network scope) and the page's public URL as
  `source_url` go into the repo; the saved pages are never committed or copied into the
  vault.
- CFBD: the free tier allows 1,000 requests per calendar month. Count every call, and
  never call per-game endpoints such as `/metrics/wp` in bulk.

# Website

- Site-specific design decisions (fonts, layout, filter accents, marks) live in
  `docs/design.md`; read it before any visual change.
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
- MLB views (behind `MLB_SITE_ENABLED`, off in production until the user signs off)
  credit 506 crews and networks to 506 Sports, each relayed crew to its blog post and
  the press page it cites, Wikipedia-derived crews and outlets under CC BY-SA 4.0 with
  the article link, and Retrosheet-derived lineups and excitement with Retrosheet's
  credit line. Take a source's data down if it objects; never contact 506's owners.

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
