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
