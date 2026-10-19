"""Cited CFB booth order per network family and season (Phase 10 D-01, D-02, D-04..D-06).

The order is hand-entered from published lineups, never inferred. Every error names the
file and line only, never cell content, because the scheduled job's logs are public.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from booth_review.errors import ReferenceTableError
from booth_review.people.registry import load_people
from booth_review.reference import read_reference_csv_numbered
from booth_review.resolve.networks import load_networks
from booth_review.seasons import current_season

CFB_BOOTH_RANK_COLUMNS = ("family", "season", "rank", "pbp", "analyst", "scope", "source_url")
CFB_BOOTH_FAMILIES = ("disney", "fox", "cbs", "nbc")
CFB_BOOTH_FIRST_SEASON = 2014


@dataclass(frozen=True)
class CfbBoothRank:
    family: str
    season: int
    rank: int | None
    pbp_person_id: str
    analyst_person_id: str
    scope_network_id: str | None
    source_url: str


def _err(path: Path, line_no: int, message: str) -> ReferenceTableError:
    return ReferenceTableError(f"{path.name}: line {line_no}: {message}")


def _opt_int(path: Path, line_no: int, raw: str, field: str) -> int | None:
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        raise _err(path, line_no, f"invalid {field}") from None


def _req_int(path: Path, line_no: int, raw: str, field: str) -> int:
    value = _opt_int(path, line_no, raw, field)
    if value is None:
        raise _err(path, line_no, f"{field} is required")
    return value


def _check_https(path: Path, line_no: int, url: str) -> None:
    if not url.startswith("https://") or len(url) <= len("https://"):
        raise _err(path, line_no, "source_url must be an https URL")


def load_cfb_booth_ranks(
    reference_dir: Path,
) -> dict[tuple[str, int], tuple[CfbBoothRank, ...]]:
    """(family, season) -> cited booths: ranked rows by rank, then scope rows by network id.

    A missing or header-only table is empty.
    """
    path = reference_dir / "cfb_booth_ranks.csv"
    raw_rows = read_reference_csv_numbered(path, CFB_BOOTH_RANK_COLUMNS, required=False)
    if not raw_rows:
        return {}
    people = load_people(reference_dir)
    networks = load_networks(reference_dir).networks()
    grouped: dict[tuple[str, int], list[tuple[int, CfbBoothRank]]] = {}
    for line_no, raw in raw_rows:
        family = raw["family"]
        if family not in CFB_BOOTH_FAMILIES:
            raise _err(path, line_no, "family must be disney, fox, cbs or nbc")
        season = _req_int(path, line_no, raw["season"], "season")
        last_season = current_season()
        if not CFB_BOOTH_FIRST_SEASON <= season <= last_season:
            raise _err(path, line_no, f"season must be {CFB_BOOTH_FIRST_SEASON}-{last_season}")
        scope = raw["scope"].strip() or None
        if scope is not None:
            info = networks.get(scope)
            if info is None or info[2] != "conference" or info[1] != family:
                raise _err(path, line_no, "scope must be a conference network in the row's family")
        rank = _opt_int(path, line_no, raw["rank"], "rank")
        if rank is None and scope is None:
            raise _err(path, line_no, "rank is required unless scope is set")
        if rank is not None and rank < 1:
            raise _err(path, line_no, "rank must be at least 1")
        if scope is not None and rank is not None and rank < 3:
            raise _err(path, line_no, "a conference-network lead cannot be rank 1 or 2")
        pbp = people.lookup(raw["pbp"])
        analyst = people.lookup(raw["analyst"])
        if pbp is None or analyst is None:
            raise _err(path, line_no, "name does not resolve through people.csv")
        _check_https(path, line_no, raw["source_url"])
        rows = grouped.setdefault((family, season), [])
        if rank is not None and any(r.rank == rank for _, r in rows):
            raise _err(path, line_no, "duplicate (family, season, rank)")
        if any(r.pbp_person_id == pbp for _, r in rows):
            raise _err(path, line_no, "play-by-play person appears twice in one family season")
        if scope is not None and any(r.scope_network_id == scope for _, r in rows):
            raise _err(path, line_no, "duplicate (family, season, scope)")
        rows.append(
            (line_no, CfbBoothRank(family, season, rank, pbp, analyst, scope, raw["source_url"]))
        )
    out: dict[tuple[str, int], tuple[CfbBoothRank, ...]] = {}
    for key, rows in grouped.items():
        ranked = sorted(
            (lr for lr in rows if lr[1].rank is not None), key=lambda lr: lr[1].rank or 0
        )
        for expected, (line_no, r) in enumerate(ranked, start=1):
            if r.rank != expected:
                raise _err(path, line_no, "ranks must run 1..n")
        if not ranked or ranked[0][1].rank != 1:
            raise _err(path, rows[0][0], "family season has no rank 1 booth")
        scoped = sorted(
            (lr for lr in rows if lr[1].rank is None),
            key=lambda lr: lr[1].scope_network_id or "",
        )
        out[key] = tuple(r for _, r in [*ranked, *scoped])
    return out
