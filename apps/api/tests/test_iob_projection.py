"""Story 3.7: Tests for IoB projection engine.

Tests the insulin decay curve calculations and IoB projection endpoint.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient, Response

from src.config import settings
from src.core.security import hash_password
from src.main import app
from src.models.pump_data import PumpEvent, PumpEventType
from src.models.user import User, UserRole
from src.services.iob_projection import (
    _DOSE_EVENT_TYPES,
    _MAX_SINGLE_DOSE_UNITS,
    INSULIN_DIA_HOURS,
    _AnchorVisibility,
    _classify_anchor_visibility,
    _Dose,
    _sum_iob_from_doses,
    _survives_anchor_cut,
    calculate_insulin_remaining,
    calculate_iob_activity_curve,
    project_iob,
)


def unique_email(prefix: str) -> str:
    """Generate a unique email for tests."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


def _unique_ns_id(prefix: str) -> str:
    """Generate a unique ns_id for tests.

    The `ix_pump_events_source_nsid` unique index is global on
    (source, ns_id) -- not per user -- and the shared test DB persists
    rows across runs, so a hardcoded ns_id collides on re-run.
    """
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


async def _create_user(db_session, prefix: str) -> tuple[User, str, str]:
    """Create a user directly in the database; returns (user, email, password)."""
    email = unique_email(prefix)
    password = "SecurePass123"
    user = User(
        email=email,
        hashed_password=hash_password(password),
        role=UserRole.DIABETIC,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user, email, password


async def _fetch_projection(email: str, password: str) -> Response:
    """Login and GET the IoB projection endpoint; returns the response."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        login_response = await client.post(
            "/api/auth/login",
            json={"email": email, "password": password},
        )
        assert login_response.status_code == 200, login_response.text
        session_cookie = login_response.cookies.get(settings.jwt_cookie_name)
        return await client.get(
            "/api/integrations/tandem/iob/projection",
            cookies={settings.jwt_cookie_name: session_cookie},
        )


class TestInsulinDecayCurve:
    """Tests for the insulin decay curve calculations."""

    def test_calculate_remaining_at_zero_hours(self):
        """At time 0, all insulin should remain."""
        remaining = calculate_insulin_remaining(0)
        assert remaining == 1.0

    def test_calculate_remaining_at_negative_hours(self):
        """Negative elapsed time should return full insulin."""
        remaining = calculate_insulin_remaining(-1)
        assert remaining == 1.0

    def test_calculate_remaining_at_dia(self):
        """At DIA (4 hours), no insulin should remain."""
        remaining = calculate_insulin_remaining(INSULIN_DIA_HOURS)
        assert remaining == 0.0

    def test_calculate_remaining_after_dia(self):
        """After DIA, no insulin should remain."""
        remaining = calculate_insulin_remaining(5.0)
        assert remaining == 0.0

    def test_calculate_remaining_at_half_dia(self):
        """At half DIA (2 hours), should have ~75% remaining (parabolic decay)."""
        remaining = calculate_insulin_remaining(2.0)
        # t_ratio = 2/4 = 0.5, remaining = 1 - 0.5^2 = 0.75
        assert remaining == pytest.approx(0.75, rel=0.01)

    def test_calculate_remaining_at_one_hour(self):
        """At 1 hour, should have ~94% remaining."""
        remaining = calculate_insulin_remaining(1.0)
        # t_ratio = 1/4 = 0.25, remaining = 1 - 0.25^2 = 0.9375
        assert remaining == pytest.approx(0.9375, rel=0.01)

    def test_calculate_remaining_at_three_hours(self):
        """At 3 hours, should have ~44% remaining."""
        remaining = calculate_insulin_remaining(3.0)
        # t_ratio = 3/4 = 0.75, remaining = 1 - 0.75^2 = 0.4375
        assert remaining == pytest.approx(0.4375, rel=0.01)

    def test_calculate_remaining_with_custom_dia(self):
        """Test with a custom DIA value."""
        remaining = calculate_insulin_remaining(3.0, dia_hours=6.0)
        # t_ratio = 3/6 = 0.5, remaining = 1 - 0.5^2 = 0.75
        assert remaining == pytest.approx(0.75, rel=0.01)


class TestIoBActivityCurve:
    """Tests for the bilinear activity curve."""

    def test_activity_at_zero(self):
        """At time 0, all insulin activity remains."""
        activity = calculate_iob_activity_curve(0)
        assert activity == 1.0

    def test_activity_at_dia(self):
        """At DIA, no insulin activity remains."""
        activity = calculate_iob_activity_curve(INSULIN_DIA_HOURS)
        assert activity == 0.0

    def test_activity_at_peak(self):
        """At peak time (1 hour), should have ~80% remaining."""
        activity = calculate_iob_activity_curve(1.0)
        assert activity == pytest.approx(0.8, rel=0.01)

    def test_activity_decreases_over_time(self):
        """Activity should decrease monotonically over time."""
        times = [0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
        activities = [calculate_iob_activity_curve(t) for t in times]
        for i in range(len(activities) - 1):
            assert activities[i] >= activities[i + 1]


class TestProjectIoB:
    """Tests for the IoB projection function."""

    def test_project_iob_no_elapsed_time(self):
        """With no elapsed time, projected IoB equals confirmed."""
        now = datetime.now(UTC)
        projected = project_iob(2.5, now, now)
        assert projected == 2.5

    def test_project_iob_one_hour_elapsed(self):
        """After 1 hour, IoB should decay according to curve."""
        confirmed_at = datetime.now(UTC) - timedelta(hours=1)
        now = datetime.now(UTC)
        projected = project_iob(2.5, confirmed_at, now)
        # At 1 hour, ~93.75% should remain
        expected = 2.5 * 0.9375
        assert projected == pytest.approx(expected, rel=0.01)

    def test_project_iob_two_hours_elapsed(self):
        """After 2 hours, IoB should be ~75%."""
        confirmed_at = datetime.now(UTC) - timedelta(hours=2)
        now = datetime.now(UTC)
        projected = project_iob(2.5, confirmed_at, now)
        # At 2 hours, ~75% should remain
        expected = 2.5 * 0.75
        assert projected == pytest.approx(expected, rel=0.01)

    def test_project_iob_after_dia(self):
        """After DIA, IoB should be 0."""
        confirmed_at = datetime.now(UTC) - timedelta(hours=5)
        now = datetime.now(UTC)
        projected = project_iob(2.5, confirmed_at, now)
        assert projected == 0.0

    def test_project_iob_future_time(self):
        """Project IoB to a future time."""
        now = datetime.now(UTC)
        future = now + timedelta(hours=1)
        # Start with 2.5u now, project to 1 hour from now
        projected = project_iob(2.5, now, future)
        expected = 2.5 * 0.9375
        assert projected == pytest.approx(expected, rel=0.01)

    def test_project_iob_zero_confirmed(self):
        """Zero confirmed IoB should project to zero."""
        confirmed_at = datetime.now(UTC) - timedelta(hours=1)
        now = datetime.now(UTC)
        projected = project_iob(0.0, confirmed_at, now)
        assert projected == 0.0


class TestSumIoBFromDoses:
    """Tests for the dose-summation pure function."""

    def test_single_recent_bolus(self):
        """A bolus delivered 1 hour ago should retain ~94% of its insulin."""
        now = datetime.now(UTC)
        doses = [(now - timedelta(hours=1), 2.0)]
        iob = _sum_iob_from_doses(doses, now)
        # 2.0 * 0.9375 = 1.875
        assert iob == pytest.approx(1.875, rel=0.01)

    def test_multiple_boluses(self):
        """Multiple boluses within DIA window should sum their remaining insulin."""
        now = datetime.now(UTC)
        doses = [
            (now - timedelta(hours=1), 2.0),  # 2.0 * 0.9375 = 1.875
            (now - timedelta(hours=2), 3.0),  # 3.0 * 0.75 = 2.25
        ]
        iob = _sum_iob_from_doses(doses, now)
        assert iob == pytest.approx(1.875 + 2.25, rel=0.01)

    def test_dose_outside_dia_contributes_zero(self):
        """A dose delivered beyond DIA hours ago should contribute 0."""
        now = datetime.now(UTC)
        doses = [(now - timedelta(hours=5), 5.0)]  # beyond 4h DIA
        iob = _sum_iob_from_doses(doses, now)
        assert iob == 0.0

    def test_no_doses_returns_zero(self):
        """With no doses, IoB should be 0."""
        now = datetime.now(UTC)
        iob = _sum_iob_from_doses([], now)
        assert iob == 0.0

    def test_future_dose_ignored(self):
        """A dose in the future relative to at_time should not contribute."""
        now = datetime.now(UTC)
        doses = [(now + timedelta(hours=1), 5.0)]
        iob = _sum_iob_from_doses(doses, now)
        assert iob == 0.0

    def test_dose_just_delivered(self):
        """A dose at exactly at_time should retain 100%."""
        now = datetime.now(UTC)
        doses = [(now, 3.0)]
        iob = _sum_iob_from_doses(doses, now)
        assert iob == pytest.approx(3.0, rel=0.01)

    def test_plausible_max_dose_not_clamped(self):
        """A real 60 U single dose (NovoPen 6 max) is summed in full."""
        now = datetime.now(UTC)
        doses = [(now, _MAX_SINGLE_DOSE_UNITS)]
        iob = _sum_iob_from_doses(doses, now)
        assert iob == pytest.approx(_MAX_SINGLE_DOSE_UNITS, rel=0.01)

    def test_corrupt_dose_units_are_clamped(self):
        """A corrupt/implausible units value can't poison projected IoB."""
        now = datetime.now(UTC)
        doses = [(now, 9999.0)]
        iob = _sum_iob_from_doses(doses, now)
        # Clamped to the physiological single-dose ceiling, not 9999.
        assert iob == pytest.approx(_MAX_SINGLE_DOSE_UNITS, rel=0.01)


class TestDoseEventTypePin:
    """Pin the event types the IoB engine is allowed to sum as doses.

    Guards against a future long-acting insulin type (e.g.
    PumpEventType.BASAL_INJECTION, issue #728) silently entering the
    rapid-acting decay model. If this test fails, do NOT widen the pin
    without adding a matching absorption curve for the new type.
    """

    def test_only_bolus_and_correction_are_summed(self):
        assert set(_DOSE_EVENT_TYPES) == {
            PumpEventType.BOLUS,
            PumpEventType.CORRECTION,
        }
        # BASAL_INJECTION exists (issue #728) but must stay out of the allowlist.
        assert PumpEventType.BASAL_INJECTION not in _DOSE_EVENT_TYPES


class TestAnchorVisibilityClassification:
    """Tests for the pump-anchor visibility discriminator."""

    def test_glooko_insulins_stream_is_never_visible(self):
        """Smart-pen / manual Glooko doses are invisible to every anchor."""
        visibility = _classify_anchor_visibility(
            "glooko", {"glooko_stream": "insulins", "device_delivered": True}
        )
        assert visibility is _AnchorVisibility.NEVER

    def test_insulins_marker_requires_glooko_source(self):
        """The insulins-stream marker is only trusted on Glooko rows.

        A future writer passing client-supplied metadata through must not
        be able to flip a pump bolus into an always-counted dose.
        """
        visibility = _classify_anchor_visibility(
            "mobile", {"glooko_stream": "insulins"}
        )
        assert visibility is _AnchorVisibility.PUMP

    def test_glooko_pump_stream_is_pump_visible(self):
        """Glooko pump-stream boluses are pump deliveries (anchor cut applies)."""
        assert _classify_anchor_visibility("glooko", None) is _AnchorVisibility.PUMP

    def test_direct_integrations_are_pump_visible(self):
        for source in ("tandem", "mobile", "medtronic"):
            assert _classify_anchor_visibility(source, None) is _AnchorVisibility.PUMP

    def test_nightscout_external_insulin_is_nightscout_only(self):
        """Logged external insulin: pump can't see it, but Loop's IoB can."""
        visibility = _classify_anchor_visibility(
            "nightscout:abc123",
            {"source_uploader": "loop", "bolus_subtype": "external"},
        )
        assert visibility is _AnchorVisibility.NIGHTSCOUT_ONLY

    def test_nightscout_careportal_bolus_is_nightscout_only(self):
        """Care Portal manual entries detect as a non-loop uploader."""
        visibility = _classify_anchor_visibility(
            "nightscout:abc123",
            {"source_uploader": "unknown", "bolus_subtype": "normal"},
        )
        assert visibility is _AnchorVisibility.NIGHTSCOUT_ONLY

    def test_nightscout_xdrip_manual_log_is_nightscout_only(self):
        visibility = _classify_anchor_visibility(
            "nightscout:abc123",
            {"source_uploader": "xdrip+", "bolus_subtype": "normal"},
        )
        assert visibility is _AnchorVisibility.NIGHTSCOUT_ONLY

    def test_nightscout_loop_uploader_boluses_are_pump_visible(self):
        """Closed-loop uploads record pump deliveries -- anchor cut applies."""
        for uploader in ("loop", "aaps", "trio", "oref0"):
            visibility = _classify_anchor_visibility(
                "nightscout:abc123",
                {"source_uploader": uploader, "bolus_subtype": "normal"},
            )
            assert visibility is _AnchorVisibility.PUMP, uploader

    def test_nightscout_tidepool_bolus_is_pump_visible(self):
        """Tidepool mirrors pump uploads -- treating its boluses as manual
        would double-count them against a pump-hardware anchor."""
        visibility = _classify_anchor_visibility(
            "nightscout:abc123",
            {"source_uploader": "tidepool", "bolus_subtype": "normal"},
        )
        assert visibility is _AnchorVisibility.PUMP

    def test_nightscout_missing_metadata_is_pump_visible(self):
        """An NS row with no uploader attribution cannot be positively
        identified as manual -- it degrades to the pre-fix anchor cut
        (understatement) rather than risking double-counting."""
        assert (
            _classify_anchor_visibility("nightscout:abc123", None)
            is _AnchorVisibility.PUMP
        )
        assert (
            _classify_anchor_visibility(
                "nightscout:abc123", {"bolus_subtype": "normal"}
            )
            is _AnchorVisibility.PUMP
        )


class TestSurvivesAnchorCut:
    """Tests for the per-dose anchor-cut decision."""

    ANCHOR_AT = datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC)

    def _dose(self, minutes_offset: int, visibility: _AnchorVisibility) -> _Dose:
        return _Dose(
            timestamp=self.ANCHOR_AT + timedelta(minutes=minutes_offset),
            units=1.0,
            anchor_visibility=visibility,
        )

    def test_pump_dose_after_anchor_survives(self):
        dose = self._dose(+5, _AnchorVisibility.PUMP)
        assert _survives_anchor_cut(dose, self.ANCHOR_AT, False) is True

    def test_pump_dose_at_anchor_is_cut(self):
        dose = self._dose(0, _AnchorVisibility.PUMP)
        assert _survives_anchor_cut(dose, self.ANCHOR_AT, False) is False

    def test_pump_dose_before_anchor_is_cut(self):
        dose = self._dose(-30, _AnchorVisibility.PUMP)
        assert _survives_anchor_cut(dose, self.ANCHOR_AT, False) is False

    def test_pen_dose_before_anchor_survives(self):
        dose = self._dose(-30, _AnchorVisibility.NEVER)
        assert _survives_anchor_cut(dose, self.ANCHOR_AT, False) is True

    def test_pen_dose_survives_even_nightscout_anchor(self):
        dose = self._dose(-30, _AnchorVisibility.NEVER)
        assert _survives_anchor_cut(dose, self.ANCHOR_AT, True) is True

    def test_ns_manual_dose_before_pump_anchor_survives(self):
        dose = self._dose(-30, _AnchorVisibility.NIGHTSCOUT_ONLY)
        assert _survives_anchor_cut(dose, self.ANCHOR_AT, False) is True

    def test_ns_manual_dose_before_nightscout_anchor_is_cut(self):
        """Conservative: an NS-derived anchor may already include it."""
        dose = self._dose(-30, _AnchorVisibility.NIGHTSCOUT_ONLY)
        assert _survives_anchor_cut(dose, self.ANCHOR_AT, True) is False

    def test_ns_manual_dose_after_nightscout_anchor_survives(self):
        """Post-anchor doses always count -- the anchor predates them."""
        dose = self._dose(+5, _AnchorVisibility.NIGHTSCOUT_ONLY)
        assert _survives_anchor_cut(dose, self.ANCHOR_AT, True) is True


