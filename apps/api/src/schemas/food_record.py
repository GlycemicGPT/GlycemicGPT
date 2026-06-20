"""Food record response schemas.

A food record is a descriptive nutrition observation. These schemas expose the
carb *range*, confidence, nutrition, and provenance -- and deliberately carry no
dose/insulin field. Nothing here computes or returns dosing guidance.
"""

import json
import math
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field, model_validator

from src.models.food_record import FoodRecordSource
from src.vision.carb_contract import (
    CARB_GRAMS_MAX,
    CARB_GRAMS_MIN,
    COMORBIDITY_NUTRITION_DISCLAIMER,
    COMORBIDITY_NUTRITION_NOTES,
    MACRO_GLUCOSE_NOTES,
    NET_CARBS_CAVEAT,
    NUTRITION_DOSE_DISCLAIMER,
    SAFETY_QUALIFIER,
    SUGAR_FREE_NOTE,
)

if TYPE_CHECKING:
    from src.models.food_record_audit import FoodRecordAudit


class GroundingDetail(BaseModel):
    """Grounding detail returned alongside a fresh estimate (Story 50.E1).

    Describes *which* source grounded the estimate and the grounded carb range it
    suggests. This is a descriptive, cite-able reference -- never a dose. The
    persisted record keeps its own vision estimate in ``carbs_low`` / ``carbs_high``;
    this object carries the supplementary grounded figure + citation for the UI.

    It is computed at estimate time (the create path) and is not persisted beyond
    the attribution fields (``grounding_source`` / ``grounding_source_url`` /
    ``grounding_trust_tier``), so reads of an existing record carry those flat
    fields but not this object.
    """

    source: str
    source_url: str | None = None
    trust_tier: str
    # Grounded carb range from the source (own-history prior value, or the
    # published per-serving/per-100g figure). May be absent if the source only
    # confirms identity without a usable number.
    carbs_low: float | None = Field(default=None, ge=CARB_GRAMS_MIN, le=CARB_GRAMS_MAX)
    carbs_high: float | None = Field(default=None, ge=CARB_GRAMS_MIN, le=CARB_GRAMS_MAX)
    # The basis of the grounded figure (e.g. "per 100 g", "your last log").
    serving: str | None = None
    # Human-readable note ("You've logged this before (~45g)").
    note: str | None = None
    # Source licence / non-medical disclaimer to surface (e.g. Open Food Facts).
    disclaimer: str | None = None
    # --- Grounding-backed comorbidity nutrition ---
    # Saturated fat / sugars / added sugars / sodium from the same grounded source,
    # when published. Only present on a published-fact grounding (USDA / OFF /
    # restaurant); an own-history recall leaves them None (no label). Persisted via
    # ``comorbidity_dict()`` into the record's ``grounding_nutrition_json``.
    saturated_fat_grams: float | None = Field(default=None, ge=0)
    sugars_grams: float | None = Field(default=None, ge=0)
    added_sugars_grams: float | None = Field(default=None, ge=0)
    sodium_mg: float | None = Field(default=None, ge=0)

    def comorbidity_dict(self) -> dict | None:
        """The grounded comorbidity values as a dict for persistence, or None.

        Only the present (non-None) keys are kept, so a source that publishes no
        comorbidity data persists nothing rather than a dict of nulls.
        """
        values = {
            "saturated_fat_grams": self.saturated_fat_grams,
            "sugars_grams": self.sugars_grams,
            "added_sugars_grams": self.added_sugars_grams,
            "sodium_mg": self.sodium_mg,
        }
        present = {k: v for k, v in values.items() if v is not None}
        return present or None

    @model_validator(mode="after")
    def validate_carb_ordering(self) -> "GroundingDetail":
        """Carb low must not exceed high when both are present (reject inversion)."""
        if (
            self.carbs_low is not None
            and self.carbs_high is not None
            and self.carbs_low > self.carbs_high
        ):
            msg = "carbs_low must not exceed carbs_high"
            raise ValueError(msg)
        return self


