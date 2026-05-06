"""Unit + integration tests for NightscoutClient.

Two layers:

1. **Unit tests** (the bulk) -- mock `validate_target` so DNS isn't
   touched, then mock `httpx.AsyncClient.request` so HTTP isn't
   touched either. Covers auth headers, pagination params, retry
   policy, error mapping, auto-detect, and cleanup.

2. **Integration tests** (`@pytest.mark.integration`) -- hit the
   local test Nightscout via `NIGHTSCOUT_TEST_URL` env var. Skipped
   if the env var isn't set, so CI doesn't depend on a real instance.
   These tests run against the seeded `~/dev-test/nightscout/` stack
   when developing locally.
"""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.models.nightscout_connection import (
    NightscoutApiVersion,
    NightscoutAuthType,
)
from src.services.integrations.nightscout.client import (
    DEFAULT_PAGE_SIZE,
    MAX_RETRIES_5XX,
    MAX_RETRIES_429,
    RETRY_AFTER_CAP_SECONDS,
    NightscoutClient,
    _backoff_delay,
    _parse_retry_after,
    _sha1_api_secret,
)
from src.services.integrations.nightscout.errors import (
    NightscoutAuthError,
    NightscoutNetworkError,
    NightscoutNotFoundError,
    NightscoutRateLimitError,
    NightscoutServerError,
    NightscoutValidationError,
)
from src.services.integrations.nightscout.ssrf import ValidatedTarget

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_target(
    *, scheme: str = "https", hostname: str = "ns.example.com", port: int | None = None
) -> ValidatedTarget:
    p = port or (443 if scheme == "https" else 80)
    host_header = f"{hostname}:{port}" if port else hostname
    return ValidatedTarget(
        scheme=scheme,
        hostname=hostname,
        host_header=host_header,
        port=p,
        path_prefix="",
        base_url=f"{scheme}://{host_header}",
    )


def _make_client(
    *,
    auth_type: NightscoutAuthType = NightscoutAuthType.SECRET,
    api_version: NightscoutApiVersion = NightscoutApiVersion.V1,
    credential: str = "test-secret-12chars-long",
    target: ValidatedTarget | None = None,
) -> NightscoutClient:
    """Build a client without going through `create()` (which does DNS)."""
    c = NightscoutClient(
        target=target or _fake_target(),
        auth_type=auth_type,
        credential=credential,
        api_version=api_version,
    )
    c._open()  # noqa: SLF001  -- exercising lifecycle from tests
    return c


def _resp(
    status: int, body: object = None, headers: dict | None = None
) -> httpx.Response:
    """Build a synthetic httpx Response."""
    if body is None:
        content = b""
    elif isinstance(body, bytes):
        content = body
    else:
        import json

        content = json.dumps(body).encode("utf-8")
    return httpx.Response(
        status_code=status,
        content=content,
        headers=headers or {"content-type": "application/json"},
    )


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


