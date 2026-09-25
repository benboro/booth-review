# Data

Everything in this folder is gitignored except this README and `reference/`. The
data comes from third-party sites, and being publicly viewable doesn't make it ours
to redistribute. A table is committed only when every source it draws on allows
republishing (see [Sources](#sources)).

| Folder | Contents | Committed? |
|---|---|---|
| `vault/` | A clone of the private data repo: `raw/` (pages and API responses, cached so each is fetched only once), `interim/`, `processed/`, `ledger/` (`frozen.json` records which season × source is frozen; `rr_lastmod.json` tracks each Ratings Reference record's last-seen sitemap `<lastmod>`, used by `refresh ratingsref`; `job_state.json` records the scheduled job's last successful run, for catch-up; plus the CFBD and request call ledgers), `audit/` (completeness reports and the freeze sign-off baseline), `spike/`. Vault `interim/` and `processed/` copies are rebuilt from `raw/` on every run and never read back as state | Never (not even here — it's a separate private repo) |
| `processed/` | Joined tables that feed the plot and the models, published from this public repo | Only tables whose sources all allow it. Publish one by adding a `!data/processed/<file>` line to `.gitignore`, after `!data/processed/` and `data/processed/*` |
| `reference/` | Hand-maintained tables: team-name crosswalk, announcer name variants, event flags | Yes |

## Sources

| Source | Terms | Can we republish derived data? |
|---|---|---|
| [Ratings Reference](https://ratingsreference.com/methodology) | Its compilation and JSON records are [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The figures themselves are facts credited to their original publishers | Yes. Credit RatingsReference.com, link each record used, cite each figure's original source, and note that we changed the data |
| [CollegeFootballData.com](https://collegefootballdata.com) | Its [terms](https://collegefootballdata.com/terms), updated August 12, 2026, permit using API data in websites, reasonable portions of factual data inside a larger product, and derived outputs such as charts; they prohibit providing API data as a standalone dataset or bulk download, mirrors, substitute APIs, and exposing keys in public code. Attribution ("Data provided by CollegeFootballData.com") is appreciated, not required | Yes, in the interactive chart. CFBD's admin confirmed by email on September 25, 2026 that its fields, including `excitementIndex`, may be used in the chart. A downloadable file may contain our own analysis and ordinary exports, but never a bulk download of CFBD's fields, even reformatted. Credit "Data provided by [CollegeFootballData.com](https://collegefootballdata.com)" on the site |
| [506 Sports](https://506sports.com/ncaaf.php) | No robots.txt, and no terms or copyright notice on its schedule pages. Blocks automated clients (403 Forbidden, confirmed 2026-09-25); its pages are saved by hand in a browser and brought in with `booth-review import 506` | Not yet. Ask the site owners |
| [Sports Media Watch](https://www.sportsmediawatch.com/college-football-tv-ratings/) | Its robots.txt blocks scripts, so it isn't collected | Not applicable; used for manual spot checks only |

Run the collectors to rebuild `vault/raw/` locally. Keep request rates low: 506
Sports is a small fan-run site.
