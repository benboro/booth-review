# Data

Everything in this folder is gitignored except this README and `reference/`. The
data comes from third-party sites, and being publicly viewable doesn't make it ours
to redistribute. Until each source's terms of use are checked (open question 5 in
[`docs/PLAN.md`](../docs/PLAN.md)), only code and our own hand-built tables are
committed.

| Folder | Contents | Committed? |
|---|---|---|
| `raw/` | Pages fetched from 506 Sports and Ratings Reference, and CFBD API responses, cached so each is fetched only once | Never |
| `interim/` | Parsed tables that haven't been joined yet | No |
| `processed/` | Joined tables that feed the plot and the models | Not yet. Publish a file only after its sources' terms allow it, by adding a `!data/processed/<file>` line to `.gitignore` |
| `reference/` | Hand-maintained tables: team-name crosswalk, announcer name variants, event flags | Yes |

Run the collectors to rebuild `raw/` locally. Keep request rates low: 506 Sports is
a small fan-run site.
