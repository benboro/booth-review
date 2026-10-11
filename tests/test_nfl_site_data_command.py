"""`booth-review nfl site-data` on the synthetic NFL build vault."""

from __future__ import annotations

import json

import pytest
from test_nfl_pipeline import _git, _seed, vault  # noqa: F401

from booth_review.cli import main
from booth_review.config import DataPaths
from booth_review.contract.nfl_models import validate_nfl_site_data

SITE_JSON = "processed/nfl-data.json"


def test_site_data_rebuilds_without_commit(
    vault: DataPaths,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(vault, rr=["NFL Network"])
    assert main(["nfl", "build", "--season", "2014", "--no-commit"]) == 0
    assert not (vault.vault / SITE_JSON).exists()
    capsys.readouterr()
    assert main(["nfl", "site-data", "--no-commit"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("nfl site data: 3 games, ")
    assert "Ana" not in out and "Otters" not in out
    validate_nfl_site_data(json.loads((vault.vault / SITE_JSON).read_text(encoding="utf-8")))


def test_site_data_commits_only_its_path(vault: DataPaths) -> None:  # noqa: F811
    _seed(vault, rr=["NFL Network"])
    assert main(["nfl", "build", "--season", "2014"]) == 0
    assert main(["nfl", "site-data"]) == 0
    files = _git(vault, "show", "--name-only", "--format=%s", "HEAD").splitlines()
    assert files[0].startswith("build: nfl_site ")
    assert [f for f in files[1:] if f] == [SITE_JSON]


def test_site_data_without_tables_asks_for_a_build(
    vault: DataPaths,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(["nfl", "site-data", "--no-commit"])
    assert code != 0
    assert "run `booth-review nfl build` first" in capsys.readouterr().err
