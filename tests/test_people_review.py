"""Tests for the people layer's suspicious-pair detection (grouping.py) and
the scan/apply review tool (review.py, Task 2).
"""

from __future__ import annotations

import csv
import shutil
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from booth_review.config import DataPaths
from booth_review.people.grouping import (
    Appearance,
    NameStats,
    find_suspicious_pairs,
    propose_decision,
)
from booth_review.people.registry import (
    PeopleRegistry,
    Person,
    load_people,
    load_reviewed,
)
from booth_review.people.review import (
    REVIEW_PEOPLE_COLUMNS,
    apply,
    collect_name_stats,
    main,
    scan,
)
from booth_review.resolve.names import csv_unsafe

SPIKE_FIXTURES = Path(__file__).parent / "fixtures" / "spike"
_EASTERN = ZoneInfo("America/New_York")

# A crew name deliberately shaped like a spreadsheet formula ("=") pairing
# with a suffix-only variant, so scan()'s csv_safe protection (T-03-19) can
# be proven end to end.
_INJECTION_WEEK_HTML = (
    b"<html><body><div id='content'><div class='inner'><article>"
    b"<h3>SATURDAY, SEPTEMBER 6</h3>"
    b"<div id='cgame'><div id='cmatchup'>Ghost Raiders @ Cmd Fielders</div>"
    b"<div id='ctime'>1:00 PM</div><div id='cntwk'>ECN</div>"
    b"<div id='canncrs'>=Equal Sign, Marty Sample</div></div>"
    b"<h3>SUNDAY, SEPTEMBER 7</h3>"
    b"<div id='cgame'><div id='cmatchup'>Ghost Raiders @ Cmd Fielders Two</div>"
    b"<div id='ctime'>4:00 PM</div><div id='cntwk'>ECN</div>"
    b"<div id='canncrs'>=Equal Sign Jr., Marty Sample</div></div>"
    b"</article></div></div></body></html>"
)


def _stats(
    folded: str,
    raw_spellings: tuple[str, ...],
    count: int,
    seasons: frozenset[int] = frozenset({2025}),
    networks: Counter[str] | None = None,
    appearances: tuple[Appearance, ...] = (),
) -> NameStats:
    return NameStats(
        raw_spellings=raw_spellings,
        folded=folded,
        count=count,
        seasons=seasons,
        networks=networks if networks is not None else Counter(),
        appearances=appearances,
    )


def _appearance(
    day: int, network: str = "ESPN", hour: int | None = 12, month: int = 9
) -> Appearance:
    kickoff = datetime(2025, month, day, hour, 0, tzinfo=_EASTERN) if hour is not None else None
    return Appearance(
        date_et=date(2025, month, day), kickoff_et=kickoff, network_raw=network, crew_folded=()
    )


# -- grouping.find_suspicious_pairs -------------------------------------------


def test_suffix_only_pair_flagged_and_proposes_different() -> None:
    a = _stats("mike golic", ("Mike Golic",), count=20)
    b = _stats("mike golic jr", ("Mike Golic Jr.",), count=15)
    stats = {a.folded: a, b.folded: b}
    pairs = find_suspicious_pairs(stats, reviewed=set(), registry=PeopleRegistry({}))
    assert len(pairs) == 1
    assert pairs[0].reason == "suffix_only"
    assert propose_decision(pairs[0]) == "different"


def test_collinsworth_pair_not_flagged() -> None:
    a = _stats("cris collinsworth", ("Cris Collinsworth",), count=100)
    b = _stats("jac collinsworth", ("Jac Collinsworth",), count=50)
    stats = {a.folded: a, b.folded: b}
    pairs = find_suspicious_pairs(stats, reviewed=set(), registry=PeopleRegistry({}))
    assert pairs == []


def test_nickname_pair_flagged() -> None:
    a = _stats("chris smith", ("Chris Smith",), count=10)
    b = _stats("christopher smith", ("Christopher Smith",), count=3)
    stats = {a.folded: a, b.folded: b}
    pairs = find_suspicious_pairs(stats, reviewed=set(), registry=PeopleRegistry({}))
    assert len(pairs) == 1
    assert pairs[0].reason == "nickname"


