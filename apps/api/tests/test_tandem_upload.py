"""Story 16.6: Tests for Tandem cloud upload service."""

import base64
import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from src.core.encryption import encrypt_credential
from src.core.tandem_regions import TandemLegacyRegionError
from src.database import get_session_maker
from src.main import app
from src.models.integration import (
    IntegrationCredential,
    IntegrationStatus,
    IntegrationType,
)
from src.models.pump_hardware_info import PumpHardwareInfo
from src.models.pump_raw_event import PumpRawEvent
from src.models.tandem_upload_state import TandemUploadState
from src.models.user import User
from src.services.tandem_upload import (
    _authenticate_fresh,
    build_upload_payload,
    reset_tandem_upload_state,
    sign_tdc_token,
    upload_to_tandem,
)


def _email() -> str:
    return f"upload_{uuid.uuid4().hex[:8]}@test.com"


async def _register_and_mobile_login(
    client: AsyncClient, email: str, password: str = "TestPass1"
) -> str:
    await client.post(
        "/api/auth/register",
        json={"email": email, "password": password},
    )
    resp = await client.post(
        "/api/auth/mobile/login",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


_TEST_HMAC_KEY = b"test-hmac-key-for-unit-tests"


class TestHMACSigning:
    """Test HMAC-SHA1 signing matches the Tandem protocol."""

    def test_sign_tdc_token_produces_valid_hmac(self):
        body = b'{"client":"mHealth","package":{"device":{}}}'
        result = sign_tdc_token(body, hmac_key=_TEST_HMAC_KEY)
        # Verify it's valid base64
        decoded = base64.b64decode(result)
        assert len(decoded) == 20  # SHA1 produces 20 bytes

    def test_sign_tdc_token_is_deterministic(self):
        body = b'{"test":"data"}'
        assert sign_tdc_token(body, hmac_key=_TEST_HMAC_KEY) == sign_tdc_token(
            body, hmac_key=_TEST_HMAC_KEY
        )

    def test_sign_tdc_token_matches_manual_computation(self):
        body = b'{"foo":"bar"}'
        expected = base64.b64encode(
            hmac.new(_TEST_HMAC_KEY, body, hashlib.sha1).digest()
        ).decode("ascii")
        assert sign_tdc_token(body, hmac_key=_TEST_HMAC_KEY) == expected

    def test_different_bodies_produce_different_signatures(self):
        assert sign_tdc_token(b"body1", hmac_key=_TEST_HMAC_KEY) != sign_tdc_token(
            b"body2", hmac_key=_TEST_HMAC_KEY
        )


class TestBuildUploadPayload:
    """Test payload construction matches the official app schema."""

    def _make_mock_pump_info(self):
        """Create a mock pump hardware info object."""

        class MockPumpInfo:
            serial_number = 12345678
            model_number = 99
            part_number = 11111
            pump_rev = "3.0"
            arm_sw_ver = 50000
            msp_sw_ver = 50000
            config_a_bits = 0
            config_b_bits = 0
            pcba_sn = 99999
            pcba_rev = "A"
            pump_features = {
                "dexcomG5": False,
                "basalIQ": False,
                "dexcomG6": True,
                "controlIQ": True,
                "dexcomG7": True,
                "abbottFsl2": False,
            }

        return MockPumpInfo()

    def _make_mock_raw_event(self, seq=1):
        """Create a mock raw event."""

        class MockRawEvent:
            sequence_number = seq
            raw_bytes_b64 = base64.b64encode(b"test_event_bytes").decode()
            event_type_id = 280
            pump_time_seconds = 1000000

        return MockRawEvent()

    def test_top_level_structure(self):
        pump_info = self._make_mock_pump_info()
        payload = build_upload_payload(pump_info, [])
        assert payload["client"] == "mHealth"
        assert "package" in payload
        assert "device" in payload["package"]

    def test_device_fields(self):
        pump_info = self._make_mock_pump_info()
        payload = build_upload_payload(pump_info, [])
        device = payload["package"]["device"]
        assert device["serialNum"] == 12345678
        assert device["modelNum"] == 99
        assert device["pumpRev"] == "3.0"
        assert "data" in device

    def test_misc_section(self):
        pump_info = self._make_mock_pump_info()
        payload = build_upload_payload(pump_info, [])
        misc = payload["package"]["device"]["data"]["misc"]
        assert misc["uploaderClient"] == "mobile_tconnect"
        assert misc["appVersion"] == "2.9.1 (3368rb)"
        assert "pumpFeatures" in misc

    def test_payload_uses_pump_time_when_events_present(self):
        """``pumpDateTime`` must reflect the latest event's pump time, not
        the backend's wall-clock at upload time. The stored
        ``pump_time_seconds`` value is in *Tandem epoch* (seconds since
        2008-01-01); converting it correctly requires adding
        ``TANDEM_EPOCH_OFFSET_SECONDS``. Sending the raw value as if it
        were UNIX time would render every event in the late 1980s, which
        Tandem silently rejects the same way it rejects ``now()``.
        """
        pump_info = self._make_mock_pump_info()
        # Realistic Tandem-epoch values. 564_941_700 + 1_199_145_600
        # = 1_764_087_300 UNIX = 2025-11-25T16:15:00 UTC.
        events = [self._make_mock_raw_event(seq=10) for _ in range(3)]
        for ev, ts in zip(
            events,
            [564_940_800, 564_941_100, 564_941_700],
            strict=True,
        ):
            ev.pump_time_seconds = ts
        payload = build_upload_payload(pump_info, events)
        misc = payload["package"]["device"]["data"]["misc"]
        # Latest event wins; if the epoch offset is missing we'd render
        # this as 1987-11-22 instead (which is exactly the failure mode
        # the original "fix" shipped before the adversarial-review catch).
        assert misc["pumpDateTime"] == "2025-11-25T16:15:00"

    def test_payload_falls_back_to_now_when_no_events(self):
        """With no events to anchor pump time, fall back to wall-clock so
        we still send a valid (if approximate) timestamp."""
        pump_info = self._make_mock_pump_info()
        before = datetime.now(UTC).replace(microsecond=0)
        payload = build_upload_payload(pump_info, [])
        after = datetime.now(UTC).replace(microsecond=0)
        misc = payload["package"]["device"]["data"]["misc"]
        rendered = datetime.strptime(misc["pumpDateTime"], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=UTC
        )
        assert before <= rendered <= after

    def test_payload_skips_bogus_pump_times(self):
        """Events with timestamps outside [2008, now+5y] are filtered before
        computing the max so a single bad event can't poison the batch."""
        pump_info = self._make_mock_pump_info()
        events = [self._make_mock_raw_event(seq=i) for i in range(3)]
        # Valid event from late 2025
        events[0].pump_time_seconds = 564_940_800
        # Bogus future event (~ year 2999 if treated naively)
        events[1].pump_time_seconds = 31_000_000_000
        # Another valid event from late 2025 (slightly later than events[0])
        events[2].pump_time_seconds = 564_941_100
        payload = build_upload_payload(pump_info, events)
        misc = payload["package"]["device"]["data"]["misc"]
        # The bogus one is discarded; max of remaining = 564_941_100
        # 564_941_100 + 1_199_145_600 = 1_764_086_700 = 2025-11-25T16:05:00 UTC
        assert misc["pumpDateTime"] == "2025-11-25T16:05:00"

    def test_payload_falls_back_when_every_event_is_bogus(self):
        """If every event is out of range, fall back to now() instead of
        crashing or sending garbage."""
        pump_info = self._make_mock_pump_info()
        events = [self._make_mock_raw_event(seq=i) for i in range(2)]
        # Negative pump time renders before the Tandem epoch (filtered).
        events[0].pump_time_seconds = -100_000_000
        # Far-future pump time, well past now()+5y (filtered).
        events[1].pump_time_seconds = 999_999_999_999
        before = datetime.now(UTC).replace(microsecond=0)
        payload = build_upload_payload(pump_info, events)
        after = datetime.now(UTC).replace(microsecond=0)
        misc = payload["package"]["device"]["data"]["misc"]
        rendered = datetime.strptime(misc["pumpDateTime"], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=UTC
        )
        assert before <= rendered <= after

    def test_events_included(self):
        pump_info = self._make_mock_pump_info()
        events = [self._make_mock_raw_event(i) for i in range(3)]
        payload = build_upload_payload(pump_info, events)
        data = payload["package"]["device"]["data"]
        assert "events" in data
        assert len(data["events"]) == 3
        assert all(isinstance(e, str) for e in data["events"])

    def test_no_events_omits_key(self):
        pump_info = self._make_mock_pump_info()
        payload = build_upload_payload(pump_info, [])
        data = payload["package"]["device"]["data"]
        assert "events" not in data

    def test_settings_included_when_provided(self):
        pump_info = self._make_mock_pump_info()
        payload = build_upload_payload(pump_info, [], settings_b64="abc123")
        data = payload["package"]["device"]["data"]
        assert data["settings"] == "abc123"

    def test_device_assignment_id_included(self):
        pump_info = self._make_mock_pump_info()
        payload = build_upload_payload(
            pump_info, [], device_assignment_id="abc-123-pump"
        )
        misc = payload["package"]["device"]["data"]["misc"]
        assert misc["deviceAssignmentId"] == "abc-123-pump"

    def test_device_assignment_id_defaults_to_empty(self):
        pump_info = self._make_mock_pump_info()
        payload = build_upload_payload(pump_info, [])
        misc = payload["package"]["device"]["data"]["misc"]
        assert misc["deviceAssignmentId"] == ""

    def test_payload_is_json_serializable(self):
        pump_info = self._make_mock_pump_info()
        events = [self._make_mock_raw_event(i) for i in range(5)]
        payload = build_upload_payload(pump_info, events)
        # Should not raise
        json_str = json.dumps(payload)
        assert len(json_str) > 0


class TestPumpPushWithRawEvents:
    """Test the extended pump push endpoint with raw events and hardware info."""

    async def test_push_with_raw_events(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            token = await _register_and_mobile_login(c, _email())
            now = datetime.now(UTC).isoformat()
            resp = await c.post(
                "/api/integrations/pump/push",
                json={
                    "events": [
                        {
                            "event_type": "bolus",
                            "event_timestamp": now,
                            "units": 2.5,
                        }
                    ],
                    "raw_events": [
                        {
                            "sequence_number": 100,
                            "raw_bytes_b64": base64.b64encode(b"test").decode(),
                            "event_type_id": 280,
                            "pump_time_seconds": 1000000,
                        }
                    ],
                    "source": "mobile",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["accepted"] == 1
        assert body["raw_accepted"] == 1

    async def test_push_with_hardware_info(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            token = await _register_and_mobile_login(c, _email())
            now = datetime.now(UTC).isoformat()
            resp = await c.post(
                "/api/integrations/pump/push",
                json={
                    "events": [
                        {
                            "event_type": "basal",
                            "event_timestamp": now,
                            "units": 0.8,
                        }
                    ],
                    "pump_info": {
                        "serial_number": 12345678,
                        "model_number": 99,
                        "part_number": 11111,
                        "pump_rev": "3.0",
                        "arm_sw_ver": 50000,
                        "msp_sw_ver": 50000,
                        "config_a_bits": 0,
                        "config_b_bits": 0,
                        "pcba_sn": 99999,
                        "pcba_rev": "A",
                        "pump_features": {"controlIQ": True},
                    },
                    "source": "mobile",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["accepted"] == 1

    async def test_push_without_raw_events_backward_compatible(self):
        """Existing push requests without raw_events/pump_info still work."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            token = await _register_and_mobile_login(c, _email())
            now = datetime.now(UTC).isoformat()
            resp = await c.post(
                "/api/integrations/pump/push",
                json={
                    "events": [
                        {
                            "event_type": "bolus",
                            "event_timestamp": now,
                            "units": 3.0,
                        }
                    ],
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["accepted"] == 1
        assert body["raw_accepted"] == 0
        assert body["raw_duplicates"] == 0

    async def test_raw_event_deduplication(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            token = await _register_and_mobile_login(c, _email())
            now = datetime.now(UTC).isoformat()
            raw_event = {
                "sequence_number": 200,
                "raw_bytes_b64": base64.b64encode(b"data").decode(),
                "event_type_id": 279,
                "pump_time_seconds": 2000000,
            }
            # First push
            resp1 = await c.post(
                "/api/integrations/pump/push",
                json={
                    "events": [
                        {
                            "event_type": "basal",
                            "event_timestamp": now,
                            "units": 0.5,
                        }
                    ],
                    "raw_events": [raw_event],
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp1.status_code == 200
            assert resp1.json()["raw_accepted"] == 1

            # Second push with same sequence number
            now2 = (datetime.now(UTC) + timedelta(seconds=1)).isoformat()
            resp2 = await c.post(
                "/api/integrations/pump/push",
                json={
                    "events": [
                        {
                            "event_type": "bolus",
                            "event_timestamp": now2,
                            "units": 1.0,
                        }
                    ],
                    "raw_events": [raw_event],
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp2.status_code == 200
            assert resp2.json()["raw_duplicates"] == 1


class TestTandemUploadStatusEndpoints:
    """Test the Tandem cloud upload status/settings endpoints."""

    async def test_get_status_default(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            token = await _register_and_mobile_login(c, _email())
            resp = await c.get(
                "/api/integrations/tandem/cloud-upload/status",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["enabled"] is False
        assert body["upload_interval_minutes"] == 15

    @patch("src.routers.integrations.validate_tandem_credentials")
    async def test_update_settings(self, mock_validate):
        """Enabling upload now requires a Tandem credential, so we connect
        one before flipping the toggle on."""
        mock_validate.return_value = (True, None)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            token = await _register_and_mobile_login(c, _email())
            # Seed Tandem credential via the public connect endpoint.
            connect = await c.post(
                "/api/integrations/tandem",
                json={"username": "t@example.com", "password": "p", "country": "US"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert connect.status_code == 201, connect.text

            resp = await c.put(
                "/api/integrations/tandem/cloud-upload/settings",
                json={"enabled": True, "interval_minutes": 10},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["enabled"] is True
        assert body["upload_interval_minutes"] == 10

    async def test_update_settings_invalid_interval(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            token = await _register_and_mobile_login(c, _email())
            resp = await c.put(
                "/api/integrations/tandem/cloud-upload/settings",
                json={"enabled": True, "interval_minutes": 7},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 422  # Validation error


class TestAuthenticateFresh:
    """Test _authenticate_fresh extracts correct attributes from TandemSourceApi."""

    @pytest.mark.asyncio
    async def test_extracts_access_token_camelcase(self):
        """Verify we read api.accessToken (camelCase), not _access_token."""
        mock_api = MagicMock()
        mock_api.accessToken = "test-token-12345"
        mock_api.accessTokenExpiresAt = None
        mock_api.pumperId = "pump-123"

        with patch(
            "tconnectsync.api.tandemsource.TandemSourceApi",
            return_value=mock_api,
        ):
            result = await _authenticate_fresh("user@test.com", "pass", "US")

        assert result["access_token"] == "test-token-12345"
        assert result["pumper_id"] == "pump-123"
        assert result["refresh_token"] is None

    @pytest.mark.asyncio
    async def test_raises_if_no_access_token(self):
        """Verify clear error if accessToken is missing/None."""
        mock_api = MagicMock()
        mock_api.accessToken = None
        mock_api.accessTokenExpiresAt = None
        mock_api.pumperId = None

        with (
            patch(
                "tconnectsync.api.tandemsource.TandemSourceApi",
                return_value=mock_api,
            ),
            pytest.raises(RuntimeError, match="accessToken"),
        ):
            await _authenticate_fresh("user@test.com", "pass", "US")

    @pytest.mark.asyncio
    async def test_defaults_expires_in_when_no_expiry(self):
        """Verify fallback to 3600 when accessTokenExpiresAt is None."""
        mock_api = MagicMock()
        mock_api.accessToken = "tok"
        mock_api.accessTokenExpiresAt = None
        mock_api.pumperId = None

        with patch(
            "tconnectsync.api.tandemsource.TandemSourceApi",
            return_value=mock_api,
        ):
            result = await _authenticate_fresh("user@test.com", "pass", "US")

        assert result["expires_in"] == 3600

    @pytest.mark.asyncio
    async def test_computes_real_expires_in(self):
        """Verify computed TTL from arrow datetime."""
        import arrow

        future = arrow.get().shift(minutes=+30)
        mock_api = MagicMock()
        mock_api.accessToken = "tok"
        mock_api.accessTokenExpiresAt = future
        mock_api.pumperId = None

        with patch(
            "tconnectsync.api.tandemsource.TandemSourceApi",
            return_value=mock_api,
        ):
            result = await _authenticate_fresh("user@test.com", "pass", "US")

        # Should be approximately 1800 seconds (30 minutes), allow some slack
        assert 1750 < result["expires_in"] < 1850


async def _seed_upload_fixtures(
    session,
    *,
    region: str = "US",
    seq_numbers=(100, 101, 102, 103),
) -> uuid.UUID:
    """Create a user + Tandem credential + pump hardware + raw events.

    Returns the new user's id. Uses ``flush`` (not commit) so the caller's
    transaction lifecycle stays intact -- ``upload_to_tandem`` will issue
    its own commits, and the db_session fixture will roll the whole thing
    back on teardown.
    """
    email = f"upload_regression_{uuid.uuid4().hex[:10]}@example.com"
    user = User(email=email, hashed_password="not-a-real-hash")
    session.add(user)
    await session.flush()

    credential = IntegrationCredential(
        user_id=user.id,
        integration_type=IntegrationType.TANDEM,
        encrypted_username=encrypt_credential("tandem@example.com"),
        encrypted_password=encrypt_credential("tandem-password"),
        region=region,
        status=IntegrationStatus.CONNECTED,
    )
    session.add(credential)

    pump_info = PumpHardwareInfo(
        user_id=user.id,
        serial_number=12345678,
        model_number=99,
        part_number=11111,
        pump_rev="3.0",
        arm_sw_ver=50000,
        msp_sw_ver=50000,
        config_a_bits=0,
        config_b_bits=0,
        pcba_sn=99999,
        pcba_rev="A",
        pump_features={"controlIQ": True},
    )
    session.add(pump_info)

    for seq in seq_numbers:
        session.add(
            PumpRawEvent(
                user_id=user.id,
                sequence_number=seq,
                raw_bytes_b64=base64.b64encode(f"event-{seq}".encode()).decode(),
                event_type_id=280,
                pump_time_seconds=1_000_000 + seq,
                uploaded_to_tandem=False,
            )
        )
    await session.flush()
    return user.id


async def _own_session():
    """Open a fresh session that is fully owned by the test.

    Sidesteps the ``db_session`` fixture's rollback-on-teardown semantics --
    the upload service issues commits, so the test needs to be in charge of
    cleanup (we just leak the test data; the schema is recreated per session).
    """
    return get_session_maker()()


class TestUploadEmptySetRegression:
    """Regression tests for the "12390 pending, 0 uploaded" empty-set bug.

    Before the fix, ``upload_to_tandem`` filtered events by
    ``sequence_number > max(cloud_max, local_max)``. If the user also ran the
    official t:connect app, Tandem's cloud reported a high ``maxPumpEventIndex``
    and we silently dropped every event that we had stored. The pending-count
    query in the status endpoint had no such filter, so the UI showed thousands
    of pending events while ``Upload Now`` reported "No events to upload".
    """

    @pytest.mark.asyncio
    async def test_upload_proceeds_when_cloud_max_exceeds_local_sequence(self):
        """The bug repro: cloud's high-water mark is higher than every stored
        event's sequence_number, but uploadable events still get uploaded."""
        async with await _own_session() as session:
            user_id = await _seed_upload_fixtures(
                session, region="US", seq_numbers=(10, 11, 12, 13)
            )
            await session.commit()

        mock_api = MagicMock()
        mock_api.accessToken = "fake-access-token"
        mock_api.accessTokenExpiresAt = None
        mock_api.pumperId = "pumper-abc"

        post_mock = AsyncMock(return_value={})

        async with await _own_session() as session:
            with (
                patch(
                    "tconnectsync.api.tandemsource.TandemSourceApi",
                    return_value=mock_api,
                ),
                patch(
                    "src.services.tandem_upload.fetch_tandem_config",
                    AsyncMock(
                        return_value={
                            "postUploadUrl": "https://example.test/upload",
                            "getLastEventUploadedUrl": "https://example.test/last",
                        }
                    ),
                ),
                # Cloud reports max=999999 -- way higher than our seeded seq 10-13.
                patch(
                    "src.services.tandem_upload.get_last_event_uploaded",
                    AsyncMock(return_value=999_999),
                ),
                patch(
                    "src.services.tandem_upload._post_upload",
                    post_mock,
                ),
            ):
                result = await upload_to_tandem(session, user_id)

        # Before the fix this would be 0. After the fix the upload proceeds
        # because the bad sequence_number filter has been removed.
        assert result["status"] == "success", result
        assert result["events_uploaded"] == 4, result
        assert post_mock.await_count == 1

        async with await _own_session() as session:
            rows = (
                (
                    await session.execute(
                        select(PumpRawEvent).where(PumpRawEvent.user_id == user_id)
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 4
            assert all(r.uploaded_to_tandem for r in rows)

    @pytest.mark.asyncio
    async def test_upload_returns_success_when_truly_nothing_pending(self):
        """No raw events at all -> success with events_uploaded=0."""
        async with await _own_session() as session:
            user_id = await _seed_upload_fixtures(session, region="US", seq_numbers=())
            await session.commit()

        mock_api = MagicMock()
        mock_api.accessToken = "tok"
        mock_api.accessTokenExpiresAt = None
        mock_api.pumperId = "pumper-x"

        async with await _own_session() as session:
            with (
                patch(
                    "tconnectsync.api.tandemsource.TandemSourceApi",
                    return_value=mock_api,
                ),
                patch(
                    "src.services.tandem_upload.fetch_tandem_config",
                    AsyncMock(
                        return_value={
                            "postUploadUrl": "https://example.test/upload",
                            "getLastEventUploadedUrl": "https://example.test/last",
                        }
                    ),
                ),
                patch(
                    "src.services.tandem_upload.get_last_event_uploaded",
                    AsyncMock(return_value=0),
                ),
            ):
                result = await upload_to_tandem(session, user_id)

        assert result["status"] == "success"
        assert result["events_uploaded"] == 0
        assert "no pending" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_legacy_region_raises_legacy_error(self):
        """A credential with region='EU' triggers the re-select prompt."""
        async with await _own_session() as session:
            user_id = await _seed_upload_fixtures(
                session, region="EU", seq_numbers=(1, 2)
            )
            await session.commit()

        async with await _own_session() as session:
            with pytest.raises(TandemLegacyRegionError):
                await upload_to_tandem(session, user_id)

        async with await _own_session() as session:
            state = (
                await session.execute(
                    select(TandemUploadState).where(
                        TandemUploadState.user_id == user_id
                    )
                )
            ).scalar_one_or_none()
            assert state is not None
            assert state.last_upload_status == "needs_country"
            assert state.last_error  # populated

    @pytest.mark.asyncio
    async def test_reset_requeues_uploaded_events(self):
        """``reset_tandem_upload_state`` flips uploaded_to_tandem back to False."""
        async with await _own_session() as session:
            user_id = await _seed_upload_fixtures(
                session, region="US", seq_numbers=(1, 2, 3)
            )
            # Mark them all as uploaded
            rows = (
                (
                    await session.execute(
                        select(PumpRawEvent).where(PumpRawEvent.user_id == user_id)
                    )
                )
                .scalars()
                .all()
            )
            for r in rows:
                r.uploaded_to_tandem = True
            await session.commit()

        async with await _own_session() as session:
            result = await reset_tandem_upload_state(session, user_id)
            assert result["events_requeued"] == 3

        async with await _own_session() as session:
            rows = (
                (
                    await session.execute(
                        select(PumpRawEvent).where(PumpRawEvent.user_id == user_id)
                    )
                )
                .scalars()
                .all()
            )
            assert all(not r.uploaded_to_tandem for r in rows)


class TestUploadSilentSuccessRegression:
    """Regression tests for the v0.8.2 silent-success bug.

    Production user pressed "Upload Now" three times, each returned
    "500 events sent to tandem" success, the local counter went down,
    but no events ever appeared in the official t:connect web portal.
    Two value-level payload bugs and one missing response-body check
    were responsible.
    """

    @pytest.mark.asyncio
    async def test_upload_refuses_when_pumper_id_missing(self):
        """Empty pumper_id means deviceAssignmentId would be ``""`` in the
        upload payload, which Tandem accepts (200 OK) but silently drops.
        Refuse to upload and surface a re-connect prompt instead."""
        async with await _own_session() as session:
            user_id = await _seed_upload_fixtures(
                session, region="US", seq_numbers=(1, 2)
            )
            await session.commit()

        mock_api = MagicMock()
        mock_api.accessToken = "tok"
        mock_api.accessTokenExpiresAt = None
        mock_api.pumperId = None  # <-- the bug condition

        post_mock = AsyncMock(return_value={})

        async with await _own_session() as session:
            with (
                patch(
                    "tconnectsync.api.tandemsource.TandemSourceApi",
                    return_value=mock_api,
                ),
                patch(
                    "src.services.tandem_upload.fetch_tandem_config",
                    AsyncMock(
                        return_value={
                            "postUploadUrl": "https://example.test/upload",
                            "getLastEventUploadedUrl": "https://example.test/last",
                        }
                    ),
                ),
                patch(
                    "src.services.tandem_upload.get_last_event_uploaded",
                    AsyncMock(return_value=0),
                ),
                patch(
                    "src.services.tandem_upload._post_upload",
                    post_mock,
                ),
            ):
                result = await upload_to_tandem(session, user_id)

        assert result["status"] == "error", result
        assert result["events_uploaded"] == 0
        assert "pumper id" in result["message"].lower()
        # And critically: _post_upload must NOT have been called -- we should
        # refuse to send the payload at all rather than risk a silent drop.
        assert post_mock.await_count == 0

    @pytest.mark.asyncio
    async def test_post_upload_logs_non_zero_processing_status(self, caplog):
        """``processingStatus`` is documented for the getLastEventUploaded
        endpoint but not for upload responses; we log non-zero values
        when they appear so production traces can confirm whether Tandem
        actually returns the field for uploads, but do NOT fail-close on
        it (avoids hard-rejecting valid uploads against a schema variance
        we haven't observed in the wild).
        """
        import logging

        from src.services.tandem_upload import _post_upload

        class _MockResp:
            status_code = 200
            content = b'{"processingStatus": 1}'
            text = '{"processingStatus": 1}'
            headers = {"Content-Type": "application/json"}

            def raise_for_status(self):
                return None

            def json(self):
                return {"processingStatus": 1}

        class _MockClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def post(self, url, content, headers):
                return _MockResp()

        with (
            patch("httpx.AsyncClient", lambda **kwargs: _MockClient()),
            caplog.at_level(logging.WARNING),
        ):
            result = await _post_upload(
                access_token="t",
                config={"postUploadUrl": "https://x.test/u"},
                payload={"client": "mHealth", "package": {}},
            )
        # Returns the body (no exception), but emits a WARNING for audit
        assert result == {"processingStatus": 1}
        assert "non-zero processingStatus" in caplog.text

    @pytest.mark.asyncio
    async def test_post_upload_raises_on_per_event_errors(self):
        """A 200 with a populated ``errors`` array IS a hard failure --
        Tandem accepted the request but rejected individual events. We
        refuse to mark them as uploaded so they stay queued for retry.
        """
        from src.services.tandem_upload import _post_upload

        class _MockResp:
            status_code = 200
            content = b'{"errors": [{"code": "bad"}]}'
            text = '{"errors": [{"code": "bad"}]}'
            headers = {"Content-Type": "application/json"}

            def raise_for_status(self):
                return None

            def json(self):
                return {"errors": [{"code": "bad"}]}

        class _MockClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def post(self, url, content, headers):
                return _MockResp()

        with (
            patch("httpx.AsyncClient", lambda **kwargs: _MockClient()),
            pytest.raises(RuntimeError, match="per-event error"),
        ):
            await _post_upload(
                access_token="t",
                config={"postUploadUrl": "https://x.test/u"},
                payload={"client": "mHealth", "package": {}},
            )


class TestSchedulerStartupLogs:
    """The scheduler must announce its enable/disable state at startup so
    production "scheduler not firing" reports can be diagnosed by a single
    log grep without code spelunking."""

    def test_logs_disabled_state_for_tandem_upload_and_sync(self, caplog, monkeypatch):
        import logging

        import src.services.scheduler as scheduler_module
        from src.config import settings as global_settings

        # ``monkeypatch.setattr`` auto-restores even if the test crashes,
        # which is safer than try/finally under pytest-xdist parallel
        # workers that share the same global settings singleton.
        monkeypatch.setattr(global_settings, "tandem_upload_enabled", False)
        monkeypatch.setattr(global_settings, "tandem_sync_enabled", False)
        # Reset the module-level singleton so start_scheduler() runs the
        # registration block again instead of short-circuiting.
        original_scheduler = scheduler_module.scheduler
        monkeypatch.setattr(scheduler_module, "scheduler", None)
        try:
            # Capture across all loggers; our structlog-wrapped logger routes
            # via stdlib logging but the named filter on caplog.at_level
            # doesn't always catch the wrapped path.
            with caplog.at_level(logging.WARNING):
                # start_scheduler() ends with scheduler.start() which needs a
                # running event loop. We only care about the registration
                # log lines emitted before that, so swallow the RuntimeError.
                try:
                    scheduler_module.start_scheduler()
                except RuntimeError:
                    pass
            # `caplog.text` is the joined human-readable rendering of all
            # captured records and is the most reliable way to assert
            # against structlog output.
            assert "Tandem cloud upload scheduler DISABLED" in caplog.text
            assert "Tandem sync scheduler DISABLED" in caplog.text
        finally:
            if (
                scheduler_module.scheduler is not None
                and scheduler_module.scheduler is not original_scheduler
            ):
                try:
                    scheduler_module.scheduler.shutdown(wait=False)
                except Exception:
                    pass
