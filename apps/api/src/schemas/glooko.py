"""Schemas for the Glooko (Omnipod Cloud Sync) connect/sync endpoints.

Like Medtronic Connect -- and unlike Tandem, which reuses ``integration_credentials``
-- Glooko stores everything on its own ``GlookoSyncState`` row: the Fernet-encrypted
account email + password (replayed via the web Devise login each sync, NOT rotated)
plus the control + freshness fields. These schemas only carry credentials INBOUND
on connect; no response ever echoes them back.

Connect also records an explicit acknowledgment (``accept_risk``): Glooko has no
official app integration, so we sign in with the user's own credentials. The user
confirms they understand this isn't officially supported before we store their
credentials and sync on their behalf. (The field name is historical; it gates an
informed acknowledgment, not a warranty of risk.)
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, ValidationInfo, field_validator

from src.models.glooko_sync_state import (
    SYNC_INTERVAL_DEFAULT_MINUTES,
    SYNC_INTERVAL_MAX_MINUTES,
    SYNC_INTERVAL_MIN_MINUTES,
)

#: Region keys the connect flow accepts. Must mirror
#: ``services.integrations.glooko.auth.REGIONS`` (the runtime SSRF allowlist);
#: this tuple is the early request-validation gate. US is the default; EU selects
#: the region-prefixed ``eu.api`` / ``eu.my`` hosts.
SUPPORTED_GLOOKO_REGIONS = ("US", "EU")

#: Upper bound on a submitted credential length -- reject absurd payloads early
#: (a real Glooko email/password is well under this).
MAX_CREDENTIAL_LEN = 512


def _validate_region(v: str) -> str:
    key = (v or "").strip().upper()
    if key not in SUPPORTED_GLOOKO_REGIONS:
        raise ValueError(
            f"Unsupported region {v!r}; supported: {sorted(SUPPORTED_GLOOKO_REGIONS)}"
        )
    return key


class GlookoConnectRequest(BaseModel):
    """Connect a Glooko account: store encrypted credentials + record consent."""

    email: str = Field(min_length=1, max_length=MAX_CREDENTIAL_LEN)
    password: str = Field(min_length=1, max_length=MAX_CREDENTIAL_LEN)
    region: str = "US"
    # Explicit acknowledgment that this is an unofficial connection. Required true
    # -- the endpoint refuses to store credentials without it (422 otherwise).
    accept_risk: bool = Field(
        description=(
            "Must be true: the user acknowledges that Glooko has no official app "
            "integration and that GlycemicGPT signs in with their credentials."
        ),
    )

    _region = field_validator("region")(_validate_region)

    @field_validator("email", "password")
    @classmethod
    def _no_control_chars(cls, v: str, info: ValidationInfo) -> str:
        if not v or not v.strip():
            raise ValueError("must not be blank")
        if any(c in v for c in "\r\n\0"):
            raise ValueError("must not contain control characters")
        # Email is safe to normalize, but a password must be stored byte-for-byte
        # -- leading/trailing spaces can be significant, and stripping them would
        # make some valid Glooko accounts impossible to connect.
        return v.strip() if info.field_name == "email" else v

    @field_validator("accept_risk")
    @classmethod
    def _must_accept(cls, v: bool) -> bool:
        if v is not True:
            raise ValueError(
                "Please acknowledge that this is an unofficial Glooko connection "
                "before connecting."
            )
        return v


class GlookoStatusResponse(BaseModel):
    """Connection + freshness status. NEVER includes credentials."""

    connected: bool
    status: str
    enabled: bool
    cgm_sync_enabled: bool = True
    region: str | None = None
    sync_interval_minutes: int = SYNC_INTERVAL_DEFAULT_MINUTES
    last_sync_at: datetime | None = None
    last_error: str | None = None
    readings_synced_total: int = 0
    consent_acknowledged_at: datetime | None = None


class GlookoSyncSettingsRequest(BaseModel):
    enabled: bool
    cgm_sync_enabled: bool = True
    sync_interval_minutes: int = Field(
        default=SYNC_INTERVAL_DEFAULT_MINUTES,
        ge=SYNC_INTERVAL_MIN_MINUTES,
        le=SYNC_INTERVAL_MAX_MINUTES,
    )


class GlookoSyncResponse(BaseModel):
    message: str
    glucose_fetched: int
    glucose_stored: int
    events_fetched: int
    events_stored: int


class GlookoAvailabilityResponse(BaseModel):
    """Read-only probe of what data is reachable in the user's Glooko cloud.

    Bounds expectations for the web Cloud Sync card. A live login
    that does NOT mutate the sync-state row (Tandem #669 ``persist_status=False``).
    """

    connected: bool
    cgm_available: bool
    earliest: datetime | None = None
    latest: datetime | None = None
