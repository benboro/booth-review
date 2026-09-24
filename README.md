# booth-review

Which college football broadcasters get the best games? And after accounting for
the matchup, which ones draw more viewers?

booth-review joins public announcer listings, TV viewership figures, and game data
for FBS telecasts from 2013 on. The result is an interactive scatter plot where each
dot is one telecast, colored by network, and you can filter by individual announcer
across networks and seasons. NFL and MLB may follow.

**Status:** planning; no code yet. [`docs/PLAN.md`](docs/PLAN.md) has the
feasibility study, the analysis design, and the build plan.

## Data sources

| Source | Provides |
|---|---|
| [506 Sports](https://506sports.com/ncaaf.php) | Network and booth announcers for each game |
| [Ratings Reference](https://ratingsreference.com/league/cfb) | Viewership for each rated telecast |
| [CollegeFootballData.com](https://collegefootballdata.com) | Games, scores, betting lines, win probability, excitement |

Viewership data comes from RatingsReference.com under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), with each figure's original
publisher credited alongside it. [Sports Media Watch](https://www.sportsmediawatch.com/college-football-tv-ratings/),
the original source for most of those figures, is used only for manual spot checks.

This repo holds code, documentation, and hand-maintained reference tables. It
doesn't hold the source data itself; [`data/README.md`](data/README.md) explains
what's committed and why. The website loads a pre-built data file and never calls
these sources.

## Setup

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env   # then add your free CFBD API key
```

## License

The code is MIT-licensed. The data isn't covered by that license: it belongs to
the sources above and is subject to their terms.
