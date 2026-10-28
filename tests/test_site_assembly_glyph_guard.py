"""Site assembly runs the same heading-glyph guard the pipeline writers run.

`load_site_payload` and `sport_payload_from_bytes` also read hand-placed files and the live blob
the publisher carries over, so a name the serif face lacks must be rejected there too.
Synthetic fixtures only.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from booth_review.build.site_assembly import (
    load_site_payload,
    load_sport_payload,
    sport_payload_from_bytes,
)
from booth_review.errors import SiteBuildError

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "contract"
BAD = "Ωmega State"


def test_cfb_assembly_rejects_a_team_the_serif_face_lacks(tmp_path: Path) -> None:
    raw = json.loads((FIXTURES / "site-data.fixture.json").read_text(encoding="utf-8"))
    raw["lookups"]["teams"][0]["name"] = BAD
    source = tmp_path / "site-data.json"
    source.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(SiteBuildError, match="U\\+03A9"):
        load_site_payload(source)


def test_cfb_assembly_still_accepts_the_fixture() -> None:
    load_site_payload(FIXTURES / "site-data.fixture.json")


def test_nfl_assembly_rejects_a_franchise_the_serif_face_lacks(tmp_path: Path) -> None:
    raw = json.loads((FIXTURES / "nfl-data.fixture.json").read_text(encoding="utf-8"))
    raw["lookups"]["franchises"][0]["name"] = BAD
    source = tmp_path / "nfl-data.json"
    source.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(SiteBuildError, match="U\\+03A9"):
        load_sport_payload("nfl", source)
    with pytest.raises(SiteBuildError, match="U\\+03A9"):
        sport_payload_from_bytes("nfl", source.read_bytes())


def test_nfl_assembly_rejects_a_team_name_the_serif_face_lacks() -> None:
    raw = json.loads((FIXTURES / "nfl-data.fixture.json").read_text(encoding="utf-8"))
    raw["lookups"]["team_names"][0]["name"] = BAD
    with pytest.raises(SiteBuildError, match="U\\+03A9"):
        sport_payload_from_bytes("nfl", json.dumps(raw).encode("utf-8"))


def test_mlb_assembly_rejects_a_club_the_serif_face_lacks() -> None:
    raw = json.loads((FIXTURES / "mlb-data.fixture.json").read_text(encoding="utf-8"))
    raw["lookups"]["clubs"][0]["name"] = BAD
    with pytest.raises(SiteBuildError, match="U\\+03A9"):
        sport_payload_from_bytes("mlb", json.dumps(raw).encode("utf-8"))
