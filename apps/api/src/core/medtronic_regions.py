"""Medtronic CareLink regional hosts.

CareLink Personal is regionally split. ``US`` (carelink.minimed.com) is verified
live. ``EU``/international (carelink.minimed.eu) is built from the same pattern
but NOT yet verified against a real EU account -- the /patient REST surface +
auth flow are almost certainly identical (same Auth0 SPA), but treat EU as
"needs live verification by an EU user" until confirmed.

The base_url is host-allowlisted again in CareLinkClient/CareLinkSession, so a
bad value here fails closed rather than letting the bearer reach an arbitrary
host.
"""

from __future__ import annotations

#: Region code -> CareLink web host. Extend if Medtronic exposes more regional
#: hosts; keep values under minimed.com / minimed.eu (the client's allowlist).
MEDTRONIC_REGION_TO_BASE_URL: dict[str, str] = {
    "US": "https://carelink.minimed.com",
    "EU": "https://carelink.minimed.eu",
}

SUPPORTED_MEDTRONIC_REGIONS: frozenset[str] = frozenset(MEDTRONIC_REGION_TO_BASE_URL)


def resolve_region_base_url(region: str) -> str:
    """Map a region code to its CareLink base URL. Raises ValueError if the
    region is unknown (callers map that to HTTP 400)."""
    key = (region or "").strip().upper()
    try:
        return MEDTRONIC_REGION_TO_BASE_URL[key]
    except KeyError as e:
        raise ValueError(
            f"Unsupported Medtronic region {region!r}; "
            f"supported: {sorted(SUPPORTED_MEDTRONIC_REGIONS)}"
        ) from e