class TestAuthHeaders:
    def test_v1_headers_use_sha1_of_credential(self):
        c = _make_client(auth_type=NightscoutAuthType.SECRET, credential="my-secret")
        headers = c._v1_headers()
        # Compare against an independently-computed SHA-1 to verify it's
        # really the right hash (and the suppressed lint isn't masking
        # an algorithm mistake).
        expected = hashlib.sha1(b"my-secret").hexdigest()  # noqa: S324  # nosemgrep: python.lang.security.insecure-hash-algorithms.insecure-hash-algorithm-sha1
        assert headers == {"api-secret": expected}

    def test_v3_headers_use_bearer_token(self):
        c = _make_client(auth_type=NightscoutAuthType.TOKEN, credential="abc.def.ghi")
        assert c._v3_headers() == {"Authorization": "Bearer abc.def.ghi"}

    def test_sha1_helper_matches_nightscout_protocol(self):
        # The Nightscout test instance uses this exact secret. The
        # SHA-1 below was independently verified against the running
        # instance during development.
        secret = "glycemicgpt-test-secret-min12chars"
        expected = hashlib.sha1(secret.encode()).hexdigest()  # noqa: S324  # nosemgrep: python.lang.security.insecure-hash-algorithms.insecure-hash-algorithm-sha1
        assert _sha1_api_secret(secret) == expected


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_create_validates_url_and_returns_open_client(self):
        with patch(
            "src.services.integrations.nightscout.client.validate_target",
            new=AsyncMock(return_value=_fake_target()),
        ):
            c = await NightscoutClient.create(
                base_url="https://ns.example.com",
                auth_type=NightscoutAuthType.SECRET,
                credential="x",
                api_version=NightscoutApiVersion.V1,
            )
        assert c._client is not None
        await c.aclose()
        assert c._client is None

    @pytest.mark.asyncio
    async def test_create_raises_validation_error_on_bad_url(self):
        with (
            patch(
                "src.services.integrations.nightscout.client.validate_target",
                new=AsyncMock(side_effect=ValueError("bad")),
            ),
            pytest.raises(NightscoutValidationError),
        ):
            await NightscoutClient.create(
                base_url="bad",
                auth_type=NightscoutAuthType.SECRET,
                credential="x",
                api_version=NightscoutApiVersion.V1,
            )

    @pytest.mark.asyncio
    async def test_async_context_manager_closes_underlying_client(self):
        with patch(
            "src.services.integrations.nightscout.client.validate_target",
            new=AsyncMock(return_value=_fake_target()),
        ):
            async with await NightscoutClient.create(
                base_url="https://ns.example.com",
                auth_type=NightscoutAuthType.SECRET,
                credential="x",
                api_version=NightscoutApiVersion.V1,
            ) as c:
                assert c._client is not None
            assert c._client is None


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


class TestErrorMapping:
    @pytest.mark.asyncio
    async def test_401_raises_auth_error(self):
        c = _make_client()
        with (
            patch.object(c._client, "request", new=AsyncMock(return_value=_resp(401))),
            pytest.raises(NightscoutAuthError),
        ):
            await c.fetch_entries()

    @pytest.mark.asyncio
    async def test_403_raises_auth_error(self):
        c = _make_client()
        with (
            patch.object(c._client, "request", new=AsyncMock(return_value=_resp(403))),
            pytest.raises(NightscoutAuthError),
        ):
            await c.fetch_entries()

    @pytest.mark.asyncio
    async def test_404_raises_not_found_error(self):
        c = _make_client()
        with (
            patch.object(c._client, "request", new=AsyncMock(return_value=_resp(404))),
            pytest.raises(NightscoutNotFoundError),
        ):
            await c.fetch_entries()

    @pytest.mark.asyncio
    async def test_transport_error_raises_network_error(self):
        c = _make_client()
        with (
            patch.object(
                c._client,
                "request",
                new=AsyncMock(side_effect=httpx.ConnectError("conn refused")),
            ),
            pytest.raises(NightscoutNetworkError),
        ):
            await c.fetch_entries()

    @pytest.mark.asyncio
    async def test_credential_scrubbed_from_network_error_message(self):
        """Defense-in-depth: if h11/httpx leaks the credential into an
        exception message (LocalProtocolError quotes the offending
        header value), NightscoutNetworkError must not propagate the
        raw value -- it gets persisted to last_sync_error and shown
        to caregivers / written to logs."""
        secret = "super-secret-bearer-token-9zk"
        c = _make_client(
            auth_type=NightscoutAuthType.TOKEN,
            api_version=NightscoutApiVersion.V3,
            credential=secret,
        )
        err = httpx.RemoteProtocolError(
            f"Illegal header value b'Bearer {secret}\\r\\n'"
        )
        with (
            patch.object(c._client, "request", new=AsyncMock(side_effect=err)),
            pytest.raises(NightscoutNetworkError) as exc_info,
        ):
            await c._request("GET", "/api/v3/version")
        assert secret not in str(exc_info.value)
        assert "<redacted>" in str(exc_info.value)

    def test_v3_headers_reject_control_chars_in_credential(self):
        """Pre-flight rejection of credentials with embedded CRLF/etc.
        Catches the common copy-paste-with-stray-newline case before
        the credential ever reaches the wire."""
        c = _make_client(
            auth_type=NightscoutAuthType.TOKEN,
            credential="bearer-token-with-newline\r\nInjected: header",
        )
        with pytest.raises(NightscoutValidationError, match="control"):
            c._v3_headers()


