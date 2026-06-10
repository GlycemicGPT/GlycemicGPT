"""CarePartner (Connect) Auth0 token handling -- the autonomous-renewal core.

The CarePartner mobile app uses a *public* Auth0 Native client (PKCE, no client
secret) with ``offline_access``, so a one-time interactive login yields a
client-held **refresh token** that the backend can renew server-side -- no
browser, no cookies. (This is precisely what the CareLink *web* flow could not
do; see the project memory.)

This module provides:
  - the per-region Auth0 config (client_id, audience, login host, cloud host);
  - ``refresh_access_token`` -- a single POST /oauth/token refresh-grant call;
  - ``ConnectTokenProvider`` -- a cached bearer provider for the data client
    that refreshes the short-lived access token on demand and surfaces the
    **rotated** refresh token via a persist callback (Auth0 rotating refresh
    tokens invalidate the old one, so each new refresh token MUST be stored).

Params are clean-room: fetched first-hand from Medtronic's own public discovery
+ SSO-config endpoints, not from any third-party library. Renewal + rotation
were verified live (access ``expires_in`` 10800s; refresh grant returns a new
access token AND rotates the refresh token).
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urlencode, urlparse

import httpx

from .connect_client import CLOUD_HOST_EU, CLOUD_HOST_US

#: Refresh the access token this many seconds before it actually expires, so an
#: in-flight data call never rides an about-to-expire bearer.
_EXPIRY_SKEW_SECONDS = 120

#: Auth0 login hosts must stay within Medtronic's domains (SSRF guard -- the
#: refresh token is POSTed here).
_ALLOWED_AUTH_HOST_SUFFIXES = ("minimed.com", "minimed.eu")

#: Scope requested on login; offline_access is what yields the refresh token.
_SCOPE = "profile openid offline_access"

#: Custom-scheme redirect the CarePartner app registers. The browser cannot
#: follow it, which is exactly why the user copies the blocked redirect URL.
_REDIRECT_URI = "com.medtronic.carepartner:/sso"


@dataclass(frozen=True)
class ConnectRegion:
    """Per-region CarePartner Auth0 + cloud configuration."""

    key: str
    auth_host: str  # Auth0 tenant login host
    client_id: str
    audience: str
    cloud_host: str  # CarePartner data cloud (clcloud.minimed.*)
    redirect_uri: str = _REDIRECT_URI


# Both US and EU/OUS use Auth0 (verified live from Medtronic's discovery +
# SSO-config JSONs at carelink.minimed.{com,eu}/configs/v1/carepartner_auth0_*).
# A `Layer7SSOConfiguration` (MAG) also appears in the discovery but is the
# LEGACY path; both regions currently set `UseSSOConfiguration: Auth0`.
# The only differences between regions are client_id, audience, auth host, and
# cloud host -- everything else (PKCE flow, redirect_uri, scope) is identical.
#
# EU covers all non-US CarePartner countries: UK (`GB`), EU member states,
# Australia, South Africa, etc. -- per Medtronic's `supportedCountries` they
# all share this one OUS Auth0 tenant.
_REGION_US = ConnectRegion(
    key="US",
    auth_host="carelink-login.minimed.com",
    client_id="0FGoNwY0SP8ZmESYSfEOgMw03c58c1hk",
    audience="carepartner.patient.us",
    cloud_host=CLOUD_HOST_US,
)
_REGION_EU = ConnectRegion(
    key="EU",
    auth_host="carelink-login.minimed.eu",
    client_id="PeAhkbhQWlQRxJiQxWfcFBiGus1lxfe9",
    audience="carepartner.patient.ous",
    cloud_host=CLOUD_HOST_EU,
)

REGIONS: dict[str, ConnectRegion] = {"US": _REGION_US, "EU": _REGION_EU}


def get_region(region: str) -> ConnectRegion:
    """Look up a region config by key (case-insensitive). Raises ValueError."""
    try:
        return REGIONS[(region or "").strip().upper()]
    except KeyError:
        raise ValueError(
            f"Unknown CarePartner region {region!r}; known: {sorted(REGIONS)}"
        ) from None


class ConnectTokenError(Exception):
    """The refresh grant failed -- the refresh token is invalid/expired/revoked.

    Recovery is a fresh interactive login (the refresh token has a finite life,
    ~1 week, and rotation means a stale one is permanently dead)."""


@dataclass
class TokenResponse:
    access_token: str
    expires_in: int
    #: The refresh token to persist for next time. With Auth0 rotation this is a
    #: NEW value; if the server did not rotate, it falls back to the one sent.
    refresh_token: str


async def refresh_access_token(
    region: ConnectRegion,
    refresh_token: str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout_seconds: float = 30.0,
) -> TokenResponse:
    """Exchange a refresh token for a fresh access token (Auth0 refresh grant).

    Public/PKCE client -> no client secret. Returns the new access token and the
    (rotated) refresh token to persist.

    .. warning::
       Auth0 ROTATES the refresh token on every call. The returned
       ``refresh_token`` **MUST be persisted** before the next refresh, or the
       chain dies (Auth0 marks the spent token dead and the next refresh with
       the stale token returns 403 ``invalid_grant``, forcing a full re-login).
       The ``ConnectTokenProvider.on_rotate`` callback + the orchestrator's
       ``_persist_rotated`` hook handle this in the normal flow. **DO NOT call
       this function from one-off scripts/tests against the live DB token
       without persisting the rotation** -- doing so silently bricks the chain.
       For diagnostics, use the orchestrator (``sync_connect_for_user``) which
       persists on every cycle.
    """
    _assert_auth_host(region)
    if not refresh_token:
        raise ConnectTokenError("No refresh token available; re-login required")

    owns = client is None
    http = client or httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds))
    try:
        resp = await http.post(
            f"https://{region.auth_host}/oauth/token",
            json={
                "grant_type": "refresh_token",
                "client_id": region.client_id,
                "refresh_token": refresh_token,
                "scope": _SCOPE,
            },
            headers={"Accept": "application/json"},
        )
    except httpx.HTTPError as e:
        raise ConnectTokenError(f"Network error during token refresh: {e}") from e
    finally:
        if owns:
            await http.aclose()

    if resp.status_code in (400, 401, 403):
        # Auth0 returns 4xx (invalid_grant) for a dead/rotated refresh token.
        raise ConnectTokenError(
            f"Refresh token rejected ({resp.status_code}); re-login required"
        )
    if resp.status_code >= 400:
        raise ConnectTokenError(f"Token endpoint error {resp.status_code}")

    try:
        data = resp.json()
    except ValueError as e:
        raise ConnectTokenError("Token endpoint returned non-JSON") from e
    access = data.get("access_token")
    if not access:
        raise ConnectTokenError("Token response missing access_token")
    return TokenResponse(
        access_token=access,
        expires_in=int(data.get("expires_in") or 0),
        # Rotation: persist the new refresh token; fall back to the old one if
        # the server chose not to rotate on this call.
        refresh_token=data.get("refresh_token") or refresh_token,
    )


def _assert_auth_host(region: ConnectRegion) -> None:
    host = (urlparse("https://" + region.auth_host).hostname or "").lower()
    if not any(
        host == s or host.endswith("." + s) for s in _ALLOWED_AUTH_HOST_SUFFIXES
    ):
        raise ValueError(f"Refusing token request to untrusted auth host {host!r}")


def generate_pkce() -> tuple[str, str]:
    """Return ``(code_verifier, code_challenge)`` for an S256 PKCE exchange."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_authorize_url(
    region: ConnectRegion, *, code_challenge: str, state: str
) -> str:
    """Build the Auth0 ``/authorize`` URL for the one-time CarePartner login.

    The user opens this, logs in + solves the captcha; Auth0 redirects to the
    custom-scheme ``redirect_uri`` (which the browser cannot follow) carrying
    the ``code`` that ``exchange_code_for_tokens`` then spends.
    """
    query = urlencode(
        {
            "client_id": region.client_id,
            "redirect_uri": region.redirect_uri,
            "audience": region.audience,
            "scope": _SCOPE,
            "response_type": "code",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state,
        }
    )
    return f"https://{region.auth_host}/authorize?{query}"


