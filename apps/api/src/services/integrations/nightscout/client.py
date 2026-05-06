"""Nightscout v1 + v3 read client.

The HTTP layer that the GlycemicGPT integration uses to read CGM
entries, treatments, device status, and profile data from a user's
Nightscout (or Nocturne) instance.

Read-only by design. Story 43.3 (translator) + 43.4 (sync scheduler)
consume this client; nothing writes back to Nightscout.

Auth modes:

- **v1 (`auth_type=secret`)**: send the SHA-1 hex digest of the user's
  API_SECRET in the `api-secret` header. SHA-1 is a Nightscout
  protocol requirement, not a security choice (server hashes its own
  secret with SHA-1 and compares). See connection_test.py docstring
  on `_sha1_hex` for full rationale and lint suppressions.
- **v3 (`auth_type=token`)**: send a bearer token in the
  `Authorization: Bearer <token>` header. The token is a Nightscout
  v3 access token associated with a subject, not the API_SECRET. The
  user obtains this from their Nightscout admin tools.
- **`auth_type=auto`**: defer to the explicit api_version. If
  api_version is also `auto`, try v1 first (universal across the
  install base); fall back to v3 only if v1 status returns 404.

Pagination:

- The fetch methods issue a **single request** with `count=N` and an
  optional `find[<field>][$gte]` lower bound. They do NOT loop. Story
  43.4's background sync calls them on a fixed cadence, so multi-page
  pagination is unnecessary as long as `count` exceeds one cycle's
  worth of records (5000 covers a week of 5-min CGM, far more than
  any sane sync interval). If a future caller needs to drain a large
  backlog in one go, layer a paging loop on top.
- v3 endpoints have a different shape (`limit`, `lastModified`) and
  are not implemented for fetches in this client; `_require_v1_for_fetch`
  raises `NotImplementedError` for v3 callers.

Retry policy:

- 429 → exponential backoff, up to MAX_RETRIES_429 retries (4 attempts total) then raise NightscoutRateLimitError
- 5xx → one retry with jitter then raise NightscoutServerError
- 401/403 → raise NightscoutAuthError immediately (no retry)
- 404 → raise NightscoutNotFoundError (auto-detect uses this)
- transport errors → raise NightscoutNetworkError
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from src.models.nightscout_connection import (
    NightscoutApiVersion,
    NightscoutAuthType,
)

from .errors import (
    NightscoutAuthError,
    NightscoutNetworkError,
    NightscoutNotFoundError,
    NightscoutRateLimitError,
    NightscoutServerError,
    NightscoutValidationError,
)
from .ssrf import ValidatedTarget, validate_target

logger = logging.getLogger(__name__)


# Default total request timeout. Story 43.4's background sync uses
# this; the connection-test path overrides to a tighter value for
# fast user feedback.
DEFAULT_TIMEOUT_SECONDS = 30.0
CONNECT_TEST_TIMEOUT_SECONDS = 8.0

# Pagination upper bound. Nightscout v1 accepts up to ~50000 but
# pages of 5000 are a sane batch -- large enough that 7 days of
# 5-minute CGM data (~2000 records) lands in one or two pages, small
# enough that a single failure isn't catastrophic.
DEFAULT_PAGE_SIZE = 5000

# Retry budget for transient errors.
MAX_RETRIES_429 = 3
MAX_RETRIES_5XX = 1
RETRY_BASE_DELAY_SECONDS = 1.0
# Server-supplied Retry-After is bounded by the user's URL (any
# Nightscout instance, including misconfigured or hostile ones), so
# clamp before sleeping. A pathological `Retry-After: 86400` from a
# misbehaving proxy would otherwise pin the connection-test endpoint
# or a sync worker for hours.
RETRY_AFTER_CAP_SECONDS = 30.0


def _sha1_api_secret(secret: str) -> str:
    """SHA-1 hex of the API_SECRET for the v1 `api-secret` header.

    See connection_test.py `_sha1_hex` docstring for the protocol-
    mandate explanation. SHA-1 here is required by Nightscout v1; we
    are not signing or authenticating anything ourselves.
    """
    return hashlib.sha1(secret.encode("utf-8")).hexdigest()  # noqa: S324  # nosemgrep: python.lang.security.insecure-hash-algorithms.insecure-hash-algorithm-sha1


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConnectionTestOutcome:
    """Result of a connection-test attempt.

    Stable shape -- the connection-test stub is a thin wrapper around
    NightscoutClient.test_connection() and the router serializes this
    to the wire.
    """

    ok: bool
    server_version: str | None = None
    api_version_detected: NightscoutApiVersion | None = None
    auth_validated: bool = False
    error: str | None = None


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class NightscoutClient:
    """Async HTTP client for a single Nightscout instance.

    One client per (user, connection) -- the URL and auth are bound
    at construction. Use as an async context manager so the
    underlying httpx client is closed cleanly.

    **Concurrency contract**: a single client instance is intended for
    sequential use by one coroutine at a time. The underlying
    `httpx.AsyncClient` is reentrant for separate requests, but
    `_effective_api_version` (set during `test_connection()` and read
    by fetch methods) is plain mutable state with no lock. If you need
    concurrent fetches, build separate clients. The background sync
    scheduler (Story 43.4) follows this pattern: one client per
    connection per sync cycle, sequential within the cycle.

    Example:
        async with NightscoutClient.create(
            base_url="https://my-ns.example.com",
            auth_type=NightscoutAuthType.SECRET,
            credential="my-api-secret",
            api_version=NightscoutApiVersion.AUTO,
        ) as client:
            outcome = await client.test_connection()
            entries = await client.fetch_entries(count=500)
    """

    def __init__(
        self,
        target: ValidatedTarget,
        auth_type: NightscoutAuthType,
        credential: str,
        api_version: NightscoutApiVersion,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._target = target
        self._auth_type = auth_type
        self._credential = credential
        self._api_version = api_version
        self._timeout_seconds = timeout_seconds
        # Lazily set after a successful auto-detect, or carried over
        # from the explicit api_version. Used by the per-resource
        # methods to pick the right endpoint shape.
        self._effective_api_version: NightscoutApiVersion | None = (
            api_version if api_version != NightscoutApiVersion.AUTO else None
        )
        self._client: httpx.AsyncClient | None = None

    # -- lifecycle ---------------------------------------------------------

    @classmethod
    async def create(
        cls,
        base_url: str,
        auth_type: NightscoutAuthType,
        credential: str,
        api_version: NightscoutApiVersion,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> NightscoutClient:
        """Validate the URL and return an opened client.

        Raises NightscoutValidationError if the URL fails the SSRF
        guard. The client must be closed via `await client.aclose()`
        or used as an async context manager.
        """
        try:
            target = await validate_target(base_url)
        except ValueError as exc:
            raise NightscoutValidationError(str(exc)) from exc
        client = cls(
            target=target,
            auth_type=auth_type,
            credential=credential,
            api_version=api_version,
            timeout_seconds=timeout_seconds,
        )
        client._open()
        return client

    def _open(self) -> None:
        if self._client is not None:
            return
        # Granular timeouts so connect failures surface fast even
        # when the overall budget is generous. Connect is the
        # short-pole most often (DNS / TLS handshake / down server);
        # read budget is what we actually want to be generous about.
        timeout = httpx.Timeout(
            connect=min(5.0, self._timeout_seconds),
            read=self._timeout_seconds,
            write=min(5.0, self._timeout_seconds),
            pool=min(2.0, self._timeout_seconds),
        )
        self._client = httpx.AsyncClient(
            base_url=self._target.base_url,
            timeout=timeout,
            follow_redirects=False,
            headers={
                "User-Agent": "GlycemicGPT/1.0 (Nightscout client)",
                "Accept": "application/json",
            },
        )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> NightscoutClient:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()

    # -- auth + headers ----------------------------------------------------

    def _v1_headers(self) -> dict[str, str]:
        # SHA-1 of the credential -- safe to send regardless of input
        # bytes; output is always [0-9a-f]{40}.
        return {"api-secret": _sha1_api_secret(self._credential)}

    def _v3_headers(self) -> dict[str, str]:
        # Reject control bytes in the credential before interpolating
        # into the header. h11's LocalProtocolError quotes the entire
        # offending header value (including the credential!) into its
        # message, which then flows through NightscoutNetworkError ->
        # ConnectionTestOutcome.error -> last_sync_error in the DB.
        # Sanitize at the source.
        if any(ord(c) < 0x20 or ord(c) == 0x7F for c in self._credential):
            raise NightscoutValidationError(
                "v3 token contains control characters; check for stray "
                "newlines or whitespace from copy-paste"
            )
        return {"Authorization": f"Bearer {self._credential}"}

    # -- low-level request with retry --------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        """Issue a single HTTP request with retry/backoff on 429 and 5xx."""
        if self._client is None:
            self._open()
        # Plain check (not assert -- assert is stripped under -O).
        if self._client is None:
            raise RuntimeError("NightscoutClient was closed")
        client = self._client

        attempts_429 = 0
        attempts_5xx = 0

        while True:
            try:
                resp = await client.request(
                    method,
                    path,
                    params=params,
                    headers=headers,
                    timeout=timeout,
                )
            except httpx.HTTPError as exc:
                # Transport-level errors are not retried at this layer
                # -- the scheduler retries at the connection level on
                # the next sync interval.
                #
                # Defense in depth: scrub the credential out of error
                # strings before they reach NightscoutNetworkError.
                # h11's LocalProtocolError, in particular, includes
                # the offending header value (which can be the bearer
                # token) in its message. We already validate v3
                # tokens for control bytes in `_v3_headers`, but a
                # future header-level surface should not regress the
                # invariant. `from None` breaks the exception chain
                # so the original `exc.args` are not preserved on
                # the traceback either.
                msg = str(exc).replace(self._credential, "<redacted>")
                raise NightscoutNetworkError(msg) from None

            if resp.status_code == 429:
                retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
                if attempts_429 >= MAX_RETRIES_429:
                    raise NightscoutRateLimitError(
                        "Nightscout rate limit exceeded after retries",
                        retry_after_seconds=retry_after,
                    )
                # Honor server's Retry-After when present, but clamp
                # to a sane ceiling so a hostile/misconfigured server
                # can't pin us for hours. Fall back to exponential
                # backoff with jitter otherwise.
                if retry_after is not None:
                    delay = min(retry_after, RETRY_AFTER_CAP_SECONDS)
                else:
                    delay = _backoff_delay(attempts_429)
                attempts_429 += 1
                logger.info(
                    "nightscout_429_backoff",
                    extra={
                        "attempt": attempts_429,
                        "delay": delay,
                        "request_path": path,
                        "honored_retry_after": retry_after is not None,
                    },
                )
                await asyncio.sleep(delay)
                continue

            if 500 <= resp.status_code < 600:
                if attempts_5xx >= MAX_RETRIES_5XX:
                    raise NightscoutServerError(
                        f"Nightscout server returned {resp.status_code}",
                        status_code=resp.status_code,
                    )
                attempts_5xx += 1
                await asyncio.sleep(_backoff_delay(attempts_5xx))
                continue

            return resp

    def _raise_for_auth_or_404(self, resp: httpx.Response, *, what: str) -> None:
        if resp.status_code in (401, 403):
            raise NightscoutAuthError(
                f"Authentication rejected for {what}",
                status_code=resp.status_code,
            )
        if resp.status_code == 404:
            raise NightscoutNotFoundError(
                f"{what} not found at this URL",
                status_code=resp.status_code,
            )

    # -- connection test ---------------------------------------------------

    async def test_connection(self) -> ConnectionTestOutcome:
        """Probe the instance to confirm the credential is accepted.

        Picks the API version per the resolution rules:
        - explicit api_version=v1 OR (auto + auth_type=secret) → v1 only
        - explicit api_version=v3 OR (auto + auth_type=token) → v3 only
        - otherwise (api_version=auto, auth_type=auto): try v1, fall
          back to v3 on 404.
        """
        try:
            if self._should_use_v1_only():
                return await self._test_v1()
            if self._should_use_v3_only():
                return await self._test_v3()

            # Pure auto (api_version=AUTO + auth_type=AUTO). v1 first
            # because it's universal across the install base. Fall
            # back to v3 in two cases:
            #   - v1 returns 404 (server doesn't speak v1 at all)
            #   - v1 auth fails (the credential might actually be a
            #     v3 token; the user said they didn't know which)
            v1 = await self._test_v1()
            if v1.ok:
                return v1
            v1_path_unsupported = (
                v1.api_version_detected is None and v1.error is not None
            )
            v1_auth_failed = (
                v1.api_version_detected == NightscoutApiVersion.V1
                and v1.auth_validated is False
            )
            if v1_path_unsupported or v1_auth_failed:
                v3 = await self._test_v3()
                if v3.ok:
                    return v3
                # Both failed -- prefer the more informative error.
                # If v3 reached the server (api_version_detected set)
                # it's a better failure to report than v1's.
                if v3.api_version_detected is not None:
                    return v3
            return v1
        except NightscoutValidationError as exc:
            return ConnectionTestOutcome(ok=False, error=str(exc))
        except NightscoutNetworkError as exc:
            return ConnectionTestOutcome(ok=False, error=f"network: {exc}")
        except NightscoutRateLimitError as exc:
            # _test_v3 doesn't catch rate-limit-exhaustion locally
            # (only _test_v1 does, for its server-error path); cover
            # it here so test_connection() always returns an outcome.
            return ConnectionTestOutcome(ok=False, error=f"rate limited: {exc}")
        except NightscoutServerError as exc:
            return ConnectionTestOutcome(ok=False, error=f"server error: {exc}")

    def _should_use_v1_only(self) -> bool:
        return self._api_version == NightscoutApiVersion.V1 or (
            self._api_version == NightscoutApiVersion.AUTO
            and self._auth_type == NightscoutAuthType.SECRET
        )

    def _should_use_v3_only(self) -> bool:
        return self._api_version == NightscoutApiVersion.V3 or (
            self._api_version == NightscoutApiVersion.AUTO
            and self._auth_type == NightscoutAuthType.TOKEN
        )

    async def _test_v1(self) -> ConnectionTestOutcome:
        try:
            resp = await self._request(
                "GET",
                "/api/v1/status.json",
                headers=self._v1_headers(),
                timeout=CONNECT_TEST_TIMEOUT_SECONDS,
            )
        except NightscoutServerError as exc:
            return ConnectionTestOutcome(
                ok=False, error=f"Nightscout server error: {exc}"
            )

        # Status-class handling. _request() only raises on 5xx (after
        # retries) and rate-limit-exhausted; 4xx flows through as a
        # response.
        if resp.status_code in (401, 403):
            return ConnectionTestOutcome(
                ok=False,
                api_version_detected=NightscoutApiVersion.V1,
                auth_validated=False,
                error="Authentication rejected by Nightscout v1 (bad API_SECRET?)",
            )
        if resp.status_code == 404:
            return ConnectionTestOutcome(
                ok=False, error="v1 status endpoint not found at this URL"
            )
        if resp.status_code != 200:
            return ConnectionTestOutcome(
                ok=False, error=f"Unexpected status {resp.status_code}"
            )
        body = _parse_json_or_none(resp)
        version = body.get("version") if isinstance(body, dict) else None
        # Cache the detected version for subsequent calls.
        self._effective_api_version = NightscoutApiVersion.V1
        return ConnectionTestOutcome(
            ok=True,
            server_version=version,
            api_version_detected=NightscoutApiVersion.V1,
            auth_validated=True,
        )

    async def _test_v3(self) -> ConnectionTestOutcome:
        # /api/v3/version is unauthenticated -- it tells us whether
        # the server speaks v3 at all but doesn't validate the token.
        # We follow with a /api/v3/status call (or any authenticated
        # endpoint) to validate the token.
        ver_resp = await self._request(
            "GET", "/api/v3/version", timeout=CONNECT_TEST_TIMEOUT_SECONDS
        )
        if ver_resp.status_code == 404:
            return ConnectionTestOutcome(
                ok=False, error="v3 version endpoint not found at this URL"
            )
        if ver_resp.status_code != 200:
            return ConnectionTestOutcome(
                ok=False, error=f"v3 version returned status {ver_resp.status_code}"
            )

        # Now hit a token-protected endpoint to validate auth.
        status_resp = await self._request(
            "GET",
            "/api/v3/status",
            headers=self._v3_headers(),
            timeout=CONNECT_TEST_TIMEOUT_SECONDS,
        )
        if status_resp.status_code in (401, 403):
            return ConnectionTestOutcome(
                ok=False,
                api_version_detected=NightscoutApiVersion.V3,
                auth_validated=False,
                error="Authentication rejected by Nightscout v3 (bad token?)",
            )
        if status_resp.status_code == 404:
            return ConnectionTestOutcome(ok=False, error="v3 status endpoint not found")

        # Real Nightscout v3 returns
        # {"status": 200, "version": "15.0.8", "apiVersion": "3.0.5", ...}
        # -- there is no `result` envelope. (Verified against
        # cgm-remote-monitor 15.0.8 running locally during development.)
        body = _parse_json_or_none(ver_resp)
        version = body.get("version") if isinstance(body, dict) else None
        self._effective_api_version = NightscoutApiVersion.V3
        return ConnectionTestOutcome(
            ok=True,
            server_version=version,
            api_version_detected=NightscoutApiVersion.V3,
            auth_validated=True,
        )

    # -- data fetches (v1 paths; v3 wrappers can come later) ---------------

    def _require_v1_for_fetch(self, what: str) -> None:
        """Guard for fetch methods.

        v3 data fetches (with their different pagination + endpoint
        shape) are out of scope for this PR. Story 43.4's background
        sync drives the v1 path; if/when the project sees a v3-only
        Nightscout user, add v3 endpoints here in a follow-up.

        Failing loudly with NotImplementedError is preferable to
        silently sending v1 paths with a v3 token (the previous
        behavior of this code).
        """
        # `_effective_api_version` is seeded from `_api_version`
        # whenever the latter isn't AUTO, so checking the effective
        # value alone covers both explicit-v3 and auto-resolved-to-v3.
        if self._effective_api_version == NightscoutApiVersion.V3:
            raise NotImplementedError(
                f"v3 {what} fetches are not yet implemented. Use api_version=v1 "
                "or wait for v3 fetch support to land."
            )

    async def fetch_entries(
        self,
        *,
        since: datetime | None = None,
        count: int = DEFAULT_PAGE_SIZE,
    ) -> list[dict[str, Any]]:
        """Fetch CGM entries newest-first.

        Args:
            since: only return entries with dateString >= this UTC
                timestamp. **Must be timezone-aware** (raises ValueError
                on naive datetimes -- silently treating naive as UTC
                corrupted wall-clock data on dev machines outside UTC).
                None = no lower bound (subject to Nightscout's
                own retention).
            count: page size. Server caps at ~50000 silently.
        """
        self._require_v1_for_fetch("entries")
        return await self._fetch_v1_collection(
            "/api/v1/entries.json",
            since=since,
            since_field="dateString",
            count=count,
        )

    async def fetch_treatments(
        self,
        *,
        since: datetime | None = None,
        count: int = DEFAULT_PAGE_SIZE,
    ) -> list[dict[str, Any]]:
        self._require_v1_for_fetch("treatments")
        return await self._fetch_v1_collection(
            "/api/v1/treatments.json",
            since=since,
            since_field="created_at",
            count=count,
        )

    async def fetch_devicestatus(
        self,
        *,
        since: datetime | None = None,
        count: int = DEFAULT_PAGE_SIZE,
    ) -> list[dict[str, Any]]:
        self._require_v1_for_fetch("devicestatus")
        return await self._fetch_v1_collection(
            "/api/v1/devicestatus.json",
            since=since,
            since_field="created_at",
            count=count,
        )

    async def fetch_profile(self) -> list[dict[str, Any]]:
        """Profile data is not paginated; returns the full profile list.

        Most Nightscout instances have one or two profiles total
        (Default + maybe a sleep / exercise variant). The profile
        endpoint returns everything; no since-filter is meaningful.
        """
        self._require_v1_for_fetch("profile")
        resp = await self._request(
            "GET", "/api/v1/profile.json", headers=self._v1_headers()
        )
        self._raise_for_auth_or_404(resp, what="profile")
        if resp.status_code != 200:
            raise NightscoutServerError(
                f"profile returned status {resp.status_code}",
                status_code=resp.status_code,
            )
        body = _parse_json_or_none(resp)
        return body if isinstance(body, list) else []

    async def _fetch_v1_collection(
        self,
        path: str,
        *,
        since: datetime | None,
        since_field: str,
        count: int,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"count": count}
        if since is not None:
            # Reject naive datetimes loudly. The previous behavior
            # ("treat as UTC") silently corrupted wall-clock data
            # when callers ran outside UTC.
            if since.tzinfo is None:
                raise ValueError(
                    "since must be a timezone-aware datetime "
                    "(use datetime.now(UTC) or attach tzinfo explicitly)"
                )
            since_utc = since.astimezone(UTC)
            params[f"find[{since_field}][$gte]"] = since_utc.isoformat().replace(
                "+00:00", "Z"
            )
        resp = await self._request(
            "GET", path, params=params, headers=self._v1_headers()
        )
        self._raise_for_auth_or_404(resp, what=path)
        if resp.status_code != 200:
            raise NightscoutServerError(
                f"{path} returned status {resp.status_code}",
                status_code=resp.status_code,
            )
        body = _parse_json_or_none(resp)
        return body if isinstance(body, list) else []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_PARSE_FAILED = object()  # sentinel distinct from None / [] / {}


def _parse_json_or_none(resp: httpx.Response) -> Any:
    """Parse a response as JSON; return None on empty body, sentinel on
    malformed.

    Distinguishing empty-body (status 204 / valid empty) from malformed
    JSON matters for diagnostics: callers want to know "server has no
    records" vs "server returned garbage." For now we keep the contract
    simple (return None for both, callers downcast to []), but the
    sentinel is plumbed for future expansion.
    """
    if not resp.content:
        return None
    try:
        return resp.json()
    except (ValueError, TypeError):
        # Don't log resp.text -- a malformed body could contain user
        # PII (glucose values, free-text "Notes" treatments, etc.)
        # that we don't want shipped to log aggregators. Status code
        # + length is enough to triage.
        logger.warning(
            "nightscout_response_parse_failed",
            extra={
                "status": resp.status_code,
                "content_length": len(resp.content),
            },
        )
        return _PARSE_FAILED


def _backoff_delay(attempt: int) -> float:
    """Exponential backoff with full jitter."""
    return RETRY_BASE_DELAY_SECONDS * (2**attempt) * (0.5 + random.random() / 2)


def _parse_retry_after(value: str | None) -> float | None:
    """Parse a Retry-After header as seconds.

    Returns None for missing, malformed, or negative values. The HTTP
    spec also allows an HTTP-date form, which we don't support; servers
    in the wild use the integer-seconds form.
    """
    if not value:
        return None
    try:
        parsed = float(value)
    except (ValueError, TypeError):
        return None
    if parsed < 0:
        return None
    return parsed
