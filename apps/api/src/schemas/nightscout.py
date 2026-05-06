"""Story 43.1: Nightscout connection schemas.

Pydantic request/response shapes for the
`/api/integrations/nightscout` endpoints.

Secrets are NEVER returned in any response shape -- responses include
only `has_credential` (boolean) so the UI can indicate "credential is
set" without exposing it.
"""

import uuid
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

from src.models.nightscout_connection import (
    INITIAL_SYNC_WINDOW_DAYS_OPTIONS,
    SYNC_INTERVAL_MAX_MINUTES,
    SYNC_INTERVAL_MIN_MINUTES,
    NightscoutApiVersion,
    NightscoutAuthType,
    NightscoutSyncStatus,
)

# Maximum length we accept for credentials at the wire layer. Real
# Nightscout API_SECRETs are typically 12-64 chars; v3 JWTs are larger
# but bounded. 4 KB is a generous headroom that still rejects garbage.
_MAX_CREDENTIAL_LEN = 4096


def _normalize_base_url(value: str) -> str:
    """Validate + normalize a Nightscout base URL.

    Reject anything that isn't an http(s) URL with a host. Reject
    query strings and fragments outright -- they have no legitimate
    use here and they let attackers smuggle credentials past simple
    string comparisons (e.g. `https://valid.com/?@evil.com`).
    Preserves the path (some NS deployments live at /nightscout).
    """
    value = value.strip()
    if not value:
        raise ValueError("base_url must not be empty")
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("base_url must be an http:// or https:// URL")
    if not parsed.netloc:
        raise ValueError("base_url must include a host")
    if parsed.query:
        raise ValueError("base_url must not contain a query string")
    if parsed.fragment:
        raise ValueError("base_url must not contain a fragment (#)")
    # Reject embedded credentials in the URL (https://user:pass@host).
    if parsed.username or parsed.password:
        raise ValueError("base_url must not contain embedded user:password credentials")
    # Just trim a single trailing slash.
    if value.endswith("/"):
        value = value[:-1]
    return value


# ---------------------------------------------------------------------------
# Create / update
# ---------------------------------------------------------------------------


class NightscoutConnectionCreate(BaseModel):
    """Request body for POST /api/integrations/nightscout."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=120,
        description="Human-readable label shown in dashboards",
    )
    base_url: str = Field(
        ...,
        max_length=500,
        description="Nightscout instance URL, e.g. https://my-ns.example.com",
    )
    auth_type: NightscoutAuthType = Field(
        default=NightscoutAuthType.AUTO,
        description="secret | token | auto (auto-detect)",
    )
    credential: str = Field(
        ...,
        min_length=1,
        max_length=_MAX_CREDENTIAL_LEN,
        description="API_SECRET (v1) or bearer token (v3)",
    )
    api_version: NightscoutApiVersion = Field(
        default=NightscoutApiVersion.AUTO,
        description="v1 | v3 | auto (auto-detect)",
    )
    sync_interval_minutes: int = Field(
        default=5,
        ge=SYNC_INTERVAL_MIN_MINUTES,
        le=SYNC_INTERVAL_MAX_MINUTES,
        description="How often to poll. Default 5 min; bounded 1 min - 24 hr.",
    )
    initial_sync_window_days: int = Field(
        default=7,
        validate_default=True,  # Run _check_window against the default
        description="Days of history to backfill on first sync. 0 means 'all available'.",
    )

    @field_validator("base_url")
    @classmethod
    def _check_base_url(cls, v: str) -> str:
        return _normalize_base_url(v)

    @field_validator("initial_sync_window_days")
    @classmethod
    def _check_window(cls, v: int) -> int:
        if v not in INITIAL_SYNC_WINDOW_DAYS_OPTIONS:
            raise ValueError(
                f"initial_sync_window_days must be one of "
                f"{sorted(INITIAL_SYNC_WINDOW_DAYS_OPTIONS)}"
            )
        return v


class NightscoutConnectionUpdate(BaseModel):
    """Request body for PATCH /api/integrations/nightscout/{id}.

    All fields optional. Setting `credential` triggers a re-test on the
    server side (Story 43.1 AC4).
    """

    name: str | None = Field(default=None, min_length=1, max_length=120)
    base_url: str | None = Field(default=None, max_length=500)
    auth_type: NightscoutAuthType | None = None
    credential: str | None = Field(
        default=None,
        min_length=1,
        max_length=_MAX_CREDENTIAL_LEN,
    )
    api_version: NightscoutApiVersion | None = None
    is_active: bool | None = None
    sync_interval_minutes: int | None = Field(
        default=None,
        ge=SYNC_INTERVAL_MIN_MINUTES,
        le=SYNC_INTERVAL_MAX_MINUTES,
    )
    initial_sync_window_days: int | None = None

    @field_validator("base_url")
    @classmethod
    def _check_base_url(cls, v: str | None) -> str | None:
        return None if v is None else _normalize_base_url(v)

    @field_validator("initial_sync_window_days")
    @classmethod
    def _check_window(cls, v: int | None) -> int | None:
        if v is None:
            return v
        if v not in INITIAL_SYNC_WINDOW_DAYS_OPTIONS:
            raise ValueError(
                f"initial_sync_window_days must be one of "
                f"{sorted(INITIAL_SYNC_WINDOW_DAYS_OPTIONS)}"
            )
        return v

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "NightscoutConnectionUpdate":
        if not any(getattr(self, f) is not None for f in type(self).model_fields):
            raise ValueError("at least one field must be provided")
        return self


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------


class NightscoutConnectionResponse(BaseModel):
    """Response shape for a single connection.

    Note: NEVER includes the credential. `has_credential` flags whether
    one is stored.
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    base_url: str
    auth_type: NightscoutAuthType
    api_version: NightscoutApiVersion
    is_active: bool
    has_credential: bool
    sync_interval_minutes: int
    initial_sync_window_days: int
    last_sync_status: NightscoutSyncStatus
    last_synced_at: datetime | None
    last_sync_error: str | None
    detected_uploaders_json: dict[str, Any] | None
    last_evaluated_at: datetime | None
    created_at: datetime
    updated_at: datetime