async def exchange_code_for_tokens(
    region: ConnectRegion,
    code: str,
    code_verifier: str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout_seconds: float = 30.0,
) -> TokenResponse:
    """Exchange an authorization ``code`` + PKCE verifier for tokens.

    Public/PKCE client -> no client secret. Returns the access token and the
    refresh token to persist for autonomous renewal.
    """
    _assert_auth_host(region)
    if not code or not code_verifier:
        raise ConnectTokenError("Missing authorization code or verifier")

    owns = client is None
    http = client or httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds))
    try:
        resp = await http.post(
            f"https://{region.auth_host}/oauth/token",
            json={
                "grant_type": "authorization_code",
                "client_id": region.client_id,
                "code": code,
                "code_verifier": code_verifier,
                "redirect_uri": region.redirect_uri,
            },
            headers={"Accept": "application/json"},
        )
    except httpx.HTTPError as e:
        raise ConnectTokenError(f"Network error during code exchange: {e}") from e
    finally:
        if owns:
            await http.aclose()

    if resp.status_code in (400, 401, 403):
        raise ConnectTokenError(
            f"Authorization code rejected ({resp.status_code}); re-login required"
        )
    if resp.status_code >= 400:
        raise ConnectTokenError(f"Token endpoint error {resp.status_code}")

    try:
        data = resp.json()
    except ValueError as e:
        raise ConnectTokenError("Token endpoint returned non-JSON") from e
    access = data.get("access_token")
    refresh = data.get("refresh_token")
    if not access:
        raise ConnectTokenError("Token response missing access_token")
    if not refresh:
        # No refresh token => offline_access wasn't granted => autonomous sync
        # is impossible. Fail loudly rather than store an unusable connection.
        raise ConnectTokenError("Token response missing refresh_token")
    return TokenResponse(
        access_token=access,
        expires_in=int(data.get("expires_in") or 0),
        refresh_token=refresh,
    )


