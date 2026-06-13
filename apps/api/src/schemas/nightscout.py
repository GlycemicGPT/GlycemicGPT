"""Story 43.1: Nightscout connection schemas.

Pydantic request/response shapes for the
`/api/integrations/nightscout` endpoints.

Secrets are NEVER returned in any response shape -- responses include
only `has_credential` (boolean) so the UI can indicate "credential is
set" without exposing it.
"""

import uuid
from datetime import datetime
from typing import Any, Literal
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


class NightscoutManualSyncResponse(BaseModel):
    """Response shape for POST /api/integrations/nightscout/{id}/sync.

    Story 43.4 AC10 -- the user-triggered "sync now" path. The
    background scheduler returns the same shape internally; only this
    endpoint exposes it to clients.
    """

    connection_id: uuid.UUID
    status: NightscoutSyncStatus
    entries_inserted: int
    entries_skipped: int
    entries_failed: int
    treatments_inserted_pump: int
    treatments_inserted_glucose: int
    treatments_failed: int
    devicestatuses_inserted: int
    devicestatuses_failed: int
    profile_synced: bool
    duration_ms: int
    error: str | None = Field(
        default=None,
        description="Human-readable failure reason when status != ok",
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
    basal_segments: list[NightscoutProfileSegmentDTO] | None
    carb_ratio_segments: list[NightscoutProfileSegmentDTO] | None
    sensitivity_segments: list[NightscoutProfileSegmentDTO] | None
    target_low_segments: list[NightscoutProfileSegmentDTO] | None
    target_high_segments: list[NightscoutProfileSegmentDTO] | None


# ---------------------------------------------------------------------------
# Story 43.7a -- evaluate / discovery report
# ---------------------------------------------------------------------------


class NightscoutDiscoveryProfileSummary(BaseModel):
    """Profile facts surfaced on the discovery report.

    Schedules carry the profile snapshot's `[{time, value, ...}, ...]`
    shape verbatim so downstream code (43.7b derive, the wizard's
    review table) sees the same structure the snapshot stores. Single-
    band target_low / target_high values are min / max across the
    target schedule (a single-segment 70-180 target reports identical
    bounds; a time-varying target reports the safest summary the
    review screen can render in one row).

    `target_low` / `target_high` are kept as `float` so mmol/L profiles
    (where targets are sub-ten decimals like 4.4 / 7.8) preserve their
    clinical precision. Wizard / 43.7b derive code is responsible for
    unit normalization at render / write time.
    """

    target_low: float | None = None
    target_high: float | None = None
    dia_hours: float | None = None
    # NS profile units are one of "mg/dl" / "mmol" per upstream
    # `lib/units.js`. Constrained because mg/dL <-> mmol/L is a
    # ~18x scale factor -- a misread here corrupts every downstream
    # target / ISF / DIA calculation. Strict Literal so a future
    # NS version that introduces a third unit string fails loud
    # at the schema layer rather than silently writing garbage.
    units: Literal["mg/dl", "mmol"] | None = None
    timezone: str | None = None
    carb_ratio_schedule: list[NightscoutProfileSegmentDTO] | None = None
    isf_schedule: list[NightscoutProfileSegmentDTO] | None = None
    basal_schedule: list[NightscoutProfileSegmentDTO] | None = None
    target_low_schedule: list[NightscoutProfileSegmentDTO] | None = None
    target_high_schedule: list[NightscoutProfileSegmentDTO] | None = None
    is_malformed: bool = False  # AC11: profile fetch returned but unparseable


class OnboardingScheduleSegment(BaseModel):
    """Story 43.7b -- a single time-segmented entry in our canonical
    schedule shape.

    Difference from `NightscoutProfileSegmentDTO`: this carries
    `start_minutes` (int, 0-1439) for direct insertion into our
    `pump_profiles.segments` JSONB column and downstream math. The
    NS source uses `time` as "HH:MM" + optional `timeAsSeconds`;
    the derive module converts.
    """

    start_minutes: int = Field(ge=0, lt=24 * 60)
    # Medical-safety guard: schedule values (basal U/hr, carb ratio
    # g/U, ISF mg/dL/U) must always be strictly positive. A `0.0`
    # basal would mean "infinitely no insulin" -- not a real profile
    # segment shape (suspends are encoded separately, not as a 0
    # basal segment). Negatives are physiologically impossible.
    value: float = Field(gt=0)


class OnboardingNumericFieldDerivation(BaseModel):
    """Per-field proposal for a single-value setting (target_low,
    target_high, dia_hours, ...).

    The wizard renders one row per field in a diff table:
    'Setting | Currently | From Nightscout | Use this? [checkbox]'.
    `current_value` powers the "Currently" column, `proposed_value`
    the "From Nightscout" column, `default_checked` the checkbox's
    initial state per AC4 (checked iff the user's current value is
    the platform default -- i.e. they haven't customized it).
    `proposed_value=None` when NS has nothing to propose; the
    wizard hides the row in that case.
    """

    field: str  # stable identifier: "target_low" | "target_high" | "dia_hours" | ...
    # Medical-safety guard: glucose targets and DIA must be strictly
    # positive. Optional (None when no current row / no NS proposal).
    # Upper bounds are NOT enforced here -- the wizard's diff table
    # surfaces unusual values for the user to confirm before write.
    current_value: float | None = Field(default=None, gt=0)
    proposed_value: float | None = Field(default=None, gt=0)
    default_checked: bool = False


class OnboardingScheduleFieldDerivation(BaseModel):
    """Per-field proposal for a time-segmented schedule (basal,
    carb_ratio, isf).

    Same wizard contract as `OnboardingNumericFieldDerivation` but
    the "current" / "proposed" values are lists of segments. The
    wizard renders a "current vs proposed" preview; per the 43.7c
    decision the user can opt the WHOLE schedule in/out (no
    per-segment editing in v1). `proposed_segments=None` when the
    NS profile doesn't carry this schedule.
    """

    field: str  # "basal_schedule" | "carb_ratio_schedule" | "isf_schedule"
    current_segments: list[OnboardingScheduleSegment] | None = None
    proposed_segments: list[OnboardingScheduleSegment] | None = None
    default_checked: bool = False


class OnboardingDerivation(BaseModel):
    """Story 43.7b -- the wizard step 3 review-table source.

    Returned by the `derive_onboarding_proposals()` pure function
    given a Nightscout profile snapshot + the user's current
    canonical settings. The wizard step 3 renders one row per
    derivation field (numeric + schedule), using `default_checked`
    for the initial checkbox state and `proposed_value` /
    `proposed_segments` for the right-hand "From Nightscout"
    column.

    Shape stable: the derivation includes ALL derivable fields even
    when NS has nothing to propose (with `proposed_value=None` /
    `proposed_segments=None`), so the wizard's row layout is
    deterministic across users + connections.
    """

    has_profile: bool
    # True when the Nightscout profile is in mmol/L but our canonical
    # settings are mg/dL (or vice versa). The wizard surfaces this
    # so the user understands values were unit-converted before the
    # diff table renders. Always False when units match.
    units_converted: bool = False
    # True when the snapshot's `source_units` did NOT match any
    # known mg/dL or mmol/L variant. The wizard MUST surface this
    # before applying any glucose-domain proposal -- silently
    # defaulting an unknown unit string to mg/dL could write wrong
    # targets / ISFs to canonical settings.
    units_unknown: bool = False
    target_low: OnboardingNumericFieldDerivation
    target_high: OnboardingNumericFieldDerivation
    dia_hours: OnboardingNumericFieldDerivation
    carb_ratio_schedule: OnboardingScheduleFieldDerivation
    isf_schedule: OnboardingScheduleFieldDerivation
    basal_schedule: OnboardingScheduleFieldDerivation


class NightscoutDiscoveryReport(BaseModel):
    """Story 43.7a AC1: the evaluate endpoint's response shape.

    Persisted on `nightscout_connections.detected_uploaders_json` and
    cached for 5 minutes per AC9 -- the field name predates this report
    (Story 43.1 forward-engineered it), but it now stores the full
    report, not just the uploader list.
    """

    status_ok: bool
    server_version: str | None = None
    earliest_entry_at: datetime | None = None
    # `entry_count_estimate` is an EXTRAPOLATION from the recent-7d
    # rate * the span between the oldest sampled entry and now. For
    # instances with steady CGM upload, this lands within ~10% of the
    # true total. For sparse / intermittent uploaders, it's a rough
    # order-of-magnitude. The wizard renders this as "~N entries" so
    # the rough-estimate nature is OK. Constrained `>= 0` to reject
    # anyone serializing in a corrupt state.
    entry_count_estimate: int = Field(default=0, ge=0)
    recent_entry_count_7d: int = Field(default=0, ge=0)
    uploaders_detected: list[str] = []
    has_treatments: bool = False
    treatment_count_estimate: int = Field(default=0, ge=0)
    has_devicestatus: bool = False
    has_profile: bool = False
    profile_summary: NightscoutDiscoveryProfileSummary | None = None
    # First detected closed-loop platform from the uploader sample,
    # if any -- one of "loop" | "aaps" | "trio" | "oref0" | None.
    # Treated as a HINT, not source-of-truth: a multi-uploader
    # sample (e.g. legacy Loop records still in retention plus
    # current Trio uploads) reports the first match across the
    # `LOOP_UPLOADERS` preference order. The wizard surfaces this
    # for UI flavor / freshness expectations only.
    active_pump_loop: str | None = None
    # Names of upstream resources that a per-resource probe
    # FAILED to read, even though `test_connection` passed. Empty
    # on a clean evaluate. Populated when an instance's token has
    # entries-only scope (or any other partial-permission pattern):
    # the wizard can surface "we couldn't read your treatments --
    # your token might be entries-only" rather than silently
    # claiming the data isn't there. Names match the orchestrator's
    # internal labels: "treatments" | "devicestatus" | "profile" |
    # "recent_entries" | "oldest_entries".
    partial_resources: list[str] = []
    evaluated_at: datetime
    error: str | None = None  # populated when status_ok is False


# ---------------------------------------------------------------------------
# Apply-onboarding endpoint -- writes confirmed proposals to canonical
# settings tables and triggers the connection's first sync.
# ---------------------------------------------------------------------------


class NightscoutApplyOnboardingRequest(BaseModel):
    """Request body for POST /{id}/apply-onboarding.

    Per-field opt-in flags drive what gets written. Override values
    let the user replace the Nightscout-derived proposal with their
    own typed value at confirmation time -- limited to top-level
    numerics in this iteration; per-segment schedule overrides are
    deferred. `initial_sync_window_days` (when present) writes to
    the connection row and drives the first sync's lookback window.

    `confirm_units_unknown` is a hard gate: when the discovery
    derivation flagged `units_unknown=True` AND any glucose-domain
    import is requested (target_low / target_high / isf_schedule),
    the request MUST include `confirm_units_unknown=True` to
    proceed. Default false -- silence is rejection.
    """

    model_config = {"extra": "forbid"}

    # Per-field opt-in flags. Default false: omitting a flag means
    # "do not import this field." Wizard step 3's "Use this?"
    # checkboxes drive these.
    import_target_low: bool = False
    import_target_high: bool = False
    import_dia_hours: bool = False
    import_basal_schedule: bool = False
    import_carb_ratio_schedule: bool = False
    import_isf_schedule: bool = False

    # Top-level overrides. Honored only when the matching import
    # flag is true; ignored otherwise (validated below). Range
    # validation falls through to the existing canonical writers
    # (TargetGlucoseRangeUpdate / InsulinConfigUpdate validators).
    override_target_low: float | None = Field(default=None, gt=0)
    override_target_high: float | None = Field(default=None, gt=0)
    override_dia_hours: float | None = Field(default=None, gt=0)

    # First-sync window. None = leave the connection's existing
    # value alone. Allowed: matches `INITIAL_SYNC_WINDOW_DAYS_OPTIONS`
    # (1, 7, 30, 90, 0) where 0 means "all available".
    initial_sync_window_days: int | None = None

    # Hard gate for unknown-units profiles. Required true when
    # the derivation reported `units_unknown=True` AND the request
    # includes any glucose-domain import. Server-side enforced in
    # the endpoint (the request schema can't see the derivation).
    confirm_units_unknown: bool = False

    @field_validator("initial_sync_window_days")
    @classmethod
    def _valid_sync_window(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if value not in INITIAL_SYNC_WINDOW_DAYS_OPTIONS:
            raise ValueError(
                f"initial_sync_window_days must be one of "
                f"{list(INITIAL_SYNC_WINDOW_DAYS_OPTIONS)} (got {value})"
            )
        return value

    @model_validator(mode="after")
    def _overrides_only_with_import_flag(self) -> "NightscoutApplyOnboardingRequest":
        """Reject overrides for fields whose import flag is false.

        A user passing `override_target_low=80` without
        `import_target_low=True` is signaling intent that the schema
        can't honor (we'd silently ignore the override). 422 makes
        the contract explicit.
        """
        violations: list[str] = []
        if self.override_target_low is not None and not self.import_target_low:
            violations.append("override_target_low requires import_target_low=true")
        if self.override_target_high is not None and not self.import_target_high:
            violations.append("override_target_high requires import_target_high=true")
        if self.override_dia_hours is not None and not self.import_dia_hours:
            violations.append("override_dia_hours requires import_dia_hours=true")
        if violations:
            raise ValueError("; ".join(violations))
        return self


FirstSyncStatus = Literal["ok", "timeout", "error", "skipped"]


class NightscoutApplyOnboardingResponse(BaseModel):
    """Response body for POST /{id}/apply-onboarding.

    Mirrors the wizard step 4's progress UI requirements: the
    `applied` map tells the wizard which rows in its diff table
    actually got written (so it can render checkmarks), and
    `first_sync_status` distinguishes "settings saved, sync ran
    fine" from "settings saved, sync timed out" -- both are 200
    on the wire (the settings success deserves the success code;
    the wizard reads the field to decide whether to poll).
    """

    connection_id: uuid.UUID
    # Per-field "did we actually persist this?" flags. True iff
    # the import flag was set AND the derivation had a value to
    # apply. False otherwise. Wizard renders ticks against this.
    applied: dict[str, bool]
    target_glucose_range: dict[str, Any] | None = None
    insulin_config: dict[str, Any] | None = None
    pump_profile_id: uuid.UUID | None = None
    first_sync_status: FirstSyncStatus
    first_sync_error: str | None = None
    sync_result: NightscoutManualSyncResponse | None = None
