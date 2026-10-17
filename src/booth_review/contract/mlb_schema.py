"""Generates docs/mlb-data.schema.json from contract/mlb_models.py.

`tests/test_mlb_contract.py`'s drift test fails if the committed schema file
ever diverges from what `render_schema()` produces from the current models.
"""

from __future__ import annotations

from pathlib import Path

from booth_review.contract.mlb_models import MLB_SCHEMA_VERSION, MlbSiteData
from booth_review.transport.cache import atomic_write_json

SCHEMA_PATH = Path("docs/mlb-data.schema.json")


def render_schema() -> dict[str, object]:
    """The JSON Schema for `MlbSiteData`, with identifying metadata added."""
    schema = MlbSiteData.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = f"booth-review/mlb-data/{MLB_SCHEMA_VERSION}"
    schema["title"] = "booth-review MLB data"
    return schema


def main(argv: list[str] | None = None) -> int:
    del argv  # no arguments; kept for a consistent module-main signature
    atomic_write_json(SCHEMA_PATH, render_schema())
    print(f"wrote docs/mlb-data.schema.json (schema_version {MLB_SCHEMA_VERSION})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
