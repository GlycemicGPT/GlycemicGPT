"""Pydantic input models for raw Nightscout v1 API shapes.

Story 43.3 (translator) PR1. The translator's input layer: typed
parsers + field-presence routing helpers that decouple the messy
on-the-wire reality from the internal-ORM mapping (PR2).

**Design rules driven by the fixture survey** (`_bmad-output/planning-artifacts/nightscout-translator-fixture-survey.md`):

1. **Be permissive on input.** Real-world Nightscout traffic is
   uploader-specific; every uploader uses slightly different fields,
   field casings, and unit conventions. Models accept extra fields
   (`extra="allow"`) and never crash on unknown shapes.

2. **Route by field presence, not eventType.** eventType is a hint;
   the actual semantic event is determined by which fields are
   populated. Empty/missing/`<none>` eventType is valid (xDrip+
   behavior). See `NightscoutTreatment.semantic_kind`.

3. **Encode unit conventions explicitly.** `duration` is minutes for
   treatments collection; seconds for `devicestatus.override.duration`
   (Loop-specific asymmetry, verified 2026-05-06 against
   `LoopKit/NightscoutKit OverrideTreatment.swift:62-70` vs
   `OverrideStatus.swift:44-46`). `utcOffset` is minutes (not ms).
   Glucose conversion factor is 18.02.

4. **Detect uploader from `device` + `enteredBy` (case-insensitive,
   superset of `nightscout-reporter`'s heuristic).** Reporter does NOT
   detect Loop or Trio -- our heuristic does. `device` (machine-set:
   `loop://iPhone`) and `enteredBy` (human/app-set: `"Loop"`) carry
   different signals; preserve both.

5. **Do not lose data.** Unknown eventTypes route to a generic event
   preserving the raw eventType + all fields. Translator-to-ORM mapping
   layer (PR2) decides what to do with them. AC6 of Story 43.3:
   "unrecognized event types are logged and skipped (not crashed)."
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Glucose conversion factor (mg/dL ↔ mmol/L). Derived from glucose
# molecular weight 180.16 / 10. Matches AAPS and nightscout-reporter
# conventions per `mapping/nightscout-reporter/unit-conversion.md`.
MGDL_PER_MMOL = 18.02

# Glucose gap rule. Per `mapping/nightscout-reporter/README.md §Glucose
# Gaps`: SGV outside [20, 1000] mg/dL is treated as a sensor gap, not a
# valid reading. Lock against `sgv: 0` corruption.
SGV_MIN_VALID = 20
SGV_MAX_VALID = 1000

# Loop's ObjectIdCache is memory-only and doesn't persist across app
# restarts (`mapping/loop/sync-identity-fields.md GAP-SYNC-005`).
# Defensive secondary dedup key uses a 2-second window.
DEDUP_TIME_WINDOW_SECONDS = 2


# Direction enum -- canonical wire form uses spaces. Defensive parser
# accepts underscore form too (some uploaders emit `NOT_COMPUTABLE`).
# Trio extends with `TripleUp`/`TripleDown` outside the canonical enum.
_CANONICAL_DIRECTIONS = {
    "NONE",
    "DoubleUp",
    "SingleUp",
    "FortyFiveUp",
    "Flat",
    "FortyFiveDown",
    "SingleDown",
    "DoubleDown",
    "NOT COMPUTABLE",
    "RATE OUT OF RANGE",
}
_DIRECTION_NORMALIZATIONS = {
    "NOT_COMPUTABLE": "NOT COMPUTABLE",
    "RATE_OUT_OF_RANGE": "RATE OUT OF RANGE",
}


def _normalize_direction(value: str | None) -> str | None:
    """Coerce direction to canonical wire form, accept underscored variants."""
    if value is None:
        return None
    return _DIRECTION_NORMALIZATIONS.get(value, value)


def _coerce_to_float(value: Any) -> float | None:
    """Care Portal sends numbers as strings; coerce permissively."""
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return result


def _parse_signed_string(value: Any) -> int | None:
    """Trio's `tick` is a signed string (`"-1"`, `"+5"`). Parse permissively.

    Accepts already-numeric values too -- some uploaders emit ints.
    """
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.lstrip("+"))
        except ValueError:
            return None
    return None


def _parse_iso_or_epoch(value: Any) -> datetime | None:
    """Accept ISO 8601 with/without ms, with/without 'Z', or epoch (s/ms).

    `mapping/xdrip4ios/treatment-classification.md §Date Parsing`
    documents the .-vs-no-. discrimination across uploaders. Be liberal.
    """
    if value is None or value == "":
        return None
    if isinstance(value, int | float):
        # Heuristic: epoch-ms values are > 10^11 (year 1973+ in ms);
        # smaller numbers are epoch-seconds. Anything older than the
        # CGM era is likely a parser error and we'd rather raise via
        # validation than silently coerce a meaningless date.
        if value > 1e11:
            return datetime.fromtimestamp(value / 1000.0, tz=UTC)
        return datetime.fromtimestamp(float(value), tz=UTC)
    if isinstance(value, str):
        # Strip trailing Z for fromisoformat compatibility (Python
        # 3.11+ handles it, but be defensive for fractional-Z forms).
        s = value.replace("Z", "+00:00") if value.endswith("Z") else value
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return None
        return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
    return None


# ---------------------------------------------------------------------------
# Source attribution
# ---------------------------------------------------------------------------


def detect_uploader(entered_by: str | None, device: str | None) -> str:
    """Identify the upstream uploader from `enteredBy` + `device` strings.

    Lowercase-then-match, superset of `nightscout-reporter`'s heuristic
    (Reporter explicitly does NOT detect Loop or Trio -- gap noted in
    `mapping/nightscout-reporter/uploader-detection.md`). We add Loop
    and Trio.

    Returns one of: "loop", "aaps", "trio", "oref0", "xdrip+",
    "xdrip4ios", "spike", "tidepool", "care_portal", "unknown".
    """
    eb = (entered_by or "").lower().strip()
    dev = (device or "").lower().strip()

    # xDrip4iOS first -- substring "xdrip4ios" is unique
    if "xdrip4ios" in eb or "xdrip4ios" in dev:
        return "xdrip4ios"
    # xDrip+ Android (the older xDrip family)
    if eb.startswith("xdrip") or dev.startswith("xdrip-"):
        return "xdrip+"
    # AAPS (covers `openaps://AndroidAPS`, `androidaps`, etc.)
    if "androidaps" in eb or eb == "openaps://androidaps":
        return "aaps"
    # Trio
    if eb == "trio" or dev == "trio":
        return "trio"
    # Loop iOS
    if eb == "loop" or eb.startswith("loop ") or dev.startswith("loop://"):
        return "loop"
    # Spike / Tidepool (exact)
    if eb in ("spike", "tidepool"):
        return eb
    # oref0 falls back when device starts with `openaps://<host>` AND
    # we haven't matched AAPS above (which uses the degenerate
    # `openaps://AndroidAPS` form).
    if dev.startswith("openaps://"):
        return "oref0"
    if eb == "openaps":  # Profile Switch from oref0 uses bare "OpenAPS"
        return "oref0"
    return "unknown"


def parse_openaps_uri(device: str | None) -> tuple[str | None, str | None]:
    """Split `openaps://<host>/<device>` into `(rig_host, device_ref)`.

    `mapping/openaps/nightscout-formats.md §Device Identifier`. AAPS
    uses degenerate one-segment form `openaps://AndroidAPS` -- in that
    case we return `(None, "AndroidAPS")` so callers can distinguish.
    """
    if not device or not device.startswith("openaps://"):
        return (None, None)
    rest = device[len("openaps://") :]
    if "/" not in rest:
        return (None, rest)
    host, _, ref = rest.partition("/")
    return (host or None, ref or None)


# ---------------------------------------------------------------------------
# Entries
# ---------------------------------------------------------------------------


class NightscoutEntry(BaseModel):
    """A single record from `/api/v1/entries.json`.

    Three `type` values exist in the wild: `sgv` (CGM reading), `mbg`
    (manual fingerstick BG), `cal` (Dexcom calibration). We accept all
    three; `cal` records are typically not surfaced as glucose readings
    but are useful for noise/calibration analysis.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str | None = Field(default=None, alias="_id")
    type: str  # "sgv" | "mbg" | "cal"
    sgv: float | None = None
    mbg: float | None = None
    direction: str | None = None
    trend: int | None = None
    noise: int | str | None = None  # xDrip+ Android stores as string
    delta: float | None = None
    filtered: float | None = None
    unfiltered: float | None = None
    rssi: int | None = None
    slope: float | None = None  # cal-type only
    intercept: float | None = None  # cal-type only
    scale: float | None = None  # cal-type only

    # Timestamp fields -- fallback chain documented per
    # synthesis §2.1. For entries the canonical is `date` (epoch ms).
    date: int | float | None = None
    date_string: str | None = Field(default=None, alias="dateString")
    sys_time: str | None = Field(default=None, alias="sysTime")
    mills: int | float | None = None  # never persisted, runtime-only

    device: str | None = None
    utc_offset: int | None = Field(default=None, alias="utcOffset")  # minutes

    # v3 envelope fields (optional; pre-v14 NS doesn't emit these)
    identifier: str | None = None
    app: str | None = None
    subject: str | None = None

    @field_validator("noise", mode="before")
    @classmethod
    def _coerce_noise(cls, v: Any) -> int | None:
        """xDrip+ Android stores noise as string; canonical NS as int."""
        if v is None or v == "":
            return None
        try:
            return int(v)
        except (ValueError, TypeError):
            return None

    @field_validator("direction", mode="before")
    @classmethod
    def _normalize_direction_field(cls, v: Any) -> str | None:
        return _normalize_direction(v) if isinstance(v, str) else v

    @property
    def is_fingerstick(self) -> bool:
        """Per synthesis §1.8: dual-path fingerstick. Entries route is `mbg`."""
        return self.type == "mbg"

    @property
    def is_glucose_gap(self) -> bool:
        """Per synthesis §2.6: SGV outside [20, 1000] is a gap, not a reading.

        Returns True for sgv-type entries with out-of-range values.
        Other types (mbg, cal) are not gap-checked here.
        """
        if self.type != "sgv" or self.sgv is None:
            return False
        return self.sgv < SGV_MIN_VALID or self.sgv > SGV_MAX_VALID

    @property
    def canonical_timestamp(self) -> datetime | None:
        """Resolve the entry's timestamp from the fallback chain.

        Order: `date` (epoch ms) -> `dateString` (ISO Z) -> `sysTime`
        -> `mills`. The first non-null wins. Server normalizes
        `dateString = sysTime` on insert.
        """
        for candidate in (self.date, self.date_string, self.sys_time, self.mills):
            parsed = _parse_iso_or_epoch(candidate)
            if parsed is not None:
                return parsed
        return None


