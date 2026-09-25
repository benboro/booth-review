"""Ratings Reference and CFBD source inventories, the 506 rank-prefix-vs-poll
comparison, the write-only interim mirror, and `run_inventory` (SPIKE-03, plus
the 506 third of SPIKE-03 already built in inventory_506.py).

Like inventory_506.py, this module is the only place a real Ratings Reference
or CFBD row appears outside the vault-only Markdown/JSON reports it writes;
docs/sources/ratings-reference.md and docs/sources/cfbd.md are written by
hand, in our own words, with invented examples (D-07). Nothing here builds an
HTTP client: every fact comes from files already cached under
data/vault/raw/ and data/vault/ledger/.
"""

from __future__ import annotations

import csv
import io
import json
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import cast

from booth_review.config import DataPaths
from booth_review.errors import ParseError
from booth_review.sources.cfbd.parser import (
    parse_games,
    parse_lines,
    parse_media,
    parse_rankings,
    parse_wp_pregame,
)
from booth_review.sources.ratingsref.parser import parse_record
from booth_review.sources.sports506.parser import parse_week_page
from booth_review.spike.inventory_506 import build_506_inventory, write_506_inventory
from booth_review.transport.budget import CfbdBudget
from booth_review.transport.cache import atomic_write_bytes, atomic_write_json
from booth_review.vault import VaultRepo, batch_message

_MAX_EXAMPLES = 5
_WEEK_LABELS: tuple[str, ...] = (*(str(n) for n in range(17)), "B")
_CFBD_SEASONS: tuple[int, ...] = tuple(range(2014, 2026))
_RR_SEASONS: tuple[int, ...] = (2024, 2025)

_AP_POLL_NAME = "AP Top 25"
_CFP_POLL_NAME = "Playoff Committee Rankings"
_CFP_START_WEEK = 11  # first week CFBD's Playoff Committee Rankings appear (2025)

_STARTDATE_RE = re.compile(r'"startDate"\s*:\s*"([^"]*)"')
_STARTDATE_SUFFIX_RE = re.compile(r"(Z|[+-]\d{2}:\d{2})$")


def _week_page_path(paths: DataPaths, season: int, label: str) -> Path:
    name = label if label == "B" else label.zfill(2)
    return paths.raw / "sports506" / str(season) / f"wk-{name}.html"


def _label_to_cfbd_week(label: str) -> int | None:
    """506's "wk=0" and "wk=1" both fall inside CFBD's week=1 (CFBD folds the
    season-opener "week 0" games into week 1); every other numeric label maps
    1:1. "B" (bowls/CFP) has no single CFBD week, so it's handled separately.
    """
    if label == "B":
        return None
    return max(int(label), 1)


# -- Ratings Reference inventory ---------------------------------------------------------


