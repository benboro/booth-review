# booth-review

Analysis of which broadcasters get the best college football games, and who draws
viewers beyond what the matchup predicts. `docs/PLAN.md` covers scope, sources, data
model, and build phases; read the relevant section before starting a phase.

# Public Repo Rules

- This repo is public. Never commit secrets. The CFBD API key lives in `.env`
  (gitignored); `.env.example` is the template.
- Everything under `data/` is gitignored except `data/README.md` and `data/reference/`.
  Never loosen these rules to commit scraped pages or API responses. A derived table
  can be published only if every source it draws on allows it (see the source table
  in `data/README.md`); publish it with an explicit `!data/processed/<file>` line in
  `.gitignore`.
- GSD planning files (`.planning/`) and Fable task briefs (`fable-*.md`) are local and
  gitignored. Never commit them, and never commit GSD-generated sections (marked
  `<!-- GSD:`) in `AGENTS.md`; `CLAUDE.md` is a symlink to it, so tools that write
  `CLAUDE.md` edit `AGENTS.md`.
- Before every commit, check `git status` for staged data, cache, or `.env` files.

# Collecting Data

- Identify every request with the user agent
  `booth-review/<version> (+https://github.com/benboro/booth-review)`, and check the
  site's robots.txt before fetching.
- Send one request at a time, with a pause between requests. 506 Sports is a small
  fan-run site; keep its rate especially low.
- Cache every page and API response under `data/raw/`. Never re-fetch a cached
  response from a completed season. When re-checking current-season data, send
  conditional requests (ETag / Last-Modified) where the source supports them.
- Ratings Reference: read the per-telecast JSON records (`/api/telecast/<id>.json`)
  instead of scraping HTML. Keep each row's record URL and the figure's original
  `source_url`; Ratings Reference's reuse terms ask for both.
- Sports Media Watch: never collect with scripts; its robots.txt blocks them. Use it
  only for manual spot checks.
- CFBD: the free tier allows 1,000 requests per calendar month. Count every call, and
  never call per-game endpoints such as `/metrics/wp` in bulk.

# Website

- The website serves only pre-built data files. All data is pulled ahead of time,
  server-side; viewing the page never sends a request to CFBD or any other data
  source, and the CFBD key never appears in site code or build output.

# Tooling

- Use uv for everything: `uv sync`, `uv run pytest`, `uv run ruff check .`,
  `uv run ruff format .`, `uv run mypy src`. Add dependencies with `uv add` or
  `uv add --dev`, not pip.
- Do not prefix shell commands with `cd` to the repo root; the working directory is
  already the root.

# Conventions

- Use `pathlib` for all file and directory operations (enforced by ruff `PTH`).
- Use timezone-aware datetimes (enforced by ruff `DTZ`). 506 Sports lists kickoff
  times in ET.
- Team and announcer names differ across sources. Resolve them through the
  crosswalk tables in `data/reference/`, not with one-off string fixes in parsers.