# ---------------------------------------------------------------------------
# Treatments
# ---------------------------------------------------------------------------


# Internal "semantic kind" classification. eventType is a hint; this
# enum captures what the translator actually does with the record.
SemanticKind = Literal[
    "bolus",
    "carb_entry",
    "meal_bolus_pair",  # carbs + insulin -- split into bolus + carb_entry rows
    "temp_basal",
    "temp_basal_suspend",
    "temp_basal_cancel",  # sentinel: don't ingest as event
    "combo_bolus",
    "override",
    "temp_target",
    "profile_switch",
    "effective_profile_switch",  # AAPS Note-with-originalProfileName
    "fingerstick_bg_check",  # treatments-route fingerstick (xDrip4iOS)
    "device_event",  # site/sensor/insulin/battery change
    "aps_offline",  # OpenAPS Offline / loop-down marker
    "exercise_log",  # genuine exercise log (NOT override-derived)
    "note",
    "announcement",
    "unknown",  # preserve raw eventType + fields, do not crash
]


# Treatment eventTypes that are unambiguously "device events" (no
# parsing required, share treatment schema, share field set).
_DEVICE_EVENT_EVENTTYPES = frozenset(
    {
        "site change",
        "sensor change",
        "sensor start",
        "sensor stop",
        "insulin change",
        "pump battery change",
    }
)