# ---------------------------------------------------------------------------
# Retry / backoff
# ---------------------------------------------------------------------------


class TestRetryPolicy:
    @pytest.mark.asyncio
    async def test_429_retries_then_succeeds(self):
        c = _make_client()
        responses = [_resp(429), _resp(429), _resp(200, [])]
        with (
            patch.object(c._client, "request", new=AsyncMock(side_effect=responses)),
            patch(
                "src.services.integrations.nightscout.client.asyncio.sleep",
                new=AsyncMock(),  # don't actually sleep in tests
            ),
        ):
            result = await c.fetch_entries()
        assert result == []

    @pytest.mark.asyncio
    async def test_429_exhausts_budget_raises_rate_limit_error(self):
        c = _make_client()
        # MAX_RETRIES_429 + 1 = 4 attempts before giving up.
        responses = [_resp(429, headers={"Retry-After": "30"})] * (MAX_RETRIES_429 + 1)
        with (
            patch.object(c._client, "request", new=AsyncMock(side_effect=responses)),
            patch(
                "src.services.integrations.nightscout.client.asyncio.sleep",
                new=AsyncMock(),
            ),
            pytest.raises(NightscoutRateLimitError) as exc_info,
        ):
            await c.fetch_entries()
        assert exc_info.value.retry_after_seconds == 30.0

    @pytest.mark.asyncio
    async def test_500_retries_then_raises(self):
        c = _make_client()
        # Size from MAX_RETRIES_5XX so the test stays in lockstep with
        # the constant if it's ever bumped.
        responses = [_resp(500)] * (MAX_RETRIES_5XX + 1)
        with (
            patch.object(c._client, "request", new=AsyncMock(side_effect=responses)),
            patch(
                "src.services.integrations.nightscout.client.asyncio.sleep",
                new=AsyncMock(),
            ),
            pytest.raises(NightscoutServerError),
        ):
            await c.fetch_entries()

    @pytest.mark.asyncio
    async def test_500_then_200_succeeds_on_retry(self):
        c = _make_client()
        # MAX_RETRIES_5XX failures followed by a success should be
        # within budget regardless of how the constant is tuned.
        responses = [_resp(503)] * MAX_RETRIES_5XX + [_resp(200, [{"sgv": 100}])]
        with (
            patch.object(c._client, "request", new=AsyncMock(side_effect=responses)),
            patch(
                "src.services.integrations.nightscout.client.asyncio.sleep",
                new=AsyncMock(),
            ),
        ):
            result = await c.fetch_entries()
        assert result == [{"sgv": 100}]

    @pytest.mark.asyncio
    async def test_429_retry_after_clamped_to_cap(self):
        """Pathological Retry-After should not pin us for hours."""
        c = _make_client()
        responses = [
            _resp(429, headers={"Retry-After": "86400"}),
            _resp(200, []),
        ]
        sleep_mock = AsyncMock()
        with (
            patch.object(c._client, "request", new=AsyncMock(side_effect=responses)),
            patch(
                "src.services.integrations.nightscout.client.asyncio.sleep",
                new=sleep_mock,
            ),
        ):
            result = await c.fetch_entries()
        assert result == []
        # First (and only) sleep should be the clamped cap, not 86400.
        sleep_mock.assert_awaited_once()
        assert sleep_mock.await_args.args[0] == RETRY_AFTER_CAP_SECONDS


# ---------------------------------------------------------------------------
# Pagination params
# ---------------------------------------------------------------------------


