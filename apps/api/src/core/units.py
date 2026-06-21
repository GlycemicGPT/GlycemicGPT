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
