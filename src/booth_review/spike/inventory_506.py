"""506 inventory (SPIKE-03): the real page structure learned in the parser
(plan 01-10), counted into a private report with real examples in the vault,
and the machine-readable counts docs/sources/506.md is written from.

Nothing in this module prints, logs, or returns a real 506 row outside
Inventory506 itself: build_506_inventory's return value (and the vault-only
Markdown report write_506_inventory produces from it) are the only places a
real team, network, or crew string appears. The public counterpart,
docs/sources/506.md, is written by hand in the plan, in our own words, with
invented examples (D-07).

Run as `uv run python -m booth_review.spike.inventory_506` to build and write
both the JSON and Markdown reports for the real vault, then commit the vault.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass, field

from booth_review.config import DataPaths
from booth_review.sources.sports506.parser import Listing506, parse_week_page
from booth_review.transport.cache import Manifest, atomic_write_bytes, atomic_write_json

_WEEK_LABELS: list[str] = [str(n) for n in range(17)] + ["B"]
_MAX_EXAMPLES = 5

_OTHER_DELIMITER_CANDIDATES = (" and ", " & ", " / ", ";")
_SUFFIXES = ("Jr.", "Sr.", "II", "III", "IV")
_RANK_TAG_RE = re.compile(r"<font size=1>([^<]*)</font>")

_RANK_PREFIX_POLL_HEADING = (
    "## Rank-prefix poll\n\n"
    "Filled in by plan 01-11 after comparing 506's rank prefixes with CFBD polls.\n"
)


def _cache_name(label: str) -> str:
    """Mirror sources.sports506.collector._cache_name's zero-padded filename."""
    return label if label == "B" else label.zfill(2)


def _looks_like_initials(name: str) -> bool:
    first_word = name.split(" ", 1)[0]
    return len(first_word) <= 4 and "." in first_word


def _rank_form(rank_text: str) -> str:
    return "seed_paren" if "(" in rank_text else "plain"


def _example_row(listing: Listing506) -> str:
    """A one-line, real-example rendering of a listing for the vault-only report."""
    sep = " vs " if listing.neutral else " @ "
    away = f"{listing.away_rank} {listing.away_raw}" if listing.away_rank else listing.away_raw
    home = f"{listing.home_rank} {listing.home_raw}" if listing.home_rank else listing.home_raw
    network = listing.network_raw or "(no network listed)"
    crew = listing.crew_raw or "(no crew listed)"
    label = f"{listing.game_label}: " if listing.game_label else ""
    return f"{label}{away}{sep}{home}, {listing.date_et.isoformat()}, {network}, {crew}"


@dataclass(frozen=True)
class Inventory506:
    """Counts (and, for the vault report, real examples) over one season's
    506 listings, plus what the request manifest says about conditional-GET.
    """

    season: int
    pages_found: int
    pages_expected: int
    total_listings: int
    rows_per_week: dict[str, int]
    crew_size_distribution: dict[int, int]
    delimiters: dict[str, int]
    other_delimiter_candidates: list[str]
    rank_forms: dict[str, int]
    rank_range: dict[str, int | None]
    neutral_vs_home: dict[str, int]
    feed_kind_counts: dict[str, int]
    networks: dict[str, int]
    kickoff_time_formats: dict[str, int]
    name_suffix_or_initial_examples: list[str]
    conditional_get: dict[str, object]
    feed_kind_examples: dict[str, list[str]] = field(default_factory=dict)

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


def _conditional_get_counts(paths: DataPaths, *, season: int) -> dict[str, object]:
    """What the manifest says about ETag/Last-Modified on sports506 entries.

    The 2025 pages were all hand-imported (origin "manual") after 506
    returned 403 to booth-review's first live requests (01-09-SUMMARY.md),
    so this mostly answers "conditional-GET support is unknown, not yet
    observed" rather than "yes" or "no"; the by_status breakdown keeps the
    3 blocked live attempts visible alongside the 18 imports.
    """
    total = with_etag = with_last_modified = manual_origin = 0
    by_status: Counter[str] = Counter()
    for entry in Manifest(paths.manifest).entries():
        if entry.get("source") != "sports506" or entry.get("season") != season:
            continue
        if entry.get("kind") != "page":
            continue
        total += 1
        by_status[str(entry.get("status"))] += 1
        if entry.get("etag"):
            with_etag += 1
        if entry.get("last_modified"):
            with_last_modified += 1
        if entry.get("origin") == "manual":
            manual_origin += 1
    return {
        "entries_seen": total,
        "with_etag": with_etag,
        "with_last_modified": with_last_modified,
        "manual_origin": manual_origin,
        "by_status": dict(by_status),
    }


