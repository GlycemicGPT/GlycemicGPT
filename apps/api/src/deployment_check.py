"""Deployment misconfiguration detection.

Surfaces the most common silent failure mode for self-hosters: the API
issues `Secure` session cookies (cookie_secure=True, the default), but
the platform is actually being served over plain HTTP from a non-localhost
address. Browsers refuse to store `Secure` cookies in that case, so login
appears to succeed (the API returns 200, logs say "logged in"), but the
session cookie is silently dropped and every navigation bounces back to
/login. Reported in production by a user on 2026-05-15.

`localhost` and `127.0.0.1` (and their IPv6 equivalent) are considered
"potentially trustworthy" per the W3C Secure Contexts spec, and browsers
DO honor Secure cookies for them even over HTTP — so we exclude them
from the warning to keep local development quiet.
"""

from urllib.parse import urlparse

from starlette.requests import Request

# Hosts that browsers treat as "potentially trustworthy" even over plain HTTP.
# See: https://w3c.github.io/webappsec-secure-contexts/#localhost
# Note: urlparse normalizes bracketed IPv6 ("[::1]") to bare form ("::1") for
# .hostname, so the bare form is the only one we need to match against.
_TRUSTWORTHY_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def is_secure_or_trustworthy_origin(origin: str) -> bool:
    """Return True if a Secure cookie issued for this origin would be stored.

    HTTPS origins always qualify. Plain-HTTP origins only qualify if the
    host is localhost/loopback. Non-http(s) schemes (ws://, file://,
    javascript:, ...) are reported as not-trustworthy by the caller; they
    don't belong in CORS_ORIGINS in the first place.
    """
    parsed = urlparse(origin)
    if parsed.scheme == "https":
        return True
    if parsed.scheme != "http":
        return False
    host = (parsed.hostname or "").lower()
    return host in _TRUSTWORTHY_HOSTS


def find_insecure_origins(origins: list[str]) -> list[str]:
    """Return any plain-HTTP non-localhost origins from the input list.

    Only `http://...` entries with non-localhost hosts are flagged. Origins
    with other schemes (`ws://`, `javascript:`, malformed input) are
    ignored — they may deserve their own warning, but they don't relate to
    the cookie-Secure failure mode this check exists for.
    """
    flagged: list[str] = []
    for origin in origins:
        parsed = urlparse(origin)
        if parsed.scheme != "http":
            continue
        host = (parsed.hostname or "").lower()
        if host not in _TRUSTWORTHY_HOSTS:
            flagged.append(origin)
    return flagged


def request_is_insecure_http(request: Request) -> bool:
    """Return True if this request was received over plain HTTP from a
    non-trustworthy host.

    Deliberately ignores the `X-Forwarded-Proto` request header — it's
    set by reverse proxies but is also trivially spoofable by a direct
    client. A correctly configured reverse-proxy deployment runs uvicorn
    with `--proxy-headers` (and `--forwarded-allow-ips`), which makes
    Starlette set `request.url.scheme` from the trusted header. So
    relying on `request.url.scheme` alone is both safe (no spoofing
    bypass) and accurate for any properly configured deployment.
    """
    if request.url.scheme == "https":
        return False
    host = (request.url.hostname or "").lower()
    return host not in _TRUSTWORTHY_HOSTS
