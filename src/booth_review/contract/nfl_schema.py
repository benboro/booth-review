"""Generates docs/nfl-data.schema.json from contract/nfl_models.py (999.5 D-07).

`tests/test_nfl_contract.py`'s drift test fails if the committed schema file
ever diverges from what `render_schema()` produces from the current models.
"""

from __future__ import annotations

from pathlib import Path

from booth_review.contract.nfl_models import NFL_SCHEMA_VERSION, NflSiteData
from booth_review.transport.cache import atomic_write_json

SCHEMA_PATH = Path("docs/nfl-data.schema.json")


def render_schema() -> dict[str, object]:
    """The JSON Schema for `NflSiteData`, with identifying metadata added."""
    schema = NflSiteData.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = f"booth-review/nfl-data/{NFL_SCHEMA_VERSION}"
    schema["title"] = "booth-review NFL data"
    return schema


def main(argv: list[str] | None = None) -> int:
    del argv  # no arguments; kept for a consistent module-main signature
    atomic_write_json(SCHEMA_PATH, render_schema())
    print(f"wrote docs/nfl-data.schema.json (schema_version {NFL_SCHEMA_VERSION})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
