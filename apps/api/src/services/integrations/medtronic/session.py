"""CareLink session: a captured browser session + a self-refreshing bearer.

Spike-confirmed model (clean-room):
- The non-httpOnly ``auth_tmp_token`` cookie IS the bearer for ``/patient/*``.
- When it nears expiry (tracked by the ``c_token_valid_to`` cookie), a silent
  re-auth via ``GET /patient/sso/auth`` (following redirects, carrying the
  Auth0 session cookies) mints a fresh ``auth_tmp_token`` -- no captcha, no
  re-login, until the underlying Auth0 session itself expires.

The cookie bundle is captured once (the user completes the captcha login in a
real browser) and stored encrypted. ``CareLinkSession`` loads it into an httpx
cookie jar; ``bearer()`` returns a valid token (refreshing first if needed) and
is passed as the ``bearer_provider`` to :class:`CareLinkClient`. Share
``.http`` with the client so the jar's cookies ride along on /patient/* calls
too. After use, persist ``export_cookies()`` back to storage so a refreshed
token survives.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import unquote, urlparse

import httpx

from .client import US_BASE_URL, CareLinkAuthError, CareLinkError

_ALLOWED_HOST_SUFFIXES = ("minimed.com", "minimed.eu")
_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/145.0.0.0 Safari/537.36"
)
# Refresh this many seconds before the token's stated expiry, to avoid racing
# a request against expiry.
_REFRESH_SKEW_SECONDS = 60


def _validate_host(base_url: str) -> str:
    host = (urlparse(base_url).hostname or "").lower()
    if not any(host == s or host.endswith("." + s) for s in _ALLOWED_HOST_SUFFIXES):
        raise ValueError(
            f"Refusing CareLink base_url with untrusted host {host!r}; "
            f"allowed suffixes: {_ALLOWED_HOST_SUFFIXES}"
        )
    return host


class CareLinkSession:
    """A captured CareLink session that yields a refreshing bearer."""

    def __init__(
        self,
        *,
        cookies: list[dict],
        base_url: str = US_BASE_URL,
        http: httpx.AsyncClient | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._host = _validate_host(base_url)
        self._base_url = base_url.rstrip("/")
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(timeout=timeout_seconds)
        for c in cookies:
            self._http.cookies.set(
                c["name"],
                c["value"],
                domain=(c.get("domain") or "").lstrip("."),
                path=c.get("path") or "/",
            )
        # Source of truth for the bearer + its expiry. Tracked explicitly (not
        # re-read from the jar each time) because a refresh's Set-Cookie can
        # land under a leading-dot domain and coexist with the initially-loaded
        # one -- so refresh() resolves the freshest value into these.
        self._token = self._jar_value("auth_tmp_token")
        self._valid_raw = self._jar_value("c_token_valid_to")

    @property
    def http(self) -> httpx.AsyncClient:
        """The httpx client whose jar holds the session cookies. Share it with
        CareLinkClient so cookies ride along on /patient/* requests."""
        return self._http

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self) -> CareLinkSession:
        return self

    async def __aexit__(self, *_a: object) -> None:
        await self.aclose()

    def _jar_values(self, name: str) -> list[str]:
        """All host-matching values for a cookie name (a refresh can transiently
        leave a stale + fresh pair under different domain forms)."""
        return [
            c.value
            for c in self._http.cookies.jar
            if c.name == name and (c.domain or "").lstrip(".") == self._host
        ]

    def _jar_value(self, name: str) -> str | None:
        vs = self._jar_values(name)
        return vs[0] if vs else None

    def _valid_to(self) -> datetime | None:
        if not self._valid_raw:
            return None
        s = unquote(self._valid_raw).strip().strip('"')
        # Java-style: "Thu May 21 06:07:47 UTC 2026"
        try:
            return datetime.strptime(s, "%a %b %d %H:%M:%S UTC %Y").replace(tzinfo=UTC)
        except ValueError:
            return None

    def needs_refresh(self) -> bool:
        vt = self._valid_to()
        if vt is None:
            return True
        return datetime.now(UTC) >= vt - timedelta(seconds=_REFRESH_SKEW_SECONDS)

    async def refresh(self) -> None:
        """Silently re-auth via /patient/sso/auth, carrying the Auth0 session
        cookies, and resolve the freshest auth_tmp_token. Raises
        CareLinkAuthError if the session has expired (bounced to login).

        Does NOT pre-delete the token: when the session is still valid /sso/auth
        is a no-op (issues no new token), so deleting first would lose it. We
        instead pick a jar value different from the pre-refresh token (the newly
        issued one) and fall back to the existing token if none changed.
        """
        before = self._token
        try:
            resp = await self._http.get(
                f"{self._base_url}/patient/sso/auth",
                follow_redirects=True,
                headers={"User-Agent": _UA},
            )
        except httpx.HTTPError as e:
            raise CareLinkError(f"CareLink session refresh failed: {e}") from e
        final = (resp.url.path + " " + (resp.url.host or "")).lower()
        if "login" in final or resp.status_code >= 400:
            raise CareLinkAuthError(
                "CareLink session is no longer valid; reconnect required."
            )
        tokens = self._jar_values("auth_tmp_token")
        if tokens:
            self._token = next((t for t in tokens if t != before), tokens[-1])
        vts = self._jar_values("c_token_valid_to")
        if vts:
            self._valid_raw = next((v for v in vts if v != self._valid_raw), vts[-1])

    async def bearer(self) -> str:
        """Return a valid bearer (auth_tmp_token), refreshing first if needed.
        This is the ``bearer_provider`` for CareLinkClient."""
        if self.needs_refresh():
            await self.refresh()
        if not self._token:
            raise CareLinkAuthError(
                "No auth_tmp_token in the CareLink session; reconnect required."
            )
        return self._token

    def export_cookies(self) -> list[dict]:
        """Current cookies (incl. any refreshed values) for re-persisting the
        encrypted bundle to storage."""
        return [
            {"name": c.name, "value": c.value, "domain": c.domain, "path": c.path}
            for c in self._http.cookies.jar
        ]
