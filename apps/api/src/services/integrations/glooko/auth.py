"""Glooko web-session authentication (clean-room).

The Glooko personal account authenticates through its **web app** (a Rails
Devise form login), NOT the mobile ``POST /api/v2/users/sign_in`` endpoint --
that one authenticates the credentials but then 422s for web-only accounts
(no completed mobile-device registration). This was confirmed first-hand from a
live capture.

Working flow (reproduced headlessly here, no browser -- happy path only; no
CAPTCHA/MFA was observed in the personal flow, but headless-login durability is the
one open productionization risk):

    1. GET  {web_host}/users/sign_in            -> pre-auth session cookie + CSRF <meta>
    2. POST {web_host}/users/sign_in?id=login_form  (form-urlencoded:
           authenticity_token, user[email], user[password], commit, language, redirect_to)
       -> 302; rotates `_logbook-web_session` to an AUTHENTICATED cookie (domain .glooko.com)
    3. GET  {api_host}/api/v3/session/users      -> confirms the session + yields the
           patient slug (the param all data calls key on).

The resulting ``_logbook-web_session`` cookie (domain ``.glooko.com``) is replayed
by ``GlookoClient`` on the region API host. There is no reliable session TTL from a
single capture window, so we treat a later data-call 401 as "expired, re-login".

EU sub-cluster routing (live finding, German account): the EU login POST 302s to a
COUNTRY SUB-CLUSTER web host (e.g. ``de-fr.my.glooko.com``), and the ``eu.*`` /
apex API hosts then reject every session/data call with ``421 Misdirected
Request``. The working API host mirrors the sub-cluster web host
(``de-fr.api.glooko.com``). So after login we derive the API host from the final
post-redirect web host (``<cluster>.my.glooko.com`` -> ``<cluster>.api.glooko.com``
-- a rule the US hosts also satisfy) and carry it on the session; the static
region map is only the fallback when no redirect occurs.

Clean-room attribution: the endpoint paths and form fields were observed
first-hand from a live capture, not copied from the AGPL-3.0
``nightscout-connect`` / ``jpollock`` Glooko sources.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

from .errors import GlookoAuthError, GlookoNetworkError

#: The Devise session cookie (domain ``.glooko.com``, so it spans both the web
#: and API hosts). This is the single credential replayed on data calls.
SESSION_COOKIE_NAME = "_logbook-web_session"

_SIGN_IN_PAGE_PATH = "/users/sign_in"
_SIGN_IN_POST_PATH = "/users/sign_in?id=login_form"
_SESSION_USERS_PATH = "/api/v3/session/users"

#: SSRF guard: every Glooko host we talk to must live under glooko.com. ``region``
#: is operator-supplied (US/EU), so this bounds what a bad value can reach.
_ALLOWED_HOST_SUFFIX = "glooko.com"

_CSRF_META_RE = re.compile(
    r'<meta[^>]*name="csrf-token"[^>]*content="([^"]+)"', re.IGNORECASE
)

_DEFAULT_TIMEOUT = 40.0


@dataclass(frozen=True)
class GlookoRegion:
    """Per-region Glooko hosts."""

    key: str
    web_host: str  # e.g. https://us.my.glooko.com (Devise login)
    api_host: str  # e.g. https://us.api.glooko.com (data + session)


# Region API/web clusters are REGION-PREFIXED (live finding -- the apex
# ``api.glooko.com`` is not the per-account host and 422s). The EU entry is the
# LOGIN router only: EU accounts are re-homed to a country sub-cluster by the
# login redirect (see module docstring), so the EU api_host here is just the
# fallback for the no-redirect case.
REGIONS: dict[str, GlookoRegion] = {
    "US": GlookoRegion("US", "https://us.my.glooko.com", "https://us.api.glooko.com"),
    "EU": GlookoRegion("EU", "https://eu.my.glooko.com", "https://eu.api.glooko.com"),
}


def validate_glooko_host(url: str) -> str:
    """SSRF-validate that ``url``'s host lives under ``glooko.com``; returns ``url``.

    Raises ``ValueError`` on anything else -- same posture as ``resolve_region``
    (a bad host is a config/programming error, not a runtime auth failure).
    """
    name = (urlparse(url).hostname or "").lower()
    if not (name == _ALLOWED_HOST_SUFFIX or name.endswith("." + _ALLOWED_HOST_SUFFIX)):
        raise ValueError(
            f"Refusing Glooko host {name!r} outside {_ALLOWED_HOST_SUFFIX}"
        )
    return url


#: Post-login web hosts look like ``<cluster>.my.glooko.com`` (``us``, ``eu``,
#: ``de-fr``, ...). The matching data host swaps the ``my`` label for ``api``.
_CLUSTER_WEB_HOST_RE = re.compile(
    r"^(?P<cluster>[a-z0-9-]+)\.my\.glooko\.com$", re.IGNORECASE
)


def derive_api_host(web_url: str) -> str | None:
    """Map a (post-redirect) web URL to its cluster API host, or ``None``.

    ``https://de-fr.my.glooko.com/...`` -> ``https://de-fr.api.glooko.com``.
    Returns ``None`` when the host doesn't match the known web-host shape (the
    caller falls back to the static region map) -- which also means a redirect
    pointing outside ``*.my.glooko.com`` can never steer data calls anywhere
    unexpected.
    """
    name = (urlparse(web_url).hostname or "").lower()
    m = _CLUSTER_WEB_HOST_RE.match(name)
    if m is None:
        return None
    return f"https://{m.group('cluster').lower()}.api.glooko.com"


def resolve_region(region: str) -> GlookoRegion:
    """Resolve + SSRF-validate a region. Raises ``ValueError`` on a bad region/host.

    A misconfigured region or an out-of-allowlist host is a programming/config
    error, NOT a runtime auth failure -- so it raises ``ValueError`` (matching the
    Medtronic sibling) rather than ``GlookoAuthError``, so the orchestrator does
    not mistake it for an expired session to re-auth.
    """
    reg = REGIONS.get((region or "").upper())
    if reg is None:
        raise ValueError(
            f"Unknown Glooko region {region!r}; expected one of {sorted(REGIONS)}"
        )
    for host in (reg.web_host, reg.api_host):
        validate_glooko_host(host)
    return reg


@dataclass
class GlookoSession:
    """An authenticated Glooko web session, replayable on the region API host.

    Carries the cookie jar (so a fresh client can replay it), the region key, and
    the discovered patient identifiers. Model-agnostic -- the sync orchestrator
    persists the relevant bits onto ``GlookoSyncState``.
    """

    region: str
    cookies: dict[str, str]
    patient_slug: str | None = None
    patient_oid: str | None = None
    #: Cluster API host resolved from the post-login redirect (EU accounts are
    #: re-homed to country sub-clusters, e.g. ``https://de-fr.api.glooko.com``).
    #: ``None`` -> the static region api_host applies.
    api_host: str | None = None
    created_at: float = field(default_factory=time.time)

    @property
    def is_authenticated(self) -> bool:
        return bool(self.cookies.get(SESSION_COOKIE_NAME))


def _extract_csrf(html: str) -> str:
    m = _CSRF_META_RE.search(html or "")
    return m.group(1) if m else ""


_OID_RE = re.compile(r"^[0-9a-f]{24}$")


def _extract_patient_ids(body: object) -> tuple[str | None, str | None]:
    """Extract (patient_slug, patient_oid) from the ``/api/v3/session/users`` payload.

    The live capture showed the slug under ``currentPatient.glookoCode`` and a
    Mongo OID under ``currentPatient.id`` -- parse that known shape directly. As a
    defensive fallback (the session shape is upstream-``Experimental`` and may carry
    the patient under a different wrapper), scan the top-level dict values one level
    deep for a ``glookoCode`` -- but do NOT deep-walk for an arbitrary 24-hex ``id``,
    which risked grabbing an unrelated OID.
    """
    if not isinstance(body, dict):
        return None, None

    def _from_patient(obj: object) -> tuple[str | None, str | None]:
        if not isinstance(obj, dict):
            return None, None
        slug = obj.get("glookoCode")
        oid = obj.get("id")
        slug = slug if isinstance(slug, str) and slug else None
        oid = oid if isinstance(oid, str) and _OID_RE.match(oid) else None
        return slug, oid

    slug, oid = _from_patient(body.get("currentPatient"))
    if slug is None:
        # Fallback: the patient block may sit under a differently-named wrapper.
        for value in body.values():
            cand_slug, cand_oid = _from_patient(value)
            if cand_slug:
                slug, oid = cand_slug, oid or cand_oid
                break
    return slug, oid


async def glooko_login(
    email: str,
    password: str,
    region: str = "US",
    *,
    client: httpx.AsyncClient | None = None,
) -> GlookoSession:
    """Log in via the Glooko web Devise flow and return an authenticated session.

    Takes credentials as arguments (no DB coupling) so it is unit-testable and
    the sync orchestrator can wire it to decrypted ``GlookoSyncState`` creds.

    Raises ``GlookoAuthError`` on bad credentials / unconfirmed session, and
    ``GlookoNetworkError`` on transport failures.
    """
    if not email or not password:
        raise GlookoAuthError("email and password are required")
    reg = resolve_region(region)
    owns_client = client is None
    # One client across the 3 calls so the Devise session cookie persists between
    # the CSRF GET, the login POST, and the session verification.
    http = client or httpx.AsyncClient(
        timeout=httpx.Timeout(_DEFAULT_TIMEOUT), follow_redirects=True
    )
    try:
        try:
            page = await http.get(
                reg.web_host + _SIGN_IN_PAGE_PATH,
                headers={"Accept": "text/html"},
            )
            # A failed sign-in PAGE fetch (5xx) or a page that doesn't expose the
            # CSRF token is a transient/protocol problem, NOT bad credentials --
            # surfacing it as a network error keeps a valid connection from being
            # marked disconnected on a Glooko outage.
            if 500 <= page.status_code < 600:
                raise GlookoNetworkError(
                    f"Glooko sign-in page server error ({page.status_code})"
                )
            token = _extract_csrf(page.text)
            if not token:
                raise GlookoNetworkError(
                    "Glooko sign-in page did not expose a CSRF token"
                )
            login = await http.post(
                reg.web_host + _SIGN_IN_POST_PATH,
                data={
                    "authenticity_token": token,
                    "user[email]": email,
                    "user[password]": password,
                    "commit": "Log In",
                    "language": "en",
                    "redirect_to": "",
                },
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Origin": reg.web_host,
                },
            )
            if 500 <= login.status_code < 600:
                raise GlookoNetworkError(
                    f"Glooko login server error ({login.status_code})"
                )
            # The login may re-home the account to a country sub-cluster
            # (eu.my -> de-fr.my, observed live); the data host must follow,
            # or every call below 421s. With redirects followed, ``login.url``
            # is the final web URL; with an injected no-redirect client, fall
            # back to the Location header. Unknown host shapes -> region default.
            final_web_url = str(login.url)
            if login.is_redirect:
                final_web_url = login.headers.get("location") or final_web_url
            api_host = derive_api_host(final_web_url) or reg.api_host
            # The session-users call is the authoritative success oracle: a
            # pre-auth `_logbook-web_session` cookie exists even before login, so
            # cookie-presence alone is not proof. 401 here == bad credentials.
            verify = await http.get(
                api_host + _SESSION_USERS_PATH,
                headers={"Accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise GlookoNetworkError(
                f"Glooko login network error ({reg.key}): {type(exc).__name__}: {exc or '<no message>'}"
            ) from exc

        if verify.status_code in (401, 403):
            raise GlookoAuthError("Glooko login rejected -- check email/password")
        if 500 <= verify.status_code < 600:
            # A server-side error during the session check is transient, not an
            # auth failure -- the orchestrator should retry, not mark for re-auth.
            raise GlookoNetworkError(
                f"Glooko session check server error ({verify.status_code})"
            )
        if verify.status_code >= 400:
            raise GlookoAuthError(f"Glooko session check failed ({verify.status_code})")

        # Persist only the session cookie -- it is the single credential replayed on
        # data calls (its real domain is ``.glooko.com``, spanning web + API hosts).
        session_value = next(
            (
                c.value
                for c in http.cookies.jar
                if c.name == SESSION_COOKIE_NAME and c.value
            ),
            None,
        )
        if not session_value:
            raise GlookoAuthError("Glooko login did not yield a session cookie")

        try:
            slug, oid = _extract_patient_ids(verify.json())
        except ValueError:
            slug, oid = None, None
        return GlookoSession(
            region=reg.key,
            cookies={SESSION_COOKIE_NAME: session_value},
            patient_slug=slug,
            patient_oid=oid,
            api_host=api_host,
        )
    finally:
        if owns_client:
            await http.aclose()