def test_similar_first_prefix_pair_flagged() -> None:
    a = _stats("jon smith", ("Jon Smith",), count=8)
    b = _stats("jonas smith", ("Jonas Smith",), count=2)
    stats = {a.folded: a, b.folded: b}
    pairs = find_suspicious_pairs(stats, reviewed=set(), registry=PeopleRegistry({}))
    assert len(pairs) == 1
    assert pairs[0].reason == "similar_first"


def test_near_spelling_pair_flagged() -> None:
    frequent = _stats("bob smith", ("Bob Smith",), count=15)
    rare = _stats("bob smth", ("Bob Smth",), count=1)
    stats = {frequent.folded: frequent, rare.folded: rare}
    pairs = find_suspicious_pairs(stats, reviewed=set(), registry=PeopleRegistry({}))
    assert len(pairs) == 1
    assert pairs[0].reason == "near_spelling"


def test_possible_two_people_flagged_for_overlapping_networks() -> None:
    entry = _stats(
        "sam split",
        ("Sam Split",),
        count=2,
        appearances=(_appearance(6, "ESPN", 12), _appearance(6, "ABC", 13)),
    )
    stats = {entry.folded: entry}
    pairs = find_suspicious_pairs(stats, reviewed=set(), registry=PeopleRegistry({}))
    assert len(pairs) == 1
    assert pairs[0].reason == "possible_two_people"
    assert pairs[0].name_a == pairs[0].name_b == "Sam Split"
    assert propose_decision(pairs[0]) == "one"


def test_possible_two_people_not_flagged_for_same_network() -> None:
    entry = _stats(
        "sam solo",
        ("Sam Solo",),
        count=2,
        appearances=(_appearance(6, "ESPN", 12), _appearance(6, "ESPN", 13)),
    )
    stats = {entry.folded: entry}
    pairs = find_suspicious_pairs(stats, reviewed=set(), registry=PeopleRegistry({}))
    assert pairs == []


def test_reviewed_pair_not_reflagged() -> None:
    a = _stats("mike golic", ("Mike Golic",), count=20)
    b = _stats("mike golic jr", ("Mike Golic Jr.",), count=15)
    stats = {a.folded: a, b.folded: b}
    reviewed = {frozenset({"mike golic", "mike golic jr"})}
    pairs = find_suspicious_pairs(stats, reviewed=reviewed, registry=PeopleRegistry({}))
    assert pairs == []


def test_already_merged_pair_not_reflagged() -> None:
    a = _stats("mike golic", ("Mike Golic",), count=20)
    b = _stats("mike golic jr", ("Mike Golic Jr.",), count=15)
    stats = {a.folded: a, b.folded: b}
    registry = PeopleRegistry(
        {
            "mike-golic": Person(
                person_id="mike-golic",
                canonical_name="Mike Golic",
                variants=("Mike Golic", "Mike Golic Jr."),
                usual_role="unknown",
                role_override=None,
            )
        }
    )
    pairs = find_suspicious_pairs(stats, reviewed=set(), registry=registry)
    assert pairs == []


# -- grouping.propose_decision (same/different logic) -------------------------


def test_propose_decision_same_when_no_overlap_and_shared_network() -> None:
    a = _stats(
        "chris smith",
        ("Chris Smith",),
        count=10,
        networks=Counter({"ESPN": 10}),
        appearances=(_appearance(6, "ESPN"),),
    )
    b = _stats(
        "christopher smith",
        ("Christopher Smith",),
        count=2,
        networks=Counter({"ESPN": 2}),
        appearances=(_appearance(13, "ESPN"),),
    )
    pair = find_suspicious_pairs({a.folded: a, b.folded: b}, set(), PeopleRegistry({}))[0]
    assert propose_decision(pair) == "same"