@pytest.mark.asyncio
class TestIoBProjectionEndpoint:
    """Tests for the IoB projection API endpoint."""

    async def test_iob_projection_requires_auth(self):
        """IoB projection endpoint requires authentication."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/api/integrations/tandem/iob/projection")

        assert response.status_code == 401

    async def test_iob_projection_no_data(self):
        """IoB projection returns 404 when no data available."""
        email = unique_email("iob_no_data")
        password = "SecurePass123"

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            await client.post(
                "/api/auth/register",
                json={"email": email, "password": password},
            )

        response = await _fetch_projection(email, password)

        assert response.status_code == 404
        assert "No IoB data" in response.json()["detail"]

    async def test_iob_projection_with_data(self, db_session):
        """IoB projection returns data when pump events exist."""
        user, email, password = await _create_user(db_session, "iob_with_data")

        # Create a pump event with IoB data
        now = datetime.now(UTC)
        pump_event = PumpEvent(
            user_id=user.id,
            event_type=PumpEventType.BOLUS,
            event_timestamp=now - timedelta(minutes=30),
            units=2.0,
            iob_at_event=2.5,
            received_at=now,
        )
        db_session.add(pump_event)
        await db_session.commit()

        response = await _fetch_projection(email, password)
        assert response.status_code == 200

        data = response.json()
        assert data["confirmed_iob"] == 2.5
        assert "projected_iob" in data
        assert "projected_30min" in data
        assert "projected_60min" in data
        assert data["is_stale"] is False
        assert data["stale_warning"] is None
        assert data["is_estimated"] is False

    async def test_iob_projection_stale_data(self, db_session):
        """IoB projection shows stale warning for old data."""
        user, email, password = await _create_user(db_session, "iob_stale")

        # Create a pump event with IoB data from 3 hours ago
        now = datetime.now(UTC)
        pump_event = PumpEvent(
            user_id=user.id,
            event_type=PumpEventType.BOLUS,
            event_timestamp=now - timedelta(hours=3),
            units=2.0,
            iob_at_event=2.5,
            received_at=now - timedelta(hours=3),
        )
        db_session.add(pump_event)
        await db_session.commit()

        response = await _fetch_projection(email, password)
        assert response.status_code == 200

        data = response.json()
        assert data["is_stale"] is True
        assert data["stale_warning"] is not None
        assert "unreliable" in data["stale_warning"].lower()

    async def test_iob_projection_decay_over_time(self, db_session):
        """IoB projection correctly applies decay curve."""
        user, email, password = await _create_user(db_session, "iob_decay")

        # Create a pump event with IoB data from 2 hours ago
        now = datetime.now(UTC)
        pump_event = PumpEvent(
            user_id=user.id,
            event_type=PumpEventType.BOLUS,
            event_timestamp=now - timedelta(hours=2),
            units=2.0,
            iob_at_event=4.0,
            received_at=now - timedelta(hours=2),
        )
        db_session.add(pump_event)
        await db_session.commit()

        response = await _fetch_projection(email, password)
        assert response.status_code == 200

        data = response.json()
        # After 2 hours, ~75% should remain (4.0 * 0.75 = 3.0)
        assert data["projected_iob"] == pytest.approx(3.0, rel=0.1)
        # 30 min ahead should be less
        assert data["projected_30min"] < data["projected_iob"]
        # 60 min ahead should be even less
        assert data["projected_60min"] < data["projected_30min"]

    async def test_iob_includes_post_confirmation_bolus(self, db_session):
        """Boluses delivered after the pump's IoB snapshot increase IoB."""
        user, email, password = await _create_user(db_session, "iob_hybrid")

        now = datetime.now(UTC)

        # Pump-confirmed IoB snapshot: 2.0u at 1 hour ago
        snapshot_event = PumpEvent(
            user_id=user.id,
            event_type=PumpEventType.CORRECTION,
            event_timestamp=now - timedelta(hours=1),
            units=0.5,
            iob_at_event=2.0,
            received_at=now - timedelta(hours=1),
        )
        # A 3.0u bolus delivered 30 minutes AFTER the snapshot
        post_bolus = PumpEvent(
            user_id=user.id,
            event_type=PumpEventType.BOLUS,
            event_timestamp=now - timedelta(minutes=30),
            units=3.0,
            iob_at_event=None,
            received_at=now - timedelta(minutes=30),
        )
        db_session.add_all([snapshot_event, post_bolus])
        await db_session.commit()

        response = await _fetch_projection(email, password)
        assert response.status_code == 200
        data = response.json()

        # pump_component: 2.0 * remaining(1h, 4h) = 2.0 * 0.9375 = 1.875
        # post_component: 3.0 * remaining(0.5h, 4h) = 3.0 * 0.984375 = 2.953
        # total ≈ 4.83
        # Without the fix, this would just be 1.875 (ignoring the 3.0u bolus)
        assert data["projected_iob"] > 4.0
        assert data["projected_iob"] == pytest.approx(4.83, rel=0.1)
        assert data["confirmed_iob"] == 2.0

    async def test_iob_no_double_counting(self, db_session):
        """Doses before the pump confirmation are NOT double-counted."""
        user, email, password = await _create_user(db_session, "iob_nodup")

        now = datetime.now(UTC)

        # A bolus from 2 hours ago (units=5.0)
        old_bolus = PumpEvent(
            user_id=user.id,
            event_type=PumpEventType.BOLUS,
            event_timestamp=now - timedelta(hours=2),
            units=5.0,
            iob_at_event=None,
            received_at=now - timedelta(hours=2),
        )
        # Pump snapshot 1 hour ago already includes the old bolus's IoB
        snapshot = PumpEvent(
            user_id=user.id,
            event_type=PumpEventType.CORRECTION,
            event_timestamp=now - timedelta(hours=1),
            units=0.5,
            iob_at_event=3.0,  # pump's total IoB at that point
            received_at=now - timedelta(hours=1),
        )
        db_session.add_all([old_bolus, snapshot])
        await db_session.commit()

        response = await _fetch_projection(email, password)
        assert response.status_code == 200
        data = response.json()

        # pump_component: 3.0 * remaining(1h, 4h) = 3.0 * 0.9375 = 2.8125
        # post_component: 0 (old_bolus is BEFORE snapshot, so excluded)
        # total ≈ 2.81
        # If double-counted, it would be 2.81 + 5.0*0.75 = 6.56 (wrong!)
        assert data["projected_iob"] == pytest.approx(2.81, rel=0.1)

    async def test_iob_dose_only_fallback(self, db_session):
        """When no pump confirmation exists, uses pure dose summation."""
        user, email, password = await _create_user(db_session, "iob_fallback")

        now = datetime.now(UTC)

        # Bolus with no pump IoB snapshot
        bolus = PumpEvent(
            user_id=user.id,
            event_type=PumpEventType.BOLUS,
            event_timestamp=now - timedelta(hours=1),
            units=4.0,
            iob_at_event=None,
            received_at=now - timedelta(hours=1),
        )
        db_session.add(bolus)
        await db_session.commit()

        response = await _fetch_projection(email, password)
        assert response.status_code == 200
        data = response.json()

        # Pure dose sum: 4.0 * remaining(1h, 4h) = 4.0 * 0.9375 = 3.75
        assert data["projected_iob"] == pytest.approx(3.75, rel=0.1)
        assert data["is_estimated"] is True
        assert "estimated" in data["stale_warning"].lower()

    async def test_iob_same_timestamp_not_double_counted(self, db_session):
        """A dose at the exact same timestamp as the snapshot is not double-counted."""
        user, email, password = await _create_user(db_session, "iob_same_ts")

        now = datetime.now(UTC)
        snapshot_time = now - timedelta(hours=1)

        # Bolus and IoB snapshot at the exact same timestamp
        event = PumpEvent(
            user_id=user.id,
            event_type=PumpEventType.BOLUS,
            event_timestamp=snapshot_time,
            units=5.0,
            iob_at_event=3.0,  # pump's IoB already includes this bolus
            received_at=snapshot_time,
        )
        db_session.add(event)
        await db_session.commit()

        response = await _fetch_projection(email, password)
        assert response.status_code == 200
        data = response.json()

        # Should only be the decayed snapshot (3.0 * 0.9375 = 2.81)
        # NOT snapshot + dose (which would be 2.81 + 5.0*0.9375 = 7.5)
        assert data["projected_iob"] == pytest.approx(2.81, rel=0.1)

    async def test_iob_fetch_excludes_non_bolus_events(self, db_session):
        """Basal and other non-bolus events are excluded from dose summation."""
        user, email, password = await _create_user(db_session, "iob_excl")

        now = datetime.now(UTC)

        # Pump snapshot 2 hours ago
        snapshot = PumpEvent(
            user_id=user.id,
            event_type=PumpEventType.CORRECTION,
            event_timestamp=now - timedelta(hours=2),
            units=0.5,
            iob_at_event=1.0,
            received_at=now - timedelta(hours=2),
        )
        # Basal event after snapshot (should NOT be added to IoB)
        basal = PumpEvent(
            user_id=user.id,
            event_type=PumpEventType.BASAL,
            event_timestamp=now - timedelta(hours=1),
            units=0.8,
            iob_at_event=None,
            received_at=now - timedelta(hours=1),
        )
        # Suspend event after snapshot (should NOT be added)
        suspend = PumpEvent(
            user_id=user.id,
            event_type=PumpEventType.SUSPEND,
            event_timestamp=now - timedelta(minutes=30),
            units=None,
            iob_at_event=None,
            received_at=now - timedelta(minutes=30),
        )
        db_session.add_all([snapshot, basal, suspend])
        await db_session.commit()

        response = await _fetch_projection(email, password)
        assert response.status_code == 200
        data = response.json()

        # Should only be decayed snapshot: 1.0 * remaining(2h, 4h) = 1.0 * 0.75 = 0.75
        # Basal and suspend events should NOT contribute
        assert data["projected_iob"] == pytest.approx(0.75, rel=0.1)
        assert data["is_estimated"] is False


