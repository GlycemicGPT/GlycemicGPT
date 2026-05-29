"""CareLink CarePartner (Connect) HTTP client -- recent-data fetch (clean-room).

The autonomous follower path. Where the manual import (``client.py``) talks to
the CareLink Personal *web* API and downloads a historical CSV, this client
talks to the CarePartner *mobile* cloud and pulls the recent (~24h) snapshot:

    POST {cloud}/connect/carepartner/v13/display/message
        body {username, role, patientId?, appVersion} + Bearer access token
        -> DisplayMessage{patientData: RecentData}

``RecentData`` is then handed to ``connect_mapper.map_recent_data``.

**Auth is injected** as an async ``bearer_provider`` (an Auth0 access token from
the rotating refresh-token grant -- see ``connect_auth``), exactly like
``CareLinkClient``, so this data method is independent of and testable without
the token machinery.

Clean-room attribution: the endpoint path, request body, and response envelope
were learned from xDrip (NightscoutFoundation/xDrip, ``cgm/carelinkfollow`` --
GPL-3.0, license-compatible with this GPL-3.0 project), re-implemented in Python.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from urllib.parse import urlparse

import httpx

#: CarePartner cloud hosts per region (xDrip CARELINK_CLOUD_SERVER_*). The data
#: API lives under the "cumulus" cloud host, not carelink.minimed.com.
CLOUD_HOST_US = "https://clcloud.minimed.com"
#: EU/OUS uses the SAME Auth0 PKCE flow as US (see ``connect_auth.REGIONS``;
#: both were derived from Medtronic's discovery + SSO-config JSONs). It is
#: exposed as a selectable region, but has not been validated end-to-end against
#: a live OUS account yet -- consistent with the rest of this alpha feature, if
#: it misbehaves users report an issue rather than us gating it off.
CLOUD_HOST_EU = "https://clcloud.minimed.eu"

#: display/message path (xDrip API_PATH_DISPLAY_MESSAGE).
_DISPLAY_MESSAGE_PATH = "/connect/carepartner/v13/display/message"

#: CarePartner app version sent in the request body (xDrip uses "3.6.0").
APP_VERSION = "3.6.0"

#: Max retries on HTTP 429 before giving up.
_MAX_RETRIES_429 = 3

#: A real ~24h CarePartner snapshot is tiny; reject an implausibly large
#: response before we JSON-parse it (parsing would allocate a second, larger
#: structure on top of the raw bytes). NOTE: httpx has already buffered the body
#: by the time this check runs, so it bounds parse-time blow-up, not the
#: download itself.
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024

#: Allowed host suffixes -- base_url is injectable, so without this an
#: attacker-influenced region/url could make the client POST the bearer to an
#: arbitrary host (SSRF / credential exfiltration). Same allowlist as the manual
#: client; CarePartner clouds live under minimed.com (US) / minimed.eu (EU).
_ALLOWED_HOST_SUFFIXES = ("minimed.com", "minimed.eu")

#: Valid CarePartner roles. "patient" = the user syncing their own pump (the
#: autonomous self-sync case); "carepartner" = a follower watching someone else
#: (requires patientId).
ROLE_PATIENT = "patient"
ROLE_CAREPARTNER = "carepartner"

BearerProvider = Callable[[], Awaitable[str]]


class ConnectError(Exception):
    """Base error for CarePartner Connect client calls."""


class ConnectAuthError(ConnectError):
    """401/403 from CarePartner -- the access token is invalid or expired."""


class CareLinkConnectClient:
    def __init__(
        self,
        *,
        bearer_provider: BearerProvider,
        username: str,
        base_url: str = CLOUD_HOST_US,
        role: str = ROLE_PATIENT,
        patient_id: str | None = None,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        host = (urlparse(base_url).hostname or "").lower()
        if not any(host == s or host.endswith("." + s) for s in _ALLOWED_HOST_SUFFIXES):
            raise ValueError(
                f"Refusing CarePartner base_url with untrusted host {host!r}; "
                f"allowed: {_ALLOWED_HOST_SUFFIXES}"
            )
        if role not in (ROLE_PATIENT, ROLE_CAREPARTNER):
            raise ValueError(f"Unknown CarePartner role {role!r}")
        if role == ROLE_CAREPARTNER and not patient_id:
            raise ValueError("carepartner role requires a patient_id")
        if not username:
            raise ValueError("username is required")
        self._bearer_provider = bearer_provider
        self._username = username
        self._role = role
        self._patient_id = patient_id
        self._base_url = base_url.rstrip("/")
        self._owns_client = client is None
        # CarePartner (clcloud.minimed.com) sits behind Cloudflare; we've seen
        # the very first POST from a freshly-created httpx client take longer
        # than 5s end-to-end, which made the original tight connect/pool
        # timeouts trip with an empty-message error. Give it the full budget.
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds)
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> CareLinkConnectClient:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()

    async def _headers(self) -> dict[str, str]:
        bearer = await self._bearer_provider()
        return {
            "Authorization": f"Bearer {bearer}",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
        }

    def _check(self, resp: httpx.Response) -> None:
        if resp.status_code in (401, 403):
            raise ConnectAuthError(
                f"CarePartner auth failed ({resp.status_code}); token invalid/expired"
            )
        if resp.status_code >= 400:
            raise ConnectError(
                f"CarePartner request to {resp.request.url.path} failed: "
                f"{resp.status_code}"
            )

    def _retry_after_seconds(self, resp: httpx.Response, attempt: int) -> float:
        header = resp.headers.get("Retry-After")
        if header and header.isdigit():
            return min(float(header), 30.0)
        return min(2.0 * (2**attempt), 30.0) + random.random()

    async def _post(self, path: str, *, json: dict) -> httpx.Response:
        """POST with retry on 429 (honoring Retry-After) and one retry on 5xx."""
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES_429 + 1):
            try:
                resp = await self._client.post(
                    f"{self._base_url}{path}",
                    headers=await self._headers(),
                    json=json,
                )
            except httpx.HTTPError as e:
                # Include the exception class -- httpx's TimeoutException and
                # similar can have empty str() repr, which would otherwise hide
                # the real failure mode in operator-visible error messages.
                raise ConnectError(
                    f"CarePartner network error on POST {path}: "
                    f"{type(e).__name__}: {e or '<no message>'}"
                ) from e

            if resp.status_code == 429 and attempt < _MAX_RETRIES_429:
                await asyncio.sleep(self._retry_after_seconds(resp, attempt))
                continue
            if 500 <= resp.status_code < 600 and attempt == 0:
                await asyncio.sleep(0.5 + random.random() * 0.5)
                last_exc = ConnectError(
                    f"CarePartner {resp.status_code} on POST {path}"
                )
                continue
            self._check(resp)
            return resp
        raise last_exc or ConnectError(f"CarePartner request to {path} kept failing")

    async def get_recent_data(self) -> dict:
        """Fetch the recent (~24h) ``RecentData`` snapshot for this account.

        Returns the ``patientData`` object from the ``DisplayMessage`` envelope,
        ready for ``connect_mapper.map_recent_data``. Raises ConnectAuthError on
        401/403, ConnectError otherwise.
        """
        body: dict[str, str] = {
            "username": self._username,
            "role": self._role,
            "appVersion": APP_VERSION,
        }
        if self._role == ROLE_CAREPARTNER and self._patient_id:
            body["patientId"] = self._patient_id

        resp = await self._post(_DISPLAY_MESSAGE_PATH, json=body)
        if len(resp.content) > _MAX_RESPONSE_BYTES:
            raise ConnectError(
                f"CarePartner display/message response too large "
                f"({len(resp.content)} bytes > {_MAX_RESPONSE_BYTES} cap)"
            )
        try:
            data = resp.json()
        except ValueError as e:
            raise ConnectError("CarePartner display/message returned non-JSON") from e
        if not isinstance(data, dict):
            raise ConnectError("CarePartner display/message returned unexpected shape")

        # DisplayMessage{patientData: RecentData}. Some responses may already be
        # the RecentData object; accept either rather than silently returning {}.
        patient_data = data.get("patientData")
        if isinstance(patient_data, dict):
            return patient_data
        if "sgs" in data or "markers" in data:
            return data
        raise ConnectError("CarePartner display/message missing patientData")
