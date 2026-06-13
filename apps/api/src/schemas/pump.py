"""Story 3.4 & 3.5: Pump data schemas.

Pydantic schemas for pump event API requests and responses,
including pump activity mode data.
"""

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.models.pump_data import MAX_INSULIN_DOSE_UNITS, PumpEventType


class PumpEventResponse(BaseModel):
    """Response schema for a single pump event."""

    model_config = ConfigDict(from_attributes=True)

    event_type: PumpEventType
    event_timestamp: datetime
    units: float | None = None
    duration_minutes: int | None = None
    is_automated: bool = False
    control_iq_reason: str | None = None
    pump_activity_mode: str | None = None
    basal_adjustment_pct: float | None = None
    iob_at_event: float | None = None
    cob_at_event: float | None = None
    bg_at_event: int | None = None
    received_at: datetime
    source: str = "tandem"


class PumpEventHistoryResponse(BaseModel):
    """Response schema for pump event history."""

    events: list[PumpEventResponse]
    count: int


class PumpStatusBasal(BaseModel):
    """Latest basal rate from pump."""

    rate: float
    is_automated: bool
    timestamp: datetime


class PumpStatusBattery(BaseModel):
    """Latest battery status from pump."""

    percentage: int
    is_charging: bool
    timestamp: datetime


class PumpStatusReservoir(BaseModel):
    """Latest reservoir level from pump."""

    units_remaining: float
    timestamp: datetime


class LoopStatusResponse(BaseModel):
    """Closed-loop runtime state for the hero card badge.

    Story 43.12 PR 6. Surfaces what the user's closed-loop algorithm
    (Loop / AAPS / Trio / oref0 / iAPS) is doing right now -- whether
    it's actively looping, paused, or has failed a cycle. Read-only
    projection over the latest `device_status_snapshots` row;
    suppressed when the snapshot is older than the staleness threshold
    in `loop_state_extractor.py`.
    """

    state: Literal["looping", "not_looping", "failed"] = Field(
        ...,
        description="'looping' | 'not_looping' | 'failed'",
    )
    source: Literal["loop", "aaps", "trio", "oref0", "iaps"] = Field(
        ...,
        description="'loop' | 'aaps' | 'trio' | 'oref0' | 'iaps'",
    )
    issued_at: datetime = Field(
        ...,
        description="When the source loop emitted the cycle this state reflects.",
    )
    failure_reason: str | None = Field(
        default=None,
        description="Populated only when state == 'failed'.",
    )


class OverrideStatusResponse(BaseModel):
    """Active workout / pre-meal / sleep override on the hero card.

    Loop-only in PR 6 -- AAPS / Trio publish overrides via Temp Target
    treatments, not devicestatus, and are deferred to a follow-up. The
    schema is general enough to accept those once their extractor lands.
    """

    name: str = Field(..., description="User-facing override name (e.g. 'Pre-meal').")
    started_at: datetime
    ends_at: datetime | None = Field(
        default=None,
        description="None for indefinite overrides.",
    )
    multiplier: float | None = Field(
        default=None,
        description="Loop's `insulinNeedsScaleFactor`.",
    )
    target_low_mgdl: float | None = None
    target_high_mgdl: float | None = None


class PumpStatusResponse(BaseModel):
    """Aggregated latest pump status (basal, battery, reservoir).

    PR 6 added closed-loop surfaces (`loop_status`, `override`,
    `cob_grams`) sourced from Nightscout devicestatus snapshots. They
    are nullable and read-only -- absence means "no NS devicestatus
    data" or "stale" or "this closed-loop isn't publishing the field".
    Existing pump_event-derived fields (basal/battery/reservoir) are
    unchanged.
    """

    basal: PumpStatusBasal | None = None
    battery: PumpStatusBattery | None = None
    reservoir: PumpStatusReservoir | None = None

    # PR 6 additions. Suppressed when no recent NS devicestatus exists.
    loop_status: LoopStatusResponse | None = None
    override: OverrideStatusResponse | None = None
    # COB is bounded at the schema layer (not just the extractor)
    # because the value flows verbatim from `device_status_snapshots.cob_grams`
    # without intermediate sanitation. 500 g is far above any
    # clinically plausible carb count; rejection here means a buggy
    # mapper bug surfaces as a 500 rather than silently sending
    # nonsense to the user.
    cob_grams: float | None = Field(default=None, ge=0, le=500)


