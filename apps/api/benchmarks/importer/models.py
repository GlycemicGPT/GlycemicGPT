from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from src.core.treatment_safety.models import MAX_GLUCOSE_MGDL, MIN_GLUCOSE_MGDL


@dataclass
class GlucosePoint:
    timestamp: datetime
    value_mgdl: float

    def __post_init__(self) -> None:
        # The canonical glucose invariant lives on the model itself, so no caller
        # (parser, DB importer, or a directly-constructed series) can introduce an
        # out-of-range value that would silently skew a benchmark. Parsers drop
        # out-of-range rows before constructing; this is the last-resort guard.
        if not MIN_GLUCOSE_MGDL <= self.value_mgdl <= MAX_GLUCOSE_MGDL:
            raise ValueError(
                f"GlucosePoint.value_mgdl must be within "
                f"{MIN_GLUCOSE_MGDL}-{MAX_GLUCOSE_MGDL} mg/dL, got {self.value_mgdl}"
            )


@dataclass
class InsulinEvent:
    timestamp: datetime
    units: float
    is_automated: bool = False


@dataclass
class LocalSeries:
    glucose: list[GlucosePoint] = field(default_factory=list)
    insulin: list[InsulinEvent] = field(default_factory=list)
