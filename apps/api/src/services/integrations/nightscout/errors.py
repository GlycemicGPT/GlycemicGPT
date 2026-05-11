"""Typed exceptions for the Nightscout client.

Callers can switch on these to drive UI status (auth_failed → re-auth
prompt; rate_limited → backoff; etc.) without parsing string messages.
"""

from __future__ import annotations


class NightscoutError(Exception):
    """Base class for all Nightscout client errors."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class NightscoutValidationError(NightscoutError):
    """Pre-flight validation failed (bad URL, SSRF guard rejected, etc.).

    Maps to last_sync_status='error' in the connection model. Does not
    indicate a server-side problem -- the request never went out.
    """


class NightscoutAuthError(NightscoutError):
    """Server rejected the credential (401 or 403).

    Maps to last_sync_status='auth_failed'. Do not retry; surface a
    re-authenticate prompt to the user.
    """


class NightscoutNotFoundError(NightscoutError):
    """The endpoint or resource was not found (404).

    For auto-detect: a v1 endpoint 404 is the signal to fall back to
    v3 (or vice versa). For data fetches: indicates the user's NS
    instance does not expose the requested resource type.
    """


class NightscoutRateLimitError(NightscoutError):
    """Server signalled rate limiting (429).

    Caller (or background sync scheduler) should back off. The client
    handles short-term backoff itself; this error is raised when the
    backoff budget is exhausted.
    """

    def __init__(
        self, message: str, *, retry_after_seconds: float | None = None
    ) -> None:
        super().__init__(message, status_code=429)
        self.retry_after_seconds = retry_after_seconds


class NightscoutServerError(NightscoutError):
    """Server returned a 5xx after our retry budget was used."""


class NightscoutNetworkError(NightscoutError):
    """Transport-level failure (DNS, TCP, TLS, timeout). No status code.

    The remote may or may not be reachable; user-facing surface is
    "could not reach <host>." Caller can decide whether to retry.
    """
