# Data

Everything in this folder is gitignored except this README and `reference/`. The
data comes from third-party sites, and being publicly viewable doesn't make it ours
to redistribute. A table is committed only when every source it draws on allows
republishing (see [Sources](#sources)).

| Folder | Contents | Committed? |
|---|---|---|
| `raw/` | Pages from 506 Sports and API responses from Ratings Reference and CFBD, cached so each is fetched only once | Never |
| `interim/` | Parsed tables that haven't been joined yet | No |
| `processed/` | Joined tables that feed the plot and the models | Only tables whose sources all allow it. Publish one by adding a `!data/processed/<file>` line to `.gitignore` |
| `reference/` | Hand-maintained tables: team-name crosswalk, announcer name variants, event flags | Yes |

## Sources

| Source | Terms | Can we republish derived data? |
|---|---|---|
| [Ratings Reference](https://ratingsreference.com/methodology) | Its compilation and JSON records are [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The figures themselves are facts credited to their original publishers | Yes. Credit RatingsReference.com, link each record used, cite each figure's original source, and note that we changed the data |
| [CollegeFootballData.com](https://collegefootballdata.com) | The API key terms cover usage limits (1,000 requests per month on the free tier), not republishing | Not yet. Ask CFBD, especially about its `excitementIndex` |
| [506 Sports](https://506sports.com/ncaaf.php) | No robots.txt, and no terms or copyright notice on its schedule pages | Not yet. Ask the site owners |
| [Sports Media Watch](https://www.sportsmediawatch.com/college-football-tv-ratings/) | Its robots.txt blocks scripts, so it isn't collected | Not applicable; used for manual spot checks only |

Run the collectors to rebuild `raw/` locally. Keep request rates low: 506 Sports is
a small fan-run site.
