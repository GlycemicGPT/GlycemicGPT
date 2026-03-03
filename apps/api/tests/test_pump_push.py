"""Story 16.5: Tests for mobile login and pump push endpoints."""

import uuid
from datetime import UTC, datetime, timedelta

from httpx import ASGITransport, AsyncClient

from src.main import app
from src.schemas.pump import PumpEventPushItem


def _email() -> str:
    return f"pump_{uuid.uuid4().hex[:8]}@test.com"


async def _register_and_mobile_login(
    client: AsyncClient, email: str, password: str = "TestPass1"
) -> str:
    """Register a user and return a bearer token via mobile login."""
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


class TestMobileLogin:
    async def test_mobile_login_returns_bearer_token(self):
        email = _email()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            await c.post(
                "/api/auth/register",
                json={"email": email, "password": "TestPass1"},
            )
            resp = await c.post(
                "/api/auth/mobile/login",
                json={"email": email, "password": "TestPass1"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"
        assert body["expires_in"] > 0
        assert body["user"]["email"] == email

    async def test_mobile_login_invalid_credentials(self):
        email = _email()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            await c.post(
                "/api/auth/register",
                json={"email": email, "password": "TestPass1"},
            )
            resp = await c.post(
                "/api/auth/mobile/login",
                json={"email": email, "password": "WrongPass1"},
            )
        assert resp.status_code == 401

    async def test_bearer_token_works_on_me_endpoint(self):
        email = _email()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            token = await _register_and_mobile_login(c, email)
            resp = await c.get(
                "/api/auth/me",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        assert resp.json()["email"] == email


class TestPumpPush:
    async def test_push_single_event(self):
        email = _email()
        now = datetime.now(UTC).isoformat()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            token = await _register_and_mobile_login(c, email)
            resp = await c.post(
                "/api/integrations/pump/push",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "events": [
                        {
                            "event_type": "basal",
                            "event_timestamp": now,
                            "units": 0.5,
                            "is_automated": True,
                            "pump_activity_mode": "none",
                        }
                    ],
                    "source": "mobile",
                },
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["accepted"] == 1
        assert body["duplicates"] == 0

    async def test_push_duplicate_events(self):
        email = _email()
        now = datetime.now(UTC).isoformat()
        event = {
            "event_type": "bolus",
            "event_timestamp": now,
            "units": 3.5,
            "is_automated": False,
        }
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            token = await _register_and_mobile_login(c, email)
            headers = {"Authorization": f"Bearer {token}"}

            resp1 = await c.post(
                "/api/integrations/pump/push",
                headers=headers,
                json={"events": [event], "source": "mobile"},
            )
            assert resp1.status_code == 200
            assert resp1.json()["accepted"] == 1

            resp2 = await c.post(
                "/api/integrations/pump/push",
                headers=headers,
                json={"events": [event], "source": "mobile"},
            )
            assert resp2.status_code == 200
            assert resp2.json()["accepted"] == 0
            assert resp2.json()["duplicates"] == 1

    async def test_push_unauthenticated(self):
        now = datetime.now(UTC).isoformat()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            resp = await c.post(
                "/api/integrations/pump/push",
                json={
                    "events": [
                        {"event_type": "basal", "event_timestamp": now, "units": 0.5}
                    ],
                    "source": "mobile",
                },
            )
        assert resp.status_code == 401

    async def test_push_empty_events_rejected(self):
        email = _email()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            token = await _register_and_mobile_login(c, email)
            resp = await c.post(
                "/api/integrations/pump/push",
                headers={"Authorization": f"Bearer {token}"},
                json={"events": [], "source": "mobile"},
            )
        assert resp.status_code == 422

    async def test_push_mixed_batch(self):
        email = _email()
        base = datetime.now(UTC)
        events = [
            {
                "event_type": "bg_reading",
                "event_timestamp": (base - timedelta(minutes=2)).isoformat(),
                "iob_at_event": 2.5,
            },
            {
                "event_type": "basal",
                "event_timestamp": (base - timedelta(minutes=1)).isoformat(),
                "units": 0.8,
                "is_automated": True,
                "pump_activity_mode": "sleep",
            },
            {
                "event_type": "correction",
                "event_timestamp": base.isoformat(),
                "units": 1.2,
                "is_automated": True,
            },
        ]
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            token = await _register_and_mobile_login(c, email)
            resp = await c.post(
                "/api/integrations/pump/push",
                headers={"Authorization": f"Bearer {token}"},
                json={"events": events, "source": "mobile"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["accepted"] == 3
        assert body["duplicates"] == 0

    async def test_push_future_timestamp_rejected(self):
        email = _email()
        future = (datetime.now(UTC) + timedelta(minutes=10)).isoformat()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            token = await _register_and_mobile_login(c, email)
            resp = await c.post(
                "/api/integrations/pump/push",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "events": [
                        {"event_type": "basal", "event_timestamp": future, "units": 0.5}
                    ],
                    "source": "mobile",
                },
            )
        assert resp.status_code == 422


class TestPumpActivityModeBackwardsCompat:
    """Tests for PumpEventPushItem backwards-compat validator."""

    def test_old_control_iq_mode_standard_maps_to_none(self):
        """Old clients sending control_iq_mode='standard' get pump_activity_mode='none'."""
        now = datetime.now(UTC).isoformat()
        item = PumpEventPushItem(
            event_type="basal",
            event_timestamp=now,
            units=0.5,
            control_iq_mode="standard",
        )
        assert item.pump_activity_mode == "none"

    def test_old_control_iq_mode_sleep_maps_directly(self):
        """Old clients sending control_iq_mode='sleep' maps as-is."""
        now = datetime.now(UTC).isoformat()
        item = PumpEventPushItem(
            event_type="basal",
            event_timestamp=now,
            units=0.5,
            control_iq_mode="sleep",
        )
        assert item.pump_activity_mode == "sleep"

    def test_new_field_takes_precedence(self):
        """When both fields present, pump_activity_mode wins."""
        now = datetime.now(UTC).isoformat()
        item = PumpEventPushItem(
            event_type="basal",
            event_timestamp=now,
            units=0.5,
            pump_activity_mode="exercise",
            control_iq_mode="sleep",
        )
        assert item.pump_activity_mode == "exercise"

    def test_no_mode_fields_yields_none(self):
        """When neither field is set, pump_activity_mode is None."""
        now = datetime.now(UTC).isoformat()
        item = PumpEventPushItem(
            event_type="basal",
            event_timestamp=now,
            units=0.5,
        )
        assert item.pump_activity_mode is None