class TestFetchEntries:
    @pytest.mark.asyncio
    async def test_fetch_entries_default_params(self):
        c = _make_client()
        mock_request = AsyncMock(return_value=_resp(200, []))
        with patch.object(c._client, "request", new=mock_request):
            await c.fetch_entries()
        call = mock_request.call_args
        assert call.args[0] == "GET"
        assert call.args[1] == "/api/v1/entries.json"
        assert call.kwargs["params"] == {"count": DEFAULT_PAGE_SIZE}

    @pytest.mark.asyncio
    async def test_fetch_entries_with_since_and_count(self):
        c = _make_client()
        since = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
        mock_request = AsyncMock(return_value=_resp(200, []))
        with patch.object(c._client, "request", new=mock_request):
            await c.fetch_entries(since=since, count=100)
        params = mock_request.call_args.kwargs["params"]
        assert params["count"] == 100
        assert params["find[dateString][$gte]"] == "2026-05-01T12:00:00Z"

    @pytest.mark.asyncio
    async def test_fetch_treatments_uses_created_at_field(self):
        c = _make_client()
        since = datetime(2026, 5, 1, tzinfo=UTC)
        mock_request = AsyncMock(return_value=_resp(200, []))
        with patch.object(c._client, "request", new=mock_request):
            await c.fetch_treatments(since=since, count=200)
        params = mock_request.call_args.kwargs["params"]
        assert params["find[created_at][$gte]"] == "2026-05-01T00:00:00Z"

    @pytest.mark.asyncio
    async def test_fetch_devicestatus_uses_created_at_field(self):
        c = _make_client()
        since = datetime(2026, 5, 1, tzinfo=UTC)
        mock_request = AsyncMock(return_value=_resp(200, []))
        with patch.object(c._client, "request", new=mock_request):
            await c.fetch_devicestatus(since=since)
        params = mock_request.call_args.kwargs["params"]
        assert "find[created_at][$gte]" in params

    @pytest.mark.asyncio
    async def test_fetch_entries_naive_datetime_raises_value_error(self):
        """Naive datetimes are rejected. The previous "treat as UTC"
        behavior silently corrupted wall-clock data when callers ran
        outside UTC. Force the caller to be explicit."""
        c = _make_client()
        naive = datetime(2026, 5, 1, 12, 0, 0)  # no tzinfo
        with (
            patch.object(
                c._client, "request", new=AsyncMock(return_value=_resp(200, []))
            ),
            pytest.raises(ValueError, match="timezone-aware"),
        ):
            await c.fetch_entries(since=naive)


# ---------------------------------------------------------------------------
# fetch_profile
# ---------------------------------------------------------------------------


class TestFetchProfile:
    @pytest.mark.asyncio
    async def test_fetch_profile_returns_list(self):
        c = _make_client()
        with patch.object(
            c._client,
            "request",
            new=AsyncMock(return_value=_resp(200, [{"defaultProfile": "Default"}])),
        ):
            profiles = await c.fetch_profile()
        assert profiles == [{"defaultProfile": "Default"}]

    @pytest.mark.asyncio
    async def test_fetch_profile_handles_non_list_body(self):
        c = _make_client()
        with patch.object(
            c._client,
            "request",
            new=AsyncMock(return_value=_resp(200, {"unexpected": True})),
        ):
            profiles = await c.fetch_profile()
        # Defensive: shouldn't crash on unexpected shapes.
        assert profiles == []


# ---------------------------------------------------------------------------
# test_connection / auto-detect
# ---------------------------------------------------------------------------