class EstimateDispersion(BaseModel):
    """Multi-sample dispersion detail returned with a fresh estimate (Story 50.H1).

    The same photo is sampled N times; ``confidence`` is derived from how much
    those samples disagree (their coefficient of variation), NOT from the model's
    self-reported confidence -- which research shows is uncorrelated with accuracy
    and is therefore never surfaced as a safety signal. ``carbs_low`` / ``carbs_high``
    on the record are the empirical band (the observed spread across samples).

    This is computed at estimate time (the create path) and is transient: it is
    not persisted by H1 (50.H3 adds durable audit retention), so reads of an
    existing record do not carry it.

    Safety: ``wide_spread`` and ``note`` exist to communicate uncertainty
    viscerally, never to bless a number. Low dispersion is NOT "safe to dose" --
    consistency is not correctness -- so callers keep the never-dose-or-bolus
    qualifier dominant regardless of this value.
    """

    # Empirical, dispersion-derived band (constrained so a typo'd band can't pass
    # this system boundary).
    confidence: Literal["low", "medium", "high"]
    coefficient_of_variation: float | None = None
    # The configured target sample count (settings.meal_estimate_sample_count),
    # not necessarily the number of network calls made; ``samples_used`` is how
    # many produced a usable, in-bounds estimate.
    samples_requested: int
    samples_used: int
    identity_agreement: bool
    distinct_identities: list[str] = Field(default_factory=list)
    wide_spread: bool = False
    note: str | None = None


# --- Glucose-relevant nutrition surfacing (Story 50.N1) ---------------------- #
# The four glucose-relevant, photo-estimable non-carb macros, in display order,
# paired with a user label and unit. The descriptive glucose framing per macro
# lives in ``carb_contract.MACRO_GLUCOSE_NOTES`` so all the safety-adjacent copy
# sits in one scrubber-checked place. Only these four known keys are surfaced as
# framed facts; arbitrary keys from a user correction are intentionally not
# echoed back as "nutrition facts" (the raw ``*_nutrition_json`` still carries
# them for any client that wants them).
_MACRO_DISPLAY: dict[str, tuple[str, str]] = {
    "protein_grams": ("Protein", "g"),
    "fat_grams": ("Fat", "g"),
    "fiber_grams": ("Fiber", "g"),
    "calories": ("Calories", "kcal"),
}

# Sane upper bounds for surfaced macro values, so a single off-contract garbage
# field can't render an absurd nutrition card. Reject-not-clamp (like the carb
# bounds): an over-ceiling value is dropped, never shown. Grams mirror the carb
# ceiling; calories allow a large-but-finite meal.
_MACRO_MAX: dict[str, float] = {
    "protein_grams": CARB_GRAMS_MAX,
    "fat_grams": CARB_GRAMS_MAX,
    "fiber_grams": CARB_GRAMS_MAX,
    "calories": 10000.0,
}


class MacroFact(BaseModel):
    """One glucose-relevant macro with descriptive framing (Story 50.N1).

    Read-only and descriptive: ``glucose_note`` explains how the macro tends to
    affect glucose (no peak-timing number, no dosing language) -- it is never a
    dose, and the value never feeds dosing math.
    """

    key: str
    label: str
    value: float = Field(ge=0)
    unit: str
    glucose_note: str = ""


class NetCarbsEstimate(BaseModel):
    """Net carbs (total carbs minus fiber), surfaced only behind a caveat (50.N1).

    The highest dosing-creep risk of the carb fields, so the product decision
    (2026-06-19) is surface-with-heavy-caveat: it travels with ``caveat`` (the
    ADA "count total carbs" pointer plus the never-dose prohibition), is clearly
    secondary to the total carb range, and is **display-only** -- computed at
    serialization time, never persisted, and never fed to IoB / treatment_safety
    / carb-ratio math.
    """

    low: float = Field(ge=CARB_GRAMS_MIN, le=CARB_GRAMS_MAX)
    high: float = Field(ge=CARB_GRAMS_MIN, le=CARB_GRAMS_MAX)
    caveat: str = NET_CARBS_CAVEAT

    @model_validator(mode="after")
    def validate_ordering(self) -> "NetCarbsEstimate":
        """Net-carb low must not exceed high (mirrors the other carb-band models)."""
        if self.low > self.high:
            msg = "net carbs low must not exceed high"
            raise ValueError(msg)
        return self