class NightscoutConnectionListResponse(BaseModel):
    """Response shape for GET /api/integrations/nightscout."""

    connections: list[NightscoutConnectionResponse]


class NightscoutConnectionTestResult(BaseModel):
    """Outcome of a connection-test attempt.

    Returned by POST /api/integrations/nightscout (creation) and by
    POST /api/integrations/nightscout/{id}/test (manual re-test).
    """

    ok: bool = Field(..., description="True if the test fully succeeded")
    server_version: str | None = Field(
        default=None,
        description="Nightscout server version reported by /api/v1/status",
    )
    api_version_detected: NightscoutApiVersion | None = Field(
        default=None,
        description="Which API version the server appears to speak",
    )
    auth_validated: bool = Field(
        default=False,
        description="True if the credential was accepted (i.e. authorized response)",
    )
    error: str | None = Field(
        default=None,
        description="Human-readable failure reason when ok=false",
    )


class NightscoutConnectionCreatedResponse(BaseModel):
    """Response shape for POST /api/integrations/nightscout.

    Bundles the persisted connection with the connection-test outcome
    so the caller can render success/failure feedback in one round trip.
    """

    connection: NightscoutConnectionResponse
    test: NightscoutConnectionTestResult


class NightscoutConnectionDeletedResponse(BaseModel):
    """Response shape for DELETE /api/integrations/nightscout/{id}."""

    id: uuid.UUID
    deactivated: bool = True
    message: str = (
        "Connection deactivated. Historical data and per-source attribution "
        "are preserved."
    )


# ---------------------------------------------------------------------------
# Read endpoints (consumed by the mobile cloud-source plugin + the
# onboarding wizard)
# ---------------------------------------------------------------------------


class NightscoutGlucoseReadingDTO(BaseModel):
    """A glucose reading row stripped to what the mobile plugin needs.

    Internal `user_id` and DB UUIDs are omitted; downstream consumers
    only need the timestamp + value + trend + source attribution.
    """

    model_config = {"from_attributes": True}

    ns_id: str | None
    reading_timestamp: datetime
    value: int
    trend: str
    trend_rate: float | None
    source: str


class NightscoutPumpEventDTO(BaseModel):
    """A pump event row stripped to what the mobile plugin needs.

    `metadata_json` carries clinically-meaningful extras filtered through
    a storage-side allowlist (see `_pump_events_mapper._METADATA_ALLOWLIST`).
    The DTO field is `repr=False` so that any future log/audit trail of
    this object doesn't echo free-text `notes` / `reason` content; the
    underlying value is still serialized normally to JSON callers (the
    data owner's own authenticated client).
    """

    model_config = {"from_attributes": True}

    ns_id: str | None
    event_timestamp: datetime
    event_type: str
    units: float | None
    duration_minutes: int | None
    is_automated: bool
    metadata_json: dict[str, Any] | None = Field(default=None, repr=False)
    meal_event_id: uuid.UUID | None
    source: str


class NightscoutDataResponse(BaseModel):
    """Merged read response for the cloud-source mobile plugin.

    The plugin pulls this with `?since=<ISO>` to backfill its Room DB
    incrementally. Both arrays are sorted ascending by timestamp.
    Pagination is via the `since` cursor on subsequent calls; the
    cursor is **inclusive** (`>=`) to avoid losing rows that share a
    timestamp with the boundary, so callers MUST dedupe by `ns_id`
    locally -- duplicates are bounded to ~1 row per page boundary per
    array.

    `limit` applies **per array**, not across both -- a single response
    may contain up to `limit` glucose readings AND up to `limit` pump
    events. `effective_limit_per_array` echoes the value used so the
    client doesn't have to track the cap.
    """

    connection_id: uuid.UUID
    fetched_at: datetime
    effective_limit_per_array: int
    glucose_readings: list[NightscoutGlucoseReadingDTO]
    pump_events: list[NightscoutPumpEventDTO]


class NightscoutProfileSegmentDTO(BaseModel):
    """A single (time, value) entry from a Nightscout profile schedule."""

    model_config = {"extra": "allow"}

    time: str  # "HH:MM"
    value: float


class NightscoutProfileSnapshotResponse(BaseModel):
    """Read response for the onboarding wizard's profile pre-fill source.

    Returned with empty arrays when no snapshot exists yet (the connection
    has been added but profile sync hasn't run). The wizard renders a
    "no profile detected" state in that case.
    """

    model_config = {"from_attributes": True}

    connection_id: uuid.UUID
    has_snapshot: bool
    fetched_at: datetime | None
    source_default_profile_name: str | None
    source_units: str | None
    source_timezone: str | None
    source_dia_hours: float | None
    basal_segments: list[dict[str, Any]] | None
    carb_ratio_segments: list[dict[str, Any]] | None
    sensitivity_segments: list[dict[str, Any]] | None
    target_low_segments: list[dict[str, Any]] | None
    target_high_segments: list[dict[str, Any]] | None