class TandemSyncResponse(BaseModel):
    """Response schema for Tandem sync operation."""

    message: str
    events_fetched: int
    events_stored: int
    profiles_stored: int = 0
    last_event: PumpEventResponse | None = None


class TandemSyncStatusResponse(BaseModel):
    """Response schema for Tandem sync status.

    Combines the per-user sync *control* (``enabled`` / interval / cumulative
    pull count, from ``TandemSyncState``) with sync *freshness*
    (``last_sync_at`` / ``last_error``, from ``IntegrationCredential``).
    ``enabled`` / ``sync_interval_minutes`` reflect the effective state:
    when no state row exists, a connected user defaults to enabled at the
    default interval (backward-compatible with the prior global sync).
    """

    integration_status: str
    last_sync_at: datetime | None = None
    last_error: str | None = None
    events_available: int
    latest_event: PumpEventResponse | None = None

    # Per-user control surface (Story: per-user Tandem sync).
    enabled: bool = True
    sync_interval_minutes: int = 60
    events_pulled_total: int = 0
    # True when the stored Tandem region is a legacy bucket label (e.g. "EU")
    # that can no longer be resolved to a country -- the user must reconnect
    # with their country selected before sync can run.
    needs_country_reselect: bool = False


class TandemAvailabilityResponse(BaseModel):
    """Date range of pump data available in the user's t:connect cloud.

    Used to bound the manual-import date picker. ``latest`` is the last-upload
    timestamp (the reliable "newest data" marker); Tandem's maxDateWithEvents
    is ignored because it returns a bogus far-future date.
    """

    earliest: datetime | None = Field(
        default=None, description="Oldest date with pump data available to pull"
    )
    latest: datetime | None = Field(
        default=None,
        description="Most recent date with data (the last upload to t:connect)",
    )
    pump_count: int = Field(default=0, description="Pumps found on the account")


# Max span for a single manual import. Tandem's event log is dense
# (~30 days of Control-IQ data ≈ 9k stored events and ~24s to fetch+store);
# the web's reverse proxy times the request out around 30s, so we cap the
# window to one that reliably completes well under that. Larger/older
# history is imported in successive month chunks (full-history backfill via
# a background job is a planned follow-up).
MAX_IMPORT_RANGE_DAYS = 31


class TandemImportRequest(BaseModel):
    """Manual one-time custom-range import (Tandem cloud download).

    Bounds: ``end`` after ``start``; ``end`` not in the future; span capped
    at ``MAX_IMPORT_RANGE_DAYS`` so a single synchronous import completes
    before the HTTP proxy times out.
    """

    start_date: datetime = Field(..., description="Start of the range to import")
    end_date: datetime = Field(..., description="End of the range to import")

    @model_validator(mode="after")
    def _validate_range(self) -> "TandemImportRequest":
        # Normalize to UTC and persist back onto the model: a naive input is
        # assumed UTC, an offset-aware input is converted. Downstream code
        # formats these as %Y-%m-%d, so without normalization an offset-aware
        # value would format in its original tz and shift the requested day.
        start = (
            self.start_date.replace(tzinfo=UTC)
            if self.start_date.tzinfo is None
            else self.start_date.astimezone(UTC)
        )
        end = (
            self.end_date.replace(tzinfo=UTC)
            if self.end_date.tzinfo is None
            else self.end_date.astimezone(UTC)
        )
        self.start_date = start
        self.end_date = end
        if end <= start:
            raise ValueError("end_date must be after start_date")
        if end > datetime.now(UTC) + timedelta(minutes=5):
            raise ValueError("end_date cannot be in the future")
        if (end - start) > timedelta(days=MAX_IMPORT_RANGE_DAYS):
            raise ValueError(f"import range cannot exceed {MAX_IMPORT_RANGE_DAYS} days")
        return self


