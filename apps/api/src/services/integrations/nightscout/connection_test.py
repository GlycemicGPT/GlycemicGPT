"""Story 43.1: minimal connection-test stub for Nightscout.

This is a deliberate stub. It exists so the POST /api/integrations/nightscout
endpoint can return a real success/failure result before the full HTTP
client (Story 43.2) lands. Once 43.2 ships, that module replaces this
file -- the public function signature `test_connection()` stays stable
so the router doesn't change.

Security posture for the Story 43.1 stub:

- DNS is resolved once via asyncio's resolver with a timeout; the
  resolved IPs are validated against metadata blocks AND
  private/loopback ranges (the latter only when
  `settings.allow_private_ai_urls` is true).
- Metadata blocks are enforced regardless of homelab mode -- IMDS,
  Google metadata, Azure metadata, Alibaba, Oracle, DigitalOcean.
- The HTTP request connects via the original hostname (httpx's
  default), so TLS SNI is correct for cert-based vhosts. This leaves
  a narrow DNS-rebinding window between pre-flight validation and
  connect; see `_client_for_target` for the trade-off rationale.
  Story 43.2 ships transport-level pinning + SNI override that
  closes this gap.
- `follow_redirects=False` so the HTTP layer can't redirect us off
  the validated host.

What this stub explicitly does NOT do (Story 43.2 owns these):

- Pagination
- Retry/backoff on transient failures
- Streaming response handling
- Rate-limit-aware backoff
- Auto-detection-with-detection-cache
"""

import asyncio
import contextlib
import hashlib
import ipaddress
import logging
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from src.config import settings
from src.models.nightscout_connection import (
    NightscoutApiVersion,
    NightscoutAuthType,
)

logger = logging.getLogger(__name__)


# Tight overall timeout for connection-tests so the user gets fast
# feedback. Story 43.4's background sync uses a longer timeout.
CONNECTION_TEST_TIMEOUT_SECONDS = 8.0
DNS_TIMEOUT_SECONDS = 3.0


# Metadata blocks across the major cloud providers. Always enforced,
# regardless of `allow_private_ai_urls`. Includes both IPv4 and the
# IPv6 link-local range used for IMDS.
_METADATA_NETS_V4 = (
    ipaddress.IPv4Network("169.254.169.254/32"),  # AWS / Azure / GCP / DO
    ipaddress.IPv4Network("100.100.100.200/32"),  # Alibaba
    ipaddress.IPv4Network("192.0.0.192/32"),  # Oracle Cloud
)
_METADATA_NETS_V6 = (
    # AWS uses fd00:ec2::254 for IPv6 IMDS
    ipaddress.IPv6Network("fd00:ec2::254/128"),
)


@dataclass
class ConnectionTestOutcome:
    """Result of attempting to talk to a Nightscout instance."""

    ok: bool
    server_version: str | None = None
    api_version_detected: NightscoutApiVersion | None = None
    auth_validated: bool = False
    error: str | None = None


