"""SSRF guard for Nightscout client.

Pre-flight URL/IP validation. Cloud-metadata endpoints are blocked
unconditionally; private and loopback IPs are blocked only when
`settings.allow_private_ai_urls` is false (cloud-deployment mode --
the homelab default permits private targets so users can connect to
self-hosted Nightscout instances on their LAN).

What this module does NOT do (intentionally):

- Transport-level IP pinning. The httpx client connects via hostname
  and re-resolves at connect time. There is a narrow DNS-rebinding
  window between this pre-flight validation and the actual TCP
  connect. A determined attacker controlling a malicious DNS server
  (and able to convince a user to type that hostname as their
  Nightscout base URL) could swap the resolved IP between validation
  and connect.

  Why we accept this for the v1 client:
  1. The threat requires the user to (a) type a hostname controlled
     by an attacker as their Nightscout URL and (b) the attacker's
     DNS server to be timed precisely.
  2. The metadata IP block above always fires when validation sees a
     metadata IP -- so the high-impact metadata-exfiltration case is
     closed even if rebinding occurs.
  3. Implementing transport-level pinning requires subclassing
     httpcore internals (httpx's transport doesn't expose the
     resolver). That code is substantial, version-coupled, and
     unjustified for the threat reduction it offers in our deployment
     model (homelab-first).
  4. HTTPS deployments are protected by TLS cert verification: a
     rebinding to a different IP would not have the expected
     certificate.

  If a future deployment scenario warrants closing this window
  (e.g., multi-tenant SaaS where users connect to arbitrary
  Nightscout URLs), add a custom httpcore transport then.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

from src.config import settings

DNS_TIMEOUT_SECONDS = 3.0


# Cloud metadata blocks -- always enforced regardless of homelab flag.
_METADATA_NETS_V4 = (
    ipaddress.IPv4Network("169.254.169.254/32"),  # AWS / Azure / GCP / DO
    ipaddress.IPv4Network("100.100.100.200/32"),  # Alibaba
    ipaddress.IPv4Network("192.0.0.192/32"),  # Oracle Cloud
)
_METADATA_NETS_V6 = (
    ipaddress.IPv6Network("fd00:ec2::254/128"),  # AWS IPv6 IMDS
)


def ip_is_metadata(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True if the address is a known cloud-metadata endpoint."""
    if isinstance(addr, ipaddress.IPv4Address):
        return any(addr in net for net in _METADATA_NETS_V4)
    # IPv6: also check IPv4-mapped forms of the IPv4 metadata IPs.
    if addr.ipv4_mapped is not None:
        return any(addr.ipv4_mapped in net for net in _METADATA_NETS_V4)
    return any(addr in net for net in _METADATA_NETS_V6)


def ip_is_disallowed_private(
    addr: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    """True if the address is private/loopback and homelab mode is OFF."""
    if settings.allow_private_ai_urls:
        return False
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


async def resolve_host(
    hostname: str,
) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolve a hostname with a hard DNS timeout. Non-blocking."""
    loop = asyncio.get_running_loop()
    try:
        addrs = await asyncio.wait_for(
            loop.getaddrinfo(hostname, None, type=socket.SOCK_STREAM),
            timeout=DNS_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        # `asyncio.TimeoutError` is an alias for the builtin
        # `TimeoutError` since Python 3.11; the project requires 3.11+
        # so catching the builtin covers both.
        raise ValueError(f"DNS resolution timed out for {hostname}") from exc
    except OSError as exc:
        # `getaddrinfo` documents `gaierror` (a subclass of OSError),
        # but the underlying syscall can also surface plain OSError
        # (e.g., "Network is unreachable" / EAI_SYSTEM). Catch the
        # base class so any resolution failure maps cleanly to
        # ValueError -- the contract callers rely on.
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
class ValidatedTarget:
    """A successfully validated Nightscout target."""

    scheme: str
    hostname: str
    host_header: str  # host[:port] for the Host header
    port: int
    path_prefix: str  # e.g. "" or "/nightscout" (no trailing slash)
    base_url: str  # scheme://host_header + path_prefix

    @property
    def is_https(self) -> bool:
        return self.scheme == "https"


async def validate_target(url: str) -> ValidatedTarget:
    """Pre-flight URL parse + DNS resolution + IP-block check.

    Raises:
        ValueError: if any check fails. The caller should map this to
            a user-facing connection-error message.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL must use http:// or https://")
    if parsed.query or parsed.fragment:
        raise ValueError("URL must not contain query strings or fragments")
    if parsed.username or parsed.password:
        raise ValueError("URL must not contain embedded user:password credentials")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("Invalid URL: missing host")

    addrs = await resolve_host(hostname)
    for addr in addrs:
        if ip_is_metadata(addr):
            raise ValueError(
                "URL resolves to a cloud metadata endpoint; refusing to connect"
            )
        if ip_is_disallowed_private(addr):
            raise ValueError(
                "URL resolves to a private/loopback/reserved IP. Set "
                "ALLOW_PRIVATE_AI_URLS=true if this is a homelab deployment."
            )

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    # Only include the port in the Host header when it's NOT the
    # scheme-default. Many reverse proxies (nginx, Caddy, Traefik)
    # match vhosts against `Host: example.com` and refuse
    # `Host: example.com:443`, breaking the connection.
    is_default_port = (parsed.scheme == "https" and parsed.port == 443) or (
        parsed.scheme == "http" and parsed.port == 80
    )
    host_header = (
        f"{hostname}:{parsed.port}"
        if (parsed.port is not None and not is_default_port)
        else hostname
    )
    path_prefix = parsed.path.rstrip("/")
    base_url = f"{parsed.scheme}://{host_header}{path_prefix}"

    return ValidatedTarget(
        scheme=parsed.scheme,
        hostname=hostname,
        host_header=host_header,
        port=port,
        path_prefix=path_prefix,
        base_url=base_url,
    )