class TandemSyncSettingsRequest(BaseModel):
    """Request schema for updating per-user Tandem sync settings.

    ``sync_interval_minutes`` floor of 15 matches the model/DB bound:
    t:connect refreshes its cloud roughly hourly, so sub-15-min polling
    cannot surface fresher data.
    """

    enabled: bool = Field(..., description="Whether scheduled sync runs for this user")
    sync_interval_minutes: int = Field(
        default=60,
        ge=15,
        le=1440,
        description="Minutes between scheduled syncs (15-1440)",
    )


class ControlIQActivityResponse(BaseModel):
    """Response schema for Control-IQ activity summary (Story 3.5).

    This provides aggregated metrics about Control-IQ automated actions,
    helping understand what the pump is doing automatically so AI analysis
    can focus on what Control-IQ cannot adjust (carb ratios, correction factors).
    """

    # Event counts
    total_events: int
    automated_events: int
    manual_events: int

    # Correction boluses delivered by Control-IQ
    correction_count: int
    total_correction_units: float

    # Basal rate adjustments
    basal_increase_count: int
    basal_decrease_count: int
    avg_basal_adjustment_pct: float | None = None

    # Insulin suspends (for predicted low)
    suspend_count: int
    automated_suspend_count: int

    # Activity mode usage
    sleep_mode_events: int
    exercise_mode_events: int
    standard_mode_events: int

    # Time range analyzed
    start_time: datetime
    end_time: datetime
    hours_analyzed: int


class IoBProjectionResponse(BaseModel):
    """Response schema for IoB projection (Story 3.7).

    Provides projected insulin-on-board based on the last confirmed value
    and the insulin decay curve for rapid-acting insulins.
    """

    # Last confirmed IoB from pump
    confirmed_iob: float
    confirmed_at: datetime

    # Current projected IoB (accounting for decay since confirmation)
    projected_iob: float
    projected_at: datetime

    # Future projections
    projected_30min: float
    projected_60min: float

    # Data staleness
    minutes_since_confirmed: int
    is_stale: bool
    stale_warning: str | None = None
    is_estimated: bool = False


# ============================================================================
# Story 16.5: Mobile Pump Push Schemas
# ============================================================================


class PumpEventPushItem(BaseModel):
    """A single pump event pushed from a mobile client."""

    event_type: PumpEventType
    event_timestamp: datetime = Field(
        ..., description="When the event occurred (ISO-8601 with timezone)"
    )
    units: float | None = None
    duration_minutes: int | None = None
    is_automated: bool = False
    pump_activity_mode: str | None = None
    control_iq_mode: str | None = None  # backwards compat: old field name
    basal_adjustment_pct: float | None = None
    iob_at_event: float | None = None
    bg_at_event: int | None = None

    @model_validator(mode="before")
    @classmethod
    def migrate_control_iq_mode(cls, data: dict) -> dict:
        """Accept old control_iq_mode field and map to pump_activity_mode."""
        if isinstance(data, dict):
            old = data.get("control_iq_mode")
            new = data.get("pump_activity_mode")
            if old and not new:
                # Map legacy "standard"/"Standard"/"STANDARD" -> "none"
                old_lower = old.lower() if isinstance(old, str) else old
                data["pump_activity_mode"] = "none" if old_lower == "standard" else old
                data.pop("control_iq_mode", None)
        return data

    @field_validator("event_timestamp")
    @classmethod
    def timestamp_not_in_future(cls, v: datetime) -> datetime:
        """Reject timestamps more than 5 minutes in the future."""
        now = datetime.now(UTC)
        if v.tzinfo is None:
            v = v.replace(tzinfo=UTC)
        if v > now + timedelta(minutes=5):
            raise ValueError(
                "event_timestamp cannot be more than 5 minutes in the future"
            )
        return v


