"""Shared unit metadata and conversion helpers."""

from __future__ import annotations

import enum


class GlucoseUnit(str, enum.Enum):
    """Supported user-facing glucose display units."""

    MGDL = "mgdl"
    MMOL = "mmol"


# 1 mmol/L = 18.0156 mg/dL -- the exact glucose mass-to-molarity factor
# (molar mass 180.156 g/mol / 10) and the ADA / IFCC consensus value. This
# is the single canonical factor so ingestion, onboarding, and display
# conversion cannot drift independently. It supersedes two earlier in-repo
# constants (a translator-local 18.02 and an onboarding 18.0182); both were
# slightly off, and 18.0182 in particular rendered the textbook 100 mg/dL as
# 5.5 mmol/L instead of the universally-recognized 5.6. Accuracy matters here
# because every mmol/L surface in the unit epic reads off this factor.
MGDL_PER_MMOL: float = 18.0156


def mgdl_to_mmol(value_mgdl: int | float) -> float:
    """Convert mg/dL to mmol/L, rounded for display."""
    return round(value_mgdl / MGDL_PER_MMOL, 1)


def mmol_to_mgdl(value_mmol: int | float) -> int:
    """Convert mmol/L to integer mg/dL."""
    return int(round(value_mmol * MGDL_PER_MMOL))


# ── Display formatting (AI-text layer) ──
#
# Storage is canonical mg/dL everywhere; these helpers are the single
# choke-point that turns a stored mg/dL value into the text a user reads in
# their preferred unit. They live here -- next to the one conversion constant
# -- so no surface invents its own conversion or label and the mg/dL and mmol/L
# representations can never drift. mg/dL output is byte-identical to the legacy
# hand-written f-strings (integer, ``mg/dL`` label); mmol/L converts from the
# most-precise mg/dL source and rounds to one decimal LAST so threshold anchors
# land on their conventional values (70 -> 3.9, 180 -> 10.0, 120 -> 6.7).


def glucose_unit_label(unit: GlucoseUnit) -> str:
    """Return the user-facing label for a glucose unit (``mg/dL`` / ``mmol/L``)."""
    return "mmol/L" if unit == GlucoseUnit.MMOL else "mg/dL"


def format_glucose_value(value_mgdl: int | float, unit: GlucoseUnit) -> str:
    """Format a stored mg/dL value as a bare number in the user's unit (no label).

    mg/dL renders as a whole number (matching the legacy ``{value:.0f}``
    output); mmol/L converts once and renders to one decimal place.
    """
    if unit == GlucoseUnit.MMOL:
        return f"{mgdl_to_mmol(value_mgdl):.1f}"
    return f"{value_mgdl:.0f}"


def format_glucose(value_mgdl: int | float, unit: GlucoseUnit) -> str:
    """Format a stored mg/dL value as a labeled string in the user's unit.

    e.g. ``"120 mg/dL"`` or ``"6.7 mmol/L"``. The same helper renders glucose
    *deltas* (a drop is a linear difference, so it converts by the same factor)
    -- the caller phrases the surrounding text.
    """
    return f"{format_glucose_value(value_mgdl, unit)} {glucose_unit_label(unit)}"


def format_glucose_range(
    low_mgdl: int | float, high_mgdl: int | float, unit: GlucoseUnit
) -> str:
    """Format a stored mg/dL low-high range as a labeled string in the user's unit.

    e.g. ``"70-180 mg/dL"`` or ``"3.9-10.0 mmol/L"``.
    """
    return (
        f"{format_glucose_value(low_mgdl, unit)}-"
        f"{format_glucose_value(high_mgdl, unit)} {glucose_unit_label(unit)}"
    )


def format_glucose_rate(value_mgdl_per_unit: int | float, unit: GlucoseUnit) -> str:
    """Format an ISF-style rate (glucose drop per unit of insulin) in the user's unit.

    The rate is a glucose delta per insulin unit, so it converts by the same
    linear factor as a value: ``"50.0 mg/dL per unit"`` -> ``"2.8 mmol/L per unit"``.
    """
    if unit == GlucoseUnit.MMOL:
        return f"{mgdl_to_mmol(value_mgdl_per_unit):.1f} mmol/L per unit"
    return f"{value_mgdl_per_unit:.1f} mg/dL per unit"


def format_correction_factor_value(
    value_mgdl_per_unit: int | float, unit: GlucoseUnit
) -> str:
    """Format a correction-factor drop-per-unit value for ``1:X`` notation.

    A correction factor is the same physical quantity as the observed ISF
    (glucose drop per insulin unit), so it converts for mmol/L users -- a US
    ``1:50`` (mg/dL per unit) is ``1:2.8`` mmol/L per unit, which keeps it on the
    same scale as the converted observed ISF the prompt compares it against.
    mg/dL keeps the stored value verbatim, preserving any fractional
    (mmol-derived) precision and staying byte-identical to the legacy
    ``1:{correction_factor}`` rendering. (Carb ratios are grams per unit, not a
    glucose quantity, and never convert.)
    """
    if unit == GlucoseUnit.MMOL:
        return f"{mgdl_to_mmol(value_mgdl_per_unit):.1f}"
    return f"{value_mgdl_per_unit}"


def glucose_unit_prompt_instruction(unit: GlucoseUnit) -> str:
    """Return the explicit instruction telling the LLM which unit to report in.

    The in-context glucose numbers are already converted to ``unit`` before the
    prompt is built; this reinforces that and pins the output precision, because
    the model's free-text cannot be post-converted (no ``mg/dL`` -> ``mmol/L``
    rewriter exists for model prose).
    """
    if unit == GlucoseUnit.MMOL:
        return (
            "Report all glucose values in mmol/L to one decimal place; "
            "the glucose data below is already in mmol/L."
        )
    return (
        "Report all glucose values in mg/dL as whole numbers; "
        "the glucose data below is already in mg/dL."
    )


def glucose_display_matches(
    stored_mgdl: int | float, spoken_value: int | float, unit: GlucoseUnit
) -> bool:
    """Whether an AI-spoken glucose figure matches a stored mg/dL reading.

    The spoken value is in ``unit``; the stored value is canonical mg/dL.
    Comparison uses a display-rounding tolerance band (±1 mg/dL / ±0.1 mmol/L),
    never equality -- converting and rounding to display precision can shift a
    value by up to half a display step, so an exact check would spuriously fail.

    This is the rounding-tolerant slice the AI-text layer needs now; the full
    spoken-glucose citation verification is handled by the end-to-end
    citation-verification work.
    """
    if unit == GlucoseUnit.MMOL:
        return abs((stored_mgdl / MGDL_PER_MMOL) - spoken_value) <= 0.1 + 1e-9
    return abs(stored_mgdl - spoken_value) <= 1.0 + 1e-9
