"""Read-only RR-corpus diagnostic for the Task 3 checkpoint (FLAG-01/02).

Reads only cached raw/ratingsref/telecast/*/*.json records through
parse_record, sends no request, and writes nothing. Prints aggregate counts
only (network and publisher names, never a record's figures or free text) --
per T-03-10, this output is safe to view in a terminal but is never pasted
into a commit or a public doc.
"""

from __future__ import annotations

import sys
from collections import Counter
from datetime import date

from booth_review.config import DataPaths
from booth_review.errors import ParseError, ReferenceTableError
from booth_review.flags.era import era_for, load_eras
from booth_review.reference import reference_dir
from booth_review.sources.ratingsref.parser import parse_record

_TOP_N = 15


def main(argv: list[str] | None = None) -> int:
    del argv
    paths = DataPaths.from_env()
    telecast_dir = paths.raw / "ratingsref" / "telecast"

    try:
        eras = load_eras(reference_dir())
    except ReferenceTableError:
        eras = None

    parse_errors = 0
    era_id_counts: Counter[str] = Counter()
    era_id_dates: dict[str, list[date]] = {}
    matrix: Counter[tuple[str, str]] = Counter()
    measured_by_counts: Counter[str | None] = Counter()
    blend_network_counts: Counter[str] = Counter()
    blend_publisher_counts: Counter[str | None] = Counter()

    for record_path in sorted(telecast_dir.glob("*/*.json")):
        try:
            record = parse_record(record_path.read_bytes())
        except ParseError:
            parse_errors += 1
            continue

        event_date = record.telecast.event_date
        our_era_id: str | None = None
        if eras is not None:
            try:
                our_era_id = era_for(event_date, eras).era_id
            except ReferenceTableError:
                our_era_id = None

        for claim in record.claims:
            if claim.era_id is not None:
                era_id_counts[claim.era_id] += 1
                era_id_dates.setdefault(claim.era_id, []).append(event_date)
                if our_era_id is not None:
                    matrix[(our_era_id, claim.era_id)] += 1

            measured_by_counts[claim.measured_by] += 1
            if claim.measured_by == "blend":
                for network in record.telecast.networks:
                    blend_network_counts[network] += 1
                blend_publisher_counts[claim.publisher] += 1

    print(f"RR records scanned under: {telecast_dir}")
    print(f"parse errors (skipped, not counted below): {parse_errors}")
    print()

    print("Claims per RR era_id (earliest .. latest telecast event_date):")
    for era_id, count in sorted(era_id_counts.items()):
        dates = era_id_dates[era_id]
        print(f"  {era_id}: {count} claims, {min(dates)} .. {max(dates)}")
    print()

    if eras is None:
        print(
            f"Era matrix: skipped -- data/reference/measurement_eras.csv "
            f"not yet loadable from {reference_dir()}"
        )
    else:
        print("Our era x RR era_id (claim counts):")
        for (our_era_id, rr_era_id), count in sorted(matrix.items()):
            print(f"  {our_era_id} x {rr_era_id}: {count}")
    print()

    print("measured_by counts:")
    for measured_by, count in measured_by_counts.most_common():
        print(f"  {measured_by!r}: {count}")
    print()

    print(f"blend claims by telecast network (top {_TOP_N}):")
    for network, count in blend_network_counts.most_common(_TOP_N):
        print(f"  {network}: {count}")
    print()

    print(f"blend claims by publisher (top {_TOP_N}):")
    for publisher, count in blend_publisher_counts.most_common(_TOP_N):
        print(f"  {publisher!r}: {count}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
