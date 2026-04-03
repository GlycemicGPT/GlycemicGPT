"""Treatment safety clinical constants.

All clinically significant values are defined here with documented
rationale. These are DEFAULTS -- user-configurable limits override
where applicable (e.g., max single bolus comes from the user's
safety_limits row, not from here).
"""

from typing import Final

# CGM freshness: Maximum age of CGM reading (minutes) before a bolus
# is refused. 15 min = 3x the 5-minute CGM reading interval. This
# matches clinical standard of care (e.g., Tandem Control-IQ uses
# 10-20 min depending on mode).
CGM_FRESHNESS_MAX_MINUTES: Final[int] = 15

# Rate limit: Minimum interval (minutes) between consecutive bolus
# deliveries for the same user. Prevents accidental double-dosing.
# 15 min aligns with rapid-acting insulin onset (Humalog/NovoLog).
MIN_BOLUS_INTERVAL_MINUTES: Final[int] = 15

# Daily total: Default max daily insulin via bolus (milliunits).
# 100 units covers high-insulin-need T2D while still providing a
# safety net. User-configurable via safety_limits.
DEFAULT_MAX_DAILY_BOLUS_MILLIUNITS: Final[int] = 100_000

# Glucose safety floor: Below this (mg/dL), no bolus should be
# delivered. This is a hard floor independent of user settings.
# 70 mg/dL is the ADA hypoglycemia threshold.
LOW_GLUCOSE_THRESHOLD_MGDL: Final[int] = 70
