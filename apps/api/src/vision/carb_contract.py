"""Structured carb-estimate contract for vision carb estimation.

This module owns the *shape* of a vision carb estimate and the prompt that
elicits it. It is deliberately model-agnostic: the same messages are sent to
any OpenAI-compatible endpoint (the GlycemicGPT sidecar for cloud vision, or a
local vision model), so one contract serves both the production estimation
pipeline (``src.services.food_vision``) and the offline accuracy harness
(``evals/vision_carb`` re-exports this module so the two never drift).

Safety posture (non-negotiable; the product's "mirror, never advisor" charter):
  * Output describes the *food*, never an *action*. No insulin/dose/units phrasing.
  * The estimate is a carb *range* plus a *confidence* signal -- never a bare,
    falsely-precise integer.
  * Nothing here computes or implies a dose; downstream code must never feed an
    estimate into IoB / treatment_safety / carb-ratio math.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field

CONFIDENCE_LEVELS = ("low", "medium", "high")

# Absolute carbohydrate bounds (grams) for a single photographed meal. These
# follow the platform's reject-not-clamp convention (see
# `schemas/safety_limits.py`): a value outside the range is rejected, never
# silently clamped, so a hallucinated or mis-parsed estimate is surfaced as an
# error rather than persisted as a misleading record. The ceiling is a generous
# sanity bound -- a single plate above ~1 kg of carbohydrate is implausible and
# signals a model/parse failure, not a real meal.
CARB_GRAMS_MIN = 0.0
CARB_GRAMS_MAX = 1000.0


class CarbBoundsError(ValueError):
    """A carb range fell outside the absolute bounds (reject-not-clamp)."""


def validate_carb_range(low: float, high: float) -> tuple[float, float]:
    """Return ``(low, high)`` unchanged, or raise if outside absolute bounds.

    Reject-not-clamp: invalid values raise ``CarbBoundsError`` so the caller can
    surface a clear error instead of storing a distorted estimate. Never clamps.

    Notes:
      * This is the standalone/defense-in-depth bound check. In the estimation
        pipeline ``parse_estimate`` runs first and already normalizes a swapped
        ``low``/``high``, so the ``low > high`` branch here is reachable only
        when this is called directly (e.g. the eval harness) on un-normalized
        input.
      * ``low == high`` is permitted: the model is prompted for a range, but a
        degenerate equal-bound estimate is a valid value -- we never *fabricate*
        a point, and the confidence signal plus the persistent
        "never use it to dose or bolus" qualifier carry the uncertainty.
    """
    if not (math.isfinite(low) and math.isfinite(high)):
        msg = "carbohydrate bound is not a finite number"
        raise CarbBoundsError(msg)
    if low < CARB_GRAMS_MIN or high < CARB_GRAMS_MIN:
        msg = f"carbohydrate bound below {CARB_GRAMS_MIN:g} g"
        raise CarbBoundsError(msg)
    if low > CARB_GRAMS_MAX or high > CARB_GRAMS_MAX:
        msg = f"carbohydrate bound above {CARB_GRAMS_MAX:g} g"
        raise CarbBoundsError(msg)
    if low > high:
        msg = "carbs_low must not exceed carbs_high"
        raise CarbBoundsError(msg)
    return low, high


# The model is asked to return exactly this JSON shape. Documented here so the
# backend estimation service and the local-model benchmark share one
# definition of "a vision carb estimate".
ESTIMATE_JSON_SHAPE = {
    "food_description": "string -- what the food appears to be",
    "items": "optional array of {name, estimated_portion} -- components seen",
    "carbs_grams_low": "number -- low end of the carbohydrate range, in grams",
    "carbs_grams_high": "number -- high end of the carbohydrate range, in grams",
    "confidence": 'one of "low" | "medium" | "high"',
    "assumptions": "string -- portion-size / preparation assumptions made",
    "nutrition": (
        "optional object with any of protein_grams, fat_grams, fiber_grams, "
        "calories -- include only what is visually estimable"
    ),
}

SYSTEM_PROMPT = (
    "You are a nutrition observation assistant for a diabetes monitoring app. "
    "You look at a photo of food and describe its likely carbohydrate content. "
    "You are a mirror and an observer, never an advisor: you describe what the "
    "food is, never what the person should do about it.\n\n"
    "Hard rules:\n"
    "- Report carbohydrates as a RANGE (low to high grams), never a single "
    "confident number. Real plates are uncertain; reflect that.\n"
    "- Include a confidence signal (low/medium/high) based on how clearly you "
    "can identify the food and judge the portion.\n"
    "- State the portion assumptions you made.\n"
    "- NEVER mention insulin, dosing, units to take, boluses, carb ratios, or "
    "any treatment action. You describe food, not therapy.\n"
    "- If you cannot tell what the food is, say so and widen the range.\n\n"
    "Respond with ONLY a JSON object (no prose, no code fence) of this shape:\n"
    + json.dumps(ESTIMATE_JSON_SHAPE, indent=2)
)

USER_PROMPT = (
    "Estimate the carbohydrates in this meal. Describe the food and give a "
    "low-high gram range with a confidence level. Return only the JSON object."
)

# Phrasing that would turn a description into dosing advice. Its presence in a
# response is a safety-posture violation. Bare "units" is NOT flagged on its own
# (it has benign uses, e.g. "unit of measurement") -- only insulin units / a
# dosing-or-suggestion verb near "units" / the "Nu"/"NU" insulin-unit
# abbreviation (e.g. "6u", "take 4U") / explicit dosing terms.
#
# Story 50.N1 added two more, to close the dosing-creep risk that surfacing net
# carbs + fat/protein introduces: "dose (on/for) (net) carbs" -- dosing a carb
# figure directly, with or without a preposition -- and the Warsaw fat-protein-
# unit concept ("FPU" / "fat-protein units"), whose whole purpose is to convert
# fat+protein into extra insulin. Both are hard violations regardless of nearby
# "units" wording.
_DOSING_PATTERNS = re.compile(
    r"\b("
    r"insulin|bolus(?:es|ing)?|"
    r"units?\s+of\s+insulin|"
    r"(?:take|inject|administer|give|deliver|dose|dosing|suggest|recommend"
    r"|consider|cover|need)\b[^.]{0,40}\bunits?\b|"
    r"(?:dose|dosing)\s+(?:(?:for|on|off|against|using|from|per)\s+)?"
    r"(?:the\s+)?(?:net\s+)?carb(?:s|ohydrates?)?|"
    r"fat[- ]protein\s+units?|fpus?|"
    r"\d{1,3}\s*u\b|"
    r"carb\s*ratio|insulin[- ]to[- ]carb|correction\s+factor|"
    r"how\s+much\s+insulin"
    r")\b",
    re.IGNORECASE,
)

# Canonical user-facing safety qualifier for a vision carb estimate. Names the
# prohibited action explicitly (never dose/bolus) rather than the softer
# "verify before dosing". Single source of truth for the API surfaces; the
# mobile client mirrors this string in MealComponents.kt.
SAFETY_QUALIFIER = (
    "Rough estimate — an AI guess that's often wrong. "
    "Never use it to calculate an insulin dose or bolus."
)

# The non-negotiable prohibition shared by every carb surface: a carb figure --
# whether an AI vision estimate or one grounded against a published source (USDA /
# Open Food Facts) -- is descriptive only and must never drive a dose. Kept as a
# single source of truth so the exact phrasing cannot drift between the inline
# estimate qualifier below and the grounding disclaimers in
# ``services/nutrition_sources.py``. Deliberately absolute ("never use it to dose
# or bolus") rather than the permissive "verify before dosing", which would imply
# dosing off the figure is fine once checked.
NEVER_DOSE_PROHIBITION = "never use it to dose or bolus"

# Inline counterpart to SAFETY_QUALIFIER for when a carb figure is embedded in a
# sentence (chat / daily brief) rather than shown on its own. Same non-negotiable
# posture: the figure is an AI guess, often wrong, and must NEVER drive a dose.
# It names the prohibited action and deliberately avoids "verify before dosing",
# which would wrongly imply that dosing off the estimate is fine once checked --
# we never tell a user it is OK to bolus from a carb guess.
MEAL_ESTIMATE_QUALIFIER = f"AI estimate, often wrong — {NEVER_DOSE_PROHIBITION}"

# --- Glucose-relevant nutrition framing (Story 50.N1) ------------------------
# Protein/fat/fiber/calories are the strongest photo-estimable, glucose-relevant
# *non-carb* fields; surfaced alongside the carb range they explain *why* a meal
# behaves the way it does -- never how to dose. Each note describes the food's
# effect on glucose and is deliberately:
#   * free of any dosing language (each passes ``find_dosing_violations``), and
#   * free of a specific peak-timing number -- the "protein peaks at ~5h" claim
#     was found overstated, so protein/fat say "later, in the hours after a meal"
#     with no figure (real time-to-peak is shorter and highly variable).
# Keyed by the ``nutrition_json`` key so the framing travels with the value.
MACRO_GLUCOSE_NOTES = {
    "protein_grams": "Protein can nudge glucose up later, in the hours after a meal.",
    "fat_grams": "Fat can slow digestion, so glucose may rise later, hours after a meal.",
    "fiber_grams": "Fiber slows and blunts the rise in glucose.",
    "calories": "Calories reflect the overall size of the meal.",
}

# Net carbs (total carbs minus fiber) is the highest dosing-creep risk of the
# nutrition fields, so it is surfaced ONLY with this caveat (product decision
# 2026-06-19): named as inexact, pointing the user back to total carbs (the ADA's
# recommendation), and carrying the non-negotiable never-dose prohibition. Like
# ``SAFETY_QUALIFIER`` it intentionally *names* the prohibited action ("dose or
# bolus"), so -- by design -- it does NOT itself pass ``find_dosing_violations``:
# it is a prohibition, not a description of food.
NET_CARBS_CAVEAT = (
    "Net carbs (total carbs minus fiber) is a rough estimate, not exact — "
    "the ADA recommends counting total carbs. "
    f"AI estimate, often wrong — {NEVER_DOSE_PROHIBITION}."
)

# Section-level disclaimer for the whole nutrition block: these figures describe
# the meal and must never drive a dose. Carries the never-dose prohibition so the
# framing can never be read as therapy guidance.
NUTRITION_DOSE_DISCLAIMER = (
    "These nutrition figures are rough AI estimates that describe the meal — "
    f"{NEVER_DOSE_PROHIBITION}."
)

# --- Grounding-backed comorbidity / label nutrition framing -----
# Saturated fat, sugars/added sugars, and sodium aren't reliably estimable from a
# plated-food photo, and their value is comorbidity (blood-pressure / cardiovascular)
# awareness -- so they are GROUNDING-ONLY (looked up from a published source after
# identity confirmation) and framed as awareness, never a directive. Each note is
# deliberately:
#   * free of any dosing language (each passes ``find_dosing_violations``), and
#   * descriptive of why the figure matters, not a clinical limit or a dose input.
# Adversarially verified: total fat (not its saturation) drives the acute glucose
# effect, so saturated fat is framed as cardiovascular awareness only; sodium has
# no acute glucose link but real blood-pressure value. Keyed by the grounding
# nutrition key so the framing travels with the value.
COMORBIDITY_NUTRITION_NOTES = {
    "saturated_fat_grams": (
        "Saturated fat is a heart-health signal, not a glucose one — it doesn't "
        "change your sugar rise, but it's worth knowing for cardiovascular health."
    ),
    "sugars_grams": (
        "Sugars are carbohydrates that tend to spike glucose sooner than starches do."
    ),
    "added_sugars_grams": (
        "Added sugars are put in during processing — like other sugars, they tend "
        "to spike glucose sooner."
    ),
    "sodium_mg": (
        "Sodium matters for blood pressure — it doesn't affect glucose, but it's "
        "worth keeping an eye on for cardiovascular health."
    ),
}

# The "sugar-free is not carb-free" note that travels with a surfaced sugars
# figure: a reminder that the absence of sugar does not mean the food won't raise
# glucose. Descriptive and dosing-language-free (passes ``find_dosing_violations``);
# it points back to total carbs, never to a dose.
SUGAR_FREE_NOTE = (
    "Sugar-free doesn't mean carb-free — sugar alcohols and starches still raise "
    "glucose, so count total carbohydrates."
)

# Section-level disclaimer for the comorbidity block. These are PUBLISHED reference
# figures (not AI estimates), shown for blood-pressure / heart-health awareness, so
# -- like the OFF / restaurant disclaimers -- this avoids the "AI guess" framing and
# reuses only the canonical ``NEVER_DOSE_PROHIBITION``. By naming the prohibited
# action ("bolus") it intentionally does NOT itself pass ``find_dosing_violations``:
# it is a prohibition, not a description of food.
COMORBIDITY_NUTRITION_DISCLAIMER = (
    "These figures come from published nutrition data, shown for blood-pressure "
    f"and heart-health awareness — a descriptive reference only; {NEVER_DOSE_PROHIBITION}."
)


@dataclass
class ParsedEstimate:
    """A validated vision carb estimate plus its safety findings."""

    carbs_low: float | None
    carbs_high: float | None
    confidence: str | None
    food_description: str
    raw_text: str
    nutrition: dict = field(default_factory=dict)
    # The model's stated portion-size / preparation assumptions (Story 50.N1).
    # Retained (the contract always asked for it; it used to be dropped) so the
    # *assumed portion* -- the dominant error source -- can be surfaced as the
    # primary sanity-check on the estimate. Free-form prose; treated like
    # ``food_description`` (dosing-scrubbed before it is persisted/surfaced).
    assumptions: str = ""
    parse_ok: bool = False
    parse_error: str | None = None
    dosing_violations: list[str] = field(default_factory=list)

    @property
    def midpoint(self) -> float | None:
        if self.carbs_low is None or self.carbs_high is None:
            return None
        return (self.carbs_low + self.carbs_high) / 2.0

    @property
    def is_safe(self) -> bool:
        return not self.dosing_violations


def find_dosing_violations(text: str) -> list[str]:
    """Return any dosing/advice phrases found in a model response."""
    return [m.group(0) for m in _DOSING_PATTERNS.finditer(text or "")]


def _extract_json_object(text: str) -> str | None:
    """Pull the first balanced JSON object out of a model response.

    Tolerates code fences and surrounding prose so a slightly chatty model is
    still scoreable. The brace scan is string-aware -- braces inside string
    literals do not affect nesting depth -- so a valid object whose description
    contains "{" or "}" is not truncated.
    """
    if not text:
        return None
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _coerce_number(value: object) -> float | None:
    # bool is a subclass of int; reject it so True/False aren't read as 1/0.
    if isinstance(value, bool):
        return None
    result: float | None = None
    if isinstance(value, (int, float)):
        result = float(value)
    elif isinstance(value, str):
        m = re.search(r"-?\d+(?:\.\d+)?", value)
        if m:
            result = float(m.group(0))
    # Reject NaN / +-Inf: Python's json accepts these non-standard tokens, and
    # they slip past every range comparison (all `nan < x` are False), so guard
    # here rather than letting a non-finite carb value reach the DB.
    if result is None or not math.isfinite(result):
        return None
    return result


def parse_estimate(raw_text: str) -> ParsedEstimate:
    """Parse and validate a model response into a ParsedEstimate.

    Always runs the dosing-safety scan, even when JSON parsing fails, so an
    off-contract response that smuggles in advice is still flagged.
    """
    violations = find_dosing_violations(raw_text)

    # Try the whole response as JSON first (the common, on-contract case, and
    # robust to braces inside string values); only then fall back to extracting
    # a balanced object from surrounding prose / a code fence.
    blob = _extract_json_object(raw_text)
    candidates = []
    if raw_text and raw_text.strip():
        candidates.append(raw_text.strip())
    if blob:
        candidates.append(blob)

    data = None
    parse_error: str | None = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as exc:
            parse_error = f"invalid JSON: {exc}"
            continue
        if isinstance(parsed, dict):
            data = parsed
            parse_error = None
            break
        parse_error = "JSON value is not an object"

    if data is None:
        return ParsedEstimate(
            carbs_low=None,
            carbs_high=None,
            confidence=None,
            food_description="",
            raw_text=raw_text,
            parse_ok=False,
            # If there was no object to find at all, say so plainly; otherwise
            # surface why the object we found did not parse.
            parse_error=(parse_error if blob else "no JSON object found in response"),
            dosing_violations=violations,
        )

    low = _coerce_number(data.get("carbs_grams_low"))
    high = _coerce_number(data.get("carbs_grams_high"))
    confidence = data.get("confidence")
    if isinstance(confidence, str):
        confidence = confidence.strip().lower()
        if confidence not in CONFIDENCE_LEVELS:
            confidence = None

    error = None
    parse_ok = True
    if low is None or high is None:
        parse_ok = False
        error = "missing carbs_grams_low / carbs_grams_high"
    elif low < 0 or high < 0:
        # Carbohydrates can't be negative; an impossible range would distort the
        # accuracy metrics, so treat it as unparseable rather than scoring it.
        # Null the values too so a caller that ignores `parse_ok` can't read a
        # negative bound.
        parse_ok = False
        error = "negative carbohydrate bound"
        low = high = None
    elif low > high:
        # Tolerate a swapped range rather than discard the data point.
        low, high = high, low

    nutrition = data.get("nutrition")
    if not isinstance(nutrition, dict):
        nutrition = {}

    # Only treat a string as a description; a JSON null/number must not become
    # the literal "None"/"42".
    raw_description = data.get("food_description")
    food_description = (
        raw_description.strip() if isinstance(raw_description, str) else ""
    )

    # Same string-only guard for the portion/preparation assumptions.
    raw_assumptions = data.get("assumptions")
    assumptions = raw_assumptions.strip() if isinstance(raw_assumptions, str) else ""

    return ParsedEstimate(
        carbs_low=low,
        carbs_high=high,
        confidence=confidence,
        food_description=food_description,
        raw_text=raw_text,
        nutrition=nutrition,
        assumptions=assumptions,
        parse_ok=parse_ok,
        parse_error=error,
        dosing_violations=violations,
    )
