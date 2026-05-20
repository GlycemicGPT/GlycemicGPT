"""Story 3.4 & 3.5: Pump data schemas.

Pydantic schemas for pump event API requests and responses,
including pump activity mode data.
"""

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.models.pump_data import PumpEventType


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
    """Response schema for Tandem sync status."""

    integration_status: str
    last_sync_at: datetime | None = None
    last_error: str | None = None
    events_available: int
    latest_event: PumpEventResponse | None = None


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
        ..., ge=0, le=25, description="Bolus units (hard safety cap 25U)"
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