def test_propose_decision_different_when_no_shared_network() -> None:
    a = _stats(
        "chris smith",
        ("Chris Smith",),
        count=10,
        networks=Counter({"ESPN": 10}),
        appearances=(_appearance(6, "ESPN"),),
    )
    b = _stats(
        "christopher smith",
        ("Christopher Smith",),
        count=2,
        networks=Counter({"FOX": 2}),
        appearances=(_appearance(13, "FOX"),),
    )
    pair = find_suspicious_pairs({a.folded: a, b.folded: b}, set(), PeopleRegistry({}))[0]
    assert propose_decision(pair) == "different"


def test_propose_decision_different_when_appearances_overlap() -> None:
    a = _stats(
        "chris smith",
        ("Chris Smith",),
        count=10,
        networks=Counter({"ESPN": 10}),
        appearances=(_appearance(6, "ESPN", 12),),
    )
    b = _stats(
        "christopher smith",
        ("Christopher Smith",),
        count=2,
        networks=Counter({"ESPN": 2}),
        appearances=(_appearance(6, "ABC", 13),),
    )
    pair = find_suspicious_pairs({a.folded: a, b.folded: b}, set(), PeopleRegistry({}))[0]
    assert propose_decision(pair) == "different"


def test_propose_decision_different_when_share_a_crew() -> None:
    a = _stats(
        "chris smith",
        ("Chris Smith",),
        count=10,
        networks=Counter({"ESPN": 10}),
        appearances=(
            Appearance(
                date_et=date(2025, 9, 6),
                kickoff_et=None,
                network_raw="ESPN",
                crew_folded=("chris smith", "christopher smith"),
            ),
        ),
    )
    b = _stats(
        "christopher smith",
        ("Christopher Smith",),
        count=2,
        networks=Counter({"ESPN": 2}),
        appearances=(_appearance(20, "ESPN"),),
    )
    pair = find_suspicious_pairs({a.folded: a, b.folded: b}, set(), PeopleRegistry({}))[0]
    assert propose_decision(pair) == "different"


# -- review.scan / review.apply (end to end over a synthetic vault) ---------


def _build_vault(paths: DataPaths) -> None:
    games_dir = paths.raw / "cfbd" / "games"
    games_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(SPIKE_FIXTURES / "cfbd_games_2025.json", games_dir / "2025.json")

    week_dir = paths.raw / "sports506" / "2025"
    week_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(SPIKE_FIXTURES / "506_wk-01.html", week_dir / "wk-1.html")
    shutil.copy(SPIKE_FIXTURES / "506_wk-B.html", week_dir / "wk-B.html")
    (week_dir / "wk-2.html").write_bytes(_INJECTION_WEEK_HTML)


def test_collect_name_stats_counts_and_skips_placeholders(vault_paths: DataPaths) -> None:
    _build_vault(vault_paths)
    result = collect_name_stats(vault_paths)
    assert result.names_total > 0
    assert result.placeholders_skipped == 0
    assert "equal sign" in result.stats
    assert "equal sign jr" in result.stats


def test_scan_registers_names_and_writes_review_file(
    vault_paths: DataPaths, tmp_path: Path
) -> None:
    _build_vault(vault_paths)
    ref_dir = tmp_path / "reference"
    ref_dir.mkdir()
    (ref_dir / "people.csv").write_text(
        "person_id,canonical_name,variants,usual_role,role_override\n", encoding="utf-8"
    )
    (ref_dir / "people_reviewed.csv").write_text(
        "name_a,name_b,reason,decision\n", encoding="utf-8"
    )

    summary = scan(vault_paths, ref_dir)
    assert summary.names_total > 0
    assert summary.persons > 0
    assert summary.new_persons == summary.persons

    registry = load_people(ref_dir)
    assert registry.lookup("=Equal Sign") is not None
    assert registry.lookup("Marty Sample") is not None

    review_path = vault_paths.interim / "review_people.csv"
    assert review_path.is_file()
    with review_path.open(encoding="utf-8") as fh:
        header = fh.readline().strip().split(",")
    assert tuple(header) == REVIEW_PEOPLE_COLUMNS

    import csv as csv_module

    with review_path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv_module.DictReader(fh))
    injected = [r for r in rows if csv_unsafe(r["name_a"]) == "=Equal Sign"]
    assert len(injected) == 1
    assert injected[0]["name_a"].startswith("'")
    assert injected[0]["reason"] == "suffix_only"
    assert injected[0]["proposed"] == "different"


