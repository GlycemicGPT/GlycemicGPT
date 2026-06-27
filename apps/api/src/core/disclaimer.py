"""Single source of truth for the safety-disclaimer version and its check.

Lives in ``core`` (a leaf module) so the disclaimer router, the auth router, and
the user response schema can share the version-gating logic without importing
one another.

Version-bump contract: incrementing :data:`DISCLAIMER_VERSION` must re-prompt
*every* surface.

* Session (pre-auth) flow: ``/api/disclaimer/status`` compares the stored
  ``DisclaimerAcknowledgment.disclaimer_version``; ``/acknowledge`` advances it.
* Authenticated flow: the ``users.disclaimer_version`` column is compared via
  :func:`has_acknowledged_current`; ``/acknowledge-auth`` advances it. This
  replaces the one-shot reset migration used for v1.1 (see migration
  ``056_reset_disclaimer_for_v1_1`` -- its own note recommends this column).
"""

from __future__ import annotations

from typing import Protocol

# Current disclaimer version -- increment when the disclaimer text changes.
# 1.1: added AI data-handling acknowledgment (cloud vs local provider data flow).
# 1.2: added photo carb-estimate (vision) acknowledgment (Story 50.S).
DISCLAIMER_VERSION = "1.2"


class _AcknowledgingUser(Protocol):
    """Structural type for the user fields the version check reads."""

    disclaimer_acknowledged: bool
    disclaimer_version: str | None


def has_acknowledged_current(user: _AcknowledgingUser) -> bool:
    """Return ``True`` only if the user acknowledged the *current* disclaimer.

    An acknowledgment recorded for an older version (or none at all) does not
    count, so bumping :data:`DISCLAIMER_VERSION` re-prompts authenticated users
    on their next request -- mirroring the session-based flow and removing the
    need for a reset migration on every bump.
    """
    return bool(user.disclaimer_acknowledged) and (
        user.disclaimer_version == DISCLAIMER_VERSION
    )
