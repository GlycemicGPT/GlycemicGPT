"""Direct tests for the SSRF guard module.

Most of the SSRF behavior is also exercised end-to-end via
test_nightscout_connection.py's TestSsrfGuard class. This file
focuses on the pure-helper cases (URL parsing, host_header
construction) that don't need DNS mocks.
"""

from __future__ import annotations

import ipaddress
from unittest.mock import patch

import pytest

from src.services.integrations.nightscout import ssrf


@pytest.mark.asyncio
async def test_validate_target_strips_default_https_port():
    """https://example.com:443/ should produce host_header='example.com'
    (no :443) so reverse-proxied vhosts match correctly."""
    with patch.object(
        ssrf,
        "resolve_host",
        return_value=[ipaddress.IPv4Address("8.8.8.8")],
    ):
        target = await ssrf.validate_target("https://example.com:443/")
    assert target.host_header == "example.com"
    assert target.base_url == "https://example.com"


@pytest.mark.asyncio
async def test_validate_target_strips_default_http_port():
    with patch.object(
        ssrf,
        "resolve_host",
        return_value=[ipaddress.IPv4Address("8.8.8.8")],
    ):
        target = await ssrf.validate_target("http://example.com:80/")
    assert target.host_header == "example.com"


@pytest.mark.asyncio
async def test_validate_target_keeps_nondefault_port():
    """A non-default port (e.g. 1337) should be preserved in the
    Host header so requests reach the right virtual host."""
    with patch.object(
        ssrf,
        "resolve_host",
        return_value=[ipaddress.IPv4Address("8.8.8.8")],
    ):
        target = await ssrf.validate_target("http://example.com:1337/")
    assert target.host_header == "example.com:1337"
    assert target.port == 1337


@pytest.mark.asyncio
async def test_validate_target_preserves_path_prefix():
    """Some Nightscout deployments live at a sub-path
    (e.g. /nightscout). The validator must keep that intact."""
    with patch.object(
        ssrf,
        "resolve_host",
        return_value=[ipaddress.IPv4Address("8.8.8.8")],
    ):
        target = await ssrf.validate_target("https://example.com/nightscout")
    assert target.path_prefix == "/nightscout"
    assert target.base_url == "https://example.com/nightscout"


@pytest.mark.asyncio
async def test_validate_target_strips_trailing_slash():
    with patch.object(
        ssrf,
        "resolve_host",
        return_value=[ipaddress.IPv4Address("8.8.8.8")],
    ):
        target = await ssrf.validate_target("https://example.com/path/")
    assert target.path_prefix == "/path"


@pytest.mark.asyncio
async def test_validate_target_rejects_query_string():
    with pytest.raises(ValueError, match="query"):
        await ssrf.validate_target("https://example.com/?foo=bar")


@pytest.mark.asyncio
async def test_validate_target_rejects_fragment():
    with pytest.raises(ValueError, match="fragment"):
        await ssrf.validate_target("https://example.com/#hash")


@pytest.mark.asyncio
async def test_validate_target_rejects_embedded_creds():
    with pytest.raises(ValueError, match="user:password"):
        await ssrf.validate_target("https://user:pass@example.com")


@pytest.mark.asyncio
async def test_validate_target_rejects_non_http_scheme():
    with pytest.raises(ValueError, match="http"):
        await ssrf.validate_target("ftp://example.com")


@pytest.mark.asyncio
async def test_validate_target_rejects_missing_host():
    with pytest.raises(ValueError, match="host"):
        await ssrf.validate_target("https:///path")


def test_ip_is_metadata_aws_imds_v4():
    assert ssrf.ip_is_metadata(ipaddress.IPv4Address("169.254.169.254")) is True


def test_ip_is_metadata_alibaba():
    assert ssrf.ip_is_metadata(ipaddress.IPv4Address("100.100.100.200")) is True


def test_ip_is_metadata_oracle():
    assert ssrf.ip_is_metadata(ipaddress.IPv4Address("192.0.0.192")) is True


def test_ip_is_metadata_aws_ipv6():
    assert ssrf.ip_is_metadata(ipaddress.IPv6Address("fd00:ec2::254")) is True


def test_ip_is_metadata_ipv4_mapped_ipv6():
    """169.254.169.254 expressed as ::ffff:169.254.169.254 is still
    a metadata IP."""
    assert ssrf.ip_is_metadata(ipaddress.IPv6Address("::ffff:169.254.169.254")) is True


def test_ip_is_metadata_normal_ip():
    assert ssrf.ip_is_metadata(ipaddress.IPv4Address("8.8.8.8")) is False
    assert ssrf.ip_is_metadata(ipaddress.IPv6Address("2001:db8::1")) is False


def test_ip_is_disallowed_private_homelab_off():
    """When `allow_private_ai_urls=false`, private IPs are rejected."""
    with patch.object(ssrf.settings, "allow_private_ai_urls", False):
        assert ssrf.ip_is_disallowed_private(ipaddress.IPv4Address("10.0.0.1")) is True
        assert ssrf.ip_is_disallowed_private(ipaddress.IPv4Address("127.0.0.1")) is True
        assert ssrf.ip_is_disallowed_private(ipaddress.IPv4Address("8.8.8.8")) is False


def test_ip_is_disallowed_private_homelab_on():
    """When `allow_private_ai_urls=true`, private IPs are permitted
    (homelab default). Metadata IPs are still blocked separately."""
    with patch.object(ssrf.settings, "allow_private_ai_urls", True):
        assert ssrf.ip_is_disallowed_private(ipaddress.IPv4Address("10.0.0.1")) is False
        assert (
            ssrf.ip_is_disallowed_private(ipaddress.IPv4Address("127.0.0.1")) is False
        )
