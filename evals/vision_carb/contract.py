"""Vision carb-estimate contract -- re-exported from the backend.

The canonical contract (prompt + JSON shape + parser + dosing-safety scan)
lives in the production backend at ``apps/api/src/vision/carb_contract.py`` so
the live estimation pipeline and this offline accuracy harness score against
the exact same definition and can never drift. This shim makes the backend
module importable as ``contract`` from the harness/tests, which run with this
directory on ``sys.path``.

The module is pure-stdlib and importing it pulls in only the trivial ``src``
and ``src.vision`` package ``__init__`` files -- no FastAPI/SQLAlchemy/config.
"""

import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_API_ROOT = os.path.join(_REPO_ROOT, "apps", "api")
if _API_ROOT not in sys.path:
    sys.path.insert(0, _API_ROOT)

from src.vision.carb_contract import (  # noqa: E402,F401
    CARB_GRAMS_MAX,
    CARB_GRAMS_MIN,
    CONFIDENCE_LEVELS,
    ESTIMATE_JSON_SHAPE,
    SYSTEM_PROMPT,
    USER_PROMPT,
    CarbBoundsError,
    ParsedEstimate,
    find_dosing_violations,
    parse_estimate,
    validate_carb_range,
)

__all__ = [
    "CARB_GRAMS_MAX",
    "CARB_GRAMS_MIN",
    "CONFIDENCE_LEVELS",
    "ESTIMATE_JSON_SHAPE",
    "SYSTEM_PROMPT",
    "USER_PROMPT",
    "CarbBoundsError",
    "ParsedEstimate",
    "find_dosing_violations",
    "parse_estimate",
    "validate_carb_range",
]
