"""Shared unit metadata and conversion helpers."""

from __future__ import annotations

import enum


class GlucoseUnit(str, enum.Enum):
    """Supported user-facing glucose display units."""

    MGDL = "mgdl"
    MMOL = "mmol"


# 1 mmol/L = 18.0182 mg/dL (standard glucose mass-to-molarity conversion;
# ADA / IFCC consensus is 18.0156 to 4 decimals). 18.0182 is the single
# canonical factor so ingestion, onboarding, and display conversion cannot
# drift independently. It is chosen for round-trip precision after rounding
# to 1 decimal at the wire boundary: sub-decimal differences wash out
# (e.g. 4.4 mmol -> 79.28 vs 79.27 both round to 79.3). It supersedes the
# old translator-local 18.02; the ~0.01% shift is below the rounding step
# for whole-number mg/dL.
MGDL_PER_MMOL: float = 18.0182


def mgdl_to_mmol(value_mgdl: int | float) -> float:
    """Convert mg/dL to mmol/L, rounded for display."""
    return round(value_mgdl / MGDL_PER_MMOL, 1)


def mmol_to_mgdl(value_mmol: int | float) -> int:
    """Convert mmol/L to integer mg/dL."""
    return int(round(value_mmol * MGDL_PER_MMOL))