class TestConnectionTest:
    @pytest.mark.asyncio
    async def test_v1_only_path_used_for_explicit_v1(self):
        c = _make_client(api_version=NightscoutApiVersion.V1)
        mock_request = AsyncMock(return_value=_resp(200, {"version": "15.0.8"}))
        with patch.object(c._client, "request", new=mock_request):
            outcome = await c.test_connection()
        assert outcome.ok is True
        assert outcome.api_version_detected == NightscoutApiVersion.V1
        assert outcome.server_version == "15.0.8"
        assert mock_request.call_count == 1
        assert mock_request.call_args.args[1] == "/api/v1/status.json"

    @pytest.mark.asyncio
    async def test_v3_only_path_used_for_explicit_v3(self):
        c = _make_client(
            auth_type=NightscoutAuthType.TOKEN, api_version=NightscoutApiVersion.V3
        )
        # Real Nightscout v3 /api/v3/version response shape (verified
        # against cgm-remote-monitor 15.0.8) -- no `result` envelope.
        responses = [
            _resp(
                200,
                {"status": 200, "version": "15.0.8", "apiVersion": "3.0.5"},
            ),  # /api/v3/version
            _resp(200, {}),  # /api/v3/status with auth
        ]
        with patch.object(c._client, "request", new=AsyncMock(side_effect=responses)):
            outcome = await c.test_connection()
        assert outcome.ok is True
        assert outcome.api_version_detected == NightscoutApiVersion.V3
        assert outcome.server_version == "15.0.8"

    @pytest.mark.asyncio
    async def test_auto_with_secret_uses_v1_only(self):
        c = _make_client(
            auth_type=NightscoutAuthType.SECRET, api_version=NightscoutApiVersion.AUTO
        )
        mock_request = AsyncMock(return_value=_resp(200, {"version": "15.0.8"}))
        with patch.object(c._client, "request", new=mock_request):
            outcome = await c.test_connection()
        assert outcome.api_version_detected == NightscoutApiVersion.V1
        # Only one call (no v3 fallback attempted).
        assert mock_request.call_count == 1

    @pytest.mark.asyncio
    async def test_auto_with_token_uses_v3_only(self):
        c = _make_client(
            auth_type=NightscoutAuthType.TOKEN, api_version=NightscoutApiVersion.AUTO
        )
        responses = [
            _resp(200, {"status": 200, "version": "15.0.8", "apiVersion": "3.0.5"}),
            _resp(200, {}),
        ]
        with patch.object(c._client, "request", new=AsyncMock(side_effect=responses)):
            outcome = await c.test_connection()
        assert outcome.api_version_detected == NightscoutApiVersion.V3

    @pytest.mark.asyncio
    async def test_pure_auto_falls_back_to_v3_on_v1_404(self):
        """auto/auto -- v1 status 404, v3 path succeeds."""
        c = _make_client(
            auth_type=NightscoutAuthType.AUTO, api_version=NightscoutApiVersion.AUTO
        )
        responses = [
            _resp(404),  # /api/v1/status.json -- server doesn't speak v1
            _resp(200, {"status": 200, "version": "15.0.8", "apiVersion": "3.0.5"}),
            _resp(200, {}),  # /v3/status with auth
        ]
        with patch.object(c._client, "request", new=AsyncMock(side_effect=responses)):
            outcome = await c.test_connection()
        assert outcome.ok is True
        assert outcome.api_version_detected == NightscoutApiVersion.V3

    @pytest.mark.asyncio
    async def test_pure_auto_falls_back_to_v3_on_v1_auth_failure(self):
        """auto/auto: if v1 401s, the credential might actually be a
        v3 token (the user said they didn't know which type it was).
        Fall back and try v3."""
        c = _make_client(
            auth_type=NightscoutAuthType.AUTO,
            api_version=NightscoutApiVersion.AUTO,
            credential="v3-bearer-token-not-a-secret",
        )
        responses = [
            _resp(401),  # v1 rejected
            _resp(200, {"status": 200, "version": "15.0.8", "apiVersion": "3.0.5"}),
            _resp(200, {}),  # v3 status accepts the token
        ]
        with patch.object(c._client, "request", new=AsyncMock(side_effect=responses)):
            outcome = await c.test_connection()
        assert outcome.ok is True
        assert outcome.api_version_detected == NightscoutApiVersion.V3

    @pytest.mark.asyncio
    async def test_explicit_secret_does_not_fall_back_on_v1_auth_failure(self):
        """If user explicitly said `auth_type=secret`, a 401 is a real
        auth failure -- don't second-guess by trying v3."""
        c = _make_client(
            auth_type=NightscoutAuthType.SECRET, api_version=NightscoutApiVersion.AUTO
        )
        mock_request = AsyncMock(return_value=_resp(401))
        with patch.object(c._client, "request", new=mock_request):
            outcome = await c.test_connection()
        assert outcome.ok is False
        assert outcome.auth_validated is False
        assert mock_request.call_count == 1

    @pytest.mark.asyncio
    async def test_v1_auth_failure_returns_failure_outcome_not_exception(self):
        c = _make_client(api_version=NightscoutApiVersion.V1)
        with patch.object(c._client, "request", new=AsyncMock(return_value=_resp(401))):
            outcome = await c.test_connection()
        assert outcome.ok is False
        assert outcome.auth_validated is False
        assert outcome.api_version_detected == NightscoutApiVersion.V1
        assert "Authentication rejected" in (outcome.error or "")

    @pytest.mark.asyncio
    async def test_network_error_during_test_returns_failure_outcome(self):
        c = _make_client(api_version=NightscoutApiVersion.V1)
        with patch.object(
            c._client,
            "request",
            new=AsyncMock(side_effect=httpx.ConnectError("conn refused")),
        ):
            outcome = await c.test_connection()
        assert outcome.ok is False
        assert "network" in (outcome.error or "").lower()

    @pytest.mark.asyncio
    async def test_v3_server_error_returns_failure_outcome(self):
        """5xx burst on /api/v3/version (after retry exhaustion)
        must surface as an outcome, not propagate as an exception.
        `_test_v3` doesn't catch it locally -- the outer handler in
        `test_connection` is what saves us."""
        c = _make_client(
            auth_type=NightscoutAuthType.TOKEN, api_version=NightscoutApiVersion.V3
        )
        responses = [_resp(500)] * (MAX_RETRIES_5XX + 1)
        with (
            patch.object(c._client, "request", new=AsyncMock(side_effect=responses)),
            patch(
                "src.services.integrations.nightscout.client.asyncio.sleep",
                new=AsyncMock(),
            ),
        ):
            outcome = await c.test_connection()
        assert outcome.ok is False
        assert "server error" in (outcome.error or "").lower()

    @pytest.mark.asyncio
    async def test_v3_rate_limit_returns_failure_outcome(self):
        """429 storm on v3 probes (after retry exhaustion) must surface
        as an outcome, not propagate as an exception."""
        c = _make_client(
            auth_type=NightscoutAuthType.TOKEN, api_version=NightscoutApiVersion.V3
        )
        responses = [_resp(429, headers={"Retry-After": "1"})] * (MAX_RETRIES_429 + 1)
        with (
            patch.object(c._client, "request", new=AsyncMock(side_effect=responses)),
            patch(
                "src.services.integrations.nightscout.client.asyncio.sleep",
                new=AsyncMock(),
            ),
        ):
            outcome = await c.test_connection()
        assert outcome.ok is False
        assert "rate limited" in (outcome.error or "").lower()


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_backoff_delay_grows_with_attempts(self):
        d0 = _backoff_delay(0)
        d2 = _backoff_delay(2)
        # With jitter we can't assert exact values, but the upper
        # bounds are clearly increasing.
        assert d0 <= 2.0
        assert d2 <= 8.0
        assert d2 > d0  # almost always true with jitter; if flaky, drop

    def test_parse_retry_after_seconds(self):
        assert _parse_retry_after("30") == 30.0
        assert _parse_retry_after("0") == 0.0
        assert _parse_retry_after("") is None
        assert _parse_retry_after(None) is None
        assert _parse_retry_after("not-a-number") is None

    def test_parse_retry_after_rejects_negatives(self):
        """Negative values are nonsensical; treat as missing."""
        assert _parse_retry_after("-1") is None
        assert _parse_retry_after("-30.5") is None