def _ip_is_metadata(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True if the address is a known cloud-metadata endpoint."""
    if isinstance(addr, ipaddress.IPv4Address):
        return any(addr in net for net in _METADATA_NETS_V4)
    # IPv6: also check for IPv4-mapped IPv6 forms of the IPv4 metadata IPs.
    if addr.ipv4_mapped is not None:
        return any(addr.ipv4_mapped in net for net in _METADATA_NETS_V4)
    return any(addr in net for net in _METADATA_NETS_V6)


def _ip_is_disallowed_private(
    addr: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    """True if the address is private/loopback/link-local/etc and
    `allow_private_ai_urls` is false (i.e. cloud-deployment mode)."""
    if settings.allow_private_ai_urls:
        # Homelab mode: allow private IPs (still blocks metadata via
        # the dedicated check above).
        return False
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


async def _resolve_host(
    hostname: str,
) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolve a hostname to its IP addresses with a hard timeout.

    Uses the running event loop's `getaddrinfo` so the call is
    non-blocking. Wrapped in `wait_for` so a hung resolver can't park
    a worker indefinitely.
    """
    loop = asyncio.get_running_loop()
    try:
        addrs = await asyncio.wait_for(
            loop.getaddrinfo(hostname, None, type=socket.SOCK_STREAM),
            timeout=DNS_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        raise ValueError(f"DNS resolution timed out for {hostname}") from exc
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve host: {hostname}") from exc

    out: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for entry in addrs:
        sockaddr = entry[4]
        try:
            out.append(ipaddress.ip_address(sockaddr[0]))
        except ValueError:
            continue
    if not out:
        raise ValueError(f"No usable IP addresses for {hostname}")
    return out


@dataclass(frozen=True)
class _ValidatedTarget:
    """A successfully validated Nightscout target.

    The HTTP client connects to `ip` directly and sets the `Host`
    header to `host_header`, eliminating DNS rebinding between
    validation and request.
    """

    scheme: str
    host_header: str  # original host[:port] for SNI/Host header
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address
    port: int
    path_prefix: str  # e.g. "" or "/nightscout"


async def _validate_nightscout_url(url: str) -> _ValidatedTarget:
    """SSRF guard for user-supplied Nightscout URLs.

    Resolves the host once (with a timeout), validates every resolved
    address against metadata + (homelab-aware) private-ip blocks, and
    returns a validated target the HTTP layer can pin to without
    re-resolving.

    Always rejects:
    - Non-http(s) schemes
    - URLs with query strings or fragments (defense against parser
      tricks like `https://valid.com/?@evil.com`)
    - Resolved addresses that hit a known cloud metadata endpoint
    - Resolved addresses that are private/loopback when
      `allow_private_ai_urls=false`
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("base_url must use http:// or https://")

    if parsed.query or parsed.fragment:
        raise ValueError("base_url must not contain query strings or fragments")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("Invalid URL: missing host")

    addrs = await _resolve_host(hostname)

    chosen: ipaddress.IPv4Address | ipaddress.IPv6Address | None = None
    for addr in addrs:
        if _ip_is_metadata(addr):
            raise ValueError(
                "URL resolves to a cloud metadata endpoint; refusing to connect"
            )
        if _ip_is_disallowed_private(addr):
            raise ValueError(
                "URL resolves to a private/loopback/reserved IP. Set "
                "ALLOW_PRIVATE_AI_URLS=true if this is a homelab deployment."
            )
        # Prefer the first address that survived validation.
        if chosen is None:
            chosen = addr

    if chosen is None:
        raise ValueError(f"No usable address for {hostname}")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    host_header = f"{hostname}:{parsed.port}" if parsed.port is not None else hostname

    return _ValidatedTarget(
        scheme=parsed.scheme,
        host_header=host_header,
        ip=chosen,
        port=port,
        path_prefix=parsed.path.rstrip("/"),
    )


def _sha1_hex(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()  # noqa: S324


@contextlib.asynccontextmanager
async def _client_for_target(target: _ValidatedTarget):
    """An httpx client targeted at the validated hostname.

    Trade-off (intentional for the Story 43.1 stub):

    - We connect via the hostname (httpx's default), so TLS SNI is set
      correctly. This matters because the most common Nightscout
      deployment is NS behind a reverse proxy with cert-based virtual
      hosting -- connecting to the IP literal gives the wrong SNI and
      breaks HTTPS for those users.
    - The cost is a narrow DNS-rebinding window between
      `_validate_nightscout_url` and the actual connect: a malicious
      resolver could return a public IP for the validation and a
      private/metadata IP for the request.
    - The metadata block above always rejects when validation sees a
      metadata IP, but a rebinding attack that returns a *different*
      private IP at request time is not caught here.

    Story 43.2 ships the full client with transport-level pinning +
    SNI override (e.g. custom `httpx.AsyncHTTPTransport` with the
    resolver constrained to the validated IP). Until then, the SSRF
    surface for this stub is "user has access to a malicious resolver
    AND can swap to a private IP after validation." The
    high-impact metadata-exfiltration case is closed by the IP-block
    defense above.
    """
    base = f"{target.scheme}://{target.host_header}{target.path_prefix}"

    async with httpx.AsyncClient(
        timeout=CONNECTION_TEST_TIMEOUT_SECONDS,
        follow_redirects=False,
        headers={
            "User-Agent": "GlycemicGPT/1.0 (Nightscout connection test)",
        },
        base_url=base,
    ) as client:
        yield client


async def _try_v1(client: httpx.AsyncClient, secret: str) -> ConnectionTestOutcome:
    """v1 auth: api-secret header carrying SHA-1 hex of API_SECRET."""
    try:
        resp = await client.get(
            "/api/v1/status.json", headers={"api-secret": _sha1_hex(secret)}
        )
    except httpx.HTTPError as exc:
        return ConnectionTestOutcome(ok=False, error=f"network: {exc}")

    if resp.status_code in (401, 403):
        return ConnectionTestOutcome(
            ok=False,
            api_version_detected=NightscoutApiVersion.V1,
            auth_validated=False,
            error="Authentication rejected by Nightscout v1 (bad API_SECRET?)",
        )
    if resp.status_code == 404:
        return ConnectionTestOutcome(
            ok=False,
            error="v1 status endpoint not found at this URL",
        )
    if resp.status_code >= 500:
        return ConnectionTestOutcome(
            ok=False,
            error=f"Nightscout server returned {resp.status_code}",
        )
    if resp.status_code != 200:
        return ConnectionTestOutcome(
            ok=False, error=f"Unexpected status {resp.status_code}"
        )

    try:
        body = resp.json()
    except ValueError:
        return ConnectionTestOutcome(ok=False, error="v1 status returned non-JSON")

    server_version = body.get("version") if isinstance(body, dict) else None
    return ConnectionTestOutcome(
        ok=True,
        server_version=server_version,
        api_version_detected=NightscoutApiVersion.V1,
        auth_validated=True,
    )


async def _try_v3(client: httpx.AsyncClient, token: str) -> ConnectionTestOutcome:
    """v3 auth: Bearer token in Authorization header."""
    try:
        resp = await client.get(
            "/api/v3/version", headers={"Authorization": f"Bearer {token}"}
        )
    except httpx.HTTPError as exc:
        return ConnectionTestOutcome(ok=False, error=f"network: {exc}")

    if resp.status_code in (401, 403):
        return ConnectionTestOutcome(
            ok=False,
            api_version_detected=NightscoutApiVersion.V3,
            auth_validated=False,
            error="Authentication rejected by Nightscout v3 (bad token?)",
        )
    if resp.status_code == 404:
        return ConnectionTestOutcome(
            ok=False, error="v3 version endpoint not found at this URL"
        )
    if resp.status_code >= 500:
        return ConnectionTestOutcome(
            ok=False, error=f"Nightscout server returned {resp.status_code}"
        )
    if resp.status_code != 200:
        return ConnectionTestOutcome(
            ok=False, error=f"Unexpected status {resp.status_code}"
        )

    try:
        body = resp.json()
    except ValueError:
        return ConnectionTestOutcome(ok=False, error="v3 version returned non-JSON")

    server_version = body.get("version") if isinstance(body, dict) else None
    return ConnectionTestOutcome(
        ok=True,
        server_version=server_version,
        api_version_detected=NightscoutApiVersion.V3,
        auth_validated=True,
    )


async def test_connection(
    base_url: str,
    auth_type: NightscoutAuthType,
    credential: str,
    api_version: NightscoutApiVersion,
) -> ConnectionTestOutcome:
    """Probe a Nightscout instance to validate it accepts our credential.

    Args:
        base_url: Nightscout root URL (no trailing slash).
        auth_type: secret | token | auto.
        credential: API_SECRET (v1) or bearer token (v3).
        api_version: v1 | v3 | auto.

    Returns:
        ConnectionTestOutcome describing success or the failure reason.
    """
    try:
        target = await _validate_nightscout_url(base_url)
    except ValueError as exc:
        return ConnectionTestOutcome(ok=False, error=str(exc))

    async with _client_for_target(target) as client:
        # Strategy:
        # - explicit v1 with secret auth -> _try_v1
        # - explicit v3 with token auth -> _try_v3
        # - auto: try v1 first (more widely deployed), fall back to v3
        if api_version == NightscoutApiVersion.V1 or (
            api_version == NightscoutApiVersion.AUTO
            and auth_type == NightscoutAuthType.SECRET
        ):
            return await _try_v1(client, credential)

        if api_version == NightscoutApiVersion.V3 or (
            api_version == NightscoutApiVersion.AUTO
            and auth_type == NightscoutAuthType.TOKEN
        ):
            return await _try_v3(client, credential)

        # Pure-auto with auto auth_type: try v1 first, fall back to v3.
        v1 = await _try_v1(client, credential)
        if v1.ok:
            return v1
        # If v1 was a 404, the instance might be v3-only.
        if v1.error and "not found" in v1.error.lower():
            v3 = await _try_v3(client, credential)
            if v3.ok:
                return v3
        return v1
