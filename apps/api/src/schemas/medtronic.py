"""Schemas for the Medtronic CareLink manual historical-import (feature B).

Stateless: the captured ``auth_tmp_token`` is sent in the ``X-CareLink-Token``
request HEADER (NOT the JSON body) so it can never land in a body-validation
422 echo or in request-body logging. The backend uses it per-request and never
stores it. No credential storage / scheduler / sync-state -- a manual import
completes within one ~50-min token life.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from urllib.parse import urlparse
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


# ---------------------------------------------------------------------------
# Medtronic CareLink CarePartner (Connect) -- autonomous sync (feature A)
#
# Unlike the manual import, this stores a credential: the captured Auth0
# refresh token. Like the manual token it is sent in a request HEADER (NOT the
# body) so a body-validation 422 can never echo it and it never lands in
# request-body logging. The backend encrypts it at rest and rotates it.
# ---------------------------------------------------------------------------

#: Connect regions (Auth0 tenant + cloud host). Mirrors connect_auth.REGIONS.
#: "EU" covers all non-US CarePartner countries (UK/GB, EU, AU, ZA, …) -- they
#: all share Medtronic's single OUS Auth0 tenant + cloud.
SUPPORTED_CONNECT_REGIONS = ("US", "EU")

#: Connect roles: "patient" (self-sync) or "carepartner" (follower).
CONNECT_ROLES = ("patient", "carepartner")

# Per-user sync cadence bounds (mirror the model's CHECK constraint).
CONNECT_SYNC_INTERVAL_MIN = 15
CONNECT_SYNC_INTERVAL_MAX = 1440
CONNECT_SYNC_INTERVAL_DEFAULT = 30


class MedtronicConnectStatusResponse(BaseModel):
    connected: bool
    status: str
    enabled: bool
    region: str | None = None
    role: str | None = None
    sync_interval_minutes: int = CONNECT_SYNC_INTERVAL_DEFAULT
    last_sync_at: datetime | None = None
    last_error: str | None = None
    readings_synced_total: int = 0


class MedtronicConnectSettingsRequest(BaseModel):
    enabled: bool
    sync_interval_minutes: int = Field(
        default=CONNECT_SYNC_INTERVAL_DEFAULT,
        ge=CONNECT_SYNC_INTERVAL_MIN,
        le=CONNECT_SYNC_INTERVAL_MAX,
    )


class MedtronicConnectSyncResponse(BaseModel):
    message: str
    glucose_fetched: int
    glucose_stored: int
    events_fetched: int
    events_stored: int


#: Max length of the opaque PKCE session blob / pasted redirect URL.
MAX_PKCE_BLOB_LEN = 8192


class MedtronicConnectPairResponse(BaseModel):
    """A short-lived pairing token for the local login-helper CLI."""

    pairing_token: str
    expires_at: datetime


class MedtronicConnectInstallRequest(BaseModel):
    """The web card's call to mint a short-handle install bundle.

    Inputs mirror the four query params the long-form one-liner used to
    inline. They're validated once here (instead of on every helper-
    template render) and stored in Redis under the returned handle.
    """

    api_url: str = Field(min_length=1, max_length=1024)
    username: str = Field(min_length=1, max_length=256)
    region: str

    @field_validator("api_url")
    @classmethod
    def _api_scheme(cls, v: str) -> str:
        s = (v or "").strip()
        if any(c in s for c in "\r\n\0"):
            raise ValueError("api_url contains control characters")
        # Require HTTPS so the pairing token / auth handshake is never sent in
        # cleartext, with an explicit carve-out for loopback (local dev /
        # self-host on the same machine, where there's no network to sniff).
        host = (urlparse(s).hostname or "").lower()
        is_loopback = host in {"localhost", "127.0.0.1", "::1"}
        if s.startswith("https://"):
            return s
        if s.startswith("http://") and is_loopback:
            return s
        raise ValueError(
            "api_url must use https:// (http:// is allowed only for "
            "loopback hosts: localhost, 127.0.0.1, ::1)"
        )

    @field_validator("username")
    @classmethod
    def _username_clean(cls, v: str) -> str:
        s = (v or "").strip()
        if not s:
            raise ValueError("username is required")
        if any(c in s for c in "\r\n\0"):
            raise ValueError("username contains control characters")
        return s

    @field_validator("region")
    @classmethod
    def _install_region(cls, v: str) -> str:
        key = (v or "").strip().upper()
        if key not in SUPPORTED_CONNECT_REGIONS:
            raise ValueError(
                f"Unsupported region {v!r}; supported: {list(SUPPORTED_CONNECT_REGIONS)}"
            )
        return key


class MedtronicConnectInstallResponse(BaseModel):
    """Short-handle install bundle response. The frontend assembles the actual
    install URL from this handle + its own knowledge of the instance origin --
    the backend doesn't try to guess the user's reverse-proxy hostname.

    ``pairing_token`` is the SAME underlying Fernet token stored inside the
    handle's bundle. It's exposed here so the in-page Python-CLI advanced
    fallback can still build a ``--pair <token>`` command without needing a
    second backend call. Both the short ``/install/<handle>.sh`` URL and the
    long-form CLI invocation consume the same jti at ``/exchange`` -- using
    one immediately darks the other.
    """

    handle: str
    pairing_token: str
    expires_at: datetime


class MedtronicConnectAuthUrlResponse(BaseModel):
    """The one-time CarePartner login URL + an opaque PKCE session blob.

    ``pkce_session`` is an encrypted blob (the backend holds the code_verifier
    inside it); the frontend round-trips it to ``/connect/exchange`` unchanged.
    It is opaque + Fernet-encrypted, so it carries no usable secret in the clear.
    """

    authorize_url: str
    pkce_session: str
    state: str


class MedtronicConnectExchangeRequest(BaseModel):
    """Complete the PKCE login: the opaque session + the pasted blocked-redirect
    URL (which carries the single-use authorization ``code`` + ``state``)."""

    pkce_session: str = Field(min_length=1, max_length=MAX_PKCE_BLOB_LEN)
    redirect_url: str = Field(min_length=1, max_length=MAX_PKCE_BLOB_LEN)
    username: str = Field(min_length=1, max_length=256)
    role: str = "patient"
    patient_id: str | None = Field(default=None, max_length=256)

    @field_validator("role")
    @classmethod
    def _exchange_role(cls, v: str) -> str:
        key = (v or "").strip().lower()
        if key not in CONNECT_ROLES:
            raise ValueError(
                f"Unsupported role {v!r}; supported: {list(CONNECT_ROLES)}"
            )
        return key

    @model_validator(mode="after")
    def _follower_needs_patient(self) -> MedtronicConnectExchangeRequest:
        if self.role == "carepartner" and not self.patient_id:
            raise ValueError("patient_id is required for the carepartner role")
        return self
