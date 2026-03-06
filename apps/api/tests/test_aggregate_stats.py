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


def _boundary_cutoff(days: int, boundary_hour: int = 0) -> datetime:
    """Compute the boundary-aligned cutoff matching the backend logic.

    The insulin summary and bolus review endpoints now align their query
    window to the day boundary hour rather than using ``now - timedelta(days)``.
    Test data must be placed after this cutoff to be counted.
    """
    now = datetime.now(UTC)
    today_boundary = now.replace(hour=boundary_hour, minute=0, second=0, microsecond=0)
    if now < today_boundary:
        effective_boundary = today_boundary - timedelta(days=1)
    else:
        effective_boundary = today_boundary
    return effective_boundary - timedelta(days=max(days - 1, 0))


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
    """Insert test pump events spanning the last 7 days.

    Events are placed relative to the boundary-aligned cutoff so they
    always fall within the 7-day query window.  Only 6 *complete* days
    are seeded (the current partial day is skipped) to avoid timing
    flakes when the test runs near midnight.

    Totals: 18 boluses (3/day * 6), 12 corrections (2/day * 6).
    """
    uid = uuid.UUID(user_id)
    cutoff = _boundary_cutoff(days=7)

    # Basal events (one per hour for 6 complete days = 144 hours)
    for h in range(144):
        ts = cutoff + timedelta(hours=h + 1)
        db.add(
            PumpEvent(
                user_id=uid,
                event_type=PumpEventType.BASAL,
                event_timestamp=ts,
                units=0.8,
                is_automated=True,
                received_at=ts,
                source="mobile",
            )
        )

    # Bolus events (3 per day for 6 complete days)
    for d in range(6):
        day_start = cutoff + timedelta(days=d)
        for meal_h in [8, 12, 18]:
            ts = day_start + timedelta(hours=meal_h)
            db.add(
                PumpEvent(
                    user_id=uid,
                    event_type=PumpEventType.BOLUS,
                    event_timestamp=ts,
                    units=4.5,
                    is_automated=False,
                    received_at=ts,
                    source="mobile",
                )
            )

    # Correction events (2 per day for 6 complete days)
    for d in range(6):
        day_start = cutoff + timedelta(days=d)
        for h_offset in [10, 15]:
            ts = day_start + timedelta(hours=h_offset)
            db.add(
                PumpEvent(
                    user_id=uid,
                    event_type=PumpEventType.CORRECTION,
                    event_timestamp=ts,
                    units=1.2,
                    is_automated=True,
                    control_iq_reason="high_bg",
                    received_at=ts,
                    source="mobile",
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
        # Expected: basal ~19.1 U/day (0.8 U/hr * 24h), bolus 13.5 + correction 2.4
        # = TDD ~35 U/day.  Seed covers 6 complete days (see seed_pump_events).
        assert 25 < data["tdd"] < 45, f"TDD out of range: {data['tdd']}"
        assert data["basal_units"] > 0
        assert data["bolus_units"] > 0
        assert data["bolus_count"] == 18  # 3/day * 6 complete days
        assert data["correction_count"] == 12  # 2/day * 6 complete days
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

    async def test_basal_rapid_polling_not_overcounted(self):
        """Mobile BLE polling stores rate every ~15s; SUM would massively overcount."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie, user_id = await register_and_login(client)

            async for db in get_db():
                now = datetime.now(UTC)
                uid = uuid.UUID(user_id)
                cutoff = _boundary_cutoff(days=1)
                base_ts = cutoff + timedelta(minutes=30)
                # 240 records over 1 hour (every 15 seconds) at 0.8 U/hr
                for i in range(240):
                    ts = base_ts + timedelta(seconds=i * 15)
                    if ts > now:
                        break
                    db.add(
                        PumpEvent(
                            user_id=uid,
                            event_type=PumpEventType.BASAL,
                            event_timestamp=ts,
                            units=0.8,
                            is_automated=True,
                            received_at=ts,
                            source="mobile",
                        )
                    )
                await db.commit()
                break

            resp = await client.get(
                "/api/integrations/insulin/summary?days=1",
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 200
        data = resp.json()
        # Time-weighted: 0.8 U/hr * ~1 hour = ~0.8 U (not 240 * 0.8 = 192)
        # Lower bound varies based on how much of the window has elapsed.
        assert 0.1 < data["basal_units"] < 1.5, (
            f"Basal overcounted: {data['basal_units']} U (expected ~0.8)"
        )

    async def test_basal_gap_capped(self):
        """Gaps longer than max gap should be capped to prevent phantom insulin."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie, user_id = await register_and_login(client)

            async for db in get_db():
                now = datetime.now(UTC)
                uid = uuid.UUID(user_id)
                # Use days=2 so the window is wide enough for a 6-hour gap
                # even when the test runs shortly after midnight.
                cutoff = _boundary_cutoff(days=2)
                first_ts = cutoff + timedelta(hours=1)
                second_ts = first_ts + timedelta(hours=6)
                db.add(
                    PumpEvent(
                        user_id=uid,
                        event_type=PumpEventType.BASAL,
                        event_timestamp=first_ts,
                        units=0.8,
                        is_automated=True,
                        received_at=now,
                        source="mobile",
                    )
                )
                db.add(
                    PumpEvent(
                        user_id=uid,
                        event_type=PumpEventType.BASAL,
                        event_timestamp=second_ts,
                        units=0.8,
                        is_automated=True,
                        received_at=now,
                        source="mobile",
                    )
                )
                await db.commit()
                break

            resp = await client.get(
                "/api/integrations/insulin/summary?days=2",
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 200
        data = resp.json()
        # Gap of 6h should be capped at 2h: 0.8 * 2.0 = 1.6 U max from first
        # record. Second record has ~0 gap to now. Total < 2.0 U.
        assert data["basal_units"] < 2.0, (
            f"Gap not capped: {data['basal_units']} U (expected ~1.6)"
        )
        assert data["basal_units"] > 1.0

    async def test_basal_only_no_boluses(self):
        """Basal-only data (zero boluses) should produce 100% basal split."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie, user_id = await register_and_login(client)

            async for db in get_db():
                now = datetime.now(UTC)
                uid = uuid.UUID(user_id)
                cutoff = _boundary_cutoff(days=1)
                # 24 hourly basal records at 1.0 U/hr, starting from cutoff
                for h in range(24):
                    ts = cutoff + timedelta(hours=h)
                    if ts > now:
                        break
                    db.add(
                        PumpEvent(
                            user_id=uid,
                            event_type=PumpEventType.BASAL,
                            event_timestamp=ts,
                            units=1.0,
                            is_automated=True,
                            received_at=ts,
                            source="mobile",
                        )
                    )
                await db.commit()
                break

            resp = await client.get(
                "/api/integrations/insulin/summary?days=1",
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["basal_pct"] == 100.0
        assert data["bolus_pct"] == 0.0
        assert data["bolus_count"] == 0
        assert data["basal_units"] > 0

    async def test_basal_suspended_zero_rate(self):
        """Suspended pump (rate=0) should contribute 0 to basal total."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie, user_id = await register_and_login(client)

            async for db in get_db():
                now = datetime.now(UTC)
                uid = uuid.UUID(user_id)
                cutoff = _boundary_cutoff(days=1)
                # Suspended record (rate = 0) followed by a normal record
                db.add(
                    PumpEvent(
                        user_id=uid,
                        event_type=PumpEventType.BASAL,
                        event_timestamp=cutoff + timedelta(minutes=30),
                        units=0.0,
                        is_automated=True,
                        received_at=now,
                        source="mobile",
                    )
                )
                db.add(
                    PumpEvent(
                        user_id=uid,
                        event_type=PumpEventType.BASAL,
                        event_timestamp=cutoff + timedelta(hours=1, minutes=30),
                        units=0.8,
                        is_automated=True,
                        received_at=now,
                        source="mobile",
                    )
                )
                await db.commit()
                break

            resp = await client.get(
                "/api/integrations/insulin/summary?days=1",
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 200
        data = resp.json()
        # Suspended hour contributes 0. Second record has ~0 gap to now.
        # Total should be very close to 0.
        assert data["basal_units"] < 0.5

    async def test_basal_carry_over_from_before_cutoff(self):
        """A basal rate started before the query window should carry into it."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie, user_id = await register_and_login(client)

            async for db in get_db():
                now = datetime.now(UTC)
                uid = uuid.UUID(user_id)
                # Use days=2 so there's always enough window for the test.
                cutoff = _boundary_cutoff(days=2)
                # Record BEFORE the boundary-aligned cutoff at 1.0 U/hr
                db.add(
                    PumpEvent(
                        user_id=uid,
                        event_type=PumpEventType.BASAL,
                        event_timestamp=cutoff - timedelta(hours=2),
                        units=1.0,
                        is_automated=True,
                        received_at=now,
                        source="mobile",
                    )
                )
                # Record INSIDE the window (3 hours after cutoff)
                db.add(
                    PumpEvent(
                        user_id=uid,
                        event_type=PumpEventType.BASAL,
                        event_timestamp=cutoff + timedelta(hours=3),
                        units=0.5,
                        is_automated=True,
                        received_at=now,
                        source="mobile",
                    )
                )
                await db.commit()
                break

            resp = await client.get(
                "/api/integrations/insulin/summary?days=2",
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 200
        data = resp.json()
        # The pre-cutoff record at 1.0 U/hr should carry over into the window,
        # contributing delivery from cutoff to cutoff+3h (capped at 2h max gap).
        # That gives 1.0 * 2.0 = 2.0 U from carry-over.
        # Plus the in-window record at 0.5 U/hr from cutoff+3h to now.
        # Without carry-over, only the second record contributes.
        assert data["basal_units"] > 1.0, (
            f"Carry-over missing: {data['basal_units']} U (expected >1.0)"
        )


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
        assert data["total_count"] == 30  # 18 bolus + 12 correction (6 complete days)
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

        assert resp_a.status_code == 200
        assert resp_b.status_code == 200
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

        assert resp_a.status_code == 200
        assert resp_b.status_code == 200
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

        assert resp_a.status_code == 200
        assert resp_b.status_code == 200
        assert (
            resp_a.json()["total_count"] == 30
        )  # 18 bolus + 12 correction (6 complete days)
        assert resp_b.json()["total_count"] == 0
        assert resp_b.json()["boluses"] == []

    async def test_tir_detail_isolation(self):
        """Verify include_details=true path isolates user data."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie_a, user_a = await register_and_login(client)
            cookie_b, _ = await register_and_login(client)

            async for db in get_db():
                await seed_glucose(db, user_a, count=50)
                break

            resp_a = await client.get(
                "/api/integrations/glucose/time-in-range"
                "?minutes=1440&include_details=true",
                cookies={settings.jwt_cookie_name: cookie_a},
            )
            resp_b = await client.get(
                "/api/integrations/glucose/time-in-range"
                "?minutes=1440&include_details=true",
                cookies={settings.jwt_cookie_name: cookie_b},
            )

        assert resp_a.status_code == 200
        assert resp_b.status_code == 200
        assert resp_a.json()["readings_count"] == 50
        assert resp_b.json()["readings_count"] == 0


async def seed_5_bucket_glucose(
    db: AsyncSession,
    user_id: str,
    minutes_ago_start: int = 0,
):
    """Insert glucose readings spanning all 5 TIR buckets.

    Defaults: urgent_low=55, low=70, high=180, urgent_high=250.
    Inserts readings at: 40 (urgent_low), 60 (low), 65 (low),
    100 (in_range), 120 (in_range), 150 (in_range), 160 (in_range),
    200 (high), 220 (high), 280 (urgent_high).
    """
    now = datetime.now(UTC)
    uid = uuid.UUID(user_id)
    values = [40, 60, 65, 100, 120, 150, 160, 200, 220, 280]
    for i, val in enumerate(values):
        ts = now - timedelta(minutes=minutes_ago_start + i * 5)
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


@pytest.mark.asyncio
class TestTirDetail:
    async def test_tir_5_bucket_detail(self):
        """Verify 5 buckets with known glucose values spanning all ranges."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie, user_id = await register_and_login(client)

            async for db in get_db():
                await seed_5_bucket_glucose(db, user_id)
                break

            resp = await client.get(
                "/api/integrations/glucose/time-in-range"
                "?minutes=1440&include_details=true",
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["buckets"]) == 5
        labels = [b["label"] for b in data["buckets"]]
        assert labels == [
            "urgent_low",
            "low",
            "in_range",
            "high",
            "urgent_high",
        ]
        # 1 urgent_low (40), 2 low (60,65), 4 in_range (100,120,150,160),
        # 2 high (200,220), 1 urgent_high (280)
        readings = {b["label"]: b["readings"] for b in data["buckets"]}
        assert readings["urgent_low"] == 1
        assert readings["low"] == 2
        assert readings["in_range"] == 4
        assert readings["high"] == 2
        assert readings["urgent_high"] == 1
        assert data["readings_count"] == 10

    async def test_tir_previous_period(self):
        """Verify previous_buckets is populated when previous period has data."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie, user_id = await register_and_login(client)

            async for db in get_db():
                # Current period: last 60 min
                await seed_5_bucket_glucose(db, user_id, minutes_ago_start=0)
                # Previous period: 60-120 min ago (10 readings)
                await seed_5_bucket_glucose(db, user_id, minutes_ago_start=60)
                break

            resp = await client.get(
                "/api/integrations/glucose/time-in-range"
                "?minutes=60&include_details=true",
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["previous_buckets"] is not None
        assert len(data["previous_buckets"]) == 5
        assert data["previous_readings_count"] == 10

    async def test_tir_previous_period_insufficient_data(self):
        """Verify previous_buckets=null when < 10 readings in prev period."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie, user_id = await register_and_login(client)

            async for db in get_db():
                # Only current period data, no previous period readings
                await seed_5_bucket_glucose(db, user_id, minutes_ago_start=0)
                break

            resp = await client.get(
                "/api/integrations/glucose/time-in-range"
                "?minutes=1440&include_details=true",
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["previous_buckets"] is None
        assert data["previous_readings_count"] is None

    async def test_tir_previous_period_boundary_9_readings(self):
        """Verify previous_buckets=null when exactly 9 readings (below 10 threshold)."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie, user_id = await register_and_login(client)

            async for db in get_db():
                # Current period: last 60 min (10 readings)
                await seed_5_bucket_glucose(db, user_id, minutes_ago_start=0)
                # Previous period: 60-120 min ago -- only 9 readings
                now = datetime.now(UTC)
                uid = uuid.UUID(user_id)
                for i in range(9):
                    ts = now - timedelta(minutes=60 + i * 5)
                    db.add(
                        GlucoseReading(
                            user_id=uid,
                            value=120,
                            reading_timestamp=ts,
                            trend=TrendDirection.FLAT,
                            trend_rate=0.0,
                            received_at=ts,
                            source="mobile",
                        )
                    )
                await db.commit()
                break

            resp = await client.get(
                "/api/integrations/glucose/time-in-range"
                "?minutes=60&include_details=true",
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["previous_buckets"] is None
        assert data["previous_readings_count"] is None

    async def test_tir_detail_bucket_sum(self):
        """Verify all bucket percentages sum to 100.0."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie, user_id = await register_and_login(client)

            async for db in get_db():
                await seed_5_bucket_glucose(db, user_id)
                break

            resp = await client.get(
                "/api/integrations/glucose/time-in-range"
                "?minutes=1440&include_details=true",
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 200
        data = resp.json()
        total_pct = sum(b["pct"] for b in data["buckets"])
        assert abs(total_pct - 100.0) < 0.01

    async def test_tir_detail_backward_compat(self):
        """Verify include_details=false returns old 3-bucket schema."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie, user_id = await register_and_login(client)

            async for db in get_db():
                await seed_5_bucket_glucose(db, user_id)
                break

            resp = await client.get(
                "/api/integrations/glucose/time-in-range?minutes=1440",
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 200
        data = resp.json()
        # Old schema has low_pct, in_range_pct, high_pct
        assert "low_pct" in data
        assert "in_range_pct" in data
        assert "high_pct" in data
        # Should NOT have 5-bucket fields
        assert "buckets" not in data


@pytest.mark.asyncio
class TestSourceFilteringAndDedup:
    """Story 30.10: source filtering and bolus/correction dedup tests."""

    async def test_source_test_excluded(self):
        """Events with source='test' should be excluded from insulin summary."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie, user_id = await register_and_login(client)

            async for db in get_db():
                now = datetime.now(UTC)
                uid = uuid.UUID(user_id)
                cutoff = _boundary_cutoff(days=1)
                ts = cutoff + timedelta(hours=1)
                # Insert bolus and basal with source='test' -- should be ignored
                db.add(
                    PumpEvent(
                        user_id=uid,
                        event_type=PumpEventType.BOLUS,
                        event_timestamp=ts,
                        units=5.0,
                        is_automated=False,
                        received_at=now,
                        source="test",
                    )
                )
                db.add(
                    PumpEvent(
                        user_id=uid,
                        event_type=PumpEventType.BASAL,
                        event_timestamp=ts,
                        units=1.0,
                        is_automated=True,
                        received_at=now,
                        source="test",
                    )
                )
                await db.commit()
                break

            resp = await client.get(
                "/api/integrations/insulin/summary?days=1",
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["tdd"] == 0.0
        assert data["bolus_count"] == 0

    async def test_bolus_correction_dedup(self):
        """Same delivery stored as both bolus and correction should be counted once."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie, user_id = await register_and_login(client)

            async for db in get_db():
                now = datetime.now(UTC)
                uid = uuid.UUID(user_id)
                cutoff = _boundary_cutoff(days=1)
                ts = cutoff + timedelta(hours=1)
                # Same timestamp and units, different event_type (mobile dual-creation)
                db.add(
                    PumpEvent(
                        user_id=uid,
                        event_type=PumpEventType.BOLUS,
                        event_timestamp=ts,
                        units=3.0,
                        is_automated=False,
                        received_at=now,
                        source="mobile",
                    )
                )
                db.add(
                    PumpEvent(
                        user_id=uid,
                        event_type=PumpEventType.CORRECTION,
                        event_timestamp=ts,
                        units=3.0,
                        is_automated=True,
                        control_iq_reason="high_bg",
                        received_at=now,
                        source="mobile",
                    )
                )
                await db.commit()
                break

            resp = await client.get(
                "/api/integrations/insulin/summary?days=1",
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 200
        data = resp.json()
        # Should count as ONE delivery of 3.0 U, classified as correction
        assert data["correction_count"] == 1
        assert data["bolus_count"] == 0
        # correction_units is daily avg (3.0 / 1 day = 3.0)
        assert abs(data["correction_units"] - 3.0) < 0.5

    async def test_cross_source_prefers_mobile(self):
        """When both mobile and tandem have data, only mobile is aggregated."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie, user_id = await register_and_login(client)

            async for db in get_db():
                now = datetime.now(UTC)
                uid = uuid.UUID(user_id)
                cutoff = _boundary_cutoff(days=1)
                ts = cutoff + timedelta(hours=1)
                # Mobile bolus
                db.add(
                    PumpEvent(
                        user_id=uid,
                        event_type=PumpEventType.BOLUS,
                        event_timestamp=ts,
                        units=4.0,
                        is_automated=False,
                        received_at=now,
                        source="mobile",
                    )
                )
                # Tandem bolus at slightly different timestamp (cloud sync)
                db.add(
                    PumpEvent(
                        user_id=uid,
                        event_type=PumpEventType.BOLUS,
                        event_timestamp=ts - timedelta(seconds=5),
                        units=4.0,
                        is_automated=False,
                        received_at=now,
                        source="tandem",
                    )
                )
                await db.commit()
                break

            resp = await client.get(
                "/api/integrations/insulin/summary?days=1",
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 200
        data = resp.json()
        # Only the mobile bolus (4.0 U) should be counted, not both
        assert data["bolus_count"] == 1
        assert abs(data["bolus_units"] - 4.0) < 0.5

    async def test_tandem_fallback_when_no_mobile(self):
        """When only tandem data exists, it should be used for aggregation."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie, user_id = await register_and_login(client)

            async for db in get_db():
                now = datetime.now(UTC)
                uid = uuid.UUID(user_id)
                cutoff = _boundary_cutoff(days=1)
                ts = cutoff + timedelta(hours=1)
                db.add(
                    PumpEvent(
                        user_id=uid,
                        event_type=PumpEventType.BOLUS,
                        event_timestamp=ts,
                        units=5.5,
                        is_automated=False,
                        received_at=now,
                        source="tandem",
                    )
                )
                db.add(
                    PumpEvent(
                        user_id=uid,
                        event_type=PumpEventType.BASAL,
                        event_timestamp=ts,
                        units=0.8,
                        is_automated=True,
                        received_at=now,
                        source="tandem",
                    )
                )
                db.add(
                    PumpEvent(
                        user_id=uid,
                        event_type=PumpEventType.BASAL,
                        event_timestamp=ts + timedelta(hours=2),
                        units=0.8,
                        is_automated=True,
                        received_at=now,
                        source="tandem",
                    )
                )
                await db.commit()
                break

            resp = await client.get(
                "/api/integrations/insulin/summary?days=1",
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["tdd"] > 0
        assert data["bolus_count"] == 1
        assert data["basal_units"] > 0

    async def test_bolus_review_excludes_test_source(self):
        """Bolus review endpoint should exclude source='test' events."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie, user_id = await register_and_login(client)

            async for db in get_db():
                now = datetime.now(UTC)
                uid = uuid.UUID(user_id)
                cutoff = _boundary_cutoff(days=1)
                ts = cutoff + timedelta(hours=1)
                # One mobile bolus (should appear) and one test bolus (excluded)
                db.add(
                    PumpEvent(
                        user_id=uid,
                        event_type=PumpEventType.BOLUS,
                        event_timestamp=ts,
                        units=3.0,
                        is_automated=False,
                        received_at=now,
                        source="mobile",
                    )
                )
                db.add(
                    PumpEvent(
                        user_id=uid,
                        event_type=PumpEventType.BOLUS,
                        event_timestamp=ts + timedelta(minutes=30),
                        units=5.0,
                        is_automated=False,
                        received_at=now,
                        source="test",
                    )
                )
                await db.commit()
                break

            resp = await client.get(
                "/api/integrations/bolus/review?days=1",
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 200
        data = resp.json()
        # Only the mobile bolus should appear
        assert data["total_count"] == 1
        assert len(data["boluses"]) == 1
        assert abs(data["boluses"][0]["units"] - 3.0) < 0.01