PersistCallback = Callable[[str], Awaitable[None]]


class ConnectTokenProvider:
    """A cached bearer provider for ``CareLinkConnectClient``.

    Holds the current refresh token, lazily fetches an access token, caches it
    until shortly before expiry, and (on rotation) hands the new refresh token
    to ``on_rotate`` so the caller can persist it.
    """

    def __init__(
        self,
        *,
        region: ConnectRegion,
        refresh_token: str,
        on_rotate: PersistCallback | None = None,
        client: httpx.AsyncClient | None = None,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._region = region
        self._refresh_token = refresh_token
        self._on_rotate = on_rotate
        self._client = client
        self._now = now
        self._access_token: str | None = None
        self._expires_at: float = 0.0

    @property
    def refresh_token(self) -> str:
        """The current (possibly rotated) refresh token to persist."""
        return self._refresh_token

    async def __call__(self) -> str:
        """Return a valid access token, refreshing if expired/near-expiry."""
        if self._access_token and self._now() < self._expires_at:
            return self._access_token
        token = await refresh_access_token(
            self._region, self._refresh_token, client=self._client
        )
        self._access_token = token.access_token
        self._expires_at = self._now() + max(0, token.expires_in - _EXPIRY_SKEW_SECONDS)
        if token.refresh_token != self._refresh_token:
            self._refresh_token = token.refresh_token
            if self._on_rotate is not None:
                await self._on_rotate(token.refresh_token)
        return self._access_token
