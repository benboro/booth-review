"""The D-13/D-14 site-data contract: display fields only.

`models.py` defines the pydantic models Phase 4's static site builds against;
`schema.py` generates the JSON Schema published at docs/site-data.schema.json
from those models. No join code lives here -- this package only fixes the
shape of the data Phase 3's build produces and Phase 4 consumes.
"""