def _confirm_every_proposal(review_path: Path) -> None:
    """Simulate a reviewer copying each proposal into the decision column."""
    with review_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    for row in rows:
        row["decision"] = row["proposed"]
    with review_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def test_scan_then_apply_is_idempotent(vault_paths: DataPaths, tmp_path: Path) -> None:
    _build_vault(vault_paths)
    ref_dir = tmp_path / "reference"
    ref_dir.mkdir()
    (ref_dir / "people.csv").write_text(
        "person_id,canonical_name,variants,usual_role,role_override\n", encoding="utf-8"
    )
    (ref_dir / "people_reviewed.csv").write_text(
        "name_a,name_b,reason,decision\n", encoding="utf-8"
    )

    scan(vault_paths, ref_dir)
    _confirm_every_proposal(vault_paths.interim / "review_people.csv")
    first = apply(vault_paths, ref_dir)
    people_after_first = (ref_dir / "people.csv").read_text(encoding="utf-8")
    reviewed_after_first = (ref_dir / "people_reviewed.csv").read_text(encoding="utf-8")

    second = apply(vault_paths, ref_dir)
    people_after_second = (ref_dir / "people.csv").read_text(encoding="utf-8")
    reviewed_after_second = (ref_dir / "people_reviewed.csv").read_text(encoding="utf-8")

    assert people_after_first == people_after_second
    assert reviewed_after_first == reviewed_after_second
    assert first.persons == second.persons

    reviewed_pairs = load_reviewed(ref_dir)
    decisions = {(p.name_a, p.name_b): p.decision for p in reviewed_pairs}
    assert decisions[("=Equal Sign", "=Equal Sign Jr.")] == "different"

    registry = load_people(ref_dir)
    assert registry.lookup("=Equal Sign") != registry.lookup("=Equal Sign Jr.")


def test_main_output_contains_no_name(
    vault_paths: DataPaths, tmp_path: Path, monkeypatch, capsys
) -> None:
    _build_vault(vault_paths)
    ref_dir = tmp_path / "reference"
    ref_dir.mkdir()
    (ref_dir / "people.csv").write_text(
        "person_id,canonical_name,variants,usual_role,role_override\n", encoding="utf-8"
    )
    (ref_dir / "people_reviewed.csv").write_text(
        "name_a,name_b,reason,decision\n", encoding="utf-8"
    )
    monkeypatch.setenv("BOOTH_REVIEW_REFERENCE", str(ref_dir))

    exit_code = main(["scan"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Equal Sign" not in out
    assert "Marty Sample" not in out

    exit_code = main(["apply"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Equal Sign" not in out
    assert "Marty Sample" not in out


# -- WR-10: apply never applies a proposal nobody confirmed -----------------------------------


def test_apply_ignores_unconfirmed_proposals_and_counts_them(
    vault_paths: DataPaths, tmp_path: Path
) -> None:
    _build_vault(vault_paths)
    ref_dir = tmp_path / "reference"
    ref_dir.mkdir()
    (ref_dir / "people.csv").write_text(
        "person_id,canonical_name,variants,usual_role,role_override\n", encoding="utf-8"
    )
    (ref_dir / "people_reviewed.csv").write_text(
        "name_a,name_b,reason,decision\n", encoding="utf-8"
    )

    scan(vault_paths, ref_dir)
    with (vault_paths.interim / "review_people.csv").open(newline="", encoding="utf-8") as fh:
        review_rows = list(csv.DictReader(fh))
    assert review_rows
    assert all(row["proposed"] for row in review_rows)
    people_before = (ref_dir / "people.csv").read_text(encoding="utf-8")

    summary = apply(vault_paths, ref_dir)

    assert summary.pairs_applied == 0
    assert summary.undecided == len(review_rows)
    assert load_reviewed(ref_dir) == []
    assert (ref_dir / "people.csv").read_text(encoding="utf-8") == people_before