class NutritionFacts(BaseModel):
    """Display-ready, glucose-framed nutrition for a food record (Story 50.N1).

    Computed at serialization time from the record's (corrected-or-original)
    nutrition + carbs + assumptions and **never persisted**, so the framed macros
    and net carbs only ever exist as a read-side description -- there is no column
    for them to leak into dosing math from. ``portion`` is the assumed portion
    (the estimate's primary sanity-check); ``disclaimer`` carries the never-dose
    prohibition over the whole block.
    """

    portion: str | None = None
    macros: list[MacroFact] = Field(default_factory=list)
    net_carbs: NetCarbsEstimate | None = None
    disclaimer: str = NUTRITION_DOSE_DISCLAIMER


def _macro_value(raw: object, maximum: float | None = None) -> float | None:
    """Coerce a nutrition value to a finite, in-range float, else ``None``.

    Drops anything that is not a non-negative finite number, and (when
    ``maximum`` is given) anything above that ceiling -- reject-not-clamp, so an
    absurd off-contract value is omitted rather than rendered.
    """
    # bool is an int subclass; a True/False must never read as 1/0 grams.
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    value = float(raw)
    if not math.isfinite(value) or value < 0:
        return None
    if maximum is not None and value > maximum:
        return None
    return value


def build_nutrition_facts(
    *,
    nutrition: dict | None,
    carbs_low: float,
    carbs_high: float,
    portion: str | None,
) -> NutritionFacts | None:
    """Assemble the display-ready, glucose-framed nutrition block (Story 50.N1).

    Returns ``None`` when there is nothing to show (no usable macros and no
    portion). Net carbs is included only when fiber is known and leaves a positive
    remainder. Everything here is descriptive -- nothing computed is a dose, and
    the result is never persisted.
    """
    nutrition = nutrition or {}
    portion_text = (
        portion.strip() if isinstance(portion, str) and portion.strip() else None
    )

    macros: list[MacroFact] = []
    for key, (label, unit) in _MACRO_DISPLAY.items():
        value = _macro_value(nutrition.get(key), _MACRO_MAX.get(key))
        if value is None:
            continue
        macros.append(
            MacroFact(
                key=key,
                label=label,
                value=value,
                unit=unit,
                glucose_note=MACRO_GLUCOSE_NOTES.get(key, ""),
            )
        )

    # Net carbs = total carbs minus fiber, as a range mirroring the carb band.
    # Fiber-gated and clamped at zero; skipped when fiber would wipe out the band
    # (a zero/negative net value is not worth surfacing).
    net_carbs: NetCarbsEstimate | None = None
    fiber = _macro_value(nutrition.get("fiber_grams"), _MACRO_MAX["fiber_grams"])
    if fiber and fiber > 0:
        net_high = carbs_high - fiber
        if net_high > 0:
            net_low = max(0.0, carbs_low - fiber)
            net_carbs = NetCarbsEstimate(low=net_low, high=net_high)

    if not macros and net_carbs is None and portion_text is None:
        return None
    return NutritionFacts(portion=portion_text, macros=macros, net_carbs=net_carbs)


# --- Grounding-backed comorbidity / label nutrition ------------ #
# The comorbidity (blood-pressure / cardiovascular) label fields, in display
# order, paired with a user label and unit. Unlike the N1 macros (photo-estimated)
# these are GROUNDING-ONLY: surfaced solely from an authoritative grounded source
# after identity confirmation. The descriptive awareness framing per field lives in
# ``carb_contract.COMORBIDITY_NUTRITION_NOTES`` so all the safety-adjacent copy sits
# in one scrubber-checked place.
_COMORBIDITY_DISPLAY: dict[str, tuple[str, str]] = {
    "saturated_fat_grams": ("Saturated fat", "g"),
    "sugars_grams": ("Sugars", "g"),
    "added_sugars_grams": ("Added sugars", "g"),
    "sodium_mg": ("Sodium", "mg"),
}