@pytest.mark.asyncio
class TestNonPumpDoseProjection:
    """Non-pump doses (smart-pen via Glooko, manual Nightscout entries)
    must contribute to projected IoB even when a pump-confirmed anchor
    exists -- the anchor's writer never knew about them.
    """

    # Decay reference (parabolic, DIA=4h): remaining(0.5h) = 0.984375,
    # remaining(1h) = 0.9375, remaining(2h) = 0.75.

    async def test_basal_injection_does_not_enter_projected_iob(self, db_session):
        """Behavioral pin: a long-acting BASAL_INJECTION must NOT contribute to
        projected IoB (issue #728) -- the invariant the new event type relies on.
        A 4 U bolus counts; a co-timed 20 U basal injection adds nothing, so the
        projection stays in bolus range and never balloons toward ~24 U."""
        user, email, password = await _create_user(db_session, "iob_basal_inj")
        now = datetime.now(UTC)
        bolus = PumpEvent(
            user_id=user.id,
            event_type=PumpEventType.BOLUS,
            event_timestamp=now - timedelta(minutes=30),
            units=4.0,
            received_at=now,
            source="glooko",
            ns_id=_unique_ns_id("bolus"),
        )
        basal_injection = PumpEvent(
            user_id=user.id,
            event_type=PumpEventType.BASAL_INJECTION,
            event_timestamp=now - timedelta(minutes=30),
            units=20.0,
            received_at=now,
            source="glooko",
            ns_id=_unique_ns_id("basal-inj"),
            metadata_json={"glooko_stream": "insulins", "device_delivered": True},
        )
        db_session.add_all([bolus, basal_injection])
        await db_session.commit()

        response = await _fetch_projection(email, password)
        assert response.status_code == 200
        projected = response.json()["projected_iob"]
        # Projected IoB is exactly the 4 U bolus decaying (parabolic, DIA=4h):
        # 4.0 * remaining(0.5h) = 4.0 * 0.984375 = 3.9375. The 20 U basal
        # injection contributes nothing -- if it had leaked into the rapid-acting
        # model the total would balloon past 20, so pinning the bolus-only value
        # guards both the exclusion and the bolus contribution itself.
        assert projected == pytest.approx(3.9375, rel=0.02)

    async def test_pen_dose_before_pump_anchor_counts(self, db_session):
        """THE BUG: a pen dose at-or-before the anchor must not vanish.

        Glooko pump+pen dual user: the pump bolus row carries the IoB
        anchor, the pen dose predates it. Pre-fix the pen dose contributed
        zero; post-fix it decays independently and adds on top.
        """
        user, email, password = await _create_user(db_session, "iob_pen_before")
        now = datetime.now(UTC)

        anchor_bolus = PumpEvent(
            user_id=user.id,
            event_type=PumpEventType.BOLUS,
            event_timestamp=now - timedelta(minutes=30),
            units=1.0,
            iob_at_event=2.0,
            received_at=now,
            source="glooko",
            ns_id=_unique_ns_id("glooko-pump-bolus"),
        )
        pen_dose = PumpEvent(
            user_id=user.id,
            event_type=PumpEventType.BOLUS,
            event_timestamp=now - timedelta(hours=1),
            units=4.0,
            iob_at_event=None,
            received_at=now,
            source="glooko",
            ns_id=_unique_ns_id("glooko-pen-dose"),
            metadata_json={"glooko_stream": "insulins", "device_delivered": True},
        )
        db_session.add_all([anchor_bolus, pen_dose])
        await db_session.commit()

        response = await _fetch_projection(email, password)
        assert response.status_code == 200
        data = response.json()

        # pump anchor: 2.0 * remaining(0.5h) = 1.96875
        # pen dose:    4.0 * remaining(1h)   = 3.75  (pre-fix: 0)
        assert data["projected_iob"] == pytest.approx(5.72, rel=0.05)
        assert data["is_estimated"] is False

    async def test_pen_dose_exactly_at_anchor_counts(self, db_session):
        """A pen dose at the exact anchor timestamp still counts -- the
        anchor cannot include it no matter the timing."""
        user, email, password = await _create_user(db_session, "iob_pen_at")
        now = datetime.now(UTC)
        anchor_time = now - timedelta(hours=1)

        anchor = PumpEvent(
            user_id=user.id,
            event_type=PumpEventType.BG_READING,
            event_timestamp=anchor_time,
            units=None,
            iob_at_event=1.5,
            received_at=now,
            source="tandem",
        )
        pen_dose = PumpEvent(
            user_id=user.id,
            event_type=PumpEventType.BOLUS,
            event_timestamp=anchor_time,
            units=2.0,
            iob_at_event=None,
            received_at=now,
            source="glooko",
            ns_id=_unique_ns_id("glooko-pen-dose"),
            metadata_json={"glooko_stream": "insulins", "device_delivered": True},
        )
        db_session.add_all([anchor, pen_dose])
        await db_session.commit()

        response = await _fetch_projection(email, password)
        assert response.status_code == 200
        data = response.json()

        # anchor: 1.5 * 0.9375 = 1.40625; pen: 2.0 * 0.9375 = 1.875
        assert data["projected_iob"] == pytest.approx(3.28, rel=0.05)

    async def test_pen_dose_older_than_dia_contributes_zero(self, db_session):
        """A pen dose beyond the DIA window is fully decayed -- no effect."""
        user, email, password = await _create_user(db_session, "iob_pen_old")
        now = datetime.now(UTC)

        anchor = PumpEvent(
            user_id=user.id,
            event_type=PumpEventType.BG_READING,
            event_timestamp=now - timedelta(minutes=30),
            units=None,
            iob_at_event=1.0,
            received_at=now,
            source="tandem",
        )
        stale_pen_dose = PumpEvent(
            user_id=user.id,
            event_type=PumpEventType.BOLUS,
            event_timestamp=now - timedelta(hours=5),
            units=10.0,
            iob_at_event=None,
            received_at=now,
            source="glooko",
            ns_id=_unique_ns_id("glooko-pen-dose"),
            metadata_json={"glooko_stream": "insulins", "device_delivered": True},
        )
        db_session.add_all([anchor, stale_pen_dose])
        await db_session.commit()

        response = await _fetch_projection(email, password)
        assert response.status_code == 200
        data = response.json()

        # Only the anchor: 1.0 * remaining(0.5h) = 0.984375
        assert data["projected_iob"] == pytest.approx(0.98, rel=0.05)

    async def test_glooko_pump_bolus_not_double_counted(self, db_session):
        """DOUBLE-COUNT REGRESSION: a Glooko PUMP-stream bolus before the
        anchor is already inside the pump's IoB snapshot and must stay cut.
        Only the `insulins` stream is anchor-blind."""
        user, email, password = await _create_user(db_session, "iob_nodup_glooko")
        now = datetime.now(UTC)

        old_pump_bolus = PumpEvent(
            user_id=user.id,
            event_type=PumpEventType.BOLUS,
            event_timestamp=now - timedelta(hours=2),
            units=5.0,
            iob_at_event=None,
            received_at=now,
            source="glooko",
            ns_id=_unique_ns_id("glooko-pump-bolus"),
        )
        anchor_bolus = PumpEvent(
            user_id=user.id,
            event_type=PumpEventType.BOLUS,
            event_timestamp=now - timedelta(minutes=30),
            units=0.5,
            iob_at_event=3.0,  # pump total -- already includes the 5.0u bolus
            received_at=now,
            source="glooko",
            ns_id=_unique_ns_id("glooko-pump-bolus"),
        )
        db_session.add_all([old_pump_bolus, anchor_bolus])
        await db_session.commit()

        response = await _fetch_projection(email, password)
        assert response.status_code == 200
        data = response.json()

        # Anchor only: 3.0 * remaining(0.5h) = 2.953
        # Double-counting would add 5.0 * 0.75 = 3.75 on top (~6.7)
        assert data["projected_iob"] == pytest.approx(2.95, rel=0.05)

    async def test_pen_dose_after_anchor_counted_once(self, db_session):
        """A pen dose after the anchor passes both the timestamp rule and
        the anchor-blind rule -- it must still be summed exactly once."""
        user, email, password = await _create_user(db_session, "iob_pen_once")
        now = datetime.now(UTC)

        anchor = PumpEvent(
            user_id=user.id,
            event_type=PumpEventType.BG_READING,
            event_timestamp=now - timedelta(hours=1),
            units=None,
            iob_at_event=1.0,
            received_at=now,
            source="tandem",
        )
        pen_dose = PumpEvent(
            user_id=user.id,
            event_type=PumpEventType.BOLUS,
            event_timestamp=now - timedelta(minutes=30),
            units=3.0,
            iob_at_event=None,
            received_at=now,
            source="glooko",
            ns_id=_unique_ns_id("glooko-pen-dose"),
            metadata_json={"glooko_stream": "insulins", "device_delivered": True},
        )
        db_session.add_all([anchor, pen_dose])
        await db_session.commit()

        response = await _fetch_projection(email, password)
        assert response.status_code == 200
        data = response.json()

        # anchor: 1.0 * 0.9375 = 0.9375; pen ONCE: 3.0 * 0.984375 = 2.953
        # Summed twice it would be ~6.84.
        assert data["projected_iob"] == pytest.approx(3.89, rel=0.05)

    async def test_ns_manual_dose_with_pump_anchor_counts(self, db_session):
        """A Care Portal manual entry is invisible to a pump-hardware anchor."""
        user, email, password = await _create_user(db_session, "iob_ns_manual")
        now = datetime.now(UTC)

        anchor = PumpEvent(
            user_id=user.id,
            event_type=PumpEventType.BG_READING,
            event_timestamp=now - timedelta(minutes=30),
            units=None,
            iob_at_event=2.0,
            received_at=now,
            source="tandem",
        )
        careportal_dose = PumpEvent(
            user_id=user.id,
            event_type=PumpEventType.BOLUS,
            event_timestamp=now - timedelta(hours=1),
            units=2.0,
            iob_at_event=None,
            received_at=now,
            source="nightscout:11111111-1111-1111-1111-111111111111",
            ns_id=_unique_ns_id("ns-careportal"),
            metadata_json={"source_uploader": "unknown", "bolus_subtype": "normal"},
        )
        db_session.add_all([anchor, careportal_dose])
        await db_session.commit()

        response = await _fetch_projection(email, password)
        assert response.status_code == 200
        data = response.json()

        # anchor: 2.0 * 0.984375 = 1.96875; manual: 2.0 * 0.9375 = 1.875
        assert data["projected_iob"] == pytest.approx(3.84, rel=0.05)

    async def test_ns_manual_dose_with_nightscout_anchor_excluded(self, db_session):
        """Conservative rule: against a Nightscout-derived anchor (loop
        devicestatus IoB), NS manual entries keep the anchor cut -- AAPS
        NS-sync can import them into the loop's own IoB, so adding them
        here would risk double-counting."""
        user, email, password = await _create_user(db_session, "iob_ns_anchor")
        now = datetime.now(UTC)
        ns_source = "nightscout:22222222-2222-2222-2222-222222222222"

        ns_anchor = PumpEvent(
            user_id=user.id,
            event_type=PumpEventType.BATTERY,
            event_timestamp=now - timedelta(minutes=30),
            units=None,
            iob_at_event=2.5,
            received_at=now,
            source=ns_source,
            ns_id=_unique_ns_id("ns-devicestatus"),
        )
        careportal_dose = PumpEvent(
            user_id=user.id,
            event_type=PumpEventType.BOLUS,
            event_timestamp=now - timedelta(hours=1),
            units=3.0,
            iob_at_event=None,
            received_at=now,
            source=ns_source,
            ns_id=_unique_ns_id("ns-careportal"),
            metadata_json={"source_uploader": "unknown", "bolus_subtype": "normal"},
        )
        db_session.add_all([ns_anchor, careportal_dose])
        await db_session.commit()

        response = await _fetch_projection(email, password)
        assert response.status_code == 200
        data = response.json()

        # Anchor only: 2.5 * remaining(0.5h) = 2.4609
        assert data["projected_iob"] == pytest.approx(2.46, rel=0.05)

    async def test_ns_loop_bolus_before_pump_anchor_excluded(self, db_session):
        """A loop-uploaded NS bolus records a pump delivery -- it is inside
        the pump's IoB snapshot and must stay behind the anchor cut."""
        user, email, password = await _create_user(db_session, "iob_ns_loop")
        now = datetime.now(UTC)

        anchor = PumpEvent(
            user_id=user.id,
            event_type=PumpEventType.BG_READING,
            event_timestamp=now - timedelta(minutes=30),
            units=None,
            iob_at_event=2.0,
            received_at=now,
            source="tandem",
        )
        loop_bolus = PumpEvent(
            user_id=user.id,
            event_type=PumpEventType.BOLUS,
            event_timestamp=now - timedelta(hours=1),
            units=4.0,
            iob_at_event=None,
            received_at=now,
            source="nightscout:33333333-3333-3333-3333-333333333333",
            ns_id=_unique_ns_id("ns-loop-bolus"),
            metadata_json={"source_uploader": "loop", "bolus_subtype": "normal"},
        )
        db_session.add_all([anchor, loop_bolus])
        await db_session.commit()

        response = await _fetch_projection(email, password)
        assert response.status_code == 200
        data = response.json()

        # Anchor only: 2.0 * remaining(0.5h) = 1.96875
        assert data["projected_iob"] == pytest.approx(1.97, rel=0.05)

    async def test_ns_backfilled_bolus_is_not_the_anchor(self, db_session):
        """An NS bolus whose iob_at_event was backfilled from an older
        devicestatus snapshot must not anchor the projection: its IoB
        value predates its own timestamp. The devicestatus-derived
        BATTERY row anchors instead, and the bolus -- now after that
        anchor -- contributes via the timestamp rule."""
        user, email, password = await _create_user(db_session, "iob_ns_backfill")
        now = datetime.now(UTC)
        ns_source = "nightscout:44444444-4444-4444-4444-444444444444"

        battery_anchor = PumpEvent(
            user_id=user.id,
            event_type=PumpEventType.BATTERY,
            event_timestamp=now - timedelta(minutes=40),
            units=None,
            iob_at_event=1.0,
            received_at=now,
            source=ns_source,
            ns_id=_unique_ns_id("ns-devicestatus"),
        )
        # Newest row with iob_at_event -- but it's a backfilled bolus
        # (translator copied 1.0 from the 40-min-old devicestatus).
        backfilled_bolus = PumpEvent(
            user_id=user.id,
            event_type=PumpEventType.BOLUS,
            event_timestamp=now - timedelta(minutes=30),
            units=2.0,
            iob_at_event=1.0,
            received_at=now,
            source=ns_source,
            ns_id=_unique_ns_id("ns-careportal"),
            metadata_json={"source_uploader": "unknown", "bolus_subtype": "normal"},
        )
        db_session.add_all([battery_anchor, backfilled_bolus])
        await db_session.commit()

        response = await _fetch_projection(email, password)
        assert response.status_code == 200
        data = response.json()

        # Anchor = BATTERY row: 1.0 * remaining(40min) = 0.9722
        # Bolus is AFTER that anchor: 2.0 * remaining(30min) = 1.96875
        # Anchoring on the backfilled bolus instead would yield only
        # 1.0 * remaining(30min) = 0.984 (the bolus cut against itself).
        assert data["confirmed_iob"] == 1.0
        assert data["projected_iob"] == pytest.approx(2.94, rel=0.05)

    async def test_pen_only_user_unaffected(self, db_session):
        """Pen-only users (no anchor) keep the honest is_estimated path."""
        user, email, password = await _create_user(db_session, "iob_pen_only")
        now = datetime.now(UTC)

        pen_dose = PumpEvent(
            user_id=user.id,
            event_type=PumpEventType.BOLUS,
            event_timestamp=now - timedelta(hours=1),
            units=4.0,
            iob_at_event=None,
            received_at=now,
            source="glooko",
            ns_id=_unique_ns_id("glooko-pen-dose"),
            metadata_json={"glooko_stream": "insulins", "device_delivered": True},
        )
        db_session.add(pen_dose)
        await db_session.commit()

        response = await _fetch_projection(email, password)
        assert response.status_code == 200
        data = response.json()

        # Pure dose sum: 4.0 * 0.9375 = 3.75
        assert data["projected_iob"] == pytest.approx(3.75, rel=0.05)
        assert data["is_estimated"] is True
        assert "estimated" in data["stale_warning"].lower()
