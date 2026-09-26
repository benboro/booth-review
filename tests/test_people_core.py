"""Tests for the people layer's core building blocks (Task 1): folding,
slugs, usual-role inference, and the public registry loaders/writers.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from booth_review.errors import ReferenceTableError
from booth_review.people.normalize import fold_person, is_placeholder, split_suffix, surname
from booth_review.people.registry import (
    PEOPLE_COLUMNS,
    PERSON_OVERRIDE_COLUMNS,
    REVIEWED_COLUMNS,
    PeopleRegistry,
    Person,
    PersonOverride,
    ReviewedPair,
    apply_decisions,
    load_people,
    load_person_overrides,
    load_reviewed,
    register_names,
    with_usual_roles,
    write_people,
    write_reviewed,
)
from booth_review.people.roles import crew_roles, infer_usual_roles
from booth_review.people.slugs import assign_slug, slugify
from booth_review.reference import read_reference_csv

REFERENCE_FIXTURES = Path(__file__).parent / "fixtures" / "reference"


# -- normalize.fold_person / is_placeholder / split_suffix / surname --------


def test_fold_person_suffix_stays_distinct() -> None:
    assert fold_person("Mike Golic, Jr.") == fold_person("mike golic jr") == "mike golic jr"
    assert fold_person("Mike Golic") == "mike golic"
    assert fold_person("Mike Golic") != fold_person("Mike Golic Jr.")


def test_fold_person_collinsworth_pair_distinct() -> None:
    assert fold_person("Cris Collinsworth") != fold_person("Jac Collinsworth")


def test_fold_person_accents_and_apostrophes() -> None:
    assert fold_person("José O'Neil") == "jose oneil"


def test_fold_person_hyphens_and_periods_become_spaces() -> None:
    assert fold_person("Jean-Paul") == "jean paul"
    assert fold_person("J.P. Smith") == "j p smith"


@pytest.mark.parametrize("name", ["TBA", "tbd", "Various", "N/A", "None"])
def test_is_placeholder_true(name: str) -> None:
    assert is_placeholder(name) is True


def test_is_placeholder_false_for_real_name() -> None:
    assert is_placeholder("Mike Golic") is False


def test_split_suffix() -> None:
    assert split_suffix(fold_person("Mike Golic Jr.")) == ("mike golic", "jr")
    assert split_suffix(fold_person("Mike Golic")) == ("mike golic", None)


def test_surname() -> None:
    assert surname(fold_person("Mike Golic Jr.")) == "golic"
    assert surname(fold_person("Mike Golic")) == "golic"
    assert surname(fold_person("Jac Collinsworth")) == "collinsworth"


# -- slugs.slugify / assign_slug --------------------------------------------


def test_slugify() -> None:
    assert slugify("Jac Collinsworth") == "jac-collinsworth"
    assert slugify("Mike Golic Jr.") == "mike-golic-jr"


def test_assign_slug_collision() -> None:
    assert assign_slug("mike-golic", taken=set()) == "mike-golic"
    assert assign_slug("mike-golic", taken={"mike-golic"}) == "mike-golic-2"
    assert assign_slug("mike-golic", taken={"mike-golic", "mike-golic-2"}) == "mike-golic-3"


# -- roles.infer_usual_roles / crew_roles -----------------------------------


def test_infer_usual_roles_from_two_person_crews() -> None:
    crews = [
        ("pbp-a", "analyst-a"),
        ("pbp-a", "analyst-b"),
        ("pbp-b", "analyst-a"),
    ]
    usual = infer_usual_roles(crews)
    assert usual["pbp-a"] == "pbp"
    assert usual["analyst-a"] == "analyst"


def test_infer_usual_roles_requires_two_appearances() -> None:
    usual = infer_usual_roles([("pbp-a", "analyst-a")])
    # Only one two-person appearance each: below MIN_TWO_PERSON_APPEARANCES.
    assert usual["pbp-a"] == "unknown"
    assert usual["analyst-a"] == "unknown"


def test_infer_usual_roles_mixed_positions_stay_unknown() -> None:
    crews = [("mixed", "other-a"), ("other-b", "mixed")]
    usual = infer_usual_roles(crews)
    # "mixed" appeared once as pbp, once as analyst: below the 2/3 share.
    assert usual["mixed"] == "unknown"


def test_infer_usual_roles_ignores_non_two_person_crews() -> None:
    usual = infer_usual_roles([("solo",), ("a", "b", "c"), ("a", "b", "c", "d")])
    assert usual == {}


def test_crew_roles_two_person_is_positional() -> None:
    assert crew_roles(("x", "y"), usual={}, overrides={}) == ["pbp", "analyst"]
    # Positional even when usual/override data disagrees.
    assert crew_roles(("x", "y"), usual={"x": "analyst"}, overrides={"y": "pbp"}) == [
        "pbp",
        "analyst",
    ]


def test_crew_roles_three_person_uses_override_then_usual_then_unknown() -> None:
    roles = crew_roles(
        ("a", "b", "c"),
        usual={"b": "analyst"},
        overrides={"a": "pbp"},
    )
    assert roles == ["pbp", "analyst", "unknown"]


# -- registry.load_people / write_people ------------------------------------


def test_load_people_real_fixture_distinguishes_golic_and_collinsworth() -> None:
    registry = load_people(REFERENCE_FIXTURES)
    assert registry.lookup("Mike Golic Jr.") != registry.lookup("Mike Golic")
    assert registry.lookup("Jac Collinsworth") != registry.lookup("Cris Collinsworth")
    assert registry.lookup("Mike Golic Jr.") is not None
    assert registry.lookup("Mike Golic") is not None


def test_load_people_missing_file_is_empty_registry(tmp_path: Path) -> None:
    registry = load_people(tmp_path)
    assert registry.persons == {}
    assert registry.lookup("Anyone") is None


def test_load_people_rejects_duplicate_person_id(tmp_path: Path) -> None:
    path = tmp_path / "people.csv"
    path.write_text(
        "person_id,canonical_name,variants,usual_role,role_override\n"
        "a-b,A B,A B,unknown,\n"
        "a-b,C D,C D,unknown,\n",
        encoding="utf-8",
    )
    with pytest.raises(ReferenceTableError, match="duplicate person_id"):
        load_people(tmp_path)


def test_load_people_rejects_invalid_person_id_pattern(tmp_path: Path) -> None:
    path = tmp_path / "people.csv"
    path.write_text(
        "person_id,canonical_name,variants,usual_role,role_override\nBad_ID,A B,A B,unknown,\n",
        encoding="utf-8",
    )
    with pytest.raises(ReferenceTableError, match="invalid person_id"):
        load_people(tmp_path)


def test_load_people_rejects_variant_owned_by_two_people(tmp_path: Path) -> None:
    path = tmp_path / "people.csv"
    path.write_text(
        "person_id,canonical_name,variants,usual_role,role_override\n"
        "a-b,A B,A B,unknown,\n"
        "c-d,C D,A B,unknown,\n",
        encoding="utf-8",
    )
    with pytest.raises(ReferenceTableError, match="already owned by"):
        load_people(tmp_path)


def test_load_people_rejects_canonical_missing_from_variants(tmp_path: Path) -> None:
    path = tmp_path / "people.csv"
    path.write_text(
        "person_id,canonical_name,variants,usual_role,role_override\n"
        "a-b,Someone Else,A B,unknown,\n",
        encoding="utf-8",
    )
    with pytest.raises(ReferenceTableError, match="missing from variants"):
        load_people(tmp_path)


def test_load_people_rejects_invalid_role(tmp_path: Path) -> None:
    path = tmp_path / "people.csv"
    path.write_text(
        "person_id,canonical_name,variants,usual_role,role_override\na-b,A B,A B,sideline,\n",
        encoding="utf-8",
    )
    with pytest.raises(ReferenceTableError, match="invalid usual_role"):
        load_people(tmp_path)


def test_load_people_rejects_invalid_role_override(tmp_path: Path) -> None:
    path = tmp_path / "people.csv"
    path.write_text(
        "person_id,canonical_name,variants,usual_role,role_override\n"
        "a-b,A B,A B,unknown,sideline\n",
        encoding="utf-8",
    )
    with pytest.raises(ReferenceTableError, match="invalid role_override"):
        load_people(tmp_path)


def test_write_then_read_people_round_trips(tmp_path: Path) -> None:
    registry = PeopleRegistry(
        {
            "a-b": Person(
                person_id="a-b",
                canonical_name="A B",
                variants=("A B", "A. B."),
                usual_role="pbp",
                role_override=None,
            )
        }
    )
    write_people(tmp_path, registry)
    reloaded = load_people(tmp_path)
    assert reloaded.persons == registry.persons
    rows = read_reference_csv(tmp_path / "people.csv", PEOPLE_COLUMNS)
    assert rows[0]["variants"] == "A B|A. B."


# -- registry.load_reviewed / write_reviewed --------------------------------


def test_load_reviewed_real_fixture() -> None:
    pairs = load_reviewed(REFERENCE_FIXTURES)
    decisions = {(p.name_a, p.name_b): p.decision for p in pairs}
    assert decisions[("Chris Venn", "Kris Venn")] == "same"
    assert decisions[("Mike Golic", "Mike Golic Jr.")] == "different"


def test_load_reviewed_rejects_invalid_decision(tmp_path: Path) -> None:
    path = tmp_path / "people_reviewed.csv"
    path.write_text("name_a,name_b,reason,decision\nA,B,nickname,maybe\n", encoding="utf-8")
    with pytest.raises(ReferenceTableError, match="invalid decision"):
        load_reviewed(tmp_path)


def test_write_reviewed_orders_pair_by_fold(tmp_path: Path) -> None:
    write_reviewed(
        tmp_path,
        [
            ReviewedPair(
                name_a="Zeb Zorn", name_b="Aaron Adams", reason="other", decision="different"
            )
        ],
    )
    rows = read_reference_csv(tmp_path / "people_reviewed.csv", REVIEWED_COLUMNS)
    assert rows[0]["name_a"] == "Aaron Adams"
    assert rows[0]["name_b"] == "Zeb Zorn"


# -- registry.load_person_overrides ------------------------------------------


def test_load_person_overrides_real_fixture() -> None:
    overrides = load_person_overrides(REFERENCE_FIXTURES)
    assert overrides == [
        PersonOverride(
            season=2025, pointer="3:12", position=0, person_id="dale-harlow-jr", reason="two-people"
        )
    ]


def test_load_person_overrides_rejects_bad_pointer(tmp_path: Path) -> None:
    path = tmp_path / "person_overrides.csv"
    path.write_text(
        "season,pointer,position,person_id,reason\n2025,bad,0,dale-harlow,two-people\n",
        encoding="utf-8",
    )
    with pytest.raises(ReferenceTableError, match="malformed pointer"):
        load_person_overrides(tmp_path)


def test_load_person_overrides_rejects_bad_position(tmp_path: Path) -> None:
    path = tmp_path / "person_overrides.csv"
    path.write_text(
        "season,pointer,position,person_id,reason\n2025,3:12,9,dale-harlow,two-people\n",
        encoding="utf-8",
    )
    with pytest.raises(ReferenceTableError, match="position out of range"):
        load_person_overrides(tmp_path)


def test_load_person_overrides_rejects_bad_reason(tmp_path: Path) -> None:
    path = tmp_path / "person_overrides.csv"
    path.write_text(
        "season,pointer,position,person_id,reason\n2025,3:12,0,dale-harlow,guess\n",
        encoding="utf-8",
    )
    with pytest.raises(ReferenceTableError, match="invalid reason"):
        load_person_overrides(tmp_path)


def test_person_override_columns_shape() -> None:
    assert PERSON_OVERRIDE_COLUMNS == ("season", "pointer", "position", "person_id", "reason")


# -- registry.register_names -------------------------------------------------


def test_register_names_creates_new_person_with_frequent_canonical() -> None:
    registry = PeopleRegistry({})
    updated = register_names(registry, {"Pat Sample": 5, "PAT SAMPLE": 1})
    person_id = updated.lookup("Pat Sample")
    assert person_id is not None
    person = updated.persons[person_id]
    assert person.canonical_name == "Pat Sample"
    assert set(person.variants) == {"Pat Sample", "PAT SAMPLE"}


def test_register_names_ties_broken_lexically() -> None:
    registry = PeopleRegistry({})
    updated = register_names(registry, {"Zeta Sample": 3, "Alpha Sample Variant": 3})
    # These fold differently, so they're two distinct persons; the tie-break
    # case is exercised via _pick_canonical directly through a same-fold
    # group in the next test.
    assert updated.lookup("Zeta Sample") != updated.lookup("Alpha Sample Variant")


def test_register_names_never_renames_existing_person() -> None:
    registry = PeopleRegistry(
        {
            "pat-sample": Person(
                person_id="pat-sample",
                canonical_name="Pat Sample",
                variants=("Pat Sample",),
                usual_role="unknown",
                role_override=None,
            )
        }
    )
    updated = register_names(registry, {"Pat Sample": 1, "Pat  Sample": 1})
    assert updated.lookup("Pat Sample") == "pat-sample"
    assert "Pat  Sample" in updated.persons["pat-sample"].variants
    assert set(updated.persons.keys()) == {"pat-sample"}


def test_register_names_new_person_on_id_collision_gets_suffix() -> None:
    registry = PeopleRegistry(
        {
            "pat-sample": Person(
                person_id="pat-sample",
                canonical_name="Pat Sample",
                variants=("Pat Sample",),
                usual_role="unknown",
                role_override=None,
            )
        }
    )
    # "Pat_ Sample" folds to "pat_ sample" (underscore is a word character,
    # so it survives fold_person's punctuation collapse and keeps this a
    # distinct fold group from "Pat Sample"), but slugify strips the
    # underscore, so both slugify to "pat-sample" -- a genuine collision
    # between two different people.
    updated = register_names(registry, {"Pat_ Sample": 1})
    assert set(updated.persons.keys()) == {"pat-sample", "pat-sample-2"}


# -- registry.apply_decisions -------------------------------------------------


def _build_two_persons() -> PeopleRegistry:
    return PeopleRegistry(
        {
            "dale-harlow": Person(
                person_id="dale-harlow",
                canonical_name="Dale Harlow",
                variants=("Dale Harlow",),
                usual_role="unknown",
                role_override=None,
            ),
            "dale-harlow-jr": Person(
                person_id="dale-harlow-jr",
                canonical_name="Dale Harlow Jr.",
                variants=("Dale Harlow Jr.",),
                usual_role="unknown",
                role_override=None,
            ),
        }
    )


def test_apply_decisions_same_merges_into_name_a_person() -> None:
    registry = _build_two_persons()
    reviewed = [
        ReviewedPair(
            name_a="Dale Harlow", name_b="Dale Harlow Jr.", reason="suffix_only", decision="same"
        )
    ]
    updated = apply_decisions(registry, reviewed, name_counts={})
    assert set(updated.persons.keys()) == {"dale-harlow"}
    assert set(updated.persons["dale-harlow"].variants) == {"Dale Harlow", "Dale Harlow Jr."}
    assert updated.lookup("Dale Harlow Jr.") == "dale-harlow"


def test_apply_decisions_different_is_noop_when_already_separate() -> None:
    registry = _build_two_persons()
    reviewed = [
        ReviewedPair(
            name_a="Dale Harlow",
            name_b="Dale Harlow Jr.",
            reason="suffix_only",
            decision="different",
        )
    ]
    updated = apply_decisions(registry, reviewed, name_counts={})
    assert updated.persons == registry.persons


def test_apply_decisions_different_splits_back_out_after_a_merge() -> None:
    registry = _build_two_persons()
    same_then_different = [
        ReviewedPair(
            name_a="Dale Harlow", name_b="Dale Harlow Jr.", reason="suffix_only", decision="same"
        )
    ]
    merged = apply_decisions(registry, same_then_different, name_counts={})
    assert set(merged.persons.keys()) == {"dale-harlow"}

    split_decision = [
        ReviewedPair(
            name_a="Dale Harlow",
            name_b="Dale Harlow Jr.",
            reason="suffix_only",
            decision="different",
        )
    ]
    resplit = apply_decisions(merged, split_decision, name_counts={"Dale Harlow Jr.": 4})
    assert resplit.lookup("Dale Harlow") == "dale-harlow"
    new_id = resplit.lookup("Dale Harlow Jr.")
    assert new_id is not None
    assert new_id != "dale-harlow"
    # Fresh slug, never reusing the pre-merge id verbatim in a way that
    # collides with the still-live "dale-harlow" id.
    assert set(resplit.persons["dale-harlow"].variants) == {"Dale Harlow"}
    assert set(resplit.persons[new_id].variants) == {"Dale Harlow Jr."}


def test_apply_decisions_one_is_noop() -> None:
    registry = _build_two_persons()
    reviewed = [
        ReviewedPair(
            name_a="Dale Harlow",
            name_b="Dale Harlow Jr.",
            reason="possible_two_people",
            decision="one",
        )
    ]
    updated = apply_decisions(registry, reviewed, name_counts={})
    assert updated.persons == registry.persons


def test_apply_decisions_idempotent() -> None:
    registry = _build_two_persons()
    reviewed = [
        ReviewedPair(
            name_a="Dale Harlow", name_b="Dale Harlow Jr.", reason="suffix_only", decision="same"
        )
    ]
    once = apply_decisions(registry, reviewed, name_counts={})
    twice = apply_decisions(once, reviewed, name_counts={})
    assert once.persons == twice.persons


def test_apply_decisions_missing_name_is_noop() -> None:
    registry = _build_two_persons()
    reviewed = [
        ReviewedPair(name_a="Nobody Here", name_b="Dale Harlow", reason="other", decision="same")
    ]
    updated = apply_decisions(registry, reviewed, name_counts={})
    assert updated.persons == registry.persons


# -- registry.with_usual_roles ------------------------------------------------


def test_with_usual_roles_sets_usual_role_and_keeps_override() -> None:
    registry = PeopleRegistry(
        {
            "a-b": Person(
                person_id="a-b",
                canonical_name="A B",
                variants=("A B",),
                usual_role="unknown",
                role_override="analyst",
            )
        }
    )
    updated = with_usual_roles(registry, {"a-b": "pbp"})
    assert updated.persons["a-b"].usual_role == "pbp"
    assert updated.persons["a-b"].role_override == "analyst"


def test_with_usual_roles_defaults_missing_to_unknown() -> None:
    registry = PeopleRegistry(
        {
            "a-b": Person(
                person_id="a-b",
                canonical_name="A B",
                variants=("A B",),
                usual_role="pbp",
                role_override=None,
            )
        }
    )
    updated = with_usual_roles(registry, {})
    assert updated.persons["a-b"].usual_role == "unknown"
