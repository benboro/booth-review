"""Automatic 506/RR lookups for each selected CFBD game, crew resolution, the
D-06 outputs (join.csv, the review summary, and a draft report), and the
--finalize join-rate computation (D-09).

Matching is deterministic and tiered: exact -> date-shift -> partial ->
ambiguous -> none (ARCHITECTURE.md Pattern 3). No HTTP client is built here
(T-01-51); everything is read from data already cached under
data/vault/raw/. Outputs are written only under data/vault/spike/ (T-01-48).
"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Literal, cast

from booth_review.config import DataPaths
from booth_review.errors import BoothReviewError, ParseError
from booth_review.sources.cfbd.parser import CfbdGame, parse_games
from booth_review.sources.ratingsref.parser import RRRecord, parse_record
from booth_review.sources.ratingsref.sitemap import SitemapEntry, parse_sitemap
from booth_review.sources.sports506.parser import Listing506, parse_week_page
from booth_review.spike.headline import HEADLINE_RULE, select_headline
from booth_review.spike.names import normalize_team, significant_tokens, to_et_date, to_et_datetime
from booth_review.spike.selection import DEFAULT_SEED, Selection
from booth_review.transport.cache import atomic_write_bytes

MatchConfidence = Literal["exact", "date-shift", "partial", "ambiguous", "none"]

_RR_SLUG_PREFIX = "cfb-"
_SEASON = 2025
_WEEK_LABELS: tuple[str, ...] = (*(str(n) for n in range(17)), "B")

_CONFIDENCE_RANK: dict[str, int] = {
    "exact": 0,
    "date-shift": 1,
    "partial": 2,
    "ambiguous": 3,
    "none": 4,
}

_SUFFIXES = ("Jr.", "Sr.", "II", "III", "IV")


class ReviewIncompleteError(BoothReviewError):
    """Raised by finalize() when any join.csv row still has review_status
    'pending'; the join rate is only ever computed from reviewed rows (D-09).
    """


class JoinFileMissingError(BoothReviewError):
    """Raised by finalize() when join.csv does not exist yet -- `spike join`
    must run (and produce join.csv) before `spike join --finalize`.
    """


@dataclass(frozen=True)
class Match506:
    confidence: MatchConfidence
    listings: tuple[Listing506, ...]


@dataclass(frozen=True)
class MatchRR:
    confidence: MatchConfidence
    records: tuple[RRRecord, ...]


@dataclass(frozen=True)
class CrewResolution:
    crew: str | None
    matched_listing: Listing506 | None
    notes: str


def _pair(a: str, b: str) -> frozenset[str]:
    return frozenset({normalize_team(a), normalize_team(b)})


def _rr_slug_pair(record: RRRecord) -> frozenset[str]:
    return frozenset(normalize_team(_strip_rr_prefix(slug)) for slug in record.telecast.teams)


def _strip_rr_prefix(slug: str) -> str:
    return slug[len(_RR_SLUG_PREFIX) :] if slug.startswith(_RR_SLUG_PREFIX) else slug


def match_506(game: CfbdGame, listings: Sequence[Listing506]) -> Match506:
    """Match `game` to its 506 listing(s) on unordered team pair + ET date.

    Returns every listing of the matched game (main, alt, Spanish feeds all
    share the same matchup text and date).
    """
    game_et_date = to_et_date(game.start_date)
    game_pair = _pair(game.away_team, game.home_team)
    home_tokens = significant_tokens(game.home_team)
    away_tokens = significant_tokens(game.away_team)

    same_pair = [ln for ln in listings if _pair(ln.away_raw, ln.home_raw) == game_pair]

    exact = [ln for ln in same_pair if ln.date_et == game_et_date]
    if exact:
        return Match506(confidence="exact", listings=tuple(exact))

    shifted = [ln for ln in same_pair if abs((ln.date_et - game_et_date).days) == 1]
    if shifted:
        return Match506(confidence="date-shift", listings=tuple(shifted))

    nearby = [ln for ln in listings if abs((ln.date_et - game_et_date).days) <= 1]
    partial_candidates = []
    for ln in nearby:
        listing_tokens = significant_tokens(ln.away_raw) | significant_tokens(ln.home_raw)
        if (home_tokens & listing_tokens) and (away_tokens & listing_tokens):
            partial_candidates.append(ln)

    if not partial_candidates:
        return Match506(confidence="none", listings=())

    groups: dict[tuple[object, ...], list[Listing506]] = {}
    for ln in partial_candidates:
        key = (ln.date_et, ln.away_raw.strip().casefold(), ln.home_raw.strip().casefold())
        groups.setdefault(key, []).append(ln)

    if len(groups) > 1:
        return Match506(confidence="ambiguous", listings=())

    only_group = next(iter(groups.values()))
    return Match506(confidence="partial", listings=tuple(only_group))


def match_rr(game: CfbdGame, records: Sequence[RRRecord]) -> MatchRR:
    """Apply the same match_506 rules to RR telecast.teams slugs and
    event_date. Duplicate records that resolve to the same game are all
    returned (JOIN-05); the caller pools their claims for headline selection.
    """
    game_et_date = to_et_date(game.start_date)
    game_pair = _pair(game.away_team, game.home_team)
    home_tokens = significant_tokens(game.home_team)
    away_tokens = significant_tokens(game.away_team)

    same_pair = [r for r in records if _rr_slug_pair(r) == game_pair]

    exact = [r for r in same_pair if r.telecast.event_date == game_et_date]
    if exact:
        return MatchRR(confidence="exact", records=tuple(exact))

    shifted = [r for r in same_pair if abs((r.telecast.event_date - game_et_date).days) == 1]
    if shifted:
        return MatchRR(confidence="date-shift", records=tuple(shifted))

    nearby = [r for r in records if abs((r.telecast.event_date - game_et_date).days) <= 1]
    partial_candidates = []
    for r in nearby:
        record_tokens: set[str] = set()
        for slug in r.telecast.teams:
            record_tokens |= significant_tokens(slug)
        if (home_tokens & record_tokens) and (away_tokens & record_tokens):
            partial_candidates.append(r)

    if not partial_candidates:
        return MatchRR(confidence="none", records=())

    groups: dict[tuple[object, ...], list[RRRecord]] = {}
    for r in partial_candidates:
        key = (r.telecast.event_date, _rr_slug_pair(r))
        groups.setdefault(key, []).append(r)

    if len(groups) > 1:
        return MatchRR(confidence="ambiguous", records=())

    only_group = next(iter(groups.values()))
    return MatchRR(confidence="partial", records=tuple(only_group))


def resolve_crew(listings: Sequence[Listing506], rr_networks: Sequence[str]) -> CrewResolution:
    """Pick the main-feed listing whose network matches one of `rr_networks`
    (case-insensitive); else the first main-feed listing. Alt and Spanish
    feeds are never the resolved crew; they go into notes.
    """
    main_listings = [ln for ln in listings if ln.feed_kind == "main"]
    other_listings = [ln for ln in listings if ln.feed_kind != "main"]

    rr_networks_lower = {n.lower() for n in rr_networks}
    matched = next(
        (
            ln
            for ln in main_listings
            if ln.network_raw and ln.network_raw.lower() in rr_networks_lower
        ),
        None,
    )
    chosen = matched if matched is not None else (main_listings[0] if main_listings else None)

    notes = "; ".join(
        f"{ln.feed_kind}: {ln.network_raw or '(no network)'} ({ln.crew_raw or 'no crew listed'})"
        for ln in other_listings
    )
    crew = chosen.crew_raw if chosen is not None else None
    return CrewResolution(crew=crew, matched_listing=chosen, notes=notes)


# -- D-06 outputs: join.csv, summary.md, report.md --------------------------------------

_JOIN_ROW_FIELDS = (
    "cfbd_game_id",
    "categories",
    "cfbd_matchup",
    "cfbd_start_et",
    "s506_week",
    "s506_row_index",
    "s506_row",
    "s506_confidence",
    "rr_record_urls",
    "rr_headline_value",
    "rr_headline_publisher",
    "rr_headline_source_url",
    "rr_claim_count",
    "rr_confidence",
    "resolved_crew",
    "match_confidence",
    "doubtful",
    "notes",
    "review_status",
    "review_note",
)


@dataclass
class JoinRow:
    """One data/vault/spike/join.csv row: the CFBD game id, the matched 506
    row, the matched RR headline figure and record URLs, the resolved crew,
    match confidence, notes, and a review_status column (D-06).
    """

    cfbd_game_id: int
    categories: str
    cfbd_matchup: str
    cfbd_start_et: str
    s506_week: str
    s506_row_index: str
    s506_row: str
    s506_confidence: str
    rr_record_urls: str
    rr_headline_value: str
    rr_headline_publisher: str
    rr_headline_source_url: str
    rr_claim_count: int
    rr_confidence: str
    resolved_crew: str
    match_confidence: str
    doubtful: bool
    notes: str
    review_status: str
    review_note: str

    def to_csv_dict(self) -> dict[str, object]:
        return {field.name: getattr(self, field.name) for field in fields(self)}


def _week_page_path(paths: DataPaths, season: int, label: str) -> Path:
    name = label if label == "B" else label.zfill(2)
    return paths.raw / "sports506" / str(season) / f"wk-{name}.html"


def _load_all_506_listings(paths: DataPaths, season: int) -> list[Listing506]:
    listings: list[Listing506] = []
    for label in _WEEK_LABELS:
        page_path = _week_page_path(paths, season, label)
        if not page_path.is_file():
            continue
        listings.extend(parse_week_page(page_path.read_bytes(), season=season, week_label=label))
    return listings


def _load_all_rr_records(paths: DataPaths, season: int) -> list[RRRecord]:
    records: list[RRRecord] = []
    season_dir = paths.raw / "ratingsref" / "telecast" / str(season)
    if season_dir.is_dir():
        for record_path in sorted(season_dir.glob("*.json")):
            try:
                records.append(parse_record(record_path.read_bytes()))
            except ParseError:
                continue
    return records


def load_rr_sitemap_entries(paths: DataPaths) -> list[SitemapEntry]:
    """The most recently cached RR sitemap's CFB entries, or [] if none is
    cached yet. Sends no request: reads only from data/vault/raw/.
    """
    sitemap_dir = paths.raw / "ratingsref" / "sitemap"
    if not sitemap_dir.is_dir():
        return []
    files = sorted(sitemap_dir.glob("*.xml"))
    if not files:
        return []
    entries, _skipped = parse_sitemap(files[-1].read_bytes())
    return entries


def _render_506_row(listing: Listing506 | None) -> str:
    if listing is None:
        return ""
    sep = "vs" if listing.neutral else "@"
    return (
        f"{listing.away_raw} {sep} {listing.home_raw} | "
        f"{listing.network_raw or ''} | {listing.crew_raw or ''}"
    )


def build_join_rows(paths: DataPaths, selections: Sequence[Selection]) -> list[JoinRow]:
    """Load the 2025 CFBD games, every cached 506 listing, and every cached
    RR record, then run match_506/match_rr/select_headline/resolve_crew for
    each selected game (D-06). review_status is "pending" on every row.
    """
    games_path = paths.raw / "cfbd" / "games" / f"{_SEASON}.json"
    games_by_id = {g.id: g for g in parse_games(games_path.read_bytes())}

    all_listings = _load_all_506_listings(paths, _SEASON)
    all_records = _load_all_rr_records(paths, _SEASON)

    rows: list[JoinRow] = []
    for selection in selections:
        try:
            game = games_by_id[selection.cfbd_game_id]
        except KeyError as exc:
            raise ParseError(
                f"selection.csv references cfbd_game_id {selection.cfbd_game_id} not found "
                f"in cfbd/games/{_SEASON}.json"
            ) from exc
        m506 = match_506(game, all_listings)
        mrr = match_rr(game, all_records)

        pooled_claims = [claim for record in mrr.records for claim in record.claims]
        headline = select_headline(pooled_claims) if pooled_claims else None

        rr_networks = [n for r in mrr.records for n in r.telecast.networks]
        crew = resolve_crew(m506.listings, rr_networks)

        network_mismatch = bool(
            crew.matched_listing is not None
            and crew.matched_listing.network_raw is not None
            and rr_networks
            and crew.matched_listing.network_raw.lower() not in {n.lower() for n in rr_networks}
        )

        match_conf = max((m506.confidence, mrr.confidence), key=lambda c: _CONFIDENCE_RANK[c])
        doubtful = match_conf != "exact" or len(mrr.records) >= 2 or network_mismatch

        notes_parts = [crew.notes] if crew.notes else []
        if network_mismatch:
            assert crew.matched_listing is not None
            notes_parts.append(
                f"network mismatch: 506={crew.matched_listing.network_raw} "
                f"RR={sorted(set(rr_networks))}"
            )
        notes = "; ".join(notes_parts)

        neutral_sep = "vs" if game.neutral_site else "@"
        rows.append(
            JoinRow(
                cfbd_game_id=game.id,
                categories="|".join(selection.categories),
                cfbd_matchup=f"{game.away_team} {neutral_sep} {game.home_team}",
                cfbd_start_et=to_et_datetime(game.start_date).isoformat(),
                s506_week=crew.matched_listing.week_label if crew.matched_listing else "",
                s506_row_index=(
                    str(crew.matched_listing.source_row_index) if crew.matched_listing else ""
                ),
                s506_row=_render_506_row(crew.matched_listing),
                s506_confidence=m506.confidence,
                rr_record_urls="; ".join(r.record_url for r in mrr.records),
                rr_headline_value=(
                    str(headline.value) if headline and headline.value is not None else ""
                ),
                rr_headline_publisher=(headline.publisher or "") if headline else "",
                rr_headline_source_url=(headline.source_url or "") if headline else "",
                rr_claim_count=sum(len(r.claims) for r in mrr.records),
                rr_confidence=mrr.confidence,
                resolved_crew=crew.crew or "",
                match_confidence=match_conf,
                doubtful=doubtful,
                notes=notes,
                review_status="pending",
                review_note="",
            )
        )
    return rows


def _write_join_csv(path: Path, rows: Sequence[JoinRow]) -> None:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_JOIN_ROW_FIELDS)
    writer.writeheader()
    for row in rows:
        writer.writerow(row.to_csv_dict())
    atomic_write_bytes(path, buf.getvalue().encode("utf-8"))


def _render_summary(rows: Sequence[JoinRow]) -> str:
    lines = [
        "# SPIKE-02 hand-join review",
        "",
        "For D-08: review each doubtful (CHECK-flagged) row against the vault's "
        "join.csv before the join rate is recorded.",
        "",
        "| # | Matchup | ET date | Categories | 506 | RR | Crew | Confidence | Doubtful |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for i, row in enumerate(rows, start=1):
        flag = "CHECK" if row.doubtful else ""
        lines.append(
            f"| {i} | {row.cfbd_matchup} | {row.cfbd_start_et} | {row.categories} | "
            f"{row.s506_confidence} | {row.rr_confidence} | {row.resolved_crew} | "
            f"{row.match_confidence} | {flag} |"
        )
    lines.append("")
    return "\n".join(lines)


def _name_matching_problems(rows: Sequence[JoinRow]) -> list[str]:
    problems: list[str] = []
    for row in rows:
        if row.s506_confidence != "exact":
            problems.append(
                f"506 ({row.s506_confidence}): cfbd='{row.cfbd_matchup}' row='{row.s506_row}'"
            )
        if row.rr_confidence != "exact":
            problems.append(
                f"RR ({row.rr_confidence}): cfbd='{row.cfbd_matchup}' "
                f"records='{row.rr_record_urls}'"
            )
        if "network mismatch" in row.notes:
            problems.append(f"network mismatch: cfbd='{row.cfbd_matchup}' notes='{row.notes}'")
    return problems


def _announcer_observations(rows: Sequence[JoinRow]) -> list[str]:
    observations: list[str] = []
    for row in rows:
        if not row.resolved_crew:
            continue
        names = [n.strip() for n in row.resolved_crew.split(",") if n.strip()]
        if len(names) >= 3:
            observations.append(f"three-person crew: '{row.resolved_crew}' ({row.cfbd_matchup})")
        for name in names:
            if any(name.endswith(suffix) for suffix in _SUFFIXES):
                observations.append(f"suffix: '{name}' ({row.cfbd_matchup})")
            first_word = name.split(" ", 1)[0]
            if len(first_word) <= 4 and "." in first_word:
                observations.append(f"initials: '{name}' ({row.cfbd_matchup})")
        if "alt:" in row.notes or "spanish:" in row.notes:
            observations.append(f"alt/spanish feed noted: {row.notes} ({row.cfbd_matchup})")
    return observations


def _render_report(rows: Sequence[JoinRow], *, final: dict[str, object] | None) -> str:
    total = len(rows)
    lines = ["# SPIKE-02 hand-join report", ""]
    if final is None:
        auto_confirmed = sum(1 for r in rows if r.match_confidence in ("exact", "date-shift"))
        lines += [
            "Join rate: PENDING REVIEW",
            f"Provisional automatic rate (exact or date-shift): {auto_confirmed}/{total}",
            "",
        ]
    else:
        rate_pct = cast(float, final["join_rate"]) * 100
        verdict = "PASS" if final["passed"] else "FAIL"
        lines += [
            f"Join rate: {final['confirmed']}/{total} = {rate_pct:.1f}%",
            f"D-09 exit rule (80%): {verdict}",
            "",
        ]
    lines += [
        "## Headline-figure rule",
        "",
        HEADLINE_RULE,
        "",
        "## Selection rules and seed",
        "",
        "Categories required: at least 2 rematch, 2 neutral-site, 1 post-DST "
        "November, 1 late-or-Hawaii, and 1 CFP/MegaCast game, drawn only from "
        "candidates with an RR sitemap entry within one day sharing a "
        f"significant token with each team (rated_hint). Seed: {DEFAULT_SEED}.",
        "",
        "## Name-matching problems",
        "",
    ]
    problems = _name_matching_problems(rows)
    lines.extend(f"- {p}" for p in problems) if problems else lines.append("None found.")
    lines += ["", "## Announcer-name observations", ""]
    observations = _announcer_observations(rows)
    lines.extend(f"- {o}" for o in observations) if observations else lines.append("None found.")
    lines.append("")
    return "\n".join(lines)


def write_outputs(
    paths: DataPaths, rows: Sequence[JoinRow], selections: Sequence[Selection]
) -> None:
    """Write join.csv (D-06), the D-08 review summary.md, and a draft
    report.md ("Join rate: PENDING REVIEW" until --finalize runs).

    `selections` isn't read directly (each JoinRow already carries its
    selection's categories); it stays in the signature to match the plan's
    documented `write_outputs(paths, rows, selections)` call shape.
    """
    _ = selections
    _write_join_csv(paths.spike / "join.csv", rows)
    atomic_write_bytes(paths.spike / "summary.md", _render_summary(rows).encode("utf-8"))
    atomic_write_bytes(paths.spike / "report.md", _render_report(rows, final=None).encode("utf-8"))


# -- finalize: the reviewed join rate against the D-09 80% exit rule --------------------


def _row_from_csv_dict(raw: dict[str, str]) -> JoinRow:
    try:
        return JoinRow(
            cfbd_game_id=int(raw["cfbd_game_id"]),
            categories=raw["categories"],
            cfbd_matchup=raw["cfbd_matchup"],
            cfbd_start_et=raw["cfbd_start_et"],
            s506_week=raw["s506_week"],
            s506_row_index=raw["s506_row_index"],
            s506_row=raw["s506_row"],
            s506_confidence=raw["s506_confidence"],
            rr_record_urls=raw["rr_record_urls"],
            rr_headline_value=raw["rr_headline_value"],
            rr_headline_publisher=raw["rr_headline_publisher"],
            rr_headline_source_url=raw["rr_headline_source_url"],
            rr_claim_count=int(raw["rr_claim_count"]),
            rr_confidence=raw["rr_confidence"],
            resolved_crew=raw["resolved_crew"],
            match_confidence=raw["match_confidence"],
            doubtful=raw["doubtful"] in ("True", "true", "1"),
            notes=raw["notes"],
            review_status=raw["review_status"],
            review_note=raw["review_note"],
        )
    except KeyError as exc:
        raise ParseError(f"join.csv is missing expected column {exc}") from exc


def finalize(paths: DataPaths) -> dict[str, object]:
    """Read join.csv, require every row to be reviewed (confirmed, corrected,
    or rejected), compute the join rate from confirmed rows only, and
    rewrite report.md with the final rate and the D-09 80% verdict.

    Raises ReviewIncompleteError if any row is still "pending".
    """
    join_path = paths.spike / "join.csv"
    try:
        with join_path.open(newline="", encoding="utf-8") as fh:
            raw_rows = list(csv.DictReader(fh))
    except FileNotFoundError as exc:
        raise JoinFileMissingError(
            f"join.csv not found at {join_path}; run 'spike join' before 'spike join --finalize'"
        ) from exc

    if any(r["review_status"] == "pending" for r in raw_rows):
        raise ReviewIncompleteError(
            "cannot finalize: some join.csv rows still have review_status 'pending'"
        )

    total = len(raw_rows)
    confirmed = sum(1 for r in raw_rows if r["review_status"] == "confirmed")
    corrected = sum(1 for r in raw_rows if r["review_status"] == "corrected")
    rejected = sum(1 for r in raw_rows if r["review_status"] == "rejected")
    join_rate = confirmed / total if total else 0.0
    passed = join_rate >= 0.80

    result: dict[str, object] = {
        "confirmed": confirmed,
        "corrected": corrected,
        "rejected": rejected,
        "total": total,
        "join_rate": join_rate,
        "passed": passed,
    }

    rows = [_row_from_csv_dict(r) for r in raw_rows]
    atomic_write_bytes(
        paths.spike / "report.md", _render_report(rows, final=result).encode("utf-8")
    )
    return result
