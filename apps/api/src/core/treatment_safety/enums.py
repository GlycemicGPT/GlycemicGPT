"""Treatment safety enums.

Validation types for the treatment safety subsystem.
See __init__.py for important regulatory context.
"""

from enum import StrEnum, auto


class SafetyCheckType(StrEnum):
    """Types of safety checks applied to treatment requests."""

    max_single_bolus = auto()
    max_daily_total = auto()
    cgm_freshness = auto()
    rate_limit = auto()
    glucose_range_check = auto()
    user_confirmation_required = auto()


class BolusSource(StrEnum):
    """Origin of a bolus request.

    Both ``ai_suggested`` and ``automated`` boluses MUST pass
    ``SafetyCheckType.user_confirmation_required`` before approval.
    This invariant is enforced structurally in the validator.

    ``ai_suggested``: AI-recommended bolus. MUST be presented with a
    mandatory disclaimer. Auto-execution is strictly prohibited
    regardless of validation outcome.

    ``automated``: Closed-loop pump mode bolus. Requires explicit
    user confirmation before any delivery action.
    """

    manual = auto()
    ai_suggested = auto()
    automated = auto()


class ValidationStatus(StrEnum):
    """Outcome of a bolus validation check."""

    approved = auto()
    rejected = auto()