def build_506_inventory(paths: DataPaths, season: int = 2025) -> Inventory506:
    """Parse every cached `season` 506 week page under `paths.raw` and count
    the structural facts SPIKE-03 asks about: crew delimiters, rank-prefix
    forms, alt-cast/Spanish rows, rows without crews, and (from the request
    manifest) conditional-GET support.
    """
    season_dir = paths.raw / "sports506" / str(season)

    rows_per_week: dict[str, int] = {}
    all_listings: list[Listing506] = []
    pages_found = 0
    rank_forms: Counter[str] = Counter()

    for label in _WEEK_LABELS:
        page_path = season_dir / f"wk-{_cache_name(label)}.html"
        if not page_path.is_file():
            continue
        pages_found += 1
        content = page_path.read_bytes()
        listings = parse_week_page(content, season=season, week_label=label)
        rows_per_week[label] = len(listings)
        all_listings.extend(listings)
        for rank_text in _RANK_TAG_RE.findall(content.decode("utf-8", errors="replace")):
            rank_forms[_rank_form(rank_text)] += 1

    crew_size_distribution: Counter[int] = Counter(
        len(listing.crew_names) for listing in all_listings
    )

    delimiter_hits: Counter[str] = Counter()
    other_candidates: set[str] = set()
    for listing in all_listings:
        if listing.crew_raw is None:
            continue
        if len(listing.crew_names) >= 2:
            delimiter_hits[", "] += len(listing.crew_names) - 1
        elif len(listing.crew_names) == 1:
            for candidate in _OTHER_DELIMITER_CANDIDATES:
                if candidate in listing.crew_raw:
                    other_candidates.add(candidate.strip())

    rank_values = [
        rank
        for listing in all_listings
        for rank in (listing.away_rank, listing.home_rank)
        if rank is not None
    ]

    neutral_vs_home: Counter[str] = Counter(
        "neutral" if listing.neutral else "home" for listing in all_listings
    )

    feed_kind_counts: Counter[str] = Counter(listing.feed_kind for listing in all_listings)
    feed_kind_examples: dict[str, list[str]] = {}
    for kind in ("main", "alt", "spanish", "unknown"):
        examples = [_example_row(listing) for listing in all_listings if listing.feed_kind == kind]
        if examples:
            feed_kind_examples[kind] = examples[:_MAX_EXAMPLES]

    networks: Counter[str] = Counter(
        listing.network_raw for listing in all_listings if listing.network_raw is not None
    )

    kickoff_time_formats: Counter[str] = Counter(
        "H:MM AM/PM" if listing.kickoff_et is not None else "blank/TBA" for listing in all_listings
    )

    suffix_examples: set[str] = set()
    for listing in all_listings:
        for name in listing.crew_names:
            if any(name.endswith(suffix) for suffix in _SUFFIXES) or _looks_like_initials(name):
                suffix_examples.add(name)

    return Inventory506(
        season=season,
        pages_found=pages_found,
        pages_expected=len(_WEEK_LABELS),
        total_listings=len(all_listings),
        rows_per_week=rows_per_week,
        crew_size_distribution=dict(sorted(crew_size_distribution.items())),
        delimiters=dict(delimiter_hits),
        other_delimiter_candidates=sorted(other_candidates),
        rank_forms=dict(rank_forms),
        rank_range={
            "min": min(rank_values) if rank_values else None,
            "max": max(rank_values) if rank_values else None,
        },
        neutral_vs_home=dict(neutral_vs_home),
        feed_kind_counts=dict(feed_kind_counts),
        networks=dict(sorted(networks.items(), key=lambda item: (-item[1], item[0]))),
        kickoff_time_formats=dict(kickoff_time_formats),
        name_suffix_or_initial_examples=sorted(suffix_examples),
        conditional_get=_conditional_get_counts(paths, season=season),
        feed_kind_examples=feed_kind_examples,
    )