# Sane upper bounds so a single off-contract garbage value can't render an absurd
# card. Reject-not-clamp (like the macro/carb bounds): an over-ceiling value is
# dropped, never shown. Grams mirror the carb ceiling; sodium (mg) allows a large
# but finite amount (100 g of sodium per portion is already implausible).
_COMORBIDITY_MAX: dict[str, float] = {
    "saturated_fat_grams": CARB_GRAMS_MAX,
    "sugars_grams": CARB_GRAMS_MAX,
    "added_sugars_grams": CARB_GRAMS_MAX,
    "sodium_mg": 100_000.0,
}

# Whether a surfaced field is a sugars field (drives the "sugar-free is not
# carb-free" reminder).
_SUGAR_KEYS = frozenset({"sugars_grams", "added_sugars_grams"})


class ComorbidityFact(BaseModel):
    """One grounding-backed comorbidity nutrient with awareness framing.

    Read-only and descriptive: ``note`` explains why the figure matters for
    comorbidity (blood-pressure / cardiovascular) awareness, never a clinical
    limit or a dose. The value never feeds dosing math.
    """

    key: str
    label: str
    value: float = Field(ge=0)
    unit: str
    note: str = ""


class ComorbidityNutrition(BaseModel):
    """Grounding-backed comorbidity / label nutrition block.

    GROUNDING-ONLY and identity-gated: populated solely from an authoritative
    grounded source (USDA / Open Food Facts / restaurant) once the user has
    confirmed identity -- never asserted from the photo. Framed as blood-pressure /
    cardiovascular awareness, never a directive. Carries its OWN attribution
    (``source`` / ``source_url`` / ``trust_tier``), distinct from the vision
    estimate, and a ``disclaimer`` carrying the never-dose prohibition.
    """

    facts: list[ComorbidityFact] = Field(default_factory=list)
    # The "sugar-free is not carb-free" reminder; present only when a sugars
    # figure is surfaced.
    sugar_note: str | None = None
    # Grounding attribution for these figures (the single source they came from).
    source: str | None = None
    source_url: str | None = None
    trust_tier: str | None = None
    disclaimer: str = COMORBIDITY_NUTRITION_DISCLAIMER


def build_comorbidity_nutrition(
    *,
    grounding_nutrition: dict | None,
    source: str | None,
    source_url: str | None,
    trust_tier: str | None,
) -> ComorbidityNutrition | None:
    """Assemble the grounding-backed comorbidity block.

    Reads ONLY the grounded comorbidity values (never the photo's
    ``nutrition_json``), so a comorbidity figure can structurally never originate
    from the vision estimate. Returns ``None`` when there is nothing grounded to
    show. Everything here is descriptive awareness -- nothing is a dose, and the
    block is never persisted (only the flat ``grounding_nutrition_json`` is).
    """
    grounding_nutrition = grounding_nutrition or {}
    facts: list[ComorbidityFact] = []
    for key, (label, unit) in _COMORBIDITY_DISPLAY.items():
        value = _macro_value(grounding_nutrition.get(key), _COMORBIDITY_MAX.get(key))
        if value is None:
            continue
        facts.append(
            ComorbidityFact(
                key=key,
                label=label,
                value=value,
                unit=unit,
                note=COMORBIDITY_NUTRITION_NOTES.get(key, ""),
            )
        )

    if not facts:
        return None

    sugar_note = SUGAR_FREE_NOTE if any(f.key in _SUGAR_KEYS for f in facts) else None
    return ComorbidityNutrition(
        facts=facts,
        sugar_note=sugar_note,
        source=source,
        source_url=source_url,
        trust_tier=trust_tier,
    )


