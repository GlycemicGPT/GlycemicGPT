"""Story 30.1: Tests for aggregate statistics endpoints."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database import get_db
from src.main import app
from src.models.glucose import GlucoseReading, TrendDirection
from src.models.pump_data import PumpEvent, PumpEventType


def unique_email(prefix: str = "stats") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


async def register_and_login(client: AsyncClient) -> tuple[str, str]:
    """Register a test user and return (session_cookie, user_id)."""
    email = unique_email()
    password = "SecurePass123"
    reg = await client.post(
        "/api/auth/register", json={"email": email, "password": password}
    )
    assert reg.status_code == 201, f"Registration failed: {reg.text}"
    login = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, f"Login failed: {login.text}"
    cookie = login.cookies.get(settings.jwt_cookie_name)
    assert cookie is not None, "No session cookie returned"
    # Get user ID from /me endpoint
    me = await client.get("/api/auth/me", cookies={settings.jwt_cookie_name: cookie})
    assert me.status_code == 200, f"Failed to get user: {me.text}"
    user_id = me.json()["id"]
    return cookie, user_id


async def seed_glucose(
    db: AsyncSession,
    user_id: str,
    count: int = 50,
    extra_values: list[int] | None = None,
):
    """Insert test glucose readings spanning the last 24h.

    Args:
        extra_values: Additional explicit glucose values to insert
            (e.g., boundary values like 40, 400).
    """
    now = datetime.now(UTC)
    uid = uuid.UUID(user_id)
    for i in range(count):
        ts = now - timedelta(minutes=i * 5)
        # Vary values: 80-200 range
        value = 80 + (i * 3) % 120
        reading = GlucoseReading(
            user_id=uid,
            value=value,
            reading_timestamp=ts,
            trend=TrendDirection.FLAT,
            trend_rate=0.0,
            received_at=ts,
            source="test",
        )
        db.add(reading)
    # Insert explicit extra values (for boundary testing)
    for j, val in enumerate(extra_values or []):
        ts = now - timedelta(minutes=(count + j) * 5)
        db.add(
            GlucoseReading(
                user_id=uid,
                value=val,
                reading_timestamp=ts,
                trend=TrendDirection.FLAT,
                trend_rate=0.0,
                received_at=ts,
                source="test",
            )
        )
    await db.commit()


async def seed_pump_events(db: AsyncSession, user_id: str):
    """Insert test pump events spanning the last 7 days."""
    now = datetime.now(UTC)
    uid = uuid.UUID(user_id)

    # Basal events (one per hour for 7 days)
    for h in range(168):
        ts = now - timedelta(hours=h)
        db.add(
            PumpEvent(
                user_id=uid,
                event_type=PumpEventType.BASAL,
                event_timestamp=ts,
                units=0.8,
                is_automated=True,
                received_at=ts,
                source="test",
            )
        )

    # Bolus events (3 per day for 7 days)
    for d in range(7):
        for meal_h in [8, 12, 18]:
            ts = now - timedelta(days=d, hours=24 - meal_h)
            db.add(
                PumpEvent(
                    user_id=uid,
                    event_type=PumpEventType.BOLUS,
                    event_timestamp=ts,
                    units=4.5,
                    is_automated=False,
                    received_at=ts,
                    source="test",
                )
            )

    # Correction events (2 per day)
    for d in range(7):
        for h_offset in [10, 15]:
            ts = now - timedelta(days=d, hours=24 - h_offset)
            db.add(
                PumpEvent(
                    user_id=uid,
                    event_type=PumpEventType.CORRECTION,
                    event_timestamp=ts,
                    units=1.2,
                    is_automated=True,
                    control_iq_reason="high_bg",
                    received_at=ts,
                    source="test",
                )
            )

    await db.commit()


@pytest.mark.asyncio
class TestGlucoseStats:
    async def test_glucose_stats_no_data(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie, _ = await register_and_login(client)
            resp = await client.get(
                "/api/integrations/glucose/stats",
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["readings_count"] == 0
        assert data["mean_glucose"] == 0.0
        assert data["gmi"] == 0.0

    async def test_glucose_stats_with_data(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie, user_id = await register_and_login(client)

            # Seed data
            async for db in get_db():
                await seed_glucose(db, user_id, count=50)
                break

            resp = await client.get(
                "/api/integrations/glucose/stats?minutes=1440",
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["readings_count"] == 50
        assert data["mean_glucose"] > 0
        assert data["std_dev"] >= 0
        assert 0 <= data["cv_pct"] <= 200
        assert data["gmi"] > 0
        assert 0 < data["cgm_active_pct"] <= 100

    async def test_glucose_stats_unauthenticated(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/integrations/glucose/stats")
        assert resp.status_code == 401

    async def test_glucose_stats_minutes_below_minimum(self):
        """Verify minutes < 60 returns 422."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie, _ = await register_and_login(client)
            resp = await client.get(
                "/api/integrations/glucose/stats?minutes=59",
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 422

    async def test_glucose_stats_boundary_values(self):
        """Verify 40 and 400 mg/dL boundary values are included in stats."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie, user_id = await register_and_login(client)

            async for db in get_db():
                await seed_glucose(db, user_id, count=0, extra_values=[40, 400])
                break

            resp = await client.get(
                "/api/integrations/glucose/stats?minutes=1440",
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["readings_count"] == 2
        # Mean of 40 and 400 = 220
        assert abs(data["mean_glucose"] - 220.0) < 1.0

    async def test_glucose_stats_out_of_range_excluded(self):
        """Verify readings outside 20-500 mg/dL are excluded from stats."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie, user_id = await register_and_login(client)

            # Insert readings: 10 (below range), 100 (valid), 600 (above range)
            async for db in get_db():
                await seed_glucose(db, user_id, count=0, extra_values=[10, 100, 600])
                break

            resp = await client.get(
                "/api/integrations/glucose/stats?minutes=1440",
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 200
        data = resp.json()
        # Only the 100 mg/dL reading should be counted
        assert data["readings_count"] == 1
        assert abs(data["mean_glucose"] - 100.0) < 1.0

    async def test_glucose_stats_minutes_above_maximum(self):
        """Verify minutes > 43200 returns 422."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie, _ = await register_and_login(client)
            resp = await client.get(
                "/api/integrations/glucose/stats?minutes=43201",
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 422


@pytest.mark.asyncio
class TestGlucosePercentiles:
    async def test_percentiles_no_data(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie, _ = await register_and_login(client)
            resp = await client.get(
                "/api/integrations/glucose/percentiles?days=7",
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["buckets"]) == 24
        assert data["readings_count"] == 0

    async def test_percentiles_with_data(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie, user_id = await register_and_login(client)

            async for db in get_db():
                await seed_glucose(db, user_id, count=200)
                break

            resp = await client.get(
                "/api/integrations/glucose/percentiles?days=7",
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["buckets"]) == 24
        assert data["readings_count"] > 0
        # Check percentile ordering for buckets with data
        for bucket in data["buckets"]:
            if bucket["count"] > 0:
                assert bucket["p10"] <= bucket["p25"]
                assert bucket["p25"] <= bucket["p50"]
                assert bucket["p50"] <= bucket["p75"]
                assert bucket["p75"] <= bucket["p90"]

    async def test_percentiles_boundary_values(self):
        """Verify 40 and 400 mg/dL boundary values are included in percentile data."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie, user_id = await register_and_login(client)

            async for db in get_db():
                await seed_glucose(db, user_id, count=50, extra_values=[40, 400])
                break

            resp = await client.get(
                "/api/integrations/glucose/percentiles?days=7",
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["readings_count"] == 52  # 50 + 2 boundary values
        # Verify percentiles are computed and properly ordered across buckets
        populated = [b for b in data["buckets"] if b["count"] > 0]
        assert len(populated) > 0, "Expected at least one bucket with data"
        for bucket in populated:
            assert bucket["p10"] <= bucket["p25"]
            assert bucket["p25"] <= bucket["p50"]
            assert bucket["p50"] <= bucket["p75"]
            assert bucket["p75"] <= bucket["p90"]
        # With boundary values at 40/400 alongside normal 80-200 readings,
        # the full range of p10-to-p90 across all buckets should span a
        # wider range than a tight normal distribution would.
        all_p10 = [b["p10"] for b in populated]
        all_p90 = [b["p90"] for b in populated]
        full_range = max(all_p90) - min(all_p10)
        assert full_range > 50, (
            f"Expected meaningful percentile spread, got {full_range}"
        )

    async def test_percentiles_with_timezone(self):
        """Verify tz parameter is accepted and produces valid results."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie, user_id = await register_and_login(client)

            async for db in get_db():
                await seed_glucose(db, user_id, count=100)
                break

            resp = await client.get(
                "/api/integrations/glucose/percentiles?days=7&tz=America/Chicago",
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["buckets"]) == 24
        assert data["readings_count"] > 0

    async def test_percentiles_invalid_timezone(self):
        """Verify invalid tz returns 422."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie, _ = await register_and_login(client)
            resp = await client.get(
                "/api/integrations/glucose/percentiles?days=7&tz=Not/A/Zone",
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 422

    async def test_percentiles_days_below_minimum(self):
        """Verify days < 7 returns 422."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie, _ = await register_and_login(client)
            resp = await client.get(
                "/api/integrations/glucose/percentiles?days=6",
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 422

    async def test_percentiles_unauthenticated(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/integrations/glucose/percentiles?days=7")
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestInsulinSummary:
    async def test_insulin_summary_no_data(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie, _ = await register_and_login(client)
            resp = await client.get(
                "/api/integrations/insulin/summary",
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["tdd"] == 0.0
        assert data["basal_pct"] == 0.0
        assert data["bolus_pct"] == 0.0

    async def test_insulin_summary_with_data(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie, user_id = await register_and_login(client)

            async for db in get_db():
                await seed_pump_events(db, user_id)
                break

            resp = await client.get(
                "/api/integrations/insulin/summary?days=7",
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["tdd"] > 0
        assert data["basal_units"] > 0
        assert data["bolus_units"] > 0
        assert data["bolus_count"] == 21  # 3/day * 7 days
        assert data["correction_count"] == 14  # 2/day * 7 days
        assert abs(data["basal_pct"] + data["bolus_pct"] - 100) < 0.2

    async def test_insulin_summary_days_below_minimum(self):
        """Verify days < 1 returns 422."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie, _ = await register_and_login(client)
            resp = await client.get(
                "/api/integrations/insulin/summary?days=0",
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 422

    async def test_insulin_summary_unauthenticated(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/integrations/insulin/summary")
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestBolusReview:
    async def test_bolus_review_no_data(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie, _ = await register_and_login(client)
            resp = await client.get(
                "/api/integrations/bolus/review",
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_count"] == 0
        assert data["boluses"] == []

    async def test_bolus_review_with_data(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie, user_id = await register_and_login(client)

            async for db in get_db():
                await seed_pump_events(db, user_id)
                break

            resp = await client.get(
                "/api/integrations/bolus/review?days=7&limit=10",
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_count"] == 35  # 21 bolus + 14 correction
        assert len(data["boluses"]) == 10  # Limited to 10
        # Verify ordering (newest first)
        timestamps = [b["event_timestamp"] for b in data["boluses"]]
        assert timestamps == sorted(timestamps, reverse=True)

    async def test_bolus_review_unauthenticated(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/integrations/bolus/review")
        assert resp.status_code == 401

    async def test_bolus_review_pagination(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie, user_id = await register_and_login(client)

            async for db in get_db():
                await seed_pump_events(db, user_id)
                break

            page1 = await client.get(
                "/api/integrations/bolus/review?days=7&limit=5&offset=0",
                cookies={settings.jwt_cookie_name: cookie},
            )
            page2 = await client.get(
                "/api/integrations/bolus/review?days=7&limit=5&offset=5",
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert page1.status_code == 200
        assert page2.status_code == 200
        p1_ts = [b["event_timestamp"] for b in page1.json()["boluses"]]
        p2_ts = [b["event_timestamp"] for b in page2.json()["boluses"]]
        # No overlap between pages
        assert not set(p1_ts) & set(p2_ts)
        # Page 1 should be newer than page 2
        assert p1_ts == sorted(p1_ts, reverse=True)
        assert p2_ts == sorted(p2_ts, reverse=True)
        assert p1_ts[0] > p2_ts[0]


@pytest.mark.asyncio
class TestCrossUserIsolation:
    """Verify users cannot see each other's data across all endpoints."""

    async def test_glucose_stats_isolation(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie_a, user_a = await register_and_login(client)
            cookie_b, _ = await register_and_login(client)

            # Seed data only for user A
            async for db in get_db():
                await seed_glucose(db, user_a, count=50)
                break

            resp_a = await client.get(
                "/api/integrations/glucose/stats?minutes=1440",
                cookies={settings.jwt_cookie_name: cookie_a},
            )
            resp_b = await client.get(
                "/api/integrations/glucose/stats?minutes=1440",
                cookies={settings.jwt_cookie_name: cookie_b},
            )

        assert resp_a.json()["readings_count"] == 50
        assert resp_b.json()["readings_count"] == 0

    async def test_insulin_summary_isolation(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie_a, user_a = await register_and_login(client)
            cookie_b, _ = await register_and_login(client)

            async for db in get_db():
                await seed_pump_events(db, user_a)
                break

            resp_a = await client.get(
                "/api/integrations/insulin/summary?days=7",
                cookies={settings.jwt_cookie_name: cookie_a},
            )
            resp_b = await client.get(
                "/api/integrations/insulin/summary?days=7",
                cookies={settings.jwt_cookie_name: cookie_b},
            )

        assert resp_a.json()["tdd"] > 0
        assert resp_b.json()["tdd"] == 0.0

    async def test_bolus_review_isolation(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie_a, user_a = await register_and_login(client)
            cookie_b, _ = await register_and_login(client)

            async for db in get_db():
                await seed_pump_events(db, user_a)
                break

            resp_a = await client.get(
                "/api/integrations/bolus/review?days=7",
                cookies={settings.jwt_cookie_name: cookie_a},
            )
            resp_b = await client.get(
                "/api/integrations/bolus/review?days=7",
                cookies={settings.jwt_cookie_name: cookie_b},
            )

        assert resp_a.json()["total_count"] == 35
        assert resp_b.json()["total_count"] == 0
        assert resp_b.json()["boluses"] == []
