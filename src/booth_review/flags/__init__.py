"""FLAG-01..04: measurement-era, measurement-type, event, and model-break
flags, each derived from a dated public reference table (data/reference/*.csv)
keyed on the telecast's own air date -- never from a date literal in code,
and never from Ratings Reference's own era_id, which this project uses only
as a cross-check (research Pitfall 2), not to assign an era.
"""

from __future__ import annotations
