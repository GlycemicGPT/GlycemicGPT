from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class GlucosePoint:
    timestamp: datetime
    value_mgdl: float


@dataclass
class InsulinEvent:
    timestamp: datetime
    units: float
    is_automated: bool = False


@dataclass
class LocalSeries:
    glucose: list[GlucosePoint] = field(default_factory=list)
    insulin: list[InsulinEvent] = field(default_factory=list)