def _record_id_fallback(path: Path, content: bytes) -> str:
    """Best-effort telecast id for a record that failed to parse."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return path.stem
    if isinstance(data, dict):
        telecast = data.get("telecast")
        if isinstance(telecast, dict):
            tid = telecast.get("id")
            if isinstance(tid, str):
                return tid
    return path.stem


def build_rr_inventory(paths: DataPaths, seasons: Iterable[int]) -> dict[str, object]:
    """Parse every cached Ratings Reference record for `seasons` and count the
    claim vocabulary SPIKE-03 asks about: status, metric_type, figure fields,
    measured_by, measurement_method, unit, era_id, and how often a record
    carries several avg_audience claims.
    """
    records = 0
    parse_failures = 0
    parse_failure_ids: list[str] = []
    records_per_season: dict[str, int] = {}

    status_counts: Counter[str] = Counter()
    metric_type_counts: Counter[str] = Counter()
    cut_counts: Counter[str] = Counter()
    unit_counts: Counter[str] = Counter()
    era_id_counts: Counter[str] = Counter()
    measured_by_counts: Counter[str] = Counter()
    measurement_method_counts: Counter[str] = Counter()
    publisher_counts: Counter[str] = Counter()
    telecast_kind_counts: Counter[str] = Counter()
    telecast_tier_counts: Counter[str] = Counter()
    network_counts: Counter[str] = Counter()

    carrier_network_nonnull = 0
    composite_of_nonnull = 0
    supersedes_id_nonnull = 0
    source_url_null = 0
    records_with_multiple_avg_audience = 0
    claims_counts: list[int] = []
    value_by_unit: dict[str, list[float]] = {}
    extra_claim_counts: Counter[str] = Counter()
    extra_claim_examples: dict[str, list[object]] = {}
    example_ids: dict[str, list[str]] = {
        "multiple_avg_audience": [],
        "composite_of": [],
        "carrier_network": [],
        "supersedes_id": [],
    }

    for season in seasons:
        season_dir = paths.raw / "ratingsref" / "telecast" / str(season)
        count_this_season = 0
        if season_dir.is_dir():
            for record_path in sorted(season_dir.glob("*.json")):
                content = record_path.read_bytes()
                try:
                    record = parse_record(content)
                except ParseError:
                    parse_failures += 1
                    fid = _record_id_fallback(record_path, content)
                    if len(parse_failure_ids) < _MAX_EXAMPLES:
                        parse_failure_ids.append(fid)
                    continue

                records += 1
                count_this_season += 1
                telecast_kind_counts[str(record.telecast.kind)] += 1
                telecast_tier_counts[str(record.telecast.tier)] += 1
                for net in record.telecast.networks:
                    network_counts[net] += 1

                avg_audience_claims = 0
                for claim in record.claims:
                    status_counts[claim.status] += 1
                    metric_type_counts[claim.metric_type] += 1
                    if claim.cut is not None:
                        cut_counts[claim.cut] += 1
                    if claim.unit is not None:
                        unit_counts[claim.unit] += 1
                    if claim.era_id is not None:
                        era_id_counts[claim.era_id] += 1
                    if claim.measured_by is not None:
                        measured_by_counts[claim.measured_by] += 1
                    if claim.measurement_method is not None:
                        measurement_method_counts[claim.measurement_method] += 1
                    if claim.publisher is not None:
                        publisher_counts[claim.publisher] += 1
                    if claim.carrier_network is not None:
                        carrier_network_nonnull += 1
                        _add_example(example_ids["carrier_network"], record.telecast.id)
                    if claim.composite_of:
                        composite_of_nonnull += 1
                        _add_example(example_ids["composite_of"], record.telecast.id)
                    if claim.supersedes_id is not None:
                        supersedes_id_nonnull += 1
                        _add_example(example_ids["supersedes_id"], record.telecast.id)
                    if claim.source_url is None:
                        source_url_null += 1
                    if claim.metric_type == "avg_audience":
                        avg_audience_claims += 1
                    if claim.value is not None and claim.unit is not None:
                        value_by_unit.setdefault(claim.unit, []).append(claim.value)

                    for key, value in (claim.model_extra or {}).items():
                        extra_claim_counts[key] += 1
                        examples = extra_claim_examples.setdefault(key, [])
                        rendered = (
                            value
                            if value is None or isinstance(value, str | int | float | bool)
                            else repr(value)
                        )
                        if len(examples) < 3 and rendered not in examples:
                            examples.append(rendered)

                claims_counts.append(len(record.claims))
                if avg_audience_claims >= 2:
                    records_with_multiple_avg_audience += 1
                    _add_example(example_ids["multiple_avg_audience"], record.telecast.id)

        records_per_season[str(season)] = count_this_season

    return {
        "records": records,
        "parse_failures": parse_failures,
        "parse_failure_ids": parse_failure_ids,
        "records_per_season": records_per_season,
        "status_counts": dict(status_counts),
        "metric_type_counts": dict(metric_type_counts),
        "cut_counts": dict(cut_counts),
        "unit_counts": dict(unit_counts),
        "era_id_counts": dict(era_id_counts),
        "measured_by_counts": dict(measured_by_counts),
        "measurement_method_counts": dict(measurement_method_counts),
        "publisher_counts": dict(publisher_counts),
        "telecast_kind_counts": dict(telecast_kind_counts),
        "telecast_tier_counts": dict(telecast_tier_counts),
        "network_counts": dict(network_counts),
        "carrier_network_nonnull": carrier_network_nonnull,
        "composite_of_nonnull": composite_of_nonnull,
        "supersedes_id_nonnull": supersedes_id_nonnull,
        "source_url_null_count": source_url_null,
        "records_with_multiple_avg_audience": records_with_multiple_avg_audience,
        "claims_per_record": {
            "min": min(claims_counts) if claims_counts else 0,
            "max": max(claims_counts) if claims_counts else 0,
            "avg": round(sum(claims_counts) / len(claims_counts), 2) if claims_counts else 0.0,
        },
        "value_range_by_unit": {
            unit: {"min": min(vals), "max": max(vals)} for unit, vals in value_by_unit.items()
        },
        "extra_claim_keys": {
            key: {"count": count, "example_values": extra_claim_examples.get(key, [])}
            for key, count in extra_claim_counts.items()
        },
        "example_ids": example_ids,
        "lastmod_coverage": _lastmod_coverage(paths),
    }


def _add_example(bucket: list[str], value: str) -> None:
    if len(bucket) < _MAX_EXAMPLES and value not in bucket:
        bucket.append(value)


def _lastmod_coverage(paths: DataPaths) -> dict[str, object]:
    if not paths.rr_lastmod.is_file():
        return {"tracked": 0}
    data: dict[str, object] = json.loads(paths.rr_lastmod.read_text(encoding="utf-8"))
    lastmods: Counter[str] = Counter()
    for entry in data.values():
        if isinstance(entry, dict):
            lastmod = entry.get("lastmod")
            if isinstance(lastmod, str):
                lastmods[lastmod] += 1
    return {
        "tracked": len(data),
        "distinct_lastmods": len(lastmods),
        "most_common_lastmods": lastmods.most_common(5),
    }


def _render_rr_markdown(inv: dict[str, object]) -> str:
    example_ids = inv["example_ids"]
    assert isinstance(example_ids, dict)
    lines: list[str] = [
        "# Ratings Reference Inventory",
        "",
        f"{inv['records']} records parsed, {inv['parse_failures']} parse failures.",
    ]
    if inv["parse_failure_ids"]:
        lines.append(f"Parse-failure telecast ids: {inv['parse_failure_ids']}")
    lines += [
        "",
        f"Records per season: {inv['records_per_season']}",
        "",
        "## status",
        "",
        f"{inv['status_counts']}",
        "",
        "## metric_type",
        "",
        f"{inv['metric_type_counts']}",
        "",
        "## cut",
        "",
        f"{inv['cut_counts']}",
        "",
        "## unit",
        "",
        f"{inv['unit_counts']}",
        f"Value range by unit: {inv['value_range_by_unit']}",
        "",
        "## era_id",
        "",
        f"{inv['era_id_counts']}",
        "",
        "## measured_by",
        "",
        f"{inv['measured_by_counts']}",
        "",
        "## measurement_method",
        "",
        f"{inv['measurement_method_counts']}",
        "",
        "## publisher",
        "",
        f"{inv['publisher_counts']}",
        "",
        "## telecast.kind / telecast.tier / networks",
        "",
        f"kind: {inv['telecast_kind_counts']}",
        f"tier: {inv['telecast_tier_counts']}",
        f"networks: {inv['network_counts']}",
        "",
        "## Non-null special fields",
        "",
        f"carrier_network non-null: {inv['carrier_network_nonnull']} "
        f"(examples: {example_ids['carrier_network']})",
        f"composite_of non-null: {inv['composite_of_nonnull']} "
        f"(examples: {example_ids['composite_of']})",
        f"supersedes_id non-null: {inv['supersedes_id_nonnull']} "
        f"(examples: {example_ids['supersedes_id']})",
        f"source_url null count: {inv['source_url_null_count']}",
        "",
        "## claims per record",
        "",
        f"{inv['claims_per_record']}",
        f"Records with 2+ avg_audience claims: {inv['records_with_multiple_avg_audience']} "
        f"(examples: {example_ids['multiple_avg_audience']})",
        "",
        "## Unknown/extra claim fields (model_extra)",
        "",
    ]
    extra_keys = inv["extra_claim_keys"]
    assert isinstance(extra_keys, dict)
    for key, data in sorted(extra_keys.items()):
        lines.append(f"- `{key}`: count={data['count']}, examples={data['example_values']}")
    lines += [
        "",
        "## Ratings Reference lastmod coverage",
        "",
        f"{inv['lastmod_coverage']}",
        "",
    ]
    return "\n".join(lines) + "\n"


# -- CFBD inventory -----------------------------------------------------------------------


def _start_date_suffix_counts(content: bytes) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for match in _STARTDATE_RE.finditer(content.decode("utf-8")):
        suffix_match = _STARTDATE_SUFFIX_RE.search(match.group(1))
        counts[suffix_match.group(1) if suffix_match else "none"] += 1
    return dict(counts)


def _cfbd_ledger_facts(paths: DataPaths) -> dict[str, object]:
    budget = CfbdBudget(paths.cfbd_ledger)
    summary = budget.summary()

    discrepancy_count = 0
    reset_at_values: Counter[str] = Counter()
    if paths.cfbd_ledger.is_file():
        with paths.cfbd_ledger.open(encoding="utf-8") as fh:
            for raw_line in fh:
                stripped = raw_line.strip()
                if not stripped:
                    continue
                line = json.loads(stripped)
                if line.get("event") != "call":
                    continue
                if line.get("discrepancy"):
                    discrepancy_count += 1
                reset_at = line.get("info_reset_at")
                if reset_at:
                    reset_at_values[reset_at] += 1

    return {
        "info_counts_against_quota": summary.info_counts_against_quota,
        "last_remaining": summary.last_remaining,
        "floor": summary.floor,
        "calls_counted": summary.calls_counted,
        "by_endpoint": summary.by_endpoint,
        "discrepancy_count": discrepancy_count,
        "reset_at_values": dict(reset_at_values),
    }


def build_cfbd_inventory(paths: DataPaths, season: int = 2025) -> dict[str, object]:
    """Report CFBD's `startDate` time-zone format, week numbering, FBS
    classification, media fill rate, poll names, line providers, and the
    /info budget ledger for `season`, plus pregame-WP/lines/excitement
    coverage for every cached season 2014-2025 (SPIKE-03).
    """
    games_path = paths.raw / "cfbd" / "games" / f"{season}.json"
    games_content = games_path.read_bytes()
    games = parse_games(games_content)

    weeks_by_season_type: dict[str, set[int]] = {}
    games_per_season_type: Counter[str] = Counter()
    classification_counts: Counter[str] = Counter()
    start_time_tbd_count = 0
    for g in games:
        st = g.season_type or "unknown"
        weeks_by_season_type.setdefault(st, set()).add(g.week)
        games_per_season_type[st] += 1
        if g.home_classification:
            classification_counts[g.home_classification] += 1
        if g.away_classification:
            classification_counts[g.away_classification] += 1
        if g.start_time_tbd:
            start_time_tbd_count += 1

    fbs_game_ids = {
        g.id for g in games if g.home_classification == "fbs" or g.away_classification == "fbs"
    }

    media_path = paths.raw / "cfbd" / "media" / f"{season}.json"
    media_fill_rate: dict[str, object] | None = None
    top_outlets: dict[str, int] = {}
    if media_path.is_file():
        media_rows = parse_media(media_path.read_bytes())
        tv_ids = {m.id for m in media_rows if m.media_type == "tv"}
        fbs_with_tv = fbs_game_ids & tv_ids
        media_fill_rate = {
            "fbs_games": len(fbs_game_ids),
            "fbs_with_tv": len(fbs_with_tv),
            "pct": round(100 * len(fbs_with_tv) / len(fbs_game_ids), 1) if fbs_game_ids else 0.0,
        }
        top_outlets = dict(Counter(m.outlet for m in media_rows if m.outlet).most_common(15))

    rankings_path = paths.raw / "cfbd" / "rankings" / f"{season}.json"
    poll_names: dict[str, dict[str, object]] = {}
    if rankings_path.is_file():
        weeks_per_poll: dict[str, set[int]] = {}
        for poll_week in parse_rankings(rankings_path.read_bytes()):
            for poll in poll_week.polls:
                weeks_per_poll.setdefault(poll.poll, set()).add(poll_week.week)
        for name, weeks in weeks_per_poll.items():
            poll_names[name] = {"weeks": sorted(weeks), "week_count": len(weeks)}

    lines_path = paths.raw / "cfbd" / "lines" / f"{season}.json"
    line_providers: dict[str, int] = {}
    if lines_path.is_file():
        lines = parse_lines(lines_path.read_bytes())
        line_providers = dict(Counter(line.provider for line in lines if line.spread is not None))

    wp_path = paths.raw / "cfbd" / "wp_pregame" / f"{season}.json"
    pregame_wp_row_count = len(parse_wp_pregame(wp_path.read_bytes())) if wp_path.is_file() else 0

    excitement_null_rate_by_season: dict[str, dict[str, object]] = {}
    wp_pregame_coverage_by_season: dict[str, int] = {}
    lines_coverage_by_season: dict[str, int] = {}
    for year in _CFBD_SEASONS:
        year_games_path = paths.raw / "cfbd" / "games" / f"{year}.json"
        if year_games_path.is_file():
            year_games = parse_games(year_games_path.read_bytes())
            total = len(year_games)
            nulls = sum(1 for g in year_games if g.excitement_index is None)
            excitement_null_rate_by_season[str(year)] = {
                "total": total,
                "nulls": nulls,
                "pct": round(100 * nulls / total, 1) if total else 0.0,
            }
        year_wp_path = paths.raw / "cfbd" / "wp_pregame" / f"{year}.json"
        if year_wp_path.is_file():
            wp_pregame_coverage_by_season[str(year)] = len(
                parse_wp_pregame(year_wp_path.read_bytes())
            )
        year_lines_path = paths.raw / "cfbd" / "lines" / f"{year}.json"
        if year_lines_path.is_file():
            lines_coverage_by_season[str(year)] = len(parse_lines(year_lines_path.read_bytes()))

    return {
        "season": season,
        "start_date_formats": _start_date_suffix_counts(games_content),
        "weeks_by_season_type": {k: sorted(v) for k, v in weeks_by_season_type.items()},
        "start_time_tbd_count": start_time_tbd_count,
        "classification_counts": dict(classification_counts),
        "games_per_season_type": dict(games_per_season_type),
        "media_fill_rate": media_fill_rate,
        "top_outlets": top_outlets,
        "poll_names": poll_names,
        "line_providers": line_providers,
        "pregame_wp_row_count": pregame_wp_row_count,
        "excitement_null_rate_by_season": excitement_null_rate_by_season,
        "wp_pregame_coverage_by_season": wp_pregame_coverage_by_season,
        "lines_coverage_by_season": lines_coverage_by_season,
        "ledger": _cfbd_ledger_facts(paths),
    }


def _render_cfbd_markdown(inv: dict[str, object]) -> str:
    lines: list[str] = [
        f"# CFBD Inventory: season {inv['season']} (plus 2014-2025 coverage checks)",
        "",
        "## startDate time zone",
        "",
        f"Suffix forms observed: {inv['start_date_formats']}",
        "",
        "## Week numbering",
        "",
        f"Weeks by season_type: {inv['weeks_by_season_type']}",
        f"Games per season_type: {inv['games_per_season_type']}",
        f"start_time_tbd count: {inv['start_time_tbd_count']}",
        "",
        "## Classification",
        "",
        f"{inv['classification_counts']}",
        "",
        "## Media fill rate",
        "",
        f"{inv['media_fill_rate']}",
        f"Top outlets: {inv['top_outlets']}",
        "",
        "## Poll names",
        "",
    ]
    poll_names = inv["poll_names"]
    assert isinstance(poll_names, dict)
    for name, data in sorted(poll_names.items()):
        lines.append(f"- {name}: weeks {data['weeks']}")
    lines += [
        "",
        "## Line providers",
        "",
        f"{inv['line_providers']}",
        "",
        "## Pregame win probability and lines coverage (2014-2025)",
        "",
        f"Pregame WP rows ({inv['season']}): {inv['pregame_wp_row_count']}",
        f"WP row count by season: {inv['wp_pregame_coverage_by_season']}",
        f"Lines row count by season: {inv['lines_coverage_by_season']}",
        f"excitementIndex null rate by season: {inv['excitement_null_rate_by_season']}",
        "",
        "## /info cost",
        "",
        f"{inv['ledger']}",
        "",
    ]
    return "\n".join(lines) + "\n"


# -- 506 rank-prefix vs. CFBD poll comparison ----------------------------------------------


def compare_rank_prefixes(paths: DataPaths, season: int = 2025) -> dict[str, object]:
    """For every cached 506 week page, compare each ranked listing's rank
    prefix against CFBD's AP Top 25 and Playoff Committee Rankings for the
    corresponding CFBD week, matching 506's name to a CFBD school name
    exactly (case-insensitive). Rows whose name matches neither available
    poll that week are counted as skipped, not guessed at (AGENTS.md's
    crosswalk-only rule; no name is normalized here).
    """
    rankings_path = paths.raw / "cfbd" / "rankings" / f"{season}.json"
    ap_by_week: dict[int, dict[str, int]] = {}
    cfp_by_week: dict[int, dict[str, int]] = {}
    if rankings_path.is_file():
        for poll_week in parse_rankings(rankings_path.read_bytes()):
            for poll in poll_week.polls:
                target: dict[int, dict[str, int]] | None = None
                if poll.poll == _AP_POLL_NAME:
                    target = ap_by_week
                elif poll.poll == _CFP_POLL_NAME:
                    target = cfp_by_week
                if target is not None:
                    target[poll_week.week] = {r.school.lower(): r.rank for r in poll.ranks}

    by_week: dict[str, dict[str, object]] = {}
    totals = {
        "total_ranked": 0,
        "ap_checked": 0,
        "ap_matches": 0,
        "cfp_checked": 0,
        "cfp_matches": 0,
        "skipped_name_mismatch": 0,
    }
    for label in _WEEK_LABELS:
        cfbd_week = _label_to_cfbd_week(label)
        page_path = _week_page_path(paths, season, label)
        if cfbd_week is None or not page_path.is_file():
            continue
        listings = parse_week_page(page_path.read_bytes(), season=season, week_label=label)
        ap_ranks = ap_by_week.get(cfbd_week)
        cfp_ranks = cfp_by_week.get(cfbd_week)

        total_ranked = ap_checked = ap_matches = cfp_checked = cfp_matches = skipped = 0
        for listing in listings:
            for name, rank in (
                (listing.away_raw, listing.away_rank),
                (listing.home_raw, listing.home_rank),
            ):
                if rank is None:
                    continue
                total_ranked += 1
                found = False
                if ap_ranks is not None and name.lower() in ap_ranks:
                    found = True
                    ap_checked += 1
                    if ap_ranks[name.lower()] == rank:
                        ap_matches += 1
                if cfp_ranks is not None and name.lower() in cfp_ranks:
                    found = True
                    cfp_checked += 1
                    if cfp_ranks[name.lower()] == rank:
                        cfp_matches += 1
                if not found:
                    skipped += 1

        by_week[label] = {
            "cfbd_week": cfbd_week,
            "total_ranked": total_ranked,
            "ap_checked": ap_checked,
            "ap_matches": ap_matches,
            "cfp_checked": cfp_checked,
            "cfp_matches": cfp_matches,
            "skipped_name_mismatch": skipped,
        }
        totals["total_ranked"] += total_ranked
        totals["ap_checked"] += ap_checked
        totals["ap_matches"] += ap_matches
        totals["cfp_checked"] += cfp_checked
        totals["cfp_matches"] += cfp_matches
        totals["skipped_name_mismatch"] += skipped

    return {"by_week": by_week, "totals": totals}


def _pct(matches: int, checked: int) -> float | None:
    return round(100 * matches / checked, 1) if checked else None


def summarize_rank_prefix_poll(cmp: dict[str, object]) -> dict[str, object]:
    """Turn compare_rank_prefixes' per-week counts into the finding written
    into inventory-506.md's "Rank-prefix poll" section: which poll 506's
    rank prefixes track before and after the CFP rankings begin.
    """
    by_week = cast("dict[str, dict[str, object]]", cmp["by_week"])
    pre = {"ap_checked": 0, "ap_matches": 0}
    post = {"ap_checked": 0, "ap_matches": 0, "cfp_checked": 0, "cfp_matches": 0}
    for week in by_week.values():
        cfbd_week = week["cfbd_week"]
        assert isinstance(cfbd_week, int)
        is_post = cfbd_week >= _CFP_START_WEEK
        bucket = post if is_post else pre
        bucket["ap_checked"] += cast(int, week["ap_checked"])
        bucket["ap_matches"] += cast(int, week["ap_matches"])
        if is_post:
            post["cfp_checked"] += cast(int, week["cfp_checked"])
            post["cfp_matches"] += cast(int, week["cfp_matches"])

    pre_ap_pct = _pct(pre["ap_matches"], pre["ap_checked"])
    post_ap_pct = _pct(post["ap_matches"], post["ap_checked"])
    post_cfp_pct = _pct(post["cfp_matches"], post["cfp_checked"])

    finding_lines = [
        f"Before the CFP rankings begin (weeks before {_CFP_START_WEEK}), 506's rank prefixes "
        f"agree with AP Top 25 in {pre_ap_pct}% of matched rows "
        f"(n={pre['ap_matches']}/{pre['ap_checked']})."
    ]
    if post["ap_checked"] or post["cfp_checked"]:
        finding_lines.append(
            f"From week {_CFP_START_WEEK} on, agreement with the Playoff Committee Rankings is "
            f"{post_cfp_pct}% (n={post['cfp_matches']}/{post['cfp_checked']}) versus "
            f"{post_ap_pct}% with AP Top 25 in the same weeks "
            f"(n={post['ap_matches']}/{post['ap_checked']})."
        )
        if post_cfp_pct is not None and post_ap_pct is not None:
            leader = (
                "the Playoff Committee Rankings" if post_cfp_pct >= post_ap_pct else "AP Top 25"
            )
            finding_lines.append(
                f"506's rank prefixes track {leader} more closely once the CFP rankings begin."
            )

    totals = cmp["totals"]
    assert isinstance(totals, dict)
    return {
        "pre_cfp": pre,
        "post_cfp": post,
        "pre_ap_pct": pre_ap_pct,
        "post_ap_pct": post_ap_pct,
        "post_cfp_pct": post_cfp_pct,
        "finding": " ".join(finding_lines),
        "skipped_name_mismatch": totals.get("skipped_name_mismatch", 0),
    }


# -- interim mirror -------------------------------------------------------------------------


def _write_csv(path: Path, rows: list[dict[str, object]], *, fieldnames: Sequence[str]) -> None:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(fieldnames))
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    atomic_write_bytes(path, buf.getvalue().encode("utf-8"))


_SPORTS506_FIELDS = (
    "week_label",
    "date_et",
    "away_raw",
    "away_rank",
    "home_raw",
    "home_rank",
    "neutral",
    "network_raw",
    "crew_raw",
    "feed_kind",
    "game_label",
)
_RATINGSREF_FIELDS = (
    "telecast_id",
    "event_date",
    "metric_type",
    "status",
    "value",
    "unit",
    "measured_by",
    "publisher",
    "era_id",
)
_CFBD_GAMES_FIELDS = (
    "id",
    "week",
    "season_type",
    "start_date",
    "home_team",
    "away_team",
    "home_classification",
    "away_classification",
    "excitement_index",
)


def _write_sports506_interim(paths: DataPaths, season: int) -> int:
    rows: list[dict[str, object]] = []
    for label in _WEEK_LABELS:
        page_path = _week_page_path(paths, season, label)
        if not page_path.is_file():
            continue
        for listing in parse_week_page(page_path.read_bytes(), season=season, week_label=label):
            rows.append(
                {
                    "week_label": listing.week_label,
                    "date_et": listing.date_et.isoformat(),
                    "away_raw": listing.away_raw,
                    "away_rank": listing.away_rank,
                    "home_raw": listing.home_raw,
                    "home_rank": listing.home_rank,
                    "neutral": listing.neutral,
                    "network_raw": listing.network_raw,
                    "crew_raw": listing.crew_raw,
                    "feed_kind": listing.feed_kind,
                    "game_label": listing.game_label,
                }
            )
    _write_csv(
        paths.interim / f"sports506_listings_{season}.csv", rows, fieldnames=_SPORTS506_FIELDS
    )
    return len(rows)


def _write_ratingsref_interim(paths: DataPaths, season: int) -> int:
    rows: list[dict[str, object]] = []
    season_dir = paths.raw / "ratingsref" / "telecast" / str(season)
    if season_dir.is_dir():
        for record_path in sorted(season_dir.glob("*.json")):
            try:
                record = parse_record(record_path.read_bytes())
            except ParseError:
                continue
            for claim in record.claims:
                rows.append(
                    {
                        "telecast_id": record.telecast.id,
                        "event_date": record.telecast.event_date.isoformat(),
                        "metric_type": claim.metric_type,
                        "status": claim.status,
                        "value": claim.value,
                        "unit": claim.unit,
                        "measured_by": claim.measured_by,
                        "publisher": claim.publisher,
                        "era_id": claim.era_id,
                    }
                )
    _write_csv(
        paths.interim / f"ratingsref_claims_{season}.csv", rows, fieldnames=_RATINGSREF_FIELDS
    )
    return len(rows)


def _write_cfbd_games_interim(paths: DataPaths, season: int) -> int:
    rows: list[dict[str, object]] = []
    games_path = paths.raw / "cfbd" / "games" / f"{season}.json"
    if games_path.is_file():
        for g in parse_games(games_path.read_bytes()):
            rows.append(
                {
                    "id": g.id,
                    "week": g.week,
                    "season_type": g.season_type,
                    "start_date": g.start_date.isoformat(),
                    "home_team": g.home_team,
                    "away_team": g.away_team,
                    "home_classification": g.home_classification,
                    "away_classification": g.away_classification,
                    "excitement_index": g.excitement_index,
                }
            )
    _write_csv(paths.interim / f"cfbd_games_{season}.csv", rows, fieldnames=_CFBD_GAMES_FIELDS)
    return len(rows)


def write_interim(paths: DataPaths, *, season: int = 2025) -> dict[str, int]:
    """Rebuild the write-only interim CSV mirror from raw for `season`,
    overwriting any previous copies. Never read back by any code (D-03).
    """
    return {
        "sports506_listings": _write_sports506_interim(paths, season),
        "ratingsref_claims": _write_ratingsref_interim(paths, season),
        "cfbd_games": _write_cfbd_games_interim(paths, season),
    }


# -- run_inventory --------------------------------------------------------------------------


def run_inventory(paths: DataPaths, *, commit: bool) -> None:
    """Rebuild every SPIKE-03 inventory (RR, CFBD, 506, the rank-prefix-vs-poll
    comparison) and the interim mirror from local raw files, then optionally
    commit the vault with a count-only message. Sends no request: everything
    is read from data/vault/raw/ and data/vault/ledger/.
    """
    rr_inv = build_rr_inventory(paths, _RR_SEASONS)
    atomic_write_json(paths.spike / "inventory-ratingsref.json", rr_inv)
    atomic_write_bytes(
        paths.spike / "inventory-ratingsref.md", _render_rr_markdown(rr_inv).encode("utf-8")
    )

    cfbd_inv = build_cfbd_inventory(paths, season=2025)
    atomic_write_json(paths.spike / "inventory-cfbd.json", cfbd_inv)
    atomic_write_bytes(
        paths.spike / "inventory-cfbd.md", _render_cfbd_markdown(cfbd_inv).encode("utf-8")
    )

    rank_cmp = compare_rank_prefixes(paths, season=2025)
    rank_poll = summarize_rank_prefix_poll(rank_cmp)
    inv_506 = build_506_inventory(paths, season=2025)
    write_506_inventory(paths, inv_506, rank_poll=rank_poll)

    write_interim(paths, season=2025)

    if commit:
        files_written = 6  # 3 inventory pairs written this run: RR, CFBD, 506 (.md + .json each)
        VaultRepo(paths.vault).commit_batch(
            batch_message("spike", "inventory", "2025", {"files": files_written})
        )
