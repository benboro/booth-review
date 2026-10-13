# Data

Everything in this folder is gitignored except this README and `reference/`. The
data comes from third-party sites, and being publicly viewable doesn't make it ours
to redistribute. A table is committed only when every source it draws on allows
republishing (see [Sources](#sources)).

| Folder | Contents | Committed? |
|---|---|---|
| `vault/` | A clone of the private data repo: `raw/` (pages and API responses, cached so each is fetched only once), `interim/`, `processed/`, `ledger/` (`frozen.json` records which season × source is frozen; `rr_lastmod.jsonl`, an append-only log read together with the older, no-longer-written `rr_lastmod.json` snapshot, tracks each Ratings Reference record's last-seen sitemap `<lastmod>`, used by `refresh ratingsref`; `job_state.json` records the scheduled job's last successful run, for catch-up; plus the CFBD and request call ledgers), `raw/nfl/` (NFL sources, kept apart from the college-football files; `ledger/nfl_nflverse_assets.jsonl` tracks changes to nflverse release assets), `audit/` (completeness reports and the freeze sign-off baseline), `spike/`. Vault `interim/` and `processed/` copies are rebuilt from `raw/` on every run and never read back as state | Never (not even here — it's a separate private repo) |
| `incoming/506/cfb/`, `incoming/506/nfl/` | Hand-saved 506 Sports week pages for each league, waiting for `booth-review import 506` | Never |
| `processed/` | Joined tables that feed the plot and the models, published from this public repo | Only tables whose sources all allow it. Publish one by adding a `!data/processed/<file>` line to `.gitignore`, after `!data/processed/` and `data/processed/*` |
| `reference/` | Hand-maintained tables (`nfl_booth_ranks.csv` holds facts and the URL from network lineup releases, never the page): team-name crosswalk, announcer name variants, event flags, per-network `network_rarity.csv` (hand-set rarely-rated flag) | Yes |

## Sources

| Source | Terms | Can we republish derived data? |
|---|---|---|
| [Ratings Reference](https://ratingsreference.com/methodology) | Its compilation and JSON records are [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The figures themselves are facts credited to their original publishers | Yes. Credit RatingsReference.com, link each record used, cite each figure's original source, and note that we changed the data |
| [CollegeFootballData.com](https://collegefootballdata.com) | Its [terms](https://collegefootballdata.com/terms), updated August 12, 2026, permit using API data in websites, reasonable portions of factual data inside a larger product, and derived outputs such as charts; they prohibit providing API data as a standalone dataset or bulk download, mirrors, substitute APIs, and exposing keys in public code. Attribution ("Data provided by CollegeFootballData.com") is appreciated, not required | Yes, in the interactive chart. CFBD's admin confirmed by email on September 25, 2026 that its fields, including `excitementIndex`, may be used in the chart. A downloadable file may contain our own analysis and ordinary exports, but never a bulk download of CFBD's fields, even reformatted. Credit "Data provided by [CollegeFootballData.com](https://collegefootballdata.com)" on the site |
| [506 Sports](https://506sports.com/ncaaf.php) | No robots.txt, and no terms or copyright notice on its schedule pages. Blocks automated clients (403 Forbidden, confirmed 2026-09-25); its pages are saved by hand in a browser and brought in with `booth-review import 506` | Crews and networks are shown, credited to 506 Sports with a link. The owners were asked and have not replied; if they object, these come off the site |
| [nflverse](https://github.com/nflverse/nflverse-data) | The data is [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); credit nflverse. Betting-line (`spread_line`) columns and play-by-play carry no stated provenance, so they are analysis-only (see `docs/sources/nfl-field-list.md`) | Derived values only, with credit to nflverse. Never the odds columns or play-by-play themselves |
| [Wikipedia](https://en.wikipedia.org) | Article text is [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) | Only extracted scheduling facts, with the article URL; derived data that includes them is share-alike |
| [506 Sports NFL](https://506sports.com/nfl.php) | Same as the college-football row: no terms or copyright notice; pages are saved by hand | Crews and networks are shown, credited to 506 Sports with a link. The owners were asked and have not replied; if they object, these come off the site |
| [Sports Media Watch](https://www.sportsmediawatch.com/college-football-tv-ratings/) | Its robots.txt blocks scripts, so it isn't collected | Not applicable; used for manual spot checks only |

Run the collectors to rebuild `vault/raw/` locally. Keep request rates low: 506
Sports is a small fan-run site.
