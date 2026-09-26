"""Generates docs/site-data.schema.json from contract/models.py (D-14).

`tests/test_contract.py`'s drift test fails if the committed schema file ever
diverges from what `render_schema()` produces from the current models, so
the two can never quietly disagree.
"""

from __future__ import annotations

from pathlib import Path

from booth_review.contract.models import SCHEMA_VERSION, SiteData
from booth_review.transport.cache import atomic_write_json

SCHEMA_PATH = Path("docs/site-data.schema.json")


def render_schema() -> dict[str, object]:
    """The JSON Schema for `SiteData`, with the identifying metadata a bare
    `model_json_schema()` call doesn't add on its own.
    """
    schema = SiteData.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = f"booth-review/site-data/{SCHEMA_VERSION}"
    schema["title"] = "booth-review site data"
    return schema


def main(argv: list[str] | None = None) -> int:
    del argv  # no arguments; kept for a consistent module-main signature
    atomic_write_json(SCHEMA_PATH, render_schema())
    print(f"wrote docs/site-data.schema.json (schema_version {SCHEMA_VERSION})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
