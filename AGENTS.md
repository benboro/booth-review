# booth-review

Analysis of which broadcasters get the best college football games, and who draws
viewers beyond what the matchup predicts. `docs/PLAN.md` covers scope, sources, data
model, and build phases; read the relevant section before starting a phase.

# Public Repo Rules

- This repo is public. Never commit secrets. The CFBD API key lives in `.env`
  (gitignored); `.env.example` is the template.
- Everything under `data/` is gitignored except `data/README.md` and `data/reference/`.
  Never loosen these rules to commit scraped pages or API responses. Publishing a
  derived table requires confirming the sources' terms first, then adding an explicit
  `!data/processed/<file>` line to `.gitignore`.
- Before every commit, check `git status` for staged data, cache, or `.env` files.

# Collecting Data

- Cache every fetched page and API response under `data/raw/` and never re-fetch a
  cached one.
- Rate-limit requests. 506 Sports is a small fan-run site.

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
