"""Schemas for the Medtronic CareLink manual historical-import (feature B).

Stateless: the captured ``auth_tmp_token`` is sent in the ``X-CareLink-Token``
request HEADER (NOT the JSON body) so it can never land in a body-validation
422 echo or in request-body logging. The backend uses it per-request and never
stores it. No credential storage / scheduler / sync-state -- a manual import
completes within one ~50-min token life.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator, model_validator

from src.core.medtronic_regions import SUPPORTED_MEDTRONIC_REGIONS

#: Max span per manual import. Conservative start; CareLink CSV is CGM-dense, so
#: re-measure the fetch time vs the web-proxy timeout on a real range and tune
#: (mirrors the Tandem 31-day cap process).
MAX_IMPORT_DAYS = 31

#: Header carrying the captured CareLink session token (kept out of the body).
CARELINK_TOKEN_HEADER = "X-CareLink-Token"

#: Upper bound on the captured token length -- reject absurd payloads early. A
#: real auth_tmp_token (a JWT) is ~1-2 KB.
MAX_TOKEN_LEN = 8192


def _validate_region(v: str) -> str:
    key = (v or "").strip().upper()
    if key not in SUPPORTED_MEDTRONIC_REGIONS:
        raise ValueError(
            f"Unsupported region {v!r}; supported: {sorted(SUPPORTED_MEDTRONIC_REGIONS)}"
        )
    return key


class MedtronicAvailabilityRequest(BaseModel):
    region: str

    _region = field_validator("region")(_validate_region)


class MedtronicAvailabilityResponse(BaseModel):
    start: datetime | None
    end: datetime | None


class MedtronicImportRequest(BaseModel):
    region: str
    start_date: date
    end_date: date
    tz: str = Field(
        description="IANA timezone of the pump's local time, e.g. America/Chicago"
    )

    _region = field_validator("region")(_validate_region)

    @field_validator("tz")
    @classmethod
    def _valid_tz(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except Exception as e:
            raise ValueError(f"Invalid IANA timezone: {v!r}") from e
        return v

    @model_validator(mode="after")
    def _valid_range(self) -> MedtronicImportRequest:
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        if self.end_date > datetime.now(UTC).date():
            raise ValueError("end_date cannot be in the future")
        # Inclusive day count: 2025-01-01..2025-01-31 is 31 days, not 30.
        span_days = (self.end_date - self.start_date).days + 1
        if span_days > MAX_IMPORT_DAYS:
            raise ValueError(
                f"Date range too large ({span_days} days); "
                f"max {MAX_IMPORT_DAYS} days per import"
            )
        return self


class MedtronicImportResponse(BaseModel):
    message: str
    glucose_fetched: int
    glucose_stored: int
    events_fetched: int
    events_stored: int
