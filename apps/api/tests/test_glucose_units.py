"""Tests for the shared glucose display-formatting helpers.

These helpers are the single choke-point that renders a stored mg/dL value as
the text a user reads in their preferred unit. The contract they must hold:

* mg/dL output is byte-identical to the legacy hand-written f-strings
  (whole number + ``mg/dL`` label).
* mmol/L converts from the most-precise mg/dL value and rounds to one decimal
  LAST, so the conventional clinical anchors fall out of the ``18.0156`` factor
  (70 -> 3.9, 180 -> 10.0, 120 -> 6.7) and the textbook 100 -> 5.6 (not 5.5).
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.units import (
    MGDL_PER_MMOL,
    GlucoseUnit,
    format_correction_factor_value,
    format_glucose,
    format_glucose_range,
    format_glucose_rate,
    format_glucose_value,
    glucose_display_matches,
    glucose_unit_label,
    glucose_unit_prompt_instruction,
    mmol_to_mgdl,
)
from src.services.glucose_unit import resolve_glucose_unit

# The clinically conventional mg/dL -> mmol/L anchors. These are what a mmol/L
# user expects to see; if any drifts the user distrusts the number.
CONVENTIONAL_ANCHORS = {
    54: "3.0",
    70: "3.9",
    100: "5.6",  # the 18.0182-vs-18.0156 tell: must be 5.6, not 5.5
    120: "6.7",
    180: "10.0",
    250: "13.9",
}


class TestFormatGlucoseMgdl:
    """mg/dL rendering must be byte-identical to the pre-unit f-strings."""

    @pytest.mark.parametrize("value", [20, 55, 70, 99, 100, 120, 180, 250, 400, 500])
    def test_value_is_whole_number_with_label(self, value):
        assert format_glucose(value, GlucoseUnit.MGDL) == f"{value} mg/dL"

    def test_value_only_has_no_label(self):
        assert format_glucose_value(120, GlucoseUnit.MGDL) == "120"

    def test_range(self):
        assert format_glucose_range(70, 180, GlucoseUnit.MGDL) == "70-180 mg/dL"

    def test_float_value_rounds_to_whole(self):
        # Averages arrive as floats; legacy used ``:.0f``.
        assert format_glucose(145.7, GlucoseUnit.MGDL) == "146 mg/dL"

    def test_rate(self):
        assert format_glucose_rate(50.0, GlucoseUnit.MGDL) == "50.0 mg/dL per unit"

    def test_correction_factor_value_verbatim(self):
        # The CF feeds ``1:X`` notation; mg/dL keeps the stored value exactly,
        # including any fractional (mmol-derived) precision -- no rounding.
        assert format_correction_factor_value(50, GlucoseUnit.MGDL) == "50"
        assert format_correction_factor_value(27.8, GlucoseUnit.MGDL) == "27.8"

    def test_label(self):
        assert glucose_unit_label(GlucoseUnit.MGDL) == "mg/dL"


class TestFormatGlucoseMmol:
    """mmol/L rendering converts once and rounds to one decimal last."""

    @pytest.mark.parametrize("mgdl,expected", CONVENTIONAL_ANCHORS.items())
    def test_conventional_anchors(self, mgdl, expected):
        assert format_glucose_value(mgdl, GlucoseUnit.MMOL) == expected
        assert format_glucose(mgdl, GlucoseUnit.MMOL) == f"{expected} mmol/L"

    def test_99_vs_100_boundary(self):
        # 99 -> 5.49 -> "5.5"; 100 -> 5.55 -> "5.6" (Gotcha G3).
        assert format_glucose_value(99, GlucoseUnit.MMOL) == "5.5"
        assert format_glucose_value(100, GlucoseUnit.MMOL) == "5.6"

    def test_range(self):
        assert format_glucose_range(70, 180, GlucoseUnit.MMOL) == "3.9-10.0 mmol/L"

    def test_rate_converts_as_a_rate(self):
        # 50 mg/dL per unit -> 2.8 mmol/L per unit (same linear factor).
        assert format_glucose_rate(50.0, GlucoseUnit.MMOL) == "2.8 mmol/L per unit"

    def test_correction_factor_value_converts(self):
        # CF is a glucose drop per unit, so it converts like the observed ISF:
        # 1:50 (mg/dL/U) -> 1:2.8 (mmol/L/U); 1:27.8 -> 1:1.5.
        assert format_correction_factor_value(50, GlucoseUnit.MMOL) == "2.8"
        assert format_correction_factor_value(27.8, GlucoseUnit.MMOL) == "1.5"

    def test_label(self):
        assert glucose_unit_label(GlucoseUnit.MMOL) == "mmol/L"


class TestRoundTripNoDrift:
    """Anchors hold and no displayed value drifts past the tolerance band."""

    def test_anchors_are_pure_division_of_the_one_factor(self):
        # The anchors must be exactly ``round(mgdl / 18.0156, 1)`` -- no special
        # anchor table, so they can never disagree with the conversion factor.
        for mgdl, expected in CONVENTIONAL_ANCHORS.items():
            assert f"{round(mgdl / MGDL_PER_MMOL, 1):.1f}" == expected

    @pytest.mark.parametrize("mgdl", range(20, 501))
    def test_displayed_mmol_round_trips_within_tolerance(self, mgdl):
        # Render to mmol, parse it back, and confirm it matches the stored mg/dL
        # within the display tolerance band (no silent drift across the range).
        shown = float(format_glucose_value(mgdl, GlucoseUnit.MMOL))
        assert glucose_display_matches(mgdl, shown, GlucoseUnit.MMOL)
        # And it converts back to within 1 mg/dL of the original.
        assert abs(mmol_to_mgdl(shown) - mgdl) <= 1


class TestGlucoseDisplayMatches:
    """The rounding-tolerant comparison helper (citation-tolerance slice)."""

    def test_mgdl_within_one(self):
        assert glucose_display_matches(120, 120, GlucoseUnit.MGDL)
        assert glucose_display_matches(120, 121, GlucoseUnit.MGDL)
        assert not glucose_display_matches(120, 122, GlucoseUnit.MGDL)

    def test_mmol_within_one_tenth(self):
        assert glucose_display_matches(120, 6.7, GlucoseUnit.MMOL)
        assert glucose_display_matches(120, 6.6, GlucoseUnit.MMOL)
        assert not glucose_display_matches(120, 6.4, GlucoseUnit.MMOL)


class TestPromptInstruction:
    """The instruction pins both the unit and the precision."""

    def test_mgdl(self):
        text = glucose_unit_prompt_instruction(GlucoseUnit.MGDL)
        assert "mg/dL" in text
        assert "mmol/L" not in text

    def test_mmol(self):
        text = glucose_unit_prompt_instruction(GlucoseUnit.MMOL)
        assert "mmol/L" in text
        assert "one decimal" in text


class TestResolveGlucoseUnit:
    """The by-user_id resolver used by the alert/escalation/command paths."""

    async def _resolve(self, scalar_value):
        result = MagicMock()
        result.scalar_one_or_none.return_value = scalar_value
        db = AsyncMock()
        db.execute.return_value = result
        return await resolve_glucose_unit(db, uuid.uuid4())

    @pytest.mark.asyncio
    async def test_returns_configured_unit(self):
        assert await self._resolve(GlucoseUnit.MMOL) == GlucoseUnit.MMOL

    @pytest.mark.asyncio
    async def test_defaults_to_mgdl_when_missing(self):
        # A missing user (None) falls back to mg/dL, matching the non-null column.
        assert await self._resolve(None) == GlucoseUnit.MGDL