class FoodRecordResponse(BaseModel):
    """A persisted food record returned to the client.

    ``carbs_low`` / ``carbs_high`` are the original AI estimate. When the record
    has been corrected, ``corrected_carbs_*`` carry the user's values and
    ``source`` is ``user_corrected``; the original estimate is kept.

    ``confidence`` is the **empirical** dispersion-derived band (Story 50.H1), not
    the model's self-reported confidence (which is no longer surfaced).
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    meal_timestamp: datetime
    food_description: str | None = None
    # Reject-not-clamp bounds, consistent with SafetyLimits conventions.
    carbs_low: float = Field(ge=CARB_GRAMS_MIN, le=CARB_GRAMS_MAX)
    carbs_high: float = Field(ge=CARB_GRAMS_MIN, le=CARB_GRAMS_MAX)
    confidence: str | None = None
    # Server-emitted safety qualifier (Story 50.S): a constant that travels with
    # every estimate so a non-mobile client can't render carbs without the
    # "this is a guess, never dose from it" framing. Mirrors the mobile string.
    safety_qualifier: str = Field(default=SAFETY_QUALIFIER)
    nutrition_json: dict | None = None
    # The model's assumed portion / preparation (Story 50.N1), surfaced as the
    # estimate's primary sanity-check. Persisted, dosing-scrubbed, length-capped.
    assumptions: str | None = None
    source: FoodRecordSource
    corrected_carbs_low: float | None = Field(
        default=None, ge=CARB_GRAMS_MIN, le=CARB_GRAMS_MAX
    )
    corrected_carbs_high: float | None = Field(
        default=None, ge=CARB_GRAMS_MIN, le=CARB_GRAMS_MAX
    )
    corrected_nutrition_json: dict | None = None
    corrected_at: datetime | None = None
    common_food_id: uuid.UUID | None = None
    ai_model: str | None = None
    ai_provider: str | None = None
    # Food-identity confirmation (Story 50.H2). ``food_description`` is the
    # AI-identified name; ``confirmed_food_name`` is the user's confirmed/corrected
    # identity (null until confirmed); external grounding only runs once
    # ``identity_confirmed`` is true. ``suggested_identity`` is a transient
    # create-time own-history pre-fill ("looks like your saved X"); absent later.
    confirmed_food_name: str | None = None
    identity_confirmed: bool = False
    suggested_identity: str | None = None
    # Grounding provenance (Story 50.E1). The flat fields are persisted on the
    # record and present on every read; ``grounding`` is the richer create-time
    # detail (grounded range + note + disclaimer) and is absent on later reads.
    grounding_source: str | None = None
    grounding_source_url: str | None = None
    grounding_trust_tier: str | None = None
    # Grounding-backed comorbidity nutrition. ``grounding_nutrition_json`` is the
    # raw persisted column (saturated fat / sugars / added sugars / sodium) mapped
    # off the ORM; it is read internally to build ``comorbidity_nutrition`` -- the
    # display-ready, awareness-framed, attributed block clients actually consume --
    # and is itself excluded from the response (an internal column, not a client
    # field). Both are absent (null) on a record with no grounded comorbidity data.
    grounding_nutrition_json: dict | None = Field(default=None, exclude=True)
    comorbidity_nutrition: "ComorbidityNutrition | None" = None
    grounding: GroundingDetail | None = None
    # Multi-sample dispersion (Story 50.H1). Transient create-time detail
    # (empirical confidence + observed spread); absent on later reads.
    estimate_dispersion: EstimateDispersion | None = None
    # Display-ready, glucose-framed nutrition (Story 50.N1): the assumed portion,
    # the framed macros, and caveated net carbs. Computed from the fields below
    # at serialization time -- never persisted (see ``build_nutrition_facts``), so
    # it can only ever be a read-side description, never a dosing input.
    nutrition_facts: NutritionFacts | None = None
    created_at: datetime

    @model_validator(mode="after")
    def validate_carb_ordering(self) -> "FoodRecordResponse":
        """Carb low must not exceed high (reject, never reorder silently)."""
        if self.carbs_low > self.carbs_high:
            msg = "carbs_low must not exceed carbs_high"
            raise ValueError(msg)
        if (
            self.corrected_carbs_low is not None
            and self.corrected_carbs_high is not None
            and self.corrected_carbs_low > self.corrected_carbs_high
        ):
            msg = "corrected_carbs_low must not exceed corrected_carbs_high"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def build_nutrition_facts_block(self) -> "FoodRecordResponse":
        """Compute the glucose-framed nutrition block (Story 50.N1).

        Built here -- not stored -- from the corrected-or-original nutrition and
        carb band plus the assumed portion. Runs after ``validate_carb_ordering``
        so the carb band it reads is already known well-ordered.
        """
        eff_low = (
            self.corrected_carbs_low
            if self.corrected_carbs_low is not None
            else self.carbs_low
        )
        eff_high = (
            self.corrected_carbs_high
            if self.corrected_carbs_high is not None
            else self.carbs_high
        )
        self.nutrition_facts = build_nutrition_facts(
            nutrition=self.corrected_nutrition_json or self.nutrition_json,
            carbs_low=eff_low,
            carbs_high=eff_high,
            portion=self.assumptions,
        )
        return self

    @model_validator(mode="after")
    def build_comorbidity_block(self) -> "FoodRecordResponse":
        """Compute the grounding-backed comorbidity block.

        Built here -- not stored -- ONLY from the grounded comorbidity values and
        the record's grounding attribution, so a comorbidity figure can never
        originate from the photo's ``nutrition_json``. Absent on a record with no
        grounded comorbidity data.
        """
        self.comorbidity_nutrition = build_comorbidity_nutrition(
            grounding_nutrition=self.grounding_nutrition_json,
            source=self.grounding_source,
            source_url=self.grounding_source_url,
            trust_tier=self.grounding_trust_tier,
        )
        return self


class FoodRecordListResponse(BaseModel):
    """A page of food records (most recent first)."""

    records: list[FoodRecordResponse]
    total: int


class AuditSample(BaseModel):
    """One raw vision sample, as surfaced in the audit trail (Story 50.H3).

    Deliberately omits the model's self-reported confidence: that is retained in
    storage for internal eval/triage only and is never surfaced as a user-facing
    signal (the whole point of 50.H1).
    """

    carbs_low: float | None = None
    carbs_high: float | None = None
    identity: str | None = None
    parse_ok: bool = False


class AuditDispersion(BaseModel):
    """The empirical dispersion summary surfaced in the audit trail (50.H3).

    A typed allow-list (like ``AuditSample``) so the no-leak guarantee for the
    discredited self-reported confidence is enforced structurally, not by
    convention -- a future field added to the stored blob can't slip through.
    """

    confidence: str | None = None
    coefficient_of_variation: float | None = None
    samples_requested: int | None = None
    samples_used: int | None = None
    identity_agreement: bool | None = None
    distinct_identities: list[str] = Field(default_factory=list)
    wide_spread: bool | None = None


class FoodRecordAuditResponse(BaseModel):
    """The "how was this estimated" provenance trail for a food record (50.H3).

    Descriptive only -- raw per-sample reads, the empirical dispersion summary,
    and the precedence decision. No dose, and nothing here feeds dosing math.
    """

    food_record_id: uuid.UUID
    samples: list[AuditSample] = Field(default_factory=list)
    dispersion: AuditDispersion | None = None
    # The precedence decision is intentionally schema-loose (a raw dict): its
    # shape is still settling pre-50.E2. It is built entirely by our own code
    # (services.meal_audit) and never contains per-sample/self-reported data.
    precedence: dict | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_audit(cls, audit: "FoodRecordAudit") -> "FoodRecordAuditResponse":
        """Build from a ``FoodRecordAudit`` row, stripping internal-only fields."""
        samples = [
            AuditSample(
                carbs_low=s.get("carbs_low"),
                carbs_high=s.get("carbs_high"),
                identity=s.get("identity"),
                parse_ok=bool(s.get("parse_ok")),
            )
            for s in (audit.samples_json or [])
            if isinstance(s, dict)
        ]
        dispersion = (
            AuditDispersion.model_validate(audit.dispersion_json)
            if isinstance(audit.dispersion_json, dict)
            else None
        )
        return cls(
            food_record_id=audit.food_record_id,
            samples=samples,
            dispersion=dispersion,
            precedence=audit.precedence_json,
            created_at=audit.created_at,
            updated_at=audit.updated_at,
        )


# Cap user-supplied nutrition so a correction can't store an unbounded JSON blob.
# Bound both the field count and the serialized size: the key count alone does
# not stop a single key holding a deeply-nested / multi-MB value.
_MAX_NUTRITION_KEYS = 30
_MAX_NUTRITION_SERIALIZED_CHARS = 2000


def validate_nutrition(nutrition: dict | None) -> dict | None:
    """Reject an oversized nutrition object; otherwise return it unchanged.

    Shared by the food-record correction and common-food schemas so user-supplied
    nutrition is bounded identically everywhere it is accepted.
    """
    if nutrition is None:
        return None
    if len(nutrition) > _MAX_NUTRITION_KEYS:
        msg = f"nutrition has too many fields (max {_MAX_NUTRITION_KEYS})"
        raise ValueError(msg)
    if len(json.dumps(nutrition, default=str)) > _MAX_NUTRITION_SERIALIZED_CHARS:
        msg = "nutrition is too large"
        raise ValueError(msg)
    return nutrition


class FoodRecordCorrectionRequest(BaseModel):
    """A user correction of a food record's carbs/nutrition.

    Correction fixes a *description of the food*, never a dose. There is
    deliberately no insulin/units/dose field here, and the corrected values are
    never read by IoB / treatment_safety / carb-ratio math. The original AI
    estimate is preserved on the record; these values land in the
    ``corrected_*`` columns and flip provenance to ``user_corrected``.
    """

    model_config = {"extra": "forbid"}

    # Reject-not-clamp bounds, identical to the create path.
    corrected_carbs_low: float = Field(ge=CARB_GRAMS_MIN, le=CARB_GRAMS_MAX)
    corrected_carbs_high: float = Field(ge=CARB_GRAMS_MIN, le=CARB_GRAMS_MAX)
    corrected_nutrition: dict | None = None

    @model_validator(mode="after")
    def validate_correction(self) -> "FoodRecordCorrectionRequest":
        if self.corrected_carbs_low > self.corrected_carbs_high:
            msg = "corrected_carbs_low must not exceed corrected_carbs_high"
            raise ValueError(msg)
        validate_nutrition(self.corrected_nutrition)
        return self


# Cap a user-supplied identity at the schema boundary (the service caps again as
# defence-in-depth; keep in sync with common_food._MAX_IDENTITY_CHARS).
_MAX_IDENTITY_NAME_CHARS = 200


class FoodRecordIdentityRequest(BaseModel):
    """A user confirmation/correction of *what the food is* (Story 50.H2).

    Confirming identity is distinct from correcting carbs and never implies a
    dose. The confirmed name opens the grounding gate: external authoritative
    nutrition (USDA / Open Food Facts today; restaurant facts via 50.E2) is only
    looked up once an identity has been confirmed, so a misidentified label is
    never certified with a citation.
    """

    model_config = {"extra": "forbid"}

    confirmed_food_name: str = Field(min_length=1, max_length=_MAX_IDENTITY_NAME_CHARS)

    @model_validator(mode="after")
    def validate_identity(self) -> "FoodRecordIdentityRequest":
        if not self.confirmed_food_name.strip():
            msg = "confirmed_food_name must not be blank"
            raise ValueError(msg)
        return self
