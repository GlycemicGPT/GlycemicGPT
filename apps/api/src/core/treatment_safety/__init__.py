"""Treatment safety validation.

This module enforces safety guardrails for bolus delivery requests.
Every bolus request -- regardless of which plugin originates it --
must pass through the TreatmentSafetyValidator before reaching the
pump. Six checks run on every request (no short-circuit):

1. Max single bolus (user-configured)
2. Max daily total (user-configured)
3. CGM freshness (must have recent reading)
4. Rate limiting (minimum interval between boluses)
5. Glucose range (hard hypoglycemia floor + user range)
6. User confirmation (required for non-manual sources)

IMPORTANT: This validator is a software safety layer -- it does NOT
replace clinical judgment. Before implementing pump control features:

1. Review MEDICAL-DISCLAIMER.md for regulatory context
2. Review CONTRIBUTING.md for the pump control policy
3. Obtain legal counsel regarding FDA/regulatory requirements
4. Safety limits are enforced at the platform level -- see
   src.schemas.safety_limits for the active safety limit
   configuration.
"""

from src.core.treatment_safety.enums import (
    BolusSource,
    SafetyCheckType,
    ValidationStatus,
)
from src.core.treatment_safety.models import (
    BolusRequest,
    BolusValidationResult,
    SafetyCheckResult,
)
from src.core.treatment_safety.validator import TreatmentSafetyValidator

__all__ = [
    "BolusRequest",
    "BolusSource",
    "BolusValidationResult",
    "SafetyCheckResult",
    "SafetyCheckType",
    "TreatmentSafetyValidator",
    "ValidationStatus",
]