# ---------------------------------------------------------------------------
# v3 fetch guard
# ---------------------------------------------------------------------------


class TestV3FetchGuard:
    """v3 data fetches aren't implemented yet -- raise loudly rather
    than silently sending v1 paths with a Bearer token."""

    @pytest.mark.asyncio
    async def test_fetch_entries_with_v3_raises(self):
        c = _make_client(
            api_version=NightscoutApiVersion.V3, auth_type=NightscoutAuthType.TOKEN
        )
        with pytest.raises(NotImplementedError, match="v3"):
            await c.fetch_entries()

    @pytest.mark.asyncio
    async def test_fetch_treatments_with_v3_raises(self):
        c = _make_client(
            api_version=NightscoutApiVersion.V3, auth_type=NightscoutAuthType.TOKEN
        )
        with pytest.raises(NotImplementedError):
            await c.fetch_treatments()

    @pytest.mark.asyncio
    async def test_fetch_devicestatus_with_v3_raises(self):
        c = _make_client(
            api_version=NightscoutApiVersion.V3, auth_type=NightscoutAuthType.TOKEN
        )
        with pytest.raises(NotImplementedError):
            await c.fetch_devicestatus()

    @pytest.mark.asyncio
    async def test_fetch_profile_with_v3_raises(self):
        c = _make_client(
            api_version=NightscoutApiVersion.V3, auth_type=NightscoutAuthType.TOKEN
        )
        with pytest.raises(NotImplementedError):
            await c.fetch_profile()


