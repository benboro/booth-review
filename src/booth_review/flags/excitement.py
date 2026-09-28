"""FLAG-04: excitement passthrough.

A missing CFBD `excitementIndex` stays null all the way through this
project's pipeline. It is never coerced to 0.0, which would misrepresent an
unmeasured game (mostly non-FBS, before JOIN-07's filter) as a genuinely
boring one (docs/sources/cfbd.md, research Pitfall 3: null rates are only
meaningful once FBS-scoped).
"""

from __future__ import annotations


def excitement_value(excitement_index: float | None) -> float | None:
    """Identity passthrough: None stays None; every other value, including
    0.0, is returned unchanged.
    """
    return excitement_index
