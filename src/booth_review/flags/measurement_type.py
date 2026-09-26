"""FLAG-02: Nielsen+Adobe measurement-type flag.

Ratings Reference's `measured_by` vocabulary has exactly two values across
the full corpus: "nielsen" and "blend" -- no literal "adobe" string exists
anywhere in RR's data (research Assumption A1). "blend" is mapped to this
project's `nielsen_adobe` measurement type; that mapping is confirmed by the
user at the Task 3 checkpoint against blend-claim network/publisher
evidence (docs/PLAN.md section 6's "some NBC and Peacock figures combine
Nielsen and Adobe Analytics"), not assumed from RR's vocabulary alone.
"""

from __future__ import annotations

from typing import Literal

MeasurementType = Literal["nielsen", "nielsen_adobe", "unknown"]

MEASURED_BY_MAP: dict[str, MeasurementType] = {
    "nielsen": "nielsen",
    # research Assumption A1, confirmed at the Task 3 checkpoint: RR's
    # "blend" measured_by value is this project's Nielsen+Adobe type.
    "blend": "nielsen_adobe",
}


def measurement_type(measured_by: str | None) -> MeasurementType:
    """RR's measured_by value mapped to this project's measurement type.
    None or any value MEASURED_BY_MAP doesn't recognize returns "unknown"
    rather than a guess.
    """
    if measured_by is None:
        return "unknown"
    return MEASURED_BY_MAP.get(measured_by, "unknown")
