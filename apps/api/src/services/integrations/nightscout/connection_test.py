"""Connection-test entry point used by the router.

Thin wrapper around `NightscoutClient.test_connection()`. The router's
`POST /api/integrations/nightscout` endpoint calls `test_connection()`
from this module; keeping this module's public surface stable means
the router doesn't change when the underlying client evolves.

Public API:
- `test_connection(base_url, auth_type, credential, api_version)` →
  `ConnectionTestOutcome`
- `ConnectionTestOutcome` (re-exported from client)

The validation/probe logic lives in
`src.services.integrations.nightscout.client`. SSRF guards live in
`.ssrf`. Typed errors in `.errors`.
"""

from __future__ import annotations

from src.models.nightscout_connection import (
    NightscoutApiVersion,
    NightscoutAuthType,
)

from .client import (
    CONNECT_TEST_TIMEOUT_SECONDS,
    ConnectionTestOutcome,
    NightscoutClient,
)
from .errors import NightscoutValidationError

__all__ = ["ConnectionTestOutcome", "test_connection"]


async def test_connection(
    base_url: str,
    auth_type: NightscoutAuthType,
    credential: str,
    api_version: NightscoutApiVersion,
) -> ConnectionTestOutcome:
    """Probe a Nightscout instance to validate it accepts the credential.

    Returns a structured outcome describing success or the failure
    reason. **Never raises** -- the router relies on this contract to
    serialize the outcome to the wire and persist it to
    `last_sync_error`. Validation errors from `NightscoutClient.create`
    and any unexpected exceptions are flattened into
    `ConnectionTestOutcome(ok=False, error=...)`.
    """
    try:
        client = await NightscoutClient.create(
            base_url=base_url,
            auth_type=auth_type,
            credential=credential,
            api_version=api_version,
            timeout_seconds=CONNECT_TEST_TIMEOUT_SECONDS,
        )
    except NightscoutValidationError as exc:
        return ConnectionTestOutcome(ok=False, error=str(exc))
    except Exception as exc:  # noqa: BLE001
        # Defense in depth: any unexpected exception during create()
        # (DNS surprises, httpx-side bugs, etc.) is flattened into the
        # outcome rather than propagated to the router. The router has
        # no story for handling exceptions here -- it expects an
        # outcome it can persist.
        return ConnectionTestOutcome(ok=False, error=f"unexpected error: {exc}")

    try:
        async with client:
            return await client.test_connection()
    except Exception as exc:  # noqa: BLE001
        # `client.test_connection()` already catches its expected
        # error classes and returns an outcome. This handler exists
        # for the same defense-in-depth reason as above.
        return ConnectionTestOutcome(ok=False, error=f"unexpected error: {exc}")