class PumpPushRequest(BaseModel):
    """Batch of pump events pushed from a mobile client.

    ``raw_events`` and ``pump_info`` are kept for backward compatibility
    with mobile clients built before the Tandem cloud-upload feature was
    removed (PR1c). Newer servers accept the fields but no longer persist
    them; older mobile builds that send them are not broken.

    The legacy fields are typed loosely on purpose: an older mobile build
    whose ``raw_events`` shape has drifted slightly (e.g. an extra field,
    a renamed key) should *not* take down its real ``events`` batch with
    a 422. Since the server discards these payloads, validating them adds
    risk without any safety benefit.
    """

    events: list[PumpEventPushItem] = Field(
        ..., min_length=1, max_length=100, description="Pump events to push (1-100)"
    )
    raw_events: Any = Field(
        default=None,
        description=(
            "Deprecated and ignored. Previously: raw BLE bytes used by the "
            "Tandem cloud-upload feature, which was removed (PR1c). Loose-typed "
            "(any JSON shape accepted) so an older client with a drifted shape "
            "does not lose its real ``events`` batch to a 422."
        ),
    )
    pump_info: Any = Field(
        default=None,
        description=(
            "Deprecated and ignored. Previously: pump hardware identification "
            "used by the Tandem cloud-upload feature, which was removed (PR1c). "
            "Loose-typed (any JSON shape accepted) so an older client with a "
            "drifted shape does not lose its real ``events`` batch to a 422."
        ),
    )
    source: str = Field(default="mobile", max_length=50)


class PumpPushResponse(BaseModel):
    """Response after processing a pump push request."""

    accepted: int = Field(..., description="Number of new events stored")
    duplicates: int = Field(..., description="Number of duplicate events skipped")
    raw_accepted: int = Field(
        default=0,
        description=(
            "Always 0. Kept for backward compatibility; raw events are no "
            "longer persisted (the consuming Tandem cloud-upload feature "
            "was removed)."
        ),
    )
    raw_duplicates: int = Field(
        default=0,
        description="Always 0. Kept for backward compatibility (see raw_accepted).",
    )


# --- Story 30.1: Aggregate stats schemas ---


class InsulinSummaryResponse(BaseModel):
    """Response schema for insulin delivery summary (Story 30.1).

    Unit fields (tdd, basal_units, bolus_units, correction_units) are
    daily averages over the requested period. Count fields (bolus_count,
    correction_count) are totals for the full period.
    """

    tdd: float = Field(..., ge=0, description="Average total daily dose (units/day)")
    basal_units: float = Field(
        ..., ge=0, description="Average daily basal insulin (units/day)"
    )
    bolus_units: float = Field(
        ..., ge=0, description="Average daily bolus + correction insulin (units/day)"
    )
    correction_units: float = Field(
        ..., ge=0, description="Average daily automated correction insulin (units/day)"
    )
    basal_pct: float = Field(
        ..., ge=0, le=100, description="Basal percentage of TDD (0 if no data)"
    )
    bolus_pct: float = Field(
        ..., ge=0, le=100, description="Bolus percentage of TDD (0 if no data)"
    )
    bolus_count: int = Field(..., ge=0, description="Total bolus deliveries in period")
    correction_count: int = Field(
        ..., ge=0, description="Total automated corrections in period"
    )
    period_days: int = Field(..., ge=1, description="Number of days analyzed")


class BolusReviewItem(BaseModel):
    """A single bolus event for the review table."""

    model_config = ConfigDict(from_attributes=True)

    event_timestamp: datetime
    units: float = Field(
        ...,
        ge=0,
        le=MAX_INSULIN_DOSE_UNITS,
        description="Bolus units (hard safety cap = platform max single dose, 60U)",
    )
    is_automated: bool = False
    control_iq_reason: str | None = None
    pump_activity_mode: str | None = None
    iob_at_event: float | None = None
    bg_at_event: int | None = Field(
        None, ge=20, le=500, description="Glucose at bolus event (mg/dL)"
    )


class BolusReviewResponse(BaseModel):
    """Response schema for bolus review list (Story 30.1)."""

    boluses: list[BolusReviewItem]
    total_count: int = Field(..., ge=0, description="Total bolus events in period")
    period_days: int = Field(..., ge=1, description="Number of days analyzed")