_STRUCTURE_NOTES = """## Structure notes

- One `<h3>DAYNAME, MONTH DAY</h3>` header per game date (no year in the
  header text); one `<div id="cgame">` per telecast follows, each holding
  `<div id="cmatchup">`, `<div id="ctime">`, `<div id="cntwk">`, and
  `<div id="canncrs">` sub-divs. `id` is reused on every row (not unique);
  parsing walks document order and tracks the most recent `<h3>` as the
  current date.
- A rank prefix is `<font size=1>N</font>` (or `<font size=1>N (M)</font>`
  for a CFP-seeded team) immediately before the ranked team's name inside
  `cmatchup`. The parser keeps only the plain integer `N`; the parenthesized
  form is counted separately here (see "Rank prefixes" below) but not
  exposed as a Listing506 field.
- The matchup separator is literally " @ " for a home game or " vs " for a
  neutral site; a neutral game's home-side text may carry a trailing
  "(in <city>)" annotation, which the parser leaves embedded in `home_raw`
  (no field is split out for it; the plan's cleanup list is rank + crew
  splitting + whitespace collapse only).
- Bowl/CFP pages (`wk=B`) prefix `cmatchup` with `<b>Bowl or Round Name</b>`
  followed by `<br>`, then the same matchup text. The parser reads that as
  `game_label` and treats week pages (no `<b>` present) as `game_label=None`.
- One row on the `wk=B` page names a bowl ("CFP National Championship")
  before the season's participants are set: `cmatchup` holds only the label
  and a location, no matchup text. The parser drops that row rather than
  return a listing with empty teams.
- 506's bowl calendar crosses the new year (a `wk=B` page holds games from
  December of the season year into January of the next one); the parser
  detects this from the `<h3>` month sequence and rolls the year over the
  first time a header's month number is lower than the previous header's.
- An alt-cast row's `cntwk` text carries a "(alt-cast)" suffix (e.g.
  "ACCN (alt-cast)"); no Spanish-feed row was observed in 2025's 18 pages
  (see "Alt-cast and Spanish rows" below).
- Every cached 2025 page declares `charset="utf-8"` and decodes cleanly;
  none carries a browser "saved from url=(...)" comment, Mark-of-the-Web
  marker, or injected `<base>` tag, so the hand-saved "HTML only" copies
  read the same as a live fetch would have.
"""


def _render_markdown(inv: Inventory506) -> str:
    lines: list[str] = [
        f"# 506 Sports Inventory: {inv.season}",
        "",
        f"{inv.pages_found}/{inv.pages_expected} pages cached, "
        f"{inv.total_listings} listings parsed.",
        "",
        "## Rows per week",
        "",
        "| Week | Rows |",
        "|------|------|",
    ]
    for label in _WEEK_LABELS:
        if label in inv.rows_per_week:
            lines.append(f"| {label} | {inv.rows_per_week[label]} |")
    lines += [
        "",
        "## Crew delimiters",
        "",
        f"Crew-size distribution (number of names per row): {inv.crew_size_distribution}",
        f"Delimiter hits: {inv.delimiters}",
    ]
    if inv.other_delimiter_candidates:
        lines.append(
            f"Other delimiter candidates seen in a single-name crew string "
            f"(needs a look): {inv.other_delimiter_candidates}"
        )
    else:
        lines.append('No other delimiter candidates found; every multi-name crew splits on ", ".')
    if inv.name_suffix_or_initial_examples:
        lines.append(
            f"Names with a suffix or period-initials (kept verbatim, never merged): "
            f"{inv.name_suffix_or_initial_examples}"
        )
    lines += [
        "",
        "## Rank prefixes",
        "",
        f'Forms seen: {inv.rank_forms} ("seed_paren" is `N (M)`, an AP rank '
        "with a parenthesized CFP seed; only `N` becomes the away_rank/home_rank int)",
        f"Rank range observed: {inv.rank_range['min']}-{inv.rank_range['max']}",
        f'Neutral ("vs") vs. home ("@") rows: {inv.neutral_vs_home}',
        "",
        "## Alt-cast and Spanish rows",
        "",
        f"feed_kind counts: {inv.feed_kind_counts}",
    ]
    for kind, examples in inv.feed_kind_examples.items():
        lines.append(f"\n`{kind}` examples:")
        lines.extend(f"- {example}" for example in examples)
    lines += [
        "",
        "## Rows without crews",
        "",
        f"Rows with crew_names == () : {inv.crew_size_distribution.get(0, 0)} "
        f"of {inv.total_listings}",
        "",
        "## Networks",
        "",
        f"{inv.networks}",
        "",
        "## Kickoff-time formats",
        "",
        f"{inv.kickoff_time_formats}",
        "",
        "## Conditional GET",
        "",
        f"{inv.conditional_get}",
        "",
        _STRUCTURE_NOTES,
        _RANK_PREFIX_POLL_HEADING,
    ]
    return "\n".join(lines) + "\n"


def write_506_inventory(paths: DataPaths, inv: Inventory506) -> None:
    """Write the private JSON counts and the private Markdown report with
    real examples to data/vault/spike/. Never called with anything but a
    real Inventory506 in production use; tests point `paths` at a tmp vault.
    """
    atomic_write_json(paths.spike / "inventory-506.json", inv.to_json_dict())
    atomic_write_bytes(paths.spike / "inventory-506.md", _render_markdown(inv).encode("utf-8"))


if __name__ == "__main__":
    _paths = DataPaths.from_env()
    _inventory = build_506_inventory(_paths)
    write_506_inventory(_paths, _inventory)
    print(
        f"506 inventory: {_inventory.total_listings} listings across "
        f"{_inventory.pages_found}/{_inventory.pages_expected} pages "
        f"({_paths.spike / 'inventory-506.md'})"
    )
