"""The people layer (JOIN-03): joins every 506 crew name to a stable, public
person_id, never to a crew string.

The public registry (data/reference/people.csv, people_reviewed.csv) is
names-only (D-05): no game-level row (who called which game) is ever written
here. A person_id is a readable slug and, once assigned, is never renamed --
merging two ids after launch would break shared URLs (SITE-12), so a later
correction adds a variant or a pointer-only override (data/reference/
person_overrides.csv, D-06) instead of renaming or deleting an id.
"""

from __future__ import annotations