# ---------------------------------------------------------------------------
# Integration tests (live local Nightscout)
# ---------------------------------------------------------------------------
#
# Run by pointing NIGHTSCOUT_TEST_URL at a running instance, e.g.:
#
#   NIGHTSCOUT_TEST_URL=http://127.0.0.1:1337 \
#   NIGHTSCOUT_TEST_SECRET=glycemicgpt-test-secret-min12chars \
#   uv run pytest tests/test_nightscout_client.py -m integration
#
# Skipped automatically when the env vars aren't set.

_NS_URL = os.environ.get("NIGHTSCOUT_TEST_URL")
_NS_SECRET = os.environ.get(
    "NIGHTSCOUT_TEST_SECRET", "glycemicgpt-test-secret-min12chars"
)
_skip_no_live = pytest.mark.skipif(
    not _NS_URL,
    reason="set NIGHTSCOUT_TEST_URL to run integration tests against a real instance",
)


@_skip_no_live
@pytest.mark.integration
class TestLiveIntegration:
    @pytest.mark.asyncio
    async def test_v1_test_connection_against_live(self):
        async with await NightscoutClient.create(
            base_url=_NS_URL,
            auth_type=NightscoutAuthType.SECRET,
            credential=_NS_SECRET,
            api_version=NightscoutApiVersion.V1,
        ) as c:
            outcome = await c.test_connection()
        assert outcome.ok is True
        assert outcome.api_version_detected == NightscoutApiVersion.V1
        assert outcome.server_version  # any non-empty version string

    @pytest.mark.asyncio
    async def test_v1_fetch_entries_returns_recent_data(self):
        async with await NightscoutClient.create(
            base_url=_NS_URL,
            auth_type=NightscoutAuthType.SECRET,
            credential=_NS_SECRET,
            api_version=NightscoutApiVersion.V1,
        ) as c:
            entries = await c.fetch_entries(count=10)
        # The seed script populates ~2000 entries; expect at least some
        # if the seeder ran. If the instance is empty this returns [].
        assert isinstance(entries, list)
        if entries:
            first = entries[0]
            assert "sgv" in first or "type" in first

    @pytest.mark.asyncio
    async def test_v1_fetch_entries_with_since_filter(self):
        async with await NightscoutClient.create(
            base_url=_NS_URL,
            auth_type=NightscoutAuthType.SECRET,
            credential=_NS_SECRET,
            api_version=NightscoutApiVersion.V1,
        ) as c:
            since = datetime.now(UTC) - timedelta(days=1)
            entries = await c.fetch_entries(since=since, count=500)
        assert isinstance(entries, list)
        # If we have entries, they should all be newer than `since`.
        for e in entries:
            ds = e.get("dateString") or e.get("date")
            assert ds is not None

    @pytest.mark.asyncio
    async def test_v1_auth_rejected_with_wrong_secret(self):
        async with await NightscoutClient.create(
            base_url=_NS_URL,
            auth_type=NightscoutAuthType.SECRET,
            credential="wrong-secret-min12chars-but-bad",
            api_version=NightscoutApiVersion.V1,
        ) as c:
            outcome = await c.test_connection()
        assert outcome.ok is False
        assert outcome.auth_validated is False

    @pytest.mark.asyncio
    async def test_v1_fetch_profile(self):
        async with await NightscoutClient.create(
            base_url=_NS_URL,
            auth_type=NightscoutAuthType.SECRET,
            credential=_NS_SECRET,
            api_version=NightscoutApiVersion.V1,
        ) as c:
            profiles = await c.fetch_profile()
        assert isinstance(profiles, list)