# Trio Override indefinite-duration sentinel. Per Trio source
# (`OverrideStorage.swift`), indefinite overrides upload as 30-day
# duration. Treat duration >= this as "indefinite" when the source is
# Trio AND the eventType is Exercise.
TRIO_INDEFINITE_OVERRIDE_DURATION_MIN = 43200


class NightscoutTreatment(BaseModel):
    """A single record from `/api/v1/treatments.json`.

    Open-schema by design -- every uploader uses slightly different
    field combinations. Common fields are typed; uploader-specific
    fields are preserved via `extra="allow"`. Use `semantic_kind` to
    decide how to route this record into the internal ORM.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str | None = Field(default=None, alias="_id")
    event_type: str | None = Field(default=None, alias="eventType")
    created_at: str | None = None
    entered_by: str | None = Field(default=None, alias="enteredBy")
    notes: str | None = None
    is_valid: bool | None = Field(default=None, alias="isValid")  # AAPS soft-delete
    utc_offset: int | None = Field(default=None, alias="utcOffset")  # minutes

    # Bolus / carb fields
    insulin: float | None = None
    carbs: float | None = None
    protein: float | None = None  # AAPS extended-meal nutrition
    fat: float | None = None  # AAPS extended-meal nutrition
    glucose: float | None = None
    glucose_type: str | None = Field(default=None, alias="glucoseType")
    units: str | None = None  # rare; per-record unit override

    # Bolus-specific
    type: str | None = (
        None  # "NORMAL" | "SMB" | "PRIMING" (AAPS); "normal"/"square" (Loop)
    )
    is_smb_flag: bool | None = Field(
        default=None, alias="isSMB"
    )  # AAPS V1 only (avoid clash with is_smb property)
    automatic: bool | None = None  # Loop SMB signal
    microbolus: float | None = None  # Some uploaders' SMB amount
    programmed: float | None = None  # Loop
    unabsorbed: float | None = None  # Loop (always 0 -- not an SMB signal)
    bolus_type: str | None = Field(
        default=None, alias="bolusType"
    )  # Loop "Square" if duration ≥30
    insulin_type: str | None = Field(default=None, alias="insulinType")
    is_basal_insulin: bool | None = Field(
        default=None, alias="isBasalInsulin"
    )  # AAPS V3

    # Temp Basal
    duration: float | None = None  # MINUTES on the wire (synthesis §2.6)
    duration_in_milliseconds: float | None = Field(
        default=None, alias="durationInMilliseconds"
    )
    rate: float | None = None  # absolute U/h
    absolute: float | None = None  # AAPS field, == rate for absolute mode
    percent: int | float | None = None  # delta from 100 (e.g. -50 = 50%)

    # Combo bolus
    split_now: int | float | None = Field(default=None, alias="splitNow")  # %
    split_ext: int | float | None = Field(default=None, alias="splitExt")  # %
    extended_emulated: dict[str, Any] | None = Field(
        default=None, alias="extendedEmulated"
    )

    # Override / temp target
    target_top: float | None = Field(default=None, alias="targetTop")
    target_bottom: float | None = Field(default=None, alias="targetBottom")
    correction_range: list[float] | None = Field(
        default=None, alias="correctionRange"
    )  # Loop [low, high]
    insulin_needs_scale_factor: float | None = Field(
        default=None, alias="insulinNeedsScaleFactor"
    )  # Loop multiplier
    multiplier: float | None = None  # AAPS/Trio multiplier
    duration_type: str | None = Field(
        default=None, alias="durationType"
    )  # "indefinite"
    remote_address: str | None = Field(default=None, alias="remoteAddress")
    reason: str | None = None  # Override / Temp Basal reason text

    # Profile switch
    profile: str | None = None
    profile_json: str | None = Field(default=None, alias="profileJson")
    original_profile_name: str | None = Field(default=None, alias="originalProfileName")
    percentage: int | float | None = None
    timeshift: int | float | None = None
    original_duration: float | None = Field(default=None, alias="originalDuration")
    original_end: int | float | None = Field(default=None, alias="originalEnd")

    # AAPS dedup
    pump_id: int | None = Field(default=None, alias="pumpId")
    pump_type: str | None = Field(default=None, alias="pumpType")
    pump_serial: str | None = Field(default=None, alias="pumpSerial")
    bolus_calculator_result: str | None = Field(
        default=None, alias="bolusCalculatorResult"
    )

    # xDrip+ separate UUID field (distinct from `_id`)
    uuid: str | None = None

    # Loop sync
    sync_identifier: str | None = Field(default=None, alias="syncIdentifier")
    identifier: str | None = None  # Loop carbs use this; v3 envelope uses this

    # v3 envelope
    app: str | None = None
    subject: str | None = None
    srv_created: int | None = Field(default=None, alias="srvCreated")
    srv_modified: int | None = Field(default=None, alias="srvModified")

    @field_validator("carbs", "insulin", "duration", "rate", "absolute", mode="before")
    @classmethod
    def _coerce_numeric(cls, v: Any) -> float | None:
        """Care Portal sends numbers as strings; coerce permissively."""
        return _coerce_to_float(v)

    @property
    def normalized_event_type(self) -> str:
        """Lowercased eventType for case-insensitive matching."""
        return (self.event_type or "").strip().lower()

    @property
    def has_carbs(self) -> bool:
        return self.carbs is not None and self.carbs > 0

    @property
    def has_insulin(self) -> bool:
        return self.insulin is not None and self.insulin > 0

    @property
    def has_rate_signal(self) -> bool:
        return any(v is not None for v in (self.rate, self.absolute, self.percent))

    @property
    def is_smb(self) -> bool:
        """Detect SMB across all 5 known encodings (synthesis §1.1).

        - Trio: bare `eventType: "SMB"`
        - AAPS V1: `Correction Bolus` + `type: "SMB"` + `isSMB: true`
        - AAPS V3: `Correction Bolus` + `type: "SMB"` + `isBasalInsulin` (no isSMB)
        - Loop: `Correction Bolus` + `automatic: true`
        - microbolus field present (some uploaders)
        - oref0: undetectable (just emits "Bolus") -- acceptable lossage
        """
        et = self.normalized_event_type
        if et == "smb":
            return True
        if et == "correction bolus" and (
            (self.type or "").upper() == "SMB"
            or self.is_smb_flag is True
            or self.automatic is True
        ):
            return True
        return self.microbolus is not None

    @property
    def is_external_insulin(self) -> bool:
        """Trio's `External Insulin` eventType + variants from other uploaders.

        oref0 convention is `Bolus` with non-openaps enteredBy is external,
        but that requires uploader detection upstream of this property.
        """
        return self.normalized_event_type == "external insulin"

    @property
    def is_temp_basal_suspend(self) -> bool:
        """Zero-rate temp basal with duration >=30 min is a pump suspend.

        `rate=0, duration=0` is a CANCEL signal (oref0 stale-CGM, see
        synthesis §1.3 trap), distinct from suspend.
        """
        if not self.has_rate_signal:
            return False
        rate = self.rate if self.rate is not None else self.absolute
        if rate is None or rate > 0:
            return False
        return not (self.duration is None or self.duration < 30)

    @property
    def is_temp_basal_cancel(self) -> bool:
        """Zero-rate temp basal with duration=0 is a CANCEL signal, not suspend."""
        if not self.has_rate_signal:
            return False
        rate = self.rate if self.rate is not None else self.absolute
        if rate is None or rate > 0:
            return False
        return self.duration == 0

    @property
    def is_effective_profile_switch_note(self) -> bool:
        """AAPS uploads Effective Profile Switch as `Note` with `originalProfileName`.

        Telltale: a `Note` carrying `originalProfileName`. Per synthesis
        §1.6 / `mapping/aaps/profile-switch.md §Effective Profile Switch`.
        """
        return (
            self.normalized_event_type == "note"
            and self.original_profile_name is not None
        )

    @property
    def is_fingerstick_treatment(self) -> bool:
        """Treatments-route fingerstick (xDrip4iOS / Care Portal BG Check).

        Detection rule per synthesis §1.8: eventType == "BG Check" OR
        glucoseType == "Finger". Either signal alone confirms.
        """
        et = self.normalized_event_type
        gt = (self.glucose_type or "").lower().strip()
        return et == "bg check" or gt == "finger"

    @property
    def uploader(self) -> str:
        """Detect the upstream uploader from device + enteredBy."""
        return detect_uploader(self.entered_by, self.device_string)

    @property
    def device_string(self) -> str | None:
        """`device` is sometimes carried at top level on treatments
        (esp. via Care Portal). Otherwise None."""
        return getattr(self, "device", None) or self.__pydantic_extra__.get("device")  # type: ignore[union-attr]

    @property
    def is_indefinite_trio_override(self) -> bool:
        """Trio uploads indefinite overrides as duration >= 30 days."""
        return (
            self.uploader == "trio"
            and self.normalized_event_type == "exercise"
            and self.duration is not None
            and self.duration >= TRIO_INDEFINITE_OVERRIDE_DURATION_MIN
        )

    @property
    def is_combo_bolus(self) -> bool:
        et = self.normalized_event_type
        if et == "combo bolus":
            return True
        # AAPS extended bolus emulating TBR: outer Temp Basal with
        # nested extendedEmulated.
        return self.extended_emulated is not None

    @property
    def combo_split_valid(self) -> bool:
        """Per synthesis §2.6: splitNow + splitExt should sum to 100."""
        if self.split_now is None or self.split_ext is None:
            return False
        return abs((self.split_now + self.split_ext) - 100) < 0.01

    @property
    def semantic_kind(self) -> SemanticKind:
        """The translator's routing decision -- what kind of internal event is this?

        Ordering matters: more specific rules first. Field-presence
        wins over eventType when they conflict.
        """
        # Soft-delete -- treat as "unknown" so caller can drop or
        # propagate-deletion as needed.
        if self.is_valid is False:
            return "unknown"

        # Profile-switch family (check before generic Note routing)
        if self.is_effective_profile_switch_note:
            return "effective_profile_switch"
        if self.normalized_event_type == "profile switch":
            return "profile_switch"

        # Combo / extended bolus (special, has both insulin AND rate signals)
        if self.is_combo_bolus:
            return "combo_bolus"

        # Temp Basal family
        if self.is_temp_basal_cancel:
            return "temp_basal_cancel"
        if self.is_temp_basal_suspend:
            return "temp_basal_suspend"
        if self.has_rate_signal:
            return "temp_basal"

        # Fingerstick (treatments-route) -- check before generic bolus routing
        if self.is_fingerstick_treatment:
            return "fingerstick_bg_check"

        # Override / temp target / exercise
        et = self.normalized_event_type
        if et == "temporary override":
            return "override"
        if et == "exercise":
            # Trio uses "Exercise" for ALL override toggles. AAPS may
            # also use Exercise for override-derived events. A bare
            # exercise log from Care Portal goes the same path here;
            # AI analysis distinguishes via uploader + override
            # metadata.
            if self.uploader in ("trio", "aaps"):
                return "override"
            return "exercise_log"
        if et == "temporary target":
            return "temp_target"

        # OpenAPS Offline -- loop-down marker
        if et == "openaps offline":
            return "aps_offline"

        # Bolus / carb routing -- by FIELD PRESENCE (eventType is a hint)
        if self.has_carbs and self.has_insulin:
            return "meal_bolus_pair"
        if self.has_insulin:
            return "bolus"
        if self.has_carbs:
            return "carb_entry"

        # Device events (sensor/site/insulin/battery changes)
        if et in _DEVICE_EVENT_EVENTTYPES:
            return "device_event"

        # Note / Announcement / fallback
        if et == "note":
            return "note"
        if et == "announcement":
            return "announcement"

        return "unknown"

    @property
    def canonical_timestamp(self) -> datetime | None:
        """Resolve the treatment's timestamp from the fallback chain.

        Per synthesis §2.1: treatments use `created_at` (ISO Z) as
        canonical. Some uploaders also send `date` (ms), `timestamp`,
        or `mills`. Fall back through them.
        """
        candidates = [
            self.created_at,
            self.__pydantic_extra__.get("date") if self.__pydantic_extra__ else None,
            self.__pydantic_extra__.get("timestamp")
            if self.__pydantic_extra__
            else None,
            self.__pydantic_extra__.get("mills") if self.__pydantic_extra__ else None,
        ]
        for c in candidates:
            parsed = _parse_iso_or_epoch(c)
            if parsed is not None:
                return parsed
        return None


# ---------------------------------------------------------------------------
# DeviceStatus
# ---------------------------------------------------------------------------


class NightscoutDeviceStatus(BaseModel):
    """A single record from `/api/v1/devicestatus.json`.

    Open-schema -- every uploader attaches its own subtree
    (`pump`, `loop`, `openaps`, `uploader`, `xdripjs`, etc.). We type
    the common envelope; subtrees are preserved as raw dicts and
    parsed lazily by domain-specific helpers.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str | None = Field(default=None, alias="_id")
    device: str | None = None
    created_at: str | None = None
    pump: dict[str, Any] | None = None
    uploader: dict[str, Any] | None = None
    loop: dict[str, Any] | None = None
    openaps: dict[str, Any] | None = None
    xdripjs: dict[str, Any] | None = None
    override: dict[str, Any] | None = None  # Loop's override subtree

    # AAPS V1 quirk: emits `uploaderBattery` (top-level int) AND/OR
    # the nested `uploader.battery`. Accept both.
    uploader_battery: int | None = Field(default=None, alias="uploaderBattery")
    is_charging: bool | None = Field(default=None, alias="isCharging")

    @property
    def uploader_name(self) -> str:
        """Detect uploader from device string."""
        return detect_uploader(None, self.device)

    @property
    def iob_value(self) -> float | None:
        """Extract IOB using the priority order from synthesis §7.3.

        For Loop: `loop.iob` is canonical; `pump.iob` is always nil.
        For AAPS / oref0: `pump.iob` is populated, also `openaps.iob`.
        Try `loop.iob` first, then `pump.iob`, then `openaps.iob`.
        """
        if self.loop and isinstance(self.loop.get("iob"), dict):
            value = self.loop["iob"].get("iob")
            if isinstance(value, int | float):
                return float(value)
        if self.pump and isinstance(self.pump.get("iob"), int | float):
            return float(self.pump["iob"])
        if self.openaps and isinstance(self.openaps.get("iob"), dict):
            value = self.openaps["iob"].get("iob")
            if isinstance(value, int | float):
                return float(value)
        return None

    @property
    def loop_failure_reason(self) -> str | None:
        """`loop.failureReason` is mutually exclusive with `loop.enacted`."""
        if not self.loop:
            return None
        v = self.loop.get("failureReason")
        return str(v) if isinstance(v, str) else None

    @property
    def pump_battery_percent(self) -> int | None:
        if not self.pump:
            return None
        battery = self.pump.get("battery")
        if isinstance(battery, dict):
            v = battery.get("percent")
            if isinstance(v, int):
                return v
        return None

    @property
    def pump_reservoir(self) -> float | None:
        """`reservoir: null` is valid (oref0). Don't crash on None."""
        if not self.pump:
            return None
        v = self.pump.get("reservoir")
        if isinstance(v, int | float):
            return float(v)
        return None


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


