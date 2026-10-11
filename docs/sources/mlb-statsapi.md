# MLB Stats API: schedule and broadcasts

The Phase 7 spike (October 2026) read only MLB's data copyright notice, its site
terms and its robots files. It then tried single-date schedule reads by hand,
and the endpoint refused them (HTTP 406 Not Acceptable). The refusals were not
retried and no workaround was tried. Nothing was downloaded. Collection from the
Stats API is a later-phase question, and only if the terms allow it. The field
list is in [mlb-field-list.md](mlb-field-list.md).

## Terms

- **Copyright notice:** it permits only individual, non-commercial, non-bulk use
  of the data. Any other use needs the league's prior written authorization.
- **Site terms (updated March 2025):** they bar automated scripts that collect
  information from the league's sites, and bar reproduction, derivative works and
  display without written permission. They never mention the Stats API by name.
- **What that makes each field group:** blocked. A project that collects the
  schedule in bulk, derives values from it and displays them falls outside
  "non-bulk" use, so no Stats API field is used until permission exists in
  writing.

## Robots

`www.mlb.com/robots.txt` has one group for all agents that disallows several
paths (including `/api/`), names no Claude or Anthropic agent and sets no
crawl delay. `statsapi.mlb.com/robots.txt` returned HTTP 404, so no file
restricts that host. A third host, the old data host, returned HTTP 403 for its
robots file.

## What the spike read

The planned call shape was
`https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=<YYYY-MM-DD>&hydrate=broadcasts`,
one date at a time. Five date slots were fixed by kind: a 2025 regular-season
Saturday, a 2025 postseason date, a 2017 date, a date with a new 2026 outlet and
one at discretion. The first two were sent and refused with HTTP 406 on the
same wording for two different dates. The other three were not sent, since the
channel was plainly refused. No per-game endpoint, date range or Statcast file
was requested.

## Broadcast fields

Unknown, since no read succeeded. A permitted read would answer:

- whether a game carries a national flag;
- whether a broadcast is marked exclusive;
- the broadcast type (television, radio, streaming), language and feed kind;
- whether a production signal separates an outlet's own booth from a simulcast;
- how the league network and Spanish-language rows appear;
- whether any entry names people, which nothing found suggests.

## Earliest season

Unknown, for the same reason.

## Status per field

| field group | status | reason |
|---|---|---|
| Schedule and results | blocked | notice bars bulk use without written authorization |
| Broadcasts (outlet, national flag, exclusivity) | blocked | same notice; site terms bar automated collection |
| Win probability | blocked | same notice; not read |

The spike's answer to the open question: the group stays blocked until MLB
answers in writing, and an analysis-only use (never displayed) is possible only
as the project owner's recorded waiver.
