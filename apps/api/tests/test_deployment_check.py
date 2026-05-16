"""Tests for the cookie-misconfig detection helpers."""

import pytest
from starlette.requests import Request

from src.deployment_check import (
    find_insecure_origins,
    is_secure_or_trustworthy_origin,
    request_is_insecure_http,
)


def _make_request(
    scheme: str,
    host: str,
    forwarded_proto: str | None = None,
) -> Request:
    """Build a minimal Starlette Request for the helper to inspect."""
    port = 80 if scheme == "http" else 443
    # IPv6 hosts must be bracketed in the Host header (RFC 3986 §3.2.2).
    host_header = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
    headers: list[tuple[bytes, bytes]] = [(b"host", host_header.encode())]
    if forwarded_proto is not None:
        headers.append((b"x-forwarded-proto", forwarded_proto.encode()))
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/auth/login",
        "scheme": scheme,
        "server": (host, port),
        "headers": headers,
        "query_string": b"",
    }
    return Request(scope)


class TestIsSecureOrTrustworthyOrigin:
    @pytest.mark.parametrize(
        "origin",
        [
            "https://app.example.com",
            "https://192.168.1.10",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://[::1]:3000",
        ],
    )
    def test_trustworthy(self, origin):
        assert is_secure_or_trustworthy_origin(origin) is True

    @pytest.mark.parametrize(
        "origin",
        [
            "http://192.168.1.10:3000",
            "http://10.20.66.40:3000",
            "http://glycemicgpt.local",
            "ws://example.com",
            "",
        ],
    )
    def test_not_trustworthy(self, origin):
        assert is_secure_or_trustworthy_origin(origin) is False


class TestFindInsecureOrigins:
    def test_flags_only_plain_http_non_localhost(self):
        # Order is preserved from the input; assert as a set so the
        # contract isn't over-specified beyond "these and only these".
        result = find_insecure_origins(
            [
                "http://localhost:3000",
                "https://app.example.com",
                "http://192.168.1.10:3000",
                "http://10.0.0.5:3000",
            ]
        )
        assert set(result) == {
            "http://192.168.1.10:3000",
            "http://10.0.0.5:3000",
        }

    def test_preserves_input_order(self):
        result = find_insecure_origins(
            ["http://10.0.0.5:3000", "http://192.168.1.10:3000"]
        )
        assert result == ["http://10.0.0.5:3000", "http://192.168.1.10:3000"]

    def test_empty_input(self):
        assert find_insecure_origins([]) == []

    def test_all_safe(self):
        assert (
            find_insecure_origins(
                ["http://localhost:3000", "https://app.example.com"]
            )
            == []
        )

    def test_ignores_non_http_schemes(self):
        # Non-http(s) entries in CORS_ORIGINS are not this check's concern.
        assert (
            find_insecure_origins(
                [
                    "ws://example.com",
                    "javascript:alert(1)",
                    "not-a-url",
                    "https://app.example.com",
                ]
            )
            == []
        )

    def test_handles_ipv6_hosts(self):
        # urlparse normalizes bracketed IPv6 to bare form for .hostname,
        # so the loopback shortcut still works.
        assert find_insecure_origins(["http://[::1]:3000"]) == []
        assert find_insecure_origins(["http://[2001:db8::1]:3000"]) == [
            "http://[2001:db8::1]:3000"
        ]


class TestRequestIsInsecureHttp:
    def test_http_lan_ip_is_insecure(self):
        req = _make_request("http", "192.168.1.10")
        assert request_is_insecure_http(req) is True

    def test_http_localhost_is_safe(self):
        req = _make_request("http", "localhost")
        assert request_is_insecure_http(req) is False

    def test_http_loopback_is_safe(self):
        req = _make_request("http", "127.0.0.1")
        assert request_is_insecure_http(req) is False

    def test_https_is_safe(self):
        req = _make_request("https", "app.example.com")
        assert request_is_insecure_http(req) is False

    def test_x_forwarded_proto_alone_is_not_trusted(self):
        # A spoofed X-Forwarded-Proto header must not silence the warning
        # by itself — without uvicorn --proxy-headers wiring it through to
        # request.url.scheme, the header is just user input. A properly
        # configured proxy deployment sets request.url.scheme=https for us.
        req = _make_request(
            "http", "192.168.1.10", forwarded_proto="https"
        )
        assert request_is_insecure_http(req) is True

    def test_ipv6_loopback_is_safe(self):
        req = _make_request("http", "::1")
        assert request_is_insecure_http(req) is False