class NightscoutProfileStore(BaseModel):
    """A single named profile inside a NightscoutProfile document."""

    model_config = ConfigDict(extra="allow")

    dia: float | None = None
    timezone: str | None = None
    units: str | None = None  # "mg/dl" or "mmol"
    carbs_hr: float | None = None
    delay: float | None = None
    carbratio: list[dict[str, Any]] | None = None
    sens: list[dict[str, Any]] | None = None
    basal: list[dict[str, Any]] | None = None
    target_low: list[dict[str, Any]] | None = None
    target_high: list[dict[str, Any]] | None = None


class NightscoutProfile(BaseModel):
    """A single record from `/api/v1/profile.json`.

    Profiles use `startDate` (ISO Z) as canonical timestamp -- different
    from entries (`date`) and treatments (`created_at`). NS sorts the
    profile collection by `startDate desc`.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str | None = Field(default=None, alias="_id")
    default_profile: str | None = Field(default=None, alias="defaultProfile")
    start_date: str | None = Field(default=None, alias="startDate")
    store: dict[str, NightscoutProfileStore] | None = None
    units: str | None = None  # global default if per-store unset

    @property
    def canonical_timestamp(self) -> datetime | None:
        """Profile timestamp is `startDate`."""
        return _parse_iso_or_epoch(self.start_date)

    def active_profile(self) -> NightscoutProfileStore | None:
        """Return the store entry for `defaultProfile`.

        Profile name match is case-sensitive (synthesis §7.4) -- Trio
        writes `"default"`, Loop tends to `"Default"`. Preserve casing.
        """
        if self.default_profile is None or self.store is None:
            return None
        return self.store.get(self.default_profile)
